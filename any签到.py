#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cron: 0 8 * * *
new Env("Router 签到")

linux.do Cookie 登录 → OAuth 登录 router.top → 签到 → notify 推送
依赖: curl_cffi (pip install curl_cffi), nodejs (青龙面板自带)

环境变量 ：
LINUXDO_COOKIES 中，每个账号的 Cookie 用换行或 & 分隔：
     例：_t=xxx1; _forum_session=yyy1
        _t=xxx2; _forum_session=yyy2
        _t=xxx3; _forum_session=yyy3

  HTTPS_PROXY       - 代理地址（可选，中国大陆必填）
                      例: http://user:pass@host:port

获取 Cookie 方法:
  1. 浏览器登录 https://linux.do
  2. F12 → Application → Cookies → linux.do
  3. 复制 _t 和 _forum_session 的值
  4. 设置环境变量 LINUXDO_COOKIES="_t=xxx; _forum_session=yyy"
"""

import os
import re
import sys
import json
import time
import random
import subprocess
import tempfile
import functools
from urllib.parse import urljoin, urlparse, parse_qs

try:
    from curl_cffi import requests
except ImportError:
    print("缺少依赖 curl_cffi，请运行: pip install curl_cffi")
    sys.exit(1)

# ============ 常量 ============
DOMAIN = "any" + "router.top"  # 拼接避免拼写遗漏
BASE = "https://" + DOMAIN
LINUXDO_BASE = "https://linux.do"
CONNECT_BASE = "https://connect.linux.do"
LINUXDO_CLIENT_ID = "8w2uZtoWH9AUXrZr1qeCEEmvXLafea3c"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36")
SAFARI_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/15.5 Safari/605.1.15")

# ACW v2 求解器 Node.js 脚本（从 stdin 读挑战 HTML，stdout 输出 acw_sc__v2）
ACW_SOLVER_JS = r"""
const fs = require("fs");
const vm = require("vm");

let input = "";
process.stdin.setEncoding("utf-8");
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
    try {
        const jsMatch = input.match(/<script>([\s\S]*?)<\/script>/);
        if (!jsMatch) { process.stderr.write("no js\n"); process.exit(1); }
        const arg1Match = input.match(/var arg1='([A-F0-9]+)'/);
        if (!arg1Match) { process.stderr.write("no arg1\n"); process.exit(1); }
        const challengeJs = jsMatch[1];
        let capturedCookie = "";
        const sandbox = {
            arg1: arg1Match[1],
            document: { location: { reload: () => {} } },
            Date: Date, parseInt: parseInt, String: String,
            RegExp: RegExp, Math: Math, Boolean: Boolean,
            decodeURIComponent: decodeURIComponent,
            encodeURIComponent: encodeURIComponent,
            console: { log: () => {}, error: () => {}, warn: () => {} },
        };
        Object.defineProperty(sandbox.document, "cookie", {
            set: function(v) { capturedCookie = v; },
            get: function() { return capturedCookie; },
            configurable: true,
        });
        try {
            vm.runInContext(challengeJs, vm.createContext(sandbox), { timeout: 5000 });
        } catch (e) {
            process.stderr.write("exec err: " + e.message + "\n");
        }
        const m = capturedCookie.match(/acw_sc__v2=([^;]+)/);
        if (m) {
            process.stdout.write(m[1]);
        } else {
            process.stderr.write("no cookie captured\n");
            process.exit(2);
        }
    } catch (e) {
        process.stderr.write("err: " + e.message + "\n");
        process.exit(3);
    }
});
"""


# ============ 工具函数 ============
def get_proxies():
    """从环境变量获取代理配置，自动处理用户名/密码中的特殊字符"""
    proxy = (os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
             or os.environ.get("ALL_PROXY") or os.environ.get("https_proxy"))
    if proxy:
        if proxy.startswith("socks5h://"):
            proxy = "socks5://" + proxy[len("socks5h://"):]
        # 自动处理 userinfo 中的特殊字符（如密码含 @ 等）
        # 格式: scheme://user:pass@host:port，用最后一个 @ 分割 userinfo 和 host
        if "://" in proxy and "@" in proxy:
            scheme, rest = proxy.split("://", 1)
            at_idx = rest.rfind("@")
            if at_idx > 0 and ":" in rest[:at_idx]:
                userinfo = rest[:at_idx]
                hostpart = rest[at_idx+1:]
                if ":" in userinfo:
                    user, pwd = userinfo.split(":", 1)
                else:
                    user, pwd = userinfo, ""
                from urllib.parse import quote
                user = quote(user, safe="")
                pwd = quote(pwd, safe="")
                if pwd:
                    proxy = f"{scheme}://{user}:{pwd}@{hostpart}"
                else:
                    proxy = f"{scheme}://{user}@{hostpart}"
        return {"http": proxy, "https": proxy}
    return None


def retry(retries=3, min_delay=3, max_delay=8):
    """重试装饰器"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == retries - 1:
                        raise
                    delay = random.uniform(min_delay, max_delay)
                    print(f"  第 {attempt+1}/{retries} 次失败: {e}，{delay:.1f}s 后重试")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


def parse_cookie_string(cookie_str):
    """解析 Cookie 字符串为字典"""
    cookies = {}
    for part in cookie_str.strip().split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            cookies[name.strip()] = value.strip()
    return cookies


# ============ ACW v2 求解器 ============
class ACWSolver:
    """阿里云 ACW v2 反爬虫求解器（通过 Node.js 执行挑战 JS）"""

    _solver_path = None

    @classmethod
    def _get_solver_script(cls):
        """获取求解器脚本路径（写入临时文件）"""
        if cls._solver_path and os.path.exists(cls._solver_path):
            return cls._solver_path
        fd, path = tempfile.mkstemp(suffix=".js", prefix="acw_solver_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(ACW_SOLVER_JS)
        cls._solver_path = path
        return path

    @classmethod
    def solve(cls, challenge_html):
        """从挑战 HTML 计算 acw_sc__v2 cookie 值"""
        if "var arg1" not in challenge_html:
            return None
        try:
            script = cls._get_solver_script()
            result = subprocess.run(
                ["node", script],
                input=challenge_html,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                value = result.stdout.strip()
                if value and re.match(r"^[0-9a-f]{40}$", value):
                    return value
            return None
        except Exception as e:
            print(f"  ACW 求解异常: {e}")
            return None


# ============ HTTP 客户端 ============
class HttpClient:
    """带 ACW v2 自动绕过的 HTTP 客户端，手动管理 Cookie（按域名）"""

    # 按域名使用不同的浏览器指纹（connect.linux.do 需要 safari15_5 绕过 CF）
    DOMAIN_FINGERPRINTS = {
        "connect.linux.do": "safari15_5",
    }
    DEFAULT_FINGERPRINT = "firefox135"

    def __init__(self, proxies=None):
        self.session = requests.Session()
        if proxies:
            self.session.proxies = proxies
        self.session.headers.update({
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        # 按域名存储 cookie 字符串: {domain: "name1=val1; name2=val2"}
        self._domain_cookies = {}

    def set_cookies_from_string(self, cookie_str, domain):
        """为指定域名设置 cookies"""
        existing = self._domain_cookies.get(domain, "")
        if existing:
            self._domain_cookies[domain] = existing + "; " + cookie_str
        else:
            self._domain_cookies[domain] = cookie_str

    def _get_cookie_header(self, url):
        """根据 URL 域名获取对应的 Cookie header"""
        hostname = urlparse(url).hostname or ""
        # 收集匹配的 cookie 字符串
        parts = []
        # 精确匹配域名
        if hostname in self._domain_cookies:
            parts.append(self._domain_cookies[hostname])
        # 检查父域名（如 .linux.do 匹配 connect.linux.do）
        for d, c in self._domain_cookies.items():
            if d.startswith(".") and hostname.endswith(d[1:]):
                parts.append(c)
        return "; ".join(parts) if parts else None

    def _update_cookies_from_response(self, url, r):
        """从响应的 Set-Cookie 更新域名 cookie 存储"""
        hostname = urlparse(url).hostname or ""
        # curl_cffi 的 r.cookies 会自动解析 Set-Cookie
        for name, value in r.cookies.items():
            existing = self._domain_cookies.get(hostname, "")
            # 移除同名的旧 cookie，添加新的
            parts = [p.strip() for p in existing.split(";") if p.strip()]
            parts = [p for p in parts if not p.startswith(name + "=")]
            parts.append(f"{name}={value}")
            self._domain_cookies[hostname] = "; ".join(parts)

    def _get_fingerprint(self, url):
        """根据 URL 域名获取浏览器指纹"""
        hostname = urlparse(url).hostname or ""
        return self.DOMAIN_FINGERPRINTS.get(hostname, self.DEFAULT_FINGERPRINT)

    def request(self, method, url, **kwargs):
        """请求并自动处理 ACW v2 挑战和 Cookie"""
        # 按域名选择浏览器指纹
        fingerprint = self._get_fingerprint(url)
        kwargs.setdefault("impersonate", fingerprint)
        kwargs.setdefault("timeout", 30)
        kwargs.setdefault("allow_redirects", False)

        # 设置 Cookie header
        cookie = self._get_cookie_header(url)
        headers = kwargs.pop("headers", {}) or {}
        if cookie:
            headers["Cookie"] = cookie
        # 使用 safari 指纹时，覆盖 User-Agent 为 Safari UA
        if fingerprint == "safari15_5":
            headers["User-Agent"] = SAFARI_UA
        kwargs["headers"] = headers

        # 调试：打印 Cookie header
        if os.environ.get("DEBUG_COOKIE"):
            print(f"    [DEBUG] {method} {url[:80]} fp={fingerprint} Cookie: {headers.get('Cookie', 'NONE')[:80]}")

        try:
            r = self.session.request(method, url, **kwargs)
        except Exception as e:
            # 如果非默认指纹失败，回退到默认指纹
            if fingerprint != self.DEFAULT_FINGERPRINT:
                print(f"    [指纹 {fingerprint} 失败: {e}，回退到 {self.DEFAULT_FINGERPRINT}]")
                kwargs["impersonate"] = self.DEFAULT_FINGERPRINT
                if "User-Agent" in headers and headers["User-Agent"] == SAFARI_UA:
                    headers["User-Agent"] = UA
                r = self.session.request(method, url, **kwargs)
            else:
                raise

        # 更新 cookies
        self._update_cookies_from_response(url, r)

        # 检测 ACW v2 挑战
        if r.status_code == 200 and "var arg1" in r.text:
            acw_sc_v2 = ACWSolver.solve(r.text)
            if acw_sc_v2:
                hostname = urlparse(url).hostname or ""
                # 添加 acw_sc__v2 cookie
                self.set_cookies_from_string(f"acw_sc__v2={acw_sc_v2}", hostname)
                # 重新请求
                cookie = self._get_cookie_header(url)
                headers = kwargs.get("headers", {}) or {}
                headers["Cookie"] = cookie
                kwargs["headers"] = headers
                r = self.session.request(method, url, **kwargs)
                self._update_cookies_from_response(url, r)

        return r

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


# ============ linux.do 登录验证 ============
class LinuxDoLogin:
    """linux.do Cookie 登录验证"""

    def __init__(self, client):
        self.client = client

    def login_with_cookies(self, cookie_str):
        """用 Cookie 登录 linux.do，返回 (成功, 消息)"""
        if not cookie_str or not cookie_str.strip():
            return False, "未设置 LINUXDO_COOKIES 环境变量"

        # 检查必需的 cookie
        cookies = parse_cookie_string(cookie_str)
        if "_t" not in cookies:
            return False, "Cookie 中缺少 _t，请确保从浏览器复制完整的 Cookie"

        # 用 .linux.do 父域，确保 linux.do 和 connect.linux.do 都能匹配
        self.client.set_cookies_from_string(cookie_str, ".linux.do")

        return True, "Cookie 已设置（将在 OAuth 授权时验证）"


# ============ router.top OAuth 登录 + 签到 ============
class RouterCheckin:
    """router.top OAuth 登录和签到"""

    def __init__(self, client):
        self.client = client
        self.user_id = None

    @retry()
    def get_oauth_state(self):
        """获取 OAuth state"""
        r = self.client.get(BASE + "/api/oauth/state")
        if r.status_code == 200:
            return r.json().get("data")
        raise Exception(f"获取 state 失败: HTTP {r.status_code}")

    def oauth_authorize(self, state):
        """OAuth 授权，跟踪重定向链获取 code"""
        auth_url = (f"{CONNECT_BASE}/oauth2/authorize?response_type=code"
                    f"&client_id={LINUXDO_CLIENT_ID}&state={state}")

        # 完整浏览器 header（/session/sso_provider 需要 Sec-Fetch-* 等头）
        browser_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Ch-Ua": '"Chromium";v="142", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
        }

        current_url = auth_url
        rate_limit_count = 0
        for i in range(15):
            headers = dict(browser_headers)
            if i > 0:
                headers["Referer"] = current_url
            r = self.client.get(current_url, headers=headers)

            # 429 限流，等待重试（最多 12 次，使用指数退避）
            if r.status_code == 429:
                rate_limit_count += 1
                if rate_limit_count > 12:
                    print(f"    [429 限流次数过多，放弃]")
                    break
                # 优先用 Retry-After，否则用指数退避（5, 10, 15, 20, 30, 40...）
                try:
                    wait = int(r.headers.get("Retry-After", "0"))
                except ValueError:
                    wait = 0
                if wait <= 0:
                    wait = min(5 * rate_limit_count, 60)
                print(f"    [{i+1}] 429 限流（第 {rate_limit_count} 次），等待 {wait}s 后重试")
                time.sleep(wait)
                continue

            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location", "")
                if loc.startswith("http"):
                    current_url = loc
                else:
                    current_url = urljoin(current_url, loc)

                # 检查是否回到 router.top 且带 code
                if DOMAIN in current_url and "code=" in current_url:
                    params = parse_qs(urlparse(current_url).query)
                    code = params.get("code", [None])[0]
                    returned_state = params.get("state", [None])[0]
                    return code, returned_state
            elif r.status_code == 200:
                # 检查是否为授权确认页面，查找 approve 链接
                approve_match = re.search(r'href="(/oauth2/approve/[^"]+)"', r.text)
                if approve_match:
                    approve_url = urljoin(current_url, approve_match.group(1))
                    r = self.client.get(approve_url, headers={"Referer": current_url})
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get("Location", "")
                        if loc.startswith("http"):
                            current_url = loc
                        else:
                            current_url = urljoin(current_url, loc)
                        if DOMAIN in current_url and "code=" in current_url:
                            params = parse_qs(urlparse(current_url).query)
                            code = params.get("code", [None])[0]
                            returned_state = params.get("state", [None])[0]
                            return code, returned_state
                    continue

                if "linux.do/login" in current_url:
                    print("    [Cookie 无效，被重定向到登录页]")
                break
            else:
                if r.status_code == 403:
                    if "Just a moment" in r.text or "cf-chl" in r.text:
                        print(f"    [CF 拦截: {current_url[:80]}]")
                    else:
                        print(f"    [403 错误: {r.text[:200]}]")
                break

        return None, None

    def oauth_login(self, code, state):
        """用 code 和 state 完成 OAuth 登录（code 一次性，不重试）"""
        r = self.client.get(
            BASE + "/api/oauth/linuxdo",
            params={"code": code, "state": state},
            headers={"New-API-User": "-1"},
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("success") and data.get("data"):
                self.user_id = data["data"].get("id")
            return data.get("success", False), data
        return False, {"message": f"HTTP {r.status_code}: {r.text[:200]}"}

    def get_user_info(self):
        """获取用户信息"""
        headers = {}
        if self.user_id:
            headers["New-API-User"] = str(self.user_id)
        r = self.client.get(BASE + "/api/user/self", headers=headers)
        if r.status_code == 200:
            return r.json()
        return None

    def checkin(self):
        """签到（每日登录即签到）"""
        user_info = self.get_user_info()
        if not user_info or not user_info.get("success"):
            return False, "获取用户信息失败（未登录）"

        data = user_info.get("data", {})
        username = data.get("username", "未知")
        quota = data.get("quota", 0)
        used = data.get("used_quota", 0)
        # 额度单位转换（通常为 500000 = $1）
        quota_str = f"${quota/500000:.2f}" if quota > 1000 else str(quota)
        used_str = f"${used/500000:.2f}" if used > 1000 else str(used)

        return True, f"用户: {username} | 额度: {quota_str} | 已用: {used_str}"


# ============ 消息推送 ============
try:
    from notify import send as notify_send
except ImportError:
    def notify_send(title, content):
        print(f"--- 通知 ---\n{title}\n{content}\n-------------")


def notify(title, content):
    try:
        notify_send(title, content)
        return True
    except Exception as e:
        print(f"  推送异常: {e}")
        return False


# ============ 主函数 ============
def parse_accounts():
    """解析多账号环境变量 LINUXDO_COOKIES。
    分隔规则：换行或 & 分隔（注意：Cookie 中不含 &，故可安全用作分隔符）。
    返回: List[str] cookie 字符串列表
    """
    raw = os.environ.get("LINUXDO_COOKIES", "")
    return [item.strip() for item in re.split(r'[\n&]+', raw) if item.strip()]


def run_account(cookie_str, index, total, proxies):
    """单账号执行：Cookie 登录 -> OAuth -> 签到，返回 (成功, 消息列表)"""
    tag = f"【账号 {index+1}/{total}】"
    print(f"\n{tag} 开始 ===")

    # 每个账号用独立的 HttpClient，避免 cookie 互相污染
    client = HttpClient(proxies)
    messages = []

    # 1. Cookie 登录 linux.do
    print("=== 1. Cookie 登录 linux.do ===")
    linuxdo = LinuxDoLogin(client)
    success, msg = linuxdo.login_with_cookies(cookie_str)
    print(msg)
    messages.append(f"{tag} [linux.do] {msg}")

    if not success:
        return False, messages

    # 2. OAuth 登录 router.top
    print("\n=== 2. OAuth 登录 router.top ===")
    router = RouterCheckin(client)

    try:
        state = router.get_oauth_state()
        print(f"  state = {state}")
    except Exception as e:
        messages.append(f"{tag} [router.top] 获取 state 失败: {e}")
        return False, messages

    print("  进行 OAuth 授权...")
    code, returned_state = router.oauth_authorize(state)
    if not code:
        messages.append(f"{tag} [router.top] OAuth 授权失败，未获取到 code（Cookie 可能过期）")
        return False, messages
    print(f"  code = {code[:20]}...")

    success, data = router.oauth_login(code, state)
    if not success:
        messages.append(f"{tag} [router.top] OAuth 登录失败: {data}")
        return False, messages
    messages.append(f"{tag} [router.top] OAuth 登录成功")

    # 3. 获取用户信息（签到）
    print("\n=== 3. 签到 ===")
    success, msg = router.checkin()
    messages.append(f"{tag} [签到] {msg}")
    print(msg)

    return True, messages


def main():
    accounts = parse_accounts()
    if not accounts:
        msg = ("未设置环境变量 LINUXDO_COOKIES\n"
               "请从浏览器复制 linux.do 的 Cookie（需包含 _t 和 _forum_session）\n"
               "多账号可用换行或 & 分隔")
        print(msg)
        notify("Router 签到失败", msg)
        return

    print(f"共 {len(accounts)} 个账号待执行")
    proxies = get_proxies()

    all_messages = []
    success_count = 0
    fail_count = 0

    for i, cookie_str in enumerate(accounts):
        try:
            success, msgs = run_account(cookie_str, i, len(accounts), proxies)
            all_messages.extend(msgs)
            if success:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            fail_count += 1
            err_msg = f"【账号 {i+1}/{len(accounts)}】 执行异常: {e}"
            print(err_msg)
            all_messages.append(err_msg)

        # 账号间间隔 30s，避免触发 linux.do 的 429 限流
        if i < len(accounts) - 1:
            print("\n等待 30s 后处理下一个账号...")
            time.sleep(30)

    # 汇总推送
    summary = (f"Router 签到完成\n"
               f"成功：{success_count}  失败：{fail_count}\n\n"
               + "\n".join(all_messages))
    print("\n=== 推送通知 ===")
    title = "Router 签到完成" if fail_count == 0 else f"Router 签到（成功 {success_count} / 失败 {fail_count}）"
    notify(title, summary)


if __name__ == "__main__":
    main()
