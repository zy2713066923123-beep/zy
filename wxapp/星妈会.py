
# cron: 24 11,16 * * *
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星妈会小程序自动任务（支持 wxid 自动续期 + Authorization 直连）

环境变量:
1. 微信协议服务地址:
   export WECHAT_SERVER="http://127.0.0.1:8011"
2. 账号变量（多账号按换行分隔，可混填）:
   export FEIHE_DATA="wxid_xxx#156
Authorization值1#133
Authorization值2&cuk值2#170
Authorization值3&&wxid_zzz#171"

说明:
- 请求域名: momclub.feihe.com/capis
- 每行支持格式（#后为备注，可选）:
  - wxid
  - Authorization
  - Authorization&cuk
  - Authorization&wxid
  - Authorization&cuk&wxid
- 若只有 wxid，则启动时自动登录获取 Authorization
- 若已有 Authorization，脚本直接使用；失效时若该行带 wxid 则会自动续期
- WECHAT_SERVER 仅在 wxid 自动登录/续期时需要配置

功能:
- 自动签到
- 自动完成浏览任务
- 自动完成小游戏任务
- 自动统计积分增长
"""

import requests
import json
import time
import random
import os
import sys
from datetime import datetime
from urllib.parse import urlencode

from getCode import get_single_code

# 消息通知开关 (True/False)
ENABLE_NOTIFY = False

# 消息收集列表
notify_content = []

try:
    from notify import send
except ImportError:
    def send(title, content):
        print(f"通知: {title}\n{content}")

class FeiheClient:
    """星妈会小程序 API 客户端"""
    
    def __init__(self, authorization, cuk, wxid="", remark="", index=1, wechat_server=""):
        """
        初始化客户端
        
        Args:
            authorization: Authorization token
            cuk: cuk 参数
            wxid: 微信ID(用于自动续期)
            remark: 账号备注(可选)
            index: 账号序号
            wechat_server: 微信协议服务地址
        """
        self.index = index
        self.base_url = "https://momclub.feihe.com/capis"
        self.appid = "wxc83b55d61c7fc51d"
        self.authorization = authorization
        self.cuk = cuk
        self.wxid = wxid.strip()
        self.remark = (remark or "").strip()
        self.wechat_server = (wechat_server or "").strip().rstrip("/")
        self.session = requests.Session()
        self.setup_headers()
        self.nick_name = None
        self.points = 0
        self._renewing = False
    
    def setup_headers(self):
        """设置请求头"""
        self.headers = {
            'Host': 'momclub.feihe.com',
            'Connection': 'keep-alive',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'content-type': 'application/json',
            'Accept-Encoding': 'gzip,compress,br,deflate',
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.68(0x1800442b) NetType/WIFI Language/zh_CN',
            'Referer': 'https://servicewechat.com/wxc83b55d61c7fc51d/66/page-frame.html'
        }
        if self.authorization:
            self.headers['Authorization'] = self.authorization
        # 空值不传，避免发送 cuk: ""
        if self.cuk:
            self.headers['cuk'] = self.cuk

    def _set_auth_and_cuk(self, authorization=None, cuk=None):
        """更新运行中的登录态"""
        if authorization:
            self.authorization = authorization.strip()
        if cuk is not None:
            self.cuk = (cuk or "").strip()
        self.setup_headers()
    
    def log(self, message):
        """带账号标识的日志输出"""
        log_msg = ""
        if self.nick_name:
            log_msg = f"[账号{self.index}|{self.nick_name}] {message}"
        elif self.remark:
            log_msg = f"[账号{self.index}|{self.remark}] {message}"
        else:
            log_msg = f"[账号{self.index}] {message}"
            
        print(log_msg)
        notify_content.append(log_msg)

    def _request(self, method, endpoint, allow_renew=True, **kwargs):
        """发送 HTTP 请求"""
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=self.headers,
                timeout=30,
                **kwargs
            )
            response.raise_for_status()
            try:
                data = response.json()
            except Exception:
                self.log(f"⚠️ 响应非JSON: {response.text[:150]}")
                return None
            
            # 检查业务状态码
            if not data.get('success') and not data.get('ok'):
                code = data.get('code')
                msg = data.get('message') or data.get('msg', '未知错误')

                if code == 'A00004' and allow_renew and self.wxid and self.wechat_server and not self._renewing:
                    self.log("⚠️ 登录态失效(A00004)，尝试自动续期")
                    if self.renew_login():
                        self.log("✅ 自动续期成功，重试当前请求")
                        return self._request(method, endpoint, allow_renew=False, **kwargs)
                    self.log("❌ 自动续期失败")
                
                if code == 'A00001':
                    self.log(f"ℹ️ 该任务需手动或消费完成 (A00001)，已跳过")
                else:
                    self.log(f"⚠️ API 错误: [{code}] {msg}")
                
                return None
            return data
        except Exception as e:
            self.log(f"❌ 请求失败: {e}")
            return None

    def _get_wx_code(self):
        """通过 getCode.py 统一接口获取小程序 code"""
        if not self.wxid:
            raise RuntimeError("未配置 wxid")
        return get_single_code(self.appid, self.wxid)

    def _login_by_code(self, code):
        """
        使用 code 换取 accessToken
        对齐小程序 /social/ma 登录逻辑
        """
        url = f"{self.base_url}/social/ma"
        base_headers = {
            "accept-language": self.headers.get("accept-language"),
            "Referer": self.headers.get("Referer"),
            "User-Agent": self.headers.get("User-Agent"),
        }
        # 兼容后端可能的参数格式差异，按优先级尝试
        attempts = [
            ("raw", code, "application/json"),
            ("json_obj", {"code": code}, "application/json"),
            ("form_obj", {"code": code}, "application/x-www-form-urlencoded"),
        ]
        last_err = None
        for mode, body, ctype in attempts:
            try:
                login_headers = dict(base_headers)
                login_headers["content-type"] = ctype
                if mode == "raw":
                    r = self.session.post(url, data=body, headers=login_headers, timeout=20)
                elif mode == "json_obj":
                    r = self.session.post(url, json=body, headers=login_headers, timeout=20)
                else:
                    r = self.session.post(url, data=body, headers=login_headers, timeout=20)
                r.raise_for_status()
                data = r.json()

                code_value = data.get("code")
                if code_value in ("00000", "000000", "A00002"):
                    token_info = (data.get("data") or {}).get("tokenInfo") or {}
                    access_token = token_info.get("accessToken")
                    if access_token:
                        return access_token
                last_err = RuntimeError(f"/social/ma 响应异常: {data}")
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"/social/ma 登录失败: {last_err}")

    def _fetch_cuk_by_code(self, code):
        """
        使用 code 获取 cuk/openId/unionId
        与小程序 /c/login/autologin 行为对齐
        """
        query = urlencode({"code": code})
        url = f"{self.base_url}/c/login/autologin?{query}"
        headers = dict(self.headers)
        resp = self.session.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        payload = data.get("data") or {}
        return payload.get("cuk") or ""

    def renew_login(self):
        """自动续期 Authorization + cuk"""
        if self._renewing:
            return False
        self._renewing = True
        try:
            wx_code = self._get_wx_code()
            self.log(f"ℹ️ 已获取 wx code，长度: {len(wx_code)}")

            new_auth = self._login_by_code(wx_code)
            new_cuk = ""
            try:
                new_cuk = self._fetch_cuk_by_code(wx_code)
            except Exception as e:
                self.log(f"⚠️ 获取 cuk 失败，继续仅使用新 Authorization: {e}")

            self._set_auth_and_cuk(new_auth, new_cuk if new_cuk else self.cuk)
            self.log("ℹ️ 登录态已更新到当前进程")
            return True
        except Exception as e:
            self.log(f"❌ 自动续期异常: {e}")
            return False
        finally:
            self._renewing = False
    
    def get_user_info(self):
        """获取用户信息"""
        data = self._request('GET', "/c/user/memberInfo")
        if data:
            user_data = data.get('data', {})
            
            # 优先使用手机号后四位
            mobile = user_data.get('mobile') or user_data.get('memberName')
            if mobile and len(str(mobile)) >= 4:
                self.nick_name = f"用户{str(mobile)[-4:]}"
            else:
                self.nick_name = user_data.get('nickName') or user_data.get('nickname') or user_data.get('name') or '未知'
            
            grade = user_data.get('gradeName', '未知')
            self.points = user_data.get('points', 0)
            self.log(f"登陆成功 | 等级: {grade} | 积分: {self.points}")
            return True
        return False

    def get_task_list(self):
        """获取任务列表"""
        mock_time = int(time.time() * 1000)
        return self._request('GET', f"/c/activity/todo/list?mockTime={mock_time}")
    
    def check_in(self):
        """执行签到"""
        payload = {"activityId": 1111, "mockTime": int(time.time() * 1000)}
        data = self._request('POST', "/c/activity/todo/checkIn", json=payload)
        if data:
            credits = (data.get('data') or {}).get('credits', 0)
            self.log(f"✅ 签到成功 | 获得积分: {credits}")
            return True
        return False
    
    def receive_task(self, activity_id):
        """领取任务"""
        payload = {"activityId": activity_id, "mockTime": int(time.time() * 1000)}
        # 领取任务，不做过多检查，失败可能是因为已领取
        self._request('POST', "/c/activity/todo/receive", json=payload)
    
    def complete_task(self, activity_id, task_name):
        """完成任务"""
        payload = {"activityId": activity_id, "mockTime": int(time.time() * 1000)}
        data = self._request('POST', "/c/activity/todo/complete", json=payload)
        if data:
            credits = (data.get('data') or {}).get('credits', 0)
            self.log(f"✅ 完成任务[{task_name}] | 获得积分: {credits}")
            return True
        return False

    def run(self):
        """执行单账号任务"""
        self.log("� 开始执行任务")

        # 0. 若未提供 Authorization，则直接尝试用 wxid 自动获取
        if not (self.authorization or "").strip():
            if self.wxid and self.wechat_server:
                self.log("ℹ️ 未提供 Authorization，尝试通过 wxid 自动登录")
                if not self.renew_login():
                    self.log("❌ 自动登录失败，跳过此账号")
                    return
            else:
                self.log("❌ 未提供 Authorization，且未配置 wxid/WECHAT_SERVER，跳过此账号")
                return
        
        # 1. 登录验证
        if not self.get_user_info():
            self.log("❌ 登录失败，跳过此账号")
            return

        time.sleep(random.uniform(1, 2))
        
        # 2. 获取任务
        task_data = self.get_task_list()
        if not task_data:
            return

        # 3. 签到
        check_in_todo = task_data.get('data', {}).get('checkInTodo', {})
        if check_in_todo:
            join_record = check_in_todo.get('checkInExtra', {}).get('joinRecord', [])
            if any(r.get('today') and r.get('joined') for r in join_record):
                self.log("ℹ️ 今日已签到")
            else:
                self.check_in()
                time.sleep(random.uniform(2, 3))

        # 4. 其他任务
        task_todo = task_data.get('data', {}).get('taskTodo', [])
        for task in task_todo:
            task_name = task.get('name', '未知任务')
            # 过滤不需要打印的任务或者不相关的任务
            
            task_extra = task.get('taskTodoExtra', {})
            if task_extra.get('completeCount', 0) >= task_extra.get('completeLimit', 1):
                self.log(f"ℹ️ 任务[{task_name}]已完成")
                continue
            
            # 先尝试领取任务
            self.receive_task(task.get('id'))
            time.sleep(random.uniform(0.5, 1))
            
            self.complete_task(task.get('id'), task_name)
            time.sleep(random.uniform(2, 4))
            
        self.log("🏁 任务执行结束")
        
        # 再次查询积分验证增长
        try:
            time.sleep(1)
            # 复用 get_user_info 但不打印登录成功日志，而是直接获取
            data = self._request('GET', "/c/user/memberInfo")
            if data:
                new_points = data.get('data', {}).get('points', 0)
                diff = new_points - self.points
                if diff > 0:
                    self.log(f"📈 本次运行共增加积分: +{diff} (当前: {new_points})")
                else:
                    self.log(f"📊 积分无变化 (当前: {new_points})")
        except:
            pass
        print("")

def get_env_data():
    """读取环境变量"""
    import re
    # 优先读取 WX_ID，支持 fallback 到 FEIHE_DATA 兼容旧版本，不再需要解析 Authorization 等复杂变量，直接读取微信 ID
    wxid_raw = (os.getenv("WX_ID") or os.getenv("FEIHE_DATA") or "").strip()
    wechat_server = os.getenv("WECHAT_SERVER", "").strip()
    if not wxid_raw:
        print("❌ 未找到环境变量 WX_ID 或 FEIHE_DATA")
        return []
    
    accounts = []
    # 支持 @, &, 或换行分隔
    items = [x.strip() for x in re.split(r"[@&\n]+", wxid_raw) if x.strip()]
    for item in items:
        if "#" in item:
            wxid, remark = item.split("#", 1)
            wxid = wxid.strip()
            remark = remark.strip() or wxid
        else:
            wxid = item.strip()
            remark = wxid
            
        if wxid:
            accounts.append({
                "authorization": "",
                "cuk": "",
                "wxid": wxid,
                "remark": remark
            })
              
    print(f"检测到 {len(accounts)} 个账号")
    if wechat_server:
        print(f"ℹ️ 已启用自动续期服务 WECHAT_SERVER={wechat_server}")
    else:
        print("ℹ️ 未配置 WECHAT_SERVER，仅能使用已有 Authorization 账号")
    return accounts

def main():
    print(f"============ 星妈会自动化脚本 ============")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"=======================================\n")
    
    accounts = get_env_data()
    if not accounts:
        return

    for i, acc in enumerate(accounts, 1):
        client = FeiheClient(
            authorization=acc['authorization'],
            cuk=acc['cuk'],
            wxid=acc.get('wxid', ''),
            remark=acc.get('remark', ''),
            index=i,
            wechat_server=os.getenv("WECHAT_SERVER", "")
        )
        client.run()
        # 账号间延迟
        if i < len(accounts):
            time.sleep(random.uniform(5, 10))
            
    # 发送通知
    if ENABLE_NOTIFY:
        send("星妈会自动化", "\n".join(notify_content))

if __name__ == '__main__':
    main()
