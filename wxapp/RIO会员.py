#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import yyb  # 自动同步 yyb_go 存活账号
# name: RIO会员
# cron: 12 06,18 * * *
"""
RIO会员小程序签到（YYB Go版）

功能：
  1. YYB_SERVER 获取微信 code
  2. code 换 token 登录
  3. 每日签到
  4. 查看任务列表
  5. 青龙 notify 推送

环境变量：
  WX_SERVER      yyb_go 服务地址（例如：http://127.0.0.1:8000）
  PROXY_API     品赞代理提取 API，可选
  PROXY_TYPE    http / socks5，默认 http
"""

import json
import os
import random
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

import requests

try:
    import notify
except ImportError:
    notify = None

APP_NAME = "RIO会员小程序"
APPID = "wx225b10f204323da5"
BASE_URL = "https://club.rioalc.com"
API_BASE = f"{BASE_URL}/api/miniprogram"

# YYB_SERVER 解析
# ============ 统一取码（WX_ID + getCode，支持牛子/YYB 双协议自动路由）============

# ============ 账号来源：优先从 yyb-go 拉取存活账号，WX_ID 仅作兜底 ============
WX_IDS = []
try:
    accs = yyb.load_accounts()
    if accs:
        WX_IDS = [str(acc.get("openid") or acc.get("wxid") or acc.get("id") or "") for acc in accs
                  if (acc.get("openid") or acc.get("wxid") or acc.get("id"))]
        print(f"ℹ️  已从 yyb-go 同步 {len(WX_IDS)} 个存活账号")
except Exception:
    pass

if not WX_IDS:
    WX_IDS = [s.strip() for s in os.getenv("WX_ID", "").replace("&", "\n").splitlines() if s.strip()]
    if WX_IDS:
        print(f"ℹ️  yyb-go 无存活账号，回退使用 WX_ID 配置的 {len(WX_IDS)} 个账号")

WECHAT_SERVER = (os.getenv("WX_SERVER") or os.getenv("WECHAT_SERVER") or "http://127.0.0.1:8000").strip()
YYB_SERVER = (os.getenv("WX_SERVER") or os.getenv("YYB_SERVER") or "http://127.0.0.1:8000").strip()
if WECHAT_SERVER:
    os.environ["WECHAT_SERVER"] = WECHAT_SERVER
if YYB_SERVER:
    os.environ["YYB_SERVER"] = YYB_SERVER

print(f"✅ 读取到 {len(WX_IDS)} 个微信账号，自动路由牛子/YYB 双协议")

PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()
PROXY_RETRY_TIMES = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

AUTH_URL = f"{API_BASE}/auth"
USER_INFO_URL = f"{API_BASE}/user-info"
SIGN_CLICK_URL = f"{API_BASE}/user-sign-click"
TASK_DAY_LIST_URL = f"{API_BASE}/task-day-list"
POST_CREATE_URL = f"{API_BASE}/post-create"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541938) XWEB/19899"
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


def to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def log_title() -> None:
    print()
    print("╔" + "═" * 50 + "╗")
    print("║ 🍷 RIO会员小程序（YYB Go版）                    ║")
    print(f"║ 🕒 启动时间: {now_text():<32}║")
    print(f"║ 🔢 账号数量: {len(WX_IDS):<34}║")
    print("╚" + "═" * 50 + "╝")


def log_account_header(index: int, total: int, server: str) -> None:
    print()
    print("┌" + "─" * 50 + "┐")
    print(f"│ 🧩 账号 {index} / {total:<37}│")
    print(f"│ 🌍 来源 {server:<40}│")
    print("└" + "─" * 50 + "┘")


# ============ YYB Server 交互 ============

_persistent_session = None

def get_persistent_session() -> requests.Session:
    global _persistent_session
    if _persistent_session is None:
        _persistent_session = requests.Session()
        _persistent_session.trust_env = False
    return _persistent_session


def direct_session() -> requests.Session:
    return get_persistent_session()


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
                    "host": str(host), "port": int(port),
                    "username": proxy_obj.get("user") or proxy_obj.get("username") or "",
                    "password": proxy_obj.get("pass") or proxy_obj.get("password") or "",
                }
    except Exception:
        pass
    if ":" in text:
        parts = text.split(":")
        if len(parts) >= 2:
            return {
                "host": parts[0], "port": int(parts[1]),
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
    return {"http": proxy_url, "https": proxy_url}


def get_valid_proxy(account_name: str) -> Tuple[Dict[str, str] | None, str]:
    if not PROXY_API:
        return None, ""
    print(f"🌐 [代理] {account_name} 正在获取品赞代理...")
    for index in range(1, PROXY_RETRY_TIMES + 1):
        try:
            response = direct_session().get(PROXY_API, timeout=8)
            proxy_info = parse_proxy_response(response.text)
            if not proxy_info:
                print(f"⚠️ [代理] 第 {index} 次代理解析失败")
                continue
            print(f"✅ [代理] 提取到 {proxy_info['host']}:{proxy_info['port']}")
            proxies = build_proxy_dict(proxy_info)
            # 简单验证
            try:
                resp = requests.get("http://www.baidu.com", proxies=proxies, timeout=5)
                if resp.status_code == 200:
                    return proxies, proxy_info["host"]
            except Exception:
                pass
            print(f"⚠️ [代理] 第 {index} 次代理不可用")
        except Exception as exc:
            print(f"⚠️ [代理] 第 {index} 次获取代理异常: {exc}")
        if index < PROXY_RETRY_TIMES:
            sleep(1)
    print("⚠️ [代理] 获取失败，使用直连")
    return None, ""


def request_with_proxy(
    method: str, url: str, *,
    proxies: Dict[str, str] | None = None, server: str = "", **kwargs,
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
    try:
        session = direct_session()
        return session.request(method, url, **kwargs)
    except Exception as exc:
        print(f"⚠️ [请求] {server} 直连请求失败: {exc}")
        raise


# ============ 业务接口 ============

def api_headers(authorization: str = "") -> Dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }
    if authorization:
        headers["Authorization"] = authorization
    return headers


def login_with_code(code: str, proxies: Dict[str, str] | None, server: str) -> Tuple[str | None, Dict[str, Any] | None]:
    """使用 code 换 token"""
    print("🔐 [登录] 使用 code 换 token")
    try:
        response = request_with_proxy(
            "POST", AUTH_URL,
            headers=api_headers(),
            json={
                "code": code,
                "redirect_path": "/pages/welcome/loading-page?nocheck=&type_lk=3&path=%2Fpages%2Findex%2Findex",
            },
            proxies=proxies, server=server,
        )
        data = response.json()
        if data.get("code") == 200 and data.get("data"):
            user_info = data["data"]
            api_token = user_info.get("api_token", "")
            authorization = f"Bearer {api_token}"
            print(f"✅ [登录] 登录成功: {user_info.get('nick_name', '')} ({user_info.get('phone', '')}) 积分:{user_info.get('points', 0)}")
            return authorization, user_info
        else:
            print(f"❌ [登录] 登录失败: {data.get('message', data.get('msg', '未知错误'))}")
            return None, data
    except Exception as exc:
        print(f"❌ [登录] 登录请求失败: {exc}")
        return None, None


def get_user_info(authorization: str, proxies: Dict[str, str] | None, server: str) -> Dict[str, Any]:
    print("👤 [用户] 获取用户信息...")
    try:
        response = request_with_proxy(
            "GET", USER_INFO_URL,
            headers=api_headers(authorization),
            proxies=proxies, server=server,
        )
        data = response.json()
        if data.get("code") == 200 and data.get("data"):
            info = data["data"]
            rank_name = ""
            if isinstance(info.get("rank_info"), dict):
                rank_name = info["rank_info"].get("name", "")
            print(f"✅ [用户] {info.get('nick_name', '')} ({info.get('phone', '')}) 积分:{info.get('points', 0)} 等级:{rank_name}")
            return {"success": True, "userInfo": info}
        else:
            print(f"⚠️ [用户] 获取失败: {data.get('message', '')}")
            return {"success": False, "message": data.get("message", "")}
    except Exception as exc:
        print(f"⚠️ [用户] 获取失败: {exc}")
        return {"success": False, "message": str(exc)}


def do_sign(authorization: str, proxies: Dict[str, str] | None, server: str) -> Dict[str, Any]:
    print("📋 [签到] 执行签到...")
    try:
        response = request_with_proxy(
            "POST", SIGN_CLICK_URL,
            headers=api_headers(authorization),
            json={},
            proxies=proxies, server=server,
        )
        data = response.json()
        if data.get("code") == 200:
            print(f"✅ [签到] 签到成功: {data.get('message', '')}")
            return {"success": True, "message": data.get("message", "签到成功")}
        else:
            msg = data.get("message", data.get("msg", "未知错误"))
            print(f"⚠️ [签到] 签到失败: {msg}")
            return {"success": False, "message": msg}
    except Exception as exc:
        print(f"❌ [签到] 签到失败: {exc}")
        return {"success": False, "message": str(exc)}


def get_task_list(authorization: str, proxies: Dict[str, str] | None, server: str) -> Dict[str, Any]:
    print("📋 [任务] 获取每日任务列表...")
    try:
        response = request_with_proxy(
            "GET", TASK_DAY_LIST_URL,
            headers=api_headers(authorization),
            proxies=proxies, server=server,
        )
        data = response.json()
        if data.get("code") == 200 and data.get("data"):
            task_list = data["data"]
            print(f"✅ [任务] 共 {len(task_list)} 个任务")
            for task in task_list:
                status = "✅" if task.get("finished_num", 0) >= task.get("total_num", 1) else "⏳"
                print(f"   {status} {task.get('name', '')}: {task.get('points', 0)}积分 ({task.get('finished_num', 0)}/{task.get('total_num', 0)})")
            return {"success": True, "taskList": task_list}
        else:
            print(f"⚠️ [任务] 获取失败: {data.get('message', '')}")
            return {"success": False, "message": data.get("message", "")}
    except Exception as exc:
        print(f"⚠️ [任务] 获取失败: {exc}")
        return {"success": False, "message": str(exc)}


def create_post(authorization: str, proxies: Dict[str, str] | None, server: str) -> Dict[str, Any]:
    print("📝 [发帖] 执行发帖...")
    try:
        post_data = {
            "topic_id": 151,
            "post_title": "RIO会员每日签到打卡，享受优质生活体验",
            "post_content": "今天完成了RIO会员的每日签到任务，感觉很好！RIO会员的产品质量一直都很不错，包装精美，口感也很好。每天的签到任务让我更有动力坚持使用这个产品，也能积累积分兑换更多好礼。希望RIO会员能推出更多优质的产品和活动。",
            "images": [],
            "sku_id": 15,
        }
        response = request_with_proxy(
            "POST", POST_CREATE_URL,
            headers=api_headers(authorization),
            json=post_data,
            proxies=proxies, server=server,
        )
        data = response.json()
        if data.get("code") == 200:
            print(f"✅ [发帖] 发帖成功: {data.get('message', '')}")
            return {"success": True, "message": data.get("message", "发帖成功")}
        else:
            msg = data.get("message", "发帖失败")
            print(f"⚠️ [发帖] 发帖失败: {msg}")
            return {"success": False, "message": msg}
    except Exception as exc:
        print(f"❌ [发帖] 发帖失败: {exc}")
        return {"success": False, "message": str(exc)}


# ============ 账号执行 ============

def run_account(index: int, total: int, openid: str) -> Dict[str, Any]:
    wxid = openid
    result = {
        "server": openid or openid,
        "wxid": mask(wxid),
        "success": False,
        "proxyStatus": "未使用代理",
        "proxyIp": "-",
        "token": "-",
        "nickname": "-",
        "phone": "-",
        "points": 0,
        "finalPoints": 0,
        "signMsg": "-",
        "taskMsg": "-",
        "postMsg": "-",
        "error": "",
    }

    log_account_header(index, total, openid or openid)

    proxies, proxy_ip = get_valid_proxy(str(openid))
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"

    delay = random.randint(1, 3)
    print(f"⏳ [延迟] 启动延迟 {delay}s")
    sleep(delay)

    code = get_single_code(APPID, openid)
    if not code:
        result["error"] = "获取 code 失败"
        return result

    authorization, login_data = login_with_code(code, proxies, openid)
    if not authorization:
        result["error"] = f"登录失败: {json_preview(login_data)}"
        return result

    result["token"] = "获取成功"
    if login_data and isinstance(login_data, dict):
        result["nickname"] = login_data.get("nick_name", "-")
        result["phone"] = mask(login_data.get("phone", ""))
        result["points"] = to_int(login_data.get("points", 0))

    # 签到
    sign_result = do_sign(authorization, proxies, openid)
    result["signMsg"] = sign_result.get("message", "-")

    # 任务列表
    task_result = get_task_list(authorization, proxies, openid)
    if task_result.get("success"):
        tasks = task_result.get("taskList", [])
        done = sum(1 for t in tasks if t.get("finished_num", 0) >= t.get("total_num", 1))
        result["taskMsg"] = f"{done}/{len(tasks)}已完成"
    else:
        result["taskMsg"] = "获取失败"

    # 发帖
    post_result = create_post(authorization, proxies, openid)
    result["postMsg"] = post_result.get("message", "-")

    # 最终积分
    final_user = get_user_info(authorization, proxies, openid)
    if final_user.get("success"):
        result["finalPoints"] = to_int(final_user["userInfo"].get("points", 0))
        points_change = result["finalPoints"] - result["points"]
        print(f"💰 [积分] {result['points']} → {result['finalPoints']} ({'+' if points_change >= 0 else ''}{points_change})")

    result["success"] = True
    return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    total_points = sum(r.get("finalPoints", 0) for r in results)

    lines = [f"🍷 RIO会员任务结果", "━" * 30]
    lines.append(f"✅ {success_count}成功 / ❌ {fail_count}失败 / 💰 总积分{total_points}")
    lines.append("")

    for idx, res in enumerate(results, 1):
        icon = "✅" if res["success"] else "❌"
        lines.append(f"{icon} 账号{idx} ({res.get('wxid', '-')})")
        lines.append(f"  用户: {res['nickname']} ({res['phone']})")
        lines.append(f"  签到: {res['signMsg']}")
        lines.append(f"  任务: {res['taskMsg']}")
        lines.append(f"  发帖: {res['postMsg']}")
        lines.append(f"  积分: {res['points']} → {res['finalPoints']}")
        if not res["success"]:
            lines.append(f"  错误: {res['error'][:100]}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    log_title()

    results: List[Dict[str, Any]] = []

    for index, openid in enumerate(WX_IDS, 1):
        try:
            result = run_account(index, len(WX_IDS), openid)
            results.append(result)
        except Exception as exc:
            print(f"❌ [主程序] 执行异常: {exc}")
            wxid = openid
            results.append({
                "server": openid, "wxid": mask(wxid),
                "success": False, "error": traceback.format_exc().strip(),
                "token": "-", "nickname": "-", "phone": "-",
                "points": 0, "finalPoints": 0,
                "signMsg": "-", "taskMsg": "-", "postMsg": "-",
                "proxyStatus": "-", "proxyIp": "-",
            })

        if index < len(WX_IDS):
            print("⏳ [间隔] 等待 2s 后处理下一个账号")
            sleep(2)

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    total_points = sum(r.get("finalPoints", 0) for r in results)

    print()
    print("╔" + "═" * 50 + "╗")
    print("║ 🍷 RIO会员任务执行完成                          ║")
    print(f"║ ✅ 成功: {success_count:<39}║")
    print(f"║ ❌ 失败: {fail_count:<39}║")
    print(f"║ 💰 总积分: {total_points:<38}║")
    print(f"║ 🕒 结束时间: {now_text():<32}║")
    print("╚" + "═" * 50 + "╝")

    if notify:
        notify.send(APP_NAME, build_notify(results))


if __name__ == "__main__":
    main()