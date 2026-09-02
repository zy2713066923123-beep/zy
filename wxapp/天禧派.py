#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
顾家家居/天赐派每日签到（自动拉取 yyb 账号）

账号来源：自动从 YYB Go 拉取存活账号（参考汤星球.py），无需手动配置 TXP_WXID。
可选环境变量:
  WX_ID / TXP_WXID   若配置则按此过滤账号；未配置则自动同步 yyb 全部存活账号
  WX_SERVER / YYB_SERVER / WECHAT_SERVER / YINGYONGBAO_SERVER  YYB 服务地址
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests


WX_APP_ID = "wx8e727b1591061cfa"
API_APP_ID = "877139"
APP_SECRET = "Ek7mTJRJEMTNbKjM"
APP_VERSION = "2.0.111"
BRAND_CODE = "K006"
API_BASE = "https://mc.kukahome.com"
REFERER = "https://servicewechat.com/wx8e727b1591061cfa/137/page-frame.html"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090c38)XWEB/14185"
)
ENV_NAME = "TXP_WXID"
NOTIFY_TITLE = "顾家家居签到"
TIMEOUT = 20
CACHE_FILE = Path(__file__).with_name(".txp_kuka_token_cache.json")


class ScriptError(Exception):
    """脚本级错误。"""


class KukaApiError(ScriptError):
    def __init__(self, message: str, auth_failed: bool = False) -> None:
        super().__init__(message)
        self.auth_failed = auth_failed


def log(message: str) -> None:
    print(message, flush=True)


# ============ 复用 yyb 统一协议库（端点 fallback / 频率控制 / 账号解析） ============
try:
    import yyb
    _raw_server = (
        os.getenv("WX_SERVER")
        or os.getenv("YYB_SERVER")
        or os.getenv("WECHAT_SERVER")
        or os.getenv("YINGYONGBAO_SERVER")
        or ""
    ).strip().rstrip("/")
    if _raw_server:
        os.environ["WX_SERVER"] = _raw_server
        os.environ["YYB_SERVER"] = _raw_server
        os.environ["WECHAT_SERVER"] = _raw_server
    _yyb_client = yyb.YYBClient(_raw_server or None)
    log(f"已加载 yyb 协议库 @ {_yyb_client.server_url}")
except Exception as _e:
    _yyb_client = None
    log(f"加载 yyb 协议库失败: {_e}")


def json_response(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception as exc:
        raise ScriptError(f"响应不是 JSON: HTTP {response.status_code}") from exc


def response_message(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("message", "msg", "Message", "errmsg", "errorMsg", "error"):
            value = data.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def response_data(data: Any) -> Any:
    if isinstance(data, dict):
        for key in ("data", "Data", "result", "Result"):
            if key in data:
                return data[key]
    return data


def is_success(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    code = data.get("code", data.get("Code"))
    success = data.get("success", data.get("Success"))
    if code is not None:
        return code in (0, "0", 200, "200")
    if success is not None:
        return success in (True, 1, "1", "true", "True")
    return True


# ============ YYB Go 协议（复用 yyb 库，自动拉取存活账号） ============
def _fetch_yyb_accounts() -> List[Dict[str, Any]]:
    """从 YYB 拉取存活账号列表（复用 yyb 库的端点 fallback 与解析）。

    优先走 yyb.load_accounts()（内部会优先使用 WX_ID / TXP_WXID 环境变量过滤，
    未配置时自动同步 yyb_go 存活账号），返回账号 dict 列表。
    """
    if not _yyb_client:
        return []
    try:
        accs = yyb.load_accounts(ENV_NAME)
        if accs:
            return accs
        accs = _yyb_client.get_online_accounts()
        if accs:
            return accs
        accs = _yyb_client.get_accounts(force_refresh=True)
        if accs:
            log("get_online_accounts 过滤后为空，改用 get_accounts 全量账号")
            return accs
    except Exception as e:
        log(f"YYB 拉取账号异常: {e}")
    return []


def _get_code_yyb(wxid: str) -> Optional[str]:
    """通过 YYB 协议获取微信 code（复用 yyb 库，自动处理 openid/appid 与 fallback）"""
    if not _yyb_client:
        return None
    try:
        return _yyb_client.get_code(wxid, WX_APP_ID)
    except Exception as e:
        log(f"YYB getCode 异常: {e}")
        return None


class TokenCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: Dict[str, Dict[str, Any]] = self.load()

    @staticmethod
    def key(protocol: str, account: str) -> str:
        return f"{protocol}:{account}"

    def load(self) -> Dict[str, Dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def get(self, protocol: str, account: str) -> Optional[Dict[str, Any]]:
        item = self.data.get(self.key(protocol, account))
        if (
            isinstance(item, dict)
            and item.get("protocol") == protocol
            and item.get("account") == account
            and str(item.get("access_token") or "").strip()
            and str(item.get("member_id") or "").strip()
        ):
            return item
        return None

    def delete(self, protocol: str, account: str) -> None:
        self.data.pop(self.key(protocol, account), None)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def set(self, protocol: str, account: str, token: str, member_id: str) -> None:
        self.data[self.key(protocol, account)] = {
            "protocol": protocol,
            "account": account,
            "access_token": token,
            "member_id": member_id,
            "updated_at": int(time.time()),
        }
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


def sorted_parameter_string(data: Any) -> str:
    if not isinstance(data, dict) or not data:
        return ""
    pairs: List[Tuple[str, Any]] = []
    for key in sorted(data, key=lambda value: [ord(char) for char in str(value)]):
        value = data[key]
        if value is None or value == "" or value == [] or value == {}:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        pairs.append((str(key), value))
    return "&".join(f"{key}={value}" for key, value in pairs)


def parameter_sign(data: Any, timestamp: int) -> str:
    plain = sorted_parameter_string(data)
    if not plain:
        return ""
    first = hashlib.md5(plain.encode()).hexdigest()
    return hashlib.md5((first + str(timestamp)[4:10]).encode()).hexdigest()


class KukaClient:
    def __init__(self, access_token: str = "", member_id: str = "", tmp_token: str = "") -> None:
        self.session = requests.Session()
        self.access_token = access_token
        self.member_id = member_id
        self.tmp_token = tmp_token

    def headers(self, data: Any = None) -> Dict[str, str]:
        timestamp = int(time.time() * 1000)
        result = {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
            "versionNumber": APP_VERSION,
            "timestamp": str(timestamp),
            "brandCode": BRAND_CODE,
            "appid": API_APP_ID,
            "sign": hashlib.md5(f"{API_APP_ID}{APP_SECRET}{timestamp}".encode()).hexdigest(),
            "AccessToken": self.access_token,
            "X-Customer": self.member_id,
            "tmpToken": self.tmp_token,
        }
        sign = parameter_sign(data, timestamp)
        if sign:
            result["parameterSign"] = sign
        return result

    def request(self, method: str, path: str, data: Any = None) -> Any:
        response = self.session.request(
            method,
            API_BASE + path,
            json=data if method.upper() != "GET" else None,
            headers=self.headers(data),
            timeout=TIMEOUT,
        )
        result = json_response(response)
        if response.status_code >= 400:
            raise KukaApiError(f"HTTP {response.status_code}: {response_message(result) or '请求失败'}", response.status_code in (401, 403))
        code = result.get("code", result.get("Code")) if isinstance(result, dict) else None
        if code in (401, "401", 403, "403"):
            raise KukaApiError(response_message(result) or f"接口鉴权失败: {code}", True)
        if not is_success(result):
            raise KukaApiError(response_message(result) or "接口返回失败")
        return result

    def identify(self, code: str) -> Dict[str, Any]:
        response = self.session.post(
            f"{API_BASE}/club-server/api/user/identify?code={quote(code, safe='')}",
            json={},
            headers=self.headers({}),
            timeout=TIMEOUT,
        )
        result = json_response(response)
        if response.status_code >= 400 or not is_success(result):
            raise KukaApiError(response_message(result) or "顾家登录识别失败")
        data = response_data(result)
        if not isinstance(data, dict):
            raise ScriptError("顾家登录识别未返回有效数据")
        return data

    def authorize_login(self, tmp_token: str) -> Dict[str, Any]:
        self.tmp_token = tmp_token
        result = self.request(
            "POST",
            "/club-server/api/user/authorizeLogin",
            {"source": "顾家小程序", "contentName": ""},
        )
        data = response_data(result)
        if not isinstance(data, dict):
            raise ScriptError("顾家授权登录未返回有效数据")
        return data

    def calendar(self) -> Dict[str, Any]:
        result = self.request("GET", "/integral-server/user/sign/calendar")
        data = response_data(result)
        return data if isinstance(data, dict) else {}

    def sign(self) -> Any:
        result = self.request(
            "POST",
            "/integral-server/scenePoint/scene/point",
            {"scene": "sign", "brandCode": BRAND_CODE},
        )
        return response_data(result)

    def user_info(self) -> Dict[str, Any]:
        result = self.request("POST", "/club-server/api/user/info", {})
        data = response_data(result)
        return data if isinstance(data, dict) else {}


def login(
    cache: TokenCache,
    account: str,
) -> KukaClient:
    """通过 YYB 取码登录，带本地 token 缓存（自动续期）。"""
    cached = cache.get("yyb", account)
    if cached:
        client = KukaClient(str(cached.get("access_token") or ""), str(cached.get("member_id") or ""))
        try:
            client.calendar()
            log("使用缓存登录")
            return client
        except KukaApiError as exc:
            if not exc.auth_failed:
                raise
            cache.delete("yyb", account)
        except Exception as exc:
            raise ScriptError(f"缓存登录校验失败，未获取新的 code: {exc}") from exc

    code = _get_code_yyb(account)
    if not code:
        raise ScriptError("YYB 获取 code 失败")
    client = KukaClient()
    identified = client.identify(code)
    status = str(identified.get("status") or "")
    tmp_token = str(identified.get("token") or "")
    if status != "4":
        raise ScriptError(f"账号尚未完成顾家会员授权(status={status})，无法自动登录")

    authorized = client.authorize_login(tmp_token)
    token = str(authorized.get("token") or "")
    member_id = str(authorized.get("memberId") or "")
    if not token or not member_id:
        raise ScriptError("顾家授权登录未返回 token/memberId")
    client.access_token = token
    client.member_id = member_id
    cache.set("yyb", account, token, member_id)
    return client


def send_notify(content: str) -> None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from notify import send

        send(NOTIFY_TITLE, content)
    except Exception as exc:
        log(f"通知发送失败: {exc}")


def run_one(
    index: int,
    total: int,
    acc: Dict[str, Any],
    cache: TokenCache,
) -> str:
    wxid = str(acc.get("id") or acc.get("openid") or acc.get("wxid") or "").strip()
    display = acc.get("remark") or acc.get("nickname") or acc.get("alias") or wxid or f"账号{index}"
    log(f"\n====== 账号 {index}/{total}: {display} ======")
    if not wxid:
        return f"{display}: 跳过，无有效账号标识"

    client = login(cache, wxid)
    calendar = client.calendar()
    member_id = str(calendar.get("memberId") or client.member_id or "")
    nickname = display
    if member_id:
        client.member_id = member_id
    today_signed = bool(calendar.get("isTodaySigned"))
    if today_signed:
        result = f"{display}: 今日已签到，连续签到 {calendar.get('signCount', 0)} 天"
        log(result)
        return result

    reward = client.sign()
    if reward in (None, 0, "0", False):
        raise ScriptError("签到接口返回未成功")
    after = client.calendar()
    if not after.get("isTodaySigned"):
        raise ScriptError("签到接口返回成功，但复查未显示今日已签到")
    result = f"{nickname}: 签到成功，获得 {reward} 积分，连续签到 {after.get('signCount', 0)} 天"
    log(result)
    return result


def main() -> None:
    if not _yyb_client:
        log("yyb 协议库未加载，无法拉取账号")
        return
    accounts = _fetch_yyb_accounts()
    if not accounts:
        log("YYB 未拉取到存活账号")
        return

    cache = TokenCache(CACHE_FILE)
    summaries: List[str] = []
    log(f"顾家家居签到开始，自动拉取 yyb 存活账号，账号数: {len(accounts)}")
    for index, acc in enumerate(accounts, 1):
        try:
            summaries.append(run_one(index, len(accounts), acc, cache))
        except Exception as exc:
            display = acc.get("remark") or acc.get("nickname") or acc.get("alias") or acc.get("id") or f"账号{index}"
            message = f"{display}: 失败，{exc}"
            log(message)
            summaries.append(message)
        if index < len(accounts):
            time.sleep(2)

    content = "\n\n".join(summaries)
    log("\n====== 汇总 ======\n" + content)
    send_notify(content)


if __name__ == "__main__":
    main()
