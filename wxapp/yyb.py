# name: YYB-Go 微信全能力通用工具库 (Python SDK) —— 统一入口
"""
yyb-go 微信协议通用工具库 (Python SDK) —— 统一入口

这是 wxapp 下所有脚本统一引用的唯一工具库。完整封装 yyb-go 服务端提供的
所有微信小程序/公众号/云托管能力：
  1. 账号管理: 存活账号发现、WX_ID 筛选、状态检测
  2. 小程序核心: wx.login 取码、手机号授权(code/encrypted_data/iv/phone)、用户信息(getUserInfo)
  3. 加密与安全: 用户加密密钥(webapi_get_encrypt_key)、数据签名、微信步数(getWeRunData)
  4. 云开发与托管: 云函数(cloud_call_function)、云托管容器(cloud_call_container)
  5. 公众号网页授权: OAuth2 授权码换取(oauth_authorize/oauth_confirm)
  6. 云托管 GatewayV3: Gateway 鉴权与微服务调用(gateway_v3_mint/gateway_v3_call)

使用方式（所有脚本统一引用本文件即可）：
  import yyb
  code = yyb.get_single_code(APPID, wxid)

环境变量配置（只需一个 WX_SERVER 即可）：
  WX_SERVER: yyb-go 服务端地址（默认 http://127.0.0.1:8000），兼容 YYB_SERVER / WECHAT_SERVER
  WX_ID:     可选，账号过滤白名单（支持 id / openid / wxid，多个用换行或 & 分隔，支持 #备注）
"""

import os
import time
import requests
import json
import re
import builtins
from typing import List, Dict, Tuple, Optional, Literal, Any, Union

# ============================================================
# 1. 服务地址与常量定义
# ============================================================

def get_global_server_url() -> str:
    return (
        os.getenv("WX_SERVER") or
        os.getenv("YYB_SERVER") or
        os.getenv("WECHAT_SERVER") or
        os.getenv("YINGYONGBAO_SERVER") or
        "http://127.0.0.1:8000"
    ).rstrip("/")

LOGIN_TYPE_WX = "WX"
LOGIN_TYPE_SYZS = "SYZS"
LOGIN_TYPE_WMPF = "WMPF"

LOGIN_TYPE_ALIASES = {
    "": LOGIN_TYPE_WX,
    "wx": LOGIN_TYPE_WX,
    "yyb": LOGIN_TYPE_WX,
    "应用宝": LOGIN_TYPE_WX,
    "syzs": LOGIN_TYPE_SYZS,
    "手游助手": LOGIN_TYPE_SYZS,
    "wmpf": LOGIN_TYPE_WMPF,
    "微信小程序": LOGIN_TYPE_WMPF,
    "小程序": LOGIN_TYPE_WMPF,
}

LOGIN_TYPE_LABELS = {
    LOGIN_TYPE_WX: "应用宝",
    LOGIN_TYPE_SYZS: "手游助手",
    LOGIN_TYPE_WMPF: "微信小程序",
}

def normalize_login_type(value: Any) -> str:
    key = str(value or "").strip().lower()
    return LOGIN_TYPE_ALIASES.get(key, LOGIN_TYPE_WX)

def login_type_label(value: Any) -> str:
    lt = normalize_login_type(value)
    return LOGIN_TYPE_LABELS.get(lt, lt)

# ============================================================
# 2. 账号标识解析 (Identifier Parser)
# ============================================================

IDENTIFIER_SCHEMES = {
    "yyb": LOGIN_TYPE_WX,
    "wx": LOGIN_TYPE_WX,
    "syzs": LOGIN_TYPE_SYZS,
    "wmpf": LOGIN_TYPE_WMPF,
}

def parse_identifier(identifier: str) -> Dict[str, Any]:
    text = str(identifier or "").strip()
    scheme = ""
    login_type = None
    body = text

    colon_idx = text.find(":")
    if colon_idx > 0:
        key = text[:colon_idx].strip().lower()
        if key in IDENTIFIER_SCHEMES:
            scheme = key
            login_type = IDENTIFIER_SCHEMES[key]
            body = text[colon_idx + 1:].strip()

    raw_id = body
    remark = ""
    hash_idx = body.find("#")
    if hash_idx >= 0:
        raw_id = body[:hash_idx].strip()
        remark = body[hash_idx + 1:].strip()

    return {
        "scheme": scheme,
        "login_type": login_type,
        "raw_id": raw_id,
        "remark": remark,
        "original": text,
    }

def strip_scheme(identifier: str) -> str:
    return parse_identifier(identifier)["raw_id"]

# ============================================================
# 3. 通用 HTTP 客户端封装 (YYBClient)
# ============================================================

class YYBClient:
    def __init__(self, server_url: Optional[str] = None, timeout: int = 30):
        self.server_url = (server_url or get_global_server_url()).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._cached_accounts = None
        self._cache_time = 0

    def _request(self, method: str, endpoint: str, json_data: Any = None, params: Any = None) -> Any:
        url = f"{self.server_url}{'' if endpoint.startswith('/') else '/'}{endpoint}"
        try:
            resp = self.session.request(
                method=method.upper(),
                url=url,
                json=json_data,
                params=params,
                timeout=self.timeout,
            )
            if resp.status_code == 404:
                try:
                    data = resp.json()
                    msg = data.get("msg") or data.get("error") or resp.text[:80]
                except Exception:
                    msg = resp.text[:80]
                raise Exception(f"[404] 接口或账号不存在: {msg}")
            if resp.status_code in (401, 409):
                raise Exception("账号登录态已失效，需在 yyb_go 中重新扫码")

            try:
                body = resp.json()
            except Exception:
                return resp.text

            if isinstance(body, dict):
                code = body.get("code")
                if code is not None and code != 0:
                    raise Exception(f"[{code}] {body.get('msg', json.dumps(body, ensure_ascii=False))}")
                return body.get("data") if "data" in body else body
            return body
        except Exception as e:
            raise Exception(f"[YYB-SDK] 请求 {endpoint} 失败: {e}")

    def _resolve_ref(self, ref: str, expect_login_type: Optional[str] = None) -> str:
        parsed = parse_identifier(ref)
        raw = parsed["raw_id"]
        target_lt = parsed["login_type"] or (normalize_login_type(expect_login_type) if expect_login_type else None)

        if raw.isdigit():
            return raw

        accounts = self.get_accounts()
        if not accounts:
            return raw

        candidates = [
            acc for acc in accounts
            if not target_lt or normalize_login_type(acc.get("login_type")) == target_lt
        ]
        pool = candidates or accounts

        # 精确匹配 openid / wxid / id
        for acc in pool:
            if acc.get("openid") == raw or acc.get("wxid") == raw or str(acc.get("id")) == raw:
                return str(acc.get("id"))

        # 再按备注(alias)/昵称匹配：WX_ID 里常写的是 "156" 这类备注而非 openid
        lower = raw.lower()
        for acc in pool:
            labels = [
                str(acc.get(k)).strip().lower()
                for k in ("alias", "remark", "nickname")
                if isinstance(acc.get(k), str) and acc.get(k).strip()
            ]
            if lower in labels:
                return str(acc.get("id"))

        # 若只有一个候选账号，默认使用它
        if len(pool) == 1:
            return str(pool[0].get("id"))

        return raw

    # ---------- 账号管理 ----------

    def get_accounts(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        now = time.time()
        if not force_refresh and self._cached_accounts is not None and now - self._cache_time < 5:
            return self._cached_accounts
        try:
            data = self._request("GET", "/accounts")
            if isinstance(data, list):
                lst = data
            elif isinstance(data, dict) and isinstance(data.get("data"), list):
                lst = data["data"]
            else:
                lst = []
            self._cached_accounts = lst
            self._cache_time = now
            return lst
        except Exception:
            return []

    def get_online_accounts(self) -> List[Dict[str, Any]]:
        accounts = self.get_accounts(force_refresh=True)
        valid = []
        # 黑名单：仅排除明确离线/失效的账号；其余（含空值、非标准值）均视为可用，避免误杀
        OFFLINE = {"offline", "expired", "invalid", "disabled", "error", "dead", "logout"}
        for acc in accounts:
            st = str(acc.get("status") or "").lower()
            if st in OFFLINE:
                continue
            valid.append(acc)
        return valid

    # ---------- 小程序核心能力 ----------

    def get_code(self, ref: str, app_id: str) -> str:
        """获取微信小程序登录 Code (wx.login)"""
        resolved_ref = self._resolve_ref(ref)
        res = self._request("POST", "/wxapp/getCode", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
        })
        code = None
        if isinstance(res, dict):
            code = res.get("code") or (res.get("result", {}).get("code") if isinstance(res.get("result"), dict) else None)
        elif isinstance(res, str):
            code = res
        if not code:
            raise Exception(f"未拿到有效小程序 code: {res}")
        return str(code)

    def get_codes(self, refs: List[str], app_id: str) -> Dict[str, Any]:
        """批量获取小程序 Code"""
        resolved_refs = [self._resolve_ref(r) for r in refs]
        return self._request("POST", "/wxapp/getCodes", json_data={
            "refs": resolved_refs,
            "app_id": app_id,
        })

    def get_phone_number(self, ref: str, app_id: str) -> Dict[str, Any]:
        """获取手机号授权数据 (getPhoneNumber)
        返回: { "code": ..., "mobile": ..., "masked_phone": ..., "encryptedData": ..., "iv": ..., "cloudId": ... }
        """
        resolved_ref = self._resolve_ref(ref)
        res = self._request("POST", "/wxapp/getPhoneNumber", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
        })
        inner = res.get("result") if isinstance(res, dict) and isinstance(res.get("result"), dict) else (res if isinstance(res, dict) else {})
        return {
            "code": str(inner.get("code")) if inner.get("code") else None,
            "mobile": inner.get("mobile"),
            "masked_phone": inner.get("masked_phone"),
            "encryptedData": inner.get("encryptedData") or inner.get("encrypted_data"),
            "iv": inner.get("iv") or inner.get("IV"),
            "cloudId": inner.get("cloudId"),
        }

    def get_phone_encrypted(self, ref: str, app_id: str) -> Dict[str, Any]:
        """获取手机号加密数据包 (兼容别名)"""
        return self.get_phone_number(ref, app_id)

    def operate_wx_data(self, ref: str, app_id: str, payload: Dict[str, Any]) -> Any:
        """通用 operateWxData 调用（支持用户密钥、云函数、基础库协议交互）"""
        resolved_ref = self._resolve_ref(ref)
        res = self._request("POST", "/wxapp/operateWxData", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
            "payload": payload or {},
        })
        if isinstance(res, dict) and "result" in res:
            return res["result"]
        return res

    def get_user_info(self, ref: str, app_id: str, lang: str = "zh_CN") -> Any:
        """获取用户信息 (getUserInfo)"""
        resolved_ref = self._resolve_ref(ref)
        return self._request("POST", "/wxapp/getUserInfo", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
            "lang": lang,
        })

    def get_user_encrypt_key(self, ref: str, app_id: str) -> Any:
        """获取用户加密密钥 (webapi_getuserencryptkey)"""
        return self.operate_wx_data(ref, app_id, {"api_name": "webapi_getuserencryptkey"})

    def get_we_run_data(self, ref: str, app_id: str) -> Any:
        """获取微信运动步数数据 (getWeRunData)"""
        resolved_ref = self._resolve_ref(ref)
        return self._request("POST", "/wxapp/getWeRunData", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
        })

    def get_setting(self, ref: str, app_id: str) -> Any:
        """获取小程序设置 (getSetting)"""
        resolved_ref = self._resolve_ref(ref)
        return self._request("POST", "/wxapp/getSetting", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
        })

    def get_system_info(self, ref: str, app_id: str) -> Any:
        """获取系统设备信息 (getSystemInfo)"""
        resolved_ref = self._resolve_ref(ref)
        return self._request("POST", "/wxapp/getSystemInfo", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
        })

    def get_location(self, ref: str, app_id: str, loc_type: str = "wgs84") -> Any:
        """获取地理位置 (getLocation)"""
        resolved_ref = self._resolve_ref(ref)
        return self._request("POST", "/wxapp/getLocation", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
            "type": loc_type,
        })

    # ---------- 云开发与云托管 ----------

    def cloud_call_function(self, ref: str, app_id: str, env: str, name: str, data: Dict[str, Any] = None) -> Any:
        """调用小程序云函数 (cloud.callFunction)"""
        resolved_ref = self._resolve_ref(ref)
        return self._request("POST", "/wxapp/cloud/function", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
            "env": env,
            "name": name,
            "data": data or {},
        })

    def cloud_call_container(self, ref: str, app_id: str, env: str, path: str, service: str, header: Dict[str, str] = None, body: Any = None) -> Any:
        """调用小程序云托管容器服务 (cloud.callContainer)"""
        resolved_ref = self._resolve_ref(ref)
        return self._request("POST", "/wxapp/cloud/container", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
            "env": env,
            "path": path,
            "service": service,
            "header": header or {},
            "body": body,
        })

    # ---------- 微信公众号网页授权 (OAuth2) ----------

    def oauth_authorize(self, ref: str, app_id: str, redirect_uri: str, scope: str = "snsapi_userinfo", state: str = "") -> Any:
        """公众号网页授权取 code"""
        resolved_ref = self._resolve_ref(ref)
        return self._request("POST", "/wxapp/oauth/authorize", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
            "url": redirect_uri,
            "scope": scope,
            "state": state,
        })

    def oauth_confirm(self, ref: str, app_id: str, oauth_url: str) -> Any:
        """确认公众号网页授权并提取重定向 URL"""
        resolved_ref = self._resolve_ref(ref)
        return self._request("POST", "/wxapp/oauth/confirm", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
            "oauth_url": oauth_url,
        })

    # ---------- 云托管 GatewayV3 加密接口 ----------

    def gateway_v3_mint(self, ref: str, app_id: str, env: str) -> Any:
        """生成 GatewayV3 鉴权 Token"""
        resolved_ref = self._resolve_ref(ref)
        return self._request("POST", "/wxapp/gateway/v3/mint", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
            "env": env,
        })

    def gateway_v3_call(self, ref: str, app_id: str, env: str, path: str, service: str, header: Dict[str, str] = None, body: Any = None) -> Any:
        """调用 GatewayV3 加密微服务接口"""
        resolved_ref = self._resolve_ref(ref)
        return self._request("POST", "/wxapp/gateway/v3/call", json_data={
            "ref": resolved_ref,
            "app_id": app_id,
            "env": env,
            "path": path,
            "service": service,
            "header": header or {},
            "body": body,
        })

# 别名兼容
WeChatCodeGetter = YYBClient
YYBAdapter = YYBClient
WechatAdapter = YYBClient

# ============================================================
# 4. 便捷导出函数 (直接 1 行调用)
# ============================================================

def load_accounts(filter_env_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """加载并过滤账号列表（支持从 yyb_go 服务端拉取存活账号，或按 WX_ID 过滤）"""
    client = YYBClient()
    online_accounts = client.get_online_accounts()

    custom_filter = (os.getenv(filter_env_name) if filter_env_name else None) or os.getenv("WX_ID")
    if not custom_filter or not custom_filter.strip():
        return online_accounts

    filter_targets = [parse_identifier(line) for line in re.split(r'[@&\n|]+', custom_filter) if line.strip()]
    matched = []
    for acc in online_accounts:
        acc_keys = [str(acc.get("id", "")), acc.get("openid", ""), acc.get("wxid", ""), acc.get("_ref", "")]
        acc_lt = normalize_login_type(acc.get("login_type"))
        for t in filter_targets:
            if t["raw_id"] in acc_keys:
                if t["login_type"] and acc_lt != t["login_type"]:
                    continue
                acc_copy = dict(acc)
                acc_copy["remark"] = t["remark"] or acc.get("nickname") or ""
                matched.append(acc_copy)
                break
    return matched

def get_accounts() -> List[Dict[str, Any]]:
    """获取存活账号列表"""
    return load_accounts()


def resolve_accounts(env_name: str = "") -> List[str]:
    """
    统一账号解析入口（所有脚本统一调用）：
    1) 若配置了 WX_ID（或指定 env 变量），按原格式解析为 wxid 列表；
    2) 否则自动从 yyb_go 拉取存活账号，返回 wxid 列表（openid/wxid/id）。
    无论哪种方式，统一的“拿 code”入口都是 yyb.YYBClient().get_code(ref, app_id)。
    """
    val = (os.getenv("WX_ID") or (os.getenv(env_name) if env_name else "") or "").strip()
    if val:
        return [str(v).split("#")[0].strip() for v in re.split(r"[\n&]+", val) if v.strip()]
    try:
        accs = load_accounts()
        if accs:
            # 优先返回自增 id（纯数字），保证 _resolve_ref 走 isdigit 分支直接命中，
            # 避免 openid/wxid 字段名或取值与 Go 端不一致导致 account not found。
            ids = [str(a.get("id")) for a in accs if a.get("id") is not None]
            if not ids:
                ids = [str(a.get("openid") or a.get("wxid") or a.get("id")) for a in accs if (a.get("openid") or a.get("wxid") or a.get("id"))]
            print(f"[yyb] 自动从 yyb_go 同步到 {len(ids)} 个存活账号")
            return ids
    except Exception as e:
        print(f"[yyb] 自动拉取账号失败: {e}")
    print("[yyb] 未配置 WX_ID，且 yyb_go 无存活账号")
    return []

def print_online_status():
    """打印当前在线账号状态"""
    client = YYBClient()
    accounts = client.get_online_accounts()
    print(f"\n[yyb-go] 当前有 {len(accounts)} 个账号在线 (@ {client.server_url}):")
    for idx, acc in enumerate(accounts, 1):
        name = acc.get("nickname") or acc.get("alias") or acc.get("wxid") or f"账号_{idx}"
        lt = login_type_label(acc.get("login_type"))
        print(f"  - [{lt}] {name} (id={acc.get('id')}, openid={acc.get('openid') or '无'})")

def get_wechat_codes(app_id: str) -> Dict[str, str]:
    """获取所有存活账号的 Code 字典"""
    client = YYBClient()
    accounts = load_accounts()
    codes = {}
    for i, acc in enumerate(accounts, 1):
        name = acc.get("remark") or acc.get("nickname") or acc.get("alias") or f"账号_{i}"
        ref = str(acc.get("id") or acc.get("openid") or acc.get("wxid"))
        try:
            code = client.get_code(ref, app_id)
            codes[name] = code
            print(f"[yyb] ✓ {name}: {code[:16]}...")
        except Exception as e:
            print(f"[yyb] ✗ {name}: {e}")
    return codes

def get_single_code(app_id: str, identifier: str) -> Optional[str]:
    """获取单个账号的小程序 Code (wx.login)"""
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.get_code(identifier, app_id)
    except Exception as e:
        print(f"[yyb] 获取 code 失败 ({identifier}): {e}")
        return None

def get_single_phone_number(app_id: str, identifier: str) -> Optional[str]:
    """获取单个账号的手机号授权 Code"""
    if not identifier:
        return None
    client = YYBClient()
    try:
        res = client.get_phone_number(identifier, app_id)
        return res.get("code")
    except Exception as e:
        print(f"[yyb] 获取手机号 code 失败 ({identifier}): {e}")
        return None

def get_single_phone_encrypted(app_id: str, identifier: str) -> Optional[Dict[str, Any]]:
    """获取单个账号的手机号加密数据包 (encryptedData, iv, code, mobile, cloudId)"""
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.get_phone_number(identifier, app_id)
    except Exception as e:
        print(f"[yyb] 获取手机号加密数据失败 ({identifier}): {e}")
        return None

def get_single_operate_wx_data(app_id: str, identifier: str, payload: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    """获取通用 operateWxData 数据（如 webapi_getuserencryptkey / 云函数 / 用户数据等）"""
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.operate_wx_data(identifier, app_id, payload or {"api_name": "webapi_getuserencryptkey"})
    except Exception as e:
        print(f"[yyb] 获取 operate 数据失败 ({identifier}): {e}")
        return None

def get_single_user_encrypt_key(app_id: str, identifier: str) -> Optional[Any]:
    """获取单个账号的加密密钥 (webapi_getuserencryptkey)"""
    return get_single_operate_wx_data(app_id, identifier, {"api_name": "webapi_getuserencryptkey"})

def get_single_user_info(app_id: str, identifier: str) -> Optional[Any]:
    """获取单个账号的用户信息 (getUserInfo)"""
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.get_user_info(identifier, app_id)
    except Exception as e:
        print(f"[yyb] 获取用户信息失败 ({identifier}): {e}")
        return None

def get_single_we_run_data(app_id: str, identifier: str) -> Optional[Any]:
    """获取单个账号的微信步数加密数据 (getWeRunData)"""
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.get_we_run_data(identifier, app_id)
    except Exception as e:
        print(f"[yyb] 获取微信步数失败 ({identifier}): {e}")
        return None

def get_single_cloud_function(app_id: str, identifier: str, env: str, name: str, data: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    """调用小程序云函数 (cloudCallFunction)"""
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.cloud_call_function(identifier, app_id, env, name, data or {})
    except Exception as e:
        print(f"[yyb] 调用云函数失败 ({name}): {e}")
        return None

def get_single_oauth_authorize(app_id: str, identifier: str, redirect_uri: str, scope: str = "snsapi_userinfo", state: str = "") -> Optional[Any]:
    """调用公众号网页授权 (OAuth2)"""
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.oauth_authorize(identifier, app_id, redirect_uri, scope, state)
    except Exception as e:
        print(f"[yyb] 公众号网页授权失败: {e}")
        return None

# ============================================================
# 5. 全局挂载到 builtins
# ============================================================

builtins.YYBClient = YYBClient
builtins.WeChatCodeGetter = WeChatCodeGetter
builtins.YYBAdapter = YYBAdapter
builtins.WechatAdapter = WechatAdapter
builtins.get_single_code = get_single_code
builtins.get_single_phone_number = get_single_phone_number
builtins.get_single_phone_encrypted = get_single_phone_encrypted
builtins.get_single_operate_wx_data = get_single_operate_wx_data
builtins.get_single_user_encrypt_key = get_single_user_encrypt_key
builtins.get_single_user_info = get_single_user_info
builtins.get_single_we_run_data = get_single_we_run_data
builtins.get_single_cloud_function = get_single_cloud_function
builtins.get_single_oauth_authorize = get_single_oauth_authorize
builtins.load_accounts = load_accounts
builtins.resolve_accounts = resolve_accounts
builtins.get_accounts = get_accounts
builtins.get_wechat_codes = get_wechat_codes
builtins.print_online_status = print_online_status
builtins.parse_identifier = parse_identifier
builtins.strip_scheme = strip_scheme
builtins.normalize_login_type = normalize_login_type
builtins.login_type_label = login_type_label

__all__ = [
    "YYBClient",
    "WeChatCodeGetter",
    "YYBAdapter",
    "WechatAdapter",
    "get_global_server_url",
    "parse_identifier",
    "strip_scheme",
    "normalize_login_type",
    "login_type_label",
    "load_accounts",
    "get_accounts",
    "get_wechat_codes",
    "print_online_status",
    "get_single_code",
    "get_single_phone_number",
    "get_single_phone_encrypted",
    "get_single_operate_wx_data",
    "get_single_user_encrypt_key",
    "get_single_user_info",
    "get_single_we_run_data",
    "get_single_cloud_function",
    "get_single_oauth_authorize",
    "LOGIN_TYPE_WX",
    "LOGIN_TYPE_SYZS",
    "LOGIN_TYPE_WMPF",
]
