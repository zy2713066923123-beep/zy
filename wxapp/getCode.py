#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信小程序登录Code获取模块（双协议支持）
支持两种服务：
  1) Wechat (牛子协议) - 微信iPad/iPhone协议服务
  2) YYBServer (应用宝) - yyb_go 微信扫码代理服务

环境变量：
    WECHAT_SERVER:  牛子协议服务地址（默认 http://192.168.6.222:8011）
    YYB_SERVER:     应用宝服务地址（默认 http://127.0.0.1:8000）
    SERVER_TYPE:    强制指定服务类型：wechat / yyb （不设则自动检测）
    ADMIN_KEY:      牛子协议管理密钥（仅WeChatPadPro/iwechat需要）
    WX_ID:          可选，指定要获取Code的微信账号ID

使用方式：
    # 自动检测模式（优先YYB，其次Wechat）
    from getCode import get_single_code, get_wechat_codes
    
    code = get_single_code("wxd4185d00bf7e08ac", "wxid_xxx")
    
    # 或强制指定
    os.environ["SERVER_TYPE"] = "wechat"
"""

import os
import requests
import json
import pathlib
from typing import List, Dict, Tuple, Optional, Literal

ProtocolType = Literal["Wechat", "YYB", "Unknown"]

# ============================================================
#  全局配置缓存（避免重复初始化检测）
# ============================================================
_config_cache: Dict = {}

# ============================================================
#  YYB Server（应用宝）适配器
# ============================================================

class YYBAdapter:
    """应用宝(yyb_go) 服务适配器"""
    
    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip('/')
        self._accounts_cache = None
        self._cache_time = 0
    
    def health_check(self) -> bool:
        """健康检查"""
        try:
            url = f"{self.server_url}/health"
            print(f"[YYB] 健康检查: {url}")
            r = requests.get(url, timeout=5)
            print(f"[YYB] 健康检查响应: status={r.status_code}, body={r.text[:100]}")
            
            if r.status_code != 200:
                return False
            
            data = r.json()
            return data.get("code") == 0
        except Exception as e:
            print(f"[YYB] 健康检查异常: {e}")
            return False
    
    def get_accounts(self) -> List[Dict]:
        """获取在线账号列表"""
        try:
            r = requests.get(f"{self.server_url}/accounts", timeout=15)
            r.raise_for_status()
            data = r.json()
            
            if data.get("code") != 0:
                raise Exception(data.get("msg", "获取账号失败"))
            
            accounts = data.get("data", [])
            if not isinstance(accounts, list):
                raise Exception(f"返回格式错误: {type(accounts)}")
            
            # 只返回存活账号
            valid = []
            for acc in accounts:
                status = str(acc.get("status", "")).lower()
                if status in ("alive", "", "unknown"):
                    valid.append({
                        "wxid": acc.get("openid", ""),
                        "openid": acc.get("openid", ""),
                        "uin": acc.get("uin"),
                        "nickname": acc.get("nickname"),
                        "alias": acc.get("alias"),
                        "avatar": acc.get("avatar"),
                        "status": 1,
                        "loginState": 1,
                        "_ref": str(acc.get("id", "")) or acc.get("openid", ""),
                    })
            
            return valid
            
        except requests.RequestException as e:
            raise Exception(f"应用宝获取账号列表失败: {e}")
        except json.JSONDecodeError:
            raise Exception("应用宝账号列表响应格式错误")
    
    def get_code(self, ref: str, app_id: str) -> str:
        """获取小程序登录Code
        
        Args:
            ref: 账号标识 (id/uin/openid)
            app_id: 小程序AppID
            
        Returns:
            str: 微信小程序登录code
        """
        url = f"{self.server_url}/wxapp/getCode"
        payload = {
            "ref": ref,
            "app_id": app_id
        }
        
        headers = {"Content-Type": "application/json"}
        
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=30)
            result = r.json()
            
            code_val = 0
            if isinstance(result, dict):
                code_val = result.get("code", -1)
                
            # HTTP层错误或业务错误
            if r.status_code == 409:
                raise Exception("账号login_buffer已过期，需要重新扫码登录")
            if code_val != 0:
                msg = result.get("msg", f"HTTP {r.status_code}")
                raiseException(f"[{code_val}] {msg}")
            
            # 从 data.result.code 提取
            data = result.get("data", {})
            if not isinstance(data, dict):
                raise Exception(f"响应data异常: {str(data)[:100]}")
                
            inner = data.get("result", {})
            if not isinstance(inner, dict):
                raise Exception(f"result异常: {str(inner)[:100]}")
                
            code = inner.get("code")
            if not code or not isinstance(code, str) or len(code) < 5:
                raise Exception(f"未拿到有效code: {json.dumps(result, ensure_ascii=False)}")
            
            return code
            
        except requests.RequestException as e:
            raise Exception(f"应用宝请求code失败: {e}")
        except json.JSONDecodeError:
            raise Exception("应用宝code响应格式错误")


# ============================================================
#  Wechat (牛子协议) 适配器
# ============================================================

class WechatAdapter:
    """牛子(wechat) 协议服务适配器"""
    
    def __init__(self, server_url: str, admin_key: str = None):
        self.server_url = server_url.rstrip('/')
        self.admin_key = admin_key
        self.sub_type: Optional[Literal["Niuzi", "WeChatPadPro", "iwechat"]] = None
    
    def _detect_sub_protocol(self) -> Literal["Niuzi", "WeChatPadPro", "iwechat"]:
        """检测牛子子协议类型"""
        if self.sub_type:
            return self.sub_type
            
        try:
            # 尝试 iwechat
            params = {}
            if self.admin_key:
                params["key"] = self.admin_key
            r = requests.get(f"{self.server_url}/admin/GetAuthKey", 
                           params=params, timeout=5)
            if r.status_code == 200:
                self.sub_type = "iwechat"
                return self.sub_type
                
            # 尝试 WeChatPadPro
            r = requests.get(f"{self.server_url}/admin/GetAllDevices",
                           params=params, timeout=5)
            if r.status_code == 200:
                self.sub_type = "WeChatPadPro"
                return self.sub_type
                
        except Exception:
            pass
            
        # 默认 Niuzi
        try:
            r = requests.get(f"{self.server_url}/api/v1/wx/user/status", timeout=5)
            if r.status_code == 200:
                self.sub_type = "Niuzi"
                return self.sub_type
        except Exception:
            pass
            
        self.sub_type = "Niuzi"
        return self.sub_type
    
    def health_check(self) -> bool:
        """健康检查"""
        try:
            r = requests.get(f"{self.server_url}/api/v1/wx/user/status", timeout=5)
            return r.status_code == 200
        except Exception:
            return False
    
    def get_accounts(self) -> List[Dict]:
        """获取在线账号列表"""
        sub_type = self._detect_sub_protocol()
        
        if sub_type == "Niuzi":
            return self._get_niuzi_accounts()
        elif sub_type == "WeChatPadPro":
            return self._get_padpro_accounts()
        elif sub_type == "iwechat":
            return self._get_iwechat_accounts()
        else:
            return []
    
    def _get_niuzi_accounts(self) -> List[Dict]:
        """牛子协议获取账号"""
        url = f"{self.server_url}/api/v1/wx/user/status"
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            result = r.json()
            
            if not result.get('status'):
                raise Exception(f"获取在线账号失败: {result.get('message', '未知错误')}")
            
            accounts_data = result.get('data', {})
            if not isinstance(accounts_data, dict):
                raise ValueError("API返回的数据格式错误")
            
            accounts = []
            for wxid, info in accounts_data.items():
                if (isinstance(info, dict) and 
                    'wxid' in info and 'nickname' in info and
                    info.get('survival') == 1):
                    accounts.append({
                        "wxid": info['wxid'],
                        "openid": info['wxid'],
                        "nickname": info.get('nickname'),
                        "alias": None,
                        "avatar": None,
                        "status": 1,
                        "loginState": 1,
                        "_ref": info['wxid'],
                    })
            return accounts
            
        except requests.RequestException as e:
            raise Exception(f"牛子获取账号列表失败: {e}")
    
    def _get_iwechat_accounts(self) -> List[Dict]:
        """iwechat获取账号"""
        url = f"{self.server_url}/admin/GetAuthKey"
        params = {"key": self.admin_key}
        try:
            r = requests.get(url, params=params, timeout=60)
            r.raise_for_status()
            auth_data = r.json()
            if not isinstance(auth_data, list):
                raise ValueError("响应格式错误")
            
            valid = []
            for acc in auth_data:
                if acc.get('status') == 1:
                    valid.append({
                        "wxid": acc.get('wx_id', ''),
                        "openid": acc.get('wx_id', ''),
                        "nickname": acc.get('nick_name'),
                        "alias": None,
                        "avatar": None,
                        "status": 1,
                        "loginState": 1,
                        "_ref": acc.get('license', '') or acc.get('authKey', ''),
                    })
            return valid
            
        except requests.RequestException as e:
            raise Exception(f"iwechat获取账号失败: {e}")
    
    def _get_padpro_accounts(self) -> List[Dict]:
        """WeChatPadPro获取账号"""
        url = f"{self.server_url}/admin/GetAllDevices"
        params = {"key": self.admin_key}
        try:
            r = requests.get(url, params=params, timeout=60)
            r.raise_for_status()
            data = r.json()
            
            # 兼容多种响应格式
            devices = []
            if isinstance(data, dict):
                if 'Data' in data and isinstance(data['Data'], dict):
                    devices = data['Data'].get('devices', [])
                elif 'data' in data:
                    devices = data['data']
                else:
                    devices = [data]
            elif isinstance(data, list):
                devices = data
            
            if not isinstance(devices, list):
                raise ValueError("响应格式错误")
            
            valid = []
            for acc in devices:
                if acc.get('status') == 1:
                    valid.append({
                        "wxid": acc.get('deviceId', ''),
                        "openid": acc.get('deviceId', ''),
                        "nickname": acc.get('deviceName'),
                        "alias": None,
                        "avatar": None,
                        "status": 1,
                        "loginState": 1,
                        "_ref": acc.get('license', '') or acc.get('authKey', ''),
                    })
            return valid
            
        except requests.RequestException as e:
            raise Exception(f"WeChatPadPro获取账号失败: {e}")
    
    def get_code(self, wxid_or_license: str, app_id: str) -> str:
        """获取小程序登录Code
        
        Args:
            wxid_or_license: 牛子=wxid, Padpro/iwechat=license
            app_id: 小程序AppID
        """
        sub_type = self._detect_sub_protocol()
        
        if sub_type == "Niuzi":
            return self._niuzi_get_code(wxid_or_license, app_id)
        else:
            return self._legacy_get_code(wxid_or_license, app_id)
    
    def _niuzi_get_code(self, wxid: str, app_id: str) -> str:
        """牛子协议获取code"""
        actual_wxid = str(wxid).split('#')[0].strip()
        endpoints = [
            "/api/v1/wx/app/get/code",
            "/api/v1/wx/app/get/code/",
            "/api/v1/wx/get/code",
            "/wx/app/get/code",
            "/api/wx/app/get/code",
        ]
        
        print(f"[牛子] 尝试获取code: wxid={actual_wxid}, appid={app_id}")
        
        last_error = None
        for endpoint in endpoints:
            url = f"{self.server_url}{endpoint}"
            payload = {"wxid": actual_wxid, "appid": app_id}
            
            try:
                print(f"[牛子] 请求: POST {url}")
                r = requests.post(url, json=payload, timeout=15)
                print(f"[牛子] 响应状态: {r.status_code}")
                
                if r.status_code == 404:
                    print(f"[牛子] ⚠ 端点不存在: {endpoint}")
                    continue
                
                # 防御性检查：解析 JSON，处理 null 响应
                try:
                    result = r.json() if r.text and r.text.strip() else {}
                except json.JSONDecodeError:
                    result = {}
                
                # 响应数据无效（null/非对象）
                if not result or not isinstance(result, dict):
                    print(f"[牛子] ⚠ 响应数据无效(非对象): {str(result)[:100]}")
                    continue
                
                # 提取code (多层级兼容)
                code = (result.get('code') or
                       (isinstance(result.get('data'), dict) and result['data'].get('code')) or
                       (isinstance(result.get('Data'), dict) and result['Data'].get('code')) or
                       (isinstance(result.get('data'), str) and result['data']) or
                       (isinstance(result.get('Data'), str) and result['Data']))
                
                if isinstance(code, str) and len(code) > 5:
                    return code
                    
                last_error = Exception(f"无有效code: {json.dumps(result, ensure_ascii=False)[:150]}")
                
            except requests.RequestException as e:
                print(f"[牛子] 请求失败({endpoint}): {e}")
                last_error = Exception(f"请求失败: {e}")
            except json.JSONDecodeError:
                last_error = Exception("响应格式错误")
        
        raise last_error or Exception("所有API端点均不可达或返回无效数据(404)")
    
    def _legacy_get_code(self, license: str, app_id: str) -> str:
        """传统协议(PadPro/iwechat)获取code"""
        url = f"{self.server_url}/applet/JsLogin"
        params = {"key": license}
        payload = {
            "AppId": app_id,
            "Data": "",
            "Opt": 1,
            "PackageName": "",
            "SdkName": ""
        }
        
        try:
            r = requests.post(url, params=params, json=payload, timeout=60)
            r.raise_for_status()
            result = r.json()
            
            if result.get('Code') != 200:
                raise Exception(f"获取code失败: {result.get('Text', '未知错误')}")
            
            data = result.get('Data', {})
            code = data.get('Code')
            if not code:
                raise Exception("响应中无Code字段")
            
            return code
            
        except requests.RequestException as e:
            raise Exception(f"传统协议请求失败: {e}")


# ============================================================
#  统一入口类
# ============================================================

class WeChatCodeGetter:
    """
    微信小程序Code获取模块（统一入口）
    自动检测或手动指定服务类型：
      - YYB: 应用宝(yyb_go) 服务
      - Wechat: 牛子协议服务
    """
    
    def __init__(self, force_type: ProtocolType = None):
        global _config_cache
        
        # 使用缓存的配置（避免重复初始化检测）
        if _config_cache and not force_type:
            self.__dict__.update(_config_cache)
            return
            
        # 环境变量读取
        env_server_type = os.getenv("SERVER_TYPE", "").lower()
        
        # 服务地址配置
        yyb_server = (os.getenv("YYB_SERVER") or 
                     os.getenv("YINGYOGBAO_SERVER") or 
                     "http://127.0.0.1:8000")
        
        wechat_server = (os.getenv("WECHAT_SERVER") or 
                        "http://192.168.6.222:8011")
        
        admin_key = os.getenv("ADMIN_KEY")
        wx_id_filter = os.getenv("WX_ID")
        
        script_dir = pathlib.Path(__file__).parent.absolute()
        env_check_file = script_dir / "env_check.json"
        
        # 确定协议类型
        if force_type:
            protocol_type = force_type
        elif env_server_type:
            protocol_type = {
                "yyb": "YYB",
                "yingyongbao": "YYB",  
                "应用宝": "YYB",
                "wechat": "Wechat",
                "niuzi": "Wechat",
                "牛子": "Wechat",
            }.get(env_server_type, "Unknown")
        elif env_check_file.exists():
            try:
                with open(env_check_file, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    protocol_type = saved.get("protocol_type", "Unknown")
            except Exception:
                protocol_type = "Unknown"
        else:
            protocol_type = "Unknown"
        
        # 自动检测
        if protocol_type == "Unknown":
            print("[getCode] 正在自动检测服务类型...")
            
            # 优先检测应用宝
            test_yyb = YYBAdapter(yyb_server)
            if test_yyb.health_check():
                protocol_type = "YYB"
                print(f"[getCode] ✓ 检测到 应用宝 服务: {yyb_server}")
            else:
                # 其次检测牛子
                test_wx = WechatAdapter(wechat_server, admin_key)
                if test_wx.health_check():
                    protocol_type = "Wechat"
                    print(f"[getCode] ✓ 检测到 牛子 服务: {wechat_server}")
                else:
                    print(f"[getCode] ✗ 未检测到可用服务")
                    print(f"[getCode]   应用宝({yyb_server}): 不可达")
                    print(f"[codegen]   牛子({wechat_server}): 不可达")
        
        # 初始化对应适配器
        self.protocol_type = protocol_type
        self.wx_id_filter = wx_id_filter
        
        if protocol_type == "YYB":
            self.adapter = YYBAdapter(yyb_server)
            self.server_url = yyb_server
        elif protocol_type == "Wechat":
            self.adapter = WechatAdapter(wechat_server, admin_key)
            self.server_url = wechat_server
        else:
            raise ValueError(
                "无法确定服务类型！请设置环境变量：\n"
                "  WECHAT_SERVER=http://你的牛子地址:端口\n"
                "  YYB_SERVER=http://你的应用宝地址:端口\n"
                "  或设置 SERVER_TYPE=wechat / SERVER_TYPE=yyb 强制指定"
            )
        
        # 处理 WX_ID 过滤
        self.target_wx_ids = []
        if wx_id_filter:
            self.target_wx_ids = [x.strip() for x in wx_id_filter.split('&') if x.strip()]
            print(f"[getCode] WX_ID筛选: {', '.join(self.target_wx_ids)}")
        
        # 保存检测结果到文件
        try:
            with open(env_check_file, 'w', encoding='utf-8') as f:
                json.dump({"protocol_type": protocol_type}, f, ensure_ascii=False)
        except Exception:
            pass
        
        print(f"[getCode] 当前服务: {protocol_type} @ {self.server_url}")
        
        # 缓存配置
        _config_cache = {
            "protocol_type": protocol_type,
            "adapter": self.adapter,
            "server_url": self.server_url,
            "wx_id_filter": wx_id_filter,
            "target_wx_ids": self.target_wx_ids,
        }
        self.__dict__.update(_config_cache)
    
    def _filter_accounts(self, accounts: List[Dict]) -> List[Dict]:
        """根据WX_ID过滤账号"""
        if not self.target_wx_ids:
            return accounts
        
        filtered = []
        for acc in accounts:
            ref = acc.get("_ref", "")
            wxid = acc.get("wxid", "")
            openid = acc.get("openid", "")
            
            if any(t in (ref, wxid, openid) for t in self.target_wx_ids):
                filtered.append(acc)
        
        if filtered:
            print(f"[getCode] 筛选后剩余 {len(filtered)} 个账号")
        else:
            print(f"[getCode] 警告：WX_ID筛选无匹配账号")
        
        return filtered
    
    def get_online_accounts(self) -> List[Tuple[Dict, Dict]]:
        """获取在线账号列表 [(account_info, login_status), ...]"""
        accounts = self.adapter.get_accounts()
        accounts = self._filter_accounts(accounts)
        
        online = []
        for acc in accounts:
            status = {
                "loginState": acc.get("loginState", 1),
                "onlineTime": acc.get("last_checked_at", 0),
                "device": acc.get("avatar", ""),
            }
            online.append((acc, status))
        
        return online
    
    def print_online_status(self):
        """打印在线状态"""
        online = self.get_online_accounts()
        print(f"\n当前有 {len(online)} 个账号在线 ({self.protocol_type})")
        
        for acc, status in online:
            name = (acc.get("nickname") or 
                   acc.get("alias") or 
                   acc.get("wxid", "未知")[:12])
            t = status.get("onlineTime", "?")
            print(f"  {name}  (上线时间: {t})")
    
    def get_applet_code(self, app_id: str, identifier: str) -> str:
        """为单个账号获取小程序Code（支持动态fallback）
        
        Args:
            app_id: 小程序AppID
            identifier: 
              - 牛子协议: wxid
              - 应用宝: id/uin/openid
              
        Returns:
            str: 登录code
        """
        # 先尝试主适配器
        try:
            return self.adapter.get_code(identifier, app_id)
        except Exception as primary_error:
            # 动态 fallback：如果主服务是牛子且失败，尝试应用宝
            if isinstance(self.adapter, WechatAdapter):
                yyb_server = (os.getenv("YYB_SERVER") or 
                             os.getenv("YINGYOGBAO_SERVER") or 
                             "http://127.0.0.1:8000")
                
                print(f"[getCode] ⚠ 牛子服务失败({primary_error})，动态尝试应用宝服务 @ {yyb_server}...")
                try:
                    dynamic_yyb = YYBAdapter(yyb_server)
                    if dynamic_yyb.health_check():
                        print(f"[getCode] ✓ 应用宝服务可用，切换获取code")
                        code = dynamic_yyb.get_code(identifier, app_id)
                        print(f"[getCode] ✓ 应用宝获取成功")
                        return code
                    else:
                        print(f"[getCode] ✗ 应用宝服务不可用")
                except Exception as dynamic_err:
                    print(f"[getCode] ✗ 应用宝动态请求失败: {dynamic_err}")
            
            raise primary_error
    
    def get_codes_for_all_online(self, app_id: str) -> Dict[str, str]:
        """为所有在线账号获取code
        
        Returns:
            {昵称: code, ...}
        """
        online = self.get_online_accounts()
        codes = {}
        
        for i, (acc, _) in enumerate(online, 1):
            # 确定显示名
            base_name = (acc.get("nickname") or 
                        acc.get("alias") or 
                        f"账号_{i}")
            
            if not base_name.strip() or base_name.strip() == '\u3164':
                wxid = acc.get("wxid", "")
                base_name = f"账号_{wxid[-6:]}" if wxid else f"账号_{i}"
            
            # 防重名
            name = base_name
            counter = 1
            while name in codes:
                name = f"{base_name}_{counter}"
                counter += 1
            
            ref = acc.get("_ref", "")
            if not ref:
                print(f"[getCode] {name}: 缺少标识符，跳过")
                continue
            
            try:
                code = self.adapter.get_code(ref, app_id)
                codes[name] = code
                print(f"[getCode] ✓ {name}: {code[:20]}...")
            except Exception as e:
                print(f"[getCode] ✗ {name}: {e}")
        
        return codes


# ============================================================
#  便捷函数（保持向后兼容）
# ============================================================

def get_wechat_codes(app_id: str) -> Dict[str, str]:
    """获取所有在线账号的code（便捷函数）"""
    getter = WeChatCodeGetter()
    return getter.get_codes_for_all_online(app_id)


def print_online_status():
    """打印在线状态（便捷函数）"""
    getter = WeChatCodeGetter()
    getter.print_online_status()


def get_single_code(app_id: str, identifier: str) -> str:
    """
    为指定账号获取单个code（便捷函数）
    
    Args:
        app_id: 小程序AppID
        identifier: 
          - 牛子: wxid
          - 应用宝: id/uin/openid
          
    Returns:
        str: 登录code
    """
    getter = WeChatCodeGetter()
    try:
        return getter.get_applet_code(app_id, identifier)
    except Exception as e:
        print(f"[getCode] 获取失败（可能需重新登录）: {e}")
        raise


# ============================================================
#  直接运行测试
# ============================================================

if __name__ == '__main__':
    import sys
    
    print("=" * 50)
    print("  微信小程序 Code 获取工具（双协议版）")
    print("=" * 50)
    
    # 测试参数
    TEST_APPID = sys.argv[1] if len(sys.argv) > 1 else input("请输入测试 AppID: ").strip()
    
    if not TEST_APPID:
        print("未提供 AppID，退出")
        sys.exit(1)
    
    # 初始化并打印状态
    try:
        getter = WeChatCodeGetter()
    except ValueError as e:
        print(f"\n❌ 错误: {e}")
        sys.exit(1)
    
    print("\n" + "-" * 40)
    
    # 打印在线状态
    getter.print_online_status()
    
    print("\n" + "-" * 40)
    print(f"开始获取 Code (AppID={TEST_APPID})...")
    
    # 获取所有账号的code
    codes = getter.get_codes_for_all_online(TEST_APPID)
    
    if codes:
        print(f"\n✓ 成功获取 {len(codes)} 个 Code:")
        for name, code in codes.items():
            print(f"  {name}: {code}")
    else:
        print("\n✗ 未获取到任何 Code")
