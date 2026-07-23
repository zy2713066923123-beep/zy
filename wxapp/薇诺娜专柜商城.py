#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# cron: 1 11,16 * * *
"""
# name: 薇诺娜专柜商城
薇诺娜专柜商城

环境变量:
WX_ID          格式：wxid#备注，多个账号用换行或 @ 或 & 分隔

WECHAT_SERVER   微信服务端地址，默认： http://192.168.1.179:8011
"""

from __future__ import annotations

import json
import os
import re
import importlib.util
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import getCode


APP_ID = "wx250394ab3f680bfa"
DEFAULT_WECHAT_SERVER = "http://192.168.1.179:8011"
DEFAULT_QIUMEI_API_BASE = "https://api.qiumeiapp.com"
DEFAULT_SHARE_CODE = "48d96b20"
DEFAULT_TASK_DELAY_SECONDS = 7.0
REQUEST_TIMEOUT = 30
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

AUTH_REFERER = "https://servicewechat.com/wx250394ab3f680bfa/743/page-frame.html"
AUTH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf254151e) XWEB/17127"
)
TASK_REFERER = "https://servicewechat.com/wx250394ab3f680bfa/637/page-frame.html"
TASK_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.56(0x18003830) NetType/WIFI Language/zh_CN"
)


def log(message: str, level: str = "info") -> None:
    prefixes = {
        "info": "[信息]",
        "debug": "[调试]",
        "error": "[错误]",
        "success": "[成功]",
        "warn": "[提示]",
    }
    if level == "debug" and not DEBUG:
        return
    print(f"{prefixes.get(level, '[信息]')} {message}")


def load_ql_notify() -> Optional[Any]:
    for module_name in ("notify", "sendNotify"):
        try:
            notify_module = __import__(module_name)  # type: ignore
            if hasattr(notify_module, "send") or hasattr(notify_module, "sendNotify"):
                return notify_module
        except Exception:
            pass

    candidates = [
        Path(__file__).with_name("notify.py"),
        Path(__file__).with_name("sendNotify.py"),
        Path.cwd() / "notify.py",
        Path.cwd() / "sendNotify.py",
    ]

    ql_dir = os.environ.get("QL_DIR", "").strip()
    if ql_dir:
        ql_path = Path(ql_dir)
        candidates.extend(
            [
                ql_path / "deps" / "notify.py",
                ql_path / "deps" / "sendNotify.py",
                ql_path / "scripts" / "notify.py",
                ql_path / "scripts" / "sendNotify.py",
                ql_path / "data" / "scripts" / "notify.py",
                ql_path / "data" / "scripts" / "sendNotify.py",
            ]
        )

    for path in candidates:
        if not path.is_file():
            continue
        try:
            module_name = f"ql_notify_{path.stem}_{abs(hash(str(path)))}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "send"):
                return module
            if hasattr(module, "sendNotify"):
                return module
        except Exception as exc:  # pragma: no cover
            log(f"加载通知模块失败：{path}，原因：{exc}", "debug")

    return None


def send_ql_notification(title: str, content: str) -> bool:
    notify_module = load_ql_notify()
    if not notify_module:
        log("未找到青龙 notify.py/sendNotify.py，跳过推送。", "warn")
        return False

    try:
        if hasattr(notify_module, "send"):
            notify_module.send(title, content)
        elif hasattr(notify_module, "sendNotify"):
            notify_module.sendNotify(title, content)
        else:
            log("通知模块缺少 send/sendNotify 方法，跳过推送。", "warn")
            return False
        log("通知推送完成。", "success")
        return True
    except Exception as exc:  # pragma: no cover
        log(f"通知推送失败：{exc}", "error")
        return False


def mask_secret(value: Optional[str], prefix: int = 8, suffix: int = 4) -> str:
    if not value:
        return "<空>"
    if len(value) <= prefix + suffix:
        return value
    return f"{value[:prefix]}...{value[-suffix:]}"


def task_delay() -> None:
    raw = os.environ.get("TASK_DELAY_SECONDS", str(DEFAULT_TASK_DELAY_SECONDS)).strip()
    try:
        seconds = float(raw)
    except ValueError:
        seconds = DEFAULT_TASK_DELAY_SECONDS
    if seconds > 0:
        time.sleep(seconds)


def mask_phone(value: Optional[str]) -> str:
    if not value:
        return "<未返回>"
    phone = str(value).strip()
    if len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


def short_text(value: Any, limit: int = 120) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def format_api_message(payload: Any) -> str:
    if isinstance(payload, dict):
        code = payload.get("code", payload.get("Code"))
        message = payload.get("msg") or payload.get("message") or payload.get("Message")
        if message and code not in (None, ""):
            return short_text(f"{message} (code={code})")
        if message:
            return short_text(message)
        return short_text(json.dumps(payload, ensure_ascii=False))
    return short_text(payload)


def task_state_text(item: "RunResult") -> str:
    parts = [
        f"签到：{'已完成' if item.checked_in else '未完成'}",
        f"森林签到：{'已完成' if item.tree_checked_in else '未完成'}",
        f"逛商城：{'已完成' if item.browsed_mall else '未完成'}",
        f"阅读文章：{'已完成' if item.read_article else '未完成'}",
        f"助力：{'已执行' if item.assisted else '未执行'}",
        f"浇水：{item.watered_times}次",
    ]
    if item.assist_target_label:
        parts.append(f"助力目标：{item.assist_target_label}")
    return "，".join(parts)


def build_notify_content(results: List["RunResult"]) -> str:
    success_count = sum(1 for item in results if item.success)
    fail_count = len(results) - success_count
    lines = [
        "薇诺娜商城任务结果",
        f"总账号：{len(results)}",
        f"成功：{success_count}",
        f"失败：{fail_count}",
        "",
    ]

    for item in results:
        status = "成功" if item.success else "失败"
        lines.append(f"【{status}】{item.label}")
        lines.append(task_state_text(item))
        if item.errors:
            for error in item.errors[:3]:
                lines.append(f"问题：{error}")
            if len(item.errors) > 3:
                lines.append(f"其余问题：还有 {len(item.errors) - 3} 条")
        lines.append("")

    return "\n".join(lines).strip()


@dataclass
class Account:
    wxid: str
    remark: str = ""
    own_share_code: str = ""


@dataclass
class AssistTarget:
    code: str = ""
    label: str = ""
    mode: str = "单码助力"


@dataclass
class RunResult:
    wxid: str
    remark: str = ""
    success: bool = False
    code: Optional[str] = None
    sessionid: Optional[str] = None
    openid: Optional[str] = None
    unionid: Optional[str] = None
    phone_number: Optional[str] = None
    mobile_code: Optional[str] = None
    app_user_token: Optional[str] = None
    own_share_code: str = ""
    checked_in: bool = False
    tree_checked_in: bool = False
    browsed_mall: bool = False
    read_article: bool = False
    assisted: bool = False
    assist_target_label: str = ""
    assist_mode: str = ""
    watered_times: int = 0
    remaining_water_gram: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.remark or self.wxid

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        log(f"{self.label}：{message}", "error")


class WinonaError(Exception):
    pass


def parse_wxid(wxid_env: str) -> List[Account]:
    if not wxid_env or not wxid_env.strip():
        return []

    accounts: List[Account] = []
    chunks = re.split(r"[\n@,&;]+", wxid_env)
    for chunk in chunks:
        item = chunk.strip()
        if not item:
            continue
        parts = [part.strip() for part in item.split("#")]
        wxid = parts[0] if parts else ""
        remark = parts[1] if len(parts) >= 2 else ""
        own_share_code = parts[2] if len(parts) >= 3 else ""
        if wxid:
            accounts.append(
                Account(
                    wxid=wxid,
                    remark=remark,
                    own_share_code=own_share_code,
                )
            )
    return accounts


def parse_share_codes(raw: str) -> List[str]:
    if not raw or not raw.strip():
        return []
    return [item.strip() for item in re.split(r"[\n@,;]+", raw) if item.strip()]


def resolve_assist_targets(accounts: List[Account], share_codes: List[str]) -> List[AssistTarget]:
    if not accounts:
        return []

    account_labels = [account.remark or account.wxid for account in accounts]
    own_share_codes = [account.own_share_code.strip() for account in accounts]
    account_count = len(accounts)

    if account_count > 1 and all(own_share_codes):
        return [
            AssistTarget(
                code=own_share_codes[(index + 1) % account_count],
                label=account_labels[(index + 1) % account_count],
                mode="多账号循环互助",
            )
            for index in range(account_count)
        ]

    if account_count > 1 and len(share_codes) == account_count:
        return [
            AssistTarget(
                code=share_codes[(index + 1) % account_count],
                label=account_labels[(index + 1) % account_count],
                mode="多账号循环互助",
            )
            for index in range(account_count)
        ]

    fallback_code = share_codes[0] if share_codes else DEFAULT_SHARE_CODE
    return [
        AssistTarget(
            code=fallback_code,
            label="",
            mode="单码助力",
        )
        for _ in accounts
    ]


def extract_mobile_info(payload: Any) -> Dict[str, str]:
    if not isinstance(payload, dict):
        raise WinonaError("中转服务返回的手机号数据无效")

    all_mobile = payload.get("ALLMobile")
    if isinstance(all_mobile, list):
        for item in all_mobile:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            if isinstance(code, str) and code.strip():
                return {
                    "mobile": str(item.get("mobile") or ""),
                    "show_mobile": str(item.get("show_mobile") or ""),
                    "code": code.strip(),
                }

    nested_data = payload.get("Data")
    if isinstance(nested_data, str) and nested_data.strip():
        try:
            parsed = json.loads(nested_data)
        except json.JSONDecodeError:
            parsed = None

        wx_phone = parsed.get("wx_phone") if isinstance(parsed, dict) else None
        if isinstance(wx_phone, dict):
            inner = wx_phone.get("data")
            parsed_inner = None
            if isinstance(inner, str) and inner.strip():
                try:
                    parsed_inner = json.loads(inner)
                except json.JSONDecodeError:
                    parsed_inner = None

            code = parsed_inner.get("code") if isinstance(parsed_inner, dict) else None
            if isinstance(code, str) and code.strip():
                return {
                    "mobile": str(wx_phone.get("mobile") or ""),
                    "show_mobile": str(wx_phone.get("show_mobile") or ""),
                    "code": code.strip(),
                }

    raise WinonaError("中转服务未返回可用的手机号授权码")


class RelayClient:
    def __init__(
        self,
        server_url: str,
        app_id: str = APP_ID,
        timeout: int = REQUEST_TIMEOUT,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.app_id = app_id
        self.timeout = timeout
        self.session = session or requests.Session()

    def _request_json(self, path: str, payload: Dict[str, Any]) -> Any:
        url = f"{self.server_url}{path}"
        log(f"请求接口：POST {url}", "debug")
        log(
            f"中转请求参数：{json.dumps(payload, ensure_ascii=False, sort_keys=True)}",
            "debug",
        )

        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise WinonaError(f"中转服务请求失败：{path}，{exc}") from exc

        try:
            result = response.json()
        except ValueError as exc:
            raise WinonaError(
                f"中转服务返回的 JSON 无法解析：{path}，{response.text[:200]}"
            ) from exc

        log(
            f"中转响应结果：{json.dumps(result, ensure_ascii=False, indent=2)}",
            "debug",
        )

        if not isinstance(result, dict):
            raise WinonaError(f"中转服务响应格式异常：{path}，{result!r}")

        status = result.get("Code", result.get("code"))
        message = (
            result.get("Message")
            or result.get("msg")
            or result.get("message")
            or "未知错误"
        )
        data = result.get("Data", result.get("data"))

        if status not in {0, 200, "0", "200", True}:
            raise WinonaError(f"中转服务接口失败：{path}，{message}")

        return data

    def get_sessionid(self, wxid: str) -> Optional[str]:
        # 统一使用 getCode 模块获取登录凭证；getCode 不直接提供 sessionid，
        # 且该字段仅用于日志输出，因此直接返回 None
        return None

    def get_code(self, wxid: str) -> str:
        return getCode.get_single_code(self.app_id, wxid)

    def get_mobile_info(self, wxid: str) -> Dict[str, str]:
        code = getCode.get_single_phone_number(self.app_id, wxid)
        return {"code": code, "show_mobile": "", "mobile": ""}


class WinonaClient:
    def __init__(
        self,
        base_url: str = DEFAULT_QIUMEI_API_BASE,
        timeout: int = REQUEST_TIMEOUT,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.auth_base = f"{self.base_url}/zgxcx/10001"
        self.task_base = f"{self.base_url}/zg-activity/zg-daily"

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Accept": "*/*",
            "Referer": AUTH_REFERER,
            "User-Agent": AUTH_USER_AGENT,
            "xweb_xhr": "1",
        }

    def _task_headers(self) -> Dict[str, str]:
        return {
            "Accept-Encoding": "gzip, deflate, br",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": TASK_REFERER,
            "User-Agent": TASK_USER_AGENT,
        }

    def _post_form_json(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        log(f"请求接口：POST {url}", "debug")
        log(
            f"表单参数：{json.dumps(payload, ensure_ascii=False, sort_keys=True)}",
            "debug",
        )

        try:
            response = self.session.post(
                url,
                data=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise WinonaError(f"请求失败：{url}，{exc}") from exc

        try:
            result = response.json()
        except ValueError as exc:
            raise WinonaError(
                f"接口返回的 JSON 无法解析：{url}，{response.text[:200]}"
            ) from exc

        log(
            f"接口响应：{json.dumps(result, ensure_ascii=False, indent=2)}",
            "debug",
        )

        if not isinstance(result, dict):
            raise WinonaError(f"接口响应格式异常：{url}，{result!r}")

        return result

    def get_openid_unionid(self, js_code: str) -> Dict[str, str]:
        result = self._post_form_json(
            f"{self.auth_base}/zgxcxAuth",
            {"jsCode": js_code},
            self._auth_headers(),
        )

        if result.get("code") != 200 or not isinstance(result.get("data"), dict):
            raise WinonaError(f"换取 openid/unionid 失败：{format_api_message(result)}")

        data = result["data"]
        openid = data.get("openid")
        unionid = data.get("unionid")
        if not openid or not unionid:
            raise WinonaError("换取 openid/unionid 失败：接口未返回完整身份信息")
        return {"openid": str(openid), "unionid": str(unionid)}

    def fast_login(self, mobile_code: str, openid: str, unionid: str) -> Dict[str, str]:
        result = self._post_form_json(
            f"{self.auth_base}/zgxcxUserFastLogin",
            {
                "code": mobile_code,
                "unionid": unionid,
                "xcxOpenid": openid,
                "zgCounterId": 0,
                "vm1Code": "",
                "registerSource": 0,
            },
            self._auth_headers(),
        )

        if result.get("code") != 200 or not isinstance(result.get("data"), dict):
            raise WinonaError(f"商城快捷登录失败：{format_api_message(result)}")

        data = result["data"]
        token = data.get("zgUserToken") or data.get("appUserToken") or data.get("token")
        if not token:
            raise WinonaError("商城快捷登录失败：未返回 appUserToken")
        return {
            "token": str(token),
            "phoneNumber": str(data.get("phoneNumber") or ""),
        }

    def task_request(self, endpoint: str, app_user_token: str, **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"appUserToken": app_user_token}
        payload.update(extra)
        return self._post_form_json(
            f"{self.task_base}/{endpoint}",
            payload,
            self._task_headers(),
        )

    def get_forest(self, app_user_token: str) -> Dict[str, Any]:
        result = self.task_request("getZgForest", app_user_token)
        if result.get("code") != 200 or not isinstance(result.get("data"), dict):
            raise WinonaError(f"查询森林信息失败：{format_api_message(result)}")
        return result["data"]

    def get_forest_user(self, app_user_token: str) -> Dict[str, Any]:
        result = self._post_form_json(
            f"{self.task_base}/getZgForestUser",
            {"appUserToken": app_user_token},
            self._auth_headers(),
        )
        if result.get("code") != 200 or not isinstance(result.get("data"), dict):
            raise WinonaError(f"查询个人助力码失败：{format_api_message(result)}")
        return result["data"]


class WinonaTaskRunner:
    def __init__(self, client: WinonaClient) -> None:
        self.client = client

    def run(self, result: RunResult, assist_target: Optional[AssistTarget] = None) -> None:
        token = result.app_user_token
        if not token:
            raise WinonaError("执行任务前缺少 appUserToken")

        self._checkin(result, token)
        task_delay()
        self._tree_checkin(result, token)
        task_delay()
        self._assist(result, token, assist_target)
        task_delay()
        self._browse_mall(result, token)
        task_delay()
        self._read_article(result, token)
        task_delay()
        self._water_tree(result, token)

    def _checkin(self, result: RunResult, token: str) -> None:
        response = self.client.task_request("zgSigninNew", token)
        code = response.get("code")
        if code == 200:
            result.checked_in = True
            log(f"{result.label}：商城签到成功", "success")
        elif code == 703:
            result.checked_in = True
            log(f"{result.label}：今天已经签到过了")
        elif code == 600:
            raise WinonaError("商城签到失败：appUserToken 已失效")
        else:
            raise WinonaError(f"商城签到失败：{format_api_message(response)}")

    def _tree_checkin(self, result: RunResult, token: str) -> None:
        try:
            response = self.client.task_request("signinZgForest", token)
            if response.get("code") == 200:
                result.tree_checked_in = True
                water_gram = (response.get("data") or {}).get("waterGram")
                log(f"{result.label}：森林签到成功，水滴 +{water_gram}g", "success")
            else:
                result.add_error(f"森林签到失败：{format_api_message(response)}")
        except WinonaError as exc:
            result.add_error(str(exc))

    def _assist(
        self,
        result: RunResult,
        token: str,
        assist_target: Optional[AssistTarget] = None,
    ) -> None:
        if not assist_target or not assist_target.code:
            log(f"{result.label}：未配置助力目标，跳过助力", "warn")
            return

        result.assist_target_label = assist_target.label
        result.assist_mode = assist_target.mode

        try:
            response = self.client.task_request(
                "addZgForestInvite",
                token,
                sysCode="zgxcx",
                isRegister=1,
                userShareCode=assist_target.code,
            )
            if response.get("code") == 200:
                result.assisted = True
                if assist_target.label:
                    log(f"{result.label}：助力成功 -> {assist_target.label}", "success")
                else:
                    log(f"{result.label}：助力成功", "success")
            else:
                suffix = f" -> {assist_target.label}" if assist_target.label else ""
                log(
                    f"{result.label}：助力未完成{suffix}，{format_api_message(response)}",
                    "warn",
                )
        except WinonaError as exc:
            suffix = f" -> {assist_target.label}" if assist_target.label else ""
            log(f"{result.label}：助力请求失败{suffix}，{exc}", "warn")

    def _browse_mall(self, result: RunResult, token: str) -> None:
        try:
            response = self.client.task_request(
                "updateZgForestTask",
                token,
                taskCode="2025001",
            )
            if response.get("code") == 200:
                result.browsed_mall = True
                log(f"{result.label}：逛商城任务完成", "success")
            else:
                result.add_error(f"逛商城任务失败：{format_api_message(response)}")
        except WinonaError as exc:
            result.add_error(str(exc))

    def _read_article(self, result: RunResult, token: str) -> None:
        try:
            response = self.client.task_request(
                "updateZgForestTask",
                token,
                taskCode="2025002",
            )
            code = response.get("code")
            if code == 200:
                result.read_article = True
                log(f"{result.label}：阅读文章任务完成", "success")
            elif code == 703:
                result.read_article = True
                log(f"{result.label}：阅读文章触发频率限制，按已完成处理", "warn")
            else:
                result.add_error(f"阅读文章任务失败：{format_api_message(response)}")
        except WinonaError as exc:
            result.add_error(str(exc))

    def _water_tree(self, result: RunResult, token: str) -> None:
        try:
            forest = self.client.get_forest(token)
        except WinonaError as exc:
            result.add_error(str(exc))
            return

        water_gram = int(forest.get("remainWaterGram") or 0)
        result.remaining_water_gram = water_gram
        log(f"{result.label}：当前剩余水滴 {water_gram}g")

        water_times = water_gram // 10
        if water_times <= 0:
            log(f"{result.label}：水滴不足，跳过浇水", "warn")
            return

        log(f"{result.label}：计划浇水 {water_times} 次")
        water_errors: List[str] = []
        for index in range(1, water_times + 1):
            try:
                response = self.client.task_request("wateringZgForest", token)
                if response.get("code") == 200:
                    result.watered_times += 1
                else:
                    water_errors.append(
                        f"第{index}次失败：{format_api_message(response)}"
                    )
            except WinonaError as exc:
                water_errors.append(f"第{index}次请求异常：{exc}")
            if index < water_times:
                task_delay()

        if result.watered_times > 0:
            level = "success" if not water_errors else "warn"
            log(
                f"{result.label}：浇水完成，成功 {result.watered_times}/{water_times} 次",
                level,
            )

        if water_errors:
            preview = "；".join(water_errors[:3])
            if len(water_errors) > 3:
                preview = f"{preview}；其余 {len(water_errors) - 3} 次未展开"
            result.add_error(f"浇水任务异常，共 {len(water_errors)} 次失败：{preview}")


def prepare_account(
    account: Account,
    relay_client: RelayClient,
    winona_client: WinonaClient,
) -> RunResult:
    result = RunResult(wxid=account.wxid, remark=account.remark or account.wxid)

    log("")
    log(f"========== 开始准备：{result.label} ==========")

    try:
        log("获取登录凭证...")
        result.code = relay_client.get_code(account.wxid)
        log("登录凭证获取成功", "success")
        log(f"jsCode：{mask_secret(result.code)}", "debug")

        log("换取账号身份...")
        auth_info = winona_client.get_openid_unionid(result.code)
        result.openid = auth_info["openid"]
        result.unionid = auth_info["unionid"]
        log("账号身份获取成功", "success")
        log(f"openid：{result.openid}", "debug")
        log(f"unionid：{result.unionid}", "debug")

        log("获取手机号授权...")
        result.sessionid = relay_client.get_sessionid(account.wxid)
        if result.sessionid:
            log(f"sessionid：{mask_secret(result.sessionid)}", "debug")

        mobile_info = relay_client.get_mobile_info(account.wxid)
        result.phone_number = mobile_info.get("show_mobile") or mobile_info.get("mobile")
        result.mobile_code = mobile_info["code"]
        log(f"手机号授权成功：{mask_phone(result.phone_number)}", "success")
        log(f"手机号授权码：{mask_secret(result.mobile_code)}", "debug")

        log("商城快捷登录...")
        login_info = winona_client.fast_login(
            mobile_code=result.mobile_code,
            openid=result.openid,
            unionid=result.unionid,
        )
        result.app_user_token = login_info["token"]
        if login_info.get("phoneNumber"):
            result.phone_number = login_info["phoneNumber"]
        log("商城登录成功", "success")
        log(f"appUserToken：{mask_secret(result.app_user_token)}", "debug")

        try:
            forest_user = winona_client.get_forest_user(result.app_user_token)
            own_share_code = str(forest_user.get("userShareCode") or "").strip()
            if own_share_code:
                configured_share_code = account.own_share_code.strip()
                if configured_share_code and configured_share_code != own_share_code:
                    log(
                        f"{result.label}：配置的助力码与接口返回不一致，已使用接口返回值 {own_share_code}",
                        "warn",
                    )
                else:
                    log(f"{result.label}：获取到自有助力码 {own_share_code}", "success")
                result.own_share_code = own_share_code
                account.own_share_code = own_share_code
            else:
                log(f"{result.label}：接口未返回自有助力码", "warn")
        except WinonaError as exc:
            log(f"{result.label}：获取自有助力码失败，{exc}", "warn")

    except WinonaError as exc:
        result.add_error(str(exc))
    except Exception as exc:  # pragma: no cover
        result.add_error(f"未知异常：{exc}")

    return result


def run_account_tasks(
    result: RunResult,
    task_runner: WinonaTaskRunner,
    assist_target: Optional[AssistTarget] = None,
) -> RunResult:
    if assist_target:
        result.assist_target_label = assist_target.label
        result.assist_mode = assist_target.mode

    if not result.app_user_token:
        result.success = False
        log(f"{result.label}：未完成登录，跳过任务执行", "warn")
        return result

    try:
        log(f"{result.label}：开始执行日常任务...")
        task_runner.run(result, assist_target)
        result.success = len(result.errors) == 0
        if result.success:
            log(f"{result.label}：任务完成", "success")
        else:
            log(f"{result.label}：执行结束，发现 {len(result.errors)} 个问题", "warn")

    except WinonaError as exc:
        result.add_error(str(exc))
    except Exception as exc:  # pragma: no cover
        result.add_error(f"未知异常：{exc}")

    result.success = len(result.errors) == 0
    return result


def main() -> int:
    notify_title = "薇诺娜商城任务"
    log("========================================")
    log("薇诺娜商城任务开始")
    log("========================================")

    wxid_env = os.environ.get("WX_ID", "")
    server_url = os.environ.get("WECHAT_SERVER", DEFAULT_WECHAT_SERVER)
    api_base = os.environ.get("QIUMEI_API_BASE", DEFAULT_QIUMEI_API_BASE)
    share_code_raw = os.environ.get("WINONA_SHARE_CODE", "").strip()

    if not wxid_env.strip():
        message = '未设置环境变量 WX_ID，例如：wxid_xxx#备注'
        log(message, "error")
        send_ql_notification(notify_title, message)
        return 1

    accounts = parse_wxid(wxid_env)
    if not accounts:
        message = "未从 WX_ID 中解析到有效账号。"
        log(message, "error")
        send_ql_notification(notify_title, message)
        return 1

    log(f"共解析到 {len(accounts)} 个账号：")
    for index, account in enumerate(accounts, 1):
        label = f" ({account.remark})" if account.remark else ""
        log(f"{index}. {account.wxid}{label}")

    log(f"中转服务：{server_url}")
    log(f"接口地址：{api_base}")

    relay_client = RelayClient(server_url=server_url)
    winona_client = WinonaClient(base_url=api_base)
    task_runner = WinonaTaskRunner(client=winona_client)

    results: List[RunResult] = []
    for index, account in enumerate(accounts):
        results.append(prepare_account(account, relay_client, winona_client))
        if index < len(accounts) - 1:
            task_delay()

    share_codes = parse_share_codes(share_code_raw)
    assist_targets = resolve_assist_targets(accounts, share_codes)
    has_any_account_share_code = any(account.own_share_code for account in accounts)
    has_account_share_codes = len(accounts) > 1 and all(account.own_share_code for account in accounts)
    is_cyclic_assist = any(target.mode == "多账号循环互助" for target in assist_targets)

    if len(accounts) > 1 and has_any_account_share_code and not has_account_share_codes:
        log("部分账号未成功获取自有助力码，已按回退规则分配助力。", "warn")
    if is_cyclic_assist:
        if has_account_share_codes:
            log("助力模式：多账号循环互助（使用接口自动获取的账号助力码）")
        else:
            log("助力模式：多账号循环互助（使用 WINONA_SHARE_CODE 中按账号顺序配置的助力码）")
    else:
        fallback_share_code = assist_targets[0].code if assist_targets else DEFAULT_SHARE_CODE
        log(f"助力模式：单码助力（{mask_secret(fallback_share_code)}）")
        if len(share_codes) > 1 and len(share_codes) != len(accounts):
            log("助力码数量与账号数不一致，已回退为首个助力码。", "warn")

    log("助力码明细：")
    for index, account in enumerate(accounts, 1):
        own_code = account.own_share_code.strip()
        if own_code:
            log(f"{index}. {account.remark or account.wxid} 自有助力码：{own_code}")
        else:
            log(f"{index}. {account.remark or account.wxid} 自有助力码：未获取")

    log("助力分配：")
    for index, account in enumerate(accounts, 1):
        assist_target = assist_targets[index - 1] if index - 1 < len(assist_targets) else None
        if assist_target and assist_target.code:
            target_label = assist_target.label or "外部助力码"
            log(
                f"{index}. {account.remark or account.wxid} -> {target_label}，助力码：{assist_target.code}"
            )
        else:
            log(f"{index}. {account.remark or account.wxid} -> 未分配助力目标", "warn")

    for index, result in enumerate(results):
        assist_target = assist_targets[index] if index < len(assist_targets) else None
        run_account_tasks(result, task_runner, assist_target)
        if index < len(results) - 1:
            task_delay()

    success_count = sum(1 for item in results if item.success)
    fail_count = len(results) - success_count

    log("")
    log("========================================")
    log("任务汇总")
    log("========================================")
    log(f"总账号：{len(results)}")
    log(f"成功：{success_count}")
    log(f"失败：{fail_count}")

    for item in results:
        status = "成功" if item.success else "失败"
        level = "success" if item.success else "error"
        log(f"【{status}】{item.label}", level)
        log(task_state_text(item))
        for error in item.errors:
            log(f"问题：{error}", "error")

    if os.environ.get("OUTPUT_JSON", "false").lower() == "true":
        print("\n--- JSON 输出 ---")
        print(
            json.dumps(
                [asdict(item) for item in results],
                ensure_ascii=False,
                indent=2,
            )
        )

    send_ql_notification(notify_title, build_notify_content(results))

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
