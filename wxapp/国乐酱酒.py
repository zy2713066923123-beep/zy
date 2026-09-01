#!/usr/bin/env python3
# name: 国乐酱酒
# cron: 28 09,21 * * *
# -*- coding: utf-8 -*-

# yyb-go 协议通用库：自动同步 yyb_go 存活账号、统一取码（参考幸荟庄园.py）
try:
    from yyb import get_single_code, load_accounts
except ImportError:
    try:
        import yyb
        get_single_code = getattr(yyb, "get_single_code", None)
        load_accounts = getattr(yyb, "load_accounts", None)
    except ImportError:
        get_single_code = None
        load_accounts = None

import os
import time
import requests
from datetime import datetime

APPID = "wxeff120e4d11594c0"
APP_NAME = "国乐酱酒"
BASE = "https://member.guoyuejiu.com"
UA = "Mozilla/5.0 (Linux; Android 15; 22061218C Build/AQ3A.250226.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.177 Mobile Safari/537.36 XWEB/1460075 MMWEBSDK/20260202 MMWEBID/6435 MicroMessenger/8.0.71.3080(0x18004739) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android"

# ========== 从 YYB_SERVER 读取服务地址 ==========
# ============ 统一取码（WX_ID + getCode，支持牛子/YYB 双协议自动路由）============

# ============ 账号来源：优先从 yyb-go 拉取存活账号，WX_ID 仅作兜底 ============
WX_IDS = []
try:
    accs = load_accounts()
    if accs:
        WX_IDS = [str(acc.get("openid") or acc.get("wxid") or acc.get("id") or "") for acc in accs
                  if (acc.get("openid") or acc.get("wxid") or acc.get("id"))]
        print(f"ℹ️  已从 yyb-go 同步 {len(WX_IDS)} 个存活账号")
except Exception:
    pass

if not WX_IDS:
    WX_IDS = [s.strip() for s in os.getenv("WX_ID", "").replace("&", "\n").splitlines() if s.strip()]
    if WX_IDS:
        print(f"ℹ️  yyb-go 无存活账号，回退使用 WX_ID 配置的 {len(WX_IDS)} 个账号")

# 服务地址：优先 WX_SERVER，其次 YYB_SERVER / WECHAT_SERVER / YINGYONGBAO_SERVER（与 yyb.get_global_server_url 一致）
# 使用 setdefault，避免把已配置的服务地址覆盖成 127.0.0.1:8000
SERVER_URL = (
    os.getenv("WX_SERVER")
    or os.getenv("YYB_SERVER")
    or os.getenv("WECHAT_SERVER")
    or os.getenv("YINGYONGBAO_SERVER")
    or "http://127.0.0.1:18273"
).strip().rstrip("/")
os.environ.setdefault("WX_SERVER", SERVER_URL)
os.environ.setdefault("YYB_SERVER", SERVER_URL)
os.environ.setdefault("WECHAT_SERVER", SERVER_URL)
os.environ.setdefault("YINGYONGBAO_SERVER", SERVER_URL)

print(f"✅ 读取到 {len(WX_IDS)} 个微信账号，自动路由牛子/YYB 双协议 (yyb-go: {SERVER_URL})")


def code_login(openid: str) -> str | None:
    code = get_single_code(APPID, openid)
    if not code:
        return None
    try:
        payload = {
            "avatarUrl": "https://thirdwx.qlogo.cn/mmopen/vi_32/POgEwh4mIHO4nibH0KlMECNjjGxQUq24ZEaGT4poC6icRiccVGKSyXwibcPq4BWmiaIGuG1icwxaQX6grC9VemZoJ8rg/132",
            "city": "",
            "country": "",
            "gender": 0,
            "nickName": "微信用户",
            "province": "",
            "code": code,
            "source": 2
        }
        resp = requests.post(f"{BASE}/api/user/wxLogin", json=payload,
                             headers={"User-Agent": UA, "Content-Type": "application/json"},
                             timeout=10, proxies={"http": None, "https": None})
        data = resp.json()
        if data.get("code") == 0:
            print("✅ 登录成功")
            return (data.get("data") or {}).get("authorization")
        print(f"❌ 登录失败: {data.get('message', '')}")
    except Exception as e:
        print(f"❌ 登录异常: {e}")
    return None


def daily_sign(token: str) -> dict:
    result = {"success": False, "msg": "", "span_days": 0}
    try:
        resp = requests.get(f"{BASE}/api/sign/daily/sign",
                            headers={
                                "Authorization": f"Mer{token}",
                                "User-Agent": UA,
                                "Referer": f"https://servicewechat.com/{APPID}/87/page-frame.html"
                            }, timeout=10, proxies={"http": None, "https": None})
        data = resp.json()
        if data.get("code") == 0:
            result["success"] = True
            result["msg"] = "签到成功"
            result["span_days"] = (data.get("data") or {}).get("spanSumDays", 0)
            print(f"📊 签到成功 | 连续 {result['span_days']} 天")
        else:
            result["msg"] = data.get("message", "")
            print(f"❌ 签到失败：{result['msg']}")
    except Exception as e:
        result["msg"] = f"签到异常: {e}"
        print(f"❌ 签到异常: {e}")
    return result


def get_points(token: str) -> dict:
    result = {"success": False, "score": 0}
    try:
        resp = requests.get(f"{BASE}/api/user/info",
                            headers={
                                "Authorization": f"Mer{token}",
                                "User-Agent": UA
                            }, timeout=10, proxies={"http": None, "https": None})
        data = resp.json()
        if data.get("code") == 0:
            result["success"] = True
            result["score"] = (data.get("data") or {}).get("score", 0)
            print(f"💰 总积分：{result['score']}")
    except Exception as e:
        print(f"❌ 查询积分异常: {e}")
    return result


def run_account(openid: str) -> bool:
    wxid = openid
    print(f"\n{'=' * 40}")
    print(f" 国乐酱酒 | {wxid} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 40}")

    time.sleep(1.5)

    token = code_login(openid)
    if not token:
        print("❌ 登录失败，跳过")
        return False

    sign_result = daily_sign(token)
    get_points(token)
    time.sleep(1)
    return True


try:
    import notify
except ImportError:
    notify = None

if __name__ == "__main__":
    results = []
    for i, openid in enumerate(WX_IDS):
        ok = run_account(openid)
        results.append(f"{openid}: {'✅' if ok else '❌'}")
        if i < len(WX_IDS) - 1:
            time.sleep(5)

    print("\n".join(results))
    if notify:
        notify.send(APP_NAME, "\n".join(results))