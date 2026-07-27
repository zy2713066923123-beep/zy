#!/usr/bin/env python3
# name: 伊利qq星
# cron: 3 9,19 * * *
# -*- coding: utf-8 -*-

import json
import re
import os
import time
import requests
from xml.etree import ElementTree as ET
from datetime import datetime

# ========== 从 YYB_SERVER 读取服务地址 ==========
APPID = "wx650bdff052117fa4ff4af6fa319fd858ff"  # placeholder, will be overridden
APPID = "wx650bdff059f63f5b"
SECRET = "d1e4b452117fa4ff4af6fa319fd858ff"
APP_NAME = "伊利QQ星"

# ============ 统一取码（WX_ID + getCode，支持牛子/YYB 双协议自动路由）============
from getCode import get_single_code

WX_IDS = [s.strip() for s in os.getenv("WX_ID", "").replace("&", "\n").splitlines() if s.strip()]
if not WX_IDS:
    print("❌ 未配置环境变量 WX_ID")
    print("格式：wxid#备注 或 openid，多账号换行或 & 分隔")
    exit(1)

WECHAT_SERVER = os.getenv("WECHAT_SERVER", "").strip()
YYB_SERVER = os.getenv("YYB_SERVER", "").strip()
if not WECHAT_SERVER and not YYB_SERVER:
    print("❌ 未配置取码服务地址，请设置 WECHAT_SERVER 或 YYB_SERVER")
    exit(1)
if WECHAT_SERVER:
    os.environ["WECHAT_SERVER"] = WECHAT_SERVER
if YYB_SERVER:
    os.environ["YYB_SERVER"] = YYB_SERVER

print(f"✅ 读取到 {len(WX_IDS)} 个微信账号，自动路由牛子/YYB 双协议")


def read_token_cache():
    try:
        if not os.path.exists(TOKEN_CACHE_FILE):
            return {}
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_token_cache(cache):
    try:
        os.makedirs(os.path.dirname(TOKEN_CACHE_FILE), exist_ok=True)
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class YiLiQQStar:
    """伊利QQ星 - 全自动每日任务"""

    # 每日任务
    TASKS = {
        11: "发起分享",
        31: "单次签到",
        40: "分享文章",
        47: "使用工具",
        53: "知识库每日打卡",
        56: "关注公众号",
        62: "活动签到",
        75: "活动连续签到",
    }

    def __init__(self, openid):
        self.openid = openid
        self.wxid = openid
        self.base_url = "https://mall.yili.com/MAMAIF/MCSWSIAPI.asmx/Call"
        self.device_code = APPID
        self.activity_id = "13D88C0D-A850-4278-A718-35CD397EF922"
        self.auth_key = None
        self.user_id = None
        self.points_before = 0

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows',
            'Content-Type': 'application/x-www-form-urlencoded',
            'xweb_xhr': '1',
            'Referer': f'https://servicewechat.com/{APPID}/162/page-frame.html',
        }
        self._load_token()

    def _load_token(self):
        cache = read_token_cache()
        if self.wxid in cache:
            self.auth_key = cache[self.wxid].get("auth_key")

    def _save_token(self):
        cache = read_token_cache()
        cache[self.wxid] = {"auth_key": self.auth_key, "updatedAt": datetime.now().isoformat()}
        write_token_cache(cache)

    def _parse(self, resp):
        text = resp.text.strip()
        if not text:
            return {}
        if text.startswith('<?xml') or text.startswith('<string'):
            try:
                root = ET.fromstring(text)
                if root.text:
                    return json.loads(root.text)
            except Exception:
                m = re.search(r'<string[^>]*>(.*?)</string>', text, re.DOTALL)
                if m:
                    try:
                        return json.loads(m.group(1))
                    except Exception:
                        pass
        return {}

    def call(self, method, params, retry=2):
        if isinstance(params, dict):
            p = json.dumps(params)
        elif isinstance(params, str) and params:
            p = params
        else:
            p = ""

        for i in range(retry):
            try:
                r = requests.post(
                    self.base_url, headers=self.headers,
                    data={'RequestPack': json.dumps({
                        "DeviceCode": self.device_code,
                        "AuthKey": self.auth_key or "0" * 36,
                        "Method": method, "Params": p
                    })}, timeout=15,
                    proxies={"http": None, "https": None}
                )
                result = self._parse(r)
                if 'Result' in result and isinstance(result['Result'], str):
                    try:
                        result['Result'] = json.loads(result['Result'])
                    except Exception:
                        pass
                return result
            except Exception:
                if i < retry - 1:
                    time.sleep(3)
                else:
                    return {"Return": -999}

    def login(self):
        code = get_single_code(APPID, self.openid)
        if not code:
            print("❌ 获取微信code失败")
            return False
        r1 = self.call("WechatService.GetWxOpenID", json.dumps({
            "AppID": APPID, "Secret": SECRET,
            "Js_Code": code, "Grant_Type": "authorization_code"
        }))
        if r1.get('Return', -1) < 0:
            print("❌ 获取OpenID失败")
            return False
        result = r1.get('Result', {})
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                pass
        self.open_id = result.get('openid', '')
        if not self.open_id:
            print("❌ OpenID为空")
            return False
        r2 = self.call("MemberService.LoginByWechatOpenId", json.dumps({
            "Platform": APPID, "OpenId": self.open_id,
            "UnionId": result.get('unionid', '')
        }))
        if r2.get('Return', -1) < 0:
            print("❌ 登录失败")
            return False
        self.auth_key = (r2.get('Result', {}) or {}).get('AuthKey', '')
        if self.auth_key:
            self._save_token()
        return bool(self.auth_key)

    def get_info(self):
        r = self.call("MemberService.GetMyMemberInfo", "")
        if r.get('Return') == 0:
            info = r['Result']
            self.user_id = info.get('ID')
            self.points_before = float(info.get('PointsBalance', 0))
            return info
        return None

    def get_points(self):
        r = self.call("PointsService.GetPointsBalance", "")
        return r.get('Result', {}) if r.get('Return') == 0 else None

    def do_join(self, jt):
        if not self.user_id:
            return None
        ji = json.dumps({"Activity": self.activity_id, "JoinType": jt, "UserId": self.user_id})
        return self.call("MemberService.CampaignJoin", json.dumps({"JoinInfo": ji}))

    def run(self):
        print(f"\n{'=' * 40}")
        print(f" 伊利QQ星 | {self.wxid} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 40}")

        info = self.get_info() if self.auth_key else None
        if not info:
            print("[登录] ...")
            if not self.login():
                print("❌ 登录失败")
                return False
            info = self.get_info()
            if not info:
                print("❌ 获取信息失败")
                return False

        print(f"👤 {info.get('RealName')} | {info.get('MemberLevelName')} | {self.points_before}积分\n")

        for jt, name in self.TASKS.items():
            r = self.do_join(jt)
            ret = r.get('Return', -999)

            if ret == 0:
                print(f"✅ [{jt}] {name} 完成!")
            elif ret in [-31, -33]:
                print(f"⏭️  [{jt}] {name} 已完成")
            elif ret == -10:
                print(f"🔄 [{jt}] 刷新AuthKey...")
                if self.login():
                    r = self.do_join(jt)
                    print(f"  {'✅ 完成' if r.get('Return') == 0 else '❌ 失败'}")
            elif ret == -999:
                print(f"⚠️  [{jt}] {name} 网络错误")
            else:
                print(f"❌ [{jt}] {name}: {ret}")

            time.sleep(0.8)

        pts = self.get_points()
        if pts:
            a = float(pts.get('Points', self.points_before))
            d = a - self.points_before
            if d > 0:
                print(f"\n🎉 积分: {self.points_before} → {a} (+{d})")
            else:
                print(f"\n📊 积分: {self.points_before}")
        print(f"{'=' * 40}\n")
        return True


try:
    import notify
except ImportError:
    notify = None


if __name__ == "__main__":
    results = []
    for i, openid in enumerate(WX_IDS):
        ok = YiLiQQStar(openid).run()
        results.append(f"{openid}: {'✅' if ok else '❌'}")
        if i < len(WX_IDS) - 1:
            time.sleep(5)

    print("\n".join(results))
    if notify:
        notify.send(APP_NAME, "\n".join(results))
