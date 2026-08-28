#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
草原云自动签到 + 每日阅读任务 账号密码版

功能：
  1. 每日签到
  2. 每日阅读任务（阅读打卡 + 自动完成）
  3. 查询金币余额
  4. PushPlus 推送

环境变量：
  CYY               登陆账号，格式 "手机号#密码"，多个账号用 & 或换行分隔
  CYY_READ_SECONDS  阅读秒数，支持区间如 20,30 表示随机20-30秒，默认 3
  CYY_MAX_TASKS     最多完成任务数，0 表示全部，默认 0
  CYY_NO_SIGNIN     1 表示跳过签到，默认 0
  PUSH_PLUS_TOKEN   PushPlus token，可选

依赖：
  pip install requests pycryptodome
  滑块自动破解需：
  pip install pillow numpy
"""

import base64
import builtins
import hashlib
import json
import math
import os
import random
import re
import secrets
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Tuple
from urllib.parse import quote, urlencode

import requests

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_PRINT_LOCK = threading.Lock()


def _print(*args, **kwargs):
    with _PRINT_LOCK:
        builtins.print(*args, **kwargs)


# 滑块验证码可选依赖（缺失时跳过自动破解）
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

try:
    from PIL import Image
    import numpy as np
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


APP_NAME = "草原云（内蒙古日报）"

# 账号列表：格式 "手机号#密码"，多个账号用 & 或换行分隔
_CYY_DEFAULT = ""


def parse_cyy(env_value: str) -> List[str]:
    """解析账号字符串，支持 & 或换行分隔，格式：手机号#密码"""
    accounts = []
    for line in env_value.split('\n'):
        line = line.strip()
        if not line:
            continue
        for part in line.split('&'):
            part = part.strip()
            if part:
                accounts.append(part)
    return accounts


CYY = parse_cyy(os.getenv("CYY", "") or _CYY_DEFAULT)

PUSH_PLUS_TOKEN = os.getenv("PUSH_PLUS_TOKEN", "")

def _parse_read_seconds(raw: str) -> Tuple[int, int]:
    """解析阅读秒数，支持 '20,30' 区间或 '3' 固定值"""
    raw = (raw or "3").strip()
    if "," in raw:
        parts = raw.split(",")
        try:
            lo, hi = int(parts[0]), int(parts[1])
            if lo > hi:
                lo, hi = hi, lo
            return lo, hi
        except (ValueError, IndexError):
            pass
    try:
        v = int(raw)
        return v, v
    except ValueError:
        return 3, 3


CYY_READ_SECONDS = _parse_read_seconds(os.getenv("CYY_READ_SECONDS", "3"))


def get_read_seconds() -> int:
    """根据 CYY_READ_SECONDS 区间返回随机阅读秒数"""
    lo, hi = CYY_READ_SECONDS
    return random.randint(lo, hi) if hi > lo else lo
CYY_MAX_TASKS = int(os.getenv("CYY_MAX_TASKS", "0") or 0)
CYY_NO_SIGNIN = os.getenv("CYY_NO_SIGNIN", "0") == "1"

REQUEST_TIMEOUT = 30

CYY_BASE = "https://cyy.nmgcyy.com.cn"
CYY_API_BASE = "https://ya.iyunxh.com"
CYY_H5_DOMAIN = "https://nmgrb.y-h5.iyunxh.com"
CYY_APP_ID = "nmgrb"
# 租户配置硬编码（原 _auth_h5init 静态返回，多次请求一致）
CYY_APPKEY = "c17eb7a4cfa2d9fe5d1b4a078b017117"
CYY_T_ID = "2433"
CYY_ACTIVITY_ID = "11106660"
CYY_MODULE_ID = "41603"
CYY_SIGN_ACTIVITY_ID = 10609026

LOGIN_URL = f"{CYY_BASE}/member/login/memberLogin"
DEVICE_DT_URL = f"{CYY_API_BASE}/api/aosbase/_auth_dt"
APPUSER_INIT_URL = f"{CYY_API_BASE}/api/aosbase/_auth_appuserinit"
SIGN_TIMES_URL = f"{CYY_API_BASE}/api/aossignin/user_times"
SIGN_URL = f"{CYY_API_BASE}/api/aossignin/ac_sub"
USER_INFO_URL = f"{CYY_API_BASE}/api/aosbase/user_info"
OPTIONP_LIST_URL = f"{CYY_API_BASE}/api/aoslearnfoot/_optionp_list"
OPTIONP_DETAIL_URL = f"{CYY_API_BASE}/api/aoslearnfoot/optionp_detail"
TASK_LIST_URL = f"{CYY_API_BASE}/api/aosbasemodule/_task_list"
TASK_CREATE_URL = f"{CYY_API_BASE}/api/aosbasemodule/task_create"
TASK_DONE_URL = f"{CYY_API_BASE}/api/aosbasemodule/task_done"
ADD_FOOTPRINT_URL = f"{CYY_BASE}/fcpublic/Memberfootprint/addfootprint"
COMPLETE_READING_URL = f"{CYY_BASE}/fcpublic/yundian/complateReading"
CAPTCHA_GET_URL = f"{CYY_API_BASE}/api/basemodule/_captcha_get"
CAPTCHA_CHECK_URL = f"{CYY_API_BASE}/api/basemodule/_captcha_check"
CAPTCHA_VERIFY_URL = f"{CYY_API_BASE}/api/aosbasemodule/intelverifcode_check"

CYY_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) TMAppName/caoyuanyun "
    "TMAppName/caoyuanyun tm_language/zh-cn"
)

CYY_APP_USER_AGENT = "TMProject/4.7.0 (iPhone; iOS 17.0; Scale/3.00)"

# 滑块验证码 AES 密钥（config pro，逆向自前端 yundian-slide-captcha）
CAPTCHA_AES_KEY = "7Pf0cfZPHy1L7PS2PfCfP8r2BGi461LG".encode()
CAPTCHA_AES_IV = "8RsVKSCH8mQ4l7cu".encode()

# TransCode 随机字符串字符集（逆向自 transcode.js randomString）
TC_CHARSET = "abcdefhijkmnprstwxyz2345678"


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


def safe_data(resp: Dict[str, Any]) -> Dict[str, Any]:
    """Safely extract 'data' from an API response, handling null/missing."""
    data = resp.get("data") or {}
    return data if isinstance(data, dict) else {}


def log_title() -> None:
    _print()
    _print("╔" + "═" * 50 + "╗")
    _print("║ 🌾 草原云自动签到账号密码版               ║")
    _print(f"║ 🕒 启动时间: {now_text():<32}║")
    _print(f"║ 🔢 账号数量: {len(CYY):<34}║")
    _print("╚" + "═" * 50 + "╝")


def log_account_header(index: int, total: int, account: str) -> None:
    _print()
    _print("┌" + "─" * 50 + "┐")
    _print(f"│ 🧩 账号 {index} / {total:<37}│")
    _print(f"│ 📱 手机号 {mask(account):<38}│")
    _print("└" + "─" * 50 + "┘")


# ── TransCode 加密/解密（逆向自 transcode.js）──


def _md5(text: str) -> str:
    """hex_md5 等价"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _b64encode_str(text: str) -> str:
    """Base64.encode 等价（输入字符串，输出字符串）"""
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


def _random_string(n: int = 16) -> str:
    """生成随机字符串（与 transcode.js randomString 相同字符集）"""
    return "".join(random.choice(TC_CHARSET) for _ in range(n))


class TransCode:
    """
    天马(TianMa)框架 TransCode 的 Python 等价实现。
    AES-128-CBC + PKCS7，key/iv 从 timestamp 和 randomNum 派生。

    请求加密 key/iv:
      key = md5( base64(timestamp) + md5(random_num) )[:16]
      iv  = md5( base64(random_num) + md5(timestamp) )[:16]

    响应解密 key/iv:
      key = md5( base64(timestamp) + md5(timestamp) )[:16]
      iv  = md5( random_num )[:16]

    tmencryptkey = md5( base64( md5(timestamp) + random_num ) + random_num )
    """

    def __init__(self):
        self.timestamp = str(int(time.time() * 1000))
        self.random_num = _random_string(16)
        self.tmencryptkey = _md5(
            _b64encode_str(_md5(self.timestamp) + self.random_num) + self.random_num
        )

    def headers(self) -> Dict[str, str]:
        """生成请求头参数"""
        return {
            "tmencrypt": "1",
            "tmtimestamp": self.timestamp,
            "tmrandomnum": self.random_num,
            "tmencryptkey": self.tmencryptkey,
            "tmtimestampnew": self.timestamp,
            "tmrandomnumnew": self.random_num,
            "tmencryptkeynew": self.tmencryptkey,
        }

    def encrypt(self, data: Any) -> str:
        """加密请求数据，返回 Base64 字符串"""
        if isinstance(data, (dict, list)):
            plaintext = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        else:
            plaintext = str(data)

        key = _md5(_b64encode_str(self.timestamp) + _md5(self.random_num))[:16]
        iv = _md5(_b64encode_str(self.random_num) + _md5(self.timestamp))[:16]

        cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))
        ct = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
        return base64.b64encode(ct).decode("utf-8")

    def decrypt(self, ciphertext: str) -> Any:
        """解密服务器响应数据"""
        key = _md5(_b64encode_str(self.timestamp) + _md5(self.timestamp))[:16]
        iv = _md5(self.random_num)[:16]

        cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))
        pt = unpad(cipher.decrypt(base64.b64decode(ciphertext)), AES.block_size)
        return json.loads(pt.decode("utf-8"))


# ── PushPlus 推送 ──


def send_pushplus(title: str, content: str) -> None:
    if not PUSH_PLUS_TOKEN:
        _print("⚠️ [PushPlus] 未配置 PUSH_PLUS_TOKEN，跳过推送")
        return

    try:
        requests.post(
            "https://www.pushplus.plus/send",
            json={
                "token": PUSH_PLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "markdown",
            },
            timeout=10,
        )
        _print("✅ [PushPlus] 推送成功")
    except Exception as exc:
        _print(f"❌ [PushPlus] 推送失败: {exc}")


# ── 登录 ──


def _gen_device_num() -> str:
    """生成设备编号（16位hex）"""
    return secrets.token_hex(8)


def _gen_mac_no() -> str:
    """生成 MAC 地址（大写hex，无冒号，32位）"""
    return secrets.token_hex(16).upper()


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


def extract_member_id(raw_login: Any) -> int:
    if not isinstance(raw_login, dict):
        return 0

    # 账号密码登录: 解密后的数据直接包含 member_info
    member = raw_login.get("member_info")
    if isinstance(member, dict):
        try:
            return int(member.get("member_id") or 0)
        except (TypeError, ValueError):
            return 0

    # 兼容旧格式: data.member_info
    inner = raw_login.get("data")
    if not isinstance(inner, dict):
        return 0
    member = inner.get("member_info")
    if isinstance(member, dict):
        try:
            return int(member.get("member_id") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def login_by_password(
    account: str,
    password: str,
) -> Tuple[str | None, Dict[str, Any] | None]:
    """使用手机号+密码登录，返回 (token, raw_login_data)"""
    try:
        _print("🔐 [登录] 使用账号密码登录")

        tc = TransCode()

        login_data = {
            "mobile": account,
            "state": 2,
            "site_code": "0" * 32,
            "code": "",
            "password": password,
            "channel_sources": "Default",
            "device_num": _gen_device_num(),
            "device_no": _gen_device_num(),
            "imei_no": "",
            "mac_no": _gen_mac_no(),
        }

        encrypted = tc.encrypt(login_data)

        headers = {
            "Host": "cyy.nmgcyy.com.cn",
            "content-type": "application/json; charset=utf-8",
            "accept-encoding": "gzip",
            "user-agent": "okhttp/3.12.13",
            **tc.headers(),
        }

        response = requests.post(
            LOGIN_URL,
            headers=headers,
            json={"tm_encrypt_data": encrypted},
            timeout=REQUEST_TIMEOUT,
        )

        try:
            resp_json = response.json()
        except Exception:
            _print(f"❌ [登录] 响应非 JSON: HTTP {response.status_code}")
            return None, None

        # 检查是否加密响应
        if resp_json.get("tmencrypt") == 1 and resp_json.get("data"):
            try:
                decrypted = tc.decrypt(resp_json["data"])
                resp_json["data"] = decrypted
            except Exception as exc:
                _print(f"❌ [登录] 响应解密失败: {exc}")
                return None, resp_json

        code = resp_json.get("code")
        if code != 200:
            _print(f"❌ [登录] 登录失败: code={code} msg={resp_json.get('msg')}")
            return None, resp_json

        login_data_decrypted = resp_json.get("data") or {}
        token = extract_token(login_data_decrypted) or extract_token(resp_json)

        if token:
            _print(f"✅ [登录] token 获取成功: {mask(token)}")
            return token, login_data_decrypted

        _print(f"❌ [登录] 未识别 token 字段: {json_preview(resp_json)}")
        return None, resp_json

    except Exception as exc:
        _print(f"❌ [登录] 请求异常: {exc}")
        return None, None


# ── iyunxh 平台签名工具 ──


def md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def guid32() -> str:
    """前端 $u.guid(32,false): 32位随机字符串"""
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(random.choice(alphabet) for _ in range(32))


def get_aas_key(appkey: str) -> str:
    """getAASkey(appkey) = md5(偶数位 + 奇数位)"""
    if not appkey:
        return ""
    even = "".join(appkey[i] for i in range(0, len(appkey), 2))
    odd = "".join(appkey[i] for i in range(1, len(appkey), 2))
    return md5(even + odd)


def urlencode_component(value: Any) -> str:
    """前端 urlencode: encodeURIComponent 后把 !'()* 转 %XX, 空格转 +"""
    text = quote(str(value), safe="~")
    text = text.replace("!", "%21").replace("'", "%27").replace("(", "%28").replace(")", "%29") \
        .replace("*", "%2A").replace("%20", "+")
    return text


def ksort(params: Dict[str, Any]) -> Dict[str, Any]:
    return {k: params[k] for k in sorted(params.keys())}


def obj_to_query(params: Dict[str, Any], leading_qmark: bool = False) -> str:
    """前端 objToQueryParams: a=b&c=d（按 key 升序、urlencode 后的值）"""
    parts = []
    for k in sorted(params.keys()):
        parts.append(k + "=" + urlencode_component(params[k]))
    query = "&".join(parts)
    return ("?" if leading_qmark else "") + query


def make_signature() -> str:
    aaskey = get_aas_key(CYY_APPKEY)
    nonce = guid32()
    ts = int(time.time() * 1000)
    sig = md5(CYY_APP_ID + nonce + str(ts) + aaskey)
    return f"{CYY_APP_ID};{nonce};{ts};{sig}"


def fetch_device_dt(account: str) -> str:
    _print("📱 [设备] 获取设备令牌 Access-Api-Dt")
    device_id = str(int(time.time() * 1000)) + str(random.randint(10 ** 8, 10 ** 9 - 1))[:9]
    response = requests.get(
        DEVICE_DT_URL,
        headers={
            "Access-T-Id": CYY_T_ID,
            "Access-T-Id-In": CYY_T_ID,
            "Access-Api-Unique-Token": "1",
            "Access-Api-Dt": device_id,
            "User-Agent": CYY_USER_AGENT,
        },
        timeout=REQUEST_TIMEOUT,
    )
    try:
        data = response.json()
    except Exception:
        raise RuntimeError("获取设备令牌响应非 JSON: HTTP %d" % response.status_code)
    if data.get("code") not in ("0", 0):
        raise RuntimeError("获取设备令牌失败: %s" % (data.get("msg") or json_preview(data, 300)))

    token = data.get("data") or ""
    if len(token) < 68:
        raise RuntimeError("设备令牌异常(长度 %d)" % len(token))
    access_api_dt = token[32:68]
    _print(f"✅ [设备] Access-Api-Dt: {mask(access_api_dt)}")
    return access_api_dt


def appuser_init(
    account: str,
    app_user_token: str,
) -> Tuple[str, int]:
    _print("🔐 [登录] 使用 token 换 access_token")
    params = {
        "app_user_token": app_user_token,
        "appid": CYY_APP_ID,
        "noncestr": guid32(),
        "phone": "",
        "portrait_url": "/images/default/head.jpg",
        "timestamp": int(time.time()),
        "user_id": 0,
        "user_name": "微信用户",
        "wx_openid": "",
        "wx_unionid": "",
    }
    params = ksort(params)
    sign_src = obj_to_query(params) + "&appkey=" + CYY_APPKEY
    params["signature"] = md5(sign_src)

    headers = {
        "Access-T-Id": CYY_T_ID,
        "Access-T-Id-In": CYY_T_ID,
        "Access-Api-Unique-Token": "1",
        "Access-Wxclient-Type": "wx_app",
        "Access-Api-Signature": make_signature(),
        "Content-Type": "application/json",
        "User-Agent": CYY_USER_AGENT,
        "Origin": CYY_H5_DOMAIN,
        "Referer": CYY_H5_DOMAIN + "/",
    }
    response = requests.post(
        APPUSER_INIT_URL,
        headers=headers,
        json=params,
        timeout=REQUEST_TIMEOUT,
    )
    try:
        data = response.json()
    except Exception:
        raise RuntimeError("appuserinit 响应非 JSON: HTTP %d" % response.status_code)
    if data.get("code") not in ("0", 0):
        raise RuntimeError("appuserinit 失败: %s" % (data.get("msg") or json_preview(data, 300)))

    payload = data.get("data") or {}
    access_token = payload.get("access_token", "")
    info = payload.get("data") or {}
    user_id = info.get("user_id") or 0
    if not access_token:
        raise RuntimeError("未识别 access_token 字段: %s" % json_preview(data, 300))
    _print(f"✅ [登录] access_token 获取成功: {mask(access_token)}")
    return access_token, user_id


def iyunxh_headers(
    access_token: str,
    user_id: int,
    access_api_dt: str,
) -> Dict[str, str]:
    return {
        "Access-Token": access_token,
        "Access-User-Id": str(user_id),
        "Access-T-Id": CYY_T_ID,
        "Access-T-Id-In": CYY_T_ID,
        "Access-Api-Unique-Token": "1",
        "Access-Wxclient-Type": "wx_app",
        "Access-Api-Signature": make_signature(),
        "Access-Api-Dt": access_api_dt,
        "Origin": CYY_H5_DOMAIN,
        "Referer": CYY_H5_DOMAIN + "/",
    }


# ── API 调用 ──


def api_get(account: str, url: str, headers: Dict[str, str]) -> Dict[str, Any]:
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    try:
        return response.json()
    except Exception:
        return {
            "code": -1,
            "msg": f"JSON解析失败: {response.text[:300]}",
        }


def api_post(
    account: str,
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    try:
        return response.json()
    except Exception:
        return {
            "code": -1,
            "msg": f"JSON解析失败: {response.text[:300]}",
        }


def signin_times(account: str, headers: Dict[str, str]) -> Dict[str, Any]:
    sign_headers = dict(headers)
    sign_headers["X-Requested-With"] = "com.innermongoliadaily.activity"
    url = f"{SIGN_TIMES_URL}?{urlencode({'activity_id': CYY_SIGN_ACTIVITY_ID})}"
    return api_get(account, url, sign_headers)


def signin(account: str, headers: Dict[str, str]) -> Dict[str, Any]:
    sign_headers = dict(headers)
    sign_headers["X-Requested-With"] = "com.innermongoliadaily.activity"
    return api_post(account, SIGN_URL, sign_headers, {
        "id": CYY_SIGN_ACTIVITY_ID,
        "afs_tokenid": "",
        "collect_info": "",
        "longitude": 0,
        "latitude": 0,
    })


def get_user_info(account: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return api_get(account, USER_INFO_URL, headers)


def get_gold(account: str, headers: Dict[str, str]) -> int:
    resp = get_user_info(account, headers)
    if resp.get("code") in ("0", 0):
        try:
            return int(safe_data(resp).get("gold") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def get_optionp_list(account: str, headers: Dict[str, str]) -> Dict[str, Any]:
    url = f"{OPTIONP_LIST_URL}?{urlencode({'activity_id': CYY_ACTIVITY_ID})}"
    return api_get(account, url, headers)


def get_optionp_detail(account: str, headers: Dict[str, str], option_id: Any) -> Dict[str, Any]:
    url = f"{OPTIONP_DETAIL_URL}?{urlencode({'id': option_id})}"
    return api_get(account, url, headers)


def get_task_list(
    account: str,
    headers: Dict[str, str],
    module_id: Any,
    activity_id: Any,
) -> Dict[str, Any]:
    url = f"{TASK_LIST_URL}?{urlencode({'offset': 0, 'count': 30, 'module_id': module_id, 'activity_id': activity_id})}"
    return api_get(account, url, headers)


def task_create(account: str, headers: Dict[str, str], task_id: Any) -> Dict[str, Any]:
    return api_post(account, TASK_CREATE_URL, headers, {"task_id": task_id})


def task_done(
    account: str,
    headers: Dict[str, str],
    task_record_id: str,
    afs_tokenid: str = "",
) -> Dict[str, Any]:
    return api_post(account, TASK_DONE_URL, headers, {
        "task_record_id": task_record_id,
        "collect_info": "",
        "afs_tokenid": afs_tokenid,
        "device_token": "",
    })


def add_foot_print(
    account: str,
    app_user_token: str,
    member_id: int,
    article_id: int,
    title: str,
    news_url: str,
) -> Dict[str, Any]:
    param = {"h5url": news_url, "type": 1}
    body = {
        "app_id": "fcinformation",
        "native": 1,
        "src": "NewsI004WKDetailViewController",
        "paramStr": json.dumps(param, ensure_ascii=False),
        "title": title,
        "pic": "",
        "member_id": member_id,
        "intro": " ",
        "article_id": article_id,
        "article_type": "1",
        "wwwFolder": "wwwFolder",
    }
    ts = int(time.time())
    key = secrets.token_hex(16)
    nonce = secrets.token_hex(8)
    headers = {
        "token": app_user_token,
        "User-Agent": CYY_APP_USER_AGENT,
        "tmencrypt": "1",
        "tmencryptkey": key,
        "tmencryptkeynew": key,
        "tmrandomnum": nonce,
        "tmrandomnumnew": nonce,
        "tmtimestamp": str(ts),
        "tmtimestampnew": str(ts),
    }
    return api_post(account, ADD_FOOTPRINT_URL, headers, body)


def complete_reading(
    account: str,
    app_user_token: str,
    member_id: int,
    article_id: int,
) -> Dict[str, Any]:
    headers = {
        "token": app_user_token,
        "guid": str(uuid.uuid4()),
        "User-Agent": CYY_APP_USER_AGENT,
    }
    return api_post(account, COMPLETE_READING_URL, headers, {
        "content_id": article_id,
        "member_id": member_id,
    })


def parse_rule(rule: Any) -> Dict[str, Any]:
    """解析任务 rule -> {news_url, article_id, title, action}"""
    try:
        rule = rule if isinstance(rule, dict) else json.loads(rule or "{}")
    except Exception:
        return {}
    news_url = (rule.get("news_id") or "").strip()
    match = re.search(r"ArticleDetail(\d+)", news_url)
    article_id = int(match.group(1)) if match else 0
    title = (rule.get("content_info") or {}).get("title") or ""
    return {"news_url": news_url, "article_id": article_id,
            "title": title, "action": rule.get("action") or ""}


def simulate_read(rule: Any, app_user_token: str, member_id: int, read_seconds: int = 0) -> None:
    """访问任务文章 H5 页（触发页面 JS 倒计时上报），再 sleep read_seconds"""
    try:
        rule = rule if isinstance(rule, dict) else json.loads(rule)
    except Exception:
        return
    news_id = (rule.get("news_id") or "").strip()
    action = rule.get("action") or ""
    match = re.search(r"second=(\d+)", news_id)
    need = read_seconds or (int(match.group(1)) if match else 60)
    if news_id and news_id.startswith("http"):
        try:
            base = news_id.split("#")[0]
            fragment = news_id.split("#")[1] if "#" in news_id else ""
            if fragment:
                frag = re.sub(r"(ArticleDetail/\d+)/(undefined|\d+)",
                              r"\1/%s" % member_id, fragment)
                if "fc_token=" not in frag:
                    sep = "&" if "?" in frag else "?"
                    frag += f"{sep}fc_token={app_user_token or ''}"
                full_url = base + "#" + fragment
            else:
                full_url = base
            requests.get(full_url, headers={
                "User-Agent": CYY_APP_USER_AGENT,
                "Accept-Language": "zh-Hans-CN;q=1",
            }, timeout=15)
            _print(f"  [*] 已打开文章页: {full_url[:120]}")
        except Exception as exc:
            _print(f"  [warn] 文章页访问失败: {exc}")
    _print(f"  [*] 阅读文章 {need} 秒 (action={action})...")
    step = 10
    while need > 0:
        sleep(min(step, need))
        need -= step
        _print(f"  [*] 已阅读, 剩余约 {max(need, 0)} 秒")


# ── 滑块验证码 ──


def pure_aes_cbc_encrypt(plaintext: bytes) -> bytes:
    """纯 python AES-256-CBC（无 pycryptodome 时兜底，兼容 CryptoJS）"""
    SBOX = [
        0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
        0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
        0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
        0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
        0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
        0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
        0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
        0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
        0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
        0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
        0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
        0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
        0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
        0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
        0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
        0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
    ]
    RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]

    def _xtime(a):
        a = (a << 1) & 0xFF
        return a ^ 0x1B if a & 0x100 else a

    def _expand_key(key):
        nk, nr = 8, 14
        w = [[key[4*i+j] for j in range(4)] for i in range(nk)]
        for i in range(nk, 4*(nr+1)):
            temp = w[i-1][:]
            if i % nk == 0:
                temp = temp[1:] + temp[:1]
                temp = [SBOX[b] for b in temp]
                temp[0] ^= RCON[i//nk - 1]
            elif nk > 6 and i % nk == 4:
                temp = [SBOX[b] for b in temp]
            w.append([w[i-nk][j] ^ temp[j] for j in range(4)])
        return w

    def _block_encrypt(block, w):
        state = [[block[4*j+i] for j in range(4)] for i in range(4)]
        def ark(r):
            for i in range(4):
                for j in range(4):
                    state[i][j] ^= w[r*4+j][i]
        def sb():
            for i in range(4):
                for j in range(4):
                    state[i][j] = SBOX[state[i][j]]
        def sr():
            for i in range(1, 4):
                state[i] = state[i][i:] + state[i][:i]
        def mc():
            for j in range(4):
                col = [state[i][j] for i in range(4)]
                state[0][j] = _xtime(col[0]) ^ (_xtime(col[1]) ^ col[1]) ^ col[2] ^ col[3]
                state[1][j] = col[0] ^ _xtime(col[1]) ^ (_xtime(col[2]) ^ col[2]) ^ col[3]
                state[2][j] = col[0] ^ col[1] ^ _xtime(col[2]) ^ (_xtime(col[3]) ^ col[3])
                state[3][j] = (_xtime(col[0]) ^ col[0]) ^ col[1] ^ col[2] ^ _xtime(col[3])
        w = _expand_key(CAPTCHA_AES_KEY)
        ark(0)
        for rnd in range(1, 14):
            sb(); sr(); mc(); ark(rnd)
        sb(); sr(); ark(14)
        return b"".join(bytes([state[i][j] for j in range(4)]) for i in range(4))

    pad_len = 16 - (len(plaintext) % 16)
    data = plaintext + bytes([pad_len]) * pad_len
    w = _expand_key(CAPTCHA_AES_KEY)
    out = b""
    iv = CAPTCHA_AES_IV
    for i in range(0, len(data), 16):
        block = bytes(data[i+j] ^ iv[j] for j in range(16))
        enc = _block_encrypt(block, w)
        out += enc
        iv = enc
    return out


def solve_captcha(account: str, headers: Dict[str, str]) -> str:
    """自动滑块验证码求解：返回 afs_tokenid
    逆向自前端 yundian-slide-captcha 组件：
      _captcha_get -> 拼图缺口识别 -> _captcha_check -> intelverifcode_check
    """
    if not HAS_PIL:
        raise RuntimeError("需要 pillow/numpy 才能自动求解滑块(pip install pillow numpy)")

    def _aes_cbc_encrypt(plaintext: bytes) -> bytes:
        if HAS_CRYPTO:
            cipher = AES.new(CAPTCHA_AES_KEY, AES.MODE_CBC, CAPTCHA_AES_IV)
            return cipher.encrypt(pad(plaintext, 16))
        return pure_aes_cbc_encrypt(plaintext)

    def _aes_encrypt_b64(obj: Any, url_quote: bool = False) -> str:
        text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        value = base64.b64encode(_aes_cbc_encrypt(text)).decode()
        return quote(value) if url_quote else value

    def _captcha_random_string(n: int) -> str:
        alphabet = "twxyz2345678"
        return "".join(random.choice(alphabet) for _ in range(n))

    def _find_gap(bg_img: Any, block_img: Any) -> Tuple[int, int, Any]:
        """返回缺口左上角 x（自然像素坐标）：NCC 模板匹配 + 亮度低谷"""
        bg = np.asarray(bg_img.convert("RGB"), dtype=np.float64)
        rgba = np.asarray(block_img.convert("RGBA"), dtype=np.float64)
        alpha = rgba[:, :, 3:4] / 255.0
        piece = rgba[:, :, :3]
        bw = rgba.shape[1]
        h, width = bg.shape[0], bg.shape[1]
        scores = []
        for x in range(0, width - bw + 1):
            win = bg[:, x:x + bw]
            m = alpha
            num = (m * piece * win).sum()
            d1 = (m * piece * piece).sum()
            d2 = (m * win * win).sum()
            scores.append(num / math.sqrt(d1 * d2) if d1 > 0 and d2 > 0 else 0.0)
        x_max = int(np.argmax(scores))
        colmean = bg.mean(axis=(0, 2))
        from numpy.lib.stride_tricks import sliding_window_view
        sw = sliding_window_view(colmean, min(bw, 20)).mean(axis=1)
        x_bright = int(np.argmin(sw))
        return x_max, x_bright, scores

    def _build_track(target_x: float, width: int) -> List[Dict[str, Any]]:
        """生成类人手拖拽轨迹：每 100ms 采样，长度 <= 100"""
        track = []
        x = 0.0
        accel = random.uniform(1.4, 1.8)
        decel_start = target_x * 0.72
        while x < target_x - 0.5 and len(track) < 99:
            if x < decel_start:
                v = accel + random.uniform(-0.2, 0.2)
                x += v * 1.0
            else:
                x += max(0.2, accel * (target_x - x) / (target_x - decel_start + 1)) + random.uniform(-0.15, 0.15)
            track.append({"x": round(x, 1), "y": 0, "time": 100})
        if track:
            track[-1]["x"] = target_x
        else:
            track.append({"x": target_x, "y": 0, "time": 100})
        return track

    referer = CYY_H5_DOMAIN + "/module-study/pass-detail/pass-detail"
    now = int(time.time())
    params = {"once": _captcha_random_string(10), "referer": referer,
              "timestamp": now, "type": "1"}
    sig = _aes_encrypt_b64(params, url_quote=True)
    url = CAPTCHA_GET_URL + "?" + urlencode({
        "once": params["once"], "referer": referer,
        "timestamp": now, "type": "1", "signature": sig})

    get_resp = api_get(account, url, headers)
    if get_resp.get("code") not in ("0", 0):
        raise RuntimeError("获取验证码失败: %s" % json_preview(get_resp, 300))
    data = get_resp.get("data") or {}
    token = data.get("token")
    bg_url = data.get("background")
    blk_url = data.get("block")
    if not token or not bg_url or not blk_url:
        raise RuntimeError("验证码数据不完整: %s" % json_preview(data, 300))

    session = requests.Session()
    bg = Image.open(BytesIO(session.get(bg_url, timeout=REQUEST_TIMEOUT).content))
    blk = Image.open(BytesIO(session.get(blk_url, timeout=REQUEST_TIMEOUT).content))

    x_max, x_bright, scores = _find_gap(bg, blk)
    bg_w = bg.width
    candidates = [("ncc_max", x_max), ("bright_min", x_bright),
                  ("ncc_min", int(np.argmin(scores)))]
    for name, x in candidates:
        if x + 60 > bg_w - 1:
            continue
        _print(f"    [*] 尝试 {name}: x={x}")
        track = _build_track(x, bg_w)
        payload = {"x": x, "width": bg_w, "track": track}
        enc = _aes_encrypt_b64(payload)
        check_body = {"token": token, "data": enc,
                      "referer": referer, "type": "1"}
        check_resp = api_post(account, CAPTCHA_CHECK_URL, headers, check_body)
        if check_resp.get("code") in ("0", 0) and safe_data(check_resp).get("result"):
            validate = safe_data(check_resp).get("token") or ""
            _print(f"    [OK] 滑块验证通过, validate={mask(validate)}")
            verify_resp = api_post(account, CAPTCHA_VERIFY_URL, headers, {
                "validate": validate, "verif_type": 3,
                "afs_uuid": "", "source": "yundian"})
            if verify_resp.get("code") in ("0", 0):
                tokenid = safe_data(verify_resp).get("tokenid") or ""
                _print(f"    [OK] 智能验证通过, afs_tokenid={mask(tokenid)}")
                return str(tokenid)
            _print(f"    [warn] intelverifcode_check: {json_preview(verify_resp, 200)}")
        else:
            _print(f"    [x] {check_resp.get('msg') or json_preview(check_resp, 200)}")
    raise RuntimeError("全部候选位置验证失败")


# ── 业务逻辑 ──


def do_signin(account: str, headers: Dict[str, str]) -> str:
    if CYY_NO_SIGNIN:
        _print("⏭️ [签到] 已配置 CYY_NO_SIGNIN=1，跳过签到")
        return "跳过签到"

    try:
        times_resp = signin_times(account, headers)
        if times_resp.get("code") in ("0", 0):
            remain = safe_data(times_resp).get("day_remain")
            _print(f"📅 [签到] 签到次数查询: day_remain={remain}")
            if not remain:
                _print("📅 [签到] day_remain=0 (可能已签), 尝试签到...")
    except Exception as exc:
        _print(f"⚠️ [签到] 签到次数查询失败(可忽略): {exc}")

    sign_resp = signin(account, headers)
    if sign_resp.get("code") in ("0", 0):
        data = safe_data(sign_resp)
        msg = f"签到成功! 金币+{data.get('gold')} (第{data.get('times')}次)"
        _print(f"✅ [签到] {msg}")
        return msg
    if str(sign_resp.get("code")) == "1007" or "已签到" in str(sign_resp.get("msg", "")):
        msg = "今日已签到"
        _print(f"📅 [签到] {msg}")
        return msg
    msg = sign_resp.get("msg") or sign_resp.get("message") or "签到失败"
    _print(f"⚠️ [签到] {msg}")
    return msg


def do_tasks(
    account: str,
    app_user_token: str,
    access_api_dt: str,
    headers: Dict[str, str],
    member_id: int,
) -> str:
    opt_resp = get_optionp_list(account, headers)
    if opt_resp.get("code") not in ("0", 0):
        _print(f"⚠️ [任务] 获取任务活动失败: {opt_resp.get('msg') or json_preview(opt_resp, 300)}")
        return "获取任务活动失败"

    opts = opt_resp.get("data") or []
    if not isinstance(opts, list) or not opts:
        _print("⚠️ [任务] 当前没有进行中的任务活动")
        return "无任务活动"

    opt = opts[0]
    opt_id = opt.get("id")
    module_id = opt.get("m_id") or CYY_MODULE_ID
    _print(f"🎯 [任务] 任务活动: {opt.get('title')} "
          f"(option_id={opt_id}, 任务数={opt.get('task_num')})")

    try:
        detail_resp = get_optionp_detail(account, headers, opt_id)
        if detail_resp.get("code") in ("0", 0):
            detail = safe_data(detail_resp)
            done_n = detail.get("user_done_num") or 0
            undone_n = detail.get("user_undone_num") or 0
            _print(f"📊 [任务] 今日已完成 {done_n}/{done_n + undone_n}")
    except Exception as exc:
        _print(f"⚠️ [任务] 任务详情查询失败(可忽略): {exc}")

    tasks_resp = get_task_list(account, headers, module_id, opt_id)
    if tasks_resp.get("code") not in ("0", 0):
        _print(f"⚠️ [任务] 获取任务列表失败: {tasks_resp.get('msg') or json_preview(tasks_resp, 300)}")
        return "获取任务列表失败"

    tasks = tasks_resp.get("data") or []
    if not isinstance(tasks, list):
        return "任务列表为空"
    undone = [t for t in tasks if not t.get("user_done")]
    _print(f"📋 [任务] 共 {len(tasks)} 个任务, 未完成 {len(undone)} 个")
    if not undone:
        _print("✅ [任务] 今日任务已全部完成, 收工")
        return "今日任务已全部完成"

    limit = CYY_MAX_TASKS or len(undone)
    done_count = 0
    total_gold = 0
    for idx, task in enumerate(undone[:limit], 1):
        task_id = task.get("id")
        title = task.get("title") or ""
        _print(f"\n[+] 任务 #{task_id}: {title}")
        try:
            rule = task.get("rule") or {}
            if isinstance(rule, str):
                rule = json.loads(rule)
        except Exception:
            rule = {}

        # 1. 创建任务
        record_id = ""
        try:
            created = task_create(account, headers, task_id)
            record_id = safe_data(created).get("task_record_id") or ""
            _print(f"  任务记录: {record_id}")
        except Exception as exc:
            _print(f"⚠️ [任务] 任务创建失败: {exc}")
            continue

        # 2. 阅读足迹打卡
        info = parse_rule(rule)
        if info.get("article_id"):
            try:
                footprint = add_foot_print(account, app_user_token, member_id,
                                          info["article_id"], info.get("title") or title,
                                          info.get("news_url", ""))
                if footprint.get("code") == 200:
                    _print(f"  打卡成功 footprint_id={safe_data(footprint).get('footprint_id') or '-'}")
                else:
                    _print(f"  打卡: {footprint.get('msg') or json_preview(footprint, 200)} (可忽略)")
            except Exception as exc:
                _print(f"⚠️ [任务] 打卡失败: {exc}")

        # 3. 模拟阅读
        simulate_read(rule, app_user_token, member_id, get_read_seconds())

        # 4. 上报阅读完成（60秒倒计时信号）
        if info.get("article_id"):
            try:
                reading_resp = complete_reading(account, app_user_token, member_id, info["article_id"])
                if reading_resp.get("code") == 200:
                    _print("  阅读完成上报成功")
                else:
                    _print(f"  阅读完成上报: {reading_resp.get('msg') or json_preview(reading_resp, 200)} (可忽略)")
            except Exception as exc:
                _print(f"⚠️ [任务] 阅读完成上报失败: {exc}")

        # 5. 刷新 access_token 后一次提交（服务端限制每个 access_token 仅支持一枚滑块验证码）
        if not record_id:
            _print("  [OK] 无任务记录, 阅读打卡完成视为任务完成")
            done_count += 1
            continue

        _print("  [*] 刷新 access_token, 获取本任务滑块验证码")
        try:
            access_token, user_id = appuser_init(account, app_user_token)
            fresh_headers = iyunxh_headers(access_token, user_id, access_api_dt)
        except Exception as exc:
            _print(f"⚠️ [任务] 刷新 access_token 失败: {exc}")
            continue

        try:
            tokenid = solve_captcha(account, fresh_headers)
        except Exception as exc:
            _print(f"⚠️ [任务] 自动破解失败: {exc}")
            tokenid = ""

        if not tokenid:
            _print("⚠️ [任务] 自动验证失败, 跳过该任务")
            continue

        done_resp = task_done(account, fresh_headers, record_id, tokenid)
        if done_resp.get("code") in ("0", 0):
            done_data = safe_data(done_resp)
            option = done_data.get("option") or {}
            goods_title = option.get("goods_title") or ""
            # 从 goods_title 提取金币数，格式如 "金币:5" / "金币:10"
            gold_match = re.search(r"金币[:：]?\s*(\d+)", goods_title)
            task_gold = int(gold_match.group(1)) if gold_match else 0
            total_gold += task_gold
            reward_desc = goods_title or option.get("title") or "-"
            if task_gold:
                _print(f"  [OK] 完成任务! 奖励: {reward_desc} 金币+{task_gold}")
            else:
                _print(f"  [OK] 完成任务! 奖励: {reward_desc}")
            done_count += 1
        else:
            _print(f"⚠️ [任务] 任务完成失败: {done_resp.get('msg') or json_preview(done_resp, 300)}")

    _print(f"\n✅ [任务] 完成 {done_count}/{min(limit, len(undone))} 个任务, 获得金币 {total_gold}")
    return f"完成 {done_count} 个任务, 获得金币 {total_gold}"


# ── 主流程 ──


def run_account(index: int, total: int, account_str: str) -> Dict[str, Any]:
    parts = account_str.split("#", 1)
    account = parts[0]
    password = parts[1] if len(parts) > 1 else ""

    result = {
        "account": account,
        "success": False,
        "token": "-",
        "signMsg": "-",
        "tasksMsg": "-",
        "goldMsg": "-",
        "error": "",
    }

    log_account_header(index, total, account)

    delay = random.randint(5, 10)
    _print(f"⏳ [延迟] 启动延迟 {delay}s")
    sleep(delay)

    token, raw_login = login_by_password(account, password)
    if not token:
        result["error"] = f"登录失败: {json_preview(raw_login)}"
        return result

    result["token"] = mask(token)
    member_id = extract_member_id(raw_login)

    try:
        access_api_dt = fetch_device_dt(account)
        access_token, user_id = appuser_init(account, token)
        headers = iyunxh_headers(access_token, user_id, access_api_dt)

        result["signMsg"] = do_signin(account, headers)
        result["tasksMsg"] = do_tasks(account, token, access_api_dt, headers, member_id)

        gold = get_gold(account, headers)
        result["goldMsg"] = str(gold)
        _print(f"💰 [金币] 当前金币: {gold}")

        result["success"] = True
        return result

    except Exception as exc:
        result["error"] = traceback.format_exc().strip()
        _print(f"❌ [账号] 执行失败: {exc}")
        return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for item in results if item and item["success"])
    fail_count = len(results) - success_count

    content = f"""## 草原云自动签到 + 每日阅读任务

**执行时间:** {now_text()}
**账号数量:** {len(results)}
**成功:** {success_count}
**失败:** {fail_count}

---

### 各账号详情

"""

    for idx, res in enumerate(results, 1):
        masked_phone = mask(res["account"])
        if res["success"]:
            content += f'#### 👤 账号 {idx}: {masked_phone}\n\n'
            content += f'**当前金币: {res["goldMsg"]}**\n\n'
            content += '| 任务 | 结果 |\n'
            content += '|------|------|\n'
            content += f'| 签到 | {res["signMsg"]} |\n'
            content += f'| 阅读任务 | {res["tasksMsg"]} |\n'
            content += '\n---\n\n'
        else:
            content += f'#### 👤 账号 {idx}: {masked_phone}\n\n❌ 执行失败\n\n'
            if res["error"]:
                content += f'```\n{res["error"]}\n```\n\n'
            content += '---\n\n'

    content += f'### � 总计\n\n**共 {len(results)} 个账号，成功 {success_count} 个，失败 {fail_count} 个**'

    return content


def main() -> None:
    log_title()

    total = len(CYY)
    if total == 0:
        _print("⚠️ [配置] 未配置任何账号，请设置环境变量 CYY（格式: 手机号#密码，多个用 & 分隔）")
        return
    results: List[Dict[str, Any]] = [None] * total

    with ThreadPoolExecutor(max_workers=total) as executor:
        futures = {}
        for index, account_str in enumerate(CYY, 1):
            future = executor.submit(run_account, index, total, account_str)
            futures[future] = index
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx - 1] = future.result()
            except Exception as exc:
                account_str = CYY[idx - 1]
                _print(f"❌ [主程序] {account_str} 执行异常: {exc}")
                results[idx - 1] = {
                    "account": account_str.split("#")[0] if "#" in account_str else account_str,
                    "success": False,
                    "token": "-",
                    "signMsg": "-",
                    "tasksMsg": "-",
                    "goldMsg": "-",
                    "error": traceback.format_exc().strip(),
                }

    success_count = sum(1 for item in results if item and item["success"])
    fail_count = total - success_count

    _print()
    _print("╔" + "═" * 50 + "╗")
    _print("║ 🏁 草原云任务执行完成                      ║")
    _print(f"║ ✅ 成功: {success_count:<39}║")
    _print(f"║ ❌ 失败: {fail_count:<39}║")
    _print(f"║ 🕒 结束时间: {now_text():<32}║")
    _print("╚" + "═" * 50 + "╝")

    send_pushplus("🌾 草原云任务完成", build_notify(results))


if __name__ == "__main__":
    main()
