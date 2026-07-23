# cron: 27 11,15 * * *
# name: 顺丰世界杯活动

"""
顺丰2026世界杯活动 - 射门游戏 + 比赛竞猜 + 每日礼物
Author: 广哥哥整合
Version: 1.1.0
Date: 2026-07-03
WECHAT_SERVER=端口变量
wxsf=账号变量

活动周期: 2026-07-02 ~ 2026-07-20
货币: GOLD_COIN (金币)
活动码: WORLD_CUP

账号加载：优先 sfsyUrl → 否则 wxsf + WECHAT_SERVER + wxsf.json
"""

import hashlib
import json
import os
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# getCode 标准模式（优先），导入失败则回退牛子/YYB（与其他脚本一致）
try:
    from getCode import get_single_code as _gc_get_single_code
    _HAS_GETCODE = True
except Exception:
    _gc_get_single_code = None
    _HAS_GETCODE = False

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

inviteId = ['C6E5C3BDD7624520AB869D2AF9E75D95']

PROXY_TIMEOUT = 15
MAX_PROXY_RETRIES = 5
REQUEST_RETRY_COUNT = 3
CONCURRENT_NUM = int(os.getenv('SFBF', '1'))
if CONCURRENT_NUM > 20:
    CONCURRENT_NUM = 20
elif CONCURRENT_NUM < 1:
    CONCURRENT_NUM = 1

print_lock = Lock()

# ==================== 微信协议 / 缓存（与日常积分脚本一致） ====================
WXSF_ENV_NAME = "wxsf"
WECHAT_SERVER_ENV_NAME = "WECHAT_SERVER"
WXSF_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wxsf.json")

WX_APPID = "wxd4185d00bf7e08ac"
WX_PUBLIC_ID = "gh_f9d9fca26a50"
WX_SIGN_APPID = "wxapp-valid-0328"
WX_SIGN_KEY = "2b08f7f6bf564a1dada1570535fd44ba"
WX_APP_VERSION = "V17.58"

# 牛子 / YYB 协议服务器（与其他脚本一致，用于 getCode 失败时的 code 回退）
YYB_SERVER = (os.environ.get("YYB_SERVER") or os.environ.get("YINGYOGBAO_SERVER") or "").rstrip("/")

WX_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows "
    "WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254186b) XWEB/19481"
)

MCS_BASE = "https://mcs-mimp-web.sf-express.com"
UCMP_BASE = "https://ucmp.sf-express.com"

def _wx_md5(text: str, upper: bool = False) -> str:
    digest = hashlib.md5(str(text).encode()).hexdigest()
    return digest.upper() if upper else digest


def _rand_str(length: int = 32) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(random.choice(chars) for _ in range(length))


def _rand_hex(length: int = 8) -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(length))


def _rand_msgid() -> str:
    return f"WA{_rand_hex(32).upper()}"


def _rand_device_id() -> str:
    return f"{int(time.time() * 1000)}-{random.randint(1000000, 9999999)}-{_rand_hex(13)}-{random.randint(10000000, 99999999)}"


def _mask_mobile(mobile: str) -> str:
    mobile = str(mobile or "")
    if re.fullmatch(r"\d{11}", mobile):
        return f"{mobile[:3]}****{mobile[-4:]}"
    return mobile


def _load_wxsf_cache() -> Dict[str, Any]:
    try:
        if os.path.exists(WXSF_CACHE_FILE):
            with open(WXSF_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception as e:
        print(f"⚠️ 读取 wxsf.json 失败: {e}")
    return {}


def _save_wxsf_cache(cache: Dict[str, Any]) -> None:
    try:
        with open(WXSF_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 保存 wxsf.json 失败: {e}")


def _parse_wxsf_env(raw: str) -> List[Dict[str, str]]:
    accounts = []
    if not raw:
        return accounts
    parts = [x.strip() for x in re.split(r"[@&\n]+", raw) if x.strip()]
    for item in parts:
        if "#" in item:
            wxid, remark = item.split("#", 1)
            wxid = wxid.strip()
            remark = remark.strip() or wxid
        else:
            wxid = item.strip()
            remark = wxid
        if wxid:
            accounts.append({"wxid": wxid, "remark": remark})
    return accounts


def _normalize_wxsf_item(item: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(item or {})
    cookies = item.get("cookies")
    if not isinstance(cookies, dict):
        cookies = {}
    item["cookies"] = cookies

    if item.get("sessionId") and not cookies.get("sessionId"):
        cookies["sessionId"] = item["sessionId"]
    if item.get("sessionId") and not cookies.get("JSESSIONID"):
        cookies["JSESSIONID"] = item["sessionId"]
    if item.get("memId") and not cookies.get("_login_user_id_"):
        cookies["_login_user_id_"] = item["memId"]
    if item.get("mobile") and not cookies.get("_login_mobile_"):
        cookies["_login_mobile_"] = item["mobile"]

    item["sessionId"] = cookies.get("sessionId") or cookies.get("JSESSIONID") or item.get("sessionId") or ""
    item["memId"] = cookies.get("_login_user_id_") or item.get("memId") or ""
    item["mobile"] = cookies.get("_login_mobile_") or item.get("mobile") or ""

    if not item.get("deviceId"):
        item["deviceId"] = _rand_device_id()

    return item


def _cookie_string_from_item(item: Dict[str, Any]) -> str:
    item = _normalize_wxsf_item(item)
    cookies = item.get("cookies", {})
    pairs = []
    for key in ["sessionId", "JSESSIONID", "_login_user_id_", "_login_mobile_"]:
        val = cookies.get(key)
        if val:
            pairs.append(f"{key}={val}")
    return ";".join(pairs)


def _update_wxsf_cookies_from_response(item: Dict[str, Any], response: requests.Response) -> None:
    item = _normalize_wxsf_item(item)
    cookies = item["cookies"]

    for key in ["JSESSIONID", "sessionId", "_login_user_id_", "_login_mobile_"]:
        val = response.cookies.get(key)
        if val:
            cookies[key] = val

    set_cookie = response.headers.get("Set-Cookie", "")
    if set_cookie:
        for key in ["JSESSIONID", "sessionId", "_login_user_id_", "_login_mobile_"]:
            m = re.search(rf"{re.escape(key)}=([^;,\s]+)", set_cookie)
            if m:
                cookies[key] = m.group(1)

    item["sessionId"] = cookies.get("sessionId") or cookies.get("JSESSIONID") or item.get("sessionId") or ""
    if item["sessionId"]:
        cookies.setdefault("sessionId", item["sessionId"])
        cookies.setdefault("JSESSIONID", item["sessionId"])
    item["memId"] = cookies.get("_login_user_id_") or item.get("memId") or ""
    item["mobile"] = cookies.get("_login_mobile_") or item.get("mobile") or ""


def _mcs_if_login(item: Dict[str, Any], timeout: int = 15) -> bool:
    item = _normalize_wxsf_item(item)
    if not item.get("sessionId") or not item.get("memId") or not item.get("mobile"):
        return False

    timestamp = str(int(time.time() * 1000))
    signature = _wx_md5(f"token=wwesldfs29aniversaryvdld29&timestamp={timestamp}&sysCode=MCS-MIMP-CORE")
    referer = (
        f"{MCS_BASE}/up-member/newPoints?mobile={_mask_mobile(item.get('mobile'))}"
        f"&userId={item.get('memId')}&path=/up-member/newPoints&linkCode=SFAC20230803190840424"
        f"&supportShare=YES&subCategoryCode=1&from=mypoint&categoryCode=1"
    )
    headers = {
        "Host": "mcs-mimp-web.sf-express.com",
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "sysCode": "MCS-MIMP-CORE",
        "timestamp": timestamp,
        "signature": signature,
        "platform": "MINI_PROGRAM",
        "channel": "mypoint",
        "User-Agent": WX_UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
        "Cookie": _cookie_string_from_item(item),
    }
    try:
        resp = requests.post(
            f"{MCS_BASE}/mcs-mimp/ifLogin",
            headers=headers,
            json={},
            timeout=timeout,
            verify=False,
        )
        data = resp.json() if resp.text else {}
        _update_wxsf_cookies_from_response(item, resp)
        return bool(data.get("success") and int(data.get("obj", {}).get("loginStatus", -1)) == 1)
    except Exception:
        return False


def _wx_sign_headers(body_obj: Dict[str, Any], suuid: str = "", device_id: str = "") -> Dict[str, str]:
    body_text = json.dumps(body_obj or {}, ensure_ascii=False, separators=(",", ":"))
    nonce = _rand_str(32)
    sign_raw = f"appId={WX_SIGN_APPID}&nonceStr={nonce}&requestBody={body_text}&key={WX_SIGN_KEY}"
    headers = {
        "Host": "ucmp.sf-express.com",
        "Connection": "keep-alive",
        "appId": WX_SIGN_APPID,
        "sign": _wx_md5(sign_raw, upper=True),
        "nonceStr": nonce,
        "wxapp-version": WX_APP_VERSION,
        "xweb_xhr": "1",
        "deviceId": device_id or _rand_device_id(),
        "msgid": _rand_msgid(),
        "grey-mobile-rem": "7",
        "envVersion": "release",
        "User-Agent": WX_UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": f"https://servicewechat.com/{WX_APPID}/684/page-frame.html",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "bno": "",
    }
    if suuid:
        headers["suuid"] = suuid
    return headers


def _get_wx_code(wechat_server: str, wxid: str, appid: str = WX_APPID) -> str:
    """获取微信 login code：优先 getCode 标准模式，失败回退牛子 API（与其他脚本一致）"""
    # 1) getCode.py 标准模式（优先）
    if _HAS_GETCODE:
        try:
            return _gc_get_single_code(appid, wxid)
        except Exception as e:
            print(f"⚠️ getCode获取失败，尝试牛子API: {e}")

    # 2) 牛子 API 回退：WECHAT_SERVER + /api/v1/wx/app/get/code
    if wechat_server:
        try:
            base = wechat_server.rstrip("/") + "/api/v1/wx/"
            data = requests.post(
                base + "app/get/code",
                json={"wxid": wxid, "appid": appid},
                timeout=15,
            ).json()
            if data.get("Code") == 0:
                d = data.get("Data") or data.get("data") or {}
                code = d.get("code") or d.get("Code") if isinstance(d, dict) else str(d)
                if code:
                    return code
                raise Exception(f"牛子API返回code为空: {data}")
            raise Exception(f"牛子API获取code失败: {data}")
        except Exception as e:
            print(f"⚠️ 牛子API获取code失败: {e}")

    # 注：YYB（应用宝）主要提供加密密钥/云函数等高级能力，本脚本登录仅需 code，
    #    故 code 路径走 getCode + 牛子即可；YYB_SERVER 已读取以备后续扩展。
    raise Exception("无法获取微信 login code（getCode 与 牛子 均失败）")


def _refresh_wxsf_item_via_protocol(wxid: str, old_item: Dict[str, Any], wechat_server: str) -> Dict[str, Any]:
    if not wechat_server:
        raise Exception("未配置 WECHAT_SERVER，无法走微信协议刷新")

    item = _normalize_wxsf_item(old_item or {})
    session = requests.Session()
    session.verify = False

    code = _get_wx_code(wechat_server, wxid)

    h1 = _wx_sign_headers({}, suuid="", device_id=item.get("deviceId") or _rand_device_id())
    r1 = session.get(
        f"{UCMP_BASE}/wxaccess/weixin/appOnLogin?code={code}&publicId={WX_PUBLIC_ID}",
        headers=h1,
        timeout=20,
        allow_redirects=False,
    )
    d1 = r1.json() if r1.text else {}
    if not d1.get("sessionId"):
        raise Exception(f"appOnLogin失败: {d1}")
    item["sessionId"] = d1.get("sessionId", "")
    item["openId"] = d1.get("openid", "")
    item["unionId"] = d1.get("unionid", "")
    item["cookies"]["sessionId"] = item["sessionId"]
    item["cookies"]["JSESSIONID"] = item["sessionId"]

    h2 = _wx_sign_headers({}, suuid=item["sessionId"], device_id=item.get("deviceId", ""))
    r2 = session.post(
        f"{UCMP_BASE}/wxopen/weixin/wxMemIsBind",
        headers=h2,
        json={},
        timeout=20,
    )
    d2 = r2.json() if r2.text else {}
    if not d2.get("success") or not (d2.get("obj") or {}).get("memId"):
        raise Exception(f"wxMemIsBind失败: {d2}")
    bind_obj = d2.get("obj") or {}
    item["memId"] = bind_obj.get("memId", "")
    item["mobile"] = bind_obj.get("mobile", "")
    item["memNo"] = bind_obj.get("memNo", "")
    item["cookies"]["_login_user_id_"] = item["memId"]
    item["cookies"]["_login_mobile_"] = item["mobile"]

    biz_code = {
        "path": "/up-member/newPoints",
        "linkCode": "SFAC20230803190840424",
        "supportShare": "YES",
        "subCategoryCode": "1",
        "from": "mypoint",
        "categoryCode": "1",
    }
    sfnew_url = (
        f"{UCMP_BASE}/wechat-act/weixin/activity/sfnewactivity?"
        f"bizCode={requests.utils.quote(json.dumps(biz_code, ensure_ascii=False))}"
        f"&regSource=mypoint&citycode=&cityname=&wxapp-version={WX_APP_VERSION}&suuid={item['sessionId']}"
    )
    r3 = session.get(
        sfnew_url,
        headers={
            "Host": "ucmp.sf-express.com",
            "Connection": "keep-alive",
            "xweb_xhr": "1",
            "wxapp-version": WX_APP_VERSION,
            "User-Agent": f"{WX_UA} miniProgram/{WX_APPID}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Referer": f"https://servicewechat.com/{WX_APPID}/684/page-frame.html",
        },
        timeout=20,
        allow_redirects=False,
    )
    red1 = r3.headers.get("Location", "")
    if not red1:
        raise Exception(f"sfnewactivity未返回跳转地址: status={r3.status_code}")

    r4 = session.get(
        red1,
        headers={
            "User-Agent": WX_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"https://servicewechat.com/{WX_APPID}/684/page-frame.html",
            "Cookie": _cookie_string_from_item(item),
        },
        timeout=20,
        allow_redirects=False,
    )
    _update_wxsf_cookies_from_response(item, r4)
    red2 = r4.headers.get("Location", "")
    if red2:
        if red2.startswith("/"):
            red2 = f"{MCS_BASE}{red2}"
        r5 = session.get(
            red2,
            headers={
                "User-Agent": WX_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": f"https://servicewechat.com/{WX_APPID}/684/page-frame.html",
                "Cookie": _cookie_string_from_item(item),
            },
            timeout=20,
        )
        _update_wxsf_cookies_from_response(item, r5)

    if not _mcs_if_login(item):
        raise Exception("刷新后 ifLogin 校验失败")

    item["updateTime"] = datetime.now().isoformat()
    return _normalize_wxsf_item(item)


def _build_sfsy_from_wxsf(env_name: str) -> List[str]:
    wechat_server = os.getenv(WECHAT_SERVER_ENV_NAME, "").strip()
    wxsf_raw = os.getenv(WXSF_ENV_NAME, "").strip()
    wxid_raw = os.getenv("WX_ID", "").strip()
    cache = _load_wxsf_cache()

    # 账号来源优先级（单源管理）：WX_ID（与 getCode/习酒共用） > wxsf > wxsf.json 缓存
    if wxid_raw:
        selected = _parse_wxsf_env(wxid_raw)
        print(f"ℹ️ 使用 WX_ID 作为账号来源（共 {len(selected)} 个）")
    elif wxsf_raw:
        selected = _parse_wxsf_env(wxsf_raw)
    else:
        selected = [{"wxid": wxid, "remark": wxid} for wxid in cache.keys()]

    if not selected:
        return []

    account_urls = []
    for acc in selected:
        wxid = acc.get("wxid", "").strip()
        remark = acc.get("remark", wxid)
        if not wxid:
            continue

        item = _normalize_wxsf_item(cache.get(wxid, {}))
        ck_ok = _mcs_if_login(item)
        if ck_ok:
            print(f"✅ {remark} 使用 wxsf.json 缓存CK")
        else:
            if item.get("sessionId"):
                print(f"⚠️ {remark} 缓存CK失效，准备协议刷新")
            else:
                print(f"ℹ️ {remark} 无缓存CK，准备协议登录")

            try:
                item = _refresh_wxsf_item_via_protocol(wxid, item, wechat_server)
                cache[wxid] = item
                _save_wxsf_cache(cache)
                print(f"💾 {remark} 协议刷新成功并写入 wxsf.json")
            except Exception as e:
                print(f"❌ {remark} 协议刷新失败: {e}")
                if not item.get("sessionId"):
                    continue

        ck = _cookie_string_from_item(item)
        if "_login_mobile_=" not in ck or "_login_user_id_=" not in ck:
            print(f"❌ {remark} CK字段不完整，跳过")
            continue
        account_urls.append(ck)

    if account_urls:
        os.environ[env_name] = "&".join(account_urls)
        print(f"🔁 已自动将 wxsf.json 转换为 {env_name}（共{len(account_urls)}个账号）")

    return account_urls

ACTIVITY_CODE = "WORLD_CUP"
TOKEN = 'wwesldfs29aniversaryvdld29'
SYS_CODE = 'MCS-MIMP-CORE'

CURRENCY_NAMES = {'GOLD_COIN': '金币'}
CHANNEL = '26sjbapp'
PLATFORM = 'SFAPP'
CITY_CODE = '021'

SKIP_TASK_TYPES = [
    'BUY_ADD_VALUE_SERVICE_PACKET',
    'SEND_INTERNATIONAL_PACKAGE',
    'LOOK_BIG_PACKAGE_GET_CASH',
    'SEND_SUCCESS_RECALL',
    'CHARGE_NEW_EXPRESS_CARD',
    'CHARGE_COLLECT_ALL',
    'OPEN_FAMILY_HOME_MUTUAL',
    'INVITEFRIENDS_PARTAKE_ACTIVITY',
    'BROWSE_INTEGRAL_PLANET',
    'BROWSE_FAMILY_HOME_MUTUAL',
]
# 浏览类任务一律跳过（含 BROWSE_/VIEWPAGE_ 前缀），不发起 finishTask
SKIP_TASK_PREFIXES = ('BROWSE_', 'VIEWPAGE_')

# 仅对这些 taskCode 直接调用 finishTask
AUTO_FINISH_TASK_CODES = {
    '0CD7AFA68009402DBE5BF9D3C10D0115',  # 浏览积分商城（验证通过）
    '895011E183CE4E61BBACE8A63B98596A',  # 去看看互寄8折权益（未验证，可移除）
}


class Logger:
    def __init__(self):
        self.messages: List[str] = []
        self.lock = Lock()

    def _log(self, icon: str, msg: str):
        line = f"{icon} {msg}"
        with print_lock:
            print(line)
        with self.lock:
            self.messages.append(line)

    def info(self, msg): self._log('📝', msg)
    def success(self, msg): self._log('✅', msg)
    def warning(self, msg): self._log('⚠️', msg)
    def error(self, msg): self._log('❌', msg)
    def task(self, msg): self._log('🎯', msg)
    def goal(self, msg): self._log('⚽', msg)


class ProxyManager:
    def __init__(self, api_url: str):
        self.api_url = api_url

    def get_proxy(self) -> Optional[Dict[str, str]]:
        try:
            if not self.api_url:
                return None
            response = requests.get(self.api_url, timeout=10)
            if response.status_code == 200:
                proxy_text = response.text.strip()
                if ':' in proxy_text:
                    proxy = proxy_text if proxy_text.startswith('http') else f'http://{proxy_text}'
                    display = proxy
                    if '@' in proxy:
                        parts = proxy.split('@')
                        display = f"http://***:***@{parts[-1]}"
                    with print_lock:
                        print(f"✅ 获取代理: {display}")
                    return {'http': proxy, 'https': proxy}
            with print_lock:
                print(f"❌ 获取代理失败: HTTP {response.status_code}")
            return None
        except Exception as e:
            with print_lock:
                print(f"❌ 获取代理异常: {str(e)[:100]}")
            return None


class SFHttpClient:
    def __init__(self, proxy_manager: ProxyManager):
        self.proxy_manager = proxy_manager
        self.session = requests.Session()
        self.session.verify = False

        proxy = self.proxy_manager.get_proxy()
        if proxy:
            self.session.proxies = proxy
        else:
            if self.proxy_manager.api_url:
                with print_lock:
                    print("⚠️ 代理获取失败，将不使用代理")

        self.headers = {
            'Host': 'mcs-mimp-web.sf-express.com',
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 mediaCode=SFEXPRESSAPP-iOS-ML',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'channel': CHANNEL,
            'platform': PLATFORM,
            'accept-language': 'zh-CN,zh;q=0.9',
        }

    def _generate_sign(self) -> Dict[str, str]:
        timestamp = str(int(round(time.time() * 1000)))
        data = f'token={TOKEN}&timestamp={timestamp}&sysCode={SYS_CODE}'
        signature = hashlib.md5(data.encode()).hexdigest()
        return {
            'sysCode': SYS_CODE,
            'timestamp': timestamp,
            'signature': signature,
        }

    def request(self, url: str, data: Optional[Dict] = None, method: str = 'POST') -> Optional[Dict]:
        retry_count = 0
        proxy_retry_count = 0

        while proxy_retry_count < MAX_PROXY_RETRIES:
            sign_data = self._generate_sign()
            headers = {**self.headers, **sign_data}

            try:
                if method == 'POST':
                    resp = self.session.post(url, headers=headers, json=data or {}, timeout=PROXY_TIMEOUT)
                else:
                    resp = self.session.get(url, headers=headers, timeout=PROXY_TIMEOUT)
                resp.raise_for_status()

                try:
                    result = resp.json()
                    if result is None:
                        retry_count += 1
                        if retry_count < REQUEST_RETRY_COUNT:
                            time.sleep(2)
                            continue
                        return None
                    return result
                except (json.JSONDecodeError, ValueError):
                    retry_count += 1
                    if retry_count < REQUEST_RETRY_COUNT:
                        time.sleep(2)
                        continue
                    return None

            except requests.exceptions.RequestException as e:
                retry_count += 1
                error_str = str(e)

                if 'ProxyError' in error_str or 'SSLError' in error_str or 'ConnectionError' in error_str:
                    proxy_retry_count += 1
                    if proxy_retry_count < MAX_PROXY_RETRIES:
                        new_proxy = self.proxy_manager.get_proxy()
                        if new_proxy:
                            self.session.proxies = new_proxy
                        retry_count = 0
                    time.sleep(2)
                    continue

                if retry_count < REQUEST_RETRY_COUNT:
                    time.sleep(2)
                    continue
                return None

            except Exception:
                return None

        return None

    def login(self, url: str) -> tuple:
        try:
            decoded_input = unquote(url)
            if decoded_input.startswith('sessionId=') or '_login_mobile_=' in decoded_input:
                cookie_dict = {}
                for item in decoded_input.split(';'):
                    item = item.strip()
                    if '=' in item:
                        k, v = item.split('=', 1)
                        cookie_dict[k] = v
                for k, v in cookie_dict.items():
                    self.session.cookies.set(k, v, domain='mcs-mimp-web.sf-express.com')
                user_id = cookie_dict.get('_login_user_id_', '')
                phone = cookie_dict.get('_login_mobile_', '')
                return (True, user_id, phone) if phone else (False, '', '')
            else:
                self.session.get(unquote(url), headers=self.headers, timeout=PROXY_TIMEOUT)
                cookies = self.session.cookies.get_dict()
                user_id = cookies.get('_login_user_id_', '')
                phone = cookies.get('_login_mobile_', '')
                return (True, user_id, phone) if phone else (False, '', '')
        except Exception as e:
            print(f'登录异常: {str(e)}')
            return False, '', ''


class WorldCupExecutor:
    BASE_URL = 'https://mcs-mimp-web.sf-express.com/mcs-mimp'

    def __init__(self, http: SFHttpClient, logger: Logger, user_id: str):
        self.http = http
        self.logger = logger
        self.user_id = user_id
        self.level_list: List[Dict] = []

    def _post(self, path: str, data: Optional[Dict] = None) -> Optional[Dict]:
        url = f'{self.BASE_URL}{path}'
        return self.http.request(url, data=data or {})

    def get_activity_index(self) -> Optional[Dict]:
        resp = self._post('/commonPost/~memberNonactivity~worldCupIndexService~index')
        if resp and resp.get('success'):
            return resp.get('obj', {})
        return None

    def get_game_index(self) -> Optional[Dict]:
        resp = self._post('/commonPost/~memberNonactivity~worldCupGameService~index')
        if resp and resp.get('success'):
            return resp.get('obj', {})
        return None

    def get_bet_status(self) -> Optional[Dict]:
        resp = self._post('/commonPost/~memberNonactivity~worldCupMatchService~betStatus')
        if resp and resp.get('success'):
            return resp.get('obj', {})
        return None

    def get_daily_gift_status(self) -> Optional[Dict]:
        data = {"cityCode": CITY_CODE}
        resp = self._post('/commonPost/~memberNonactivity~worldCupDailyService~getDailyGiftStatus', data)
        if resp and resp.get('success'):
            return resp.get('obj', {})
        return None

    def receive_daily_gift(self) -> Optional[Dict]:
        data = {"cityCode": CITY_CODE}
        resp = self._post('/commonPost/~memberNonactivity~worldCupDailyService~receiveDailyGift', data)
        if resp and resp.get('success'):
            return resp.get('obj', {})
        return None

    def get_task_list(self) -> Optional[List[Dict]]:
        data = {"activityCode": ACTIVITY_CODE, "channelType": PLATFORM}
        resp = self._post('/commonPost/~memberNonactivity~activityTaskService~taskList', data)
        if resp and resp.get('success'):
            return resp.get('obj', [])
        return None

    def finish_task(self, task_code: str) -> bool:
        url = f'{self.BASE_URL}/commonPost/~memberEs~taskRecord~finishTask'
        data = {"taskCode": task_code}
        resp = self.http.request(url, data=data)
        return bool(resp and resp.get('success'))

    def fetch_task_reward(self) -> Optional[Dict]:
        data = {"channelType": PLATFORM, "activityCode": ACTIVITY_CODE}
        resp = self._post('/commonPost/~memberNonactivity~worldCupTaskService~fetchTaskReward', data)
        if resp and resp.get('success'):
            return resp.get('obj', {})
        return None

    def report_pass(self, level: int, shot_num: int) -> Optional[Dict]:
        data = {"level": level, "shotNum": shot_num}
        resp = self._post('/commonPost/~memberNonactivity~worldCupGameService~passReport', data)
        if resp and resp.get('success'):
            return resp.get('obj', {})
        err = resp.get('errorMessage', '未知错误') if resp else '请求失败'
        self.logger.warning(f'第{level}关上报失败: {err}')
        return None

    def place_bet(self, match_id: str, bet_result: int, bet_coin: int) -> bool:
        """下注
        bet_result: 0=主胜 1=平 2=客胜 (与 odds 数组顺序一致)
        bet_coin: 下注金币数
        """
        data = {"matchId": match_id, "betResult": bet_result, "betCoin": bet_coin}
        resp = self._post('/commonPost/~memberNonactivity~worldCupMatchService~placeBet', data)
        if resp and resp.get('success'):
            return True
        err = resp.get('errorMessage', '未知错误') if resp else '请求失败'
        self.logger.warning(f'下注失败(match={match_id}, result={bet_result}): {err}')
        return False

    def do_invite(self):
        try:
            available_invites = [inv for inv in inviteId if inv != self.user_id]
            if not available_invites:
                return
            random_invite = random.choice(available_invites)
            url = f'{self.BASE_URL}/commonPost/~memberNonactivity~worldCupIndexService~index'
            self.http.request(url, data={"inviteType": 1, "inviteUserId": random_invite})
        except Exception as e:
            self.logger.error(f"邀请初始化异常: {str(e)}")

    def do_daily_gift(self, result: Dict) -> None:
        self.logger.task('[每日礼物] 检查状态...')
        status = self.get_daily_gift_status()
        if status is None:
            self.logger.warning('[每日礼物] 获取状态失败')
            return
        if status.get('received'):
            self.logger.success('[每日礼物] 今日已领取')
            return
        if not status.get('canReceive'):
            self.logger.info('[每日礼物] 今日不可领取')
            return
        self.logger.task('[每日礼物] 尝试领取...')
        if self.receive_daily_gift():
            self.logger.success('[每日礼物] 领取成功')
            result['daily_gift'] = True
        else:
            self.logger.warning('[每日礼物] 领取失败')

    def do_tasks(self, result: Dict) -> None:
        self.logger.info('正在获取世界杯活动任务列表...')
        tasks = self.get_task_list()
        if tasks is None:
            return
        self.logger.info(f'共发现 {len(tasks)} 个任务')

        for task in tasks:
            task_name = task.get('taskName', '未知')
            task_type = task.get('taskType', '')
            task_code = task.get('taskCode', '')
            status = task.get('status')
            rest_finish = task.get('restFinishTime', 0)
            can_receive = task.get('canReceiveTokenNum', 0)
            max_finish = task.get('maxFinishTime', 0)

            if task_code not in AUTO_FINISH_TASK_CODES:
                continue

            self.logger.info(f'[{task_name}]')

            if status == 3 or (status == 1 and rest_finish <= 0):
                self.logger.success(f'[{task_name}] 已完成')
                continue

            if self.finish_task(task_code):
                self.logger.success(f'[{task_name}] 完成成功')
                result['tasks_completed'] += 1
            else:
                self.logger.warning(f'[{task_name}] 完成失败')
            time.sleep(1)

    def do_fetch_rewards(self, result: Dict) -> None:
        self.logger.info('领取任务奖励...')
        reward_resp = self.fetch_task_reward()
        if reward_resp:
            received = reward_resp.get('receivedAccountList', [])
            if received:
                for item in received:
                    currency = item.get('currency', '')
                    amount = item.get('amount', 0)
                    self.logger.success(f'领取: {currency} x{amount}')
            else:
                self.logger.info('无新奖励可领取')

    def play_game(self, result: Dict) -> None:
        self.logger.info('⚽ 开始挑战射门游戏...')
        game_info = self.get_game_index()
        if game_info is None:
            self.logger.warning('获取游戏配置失败')
            return

        self.level_list = game_info.get('levelList', [])
        cur_stage = game_info.get('curStage', 1)
        cur_level = game_info.get('curLevel', 1)

        if not self.level_list:
            self.logger.warning('游戏关卡列表为空')
            return

        self.logger.info(f'当前进度: 第{cur_stage}阶段 第{cur_level}关')

        for level_cfg in self.level_list:
            level_no = level_cfg.get('level')
            target = level_cfg.get('target', 0)
            reward = level_cfg.get('rewardCoins', 0)

            if level_no < cur_level:
                continue

            self.logger.task(f'挑战第{level_no}关（目标 {target} 次进球，奖励 {reward} 金币）')

            pass_result = self.report_pass(level_no, target)

            attempts = 0
            while attempts < 3 and (pass_result is None or not pass_result.get('coinNum', 0) >= reward):
                time.sleep(1)
                pass_result = self.report_pass(level_no, target)
                attempts += 1

            if pass_result:
                result['stages_passed'].append({
                    'level': level_no,
                    'coins': pass_result.get('coinNum', 0),
                    'reward': reward,
                })
                result['game_coins'] += pass_result.get('coinNum', 0)
                self.logger.goal(f'第{level_no}关完成，获得 {pass_result.get("coinNum", 0)} 金币')
            else:
                self.logger.warning(f'第{level_no}关未通过')

    def do_bet(self, result: Dict) -> None:
        self.logger.info('⚽ 查询比赛竞猜状态（不下注，仅展示）...')
        bet_status = self.get_bet_status()
        if bet_status is None:
            return

        account = bet_status.get('currentAccount', {})
        balance = account.get('balance', 0)
        self.logger.info(f'当前金币余额: {balance}')

        result['final_balance'] = balance
        result['final_total'] = account.get('totalAmount', 0)

        matches = bet_status.get('matchList', [])
        if not matches:
            return

        pending = [m for m in matches if m.get('matchStatus') == 'Fixture']
        self.logger.info(f'共 {len(matches)} 场比赛，{len(pending)} 场未开赛')
        for m in pending[:6]:
            self.logger.info(
                f'  · {m.get("matchTime","")} {m.get("teamAName","?")} vs {m.get("teamBName","?")} '
                f'赔率 {m.get("odds","?,?,?")}'
            )

    def show_status(self) -> None:
        self.logger.info('=' * 20 + '  世界杯活动状态  ' + '=' * 20)
        bet_status = self.get_bet_status()
        if bet_status:
            account = bet_status.get('currentAccount', {})
            self.logger.info(f'金币余额: {account.get("balance", 0)} / 累计: {account.get("totalAmount", 0)}')

        daily = self.get_daily_gift_status()
        if daily:
            status_str = '已领取' if daily.get('received') else ('可领取' if daily.get('canReceive') else '不可领取')
            self.logger.info(f'每日礼物: {status_str}')

        game = self.get_game_index()
        if game:
            self.logger.info(f'游戏阶段: 第{game.get("curStage", 1)}阶段 第{game.get("curLevel", 1)}关')

        index = self.get_activity_index()
        if index:
            self.logger.info(f'活动周期: {index.get("acStartTime", "")} ~ {index.get("acEndTime", "")}')
            self.logger.info(f'可领金币: {index.get("availableRewardCoins", 0)}')

        self.logger.info('=' * 56)

    def run(self) -> Dict[str, Any]:
        result = {
            'tasks_completed': 0,
            'game_coins': 0,
            'stages_passed': [],
            'daily_gift': False,
            'bets_placed': 0,
            'final_balance': 0,
            'final_total': 0,
        }

        self.do_invite()

        index_info = self.get_activity_index()
        if index_info:
            self.logger.success(f'已加入世界杯活动，可领 {index_info.get("availableRewardCoins", 0)} 金币')

        self.do_daily_gift(result)
        self.do_tasks(result)
        self.do_fetch_rewards(result)
        self.play_game(result)
        self.do_bet(result)

        return result


def run_account(account_url: str, index: int) -> Dict[str, Any]:
    logger = Logger()
    proxy_url = os.getenv('SF_PROXY_API_URL', '')
    proxy_manager = ProxyManager(proxy_url)

    http = SFHttpClient(proxy_manager)
    retry_count = 0
    login_success = False
    phone = ''
    user_id = ''

    while retry_count < MAX_PROXY_RETRIES and not login_success:
        try:
            if retry_count > 0:
                http = SFHttpClient(proxy_manager)
            success, user_id, phone = http.login(account_url)
            if success:
                login_success = True
                break
        except Exception:
            pass
        retry_count += 1
        if retry_count < MAX_PROXY_RETRIES:
            time.sleep(2)

    if not login_success:
        logger.error(f'账号{index + 1} 登录失败')
        return {
            'success': False, 'phone': '', 'index': index,
            'tasks_completed': 0, 'game_coins': 0, 'stages_passed': [],
            'daily_gift': False, 'bets_placed': 0,
            'final_balance': 0, 'final_total': 0,
        }

    masked_phone = phone[:3] + "****" + phone[7:] if len(phone) >= 7 else phone
    logger.success(f'账号{index + 1}: 【{masked_phone}】登录成功')

    time.sleep(random.uniform(1, 3))

    executor = WorldCupExecutor(http, logger, user_id)
    activity_result = executor.run()

    return {
        'success': True,
        'phone': phone,
        'index': index,
        **activity_result,
    }


def main():
    env_name = 'sfsyUrl'
    env_value = os.getenv(env_name)
    account_urls = []

    if env_value:
        account_urls = [url.strip() for url in env_value.split('&') if url.strip()]
        print(f"✅ 检测到环境变量 {env_name}，按原模式执行")
    else:
        print(f"ℹ️ 未检测到 {env_name}，尝试从 {WXSF_ENV_NAME} / wxsf.json 自动转换...")
        account_urls = _build_sfsy_from_wxsf(env_name)

    if not account_urls:
        print(f"❌ 无可用账号：{env_name} 为空，且 {WXSF_ENV_NAME}/wxsf.json 也不可用")
        print(f"   请配置 {env_name}，或配置 {WXSF_ENV_NAME} + {WECHAT_SERVER_ENV_NAME}")
        return

    random.shuffle(account_urls)

    print("=" * 60)
    print(f"⚽ 顺丰2026世界杯活动 v1.1.0")
    print(f"👨‍💻 广哥哥整合")
    print(f"📱 共获取到 {len(account_urls)} 个账号")
    print(f"⚙️ 并发数量: {CONCURRENT_NUM}")
    print(f"⏰ 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    all_results = []

    if CONCURRENT_NUM <= 1:
        for idx, url in enumerate(account_urls):
            result = run_account(url, idx)
            all_results.append(result)
            if idx < len(account_urls) - 1:
                print("-" * 60)
                time.sleep(2)
    else:
        with ThreadPoolExecutor(max_workers=CONCURRENT_NUM) as pool:
            futures = {pool.submit(run_account, url, idx): idx for idx, url in enumerate(account_urls)}
            for future in as_completed(futures):
                all_results.append(future.result())

    all_results.sort(key=lambda x: x['index'])

    print(f"\n" + "=" * 90)
    print(f"📊 世界杯活动汇总")
    print("=" * 90)
    print(f"{'序号':<6} {'手机号':<15} {'金币余额':<12} {'通关数':<8} {'每日礼物':<10}")
    print("-" * 90)

    total_coins = 0
    total_balance = 0

    for r in all_results:
        idx = r['index'] + 1
        phone = r['phone'][:3] + "****" + r['phone'][7:] if r.get('phone') and len(r['phone']) >= 7 else r.get('phone', '未登录')
        daily = '✅' if r.get('daily_gift') else '❌'
        balance = r.get('final_balance', 0)
        stages = len(r.get('stages_passed', []))

        total_balance += balance
        total_coins += r.get('game_coins', 0)

        print(f"{idx:<6} {phone:<15} {balance:<12} {stages:<8} {daily:<10}")

    print("-" * 90)
    print(f"{'汇总':<6} {'账号: ' + str(len(all_results)):<15} 总金币余额: {total_balance} | 游戏产出: {total_coins}")
    print("=" * 90)
    print("\n🎊 所有账号执行完成!")


if __name__ == '__main__':
    main()
