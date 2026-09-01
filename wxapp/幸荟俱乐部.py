# cron: 0 7,13,19,23 * * *
# name: 幸荟俱乐部
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
幸荟庄园 (Xinghui Manor) 青龙脚本
自动完成庄园任务获取积分，参考习酒花园脚本结构。

流程：
1. 通过 yyb 协议获取微信 code
2. 调用 mzh.php 登录，获取 phpsessid / uid / appkey
3. 调用庄园 API：
   - status: 获取积分/当前酒庄
   - winery: 获取建筑与生产选项
   - 每个建筑(plant/brew/age/bottle):
     - building/task: 查看当前生产任务
     - 无任务 -> building/start 开始生产(24h, 10积分)
     - 可收获 -> building/harvest 收获积分
     - building/daily-tasks: 每日任务
     - building/daily-task/complete: 完成每日任务(加速6h)
     - story: 阅读故事(完成阅读任务)

环境变量:
  WX_ID / WXIDXH: 要执行的微信ID(逗号分隔)
  WX_SERVER: yyb 协议服务地址
  OCR_SERVER: 可选
"""

import os
import re
import time
import json
import base64
import hashlib
import random
import requests

# ============ 配置 ============
APPID = "wxc431da386d2de6e3"  # 幸荟庄园小程序 appid

# 庄园 API 域名
MANOR_BASE = "https://yy.fenggewenhua.com/api/manor"
# 登录域名
LOGIN_BASE = "https://xcx.fenggewenhua.com"

# 建筑类型
BUILDING_TYPES = ["plant", "brew", "age", "bottle"]

# 每日任务类型
DAILY_TASK_TYPES = ["read", "game"]

# ============ 防检测/防封停配置 ============
# 每次请求之间的随机延迟范围(秒)，模拟人类操作节奏
REQUEST_DELAY_MIN = 1.2
REQUEST_DELAY_MAX = 3.5
# 429 限流时的最大重试次数
MAX_RETRY = 3
# 429 退避基础延迟(秒)，每次重试翻倍并加随机抖动
RETRY_BASE_DELAY = 3.0
# 账号之间的随机间隔范围(秒)
ACCOUNT_GAP_MIN = 5
ACCOUNT_GAP_MAX = 12
# 是否启用随机延迟(可关闭便于调试)
ENABLE_DELAY = True

# 随机 User-Agent 池，模拟不同设备，避免被识别为脚本
UA_POOL = [
    "Mozilla/5.0 (Linux; Android 13; M2012K11AC Build/AQ3A.250226.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/150.0.7871.181 Mobile Safari/537.36 XWEB/1500047 MMWEBSDK/20260502 MMWEBID/3433 MicroMessenger/8.0.76.3141(0x28004C54) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android",
    "Mozilla/5.0 (Linux; Android 14; 23127PN0CC Build/UKQ1.230917.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/150.0.7871.181 Mobile Safari/537.36 XWEB/1500047 MMWEBSDK/20260502 MMWEBID/3433 MicroMessenger/8.0.76.3141(0x28004C54) WeChat/arm64 Weixin NetType/5G Language/zh_CN ABI/arm64 MiniProgramEnv/android",
    "Mozilla/5.0 (Linux; Android 14; 2211133C Build/UKQ1.230917.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36 XWEB/1500047 MMWEBSDK/20260502 MMWEBID/3433 MicroMessenger/8.0.75.3141(0x28004C54) WeChat/arm64 Weixin NetType/4G Language/zh_CN ABI/arm64 MiniProgramEnv/android",
    "Mozilla/5.0 (Linux; Android 12; 2107119DC Build/SKQ1.211006.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/119.0.0.0 Mobile Safari/537.36 XWEB/1500047 MMWEBSDK/20260502 MMWEBID/3433 MicroMessenger/8.0.75.3141(0x28004B54) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android",
    "Mozilla/5.0 (Linux; Android 13; 22081212C Build/TKQ1.220829.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/118.0.0.0 Mobile Safari/537.36 XWEB/1500047 MMWEBSDK/20260502 MMWEBID/3433 MicroMessenger/8.0.75.3141(0x28004B54) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android",
]

def _sleep(lo, hi):
    """随机延迟，模拟人类操作节奏"""
    if not ENABLE_DELAY:
        return
    time.sleep(random.uniform(lo, hi))

def _random_ua():
    """随机选择一个 User-Agent"""
    return random.choice(UA_POOL)

# 日志
class Log:
    def __init__(self):
        self.enabled = True
    def info(self, msg):
        if self.enabled:
            print(msg, flush=True)
    def warn(self, msg):
        if self.enabled:
            print("[WARN] " + msg, flush=True)
    def error(self, msg):
        if self.enabled:
            print("[ERROR] " + msg, flush=True)

log = Log()

# ============ yyb 协议取码 ============
try:
    from yyb import get_single_code, load_accounts
    _HAS_GETCODE = True
except ImportError:
    try:
        import yyb
        get_single_code = getattr(yyb, "get_single_code", None)
        load_accounts = getattr(yyb, "load_accounts", None)
        _HAS_GETCODE = True
    except ImportError:
        get_single_code = None
        load_accounts = None
        _HAS_GETCODE = False

# ============ 登录加密 ============
def _now_ms():
    return str(int(time.time() * 1000))

def _b64(s):
    """标准 base64 (UTF-8)"""
    return base64.b64encode(s.encode("utf-8")).decode("utf-8")

def _rand_int(e, t):
    """Math.floor(Math.random()*(t-e)+e)"""
    return random.randint(e, t - 1)

def build_p_cko(keys, anow):
    """
    生成 p_cko:
    - t = 所有字段名, 用 '-_-' 连接
    - i = base64(t)
    - a = anow 最后一位
    - u = 随机大写字母 + base64, 在位置 a 插入随机数字(若 a>0)
    """
    t = "-_-".join(keys)
    i = _b64(t)
    a = int(anow[-1])
    c = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    u = c[_rand_int(1, len(c))]
    for n, ch in enumerate(i):
        u += ch
        if a > 0 and n == a:
            u += str(_rand_int(1, 9))
    return u

def build_p_ckk(anow, phpsessid, numeric_values):
    """生成 p_ckk: md5(anow + phpsessid + r.join('||'))"""
    r = "||".join(numeric_values)
    return hashlib.md5((anow + phpsessid + r).encode("utf-8")).hexdigest()

def login(code, phpsessid=""):
    """调用 mzh.php 登录，返回 (phpsessid, uid, appkey, qdn)"""
    anow = _now_ms()
    # 字段顺序必须与小程序一致
    llu = json.dumps({
        "path": "home/index/index",
        "query": {},
        "scene": 1089,
        "referrerInfo": {},
        "sessionId": "hash=1680549421&ts=%s&host=&version=671108180&device=2" % anow,
        "mode": "default",
        "apiCategory": "default",
    }, ensure_ascii=False)
    wsi = json.dumps({
        "pm": "M2012K11AC",
        "sys": "Android 15",
        "ww": 873,
        "wh": 393,
        "br": "Redmi",
    }, ensure_ascii=False)
    params = {
        "act": "config",
        "code": code,
        "enter": "0",
        "llu": llu,
        "wsi": wsi,
        "ver": "1.0",
        "currpg": "home/index/index",
    }
    # 计算 p_cko / p_ckk
    keys = list(params.keys()) + ["anow"]
    # 数值字段(匹配 /^[0-9\.]{0,20}$/)
    numeric = []
    for k in keys:
        v = params.get(k, anow if k == "anow" else "")
        if re_match_numeric(v):
            numeric.append(v)
    p_cko = build_p_cko(keys, anow)
    p_ckk = build_p_ckk(anow, phpsessid, numeric)

    params["anow"] = anow
    params["p_cko"] = p_cko
    params["p_ckk"] = p_ckk

    headers = {
        "content-type": "application/x-www-form-urlencoded",
        "User-Agent": _random_ua(),
    }
    if phpsessid:
        headers["psession"] = phpsessid

    url = LOGIN_BASE + "/xcx/mzh.php"
    resp = requests.post(url, data=params, headers=headers, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    # 响应结构: {code, message, data:{...}, phpsessid, us:{id}, appkey}
    data = body.get("data") or {}
    new_phpsessid = body.get("phpsessid") or data.get("phpsessid") or ""
    us = data.get("us") or body.get("us") or {}
    uid = str(us.get("id") or "")
    appkey = data.get("appkey") or body.get("appkey") or ""
    return new_phpsessid, uid, appkey

def re_match_numeric(v):
    """匹配 /^[0-9\.]{0,20}$/"""
    import re
    return bool(re.match(r"^[0-9\.]{0,20}$", str(v)))

# ==================== 庄园 API ====================
class ManorClient:
    def __init__(self, uid, phpsessid=""):
        self.uid = uid
        self.phpsessid = phpsessid
        self.session = requests.Session()
        self.session.headers.update({
            "content-type": "application/x-www-form-urlencoded",
            "User-Agent": _random_ua(),
        })
        if phpsessid:
            self.session.headers["phpsession"] = phpsessid

    def _post(self, path, params):
        url = MANOR_BASE + path
        # 过滤空值
        data = {k: v for k, v in params.items() if v is not None and v != ""}
        # 请求前随机延迟，模拟人类操作节奏
        _sleep(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        # 429 限流自动退避重试
        for attempt in range(MAX_RETRY + 1):
            try:
                resp = self.session.post(url, data=data, timeout=15)
                if resp.status_code == 429:
                    # 限流，退避后重试
                    backoff = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 2)
                    log.warn("    触发限流(429)，%.1fs 后重试(%d/%d)" % (backoff, attempt + 1, MAX_RETRY))
                    time.sleep(backoff)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 429 and attempt < MAX_RETRY:
                    delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 2)
                    log.warn("    触发限流(429)，%.1fs 后重试(%d/%d)" % (delay, attempt + 1, MAX_RETRY))
                    time.sleep(delay)
                    continue
                raise
        # 重试耗尽
        raise RuntimeError("请求 %s 多次触发限流(429)" % path)

    def status(self):
        return self._post("/status", {"uid": self.uid})

    def winery(self, winery_id=1):
        return self._post("/winery", {"uid": self.uid, "winery_id": winery_id})

    def building_task(self, winery_id, building_type):
        return self._post("/building/task", {"uid": self.uid, "winery_id": winery_id, "building_type": building_type})

    def building_start(self, winery_id, building_type, option_id):
        return self._post("/building/start", {"uid": self.uid, "winery_id": winery_id, "building_type": building_type, "option_id": option_id})

    def building_harvest(self, task_id):
        # 源码 harvestBuilding 只传 {uid, task_id}
        return self._post("/building/harvest", {"uid": self.uid, "task_id": task_id})

    def daily_tasks(self, winery_id, building_type):
        return self._post("/building/daily-tasks", {"uid": self.uid, "winery_id": winery_id, "building_type": building_type})

    def complete_daily_task(self, winery_id, building_type, task_type):
        return self._post("/building/daily-task/complete", {"uid": self.uid, "winery_id": winery_id, "building_type": building_type, "task_type": task_type})

    def story(self, winery_id=1):
        return self._post("/story", {"uid": self.uid, "winery_id": winery_id, "mode": "random"})

    def collection(self, winery_id=1):
        """酒柜/图鉴：查询 8 款酒的碎片收集状态"""
        return self._post("/collection", {"uid": self.uid, "winery_id": winery_id})

    def compose(self, winery_id, wine_id):
        """合成酒款：消耗 4 种碎片合成一款酒，获得积分"""
        return self._post("/collection/compose", {"uid": self.uid, "winery_id": winery_id, "wine_id": wine_id})

# ================= 任务中心 (做任务领红包) =================
# 页面: home/moneyTask/moneyTask, 活动 hid=17, 抽奖 cjHid=101
# 所有请求 POST 到 mzh.php, 带 p_cko/p_ckk 签名, header 用 psession
TASK_HID = 17
LOTTERY_HID = 101
MZH_URL = "https://xcx.fenggewenhua.com/xcx/mzh.php"

def _signed_post(phpsessid, params, currpg="home/moneyTask/moneyTask"):
    """
    带签名的通用请求 (与小程序 inc/func.js 的 post 一致):
    - 加 ver / currpg
    - 加 anow (毫秒时间戳)
    - 计算 p_cko / p_ckk
    - POST 到 mzh.php, header 带 psession
    """
    anow = _now_ms()
    data = dict(params)
    data["ver"] = "1.0"
    data["currpg"] = currpg
    data["anow"] = anow
    keys = list(data.keys())
    numeric = [str(v) for v in data.values() if re_match_numeric(v)]
    data["p_cko"] = build_p_cko(keys, anow)
    data["p_ckk"] = build_p_ckk(anow, phpsessid, numeric)
    headers = {
        "content-type": "application/x-www-form-urlencoded",
        "User-Agent": _random_ua(),
        "psession": phpsessid,
    }
    resp = requests.post(MZH_URL, data=data, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()

def task_center(phpsessid):
    """任务中心: 签到, 获取任务列表, 自动完成可领取任务, 每日抽奖, 查询余额"""
    log.info("   💰 任务中心(做任务领红包)...")
    # 0. 每日签到 (hid=177)
    try:
        _daily_sign(phpsessid)
    except Exception as e:
        log.warn("   每日签到异常: %s" % e)

    # 1. 获取任务列表
    try:
        tl = _signed_post(phpsessid, {"ajax": "hd/rwu_new", "act": "getRWuList", "aid": TASK_HID, "reg": 1})
    except Exception as e:
        log.warn("   获取任务列表失败: %s" % e)
        return
    if (tl.get("code") or 0) != 200:
        log.warn("   获取任务列表失败: %s" % tl.get("mess"))
        return

    # 2. 遍历各任务分组, 尝试完成
    groups = {
        "tuwen": "图文任务", "fx": "分享任务", "yxyq": "邀请任务",
        "goxcx": "跳转小程序", "go": "活动任务", "gz": "关注任务",
        "shop": "下单任务", "jqwq": "加群任务", "gzhkl": "公众号口令",
    }
    done = 0
    for key, label in groups.items():
        items = tl.get(key) or []
        if not items:
            continue
        for it in items:
            # 图文任务: twid 是图文ID, id 是任务ID(rwid)
            # 依据 page-frame.html: /event/web/web?twid={item.twid}&jty={item.jty}&url={item.url}&title={item.title}&rwid={item.id}
            if key == "tuwen":
                twid = it.get("twid") or it.get("id")
                rwid = it.get("id") or it.get("rwid")
            else:
                rwid = it.get("id") or it.get("rwid")
                twid = None
            title = it.get("title") or it.get("ztitle") or label
            jty = it.get("jty")
            if not rwid:
                continue
            # 已完成/不可做任务跳过 (小程序源码: status != -1 才加入可做列表)
            if it.get("status") == -1:
                continue
            # 图文任务: 需先"阅读"再上报 (web.js loadOK 调 duRWuTwMoney)
            if key == "tuwen":
                try:
                    if not twid:
                        log.info("   任务[%s] 无 twid, 跳过" % title)
                        continue
                    # 先获取等待时长(ydSeconds), 模拟阅读后再上报
                    yd = 0
                    try:
                        hi = _signed_post(phpsessid, {"ajax": "hd_info", "act": "hdinfo", "hid": TASK_HID})
                        yd = int((hi.get("var") or {}).get("ydSeconds") or 0)
                    except Exception:
                        yd = 0
                    log.info("   阅读任务[%s] twid=%s rwid=%s ydSeconds=%s" % (title, twid, rwid, yd))
                    if yd > 0:
                        log.info("   阅读任务[%s] 阅读 %ss 后上报..." % (title, yd))
                        _sleep(yd, yd + 1)
                    res = _signed_post(phpsessid, {
                        "act": "duRWuTwMoney", "ajax": "hd/rwu_new",
                        "hid": TASK_HID, "twid": twid, "rwid": rwid,
                    })
                    if (res.get("code") or 0) == 200:
                        money = res.get("money") or 0
                        jfen = res.get("jfen") or 0
                        if money or jfen:
                            log.info("   ✅ 阅读任务[%s] +%s元/%s积分" % (title, money, jfen))
                            done += 1
                        else:
                            log.info("   ✅ 阅读任务[%s] (无奖励)" % title)
                    else:
                        log.info("   阅读任务[%s] 未完成: %s" % (title, res.get("mess")))
                except Exception as e:
                    log.warn("   阅读任务[%s] 异常: %s" % (title, e))
                _sleep(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
                continue
            # 其他任务: 尝试完成
            try:
                res = _signed_post(phpsessid, {"act": "okGoXcx", "ajax": "hd/rwu_new", "appid": "", "rwid": rwid})
                if (res.get("code") or 0) == 200:
                    money = res.get("money") or 0
                    jfen = res.get("jfen") or 0
                    if money or jfen:
                        log.info("   ✅ 完成任务[%s] +%s元/%s积分" % (title, money, jfen))
                        done += 1
                    else:
                        log.info("   ✅ 完成任务[%s] (无奖励)" % title)
                else:
                    log.info("   任务[%s] 未完成: %s" % (title, res.get("mess")))
            except Exception as e:
                log.warn("   任务[%s] 异常: %s" % (title, e))
            _sleep(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)

    # 3. 每日抽奖
    try:
        _daily_lottery(phpsessid)
    except Exception as e:
        log.warn("   每日抽奖异常: %s" % e)

    # 4. 查询余额
    try:
        m = _signed_post(phpsessid, {"act": "getRWuMoney", "ajax": "hd/rwu", "hid": TASK_HID})
        if (m.get("code") or 0) == 200:
            log.info("   💰 可提现余额: %s 元 (最低 %s 元)" % (m.get("y_money"), m.get("min_money")))
    except Exception as e:
        log.warn("   查询余额失败: %s" % e)

def _daily_sign(phpsessid):
    """每日签到 (hid=177): qDao ty:0 查询, ty:1 签到, 若奖励为抽奖则 cjiang"""
    log.info("   📅 每日签到...")
    try:
        # 查询签到状态
        q = _signed_post(phpsessid, {"act": "qDao", "ty": 0})
        if (q.get("code") or 0) != 200:
            log.warn("   查询签到状态失败: %s" % q.get("mess"))
            return
        qdn = int(q.get("qdn") or 0)
        tday = int(q.get("tday") or 0)
        if tday != 0:
            log.info("   今日已签到 (累计 %s 天)" % qdn)
            return
        # 执行签到
        s = _signed_post(phpsessid, {"act": "qDao", "ty": 1})
        if (s.get("code") or 0) != 200:
            log.warn("   签到失败: %s" % s.get("mess"))
            return
        lxqd = s.get("lxqd") or []
        if lxqd:
            reward = lxqd[0]
            # reward[3]==1 表示奖励为抽奖
            if len(reward) > 3 and reward[3] == 1:
                log.info("   ✅ 签到成功! 获得抽奖机会, 开始抽奖...")
                _sign_lottery(phpsessid)
            else:
                log.info("   ✅ 签到成功! 获得 %s 金币" % (reward[0] if reward else "?"))
        else:
            log.info("   ✅ 签到成功!")
    except Exception as e:
        log.warn("   每日签到异常: %s" % e)

def _sign_lottery(phpsessid):
    """签到抽奖 (hid=177)"""
    try:
        r = _signed_post(phpsessid, {"ajax": "mzh/cjiang", "act": "cjiang", "hid": 177})
        if (r.get("code") or 0) == 200:
            jpin = r.get("jpin") or {}
            ty = jpin.get("ty")
            if ty == 3:
                log.info("   🎉 签到抽奖: +%s 元" % jpin.get("money"))
            elif ty == 4:
                log.info("   🎉 签到抽奖: +%s 金币" % jpin.get("jfen"))
            else:
                log.info("   🎉 签到抽奖: %s" % (jpin.get("name") or "未中奖"))
        else:
            log.warn("   签到抽奖失败: %s" % r.get("mess"))
    except Exception as e:
        log.warn("   签到抽奖异常: %s" % e)

def _daily_lottery(phpsessid):
    """每日抽奖 (cjHid=101)"""
    log.info("   🎰 每日抽奖...")
    try:
        c = _signed_post(phpsessid, {"ajax": "mzh/cjiang", "act": "cj_count", "hid": LOTTERY_HID})
        if (c.get("code") or 0) != 200:
            log.warn("   查询抽奖次数失败: %s" % c.get("mess"))
            return
        count = c.get("count") or {}
        today = count.get("cj_today", 0)
        total = count.get("daycjiang", 0)
        if today >= total:
            log.info("   今日抽奖次数已用完 (%s/%s)" % (today, total))
            return
        # 抽奖
        r = _signed_post(phpsessid, {"ajax": "mzh/cjiang", "act": "cjiang", "hid": LOTTERY_HID, "zdc": 100})
        if (r.get("code") or 0) == 200:
            jpin = r.get("jpin") or {}
            log.info("   🎉 抽奖结果: %s" % (jpin.get("name") or jpin.get("money") or "未中奖"))
        else:
            log.warn("   抽奖失败: %s" % r.get("mess"))
    except Exception as e:
        log.warn("   每日抽奖异常: %s" % e)

# ================= 主流程 =================
def process_account(wxid, remark):
    mask = (remark[:3] + "*****" + remark[-3:]) if len(remark) >= 7 else remark
    log.info("─" * 50)
    log.info("👤 账号: %s" % mask)

    # 1. 获取微信 code
    if not _HAS_GETCODE or not get_single_code:
        log.error("未安装 yyb 协议，无法获取微信 code")
        return
    try:
        code = get_single_code(APPID, wxid)
        if not code:
            log.error("获取 code 失败(空)")
            return
    except Exception as e:
        log.error("获取 code 异常: %s" % e)
        return

    # 2. 登录
    try:
        phpsessid, uid, appkey = login(code)
        if not uid:
            log.error("登录失败: 未获取到 uid")
            return
        log.info("   🔑 登录成功 uid=%s" % uid)
    except Exception as e:
        log.error("登录异常: %s" % e)
        return

    client = ManorClient(uid, phpsessid)

    # 2.5 任务中心(做任务领红包) + 每日抽奖
    try:
        task_center(phpsessid)
    except Exception as e:
        log.warn("任务中心异常: %s" % e)

    # 3. 获取状态
    try:
        st = client.status()
        data = st.get("data") or {}
        points = data.get("points", 0)
        cur_winery = data.get("current_winery") or {}
        winery_id = cur_winery.get("id") or data.get("profile", {}).get("current_winery_id") or 1
        log.info("   🏰 当前积分: %s, 酒庄: %s" % (points, cur_winery.get("name", winery_id)))
    except Exception as e:
        log.warn("获取状态失败: %s" % e)
        winery_id = 1

    # 4. 获取酒庄建筑
    try:
        w = client.winery(winery_id)
        buildings = (w.get("data") or {}).get("buildings") or []
    except Exception as e:
        log.warn("获取酒庄失败: %s" % e)
        buildings = []

    # 5. 处理每个建筑
    for b in buildings:
        bld = b.get("building") or {}
        btype = bld.get("type") or ""
        if not btype:
            continue
        bname = bld.get("name") or btype
        log.info("   🏗️  建筑: %s (%s)" % (bname, btype))

        # 5.1 查看当前任务
        try:
            task_resp = client.building_task(winery_id, btype)
            task = (task_resp.get("data") or {}).get("task")
        except Exception as e:
            log.warn("    获取任务失败: %s" % e)
            task = None

        if task:
            tid = task.get("id")
            remaining = task.get("remaining_seconds", 0)
            reward = task.get("reward_points", 0)
            # 可收获判断：can_harvest 为真，或 status=running 且剩余时间<=0
            status = task.get("status")
            can_harvest = bool(task.get("can_harvest")) or (
                status == "running" and remaining <= 0)
            log.info("    任务进行中: 剩余 %ss, 可收获=%s, 奖励=%s" % (remaining, can_harvest, reward))
            if can_harvest:
                try:
                    h = client.building_harvest(tid)
                    if (h.get("code") or 0) in (200, 0):
                        log.info("    ✅ 收获成功! +%s 积分" % reward)
                    else:
                        log.warn("    收获失败: %s" % h.get("message"))
                except Exception as e:
                    log.warn("    收获异常: %s" % e)
        else:
            # 无任务 -> 开始生产
            options = b.get("options") or []
            if not options:
                log.warn("    无生产选项，跳过")
                continue
            option_id = options[0].get("id")
            try:
                res = client.building_start(winery_id, btype, option_id)
                if (res.get("code") or 0) in (200, 0):
                    log.info("    ✅ 开始生产: %s (24h, 10积分)" % (options[0].get("name") or option_id))
                else:
                    log.warn("    开始生产失败: %s" % res.get("message"))
            except Exception as e:
                log.warn("    开始生产异常: %s" % e)

        # 5.2 今日任务自动完成（阅读故事/游戏挑战等，完成后获得6h加速）
        try:
            dt_resp = client.daily_tasks(winery_id, btype)
            dt_data = dt_resp.get("data") or {}
            daily_tasks = dt_data.get("daily_tasks") or []
        except Exception as e:
            log.warn("    获取今日任务失败: %s" % e)
            daily_tasks = []

        for dt in daily_tasks:
            ttype = dt.get("task_type")
            tname = dt.get("name") or ttype
            if dt.get("is_completed"):
                log.info("    今日任务[%s] 已完成" % tname)
                continue
            # 阅读类任务：先阅读酒庄故事，再完成任务
            if ttype == "read":
                try:
                    client.story(winery_id)
                    log.info("    今日任务[%s] 已阅读故事" % tname)
                except Exception as e:
                    log.warn("    今日任务[%s] 阅读故事异常: %s" % (tname, e))
            # 游戏类任务：尝试完成（若需先玩小游戏，接口会校验）
            elif ttype == "game":
                log.info("    今日任务[%s] 尝试完成游戏挑战" % tname)
            # 其他未知类型任务：同样尝试完成
            else:
                log.info("    今日任务[%s] 尝试完成" % tname)
            try:
                res = client.complete_daily_task(winery_id, btype, ttype)
                if (res.get("code") or 0) in (200, 0):
                    log.info("    ✅ 完成今日任务[%s] +6h加速" % tname)
                else:
                    log.warn("    完成今日任务[%s]失败: %s" % (tname, res.get("message")))
            except Exception as e:
                log.warn("    完成今日任务[%s]异常: %s" % (tname, e))

    # 5.3 酒柜自动合成（收集碎片合成酒款，获得积分）
    log.info("   🍷 检查酒柜合成...")
    try:
        col = client.collection(winery_id)
        col_data = col.get("data") or {}
        wines = col_data.get("wines") or []
        composable = [w for w in wines if w.get("status") == "composable"]
        if not wines:
            log.info("     酒柜为空，跳过合成")
        elif not composable:
            log.info("     暂无碎片可合成的酒款（%d 款中 %d 款已收集）" % (
                len(wines), sum(1 for w in wines if w.get("status") == "collected")))
        else:
            log.info("     发现 %d 款可合成酒款，开始自动合成..." % len(composable))
            for w in composable:
                # 源码 adaptCollection 里 wine 是扁平结构，字段直接在 wine 上
                wid = w.get("id")
                wname = w.get("name") or wid
                reward = w.get("rewardPoints", 0)
                frags = w.get("fragments") or {}
                log.info("     🍷 合成 [%s] 奖励+%s积分 (碎片: 风土%s/配方%s/陈酿%s/风味%s)" % (
                    wname, reward, frags.get("terroir", 0), frags.get("recipe", 0),
                    frags.get("aging_key", 0), frags.get("flavor_code", 0)))
                try:
                    res = client.compose(winery_id, wid)
                    if (res.get("code") or 0) in (200, 0):
                        got = (res.get("data") or {}).get("points", reward)
                        log.info("     ✅ 合成成功! +%s 积分" % got)
                    else:
                        log.warn("     合成失败: %s" % res.get("message"))
                except Exception as e:
                    log.warn("     合成异常: %s" % e)
                _sleep(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
    except Exception as e:
        log.warn("   获取酒柜失败: %s" % e)

    # 6. 最终状态
    try:
        st = client.status()
        points = (st.get("data") or {}).get("points", 0)
        log.info("   🏰 最终积分: %s" % points)
    except Exception:
        pass

# ================= 入口 =================
def main():
    # 账号列表
    accounts = []
    try:
        accs = load_accounts() if load_accounts else None
        if accs:
            accounts = [{"id": str(acc.get("openid") or acc.get("wxid") or acc.get("id") or ""), "note": acc.get("nickname") or acc.get("alias") or f"账号_{acc.get('id')}"} for acc in accs if (acc.get("openid") or acc.get("wxid") or acc.get("id"))]
    except Exception:
        pass

    if not accounts:
        raw = (os.getenv("WX_ID") or os.getenv("WXIDXH") or "").strip()
        accounts = [{"id": x.strip(), "note": x.strip()} for x in raw.split(",") if x.strip()]

    if not accounts:
        log.error("未配置账号，请设置 WX_ID 环境变量或使用 yyb.load_accounts()")
        return

    log.info("🔔 幸荟庄园, 开始! 共 %d 个账号" % len(accounts))
    for i, acc in enumerate(accounts):
        wxid = acc["id"]
        remark = acc.get("note") or wxid
        log.info("─" * 50)
        log.info("👤 [%d/%d] 账号: %s" % (i + 1, len(accounts), remark))
        try:
            process_account(wxid, remark)
        except Exception as e:
            log.error("账号处理异常: %s" % e)
        # 账号之间随机间隔，避免连续请求被识别为批量操作
        if i < len(accounts) - 1:
            gap = random.uniform(ACCOUNT_GAP_MIN, ACCOUNT_GAP_MAX)
            log.info("⏳ 等待 %.1fs 后处理下一个账号..." % gap)
            time.sleep(gap)

    log.info("全部完成!")

if __name__ == "__main__":
    main()