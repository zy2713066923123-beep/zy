#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# cron: 56 16,07 * * *
# name: 趣玩营养站
"""
RRX 活动自动化（趣玩营养站）

账号来源：与其余脚本一致，统一走 yyb 账号服务（同目录 yyb.py）
  - 默认自动从 yyb_go 拉取全部存活账号，无需配置账号变量
  - 只想跑指定账号时才配置 WX_ID（openid#备注，多账号换行或 & 分隔）

环境变量：
  WX_SERVER / YYB_SERVER / WECHAT_SERVER   yyb 协议服务地址（默认 http://127.0.0.1:18273）
  WX_ID                                    可选白名单
"""

import os
import json
import time
import random
import argparse
import threading
import requests
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import yyb  # 自动同步 yyb_go 存活账号

# ================================
#  【配置区域】 - 可根据需要修改
# ================================

# ----- 基础配置 -----
MALL_GUID = "03t02w"
WSITE_GUID = "du3id3"
DEFAULT_ACTIVITY_TYPE = "1"
CHANNEL = "2"
WX_APP_ID = "wx2c1c63e28bb33be1"
REFERER = "https://servicewechat.com/wx2c1c63e28bb33be1/2/page-frame.html"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.76(0x18004c24) NetType/WIFI "
      "Language/zh_CN miniProgram/wx2c1c63e28bb33be1")

# ----- 接口域名 -----
HOST_INFO = "https://resinfo.rrx.cn"
HOST_ACT = "https://resactiviy.rrx.cn"

# ----- 延迟配置（秒） -----
TASK_DELAY = 3.0            # 任务步骤之间的基础延迟（随机浮动 ±0.5）
LOTTERY_DELAY = 4.0         # 抽奖步骤之间的基础延迟（随机浮动 ±0.5）
ACCOUNT_INTERVAL = 2.0      # 串行模式下账号之间的间隔

# ----- 多线程配置 -----
DEFAULT_WORKERS = 1         # 默认并发线程数（1=串行，建议 3~5）

# ----- 缓存配置 -----
TOKEN_CACHE_FILE = "rrx_tokens.json"
TOKEN_EXPIRE_HOURS = 23

# ----- 重试配置 -----
MAX_RETRIES = 3
REQUEST_TIMEOUT = 15

# ----- 占位 redirectUrl（服务端会重新生成） -----
PLACEHOLDER_REDIRECT = (
    "https://min.rrx.cn/h/pages/activity/pz/home/du3id3"
    "?w=du3id3&guid=zqtlijaa&activityType=1&mwa=1&isRrxMini=1"
    "&miniCode=0b1sAe000JO62X1sBY300oKZgl4sAe0N&clkty=1"
    "&rrx_uid=M05Pa1ZUcUFzQUFJaTRPamxQeVMzbGQ0MmtkRERITjE1K1FPQlBhc1o1bVVXUnZmTGFWdmFnPT0%3D"
)

# ================================
#  【全局锁和日志】
# ================================
_print_lock = threading.Lock()
_cache_lock = threading.Lock()
_tls = threading.local()

def log(msg, tag="·"):
    who = getattr(_tls, "who", "")
    prefix = f"[{who}] " if who else ""
    with _print_lock:
        print(f"[{datetime.now():%H:%M:%S}] {tag} {prefix}{msg}", flush=True)

# ================================
#  【账号来源与取码：统一走 yyb.py】
# ================================
def load_accounts_from_env():
    """优先从 yyb_go 拉取全部存活账号，拉取失败再回退 WX_ID / QWYYZ_WX_ID 环境变量。"""
    accounts = []
    try:
        for item in yyb.YYBClient().get_online_accounts():
            ref = str(item.get("openid") or item.get("wxid") or item.get("id") or "").strip()
            if not ref:
                continue
            name = str(item.get("nickname") or item.get("alias") or item.get("remark") or "").strip()
            accounts.append(Account(ref, name))
        if accounts:
            log(f"已自动从 yyb_go 同步到 {len(accounts)} 个存活账号", "📦")
            return accounts
    except Exception as e:
        log(f"从 yyb_go 拉取账号失败: {e}", "!")

    raw = os.environ.get("WX_ID") or os.environ.get("QWYYZ_WX_ID") or ""
    for line in raw.replace("&", "\n").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("#")
        wxid = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else ""
        if wxid:
            accounts.append(Account(wxid, name))
    if not accounts:
        try:
            for ref in yyb.resolve_accounts():
                ref = str(ref).split("#")[0].strip()
                if ref:
                    accounts.append(Account(ref, ref[:8]))
        except Exception as e:
            log(f"yyb 回退拉取账号失败: {e}", "!")
    return accounts


def get_login_code(wxid: str, app_id: str) -> Optional[str]:
    """wx.login 登录 code（统一走 yyb.py 自动路由）。"""
    return yyb.get_single_code(app_id, wxid)


def get_phone_code(wxid: str, app_id: str) -> str:
    """手机号授权 code（统一走 yyb.py，按账号登录类型自动选路）。"""
    try:
        return yyb.get_single_phone_code(app_id, wxid) or ""
    except Exception as e:
        log(f"获取 phone_code 失败: {e}", "!")
        return ""

# ================================
#  【Account 和 TokenCache】
# ================================
class Account:
    def __init__(self, wxid="", name=""):
        self.wxid = wxid.strip()
        self.name = name.strip() or wxid[:8] or "未命名"
        self.token = ""
        self.cookie_dict = {}
        self.member_guid = ""
        self.nickname = ""
        self.mobile = ""
        self.activity_guid = ""
        self.activity_name = ""

class TokenCache:
    @staticmethod
    def load():
        with _cache_lock:
            if not os.path.exists(TOKEN_CACHE_FILE):
                return {}
            try:
                with open(TOKEN_CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
    @staticmethod
    def save(cache):
        with _cache_lock:
            try:
                with open(TOKEN_CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cache, f, ensure_ascii=False, indent=2)
            except Exception as e:
                log(f"保存缓存失败: {e}", "!")
    @staticmethod
    def is_valid(entry):
        if not entry or not entry.get("token") or not entry.get("expire"):
            return False
        return datetime.now() < datetime.fromisoformat(entry["expire"])

# ================================
#  【登录函数】
# ================================
def rrx_login(login_code: str, phone_code: str) -> Tuple[Optional[str], Dict, Optional[str], Optional[str]]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })

    auth_data = {
        "loginCode": login_code,
        "phoneCode": phone_code,
        "wsiteGuid": WSITE_GUID,
        "redirectUrl": PLACEHOLDER_REDIRECT,
        "isTangChen": "1",
        "isGetPhone": "0",
        "memberGuid": "",
        "isApp": "1",
        "origin": "1",
    }
    headers_auth = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json, text/plain, */*",
        "Referer": REFERER,
    }

    try:
        r1 = session.post(
            "https://portal.rrx.cn/mini/miniPhoneAuth/wxMiniPhoneAuth",
            data=auth_data,
            headers=headers_auth,
            timeout=REQUEST_TIMEOUT
        )
        r1.raise_for_status()
        resp = r1.json()
        if resp.get("code") != 1:
            return None, {}, None, f"手机号授权失败: {resp}"
    except Exception as e:
        return None, {}, None, f"手机号授权异常: {e}"

    first_redirect = resp["data"]["redirectUrl"]
    parsed = urllib.parse.urlparse(first_redirect)
    query_params = urllib.parse.parse_qs(parsed.query)
    activity_guid = query_params.get("guid", [None])[0]
    if not activity_guid:
        parsed_fallback = urllib.parse.urlparse(PLACEHOLDER_REDIRECT)
        query_fallback = urllib.parse.parse_qs(parsed_fallback.query)
        activity_guid = query_fallback.get("guid", [None])[0]

    current_url = first_redirect
    max_redirects = 8
    for step in range(max_redirects):
        extra_headers = {"Referer": REFERER}
        try:
            r = session.get(current_url, headers=extra_headers, timeout=REQUEST_TIMEOUT, allow_redirects=False)
        except Exception as e:
            return None, {}, None, f"重定向请求异常: {e}"

        if r.status_code == 302 and "Location" in r.headers:
            location = r.headers["Location"]
            if "userToken=" in location:
                final_resp = session.get(location, headers=extra_headers, timeout=REQUEST_TIMEOUT, allow_redirects=False)
                if final_resp.status_code == 302 and "Location" in final_resp.headers:
                    final_url = final_resp.headers["Location"]
                    session.get(final_url, headers=extra_headers, timeout=REQUEST_TIMEOUT)
                break
            else:
                current_url = location
                continue
        else:
            break
    else:
        return None, {}, None, "重定向次数过多"

    jwt_token = session.cookies.get("4e4a82804216ca6ac597196ae45c4c22")
    if not jwt_token:
        return None, {}, None, "未获取到 JWT Token"

    cookie_dict = session.cookies.get_dict()
    if not cookie_dict:
        return None, {}, None, "未获取到任何 Cookie"

    # 获取 member_guid
    temp_acc = Account(jwt_token, "temp")
    temp_acc.cookie_dict = cookie_dict
    client = RrxClient(temp_acc)
    ok, info = client.check_login()
    member_guid = temp_acc.member_guid if ok else None

    return jwt_token, cookie_dict, member_guid, activity_guid

# ================================
#  【RrxClient】
# ================================
class RrxClient:
    def __init__(self, acc, delay=TASK_DELAY, verbose=False):
        self.acc = acc
        self.delay = delay
        self.verbose = verbose
        self.session = requests.Session()
        if self.acc.cookie_dict:
            self.session.cookies.update(self.acc.cookie_dict)

    def _req(self, url, method="GET", data=None, host=None, retry=MAX_RETRIES):
        headers = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Origin": "https://min.rrx.cn",
            "Referer": "https://min.rrx.cn/",
            "Connection": "keep-alive",
        }
        if self.acc.token:
            headers["Authorization"] = "Bearer " + self.acc.token
        if host:
            headers["Host"] = host

        body = None
        if data is not None:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        for attempt in range(retry + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=body,
                    timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
                txt = response.text
                if self.verbose:
                    log(f"    <- {txt[:300]}", "·")
                try:
                    return response.json()
                except:
                    return {"result": -1, "msg": f"非JSON响应: {txt[:120]}"}
            except requests.exceptions.HTTPError as e:
                try:
                    err_body = e.response.text
                except:
                    err_body = ''
                if self.verbose:
                    log(f"错误响应: {err_body[:200]}", "!")
                if attempt == retry:
                    return {"result": -1, "msg": f"HTTP {e.response.status_code}"}
                time.sleep(1.5 * (attempt + 1))
            except Exception as e:
                if attempt == retry:
                    return {"result": -1, "msg": f"请求失败: {e}"}
                time.sleep(1.5 * (attempt + 1))
        return {"result": -1, "msg": "未知错误"}

    def _url(self, host, path, extra=None, **params):
        base = [("channel", CHANNEL), ("mallGuid", MALL_GUID), ("wsiteGuid", WSITE_GUID)]
        base += [(k, v) for k, v in params.items() if v is not None]
        if extra:
            base += extra
        return f"{host}{path}?" + urllib.parse.urlencode(base)

    def check_login(self):
        r = self._req(self._url(HOST_INFO, "/m/auth/checkIsLogin"), host="resinfo.rrx.cn")
        d = r.get("data") or {}
        if r.get("result") == 0 and d.get("guid"):
            self.acc.member_guid = d["guid"]
            self.acc.nickname = d.get("name") or ""
            self.acc.mobile = d.get("mobile", "")
            return True, d
        return False, "凭证无效"

    def visit_log(self):
        form = {
            "isFirstVisit": 0,
            "memberGuid": self.acc.member_guid,
            "pagePath": "pages/activity/pz/home",
            "activityGuid": self.acc.activity_guid,
            "as": 0, "ast": 1, "cs": 0, "cst": 1, "ab": 1,
            "screenWidth": 430, "screenHeight": 932,
        }
        return self._req(self._url(HOST_ACT, "/m/visitLog/add"), method="POST",
                         data={"form": json.dumps(form, separators=(",", ":"))},
                         host="resactiviy.rrx.cn", retry=1)

    def join_check(self):
        return self._req(self._url(HOST_ACT, "/m/Activity/JoinCheckByActivity",
                                   activityGuid=self.acc.activity_guid, activityType=DEFAULT_ACTIVITY_TYPE),
                         method="POST",
                         data={"activityGuid": self.acc.activity_guid, "activityType": DEFAULT_ACTIVITY_TYPE,
                               "soid": "", "isWxMini": 0},
                         host="resactiviy.rrx.cn")

    def task_list(self):
        return self._req(self._url(HOST_ACT, "/m/activityTask/getActivityTaskSettingItemList",
                                   extra=[("activityGuid", self.acc.activity_guid), ("activityGuid", self.acc.activity_guid)]),
                         host="resactiviy.rrx.cn")

    def deal_task(self, record_id):
        return self._req(self._url(HOST_ACT, "/m/activityTask/dealActivityTaskItem",
                                   activityGuid=self.acc.activity_guid, activityType=DEFAULT_ACTIVITY_TYPE,
                                   taskItemRecordId=record_id), host="resactiviy.rrx.cn")

    def receive_task(self, item_id):
        return self._req(self._url(HOST_ACT, "/m/activityTask/receiveActivityTaskSettingItem",
                                   activityGuid=self.acc.activity_guid, activityType=DEFAULT_ACTIVITY_TYPE,
                                   taskItemId=item_id), host="resactiviy.rrx.cn")

    def left_times(self):
        return self._req(self._url(HOST_ACT, "/m/activity/getLeftLotteryDayNumber",
                                   extra=[("activityGuid", self.acc.activity_guid), ("activityGuid", self.acc.activity_guid)]),
                         host="resactiviy.rrx.cn")

    def grab(self):
        return self._req(self._url(HOST_ACT, "/m/activity/grab",
                                   activityGuid=self.acc.activity_guid, activityType=DEFAULT_ACTIVITY_TYPE),
                         method="POST",
                         data={"activityGuid": self.acc.activity_guid, "activityType": DEFAULT_ACTIVITY_TYPE,
                               "lotteryWordType": 0, "lotteryWord": ""},
                         host="resactiviy.rrx.cn")

    def fetch_activity_info(self):
        if not self.acc.activity_guid:
            return
        url = self._url(HOST_INFO, "/m/activity/getDynamicData",
                        extra=[("activityGuid", self.acc.activity_guid),
                               ("activityGuid", self.acc.activity_guid)],
                        activityType=DEFAULT_ACTIVITY_TYPE,
                        mwa=1, isRrxMini=1,
                        miniCode="", fromShortUrl=1)
        r = self._req(url, host="resinfo.rrx.cn")
        if r.get("result") == 0:
            data = r.get("data", {})
            ext = data.get("activityExt", {})
            name = ext.get("activityName", "")
            if name:
                self.acc.activity_name = name
                log(f"📢 活动名称: {name}")

# ================================
#  【Token 刷新】
# ================================
def get_or_refresh_token(acc, app_id):
    cache = TokenCache.load()
    entry = cache.get(acc.wxid, {})
    if TokenCache.is_valid(entry):
        acc.token = entry["token"]
        acc.cookie_dict = entry.get("cookie_dict", {})
        acc.member_guid = entry.get("member_guid", "")
        acc.nickname = entry.get("nickname", "")
        acc.mobile = entry.get("mobile", "")
        acc.activity_guid = entry.get("activity_guid", "")
        acc.activity_name = entry.get("activity_name", "")
        if not acc.activity_guid:
            acc.activity_guid = "zqtlijaa"
        log(f"📦 使用缓存的 Token (有效至 {entry['expire']})", "📦")
        log(f"  活动 GUID: {acc.activity_guid}")
        if acc.activity_name:
            log(f"  活动名称: {acc.activity_name}")
        return True

    log("🔄 缓存已过期或不存在，开始重新登录...", "🔄")
    try:
        login_code = get_login_code(acc.wxid, app_id)
        if not login_code:
            log("❌ 未获取到 loginCode", "!")
            return False
        phone_code = get_phone_code(acc.wxid, app_id)
        log(f"✅ loginCode: {login_code[:8]}...{login_code[-4:]}")
        if phone_code:
            log(f"✅ phone_code: {phone_code[:8]}...{phone_code[-4:]}")
        else:
            log("⚠️ 未获取到 phone_code，尝试仅使用 loginCode", "⚠️")
    except Exception as e:
        log(f"❌ 获取凭证失败: {e}", "!")
        return False

    token, cookie_dict, member_guid, activity_guid = rrx_login(login_code, phone_code)
    if token:
        acc.token = token
        acc.cookie_dict = cookie_dict
        acc.member_guid = member_guid or ""
        acc.nickname = acc.nickname or acc.wxid[:8]
        acc.activity_guid = activity_guid or "zqtlijaa"
        # 获取活动名称
        temp_client = RrxClient(acc)
        ok, info = temp_client.check_login()
        if ok:
            acc.mobile = info.get("mobile", "")
        temp_client.fetch_activity_info()
        cache[acc.wxid] = {
            "token": token,
            "cookie_dict": cookie_dict,
            "member_guid": acc.member_guid,
            "nickname": acc.nickname,
            "mobile": acc.mobile,
            "activity_guid": acc.activity_guid,
            "activity_name": acc.activity_name,
            "expire": (datetime.now() + timedelta(hours=TOKEN_EXPIRE_HOURS)).isoformat()
        }
        TokenCache.save(cache)
        log(f"✅ 登录成功，Token 和 Cookie 已缓存 (有效期 {TOKEN_EXPIRE_HOURS} 小时)", "✅")
        log(f"  活动 GUID: {acc.activity_guid}")
        if acc.activity_name:
            log(f"  活动名称: {acc.activity_name}")
        return True
    else:
        log(f"❌ 登录失败: {member_guid}", "!")
        return False

# ================================
#  【任务和抽奖（含延迟打印）】
# ================================
def run_tasks(c):
    done, received, stalled = 0, 0, 0
    for rnd in range(1, 31):
        r = c.task_list()
        items = r.get("data") or []
        if not items:
            log("任务列表为空，跳过任务阶段")
            break
        action = None
        for it in items:
            status = it.get("memberTaskStatus")
            iid, rec = it.get("id"), it.get("taskItemRecordId")
            title = (it.get("title") or "")[:16]
            if status == 1 and rec:
                action = ("deal", rec, iid, title)
                break
            if status == 0:
                action = ("receive", iid, iid, title)
                break
            if status == 2 and str(it.get("taskItemRecordCanLottery")) == "1":
                action = ("receive", iid, iid, title)
                break
        if not action:
            log(f"第{rnd}轮: 无待处理任务 (共{len(items)}项, 均已完结)")
            break
        kind, arg, iid, title = action
        resp = c.deal_task(arg) if kind == "deal" else c.receive_task(arg)
        ok = str(resp.get("code")) == "1" or (str(resp.get("result")) == "0" and resp.get("msg") == "ok")
        msg = resp.get("msg") or resp.get("data") or ""
        if ok:
            done += 1 if kind == "deal" else 0
            received += 1 if kind == "receive" else 0
            log(f"第{rnd}轮 {kind} [{title}] -> {msg}", "√")
            stalled = 0
        else:
            stalled += 1
            log(f"第{rnd}轮 {kind} [{title}] 未成功 -> {msg}", "×")
            if stalled >= 3:
                log("连续3次失败，终止任务阶段", "!")
                break
        # 计算并打印实际延迟
        actual_delay = c.delay + random.uniform(-0.5, 1.5)
        log(f"  等待 {actual_delay:.1f} 秒后继续...", "⏱")
        time.sleep(max(0.5, actual_delay))
    return done, received

def run_lottery(c, delay):
    left = c.left_times()
    d = left.get("data") or {}
    n = int(d.get("leftLotteryDayNumber") or 0)
    log(f"剩余抽奖次数: {n}")
    if n <= 0:
        return 0, 0, []
    prizes, empty, wins = 0, 0, []
    for i in range(1, n + 6):
        r = c.grab()
        data = r.get("data") or {}
        code = str(r.get("result"))
        if code != "0":
            msg = r.get("msg") or ""
            if "次数" in msg or "用完" in msg:
                log(f"抽奖终止: {msg}", "·")
            else:
                log(f"第{i}抽 异常 -> {msg or r}", "×")
            break
        if not data:
            break
        name = data.get("prizeName") or "未知"
        no_prize = data.get("isNoPrize")
        left_n = data.get("leftLotteryDayNumber", "?")
        if no_prize:
            empty += 1
            log(f"第{i}抽: {name} (剩余 {left_n})", "·")
        else:
            prizes += 1
            log(f"第{i}抽: ★ {name} ★ (剩余 {left_n})", "★")
            detail = {"奖品": name, "类型": data.get("prizeType"), "订单号": data.get("orderNo") or "-",
                      "订单状态": data.get("orderState"), "发货方式": data.get("shippingType"),
                      "转盘位置": data.get("pos"), "扩展数据": json.dumps(data.get("exdata"), ensure_ascii=False) if data.get("exdata") else "-"}
            log("    └ " + " | ".join(f"{k}={v}" for k, v in detail.items()), "★")
            wins.append(detail)
        if int(left_n) <= 0:
            break
        actual_delay = delay + random.uniform(-0.5, 1.0)
        log(f"  等待 {actual_delay:.1f} 秒后继续...", "⏱")
        time.sleep(max(0.5, actual_delay))
    return prizes, empty, wins

# ================================
#  【单账号执行】
# ================================
def run_account(acc, args):
    _tls.who = acc.name
    log(f"===== 开始 =====")

    if not get_or_refresh_token(acc, args.app_id):
        log("无法获取有效 Token，跳过该账号", "!")
        return {"name": acc.name, "task_done": 0, "task_recv": 0, "prize": 0, "empty": 0, "wins": [], "error": "登录失败"}

    c = RrxClient(acc, delay=args.delay, verbose=args.verbose)
    result = {"name": acc.name, "task_done": 0, "task_recv": 0, "prize": 0, "empty": 0, "wins": [], "error": ""}

    ok, info = c.check_login()
    if not ok:
        log(f"登录验证失败: {info} —— Token 可能无效，尝试重新登录", "!")
        cache = TokenCache.load()
        if acc.wxid in cache:
            del cache[acc.wxid]
            TokenCache.save(cache)
        if get_or_refresh_token(acc, args.app_id):
            c = RrxClient(acc, delay=args.delay, verbose=args.verbose)
            ok, info = c.check_login()
            if not ok:
                log(f"重新登录后仍然失败: {info}", "!")
                result["error"] = "凭证失效"
                return result
        else:
            result["error"] = "凭证失效"
            return result

    if not acc.activity_name:
        c.fetch_activity_info()

    nick = f" ({acc.nickname})" if acc.nickname else ""
    mobile = f" [{acc.mobile}]" if acc.mobile else ""
    log(f"登录成功{nick}{mobile} (memberGuid={acc.member_guid[:8]}...)")
    log(f"活动: {acc.activity_name} (GUID: {acc.activity_guid})")

    done, received = 0, 0
    if not args.no_task:
        c.visit_log()
        jr = c.join_check()
        if str(jr.get("result")) == "0":
            log("活动参与校验通过")
        if not args.only_lottery:
            done, received = run_tasks(c)
            log(f"任务阶段: 完成 {done} 项 / 领取 {received} 项")

    result["task_done"], result["task_recv"] = done, received

    if not args.only_task:
        prize, empty, wins = run_lottery(c, args.lottery_delay)
        result["prize"], result["empty"], result["wins"] = prize, empty, wins
        if prize or empty:
            log(f"抽奖结束: 中奖 {prize} 次 / 未中 {empty} 次")
        if wins:
            names = "、".join(w.get("奖品", "?") for w in wins)
            log(f"中奖清单: {names} — 请到活动页「我的奖品」核对领取", "★")

    log(f"===== 结束: 任务{done}/{received} 中奖{result['prize']} =====")
    return result

def safe_run(acc, args, idx):
    try:
        return run_account(acc, args)
    except Exception as e:
        _tls.who = acc.name
        log(f"账号异常: {type(e).__name__}: {e}", "!")
        return {"name": acc.name, "task_done": 0, "task_recv": 0, "prize": 0, "empty": 0, "wins": [], "error": f"{type(e).__name__}", "_idx": idx}
    except KeyboardInterrupt:
        return {"name": acc.name, "task_done": 0, "task_recv": 0, "prize": 0, "empty": 0, "wins": [], "error": "已中断", "_idx": idx}

# ================================
#  【汇总输出】
# ================================
def print_summary(summary, seconds):
    print("\n" + "=" * 58)
    print(f"{'账号':<16}{'完成':>5}{'领取':>5}{'中奖':>5}{'未中':>5}  状态")
    print("-" * 58)
    for s in summary:
        status = s.get("error") or "正常"
        name = str(s.get("name"))[:14]
        print(f"{name:<16}{s.get('task_done', 0):>5}{s.get('task_recv', 0):>5}{s.get('prize', 0):>5}{s.get('empty', 0):>5}  {status[:14]}")
    print("-" * 58)
    t_done = sum(s.get("task_done", 0) for s in summary)
    t_recv = sum(s.get("task_recv", 0) for s in summary)
    t_prize = sum(s.get("prize", 0) for s in summary)
    t_empty = sum(s.get("empty", 0) for s in summary)
    t_win = [w for s in summary for w in s.get("wins", [])]
    print(f"{'合计':<15}{t_done:>6}{t_recv:>5}{t_prize:>5}{t_empty:>5}  耗时 {seconds:.0f}s")
    if t_win:
        print("\n中奖明细:")
        for w in t_win:
            print(f"  · {w.get('奖品')} | 类型={w.get('类型')} | 订单={w.get('订单号')} | 状态={w.get('订单状态')} | 发货={w.get('发货方式')}")
        print("  → 请到活动页「我的奖品」核对领取")
    print("=" * 58 + "\n")

# ================================
#  【主函数】
# ================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="WX_ID")
    ap.add_argument("--app-id", default=WX_APP_ID)
    ap.add_argument("--delay", type=float, default=TASK_DELAY, help=f"任务间延迟（秒），默认 {TASK_DELAY}")
    ap.add_argument("--lottery-delay", type=float, default=LOTTERY_DELAY, help=f"抽奖间延迟（秒），默认 {LOTTERY_DELAY}")
    ap.add_argument("-w", "--workers", type=int, default=DEFAULT_WORKERS, help=f"并发线程数，默认 {DEFAULT_WORKERS}")
    ap.add_argument("--account-delay", type=float, default=ACCOUNT_INTERVAL, help=f"串行账号间隔（秒），默认 {ACCOUNT_INTERVAL}")
    ap.add_argument("--only-task", action="store_true")
    ap.add_argument("--only-lottery", action="store_true")
    ap.add_argument("--no-task", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    if args.once:
        args.only_task = True

    accounts = load_accounts_from_env()

    if not accounts:
        log("未读取到任何账号（yyb_go 无存活账号且未配置 WX_ID），退出", "!")
        return

    seen, uniq = set(), []
    for acc in accounts:
        if acc.wxid and acc.wxid not in seen:
            seen.add(acc.wxid)
            uniq.append(acc)
    accounts = uniq
    log(f"共载入 {len(accounts)} 个账号 (来源: yyb_go 存活账号)")

    workers = max(1, min(args.workers, len(accounts)))
    log(f"并发数: {workers} 线程" if workers > 1 else "串行模式（一个账号执行完再执行下一个）")

    summary, t0 = [], time.time()
    if workers == 1:
        for idx, acc in enumerate(accounts, 1):
            res = safe_run(acc, args, idx)
            res["_idx"] = idx
            summary.append(res)
            if idx < len(accounts):
                log(f"等待 {args.account_delay} 秒后执行下一个账号...", "⏱")
                time.sleep(args.account_delay)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(safe_run, acc, args, i): acc for i, acc in enumerate(accounts, 1)}
            for f in as_completed(futures):
                summary.append(f.result())
    summary.sort(key=lambda x: x.get("_idx", 999))
    print_summary(summary, time.time() - t0)

if __name__ == "__main__":
    main()