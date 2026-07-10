#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# cron "33 9,21 * * *"
"""
微信小程序登录Code获取模块（双协议支持）
支持两种服务：
  1) Wechat (牛子协议) - 微信iPad/iPhone协议服务
  2) YYBServer (应用宝) - yyb_go 微信扫码代理服务

环境变量：
    WECHAT_SERVER:  牛子协议服务地址（默认 http://192.168.6.222:8011）
    YYB_SERVER:     应用宝服务地址（默认 http://127.0.0.1:8000）

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
import time
import requests
import json
import re
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
        """健康检查（兼容多种响应格式）"""
        try:
            url = f"{self.server_url}/health"
            print(f"[YYB] 健康检查: {url}")
            r = requests.get(url, timeout=5)
            print(f"[YYB] 响应状态: {r.status_code}, body: {r.text[:100]}")
            
            if r.status_code != 200:
                return False
            
            data = r.json()
            # 兼容多种响应格式:
            # - YYB Go: { code: 0, msg: "success", data: { ok: true } }
            # - 其他: { ok: true }
            return (data.get("code") == 0 or 
                    (isinstance(data.get("data"), dict) and data["data"].get("ok") is True) or
                    data.get("ok") is True)
        except Exception as e:
            print(f"[YYB] 健康检查异常: {e}")
            return False
    
    def _get_account_list(self) -> List[Dict]:
        """获取并缓存账号列表"""
        now = time.time()
        if self._accounts_cache and (now - self._cache_time) < 300:
            return self._accounts_cache
        
        try:
            r = requests.get(f"{self.server_url}/accounts", timeout=15)
            data = r.json()
            if data.get("code") != 0 or not isinstance(data.get("data"), list):
                return []
            self._accounts_cache = data["data"]
            self._cache_time = now
            return self._accounts_cache
        except Exception as e:
            print(f"[YYB] 获取账号列表失败: {e}")
            return []
    
    def _resolve_ref(self, wxid_or_openid: str) -> str:
        """根据 wxid/openid 查找 YYB 数据库中的 ref (优先用 id)
        
        精确匹配 openid → 匹配 id → 模糊匹配 → 备注号选择 → 单账号自动使用
        """
        accounts = self._get_account_list()
        
        # 1. 精确匹配 openid
        for acc in accounts:
            if acc.get("openid") == wxid_or_openid:
                print(f"[YYB] 精确匹配: {wxid_or_openid} → id={acc.get('id')}, openid={acc.get('openid')}")
                return str(acc.get("id", ""))
        
        # 2. 匹配 id (数字)
        if re.match(r'^\d+$', str(wxid_or_openid)):
            for acc in accounts:
                if str(acc.get("id", "")) == str(wxid_or_openid):
                    print(f"[YYB] ID匹配: {wxid_or_openid} → id={acc.get('id')}, openid={acc.get('openid')}")
                    return str(acc.get("id", ""))
        
        # 3. 模糊匹配（部分包含）
        for acc in accounts:
            acc_openid = acc.get("openid", "") or ""
            if (acc_openid and wxid_or_openid in acc_openid) or \
               (wxid_or_openid and acc_openid in wxid_or_openid):
                print(f"[YYB] 模糊匹配: {wxid_or_openid} → id={acc.get('id')}, openid={acc_openid}")
                return str(acc.get("id", ""))
        
        # 打印可用账号帮助诊断
        if accounts:
            avail = ", ".join(f"{a.get('id')}:{a.get('openid', '')}" for a in accounts)
            print(f"[YYB] ⚠ 无法精确匹配 \"{wxid_or_openid}\"，可用账号: {avail}")
            
            # 尝试从原始输入中提取备注号 (#数字)，用于在多账号中选择
            note_match = re.search(r'#(\d+)$', str(wxid_or_openid))
            
            if note_match and len(accounts) >= int(note_match.group(1)):
                idx = int(note_match.group(1)) - 1  # 1-based index
                selected = accounts[idx]
                print(f"[YYB] 通过备注#{note_match.group(1)}选择: id={selected.get('id')}, openid={selected.get('openid')}")
                return str(selected.get("id", ""))
            
            if len(accounts) == 1:
                print(f"[YYB] 自动使用唯一可用账号: id={accounts[0].get('id')}, openid={accounts[0].get('openid')}")
                return str(accounts[0].get("id", ""))
            
            # 多个账号无法确定时，使用第一个并警告
            print(f"[YYB] ⚠ 多个账号无法确定目标，默认使用第1个账号: id={accounts[0].get('id')}")
            return str(accounts[0].get("id", ""))
        else:
            print(f"[YYB] ⚠ 无可用账号！请先在应用宝扫码登录")
        
        return wxid_or_openid

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
        
        # 先将 wxid/openid 转换为 YYB 数据库中的 ref（账号 ID）
        resolved_ref = self._resolve_ref(ref)
        
        payload = {
            "ref": resolved_ref,
            "app_id": app_id
        }
        
        headers = {"Content-Type": "application/json"}
        
        try:
            print(f"[YYB] 请求code: ref={resolved_ref}, app_id={app_id}")
            r = requests.post(url, json=payload, headers=headers, timeout=30)
            print(f"[YYB] 响应状态: {r.status_code}")
            
            if r.status_code == 404:
                err_msg = r.json().get("msg") or r.json().get("error", "") or r.text[:80]
                raise Exception(f"接口/账号不存在(404): {err_msg}")
            
            if r.status_code == 400:
                raise Exception(f"参数错误 - 可能账号不存在: {r.text[:100]}")
            
            if r.status_code == 409:
                raise Exception("账号login_buffer已过期，需要重新扫码登录")
            
            result = r.json()
            code_val = 0
            if isinstance(result, dict):
                code_val = result.get("code", -1)
                
            if code_val != 0:
                msg = result.get("msg", f"HTTP {r.status_code}")
                raise Exception(f"[{code_val}] {msg}")
            
            # 从 data.result.code 提取
            data = result.get("data", {})
            if not isinstance(data, dict):
                # YYB 新版格式可能直接返回 { openid, result: { code: "xxx" } }
                if isinstance(data, dict) and data.get("result", {}).get("code"):
                    return data["result"]["code"]
                raise Exception(f"响应data异常: {str(data)[:100]}")
                
            inner = data.get("result", {})
            if not isinstance(inner, dict):
                raise Exception(f"result异常: {str(inner)[:100]}")
                
            code = inner.get("code")
            if not code or not isinstance(code, str) or len(code) < 5:
                raise Exception(f"未拿到有效code: {json.dumps(result, ensure_ascii=False)[:150]}")
            
            return code
            
        except requests.RequestException as e:
            raise Exception(f"[YYB] 请求code失败: {e}")
        except json.JSONDecodeError:
            raise Exception("[YYB] code响应格式错误")


    def get_phone_number_code(self, ref: str, app_id: str) -> str:
        """获取手机号Code
        
        Args:
            ref: 账号标识 (id/uin/openid)
            app_id: 小程序AppID
            
        Returns:
            str: 手机号code
        """
        url = f"{self.server_url}/wxapp/getPhoneNumber"
        
        # 先将 wxid/openid 转换为 YYB 数据库中的 ref（账号 ID）
        resolved_ref = self._resolve_ref(ref)
        
        payload = {
            "ref": resolved_ref,
            "app_id": app_id
        }
        
        headers = {"Content-Type": "application/json"}
        
        try:
            print(f"[YYB] 请求手机号code: ref={resolved_ref}, app_id={app_id}")
            r = requests.post(url, json=payload, headers=headers, timeout=30)
            print(f"[YYB] 响应状态: {r.status_code}")
            
            if r.status_code == 404:
                err_msg = r.json().get("msg") or r.json().get("error", "") or r.text[:80]
                raise Exception(f"接口/账号不存在(404): {err_msg}")
            
            if r.status_code == 400:
                raise Exception(f"参数错误 - 可能账号不存在: {r.text[:100]}")
            
            if r.status_code == 409:
                raise Exception("账号login_buffer已过期，需要重新扫码登录")
            
            result = r.json()
            code_val = 0
            if isinstance(result, dict):
                code_val = result.get("code", -1)
                
            if code_val != 0:
                msg = result.get("msg", f"HTTP {r.status_code}")
                raise Exception(f"[{code_val}] {msg}")
            
            # 从 data.result.code 提取
            data = result.get("data", {})
            if not isinstance(data, dict):
                if isinstance(data, dict) and data.get("result", {}).get("code"):
                    return data["result"]["code"]
                raise Exception(f"响应data异常: {str(data)[:100]}")
                
            inner = data.get("result", {})
            if not isinstance(inner, dict):
                raise Exception(f"result异常: {str(inner)[:100]}")
                
            code = inner.get("code")
            if not code or not isinstance(code, str) or len(code) < 5:
                raise Exception(f"未拿到有效手机号code: {json.dumps(result, ensure_ascii=False)[:150]}")
            
            return code
            
        except requests.RequestException as e:
            raise Exception(f"[YYB] 请求手机号code失败: {e}")
        except json.JSONDecodeError:
            raise Exception("[YYB] 手机号code响应格式错误")


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
    微信小程序Code获取模块（统一入口 - 智能路由版）
    
    根据账号ID格式自动路由：
      - 应用宝 openid（含连字符/大写字母/以o开头的微信openid）→ 应用宝(YYB) 服务
      - 其余（含不以 wxid_ 开头的真实微信 wxid）→ 牛子(Wechat) 服务
    
    健康检查按需执行（仅检查目标协议），结果按协议分别缓存
    """
    
    def __init__(self, force_type: ProtocolType = None):
        # 服务地址配置
        self.yyb_server = (os.getenv("YYB_SERVER") or 
                           os.getenv("YINGYOGBAO_SERVER") or 
                           "http://127.0.0.1:8000")
        self.wechat_server = (os.getenv("WECHAT_SERVER") or 
                             "http://192.168.6.222:8011")
        self.admin_key = os.getenv("ADMIN_KEY")
        self.wx_id_filter = os.getenv("WX_ID")
        self.protocol_type = "Unknown"
        
        self.script_dir = pathlib.Path(__file__).parent.absolute()
        self.env_check_file = self.script_dir / "env_check.json"
        
        # 处理 WX_ID 过滤
        self.target_wx_ids = []
        if self.wx_id_filter:
            self.target_wx_ids = [x.strip() for x in self.wx_id_filter.split('&') if x.strip()]
            print(f"[getCode] WX_ID筛选: {', '.join(self.target_wx_ids)}")
        
        # 预解析每个ID的目标协议: 应用宝 openid → 应用宝, 其余(含不以 wxid_ 开头的真实微信 wxid) → 牛子
        self._id_protocol_map: Dict[str, str] = {}
        for id_entry in self.target_wx_ids:
            proto = 'yyb' if self._is_yyb_openid(id_entry) else 'wechat'
            self._id_protocol_map[id_entry] = proto
        
        # 健康检查缓存（按协议分别缓存）
        self._health_cache: Dict[str, Optional[bool]] = {}
        
        # 适配器实例（延迟创建）
        self.primary_adapter = None
        
        self._force_type = force_type
    
    def init(self):
        """初始化（延迟健康检查，按需执行）"""
        # 强制类型优先
        protocol_type = self._force_type
        
        if not protocol_type:
            env_type = (os.getenv("SERVER_TYPE") or "").lower()
            if env_type:
                protocol_type = {
                    "yyb": "YYB", "yingyongbao": "YYB", "应用宝": "YYB",
                    "wechat": "Wechat", "niuzi": "Wechat", "牛子": "Wechat",
                    "auto": "Auto",
                }.get(env_type, "Auto")
        
        # 默认 Auto 模式
        if not protocol_type or protocol_type == "Unknown":
            protocol_type = "Auto"
        
        if protocol_type == "Auto":
            self._init_auto_mode()
        elif protocol_type == "YYB":
            self.protocol_type = "YYB"
            self.primary_adapter = YYBAdapter(self.yyb_server)
            print(f"[getCode] 当前服务: YYB(应用宝) @ {self.yyb_server}")
        elif protocol_type == "Wechat":
            self.protocol_type = "Wechat"
            self.primary_adapter = WechatAdapter(self.wechat_server, self.admin_key)
            print(f"[getCode] 当前服务: Wechat(牛子) @ {self.wechat_server}")
        
        # 缓存检测结果到文件
        try:
            with open(self.env_check_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "protocol_type": self.protocol_type,
                }, f, ensure_ascii=False)
        except Exception:
            pass

    def _init_auto_mode(self):
        """初始化 Auto 模式（智能路由）
        
        健康检查延迟到 get_applet_code 首次调用时执行，
        只检查目标协议的服务是否可用。
        """
        self.protocol_type = "Auto(智能路由)"
        
        # primaryAdapter 保留给 get_online_accounts 使用（默认用牛子查在线列表）
        self.primary_adapter = WechatAdapter(self.wechat_server, self.admin_key)
        
        wechat_count = sum(1 for v in self._id_protocol_map.values() if v == 'wechat')
        yyb_count = sum(1 for v in self._id_protocol_map.values() if v == 'yyb')
        print(f"[getCode] 智能路由: 牛子账号×{wechat_count} + 应用宝账号×{yyb_count}, 延迟健康检查")
    
    def _is_yyb_openid(self, identifier: str) -> bool:
        """判断 identifier 是否为「应用宝 openid」格式。
        
        并非所有微信 wxid 都以 wxid_ 开头（旧号自定义微信号等），
        因此不能以“是否 wxid_ 开头”来判定微信账号。
        这里改为正向识别应用宝 openid，其余一律视为真实微信 wxid → 走牛子协议。
        """
        raw_id = str(identifier).split('#')[0].strip()
        if not raw_id:
            return False
        if raw_id.isdigit():
            return True
        if re.match(r'^o[a-zA-Z0-9_-]{20,}$', raw_id):
            return True
        return False

    def _detect_protocol_for_identifier(self, identifier: str) -> str:
        """根据 identifier 判断应该使用哪个协议
        
        应用宝 openid → yyb
        其余（含不以 wxid_ 开头的真实微信 wxid）→ wechat
        """
        raw_id = identifier.split('#')[0].strip()
        
        # 先查预解析的映射表（来自 WX_ID 环境变量）
        for id_entry, proto in self._id_protocol_map.items():
            if id_entry.split('#')[0].strip() == raw_id or id_entry == identifier:
                return proto
        
        # 兜底：根据格式推断
        return 'yyb' if self._is_yyb_openid(raw_id) else 'wechat'
    
    def get_applet_code(self, app_id: str, identifier: str) -> str:
        """获取单个账号的code（智能路由）
        
        - wxid_* 格式 → 直接走牛子
        - openid 格式 → 直接走应用宝
        - 只检查目标协议的健康状态，结果按协议缓存
        """
        target_protocol = self._detect_protocol_for_identifier(identifier)
        print(f"[getCode] 路由: {identifier} → {target_protocol}")
        
        # 按需健康检查：只检查目标协议的服务是否可用
        cache_key = f"hc_{target_protocol}"
        if cache_key not in self._health_cache:
            if target_protocol == 'yyb':
                ok = YYBAdapter(self.yyb_server).health_check()
                self._health_cache["hc_yyb"] = ok
            else:
                ok = WechatAdapter(self.wechat_server, self.admin_key).health_check()
                self._health_cache["hc_wechat"] = ok
            self._health_cache[cache_key] = ok
        
        is_healthy = self._health_cache.get(cache_key, False)
        
        # 选择适配器
        if target_protocol == 'yyb':
            adapter = YYBAdapter(self.yyb_server)
            name = '应用宝'
            svc_url = self.yyb_server
        else:
            adapter = WechatAdapter(self.wechat_server, self.admin_key)
            name = '牛子'
            svc_url = self.wechat_server
        
        # 目标服务不可用
        if not is_healthy:
            raise Exception(f"{name}服务不可用 ({svc_url})")
        
        try:
            code = adapter.get_code(identifier, app_id)
            print(f"[getCode] ✓ {name}获取成功")
            return code
        except Exception as e:
            print(f"[getCode] ⚠ {name}获取失败: {e}")
            raise
    
    def get_applet_phone_number(self, app_id: str, identifier: str) -> str:
        """获取单个账号的手机号Code（智能路由）
        
        - wxid_* 格式 → 直接走牛子（如果支持）
        - openid 格式 → 直接走应用宝
        - 只检查目标协议的健康状态，结果按协议缓存
        """
        target_protocol = self._detect_protocol_for_identifier(identifier)
        print(f"[getCode] 手机号路由: {identifier} → {target_protocol}")
        
        # 按需健康检查：只检查目标协议的服务是否可用
        cache_key = f"hc_{target_protocol}"
        if cache_key not in self._health_cache:
            if target_protocol == 'yyb':
                ok = YYBAdapter(self.yyb_server).health_check()
                self._health_cache["hc_yyb"] = ok
            else:
                ok = WechatAdapter(self.wechat_server, self.admin_key).health_check()
                self._health_cache["hc_wechat"] = ok
            self._health_cache[cache_key] = ok
        
        is_healthy = self._health_cache.get(cache_key, False)
        
        # 选择适配器
        if target_protocol == 'yyb':
            adapter = YYBAdapter(self.yyb_server)
            name = '应用宝'
            svc_url = self.yyb_server
        else:
            adapter = WechatAdapter(self.wechat_server, self.admin_key)
            name = '牛子'
            svc_url = self.wechat_server
        
        # 目标服务不可用
        if not is_healthy:
            raise Exception(f"{name}服务不可用 ({svc_url})")
        
        try:
            if target_protocol == 'yyb':
                code = adapter.get_phone_number_code(identifier, app_id)
            else:
                raise Exception(f"{name}(牛子协议暂不支持手机号code)")
            print(f"[getCode] ✓ {name}获取手机号成功")
            return code
        except Exception as e:
            print(f"[getCode] ⚠ {name}获取手机号失败: {e}")
            raise

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
        if not self.primary_adapter:
            raise Exception("未初始化，请先调用 init()")
        accounts = self.primary_adapter.get_accounts()
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
            print(f"  {name}")
    
    def get_codes_for_all_online(self, app_id: str) -> Dict[str, str]:
        """为所有在线账号获取code（使用智能路由）
        
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
                code = self.get_applet_code(app_id, ref)
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
    getter.init()
    return getter.get_codes_for_all_online(app_id)


def print_online_status():
    """打印在线状态（便捷函数）"""
    getter = WeChatCodeGetter()
    getter.init()
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
    getter.init()
    try:
        return getter.get_applet_code(app_id, identifier)
    except Exception as e:
        print(f"[getCode] 获取失败（可能需重新登录）: {e}")
        raise
    try:
        return getter.get_applet_code(app_id, identifier)
    except Exception as e:
        print(f"[getCode] 获取失败（可能需重新登录）: {e}")
        raise


def get_single_phone_number(app_id: str, identifier: str) -> str:
    """
    为指定账号获取手机号Code（便捷函数）
    
    Args:
        app_id: 小程序AppID
        identifier: 
          - 应用宝: id/uin/openid（目前仅YYB支持）
          
    Returns:
        str: 手机号code
    """
    getter = WeChatCodeGetter()
    getter.init()
    try:
        return getter.get_applet_phone_number(app_id, identifier)
    except Exception as e:
        print(f"[getCode] 获取手机号失败（可能需重新登录或账号不存在）: {e}")
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
