# name: YYB-Go / yyb-main 微信全能力通用工具库 (Python SDK) —— 适配重写版
"""
yyb-main / yyb-go 微信协议通用工具库 (Python SDK) —— 适配重写版

完美支持 yyb-main (Python/FastAPI) 与 yyb-go 所有后端服务版本。
全功能免鉴权支持、自适应端点降级路由：
  1. 账号管理: 存活账号自动发现 (`GET /api/accounts` / `GET /accounts`)
  2. 小程序取码: `wx.login` (`POST /api/yyb/get-code` / `POST /wxapp/getCode` / `POST /wx/code`)
  3. 手机号授权: `getPhoneNumber` (`POST /api/yyb/get-phone` / `POST /wxapp/getPhoneNumber`)
  4. 用户信息: `getUserInfo` (`POST /api/yyb/get-userinfo` / `POST /wxapp/getUserInfo`)
  5. 协议扩展: `operateWxData` (`POST /api/yyb/invoke-cloud` / `POST /wxapp/operateWxData`)
  6. 云开发: `cloudCallFunction` (`POST /api/yyb/cloud-call-function` / `POST /wxapp/cloud/function`)
  7. 云托管: `cloudCallContainer` (`POST /api/yyb/cloud-call-container` / `POST /wxapp/cloud/container`)
  8. 公众号 OAuth: `oauthAuthorize` (`POST /api/yyb/oauth-authorize` / `POST /wxapp/oauth/authorize`)
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
        "http://127.0.0.1:18273"
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

    def _request_single(self, method: str, endpoint: str, json_data: Any = None, params: Any = None) -> Tuple[bool, Any]:
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
                return False, "[404] 接口不存在"

            try:
                body = resp.json()
            except Exception:
                return True, resp.text

            if isinstance(body, dict):
                if body.get("success") is False or (body.get("code") is not None and body.get("code") not in (0, 200)):
                    err_msg = body.get("msg") or body.get("error") or body.get("message") or json.dumps(body, ensure_ascii=False)
                    return False, f"[{body.get('code', -1)}] {err_msg}"
                # 兼容 yyb-go 的 respJson 字符串：解析后把内部字段提升到顶层
                if isinstance(body.get("respJson"), str) and body["respJson"].strip():
                    try:
                        inner = json.loads(body["respJson"])
                        if isinstance(inner, dict):
                            merged = dict(body)
                            merged.update(inner)
                            merged["respJson"] = body["respJson"]
                            return True, merged
                    except Exception:
                        pass
                return True, body.get("data") if "data" in body else body
            return True, body
        except Exception as e:
            return False, str(e)

    def _request_with_fallback(self, method: str, endpoints: List[str], json_data: Any = None, params: Any = None) -> Any:
        last_err = ""
        for ep in endpoints:
            ok, res = self._request_single(method, ep, json_data, params)
            if ok:
                return res
            last_err = res
        raise Exception(f"[YYB-SDK] 请求失败 ({' / '.join(endpoints)}): {last_err}")

    def _resolve_ref(self, ref: str, expect_login_type: Optional[str] = None) -> str:
        parsed = parse_identifier(ref)
        raw = parsed["raw_id"]
        target_lt = parsed["login_type"] or (normalize_login_type(expect_login_type) if expect_login_type else None)

        if not raw:
            accounts = self.get_online_accounts()
            return str(accounts[0].get("openid") or accounts[0].get("id") or "") if accounts else ""

        accounts = self.get_accounts()
        pool = self.get_online_accounts()
        if not pool:
            pool = self.get_accounts(force_refresh=True)
        if not pool:
            return raw

        if target_lt:
            filtered = [acc for acc in pool if normalize_login_type(acc.get("login_type")) == target_lt]
            if filtered:
                pool = filtered

        # 0. 如果传入空或者 "none"/"undefined"，直接返回首个存活账号
        if not raw or raw.lower() in ("none", "undefined", "null"):
            return str(pool[0].get("openid") or pool[0].get("id") or "")

        # 1. 精确匹配 openid / wxid / id
        for acc in pool:
            if acc.get("openid") == raw or acc.get("wxid") == raw or str(acc.get("id")) == raw:
                return str(acc.get("openid") or acc.get("id"))

        # 2. 按备注/昵称匹配
        lower = raw.lower()
        for acc in pool:
            labels = [
                str(acc.get(k)).strip().lower()
                for k in ("alias", "remark", "nickname")
                if isinstance(acc.get(k), str) and acc.get(k).strip()
            ]
            if lower in labels:
                return str(acc.get("openid") or acc.get("id"))

        # 3. 数字索引匹配（如 ref 为 "1" / "2"）
        if raw.isdigit():
            num = int(raw)
            if 0 < num <= len(pool):
                return str(pool[num - 1].get("openid") or pool[num - 1].get("id"))

        # 4. 自动兜底：映射到可用存活账号
        idx = abs(hash(raw)) % len(pool)
        return str(pool[idx].get("openid") or pool[idx].get("id") or raw)

    # ---------- 账号管理 ----------

    def get_accounts(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        now = time.time()
        if not force_refresh and self._cached_accounts is not None and now - self._cache_time < 5:
            return self._cached_accounts
        try:
            data = self._request_with_fallback("GET", ["/api/accounts", "/accounts"])
            if isinstance(data, list):
                lst = data
            elif isinstance(data, dict):
                lst = data.get("accounts") or data.get("data") or []
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
        OFFLINE = {"offline", "expired", "invalid", "disabled", "error", "dead", "logout"}
        for acc in accounts:
            st = str(acc.get("status") or "").lower()
            if st in OFFLINE:
                continue
            if int(acc.get("loginSource") or acc.get("login_source") or 1) == 3 and acc.get("hasSession") is False:
                name = acc.get("nickname") or acc.get("alias") or acc.get("wxid") or acc.get("openid") or acc.get("id") or "未知"
                print(f"[yyb] 跳过微信小程序账号「{name}」：wmpf_session_id 为空/失效（hasSession=false），需重新登录该小程序号")
                continue
            valid.append(acc)
        return valid

    # ---------- 小程序核心能力 ----------

    # 微信授权频率控制：两次取码之间的最小间隔(秒)，防止触发后端频率限制
    _last_code_time = 0.0
    _code_min_interval = float(os.getenv("WX_CODE_INTERVAL", "3.0"))

    def _throttle_code(self):
        now = time.time()
        wait = self._code_min_interval - (now - self._last_code_time)
        if wait > 0:
            time.sleep(wait)
        self._last_code_time = time.time()

    def get_code(self, ref: str, app_id: str) -> str:
        """获取微信小程序登录 Code (wx.login)，带频率控制与退避重试"""
        resolved_ref = self._resolve_ref(ref)
        max_retry = int(os.getenv("WX_CODE_RETRY", "2"))
        last_err = ""
        for attempt in range(max_retry):
            self._throttle_code()
            try:
                res = self._request_with_fallback("POST", ["/api/yyb/get-code", "/wxapp/getCode", "/wx/code"], json_data={
                    "openid": resolved_ref,
                    "appid": app_id,
                })
                code = None
                if isinstance(res, dict):
                    code = res.get("code") or (res.get("data", {}).get("code") if isinstance(res.get("data"), dict) else None)
                elif isinstance(res, str):
                    code = res
                if not code:
                    raise Exception(f"未拿到有效小程序 code: {res}")
                return str(code)
            except Exception as e:
                msg = str(e)
                last_err = msg
                # 命中频率限制时，退避重试
                if re.search(r"frequency|limit|slowdown|频率|频繁|太频繁", msg, re.IGNORECASE):
                    backoff = 2.0 * (attempt + 1)
                    print(f"[yyb] 命中微信授权频率限制，{backoff}s 后重试 ({attempt + 1}/{max_retry})")
                    time.sleep(backoff)
                    continue
                raise
        raise Exception(f"获取 code 失败(重试{max_retry}次): {last_err}")

    def get_codes(self, refs: List[str], app_id: str) -> Dict[str, Any]:
        """批量获取小程序 Code"""
        resolved_refs = [self._resolve_ref(r) for r in refs]
        return self._request_with_fallback("POST", ["/api/yyb/get-codes", "/wxapp/getCodes"], json_data={
            "accounts": resolved_refs,
            "appid": app_id,
        })

    def get_phone_number(self, ref: str, app_id: str) -> Dict[str, Any]:
        """获取手机号授权数据 (getPhoneNumber)"""
        resolved_ref = self._resolve_ref(ref)
        res = self._request_with_fallback("POST", ["/api/yyb/get-phone", "/wxapp/getPhoneNumber"], json_data={
            "openid": resolved_ref,
            "appid": app_id,
        })
        inner = res.get("data") if isinstance(res, dict) and isinstance(res.get("data"), dict) else (res if isinstance(res, dict) else {})
        # 部分服务端把 encryptedData/iv 放在 raw 字段里，需兼容提取
        raw = {}
        if isinstance(inner, dict) and isinstance(inner.get("raw"), dict):
            raw = inner["raw"]
        elif isinstance(res, dict) and isinstance(res.get("raw"), dict):
            raw = res["raw"]
        return {
            "code": str(inner.get("code")) if inner.get("code") else None,
            "mobile": inner.get("mobile"),
            "masked_phone": inner.get("masked_phone"),
            "encryptedData": inner.get("encryptedData") or inner.get("encrypted_data") or raw.get("encryptedData") or raw.get("encrypted_data"),
            "iv": inner.get("iv") or inner.get("IV") or raw.get("iv") or raw.get("IV"),
            "cloudId": inner.get("cloudId"),
        }

    def get_phone_encrypted(self, ref: str, app_id: str) -> Dict[str, Any]:
        return self.get_phone_number(ref, app_id)

    def operate_wx_data(self, ref: str, app_id: str, payload: Dict[str, Any]) -> Any:
        resolved_ref = self._resolve_ref(ref)
        return self._request_with_fallback("POST", ["/api/yyb/invoke-cloud", "/wxapp/operateWxData"], json_data={
            "openid": resolved_ref,
            "appid": app_id,
            "param2": json.dumps(payload or {}, ensure_ascii=False),
        })

    def get_user_info(self, ref: str, app_id: str, lang: str = "zh_CN") -> Any:
        resolved_ref = self._resolve_ref(ref)
        return self._request_with_fallback("POST", ["/api/yyb/get-userinfo", "/wxapp/getUserInfo"], json_data={
            "openid": resolved_ref,
            "appid": app_id,
            "lang": lang,
        })

    def get_user_encrypt_key(self, ref: str, app_id: str) -> Any:
        return self.operate_wx_data(ref, app_id, {"api_name": "webapi_getuserencryptkey"})

    def get_we_run_data(self, ref: str, app_id: str) -> Any:
        return self.operate_wx_data(ref, app_id, {"api_name": "webapi_getwerundata"})

    def get_setting(self, ref: str, app_id: str) -> Any:
        return self.operate_wx_data(ref, app_id, {"api_name": "webapi_getsetting"})

    def get_system_info(self, ref: str, app_id: str) -> Any:
        return self.operate_wx_data(ref, app_id, {"api_name": "webapi_getsysteminfo"})

    def get_location(self, ref: str, app_id: str, loc_type: str = "wgs84") -> Any:
        return self.operate_wx_data(ref, app_id, {"api_name": "webapi_getlocation", "type": loc_type})

    # ---------- 云开发与云托管 ----------

    def cloud_call_function(self, ref: str, app_id: str, env: str, name: str, data: Dict[str, Any] = None) -> Any:
        resolved_ref = self._resolve_ref(ref)
        return self._request_with_fallback("POST", ["/api/yyb/cloud-call-function", "/wxapp/cloud/function"], json_data={
            "openid": resolved_ref,
            "appid": app_id,
            "cloudEnv": env,
            "functionName": name,
            "functionData": data or {},
        })

    def cloud_call_container(self, ref: str, app_id: str, env: str, path: str, service: str, header: Dict[str, str] = None, body: Any = None) -> Any:
        resolved_ref = self._resolve_ref(ref)
        return self._request_with_fallback("POST", ["/api/yyb/cloud-call-container", "/wxapp/cloud/container"], json_data={
            "openid": resolved_ref,
            "appid": app_id,
            "cloudHost": service,
            "path": path,
            "headers": header or {},
            "data": body or "",
        })

    # ---------- 微信公众号网页授权 (OAuth2) ----------

    def oauth_authorize(self, ref: str, app_id: str, redirect_uri: str, scope: str = "snsapi_userinfo", state: str = "") -> Any:
        resolved_ref = self._resolve_ref(ref)
        return self._request_with_fallback("POST", ["/api/yyb/oauth-authorize", "/wxapp/oauth/authorize"], json_data={
            "openid": resolved_ref,
            "appid": app_id,
            "url": redirect_uri,
            "scope": scope,
            "state": state,
        })

    def oauth_confirm(self, ref: str, app_id: str, oauth_url: str) -> Any:
        resolved_ref = self._resolve_ref(ref)
        return self._request_with_fallback("POST", ["/api/yyb/oauth-authorize-confirm", "/wxapp/oauth/confirm"], json_data={
            "openid": resolved_ref,
            "appid": app_id,
            "oauth_url": oauth_url,
        })

# 别名兼容
WeChatCodeGetter = YYBClient
YYBAdapter = YYBClient
WechatAdapter = YYBClient

# ============================================================
# 4. 便捷导出函数 (直接 1 行调用)
# ============================================================

def load_accounts(filter_env_name: Optional[str] = None) -> List[Dict[str, Any]]:
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
    if not matched and online_accounts:
        return [
            {**online_accounts[idx % len(online_accounts)], "remark": t["remark"] or online_accounts[idx % len(online_accounts)].get("nickname") or f"账号{idx + 1}"}
            for idx, t in enumerate(filter_targets)
        ]
    return matched

def get_accounts() -> List[Dict[str, Any]]:
    return load_accounts()

def resolve_accounts(env_name: str = "") -> List[str]:
    val = (os.getenv("WX_ID") or (os.getenv(env_name) if env_name else "") or "").strip()
    if val:
        return [str(v).split("#")[0].strip() for v in re.split(r"[\n&]+", val) if v.strip()]
    try:
        accs = load_accounts()
        if accs:
            ids = [str(a.get("openid") or a.get("wxid") or a.get("id") or "") for a in accs if (a.get("openid") or a.get("wxid") or a.get("id"))]
            print(f"[yyb] 自动从 yyb_go 同步到 {len(ids)} 个存活账号")
            return ids
    except Exception as e:
        print(f"[yyb] 自动拉取账号失败: {e}")
    print("[yyb] 未配置 WX_ID，且 yyb-main 无存活账号")
    return []

def print_online_status():
    client = YYBClient()
    all_accounts = client.get_accounts(force_refresh=True)
    accounts = client.get_online_accounts()
    print(f"\n[yyb-main] 当前有 {len(accounts)} 个账号在线 (@ {client.server_url}):")
    for idx, acc in enumerate(accounts, 1):
        name = acc.get("nickname") or acc.get("alias") or acc.get("wxid") or f"账号_{idx}"
        lt = login_type_label(acc.get("login_type"))
        print(f"  - [{lt}] {name} (id={acc.get('id')}, openid={acc.get('openid') or '无'})")
    skipped = [a for a in all_accounts
               if int(a.get("loginSource") or a.get("login_source") or 1) == 3 and a.get("hasSession") is False]
    if skipped:
        print(f"[yyb-main] 另有 {len(skipped)} 个微信小程序账号因 wmpf_session_id 为空/失效被跳过（需重新登录）:")
        for idx, acc in enumerate(skipped, 1):
            name = acc.get("nickname") or acc.get("alias") or acc.get("wxid") or f"账号_{idx}"
            print(f"  - [小程序] {name} (openid={acc.get('openid') or '无'})")

def get_wechat_codes(app_id: str) -> Dict[str, str]:
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
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.get_code(identifier, app_id)
    except Exception as e:
        print(f"[yyb] 获取 code 失败 ({identifier}): {e}")
        return None

def get_single_phone_number(app_id: str, identifier: str) -> Optional[str]:
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
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.get_phone_number(identifier, app_id)
    except Exception as e:
        print(f"[yyb] 获取手机号加密数据失败 ({identifier}): {e}")
        return None

def get_single_operate_wx_data(app_id: str, identifier: str, payload: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.operate_wx_data(identifier, app_id, payload or {"api_name": "webapi_getuserencryptkey"})
    except Exception as e:
        print(f"[yyb] 获取 operate 数据失败 ({identifier}): {e}")
        return None

def get_single_user_encrypt_key(app_id: str, identifier: str) -> Optional[Any]:
    return get_single_operate_wx_data(app_id, identifier, {"api_name": "webapi_getuserencryptkey"})

def get_single_user_info(app_id: str, identifier: str) -> Optional[Any]:
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.get_user_info(identifier, app_id)
    except Exception as e:
        print(f"[yyb] 获取用户信息失败 ({identifier}): {e}")
        return None

def get_single_we_run_data(app_id: str, identifier: str) -> Optional[Any]:
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.get_we_run_data(identifier, app_id)
    except Exception as e:
        print(f"[yyb] 获取微信步数失败 ({identifier}): {e}")
        return None

def get_single_cloud_function(app_id: str, identifier: str, env: str, name: str, data: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.cloud_call_function(identifier, app_id, env, name, data or {})
    except Exception as e:
        print(f"[yyb] 调用云函数失败 ({name}): {e}")
        return None

def get_single_oauth_authorize(app_id: str, identifier: str, redirect_uri: str, scope: str = "snsapi_userinfo", state: str = "") -> Optional[Any]:
    if not identifier:
        return None
    client = YYBClient()
    try:
        return client.oauth_authorize(identifier, app_id, redirect_uri, scope, state)
    except Exception as e:
        print(f"[yyb] 公众号网页授权失败: {e}")
        return None

# ============================================================
# 5. 通用 token 缓存工具（与 yyb.js 保持一致，供各脚本复用）
# 说明：微信 wx.login 的 code 是一次性的，不能缓存；但登录后换取的
# 业务 token 在有效期内可复用，从而大幅减少取 code 频率、规避限流。
# 缓存文件统一存放在 token_caches/ 目录，与 yyb.js 共享同一套缓存。
# 用法：
#   import yyb
#   t = yyb.get_cached_token('myapp', openid)        # 取缓存（自动判过期）
#   yyb.save_cached_token('myapp', openid, token)    # 存缓存（str 或 dict 均可）
#   yyb.remove_cached_token('myapp', openid)         # token 失效时清除
# ============================================================

TOKEN_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'token_caches')


def _token_cache_path(name: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', str(name or 'default'))
    return os.path.join(TOKEN_CACHE_DIR, f"{safe}.json")


def read_token_cache(name: str) -> Dict[str, Any]:
    """读取整个 token 缓存文件，返回 {openid: {token, updatedAt}, ...}。"""
    try:
        p = _token_cache_path(name)
        if not os.path.exists(p):
            return {}
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_token_cache(name: str, cache: Dict[str, Any]) -> None:
    """将整个 token 缓存写入文件。"""
    try:
        os.makedirs(TOKEN_CACHE_DIR, exist_ok=True)
        with open(_token_cache_path(name), 'w', encoding='utf-8') as f:
            json.dump(cache or {}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[yyb] 写入 token 缓存失败: {e}")


def _cache_time_ms(v: Any) -> int:
    """时间戳归一化：兼容毫秒数字与 ISO 字符串。"""
    if not v:
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(v).strip().replace('Z', '+00:00')).timestamp() * 1000)
    except Exception:
        return 0


def _jwt_exp_sec(token: Any) -> int:
    """解析 JWT 的 exp（秒）；非 JWT 或解析失败返回 0。"""
    if not isinstance(token, str) or not token:
        return 0
    parts = token.split('.')
    if len(parts) < 2:
        return 0
    try:
        payload = json.loads(_b64url_decode(parts[1]))
        return int(payload.get('exp') or 0)
    except Exception:
        return 0


def get_cached_token(cache_name: str, openid: str, opts: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """读取某账号缓存的登录态，并判断是否仍有效。

    支持两种存储形态（由 save_cached_token 写入）：
      1) 字符串 token：save_cached_token(name, key, 'xxx')    → 读回 cached['token']
      2) 任意字段字典：save_cached_token(name, key, {...})     → 读回 cached['字段名']
    有效期判断：
      1) JWT：token 含 exp 字段，按 exp 判断（可提前 expire_lead_sec 秒失效）
      2) 非 JWT：按缓存时长 max_age_ms 兜底（默认 6 小时）
    返回展平后的字典（含 updatedAt）或 None（无缓存/已过期）。
    """
    opts = opts or {}
    expire_lead_sec = int(opts.get('expire_lead_sec', 60))
    max_age_ms = int(opts.get('max_age_ms', 6 * 3600 * 1000))
    cache = read_token_cache(cache_name)
    item = cache.get(openid)
    if not isinstance(item, dict):
        return None

    # 兼容旧缓存：曾把整个字典嵌套存进 token 字段，此处展平
    inner = item.get('token')
    if isinstance(inner, dict):
        data = dict(inner)
        data['updatedAt'] = item.get('updatedAt')
    else:
        data = dict(item)

    has_payload = any(k != 'updatedAt' and v not in (None, '') for k, v in data.items())
    if not has_payload:
        return None

    now_ms = int(time.time() * 1000)
    # JWT 判断（仅当 token 为字符串且含 exp）
    exp = _jwt_exp_sec(data.get('token'))
    if exp:
        return data if exp * 1000 - expire_lead_sec * 1000 > now_ms else None

    # 时间兜底
    updated_at = _cache_time_ms(data.get('updatedAt'))
    if updated_at and now_ms - updated_at < max_age_ms:
        return data
    return None


def save_cached_token(cache_name: str, openid: str, token: Union[str, Dict[str, Any]]) -> None:
    """保存某账号的登录态。

    token 为字符串时存为 {'token': ..., 'updatedAt': ...}；为字典时按字段平铺存储。
    """
    if token is None or token == '':
        return
    payload = dict(token) if isinstance(token, dict) else {'token': token}
    payload['updatedAt'] = int(time.time() * 1000)
    cache = read_token_cache(cache_name)
    cache[openid] = payload
    write_token_cache(cache_name, cache)


def remove_cached_token(cache_name: str, openid: str) -> None:
    """删除某账号缓存（token 失效时调用，下次运行重新登录）。"""
    cache = read_token_cache(cache_name)
    if openid in cache:
        del cache[openid]
        write_token_cache(cache_name, cache)


def _b64url_decode(s: str) -> str:
    """Base64URL 解码（JWT payload 使用）。"""
    import base64 as _b64
    padding = '=' * (-len(s) % 4)
    return _b64.urlsafe_b64decode(s + padding).decode('utf-8', errors='ignore')


# 全局挂载到 builtins
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
builtins.read_token_cache = read_token_cache
builtins.write_token_cache = write_token_cache
builtins.get_cached_token = get_cached_token
builtins.save_cached_token = save_cached_token
builtins.remove_cached_token = remove_cached_token

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
    "read_token_cache",
    "write_token_cache",
    "get_cached_token",
    "save_cached_token",
    "remove_cached_token",
    "LOGIN_TYPE_WX",
    "LOGIN_TYPE_SYZS",
    "LOGIN_TYPE_WMPF",
]
