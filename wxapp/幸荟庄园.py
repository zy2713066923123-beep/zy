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
MANOR_BASE = "https://yy.fenggewenhua.com"
# 登录域名
LOGIN_BASE = "https://xcx.fenggewenhua.com"

# 建筑类型
BUILDING_TYPES = ["plant", "brew", "age", "bottle"]

# 每日任务类型
DAILY_TASK_TYPES = ["read", "game"]

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
    """调用 mzh.php 登录，返回 (phpsessid, uid, appkey)"""
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
        "User-Agent": "Mozilla/5.0 (Linux; Android 15; M2012K11AC Build/AQ3A.250226.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/150.0.7871.181 Mobile Safari/537.36 XWEB/1500047 MMWEBSDK/20260502 MMWEBID/3433 MicroMessenger/8.0.76.3141(0x28004C54) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android",
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
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; M2021K11AC Build/AQ3A.250226.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/150.0.7871.181 Mobile Safari/537.36 XWEB/1500047 MMWEBSDK/20260502 MMWEBID/3433 MicroMessenger/8.0.76.3141(0x28004C54) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android",
        })
        if phpsessid:
            self.session.headers["phpsession"] = phpsessid

    def _post(self, path, params):
        url = MANOR_BASE + path
        # 过滤空值
        data = {k: v for k, v in params.items() if v is not None and v != ""}
        resp = self.session.post(url, data=data, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def status(self):
        return self._post("/manor/status", {"uid": self.uid})

    def winery(self, winery_id=1):
        return self._post("/manor/winery", {"uid": self.uid, "winery_id": winery_id})

    def building_task(self, winery_id, building_type):
        return self._post("/manor/building/task", {"uid": self.uid, "winery_id": winery_id, "building_type": building_type})

    def building_start(self, winery_id, building_type, option_id):
        return self._post("/manor/building/start", {"uid": self.uid, "winery_id": winery_id, "building_type": building_type, "option_id": option_id})

    def building_harvest(self, winery_id, building_type, task_id):
        return self._post("/manor/building/harvest", {"uid": self.uid, "task_id": task_id})

    def daily_tasks(self, winery_id, building_type):
        return self._post("/manor/building/daily-tasks", {"uid": self.uid, "winery_id": winery_id, "building_type": building_type})

    def complete_daily_task(self, winery_id, building_type, task_type):
        return self._post("/manor/building/daily-task/complete", {"uid": self.uid, "winery_id": winery_id, "building_type": building_type, "task_type": task_type})

    def story(self, winery_id=1):
        return self._post("/manor/story", {"uid": self.uid, "winery_id": winery_id, "mode": "random"})

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
            can_harvest = task.get("can_harvest")
            remaining = task.get("remaining_seconds", 0)
            reward = task.get("reward_points", 0)
            log.info("    任务进行中: 剩余 %ss, 可收获=%s, 奖励=%s" % (remaining, can_harvest, reward))
            if can_harvest:
                try:
                    h = client.building_harvest(winery_id, btype, tid)
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

        # 5.2 每日任务
        try:
            dt_resp = client.daily_tasks(winery_id, btype)
            dt_data = dt_resp.get("data") or {}
            daily_tasks = dt_data.get("daily_tasks") or []
        except Exception as e:
            log.warn("    获取每日任务失败: %s" % e)
            daily_tasks = []

        for dt in daily_tasks:
            ttype = dt.get("task_type")
            tname = dt.get("name") or ttype
            if dt.get("is_completed"):
                log.info("    每日任务[%s] 已完成" % tname)
                continue
            # 阅读任务先读故事
            if ttype == "read":
                try:
                    client.story(winery_id)
                except Exception:
                    pass
            try:
                res = client.complete_daily_task(winery_id, btype, ttype)
                if (res.get("code") or 0) in (200, 0):
                    log.info("    ✅ 完成每日任务[%s] +6h加速" % tname)
                else:
                    log.warn("    完成每日任务[%s]失败: %s" % (tname, res.get("message")))
            except Exception as e:
                log.warn("    完成每日任务[%s]异常: %s" % (tname, e))

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
        time.sleep(2)

    log.info("全部完成!")

if __name__ == "__main__":
    main()