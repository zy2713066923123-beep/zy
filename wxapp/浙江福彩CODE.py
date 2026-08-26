import yyb  # 自动同步 yyb_go 存活账号


"""
name: 浙江福彩签到 (微信协议版)
入口: 微信公众号
功能: 签到
变量: 填写WX_ID中的openid/账号标识，多账号换行分割
需要配置WECHAT_SERVER、WX_ID，用于获取wx.login code
账号变量名:zjfc
cron: 34 8,14 * * *
"""
# name: 浙江福彩签到

import requests
import json
import os
import sys
import time
import random

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from notify import send as notify_send
except ImportError:
    print("未找到 notify.py，将仅在控制台输出日志。")
    def notify_send(title, content):
        print(f"--- 通知 ---\n{title}\n{content}\n-------------")

MINI_APP_ID = "wx1ad1780dde6b2260"
BASE_URL = "https://flcp.hy960.com"
HOST = "flcp.hy960.com"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "NetType/WIFI MicroMessenger/7.0.20.1781(0x6700143B) "
    "WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541a13) "
    "XWEB/19977 Flue"
)

session = requests.Session()
message_list = []


def log(msg):
    """统一日志输出"""
    print(msg)
    message_list.append(msg)


def get_wx_code(account_id):
    """获取微信登录 code"""
    try:
        return yyb.get_single_code(MINI_APP_ID, account_id)
    except Exception as e:
        raise RuntimeError(f"获取code失败: {e}")


def login(session, code):
    """用 OAuth code 换取 flcpSession"""
    url = f"{BASE_URL}/oauth/mp"
    params = {"code": code, "state": ""}
    try:
        response = session.get(
            url,
            params=params,
            allow_redirects=False,
            timeout=15,
        )
        if response.status_code in (301, 302, 303, 307, 308):
            cookies = response.headers.get("Set-Cookie", "")
            import re
            match = re.search(r"flcpSession=([^;]+)", cookies)
            if match:
                return match.group(1)
            else:
                log(f"⚠️ 302响应中未找到 flcpSession Cookie")
                return None
        elif response.status_code == 200:
            data = response.json() if response.text else {}
            token = data.get("data", {}).get("token") or data.get("data", {}).get("session")
            if token:
                return token
            return None
        else:
            log(f"❌ 登录返回状态码 {response.status_code}")
            return None
    except requests.RequestException as e:
        log(f"❌ 登录网络错误: {e}")
        return None


def get_user_info(session, tag):
    """获取用户信息"""
    try:
        response = session.get(f"{BASE_URL}/api/user/info", timeout=10)
        data = response.json()
        if data.get("code") == 200:
            user_data = data.get("data", {})
            nickname = user_data.get("nickname") or user_data.get("nickName") or ""
            score = user_data.get("score", "未知")
            display = f"{nickname} " if nickname else ""
            log(f"{tag}👤 {display}📊 当前积分: {score}")
            return True
        else:
            log(f"{tag}❌ Session失效")
            return False
    except Exception as e:
        log(f"{tag}❌ 获取用户信息失败: {e}")
        return False


def check_signed(session):
    """检查今日是否已签到"""
    try:
        response = session.get(f"{BASE_URL}/api/user/member-data", timeout=10)
        data = response.json()
        if data.get("code") == 200 and data.get("data", {}).get("isChecked"):
            return True
    except Exception:
        pass
    return False


def do_sign(session):
    """执行签到"""
    try:
        response = session.post(f"{BASE_URL}/api/user/checkin", timeout=10)
        data = response.json()
        if data.get("code") == 200:
            add_score = data.get("data", {}).get("score") or data.get("data", {}).get("addScore") or ""
            score_msg = f" 获得积分: {add_score}" if add_score else ""
            log(f"✅ 签到成功！{score_msg}")
            return True
        elif data.get("code") == 400 and "已签到" in str(data.get("msg", "")):
            log("✅ 今日已签到")
            return True
        else:
            log(f"⚠️ {data.get('msg', json.dumps(data))}")
            return False
    except Exception as e:
        log(f"❌ 签到失败: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("🚀 浙江福彩签到脚本")
    print("=" * 50)

    # 从环境变量读取账号
    raw_env = os.getenv("WX_ID") or os.getenv("zjfc", "")
    if not raw_env:
        # 未配置 WX_ID 时，自动从 yyb_go 拉取存活账号
        raw_env = "\n".join(resolve_accounts())
    accounts = [item.split('#')[0].strip() for item in raw_env.replace("&", "\n").splitlines() if item.strip()]

    if not accounts:
        log("❌ 未检测到账号信息，退出脚本。")
    else:
        log(f"✅ 共解析到 {len(accounts)} 个账号\n")

        for i, account_id in enumerate(accounts, 1):
            tag = f"[账号{i}]"
            log(f"────── {tag} 开始 ──────")

            # 创建 session
            s = requests.Session()
            s.headers["User-Agent"] = DEFAULT_UA
            s.headers["Origin"] = BASE_URL
            s.headers["Referer"] = f"{BASE_URL}/user/"

            # 获取微信授权 code
            log(f"{tag}🔑 获取微信授权code...")
            try:
                code = get_wx_code(account_id)
            except Exception as e:
                log(f"{tag}❌ 获取授权code失败: {e}")
                continue

            if not code:
                log(f"{tag}❌ 获取授权code失败，请检查协议服务器")
                continue

            # 用 code 登录换取 session
            time.sleep(random.uniform(1, 2))
            session_token = login(s, code)
            if not session_token:
                log(f"{tag}❌ 登录失败")
                continue

            # 设置 cookie
            s.cookies.set("flcpSession", session_token, domain=HOST)

            # 获取用户信息
            time.sleep(random.uniform(1, 2))
            if not get_user_info(s, tag):
                continue

            # 检查并执行签到
            time.sleep(random.uniform(1, 2))
            if check_signed(s):
                log(f"{tag}✅ 今日已签到")
            else:
                time.sleep(random.uniform(1, 2))
                do_sign(s)

            log(f"────── {tag} 结束 ──────\n")
            time.sleep(random.uniform(1, 3))

    # 推送通知
    notify_send("浙江福彩签到结果", "\n".join(message_list))
    print("\n🎉 所有任务执行完毕")