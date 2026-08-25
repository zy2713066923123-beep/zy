import getCode  # 自动同步 yyb_go 存活账号
# name:中国移动
# cron:10 8,15 * * *

"""
中国移动小程序动态 code 版

功能：
  1. 四端口本地服务获取微信 code
  2. code 接口自动换取 token（逆向小程序 wechat86-applet/login，全程自动无需种子）
  3. login 返回 sessionId 即 JWT，经 wmhsso 换 wmhToken，打通任务中心 QWHD_SESSION_TOKEN
  4. 每日打卡抽奖 (do/mark)
  5. 任务中心完成/领奖 (taskInfo -> finishTask 带 sign 签名，小程序通道 irgdirect 兜底)
  6. 卡片任务 (getCardTaskList 完成/领奖)
  7. 31 天连续打卡领奖 (mark31/markstatus + taskAward)
  8. 月度信息 / 用户信息 / 签到状态查询
  9. PushPlus 推送
  10. 品赞代理，业务请求优先代理，失败直连兜底

环境变量：
  PLUSPLUS_TOKEN        PushPlus token，可选
  PROXY_API             品赞代理提取 API，可选
  PROXY_TYPE            http / socks5，默认 http
  YD_PROVINCE           省份编码，默认 771
  YD_YX                 小程序通道 yx 投放码，默认 JHT042591F0005

说明：
  无需任何账号种子：本地 code 服务返回微信 code 后，脚本自动调用
  小程序 code 接口 (wx.online-cmcc.cn/wmhnewcenter/wechat86-applet/login)
  换取 sessionId(JWT)，再经 wmhsso -> wmhToken -> qwhdmark 换取任务中心
  QWHD_SESSION_TOKEN 执行任务。encryptData 解密密钥已内置，无需配置。
  仅保留小程序渠道：code 服务每次运行自动刷新 token，打卡 + 5 个任务 +
  31 天/月度信息全自动完成，无需抓包。

依赖：
  pip install requests pycryptodome
  socks5 代理需：
  pip install requests[socks]
"""

import base64
import hashlib
import json
import os
import random
import re
import string
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

import ssl

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 优先使用 curl_cffi（浏览器 TLS 指纹，绕过 SSL 反爬），缺失时回退 requests
try:
    from curl_cffi import requests as _cffi_requests
    HAS_CFFI = True
except Exception:
    _cffi_requests = None
    HAS_CFFI = False

DEFAULT_FINGERPRINT = "chrome"

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
except ImportError:
    AES = None
    pad = None
    unpad = None


APP_NAME = "中国移动小程序"
APPID = "wx43aab19a93a3a6f2"

# ============ 统一取码（WX_ID + getCode，支持牛子/YYB 双协议自动路由）============


# 账号（WX_ID = wxid#备注，多个换行或 & 分隔）
WX_IDS = [s.strip() for s in os.getenv("WX_ID", "").replace("&", "\n").splitlines() if s.strip()]
if not WX_IDS:
    print("❌ 未配置环境变量 WX_ID，请按 wxid/openid#备注 格式配置（多个换行分隔）")

# 兼容旧版 SERVERS 本地 code 服务（已废弃，保留用于报错提示）
SERVERS = [wx.split("#")[0].strip() for wx in WX_IDS] or ["127.0.0.1:8088"]

PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()

PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"
PROXY_FETCH_INTERVAL = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

YD_LRSB_HEADER = os.getenv("YD_LRSB_HEADER", "ZS93dUFVa2kzaEpQSjM0SG55MUFDdz09")
EMERGENCY_PROVINCE = os.getenv("YD_PROVINCE", "771")
YD_YX = os.getenv("YD_YX", "JHT042591F0005")
YD_TOUCH_ID = os.getenv("YD_TOUCH_ID", "26-05-10005-2007-A01")
# irgdirect/mark-task 接口必带的反爬头（抓包/源码同值，如失效可从最新抓包重新提取）
IRG_DIRECT_REFER = os.getenv(
    "YD_DIRECT_REFER",
    "npbmTURDvrcszWXCrKNMrrY2SodICV2jwu5N6+rWG34nuE7mgfSBLxznaVIUZT0y",
)

APPLET_AES_KEY = "1234123412ABCDEF"
APPLET_AES_IV = "ABCDEF1234123412"

APPLET_BASE = "https://wx.online-cmcc.cn"
LOGIN_URL = f"{APPLET_BASE}/wmhnewcenter/wechat86-applet/login"
WMHSSO_URL = f"{APPLET_BASE}/wmhnewcenter/wechat86-applet/wmhsso"
IRG_FINISH_TASK_URL = (
    f"{APPLET_BASE}/wmhnewcenter/wechat86-applet/irgdirect/mark-task/api/task/finishTask"
)

QWHD_MARK_PAGE = "https://wx.10086.cn/qwhdhub/qwhdmark/1021122301"
QWHD_BASE = "https://wx.10086.cn/qwhdhub/api/mark"
QWHD_PAGE_REFERER = "https://wx.10086.cn/qwhdhub/qwhdmark/1021122301?redirectSource=SSO_YQS"
TASK_LIST_URL = f"{QWHD_BASE}/task/taskList"
TASK_INFO_URL = f"{QWHD_BASE}/task/taskInfo"
GET_TASK_AWARD_URL = f"{QWHD_BASE}/task/getTaskAward"
FINISH_TASK_URL = f"{QWHD_BASE}/task/finishTask"
GET_CARD_TASK_LIST_URL = f"{QWHD_BASE}/task/getCardTaskList"
DO_MARK_URL = f"{QWHD_BASE}/do/mark"
MONTH_INFO_URL = f"{QWHD_BASE}/month/monthInfo"
USER_INFO_URL = f"{QWHD_BASE}/user/info"
COMMON_INFO_URL = f"{QWHD_BASE}/info/commonInfo"
MARK31_STATUS_URL = f"{QWHD_BASE}/mark31/markstatus"
MARK31_AWARD_URL = f"{QWHD_BASE}/mark31/taskAward"

APPLET_ASK_CONFIG = (
    "feeCard,callBalance,broadband,noReal,noPuk,fareLink,recommendCard,xmeFloatBar,"
    "showGrayUI,NBEJXHSN,commodityDisableProvince,txCooperateOffingPro,netAge,oneKeyLog"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541923) XWEB/19823"
)

APP_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; 2512BPNDAC Build/UKQ1.230917.001; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/109.0.5414.86 "
    "MQQBrowser/6.2 TBS/047115 Mobile Safari/537.36 leadeon/12.0.2/CMCCIT"
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


def to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def log_title() -> None:
    print()
    print("╔" + "═" * 50 + "╗")
    print("║ 📱 中国移动小程序动态 code 版                  ║")
    print(f"║ 🕒 启动时间: {now_text():<32}║")
    print(f"║ 🔢 账号数量: {len(WX_IDS):<34}║")
    print("╚" + "═" * 50 + "╝")


def log_account_header(index: int, total: int, server: str) -> None:
    print()
    print("┌" + "─" * 50 + "┐")
    print(f"│ 🧩 账号 {index} / {total:<37}│")
    print(f"│ 🌍 来源 {server:<40}│")
    print("└" + "─" * 50 + "┘")


def direct_session():
    """优先返回 curl_cffi Session（带浏览器 TLS 指纹，绕过 SSL 反爬），失败回退 requests"""
    if HAS_CFFI:
        try:
            session = _cffi_requests.Session()
            session.verify = False
            return session
        except Exception:
            pass
    session = requests.Session()
    session.trust_env = False
    # 跳过证书校验，规避证书/套件问题
    session.verify = False
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        session.mount(
            "https://",
            requests.adapters.HTTPAdapter(
                max_retries=requests.adapters.Retry(total=2, backoff_factor=0.5),
                ssl_context=ctx,
            ),
        )
    except Exception:
        pass
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
        kwargs.setdefault("verify", False)
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            print(f"⚠️ [代理] {server} 代理请求失败: {exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            print("🔁 [兜底] 切换直连重试")

    session = direct_session()
    if HAS_CFFI:
        kwargs.setdefault("impersonate", DEFAULT_FINGERPRINT)
    return session.request(method, url, **kwargs)


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


def get_code(wxid: str) -> str | None:
    """通过 getCode 统一接口获取微信 login code（支持牛子/YYB 双协议自动路由）"""
    if get_single_code is None:
        print("❌ [授权] getCode 模块未加载，请确认 getCode.py 与本脚本同目录")
        return None
    print(f"🔐 [授权] 通过 getCode 获取 code: {mask(wxid)}")
    try:
        code = get_single_code(APPID, wxid)
        if not code:
            print("❌ [授权] code 获取失败（返回空）")
            return None
        print("✅ [授权] code 获取成功")
        return code
    except Exception as exc:
        print(f"❌ [授权] code 获取异常: {exc}")
        return None


def applet_aes_decrypt(data: str) -> str:
    """wechat86-applet encryptData 解密：双层 base64 -> AES-CBC(固定 key/iv) -> 明文"""
    if AES is None or unpad is None:
        raise ImportError("未安装 pycryptodome，无法解密 encryptData")

    raw = base64.b64decode(data)
    try:
        inner = base64.b64decode(raw)
        if len(inner) % 16 == 0:
            raw = inner
    except Exception:
        pass

    cipher = AES.new(APPLET_AES_KEY.encode("utf-8"), AES.MODE_CBC, APPLET_AES_IV.encode("utf-8"))
    return unpad(cipher.decrypt(raw), AES.block_size).decode("utf-8")


def applet_headers(jwt: str | None = None) -> Dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "xweb_xhr": "1",
        "X-APPLET-ASK-CONFIG": APPLET_ASK_CONFIG,
        "X-EMERGENCY-PROVINCE": EMERGENCY_PROVINCE,
        "X-EMERGENCY-NEW": "yes",
        "Referer": f"https://servicewechat.com/{APPID}/524/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Lrsbhbg8": YD_LRSB_HEADER,
    }
    if jwt:
        headers["X-WECHAT86-APPLET-JWT"] = jwt
        headers["X-CORE-APPLET-TOKEN"] = jwt
    else:
        headers["X-WECHAT86-APPLET-JWT"] = ""
    return headers


def login_by_code(
    server: str,
    code: str,
    proxies: Dict[str, str] | None,
) -> Tuple[str | None, Dict[str, Any] | None]:
    """使用微信 code 调用小程序 login 接口，返回的 sessionId 即 JWT"""
    try:
        print("🔐 [登录] 使用 code 接口换取 JWT")
        headers = applet_headers()
        headers["X-WX-Code"] = code

        response = request_with_proxy(
            "GET",
            LOGIN_URL,
            headers=headers,
            proxies=proxies,
            server=server,
        )

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text[:800]}

        if str(data.get("rtnCode", "")) not in ("0",):
            print(f"❌ [登录] 接口返回异常: {json_preview(data)}")
            return None, data

        try:
            info = json.loads(applet_aes_decrypt(data.get("encryptData", "")))
        except Exception as exc:
            print(f"❌ [登录] encryptData 解密失败: {exc}")
            return None, data

        jwt = (info.get("data") or {}).get("sessionId")
        if jwt:
            print(f"✅ [登录] JWT 获取成功: {mask(jwt)}")
            return jwt, info

        print(f"❌ [登录] 未获取到 sessionId: {json_preview(info)}")
        return None, info
    except Exception as exc:
        print(f"❌ [登录] 请求异常: {exc}")
        return None, None


def sso_to_qwhd(
    server: str,
    jwt: str,
    proxies: Dict[str, str] | None,
) -> str | None:
    """JWT -> wmhsso 得 wmhToken -> 访问 qwhdmark 页换取 QWHD_SESSION_TOKEN"""
    try:
        print("🔗 [SSO] 正在用 JWT 打通任务中心")
        headers = applet_headers(jwt)
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        response = request_with_proxy(
            "POST",
            f"{WMHSSO_URL}?redirectSource=SSO_YQS",
            headers=headers,
            data={},
            proxies=proxies,
            server=server,
        )

        try:
            data = response.json()
        except Exception:
            data = {}

        wmh_token = ""
        try:
            sso_info = json.loads(applet_aes_decrypt(data.get("encryptData", "")))
            wmh_token = ((sso_info.get("bean") or {}).get("token") or "").strip()
        except Exception as exc:
            print(f"⚠️ [SSO] wmhsso 解密失败: {exc}")

        if not wmh_token:
            print(f"❌ [SSO] 未获取到 wmhToken: {json_preview(data)}")
            return None

        print(f"✅ [SSO] wmhToken 获取成功: {mask(wmh_token)}")

        session = direct_session()
        session.headers.update({"User-Agent": USER_AGENT})
        session.get(
            QWHD_MARK_PAGE,
            params={
                "wmhToken": wmh_token,
                "ys": "",
                "yx": YD_YX,
                "touch_id": YD_TOUCH_ID,
            },
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT,
        )

        token = session.cookies.get("QWHD_SESSION_TOKEN")
        if token:
            print(f"✅ [SSO] QWHD_SESSION_TOKEN 获取成功: {mask(token)}")
            return token

        print("❌ [SSO] 未能获取 QWHD_SESSION_TOKEN")
        return None
    except Exception as exc:
        print(f"❌ [SSO] 异常: {exc}")
        return None


def qwhd_headers(token: str, app_channel: bool = False) -> Dict[str, str]:
    """qwhd 任务中心请求头（小程序渠道微信 UA）"""
    return {
        "User-Agent": APP_USER_AGENT if app_channel else USER_AGENT,
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "*/*",
        "Origin": "https://wx.10086.cn",
        "Referer": QWHD_PAGE_REFERER,
        "x-requested-with": "XMLHttpRequest",
        "login-check": "1",
        "Cookie": f"QWHD_SESSION_TOKEN={token}",
    }


def qwhd_api_post(
    server: str,
    url: str,
    token: str,
    proxies: Dict[str, str] | None,
    payload: Dict[str, Any] | None = None,
    app_channel: bool = False,
) -> Dict[str, Any]:
    response = request_with_proxy(
        "POST",
        url,
        headers=qwhd_headers(token, app_channel),
        json=payload if payload is not None else {},
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


def build_task_sign(task_id: str) -> Tuple[str, str]:
    """app 通道 finishTask 签名：random=32位随机串+13位毫秒时间戳，sign=md5(taskId|random)"""
    prefix = "".join(random.choices(string.ascii_lowercase + string.digits, k=32))
    random_str = prefix + str(int(time.time() * 1000))
    sign = hashlib.md5(f"{task_id}|{random_str}".encode("utf-8")).hexdigest()
    return sign, random_str


def task_fetch_info(
    server: str,
    token: str,
    proxies: Dict[str, str] | None,
    task_id: str,
    fallback_type: str,
    app_channel: bool = False,
) -> Tuple[str, str, int, str]:
    """taskInfo 返回权威 taskType/taskToken/scanTime/cToken，失败回退列表 taskType"""
    try:
        resp = qwhd_api_post(server, TASK_INFO_URL, token, proxies, {"taskId": task_id}, app_channel)
        if resp.get("code") == "SUCCESS":
            data = resp.get("data") or {}
            try:
                scan_time = int(str(data.get("scanTime") or "0"))
            except (TypeError, ValueError):
                scan_time = 0
            return (
                str(data.get("taskType") or fallback_type),
                str(data.get("taskToken") or ""),
                scan_time,
                str(data.get("cToken") or ""),
            )
    except Exception:
        pass
    return fallback_type, "", 0, ""


def qwhd_finish_task(
    server: str,
    token: str,
    proxies: Dict[str, str] | None,
    task_id: str,
    task_type: str,
    app_channel: bool = False,
) -> Tuple[bool, str]:
    """app 通道 finishTask，需带 sign + random"""
    try:
        sign, random_str = build_task_sign(task_id)
        resp = qwhd_api_post(
            server,
            FINISH_TASK_URL,
            token,
            proxies,
            {
                "taskId": task_id,
                "taskType": task_type,
                "sign": sign,
                "random": random_str,
            },
            app_channel,
        )
        if resp.get("code") == "SUCCESS":
            return True, "成功"
        msg = resp.get("msg") or str(resp.get("code"))
        print(f"⚠️ [qwhd] finishTask 失败 (taskId={task_id}, taskType={task_type}): {msg}")
        return False, msg
    except Exception as exc:
        return False, str(exc)


def irg_finish_task(
    server: str,
    jwt: str,
    proxies: Dict[str, str] | None,
    task_id: str,
    task_type: str,
) -> Tuple[bool, str]:
    """小程序通道 finishTask：wxmini 专属字段，响应 encryptData"""
    try:
        headers = applet_headers(jwt)
        headers["Content-Type"] = "application/json;charset=UTF-8"
        headers["X-DIRECT-REFER"] = IRG_DIRECT_REFER
        headers["X-TRANSFER-REFER"] = "PHONE"
        payload = {
            "taskId": task_id,
            "taskType": task_type,
            "touch_id": "",
            "ys": "",
            "ystitle": "",
            "yx": YD_YX,
            "prov": EMERGENCY_PROVINCE,
            "phone": "#{telephone}",
            "channel": "wxmini",
        }
        response = request_with_proxy(
            "POST",
            IRG_FINISH_TASK_URL,
            headers=headers,
            json=payload,
            proxies=proxies,
            server=server,
        )
        status = response.status_code
        body = (response.text or "").strip()
        if not body:
            print(f"⚠️ [irg] HTTP {status} 空响应 (taskId={task_id}, taskType={task_type})")
            return False, f"接口返回空(HTTP {status})"
        try:
            data = json.loads(body)
        except Exception:
            print(f"⚠️ [irg] HTTP {status} 非JSON: {body[:120]}")
            return False, f"接口非JSON(HTTP {status}): {body[:80]}"
        try:
            inner = json.loads(applet_aes_decrypt(data.get("encryptData", "")))
        except Exception:
            return False, data.get("rtnMsg") or "encryptData 解密失败"
        if str(inner.get("code")) == "SUCCESS":
            return True, "成功"
        return False, inner.get("msg") or str(inner.get("code"))
    except Exception as exc:
        return False, str(exc)


def task_browse_jump(
    server: str,
    token: str,
    proxies: Dict[str, str] | None,
    jump_url: str,
    task_token: str = "",
    scan_time: int = 0,
    app_channel: bool = False,
) -> bool:
    """浏览类任务：GET 访问跳转页(带 taskToken)并等待 scanTime 秒再回来结算"""
    if not jump_url or not str(jump_url).startswith("http"):
        return False
    url = str(jump_url)
    if task_token:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}taskToken={quote(task_token)}&jtToken={quote(task_token)}"
    try:
        print(f"🌐 [浏览] {url[:120]}")
        response = request_with_proxy(
            "GET",
            url,
            headers={
                "User-Agent": APP_USER_AGENT if app_channel else USER_AGENT,
                "Cookie": f"QWHD_SESSION_TOKEN={token}",
                "Referer": QWHD_PAGE_REFERER,
            },
            proxies=proxies,
            server=server,
        )
        final_url = getattr(response, "url", "") or url
        print(f"🌐 [浏览] -> HTTP {response.status_code}, 落地 {final_url[:100]}")
        if scan_time > 0:
            sleep(min(scan_time, 8))
        return response.status_code < 500
    except Exception as exc:
        print(f"⚠️ [浏览] 请求异常: {exc}")
        return False


def finish_one_task(
    server: str,
    token: str,
    proxies: Dict[str, str] | None,
    task_id: str,
    task_type: str,
    jump_url: str,
    jwt: str | None,
    task_token: str = "",
    scan_time: int = 0,
    app_channel: bool = False,
) -> Tuple[bool, str]:
    """完成单个任务：浏览类先 GET 跳转页(带taskToken)，再 app sign / 小程序 irgdirect 结算"""
    if task_token:
        task_browse_jump(server, token, proxies, jump_url, task_token, scan_time, app_channel)

    ok, msg = qwhd_finish_task(server, token, proxies, task_id, task_type, app_channel)
    if ok:
        return True, msg

    if jwt:
        ok, msg = irg_finish_task(server, jwt, proxies, task_id, task_type)
        if ok:
            return True, msg

    if not task_token and task_browse_jump(server, token, proxies, jump_url, "", 0, app_channel):
        ok, msg = qwhd_finish_task(server, token, proxies, task_id, task_type, app_channel)
        if ok:
            return True, msg
        if jwt:
            ok, msg = irg_finish_task(server, jwt, proxies, task_id, task_type)
            if ok:
                return True, msg

    return False, msg


def run_task_award(
    server: str,
    token: str,
    proxies: Dict[str, str] | None,
    task_id: str,
    task_name: str,
    app_channel: bool = False,
) -> Tuple[bool, str]:
    """领取任务奖励，幂等"""
    try:
        award_resp = qwhd_api_post(server, GET_TASK_AWARD_URL, token, proxies, {"taskId": task_id}, app_channel)
        if award_resp.get("code") == "SUCCESS":
            award_num = (award_resp.get("data") or {}).get("awardNum", "")
            return True, f"{task_name}x{award_num}"
        return False, award_resp.get("msg") or str(award_resp.get("code"))
    except Exception as exc:
        return False, str(exc)


def process_task_list(
    server: str,
    token: str,
    proxies: Dict[str, str] | None,
    tasks: List[Dict[str, Any]],
    jwt: str | None,
    app_channel: bool = False,
) -> Tuple[int, int, List[str]]:
    """逐个处理任务：status==0 完成并领奖，status 1/2 幂等补领奖"""
    finished = 0
    awarded = 0
    prize_names: List[str] = []

    for task in tasks:
        if not isinstance(task, dict):
            continue

        task_id = str(task.get("taskId") or "")
        task_name = task.get("taskName") or task_id
        status = str(task.get("status"))
        if not task_id or status not in ("0", "1", "2", ""):
            continue

        sleep(random.randint(1, 3))

        try:
            if status == "0":
                if jwt is None and not str(task.get("jumpUrl") or "").startswith("http"):
                    print(f"ℹ️ [任务] {task_name} 外部跳转任务(非网页)，无法接口自动完成，跳过")
                    continue
                task_type, task_token, scan_time, _c_token = task_fetch_info(
                    server, token, proxies, task_id, str(task.get("taskType") or ""), app_channel
                )
                if not str(task.get("jumpUrl") or "").startswith("http"):
                    print(f"ℹ️ [任务] {task_name} 为外部跳转任务(非网页)，继续尝试接口结算")
                ok, msg = finish_one_task(
                    server,
                    token,
                    proxies,
                    task_id,
                    task_type,
                    task.get("jumpUrl") or "",
                    jwt,
                    task_token,
                    scan_time,
                    app_channel,
                )
                if ok:
                    finished += 1
                    print(f"✅ [任务] 完成 {task_name}")
                else:
                    print(f"⚠️ [任务] {task_name} 未完成: {msg}")

            award_ok, award_msg = run_task_award(server, token, proxies, task_id, task_name, app_channel)
            if award_ok:
                awarded += 1
                prize_names.append(award_msg)
                print(f"🎁 [领奖] {award_msg}")
            elif status == "0":
                print(f"⚠️ [领奖] {task_name}: {award_msg}")
        except Exception as exc:
            print(f"⚠️ [任务] {task_name} 异常: {exc}")

    return finished, awarded, prize_names


def task_user_info(server: str, token: str, proxies: Dict[str, str] | None, app_channel: bool = False) -> str:
    resp = qwhd_api_post(server, USER_INFO_URL, token, proxies, {"appVersion": "", "miniVersion": ""}, app_channel)
    data = resp.get("data") or {}
    nick = data.get("nickName") or ""
    mobile = data.get("mobile") or ""
    province = data.get("provinceCode") or ""
    if nick or mobile:
        return f"{nick} {mobile} 省份{province}".strip()
    return json_preview(resp, 120)


def task_do_mark(server: str, token: str, proxies: Dict[str, str] | None, app_channel: bool = False) -> str:
    resp = qwhd_api_post(server, DO_MARK_URL, token, proxies, {}, app_channel)
    if resp.get("code") == "SUCCESS":
        data = resp.get("data") or {}
        prize = data.get("prizeName") or "打卡成功"
        print(f"✅ [打卡] {prize}")
        return f"每日打卡: {prize}"
    msg = resp.get("msg") or json_preview(resp, 200)
    print(f"⚠️ [打卡] {msg}")
    return f"每日打卡: {msg}"


def task_center(
    server: str,
    token: str,
    proxies: Dict[str, str] | None,
    jwt: str | None = None,
    app_channel: bool = False,
) -> str:
    resp = qwhd_api_post(server, TASK_LIST_URL, token, proxies, {}, app_channel)
    if resp.get("code") != "SUCCESS":
        return f"任务列表: {resp.get('msg') or '获取失败'}"

    data = resp.get("data") or {}
    tasks = data.get("tasks") or []
    current_fee = data.get("currentFee", "")
    print(f"📋 [任务] 共 {len(tasks)} 个任务，当前话费 {current_fee}")

    finished, awarded, prize_names = process_task_list(server, token, proxies, tasks, jwt, app_channel)

    if awarded:
        return f"完成{finished}/领奖{awarded}: {'、'.join(prize_names[:6])}"
    return f"任务{len(tasks)}个，完成{finished}，无可领奖励"


def task_card_center(
    server: str,
    token: str,
    proxies: Dict[str, str] | None,
    jwt: str | None = None,
    app_channel: bool = False,
) -> str:
    resp = qwhd_api_post(server, GET_CARD_TASK_LIST_URL, token, proxies, {}, app_channel)
    if resp.get("code") != "SUCCESS":
        return ""

    tasks = (resp.get("data") or {}).get("tasks") or []
    if not tasks:
        return ""
    print(f"🃏 [卡片任务] 共 {len(tasks)} 个")

    finished, awarded, prize_names = process_task_list(server, token, proxies, tasks, jwt, app_channel)

    if awarded:
        return f"卡片任务完成{finished}/领奖{awarded}: {'、'.join(prize_names[:4])}"
    return f"卡片任务{len(tasks)}个，完成{finished}"


def task_mark31(server: str, token: str, proxies: Dict[str, str] | None, app_channel: bool = False) -> str:
    resp = qwhd_api_post(server, MARK31_STATUS_URL, token, proxies, {}, app_channel)
    if resp.get("code") != "SUCCESS":
        return f"31天打卡: {resp.get('msg') or '查询失败'}"

    items = (resp.get("data") or {}).get("accumulateTaskInfo") or []
    print(f"📅 [31天] 累计任务 {len(items)} 个")
    claimed: List[str] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("id") or "")
        days = item.get("num") or ""
        if not task_id or str(item.get("status")) != "1":
            continue

        sleep(random.randint(1, 3))
        try:
            award = qwhd_api_post(server, f"{MARK31_AWARD_URL}/{task_id}", token, proxies, {}, app_channel)
            if award.get("code") == "SUCCESS":
                prize = (award.get("data") or {}).get("prizeName") or "未知奖品"
                claimed.append(f"{days}天{prize}")
                print(f"🎁 [31天] {days}天奖励: {prize}")
            else:
                print(f"⚠️ [31天] {days}天不可领: {award.get('msg') or award.get('code')}")
        except Exception:
            pass

    if claimed:
        return f"31天打卡领奖: {'、'.join(claimed)}"
    return "31天打卡: 今日无可领奖励"


def task_month_info(server: str, token: str, proxies: Dict[str, str] | None, app_channel: bool = False) -> str:
    resp = qwhd_api_post(server, MONTH_INFO_URL, token, proxies, {}, app_channel)
    if resp.get("code") == "SUCCESS":
        data = resp.get("data")
        if isinstance(data, dict) and data:
            return f"月度: {json_preview(data, 120)}"
        return "月度: 已查询"
    return f"月度: {resp.get('msg') or '查询失败'}"


def run_account(index: int, total: int, wxid: str, remark: str = "") -> Dict[str, Any]:
    # server 参数保持兼容：内部以 wxid 作为标识标签
    server = wxid
    result = {
        "server": f"{remark} {wxid}".strip() if remark else wxid,
        "success": False,
        "proxyStatus": "未使用代理",
        "proxyIp": "-",
        "token": "-",
        "account": "-",
        "markMsg": "-",
        "taskMsg": "-",
        "mark31Msg": "-",
        "monthMsg": "-",
        "error": "",
    }

    log_account_header(index, total, wxid)

    proxies, proxy_ip = get_valid_proxy(server)
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"

    sleep(PROXY_FETCH_INTERVAL)

    delay = random.randint(2, 6)
    print(f"⏳ [延迟] 启动延迟 {delay}s")
    sleep(delay)

    jwt = None
    qwhd_token = ""
    wxmini_ok = False

    code = get_code(wxid)
    if code:
        jwt, _info = login_by_code(server, code, proxies)
        if jwt:
            qwhd_token = sso_to_qwhd(server, jwt, proxies)
            if qwhd_token:
                wxmini_ok = True
                result["token"] = mask(jwt)

    if not qwhd_token:
        result["error"] = "code 换 token 失败（请检查 WX_ID 配置与 getCode 服务）"
        return result

    result["token"] = mask(qwhd_token)

    try:
        result["account"] = task_user_info(server, qwhd_token, proxies)
        print(f"👤 [账号] {result['account']}")

        sleep(random.randint(1, 3))
        result["markMsg"] = task_do_mark(server, qwhd_token, proxies)

        sleep(random.randint(1, 3))
        result["taskMsg"] = task_center(server, qwhd_token, proxies, jwt)

        sleep(random.randint(1, 3))
        card_msg = task_card_center(server, qwhd_token, proxies, jwt)
        if card_msg:
            result["taskMsg"] = f"{result['taskMsg']} | {card_msg}"

        sleep(random.randint(1, 3))
        result["mark31Msg"] = task_mark31(server, qwhd_token, proxies)
        if wxmini_ok and "0 个" in result["mark31Msg"]:
            print("ℹ️ [31天] wxmini 渠道今日无可领奖励")

        sleep(random.randint(1, 2))
        result["monthMsg"] = task_month_info(server, qwhd_token, proxies)

        result["success"] = True
        return result

    except Exception as exc:
        result["error"] = traceback.format_exc().strip()
        print(f"❌ [账号] 执行失败: {exc}")
        return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count

    content = f"""📱 中国移动四账号任务结果

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
👤 账号：{res["account"]}
📝 打卡：{res["markMsg"]}
🎁 任务：{res["taskMsg"]}
📅 31天：{res["mark31Msg"]}
📅 月度：{res["monthMsg"]}
{icon} 结果：{"成功" if res["success"] else "失败"}
"""

        if not res["success"]:
            content += f"❌ 原因：{res['error']}\n"

        content += "━━━━━━━━━━━━━━━━━━━━\n"

    return content


def main() -> None:
    log_title()

    if not WX_IDS:
        print("❌ 未配置环境变量 WX_ID，无法执行任务")
        return

    accounts = []
    for line in WX_IDS:
        idx = line.rfind("#")
        if idx > 0:
            accounts.append((line[:idx].strip(), line[idx + 1:].strip()))
        else:
            accounts.append((line, ""))

    results: List[Dict[str, Any]] = []

    for index, (wxid, remark) in enumerate(accounts, 1):
        try:
            result = run_account(index, len(accounts), wxid, remark)
            results.append(result)
        except Exception as exc:
            print(f"❌ [主程序] {wxid} 执行异常: {exc}")
            results.append({
                "server": f"{remark} {wxid}".strip() if remark else wxid,
                "success": False,
                "proxyStatus": "-",
                "proxyIp": "-",
                "token": "-",
                "account": "-",
                "markMsg": "-",
                "taskMsg": "-",
                "mark31Msg": "-",
                "monthMsg": "-",
                "error": traceback.format_exc().strip(),
            })

        if index < len(accounts):
            print("⏳ [间隔] 等待 2s 后处理下一个账号")
            sleep(2)

    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count

    print()
    print("╔" + "═" * 50 + "╗")
    print("║ 🏁 中国移动任务执行完成                        ║")
    print(f"║ ✅ 成功: {success_count:<39}║")
    print(f"║ ❌ 失败: {fail_count:<39}║")
    print(f"║ 🕒 结束时间: {now_text():<32}║")
    print("╚" + "═" * 50 + "╝")

    send_pushplus("📱 中国移动四账号任务完成", build_notify(results))


if __name__ == "__main__":
    main()