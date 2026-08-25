# name: 微信Code获取模块

"""
微信小程序登录Code获取模块（yyb_go 统一协议网关）

对接 yyb_go 服务，自动从服务端获取存活账号，并根据账号自身类型自适应走不同协议：
  - WX   (应用宝 iLink/MMTLS): 支持全功能取码、手机号、云函数、运动步数，服务端自动续期
  - SYZS (手游助手 login_buffer): 支持标准小程序取码
  - WMPF (微信小程序 transfer): 支持标准小程序取码、手机号，失效时提示重扫

环境变量：
    WX_SERVER:     yyb_go 服务地址（推荐，默认 http://127.0.0.1:8000）
                   同时兼容 YYB_SERVER / WECHAT_SERVER / YINGYONGBAO_SERVER
    WX_ID:         可选，默认留空自动拉取 yyb_go 上所有存活账号。
                   若配置则作为白名单过滤（支持 id/openid，多个用 & 或换行分隔，支持 #备注）。
"""

import os
import time
import requests
import json
import re
import pathlib
from typing import List, Dict, Tuple, Optional, Literal

ProtocolType = Literal["YYB", "Auto", "Wechat", "Unknown"]

# ============================================================
#  服务地址解析（首选 WX_SERVER）
# ============================================================
def get_global_server_url() -> str:
    return (
        os.getenv("WX_SERVER") or
        os.getenv("YYB_SERVER") or
        os.getenv("WECHAT_SERVER") or
        os.getenv("YINGYONGBAO_SERVER") or
        "http://127.0.0.1:8000"
    ).rstrip("/")

# ============================================================
#  YYB 登录模式（与 yyb_go internal/qr 的 LoginType 常量对齐）
# ============================================================
LOGIN_TYPE_WX = "WX"
LOGIN_TYPE_SYZS = "SYZS"
LOGIN_TYPE_WMPF = "WMPF"

_LOGIN_TYPE_ALIASES = {
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

def normalize_login_type(value) -> str:
    """把任意写法的登录模式归一化为 WX / SYZS / WMPF，未知值一律回退 WX。"""
    key = str(value or "").strip().lower()
    return _LOGIN_TYPE_ALIASES.get(key, LOGIN_TYPE_WX)

def login_type_label(value) -> str:
    """返回登录模式的中文展示名。"""
    lt = normalize_login_type(value)
    return LOGIN_TYPE_LABELS.get(lt, lt)

# ============================================================
#  账号标识解析与前缀语法
# ============================================================
_IDENTIFIER_SCHEMES: Dict[str, Tuple[str, Optional[str]]] = {
    "wxid": ("wechat", None),
    "niuzi": ("wechat", None),
    "wechat": ("wechat", None),
    "yyb": ("yyb", LOGIN_TYPE_WX),
    "wx": ("yyb", LOGIN_TYPE_WX),
    "syzs": ("yyb", LOGIN_TYPE_SYZS),
    "wmpf": ("yyb", LOGIN_TYPE_WMPF),
}

def parse_identifier(identifier) -> Dict:
    """解析账号标识，拆出前缀(scheme)、真实ID与备注。
    支持 `scheme:id#备注`，也兼容无前缀的 `id#备注`。
    """
    text = str(identifier or "").strip()
    scheme = ""
    protocol = ""
    login_type = None
    body = text

    if ":" in text:
        head, _, rest = text.partition(":")
        key = head.strip().lower()
        if key in _IDENTIFIER_SCHEMES:
            scheme = key
            protocol, login_type = _IDENTIFIER_SCHEMES[key]
            body = rest.strip()

    raw_id, _, note = body.partition("#")

    return {
        "original": text,
        "scheme": scheme,
        "protocol": protocol,
        "login_type": login_type,
        "raw_id": raw_id.strip(),
        "note": note.strip(),
        "id_with_note": body,
    }

def strip_scheme(identifier) -> str:
    """去掉 scheme 前缀，保留 `id#备注`"""
    return parse_identifier(identifier)["id_with_note"]

# ============================================================
#  启动阶段：自动从 yyb_go 拉取账号并同步至 os.environ["WX_ID"]
# ============================================================
def _bootstrap_accounts_sync():
    """在模块加载时自动向 yyb_go 请求存活账号列表并写入 os.environ['WX_ID']"""
    if os.getenv("WX_ID") and os.getenv("WX_ID").strip():
        return

    has_server_env = bool(os.getenv("WX_SERVER") or os.getenv("YYB_SERVER") or os.getenv("WECHAT_SERVER") or os.getenv("YINGYONGBAO_SERVER"))
    server_url = get_global_server_url()

    if not has_server_env:
        print(f"[getCode] ⚠️ 未检测到 WX_SERVER 环境变量，尝试连接默认地址: {server_url}")

    try:
        r = requests.get(f"{server_url}/accounts", timeout=4)
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == 0 and isinstance(data.get("data"), list):
                alive_accounts = [
                    acc for acc in data["data"]
                    if str(acc.get("status", "")).lower() in ("alive", "", "unknown")
                ]
                if alive_accounts:
                    lines = []
                    for acc in alive_accounts:
                        ident = acc.get("openid") or str(acc.get("id"))
                        note = acc.get("nickname") or acc.get("alias") or f"账号_{acc.get('id')}"
                        lines.append(f"{ident}#{note}")
                    os.environ["WX_ID"] = "\n".join(lines)
                    print(f"[getCode] 自动从 yyb_go ({server_url}) 同步到 {len(alive_accounts)} 个存活账号:")
                    for acc in alive_accounts:
                        name = acc.get("nickname") or acc.get("alias") or "未知"
                        lt = normalize_login_type(acc.get("login_type"))
                        print(f"  - [{login_type_label(lt)}] {name} (id={acc.get('id')}, openid={acc.get('openid')})")
                else:
                    print(f"[getCode] ⚠️ 提示: yyb_go ({server_url}) 当前无存活账号，请先在 yyb_go 网页端扫码登录")
            else:
                print(f"[getCode] ❌ 从 yyb_go ({server_url}) 获取账号失败: {data.get('msg', '未知响应')}")
        else:
            print(f"[getCode] ❌ 请求 yyb_go ({server_url}/accounts) 响应状态异常: {r.status_code}")
    except Exception as e:
        print(f"[getCode] ❌ 无法连接取码服务 ({server_url}/accounts)，原因: {e}")
        print(f"[getCode] 请确认: 1. 在青龙中配置了环境变量 WX_SERVER=http://服务IP:端口；2. yyb_go 服务正在运行且网络可达。")

# 模块导入时执行同步拉取
_bootstrap_accounts_sync()

# ============================================================
#  YYB Server（yyb_go）适配器
# ============================================================

class YYBAdapter:
    """yyb_go 服务适配器"""

    def __init__(self, server_url: str = None):
        self.server_url = (server_url or get_global_server_url()).rstrip('/')
        self._accounts_cache = None
        self._cache_time = 0

    def health_check(self) -> bool:
        """健康检查"""
        try:
            url = f"{self.server_url}/health"
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                return False
            data = r.json()
            return (data.get("code") == 0 or
                    (isinstance(data.get("data"), dict) and data["data"].get("ok") is True) or
                    data.get("ok") is True)
        except Exception as e:
            print(f"[YYB] 健康检查异常: {e}")
            return False

    def _get_account_list(self) -> List[Dict]:
        """获取并缓存账号列表（5分钟）"""
        now = time.time()
        if self._accounts_cache and (now - self._cache_time) < 300:
            return self._accounts_cache

        try:
            r = requests.get(f"{self.server_url}/accounts", timeout=15)
            data = r.json()
            if data.get("code") != 0 or not isinstance(data.get("data"), list):
                return []
            self._accounts_cache = data["data"]
            self._cache_time = now
            return self._accounts_cache
        except Exception as e:
            print(f"[YYB] 获取账号列表失败: {e}")
            return []

    def _resolve_account(self, wxid_or_openid: str,
                         expect_login_type: Optional[str] = None) -> Dict:
        """根据 wxid/openid 查找 YYB 数据库中的账号记录"""
        if not wxid_or_openid:
            raise Exception("identifier 未提供（WX_ID 解析为空），请检查服务状态或调用参数")

        parsed = parse_identifier(wxid_or_openid)
        raw_id = parsed["raw_id"]
        if expect_login_type is None:
            expect_login_type = parsed["login_type"]

        accounts = self._get_account_list()

        if expect_login_type:
            scoped = [
                acc for acc in accounts
                if normalize_login_type(acc.get("login_type")) == expect_login_type
            ]
            if scoped:
                accounts = scoped

        # 1. 精确匹配 openid
        for acc in accounts:
            if (acc.get("openid") or "") == raw_id:
                return acc

        # 2. 匹配 id (数字)
        if raw_id.isdigit():
            for acc in accounts:
                if str(acc.get("id", "")) == raw_id or str(acc.get("uin", "")) == raw_id:
                    return acc

        # 3. 匹配 nickname / alias
        if parsed.get("note"):
            for acc in accounts:
                if acc.get("nickname") == parsed["note"] or acc.get("alias") == parsed["note"]:
                    return acc

        # 4. 唯一前缀匹配
        if len(raw_id) >= 8:
            prefix_hits = [
                acc for acc in accounts
                if (acc.get("openid") or "") and (acc["openid"].startswith(raw_id) or raw_id.startswith(acc["openid"]))
            ]
            if len(prefix_hits) == 1:
                return prefix_hits[0]

        # 5. 备注号选择 (#1, #2)
        note_match = re.search(r'#(\d+)$', str(wxid_or_openid))
        if note_match:
            idx_1based = int(note_match.group(1))
            if 1 <= idx_1based <= len(accounts):
                return accounts[idx_1based - 1]

        # 6. 如果环境变量 WX_ID 中配置的是旧版 wxid_xxx（在 yyb_go 中不存在对应 openid）：
        # 自动按配置项顺序匹配到 yyb_go 中的存活账号
        wx_id_env = os.getenv("WX_ID") or ""
        if wx_id_env:
            raw_entries = [parse_identifier(x)["raw_id"] for x in re.split(r'[@&\n\r|]+', wx_id_env) if x.strip()]
            if raw_id in raw_entries:
                idx = raw_entries.index(raw_id)
                if 0 <= idx < len(accounts):
                    mapped = accounts[idx]
                    print(f"[getCode] 智能映射: 旧版标识 [{raw_id}] 自动匹配 yyb_go 账号 [{idx+1}: {mapped.get('nickname') or mapped.get('id')}]")
                    return mapped

        # 7. 兜底首个可用账号
        if accounts:
            return accounts[0]

        return {}

    def _resolve_ref(self, wxid_or_openid: str,
                     expect_login_type: Optional[str] = None) -> str:
        acc = self._resolve_account(wxid_or_openid, expect_login_type)
        if acc and acc.get("id") is not None:
            return str(acc.get("id"))
        if acc and acc.get("openid"):
            return str(acc.get("openid"))
        return parse_identifier(wxid_or_openid)["raw_id"] or str(wxid_or_openid)

    def get_accounts(self) -> List[Dict]:
        """获取存活账号列表"""
        try:
            r = requests.get(f"{self.server_url}/accounts", timeout=15)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 0:
                raise Exception(data.get("msg", "获取账号失败"))
            accounts = data.get("data", [])
            if not isinstance(accounts, list):
                raise Exception(f"返回格式错误: {type(accounts)}")

            valid = []
            for acc in accounts:
                status = str(acc.get("status", "")).lower()
                if status in ("alive", "", "unknown"):
                    valid.append({
                        "id": acc.get("id"),
                        "wxid": acc.get("openid", ""),
                        "openid": acc.get("openid", ""),
                        "uin": acc.get("uin"),
                        "nickname": acc.get("nickname"),
                        "alias": acc.get("alias"),
                        "avatar": acc.get("avatar"),
                        "login_type": normalize_login_type(acc.get("login_type")),
                        "status": 1,
                        "loginState": 1,
                        "_ref": str(acc.get("id", "")) or acc.get("openid", ""),
                    })
            return valid
        except Exception as e:
            raise Exception(f"[YYB] 获取账号列表失败: {e}")

    def _post_code(self, path: str, ref: str, app_id: str, kind: str = "code",
                   expect_login_type: Optional[str] = None) -> str:
        resolved_ref = self._resolve_ref(ref, expect_login_type)
        url = f"{self.server_url}{path}"
        payload = {"ref": resolved_ref, "app_id": app_id}
        headers = {"Content-Type": "application/json"}

        try:
            print(f"[YYB] 请求{kind}: ref={resolved_ref}, app_id={app_id}")
            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code == 404:
                try:
                    body = r.json()
                    err_msg = body.get("msg") or body.get("error", "") or r.text[:80]
                except Exception:
                    err_msg = r.text[:80]
                raise Exception(f"接口/账号不存在(404): {err_msg}")

            if r.status_code == 400:
                raise Exception(f"参数错误 - 可能账号不存在: {r.text[:100]}")

            if r.status_code == 409:
                raise Exception("账号登录态已失效，需在 yyb_go 重新扫码登录")

            result = r.json()
            code_val = result.get("code", -1) if isinstance(result, dict) else -1
            if code_val != 0:
                msg = result.get("msg", f"HTTP {r.status_code}") if isinstance(result, dict) else r.text[:100]
                raise Exception(f"[{code_val}] {msg}")

            data = result.get("data", {})
            if isinstance(data, dict):
                inner = data.get("result", {})
                if isinstance(inner, dict):
                    if inner.get("code"):
                        return inner["code"]
                    if inner.get("login_buffer"):
                        return inner["login_buffer"]
                if data.get("code") and isinstance(data["code"], str):
                    return data["code"]
                if data.get("login_buffer") and isinstance(data["login_buffer"], str):
                    return data["login_buffer"]
            raise Exception(f"未拿到有效{kind}: {json.dumps(result, ensure_ascii=False)[:150]}")
        except requests.RequestException as e:
            raise Exception(f"[YYB] 请求{kind}失败: {e}")

    def get_code(self, ref: str, app_id: str,
                 expect_login_type: Optional[str] = None) -> str:
        return self._post_code("/wxapp/getCode", ref, app_id, "code", expect_login_type)

    def get_phone_number_code(self, ref: str, app_id: str,
                              expect_login_type: Optional[str] = None) -> str:
        return self._post_code("/wxapp/getPhoneNumber", ref, app_id, "手机号code", expect_login_type)

# 兼容别名
class WechatAdapter(YYBAdapter):
    def __init__(self, server_url: str = None, admin_key: str = None):
        super().__init__(server_url)
        self.admin_key = admin_key

# ============================================================
#  统一入口类
# ============================================================

class WeChatCodeGetter:
    """微信小程序Code获取统一入口"""

    def __init__(self, force_type: ProtocolType = None):
        self.server_url = get_global_server_url()
        self.adapter = YYBAdapter(self.server_url)
        self.primary_adapter = self.adapter
        self.target_wx_ids = []

        wx_id_env = os.getenv("WX_ID")
        if wx_id_env:
            self.target_wx_ids = [x.strip() for x in re.split(r'[@&\n|]+', wx_id_env) if x.strip()]

    def init(self):
        return True

    def _filter_accounts(self, accounts: List[Dict]) -> List[Dict]:
        if not self.target_wx_ids:
            return accounts

        filtered = []
        for acc in accounts:
            ref = str(acc.get("_ref", ""))
            acc_id = str(acc.get("id", ""))
            wxid = str(acc.get("wxid", ""))
            openid = str(acc.get("openid", ""))
            acc_login_type = normalize_login_type(acc.get("login_type"))

            for target in self.target_wx_ids:
                parsed = parse_identifier(target)
                raw_id = parsed["raw_id"]
                if not raw_id or raw_id not in (ref, acc_id, wxid, openid):
                    continue
                if parsed["login_type"] and acc_login_type != parsed["login_type"]:
                    continue
                filtered.append(acc)
                break
        return filtered

    def get_online_accounts(self) -> List[Tuple[Dict, Dict]]:
        """获取在线账号列表 [(account_info, login_status), ...]"""
        accounts = self.adapter.get_accounts()
        accounts = self._filter_accounts(accounts)

        online = []
        for acc in accounts:
            status = {
                "loginState": acc.get("loginState", 1),
                "onlineTime": acc.get("last_checked_at", 0),
                "device": acc.get("avatar", ""),
            }
            online.append((acc, status))
        return online

    def print_online_status(self):
        """打印在线状态"""
        online = self.get_online_accounts()
        print(f"\n当前有 {len(online)} 个账号在线 (@ {self.server_url})")
        for acc, status in online:
            name = (acc.get("nickname") or acc.get("alias") or acc.get("wxid", "未知")[:12])
            lt = login_type_label(acc.get("login_type"))
            print(f"  [{lt}] {name} (id={acc.get('id')}, openid={acc.get('openid')})")

    def get_applet_code(self, app_id: str, identifier: str) -> str:
        if not identifier:
            raise Exception("identifier 未提供，请检查 WX_ID 环境变量或调用参数")
        parsed = parse_identifier(identifier)
        return self.adapter.get_code(identifier, app_id, parsed["login_type"])

    def get_applet_phone_number(self, app_id: str, identifier: str) -> str:
        if not identifier:
            return None
        parsed = parse_identifier(identifier)
        return self.adapter.get_phone_number_code(identifier, app_id, parsed["login_type"])

    def get_codes_for_all_online(self, app_id: str) -> Dict[str, str]:
        online = self.get_online_accounts()
        codes = {}

        for i, (acc, _) in enumerate(online, 1):
            base_name = (acc.get("nickname") or acc.get("alias") or f"账号_{i}")
            if not base_name.strip() or base_name.strip() == '\u3164':
                wxid = acc.get("wxid", "")
                base_name = f"账号_{wxid[-6:]}" if wxid else f"账号_{i}"

            name = base_name
            counter = 1
            while name in codes:
                name = f"{base_name}_{counter}"
                counter += 1

            ref = acc.get("_ref") or str(acc.get("id")) or acc.get("openid", "")
            if not ref:
                continue

            try:
                code = self.get_applet_code(app_id, ref)
                codes[name] = code
                print(f"[getCode] ✓ {name}: {code[:20]}...")
            except Exception as e:
                print(f"[getCode] ✗ {name}: {e}")
        return codes

# ============================================================
#  便捷导出函数
# ============================================================

def load_accounts(filter_env_name: Optional[str] = None) -> List[Dict]:
    """动态加载账号列表（支持从 yyb_go 服务端拉取存活账号）"""
    getter = WeChatCodeGetter()
    getter.init()
    online_tuples = getter.get_online_accounts()
    online_accounts = [acc for acc, _ in online_tuples]

    custom_filter = (os.getenv(filter_env_name) if filter_env_name else None) or os.getenv("WX_ID")
    if not custom_filter:
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
                matched.append(acc)
                break
    return matched

def get_accounts() -> List[Dict]:
    """获取所有存活账号列表"""
    return load_accounts()

def get_wechat_codes(app_id: str) -> Dict[str, str]:
    getter = WeChatCodeGetter()
    getter.init()
    return getter.get_codes_for_all_online(app_id)

def print_online_status():
    getter = WeChatCodeGetter()
    getter.init()
    getter.print_online_status()

def get_single_code(app_id: str, identifier: str) -> Optional[str]:
    """获取单个账号的code（失败返回 None）"""
    if not identifier:
        print("[getCode] 缺少 identifier，跳过获取 code")
        return None
    getter = WeChatCodeGetter()
    getter.init()
    try:
        return getter.get_applet_code(app_id, identifier)
    except Exception as e:
        print(f"[getCode] 获取失败（返回 None 跳过）: {e}")
        return None

def get_single_phone_number(app_id: str, identifier: str) -> Optional[str]:
    """获取手机号code"""
    if not identifier:
        return None
    getter = WeChatCodeGetter()
    getter.init()
    try:
        return getter.get_applet_phone_number(app_id, identifier)
    except Exception as e:
        print(f"[getCode] 获取手机号失败: {e}")
        return None

if __name__ == '__main__':
    import sys
    print("=" * 50)
    print("  微信小程序 Code 获取工具 (yyb_go 网关版)")
    print("=" * 50)
    getter = WeChatCodeGetter()
    getter.print_online_status()