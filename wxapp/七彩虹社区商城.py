import yyb  # 自动同步 yyb_go 存活账号
# cron: 40 06,18 * * *# 1 环境变量 WX_SERVER 填 yyb_go 服务地址（例如：http://127.0.0.1:8000）
# name: 七彩虹社区商城
# 2 环境变量 WX_ID（可选，默认自动拉取 yyb_go 上所有存活账号，支持 wxid#备注 白名单过滤）
#    多账号支持使用换行或 @ 分隔，例如：
#    wxid_xxx#主号@wxid_yyy#小号

import argparse
import base64
import hashlib
import json
import os
import random
import re
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

import requests

# 通知模块
try:
    import notify
except ImportError:
    print("未找到 notify.py，将仅在控制台输出日志。")
    class notify:
        @staticmethod
        def send(title, content):
            print(f"--- 通知 ---\n{title}\n{content}\n-------------")


# 这里是脚本默认配置。
# 如果当前目录存在 colorful_config.json，会用配置文件覆盖这里的默认值。
默认配置 = {
    "接口基础地址": "https://interface.skycolorful.com",
    "小程序AppId": "wx49018277e65fc3e1",
    "接口AppId": "815d8026-9a52-4445-a42c-a5443134232e",
    "接口AppSecret": "2b5c01fb-7640-401a-8188-43a13190a626",
    "请求超时秒": 20,
    "会话文件": "colorful_session.json",
    "优先使用缓存令牌": True,
    "登录成功后保存会话": False,
    "论坛模块ID": "09539c50-6de2-4a0c-adc8-535e488a419e",
    "资料生日起始年份": 1980,
    "资料生日结束年份": 2005,
    "随机等待秒": [10, 15],
    "启用自动完善资料": True,
    "启用自动发帖": False,
    "启用自动评论": False,
    "启用自动点赞": True,
    "点赞次数": 5,
    "点赞最大翻页": 5,
    "评论次数": 3,
    "启用抽奖": False,
    "抽奖积分上限": 200,
}


兜底文案 = [
    "生活不会辜负每一个认真前进的人。",
    "把普通的日子过得浪漫一点，就是本事。",
    "今天也要保持热爱，奔赴下一场山海。",
    "慢一点没关系，重要的是别停下。",
    "愿你眼里有光，手里有活，心里有梦。",
]


def 深度更新(原字典, 新字典):
    for 键, 值 in 新字典.items():
        if isinstance(值, dict) and isinstance(原字典.get(键), dict):
            深度更新(原字典[键], 值)
        else:
            原字典[键] = 值
    return 原字典


def 读取配置(配置文件路径):
    配置 = json.loads(json.dumps(默认配置))
    配置文件 = Path(配置文件路径)
    if not 配置文件.exists():
        内容 = {}
    else:
        内容 = json.loads(配置文件.read_text(encoding="utf-8"))
        if not isinstance(内容, dict):
            raise ValueError("配置文件必须是 JSON 对象。")

    配置 = 深度更新(配置, 内容)

    环境变量中转服务 = (os.getenv("WX_SERVER") or os.getenv("WECHAT_SERVER") or "").strip()
    if 环境变量中转服务:
        配置["中转服务器"] = 环境变量中转服务

    if not (配置.get("中转服务器") or "").strip():
        raise ValueError(
            "未检测到中转服务地址。请设置环境变量 WECHAT_SERVER，"
            '或在配置文件中提供「中转服务器」。'
        )

    return 配置


def 生成安全文件名(名称):
    名称 = (名称 or "").strip()
    名称 = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", 名称)
    名称 = 名称.strip(" ._")
    return 名称 or "account"


def 生成账号会话文件路径(基础会话文件, 微信ID, 备注):
    基础路径 = Path(基础会话文件)
    账号标识 = 生成安全文件名(备注 or 微信ID)
    短哈希 = hashlib.md5(微信ID.encode("utf-8")).hexdigest()[:8]
    文件名 = f"{基础路径.stem}_{账号标识}_{短哈希}{基础路径.suffix or '.json'}"
    return str(基础路径.with_name(文件名))


def 解析环境变量账号列表():
    原始值 = os.getenv("WX_ID") or ""
    原始值 = 原始值.strip()
    if not 原始值:
        # 未配置 WX_ID 时，自动从 yyb_go 拉取存活账号
        自动账号 = resolve_accounts()
        if 自动账号:
            原始值 = "\n".join(自动账号)
        else:
            raise ValueError(
                '未检测到环境变量 WX_ID。请按「wxid#备注」格式设置，'
                "多账号可用换行或 @ 分隔。"
            )

    账号列表 = []
    条目列表 = [条目.strip() for 条目 in re.split(r"[\r\n@]+", 原始值) if 条目.strip()]
    for 条目 in 条目列表:
        if "#" in 条目:
            微信ID, 备注 = 条目.split("#", 1)
        else:
            微信ID, 备注 = 条目, ""

        微信ID = 微信ID.strip()
        备注 = 备注.strip()
        if not 微信ID:
            continue

        账号列表.append(
            {
                "微信ID": 微信ID,
                "账号名称": 备注 or 微信ID,
            }
        )

    if not 账号列表:
        raise ValueError(
            "环境变量 colorful_wxid 解析后没有得到有效账号。"
        )

    return 账号列表


def 脱敏(文本, 前缀长度=12, 后缀长度=8):
    if not 文本:
        return "N/A"
    if len(文本) <= 前缀长度 + 后缀长度:
        return 文本
    return f"{文本[:前缀长度]}...{文本[-后缀长度:]}"


def 脱敏手机号(手机号):
    """隐藏手机号中间4位"""
    if not 手机号 or len(手机号) != 11:
        return 手机号 or "N/A"
    return f"{手机号[:3]}****{手机号[-4:]}"


class 七彩虹商城客户端:
    def __init__(self, 配置):
        self.配置 = 配置
        self.账号名称 = 配置["账号名称"]
        self.中转服务器 = 配置["中转服务器"].rstrip("/")
        self.接口基础地址 = 配置["接口基础地址"].rstrip("/")
        self.微信ID = 配置["微信ID"]
        self.小程序AppId = 配置["小程序AppId"]
        self.接口AppId = 配置["接口AppId"]
        self.接口AppSecret = 配置["接口AppSecret"]
        self.接口AppSecret请求头值 = base64.b64encode(
            self.接口AppSecret.encode("utf-8")
        ).decode("ascii")
        self.请求超时秒 = int(配置["请求超时秒"])
        self.会话文件 = Path(配置["会话文件"])

        self.session = requests.Session()
        self.access_token = ""
        self.refresh_token = ""
        self.open_id = ""
        self.phone = ""
        self.phone_code = ""
        self.user_info = {}

        self.已执行资料完善 = False
        self.已执行发帖 = False
        self.已执行评论 = False
        self.已执行点赞 = False

    def 打印(self, 内容=""):
        print(f"[{self.账号名称}] {内容}")

    def 分割线(self, 标题):
        print("\n" + "=" * 60)
        print(f"{标题}")
        print("=" * 60)

    @staticmethod
    def 紧凑JSON(对象):
        return json.dumps(对象, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def MD5(文本):
        return hashlib.md5(文本.encode("utf-8")).hexdigest()

    @staticmethod
    def 是应用宝账号(标识):
        原始标识 = str(标识 or "").split("#", 1)[0].strip()
        if re.match(r"^wxid_", 原始标识, re.I):
            return False
        if re.match(r"^[a-z][a-z0-9]{10,25}$", 原始标识):
            return False
        return True

    @staticmethod
    def 结果码(结果):
        if not isinstance(结果, dict):
            return None
        return 结果.get("Code", 结果.get("code"))

    @staticmethod
    def 结果消息(结果):
        if not isinstance(结果, dict):
            return ""
        return 结果.get("Message", 结果.get("message", ""))

    @staticmethod
    def 解析JSON字符串(值, 默认值=None):
        if 默认值 is None:
            默认值 = {}
        if isinstance(值, dict):
            return 值
        if isinstance(值, str):
            try:
                return json.loads(值)
            except json.JSONDecodeError:
                return 默认值
        return 默认值

    # 七彩虹接口每次请求都要带动态签名，这里按前端真实逻辑生成。
    def 生成签名请求头(self):
        ticks = int(time.time() * 1000)
        request_id = str(uuid.uuid4())
        签名原文 = "".join(
            [
                self.紧凑JSON({"AppId": self.接口AppId}),
                self.紧凑JSON({"Ticks": ticks}),
                self.紧凑JSON({"requestId": request_id}),
                self.紧凑JSON({"AppSecret": self.接口AppSecret}),
            ]
        )

        return {
            "AppId": self.接口AppId,
            "Ticks": str(ticks),
            "AppSecret": self.接口AppSecret请求头值,
            "requestId": request_id,
            "Sign": self.MD5(签名原文),
        }

    def 生成接口请求头(self, 带鉴权=True):
        请求头 = {
            "Host": "interface.skycolorful.com",
            "Connection": "keep-alive",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36 "
                "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
                "MiniProgramEnv/Windows WindowsWechat/WMPF "
                "WindowsWechat(0x63090a1b)XWEB/14185"
            ),
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/json",
            "version": "2.0.0",
            "User-from": "xcx",
            "source": "Wx",
            "xweb_xhr": "1",
            "UcSource": "30",
            "Referer": f"https://servicewechat.com/{self.小程序AppId}/89/page-frame.html",
            "Authorization": f"Bearer {self.access_token}" if 带鉴权 and self.access_token else "",
            "X-Authorization": (
                f"Bearer {self.refresh_token}" if 带鉴权 and self.refresh_token else ""
            ),
        }
        请求头.update(self.生成签名请求头())
        return 请求头

    def 解析响应(self, 响应):
        文本 = 响应.text.strip()
        if not 文本:
            return {
                "Code": 响应.status_code,
                "Message": "响应体为空",
                "Success": 响应.ok,
            }

        try:
            return 响应.json()
        except ValueError:
            return {
                "Code": 响应.status_code,
                "Message": "响应不是 JSON",
                "Success": False,
                "RawText": 文本,
            }

    def 从响应头更新令牌(self, 响应):
        access_token = 响应.headers.get("access-token") or 响应.headers.get("Access-Token")
        refresh_token = 响应.headers.get("x-access-token") or 响应.headers.get("x-Access-Token")
        if access_token:
            self.access_token = access_token
        if refresh_token:
            self.refresh_token = refresh_token

    def 请求接口(self, method, path, body=None, params=None, 带鉴权=True):
        url = f"{self.接口基础地址}/api{path}"
        headers = self.生成接口请求头(带鉴权=带鉴权)
        kwargs = {
            "headers": headers,
            "timeout": self.请求超时秒,
        }
        if params:
            kwargs["params"] = params
        if method.upper() != "GET":
            kwargs["data"] = self.紧凑JSON(body or {})

        try:
            响应 = self.session.request(method.upper(), url, **kwargs)
        except requests.RequestException as 异常:
            return {"Code": -1, "Message": f"请求异常: {异常}", "Success": False}

        self.从响应头更新令牌(响应)
        结果 = self.解析响应(响应)

        if 响应.status_code in (400, 401):
            if self.结果码(结果) in (None, 0):
                结果["Code"] = 401
                结果.setdefault("Message", "未授权或请求无效")

        return 结果

    def 请求中转服务(self, path, payload):
        url = f"{self.中转服务器}{path}"
        try:
            响应 = requests.post(
                url,
                json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=self.请求超时秒,
            )
        except requests.RequestException as 异常:
            return {"Code": -1, "Message": f"中转服务请求失败: {异常}", "status": False}

        return self.解析响应(响应)

    def 保存会话(self):
        if not self.配置.get("登录成功后保存会话", True):
            return

        数据 = {
            "账号名称": self.账号名称,
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "phone": self.phone,
            "open_id": self.open_id,
            "phone_code": self.phone_code,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "user_info": self.user_info,
            "decrypt_phone_request_body": {
                "OpenId": self.open_id,
                "Code": self.phone_code,
            },
        }
        self.会话文件.write_text(
            json.dumps(数据, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.打印(f"会话已保存到 {self.会话文件}")

    def 读取缓存会话(self):
        if not self.会话文件.exists():
            return False
        try:
            数据 = json.loads(self.会话文件.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        self.phone = 数据.get("phone", "")
        self.open_id = 数据.get("open_id", "")
        self.phone_code = 数据.get("phone_code", "")
        self.access_token = 数据.get("access_token", "")
        self.refresh_token = 数据.get("refresh_token", "")
        self.user_info = 数据.get("user_info", {}) or {}
        return bool(self.access_token and self.refresh_token)

    def 获取手机号信息(self):
        self.打印("[1/4] 获取手机号信息...")
        try:
            res = get_single_phone_encrypted(self.小程序AppId, self.微信ID)
            phone = res.get("mobile", "") if res else ""
            encrypted_data = res.get("encryptedData", "") if res else ""
            iv = res.get("iv", "") if res else ""
            code = res.get("code", "") if res else ""
            if not code:
                code = get_single_phone_number(self.小程序AppId, self.微信ID) or ""
            if code or phone:
                self.phone = phone
                self.phone_code = code
                if phone:
                    self.打印(f"    手机号: {脱敏手机号(phone)}")
                if code:
                    self.打印(f"    手机号 code: {脱敏(code, 24, 6)}")
                return {
                    "phone": phone,
                    "code": code,
                    "encrypted_data": encrypted_data,
                    "iv": iv,
                }
        except Exception as 异常:
            self.打印(f"    获取手机号信息异常: {异常}")
        self.打印("    获取手机号信息失败")
        return None

    def 获取微信授权码(self):
        """通过 yyb.py 统一接口获取微信 login code"""
        self.打印("[2/4] 获取微信授权码...")
        try:
            code = get_single_code(self.小程序AppId, self.微信ID)
        except Exception as e:
            self.打印(f"    获取微信授权码异常: {e}")
            return None

        if not code:
            self.打印(f"    中转服务没有返回微信授权码")
            return None

        self.打印(f"    授权码: {code}")
        return code

    def 用微信授权码换取OpenId(self, 微信授权码):
        self.打印("[3/4] 用 wx.login 授权码换取 OpenId...")
        结果 = self.请求接口("POST", "/User/OnLogin", body={"Code": 微信授权码}, 带鉴权=False)
        if self.结果码(结果) != 0:
            self.打印(f"    OnLogin 失败: {结果}")
            return None

        open_id = (结果.get("Data") or {}).get("OpenId", "")
        if not open_id:
            self.打印(f"    OnLogin 成功但没有 OpenId: {结果}")
            return None

        self.open_id = open_id
        self.打印(f"    OpenId: {open_id}")
        return open_id

    def 用手机号code换取Token(self, open_id, phone_code):
        self.打印("[4/4] 用手机号 code 换取 Token...")
        body = {"OpenId": open_id, "Code": phone_code}
        结果 = self.请求接口("POST", "/User/DecryptPhoneNumber", body=body, 带鉴权=False)
        if self.结果码(结果) != 0:
            self.打印(f"    DecryptPhoneNumber 失败: {结果}")
            return None

        data = 结果.get("Data") or {}
        access_token = data.get("Token", "")
        refresh_token = data.get("RefreshToken", "")
        if not access_token or not refresh_token:
            self.打印(f"    DecryptPhoneNumber 成功但没有返回完整令牌: {结果}")
            return None

        self.access_token = access_token
        self.refresh_token = refresh_token

        self.打印(f"    Access Token: {脱敏(access_token)}")
        self.打印(f"    Refresh Token: {脱敏(refresh_token)}")
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

    def 获取用户信息(self):
        结果 = self.请求接口("GET", "/User/GetUserInfo")
        if self.结果码(结果) != 0:
            return None
        self.user_info = 结果.get("Data") or {}
        return self.user_info

    def 确认缓存令牌是否可用(self):
        if not self.access_token or not self.refresh_token:
            return False
        self.打印("检测到本地缓存令牌，先尝试校验...")
        user_info = self.获取用户信息()
        if not user_info:
            self.打印("    缓存令牌已失效，将重新登录。")
            return False
        self.打印("    缓存令牌有效，可直接复用。")
        return True

    # 登录链路分 4 步：
    # 1. 中转服务拿手机号信息
    # 2. 中转服务拿 wx.login 授权码
    # 3. OnLogin 换取 OpenId
    # 4. DecryptPhoneNumber 换取业务 Token
    def 执行完整登录流程(self):
        self.分割线("七彩虹商城 登录流程")
        手机号信息 = self.获取手机号信息()
        if not 手机号信息:
            return False

        微信授权码 = self.获取微信授权码()
        if not 微信授权码:
            return False

        open_id = self.用微信授权码换取OpenId(微信授权码)
        if not open_id:
            return False

        token结果 = self.用手机号code换取Token(open_id, 手机号信息["code"])
        if not token结果:
            return False

        user_info = self.获取用户信息()
        if not user_info:
            self.打印("    登录成功，但获取用户信息失败。")
            return False

        self.打印(f"[校验] 用户昵称: {user_info.get('NickName', 'N/A')}")
        self.打印(f"[校验] 手机号: {脱敏手机号(user_info.get('Mobile'))}")
        self.保存会话()
        return True

    def 确保已登录(self, 强制重新登录=False):
        if (
            not 强制重新登录
            and self.配置.get("优先使用缓存令牌", True)
            and self.读取缓存会话()
            and self.确认缓存令牌是否可用()
        ):
            return True

        return self.执行完整登录流程()

    def 随机等待(self):
        下限, 上限 = self.配置.get("随机等待秒", [10, 15])
        秒数 = random.randint(int(下限), int(上限))
        self.打印(f"随机等待 {秒数} 秒，模拟正常操作节奏...")
        time.sleep(秒数)

    def 刷新登录时效(self):
        候选参数 = []
        if self.user_info.get("Mobile"):
            候选参数.append(("手机号", self.user_info["Mobile"]))
        if self.user_info.get("Id"):
            候选参数.append(("用户ID", self.user_info["Id"]))

        if not 候选参数:
            self.打印("没有可用的刷新登录参数，跳过 RefreshLoginTime。")
            return None

        for 参数类型, 参数值 in 候选参数:
            结果 = self.请求接口("POST", "/User/RefreshLoginTime", body={"phone": 参数值})
            if self.结果码(结果) == 0:
                self.打印(f"刷新登录时效成功，参数来源: {参数类型}")
                return 结果
            self.打印(f"刷新登录时效失败，参数来源 {参数类型}: {结果}")

        return None

    def 获取积分配置(self):
        return self.请求接口("GET", "/Sys/GetPointConfig")

    def 获取签到日历(self):
        return self.请求接口("GET", "/User/SignDaysV2")

    def 获取签到状态(self):
        return self.请求接口("GET", "/User/IsSignV2")

    def 执行签到V2(self):
        return self.请求接口("POST", "/User/SignV2", body={})

    def 执行社区签到V1(self):
        return self.请求接口("POST", "/User/Sign", body={})

    # 这里优先走当前小程序实际使用的 SignV2 接口，
    # 同时在签到前后把状态再读一遍，便于观察执行结果。
    def 执行签到流程(self):
        self.分割线("签到任务")

        签到前 = self.获取签到日历()
        if self.结果码(签到前) == 0:
            今日状态 = False
            for 项 in (签到前.get("Data") or {}).get("DataList", []):
                if 项.get("Num") == 1:
                    今日状态 = bool(项.get("Status"))
                    break
            self.打印(f"签到前，今日是否已签到: {'是' if 今日状态 else '否'}")

        签到结果 = self.执行签到V2()
        self.打印(
            f"签到V2结果: code={self.结果码(签到结果)} "
            f"message={self.结果消息(签到结果) or '无'}"
        )

        状态结果 = self.获取签到状态()
        if self.结果码(状态结果) == 0:
            数据 = 状态结果.get("Data") or {}
            self.打印(
                f"签到后状态: IsSign={数据.get('IsSign')} Point={数据.get('Point')}"
            )

        return 签到结果

    def 获取随机生日(self):
        起始年份 = int(self.配置["资料生日起始年份"])
        结束年份 = int(self.配置["资料生日结束年份"])
        起始日期 = date(起始年份, 1, 1)
        结束日期 = date(结束年份, 12, 31)
        间隔天数 = (结束日期 - 起始日期).days
        随机日期 = 起始日期 + timedelta(days=random.randint(0, 间隔天数))
        return 随机日期.strftime("%Y-%m-%d")

    def 自动完善资料(self):
        if self.已执行资料完善:
            return None
        self.已执行资料完善 = True

        昵称 = self.user_info.get("NickName", "七彩虹用户")
        生日 = self.获取随机生日()
        payload = {
            "Birthday": 生日,
            "Nickname": 昵称,
            "Sex": 1,
        }
        self.打印(f"开始执行资料完善，随机生日: {生日}")
        结果 = self.请求接口("POST", "/User/DoEditInfo", body=payload)
        self.打印(
            f"资料完善结果: code={self.结果码(结果)} message={self.结果消息(结果) or '无'}"
        )
        return 结果

    def 获取一言文案(self):
        try:
            响应 = requests.get(
                "https://v1.hitokoto.cn/?c=a&c=b&c=c&c=d&c=e&c=f&c=i&c=j&c=k&c=l&min_length=5",
                timeout=10,
            )
            数据 = 响应.json()
            文案 = 数据.get("hitokoto", "").strip()
            if 文案:
                return 文案
        except Exception:
            pass
        return random.choice(兜底文案)

    def 获取帖子列表(self, page=1, size=20):
        params = {
            "page": page,
            "size": size,
            "moduleId": self.配置["论坛模块ID"],
            "phone": "",
        }
        return self.请求接口("GET", "/Bbs/GetPostingList", params=params)

    def 自动发帖(self):
        if self.已执行发帖:
            return None
        self.已执行发帖 = True

        文案 = self.获取一言文案()
        payload = {
            "ModuleId": self.配置["论坛模块ID"],
            "Phone": self.user_info.get("Mobile", ""),
            "Title": "签到",
            "Content": 文案,
            "Pictures": [],
            "Source": 30,
        }
        self.打印(f"开始自动发帖，内容: {文案}")
        结果 = self.请求接口("POST", "/Bbs/Posting", body=payload)
        self.打印(
            f"自动发帖结果: code={self.结果码(结果)} message={self.结果消息(结果) or '无'}"
        )
        return 结果

    def 自动评论(self, 评论次数):
        if self.已执行评论:
            return None
        self.已执行评论 = True

        帖子结果 = self.获取帖子列表()
        帖子列表 = ((帖子结果.get("Data") or {}).get("DataList") or []) if isinstance(帖子结果, dict) else []
        if not 帖子列表:
            self.打印("没有可评论的帖子，跳过自动评论。")
            return None

        成功次数 = 0
        for 索引 in range(int(评论次数)):
            帖子 = random.choice(帖子列表)
            文案 = self.获取一言文案()
            payload = {
                "PostId": 帖子.get("Id", ""),
                "ReplyId": "",
                "ParentReplyId": "",
                "Phone": self.user_info.get("Mobile", ""),
                "Content": 文案,
                "Pictures": [],
            }
            结果 = self.请求接口("POST", "/Bbs/PostReply", body=payload)
            if self.结果码(结果) == 0:
                成功次数 += 1
                self.打印(f"第 {索引 + 1}/{评论次数} 次评论成功")
            else:
                self.打印(f"第 {索引 + 1}/{评论次数} 次评论失败: {结果}")
            if 索引 != int(评论次数) - 1:
                self.随机等待()

        return 成功次数

    def 自动点赞(self, 点赞次数):
        if self.已执行点赞:
            return None
        self.已执行点赞 = True

        目标次数 = int(点赞次数)
        最大翻页 = int(self.配置.get("点赞最大翻页", 5))
        成功次数 = 0
        已尝试帖子 = set()
        当前页 = 1

        while 成功次数 < 目标次数 and 当前页 <= 最大翻页:
            帖子结果 = self.获取帖子列表(page=当前页)
            帖子列表 = ((帖子结果.get("Data") or {}).get("DataList") or []) if isinstance(帖子结果, dict) else []
            if not 帖子列表:
                if 当前页 == 1:
                    self.打印("没有可点赞的帖子，跳过自动点赞。")
                else:
                    self.打印(f"第 {当前页} 页无更多帖子，结束点赞。")
                break

            for 帖子 in 帖子列表:
                if 成功次数 >= 目标次数:
                    break

                帖子ID = 帖子.get("Id") or ""
                if not 帖子ID or 帖子ID in 已尝试帖子:
                    continue
                # 已点赞过的帖子直接跳过，避免浪费请求
                if 帖子.get("IsLike") is True:
                    continue
                已尝试帖子.add(帖子ID)

                if 成功次数:
                    self.随机等待()

                标题 = str(帖子.get("Title") or "无标题")[:20]
                结果 = self.请求接口("POST", "/Bbs/Like", body={
                    "postId": 帖子ID,
                    "postReplyId": "0",
                })
                if self.结果码(结果) == 0:
                    成功次数 += 1
                    self.打印(f"第 {成功次数}/{目标次数} 次点赞成功: {标题}")
                    continue

                消息 = str(self.结果消息(结果) or 结果)
                # 重复点赞不计入失败，换下一个帖子继续
                if re.search(r"已点赞|已经|重复|不能", 消息):
                    continue
                self.打印(f"点赞失败: {消息}")

            当前页 += 1

        if 成功次数 >= 目标次数:
            self.打印(f"今日点赞已达上限 {目标次数} 次，获得 {目标次数 * 2} 积分")
        else:
            self.打印(f"本轮共点赞 {成功次数} 次，获得 {成功次数 * 2} 积分")

        return 成功次数

    def 获取活动列表(self):
        params = {"Page": 1, "Limit": 20}
        return self.请求接口("GET", "/Activity/GetPageList", params=params)

    def 获取抽奖详情(self, activity_key):
        params = {"Key": activity_key}
        return self.请求接口("GET", "/LuckyDraw/GetLuckyDraw", params=params)

    def 执行抽奖(self, activity_key):
        return self.请求接口("POST", "/LuckyDraw/Do", body={"key": activity_key})

    # 抽奖默认关闭，只在配置里显式打开时执行。
    # 同时会按照"抽奖积分上限"做保护，避免高消耗活动被误跑。
    def 自动抽奖(self):
        self.分割线("积分抽奖")

        活动结果 = self.获取活动列表()
        活动列表 = ((活动结果.get("Data") or {}).get("DataList") or []) if isinstance(活动结果, dict) else []
        if not 活动列表:
            self.打印("没有获取到可用活动，跳过抽奖。")
            return

        for 活动 in 活动列表:
            活动名 = 活动.get("Name", "未知活动")
            self.打印(
                f"检查活动: {活动名} | 状态={活动.get('StatusDescription')} | 类型={活动.get('TypeDescription')}"
            )
            if 活动.get("Type") != 1 or 活动.get("Status") != 1:
                continue

            抽奖详情 = self.获取抽奖详情(活动.get("ActivityKey", ""))
            if self.结果码(抽奖详情) != 0:
                self.打印(f"获取抽奖详情失败: {抽奖详情}")
                continue

            详情数据 = 抽奖详情.get("Data") or {}
            抽奖数据 = 详情数据.get("LuckyDraw") or {}
            消耗积分 = 抽奖数据.get("Expend", 0) or 0
            剩余次数 = 详情数据.get("ResidueCount", 0) or 0

            if 消耗积分 > int(self.配置["抽奖积分上限"]):
                self.打印(f"活动 {活动名} 单次消耗 {消耗积分} 积分，超过阈值，已跳过。")
                continue

            if 剩余次数 <= 0:
                self.打印(f"活动 {活动名} 当前没有剩余抽奖次数。")
                continue

            for 次数 in range(剩余次数):
                结果 = self.执行抽奖(活动.get("ActivityKey", ""))
                if self.结果码(结果) == 0:
                    奖品名 = ((结果.get("Data") or {}).get("Name")) or "未知奖品"
                    self.打印(f"第 {次数 + 1}/{剩余次数} 次抽奖成功，获得: {奖品名}")
                else:
                    self.打印(f"第 {次数 + 1}/{剩余次数} 次抽奖失败: {结果}")
                time.sleep(2)

    def 打印用户摘要(self):
        self.分割线("当前账号信息")
        self.打印(f"昵称: {self.user_info.get('NickName', 'N/A')}")
        self.打印(f"手机号: {脱敏手机号(self.user_info.get('Mobile'))}")
        self.打印(f"用户ID: {self.user_info.get('Id', 'N/A')}")
        self.打印(f"当前积分: {self.user_info.get('Point', 'N/A')}")
        self.打印(f"当前成长值: {self.user_info.get('Growth', 'N/A')}")
        self.打印(f"Access Token: {脱敏(self.access_token)}")
        self.打印(f"Refresh Token: {脱敏(self.refresh_token)}")

    # 这里把 JS 脚本里的积分任务逻辑合并到 Python 中。
    # 默认只开启相对稳妥的动作，发帖/评论/抽奖通过开关控制。
    def 执行商城任务(self):
        积分配置 = self.获取积分配置()
        if self.结果码(积分配置) != 0:
            self.打印(f"获取积分配置失败: {积分配置}")
            return

        数据 = 积分配置.get("Data") or {}
        shop_list = 数据.get("ShopList") or []
        daily_task_outs = 数据.get("DailyTaskOuts") or []

        self.分割线("积分任务配置")
        for 任务 in shop_list:
            self.打印(
                f"商城任务: {任务.get('Name')} | {任务.get('Title')} | 当前状态: {任务.get('Status')}"
            )
        for 任务 in daily_task_outs:
            self.打印(
                f"客户端任务: {任务.get('Title')} | 奖励={任务.get('RewardNum')} | 已领取={任务.get('IsGet')}"
            )

        for 任务 in shop_list:
            名称 = 任务.get("Name", "")

            if 名称 == "会员注册":
                self.打印("会员注册奖励属于首登奖励，当前脚本只做展示。")
                continue

            if 名称 == "会员信息完善":
                if self.配置.get("启用自动完善资料", True):
                    self.自动完善资料()
                else:
                    self.打印("已关闭自动完善资料，跳过。")
                continue

            if 名称 == "每日签到":
                self.打印("每日签到已在签到流程中处理。")
                continue

            if 名称 == "社区帖子点赞":
                if self.配置.get("启用自动点赞", True):
                    self.自动点赞(self.配置.get("点赞次数", 5))
                else:
                    self.打印("已关闭自动点赞，跳过。")
                continue

            self.打印(f'暂未针对任务「{名称}」编写自动执行逻辑。')

        if self.配置.get("启用自动发帖", False):
            self.分割线("补充社区发帖任务")
            self.自动发帖()

        if self.配置.get("启用自动评论", False):
            self.分割线("补充社区评论任务")
            self.自动评论(self.配置.get("评论次数", 3))

        if self.配置.get("启用自动点赞", True) and not self.已执行点赞:
            self.分割线("补充社区点赞任务")
            self.自动点赞(self.配置.get("点赞次数", 5))

    def 运行(self, 仅登录=False):
        if not self.确保已登录():
            self.打印("登录失败，任务执行终止。")
            return False

        self.打印用户摘要()

        if 仅登录:
            self.打印("仅登录模式已完成。")
            return True

        self.刷新登录时效()
        self.执行签到流程()
        self.执行商城任务()

        if self.配置.get("启用抽奖", False):
            self.自动抽奖()
        else:
            self.打印("抽奖功能当前关闭，如需启用请修改配置。")

        最新用户信息 = self.获取用户信息()
        if 最新用户信息:
            self.分割线("任务执行结果")
            self.打印(f"最终积分: {最新用户信息.get('Point', 'N/A')}")
            self.打印(f"最终成长值: {最新用户信息.get('Growth', 'N/A')}")
            self.保存会话()
        else:
            self.打印("任务结束后重新获取用户信息失败。")

        return True


def 发送青龙通知(标题, 内容):
    """调用青龙面板的 notify.py 发送通知"""
    try:
        notify.send(标题, 内容)
        return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(
        description=(
            "七彩虹社区商城 脚本。"
            "登录账号从环境变量 WX_ID 读取，"
            "格式为 wxid#备注，多账号支持换行或 @ 分隔。"
            "中转服务地址从环境变量 WECHAT_SERVER 读取。"
        )
    )
    parser.add_argument(
        "--config",
        default="colorful_config.json",
        help="配置文件路径，默认读取当前目录下的 colorful_config.json",
    )
    parser.add_argument(
        "--only-login",
        action="store_true",
        help="只执行登录和账号校验，不执行后续任务",
    )
    parser.add_argument(
        "--force-login",
        action="store_true",
        help="忽略本地缓存会话，强制重新登录",
    )
    parser.add_argument(
        "--enable-lottery",
        action="store_true",
        help="临时开启抽奖，无需修改配置文件",
    )
    args = parser.parse_args()

    try:
        基础配置 = 读取配置(args.config)
        if args.enable_lottery:
            基础配置["启用抽奖"] = True

        账号列表 = 解析环境变量账号列表()
    except ValueError as 异常:
        print(f"配置错误: {异常}")
        raise SystemExit(1)

    print("=" * 60)
    print(f"共解析到 {len(账号列表)} 个账号")
    print("=" * 60)
    for 索引, 账号 in enumerate(账号列表, start=1):
        print(f"{索引}. {账号['账号名称']} -> {账号['微信ID']}")

    结果列表 = []
    详细结果 = []
    for 索引, 账号 in enumerate(账号列表, start=1):
        print("\n" + "#" * 60)
        print(f"开始执行第 {索引}/{len(账号列表)} 个账号: {账号['账号名称']}")
        print("#" * 60)

        当前配置 = json.loads(json.dumps(基础配置))
        当前配置["微信ID"] = 账号["微信ID"]
        当前配置["账号名称"] = 账号["账号名称"]
        if 当前配置.get("优先使用缓存令牌", True) or 当前配置.get(
            "登录成功后保存会话", False
        ):
            当前配置["会话文件"] = 生成账号会话文件路径(
                基础配置["会话文件"],
                账号["微信ID"],
                账号["账号名称"],
            )

        客户端 = 七彩虹商城客户端(当前配置)
        if args.force_login:
            客户端.配置["优先使用缓存令牌"] = False

        成功 = 客户端.运行(仅登录=args.only_login)
        结果列表.append((账号["账号名称"], 成功))
        
        # 记录详细结果
        if 客户端.user_info:
            详细结果.append({
                "名称": 账号["账号名称"],
                "昵称": 客户端.user_info.get("NickName", "N/A"),
                "手机号": 脱敏手机号(客户端.user_info.get("Mobile")),
                "积分": 客户端.user_info.get("Point", "N/A"),
                "成长值": 客户端.user_info.get("Growth", "N/A"),
                "状态": "成功" if 成功 else "失败"
            })
        else:
            详细结果.append({
                "名称": 账号["账号名称"],
                "昵称": "N/A",
                "手机号": "N/A",
                "积分": "N/A",
                "成长值": "N/A",
                "状态": "成功" if 成功 else "失败"
            })

    print("\n" + "=" * 60)
    print("账号执行汇总")
    print("=" * 60)
    存在失败 = False
    成功数 = 0
    for 账号名称, 成功 in 结果列表:
        状态 = "成功" if 成功 else "失败"
        print(f"{账号名称}: {状态}")
        if 成功:
            成功数 += 1
        else:
            存在失败 = True

    # 构建通知内容
    通知标题 = f"七彩虹商城任务完成"
    通知内容 = f"执行结果: {成功数}/{len(账号列表)} 成功\n\n"
    for 结果 in 详细结果:
        通知内容 += f"【{结果['名称']}】\n"
        通知内容 += f"  昵称: {结果['昵称']}\n"
        通知内容 += f"  手机号: {结果['手机号']}\n"
        通知内容 += f"  积分: {结果['积分']}\n"
        通知内容 += f"  成长值: {结果['成长值']}\n"
        通知内容 += f"  状态: {结果['状态']}\n\n"

    # 发送青龙通知
    通知成功 = 发送青龙通知(通知标题, 通知内容.strip())
    if 通知成功:
        print("已发送青龙通知")
    else:
        print("青龙通知模块未找到，跳过推送")

    if 存在失败:
        raise SystemExit(1)


if __name__ == "__main__":
    main()