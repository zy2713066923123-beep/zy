#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# cron: 44 09,21 * * *
# name: 天龙泉
"""
天龙泉青龙脚本

功能：
1. 兼容 YYB Go / wechatLoader 获取小程序 code
2. 按小程序首次进入流程调用 app-jingyoujia/login，并缓存 token
3. 查询个人信息 / 积分 / 会员等级 / 任务列表
4. 自动完成每日签到奖励
5. 按顺序完成：日常签到 / 点赞 / 观看视频 / 拍照打卡 / 幸运拍一拍
6. 可选执行积分抽奖；邀请好友任务不执行

约定：
- 账号环境变量：TLYZ_WXID
- 服务地址：YYB_SERVER / WECHAT_SERVER
- 多账号分隔：& 或换行
- 账号备注：# 后为备注，展示保留，请求时去掉

可选开关：
- TLYZ_ENABLE_PHOTO_PUNCH=1      # 拍照打卡，默认开启
- TLYZ_ENABLE_SECOND_BEAT=1      # 幸运拍一拍，默认开启
- TLYZ_ENABLE_TURNTABLE=0        # 积分抽奖，默认关闭
- TLYZ_LIKE_INTERVAL=2            # 点赞请求之间的间隔秒数
- TLYZ_VIDEO_SECONDS=0             # 观看视频秒数，0 表示使用服务端配置

拍照打卡参数：
- 经纬度查询网站：https://jingweidu.bmcx.com
- 固定图片直链：https://a.zdmimg.com/202402/28/65de08ba4403b4087.jpg_e680.jpg   #图片URL  对应89行自行修改
- 同目录备用图片：daka.jpg
- TLYZ_LONGITUDE=110.1797835385929  #经度  对应77行自行修改
- TLYZ_LATITUDE=25.2353435433485  #纬度  对应78行自行修改
- TLYZ_PHOTO_CODE=campChannel

幸运拍一拍参数：
- TLYZ_SECOND_BEAT_DELAY=0.2
- TLYZ_SECOND_BEAT_INTERVAL=20  # 多局之间的等待秒数，避免服务端判定重复点击
- 每次自动在 9.01~9.19 秒之间随机提交
- TLYZ_TURNTABLE_ACTIVITY_ID=活动ID

幸运拍一拍规则：
- 每次消耗 9 积分，每天默认 3 次机会
- 结果值 9.01~9.19 秒为目标区间，最高可得 50 积分
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import mimetypes
import json
import os
import random
import re
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

try:
    import yyb  # 自动同步 yyb_go 存活账号
except Exception:
    yyb = None

try:
    from notify import send as send_notify
except Exception:
    send_notify = None


APP_ID = "wx692c4fa7343becd4"
APP_VERSION = "322"
BASE_REMOTE = "https://myx.tlyzclub.com/tlqcode"
BUSINESS_BASE = f"{BASE_REMOTE}/app-jingyoujia"
APP_LOGIN_URL = f"{BUSINESS_BASE}/login"
ENC_KEY = b"Z0J7M480h6kppf67"
DEFAULT_LONGITUDE = 110.1797835385929
DEFAULT_LATITUDE = 25.2353435433485
TIMEOUT = 20
DEFAULT_ACTIVITY_TYPE = "MOUNTAIN_CLIMBING_2024"
DEFAULT_SHEEP_FEAST_TYPE = "31"
MAX_SECOND_BEAT_ATTEMPTS = 3
DEFAULT_LIKE_COUNT = 3
DEFAULT_LIKE_INTERVAL = 2.0
DEFAULT_VIDEO_SECONDS = 10.0

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_FILE = SCRIPT_DIR / ".tlyz_token_cache.json"
PHOTO_RECORD_URL = "https://a.zdmimg.com/202402/28/65de08ba4403b4087.jpg_e680.jpg"
PHOTO_FILE = SCRIPT_DIR / "daka.jpg"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090c38)XWEB/14185"
)
REFERER = f"https://servicewechat.com/{APP_ID}/{APP_VERSION}/page-frame.html"


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def today_ymd() -> Tuple[int, int, int]:
    dt = datetime.now()
    return dt.year, dt.month, dt.day


def log(msg: str) -> None:
    print(msg, flush=True)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on", "enable", "enabled"}


def split_accounts(raw: str) -> List[str]:
    if not raw:
        return []
    items: List[str] = []
    for part in re.split(r"[&\n]+", raw):
        part = part.strip()
        if part:
            items.append(part)
    return items


def strip_comment(text: str) -> str:
    return text.split("#", 1)[0].strip()


def normalize_business_token(token: Any) -> str:
    """缓存裸 JWT，发送时只保留一个 JYJwx 前缀。"""
    value = str(token or "").strip()
    if value.startswith("JYJwx "):
        return value[6:].strip()
    return value


def parse_account_item(item: str) -> Tuple[str, Optional[str], str]:
    """
    返回：
      display: 原始展示串（保留 # 备注）
      protocol: wl / yyb / None
      account: 去掉前缀和备注后的真实账号值
    """
    display = item.strip()
    main = strip_comment(display)
    protocol = None
    if main.startswith("wl:"):
        protocol = "wl"
        main = main[3:].strip()
    elif main.startswith("yyb:"):
        protocol = "yyb"
        main = main[4:].strip()
    return display, protocol, main


def is_scalar(v: Any) -> bool:
    return isinstance(v, (str, int, float, bool)) or v is None


def walk_scalars(obj: Any) -> Iterable[Any]:
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk_scalars(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_scalars(v)
    elif is_scalar(obj):
        yield obj


def value_matches_account(value: Any, account: str) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        if account.isdigit():
            return str(int(value)) == account
        return False
    if isinstance(value, str):
        return value == account
    return False


def payload_matches_account(payload: Any, account: str) -> bool:
    for scalar in walk_scalars(payload):
        if value_matches_account(scalar, account):
            return True
    return False


def read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_file(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def deep_find_string(obj: Any, keys: Tuple[str, ...]) -> Optional[str]:
    """
    在嵌套对象里按 BFS 找到第一个符合 key 的非空字符串值。
    """
    queue: List[Any] = [obj]
    while queue:
        cur = queue.pop(0)
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in keys and isinstance(v, str) and v.strip():
                    return v.strip()
                queue.append(v)
        elif isinstance(cur, list):
            queue.extend(cur)
    return None


def aes_ecb_encrypt(text: str) -> str:
    cipher = AES.new(ENC_KEY, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(text.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("utf-8")


def response_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        text = resp.text[:500]
        raise RuntimeError(f"响应不是 JSON：HTTP {resp.status_code} {text}")


def service_ok(data: Any, status_code: int = 200) -> bool:
    if status_code == 200:
        if isinstance(data, dict):
            for key in ("code", "Code"):
                if key in data and isinstance(data[key], int):
                    if data[key] not in (0, 200):
                        return False
            for key in ("status", "Success"):
                if key in data and isinstance(data[key], bool) and not data[key]:
                    return False
        return True
    return False


@dataclass
class ServiceState:
    name: str
    base_url: str
    raw_payload: Any = None
    error: Optional[str] = None

    @property
    def available(self) -> bool:
        return self.error is None and self.raw_payload is not None


class TlyzClient:
    def __init__(self, protocol: str, account: str, display: str, server: str):
        self.protocol = protocol
        self.account = account
        self.display = display
        self.server = server.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "xweb_xhr": "1",
                "appId": APP_ID,
                "User-Agent": UA,
                "Referer": REFERER,
                "Origin": "https://servicewechat.com",
            }
        )
        self.cache_key = f"{self.protocol}:{self.account}"
        self.token: Optional[str] = None
        self.auth_info: Dict[str, Any] = {}
        self.open_id: str = os.getenv("TLYZ_OPEN_ID", "").strip()
        self.customer_id: str = os.getenv("TLYZ_CUSTOM_ID", "").strip()
        self.oss_user_id: str = os.getenv("TLYZ_OSS_USER_ID", "").strip()
        self.cache = self._load_cache()
        cached_token = self.cache.get(self.cache_key)
        self.token = normalize_business_token(cached_token) if cached_token else None

    def _load_cache(self) -> Dict[str, str]:
        data = read_json_file(CACHE_FILE, {})
        return data if isinstance(data, dict) else {}

    def _save_cache(self) -> None:
        write_json_file(CACHE_FILE, self.cache)

    def cache_token(self, token: str) -> None:
        self.token = token
        self.cache[self.cache_key] = token
        self._save_cache()

    def clear_token(self) -> None:
        self.token = None
        if self.cache_key in self.cache:
            self.cache.pop(self.cache_key, None)
            self._save_cache()

    def url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return self.server + path

    def business_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return BUSINESS_BASE + path

    @staticmethod
    def remote_url(path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return BASE_REMOTE + path

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        auth: bool = True,
        retry_login: bool = True,
    ) -> Any:
        headers = {}
        if auth:
            if not self.token:
                raise RuntimeError("缺少 token，请先登录")
            headers["Authorization"] = (
                self.token if self.token.startswith("JYJwx ") else f"JYJwx {self.token}"
            )

        resp = self.session.request(
            method=method.upper(),
            url=self.business_url(path),
            params=params,
            json=json_body,
            headers=headers,
            timeout=TIMEOUT,
        )
        data = response_json(resp)

        if retry_login and self.is_unauthorized(data, resp.status_code):
            self.clear_token()
            self.login()
            return self.request(
                method,
                path,
                params=params,
                json_body=json_body,
                auth=auth,
                retry_login=False,
            )

        return data

    @staticmethod
    def is_unauthorized(data: Any, status_code: int) -> bool:
        if status_code == 401:
            return True
        if isinstance(data, dict):
            code = data.get("code", data.get("Code"))
            if code in (401, 403):
                return True
            msg = str(data.get("msg") or data.get("Message") or "").lower()
            if any(x in msg for x in ("unauthorized", "token", "登录", "未授权")):
                return True
        return False

    def get_mini_program_code(self) -> str:
        if self.protocol == "wl":
            body = {"wxid": self.account, "appid": APP_ID}
            data = self.session.post(
                self.url("/api/v1/wx/app/get/code"),
                json=body,
                timeout=TIMEOUT,
            )
            payload = response_json(data)
            code = deep_find_string(payload, ("code", "Code"))
            if code:
                return code
            raise RuntimeError(f"wechatLoader 获取 code 失败：{payload}")

        if self.protocol == "yyb":
            body = {"ref": self.account, "app_id": APP_ID}
            resp = self.session.post(
                self.url("/wxapp/getCode"),
                json=body,
                timeout=TIMEOUT,
            )
            payload = response_json(resp)
            code = deep_find_string(payload, ("code", "Code"))
            if code:
                return code
            raise RuntimeError(f"YYB Go 获取 code 失败：{payload}")

        raise RuntimeError(f"未知协议：{self.protocol}")

    def login(self) -> str:
        code = self.get_mini_program_code()
        resp = self.session.post(
            APP_LOGIN_URL,
            json={"code": code},
            headers={"Authorization": "none"},
            timeout=TIMEOUT,
        )
        payload = response_json(resp)
        if not service_ok(payload, resp.status_code):
            raise RuntimeError(f"业务登录失败：{payload}")
        data = payload.get("data") or payload.get("Data") or {}
        if isinstance(data, dict):
            self.auth_info = data
            self.open_id = self.open_id or str(data.get("openId") or data.get("openid") or "").strip()
            self.customer_id = self.customer_id or str(
                data.get("customerId")
                or data.get("cusId")
                or data.get("id")
                or ""
            ).strip()
        token = deep_find_string(payload, ("accessToken", "token", "Token"))
        if not token:
            raise RuntimeError(f"登录失败，未找到 token：{payload}")
        token = normalize_business_token(token)
        self.cache_token(token)
        return token

    def ensure_login(self) -> None:
        if not self.token:
            self.login()

    def api_get(self, path: str, *, params: Optional[Dict[str, Any]] = None, retry_login: bool = True) -> Any:
        self.ensure_login()
        return self.request("GET", path, params=params, auth=True, retry_login=retry_login)

    def api_post(self, path: str, *, body: Optional[Dict[str, Any]] = None, retry_login: bool = True) -> Any:
        self.ensure_login()
        return self.request("POST", path, json_body=body, auth=True, retry_login=retry_login)

    def get_customer_details(self) -> Any:
        return self.api_get("/app/jingyoujia/customer/detail")

    def query_cust_integral(self) -> Any:
        return self.api_get("/app/jingyoujia/customer/queryCustIntegral")

    def query_cust_member_level(self) -> Any:
        return self.api_get("/business/member/queryCustMemberLevel")

    def query_user_task_list(self) -> Any:
        return self.api_get("/app/jingyoujia/task/queryUserTaskList")

    def query_ugc_excellent_topic_list(self, page_num: int = 1, page_size: int = 20) -> Any:
        return self.api_get(
            "/app/ugcExcellent/queryUgcExcellentTopicList",
            params={"pageNum": page_num, "pageSize": page_size},
        )

    def send_topic_like(self, invoke_type: Any, topic_id: Any, longitude: Any, latitude: Any) -> Any:
        return self.api_post(
            "/app/jingyoujia/ugc/sendTopicLike",
            body={
                "invokeType": invoke_type,
                "topicId": topic_id,
                "longitude": longitude,
                "latitude": latitude,
            },
        )

    def query_video_topic_list(self, page_num: int = 1, page_size: int = 10) -> Any:
        return self.api_get(
            "/app/jingyoujia/ugc/com/queryUgcComTopicList",
            params={
                "invokeType": 7,
                "topicType": 12,
                "pageNum": page_num,
                "pageSize": page_size,
                "channel": "",
                "themeId": "",
            },
        )

    def query_video_reward_seconds(self) -> Any:
        return self.api_get("/app/config/data/type/video_reward_seconds")

    def video_start(self, business_id: Any, latitude: Any, longitude: Any) -> Any:
        return self.api_post(
            "/business/spring2024/videoStart",
            body={
                "businessId": business_id,
                "currentDuration": 0,
                "lat": latitude,
                "lon": longitude,
            },
        )

    def video_complete(
        self,
        business_id: Any,
        watch_id: Any,
        latitude: Any,
        longitude: Any,
    ) -> Any:
        return self.api_post(
            "/business/spring2024/videoComplete",
            body={
                "businessId": business_id,
                "currentDuration": 3,
                "lat": latitude,
                "lon": longitude,
                "watchId": watch_id,
            },
        )

    def view_video(self, latitude: Any, longitude: Any) -> Any:
        return self.api_post(
            "/app/jingyoujia/ugc/run/viewVideo",
            body={"longitude": longitude, "latitude": latitude},
        )

    def judge_exist_photo_punch(self, activity_type: str) -> Any:
        return self.api_get(f"/app/jingyoujia/activityCommon/judgeExistPhotoPunch?activityType={activity_type}")

    def query_drink_punch_info(self, activity_type: str) -> Any:
        return self.api_get(f"/app/jingyoujia/activityCommon/queryDrinkPunchInfo?activityType={activity_type}")

    def get_free_record_list(self, activity_type: str, sheep_feast_type: str = DEFAULT_SHEEP_FEAST_TYPE) -> Any:
        return self.api_get(
            f"/app/jingyoujia/activityCommon/getFreeRecordList?activityType={activity_type}&sheepFeastType={sheep_feast_type}"
        )

    def ai_judge(self, recognition_url: str) -> Any:
        return self.api_post("/app/img/ai/recognition", body={"recognitionUrl": recognition_url})

    def photo_punch(self, activity_type: str, record_url: str, latitude: Any, longitude: Any, code: str = "") -> Any:
        payload = {
            "activityType": activity_type,
            "recordUrl": record_url,
            "latitude": latitude,
            "longitude": longitude,
            "code": code,
        }
        return self.api_post("/app/jingyoujia/activityCommon/photoPunch", body=payload)

    def query_second_beat_config(self) -> Any:
        return self.api_get("/app/jingyoujia/beatSecondConfig/queryConfig")

    def query_second_beat_times(self, config_id: Any) -> Any:
        return self.api_get(f"/app/jingyoujia/beatSecondConfig/queryIntegralAndTimes?configId={config_id}")

    def second_beat_start(self, game_id: Any) -> Any:
        payload = {"gameId": game_id}
        return self.api_post(
            "/app/jingyoujia/beatSecondConfig/starGame",
            body={"v1": aes_ecb_encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))},
        )

    def second_beat_end(self, beat_time: Any, record_id: Any) -> Any:
        payload = {"beatTime": beat_time, "recordId": record_id}
        return self.api_post(
            "/app/jingyoujia/beatSecondConfig/endGame",
            body={"v1": aes_ecb_encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))},
        )

    def query_turntable_goods_list(self) -> Any:
        return self.api_get("/app/jingyoujia/taskHallTurntable/queryTurntableGoodsList")

    def query_turntable_by_act_id(self, activity_id: Any) -> Any:
        return self.api_get(f"/app/jingyoujia/taskHallTurntable/queryTurntableByActId?activityId={activity_id}")

    def get_user_lottery_numbers(self, activity_id: Any) -> Any:
        return self.api_get(f"/app/jingyoujia/taskHallTurntable/getUserLotteryNumbers?activityId={activity_id}")

    def extract_turntable_goods(self, activity_id: Any) -> Any:
        payload = {"activityId": activity_id}
        encrypted = aes_ecb_encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return self.api_post(
            "/app/jingyoujia/taskHallTurntable/extractTurntableGoods",
            body={"v1": encrypted},
        )

    def get_oss_signature(self, file_name: str, file_size: int, content_type: int = 2) -> Any:
        headers = {
            "CANCAL": "mobile",
            "Form-type": "routine",
            "xweb_xhr": "1",
        }
        if self.customer_id:
            headers["CUSTOMAT"] = self.customer_id
        if self.open_id:
            headers["Authorization"] = f"Bearer {self.open_id}"
        if self.oss_user_id:
            headers["TLQUSERID"] = self.oss_user_id
        resp = self.session.post(
            self.remote_url("/mobile/song/getOssSignature"),
            json={"fileName": file_name, "contentType": content_type, "fileSize": file_size},
            headers=headers,
            timeout=TIMEOUT,
        )
        payload = response_json(resp)
        if not service_ok(payload, resp.status_code):
            raise RuntimeError(f"获取 OSS 签名失败：{payload}")
        data = payload.get("data") or payload.get("Data") or {}
        if not isinstance(data, dict):
            raise RuntimeError(f"获取 OSS 签名失败：{payload}")
        return data

    def upload_photo_file(self, file_path: Path) -> str:
        if not file_path.exists():
            raise FileNotFoundError(f"图片不存在：{file_path}")

        file_size = file_path.stat().st_size
        file_name = file_path.name
        sig = self.get_oss_signature(file_name, file_size)
        bucket = str(sig.get("bucket") or "tlqwine").strip()
        region = str(sig.get("region") or "cn-guangzhou").strip()
        dir_prefix = str(sig.get("dir") or "ossUpload/").strip()
        policy = str(sig.get("policy") or "").strip()
        signature = str(sig.get("signature") or "").strip()
        access_id = str(sig.get("accessId") or "").strip()

        if not all((bucket, region, dir_prefix, policy, signature, access_id)):
            raise RuntimeError(f"OSS 签名字段不完整：{sig}")

        day_prefix = datetime.now().strftime("%Y-%m-%d")
        upload_prefix = f"tlq/{datetime.now().strftime('%Y/%m/%d')}/"
        base_dir = f"{dir_prefix}{day_prefix}/{upload_prefix}"
        key = f"{base_dir}image/{file_name}"
        upload_url = f"https://{bucket}.oss-{region}.aliyuncs.com/"
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

        with file_path.open("rb") as fh:
            resp = self.session.post(
                upload_url,
                data={
                    "OSSAccessKeyId": access_id,
                    "signature": signature,
                    "dir": base_dir,
                    "policy": policy,
                    "key": key,
                    "success_action_status": "200",
                },
                files={"file": (file_name, fh, mime_type)},
                timeout=TIMEOUT,
            )

        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(f"OSS 上传失败：HTTP {resp.status_code} {resp.text[:300]}")
        return f"https://{bucket}.oss-{region}.aliyuncs.com/{key}"

    def build_photo_record_url(self) -> str:
        if PHOTO_RECORD_URL:
            return PHOTO_RECORD_URL
        if PHOTO_FILE.exists():
            return self.upload_photo_file(PHOTO_FILE)
        raise RuntimeError("未找到固定图片直链，且同目录不存在 daka.jpg")

    def find_check_task(self) -> Any:
        return self.api_get("/app/jingyoujia/taskContinuousRecord/findCheckTask")

    def query_record(self, task_id: Any) -> Any:
        return self.api_get(f"/app/jingyoujia/taskContinuousRecord/queryRecord?taskId={task_id}")

    def list_cust_user_alow(self, task_id: Any) -> Any:
        return self.api_get(f"/app/jingyoujia/taskContinuousRecord/listCustUserAlow?taskId={task_id}")

    def task_continuous_record(self, task_id: Any, longitude: Any, latitude: Any) -> Any:
        payload = {"taskId": task_id, "longitude": longitude, "latitude": latitude}
        encrypted = aes_ecb_encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return self.api_post("/app/jingyoujia/taskContinuousRecord", body={"v1": encrypted})

    def add_by_alow(self, task_id: Any, alow_day: str, longitude: Any, latitude: Any) -> Any:
        payload = {"alowDay": alow_day, "taskId": task_id, "longitude": longitude, "latitude": latitude}
        encrypted = aes_ecb_encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return self.api_post("/app/jingyoujia/taskContinuousRecord/addByAlow", body={"v1": encrypted})


def load_service_state(name: str, base_url: Optional[str], path: str) -> ServiceState:
    if not base_url:
        return ServiceState(name=name, base_url="", raw_payload=None, error="未配置")
    client = requests.Session()
    try:
        resp = client.get(base_url.rstrip("/") + path, timeout=TIMEOUT)
        payload = response_json(resp)
        return ServiceState(name=name, base_url=base_url, raw_payload=payload)
    except Exception as exc:
        return ServiceState(name=name, base_url=base_url, raw_payload=None, error=str(exc))


def resolve_protocol(
    display: str,
    account: str,
    explicit_protocol: Optional[str],
    wl_state: ServiceState,
    yyb_state: ServiceState,
) -> Tuple[Optional[str], str]:
    if explicit_protocol:
        return explicit_protocol, account

    if account.startswith("wxid_"):
        return "wl", account

    matches: List[str] = []
    if wl_state.available and payload_matches_account(wl_state.raw_payload, account):
        matches.append("wl")
    if yyb_state.available and payload_matches_account(yyb_state.raw_payload, account):
        matches.append("yyb")

    if len(matches) == 1:
        return matches[0], account

    return None, account


def format_task_list(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    basic = data.get("basicList") or []
    grow = data.get("growList") or []
    all_tasks = []
    for item in list(basic) + list(grow):
        if not isinstance(item, dict):
            continue
        name = item.get("taskName") or item.get("name") or item.get("taskTitle") or "未知任务"
        finish = is_truthy(item.get("isFinish"))
        status = "已完成" if finish else "未完成"
        all_tasks.append(f"{name}({status})")
    return "；".join(all_tasks)


def is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def task_item_by_type(task_response: Any, task_type: int) -> Optional[Dict[str, Any]]:
    if not isinstance(task_response, dict):
        return None
    data = task_response.get("data") or task_response.get("Data") or task_response
    if not isinstance(data, dict):
        return None
    for key in ("basicList", "growList", "rows"):
        items = data.get(key) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                current_type = int(item.get("taskType"))
            except (TypeError, ValueError):
                continue
            if current_type == task_type:
                return item
    return None


def task_finished(client: TlyzClient, task_type: int) -> Optional[bool]:
    task_response = client.query_user_task_list()
    item = task_item_by_type(task_response, task_type)
    if item is None:
        return None
    return is_truthy(item.get("isFinish"))


def response_code_and_message(response: Any) -> Tuple[Any, str, Any]:
    if not isinstance(response, dict):
        return None, "", None
    return (
        response.get("code", response.get("Code")),
        str(response.get("msg") or response.get("Message") or ""),
        response.get("data") if "data" in response else response.get("Data"),
    )


def response_rows(response: Any) -> List[Dict[str, Any]]:
    if not isinstance(response, dict):
        return []
    rows = response.get("rows")
    if rows is None:
        data = response.get("data") or response.get("Data")
        rows = data.get("rows") if isinstance(data, dict) else None
    return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def compact_error(message: Any) -> str:
    text = str(message or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180] + ("..." if len(text) > 180 else "")


def compact_task_detail(task_name: str, detail: str) -> str:
    """只保留通知需要的最终结果，避免把接口和数据库堆栈推送出去。"""
    lines = [line.strip() for line in detail.splitlines() if line.strip()]

    if task_name == "签到":
        selected = [
            line
            for line in lines
            if line.startswith(("用户：", "积分：", "会员等级：", "今日签到："))
        ]
        if selected:
            return "\n".join(selected)

    if task_name == "点赞":
        if any("已完成" in line for line in lines):
            return "点赞：已完成"
        count = sum("点赞：成功" in line for line in lines)
        if count:
            return f"点赞：成功（{count}/{DEFAULT_LIKE_COUNT}）"

    if task_name == "观看视频":
        if any("已完成" in line for line in lines):
            return "观看视频：已完成"
        if any(line.startswith("观看视频任务：成功") for line in lines):
            return "观看视频：已完成"
        if any("接口成功但任务状态仍未完成" in line for line in lines):
            return "观看视频：接口成功但任务状态仍未完成"

    if task_name == "拍照打卡":
        if any("已完成" in line or "拍照打卡：成功" in line for line in lines):
            return "拍照打卡：已完成"

    if task_name == "幸运拍一拍":
        if any("次数用完" in line for line in lines):
            return "幸运拍一拍：次数用完"
        attempt_count = sum(bool(re.match(r"第 \d+ 次：", line)) for line in lines)
        win_count = sum("中奖" in line for line in lines)
        reward_total = 0.0
        for line in lines:
            match = re.search(r"奖励 ([\d.]+) 积分", line)
            if match:
                reward_total += float(match.group(1))
        if attempt_count:
            reward_text = f"，奖励 {reward_total:g} 积分" if reward_total else ""
            return f"幸运拍一拍：完成 {attempt_count} 次，中奖 {win_count} 次{reward_text}"

    if task_name == "积分抽奖":
        if any("次数用完" in line for line in lines):
            return "积分抽奖：次数用完"
        if any("成功" in line for line in lines):
            prize = next((line for line in lines if line.startswith("中奖：")), "")
            return f"积分抽奖：成功{f'，{prize}' if prize else ''}"

    for line in reversed(lines):
        if any(word in line for word in ("失败", "异常", "未找到", "没有", "提醒", "频繁")):
            return f"{task_name}：{compact_error(line)}"
    return f"{task_name}：{compact_error(lines[-1] if lines else '无结果')}"


def extract_task_id(task_data: Any) -> Optional[Any]:
    if isinstance(task_data, dict):
        for key in ("id", "taskId", "task_id"):
            val = task_data.get(key)
            if val not in (None, ""):
                return val
    return None


def parse_alow_day(raw: str) -> Optional[str]:
    raw = (raw or "").strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    if re.fullmatch(r"\d{1,2}", raw):
        year, month, _ = today_ymd()
        return f"{year:04d}-{month:02d}-{int(raw):02d}"
    return None


def get_env_float(name: str, default: float = 0.0) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def get_photo_location() -> Tuple[float, float]:
    longitude = get_env_float("TLYZ_LONGITUDE", DEFAULT_LONGITUDE)
    latitude = get_env_float("TLYZ_LATITUDE", DEFAULT_LATITUDE)
    return longitude, latitude


def mask_mobile(value: Any) -> str:
    text = str(value or "-").strip()
    if len(text) >= 7:
        return f"{text[:3]}****{text[-4:]}"
    return "****" if text not in {"", "-"} else text


def extract_dict(data: Any) -> Dict[str, Any]:
    if isinstance(data, dict):
        return data
    return {}


def extract_text_value(obj: Any, keys: Tuple[str, ...] = ()) -> str:
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return str(obj)
    if isinstance(obj, dict):
        for key in keys:
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return str(val)
        for val in obj.values():
            found = extract_text_value(val, keys)
            if found:
                return found
    if isinstance(obj, list):
        for item in obj:
            found = extract_text_value(item, keys)
            if found:
                return found
    return ""


def sign_one_account(client: TlyzClient) -> Tuple[bool, str]:
    lines: List[str] = []
    alow_day = parse_alow_day(os.getenv("TLYZ_SIGN_CARD_DAY", ""))

    details = client.get_customer_details()
    if isinstance(details, dict):
        info = details.get("data") or details.get("Data") or {}
        if isinstance(info, dict):
            nickname = info.get("nickName") or info.get("nickname") or "-"
            mobile = info.get("mobile") or "-"
            lines.append(f"用户：{nickname} | 手机：{mask_mobile(mobile)}")

    try:
        integral = client.query_cust_integral()
        if isinstance(integral, dict):
            lines.append(f"积分：{integral.get('data', integral.get('Data', '-'))}")
    except Exception as exc:
        lines.append(f"查询积分失败：{exc}")

    try:
        level = client.query_cust_member_level()
        if isinstance(level, dict):
            data = level.get("data") or level.get("Data") or {}
            if isinstance(data, dict):
                level_name = data.get("currentLevelName") or data.get("levelName") or data.get("name")
                if level_name:
                    lines.append(f"会员等级：{level_name}")
    except Exception as exc:
        lines.append(f"查询会员等级失败：{exc}")

    try:
        task_list = client.query_user_task_list()
        if isinstance(task_list, dict):
            data = task_list.get("data") or task_list.get("Data") or {}
            task_text = format_task_list(data)
            if task_text:
                lines.append(f"任务：{task_text}")
    except Exception as exc:
        lines.append(f"查询任务列表失败：{exc}")

    check_task = client.find_check_task()
    if not isinstance(check_task, dict):
        raise RuntimeError(f"findCheckTask 返回异常：{check_task}")

    task_data = check_task.get("data") or check_task.get("Data")
    if not task_data:
        return False, "\n".join(lines + ["当前没有可签到活动"])

    task_id = extract_task_id(task_data)
    if task_id is None:
        return False, "\n".join(lines + [f"未找到签到 taskId：{task_data}"])

    try:
        alow_count = client.list_cust_user_alow(task_id)
        if isinstance(alow_count, dict):
            count_data = alow_count.get("data", alow_count.get("Data"))
            if count_data is not None:
                lines.append(f"签到卡：{count_data}")
    except Exception as exc:
        lines.append(f"查询签到卡失败：{exc}")

    record = client.query_record(task_id)
    if isinstance(record, dict):
        record_data = record.get("data") or record.get("Data") or {}
        today_finish = bool(record_data.get("todayFinish")) if isinstance(record_data, dict) else False
        continuous_num = record_data.get("continuousNum") if isinstance(record_data, dict) else None
        if today_finish:
            lines.append(f"今日签到：已完成{f'，连续天数 {continuous_num}' if continuous_num is not None else ''}")
            return True, "\n".join(lines)
    else:
        lines.append(f"queryRecord 返回异常：{record}")

    local_lon, local_lat = get_photo_location()

    if alow_day:
        sign_card_resp = client.add_by_alow(task_id, alow_day, local_lon, local_lat)
        if not isinstance(sign_card_resp, dict):
            raise RuntimeError(f"补签返回异常：{sign_card_resp}")
        code = sign_card_resp.get("code", sign_card_resp.get("Code"))
        msg = sign_card_resp.get("msg", sign_card_resp.get("Message", ""))
        data = sign_card_resp.get("data") or sign_card_resp.get("Data") or {}
        if code == 200:
            reward = None
            if isinstance(data, dict):
                reward = data.get("currentSignIntegral")
            lines.append(f"补签[{alow_day}]：成功{f'，奖励 {reward} 积分' if reward is not None else ''}")
            return True, "\n".join(lines)
        raise RuntimeError(f"补签失败：code={code} msg={msg} data={data}")

    sign_resp = client.task_continuous_record(task_id, local_lon, local_lat)
    if not isinstance(sign_resp, dict):
        raise RuntimeError(f"签到返回异常：{sign_resp}")

    code = sign_resp.get("code", sign_resp.get("Code"))
    msg = sign_resp.get("msg", sign_resp.get("Message", ""))
    data = sign_resp.get("data") or sign_resp.get("Data") or {}

    if code in (2001, "2001"):
        lines.append("今日签到：需要先在小程序内点击一次‘授权手机号’")
        return False, "\n".join(lines)

    if code == 20230529:
        lines.append("今日签到：触发风控/验证码")
        return False, "\n".join(lines)

    if code == 200:
        reward = None
        if isinstance(data, dict):
            reward = data.get("currentSignIntegral")
        lines.append(f"今日签到：成功{f'，奖励 {reward} 积分' if reward is not None else ''}")
        try:
            new_integral = client.query_cust_integral()
            if isinstance(new_integral, dict):
                lines.append(f"签到后积分：{new_integral.get('data', new_integral.get('Data', '-'))}")
        except Exception:
            pass
        return True, "\n".join(lines)

    raise RuntimeError(f"签到失败：code={code} msg={msg} data={data}")


def like_one_account(client: TlyzClient) -> Tuple[bool, str]:
    lines: List[str] = []
    finished = task_finished(client, 16)
    if finished is True:
        return True, "点赞任务：已完成"

    longitude, latitude = get_photo_location()
    topics = response_rows(client.query_ugc_excellent_topic_list())
    liked = 0
    seen_topic_ids = set()
    interval = max(0.0, get_env_float("TLYZ_LIKE_INTERVAL", DEFAULT_LIKE_INTERVAL))

    for topic in topics:
        topic_id = topic.get("topicId") or topic.get("id")
        if topic_id in (None, "") or str(topic_id) in seen_topic_ids:
            continue
        seen_topic_ids.add(str(topic_id))
        if is_truthy(topic.get("alreadyLike")):
            continue

        if liked and interval:
            time.sleep(interval)
        response = client.send_topic_like(1, topic_id, longitude, latitude)
        code, message, data = response_code_and_message(response)
        if code in (200, "200"):
            liked += 1
            reward = data.get("rewardNum") if isinstance(data, dict) else None
            reward_text = f"，奖励 {reward} 积分" if reward is not None and reward != -2 else ""
            lines.append(f"第 {liked} 次点赞：成功{reward_text}")
            if liked >= DEFAULT_LIKE_COUNT:
                break
            continue

        if "操作频繁" in message:
            lines.append("点赞：服务端提示操作频繁，停止后续请求")
            break
        lines.append(f"点赞请求失败：code={code} msg={message} data={data}")

    if liked >= DEFAULT_LIKE_COUNT:
        lines.append("点赞任务：成功")
        return True, "\n".join(lines)
    if not topics:
        lines.append("点赞任务：未找到可用内容")
    else:
        lines.append(f"点赞任务：仅完成 {liked}/{DEFAULT_LIKE_COUNT} 次")
    return False, "\n".join(lines)


def watch_video_one_account(client: TlyzClient) -> Tuple[bool, str]:
    lines: List[str] = []
    finished = task_finished(client, 15)
    if finished is True:
        return True, "观看视频任务：已完成"

    rows = response_rows(client.query_video_topic_list())
    video = next((item for item in rows if item.get("id") not in (None, "")), None)
    if video is None:
        return False, "观看视频任务：未找到可用视频"

    business_id = video.get("id")
    title = video.get("topic") or video.get("content") or business_id
    longitude, latitude = get_photo_location()
    configured_seconds = DEFAULT_VIDEO_SECONDS
    try:
        config_response = client.query_video_reward_seconds()
        config_value = extract_text_value(config_response, ("configValue",))
        if config_value:
            configured_seconds = float(config_value)
    except Exception as exc:
        lines.append(f"读取观看时长配置失败，使用默认值 {DEFAULT_VIDEO_SECONDS:g} 秒：{exc}")

    requested_seconds = get_env_float("TLYZ_VIDEO_SECONDS", 0.0)
    watch_seconds = requested_seconds if requested_seconds > 0 else configured_seconds
    watch_seconds = max(1.0, min(watch_seconds, 120.0))
    lines.append(f"视频：{title}")
    lines.append(f"观看时长：{watch_seconds:g} 秒")

    start_response = client.video_start(business_id, latitude, longitude)
    start_code, start_message, start_data = response_code_and_message(start_response)
    if start_code not in (200, "200"):
        raise RuntimeError(
            f"观看视频开始失败：code={start_code} msg={start_message} data={start_data}"
        )

    watch_id = extract_text_value(start_data, ("watchId", "watch_id"))
    if not watch_id and isinstance(start_response, dict):
        watch_id = str(start_response.get("msg") or "").strip()
    if not watch_id:
        raise RuntimeError(f"观看视频开始成功但未找到 watchId：{start_response}")

    log(f"观看视频：播放中，等待 {watch_seconds:g} 秒")
    time.sleep(watch_seconds)
    complete_response = client.video_complete(business_id, watch_id, latitude, longitude)
    complete_code, complete_message, complete_data = response_code_and_message(complete_response)
    if complete_code not in (200, "200"):
        raise RuntimeError(
            f"观看视频完成失败：code={complete_code} msg={complete_message} data={complete_data}"
        )

    # videoStart/videoComplete 只记录播放过程，viewVideo 才是任务中心的完成接口。
    view_response = client.view_video(latitude, longitude)
    view_code, view_message, view_data = response_code_and_message(view_response)
    if view_code not in (200, "200"):
        raise RuntimeError(
            f"观看视频任务提交失败：code={view_code} msg={view_message} data={view_data}"
        )
    reward = view_data.get("integral") if isinstance(view_data, dict) else None
    if reward is not None:
        lines.append(f"任务奖励：{reward} 积分")

    final_status = task_finished(client, 15)
    if final_status is False:
        lines.append("观看视频任务：接口成功但任务状态仍未完成")
        return False, "\n".join(lines)
    lines.append("观看视频任务：成功")
    return True, "\n".join(lines)


def photo_punch_one_account(client: TlyzClient) -> Tuple[bool, str]:
    lines: List[str] = []
    activity_type = DEFAULT_ACTIVITY_TYPE
    lines.append(f"活动类型：{activity_type}")

    try:
        status = client.judge_exist_photo_punch(activity_type)
        if isinstance(status, dict):
            data = extract_dict(status.get("data") or status.get("Data"))
            if data:
                already = bool(data.get("alreadySign"))
                record_total = data.get("recordTotalNumber")
                month_total = data.get("monthTotalNumber")
                if record_total is not None:
                    lines.append(f"累计打卡：{record_total}")
                if month_total is not None:
                    lines.append(f"本月次数：{month_total}")
                if already:
                    return True, "\n".join(lines + ["今日拍照打卡：已完成"])
    except Exception as exc:
        lines.append(f"查询今日状态失败：{exc}")

    try:
        free_list = client.get_free_record_list(activity_type)
        if isinstance(free_list, dict):
            data = free_list.get("data") or free_list.get("Data")
            if isinstance(data, list):
                lines.append(f"展示记录：{len(data)} 条")
    except Exception as exc:
        lines.append(f"查询展示记录失败：{exc}")

    try:
        drink_info = client.query_drink_punch_info(activity_type)
        if isinstance(drink_info, dict):
            data = extract_dict(drink_info.get("data") or drink_info.get("Data"))
            if data:
                awards = data.get("awards")
                if isinstance(awards, list):
                    lines.append(f"奖励档位：{len(awards)} 个")
                record_total = data.get("recordTotalNumber")
                if record_total is not None:
                    lines.append(f"当前记录：{record_total}")
    except Exception as exc:
        lines.append(f"查询奖励信息失败：{exc}")

    record_url = client.build_photo_record_url()
    lines.append(f"打卡图片：{record_url}")

    ai_resp = client.ai_judge(record_url)
    ai_ok = False
    if isinstance(ai_resp, dict):
        ai_ok = ai_resp.get("code") in (0, 200) and bool(ai_resp.get("data"))
    if not ai_ok:
        raise RuntimeError(f"图片识别失败：{ai_resp}")

    longitude, latitude = get_photo_location()
    code = os.getenv("TLYZ_PHOTO_CODE", "").strip()
    punch_resp = client.photo_punch(activity_type, record_url, latitude=latitude, longitude=longitude, code=code)
    if not isinstance(punch_resp, dict):
        raise RuntimeError(f"拍照打卡返回异常：{punch_resp}")

    punch_code = punch_resp.get("code", punch_resp.get("Code"))
    punch_msg = punch_resp.get("msg", punch_resp.get("Message", ""))
    punch_data = punch_resp.get("data") or punch_resp.get("Data") or {}
    if punch_code == 200:
        if isinstance(punch_data, dict):
            record_value = punch_data.get("recordValue")
            record_total = punch_data.get("recordTotalNumber")
            if record_value is not None:
                lines.append(f"本次打卡值：{record_value}")
            if record_total is not None:
                lines.append(f"累计打卡：{record_total}")
        lines.append("拍照打卡：成功")
        return True, "\n".join(lines)

    if punch_code == 20230529:
        return False, "\n".join(lines + ["拍照打卡：触发验证码"])

    raise RuntimeError(f"拍照打卡失败：code={punch_code} msg={punch_msg} data={punch_data}")


def second_beat_one_account(client: TlyzClient) -> Tuple[bool, str]:
    lines: List[str] = []

    cfg_resp = client.query_second_beat_config()
    if not isinstance(cfg_resp, dict):
        raise RuntimeError(f"拍一拍配置返回异常：{cfg_resp}")
    cfg_code = cfg_resp.get("code", cfg_resp.get("Code"))
    cfg_msg = cfg_resp.get("msg", cfg_resp.get("Message", ""))
    cfg_data = cfg_resp.get("data") or cfg_resp.get("Data") or {}
    if cfg_code != 200:
        raise RuntimeError(f"拍一拍配置失败：code={cfg_code} msg={cfg_msg} data={cfg_data}")

    if not isinstance(cfg_data, dict):
        raise RuntimeError(f"拍一拍配置异常：{cfg_data}")

    config_id = cfg_data.get("id") or cfg_data.get("configId") or cfg_data.get("activityId") or 1
    activity_status = cfg_data.get("activityStatus")
    if activity_status is not None:
        lines.append(f"活动状态：{activity_status}")
    lines.append(f"活动ID：{config_id}")

    times_resp = client.query_second_beat_times(config_id)
    if not isinstance(times_resp, dict):
        raise RuntimeError(f"拍一拍次数返回异常：{times_resp}")
    times_code = times_resp.get("code", times_resp.get("Code"))
    times_msg = times_resp.get("msg", times_resp.get("Message", ""))
    times_data = times_resp.get("data") or times_resp.get("Data") or {}
    if times_code != 200:
        raise RuntimeError(f"拍一拍次数查询失败：code={times_code} msg={times_msg} data={times_data}")

    if not isinstance(times_data, dict):
        raise RuntimeError(f"拍一拍次数异常：{times_data}")

    last_times = times_data.get("lastTimes")
    if last_times is None:
        last_times = times_data.get("userTimes") or times_data.get("times") or 0
    try:
        last_times_num = int(last_times)
    except Exception:
        last_times_num = 0
    lines.append(f"剩余次数：{last_times_num}")

    if last_times_num <= 0:
        return False, "\n".join(lines + ["幸运拍一拍：次数用完"])

    attempt_count = min(last_times_num, MAX_SECOND_BEAT_ATTEMPTS)
    lines.append(f"本次执行：{attempt_count} 次，每次消耗 9 积分")
    completed = 0
    for attempt in range(1, attempt_count + 1):
        if attempt > 1:
            interval = max(0.0, get_env_float("TLYZ_SECOND_BEAT_INTERVAL", 20.0))
            if interval:
                wait_text = f"幸运拍一拍：等待 {interval:g} 秒后开始第 {attempt} 次"
                lines.append(wait_text)
                log(wait_text)
                time.sleep(interval)

        start_resp = client.second_beat_start(config_id)
        if not isinstance(start_resp, dict):
            raise RuntimeError(f"拍一拍开始返回异常：{start_resp}")
        start_code = start_resp.get("code", start_resp.get("Code"))
        start_msg = start_resp.get("msg", start_resp.get("Message", ""))
        start_data = start_resp.get("data") or start_resp.get("Data")
        if start_code not in (200, "200"):
            if "操作频繁" in str(start_msg):
                lines.append(f"第 {attempt} 次：服务端提示操作频繁，停止后续尝试")
                break
            raise RuntimeError(f"拍一拍开始失败：code={start_code} msg={start_msg} data={start_data}")

        record_id = extract_text_value(start_data, ("recordId", "id"))
        if not record_id:
            record_id = extract_text_value(start_resp, ("recordId", "id"))
        if not record_id:
            raise RuntimeError(f"拍一拍开始成功但未找到 recordId：{start_resp}")

        delay = max(0.0, get_env_float("TLYZ_SECOND_BEAT_DELAY", 0.2))
        time.sleep(delay)
        result_num = f"{random.randint(901, 919) / 100:.2f}"
        end_resp = client.second_beat_end(result_num, record_id)
        if not isinstance(end_resp, dict):
            raise RuntimeError(f"拍一拍结束返回异常：{end_resp}")
        end_code = end_resp.get("code", end_resp.get("Code"))
        end_msg = end_resp.get("msg", end_resp.get("Message", ""))
        end_data = end_resp.get("data") or end_resp.get("Data") or {}
        if end_code not in (200, "200"):
            raise RuntimeError(f"拍一拍结束失败：code={end_code} msg={end_msg} data={end_data}")

        reward = end_data.get("integral") if isinstance(end_data, dict) else None
        prize_status = end_data.get("prizeStatus") if isinstance(end_data, dict) else None
        reward_text = f"，奖励 {reward} 积分" if reward is not None else ""
        status_text = "中奖" if prize_status else "未中奖"
        lines.append(f"第 {attempt} 次：{status_text}{reward_text}，结果值 {result_num}")
        completed += 1

    return completed == attempt_count, "\n".join(lines)


def turntable_one_account(client: TlyzClient) -> Tuple[bool, str]:
    lines: List[str] = []
    activity_id = os.getenv("TLYZ_TURNTABLE_ACTIVITY_ID", "").strip()

    if activity_id:
        resp = client.query_turntable_by_act_id(activity_id)
    else:
        resp = client.query_turntable_goods_list()

    if not isinstance(resp, dict):
        raise RuntimeError(f"转盘活动返回异常：{resp}")
    code = resp.get("code", resp.get("Code"))
    msg = resp.get("msg", resp.get("Message", ""))
    data = resp.get("data") or resp.get("Data") or {}
    if code != 200:
        raise RuntimeError(f"转盘活动查询失败：code={code} msg={msg} data={data}")

    if not isinstance(data, dict):
        raise RuntimeError(f"转盘活动数据异常：{data}")

    turntable_id = data.get("id") or data.get("activityId") or activity_id
    if not turntable_id:
        raise RuntimeError(f"未找到转盘活动 ID：{data}")
    activity_name = data.get("activityName") or data.get("content") or "积分抽奖"
    cost_num = data.get("costNum")
    if activity_name:
        lines.append(f"活动：{activity_name}")
    if cost_num is not None:
        lines.append(f"消耗积分：{cost_num}")

    goods_list = data.get("awardDetailList") or data.get("goodsList") or data.get("turntableList") or []
    if isinstance(goods_list, list):
        lines.append(f"奖品数：{len(goods_list)}")

    num_resp = client.get_user_lottery_numbers(turntable_id)
    if not isinstance(num_resp, dict):
        raise RuntimeError(f"查询抽奖次数返回异常：{num_resp}")
    num_code = num_resp.get("code", num_resp.get("Code"))
    num_msg = num_resp.get("msg", num_resp.get("Message", ""))
    num_data = num_resp.get("data") or num_resp.get("Data") or {}
    if num_code != 200:
        raise RuntimeError(f"查询抽奖次数失败：code={num_code} msg={num_msg} data={num_data}")

    if not isinstance(num_data, dict):
        raise RuntimeError(f"查询抽奖次数数据异常：{num_data}")

    left_num = num_data.get("userLotteryNumbers") or num_data.get("leftNum") or 0
    try:
        left_num_num = int(left_num)
    except Exception:
        left_num_num = 0
    lines.append(f"剩余次数：{left_num_num}")

    if left_num_num <= 0:
        return False, "\n".join(lines + ["积分抽奖：次数用完"])

    draw_resp = client.extract_turntable_goods(turntable_id)
    if not isinstance(draw_resp, dict):
        raise RuntimeError(f"抽奖返回异常：{draw_resp}")
    draw_code = draw_resp.get("code", draw_resp.get("Code"))
    draw_msg = draw_resp.get("msg", draw_resp.get("Message", ""))
    draw_data = draw_resp.get("data") or draw_resp.get("Data") or {}

    if draw_code == 200:
        if isinstance(draw_data, dict):
            award_name = draw_data.get("awardName") or draw_data.get("name")
            award_type = draw_data.get("awardType")
            if award_name:
                lines.append(f"中奖：{award_name}")
            if award_type is not None:
                lines.append(f"奖品类型：{award_type}")
        lines.append("积分抽奖：成功")
        try:
            fresh_num = client.get_user_lottery_numbers(turntable_id)
            if isinstance(fresh_num, dict):
                fresh_data = fresh_num.get("data") or fresh_num.get("Data") or {}
                if isinstance(fresh_data, dict) and fresh_data.get("userLotteryNumbers") is not None:
                    lines.append(f"剩余次数更新：{fresh_data.get('userLotteryNumbers')}")
        except Exception:
            pass
        return True, "\n".join(lines)

    if draw_code == 20230529:
        return False, "\n".join(lines + ["积分抽奖：触发验证码"])

    raise RuntimeError(f"积分抽奖失败：code={draw_code} msg={draw_msg} data={draw_data}")


def load_accounts_from_env() -> List[str]:
    env = os.getenv("TLYZ_WXID", "")
    if env.strip():
        return split_accounts(env)
    # 未配置 TLYZ_WXID 时，自动从 yyb_go 拉取存活账号
    if yyb is None:
        log("未配置 TLYZ_WXID，且未安装 yyb 模块，结束")
        return []
    try:
        ids = yyb.resolve_accounts()
        if not ids:
            log("未配置 TLYZ_WXID，且 yyb 无存活账号，结束")
            return []
        log(f"自动从 yyb_go 同步到 {len(ids)} 个存活账号")
        return [f"yyb:{acc}" for acc in ids]
    except Exception as exc:
        log(f"自动拉取 yyb 账号失败：{exc}")
        return []


def needs_protocol_lookup(accounts: List[str]) -> bool:
    for raw in accounts:
        _, explicit_protocol, account = parse_account_item(raw)
        if account and not explicit_protocol and not account.startswith("wxid_"):
            return True
    return False


def load_remote_state() -> Tuple[ServiceState, ServiceState]:
    wl_server = os.getenv("WECHAT_SERVER", "").strip()
    yyb_server = os.getenv("YYB_SERVER", "").strip()

    states = {
        "wl": ServiceState("wechatLoader", "", None, "未配置"),
        "yyb": ServiceState("YYB Go", "", None, "未配置"),
    }
    jobs = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        if wl_server:
            jobs["wl"] = executor.submit(
                load_service_state,
                "wechatLoader",
                wl_server,
                "/api/v1/wx/user/status",
            )
        if yyb_server:
            jobs["yyb"] = executor.submit(load_service_state, "YYB Go", yyb_server, "/accounts")
        for key, job in jobs.items():
            states[key] = job.result()

    return states["wl"], states["yyb"]


def print_task_result(
    display: str,
    protocol: str,
    task_name: str,
    detail: str,
    results_for_notify: List[str],
) -> None:
    compact_detail = compact_task_detail(task_name, detail)
    output = "\n".join(f"    {line}" for line in compact_detail.splitlines())
    log(output)
    results_for_notify.append(f"{display} ({protocol})\n{compact_detail}")


def main() -> None:
    accounts = load_accounts_from_env()
    if not accounts:
        log("未找到 TLYZ_WXID，结束")
        return

    log(f"天龙泉脚本开始 | {now_str()} | 账号数 {len(accounts)}")
    if needs_protocol_lookup(accounts):
        log("正在读取服务账号列表...")
        wl_state, yyb_state = load_remote_state()
    else:
        wl_state = ServiceState("wechatLoader", "", None, "本次无需读取")
        yyb_state = ServiceState("YYB Go", "", None, "本次无需读取")

    if wl_state.error:
        log(f"wechatLoader 状态：{wl_state.error}")
    else:
        log("wechatLoader 状态：已读取")
    if yyb_state.error:
        log(f"YYB Go 状态：{yyb_state.error}")
    else:
        log("YYB Go 状态：已读取")

    enable_photo_punch = env_bool("TLYZ_ENABLE_PHOTO_PUNCH", True)
    enable_second_beat = env_bool("TLYZ_ENABLE_SECOND_BEAT", True)
    enable_turntable = env_bool("TLYZ_ENABLE_TURNTABLE", False)
    if enable_photo_punch:
        log("拍照打卡：开启")
    else:
        log("拍照打卡：关闭")
    if enable_second_beat:
        log("幸运拍一拍：开启")
    else:
        log("幸运拍一拍：关闭")
    log("任务顺序：日常签到 -> 点赞 -> 观看视频 -> 拍照打卡 -> 幸运拍一拍")
    log("邀请好友：跳过")
    if enable_turntable:
        log("积分抽奖：开启")
    else:
        log("积分抽奖：关闭")

    results_for_notify: List[str] = []

    for idx, raw in enumerate(accounts, 1):
        display, explicit_protocol, account = parse_account_item(raw)
        if not account:
            log(f"[{idx}] 跳过空账号：{display}")
            continue

        protocol, normalized = resolve_protocol(display, account, explicit_protocol, wl_state, yyb_state)
        if protocol is None:
            log(f"[{idx}] {display} -> 无法判断协议，请加 wl: 或 yyb:")
            results_for_notify.append(f"{display}\n无法判断协议，请加 wl: 或 yyb:")
            continue

        if protocol == "wl":
            server = os.getenv("WECHAT_SERVER", "").strip()
        else:
            server = os.getenv("YYB_SERVER", "").strip()
            if not server and yyb is not None:
                server = yyb.get_global_server_url()
        if not server:
            log(f"[{idx}] {display} -> 协议 {protocol} 但未配置对应服务地址")
            results_for_notify.append(f"{display}\n未配置对应服务地址")
            continue

        client = TlyzClient(protocol, normalized, display, server)
        try:
            log(f"[{idx}] {display} [{protocol}]")
            if client.token:
                log(f"[{idx}] {display} -> 命中 token 缓存")
            else:
                log(f"[{idx}] {display} -> 开始登录")
                client.login()

            log("    日常签到：执行中")
            _, detail = sign_one_account(client)
            print_task_result(display, protocol, "签到", detail, results_for_notify)

            try:
                log("    点赞：执行中")
                _, like_detail = like_one_account(client)
                print_task_result(display, protocol, "点赞", like_detail, results_for_notify)
            except Exception as exc:
                msg = compact_error(exc)
                log(f"    点赞失败：{msg}")
                results_for_notify.append(f"{display} ({protocol})\n点赞失败：{msg}")

            try:
                log("    观看视频：执行中")
                _, video_detail = watch_video_one_account(client)
                print_task_result(display, protocol, "观看视频", video_detail, results_for_notify)
            except Exception as exc:
                msg = compact_error(exc)
                log(f"    观看视频失败：{msg}")
                results_for_notify.append(f"{display} ({protocol})\n观看视频失败：{msg}")

            if enable_photo_punch:
                try:
                    log("    拍照打卡：执行中")
                    _, punch_detail = photo_punch_one_account(client)
                    print_task_result(display, protocol, "拍照打卡", punch_detail, results_for_notify)
                except Exception as exc:
                    msg = compact_error(exc)
                    log(f"    拍照打卡失败：{msg}")
                    results_for_notify.append(f"{display} ({protocol})\n拍照打卡失败：{msg}")

            if enable_second_beat:
                try:
                    log("    幸运拍一拍：执行中")
                    _, beat_detail = second_beat_one_account(client)
                    print_task_result(display, protocol, "幸运拍一拍", beat_detail, results_for_notify)
                except Exception as exc:
                    msg = compact_error(exc)
                    log(f"    幸运拍一拍失败：{msg}")
                    results_for_notify.append(f"{display} ({protocol})\n幸运拍一拍失败：{msg}")

            if enable_turntable:
                try:
                    log("    积分抽奖：执行中")
                    _, turn_detail = turntable_one_account(client)
                    print_task_result(display, protocol, "积分抽奖", turn_detail, results_for_notify)
                except Exception as exc:
                    msg = compact_error(exc)
                    log(f"    积分抽奖失败：{msg}")
                    results_for_notify.append(f"{display} ({protocol})\n积分抽奖失败：{msg}")
        except Exception as exc:
            msg = compact_error(exc)
            log(f"[{idx}] {display} [{protocol}] 失败：{msg}")
            results_for_notify.append(f"{display} ({protocol})\n失败：{msg}")

    log(f"天龙泉脚本结束 | {now_str()}")

    if send_notify and results_for_notify:
        try:
            send_notify("天龙泉", "\n\n".join(results_for_notify))
        except Exception as exc:
            log(f"通知发送失败：{exc}")


if __name__ == "__main__":
    main()
