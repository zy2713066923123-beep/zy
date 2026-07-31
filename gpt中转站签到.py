# 当前脚本来自于 http://script.345yun.cn 脚本库下载！
# 当前脚本来自于 http://2.345yun.cn 脚本库下载！
# 当前脚本来自于 http://2.345yun.cc 脚本库下载！
# 脚本库官方QQ群1群: 429274456
# 脚本库官方QQ群2群: 1077801222
# 脚本库官方QQ群3群: 433030897
# 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
# 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
# 您在使用脚本库下载的脚本时自行检查判断风险。
# 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。

"""
name: GPT专供站 每日签到
cron: 0 1 * * *
new Env('GPT专供站每日签到');
"""

import os
import re
import sys
import json
import time
import requests

# ============ 青龙环境变量 ============
# GPT456_ACCOUNTS: 多账号 JSON 字符串,格式:
# username----password 或 username&password
# ========================================================

DEFAULT_BASE_URL = "https://gpt.api456.me"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Content-Type": "application/json",
    "Origin": "https://gpt.api456.me",
    "Referer": "https://gpt.api456.me/dashboarda/",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-ch-ua": "\"Not A(Brand\";v=\"8\", \"Chromium\";v=\"132\", \"Google Chrome\";v=\"132\"",
    "sec-ch-ua-mobile": "?0",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def get_accounts():
    """从青龙环境变量读取账号列表"""
    raw = os.getenv("GPT456_ACCOUNTS", "").strip()
    accounts = []
    if not raw:
        return accounts

    # 尝试 JSON 解析(推荐)
    if raw.startswith("[") or raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                accounts.append({
                    "username": str(item.get("username", "")).strip(),
                    "password": str(item.get("password", "")).strip(),
                    "base_url": str(item.get("base_url", DEFAULT_BASE_URL)).strip().rstrip("/"),
                    "name": str(item.get("name", "")).strip(),
                })
            return accounts
        except Exception as e:
            print(f"[账号解析] JSON 格式错误: {e}")

    # 兼容分隔符: ---- & :: 
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        for sep in ["----", "::", "&"]:
            if sep in line:
                u, p = line.split(sep, 1)
                accounts.append({
                    "username": u.strip(),
                    "password": p.strip(),
                    "base_url": DEFAULT_BASE_URL,
                    "name": "",
                })
                break
    return accounts


class GPT456Client:
    def __init__(self, username, password, base_url=DEFAULT_BASE_URL, name=""):
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.name = name or username
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.user_id = None

    def log(self, msg):
        print(f"[{self.name}] {msg}")

    def _api(self, path, method="GET", **kwargs):
        url = self.base_url + path
        return self.session.request(method, url, timeout=30, **kwargs)

    def login(self):
        """登录获取 session"""
        try:
            r = self._api("/api/user/login", method="POST",
                          json={"username": self.username, "password": self.password})
            data = r.json()
            if not data.get("success"):
                self.log(f"❌ 登录失败: {data.get('message', '未知错误')}")
                return False
            user = data.get("data", {})
            self.user_id = str(user.get("id", ""))
            self.log(f"✅ 登录成功 (uid={self.user_id}, group={user.get('group')})")
            # 后续请求需要带 new-api-user 头
            self.session.headers["new-api-user"] = self.user_id
            return True
        except Exception as e:
            self.log(f"❌ 登录异常: {e}")
            return False

    def get_summary(self):
        """查询当前账户概览 & 今日签到状态"""
        try:
            r = self._api("/api/portal/summary", method="GET")
            data = r.json()
            if not data.get("success"):
                self.log(f"❌ 查询概览失败: {data.get('message')}")
                return None
            d = data.get("data", {})
            daily = d.get("daily_public_quota", {})
            quota = d.get("quota", {})
            user = d.get("user", {})
            return {
                "claimed": daily.get("claimed", False),
                "claimable_cp": daily.get("claimable_compute_points", 0),
                "daily_cp": daily.get("daily_compute_points", 0),
                "remaining_cp": daily.get("quota_remaining_compute_points", 0),
                "date": daily.get("date", ""),
                "balance_cp": quota.get("display", 0),
                "used_cp": quota.get("used_display", 0),
                "username": user.get("username", ""),
                "email": user.get("email", ""),
            }
        except Exception as e:
            self.log(f"❌ 查询概览异常: {e}")
            return None

    def claim(self):
        """签到领取每日公益额度"""
        try:
            r = self._api("/api/portal/daily-public-quota/claim", method="POST")
            data = r.json()
            if not data.get("success"):
                self.log(f"❌ 签到失败: {data.get('message', '未知错误')}")
                return None
            d = data.get("data", {})
            return {
                "claimed": d.get("claimed"),
                "daily_cp": d.get("daily_compute_points", 0),
                "remaining_cp": d.get("quota_remaining_compute_points", 0),
                "claimable_cp": d.get("claimable_compute_points", 0),
            }
        except Exception as e:
            self.log(f"❌ 签到异常: {e}")
            return None

    def logout(self):
        try:
            self._api("/api/user/logout", method="GET")
        except Exception:
            pass

    def run(self):
        self.log("========== 开始执行 ==========")
        if not self.login():
            return False

        info = self.get_summary()
        if info:
            self.log(f"👤 账户: {info['email'] or info['username']}")
            self.log(f"💰 余额: {info['balance_cp']} 算力点 (已用 {info['used_cp']})")
            self.log(f"📅 日期: {info['date']} | 今日额度: {info['daily_cp']} 算力点")
            self.log(f"📌 今日是否已签到: {'是' if info['claimed'] else '否'}")

        if info and info["claimed"]:
            self.log("今日已签到,跳过领取(剩余 %s 算力点)" % info["remaining_cp"])
            self.logout()
            return True

        # 防止风控,稍微延迟
        time.sleep(2)
        result = self.claim()
        if result:
            self.log(f"🎉 签到成功!本次领取: {result['daily_cp']} 算力点")
            self.log(f"📦 当前剩余额度: {result['remaining_cp']} 算力点")
        else:
            self.log("⚠️ 签到未成功,可能今日已领取或接口变动")

        # 再次查询最新余额
        time.sleep(1)
        new_info = self.get_summary()
        if new_info:
            self.log(f"📈 最新余额: {new_info['balance_cp']} 算力点")

        self.logout()
        self.log("========== 执行完毕 ==========\n")
        return True


def main():
    accounts = get_accounts()
    if not accounts:
        print("⚠️ 未读取到账号信息!")
        print("请在青龙环境变量中添加 GPT456_ACCOUNTS")
        print("格式(JSON,推荐):")
        print('[{"username":"123456","password":"123456"},...]')
        print("或单账号: 123456----123456")
        sys.exit(1)

    print(f"🔍 共读取到 {len(accounts)} 个账号\n")
    success, fail = 0, 0
    for i, acc in enumerate(accounts, 1):
        print(f"\n========== 账号 {i}/{len(accounts)} ==========")
        if not acc["username"] or not acc["password"]:
            print("⚠️ 账号或密码为空,跳过")
            fail += 1
            continue
        client = GPT456Client(
            username=acc["username"],
            password=acc["password"],
            base_url=acc["base_url"],
            name=acc["name"],
        )
        try:
            ok = client.run()
            if ok:
                success += 1
            else:
                fail += 1
        except Exception as e:
            print(f"❌ 账号 {acc['username']} 执行异常: {e}")
            fail += 1
        # 多账号间隔,防止风控
        if i < len(accounts):
            time.sleep(5)

    print(f"\n========== 全部完成 ==========")
    print(f"✅ 成功: {success}  ❌ 失败: {fail}")

    if fail > 0 and success == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

# 当前脚本来自于 http://script.345yun.cn 脚本库下载！
# 当前脚本来自于 http://2.345yun.cn 脚本库下载！
# 当前脚本来自于 http://2.345yun.cc 脚本库下载！
# 脚本库官方QQ群1群: 429274456
# 脚本库官方QQ群2群: 1077801222
# 脚本库官方QQ群3群: 433030897
# 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
# 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
# 您在使用脚本库下载的脚本时自行检查判断风险。
# 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。