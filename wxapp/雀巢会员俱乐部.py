#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import yyb  # 自动同步 yyb_go 存活账号
# cron:52 8,16 * * *
"""
# name: 雀巢会员俱乐部
脚本名称：雀巢会员俱乐部
说明：
  通过 yyb.py 获取 code，再调用雀巢登录接口换 token 后执行签到。

环境变量：
  WX_ID           wxid 列表，格式：wxid#备注 或 备注#wxid，多个账号用换行、@或&分隔 (兼容 Nestle_wxid)
  WECHAT_SERVER   微信服务端地址（由 yyb.py 使用）
  PROXY_API       品赞代理提取链接，可选
  PROXY_TYPE      代理类型：http / socks5，默认：http
  IPZAN_CONFIG    品赞自动加白名单，可选，推荐格式：
                  套餐购买编号#登录密码#套餐提取密匙#签名秘钥#1
"""

import os
import sys
import asyncio
import json
import random
import re
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import parse_qsl

# 强制全局禁用所有系统代理环境变量
for env_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 
                'ALL_PROXY', 'all_proxy', 'NO_PROXY', 'no_proxy']:
    os.environ.pop(env_var, None)

try:
    import httpx
    from httpx import AsyncHTTPTransport
    from httpx_socks import AsyncProxyTransport
except ImportError:
    print("❌ 缺少依赖库，请执行：pip install httpx[http2] httpx-socks python-dotenv")
    sys.exit(1)

try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None

# ===================== 配置项 =====================
WECHAT_SERVER = (os.getenv("WX_SERVER") or os.getenv("WECHAT_SERVER") or os.getenv("YYB_SERVER") or "http://127.0.0.1:8000").strip().rstrip("/")
WXID_ENV = (
    os.getenv("WX_ID")
    or os.getenv("Nestlé_wxid")
    or os.getenv("Nestle_wxid")
    or os.getenv("NESTLE_WXID")
    or ""
).strip()

try:
    from notify import send as notify_send
except ImportError:
    def notify_send(title, content):
        print(f"--- 通知 ---\n{title}\n{content}\n-------------")

# 品赞代理配置（环境变量，可选）
PROXY_API = (os.getenv("PROXY_API") or os.getenv("UNICOM_PROXY_API", "")).strip()
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()
PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"
IPZAN_WHITELIST_CACHE: set[str] = set()
IPZAN_WHITELIST_NOOP_LOGGED = False

# 核心代理开关
ENABLE_PER_ACCOUNT_PROXY = True
PROXY_FETCH_INTERVAL = 3000
ENABLE_DIRECT_FALLBACK = True

# 固定配置
APPID = "wxc5db704249c9bb31"
APP_VERSION = "491"
XWEB_VERSION = "19823"
TOKEN_CLIENT_ID = "wechatMini"
TOKEN_CLIENT_SECRET = "secret"
TOKEN_GRANT_TYPE = "wechat_auth_code"
TOKEN_URL = "https://crm.nestlechinese.com/openapi/identityservice/connect/token"

# UA池
USER_AGENT_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/19823",
    f"Mozilla/5.0 (Linux; Android 14; 2512BPNDAC Build/UKQ1.230917.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.153 Mobile Safari/537.36 XWEB/{XWEB_VERSION} MMWEBSDK/20251006 MiniProgramEnv/android"
]

# 跳过的任务GUID
SKIP_TASK_GUIDS = {"38C8BBDA3DAE4CD685B270D939E5063D", "36EFECD2AD8C44278317ED567EB24DD9"}

# ===================== 工具函数 =====================
def sleep(ms: int) -> asyncio.Future:
    return asyncio.sleep(ms / 1000)

def random_int(min_val: int, max_val: int) -> int:
    return random.randint(min_val, max_val)

def get_ua() -> str:
    return random.choice(USER_AGENT_LIST)

def build_direct_transport() -> AsyncHTTPTransport:
    return AsyncHTTPTransport()

def mask_text(value: str) -> str:
    value = str(value or "")
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-6:]}"

def parse_accounts() -> List[Dict[str, str]]:
    if not WXID_ENV:
        print("❌ 未配置 WX_ID 环境变量")
        print("格式: wxid#备注，多个账号用换行、@或&分隔")
        return []

    accounts = []
    for raw_line in re.split(r"[\r\n@&]+", WXID_ENV):
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split("#", 1)
        if len(parts) == 1:
            wxid = parts[0].strip()
            remark = ""
        else:
            part_a, part_b = parts[0].strip(), parts[1].strip()
            if part_b.startswith("wxid_") and not part_a.startswith("wxid_"):
                wxid, remark = part_b, part_a
            else:
                wxid, remark = part_a, part_b

        if not wxid:
            continue

        accounts.append({
            "wxid": wxid,
            "remark": remark,
            "name": remark or wxid,
        })

    if not accounts:
        print("❌ 环境变量中未解析到有效账号")

    return accounts

def parse_ipzan_config() -> Dict[str, str]:
    raw = os.getenv("IPZAN_CONFIG", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            return {
                "no": str(data.get("no") or "").strip(),
                "password": str(data.get("password") or "").strip(),
                "fetchKey": str(data.get("fetchKey") or data.get("fetch_key") or "").strip(),
                "signKey": str(data.get("signKey") or data.get("sign_key") or "").strip(),
                "replace": str(data.get("replace", "1")).strip() or "1",
            }
        except Exception:
            pass

        if "=" in raw and "&" in raw:
            params = dict(parse_qsl(raw, keep_blank_values=True))
            return {
                "no": str(params.get("no") or "").strip(),
                "password": str(params.get("password") or "").strip(),
                "fetchKey": str(params.get("fetchKey") or params.get("fetch_key") or "").strip(),
                "signKey": str(params.get("signKey") or params.get("sign_key") or "").strip(),
                "replace": str(params.get("replace") or "1").strip() or "1",
            }

        parts = [item.strip() for item in re.split(r"[#|&]", raw)]
        return {
            "no": parts[0] if len(parts) > 0 else "",
            "password": parts[1] if len(parts) > 1 else "",
            "fetchKey": parts[2] if len(parts) > 2 else "",
            "signKey": parts[3] if len(parts) > 3 else "",
            "replace": parts[4] if len(parts) > 4 and parts[4] else "1",
        }

    return {
        "no": str(os.getenv("IPZAN_NO", "")).strip(),
        "password": str(os.getenv("IPZAN_PASSWORD", "")).strip(),
        "fetchKey": str(os.getenv("IPZAN_FETCH_KEY", "")).strip(),
        "signKey": str(os.getenv("IPZAN_SIGN_KEY", "")).strip(),
        "replace": str(os.getenv("IPZAN_REPLACE", "1")).strip() or "1",
    }

IPZAN_SETTINGS = parse_ipzan_config()

def is_ipzan_whitelist_config_ready() -> bool:
    return bool(
        IPZAN_SETTINGS["no"]
        and IPZAN_SETTINGS["password"]
        and IPZAN_SETTINGS["fetchKey"]
        and IPZAN_SETTINGS["signKey"]
    )

def is_valid_proxy_host(host: str) -> bool:
    host = str(host or "").strip()
    if not host:
        return False

    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        return all(0 <= int(part) <= 255 for part in host.split("."))

    return bool(re.fullmatch(r"[a-zA-Z0-9.-]+", host))

def extract_ipv4(text: str) -> str:
    match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", str(text or ""))
    if not match:
        return ""
    ip = match.group(0)
    return ip if is_valid_proxy_host(ip) else ""

def pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    padding = block_size - len(data) % block_size
    return data + bytes([padding]) * padding

def build_ipzan_sign(timestamp: int) -> str:
    if AES is None:
        raise RuntimeError("缺少 pycryptodome，无法生成品赞白名单签名")

    key_bytes = IPZAN_SETTINGS["signKey"].encode("utf-8")
    if len(key_bytes) not in (16, 24, 32):
        raise ValueError(
            f"品赞签名秘钥长度无效，当前为 {len(key_bytes)} 字节，仅支持 16/24/32 字节"
        )

    plain = f"{IPZAN_SETTINGS['password']}:{IPZAN_SETTINGS['fetchKey']}:{timestamp}".encode("utf-8")
    cipher = AES.new(key_bytes, AES.MODE_ECB)
    return cipher.encrypt(pkcs7_pad(plain)).hex()

async def add_ipzan_whitelist(ip: str) -> bool:
    if not is_valid_proxy_host(ip):
        print(f"⚠️ [白名单] 无法识别待添加 IP: {ip or '-'}")
        return False

    if ip in IPZAN_WHITELIST_CACHE:
        print(f"ℹ️ [白名单] {ip} 本次运行已尝试添加，等待代理生效")
        return True

    if not is_ipzan_whitelist_config_ready():
        print("⚠️ [白名单] 未配置有效 IPZAN_CONFIG，无法自动加白")
        return False

    try:
        timestamp = int(time.time())
        sign = build_ipzan_sign(timestamp)
    except Exception as exc:
        print(f"❌ [白名单] 生成签名失败: {exc}")
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0, transport=build_direct_transport()) as client:
            response = await client.post(
                "https://service.ipzan.com/whiteList-add",
                json={
                    "no": IPZAN_SETTINGS["no"],
                    "ip": ip,
                    "sign": sign,
                    "replace": IPZAN_SETTINGS["replace"] or "1",
                },
            )

        try:
            data = response.json()
        except Exception:
            data = {"message": response.text}

        message = data.get("message") or data.get("msg") or json.dumps(data, ensure_ascii=False)
        success = bool(
            data.get("code") == 0
            or data.get("success") is True
            or re.search(r"成功|success|已在白名单|已存在", message, re.I)
        )

        if success:
            IPZAN_WHITELIST_CACHE.add(ip)
            print(f"✅ [白名单] {ip} 添加成功")
            return True

        print(f"⚠️ [白名单] {ip} 添加失败: {message}")
    except Exception as exc:
        print(f"❌ [白名单] {ip} 添加异常: {exc}")

    return False

def parse_ipzan_whitelist_error(raw_text: Any) -> Optional[Dict[str, str]]:
    text = str(raw_text or "").strip()
    if not text:
        return None

    message = text
    try:
        data = json.loads(text)
        message = str(data.get("message") or data.get("msg") or text).strip()
    except Exception:
        pass

    if not re.search(r"白名单|whitelist", message, re.I):
        if not re.search(r"白名单|whitelist", text, re.I):
            return None
        message = text

    ip = extract_ipv4(message or text)
    if not ip:
        return None

    return {
        "ip": ip,
        "message": message,
    }

# ===================== 品赞代理系统 =====================
def parse_proxy_response(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if not text:
        return None

    try:
        data = json.loads(text)
        proxy_obj = None
        if data.get("data") and isinstance(data["data"], list) and len(data["data"]) > 0:
            proxy_obj = data["data"][0]
        elif data.get("ip") and data.get("port"):
            proxy_obj = data
        elif data.get("result") and data["result"].get("ip") and data["result"].get("port"):
            proxy_obj = data["result"]

        if proxy_obj:
            return {
                "host": proxy_obj["ip"],
                "port": int(proxy_obj["port"]),
                "username": proxy_obj.get("user") or proxy_obj.get("username") or "",
                "password": proxy_obj.get("pass") or proxy_obj.get("password") or ""
            }
    except json.JSONDecodeError:
        if ":" in text:
            parts = text.split(":")
            if len(parts) >= 2:
                return {
                    "host": parts[0],
                    "port": int(parts[1]),
                    "username": parts[2] if len(parts) >= 3 else "",
                    "password": parts[3] if len(parts) >= 4 else ""
                }
    return None

async def validate_proxy(proxy_info: Dict[str, Any]) -> bool:
    if not proxy_info:
        return False
    
    try:
        transport = build_proxy_transport(proxy_info)
        async with httpx.AsyncClient(transport=transport, timeout=15.0) as client:
            response = await client.get(PROXY_VALIDATE_URL)
            if response.status_code == 200:
                ip = response.json().get("origin", "未知")
                print(f"✅ 代理验证通过 | 出口IP: {ip}")
                return True
    except Exception as e:
        print(f"⚠️ 代理验证失败 | 原因: {str(e)}")
    return False

def build_proxy_transport(proxy_info: Dict[str, Any]) -> Optional[AsyncProxyTransport]:
    if not proxy_info:
        return None
    
    host = proxy_info["host"]
    port = proxy_info["port"]
    username = proxy_info["username"]
    password = proxy_info["password"]

    try:
        if PROXY_TYPE == "socks5":
            proxy_url = f"socks5://{username}:{password}@{host}:{port}" if username and password else f"socks5://{host}:{port}"
        else:
            proxy_url = f"http://{username}:{password}@{host}:{port}" if username and password else f"http://{host}:{port}"
        
        return AsyncProxyTransport.from_url(proxy_url)
    except Exception as e:
        print(f"❌ 代理生成失败 | 原因: {str(e)}")
        return None

async def get_valid_proxy(account_name: str) -> Optional[Dict[str, Any]]:
    global IPZAN_WHITELIST_NOOP_LOGGED

    if not PROXY_API:
        print(f"ℹ️ [{account_name}] 未配置代理 | 使用直连模式")
        return None

    print(f"🔌 [{account_name}] 正在获取专属代理...")
    whitelist_handled_ips: set[str] = set()
    whitelist_triggered = False

    for i in range(PROXY_RETRY_TIMES):
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=build_direct_transport()) as client:
                response = await client.get(PROXY_API)
            proxy_info = parse_proxy_response(response.text)
            
            if not proxy_info:
                raw_text = response.text.strip()
                whitelist_info = parse_ipzan_whitelist_error(raw_text)
                if whitelist_info and whitelist_info.get("ip"):
                    whitelist_triggered = True
                    print(f"⚠️ [{account_name}] 检测到品赞白名单限制: {whitelist_info['message']}")
                    ip = whitelist_info["ip"]
                    if ip not in whitelist_handled_ips:
                        whitelist_handled_ips.add(ip)
                        if await add_ipzan_whitelist(ip):
                            print(f"🔄 [{account_name}] 等待2秒后重新提取代理")
                            await sleep(2000)
                            continue

                if raw_text:
                    print(f"⚠️ [{account_name}] 第{i+1}次获取代理失败 | {raw_text[:120]}")
                else:
                    print(f"⚠️ [{account_name}] 第{i+1}次获取代理失败 | 响应为空")
                continue

            if is_ipzan_whitelist_config_ready() and not whitelist_triggered and not IPZAN_WHITELIST_NOOP_LOGGED:
                IPZAN_WHITELIST_NOOP_LOGGED = True
                print("ℹ️ [白名单] 当前服务器IP已在品赞白名单中，无需自动加白")

            if await validate_proxy(proxy_info):
                return proxy_info
            else:
                print(f"⚠️ [{account_name}] 第{i+1}次代理不可用 | 重试中...")
        
        except Exception as e:
            print(f"⚠️ [{account_name}] 第{i+1}次获取代理异常 | 原因: {str(e)}")
        
        if i < PROXY_RETRY_TIMES - 1:
            await sleep(2000)

    print(f"❌ [{account_name}] 代理获取失败 | 切换直连模式")
    return None

# ===================== 通知推送函数 =====================
async def send_notification(title: str, content: str) -> None:
    try:
        result = notify_send(title, content)
        if asyncio.iscoroutine(result):
            await result
        print("✅ 已调用通知系统推送消息")
    except Exception as exc:
        print(f"❌ 推送失败 | 原因: {exc}")

# ===================== 核心业务类 =====================
class QueChaoBot:
    def __init__(self, account: Dict[str, str], proxy_info: Optional[Dict[str, Any]] = None):
        self.account = account
        self.wxid = account.get("wxid", "").strip()
        self.server = account.get("name") or account.get("remark") or self.wxid or "未命名账号"
        self.proxy_info = proxy_info
        self.base_url = "https://crm.nestlechinese.com"
        self.token = None
        self.ua = get_ua()
        self.client = None

    async def get_code(self) -> Optional[str]:
        """通过微信服务端按 wxid 获取动态 code。"""
        if not self.wxid:
            print(f"❌ [{self.server}] 未提供有效 wxid")
            return None

        print(f"🔐 [{self.server}] 请求获取 code | wxid: {mask_text(self.wxid)}")
        
        try:
            code = await asyncio.to_thread(get_single_code, APPID, self.wxid)
            if not code:
                print(f"❌ [{self.server}] 获取 code 失败")
                return None
                
            code_preview = str(code)[:8] + "..."
            print(f"✅ [{self.server}] 获取 code 成功 | 预览: {code_preview}")
            return str(code)
            
        except Exception as e:
            print(f"❌ [{self.server}] 获取 code 异常 | 原因: {str(e)}")
            return None

    async def get_token_by_code(self, code: str) -> Optional[str]:
        """通过code换取token（简洁日志）"""
        print(f"🔑 [{self.server}] 正在换取token...")
        
        headers = {
            "Host": "crm.nestlechinese.com",
            "Connection": "keep-alive",
            "User-Agent": self.ua,
            "xweb_xhr": "1",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": f"https://servicewechat.com/{APPID}/{APP_VERSION}/page-frame.html",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }
        
        form_data = {
            "client_id": TOKEN_CLIENT_ID,
            "client_secret": TOKEN_CLIENT_SECRET,
            "grant_type": TOKEN_GRANT_TYPE,
            "auth_code": code
        }

        try:
            transport = build_proxy_transport(self.proxy_info) if self.proxy_info else build_direct_transport()
            mode = "代理" if self.proxy_info else "直连"
            
            async with httpx.AsyncClient(
                transport=transport, 
                headers=headers, 
                timeout=20.0, 
                http2=True
            ) as client:
                response = await client.post(TOKEN_URL, data=form_data)
            
            if response.status_code != 200:
                raise Exception(f"HTTP错误: {response.status_code}")
            
            res = response.json()
            if res.get("access_token") and res.get("token_type", "Bearer").lower() == "bearer":
                self.token = res["access_token"]
                print(f"✅ [{self.server}] 获取token成功 | 模式: {mode}")
                return self.token
            else:
                raise Exception(f"业务错误: {res.get('error', '未知错误')}")
        except Exception as e:
            print(f"⚠️ [{self.server}] {mode}获取token失败 | 原因: {str(e)}")
            
            if self.proxy_info and ENABLE_DIRECT_FALLBACK:
                print(f"🌐 [{self.server}] 切换直连重试...")
                try:
                    async with httpx.AsyncClient(
                        headers=headers, 
                        timeout=20.0, 
                        http2=True, 
                        transport=build_direct_transport()
                    ) as client:
                        response = await client.post(TOKEN_URL, data=form_data)
                    
                    res = response.json()
                    if res.get("access_token"):
                        self.token = res["access_token"]
                        print(f"✅ [{self.server}] 直连获取token成功")
                        return self.token
                    else:
                        raise Exception(f"直连业务错误: {res.get('error', '未知错误')}")
                except Exception as e2:
                    print(f"❌ [{self.server}] 直连获取token失败 | 原因: {str(e2)}")
        
        return None

    async def __aenter__(self):
        transport = build_proxy_transport(self.proxy_info) if self.proxy_info else build_direct_transport()
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._get_base_headers(),
            transport=transport,
            http2=True,
            timeout=30.0
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    def _get_base_headers(self) -> Dict[str, str]:
        headers = {
            "Host": "crm.nestlechinese.com",
            "displayVersion": "0",
            "User-Agent": self.ua,
            "xweb_xhr": "1",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Referer": f"https://servicewechat.com/{APPID}/{APP_VERSION}/page-frame.html",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }
        
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        
        return headers

    def check_response(self, response_data: Dict[str, Any]) -> bool:
        if response_data.get("errcode") != 200:
            print(f"❌ [{self.server}] 请求失败 | 原因: {response_data.get('errmsg', '未知错误')}")
            return False
        return True

    async def get_user_balance(self) -> Optional[int]:
        try:
            response = await self.client.post(
                "/openapi/pointsservice/api/Points/getuserbalance",
                content="{}"
            )
            response_data = response.json()
            
            if self.check_response(response_data):
                return response_data.get("data")
            return None
        except Exception as e:
            print(f"❌ [{self.server}] 获取积分失败 | 原因: {str(e)}")
            return None

    async def daily_sign(self) -> Tuple[bool, str]:
        try:
            response = await self.client.post(
                "/openapi/activityservice/api/sign2025/sign",
                content='{"rule_id":1,"goods_rule_id":1}'
            )
            response_data = response.json()
            
            if response_data.get("errcode") == 201:
                sign_msg = "今日已签到"
                print(f"ℹ️ [{self.server}] {sign_msg}")
                return True, sign_msg
                
            if self.check_response(response_data):
                data = response_data.get("data", {})
                sign_day = data.get("sign_day", 0)
                sign_points = data.get("sign_points", 0)
                sign_msg = f"签到成功 | 连续{sign_day}天 | +{sign_points}积分"
                print(f"✅ [{self.server}] {sign_msg}")
                return True, sign_msg
            else:
                sign_msg = f"签到失败: {response_data.get('errmsg', '未知错误')}"
                print(f"❌ [{self.server}] {sign_msg}")
                return False, sign_msg
                
        except Exception as e:
            sign_msg = f"签到异常: {str(e)}"
            print(f"❌ [{self.server}] {sign_msg}")
            return False, sign_msg

    async def get_task_list(self) -> List[Dict[str, Any]]:
        try:
            response = await self.client.post(
                "/openapi/activityservice/api/task/getlist",
                content="{}"
            )
            response_data = response.json()
            
            if self.check_response(response_data):
                tasks = response_data.get("data", [])
                uncompleted_tasks = [
                    task for task in tasks 
                    if task.get("task_status") == 0 
                    and task.get("task_guid") not in SKIP_TASK_GUIDS
                ]
                print(f"📋 [{self.server}] 待完成任务: {len(uncompleted_tasks)}个")
                return uncompleted_tasks
            return []
        except Exception as e:
            print(f"❌ [{self.server}] 获取任务列表失败 | 原因: {str(e)}")
            return []

    async def complete_task(self, task_guid: str, task_desc: str) -> Tuple[bool, str]:
        try:
            response = await self.client.post(
                "/openapi/activityservice/api/task/add",
                content=f'{{"task_guid":"{task_guid}"}}'
            )
            response_data = response.json()
            
            if self.check_response(response_data):
                msg = f"完成【{task_desc}】 | +2积分"
                print(f"✅ [{self.server}] {msg}")
                return True, msg
            else:
                msg = f"【{task_desc}】失败: {response_data.get('errmsg', '未知错误')}"
                print(f"❌ [{self.server}] {msg}")
                return False, msg
                
        except Exception as e:
            msg = f"【{task_desc}】异常: {str(e)}"
            print(f"❌ [{self.server}] {msg}")
            return False, msg

    async def run(self) -> Dict[str, Any]:
        result = {
            "server": self.server,
            "success": False,
            "proxy_status": "直连" if not self.proxy_info else "专属代理",
            "sign_msg": "",
            "task_msgs": [],
            "initial_score": 0,
            "final_score": 0,
            "gained_score": 0,
            "error": ""
        }

        print(f"\n{'='*40}")
        print(f"[{self.server}] 开始执行任务")
        print(f"{'='*40}")

        try:
            await sleep(random_int(2000, 5000))

            # 1. 获取code（关键日志已优化）
            code = await self.get_code()
            if not code:
                result["error"] = "获取code失败"
                return result

            # 2. 获取token
            token = await self.get_token_by_code(code)
            if not token:
                result["error"] = "获取token失败"
                return result

            # 3. 执行业务
            async with self:
                initial_balance = await self.get_user_balance()
                if initial_balance is None:
                    result["error"] = "获取初始积分失败"
                    return result
                
                result["initial_score"] = initial_balance
                print(f"💰 [{self.server}] 初始积分: {initial_balance}")

                # 每日签到
                sign_success, sign_msg = await self.daily_sign()
                result["sign_msg"] = sign_msg
                await sleep(1000)

                # 完成日常任务
                tasks = await self.get_task_list()
                task_msgs = []
                for task in tasks:
                    task_guid = task.get("task_guid", "")
                    task_desc = task.get("task_sub_desc", task.get("task_title", "未知任务"))
                    if task_guid:
                        success, msg = await self.complete_task(task_guid, task_desc)
                        task_msgs.append(msg)
                        await sleep(1000)
                result["task_msgs"] = task_msgs

                # 获取最终积分
                final_balance = await self.get_user_balance()
                if final_balance is not None:
                    result["final_score"] = final_balance
                    result["gained_score"] = final_balance - initial_balance
                    print(f"📊 [{self.server}] 今日新增: {result['gained_score']}积分 | 当前: {final_balance}")
                
                result["success"] = True
                print(f"✅ [{self.server}] 任务执行完成")

        except Exception as e:
            result["error"] = str(e)
            print(f"❌ [{self.server}] 执行异常 | 原因: {str(e)}")

        return result

# ===================== 主程序 =====================
async def main():
    accounts = parse_accounts()
    if not accounts:
        return

    print('===== 雀巢会员俱乐部每日任务 =====\n')
    print(f"📅 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔌 待执行账号: {len(accounts)} 个")
    print(f"🌐 代理模式: {'单账号独立代理' if ENABLE_PER_ACCOUNT_PROXY else '全局共用代理'}\n")

    if PROXY_API and is_ipzan_whitelist_config_ready():
        print(f"ℹ️ [白名单] 已启用品赞自动加白，套餐编号: {mask_text(IPZAN_SETTINGS['no'])}")
        print(f"ℹ️ [白名单] 自动替换模式: {IPZAN_SETTINGS['replace'] or '1'}")
    elif PROXY_API and os.getenv("IPZAN_CONFIG", "").strip():
        print("ℹ️ [白名单] 检测到 IPZAN_CONFIG，但配置不完整，白名单提示时将仅走直连")
    
    global_proxy_info = None
    if not ENABLE_PER_ACCOUNT_PROXY and PROXY_API:
        global_proxy_info = await get_valid_proxy("全局共用")

    results = []
    for index, account in enumerate(accounts):
        account_name = account.get("name") or account.get("remark") or account.get("wxid", "")
        proxy_info = global_proxy_info
        if ENABLE_PER_ACCOUNT_PROXY and PROXY_API:
            proxy_info = await get_valid_proxy(account_name)
            await sleep(PROXY_FETCH_INTERVAL)
        
        bot = QueChaoBot(account, proxy_info)
        result = await bot.run()
        results.append(result)
        
        if index < len(accounts) - 1:
            print(f"\n⏳ 等待2秒后执行下一个账号...")
            await sleep(2000)

    # 汇总结果
    notify_content = "### 雀巢每日任务执行结果\n"
    for res in results:
        notify_content += f"\n#### {res['server']}\n"
        notify_content += f"- 代理状态：{res['proxy_status']}\n"
        notify_content += f"- 执行状态：{'成功' if res['success'] else '失败'}\n"
        if res['success']:
            notify_content += f"- 签到结果：{res['sign_msg']}\n"
            notify_content += f"- 任务完成：{'; '.join(res['task_msgs']) if res['task_msgs'] else '无未完成任务'}\n"
            notify_content += f"- 初始积分：{res['initial_score']}\n"
            notify_content += f"- 最终积分：{res['final_score']}\n"
            notify_content += f"- 今日新增：{res['gained_score']} 积分\n"
        else:
            notify_content += f"- 失败原因：{res['error']}\n"

    await send_notification("雀巢每日任务完成", notify_content)
    
    print('\n' + '='*40)
    print('🎉 所有账号执行完成')
    print(f"📊 成功: {sum(1 for r in results if r['success'])}/{len(results)} 个")
    print(f"💰 今日总新增: {sum(r['gained_score'] for r in results if r['success'])} 积分")
    print('='*40)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ 用户中断执行")
    except Exception as e:
        print(f"\n❌ 程序异常: {str(e)}")