#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 小象超市
# cron: 5 8,18 * * *

"""
小象超市小程序签到动态 code 版

功能：
  1. yyb_go 自动获取存活账号并换取微信 code
  2. /user/v1/weapplogin 使用 code 换美团 token / openid
  3. 每日签到并查询买菜币余额
  4. PushPlus 推送
  5. 品赞代理，业务请求优先代理，失败直连兜底

环境变量：
  PLUSPLUS_TOKEN    PushPlus token，可选
  PROXY_API         品赞代理提取 API，可选
  PROXY_TYPE        http / socks5，默认 http
  WX_SERVER         yyb_go 服务地址，默认 http://127.0.0.1:18273
  WX_ID             可选，账号白名单（openid/wxid/备注，& 或换行分隔），不填自动使用全部存活账号

依赖：
  pip install requests
  socks5 代理需：
  pip install requests[socks]
"""

import json
import os
import random
import sys
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Tuple
from urllib.parse import quote, urlencode

import requests

# 将脚本所在目录加入搜索路径（确保能找到 yyb.py 等同目录模块）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yyb  # 自动同步 yyb_go 存活账号（与其他脚本一致）


APP_NAME = "小象超市小程序"
APPID = "wx92916b3adca84096"
MT_APP_NAME = "maicai"

# ====================== YYB 账号（自动从 yyb_go 同步存活账号） ======================
ACCOUNT_NAMES: Dict[str, str] = {}


def load_accounts() -> List[str]:
    """从 yyb_go 拉取存活账号，返回账号标识列表（可用 WX_ID 指定白名单）"""
    try:
        accounts = yyb.load_accounts()
    except Exception as exc:
        print(f"❌ 拉取 yyb_go 账号失败：{exc}")
        return []
    refs: List[str] = []
    for account in accounts or []:
        ref = str(account.get("id") or account.get("openid") or account.get("wxid") or "").strip()
        if not ref:
            continue
        ACCOUNT_NAMES[ref] = str(account.get("remark") or account.get("nickname") or account.get("alias") or ref)
        refs.append(ref)
    if refs:
        print(f"✅ 已从 yyb_go 同步 {len(refs)} 个存活账号")
    return refs


SERVERS = load_accounts()
ACCOUNT_REFS = list(SERVERS)

PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()

PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"
PROXY_FETCH_INTERVAL = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

LOGIN_URL = "https://open.meituan.com/user/v1/weapplogin"
CHECK_STATUS_URL = "https://mall.meituan.com/api/c/mallcoin/checkIn/getCheckInMainView"
SIGN_IN_URL = "https://mall.meituan.com/api/c/mallcoin/checkIn/userCheckInNew"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541c37) XWEB/25364 miniProgram/wx92916b3adca84096"
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


def safe_data(resp: Dict[str, Any]) -> Dict[str, Any]:
    return resp.get("data") or {}


def log_title() -> None:
    print()
    print("╔" + "═" * 50 + "╗")
    print("║ 🛒 小象超市动态 code 版                   ║")
    print(f"║ 🕒 启动时间: {now_text():<32}║")
    print(f"║ 🔢 账号数量: {len(SERVERS):<34}║")
    print("╚" + "═" * 50 + "╝")


def log_account_header(index: int, total: int, server: str) -> None:
    print()
    print("┌" + "─" * 50 + "┐")
    print(f"│ 🧩 账号 {index} / {total:<37}│")
    print(f"│ 🌍 来源 {ACCOUNT_NAMES.get(server, server):<40}│")
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


def send_notify(title: str, content: str) -> None:
    """通过青龙 notify.py 推送（task环境自动加载 config.sh -> webhook -> OpenClaw 微信）"""
    try:
        import sys as _sys
        notify_paths = ["/ql/data/scripts", "/ql/scripts", os.path.dirname(os.path.abspath(__file__))]
        for p in notify_paths:
            if p and p not in _sys.path:
                _sys.path.insert(0, p)
        from notify import send
        send(title, content)
        print("✅ [通知] 青龙 notify 推送已提交")
        return
    except Exception as exc:
        print(f"❌ [通知] 青龙 notify 推送失败: {exc}")
    # 兜底 PushPlus
    send_pushplus(title, content)


def send_pushplus(title: str, content: str) -> None:
    if not PLUSPLUS_TOKEN:
        print("⚠️ [PushPlus] 未配置 PLUSPLUS_TOKEN，跳过推送")
        return

    try:
        requests.post(
            "https://www.pushplus.plus/send",
            json={
                "token": PLUSPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "txt",
            },
            timeout=10,
        )
        print("✅ [PushPlus] 推送成功")
    except Exception as exc:
        print(f"❌ [PushPlus] 推送失败: {exc}")


def get_code(server: str, ref: str = "") -> str | None:
    """从 yyb_go 获取一次性微信 code（ref 为账号标识）"""
    target = ref or server
    if not target:
        print("❌ [授权] 未提供账号标识 ref")
        return None
    print(f"🔐 [授权] YYB 获取 code（账号 {ACCOUNT_NAMES.get(target, mask(target))}）")
    try:
        code = yyb.get_single_code(APPID, target)
    except Exception as exc:
        print(f"❌ [授权] code 获取异常: {exc}")
        return None
    if code:
        print("✅ [授权] code 获取成功")
        return str(code)
    print("❌ [授权] code 获取失败")
    return None


def common_headers(token: str | None = None) -> Dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "xweb_xhr": "1",
        "Referer": f"https://servicewechat.com/{APPID}/674/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "ytType": "10",
    }
    if token:
        headers["t"] = token
    return headers


def extract_token(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None

    candidates = [
        data.get("token"),
        data.get("accessToken"),
        data.get("access_token"),
        data.get("jwt"),
    ]

    inner = data.get("data")
    if isinstance(inner, dict):
        candidates.extend([
            inner.get("token"),
            inner.get("accessToken"),
            inner.get("access_token"),
            inner.get("jwt"),
        ])

        user = inner.get("user")
        if isinstance(user, dict):
            candidates.extend([
                user.get("token"),
                user.get("accessToken"),
                user.get("access_token"),
                user.get("jwt"),
            ])

    for item in candidates:
        if item and item != "null":
            return str(item)

    return None


def extract_login_identity(data: Any) -> Tuple[str | None, str | None, str | None]:
    if not isinstance(data, dict):
        return None, None, None

    inner = data.get("data")
    if not isinstance(inner, dict):
        inner = {}

    open_id = data.get("openId") or inner.get("openId")
    open_id_cipher = data.get("openIdCipher") or inner.get("openIdCipher")
    user_id = data.get("userId") or inner.get("userId")

    if open_id:
        open_id = str(open_id)
    if open_id_cipher:
        open_id_cipher = str(open_id_cipher)
    if user_id is not None:
        user_id = str(user_id)

    return open_id, open_id_cipher, user_id


def login_by_code(
    server: str,
    code: str,
    proxies: Dict[str, str] | None,
) -> Tuple[str | None, Dict[str, Any] | None]:
    try:
        print("🔐 [登录] 使用 code 换 token")
        response = request_with_proxy(
            "POST",
            LOGIN_URL,
            headers={**common_headers(), "Content-Type": "application/x-www-form-urlencoded"},
            data={"code": code, "appName": MT_APP_NAME},
            proxies=proxies,
            server=server,
        )

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text[:800]}

        token = extract_token(data)
        if token:
            print(f"✅ [登录] token 获取成功: {mask(token)}")
            return token, data

        print(f"❌ [登录] 未识别 token 字段: {json_preview(data)}")
        return None, data
    except Exception as exc:
        print(f"❌ [登录] 请求异常: {exc}")
        return None, None


def mall_params(openid: str, openid_cipher: str, user_id: str, *, check_status: bool) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "activityScene": "",
        "app_tag": "union",
        "appnm": "xiaoxiangmaicai_wxapp",
        "bizId": "2",
        "ci": "224",
        "client_page_source": "h5",
        "isSSREnv": "false",
        "mc_source": "0akaamabjacw",
        "openId": openid,
        "openIdCipher": openid_cipher,
        "page_type": "h5",
        "poi": "10002122",
        "poiId": "10002122",
        "sceneEffectiveSkus": "",
        "tenantId": "1",
        "uci": "224",
        "userid": user_id,
        "utm_medium": "wxapp",
        "utm_term": "7.26.0",
        "uuid": openid,
        "xuuid": openid,
        "ytType": "10",
        "yodaReady": "h5",
        "csecplatform": "4",
        "csecversion": "4.3.0",
    }
    if check_status:
        params["channel"] = "99"
        params["time"] = str(int(time.time() * 1000))
    return params


def api_get(
    server: str,
    url: str,
    token: str,
    openid: str,
    openid_cipher: str,
    user_id: str,
    proxies: Dict[str, str] | None,
) -> Dict[str, Any]:
    params = mall_params(openid, openid_cipher, user_id, check_status=True)
    full_url = f"{url}?{urlencode(params)}"
    response = request_with_proxy(
        "GET",
        full_url,
        headers=common_headers(token),
        proxies=proxies,
        server=server,
    )
    try:
        return response.json()
    except Exception:
        return {
            "code": -1,
            "msg": f"JSON解析失败: {response.text[:300]}",
        }


def api_post(
    server: str,
    url: str,
    token: str,
    openid: str,
    openid_cipher: str,
    user_id: str,
    proxies: Dict[str, str] | None,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    params = mall_params(openid, openid_cipher, user_id, check_status=False)
    full_url = f"{url}?{urlencode(params)}"
    response = request_with_proxy(
        "POST",
        full_url,
        headers=common_headers(token),
        json=payload,
        proxies=proxies,
        server=server,
    )
    try:
        return response.json()
    except Exception:
        return {
            "code": -1,
            "msg": f"JSON解析失败: {response.text[:300]}",
        }


def run_account(index: int, total: int, server: str, ref: str = "") -> Dict[str, Any]:
    result = {
        "server": server,
        "success": False,
        "proxyStatus": "未使用代理",
        "proxyIp": "-",
        "token": "-",
        "signMsg": "-",
        "balance": "-",
        "error": "",
    }

    log_account_header(index, total, server)

    proxies, proxy_ip = get_valid_proxy(server)
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"

    sleep(PROXY_FETCH_INTERVAL)

    delay = random.randint(2, 6)
    print(f"⏳ [延迟] 启动延迟 {delay}s")
    sleep(delay)

    code = get_code(server, ref)
    if not code:
        result["error"] = "获取 code 失败"
        return result

    token, raw_login = login_by_code(server, code, proxies)
    if not token:
        result["error"] = f"登录失败: {json_preview(raw_login)}"
        return result

    open_id, open_id_cipher, user_id = extract_login_identity(raw_login)
    if not open_id or not open_id_cipher or not user_id:
        result["error"] = f"登录响应缺少身份字段: {json_preview(raw_login)}"
        return result

    result["token"] = mask(token)

    try:
        check_resp = api_get(
            server,
            CHECK_STATUS_URL,
            token,
            open_id,
            open_id_cipher,
            user_id,
            proxies,
        )

        if check_resp.get("code") == 0:
            data = safe_data(check_resp)
            user_info = data.get("userInfo") if isinstance(data, dict) else {}
            if not isinstance(user_info, dict):
                user_info = {}

            balance = user_info.get("balance", "0")
            status = data.get("checkInButtonStatus", "UNKNOWN")
            result["balance"] = balance
            print(f"💰 [余额] {balance} 买菜币  |  签到状态: {status}")

            if status != "CHECKED":
                sign_resp = api_post(
                    server,
                    SIGN_IN_URL,
                    token,
                    open_id,
                    open_id_cipher,
                    user_id,
                    proxies,
                    {
                        "userId": user_id,
                        "riskMap": {
                            "platform": 13,
                            "app": 95,
                            "utm_term": "",
                            "uuid": open_id,
                            "utm_medium": "wxapp",
                            "fingerprint": "",
                        },
                    },
                )

                if sign_resp.get("code") == 0:
                    sign_data = sign_resp.get("data") or {}
                    if not isinstance(sign_data, dict):
                        sign_data = {}
                    reward = sign_data.get("rewardValue", "")
                    signed_result = sign_data.get("result")
                    if reward not in ("", "-1", None):
                        result["signMsg"] = f"签到成功 +{reward} 买菜币"
                    elif signed_result is False:
                        result["signMsg"] = "今日已签到或无需重复签到"
                    else:
                        result["signMsg"] = "签到接口已返回"
                    print(f"✅ [签到] {result['signMsg']}")
                else:
                    result["signMsg"] = (
                        sign_resp.get("msg")
                        or sign_resp.get("message")
                        or "签到失败"
                    )
                    print(f"⚠️ [签到] {result['signMsg']}")
            else:
                result["signMsg"] = "今日已签到"
                print(f"⚠️ [签到] {result['signMsg']}")
        else:
            result["signMsg"] = (
                check_resp.get("msg")
                or check_resp.get("message")
                or "查询失败"
            )
            print(f"⚠️ [签到] {result['signMsg']}")

        result["success"] = True
        return result

    except Exception as exc:
        result["error"] = traceback.format_exc().strip()
        print(f"❌ [账号] 执行失败: {exc}")
        return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count

    content = f"""🛒 小象超市动态 code 版任务结果

━━━━━━━━━━━━━━━━━━━━
🏁 总结：{success_count} 成功 / {fail_count} 失败
🕒 时间：{now_text()}
━━━━━━━━━━━━━━━━━━━━
"""

    for idx, res in enumerate(results, 1):
        icon = "✅" if res["success"] else "❌"

        content += f"""
🧩 账号 {idx}
🌍 来源：{res["server"]}
🌐 代理：{res["proxyStatus"]}
📡 出口IP：{res["proxyIp"]}
🔐 Token：{res["token"]}
📝 签到：{res["signMsg"]}
💰 余额：{res["balance"]} 买菜币
{icon} 结果：{"成功" if res["success"] else "失败"}
"""

        if not res["success"]:
            content += f"❌ 原因：{res['error']}\n"

        content += "━━━━━━━━━━━━━━━━━━━━\n"

    return content


def main() -> None:
    log_title()

    if not SERVERS:
        message = "❌ 未从 yyb_go 获取到存活账号，请确认 WX_SERVER 已配置且服务内有在线账号"
        print(message)
        send_notify("🛒 小象超市签到失败", message)
        return

    results: List[Dict[str, Any]] = []

    for index, server in enumerate(SERVERS, 1):
        ref = ACCOUNT_REFS[index - 1] if index - 1 < len(ACCOUNT_REFS) else ""
        try:
            result = run_account(index, len(SERVERS), server, ref)
            results.append(result)
        except Exception as exc:
            print(f"❌ [主程序] {server} 执行异常: {exc}")
            results.append({
                "server": server,
                "success": False,
                "proxyStatus": "-",
                "proxyIp": "-",
                "token": "-",
                "signMsg": "-",
                "balance": "-",
                "error": traceback.format_exc().strip(),
            })

        if index < len(SERVERS):
            print("⏳ [间隔] 等待 2s 后处理下一个账号")
            sleep(2)

    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count

    print()
    print("╔" + "═" * 50 + "╗")
    print("║ 🏁 小象超市签到任务执行完成                 ║")
    print(f"║ ✅ 成功: {success_count:<39}║")
    print(f"║ ❌ 失败: {fail_count:<39}║")
    print(f"║ 🕒 结束时间: {now_text():<32}║")
    print("╚" + "═" * 50 + "╝")

    send_notify("🛒 小象超市动态 code 版任务完成", build_notify(results))


if __name__ == "__main__":
    main()
