#!/usr/bin/env python3
import yyb  # 自动同步 yyb_go 存活账号
# name: 小福家
# cron: 30 7,15 * * *
# -*- coding: utf-8 -*-

"""
小福家小程序登录 - 纯 YYB Go 版
code + 手机号加密数据均从 YYB Go 获取

环境变量：
  YYB_SERVER    必填：YYB Go 服务地址@微信账号标识，多行换行

依赖：
  pip install requests
"""

import os
import sys
import json
import time
import hashlib
import requests

APPID = "wxe6ba46e6100e68e9"
APPKEY = "b98b1abf926b44e3998e5573b42f101f"
APPSECRET = "e5e3333fbb7448c7813281c68bad7f57"
API_HOST = "api.xiaofujia.com"
API_BASE = f"https://{API_HOST}"
PLATFORM = 12

# ============ 统一取码（WX_ID + getCode，支持牛子/YYB 双协议自动路由）============

WX_IDS = [s.strip() for s in os.getenv("WX_ID", "").replace("&", "\n").splitlines() if s.strip()]
if not WX_IDS:
    try:
        accs = load_accounts()
        if accs:
            WX_IDS = [acc.get("openid") or str(acc.get("id")) for acc in accs]
    except Exception:
        pass

WECHAT_SERVER = (os.getenv("WX_SERVER") or os.getenv("WECHAT_SERVER") or "http://127.0.0.1:8000").strip()
YYB_SERVER = (os.getenv("WX_SERVER") or os.getenv("YYB_SERVER") or "http://127.0.0.1:8000").strip()
os.environ["WECHAT_SERVER"] = WECHAT_SERVER
os.environ["YYB_SERVER"] = YYB_SERVER

if WX_IDS:
    print(f"✅ 读取到 {len(WX_IDS)} 个微信账号，自动路由牛子/YYB 双协议")


def xiaofujia_login(code: str, mobile_code: str) -> dict | None:
    print("→ 小福家登录...")
    login_url = f"{API_BASE}/familychat/user/login"

    # yyb 应用宝手机号走新流程（phonenumber.getPhoneNumber）：返回手机号 code，后端用它换手机号。
    # 旧流程的 encryptedData/iv 在 yyb 下不可用（yyb 服务端已解密，响应里只有 code + 明文 mobile）。
    # mobile_code 为 get_single_phone_number 返回的手机号授权 code。
    auth_token = json.dumps({
        "code": code,
        "mobile_code": mobile_code,
    })
    
    body = {
        "auth_type": 2,
        "auth_token": auth_token,
        "platform": PLATFORM,
        "did": "nfPQXpkJaxRQ8BQw4B66KWtWBFXC22SH",
        "metadata": {"launch_mnp_scene": 0}
    }
    
    t = int(time.time())
    params = {"time": t, "appkey": APPKEY}
    sign_str = "".join(f"{k}{params[k]}" for k in sorted(params)) + APPSECRET
    sign = hashlib.md5(sign_str.encode()).hexdigest()
    full_url = f"{login_url}?time={t}&appkey={APPKEY}&sign={sign}"
    
    headers = {
        "content-type": "application/json;charset=UTF-8",
        "Host": API_HOST,
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49(0x18003121) NetType/WIFI Language/zh_CN",
        "Referer": "https://servicewechat.com/wxe6ba46e6100e68e9/116/page-frame.html"
    }
    
    try:
        resp = requests.post(full_url, json=body, headers=headers, timeout=30)
        data = resp.json()
        if data.get("code") != 0:
            print(f"✗ 登录失败: {data.get('msg', '未知错误')}")
            return None
        token = data.get("data", {}).get("access_token", "")
        print(f"✓ 登录成功！access_token: {token[:15]}...")
        return {"access_token": token}
    except Exception as e:
        print(f"✗ 登录异常: {e}")
        return None


def main():
    print("┌─────────────────────────────┐")
    print("│ 小福家小程序登录 │")
    print("└─────────────────────────────┘")
    
    for i, openid in enumerate(WX_IDS):
        print(f"\n========== 账号[{i+1}] {openid} ==========")
        
        code = get_single_code(APPID, openid)
        if not code:
            print(f"✗ 获取code失败，跳过")
            continue
        
        mobile = get_single_phone_number(APPID, openid)
        if not mobile:
            print(f"✗ 获取手机号失败，跳过")
            continue
        
        result = xiaofujia_login(code, mobile)
        if result:
            print(f"✓ 账号[{i+1}] ACCESS_TOKEN={result['access_token']}")
        else:
            print(f"✗ 账号[{i+1}] 登录失败")
        
        if i < len(WX_IDS) - 1:
            time.sleep(3)
    
    print("\n┌─────────────────────────────┐")
    print("│ 所有账号处理完成 │")
    print("└─────────────────────────────┘")


if __name__ == "__main__":
    main()