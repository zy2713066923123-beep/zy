# -*- coding: utf-8 -*-
"""
汤星球 双协议自动签到脚本
协议优先级：YYB Go 协议 > 牛子 WechatCodeAdapter > 手动模式
"""
import os
import json
import time
import logging
import subprocess
import requests
import urllib3

urllib3.disable_warnings()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("汤星球")

# ============ 环境变量配置 ============
txq_wxid_data = os.getenv("txq_wxid_data", "")
txq = os.getenv("txq", "")

# ============ 复用 yyb 统一协议库（端点 fallback / 频率控制 / 账号解析） ============
# 参考蒙娜丽莎.py / 上美广场.py：服务地址按优先级取环境变量，未配置才回退本地默认。
# 仅在用户确实配置过时才回写环境变量，避免默认值抢在 yyb.get_global_server_url() 之前生效。
try:
    import yyb
    _raw_server = (
        os.getenv("WX_SERVER")
        or os.getenv("YYB_SERVER")
        or os.getenv("WECHAT_SERVER")
        or os.getenv("YINGYONGBAO_SERVER")
        or ""
    ).strip().rstrip("/")
    if _raw_server:
        os.environ["WX_SERVER"] = _raw_server
        os.environ["YYB_SERVER"] = _raw_server
        os.environ["WECHAT_SERVER"] = _raw_server
    _yyb_client = yyb.YYBClient(_raw_server or None)
    log.info(f"已加载 yyb 协议库 @ {_yyb_client.server_url}")
except Exception as _e:
    _yyb_client = None
    log.warning(f"加载 yyb 协议库失败: {_e}")

# ============ 工具函数 ============
def get_nested(data, *keys, default=None):
    """安全地获取嵌套字典值。

    兼容两种调用方式：
      get_nested(data, "data", "rspMsg", "")      # 最后一个 "" 视为 default
      get_nested(data, "data", "result", "token") # 全部为 key
    """
    if not keys:
        return default
    # 若最后一个参数是空字符串，视为 default（兼容旧调用写法）
    if keys[-1] == "":
        keys = keys[:-1]
        default = ""
    cur = data
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return default
        if cur is None:
            return default
    return cur


def recursive_find_first_value(obj, keys):
    """递归查找第一个命中的字段值（keys 可为单个 key 或 key 列表）"""
    if isinstance(keys, str):
        keys = [keys]
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] is not None:
                return obj[k]
        for v in obj.values():
            r = recursive_find_first_value(v, keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = recursive_find_first_value(v, keys)
            if r is not None:
                return r
    return None


# ============ 汤星球（汤臣倍健）后端配置 ============
# 后端: vip.by-health.com，小程序 appid: wx9bb6d5ac457bd69d
HOST = "https://vip.by-health.com"
SIGN_PATH = "/vip-api/sign/daily/create"
DRAW_PATH = "/vip-api/sign/daily/draw"
DETAIL_PATH = "/vip-api/sign/activity/detail"
SIGN_ACTIVITY_ID = 11
LOGIN_PATH = "/vip-api/auth/ma/login"
AUTH_PHONE_PATH = "/vip-api/auth/ma/authPhone"
REWARD_TYPE_MAP = {0: "积分", 1: "微信红包", 2: "实物"}


def build_headers(token=None, extra=None):
    """构造请求头（汤臣倍健后端专用）"""
    h = {
        "Host": "vip.by-health.com",
        "Content-Type": "application/json;charset=utf-8",
        "Referer": f"https://servicewechat.com/{_APPID}/devtools/page-frame.html",
        "sec-ch-ua-mobile": "?1",
        "Accept": "*/*",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; MI 8 Build/QKQ1.190828.002; wv) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.136 "
            "Mobile Safari/537.36 XWEB/1340129 MMWEBSDK/20250201 MMWEBID/6533 "
            "MicroMessenger/8.0.60.2860(0x28003C51) WeChat/arm64 Weixin NetType/WIFI "
            f"Language/zh_CN ABI/arm64 miniProgram/{_APPID}"
        ),
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "sec-ch-ua-platform": "Android",
        "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Android WebView";v="134"',
        "x-requested-with": "com.tencent.mm",
        "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if token:
        h["Authorization"] = token
        h["Origin"] = "https://vip.by-health.com"
    if extra:
        h.update(extra)
    return h


# ============ 微信协议适配器（牛子） ============
def _get_wechat_adapter():
    """懒加载牛子 WechatCodeAdapter"""
    try:
        import WechatCodeAdapter
        return WechatCodeAdapter
    except ImportError:
        pass
    try:
        subprocess.run(["pip", "install", "-q", "WechatCodeAdapter"], check=False)
        import WechatCodeAdapter
        return WechatCodeAdapter
    except Exception as e:
        log.warning(f"加载 WechatCodeAdapter 失败: {e}")
        return None


# ============ YYB Go 协议（复用 yyb 库） ============
def _fetch_yyb_accounts():
    """从 YYB 拉取存活账号列表（复用 yyb 库的端点 fallback 与解析）。

    参考蒙娜丽莎.py：优先走 yyb.load_accounts()（内部会优先使用
    WX_ID / txq_wxid_data 环境变量过滤，未配置时自动同步 yyb_go 存活账号），
    返回账号 dict 列表，兼容 _parse_yyb_accounts。
    """
    if not _yyb_client:
        return []
    try:
        # 1) 优先用 load_accounts：支持 WX_ID / txq_wxid_data 过滤，返回 dict 列表
        accs = yyb.load_accounts()
        if accs:
            return accs
        # 2) 回退：get_online_accounts（过滤 hasSession=false 的小程序号）
        accs = _yyb_client.get_online_accounts()
        if accs:
            return accs
        # 3) 再回退：get_accounts（不过滤，尽量拉取全部账号）
        accs = _yyb_client.get_accounts(force_refresh=True)
        if accs:
            log.warning("get_online_accounts 过滤后为空，改用 get_accounts 全量账号")
            return accs
    except Exception as e:
        log.warning(f"YYB 拉取账号异常: {e}")
    return []


def _get_code_yyb(wxid):
    """通过 YYB 协议获取微信 code（复用 yyb 库，自动处理 openid/appid 与 fallback）"""
    if not _yyb_client:
        return None
    try:
        return _yyb_client.get_code(wxid, _APPID)
    except Exception as e:
        log.warning(f"YYB getCode 异常: {e}")
        return None





# ============ 登录 ============
def _login_with_code(code, appid):
    """使用微信 OAuth code 换取 Authorization token（汤臣倍健后端）"""
    url = f"{HOST}{LOGIN_PATH}"
    body = {"appId": appid, "code": code}
    try:
        r = requests.post(url, headers=build_headers(), json=body, timeout=15)
        data = r.json() if r.text else {}
        if not data.get("success"):
            log.warning(f"登录失败: {json.dumps(data, ensure_ascii=False)[:200]}")
            return None
        token = get_nested(data, "data", "result", "token")
        if token:
            return str(token)
        log.warning(f"未找到 token: {json.dumps(data, ensure_ascii=False)[:200]}")
    except Exception as e:
        log.warning(f"登录异常: {e}")
    return None


def _auth_phone(token, auth_code, appid):
    """调用 authPhone 接口完成会员注册/手机号授权，返回新 token 或 None。

    当签到返回 REGISTER_REQUIRED（请先注册成为会员）时，需要先用
    YYB 获取手机号授权 code，再调用本接口换取新的 Authorization。
    """
    if not auth_code:
        return None
    url = f"{HOST}{AUTH_PHONE_PATH}"
    headers = build_headers(token)
    headers["Referer"] = f"https://servicewechat.com/{appid}/112/page-frame.html"
    body = {
        "appId": appid,
        "code": auth_code,
        "nickName": "微信用户",
        "scene": "memberCenter",
        "channel": "memberCenter",
        "source": "ma",
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=15)
        data = r.json() if r.text else {}
    except Exception as e:
        log.warning(f"authPhone 请求异常: {e}")
        return None
    if not data.get("success"):
        log.warning(f"authPhone 失败: {json.dumps(data, ensure_ascii=False)[:240]}")
        return None
    new_token = get_nested(data, "data", "result", "token") or get_nested(data, "data", "token")
    if new_token:
        log.info(f"authPhone 成功! token={str(new_token)[:8]}...")
        return str(new_token)
    log.warning(f"authPhone 未返回 token: {json.dumps(data, ensure_ascii=False)[:240]}")
    return None


def _extract_phone_auth_from_yyb(token, wxid, appid, label=""):
    """从 YYB 获取手机号授权 code 并完成 authPhone，返回新 token 或 None。

    直接请求 /wxapp/getPhoneNumber 拿原始响应，递归提取 authCode/auth_code/code，
    兼容不同服务端返回结构（参考授权版 _get_phone_number_yyb）。
    """
    if not _yyb_client or not wxid:
        return None
    try:
        resolved = _yyb_client._resolve_ref(wxid)
        raw = _yyb_client._request_with_fallback(
            "POST", ["/api/yyb/get-phone", "/wxapp/getPhoneNumber"],
            json_data={"openid": resolved, "appid": appid},
        )
    except Exception as e:
        log.warning(f"{label}获取手机号授权异常: {e}")
        return None

    # 兼容 yyb-go 的 respJson 字符串
    if isinstance(raw, dict) and isinstance(raw.get("respJson"), str) and raw["respJson"].strip():
        try:
            inner = json.loads(raw["respJson"])
            if isinstance(inner, dict):
                raw = dict(raw)
                raw.update(inner)
        except Exception:
            pass

    root = raw
    if isinstance(raw, dict):
        root = raw.get("data") or raw.get("result") or raw
    auth_code = recursive_find_first_value(root, ["authCode", "auth_code", "code"])
    if not auth_code:
        log.warning(f"{label}未获取到手机号授权 code: {str(raw)[:300]}")
        return None
    new_token = _auth_phone(token, str(auth_code), appid)
    if new_token:
        mobile = recursive_find_first_value(root, ["mobile", "phone", "phoneNumber", "masked_phone"]) or ""
        if mobile:
            log.info(f"{label}手机号授权成功：{mobile}")
        else:
            log.info(f"{label}手机号授权成功")
    return new_token


# ============ 签到与宝箱 ============
def _do_draw(token, reward_record_id, label=""):
    """领取宝箱奖励，返回 reward 信息字符串或 None。"""
    url = f"{HOST}{DRAW_PATH}"
    try:
        r = requests.post(url, headers=build_headers(token), json={"rewardRecordId": reward_record_id}, timeout=15)
        data = r.json()
    except Exception as e:
        log.warning(f"{label}领取宝箱异常: {e}")
        return None

    if not data.get("success"):
        log.warning(f"{label}领取宝箱失败: {json.dumps(data, ensure_ascii=False)[:120]}")
        return None

    rsp_code = get_nested(data, "data", "rspCode", "")
    rsp_msg = get_nested(data, "data", "rspMsg", "")
    result = get_nested(data, "data", "result") or {}
    if rsp_code == "00" and result:
        reward_name = result.get("msg") or f"奖励类型{result.get('rewardType', '?')} x{result.get('rewardValue', '?')}"
        log.info(f"{label}宝箱领取成功：{reward_name}")
        return reward_name
    log.warning(f"{label}宝箱领取：{rsp_msg}")
    return None


def _check_and_draw_pending(token, label=""):
    """调用 detail 接口检查签到进度 & 领取漏领的宝箱。

    detail 返回 rewardList，包含 7/14/21/28 天四个宝箱节点：
      finishFlag=1 drawnFlag=0 rewardRecordId=<ID> → 已达成但未领取 → 自动 draw
      finishFlag=1 drawnFlag=1 → 已领取
      finishFlag=0 → 未达成

    返回 (sign_flag, drew_any)。
    """
    url = f"{HOST}{DETAIL_PATH}"
    try:
        r = requests.post(url, headers=build_headers(token), json={}, timeout=15)
        data = r.json()
    except Exception as e:
        log.warning(f"{label}获取签到详情失败: {e}")
        return None, False

    if not data.get("success"):
        return None, False

    result = get_nested(data, "data", "result") or {}
    current_count = result.get("currentCount", "?")
    sign_flag = result.get("signFlag", 0)
    reward_list = result.get("rewardList") or []

    pending = []
    for reward in reward_list:
        day = reward.get("day", "?")
        finish_flag = reward.get("finishFlag", 0)
        drawn_flag = reward.get("drawnFlag", 0)
        record_id = reward.get("rewardRecordId")
        reward_name = reward.get("rewardName") or ""
        reward_type = REWARD_TYPE_MAP.get(reward.get("rewardType"), "未知")
        reward_value = reward.get("rewardValue", "")
        if finish_flag and not drawn_flag and record_id:
            display = reward_name or f"{reward_type} x{reward_value}"
            pending.append((day, record_id, display))

    if pending:
        for day, record_id, display in pending:
            log.info(f"{label}第{day}天宝箱待领取：{display}，正在领取...")
            _do_draw(token, record_id, label)
        return sign_flag, True

    next_milestone = None
    for reward in reward_list:
        if not reward.get("finishFlag", 0):
            next_milestone = reward
            break
    if next_milestone:
        next_day = next_milestone.get("day", "?")
        remaining = next_milestone.get("remainingDay", "?")
        next_name = next_milestone.get("rewardName") or ""
        next_type = REWARD_TYPE_MAP.get(next_milestone.get("rewardType"), "")
        next_value = next_milestone.get("rewardValue", "")
        next_display = next_name or f"{next_type} x{next_value}"
        log.info(f"{label}签到进度：第{current_count}天，距第{next_day}天宝箱（{next_display}）还有{remaining}天")
    else:
        log.info(f"{label}签到进度：第{current_count}天，本期宝箱已全部领取")
    return sign_flag, False


def _create_sign(token):
    """调用签到接口，返回 JSON dict。"""
    url = f"{HOST}{SIGN_PATH}"
    r = requests.post(url, headers=build_headers(token), json={"activityId": SIGN_ACTIVITY_ID}, timeout=15)
    return r.json()


def _log_sign_success(result, label="", prefix=""):
    """打印签到成功日志。"""
    coins = result.get("dailyPointReward")
    accumulate = result.get("accumulateDay", "?")
    remaining = result.get("remainingDay", "?")
    log.info(f"{label}{prefix}签到成功：+{coins} 积分（累计{accumulate}天，距下次宝箱{remaining}天）")


def do_sign(token, label="", account=None, member_retry=False):
    """执行签到，返回 True/False。

    完整流程：
    1. 先调 detail 检查签到进度 & 领取漏领的宝箱（7/14/21/28天节点）
    2. 调 create 签到：
       - 宝箱挡签（undrawnFlag=1）：先 draw 再补 create
       - 正常签到：dailyPointReward 有值
       - 今日已签：dailyPointReward=null 无宝箱
       - REGISTER_REQUIRED（请先注册成为会员）：先 authPhone 授权再重签
    """
    # 步骤1：detail 预检，领取漏领宝箱
    sign_flag, drew_any = _check_and_draw_pending(token, label)

    # 步骤2：签到
    data = None
    for retry in range(3):
        try:
            data = _create_sign(token)
            break
        except Exception as e:
            if retry >= 2:
                log.warning(f"{label}签到异常: {e}")
                return False
            time.sleep(1)
    if data is None:
        return False

    if not data.get("success"):
        log.warning(f"{label}签到失败: {json.dumps(data, ensure_ascii=False)[:120]}")
        return False

    result = get_nested(data, "data", "result") or {}
    rsp_msg = get_nested(data, "data", "rspMsg", "") or ""
    rsp_code = get_nested(data, "data", "rspCode", "") or ""

    if rsp_code != "00":
        if "已签" in rsp_msg or "已完成" in rsp_msg:
            log.info(f"{label}签到：{rsp_msg}")
            return True
        if "请先注册成为会员" in rsp_msg and account and not member_retry:
            log.warning(f"{label}{rsp_msg}")
            wxid = str(account.get("id") or account.get("openid") or account.get("wxid") or "").strip()
            new_token = _extract_phone_auth_from_yyb(token, wxid, _APPID, label)
            if new_token:
                log.info(f"{label}会员授权后重新签到...")
                return do_sign(new_token, label, account=account, member_retry=True)
        log.warning(f"{label}{rsp_msg or json.dumps(data, ensure_ascii=False)[:80]}")
        return False

    coins = result.get("dailyPointReward")
    undrawn_flag = result.get("undrawnFlag", 0)
    undrawn_record_id = result.get("undrawnRecordId")

    # 情况1：签到成功
    if coins is not None:
        _log_sign_success(result, label)
        if undrawn_flag and undrawn_record_id:
            undrawn_name = result.get("undrawnRewardName", "宝箱奖励")
            log.info(f"{label}发现待领取宝箱：{undrawn_name}")
            _do_draw(token, undrawn_record_id, label)
        return True

    # 情况2：dailyPointReward 为 null 且有宝箱ID → 宝箱挡在签到前，先领宝箱再补签
    if undrawn_flag and undrawn_record_id:
        undrawn_name = result.get("undrawnRewardName", "宝箱奖励")
        log.info(f"{label}到达宝箱节点，签到前先领宝箱：{undrawn_name}")
        _do_draw(token, undrawn_record_id, label)
        time.sleep(1)
        try:
            data2 = _create_sign(token)
        except Exception as e:
            log.warning(f"{label}领取宝箱后补签异常: {e}")
            return False
        if data2.get("success") and get_nested(data2, "data", "rspCode", "") == "00":
            result2 = get_nested(data2, "data", "result") or {}
            if result2.get("dailyPointReward") is not None:
                _log_sign_success(result2, label, prefix="宝箱领取后")
                return True
        log.info(f"{label}宝箱已处理，今日签到状态以服务端为准")
        return True

    # 情况3：全字段 null 且无宝箱 → 今日已签到过
    log.info(f"{label}今日已签到过")
    return True


# ============ 任务类 ============
# 汤星球小程序 appid（与 yyb 取码共用）——汤臣倍健小程序
_APPID = os.getenv("TXQ_APPID", "wx9bb6d5ac457bd69d")


class AutoTask:
    def __init__(self, appid=_APPID):
        self.appid = appid
        self.adapter = None

    def log(self, msg):
        log.info(msg)

    def _ensure_adapter(self):
        if self.adapter is None:
            self.adapter = _get_wechat_adapter()
        return self.adapter

    def _parse_accounts(self, raw):
        """解析账号列表，生成器"""
        if not raw:
            return
        if isinstance(raw, str):
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                if ":" in line:
                    wxid, pwd = line.split(":", 1)
                    yield {"wxid": wxid.strip(), "pwd": pwd.strip()}
                else:
                    yield {"wxid": line, "pwd": ""}
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    yield item
                elif isinstance(item, str):
                    yield {"wxid": item, "pwd": ""}

    def _parse_yyb_accounts(self, accounts):
        """解析 YYB 账号列表"""
        for acc in accounts:
            if isinstance(acc, dict):
                yield acc

    def run(self, mode="yyb"):
        """主运行入口"""
        if mode == "yyb":
            if not _yyb_client:
                self.log("yyb 协议库未加载，无法拉取账号")
                return
            accounts = _fetch_yyb_accounts()
            if not accounts:
                self.log("YYB 未拉取到存活账号")
                return
            self.log(f"共拉取 {len(accounts)} 个存活账号")
            for i, acc in enumerate(self._parse_yyb_accounts(accounts), 1):
                # 优先用自增 id（纯数字），保证 yyb._resolve_ref 走 isdigit 分支直接命中
                wxid = str(acc.get("id") or acc.get("openid") or acc.get("wxid") or "").strip()
                if not wxid:
                    continue
                self.log(f"处理账号 [{i}/{len(accounts)}]: {wxid}")
                code = _get_code_yyb(wxid)
                if not code:
                    self.log(f"账号 {wxid} 获取 code 失败")
                    continue
                token = _login_with_code(code, self.appid)
                if not token:
                    self.log(f"账号 {wxid} 登录失败")
                    continue
                # 签到 + 宝箱（account 用于 REGISTER_REQUIRED 时手机号授权重签）
                do_sign(token, account=acc)
                # 账号间延时，规避限流
                if i < len(accounts):
                    time.sleep(2)
        elif mode == "niu":
            adapter = self._ensure_adapter()
            if not adapter:
                self.log("牛子适配器不可用")
                return
            for acc in self._parse_accounts(txq_wxid_data):
                wxid = acc.get("wxid")
                if not wxid:
                    continue
                self.log(f"处理账号: {wxid}")
                code = adapter.get_code(wxid)
                if not code:
                    self.log(f"账号 {wxid} 获取 code 失败")
                    continue
                token = _login_with_code(code, self.appid)
                if not token:
                    self.log(f"账号 {wxid} 登录失败")
                    continue
                do_sign(token)
        else:
            for acc in self._parse_accounts(txq):
                wxid = acc.get("wxid")
                if not wxid:
                    continue
                self.log(f"处理账号: {wxid}")
                code = acc.get("code")
                if not code:
                    self.log(f"账号 {wxid} 无 code")
                    continue
                token = _login_with_code(code, self.appid)
                if not token:
                    self.log(f"账号 {wxid} 登录失败")
                    continue
                do_sign(token)


if __name__ == "__main__":
    mode = os.getenv("TXQ_MODE", "yyb")
    AutoTask().run(mode=mode)