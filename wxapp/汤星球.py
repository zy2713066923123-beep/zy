# -*- coding: utf-8 -*-
"""
汤星球 双协议自动签到脚本
协议优先级：YYB Go 协议 > 牛子 WechatCodeAdapter > 手动模式
"""
import os
import re
import json
import time
import base64
import hashlib
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
    """安全地获取嵌套字典值"""
    cur = data
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return default
        if cur is None:
            return default
    return cur


def recursive_find_first_value(obj, key):
    """递归查找第一个匹配 key 的值"""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = recursive_find_first_value(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = recursive_find_first_value(v, key)
            if r is not None:
                return r
    return None


def find_phone(data):
    """从数据中提取手机号"""
    if isinstance(data, str):
        m = re.search(r"1[3-9]\d{9}", data)
        return m.group(0) if m else None
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ("phone", "phoneNumber", "mobile", "purePhoneNumber"):
                if isinstance(v, str) and re.match(r"^1[3-9]\d{9}$", v):
                    return v
            r = find_phone(v)
            if r:
                return r
    elif isinstance(data, list):
        for v in data:
            r = find_phone(v)
            if r:
                return r
    return None


def build_headers(token=None, extra=None):
    """构造请求头"""
    h = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 12; 2201123C Build/SKQ1.211006.001) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/89.0.4389.72 Safari/537.36 MicroMessenger/8.0.30",
        "Content-Type": "application/json",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
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


def _get_phone_number_yyb(wxid):
    """通过 YYB 获取手机号授权数据（复用 yyb 库）"""
    if not _yyb_client:
        return None
    try:
        return _yyb_client.get_phone_number(wxid, _APPID)
    except Exception as e:
        log.warning(f"YYB getPhoneNumber 异常: {e}")
        return None


def _extract_phone_auth_from_yyb(data):
    """从 YYB 返回中提取手机号授权信息。

    微信小程序 getPhoneNumber 通常返回 code（需后端换取手机号），
    部分协议直接返回明文手机号，这里两种都兼容。
    """
    if not data:
        return None
    # 优先取授权 code
    code = data.get("code") if isinstance(data, dict) else None
    if code and isinstance(code, str) and len(code) > 8:
        return {"code": code}
    # 其次取明文手机号
    phone = data.get("mobile") or data.get("masked_phone") if isinstance(data, dict) else None
    if not phone:
        phone = find_phone(data)
    if phone:
        return {"phone": phone}
    return None


# ============ 登录 ============
def _login_with_code(code, appid):
    """使用 code 登录，返回 token"""
    url = "https://api.tangxingqiu.com/api/login"
    try:
        r = requests.post(url, json={"code": code, "appid": appid}, timeout=15)
        data = r.json()
        token = get_nested(data, "data", "token") or get_nested(data, "token")
        if token:
            return token
        log.warning(f"登录失败: {data}")
    except Exception as e:
        log.warning(f"登录异常: {e}")
    return None


def _auth_phone(token, phone_data, retry=2):
    """会员授权手机号，处理'请先注册成为会员'。

    支持两种授权数据：
      - {"code": "..."}  微信 getPhoneNumber 授权 code
      - {"phone": "..."} 明文手机号
    失败自动重试，遇到"请先注册成为会员"则提示并返回 False。
    """
    url = "https://api.tangxingqiu.com/authPhone"
    for attempt in range(retry + 1):
        try:
            r = requests.post(url, json=phone_data, headers=build_headers(token), timeout=15)
            data = r.json()
            if data.get("code") == 0 or data.get("success"):
                log.info("手机号授权成功")
                return True
            msg = str(data.get("msg") or data.get("message") or "")
            if "会员" in msg or "注册" in msg:
                log.warning(f"需要先注册会员: {msg}")
                return False
            if attempt < retry:
                log.warning(f"授权失败({msg})，重试 {attempt + 1}/{retry}")
                time.sleep(1)
                continue
            log.warning(f"授权失败: {data}")
        except Exception as e:
            if attempt < retry:
                log.warning(f"authPhone 异常({e})，重试 {attempt + 1}/{retry}")
                time.sleep(1)
                continue
            log.warning(f"authPhone 异常: {e}")
    return False


# ============ 签到与宝箱 ============
def _do_draw(token, task_id, retry=2):
    """领取宝箱奖励"""
    url = "https://api.tangxingqiu.com/draw"
    for attempt in range(retry + 1):
        try:
            r = requests.post(url, json={"taskId": task_id}, headers=build_headers(token), timeout=15)
            data = r.json()
            if data.get("code") == 0 or data.get("success"):
                log.info(f"宝箱领取成功: taskId={task_id}")
                return data
            if attempt < retry:
                log.warning(f"draw 失败，重试 {attempt + 1}/{retry}")
                time.sleep(1)
                continue
            log.warning(f"draw 失败: {data}")
            return data
        except Exception as e:
            if attempt < retry:
                log.warning(f"draw 异常({e})，重试 {attempt + 1}/{retry}")
                time.sleep(1)
                continue
            log.warning(f"draw 异常: {e}")
    return None


def _check_and_draw_pending(token, days):
    """检查并领取宝箱（7/14/21/28 天节点）"""
    url = "https://api.tangxingqiu.com/detail"
    try:
        r = requests.get(url, headers=build_headers(token), timeout=15)
        data = r.json()
        boxes = get_nested(data, "data", "boxes") or get_nested(data, "data", "rewardList") or []
        for box in boxes:
            # 兼容多种字段命名：status / finishFlag+drawnFlag
            status = box.get("status")
            finish = box.get("finishFlag", 0)
            drawn = box.get("drawnFlag", 0)
            day = box.get("day") or box.get("days")
            task_id = box.get("id") or box.get("taskId") or box.get("rewardRecordId")
            if not task_id:
                continue
            if day == days and (status == "pending" or (finish and not drawn)):
                _do_draw(token, task_id)
    except Exception as e:
        log.warning(f"detail 异常: {e}")


def _create_sign(token, retry=2):
    """补签"""
    url = "https://api.tangxingqiu.com/sign/create"
    for attempt in range(retry + 1):
        try:
            r = requests.post(url, headers=build_headers(token), timeout=15)
            data = r.json()
            if data.get("code") == 0 or data.get("success"):
                return data
            if attempt < retry:
                log.warning(f"补签失败，重试 {attempt + 1}/{retry}")
                time.sleep(1)
                continue
            return data
        except Exception as e:
            if attempt < retry:
                log.warning(f"补签异常({e})，重试 {attempt + 1}/{retry}")
                time.sleep(1)
                continue
            log.warning(f"补签异常: {e}")
    return None


def _log_sign_success(token, days):
    """记录签到成功"""
    log.info(f"签到成功，累计 {days} 天")


def do_sign(token, retry=2):
    """执行签到主流程"""
    url = "https://api.tangxingqiu.com/sign"
    for attempt in range(retry + 1):
        try:
            r = requests.post(url, headers=build_headers(token), timeout=15)
            data = r.json()
            days = get_nested(data, "data", "days") or get_nested(data, "data", "accumulateDay") or 0
            if data.get("code") == 0 or data.get("success"):
                _log_sign_success(token, days)
                for d in (7, 14, 21, 28):
                    if days >= d:
                        _check_and_draw_pending(token, d)
                return True
            msg = str(data.get("msg") or data.get("message") or "")
            if "已签" in msg or "已完成" in msg:
                log.info(f"今日已签到: {msg}")
                return True
            if attempt < retry:
                log.warning(f"签到失败({msg})，重试 {attempt + 1}/{retry}")
                time.sleep(1)
                continue
            log.warning(f"签到失败: {data}")
        except Exception as e:
            if attempt < retry:
                log.warning(f"签到异常({e})，重试 {attempt + 1}/{retry}")
                time.sleep(1)
                continue
            log.warning(f"签到异常: {e}")
    return False


# ============ 任务类 ============
# 汤星球小程序 appid（与 yyb 取码共用）
_APPID = os.getenv("TXQ_APPID", "wx1234567890")


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
                # 自动授权手机号（会员注册/授权）
                phone_data = _extract_phone_auth_from_yyb(
                    _get_phone_number_yyb(wxid)
                )
                if phone_data:
                    _auth_phone(token, phone_data)
                # 签到 + 宝箱
                do_sign(token)
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