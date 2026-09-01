import yyb  # 自动同步 yyb_go 存活账号
"""

变量: WX_SERVER (必填，yyb_go 服务地址)；WX_ID (可选白名单，留空自动拉取存活账号) 
    PROXY_API_URL (代理api，返回一条txt文本，内容为代理ip:端口)
定时: 一天两次
cron: 24 14,02 * * *
"""
# name: 紫金

import os
import requests
import json
import time
from datetime import datetime
import re

class AutoSign:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'Content-Type': 'application/json',
            'Accept': '*/*',
            'Host': 'sxkyziqidonglai.cn',
            'Connection': 'keep-alive'
        })
        
        self.wechat_webhook = os.getenv('WECHAT_WEBHOOK', 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=')
        self.wechat_enabled = os.getenv('WECHAT_ENABLED', 'true').lower() == 'true'
            
    def mask_phone(self, phone):
        if not phone or len(phone) < 7:
            return phone
        return phone[:3] + '****' + phone[-4:]
    
    def send_wechat_message(self, sign_results):
        if not self.wechat_enabled or not self.wechat_webhook:
            print("⚠️ 企业微信推送未配置或已禁用")
            return
        
        try:
            print("🔍 正在发送企业微信消息...")
            
            # 构建消息内容
            message = "📊 小紫有约签到汇总\n\n"
            
            for i, result in enumerate(sign_results, 1):
                status_icon = "✅" if result.get('success', False) else "❌"
                message += f"{i}. {status_icon} {result['content']}\n"
            
            message += f"\n⏰ 签到时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            
            # 发送消息
            data = {
                "msgtype": "text",
                "text": {
                    "content": message
                }
            }
            
            response = requests.post(
                self.wechat_webhook,
                headers={'Content-Type': 'application/json'},
                data=json.dumps(data),
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('errcode') == 0:
                    print("✅ 企业微信消息发送成功")
                else:
                    print(f"❌ 企业微信推送失败: {result.get('errmsg')}")
            else:
                print(f"❌ 企业微信推送失败，状态码: {response.status_code}")
                
        except Exception as e:
            print(f"❌ 企业微信推送失败: {e}")
    
    def get_micro_page_detail(self, cookie, page_id="L/9h2Rpn+5IBe0zVpSniWA=="):
        """
        获取微页面详情，从中提取 actCode
        :param cookie: Cookie 字符串
        :param page_id: 页面ID，默认为7299
        :return: actCode 字符串，如果获取失败返回 None
        """
        url = "https://sxkyziqidonglai.cn/api/mobile/eShop/siteView/getMicroPageDetail"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 NetType/WIFI MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541212) XWEB/16897 Flue',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json, text/plain, */*',
            'Host': 'sxkyziqidonglai.cn',
            'Connection': 'keep-alive',
            'Origin': 'https://sxkyziqidonglai.cn',
            'Referer': f'https://sxkyziqidonglai.cn/mall/microPage?id={page_id}',
            'Cookie': cookie
        }
        
        data = {
            "siteId": "SITE_33254242630091515087",
            "id": page_id
        }
        
        try:
            response = requests.post(url, headers=headers, data=data)
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    # 从 data.json 字段中提取 actCode
                    json_data = result.get('data', {}).get('json', '')
                    if json_data:
                        try:
                            json_obj = json.loads(json_data)
                            module_list = json_obj.get('moduleList', [])
                            
                            # 遍历模块列表，查找包含 actCode 的链接
                            for module in module_list:
                                if module.get('type') == 'img':
                                    img_list = module.get('list', [])
                                    for img in img_list:
                                        jump = img.get('jump', {})
                                        jump_data = jump.get('data', '')
                                        
                                        # 使用正则表达式提取 actCode
                                        # 查找 actCode=XXX 格式
                                        match = re.search(r'actCode=([A-Z0-9]+)', jump_data)
                                        if match:
                                            act_code = match.group(1)
                                            print(f"✅ 成功获取 actCode: {act_code}")
                                            return act_code
                                        
                                        # 如果链接中包含 signIn，也可以尝试提取
                                        if 'signIn' in jump_data or 'activity/signIn' in jump_data:
                                            match = re.search(r'actCode=([A-Z0-9]+)', jump_data)
                                            if match:
                                                act_code = match.group(1)
                                                print(f"✅ 成功获取 actCode (从签到链接): {act_code}")
                                                return act_code
                        except json.JSONDecodeError as e:
                            print(f"解析 JSON 数据失败: {e}")
                    
                    print("⚠️ 未能从响应中提取 actCode")
                    return None
                else:
                    print(f"获取微页面详情失败: {result.get('msg')}")
                    return None
            else:
                print(f"获取微页面详情请求失败，状态码: {response.status_code}")
                return None
        except Exception as e:
            print(f"获取微页面详情时发生错误: {e}")
            return None
    
    def get_user_info(self, cookie):
        url = "https://sxkyziqidonglai.cn/api/mobile/eShop/eshopVipUser/getUserInfo"
        
        headers = {
            'Host': 'sxkyziqidonglai.cn',
            'Connection': 'keep-alive',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'Referer': 'https://sxkyziqidonglai.cn/mall/personal',
            'Cookie': cookie
        }
        
        data = {
            "siteId": "SITE_33254242630091515087"
        }
        
        try:
            response = requests.post(url, headers=headers, data=data)
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    return result.get('data', {})
                else:
                    print(f"获取用户信息失败: {result.get('msg')}")
                    return None
            else:
                print(f"请求失败，状态码: {response.status_code}")
                return None
        except Exception as e:
            print(f"获取用户信息时发生错误: {e}")
            return None
    
    def get_sign_info(self, cookie, act_code):
        url = "https://sxkyziqidonglai.cn/api/mobile/activity-v2/activity/launchPage"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 NetType/WIFI MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat(0x63090c37) XWEB/14185 Flue',
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/plain, */*',
            'Host': 'sxkyziqidonglai.cn',
            'Connection': 'keep-alive',
            'Cookie': cookie
        }
        
        data = {
            "actCode": act_code,
            "siteId": "SITE_33254242630091515087"
        }
        
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    return result.get('data', {})
                else:
                    print(f"获取签到信息失败: {result.get('msg')}")
                    return None
            else:
                print(f"获取签到信息请求失败，状态码: {response.status_code}")
                return None
        except Exception as e:
            print(f"获取签到信息时发生错误: {e}")
            return None
    
    def check_today_sign_status(self, sign_info):
        if not sign_info or 'signInfo' not in sign_info:
            return False, 0
        
        sign_info_data = sign_info['signInfo']
        continuous_days = sign_info_data.get('signContinuousDays', 0)
        
        sign_records = sign_info_data.get('signRecordVoList', [])
        today = datetime.now().strftime('%Y-%m-%d')
        
        for record in sign_records:
            if record.get('signDate') == today:
                return True, continuous_days
        
        return False, continuous_days
    
    def sign_in(self, cookie, act_code):
        url = "https://sxkyziqidonglai.cn/api/mobile/activity-v2/activity/launchByValidater"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'Content-Type': 'application/json',
            'Accept': '*/*',
            'Host': 'sxkyziqidonglai.cn',
            'Connection': 'keep-alive',
            'Cookie': cookie
        }
        
        data = {
            "actCode": act_code,
            "siteId": "SITE_33254242630091515087"
        }
        
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            if response.status_code == 200:
                result = response.json()
                return result
            else:
                print(f"签到请求失败，状态码: {response.status_code}")
                return None
        except Exception as e:
            print(f"签到时发生错误: {e}")
            return None
    
    def get_user_balance(self, cookie):
        url = "https://sxkyziqidonglai.cn/api/mobile/eShop/eshopVipUser/getUserInfo"
        
        headers = {
            'Host': 'sxkyziqidonglai.cn',
            'Connection': 'keep-alive',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'Referer': 'https://sxkyziqidonglai.cn/mall/personal',
            'Cookie': cookie
        }
        
        data = {
            "siteId": "SITE_33254242630091515087"
        }
        
        try:
            response = requests.post(url, headers=headers, data=data)
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    return result.get('data', {})
                else:
                    print(f"查询积分失败: {result.get('msg')}")
                    return None
            else:
                print(f"查询积分请求失败，状态码: {response.status_code}")
                return None
        except Exception as e:
            print(f"查询积分时发生错误: {e}")
            return None
    
    def process_accounts(self):
        cookie_env = os.getenv('zjck')
        if not cookie_env:
            print("未找到环境变量 zjck")
            return
        cookies = cookie_env.split('\n')
        
        print(f"检测到 {len(cookies)} 个账号")
       
        sign_results = [] 
        
        for i, cookie in enumerate(cookies, 1):
            cookie = cookie.strip()
            if not cookie:
                continue
                
            print(f"\n处理第 {i} 个账号...")
            
            user_info = self.get_user_info(cookie)
            if not user_info:
                print(f"第 {i} 个账号获取用户信息失败")
                sign_results.append({
                    'success': False,
                    'content': f"第 {i} 个账号获取用户信息失败"
                })
                continue
            
            phone = user_info.get('phone', '未知')
            nickname = user_info.get('nickname', '未知')
            masked_phone = self.mask_phone(phone)
            
            print(f"📱 手机号: {masked_phone}, 微信名: {nickname}")
            
            # 首先获取 actCode
            print("🔍 正在获取微页面详情...")
            act_code = self.get_micro_page_detail(cookie)
            
            if not act_code:
                print("⚠️ 无法获取 actCode，使用默认值")
                act_code = "SIGNIN202510291408132731"  # 备用默认值
            
            print(f"📋 使用 actCode: {act_code}")
            
            print("🔍 正在获取签到信息...")
            sign_info = self.get_sign_info(cookie, act_code)
            is_signed_today, continuous_days = self.check_today_sign_status(sign_info)
            
            print(f"📅 连续签到天数: {continuous_days} 天")
            
            if is_signed_today:
                print("✅ 今日已签到，跳过签到操作")
                sign_msg = "今日已签到"
                sign_success = True
            else:
                print("🔍 今日未签到，正在执行签到...")
                sign_result = self.sign_in(cookie, act_code)
                
                if sign_result:
                    sign_msg = sign_result.get('msg', '签到成功')
                    sign_success = sign_result.get('success', False)
                    print(f"📝 签到结果: {sign_msg}")
                    
                    if sign_success:
                        print("🔍 签到成功，重新获取签到信息...")
                        time.sleep(1)  # 等待1秒让服务器更新
                        updated_sign_info = self.get_sign_info(cookie, act_code)
                        if updated_sign_info:
                            _, updated_continuous_days = self.check_today_sign_status(updated_sign_info)
                            if updated_continuous_days > continuous_days:
                                continuous_days = updated_continuous_days
                                print(f"📅 更新连续签到天数: {continuous_days} 天")
                else:
                    sign_msg = "签到失败"
                    sign_success = False
                    print(f"❌ 签到失败")
            
            print("🔍 正在查询最新积分...")
            balance_info = self.get_user_balance(cookie)
            
            if balance_info:
                balance = balance_info.get('balance', 0)
                print(f"💰 当前积分: {balance}")
                
                print(f"✅ 手机号: {masked_phone}  微信名: {nickname}  连续签到: {continuous_days}天  签到: {sign_msg}  余额: {balance}")
                
                sign_results.append({
                    'success': sign_success,
                    'content': f"手机号: {masked_phone}  微信名: {nickname}  连续签到: {continuous_days}天  签到: {sign_msg}  余额: {balance}"
                })
            else:
                print(f"❌ 查询积分失败")
                sign_results.append({
                    'success': sign_success,
                    'content': f"手机号: {masked_phone}  微信名: {nickname}  连续签到: {continuous_days}天  签到: {sign_msg}  余额: 查询失败"
                })
            
            if i < len(cookies):
                print("⏳ 等待 2 秒后继续...")
                time.sleep(2)
        
        if sign_results:
            self.send_wechat_message(sign_results)

def main():
    auto_sign = AutoSign()
    auto_sign.process_accounts()

if __name__ == "__main__":
    main()