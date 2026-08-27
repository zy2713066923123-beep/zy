#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import yyb  # 自动同步 yyb_go 存活账号
# name: 比亚迪海洋签到
# cron: 36 12,00 * * *
"""
比亚迪海洋小程序签到脚本（code 版）
By 南归
功能：
  1. WeChatLoader 获取微信 code
  2. 使用 code 换取 session_id
  3. 每日签到
  4. AES-128-CBC 加解密

环境变量：
  WeChatLoader_api   WeChatLoader 服务地址
  WXID               微信ID，多账号用 & 分隔
"""

import base64
import hashlib
import json
import os
import sys
import time
import traceback
import uuid as uuid_mod
from datetime import datetime
from typing import Any, Dict, List, Tuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import notify

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

APP_NAME = "比亚迪海洋小程序签到"
APPID = "wxf62054ec313d6f53"

# ============ 统一取码（WX_ID + 统一 getCode 模块，支持牛子/YYB 双协议自动路由）============
# 环境变量：
#   WX_ID       微信账号标识（wxid），多账号换行或 & 分隔
#   WECHAT_SERVER 牛子/WeChatLoader 取码服务地址（如 http://127.0.0.1:8088）
#   YYB_SERVER   YYB 应用宝取码服务地址（YYB 账号时使用，可选）
import asyncio

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
    print(f"✅ 成功读取 {len(WX_IDS)} 个微信账号，自动路由牛子/YYB 双协议")
print("-" * 60 + "\n")

AES_KEY = os.getenv("BYD_AES_KEY", "3993014457161851").encode()
AES_IV = os.getenv("BYD_AES_IV", "PDVcDRWMrBlLHTqh").encode()
APPKEY = os.getenv("BYD_APPKEY", "hyMinaApi")
APPSECRET = os.getenv("BYD_APPSECRET", "Kfl%BOk6C5PwARw8")

BASE_URL = "https://mina.bydoceanauto.com"
DECRYPT_CODE_URL = f"{BASE_URL}/?service=mina.decryptCode"
SIGN_URL = f"{BASE_URL}/?s=ForCommonUcSrv.forward&serviceDir=activity/sign/signIn"
INTEGRAL_URL = f"{BASE_URL}/App/Forward2Rights/integral?serviceDir=/Integral/User/user"

REQUEST_TIMEOUT = 30

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541938) XWEB/19823"
)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def mask(value: Any) -> str:
    value = str(value or "")
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-6:]}"


def gen_nonce(length: int = 16) -> str:
    import random
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choice(chars) for _ in range(length))


def gen_client_trace_id() -> str:
    return f"mina-{uuid_mod.uuid4()}"


def gen_checksum(nonce: str, curtime: str) -> str:
    raw = f"{APPSECRET}{nonce}{curtime}"
    return hashlib.sha256(raw.encode()).hexdigest()


def aes_encrypt(plaintext: str) -> str:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    padded = pad(plaintext.encode("utf-8"), AES.block_size)
    encrypted = cipher.encrypt(padded)
    return base64.b64encode(encrypted).decode("utf-8")


def aes_decrypt(ciphertext: str) -> str:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    decoded = base64.b64decode(ciphertext)
    decrypted = unpad(cipher.decrypt(decoded), AES.block_size)
    return decrypted.decode("utf-8")


# 取微信 code 使用统一模块 getCode 的 get_single_code（按 WX_ID 自动路由牛子/YYB 双协议）


def common_headers() -> Dict[str, str]:
    nonce = gen_nonce()
    curtime = str(int(time.time()))
    return {
        "Content-Type": "application/json",
        "X-Clienttraceid": gen_client_trace_id(),
        "Nonce": nonce,
        "Curtime": curtime,
        "Checksum": gen_checksum(nonce, curtime),
        "Appkey": APPKEY,
        "User-Agent": USER_AGENT,
        "Xweb_xhr": "1",
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": f"https://servicewechat.com/{APPID}/115/page-frame.html",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def get_session_id(code: str) -> str:
    payload_plain = json.dumps({"code": code})
    encrypted_payload = aes_encrypt(payload_plain)

    resp = requests.post(
        DECRYPT_CODE_URL,
        headers=common_headers(),
        data=encrypted_payload,
        timeout=REQUEST_TIMEOUT,
    )

    resp_text = resp.text.strip()
    data = None
    try:
        decrypted = aes_decrypt(resp_text)
        data = json.loads(decrypted)
    except Exception:
        try:
            json_data = resp.json()
            if isinstance(json_data, dict):
                data = json_data
        except Exception:
            pass

    if not isinstance(data, dict):
        raise Exception(f"解密/解析响应失败，原始内容: {resp_text[:200]}")

    session_id = data.get("session_id") or (data.get("data") or {}).get("session_id")
    if not session_id:
        raise Exception(f"未获取到 session_id: {json.dumps(data, ensure_ascii=False)[:200]}")
    return session_id


def do_sign(session_id: str) -> Dict[str, Any]:
    payload_plain = json.dumps({
        "date": "",
        "belong_brand": "hy",
        "session_id": session_id,
        "app_version": "460",
        "app_client": "mina",
    })
    encrypted_payload = aes_encrypt(payload_plain)

    resp = requests.post(
        SIGN_URL,
        headers=common_headers(),
        data=encrypted_payload,
        timeout=REQUEST_TIMEOUT,
    )

    resp_text = resp.text.strip()
    data = None
    try:
        decrypted = aes_decrypt(resp_text)
        data = json.loads(decrypted)
    except Exception:
        try:
            json_data = resp.json()
            if isinstance(json_data, dict):
                data = json_data
        except Exception:
            pass

    if not isinstance(data, dict):
        raise Exception(f"解密/解析签到响应失败，原始内容: {resp_text[:200]}")
    return data



def get_user_integral(session_id: str) -> Dict[str, Any]:
    """查询积分信息"""
    payload_plain = json.dumps({
        "session_id": session_id,
        "app_version": "460",
        "app_client": "mina",
    })
    encrypted_payload = aes_encrypt(payload_plain)

    resp = requests.post(
        INTEGRAL_URL,
        headers=common_headers(),
        data=encrypted_payload,
        timeout=REQUEST_TIMEOUT,
    )

    resp_text = resp.text.strip()
    data = None
    try:
        decrypted = aes_decrypt(resp_text)
        data = json.loads(decrypted)
    except Exception:
        try:
            json_data = resp.json()
            if isinstance(json_data, dict):
                data = json_data
        except Exception:
            pass

    if not isinstance(data, dict):
        raise Exception(f"解密/解析积分响应失败，原始内容: {resp_text[:200]}")
    return data


def run_account(index: int, total: int, openid: str) -> Dict[str, Any]:
    result = {
        "wxid": openid,
        "success": False,
        "msg": "",
    }

    print()
    print(f"┌{'─' * 50}┐")
    print(f"│ 账号 {index} / {total}: {mask(openid):<37}│")
    print(f"└{'─' * 50}┘")

    try:
        code = get_single_code(APPID, openid)
    except Exception as e:
        code = None
        print(f"❌ [授权] 获取 code 异常: {e}")
    if not code:
        result["msg"] = "获取 code 失败"
        return result
    print(f"✅ [授权] code 获取成功")

    try:
        session_id = get_session_id(code)
        print(f"✅ [登录] session_id 获取成功: {mask(session_id)}")
    except Exception as exc:
        print(f"❌ [登录] session_id 获取失败: {exc}")
        result["msg"] = f"获取 session_id 失败: {exc}"
        return result

    try:
        sign_data = do_sign(session_id)
        ret = sign_data.get("ret")
        sign_detail = sign_data.get("data") or {}
        if ret == 200:
            duplicate = sign_detail.get("duplicate", False)
            days = sign_detail.get("durationDays", 0)
            integral = sign_detail.get("integral", 0)
            if duplicate:
                print(f"⚠️ [签到] 重复签到，今日已签到")
                print(f"   本次积分: +{integral} | 累计签到: {days}天")
                msg = f"重复签到 +{integral}积分 累计{days}天"
            else:
                print(f"✅ [签到] 签到成功")
                print(f"   本次积分: +{integral} | 累计签到: {days}天")
                msg = f"签到成功 +{integral}积分 累计{days}天"
            result["success"] = True
            result["msg"] = msg
            # 查询积分
            try:
                integral_data = get_user_integral(session_id)
                i_ret = integral_data.get("ret")
                if i_ret == 200:
                    inner = integral_data.get("data") or {}
                    avail = inner.get("available_integral_sum", 0)
                    freezing = inner.get("freezing_integral_sum", 0)
                    gained = inner.get("gain_integral_sum", 0)
                    expiring = inner.get("going_expired_integral_sum", 0)
                    print(f"💰 [积分] 可用: {avail} | 累计获得: {gained} | 冻结: {freezing} | 即将过期: {expiring}")
                    result["msg"] += f" | 积分{avail}"
                else:
                    print(f"⚠️ [积分] 查询失败: ret={i_ret}")
            except Exception as exc:
                print(f"⚠️ [积分] 查询异常: {exc}")
        else:
            msg = sign_data.get("msg") or json.dumps(sign_data, ensure_ascii=False)[:100]
            print(f"❌ [签到] 失败: {msg}")
            result["msg"] = msg
    except Exception as exc:
        print(f"❌ [签到] 签到失败: {exc}")
        result["msg"] = f"签到失败: {exc}"

    return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    lines = []
    for i, res in enumerate(results, 1):
        status = "✅" if res["success"] else "❌"
        lines.append(f"账号{i} {mask(res['wxid'])}: {status}{res['msg']}")
    return "\n".join(lines)


def main() -> None:
    print()
    print("╔" + "═" * 50 + "╗")
    print(f"║ 比亚迪海洋小程序签到（YYB Go版）                  ║")
    print(f"║ 启动时间: {now_text():<36}║")
    print(f"║ 账号数量: {len(WX_IDS):<36}║")
    print("╚" + "═" * 50 + "╝")

    results: List[Dict[str, Any]] = []
    for index, openid in enumerate(WX_IDS, 1):
        result = run_account(index, len(WX_IDS), openid)
        results.append(result)
        if index < len(WX_IDS):
            time.sleep(2)

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    print()
    print("╔" + "═" * 50 + "╗")
    print(f"║ 比亚迪海洋签到任务执行完成                       ║")
    print(f"║ 成功: {success_count:<40}║")
    print(f"║ 失败: {fail_count:<40}║")
    print(f"║ 结束时间: {now_text():<36}║")
    print("╚" + "═" * 50 + "╝")

    notify.send(APP_NAME, build_notify(results))


if __name__ == "__main__":
    main()