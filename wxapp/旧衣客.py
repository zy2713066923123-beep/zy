#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 旧衣客
"""
cron: 52 11,23 * * *
变量:
  export WX_SERVER='http://127.0.0.1:8000'
  export WX_ID="wxid#备注"
  多账号用换行 或 @ 分隔
"""

from __future__ import annotations
import yyb  # 自动同步 yyb_go 存活账号

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SCRIPT_NAME = "旧衣客"
ENV_NAME = (os.getenv("JYK_ENV_NAME") or "wxjyk").strip()
TARGET_APPID = (os.getenv("JYK_APPID") or "wx3f0209cc35a953a4").strip()
TARGET_VERSION = (os.getenv("JYK_VERSION") or "68").strip()
BASE_URL = (os.getenv("JYK_BASE") or "https://jyk.scjyx.com").strip().rstrip("/")
PAYCONFIG_ID = (os.getenv("JYK_PAYCONFIG_ID") or "2").strip()
PID = (os.getenv("JYK_PID") or "").strip()
DEVICE_INFO = (os.getenv("JYK_DEVICE_INFO") or "android_MEIZU_22_370").strip()

DO_NORMAL = str(os.getenv("JYK_DO_NORMAL", "1")).lower() in ("1", "true", "yes", "on")
DO_AD = str(os.getenv("JYK_DO_AD", "1")).lower() in ("1", "true", "yes", "on")
DO_GIFT = str(os.getenv("JYK_DO_GIFT", "1")).lower() in ("1", "true", "yes", "on")
DO_FIRST = str(os.getenv("JYK_DO_FIRST", "1")).lower() in ("1", "true", "yes", "on")
DO_RAIN = str(os.getenv("JYK_DO_RAIN", "1")).lower() in ("1", "true", "yes", "on")
AD_CHECKIN_TIMES = max(0, int(os.getenv("JYK_AD_TIMES", "7") or "7"))
RAIN_TIMES = max(0, int(os.getenv("JYK_RAIN_TIMES", "5") or "5"))
SIGN_DELAY_SECONDS = max(0, float(os.getenv("JYK_SIGN_DELAY", "0") or "0"))
AD_COOLDOWN_WAIT = str(os.getenv("JYK_AD_COOLDOWN", "1")).lower() in ("1", "true", "yes", "on")
USE_CACHE = str(os.getenv("JYK_USE_CACHE", "1")).lower() in ("1", "true", "yes", "on")
DEBUG = str(os.getenv("JYK_DEBUG", "0")).lower() in ("1", "true", "yes", "on")

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 16; MEIZU 22 "
    "Build/BQ2A.251110.001-BP2A.250605.031.A3; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/146.0.7680.178 Mobile Safari/537.36 "
    "MicroMessenger/8.0.60.2860(0x28003C37) WeChat/arm64 "
    "Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android"
)
REQUEST_TIMEOUT = 30
RETRY_TIMES = 3
RETRY_BASE_DELAY = 3


def normalize_wechat_server(raw: str) -> str:
    server = (raw or "http://127.0.0.1:8000").strip().rstrip("/")
    if not server:
        return "http://127.0.0.1:8000"
    if not server.startswith(("http://", "https://")):
        server = "http://" + server
    for suffix in ("/api/v1", "/api"):
        if server.lower().endswith(suffix):
            server = server[: -len(suffix)].rstrip("/")
            break
    return server or "http://127.0.0.1:8000"


def resolve_local_path(name: str) -> Path:
    path = Path(name).expanduser()
    if path.is_absolute():
        return path
    base = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
    return base / path


WECHAT_SERVER_RAW = (
    os.getenv("WX_SERVER") or os.getenv("WECHAT_SERVER") or os.getenv("YYB_SERVER") or os.getenv("YYB_WX_SERVER") or "http://127.0.0.1:8000"
)
WECHAT_SERVER = normalize_wechat_server(WECHAT_SERVER_RAW)
CACHE_FILE = resolve_local_path(os.getenv("JYK_CACHE_FILE") or (ENV_NAME + ".json"))


def log(msg: str) -> None:
    print(msg, flush=True)


def debug_log(msg: str) -> None:
    if DEBUG:
        print("[DEBUG] " + msg, flush=True)


def mask(value: Any, keep: int = 4) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= keep * 2:
        return text[:1] + "***"
    return text[:keep] + "..." + text[-keep:]


def short(value: Any, max_len: int = 220) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= max_len else text[:max_len] + "..."


def json_or_text(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return (response.text or "")[:500]


def split_accounts(raw: str) -> List[str]:
    # WX_ID 约定：多账号用换行 或 @ 分隔（兼容旧配置用 & / |）
    return [x.strip() for x in re.split(r"[@&\n|]+", raw or "") if x.strip()]


def is_wechat_protocol_id(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    if text.startswith(("wxid_", "yyb:", "wx:")):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{4,64}", text)) and "." not in text


def normalize_protocol_wxid(value: str) -> str:
    return (value or "").strip()


def parse_account(raw: str) -> Dict[str, str]:
    parts = [x.strip() for x in raw.split("#")]
    first = parts[0] if parts else ""
    remark = parts[1] if len(parts) > 1 and parts[1] else first
    if first.lower().startswith("token:"):
        return {
            "mode": "token",
            "wxid": "",
            "protocol_wxid": "",
            "remark": remark or "token账号",
            "token": first.split(":", 1)[1].strip(),
        }
    return {
        "mode": "wx",
        "wxid": first,
        "protocol_wxid": normalize_protocol_wxid(first),
        "remark": remark or first,
        "token": "",
    }


def extract_wx_code(data: Any) -> str:
    def walk(node: Any, depth: int = 0) -> str:
        if node is None or depth > 8:
            return ""
        if isinstance(node, str):
            text = node.strip()
            if re.fullmatch(r"[0-9A-Za-z_-]{8,512}", text):
                if text.lower() in ("success", "ok", "true", "false", "null"):
                    return ""
                return text
            if text.startswith(("{", "[")):
                try:
                    return walk(json.loads(text), depth + 1)
                except Exception:
                    return ""
            return ""
        if isinstance(node, list):
            for item in node:
                found = walk(item, depth + 1)
                if found:
                    return found
            return ""
        if isinstance(node, dict):
            for key in ("code", "Code", "wx_code", "wxCode", "js_code", "jscode", "loginCode", "LoginCode"):
                if key in node and node[key] not in (None, "", 0):
                    found = walk(node[key], depth + 1)
                    if found:
                        return found
            for key in ("Data", "data", "result", "Result", "payload", "Payload"):
                if key in node:
                    found = walk(node[key], depth + 1)
                    if found:
                        return found
            for value in node.values():
                if isinstance(value, (dict, list)):
                    found = walk(value, depth + 1)
                    if found:
                        return found
        return ""

    return walk(data)


def protocol_success(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    for key in ("Code", "code", "errCode", "errcode", "status", "Status"):
        if key not in data:
            continue
        val = data[key]
        if val in (0, "0", 200, "200", True, "success", "Success", "OK", "ok"):
            return True
        if isinstance(val, int) and val != 0:
            return False
    nested = data.get("Data") or data.get("data")
    if isinstance(nested, dict) and extract_wx_code(nested):
        return True
    return bool(extract_wx_code(data))


def load_cache() -> Dict[str, Any]:
    if not USE_CACHE or not CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        log("读取缓存失败: " + str(exc))
        return {}


def save_cache(cache: Dict[str, Any]) -> None:
    if not USE_CACHE:
        return
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        log("缓存写入失败: " + str(exc))


def to_num(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        return float(value)
    except Exception:
        return default


def get_wx_code(account: AccountCtx, label: str) -> Optional[str]:
    """通过统一 getCode 接口获取 wx.login code（兼容牛子 wxid / 应用宝 openid）"""
    protocol_wxid = account.protocol_wxid
    if not protocol_wxid:
        log("[" + label + "] 账号标识缺失")
        return None
    try:
        code = yyb.get_single_code(TARGET_APPID, protocol_wxid)
    except Exception as exc:
        log("[" + label + "] 获取 code 异常：" + str(exc)[:160])
        return None
    if code:
        log("[" + label + "] 获取 wx.login code 成功: " + mask(code))
        return code
    log("[" + label + "] 获取 code 失败")
    return None


@dataclass
class AccountCtx:
    index: int
    total: int
    mode: str
    wxid: str
    protocol_wxid: str
    remark: str
    access_token: str = ""
    uid: str = ""
    nickname: str = ""
    integral_before: Any = "-"
    integral_after: Any = "-"
    reward: Any = 0
    error: str = ""
    extras: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.remark or self.wxid or ("账号" + str(self.index))

    @property
    def account_display(self) -> str:
        return self.wxid or (("token-" + mask(self.access_token)) if self.access_token else ("账号" + str(self.index)))

    @property
    def cache_key(self) -> str:
        if self.wxid:
            return self.wxid
        if self.access_token:
            return "token:" + self.access_token[:24]
        return "index:" + str(self.index)

    def summary_line(self) -> str:
        line = (
            "当前账号：" + self.account_display
            + " 当前备注：" + self.label
            + " 当前积分：" + str(self.integral_after)
            + " 本次获得：" + str(self.reward)
        )
        if self.extras:
            line += " " + " ".join(self.extras)
        if self.error:
            line += " 失败：" + self.error
        return line


class JykClient:
    def __init__(self, account: AccountCtx):
        self.account = account
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update(self.common_headers(account.access_token))

    @staticmethod
    def common_headers(access_token: str = "") -> Dict[str, str]:
        headers = {
            "content-type": "application/json",
            "X-Payconfig-Id": PAYCONFIG_ID,
            "Referer": "https://servicewechat.com/" + TARGET_APPID + "/" + TARGET_VERSION + "/page-frame.html",
            "User-Agent": USER_AGENT,
        }
        if access_token:
            headers["Authorization"] = "Bearer " + access_token
        return headers

    def set_token(self, token: str) -> None:
        self.account.access_token = token
        self.session.headers.update(self.common_headers(token))

    @staticmethod
    def exchange_code(wx_code: str, label: str) -> Optional[Tuple[str, str, str]]:
        try:
            resp = requests.post(
                BASE_URL + "/api/index/get_openid",
                json={"code": wx_code, "pid": PID, "device_info": DEVICE_INFO},
                headers=JykClient.common_headers(),
                timeout=REQUEST_TIMEOUT,
                verify=False,
            )
            data = json_or_text(resp)
        except Exception as exc:
            log("[" + label + "] code 换 token 异常：" + str(exc)[:160])
            return None
        if not isinstance(data, dict) or data.get("errno") != 0:
            log("[" + label + "] code 换 token 失败 resp=" + short(data))
            return None
        info = data.get("data") or {}
        token = str(info.get("access_token") or "")
        if not token:
            log("[" + label + "] 响应缺少 access_token")
            return None
        user = info.get("userInfo") or {}
        nickname = str(user.get("nickname") or label)
        uid = str(info.get("uid") or user.get("uid") or "")
        log("[" + label + "] 登录成功 uid=" + (uid or "-") + " nick=" + mask(nickname))
        return token, uid, nickname

    def request_json(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        url = BASE_URL + (path if path.startswith("/") else "/" + path)
        try:
            if method.upper() == "GET":
                resp = self.session.get(url, params=payload or {}, timeout=REQUEST_TIMEOUT)
            else:
                resp = self.session.post(url, json=payload or {}, timeout=REQUEST_TIMEOUT)
            data = json_or_text(resp)
        except Exception as exc:
            log("[" + self.account.label + "] 请求异常 " + path + ": " + str(exc)[:160])
            return None
        if not isinstance(data, dict):
            log("[" + self.account.label + "] 响应非 JSON " + path + ": " + short(data))
            return None
        debug_log("[" + self.account.label + "] " + method + " " + path + " => " + short(data))
        return data

    def ok(self, data: Optional[Dict[str, Any]]) -> bool:
        return isinstance(data, dict) and data.get("errno") in (0, "0")

    def token_valid(self) -> bool:
        return bool(self.account.access_token) and self.ok(self.request_json("GET", "/api/checkin/home"))

    def home(self) -> Dict[str, Any]:
        data = self.request_json("GET", "/api/checkin/home") or {}
        if not self.ok(data):
            log("[" + self.account.label + "] home失败 resp=" + short(data))
            return {}
        return data.get("data") or {}

    def user_info(self) -> Dict[str, Any]:
        data = self.request_json("GET", "/api/user/getInfo") or {}
        return (data.get("data") or {}) if self.ok(data) else {}

    def extract_integral(self, home_data: Optional[Dict[str, Any]] = None) -> Any:
        if home_data and home_data.get("integral") not in (None, ""):
            return home_data.get("integral")
        info = self.user_info()
        for key in ("integral", "points", "score", "money"):
            if info.get(key) not in (None, ""):
                return info.get(key)
        return "-"

    def run_normal_checkin(self, home_data: Dict[str, Any]) -> Tuple[bool, Any]:
        if not DO_NORMAL:
            return False, 0
        if not home_data.get("enabled"):
            log("[" + self.account.label + "] 普通签到未开启")
            return False, 0
        if home_data.get("today_signed") or not home_data.get("can_sign"):
            log("[" + self.account.label + "] 普通签到：今日已完成或不可签")
            return False, 0
        prepared = self.request_json("POST", "/api/checkin/prepare") or {}
        if not self.ok(prepared):
            log("[" + self.account.label + "] 普通签到 prepare失败 resp=" + short(prepared))
            return False, 0
        body = prepared.get("data") or {}
        need_ad = bool(body.get("need_ad"))
        ad_token = str(body.get("ad_token") or "")
        if need_ad:
            if not ad_token:
                log("[" + self.account.label + "] 普通签到需要广告但无 ad_token")
                return False, 0
            if SIGN_DELAY_SECONDS > 0:
                time.sleep(SIGN_DELAY_SECONDS)
            payload = {"ad_token": ad_token}
        else:
            payload = {}
        signed = self.request_json("POST", "/api/checkin/sign", payload) or {}
        if not self.ok(signed):
            if ad_token:
                self.request_json("POST", "/api/checkin/close", {"ad_token": ad_token})
            log("[" + self.account.label + "] 普通签到 sign失败 resp=" + short(signed))
            return False, 0
        result = signed.get("data") or {}
        reward = result.get("reward") or {}
        amount = reward.get("amount") if isinstance(reward, dict) else reward
        log("[" + self.account.label + "] 普通签到成功 tip=" + str(result.get("success_tip") or "ok") + " 奖励=" + str(amount))
        return True, amount or 0

    def run_ad_checkin(self, home_data: Dict[str, Any]) -> Tuple[int, Any]:
        if not DO_AD or AD_CHECKIN_TIMES <= 0:
            return 0, 0
        ad = home_data.get("ad") or {}
        if not ad.get("enabled"):
            log("[" + self.account.label + "] 广告签到未开启")
            return 0, 0
        done = 0
        total_reward = 0.0
        for _ in range(AD_CHECKIN_TIMES):
            current = self.home() if done else home_data
            current_ad = current.get("ad") or {}
            today_count = int(current_ad.get("today_count") or 0)
            daily_limit = int(current_ad.get("daily_limit") or 0)
            if daily_limit and today_count >= daily_limit:
                log("[" + self.account.label + "] 广告签到已达上限 " + str(today_count) + "/" + str(daily_limit))
                break
            prepared = self.request_json("POST", "/api/checkin/ad/prepare") or {}
            if not self.ok(prepared):
                wait_seconds = 0
                try:
                    wait_seconds = int((prepared.get("data") or {}).get("wait_seconds") or 0)
                except Exception:
                    wait_seconds = 0
                if wait_seconds > 0 and AD_COOLDOWN_WAIT and wait_seconds <= 30:
                    log("[" + self.account.label + "] 广告签到冷却 " + str(wait_seconds) + "s")
                    time.sleep(wait_seconds + 0.5)
                    prepared = self.request_json("POST", "/api/checkin/ad/prepare") or {}
                    if not self.ok(prepared):
                        log("[" + self.account.label + "] 广告签到 prepare失败 resp=" + short(prepared))
                        break
                else:
                    log("[" + self.account.label + "] 广告签到 prepare失败 resp=" + short(prepared))
                    break
            body = prepared.get("data") or {}
            ad_token = str(body.get("ad_token") or "")
            if not ad_token:
                log("[" + self.account.label + "] 广告签到无 ad_token")
                break
            if SIGN_DELAY_SECONDS > 0:
                time.sleep(SIGN_DELAY_SECONDS)
            signed = self.request_json("POST", "/api/checkin/ad/sign", {"ad_token": ad_token}) or {}
            if not self.ok(signed):
                self.request_json("POST", "/api/checkin/ad/close", {"ad_token": ad_token})
                log("[" + self.account.label + "] 广告签到 sign失败 resp=" + short(signed))
                break
            result = signed.get("data") or {}
            reward = result.get("reward") or {}
            amount = reward.get("amount") if isinstance(reward, dict) else reward
            log("[" + self.account.label + "] 广告签到成功(" + str(today_count + 1) + "/" + str(daily_limit or "?") + ") 奖励=" + str(amount))
            done += 1
            total_reward += to_num(amount)
            time.sleep(1.2)
        return done, total_reward

    def run_gift(self) -> Tuple[int, Any]:
        if not DO_GIFT:
            return 0, 0
        data = self.request_json("GET", "/api/index/red_set") or {}
        if not self.ok(data):
            log("[" + self.account.label + "] 红包配置失败 resp=" + short(data))
            return 0, 0
        body = data.get("data") or {}
        red_set = body.get("red_set") or {}
        status = red_set.get("status") if isinstance(red_set, dict) else None
        count = int(body.get("count") or 0)
        if status != 1 or count <= 0:
            log("[" + self.account.label + "] 拆红包无可拆 status=" + str(status) + " count=" + str(count))
            return 0, 0
        opened = 0
        total = 0.0
        for _ in range(min(count, 20)):
            resp = self.request_json("GET", "/api/index/get_red") or {}
            if not self.ok(resp):
                log("[" + self.account.label + "] 拆红包失败 resp=" + short(resp))
                break
            money = (resp.get("data") or {}).get("money")
            log("[" + self.account.label + "] 拆红包成功 money=" + str(money))
            opened += 1
            total += to_num(money)
            time.sleep(0.8)
        return opened, total

    def run_first_packet(self) -> Tuple[bool, Any]:
        if not DO_FIRST:
            return False, 0
        info = self.request_json("GET", "/api/info/first_info") or {}
        if not self.ok(info):
            log("[" + self.account.label + "] 首单红包查询失败 resp=" + short(info))
            return False, 0
        body = info.get("data")
        if not body or not isinstance(body, dict) or body.get("id") in (None, ""):
            log("[" + self.account.label + "] 首单红包无可领")
            return False, 0
        packet_id = body.get("id")
        resp = self.request_json("POST", "/api/info/get_first_reward", {"id": packet_id}) or {}
        if not self.ok(resp):
            log("[" + self.account.label + "] 首单红包领取失败 resp=" + short(resp))
            return False, 0
        money = (resp.get("data") or {}).get("money")
        log("[" + self.account.label + "] 首单红包成功 id=" + str(packet_id) + " money=" + str(money))
        return True, money or 0

    def run_red_rain(self) -> Tuple[int, Any]:
        if not DO_RAIN or RAIN_TIMES <= 0:
            return 0, 0
        rain = self.request_json("GET", "/api/redrain/get_rain") or {}
        if not self.ok(rain):
            log("[" + self.account.label + "] 红包雨状态失败 resp=" + short(rain))
            return 0, 0
        body = rain.get("data") or {}
        status = body.get("status")
        rain_id = body.get("id")
        if status != 2:
            log("[" + self.account.label + "] 红包雨未进行中 status=" + str(status) + " id=" + str(rain_id))
            return 0, 0
        if rain_id in (None, ""):
            log("[" + self.account.label + "] 红包雨缺 rain_id")
            return 0, 0
        hit = 0
        total = 0.0
        for i in range(RAIN_TIMES):
            resp = self.request_json("POST", "/api/redrain/get_red", {"rain_id": rain_id}) or {}
            if not self.ok(resp):
                log("[" + self.account.label + "] 红包雨领取失败(" + str(i + 1) + ") resp=" + short(resp))
                break
            data = resp.get("data") or {}
            reward_type = data.get("type")
            amount = data.get("total")
            if amount in (None, "", 0, "0") and reward_type in (4, "4", None):
                log("[" + self.account.label + "] 红包雨本轮未领到 type=" + str(reward_type))
                break
            log("[" + self.account.label + "] 红包雨成功(" + str(i + 1) + ") total=" + str(amount))
            hit += 1
            total += to_num(amount)
            time.sleep(1.0)
        return hit, total

    def run_tasks(self) -> None:
        home_data = self.home()
        if not home_data and not self.token_valid():
            raise RuntimeError("home 接口不可用或 token 无效")
        self.account.integral_before = self.extract_integral(home_data)
        log("[" + self.account.label + "] 初始积分=" + str(self.account.integral_before) + " streak=" + str(home_data.get("streak_days", "-")))
        reward_total = 0.0
        notes: List[str] = []

        ok_n, amount_n = self.run_normal_checkin(home_data)
        if ok_n:
            reward_total += to_num(amount_n)
            notes.append("普通签到成功")
        elif home_data.get("today_signed"):
            notes.append("普通已签")

        ad_done, ad_reward = self.run_ad_checkin(self.home() or home_data)
        if ad_done:
            reward_total += to_num(ad_reward)
            notes.append("广告签到x" + str(ad_done))

        gift_n, gift_m = self.run_gift()
        if gift_n:
            reward_total += to_num(gift_m)
            notes.append("拆红包x" + str(gift_n) + "(" + str(gift_m) + ")")

        first_ok, first_m = self.run_first_packet()
        if first_ok:
            reward_total += to_num(first_m)
            notes.append("首单红包(" + str(first_m) + ")")

        rain_n, rain_m = self.run_red_rain()
        if rain_n:
            reward_total += to_num(rain_m)
            notes.append("红包雨x" + str(rain_n) + "(" + str(rain_m) + ")")

        final_home = self.home() or {}
        self.account.integral_after = self.extract_integral(final_home)
        before = to_num(self.account.integral_before, default=-1)
        after = to_num(self.account.integral_after, default=-1)
        self.account.reward = (after - before) if before >= 0 and after >= before else reward_total
        ad = final_home.get("ad") or {}
        self.account.extras.append(
            "普通已签=" + str(final_home.get("today_signed"))
            + " 广告=" + str(ad.get("today_count", "-")) + "/" + str(ad.get("daily_limit", "-"))
        )
        if notes:
            self.account.extras.append("任务：" + "、".join(notes))
        log("[" + self.account.label + "] 完成：积分=" + str(self.account.integral_after) + " 本次=" + str(self.account.reward))


def ensure_login(account: AccountCtx, cache: Dict[str, Any]) -> None:
    cached = cache.get(account.cache_key) or {}
    if isinstance(cached, dict) and cached.get("access_token") and not account.access_token:
        account.access_token = str(cached.get("access_token") or "")
        account.uid = str(cached.get("uid") or "")
        account.nickname = str(cached.get("nickname") or account.remark)
        log("[" + account.label + "] 使用缓存 token=" + mask(account.access_token))
    client = JykClient(account)
    if account.access_token:
        if client.token_valid():
            log("[" + account.label + "] 缓存校验通过")
            home = client.home()
            if home:
                account.integral_before = client.extract_integral(home)
                account.integral_after = account.integral_before
            return
        log("[" + account.label + "] 缓存 token 失效，重新协议登录")
        account.access_token = ""
        client.set_token("")
    if account.mode == "token":
        raise RuntimeError("手动 token 无效，且未配置协议账号")
    if not account.protocol_wxid:
        raise RuntimeError("未配置微信协议账号标识")
    wx_code = get_wx_code(account, account.label)
    if not wx_code:
        raise RuntimeError("获取 wx.login code 失败")
    exchanged = JykClient.exchange_code(wx_code, account.label)
    if not exchanged:
        raise RuntimeError("code 换业务 token 失败")
    token, uid, nickname = exchanged
    account.access_token, account.uid, account.nickname = token, uid, nickname
    client.set_token(token)
    if not client.token_valid():
        raise RuntimeError("业务 token 校验失败")
    cache[account.cache_key] = {
        "access_token": token,
        "token": token,
        "uid": uid,
        "nickname": nickname,
        "account": account.wxid,
        "protocol_wxid": account.protocol_wxid,
        "remark": account.remark,
        "device_info": DEVICE_INFO,
        "updated_at": int(time.time()),
        "updateTime": int(time.time() * 1000),
    }
    save_cache(cache)
    log("[" + account.label + "] 缓存已更新")


def load_accounts() -> List[AccountCtx]:
    raw = ""
    for key in ("WX_ID", ENV_NAME, "JYK_WX", "JYK_WXID"):
        value = (os.getenv(key) or "").strip()
        if value:
            raw = value
            break
    if not raw:
        # 未配置 WX_ID 时，自动从 yyb_go 拉取存活账号
        try:
            online = yyb.get_online_accounts()
            if online:
                raw = "\n".join(
                    (acc.get("openid") or acc.get("wxid") or acc.get("id") or "")
                    for acc in online
                    if (acc.get("openid") or acc.get("wxid") or acc.get("id"))
                )
                if raw:
                    log(f"[yyb] 自动从 yyb_go 同步到 {len(online)} 个存活账号")
        except Exception as exc:
            log(f"[yyb] 拉取存活账号失败: {exc}", "warn")
    accounts: List[AccountCtx] = []
    for item in split_accounts(raw) if raw else []:
        p = parse_account(item)
        accounts.append(AccountCtx(0, 0, p["mode"], p.get("wxid") or "", p.get("protocol_wxid") or "", p.get("remark") or "", p.get("token") or ""))
    manual = (os.getenv("JYK_MANUAL_TOKENS") or "").strip()
    for index, token in enumerate(split_accounts(manual), 1):
        value = token.split(":", 1)[1].strip() if token.lower().startswith("token:") else token.strip()
        if value:
            accounts.append(AccountCtx(0, 0, "token", "", "", "manual-" + str(index), value))
    total = len(accounts)
    for i, acc in enumerate(accounts, 1):
        acc.index, acc.total = i, total
    return accounts


def run_one(account: AccountCtx, cache: Dict[str, Any]) -> str:
    log("")
    log("===== 账号[" + str(account.index) + "/" + str(account.total) + "] " + account.label + " =====")
    log("[" + account.label + "] 当前账号：" + account.account_display + " mode=" + account.mode)
    try:
        ensure_login(account, cache)
        JykClient(account).run_tasks()
        return account.summary_line()
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        account.error = str(exc)[:200]
        log("[" + account.label + "] 执行异常：" + account.error)
        return account.summary_line()


def main() -> int:
    accounts = load_accounts()
    if not accounts:
        log("未配置账号变量 WX_ID（兼容 " + ENV_NAME + " / JYK_WX / JYK_WXID / JYK_MANUAL_TOKENS）")
        log("格式: wxid#备注  多账号换行或 @ 分隔（yyb:openid / wx:wxid 前缀兼容）")
        return 1
    log("🔔" + SCRIPT_NAME + " 微信协议版，共找到 " + str(len(accounts)) + " 个账号")
    if WECHAT_SERVER_RAW.rstrip("/") != WECHAT_SERVER:
        log("WECHAT_SERVER 已归一化: " + WECHAT_SERVER_RAW + " -> " + WECHAT_SERVER)
    log("WECHAT_SERVER=" + WECHAT_SERVER + " APPID=" + TARGET_APPID + " CACHE=" + str(CACHE_FILE))
    log(
        "任务: 普通=" + str(DO_NORMAL)
        + " 广告=" + str(DO_AD) + "x" + str(AD_CHECKIN_TIMES)
        + " 拆红包=" + str(DO_GIFT)
        + " 首单=" + str(DO_FIRST)
        + " 红包雨=" + str(DO_RAIN) + "x" + str(RAIN_TIMES)
    )
    cache = load_cache()
    summaries = []
    for index, account in enumerate(accounts, 1):
        summaries.append(run_one(account, cache))
        if index < len(accounts):
            time.sleep(2)
    print("")
    print("======== 本次汇总 ========")
    for line in summaries:
        print(line)
    return 1 if any("失败：" in x for x in summaries) else 0


if __name__ == "__main__":
    raise SystemExit(main())