import yyb  # 自动同步 yyb_go 存活账号

# name:岚财承品
# cron:16 10,22 * * *
import dataclasses
import os
import re
from typing import Any, List, Optional

DEFAULT_YYB_SERVER = (os.getenv("WX_SERVER") or os.getenv("YYB_SERVER") or "http://127.0.0.1:18273").rstrip("/")
DEFAULT_NIUZI_SERVER = (os.getenv("WX_SERVER") or os.getenv("YYB_SERVER") or os.getenv("WECHAT_SERVER") or os.getenv("YINGYONGBAO_SERVER") or "http://127.0.0.1:18273").rstrip("/")


class CodeProviderError(RuntimeError):
    """所有 code 获取错误的基类。"""


class ConfigurationError(CodeProviderError):
    """配置、协议名、AppID 或账号标识无效。"""


def _mask(value: Any, left: int = 4, right: int = 3) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= left + right:
        return "***"
    return text[:left] + "***" + text[-right:]


def infer_protocol(identifier: str) -> str:
    """青龙统一路由：wxid_ 开头走牛子，其余账号标识走 YYB。"""
    value = str(identifier or "").split("#", 1)[0].strip()
    if not value:
        raise ConfigurationError("账号标识不能为空")
    return "niuzi" if re.match(r"^wxid_", value, re.I) else "yyb"


@dataclasses.dataclass(frozen=True)
class AccountSpec:
    """WX_ID 中的一行账号。"""

    identifier: str
    remark: str
    protocol: str


def parse_wx_id(value: str) -> List[AccountSpec]:
    """解析青龙 WX_ID；多账号使用换行，每行格式 identifier#备注。"""
    raw = str(value or "")
    accounts: List[AccountSpec] = []
    seen = set()
    for index, line in enumerate(re.split(r"[\r\n]+", raw), start=1):
        line = line.strip()
        if not line:
            continue
        identifier, separator, remark = line.partition("#")
        identifier = identifier.strip()
        if not identifier:
            raise ConfigurationError(f"WX_ID 第 {index} 行账号标识为空")
        normalized = identifier.lower()
        if normalized in seen:
            raise ConfigurationError(f"WX_ID 包含重复账号：{_mask(identifier)}")
        seen.add(normalized)
        accounts.append(
            AccountSpec(
                identifier=identifier,
                remark=remark.strip() if separator and remark.strip() else f"账号{index}",
                protocol=infer_protocol(identifier),
            )
        )
    if not accounts:
        raise ConfigurationError("WX_ID 未配置任何账号")
    return accounts


def accounts_from_env(name: str = "WX_ID") -> List[AccountSpec]:
    """从青龙环境变量读取账号列表；QL_WX_ID 优先于 WX_ID。"""
    raw = os.getenv(f"QL_{name}", os.getenv(name, ""))
    if not raw:
        # 未配置 WX_ID 时，自动从 yyb_go 拉取存活账号
        raw = "\n".join(resolve_accounts())
    return parse_wx_id(raw)


@dataclasses.dataclass(frozen=True)
class ProviderConfig:
    """统一配置；可直接构造，也可通过 from_env() 读取环境变量。"""

    protocol: str = "auto"
    yyb_server: str = DEFAULT_YYB_SERVER
    niuzi_server: str = DEFAULT_NIUZI_SERVER
    timeout: float = 30.0
    retries: int = 2
    retry_backoff: float = 1.0
    verify_tls: bool = True

    @classmethod
    def from_env(cls, protocol: Optional[str] = None) -> "ProviderConfig":
        def setting(name: str, default: str = "") -> str:
            return os.getenv(f"QL_{name}", os.getenv(name, default))

        return cls(
            protocol=(protocol or setting("CODE_PROTOCOL") or "auto").strip().lower(),
            yyb_server=setting("YYB_SERVER", DEFAULT_YYB_SERVER),
            niuzi_server=setting("WECHAT_SERVER", DEFAULT_NIUZI_SERVER),
            timeout=30.0,
            retries=2,
            retry_backoff=1.0,
            verify_tls=True,
        )

    def normalized(self) -> "ProviderConfig":
        protocol = self.protocol.strip().lower()
        aliases = {"wechat": "niuzi", "牛子": "niuzi", "牛子协议": "niuzi"}
        protocol = aliases.get(protocol, protocol)
        return dataclasses.replace(self, protocol=protocol)
# <<< WECHAT_CODE_PROVIDER_EMBEDDED <<<
"""
作者:   行止
日期:   2026-08-16
入口: 微信小程序 - 岚财承品 (wxf3e96f6e152915ad)

功能: 基于抓包会话完成自动登录、签到、积分任务和会员信息查询。
  1. 使用微信 code 与手机号 encryptedData/iv 调用小程序登录接口。
  2. 自动执行每日签到、分享、分享首页视频、观看首页视频、浏览商城任务。
  3. 执行结束后刷新并输出当前积分、连续签到天数和任务完成进度。


说明:
  青龙单文件版：通过 WX_ID/QL_WX_ID 读取账号，账号以 wxid_ 开头时走牛子，
  其余 openid/数字账号走 YYB；TokenStore 内嵌，微信 code 统一走 getCode 模块。
  优先校验本地缓存 token；缓存有效时直接执行任务。
  缓存失效或缺失时，先准备手机号授权包，再用 getCode 按账号格式获取 code，
  再按抓包确认的 loginByMiniApp 接口换取业务 token，并写入 TokenStore 缓存。
"""

import importlib
import importlib.util
import os
import shutil
import sys
import json
import logging
import random
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3

# ============ 统一取码（WX_ID + getCode，支持牛子/YYB 双协议自动路由）============


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

current_path = os.path.dirname(os.path.abspath(__file__))


def env_value(name: str, default: str = "") -> str:
    """读取青龙环境变量；QL_ 前缀优先。"""
    return os.getenv(f"QL_{name}", os.getenv(name, default))


def env_bool(name: str, default: bool) -> bool:
    raw = env_value(name, "1" if default else "0").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(env_value(name, str(default))))
    except (TypeError, ValueError):
        return default


APP_NAME = "岚财承品"
APPID = "wxf3e96f6e152915ad"
TOKEN_FILE = "LCCP.json"
BASE_URL = "https://userapp.klbycp.com"
REQUEST_TIMEOUT = env_int("LCCP_REQUEST_TIMEOUT", 30, 1)
# 刷新失败时保留缓存中的手机号授权材料，便于下一次重试。
DELETE_REFRESH_FAILED_CACHE = env_bool("LCCP_DELETE_REFRESH_FAILED_CACHE", False)

# ===== 手动配置区 =====
# 是否按任务中心 limitCount 尽量补齐每日任务次数。
RUN_TASK_TO_LIMIT = env_bool("LCCP_RUN_TASK_TO_LIMIT", True)
# 每类任务单次运行上限，防止异常状态导致过多请求。
MAX_RUNS_PER_TASK = env_int("LCCP_MAX_RUNS_PER_TASK", 5, 1)
# 浏览商城任务是否按照接口返回 requiredSeconds 实际等待。
WAIT_BROWSE_SECONDS = env_bool("LCCP_WAIT_BROWSE_SECONDS", True)
# 任务之间的短间隔。
TASK_INTERVAL_SECONDS = (10, 15)
# 看课上报间隔。
COURSE_INTERVAL_SECONDS = (60, 70)

BASE_HEADERS = {
    "Connection": "keep-alive",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 "
        "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
        "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
        "UnifiedPCWindowsWechat(0xf2541c37) XWEB/25364"
    ),
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded",
    "appid": APPID,
    "xweb_xhr": "1",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": f"https://servicewechat.com/{APPID}/17/page-frame.html",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(console_handler)

log_list: List[str] = []


class TokenStore:
    """内嵌 JSON token 缓存，支持损坏备份与原子写入。"""

    def __init__(self, filename: str = TOKEN_FILE, save_dir: str = current_path):
        self.filename = filename if os.path.isabs(filename) else os.path.join(save_dir, filename)
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.filename):
            return
        try:
            with open(self.filename, "r", encoding="utf-8") as file:
                data = json.load(file)
            self._data = data if isinstance(data, dict) else {}
        except Exception as exc:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = f"{self.filename}.bad.{timestamp}.bak"
            try:
                shutil.copy2(self.filename, backup)
                logger.warning(f"缓存文件损坏，已备份到 {backup}：{exc}")
            except Exception:
                logger.warning(f"缓存文件损坏且备份失败：{exc}")
            self._data = {}

    def save(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.filename)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=os.path.basename(self.filename) + ".", suffix=".tmp", dir=directory, text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(self._data, file, ensure_ascii=False, indent=2)
                file.write("\n")
            os.replace(temp_path, self.filename)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise

    def get(self, account: str, default: Any = None) -> Any:
        return self._data.get(str(account), default)

    def set(self, account: str, value: Any) -> Any:
        self._data[str(account)] = value
        self.save()
        return value

    def update(self, account: str, value: Dict[str, Any]) -> Any:
        key = str(account)
        old = self._data.get(key)
        if isinstance(old, dict) and isinstance(value, dict):
            old.update(value)
            result = old
        else:
            self._data[key] = value
            result = value
        self.save()
        return result

    def delete(self, account: str) -> Any:
        value = self._data.pop(str(account), None)
        if value is not None:
            self.save()
        return value

    def keys(self):
        return self._data.keys()


class MobileAuthService:
    """分别按牛子和 YYB 原生协议读取手机号授权包。"""

    def __init__(self, config: "ProviderConfig"):
        self.config = config
        explicit = env_value("MOBILE_AUTH_SERVER") or env_value("WECHAT_SERVER")
        self.explicit_server = explicit.strip().rstrip("/")
        self.session = requests.Session()

    @staticmethod
    def _json_or_base64(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str) or not value.strip():
            return {}
        text = value.strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        try:
            import base64

            return json.loads(base64.b64decode(text + "=" * (-len(text) % 4)).decode())
        except Exception:
            return {}

    @classmethod
    def _normalize_mobile(cls, item: Dict[str, Any]) -> Dict[str, Any]:
        data_obj = cls._json_or_base64(item.get("data"))
        return {
            "mobile": item.get("mobile") or data_obj.get("mobile", ""),
            "show_mobile": item.get("show_mobile") or data_obj.get("show_mobile", ""),
            "encryptedData": item.get("encryptedData") or data_obj.get("encryptedData", ""),
            "iv": item.get("iv") or data_obj.get("iv", ""),
            "code": item.get("code") or data_obj.get("code", ""),
        }

    @classmethod
    def _extract_mobiles(cls, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        block = data.get("Data") or data.get("data") or {}
        if not isinstance(block, dict):
            return []
        for key in ("mobiles", "ALLMobile"):
            values = block.get(key)
            if isinstance(values, list):
                return [cls._normalize_mobile(x if isinstance(x, dict) else {}) for x in values]
        inner = cls._json_or_base64(block.get("Data"))
        result: List[Dict[str, Any]] = []
        wx_phone = inner.get("wx_phone")
        if isinstance(wx_phone, dict):
            result.append(cls._normalize_mobile(wx_phone))
        custom = inner.get("custom_phone_list")
        if isinstance(custom, list):
            result.extend(cls._normalize_mobile(x if isinstance(x, dict) else {}) for x in custom)
        return result

    def get_mobile_info(self, account: "AccountSpec") -> Tuple[Dict[str, Any], str]:
        return self._get_yyb_mobile_info(account)

    def _get_yyb_mobile_info(self, account: "AccountSpec") -> Tuple[Dict[str, Any], str]:
        """YYB 原生接口：统一 yyb.py。"""
        try:
            res = get_single_phone_encrypted(APPID, account.identifier)
            if res and res.get("encryptedData") and res.get("iv"):
                return res, "YYB /wxapp/getPhoneNumber"
            return {}, "未获取到有效 encryptedData/iv"
        except Exception as exc:
            return {}, f"YYB 手机号接口请求失败：{type(exc).__name__}: {exc}"


provider_config: Optional["ProviderConfig"] = None
mobile_auth_service: Optional[MobileAuthService] = None


class Script:
    """单账号任务对象，持有 token、会话、用户信息和岚财承品业务接口。"""

    # ===== 初始化 / 登录 =====
    def __init__(self, account: "AccountSpec", info: Dict[str, Any]):
        if not isinstance(info, dict):
            info = {}
        self.account = account
        self.wxid = account.identifier
        self.remark = account.remark
        self.info = info
        self.token = str(info.get("token") or "").strip()
        self.user_id = info.get("userId") or info.get("user_id") or ""
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update(BASE_HEADERS)
        if self.token:
            self.session.headers["AppToken"] = self.token

    def wxlogin(self, code: str, mobile_info: Dict[str, Any]) -> str:
        encrypted_data = mobile_info.get("encryptedData") or self.info.get("encryptedData") or ""
        iv = mobile_info.get("iv") or self.info.get("iv") or ""
        if not encrypted_data or not iv:
            raise RuntimeError("微信手机号授权包缺少 encryptedData/iv，无法登录")

        # 参考认养一头牛等脚本：code 字段传 wx.login 的 code（微信登录 code），
        # userCode 字段传 getPhoneNumber 返回的手机号授权 code。
        phone_code = mobile_info.get("code") or self.info.get("phoneCode") or ""

        data = self.loginByMiniApp(
            {
                "encryptedData": encrypted_data,
                "iv": iv,
                "code": code,
                "userCode": phone_code,
                "appId": APPID,
            }
        )
        if data.get("code") != 200 or not data.get("token"):
            raise RuntimeError(f"loginByMiniApp失败: {data.get('msg') or data}")

        self.token = str(data.get("token"))
        user = data.get("user") or {}
        self.user_id = user.get("userId") or self.user_id
        self.session.headers["AppToken"] = self.token
        self.info.update(
            {
                "token": self.token,
                "remark": self.remark,
                "userId": self.user_id,
                "nickname": user.get("nickname") or user.get("nickName") or self.remark,
                "phone": user.get("phone") or "",
                "encryptedData": encrypted_data,
                "iv": iv,
            }
        )
        return self.token

    def sign_in(self) -> bool:
        if not self.token:
            return False
        data = self.checkLogin()
        return data.get("code") == 200

    def prepare_mobile_info(self) -> Tuple[Dict[str, Any], str]:
        """优先读取协议服务的新授权包，失败时再尝试历史缓存。"""
        if mobile_auth_service is None:
            return {}, "手机号授权服务尚未初始化"
        fresh, detail = mobile_auth_service.get_mobile_info(self.account)
        if fresh.get("encryptedData") and fresh.get("iv"):
            self.info.update(
                {
                    "encryptedData": fresh["encryptedData"],
                    "iv": fresh["iv"],
                    "phone": fresh.get("mobile") or self.info.get("phone") or "",
                }
            )
            return fresh, detail
        cached = {
            "encryptedData": self.info.get("encryptedData") or "",
            "iv": self.info.get("iv") or "",
            "mobile": self.info.get("phone") or "",
        }
        if cached["encryptedData"] and cached["iv"]:
            return cached, f"历史缓存（获取新授权包失败：{detail}）"
        return {}, detail

    # ===== 通用请求工具 =====
    def headers(self, json_body: bool = False, with_token: bool = True) -> Dict[str, str]:
        headers = BASE_HEADERS.copy()
        headers["Content-Type"] = "application/json;charset=UTF-8" if json_body else "application/x-www-form-urlencoded"
        if with_token and self.token:
            headers["AppToken"] = self.token
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        json_body: bool = False,
        with_token: bool = True,
    ) -> Dict[str, Any]:
        url = BASE_URL + path
        headers = self.headers(json_body=json_body, with_token=with_token)
        if method.upper() == "POST":
            response = self.session.post(
                url,
                params=params,
                json=body if json_body else None,
                data=None if json_body else (body or {}),
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                verify=False,
            )
        else:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                verify=False,
            )
        response.raise_for_status()
        try:
            return response.json()
        except json.JSONDecodeError:
            return {"code": -1, "msg": response.text}

    @staticmethod
    def ok(data: Dict[str, Any]) -> bool:
        return isinstance(data, dict) and data.get("code") == 200

    @staticmethod
    def msg(data: Dict[str, Any], default: str = "") -> str:
        return str(data.get("toast") or data.get("msg") or default or data)

    @staticmethod
    def safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def sleep_short(self, section: str = "任务间隔") -> None:
        delay = random.uniform(*TASK_INTERVAL_SECONDS)
        logger.info(f"{section}，等待：{delay:.1f}s")
        time.sleep(delay)

    # ===== 登录 / 用户接口 =====
    def loginByMiniApp(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.request("POST", "/store/app/wx/loginByMiniApp", body=body, json_body=True, with_token=False)

    def checkLogin(self) -> Dict[str, Any]:
        return self.request("GET", "/store/app/user/checkLogin")

    def getUserInfo(self) -> Dict[str, Any]:
        return self.request("GET", "/store/app/user/getUserInfo")

    # ===== 积分 / 任务接口 =====
    def getUserSign(self) -> Dict[str, Any]:
        return self.request("GET", "/app/integral/getUserSign")

    def sign(self) -> Dict[str, Any]:
        return self.request("POST", "/app/integral/sign", body={}, json_body=True)

    def taskCenter(self) -> Dict[str, Any]:
        return self.request("GET", "/app/integral/taskCenter", params={"platform": "mini"})

    def addIntegral(self, log_type: int) -> Dict[str, Any]:
        return self.request("POST", "/app/api/addIntegral", body={"logType": log_type}, json_body=True)

    def start(self) -> Dict[str, Any]:
        return self.request("POST", "/app/integral/browse/start", body={}, json_body=True)

    # ===== 商城浏览接口 =====
    def init(self) -> Dict[str, Any]:
        return self.request("GET", "/store/app/index/home/init")

    def goods(self) -> Dict[str, Any]:
        return self.request(
            "GET",
            "/store/app/index/home/goods",
            params={"id": 0, "position": 2, "pageNum": 1, "pageSize": 10},
        )

    # ===== 课程接口 =====
    def publicCourseCategoryList(self, yxx_tag: int = 50, home_page: int = 1) -> Dict[str, Any]:
        return self.request(
            "GET",
            "/app/course/publicCourseCategory/list",
            params={"homePage": home_page, "yxxTag": yxx_tag, "pageNum": 1, "pageSize": 4},
        )

    def publicCourseList(self, sub_cate_id: Any = 51) -> Dict[str, Any]:
        return self.request(
            "GET",
            "/app/course/publicCourse/list",
            params={"recommendSlot": 1, "yxxTag": 50, "pageNum": 1, "pageSize": 1, "subCateId": sub_cate_id},
        )

    def getCourseById(self, course_id: Any) -> Dict[str, Any]:
        return self.request("GET", "/app/course/getCourseById", params={"courseId": course_id})

    def getCourseVideoList(self, course_id: Any) -> Dict[str, Any]:
        return self.request(
            "GET",
            "/app/course/getCourseVideoList",
            params={"courseId": course_id, "pageNum": 1, "pageSize": 50},
        )

    def videoDetails(self, video_id: Any) -> Dict[str, Any]:
        return self.request("GET", "/app/course/videoDetails", params={"videoId": video_id})

    def status(self, course_id: Any, video_id: Any) -> Dict[str, Any]:
        return self.request(
            "GET",
            "/app/course/publicCourseAnswer/status",
            params={"courseId": course_id, "videoId": video_id},
        )

    def addStudyCourse(self, course_id: Any, video_id: Any, duration: int) -> Dict[str, Any]:
        return self.request(
            "POST",
            "/app/course/addStudyCourse",
            body={"courseId": str(course_id), "duration": duration, "videoId": video_id, "userId": self.user_id},
            json_body=True,
        )

    # ===== 会员信息 =====
    def run_member_info(self) -> Dict[str, Any]:
        data = self.getUserInfo()
        user = data.get("user") or {}
        if self.ok(data):
            self.user_id = user.get("userId") or self.user_id
            self.info.update(
                {
                    "userId": self.user_id,
                    "nickname": user.get("nickname") or user.get("nickName") or self.remark,
                    "phone": user.get("phone") or "",
                    "integral": user.get("integral"),
                }
            )
            logger.info(f"昵称：{self.info.get('nickname')}")
            logger.info(f"手机号：{self.info.get('phone') or '未返回'}")
            logger.info(f"当前积分：{user.get('integral', 0)}")
            log_list.append(f"昵称：{self.info.get('nickname')}")
            log_list.append(f"手机号：{self.info.get('phone') or '未返回'}")
            log_list.append(f"当前积分：{user.get('integral', 0)}")
        else:
            logger.info(f"会员信息：{self.msg(data, '查询失败')}")
        return user

    # ===== 每日签到 =====
    def run_sign(self) -> None:
        sign_info = self.getUserSign()
        is_day_sign = bool(sign_info.get("isDaySign"))
        sign_num = self.safe_int(sign_info.get("signNum"))
        logger.info(f"连续签到：{sign_num}天")
        logger.info(f"今日状态：{'已签' if is_day_sign else '未签'}")
        log_list.append(f"连续签到：{sign_num}天")
        log_list.append(f"今日状态：{'已签' if is_day_sign else '未签'}")
        if is_day_sign:
            return
        data = self.sign()
        msg = self.msg(data, "签到失败")
        logger.info(f"签到结果：{msg}")
        log_list.append(f"签到结果：{msg}")

    # ===== 每日任务 =====
    def task_remaining(self, task: Dict[str, Any]) -> int:
        done = self.safe_int(task.get("doneCount"))
        limit = self.safe_int(task.get("limitCount"))
        if limit <= 0 or done >= limit:
            return 0
        if not RUN_TASK_TO_LIMIT:
            return 1
        return min(limit - done, MAX_RUNS_PER_TASK)

    def find_task(self, tasks: List[Dict[str, Any]], code: str) -> Optional[Dict[str, Any]]:
        for item in tasks:
            if item.get("code") == code:
                return item
        return None

    def run_add_integral_task(self, title: str, log_type: int, count: int) -> int:
        success = 0
        for index in range(1, count + 1):
            data = self.addIntegral(log_type)
            ok = self.ok(data)
            msg = self.msg(data, "任务失败")
            logger.info(f"{title}：第{index}/{count}次，{msg}")
            if ok:
                success += 1
            if index < count:
                self.sleep_short(title)
        return success

    def choose_course_video(self) -> Tuple[Any, Any, str]:
        course_id = 178
        video_id = 560
        title = "默认课程"
        course_list = self.publicCourseList()
        rows = ((course_list.get("data") or {}).get("list") or []) if isinstance(course_list.get("data"), dict) else []
        if rows:
            course_id = rows[0].get("courseId") or course_id
        videos = self.getCourseVideoList(course_id)
        video_rows = ((videos.get("data") or {}).get("list") or []) if isinstance(videos.get("data"), dict) else []
        available = [item for item in video_rows if self.safe_int(item.get("isBuy"), 1) == 1]
        if available:
            video = random.choice(available)
            video_id = video.get("videoId") or video_id
            title = video.get("title") or title
        return course_id, video_id, title

    def run_course_task(self, count: int) -> int:
        success = 0
        for index in range(1, count + 1):
            course_id, video_id, title = self.choose_course_video()
            self.getCourseById(course_id)
            self.videoDetails(video_id)
            self.status(course_id, video_id)
            duration = random.randint(35, 45)
            study = self.addStudyCourse(course_id, video_id, duration)
            logger.info(f"观看首页视频：第{index}/{count}次，课程：{title}")
            logger.info(f"看课上报：{self.msg(study, '上报完成')}")
            if self.ok(study):
                time.sleep(random.uniform(*COURSE_INTERVAL_SECONDS))
                data = self.addIntegral(10)
                msg = self.msg(data, "领取失败")
                logger.info(f"看课积分：{msg}")
                if self.ok(data):
                    success += 1
            if index < count:
                self.sleep_short("看课任务间隔")
        return success

    def run_browse_mall_task(self, count: int) -> int:
        success = 0
        for index in range(1, count + 1):
            self.checkLogin()
            start_data = self.start()
            required = self.safe_int(start_data.get("requiredSeconds"), 60)
            logger.info(f"浏览商城：第{index}/{count}次，requiredSeconds={required}")
            self.init()
            self.goods()
            if WAIT_BROWSE_SECONDS:
                delay = required + random.randint(2, 5)
                logger.info(f"浏览商城等待：{delay}s")
                time.sleep(delay)
            data = self.addIntegral(13)
            msg = self.msg(data, "领取失败")
            logger.info(f"浏览商城积分：{msg}")
            if self.ok(data):
                success += 1
            if index < count:
                self.sleep_short("浏览任务间隔")
        return success

    def run_tasks(self) -> None:
        data = self.taskCenter()
        payload = data.get("data") or {}
        tasks = payload.get("dailyTasks") or []
        logger.info(f"任务中心积分：{payload.get('integralBalance', 0)}")
        log_list.append(f"任务中心积分：{payload.get('integralBalance', 0)}")

        task_map = {
            "SHARE": ("分享得积分", 3, self.run_add_integral_task),
            "SHARE_HOME_VIDEO": ("分享首页视频", 35, self.run_add_integral_task),
        }
        for code, (title, log_type, func) in task_map.items():
            task = self.find_task(tasks, code)
            if not task:
                logger.info(f"{title}：任务中心未返回，跳过")
                continue
            remaining = self.task_remaining(task)
            logger.info(f"{title}：进度 {task.get('doneCount', 0)}/{task.get('limitCount', 0)}")
            if remaining <= 0:
                logger.info(f"{title}：已完成，跳过")
                continue
            count = func(title, log_type, remaining)
            log_list.append(f"{title}：完成 {count}/{remaining}次")

        course_task = self.find_task(tasks, "COURSE")
        if course_task:
            remaining = self.task_remaining(course_task)
            logger.info(f"观看首页视频60秒：进度 {course_task.get('doneCount', 0)}/{course_task.get('limitCount', 0)}")
            if remaining > 0:
                count = self.run_course_task(remaining)
                log_list.append(f"观看首页视频：完成 {count}/{remaining}次")
            else:
                logger.info("观看首页视频60秒：已完成，跳过")

        browse_task = self.find_task(tasks, "BROWSE_MALL")
        if browse_task:
            remaining = self.task_remaining(browse_task)
            logger.info(f"浏览商城60秒：进度 {browse_task.get('doneCount', 0)}/{browse_task.get('limitCount', 0)}")
            if remaining > 0:
                count = self.run_browse_mall_task(remaining)
                log_list.append(f"浏览商城：完成 {count}/{remaining}次")
            else:
                logger.info("浏览商城60秒：已完成，跳过")

    # ===== 结束汇总 =====
    def run_summary(self) -> None:
        data = self.getUserInfo()
        user = data.get("user") or {}
        task_data = self.taskCenter()
        task_payload = task_data.get("data") or {}
        logger.info(f"当前积分：{user.get('integral', task_payload.get('integralBalance', 0))}")
        log_list.append(f"当前积分：{user.get('integral', task_payload.get('integralBalance', 0))}")
        tasks = task_payload.get("dailyTasks") or []
        for item in tasks:
            line = f"{item.get('title')}：{item.get('doneCount', 0)}/{item.get('limitCount', 0)}"
            logger.info(line)

    def run(self) -> None:
        if not self.token:
            raise RuntimeError("缺少有效 token")

        logger.info("======会员信息=====")
        log_list.append("======会员信息=====")
        self.run_member_info()

        logger.info("======每日签到=====")
        log_list.append("======每日签到=====")
        self.run_sign()

        logger.info("======积分任务=====")
        log_list.append("======积分任务=====")
        self.run_tasks()

        logger.info("======执行汇总=====")
        log_list.append("======执行汇总=====")
        self.run_summary()


def ScriptRuntime(account: "AccountSpec", info: Dict[str, Any]) -> Dict[str, Any]:
    """
    单账号业务执行流程。

    进入这里时，main 中已经完成缓存读取、token 校验、失效刷新和失败跳过。
    """
    task = Script(account, info)
    task.run()
    return task.info


def find_notification_sender() -> Tuple[Optional[Any], str]:
    """兼容青龙新版/旧版 notify.py 与 sendNotify.py。"""
    for module_name in ("notify", "sendNotify"):
        try:
            module = importlib.import_module(module_name)
            sender = getattr(module, "send", None) or getattr(module, "sendNotify", None)
            if callable(sender):
                return sender, module_name
        except Exception:
            pass

    candidates = [
        Path(current_path) / "notify.py",
        Path(current_path) / "sendNotify.py",
        Path("/ql/data/scripts/notify.py"),
        Path("/ql/data/scripts/sendNotify.py"),
        Path("/ql/scripts/notify.py"),
        Path("/ql/scripts/sendNotify.py"),
    ]
    checked = set()
    for path in candidates:
        try:
            resolved = str(path.resolve())
            if resolved in checked or not path.is_file():
                continue
            checked.add(resolved)
            spec = importlib.util.spec_from_file_location("lccp_qinglong_notify", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sender = getattr(module, "send", None) or getattr(module, "sendNotify", None)
            if callable(sender):
                return sender, resolved
        except Exception:
            continue
    return None, ""


def send_notification(title: str, content: str) -> bool:
    sender, source = find_notification_sender()
    if sender is None:
        logger.info("\n📭 未找到青龙 notify.py/sendNotify.py，运行报告已保留在任务日志")
        return False
    try:
        sender(title, content)
        logger.info(f"\n📨 青龙通知已提交（通知模块：{source}）")
        return True
    except Exception as exc:
        logger.warning(f"\n⚠️ 青龙通知发送失败：{type(exc).__name__}: {str(exc)[:120]}")
        return False


def load_account_cache(token_cache: TokenStore, account: "AccountSpec") -> Dict[str, Any]:
    """读取新缓存键，并兼容旧 PLUS 的 yyb:openid 缓存键。"""
    info = token_cache.get(account.identifier)
    if info is None and account.protocol == "yyb":
        legacy = token_cache.get(f"yyb:{account.identifier}")
        if isinstance(legacy, dict):
            info = dict(legacy)
            token_cache.set(account.identifier, info)
            logger.info(f"♻️ {account.remark} 已兼容迁移旧 YYB 缓存")
    return info if isinstance(info, dict) else {}


def main() -> int:
    global provider_config, mobile_auth_service

    logger.info(f"🚀【{APP_NAME}】开始执行任务")
    try:
        provider_config = ProviderConfig.from_env(protocol="auto").normalized()
        mobile_auth_service = MobileAuthService(provider_config)
        accounts = accounts_from_env()
        if get_single_code is None:
            raise ConfigurationError("getCode 模块未加载，无法获取微信 code（请确认 yyb.py 与本脚本同目录）")
    except CodeProviderError as exc:
        message = f"❌ 配置错误：{exc}"
        logger.error(message)
        log_list.append(message)
        send_notification(f"{APP_NAME}｜配置失败", "\n".join(log_list))
        return 1

    protocol_count = {
        "niuzi": sum(1 for account in accounts if account.protocol == "niuzi"),
        "yyb": sum(1 for account in accounts if account.protocol == "yyb"),
    }
    message = (
        f"📡 从 WX_ID 读取到 {len(accounts)} 个账号："
        f"牛子 {protocol_count['niuzi']} 个，YYB {protocol_count['yyb']} 个"
    )
    logger.info("\n" + message)
    logger.info("🔐 缓存 token 会优先验证；只有 token 失效时才获取授权包和一次性 code。\n")
    log_list.append(message)

    token_cache = TokenStore(TOKEN_FILE, current_path)
    completed = 0
    failed = 0
    for index, account in enumerate(accounts, start=1):
        account_info = load_account_cache(token_cache, account)
        account_info["remark"] = account.remark
        account_info["protocol"] = account.protocol
        if token_cache.get(account.identifier) is None:
            token_cache.set(account.identifier, account_info)
        else:
            token_cache.update(account.identifier, {"remark": account.remark, "protocol": account.protocol})

        remark = account.remark
        logger.info(f"\n🔎 正在处理 {remark}（{account.protocol}）...")

        task = Script(account, account_info)
        token_valid = False
        try:
            token_valid = bool(account_info.get("token")) and bool(task.sign_in())
        except Exception as exc:
            logger.info(f"⚠️ {remark} token校验异常，准备尝试刷新: {exc}")

        if not token_valid:
            logger.info(f"🔄 {remark} token无效，准备手机号授权包")
            mobile_info, mobile_source = task.prepare_mobile_info()
            if not mobile_info:
                message = (
                    f"⏭️ {remark} 缺少手机号授权包：{mobile_source}。"
                    "请先在对应微信协议账号中手动进入岚财承品并授权手机号一次，再重试。"
                )
                logger.error(message)
                log_list.append(message)
                failed += 1
                continue
            account_info.update(task.info)
            token_cache.set(account.identifier, account_info)
            logger.info(f"📱 {remark} 已准备手机号授权包，来源：{mobile_source}")

            logger.info(f"🔄 {remark} 按 {account.protocol} 协议获取 code")
            try:
                if get_single_code is None:
                    raise ConfigurationError("getCode 模块未加载")
                code = get_single_code(APPID, account.identifier)
                if not code:
                    raise ConfigurationError("getCode 返回空 code")
            except CodeProviderError as exc:
                message = f"❌ {remark} 获取 code 失败：{exc}"
                logger.error(message)
                log_list.append(message)
                failed += 1
                if DELETE_REFRESH_FAILED_CACHE:
                    token_cache.delete(account.identifier)
                continue

            try:
                new_token = task.wxlogin(code, mobile_info)
            except Exception as exc:
                new_token = ""
                logger.error(f"❌ {remark} code 登录异常：{exc}")
            if not new_token:
                message = f"❌ {remark} code 登录未返回新 token；授权包可能已失效，请手动授权后重试"
                logger.error(message)
                log_list.append(message)
                failed += 1
                if DELETE_REFRESH_FAILED_CACHE:
                    token_cache.delete(account.identifier)
                continue

            account_info.update(task.info)
            account_info["token"] = new_token
            account_info["remark"] = remark
            token_cache.set(account.identifier, account_info)
            logger.info(f"✅ {remark} token已刷新并保存")
        else:
            logger.info(f"✅ {remark} token有效，执行后续任务")

        try:
            logger.info(f"▶️ 开始执行账号：{remark}")
            log_list.append(f"▶️ 开始执行账号：{remark}")
            ScriptRuntime(account, account_info)
            logger.info(f"🎉【{remark}】执行完成")
            log_list.append(f"🎉【{remark}】执行完成")
            completed += 1
        except Exception as exc:
            logger.error(f"❌ 处理账号 {remark} 时发生异常: {exc}")
            log_list.append(f"❌ 处理账号 {remark} 时发生异常: {exc}")
            failed += 1
        if index < len(accounts):
            time.sleep(random.uniform(30, 45))

    summary = f"执行完成：成功 {completed}/{len(accounts)}，失败或跳过 {failed}"
    logger.info("\n" + summary)
    log_list.append(summary)
    status = "成功" if failed == 0 else "部分失败"
    send_notification(f"{APP_NAME}｜{status}", "\n".join(log_list))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())