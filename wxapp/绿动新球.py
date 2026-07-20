# name: 绿动新球
# cron: 29 10,13 * * *
# -*- coding: utf-8 -*-
 
"""
绿动新球小程序签到 code 版
 
功能：
  1. 通过 getCode 公共模块获取微信 code
  2. 使用 code 换取 token
  3. 每日签到
  4. notify 通知推送
  5. 品赞代理，业务请求优先代理，失败直连兜底
 
环境变量：
  WX_ID             账号配置，格式：identifier#alias，多账号换行或 & 分隔
  PROXY_API         品赞代理提取 API，可选
  PROXY_TYPE        http / socks5，默认 http
  LVDONG_TOKEN      绿动token（可选，支持直接使用token模式）
 
依赖：
  pip install requests
  socks5 代理需：
  pip install requests[socks]
"""
 
import json
import os
import random
import time
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, List, Tuple
from urllib.parse import quote
 
import requests

import getCode

try:
    from notify import send as notify_send
except ImportError:
    def notify_send(title, content):
        print(f"--- 通知 ---\n{title}\n{content}\n-------------")
 
# 禁用SSL警告
import warnings
from urllib3.exceptions import InsecureRequestWarning
warnings.simplefilter('ignore', InsecureRequestWarning)
 
 
APP_NAME = "绿动新球小程序签到"
APPID = "wxa61a45f180dec800"
 
ACCOUNTS = []
_wx_id_raw = os.getenv("WX_ID", "")
if _wx_id_raw:
    for line in _wx_id_raw.replace("&", "\n").splitlines():
        line = line.strip()
        if not line:
            continue
        if "#" in line:
            identifier, alias = line.split("#", 1)
            ACCOUNTS.append((identifier.strip(), alias.strip()))
        else:
            ACCOUNTS.append((line, line))

if not ACCOUNTS:
    print("❌ 未配置环境变量 WX_ID")
    exit(1)

print(f"✅ 成功读取 {len(ACCOUNTS)} 个账号")
 
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()
LVDONG_TOKEN = os.getenv("LVDONG_TOKEN", "")
 
PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"
PROXY_FETCH_INTERVAL = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30
 
API_HOST = "lvdong.fzjingzhou.com"
LOGIN_URL = f"https://{API_HOST}/api/login/getWxMiniProgramSessionKey"
SIGN_URL = f"https://{API_HOST}/api/Person/sign"
USER_INFO_URL = f"https://{API_HOST}/api/Person/index"
 
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541923) XWEB/19823"
)
 
 
def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
 
 
def sleep(seconds: float) -> None:
    time.sleep(seconds)
 
 
def mask(value: Any) -> str:
    value = str(value or "")
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-6:]}"
 
 
def json_preview(data: Any, limit: int = 800) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)[:limit]
    except Exception:
        return str(data)[:limit]
 
 
def log_title() -> None:
    print()
    print("╔" + "═" * 50 + "╗")
    print("║ 🌿 绿动新球小程序签到 code 版                   ║")
    print(f"║ 🕒 启动时间: {now_text():<32}║")
    print(f"║ 🔢 账号数量: {len(ACCOUNTS):<34}║")
    print("╚" + "═" * 50 + "╝")
 
 
def log_account_header(index: int, total: int, alias: str) -> None:
    print()
    print("┌" + "─" * 50 + "┐")
    print(f"│ 🧩 账号 {index} / {total:<37}│")
    print(f"│ 🌍 来源 {alias:<40}│")
    print("└" + "─" * 50 + "┘")
 
 
def direct_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session
 
 
def parse_proxy_response(text: Any) -> Dict[str, Any] | None:
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
 
    text = text.strip()
    if not text:
        return None
 
    try:
        data = json.loads(text)
        proxy_obj = None
 
        if isinstance(data.get("data"), list) and data["data"]:
            proxy_obj = data["data"][0]
        elif isinstance(data.get("data"), dict):
            proxy_obj = data["data"]
        elif data.get("ip") and data.get("port"):
            proxy_obj = data
        elif isinstance(data.get("result"), dict):
            proxy_obj = data["result"]
 
        if proxy_obj:
            host = proxy_obj.get("ip") or proxy_obj.get("host")
            port = proxy_obj.get("port")
            if host and port:
                return {
                    "host": str(host),
                    "port": int(port),
                    "username": proxy_obj.get("user") or proxy_obj.get("username") or "",
                    "password": proxy_obj.get("pass") or proxy_obj.get("password") or "",
                }
    except Exception:
        pass
 
    if ":" in text:
        parts = text.split(":")
        if len(parts) >= 2:
            return {
                "host": parts[0],
                "port": int(parts[1]),
                "username": parts[2] if len(parts) > 2 else "",
                "password": parts[3] if len(parts) > 3 else "",
            }
 
    return None
 
 
def build_proxy_dict(proxy_info: Dict[str, Any] | None) -> Dict[str, str] | None:
    if not proxy_info:
        return None
 
    host = proxy_info["host"]
    port = proxy_info["port"]
    username = proxy_info.get("username", "")
    password = proxy_info.get("password", "")
 
    auth = ""
    if username and password:
        auth = f"{quote(username)}:{quote(password)}@"
 
    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = f"{scheme}://{auth}{host}:{port}"
 
    print(f"🛠️ [代理] 生成 {scheme.upper()} 代理 {host}:{port}")
 
    return {
        "http": proxy_url,
        "https": proxy_url,
    }
 
 
def validate_proxy(proxies: Dict[str, str] | None) -> Tuple[bool, str]:
    if not proxies:
        return False, ""
 
    try:
        response = requests.get(PROXY_VALIDATE_URL, proxies=proxies, timeout=15)
        if response.status_code == 200:
            try:
                ip = response.json().get("origin", "未知")
            except Exception:
                ip = "未知"
            print(f"✅ [代理] 验证通过，出口 IP: {ip}")
            return True, ip
    except Exception as exc:
        print(f"⚠️ [代理] 验证失败: {exc}")
 
    return False, ""
 
 
def get_valid_proxy(account_name: str) -> Tuple[Dict[str, str] | None, str]:
    if not PROXY_API:
        print(f"⚠️ [代理] {account_name} 未配置 PROXY_API，使用直连")
        return None, ""
 
    print(f"🌐 [代理] {account_name} 正在获取品赞代理...")
 
    for index in range(1, PROXY_RETRY_TIMES + 1):
        try:
            response = direct_session().get(PROXY_API, timeout=15)
            proxy_info = parse_proxy_response(response.text)
 
            if not proxy_info:
                print(f"⚠️ [代理] 第 {index} 次代理解析失败")
                continue
 
            print(f"✅ [代理] 提取到 {proxy_info['host']}:{proxy_info['port']}")
            proxies = build_proxy_dict(proxy_info)
 
            ok, ip = validate_proxy(proxies)
            if ok:
                return proxies, ip
 
            print(f"⚠️ [代理] 第 {index} 次代理不可用")
        except Exception as exc:
            print(f"⚠️ [代理] 第 {index} 次获取代理异常: {exc}")
 
        if index < PROXY_RETRY_TIMES:
            sleep(2)
 
    print("⚠️ [代理] 获取失败，使用直连")
    return None, ""
 
 
def request_with_proxy(
    method: str,
    url: str,
    *,
    proxies: Dict[str, str] | None = None,
    server: str = "",
    **kwargs,
) -> requests.Response:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    kwargs.setdefault("verify", False)
 
    if proxies:
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            print(f"⚠️ [代理] {server} 代理请求失败: {exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            print("🔁 [兜底] 切换直连重试")
 
    session = direct_session()
    return session.request(method, url, **kwargs)
 
 
def get_wx_code(identifier):
    try:
        return getCode.get_single_code(APPID, identifier)
    except Exception as e:
        print(f"获取code失败: {e}")
        return None

 
def common_headers() -> Dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
        "Platform": "MP-WEIXIN",
        "Accept": "*/*",
        "xweb_xhr": "1",
        "Referer": f"https://servicewechat.com/{APPID}/4/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    "Accept-Encoding": "gzip, deflate, br",
    }


def _parse_response(response):
    """解析响应，兼容接口将 data 字段甚至整体以 JSON 字符串返回（双重编码）的情况"""
    try:
        data = response.json()
    except Exception:
        return {"code": -1, "msg": f"JSON解析失败: {response.text[:300]}"}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return {"code": -1, "msg": f"JSON解析失败: {response.text[:300]}"}
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, str):
            try:
                data["data"] = json.loads(inner)
            except Exception:
                pass
    return data


def login_by_code(alias: str, code: str, proxies: Dict[str, str] | None) -> Tuple[str | None, Dict[str, Any] | None]:
    try:
        print("🔐 [登录] 使用 code 换取 token")
        post_data = {
            "code": code,
            "gdtVid": "",
            "token": ""
        }
 
        response = request_with_proxy(
            "POST",
            LOGIN_URL,
            headers=common_headers(),
            data=post_data,
            proxies=proxies,
            server=alias,
        )
 
        data = _parse_response(response)

        if data.get("code") == 1000 and data.get("data", {}).get("token"):
            token = data["data"]["token"]
            print(f"✅ [登录] token 获取成功: {mask(token)}")
            return token, data
 
        print(f"❌ [登录] 未识别 token 字段: {json_preview(data)}")
        return None, data
    except Exception as exc:
        print(f"❌ [登录] 请求异常: {exc}")
        return None, None
 
 
def get_user_info(alias: str, token: str, proxies: Dict[str, str] | None) -> Dict[str, Any]:
    response = request_with_proxy(
        "POST",
        USER_INFO_URL,
        headers=common_headers(),
        data={"token": token},
        proxies=proxies,
        server=alias,
    )
    return _parse_response(response)
 
 
def daily_sign(alias: str, token: str, proxies: Dict[str, str] | None) -> Tuple[bool, str]:
    try:
        print("📝 [签到] 执行签到操作")
        response = request_with_proxy(
            "POST",
            SIGN_URL,
            headers=common_headers(),
            data={"token": token},
            proxies=proxies,
            server=alias,
        )
 
        try:
            data = response.json()
        except Exception:
            return False, f"响应解析错误: {response.text[:300]}"
 
        code_status = data.get("code")
        msg = data.get("msg", "未知错误")
 
        if code_status == 1000:
            if "签到" in msg and "成功" in msg:
                msg = f"签到成功！{msg}"
                print(f"✅ [签到] {msg}")
                return True, msg
            elif "已签到" in msg or "今天已签到" in msg:
                print(f"⚠️ [签到] {msg}")
                return True, msg
            else:
                print(f"✅ [签到] {msg}")
                return True, msg
        elif code_status == 1001:
            print(f"⚠️ [签到] {msg}")
            return True, msg
        else:
            print(f"❌ [签到] {msg} (code:{code_status})")
            return False, msg
    except Exception as exc:
        msg = f"请求异常: {exc}"
        print(f"❌ [签到] {msg}")
        return False, msg
 
 
def run_account(index: int, total: int, identifier: str, alias: str) -> Dict[str, Any]:
    result = {
        "alias": alias,
        "success": False,
        "proxyStatus": "未使用代理",
        "proxyIp": "-",
        "token": "-",
        "nickname": "-",
        "score": "-",
        "signMsg": "-",
        "error": "",
    }
 
    log_account_header(index, total, alias)
 
    proxies, proxy_ip = get_valid_proxy(alias)
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"
 
    sleep(PROXY_FETCH_INTERVAL)
 
    delay = random.randint(2, 6)
    print(f"⏳ [延迟] 启动延迟 {delay}s")
    sleep(delay)
 
    token = None
 
    if LVDONG_TOKEN:
        print("🔐 [登录] 使用环境变量中的 LVDONG_TOKEN")
        token = LVDONG_TOKEN
    else:
        code = get_wx_code(identifier)
        if not code:
            result["error"] = "获取 code 失败"
            return result
 
        token, raw_login = login_by_code(alias, code, proxies)
        if not token:
            result["error"] = f"登录失败: {json_preview(raw_login)}"
            return result
 
    result["token"] = mask(token)
 
    user_info = get_user_info(alias, token, proxies)
    if user_info.get("code") == 1000:
        result["nickname"] = user_info.get("data", {}).get("nickname", "-")
        result["score"] = user_info.get("data", {}).get("score", 0)
        print(f"👤 [用户] 昵称: {result['nickname']}, 积分: {result['score']}")
 
    sign_success, sign_msg = daily_sign(alias, token, proxies)
    result["signMsg"] = sign_msg
    result["success"] = sign_success
 
    return result
 
 
def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count
 
    content = f"""🌿 绿动新球多账号签到结果
 
━━━━━━━━━━━━━━━━━━━━
🏁 总结：{success_count} 成功 / {fail_count} 失败
🕒 时间：{now_text()}
━━━━━━━━━━━━━━━━━━━━
"""
 
    for idx, res in enumerate(results, 1):
        icon = "✅" if res["success"] else "❌"
 
        content += f"""
🧩 账号 {idx}
🌍 来源：{res["alias"]}
🌐 代理：{res["proxyStatus"]}
📡 出口IP：{res["proxyIp"]}
👤 昵称：{res["nickname"]}
🔐 Token：{res["token"]}
📝 签到：{res["signMsg"]}
💰 积分：{res["score"]}
{icon} 结果：{"成功" if res["success"] else "失败"}
"""
 
        if not res["success"]:
            content += f"❌ 原因：{res['error']}\n"
 
        content += "━━━━━━━━━━━━━━━━━━━━\n"
 
    return content
 
 
def main() -> None:
    log_title()
 
    results: List[Dict[str, Any]] = []
 
    for index, (identifier, alias) in enumerate(ACCOUNTS, 1):
        try:
            result = run_account(index, len(ACCOUNTS), identifier, alias)
            results.append(result)
        except Exception as exc:
            print(f"❌ [主程序] {alias} 执行异常: {exc}")
            results.append({
                "alias": alias,
                "success": False,
                "proxyStatus": "-",
                "proxyIp": "-",
                "token": "-",
                "nickname": "-",
                "score": "-",
                "signMsg": "-",
                "error": traceback.format_exc().strip(),
            })
 
        if index < len(ACCOUNTS):
            print("⏳ [间隔] 等待 2s 后处理下一个账号")
            sleep(2)
 
    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count
 
    print()
    print("╔" + "═" * 50 + "╗")
    print("║ 🏁 绿动新球任务执行完成                        ║")
    print(f"║ ✅ 成功: {success_count:<39}║")
    print(f"║ ❌ 失败: {fail_count:<39}║")
    print(f"║ 🕒 结束时间: {now_text():<32}║")
    print("╚" + "═" * 50 + "╝")
 
    notify_send("🌿 绿动新球多账号签到完成", build_notify(results))
 
 
if __name__ == "__main__":
    main()
