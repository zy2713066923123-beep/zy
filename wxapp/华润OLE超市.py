#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
华润 OLE 超市小程序 - 青龙每日签到
cron: 56 11,13 * * *
# name: 华润OLE超市

环境变量：
  WX_ID           微信账号，格式 wxid#备注，多账号换行或 & / @ 分隔
                  （该变量同时被 getCode 模块用于账号过滤）
  ole_wxid        兼容旧变量名（可选）
  WECHAT_SERVER   牛子协议服务，默认 http://127.0.0.1:8000
                  （getCode 读取；仅手机号加密绑定使用 /get/all/mobile）
  YYB_SERVER      应用宝(YYB) 服务地址（getCode 读取，auto 模式自动路由）
  ADMIN_KEY       牛子协议管理密钥（WeChatPadPro/iwechat 需要）
  SERVER_TYPE     wechat / yyb / auto（默认 auto 智能路由）

说明：
  - 登录 code 通过共享模块 getCode 获取（自动路由 牛子/应用宝）。
  - 手机号授权数据同样按账号协议自动路由：
      牛子账号 → WECHAT_SERVER 的 /get/all/mobile（返回 encryptedData/iv 或 code）
      应用宝账号 → getCode.get_single_phone_number（返回手机号授权 code）

"""

from __future__ import annotations
import getCode  # 自动同步 yyb_go 存活账号

import importlib.util
import json
import os
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests


# =========================
# 可手动修改的固定配置（脚本前面）
# =========================
SHOP_CODE = "205239"  # 门店编码，签到 enter_shop_code / Header shopcode
CITY_ID = "c_region_11139"  # 城市 id，Header cityid；不需要可改空字符串
APP_VERSION = "1.10.32"  # 小程序版本
PAGE_VERSION = "108"  # servicewechat referer 版本号
DEFAULT_HEAD_IMG = (
    "https://appres.crvole.com.cn/vgdt/images/imageTag/"
    "b794c71ab4275962be33be652d4b5311.png"
)

# =========================
# 业务常量（一般不用改）
# =========================
WECHAT_MINI_APPID = "wx6c61aaeba1551439"  # OLE 超市小程序 appid（抓包 referer）
DEFAULT_WECHAT_SERVER = "http://127.0.0.1:8000"
API_BASE = "https://ole-app.crvole.com.cn"
TENANT = "VGDT"
TENANT_CHANNEL = "OLE"
CHANNEL = "wxmini"
OS_NAME = "ios"
NOTIFY_TITLE = "OLE超市签到"

PATH_CODE_AUTH = "/vgdt_app_api/v1/vgdt-fea-app-member/front_api/wechat_auths/code/mini_program"
PATH_MEMBER_LOGIN = "/vgdt_app_api/v1/vgdt-fea-app-member/front_api/member_auths_login/mini_program_wechat"
PATH_MEMBER_SIGN = "/vgdt_app_api/v1/vgdt-fea-app-member/front_api/member_sign"
PATH_MEMBER_INFO = "/vgdt_app_api/v1/vgdt-fea-app-member/front_api/members/query_member_info"


@dataclass
class WxAccount:
    wxid: str
    remark: str = ""


@dataclass
class AccountSummary:
    index: int
    wxid: str
    remark: str = ""
    open_id: str = ""
    member_id: str = ""
    sign_status: str = "未执行"
    before_integral: Optional[int] = None
    after_integral: Optional[int] = None
    got_integral: Optional[int] = None
    succession_day: Optional[int] = None
    success: bool = False
    error_message: str = ""
    detail_lines: List[str] = field(default_factory=list)

    def log(self, message: str = "") -> None:
        self.detail_lines.append(message)
        print(message)

    def build_notify_lines(self) -> List[str]:
        name = self.remark or self.wxid
        lines = [f"【账号{self.index}】{name}"]
        if self.member_id:
            lines.append(f"memberId: {self.member_id}")
        lines.append(f"结果: {self.sign_status}")
        if self.before_integral is not None or self.after_integral is not None:
            before = self.before_integral if self.before_integral is not None else "?"
            after = self.after_integral if self.after_integral is not None else "?"
            lines.append(f"积分: {before} -> {after}")
        if self.got_integral is not None:
            lines.append(f"本次: +{self.got_integral}")
        if self.succession_day is not None:
            lines.append(f"连续: {self.succession_day} 天")
        if self.error_message:
            lines.append(f"说明: {self.error_message}")
        return lines


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sleep(sec: float) -> None:
    time.sleep(sec)


def parse_wxid_list(raw_value: str) -> List[WxAccount]:
    accounts: List[WxAccount] = []
    if not raw_value:
        return accounts
    for item in re.split(r"[\n&@]", raw_value):
        item = item.strip()
        if not item:
            continue
        if "#" in item:
            wxid, remark = item.split("#", 1)
            accounts.append(WxAccount(wxid=wxid.strip(), remark=remark.strip()))
        else:
            accounts.append(WxAccount(wxid=item, remark=""))
    return accounts


def build_code_url(raw_url: str) -> str:
    value = (raw_url or "").strip().rstrip("/")
    if not value:
        return ""
    if value.endswith("/get/code") or value.endswith("/code"):
        return value
    return f"{value}/api/v1/wx/app/get/code"


def build_unique() -> str:
    # 抓包形态类似 weapp... 设备/安装标识
    return "weapp" + uuid.uuid4().hex[:38]


def build_trace_id() -> str:
    return str(int(time.time() * 1000)) + f"{random.randint(10, 99)}"


def find_notify_send() -> Optional[Callable]:
    try:
        from notify import send  # type: ignore

        return send
    except Exception:
        pass

    search_dirs: List[Path] = []
    script_dir = Path(__file__).resolve().parent
    ql_dir = os.environ.get("QL_DIR", "")
    if ql_dir:
        search_dirs.extend(
            [
                Path(ql_dir),
                Path(ql_dir) / "scripts",
                Path(ql_dir) / "data" / "scripts",
                Path(ql_dir) / "data" / "public",
            ]
        )
    search_dirs.extend(
        [
            script_dir,
            script_dir.parent,
            Path("/ql"),
            Path("/ql/scripts"),
            Path("/ql/data/scripts"),
            Path("/ql/data/public"),
        ]
    )

    seen: set[str] = set()
    for directory in search_dirs:
        directory_str = str(directory)
        if directory_str in seen:
            continue
        seen.add(directory_str)
        notify_path = directory / "notify.py"
        if not notify_path.exists():
            continue
        spec = importlib.util.spec_from_file_location("ql_notify_ole", notify_path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            continue
        if hasattr(module, "send"):
            return getattr(module, "send")
    return None


def push_notify(title: str, content: str) -> None:
    sender = find_notify_send()
    if not sender:
        print("通知: 未找到 notify.py，跳过推送")
        return
    try:
        sender(title, content)
        print("通知: 推送完成")
    except Exception as exc:
        print(f"通知: 推送失败: {exc}")


class OleSign:
    def __init__(self) -> None:
        self.wechat_code_url = build_code_url(
            os.environ.get("WECHAT_SERVER", DEFAULT_WECHAT_SERVER)
        )
        self.session = requests.Session()
        self.session.trust_env = False
        self.unique = build_unique()
        self.user_agent = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Mobile/15E148 MicroMessenger/8.0.49(0x18003137) "
            "NetType/WIFI Language/zh_CN "
            f"MiniProgramEnv/iOS miniProgram/{WECHAT_MINI_APPID}"
        )
        self.referer = (
            f"https://servicewechat.com/{WECHAT_MINI_APPID}/{PAGE_VERSION}/page-frame.html"
        )

    # ---------- 微信协议服务 ----------
    def get_code(self, wxid: str) -> Optional[str]:
        """通过共享 getCode 模块获取登录 code（自动路由 牛子/应用宝，读取 WX_ID 过滤）。"""
        try:
            return getCode.get_single_code(WECHAT_MINI_APPID, wxid)
        except Exception as exc:
            print(f"微信: 获取 code 失败: {exc}")
            return None

    def _phone_proto(self, wxid: str) -> str:
        """与 getCode 一致的协议判定：应用宝 openid / 纯数字 → yyb，其余 → wechat。"""
        raw = str(wxid).split('#')[0].strip()
        if not raw:
            return 'wechat'
        if raw.isdigit():
            return 'yyb'
        if re.match(r'^o[a-zA-Z0-9_-]{20,}$', raw):
            return 'yyb'
        return 'wechat'

    def get_phone(self, wxid: str) -> Optional[Dict[str, Any]]:
        """获取手机号授权数据（按账号协议自动路由，与登录 code 同协议）。

        返回字典（统一为以下两种之一）：
          - 牛子: {encryptedData, iv, show_mobile}  或  {code, show_mobile}
          - 应用宝: {code}   （YYB getPhoneNumber 返回手机号授权 code）
        返回 None 表示获取失败。
        """
        proto = self._phone_proto(wxid)
        if proto == 'yyb':
            try:
                code = getCode.get_single_phone_number(WECHAT_MINI_APPID, wxid)
            except Exception as exc:
                print(f"微信: YYB 获取手机号失败: {exc}")
                return None
            if not code:
                print("微信: YYB 获取手机号 code 为空")
                return None
            print(f"✅ phone code ok (len={len(code)})")
            return {"code": code}
        return self._get_phone_niuzi(wxid)

    def _get_phone_niuzi(self, wxid: str) -> Optional[Dict[str, Any]]:
        """牛子协议获取手机号（兼容 encryptedData/iv 与 code 两种返回结构）。"""
        url = self.wechat_code_url.replace("/get/code", "/get/all/mobile")
        if url == self.wechat_code_url and not url.endswith("/get/all/mobile"):
            # 完整 code URL 被错误配置时兜底
            base = self.wechat_code_url.rsplit("/api/", 1)[0] if "/api/" in self.wechat_code_url else self.wechat_code_url
            url = f"{base.rstrip('/')}/api/v1/wx/app/get/all/mobile"

        payload = {
            "wxid": wxid,
            "appid": WECHAT_MINI_APPID,
            "data": json.dumps(
                {"api_name": "webapi_getuserwxphone", "with_credentials": True},
                ensure_ascii=False,
            ),
            "opt": 0,
        }
        try:
            resp = self.session.post(
                url,
                json=payload,
                timeout=30,
                proxies={"http": None, "https": None},
            )
            result = resp.json()
        except Exception as exc:
            print(f"微信: 获取手机号异常: {exc}")
            return None

        if result.get("Success") is False:
            print(f"微信: 获取手机号失败: {result.get('Message', 'unknown')}")
            return None

        # 兼容多种返回结构：Data.Data / data.Data / Data / data
        data: Any = result.get("Data")
        if not isinstance(data, dict):
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
        raw = data
        if isinstance(data, dict):
            raw = data.get("Data", data.get("data", data))
            if data.get("wx_phone"):
                raw = data

        info: Any = {}
        if isinstance(raw, str):
            try:
                info = json.loads(raw) if raw else {}
            except Exception:
                info = {}
        elif isinstance(raw, dict):
            info = raw

        if not isinstance(info, dict):
            info = {}

        # 方式A：直接含 encryptedData/iv（老式加密包）
        enc = info.get("encryptedData") or info.get("encrypted_data")
        iv = info.get("iv")
        if enc and iv:
            show = str(info.get("show_mobile") or info.get("mobile") or "")
            return {"encryptedData": enc, "iv": iv, "show_mobile": show}

        # 方式B：含 wx_phone 子对象（可能含 encryptedData/iv 或 code）
        wx_phone = info.get("wx_phone")
        if isinstance(wx_phone, dict):
            enc = wx_phone.get("encryptedData") or wx_phone.get("encrypted_data")
            iv = wx_phone.get("iv")
            if enc and iv:
                show = str(wx_phone.get("show_mobile") or wx_phone.get("mobile") or "")
                return {"encryptedData": enc, "iv": iv, "show_mobile": show}
            if wx_phone.get("code"):
                return {"code": str(wx_phone["code"])}

        # 方式C：ALLMobile[0].code 或 Data.code（手机号授权 code）
        all_mobile = info.get("ALLMobile") or (info.get("Data", {}) or {}).get("ALLMobile")
        if isinstance(all_mobile, list) and all_mobile:
            code = all_mobile[0].get("code")
            if code:
                return {"code": str(code)}
        if info.get("code"):
            return {"code": str(info["code"])}

        print(f"微信: 手机号数据包为空: {result}")
        return None

    # ---------- OLE 业务请求 ----------
    def build_headers(
        self,
        *,
        sessionid: str = "",
        open_id: str = "",
        device_name: str = "ole-ql",
        with_shop: bool = True,
        content_type: bool = True,
    ) -> Dict[str, str]:
        headers = {
            "Host": "ole-app.crvole.com.cn",
            "Connection": "keep-alive",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": self.user_agent,
            "Referer": self.referer,
            "tenant": TENANT,
            "tenant-channel": TENANT_CHANNEL,
            "channel": CHANNEL,
            "appversion": APP_VERSION,
            "os": OS_NAME,
            "unique": self.unique,
            "traceid": build_trace_id(),
            "olewxopenid": open_id or "",
            "sessionid": sessionid or "",
            "device-name": device_name or "ole-ql",
            "xweb_xhr": "1",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        if content_type:
            headers["Content-Type"] = "application/json"
        if with_shop and SHOP_CODE:
            headers["shopcode"] = str(SHOP_CODE)
        if with_shop and CITY_ID:
            headers["cityid"] = str(CITY_ID)
        return headers

    def api_request(
        self,
        method: str,
        path: str,
        *,
        headers: Dict[str, str],
        json_body: Any = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        url = API_BASE + path
        try:
            resp = self.session.request(
                method.upper(),
                url,
                headers=headers,
                json=json_body,
                params=params,
                timeout=timeout,
            )
            text = resp.text or ""
            try:
                data = resp.json()
            except Exception:
                return None, f"HTTP {resp.status_code}, 非 JSON: {text[:200]}"
            if not isinstance(data, dict):
                return None, f"HTTP {resp.status_code}, 响应非对象"
            return data, ""
        except Exception as exc:
            return None, str(exc)

    def ok(self, data: Optional[Dict[str, Any]]) -> bool:
        if not data:
            return False
        code = data.get("state_code", data.get("code", data.get("status")))
        return str(code) in ("200", "0", "success", "SUCCESS") or code is True

    # ---------- 登录 ----------
    def login(self, account: WxAccount, summary: AccountSummary) -> Optional[Dict[str, str]]:
        """返回 {sessionid, open_id, union_id, member_id, device_name}"""
        summary.log("1️⃣ 获取微信 code...")
        code = self.get_code(account.wxid)
        if not code:
            summary.error_message = "获取 code 失败"
            return None
        summary.log(f"✅ code ok (len={len(code)})")

        summary.log("2️⃣ code 换 open_id/union_id...")
        headers1 = self.build_headers(with_shop=False, device_name="ole-ql")
        data1, err1 = self.api_request(
            "POST",
            PATH_CODE_AUTH,
            headers=headers1,
            json_body={"code": code},
        )
        if err1 or not self.ok(data1):
            summary.error_message = f"code 登录失败: {err1 or data1}"
            summary.log(f"❌ {summary.error_message}")
            return None
        d1 = (data1 or {}).get("data") or {}
        open_id = str(d1.get("open_id") or d1.get("openid") or "")
        union_id = str(d1.get("union_id") or d1.get("unionid") or "")
        # 少数环境 code 接口直接返回会话
        user_session = str(d1.get("user_session") or d1.get("access_token") or "")
        member_id = str(d1.get("member_id") or d1.get("id") or "")
        if not open_id:
            summary.error_message = f"code 登录无 open_id: {data1}"
            summary.log(f"❌ {summary.error_message}")
            return None
        summary.open_id = open_id
        summary.log(f"✅ open_id={open_id[:8]}... union_id={'Y' if union_id else 'N'}")

        # 已注册账号：code 接口直接返回会话，跳过手机号绑定
        if user_session and member_id:
            summary.member_id = member_id
            summary.log("✅ code 接口已返回 user_session，跳过手机号绑定登录")
            return {
                "sessionid": user_session,
                "open_id": open_id,
                "union_id": union_id,
                "member_id": member_id,
                "device_name": "ole-ql",
            }

        summary.log("3️⃣ 获取手机号授权数据（按账号协议自动路由）...")
        phone = self.get_phone(account.wxid)
        if not phone:
            summary.error_message = "获取手机号失败（encryptedData/iv 或 code）"
            return None

        encrypted = phone.get("encryptedData") or phone.get("encrypted_data") or ""
        iv = phone.get("iv") or ""
        phone_code = str(phone.get("code") or "")
        show_mobile = str(phone.get("show_mobile") or phone.get("mobile") or "")
        if not ((encrypted and iv) or phone_code):
            summary.error_message = "手机号数据为空"
            summary.log(f"❌ phone keys: {list(phone.keys())}")
            return None
        kind = "加密包(encryptedData/iv)" if (encrypted and iv) else "授权code"
        summary.log(f"✅ phone ok (mobile={show_mobile or 'N/A'}, 类型={kind})")

        summary.log("4️⃣ 手机号绑定登录换 sessionid...")
        # 牛子老接口返回 encryptedData/iv；应用宝/新接口返回手机号 code
        if encrypted and iv:
            body2 = {
                "head_img_url": DEFAULT_HEAD_IMG,
                "mobile": encrypted,
                "nick_name": "",
                "open_id": open_id,
                "phone": {
                    "encrypted_data": encrypted,
                    "iv": iv,
                },
                "union_id": union_id,
                "invitation_code": "",
            }
        else:
            body2 = {
                "head_img_url": DEFAULT_HEAD_IMG,
                "mobile": phone_code,
                "nick_name": "",
                "open_id": open_id,
                "phone": {
                    "code": phone_code,
                },
                "union_id": union_id,
                "invitation_code": "",
            }
        headers2 = self.build_headers(
            open_id=open_id,
            device_name=show_mobile or "ole-ql",
            with_shop=True,
        )
        data2, err2 = self.api_request(
            "POST",
            PATH_MEMBER_LOGIN,
            headers=headers2,
            json_body=body2,
        )
        if err2 or not self.ok(data2):
            summary.error_message = f"会员登录失败: {err2 or data2}"
            summary.log(f"❌ {summary.error_message}")
            return None
        d2 = (data2 or {}).get("data") or {}
        user_session = str(d2.get("user_session") or d2.get("access_token") or "")
        member_id = str(d2.get("member_id") or d2.get("id") or "")
        if not user_session:
            summary.error_message = f"未返回 user_session: {data2}"
            summary.log(f"❌ {summary.error_message}")
            return None
        summary.member_id = member_id
        summary.log(f"✅ session 获取成功 member_id={member_id or 'N/A'}")
        return {
            "sessionid": user_session,
            "open_id": open_id,
            "union_id": union_id,
            "member_id": member_id,
            "device_name": show_mobile or "ole-ql",
        }

    # ---------- 签到 ----------
    def query_sign(
        self, sessionid: str, open_id: str, device_name: str
    ) -> Optional[Dict[str, Any]]:
        headers = self.build_headers(
            sessionid=sessionid,
            open_id=open_id,
            device_name=device_name,
            with_shop=True,
            content_type=False,
        )
        data, err = self.api_request("GET", PATH_MEMBER_SIGN, headers=headers)
        if err or not self.ok(data):
            print(f"查询签到失败: {err or data}")
            return None
        return (data or {}).get("data") or {}

    def do_sign(
        self, sessionid: str, open_id: str, device_name: str
    ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        headers = self.build_headers(
            sessionid=sessionid,
            open_id=open_id,
            device_name=device_name,
            with_shop=True,
        )
        body = {"enter_shop_code": str(SHOP_CODE)}
        data, err = self.api_request(
            "POST", PATH_MEMBER_SIGN, headers=headers, json_body=body
        )
        if err:
            return False, None, err
        if not self.ok(data):
            msg = ""
            if isinstance(data, dict):
                msg = str(data.get("message") or data.get("msg") or data)
            return False, data, msg or "state_code 非成功"
        return True, (data or {}).get("data") or {}, ""

    def query_member_info(
        self, sessionid: str, open_id: str, device_name: str
    ) -> Optional[Dict[str, Any]]:
        headers = self.build_headers(
            sessionid=sessionid,
            open_id=open_id,
            device_name=device_name,
            with_shop=True,
            content_type=False,
        )
        data, err = self.api_request(
            "GET",
            PATH_MEMBER_INFO,
            headers=headers,
            params={"refresh": "true"},
        )
        if err or not self.ok(data):
            return None
        return (data or {}).get("data") or {}

    def run_account(self, account: WxAccount, index: int, total: int) -> AccountSummary:
        name = account.remark or account.wxid
        summary = AccountSummary(index=index, wxid=account.wxid, remark=account.remark)
        summary.log("")
        summary.log("=" * 48)
        summary.log(f"账号[{index}/{total}] {name}")
        summary.log("=" * 48)

        # 每账号刷新 unique，模拟独立设备
        self.unique = build_unique()

        auth = self.login(account, summary)
        if not auth:
            summary.sign_status = "登录失败"
            return summary

        sessionid = auth["sessionid"]
        open_id = auth["open_id"]
        device_name = auth.get("device_name") or "ole-ql"

        summary.log("5️⃣ 查询签到状态...")
        sign_info = self.query_sign(sessionid, open_id, device_name)
        if sign_info is None:
            summary.sign_status = "查询签到失败"
            summary.error_message = summary.error_message or "GET member_sign 失败"
            return summary

        before = sign_info.get("total_integral")
        try:
            summary.before_integral = int(before) if before is not None else None
        except Exception:
            summary.before_integral = None
        sign_of_day = str(sign_info.get("sign_of_day") or "").upper()
        succession = sign_info.get("succession_sign_day")
        try:
            summary.succession_day = int(succession) if succession is not None else None
        except Exception:
            summary.succession_day = None
        summary.log(
            f"📊 今日已签={sign_of_day or '?'} 积分={summary.before_integral} "
            f"连续={summary.succession_day}"
        )

        if sign_of_day == "Y":
            summary.sign_status = "今日已签到"
            summary.after_integral = summary.before_integral
            summary.success = True
            summary.log("✅ 今日已签到，跳过")
            return summary

        summary.log("6️⃣ 执行签到...")
        ok, sign_data, err = self.do_sign(sessionid, open_id, device_name)
        if not ok:
            # 兼容“已签到”类文案
            err_l = (err or "").lower()
            if any(k in (err or "") for k in ("已签", "重复", "already", "signed")):
                summary.sign_status = "今日已签到"
                summary.success = True
                summary.log(f"✅ 判定已签到: {err}")
                return summary
            summary.sign_status = "签到失败"
            summary.error_message = err or err_l or "POST member_sign 失败"
            summary.log(f"❌ 签到失败: {summary.error_message}")
            return summary

        got = None
        if isinstance(sign_data, dict):
            got = sign_data.get("integral")
            try:
                summary.got_integral = int(got) if got is not None else None
            except Exception:
                summary.got_integral = None
        summary.sign_status = "签到成功"
        summary.success = True
        summary.log(f"✅ 签到成功 +{summary.got_integral if summary.got_integral is not None else '?'}")

        sleep(1)
        summary.log("7️⃣ 复核签到状态...")
        after_info = self.query_sign(sessionid, open_id, device_name)
        if after_info:
            after = after_info.get("total_integral")
            try:
                summary.after_integral = int(after) if after is not None else None
            except Exception:
                summary.after_integral = None
            succession = after_info.get("succession_sign_day")
            try:
                summary.succession_day = (
                    int(succession) if succession is not None else summary.succession_day
                )
            except Exception:
                pass
            summary.log(
                f"💰 积分: {summary.before_integral} -> {summary.after_integral} "
                f"连续={summary.succession_day}"
            )
        else:
            summary.after_integral = summary.before_integral
            if summary.got_integral is not None and summary.before_integral is not None:
                summary.after_integral = summary.before_integral + summary.got_integral

        return summary


def main() -> None:
    print(f"\n🛒 OLE超市签到  |  {now_text()}")
    print(f"门店 SHOP_CODE={SHOP_CODE}  CITY_ID={CITY_ID or '(空)'}")
    print(f"appid={WECHAT_MINI_APPID}  version={APP_VERSION}")

    if not SHOP_CODE:
        print("❌ 请先在脚本顶部填写 SHOP_CODE")
        return

    wxid_raw = (
        os.environ.get("WX_ID")
        or os.environ.get("wx_id")
        or os.environ.get("ole_wxid")
        or os.environ.get("OLE_WXID")
        or os.environ.get("olewxid")
        or ""
    ).strip()
    if not wxid_raw:
        print("❌ 未配置环境变量 WX_ID（格式: wxid#备注，多账号换行或 & / @ 分隔）")
        return

    accounts = parse_wxid_list(wxid_raw)
    if not accounts:
        print("❌ 未解析到有效账号")
        return

    print(f"📋 共 {len(accounts)} 个账号")
    print(f"登录 code / 手机号: 通过 getCode 模块按账号协议自动路由（牛子/应用宝）")
    print(f"牛子手机号接口: WECHAT_SERVER => {build_code_url(os.environ.get('WECHAT_SERVER', DEFAULT_WECHAT_SERVER))}")

    signer = OleSign()
    results: List[AccountSummary] = []

    for i, account in enumerate(accounts, 1):
        try:
            results.append(signer.run_account(account, i, len(accounts)))
        except Exception as exc:
            print(f"❌ 账号[{i}]异常: {exc}")
            results.append(
                AccountSummary(
                    index=i,
                    wxid=account.wxid,
                    remark=account.remark,
                    sign_status="异常",
                    error_message=str(exc),
                )
            )
        if i < len(accounts):
            sleep(random.uniform(1.5, 3.0))

    ok_n = sum(1 for r in results if r.success)
    print("")
    print("=" * 48)
    print(f"执行完成: 成功 {ok_n}/{len(results)}")
    print("=" * 48)

    notify_lines: List[str] = [f"OLE超市签到 {now_text()}", f"成功 {ok_n}/{len(results)}", ""]
    for r in results:
        notify_lines.extend(r.build_notify_lines())
        notify_lines.append("")
    content = "\n".join(notify_lines).strip()
    print(content)
    push_notify(NOTIFY_TITLE, content)


if __name__ == "__main__":
    main()