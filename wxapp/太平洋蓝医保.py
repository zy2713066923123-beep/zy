# -*- coding: utf-8 -*-
"""
name: 太平洋蓝医保
Date: 2026-09-02
export WX_SERVER / YYB_SERVER / WECHAT_SERVER  yyb_go 服务地址（留空则用默认 http://127.0.0.1:18273）
账号自动从 yyb_go 拉取全部存活账号；WX_ID（或 lpzl_tpylyb）仅作为可选白名单过滤，留空即用全部
cron: 0 8,19 * * *
version: 2.3
"""

import os
import sys
import time
import random
import json
import re
import requests
from datetime import datetime

# 将脚本所在目录加入搜索路径（确保能找到 yyb.py 等同目录模块，与加多宝Club.py 一致）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yyb  # 自动同步 yyb_go 存活账号

# ==================== 配置 ====================
APP_NAME = "太平洋蓝医保"
WX_APPID = "wx41b377f9104ee1c2"
BASE_URL = "https://lyb-api.cpic.com.cn"

# 账号白名单环境变量（留空则自动拉取 yyb_go 全部存活账号）
ENV_NAME = "lpzl_tpylyb"
# token 缓存名（存于 token_caches/ 目录，与 yyb.js 共用同一套缓存）
CACHE_NAME = "tpylyb"
# 本地文件仅用于保存答题错题本（登录态已迁移到 yyb 统一缓存）
CK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tpylyb_token_cache.json")
# 兼容旧版本：曾把缓存写在运行目录下
_CK_FILE_LEGACY = "tpylyb_token_cache.json"

# ==================== 协议配置 ====================
# 服务地址由 yyb 统一解析（WX_SERVER / YYB_SERVER / WECHAT_SERVER / YINGYONGBAO_SERVER 任一）
SERVER_URL = yyb.get_global_server_url()


def log(msg):
    print(msg, flush=True)


def load_cache():
    for path in (CK_FILE, _CK_FILE_LEGACY):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def save_cache(data):
    with open(CK_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ==================== 取码（统一走 yyb，自动路由协议/端点） ====================
def get_code(appid, identifier):
    code = yyb.get_single_code(appid, identifier)
    if not code:
        raise RuntimeError(f"获取微信 code 失败（服务地址: {SERVER_URL}）")
    return code


def get_phone_code(appid, identifier, login_type=None):
    # 小程序（WMPF）账号取手机号方式不同，yyb 内部会自动选择/回退合适通道
    code = yyb.get_single_phone_code(appid, identifier, login_type)
    if not code:
        raise RuntimeError(f"获取手机号 code 失败（服务地址: {SERVER_URL}）")
    return code


# ==================== 账号获取（自动同步 yyb_go 存活账号） ====================
def parse_accounts():
    """从 yyb_go 拉取存活账号。

    WX_ID / lpzl_tpylyb 仅作为可选白名单过滤（支持 & 或换行分隔，openid#备注），
    留空则自动使用全部存活账号。
    """
    try:
        accounts = yyb.load_accounts(ENV_NAME)
    except Exception as e:
        log(f"❌ 拉取 yyb_go 账号失败: {e}")
        return []

    result = []
    for idx, acc in enumerate(accounts or [], 1):
        identifier = str(acc.get("openid") or acc.get("id") or acc.get("wxid") or "").strip()
        if not identifier:
            continue
        remark = acc.get("remark") or acc.get("nickname") or acc.get("alias") or f"账号{idx}"
        result.append({
            "identifier": identifier,
            "remark": remark,
            "login_type": yyb.normalize_login_type(acc.get("login_type")),
            "protocol": yyb.login_type_label(acc.get("login_type")),
        })

    if result:
        log(f"✅ 从 yyb_go 同步到 {len(result)} 个存活账号（服务地址: {SERVER_URL}）")
    else:
        log(f"❌ 未获取到存活账号，请确认 yyb_go 已启动且有在线账号（服务地址: {SERVER_URL}）")
    return result


# ==================== 太平洋蓝医保客户端 ====================
class TpylybClient:
    def __init__(self, account):
        self.identifier = account["identifier"]
        self.remark = account["remark"]
        self.protocol = account["protocol"]
        self.login_type = account.get("login_type", "")
        self.openid = ""
        self.unionid = ""
        self.token = ""
        self.session = requests.Session()
        self.headers = {
            "Host": "lyb-api.cpic.com.cn",
            "Connection": "keep-alive",
            "xweb_xhr": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254181d) XWEB/19841",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://servicewechat.com/wx41b377f9104ee1c2/144/page-frame.html",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        # 登录态缓存：优先 yyb 统一缓存（token_caches/），兼容旧版本地文件缓存
        cached = yyb.get_cached_token(CACHE_NAME, self.identifier, {"max_age_ms": 6 * 3600 * 1000})
        if not (cached and cached.get("token")):
            cached = self._legacy_cache()
        if cached:
            self.openid = cached.get("openid", "")
            self.unionid = cached.get("unionid", "")
            self.token = cached.get("token", "")
        self.is_expired = True
        self.points = 0
        self.tasks = []

    def _update_headers(self):
        if self.openid:
            self.headers["lyb-m-openid"] = self.openid
        if self.unionid:
            self.headers["lyb-m-unionid"] = self.unionid
        if self.token:
            self.headers["lyb-m-token"] = self.token
        else:
            self.headers.pop("lyb-m-token", None)

    def _legacy_cache(self):
        """兼容旧版本写在本地文件里的登录态（key 形如 yyb:openid / niuzi:openid）"""
        cache = load_cache()
        for key in (f"yyb:{self.identifier}", f"niuzi:{self.identifier}", self.identifier):
            item = cache.get(key)
            if isinstance(item, dict) and item.get("token"):
                return item
        return None

    def _save_cache(self):
        yyb.save_cached_token(CACHE_NAME, self.identifier, {
            "openid": self.openid,
            "unionid": self.unionid,
            "token": self.token,
        })

    def _clear_cache(self):
        yyb.remove_cached_token(CACHE_NAME, self.identifier)

    def _request(self, method, path, data=None):
        url = BASE_URL + path
        self._update_headers()
        resp = self.session.request(method, url, headers=self.headers, json=data, timeout=15)
        token_from_header = resp.headers.get("lyb-m-token")
        result = resp.json() if resp.text else {}
        return result, token_from_header

    def login(self):
        try:
            wx_code = get_code(WX_APPID, self.identifier)
            log(f"[{self.remark}] 获取微信 code 成功: {wx_code[:8]}...")
        except Exception as e:
            raise RuntimeError(f"获取微信 code 失败: {e}")

        resp1, _ = self._request("POST", "/lyb-api/login/wx-session", {"code": wx_code})
        if resp1.get("code") != 0:
            raise RuntimeError(f"/wx-session 失败: {resp1}")
        data1 = resp1.get("data", {})
        self.openid = data1.get("openid")
        self.unionid = data1.get("unionid")
        if not self.openid:
            raise RuntimeError(f"/wx-session 未返回 openid")

        try:
            phone_code = get_phone_code(WX_APPID, self.identifier, self.login_type)
            log(f"[{self.remark}] 获取手机号 code 成功: {phone_code[:8]}...")
        except Exception as e:
            raise RuntimeError(f"获取手机号 code 失败: {e}")

        resp2, token_header = self._request("POST", "/lyb-api/login/wx-phone", {"type": 1, "code": phone_code})
        if resp2.get("code") != 0:
            raise RuntimeError(f"/wx-phone 失败: {resp2}")

        self.token = token_header
        if not self.token:
            self.token = resp2.get("lyb-m-token")
            if not self.token:
                self.token = resp2.get("data", {}).get("token")
        if not self.token:
            raise RuntimeError("/wx-phone 未返回 token")

        self._request("POST", "/lyb-api/login/agreementConfirmReport", {"confirmType": "login"})
        self._save_cache()
        log(f"[{self.remark}] 登录成功，token: {self.token[:8]}...")
        self.is_expired = False

    def ensure_login(self):
        if self.token and self.openid:
            try:
                self.get_task()
                log(f"[{self.remark}] 命中 token 缓存，跳过取码登录")
                return
            except Exception:
                log(f"[{self.remark}] token 失效，清除缓存并重新登录")
                self._clear_cache()
                self.token = ""
                self.openid = ""
                self.unionid = ""
        self.login()
        self.get_task()

    def get_task(self):
        resp, _ = self._request("POST", "/lyb-api/healthScore/upgrade/homeInit-V1", {"channel": "", "taskCode": ""})
        if resp.get("code") != 0:
            raise RuntimeError(f"获取任务失败: {resp}")
        self.is_expired = False
        self.points = resp.get("data", {}).get("availableScore", 0)
        self.tasks = resp.get("data", {}).get("healthTask", {}).get("taskList", [])
        return resp

    def get_question(self):
        resp, _ = self._request("POST", "/lyb-api/healthScore/upgrade/jkwd/getQuestion-V1", {"taskCode": "JKWD"})
        if resp.get("code") == 0:
            return resp.get("data", {}).get("questionId")
        return None

    def check_answer(self, question_id):
        cache = load_cache()
        wrong = cache.get("wrong_questions", {})
        if question_id in wrong:
            return wrong[question_id].get("answer", "A")
        return "A"

    def save_wrong_question(self, question_id, question_text, answer):
        cache = load_cache()
        if "wrong_questions" not in cache:
            cache["wrong_questions"] = {}
        cache["wrong_questions"][question_id] = {"question": question_text, "answer": answer}
        save_cache(cache)

    def share_receive(self, answer_id):
        resp, _ = self._request("POST", "/lyb-api/healthScore/upgrade/jkwd/revive-V1", {"answerId": str(answer_id)})
        if resp.get("code") == 0:
            return resp.get("data", {}).get("reviveResult")
        return None

    def answer_question(self, question_id, answer):
        resp, _ = self._request("POST", "/lyb-api/healthScore/upgrade/jkwd/getQuestionAnswer-V1",
                                {"questionId": question_id, "selectValue": answer})
        if resp.get("code") == 0:
            data = resp.get("data", {})
            if data.get("historyAnswerResult") == "Y":
                self.save_wrong_question(data.get("questionId"), data.get("questionText"), data.get("historySelect"))
                log(f"[{self.remark}] 答题成功 ✅")
                return True
            else:
                log(f"[{self.remark}] 答题错误 ❌")
                self.save_wrong_question(data.get("questionId"), data.get("questionText"), data.get("answerResultDesc"))
                if data.get("showReviveButton"):
                    time.sleep(1)
                    revive = self.share_receive(data.get("answerId"))
                    if revive == "Y":
                        time.sleep(1)
                        self.jkwd()
                return False
        else:
            log(f"[{self.remark}] 答题请求失败: {resp}")
            return False

    def jkwd(self):
        qid = self.get_question()
        if qid:
            time.sleep(1)
            ans = self.check_answer(qid)
            self.answer_question(qid, ans)

    def sign(self):
        resp, _ = self._request("POST", "/lyb-api/healthScore/upgrade/zqdk/dk-V1", {"taskCode": "ZQDK"})
        if resp.get("code") == 0:
            reward = resp.get("data", {}).get("taskReward", 0)
            log(f"[{self.remark}] 打卡成功，获得 {reward} 积分")
        else:
            log(f"[{self.remark}] 打卡失败: {resp.get('msg')}")

    def do_tasks(self):
        for task in self.tasks:
            if task.get("taskCode") == "ZQDK":
                if task.get("taskStatus") == 1:
                    log(f"[{self.remark}] {task.get('taskName')}：已完成")
                else:
                    log(f"[{self.remark}] 开始 {task.get('taskName')}...")
                    self.sign()
            elif task.get("taskCode") == "JKWD":
                if task.get("taskStatus") == 1:
                    log(f"[{self.remark}] {task.get('taskName')}：已完成")
                else:
                    log(f"[{self.remark}] 开始 {task.get('taskName')}...")
                    self.jkwd()

    def run(self):
        self.ensure_login()
        log(f"[{self.remark}] 执行前积分：{self.points}")
        self.do_tasks()
        self.get_task()
        log(f"[{self.remark}] 执行后积分：{self.points}")


def send_notify(title, content):
    try:
        from notify import send
        send(title, content)
    except:
        pass


def main():
    accounts = parse_accounts()
    if not accounts:
        log(f"未找到账号：请确认 yyb_go 已启动且有存活账号（服务地址: {SERVER_URL}），或设置 WX_ID 白名单")
        return

    log(f"{' ' * 10}꧁༺ {APP_NAME} ༻꧂\n")
    for i, acc in enumerate(accounts, 1):
        log(f"\n----------- 🎊 第 {i} 个账号 🎊 -----------")
        try:
            client = TpylybClient(acc)
            client.run()
        except Exception as e:
            log(f"[{acc['remark']}] 执行异常: {e}")

    log("\n----------- 🎊 执 行  结 束 🎊 -----------\n")


if __name__ == "__main__":
    main()