#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 甜润世界签到施肥
# cron: 48 13,01 * * *
import yyb  # 自动同步 yyb_go 存活账号

import os
import re
import time
import json
import requests
from datetime import datetime
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

APPID = "wx210e40a77dbe7a27"
APP_NAME = "甜润世界签到施肥"
BASE = "https://m.ahzyssl.com"
UA = "Mozilla/5.0 (Linux; Android 14; PJE110) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36 MiniProgramEnv/android"

BASE_HEADERS = {
    "Host": "m.ahzyssl.com",
    "Connection": "keep-alive",
    "charset": "utf-8",
    "User-Agent": UA,
    "Referer": f"https://servicewechat.com/{APPID}/page-frame.html",
}

# ========== 从 YYB_SERVER 读取服务地址 ==========
# ============ 统一取码（WX_ID + getCode，支持牛子/YYB 双协议自动路由）============

# 统一解析服务地址：四个变量任取其一。
# 仅在用户确实配置过时才回写环境变量——若把默认值写进 YYB_SERVER，
# 会抢在 yyb.get_global_server_url() 的 WECHAT_SERVER 之前生效，导致连错服务。
_RAW_SERVER = (
    os.getenv("WX_SERVER")
    or os.getenv("YYB_SERVER")
    or os.getenv("WECHAT_SERVER")
    or os.getenv("YINGYONGBAO_SERVER")
    or ""
).strip().rstrip("/")

WECHAT_SERVER = _RAW_SERVER or "http://127.0.0.1:18273"
YYB_SERVER = WECHAT_SERVER

if _RAW_SERVER:
    os.environ["WX_SERVER"] = _RAW_SERVER
    os.environ["YYB_SERVER"] = _RAW_SERVER
    os.environ["WECHAT_SERVER"] = _RAW_SERVER
else:
    print("⚠️ 未配置 WX_SERVER/YYB_SERVER/WECHAT_SERVER，正在使用默认地址 http://127.0.0.1:18273")

# ============ 账号来源：优先 yyb-go 存活账号，WX_ID 仅作兜底 ============
ACCOUNT_NAMES: dict = {}


def sync_yyb_accounts() -> list:
    """直接用 YYBClient 拉取 yyb-go 存活账号，并打印排查信息。"""
    try:
        from yyb import YYBClient
    except Exception as e:
        print(f"[yyb] 无法导入 yyb 模块: {e}")
        return []

    client = YYBClient()
    print(f"[yyb] 服务端地址: {client.server_url}")

    try:
        raw = client.get_accounts(force_refresh=True)
    except Exception as e:
        print(f"[yyb] 请求账号列表失败: {e}")
        return []
    print(f"[yyb] 服务端返回 {len(raw)} 个账号")

    try:
        accounts = client.get_online_accounts()
    except Exception as e:
        print(f"[yyb] 过滤存活账号失败: {e}")
        return []

    ids = []
    for idx, acc in enumerate(accounts, 1):
        ident = str(acc.get("openid") or acc.get("wxid") or acc.get("id") or "").strip()
        if not ident:
            continue
        ids.append(ident)
        ACCOUNT_NAMES[ident] = (
            acc.get("remark") or acc.get("nickname") or acc.get("alias") or f"账号_{idx}"
        )
    if ids:
        print(f"[yyb] 自动从 yyb_go 同步到 {len(ids)} 个存活账号")
    else:
        print("[yyb] yyb_go 无存活账号（可能全部离线或 hasSession 失效）")
    return ids


WX_IDS = sync_yyb_accounts()

if not WX_IDS:
    for line in os.getenv("WX_ID", "").replace("&", "\n").splitlines():
        line = line.strip()
        if not line:
            continue
        ident, _, remark = line.partition("#")
        ident = ident.strip()
        if not ident:
            continue
        WX_IDS.append(ident)
        ACCOUNT_NAMES[ident] = remark.strip() or ident
    if WX_IDS:
        print(f"[wx] 回退使用 WX_ID 配置的 {len(WX_IDS)} 个账号")

print(f"✅ 读取到 {len(WX_IDS)} 个微信账号，自动路由牛子/YYB 双协议")


def code_login(openid: str) -> str | None:
    """登录获取 authToken（从 cookie 中提取 applet_auth_token）"""
    try:
        from yyb import get_single_code as _get_code
    except Exception:
        _get_code = globals().get("get_single_code")
    if not _get_code:
        print("❌ 未找到 yyb 取码函数 get_single_code")
        return None
    code = _get_code(APPID, openid)
    if not code:
        return None
    try:
        session = requests.Session()
        resp = session.get(
            f"{BASE}/wx/user/login",
            params={"code": code, "state": ""},
            headers={"User-Agent": UA},
            allow_redirects=False,
            timeout=20,
            verify=False,
            proxies={"http": None, "https": None}
        )
        # 尝试从 set-cookie 提取
        for cookie in session.cookies:
            if cookie.name == "applet_auth_token":
                print(f"✅ 登录成功，authToken: {cookie.value[:8]}...")
                return cookie.value

        # 尝试从 set-cookie header 手动解析
        set_cookies = resp.headers.get("Set-Cookie", "")
        m = re.search(r"applet_auth_token=([^;]+)", set_cookies)
        if m:
            print(f"✅ 登录成功，authToken: {m.group(1)[:8]}...")
            return m.group(1)

        # 尝试从页面内容提取
        if resp.text:
            m2 = re.search(r'applet_auth_token[=：]\s*["\']?([^"\';\s]+)', resp.text)
            if m2:
                print(f"✅ 从页面提取 authToken: {m2.group(1)[:8]}...")
                return m2.group(1)

        print(f"❌ 登录失败：未获取到token，状态码: {resp.status_code}")
        print(f"   响应头: {dict(resp.headers)}")
        print(f"   响应体: {resp.text[:500]}")
        return None
    except Exception as e:
        print(f"❌ 登录异常: {e}")
        return None


def do_request(auth_token: str, url: str, desc: str, method: str = "GET") -> dict | None:
    headers = {**BASE_HEADERS, "Authorization": auth_token}
    try:
        if method == "POST":
            resp = requests.post(url, headers=headers, timeout=45, verify=False,
                                 proxies={"http": None, "https": None})
        else:
            resp = requests.get(url, headers=headers, timeout=45, verify=False,
                                proxies={"http": None, "https": None})
        data = resp.json()
        msg = (data or {}).get("msg", "操作成功")
        print(f"[{desc}] {msg}")
        return data
    except Exception as e:
        err_msg = str(e)
        print(f"[{desc}] 失败: {err_msg}")
        return None


def sign_in_award(auth_token: str) -> list:
    """签到有奖"""
    logs = []
    resp = do_request(auth_token, f"{BASE}/applet/user/signIn/getUserSignInLog", "查询签到有奖状态")
    if not resp or resp.get("code") != 200:
        logs.append("查询签到有奖状态失败")
        return logs
    today = datetime.now().strftime("%Y-%m-%d")
    sign_list = (resp.get("data") or {}).get("userSignInList") or []
    signed = any(
        (i.get("signInDate") == today and i.get("signInStatus") == 1)
        for i in sign_list
    )
    if signed:
        logs.append("签到有奖：今日已完成")
    else:
        do_sign = do_request(auth_token, f"{BASE}/applet/user/signIn", "执行签到有奖", "POST")
        logs.append("签到有奖成功" if do_sign and do_sign.get("code") == 200 else "签到有奖失败")
    return logs


def dendrobium_sign(auth_token: str) -> list:
    """石斛签到"""
    logs = []
    resp = do_request(auth_token, f"{BASE}/applet/game/dendrobium/signIn/getUserSignInLog", "查询石斛签到状态")
    if resp and (resp.get("data") or {}).get("todaySignInStatus"):
        logs.append("石斛签到：今日已完成")
    else:
        do_sign = do_request(auth_token, f"{BASE}/applet/game/dendrobium/signIn", "执行石斛签到")
        logs.append("石斛签到成功" if do_sign and do_sign.get("code") == 200 else "石斛签到失败")
    return logs


def browse_articles(auth_token: str) -> list:
    """推文浏览（3次，每次等30-40秒）"""
    print("\n===== 检查推文浏览 =====")
    test = do_request(auth_token, f"{BASE}/applet/game/dendrobium/article/completeRead", "检查推文状态")
    if not test or test.get("code") != 200 or not (test.get("msg") or "").startswith("肥料"):
        print("今日推文已完成，跳过")
        return ["今日推文已完成，跳过"]

    logs = []
    for i in range(1, 4):
        sec = 30 + int(os.urandom(1)[0] % 11)
        print(f"第{i}次浏览，等待{sec}秒")
        time.sleep(sec)
        res = do_request(auth_token, f"{BASE}/applet/game/dendrobium/article/completeRead", f"第{i}次推文浏览")
        if res and res.get("code") == 200:
            logs.append(f"第{i}次浏览成功")
        else:
            logs.append(f"第{i}次浏览已完成")
            break
        time.sleep(2)
    return logs


def buy_fertilizer(auth_token: str) -> list:
    """徽宝买肥料"""
    print("\n===== 徽宝买肥料 =====")
    logs = []

    # 1. 查积分
    user_info = do_request(auth_token, f"{BASE}/applet/game/dendrobium/getUserInfo", "查询积分")
    if not user_info or user_info.get("code") != 200:
        logs.append("查询积分失败")
        return logs
    integrate = (user_info.get("data") or {}).get("integrate", 0)
    logs.append(f"当前徽宝: {integrate}")

    # 2. 查商品
    goods_resp = do_request(auth_token, f"{BASE}/applet/game/dendrobium/goods/list?type=1", "查询肥料商品")
    if not goods_resp or goods_resp.get("code") != 200 or not goods_resp.get("data"):
        logs.append("查询商品列表失败")
        return logs

    # 按价格降序，优先买贵的（200g > 100g）
    goods_list = sorted(goods_resp["data"], key=lambda x: x.get("price", 0), reverse=True)
    remain = integrate

    for item in goods_list:
        price = item.get("price", 0)
        if price <= 0:
            continue
        max_count = remain // price
        if max_count <= 0:
            continue
        goods_name = item.get("goodsName", "")
        goods_id = item.get("goodsId", "")
        print(f"购买 {goods_name} x{max_count} (共{max_count * price}徽宝)")
        for i in range(max_count):
            order = do_request(
                auth_token,
                f"{BASE}/applet/game/dendrobium/order/placeOrder?goodsId={goods_id}&goodsNum=1",
                f"买{goods_name} 第{i+1}次"
            )
            if order and order.get("code") == 200:
                remain -= price
            else:
                break
            time.sleep(1)

    spent = integrate - remain
    logs.append(f"共花费 {spent} 徽宝，剩余 {remain} 徽宝")
    return logs


def exhaust_fertilizer(auth_token: str) -> list:
    """自动施肥（肥料<100g停止）"""
    print("\n===== 开始自动施肥 =====")
    logs = []
    count = 0
    while True:
        info = do_request(auth_token, f"{BASE}/applet/game/dendrobium/get", "查询肥料数量")
        if not info or info.get("code") != 200:
            break
        val = (info.get("data") or {}).get("fertilizer", 0)
        if val < 100:
            logs.append(f"肥料剩余{val}g，停止")
            break
        do_request(auth_token, f"{BASE}/applet/game/dendrobium/fertilizer", f"施肥第{count+1}次")
        count += 1
        time.sleep(1)
    logs.append(f"共施肥{count}次")
    return logs


def run_account(openid: str) -> bool:
    wxid = ACCOUNT_NAMES.get(openid) or openid
    print(f"\n{'=' * 40}")
    print(f" 甜润世界 | {wxid} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 40}")

    auth_token = code_login(openid)
    if not auth_token:
        print("❌ 登录失败，跳过")
        return False

    all_logs = []

    # 1. 签到有奖
    all_logs.extend(sign_in_award(auth_token))

    # 2. 石斛签到
    all_logs.extend(dendrobium_sign(auth_token))

    # 3. 推文浏览
    all_logs.extend(browse_articles(auth_token))

    # 4. 徽宝买肥料
    all_logs.extend(buy_fertilizer(auth_token))

    # 5. 自动施肥
    all_logs.extend(exhaust_fertilizer(auth_token))

    print(f"\n📋 汇总: {'; '.join(all_logs)}")
    return True


try:
    import notify
except ImportError:
    notify = None

if __name__ == "__main__":
    if not WX_IDS:
        msg = "未获取到任何账号：请确认 WX_SERVER/YYB_SERVER 指向 yyb-go 且有存活账号，或配置 WX_ID"
        print(f"❌ {msg}")
        if notify:
            notify.send(APP_NAME, msg)
        raise SystemExit(1)

    results = []
    for i, openid in enumerate(WX_IDS):
        name = ACCOUNT_NAMES.get(openid) or openid
        ok = run_account(openid)
        results.append(f"{name}: {'✅' if ok else '❌'}")
        if i < len(WX_IDS) - 1:
            time.sleep(5)

    summary = "\n".join(results)
    print(summary)
    if notify:
        notify.send(APP_NAME, summary)