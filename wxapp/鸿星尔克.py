#!/usr/bin/python3
# -- coding: utf-8 --
# -------------------------------
# cron "21 10,16 * * *" script-path=xxx.py,tag=匹配cron用
# 账号变量（二选一）：
#   WX_ID = wxid#备注；多账号用换行或 & 分隔（走 getCode 取 code -> on_login 登录）
#   HXEK  = memberId@enterpriseId；多账号用 # 分隔（原模式，无需 getCode）
# const $ = new Env('鸿星尔克官方会员中心小程序')

import os
import re
import sys
import random
import time
import hashlib
import json
from datetime import datetime, time as times
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# 禁用安全请求警告
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# 让根目录脚本能 import wxapp/getCode（WX_ID 取 code 用）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wxapp'))
try:
    from getCode import get_single_code
    print("加载 getCode 成功！")
except Exception as _e:
    get_single_code = None
    print(f"加载 getCode 失败，WX_ID 模式不可用: {_e}")

IS_DEV = False
if os.path.isfile('DEV_ENV.py'):
    import DEV_ENV
    IS_DEV = True

# 导入通知功能
try:
    from sendNotify import send
    print("加载通知服务成功！")
except:
    print("加载通知服务失败!")

send_msg = ''
one_msg = ''

def Log(cont=''):
    global send_msg, one_msg
    print(cont)
    if cont:
        one_msg += f'{cont}\n'
        send_msg += f'{cont}\n'

# 默认设备信息（on_login 需要）
SYSTEM_INFO = {
    "SDKVersion": "3.16.2", "batteryLevel": "0", "brand": "Redmi",
    "fontSizeSetting": 16, "language": "zh_CN", "model": "M2012K11AC",
    "pixelRatio": 2.75, "platform": "android", "screenHeight": 873,
    "screenWidth": 393, "statusBarHeight": 30, "system": "Android 15",
    "version": "8.0.72", "windowHeight": 797, "windowWidth": 393,
    "benchmarkLevel": 32, "safeArea": {"width": 393, "right": 393, "top": 30, "left": 0, "bottom": 873, "height": 843},
    "theme": "-1", "host": {"env": "WeChat", "version": 671107155},
    "enableDebug": "-1", "mode": "default", "deviceOrientation": "portrait",
    "bluetoothEnabled": True, "locationEnabled": True, "wifiEnabled": True,
    "albumAuthorized": "-1", "cameraAuthorized": True, "locationAuthorized": True,
    "microphoneAuthorized": "-1", "notificationAuthorized": True,
    "notificationAlertAuthorized": "-1", "notificationBadgeAuthorized": "-1",
    "notificationSoundAuthorized": "-1", "phoneCalendarAuthorized": True,
    "bluetoothAuthorized": True, "locationReducedAccuracy": "-1",
    "devicePixelRatio": 2.75, "renderer": "-1", "environment": "-1"
}

def _collect(obj, key):
    """收集嵌套 dict/list 中所有名为 key 的值（大小写不敏感），返回列表"""
    out = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k).lower() == str(key).lower():
                    out.append(v)
                walk(v)
        elif isinstance(o, list):
            for i in o:
                walk(i)
    walk(obj)
    return out

def _pick(found, exclude='-1'):
    """优先返回不等于 exclude 的值（避开登录时透传的 -1）"""
    for v in found:
        if str(v) != str(exclude):
            return v
    return found[0] if found else None

class RUN:
    def __init__(self, index):
        global one_msg
        one_msg = ''
        self.index = index + 1
        self.memberId = None
        self.enterpriseId = None
        self.s = requests.session()
        self.s.verify = False
        self.headers = {
            'Host': 'hope.demogic.com',
            'xweb_xhr': '1',
            'channelEntrance': 'wx_app',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) XWEB/9129',
            'sign': '',
            'Accept': '*/*',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': 'https://servicewechat.com/wxa1f1fa3785a47c7d/55/page-frame.html',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        self.appid = 'wxa1f1fa3785a47c7d'
        self.defualt_parmas = {
            'memberId': '',
            'cliqueId': '-1',
            'cliqueMemberId': '-1',
            'useClique': '0',
            'enterpriseId': '',
            'appid': self.appid,
            'gicWxaVersion': '3.9.16'
        }
        self.baseUrl = 'https://hope.demogic.com/gic-wx-app/'
        self.use_power_max = False

    def init_by_hxek(self, info):
        """原 HXEK 模式：memberId@enterpriseId"""
        split_info = info.split('@')
        if len(split_info) < 2:
            print('HXEK 变量长度不足，请检查变量')
            return False
        self.memberId = split_info[0]
        self.enterpriseId = split_info[1]
        self._apply_account()
        return True

    def init_by_wxid(self, wxid):
        """WX_ID 模式：getCode 取 code -> on_login 换 memberId/enterpriseId"""
        if not get_single_code:
            print('getCode 未加载，无法使用 WX_ID 模式')
            return False
        try:
            code = get_single_code(self.appid, wxid)
        except Exception as e:
            print(f'getCode 获取 code 失败: {e}')
            return False
        try:
            self._on_login(code)
        except Exception as e:
            print(f'on_login 登录失败: {e}')
            return False
        try:
            self._login_after_handle()
        except Exception as e:
            print(f'login-after-handle 失败: {e}')
            return False
        self._apply_account()
        return True

    def _apply_account(self):
        self.headers['sign'] = self.enterpriseId
        self.defualt_parmas['memberId'] = self.memberId
        self.defualt_parmas['enterpriseId'] = self.enterpriseId

    def _on_login(self, code):
        """POST on_login.json，用 jcode 换取 memberId / enterpriseId 等"""
        sign, random_int, timestamp = self.hxek_sign("-1", self.appid)
        data = {
            'systemInfo': json.dumps(SYSTEM_INFO, ensure_ascii=False),
            'jcode': code,
            'openid': '',
            'scene': '1106',
            'memberId': '-1',
            'cliqueId': '-1',
            'cliqueMemberId': '-1',
            'useClique': '0',
            'enterpriseId': '',
            'unionid': '',
            'wxOpenid': '',
            'random': random_int,
            'appid': self.appid,
            'transId': self.appid + timestamp,
            'sign': sign,
            'timestamp': timestamp,
            'gicWxaVersion': '3.9.78',
            'launchOptions': '{"path":"pages/authorize/authorize","query":{},"scene":1106,"referrerInfo":{},"mode":"default","apiCategory":"default"}'
        }
        url = self.baseUrl + 'on_login.json'
        resp = self.s.post(url, data=data, headers=self.headers, verify=False)
        try:
            resp_json = resp.json()
        except ValueError:
            raise Exception(f'on_login 非 JSON 响应: HTTP {resp.status_code} {resp.text[:200]}')
        Log(f'on_login 响应: {json.dumps(resp_json, ensure_ascii=False)[:500]}')
        memberId = _pick(_collect(resp_json, 'memberId'))
        enterpriseId = _pick(_collect(resp_json, 'enterpriseId'))
        if not memberId or not enterpriseId:
            has_openid = _pick(_collect(resp_json, 'openid'))
            if has_openid:
                raise Exception(f'该 wxid 对应的 openid({has_openid}) 在鸿星尔克未注册会员（memberId 为空）。请先在小程序内授权手机号完成注册，或对该账号改用 HXEK=memberId@enterpriseId')
            raise Exception(f'on_login 未取到 memberId/enterpriseId，响应: {json.dumps(resp_json, ensure_ascii=False)[:500]}')
        self.memberId = str(memberId)
        self.enterpriseId = str(enterpriseId)
        openid = _pick(_collect(resp_json, 'openid'))
        unionid = _pick(_collect(resp_json, 'unionid'))
        wxOpenid = _pick(_collect(resp_json, 'wxOpenid'))
        if openid:
            self.defualt_parmas['openid'] = openid
        if unionid:
            self.defualt_parmas['unionid'] = unionid
        if wxOpenid:
            self.defualt_parmas['wxOpenid'] = wxOpenid
        Log(f'> 登录成功 memberId={self.memberId} enterpriseId={self.enterpriseId}')

    def _login_after_handle(self):
        """on_login 之后的登录后置处理：建立会话/绑定 openid 等"""
        sign, random_int, timestamp = self.hxek_sign(self.memberId, self.appid)
        body = {
            'type': 0,
            'param': '{}',
            'memberId': self.memberId,
            'cliqueId': '-1',
            'cliqueMemberId': '-1',
            'useClique': 0,
            'enterpriseId': self.enterpriseId,
            'unionid': self.defualt_parmas.get('unionid', ''),
            'openid': self.defualt_parmas.get('openid', ''),
            'wxOpenid': self.defualt_parmas.get('wxOpenid', ''),
            'sign': sign,
            'random': random_int,
            'appid': self.appid,
            'transId': self.appid + timestamp,
            'timestamp': timestamp,
            'gicWxaVersion': '3.9.78',
            'launchOptions': '{"path":"pages/authorize/authorize","query":{},"scene":1106,"referrerInfo":{},"mode":"default","apiCategory":"default"}'
        }
        url = self.baseUrl + 'login-after-handle-process.json'
        # 该接口要求 JSON body + application/json content-type
        headers = dict(self.headers)
        headers['Content-Type'] = 'application/json;charset=UTF-8'
        headers['sign'] = self.enterpriseId
        resp = self.s.post(url, json=body, headers=headers, verify=False)
        try:
            resp_json = resp.json()
        except ValueError:
            raise Exception(f'login-after-handle 非 JSON 响应: HTTP {resp.status_code} {resp.text[:200]}')
        Log(f'login-after-handle 响应: {json.dumps(resp_json, ensure_ascii=False)[:500]}')
        # 若返回了新的 memberId/enterpriseId，以最新为准
        memberId = _pick(_collect(resp_json, 'memberId'))
        enterpriseId = _pick(_collect(resp_json, 'enterpriseId'))
        if memberId:
            self.memberId = str(memberId)
        if enterpriseId:
            self.enterpriseId = str(enterpriseId)
        if self.memberId:
            self.defualt_parmas['memberId'] = self.memberId
        if self.enterpriseId:
            self.defualt_parmas['enterpriseId'] = self.enterpriseId
        Log(f'> 登录后置处理完成 memberId={self.memberId} enterpriseId={self.enterpriseId}')

    def make_request(self, url, method='post', headers={}, data={}, params=None):
        if headers == {}:
            headers = self.headers
        try:
            if method.lower() == 'get':
                response = self.s.get(url, headers=headers, verify=False, params=params)
            elif method.lower() == 'post':
                response = self.s.post(url, headers=headers, json=data, params=params, verify=False)
            else:
                raise ValueError("不支持的请求方法?: " + method)
            return response.json()
        except requests.exceptions.RequestException as e:
            print("请求异常?：", e)
        except ValueError as e:
            print("值错误或不支持的请求方法?：", e)
        except Exception as e:
            print("发生了未知错误?：", e)

    def hxek_sign(self, memberId, appid):
        secret = 'damogic8888'
        # 获取GMT+8的当前时间戳
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        # 生成随机数
        random_int = random.randint(1000000, 9999999)
        # 构建待加密字符串
        raw_string = f"timestamp={timestamp}transId={appid}{timestamp}secret={secret}random={random_int}memberId={memberId}"
        # 使用MD5进行加密
        md5_hash = hashlib.md5(raw_string.encode())
        sign = md5_hash.hexdigest()
        return sign, random_int, timestamp

    def gen_sign(self):
        sign, random_int, timestamp = self.hxek_sign(self.memberId, self.appid)
        self.defualt_parmas['random'] = random_int
        self.defualt_parmas['sign'] = sign
        self.defualt_parmas['timestamp'] = timestamp
        self.defualt_parmas['transId'] = self.appid + timestamp

    def get_member_grade_privileg(self):
        act_name = '获取用户信息'
        Log(f'\n====== {act_name} ======')
        self.gen_sign()
        self.defualt_parmas['launchOptions'] = '{"path":"pages/points-mall/member-task/member-task","query":{},"scene":1256,"referrerInfo":{},"apiCategory":"default"}'

        url = f"{self.baseUrl}get_member_grade_privileg.json"
        response = self.make_request(url,'post',params=self.defualt_parmas)
        if response.get('errcode', -1) == 0:
            data = response.get('response', {})
            member = data.get('member', {})
            if member:
                phoneNumber = member.get('phoneNumber', '')
                phone = phoneNumber[:4]+'***'+phoneNumber[-4:]
                wxOpenid = member.get('openId', '')
                unionid = member.get('thirdUnionid', '')
                self.defualt_parmas['wxOpenid'] = wxOpenid
                self.defualt_parmas['unionid'] = unionid
                Log(f'{act_name}成功！?')
                Log(f'> 当前用户：【{phone}】')
            return True
        elif response.get('errcode', -1) == 900001:
            Log(f'> 今天已签到?')
            return False
        else:
            print(f'{act_name}失败?：{response}')
            return False

    def get_member_asset(self):
        """获取用户资产信息，包括积分"""
        act_name = '获取用户资产'
        Log(f'\n====== {act_name} ======')
        self.gen_sign()
        
        # 添加资产查询参数
        asset_params = self.defualt_parmas.copy()
        asset_params['dataIconKeyList'] = 'D007,D010'  # D007代表可用积分
        asset_params['launchOptions'] = '{"path":"pages/authorize/authorize","query":{},"scene":1256,"referrerInfo":{},"apiCategory":"default"}'

        url = f"{self.baseUrl}get-member-asset.json"
        response = self.make_request(url, 'get', params=asset_params)
        
        if response.get('code') == '0':
            result = response.get('result', {})
            available_points = result.get('D007', 0)  # D007代表可用积分
            Log(f'{act_name}成功！?')
            Log(f'> 当前可用积分：【{available_points}】')
            return available_points
        else:
            Log(f'{act_name}失败?：{response}')
            return 0

    def member_sign(self):
        act_name = '签到'
        Log(f'\n====== {act_name} ======')
        self.gen_sign()
        self.defualt_parmas['launchOptions'] = '{"path":"pages/points-mall/member-task/member-task","query":{},"scene":1256,"referrerInfo":{},"apiCategory":"default"}'

        url = f"{self.baseUrl}member_sign.json"
        response = self.make_request(url,'post',params=self.defualt_parmas)
        if response.get('errcode', -1) == 0:
            res = response.get('response', {})
            memberSign = res.get('memberSign', {})
            integralCount = memberSign.get('integralCount', '')
            continuousCount = memberSign.get('continuousCount', '')
            points = res.get('points', '')
            Log(f'{act_name}成功！?')
            Log(f'> 签到获得积分：【{integralCount}】 连续签到：【{continuousCount}】天')
            return True, integralCount, continuousCount
        elif response.get('errcode', -1) == 900001:
            Log(f'> 今天已签到?')
            return True, 0, None
        else:
            print(f'{act_name}失败?：{response}')
            return False, 0, None

    def main(self):
        Log(f"\n开始执行第{self.index}个账号--------------->>>>>")
        if self.get_member_grade_privileg():
            sign_result, integralCount, continuous_count = self.member_sign()
            # 获取当前可用积分
            available_points = self.get_member_asset()
            return sign_result, integralCount, continuous_count, available_points
        else:
            return False, 0, None, 0

def random_delay(min_delay=1, max_delay=5):
    delay = random.uniform(min_delay, max_delay)
    print(f">本次随机延迟： {delay:.2f} 秒.....")
    time.sleep(delay)

def send_notification(title, content):
    """发送通知"""
    try:
        # 尝试从sendNotify导入send函数
        from sendNotify import send
        send(title, content)
        print("通知发送成功！")
    except Exception as e:
        print(f"发送通知失败: {e}")

if __name__ == '__main__':
    APP_NAME = '鸿星尔克官方会员中心小程序'
    local_version = '2025.11.06'

    # 支持两种变量：
    #   WX_ID = wxid#备注；多账号用换行或 & 分隔（走 getCode 取 code -> on_login 登录）
    #   HXEK  = memberId@enterpriseId；多账号用 # 分隔（原模式，无需 getCode）
    wx_env = (os.environ.get('WX_ID') or '').strip()
    hxek_env = (os.environ.get('HXEK') or '').strip()

    accounts = []  # [(mode, raw), ...]
    if wx_env:
        for raw in re.split(r'[\n&]', wx_env):
            raw = raw.strip()
            if raw:
                accounts.append(('wxid', raw.split('#')[0].strip()))
    if hxek_env:
        for raw in hxek_env.split('#'):
            raw = raw.strip()
            if raw:
                accounts.append(('hxek', raw))

    if not accounts:
        print("未填写 WX_ID 或 HXEK 变量")
        exit()

    # 统计信息
    success_count = 0
    fail_count = 0
    total_accounts = len(accounts)
    account_details = []
    total_points = 0  # 总积分

    print(f"\n>>>>>>>>>>共获取到{total_accounts}个账号<<<<<<<<<<")
    for index, (mode, raw) in enumerate(accounts):
        run = RUN(index)
        if mode == 'wxid':
            ok = run.init_by_wxid(raw)
            mode_label = 'WX_ID'
        else:
            ok = run.init_by_hxek(raw)
            mode_label = 'HXEK'
        if not ok:
            fail_count += 1
            account_details.append(f"账号{index+1}({mode_label}): 初始化失败 ?")
            if index < total_accounts - 1:
                random_delay(2, 5)
            continue
        run_result, integralCount, continuous_count, available_points = run.main()
        if run_result:
            success_count += 1
            account_details.append(f"账号{index+1}({mode_label}): 签到成功 ? | 本次获得: {integralCount}积分 | 连续签到: {continuous_count}天 | 总积分: {available_points}")
            total_points += available_points
        else:
            fail_count += 1
            account_details.append(f"账号{index+1}({mode_label}): 签到失败 ? | 总积分: {available_points}")
            total_points += available_points

        # 如果不是最后一个账号，添加延迟
        if index < total_accounts - 1:
            random_delay(2, 5)

    # 汇总结果
    summary = f"""
【{APP_NAME}签到结果】
执行时间: {time.strftime("%Y-%m-%d %H:%M:%S")}
总账号数: {total_accounts}
成功: {success_count} 个
失败: {fail_count} 个
总积分: {total_points}

【账号详情】
""" + "\n".join(account_details)

    print(summary)

    # 发送通知
    title = f"{APP_NAME}签到通知"
    content = summary

    try:
        from sendNotify import send
        send(title, content)
        print("通知发送成功！")
    except Exception as e:
        print(f"发送通知失败: {e}")