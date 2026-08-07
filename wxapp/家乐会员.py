#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 家乐会员
# cron: 1 9,22 * * *
"""
家乐会员 (联合利华 UFS 餐饮会员) 小程序 - 积分任务自动脚本
=========================================================
反编译源码: wx57048525e48315b4_unpacked (appid: wx57048525e48315b4)

接口分析 (来自 app-service.js + 真实抓包 HAR):
  - 微信登录:  POST {oauth}/{accountId}/v2/weapp/oauth?maijsVersion&clientId&appVersion&appName&clientTime
                头: X-Account-Id={accountId}, X-Requested-With=XMLHttpRequest
                body: {scope:"base", code, watermark:{appid}, is_group:"false"}
                返回: {accessToken, channelId, member:{id,...}, openId, unionId}
                (accountId 为 build 固定值 577c98c4905e88311f8b474a, 对所有用户一致)
  - 登录态:    通过请求头 X-Access-Token 携带 accessToken (源码 st() 函数)
                X-Account-Id 登录时携带 accountId, 登录后源码 ut() 改为携带 memberId
  - 任务列表:  GET  {business}/{accountId}/v2/memberTasks
  - 任务状态:  POST {business}/{accountId}/modules/ufscmcmall/loyalty/task/status
                body: {codes:[...]}
  - 完成简单任务: POST {business}/{accountId}/modules/ufscmcmall/loyalty/task/simple-complete
                body: {code}
  - 领取奖励(积分): POST {business}/{accountId}/modules/ufscmcmall/loyalty/task/reward
                body: {code}

说明:
  - 部分任务需要真人交互 (看视频/答题/采样/邀请等), 无法通过 simple-complete 自动完成;
    脚本会对"已完成条件但未领取"的任务调用 reward 领积分, 并对可自动完成的
    普通浏览类任务调用 simple-complete。
  - 登录依赖项目统一取码体系: WX_ID 环境变量 + getCode.get_single_code 双协议路由。

依赖环境变量:
  WX_ID               微信账号, 多账号换行或 & 分隔, 格式: wxid#备注 或 openid
  UFS_TOKEN           可选, accessToken 兜底 (getCode 不可用时使用)
  UFS_MEMBER_ID       可选, memberId 兜底

通知: 统一接入 SendNotify.capture_output (青龙 notify, 无环境自动降级为打印)
"""

import os
import sys
import time
import json
import random
import logging
import argparse
from urllib.parse import quote
from datetime import datetime
from typing import Optional, Dict, Any, List

import requests
import base64
import hashlib

# 允许从仓库根目录导入统一的取码与通知模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ============ 菜谱域(community)签名算法 (逆向自反编译小程序源码 sgin.js) ============
# 该域与 loyalty 任务域(consumer-api)是两套独立鉴权, 仅用 sign+timestamp+appid+aid 鉴权, 无需 JWT
COMMUNITY_BASE = "https://community.unileverfoodsolutions.com.cn"
COMMUNITY_VERSION = "/api/v22"
SGIN_APPID = "aem-ufs-extg"
# 菜谱域签名密钥 R (android prod 双重 base64 矩阵解出, 已用真实抓包样本验证一致)
# 直接硬编码解码后的常量, 避免运行时 base64 长度问题
_SGIN_R = "0D8BF64A9C46AC0D19D66047478B7E95kdfdkfk099E"
_NANOID_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz-"
_UUID_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def _sgin_md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def _sgin_sign(timestamp: str, appid: str = SGIN_APPID) -> str:
    return _sgin_md5(timestamp + _SGIN_R + appid)

def _sgin_randnum(ts_ms: int, n: int = 10) -> str:
    s = list(str(ts_ms)); a = []
    for _ in range(n):
        i = random.randint(0, len(s) - 1)
        a.append(s[i]); s[i] = s[-1]; s.pop()
    return "".join(a)

def _sgin_nanoid(n: int = 21) -> str:
    return "".join(random.choice(_NANOID_CHARS) for _ in range(n))

def _sgin_uuid(n: int = 6) -> str:
    return "".join(random.choice(_UUID_CHARS) for _ in range(n))

def gen_sgin_timestamp() -> str:
    ts = int(time.time() * 1000)
    return f"{_sgin_randnum(ts, 10)}-{_sgin_nanoid(21)}-{_sgin_uuid(6)}"

def gen_sgin_params() -> dict:
    ts = gen_sgin_timestamp()
    return {"sign": _sgin_sign(ts), "timestamp": ts, "appid": SGIN_APPID}

# HAR 抓取到的菜谱 artid (content/ufs/zh/recipes/sgslszj/jcr:content 的 urlencode 形式)
DEFAULT_RECIPE_ARTID = "content/ufs/zh/recipes/sgslszj/jcr:content"


# 统一取码 (与项目其它脚本一致: WX_ID + getCode 双协议自动路由)
try:
    from getCode import get_single_code
except Exception as exc:
    print(f"[警告] getCode.py 导入失败：{exc}，WX_ID 取码不可用，仅支持环境变量 token 兜底")
    get_single_code = None

# 统一通知: 桥接青龙内置 notify (无环境则降级为仅打印, 绝不抛异常)
try:
    from SendNotify import capture_output
except Exception as exc:
    print(f"[警告] 通知模块 SendNotify.py 导入失败：{exc}，将跳过通知推送。")

    def capture_output(title: str = "脚本运行结果"):
        def decorator(func):
            return func
        return decorator


# ============ 配置 ============
APPID = "wx57048525e48315b4"

# 生产环境域名 (源自反编译 He/Ve/Fe/qe/ze/Ge 映射表的 ufs-production 项)
OAUTH_BASE = os.getenv("UFS_OAUTH_BASE", "https://oauth-api.unileverfoodsolutions.com.cn").strip()
BUSINESS_BASE = os.getenv("UFS_BUSINESS_BASE", "https://business-api.unileverfoodsolutions.com.cn").strip()
CONSUMER_BASE = os.getenv("UFS_CONSUMER_BASE", "https://consumer-api.unileverfoodsolutions.com.cn").strip()
MEMBER_BASE = os.getenv("UFS_MEMBER_BASE", "https://member.unileverfoodsolutions.com.cn").strip()

# accountId (build 固定值, 来自抓包 X-Account-Id 与 oauth 路径前缀 /577c98c4905e88311f8b474a/)
# 该值由小程序 build 决定, 对所有用户一致; 如需覆盖可设环境变量 UFS_ACCOUNT_ID
ACCOUNT_ID = os.getenv("UFS_ACCOUNT_ID", "577c98c4905e88311f8b474a").strip()

WX_IDS = [s.strip() for s in os.getenv("WX_ID", "").replace("&", "\n").splitlines() if s.strip()]

# 可自动完成的任务白名单 (reward 无需真人弹窗即可领到积分)。
# 服务端的 simple-complete 接口只认特定 code, 业务任务 (进货/报单/上传/调研/邀请/
# 企微等) 返回 "Invalid task code", 无底层接口可伪造, 必须真人操作 -> 直接跳过。
# 已知可领任务 (抓包实测 reward 返回 isCompleted:true & rewardedCount:1):
#   - ULTSAMPD : 浏览爆款 (simple-complete 可完成)
#   - ULTKRL   : 查看菜谱10秒 (完成态由前端停留行为上报, simple-complete 不认该 code;
#               若任务已被置为 completed, 直接 reward 即可领到积分)
# 注意: 本小程序无"签到"任务。
# 用 UFS_AUTO_CODES 环境变量可扩展, 例如 ULTKRL,ULTSAMPD。
# 可自动完成的任务白名单 (查看菜谱 ULTKRL / 爆款 ULTSAMPD 等)。
# 支持环境变量 UFS_AUTO_CODES 扩展; 若未设置或为空则回退到默认白名单。
_auto_raw = os.getenv("UFS_AUTO_CODES", "")
if not _auto_raw.strip():
    _auto_raw = "ULTSAMPD,ULTKRL"
AUTO_CODES = {c.strip().upper() for c in _auto_raw.split(",") if c.strip()}

# 登录路径: 真实抓包为 /{accountId}/v2/weapp/oauth (需带 accountId 前缀 + 查询参数)
OAUTH_HOST_CANDIDATES = [
    OAUTH_BASE,
    "https://oauth.unileverfoodsolutions.com.cn",
]
OAUTH_PATH_CANDIDATES = [
    f"/{ACCOUNT_ID}/v2/weapp/oauth",
    "/v2/weapp/oauth",
    f"/api/{ACCOUNT_ID}/v2/weapp/oauth",
    "/api/v2/weapp/oauth",
]
# 任务接口 base 候选: 优先带 accountId 前缀 (与 oauth 一致), 失败回退根路径
TASK_BASE_CANDIDATES = [
    f"{BUSINESS_BASE.rstrip('/')}/{ACCOUNT_ID}",
    BUSINESS_BASE.rstrip("/"),
    f"{BUSINESS_BASE.rstrip('/')}/api/{ACCOUNT_ID}",
    f"{BUSINESS_BASE.rstrip('/')}/api",
]

# 运行时验证出的可用 URL (账号间复用, 避免重复消耗 code)
_WORKING_OAUTH_URL = {"url": None}
_WORKING_TASK_BASE = {"url": None}  # 形如 https://.../ 前缀, 拼接具体 action

# 登录请求固定查询参数 (来自真实抓包)
MAIJS_VERSION = os.getenv("UFS_MAIJS_VERSION", "1.5.1").strip()
APP_VERSION = os.getenv("UFS_APP_VERSION", "0.9.0").strip()
APP_NAME = os.getenv("UFS_APP_NAME", "家乐会员中心").strip()


def _client_id() -> str:
    """生成与抓包一致的 clientId (UUID v4)。"""
    import uuid
    return str(uuid.uuid4())


def _login_query() -> dict:
    """构造登录请求查询参数 (clientTime 为 ISO8601 本地时间)。"""
    return {
        "maijsVersion": MAIJS_VERSION,
        "clientId": _client_id(),
        "appVersion": APP_VERSION,
        "appName": APP_NAME,
        "clientTime": datetime.now().astimezone().isoformat(timespec="milliseconds"),
    }


def _client_time() -> str:
    """ISO8601 本地时间 (与微信端 clientTime 一致, 如 2026-08-07T11:08:42.358+08:00)。"""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"https://servicewechat.com/{APPID}/254/page-frame.html",
}

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("ufs")


def cprint(text, color="", level=logging.INFO):
    """纯文本打印 (已移除 ANSI 颜色码, 避免部分终端捕获推送产生乱码)。"""
    logger.log(level, text)


def get_code(wxid: str) -> Optional[str]:
    """通过项目统一取码体系获取微信登录 code。"""
    if not get_single_code:
        return None
    identifier = wxid.split("#")[0].strip()
    try:
        return get_single_code(APPID, identifier)
    except Exception as exc:
        cprint(f"❌ 取码失败: {exc}", "red")
        return None


class UFSClient:
    def __init__(self, access_token: str = "", member_id: str = "", account_id: str = ""):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.access_token = access_token
        self.member_id = member_id
        self.account_id = account_id or ACCOUNT_ID
        self.username = ""
        if access_token:
            self._apply_auth()

    def _apply_auth(self):
        # 真实鉴权格式 (还原自 HAR 抓包 /v2/memberTasks):
        #   X-Access-Token = 裸 accessToken (JWT)
        #   X-Account-Id   = accountId (全局固定值, 非 memberId)
        self.session.headers["X-Access-Token"] = self.access_token
        self.session.headers["X-Account-Id"] = self.account_id or ACCOUNT_ID

    # ---------- 登录 ----------
    @staticmethod
    def _parse_token(data):
        """从响应中解析 accessToken + member 信息, 兼容 axios data 透传与 {data:{}} 结构。

        返回 (token, member, member_id)，其中:
          - token       : 裸 accessToken (JWT), 用于 X-Access-Token 头
          - member_id   : member.id (memberId)
          - account_id  : member.accountId (全局 accountId, 用于 X-Account-Id 头, 见下)
        """
        if not isinstance(data, dict):
            return None, {}, None, None
        body = data.get("data", data)
        if not isinstance(body, dict):
            body = data
        token = body.get("accessToken") or data.get("accessToken") or data.get("access_token")
        member = body.get("member") or data.get("member") or {}
        if not isinstance(member, dict):
            member = {}
        member_id = member.get("id") or data.get("memberId") or data.get("openId")
        # 登录后 X-Account-Id 应携带 member.accountId (全局固定值, 而非 memberId)
        account_id = member.get("accountId") or ACCOUNT_ID
        return token, member, member_id, account_id

    def _try_login(self, url, code):
        payload = {
            "scope": "base",
            "code": code,
            "watermark": {"appid": APPID},
            "is_group": "false",
        }
        # 未登录态: X-Account-Id 携带 build 固定 accountId (来自抓包)
        headers = {
            "X-Account-Id": ACCOUNT_ID,
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            resp = self.session.post(
                url, json=payload, params=_login_query(),
                headers=headers, timeout=20,
            )
        except Exception as exc:
            return None, f"请求异常: {exc}", None
        try:
            data = resp.json()
        except Exception:
            return None, f"HTTP {resp.status_code} 非JSON: {resp.text[:200]}", resp
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}: {resp.text[:200]}", resp
        token, member, member_id, account_id = self._parse_token(data)
        if not token:
            # 可能是未注册/需业务错误码, 仍视为该 URL 有效但登录业务失败
            return "biz_error", data.get("msg") or data, resp
        return "ok", (token, member, member_id, account_id), resp

    def login(self, code: str) -> bool:
        # 1) 已探测到可用 URL 则直接复用
        if _WORKING_OAUTH_URL["url"] is not None:
            cprint(f"ℹ️ 复用已验证登录URL: {_WORKING_OAUTH_URL['url']}", "blue")
            status, result, resp = self._try_login(_WORKING_OAUTH_URL["url"], code)
            if status == "ok":
                return self._finish_login(result, resp)
            # 复用失败则回退到探测

        # 2) 自动探测正确 URL (域名 × 路径前缀)
        cprint("🔍 探测可用登录接口...", "yellow")
        for host in OAUTH_HOST_CANDIDATES:
            for path in OAUTH_PATH_CANDIDATES:
                url = host.rstrip("/") + path
                status, result, resp = self._try_login(url, code)
                if status == "ok":
                    _WORKING_OAUTH_URL["url"] = url
                    cprint(f"✅ 验证可用登录URL: {url}", "green")
                    return self._finish_login(result, resp)
                elif status == "biz_error":
                    # 该 URL 有效(返回了业务 JSON), 只是登录业务失败, 记录下来供排查
                    _WORKING_OAUTH_URL["url"] = url
                    cprint(f"⚠️ URL 可达但登录业务失败: {url} -> {result}", "yellow")
                    return False
                else:
                    cprint(f"  · 排除 {url} ({result})", "blue")
        cprint("❌ 所有登录URL候选均不可用, 请检查域名/路径", "red")
        return False

    def _finish_login(self, quad, resp):
        token, member, member_id, account_id = quad
        self.member_id = member_id or ""
        self.account_id = account_id or ACCOUNT_ID
        # 真实鉴权格式 (还原自 HAR 抓包 /v2/memberTasks):
        #   X-Access-Token = 裸 accessToken (JWT, 服务端返回原样)
        #   X-Account-Id   = accountId (全局固定值, 非 memberId)
        # 注: 任务接口无需注入 ufsproduction_accesstoken cookie, 仅靠上面两个头即可。
        self.access_token = token
        self._apply_auth()
        self.username = (member.get("name") or member.get("nickName")
                         or member_id or "未知")
        cprint(f"✅ 登录成功: {self.username}", "green")
        return True

    # ---------- 任务 (loyalty 接口走 mai.request 默认 baseURL;
    #   源码: e.rest.defaults.baseURL = e.isStaff ? businessApiBaseUrl : consumerApiBaseUrl
    #   普通会员走 consumerApiBaseUrl, 不带 accountId 前缀) ----------
    # 路径 100% 还原自反编译源码 (app-service.js):
    #   fetchList  -> GET  /v2/memberTasks
    #   fetchStatuses -> POST /modules/ufscmcmall/loyalty/task/status   {codes, extra}
    #   completeSimpleTask -> POST /modules/ufscmcmall/loyalty/task/simple-complete {code}
    #   reward -> POST /modules/ufscmcmall/loyalty/task/reward {code}
    def _task_base(self) -> str:
        """任务接口 base: 源码确认普通会员走 consumerApiBaseUrl 根域名 (不带 accountId 前缀)。"""
        return CONSUMER_BASE.rstrip("/")

    def _resolve_task_base(self) -> str:
        return self._task_base()

    def _task_params(self, **extra) -> dict:
        """任务接口通用查询参数 (还原自 HAR 抓包), extra 可覆盖/追加。"""
        p = {
            "maijsVersion": MAIJS_VERSION,
            "clientId": _client_id(),
            "appVersion": APP_VERSION,
            "appName": APP_NAME,
            "envVersion": "release",
            "clientTime": _client_time(),
        }
        p.update(extra)
        return p

    def fetch_tasks(self) -> List[Dict[str, Any]]:
        """拉取会员任务列表。查询参数还原自 HAR 抓包。"""
        base = self._task_base()
        params = self._task_params(
            **{
                "listCondition.page": 1,
                "listCondition.perPage": 100,
                "isEnabled.value": "true",
            }
        )
        self.session.headers["X-Requested-With"] = "XMLHttpRequest"
        try:
            resp = self.session.get(f"{base}/v2/memberTasks", params=params, timeout=20)
            data = resp.json()
        except Exception as exc:
            cprint(f"❌ 获取任务列表失败: {exc}", "red")
            return []
        items = data.get("items") if isinstance(data, dict) else None
        if not items:
            cprint(f"ℹ️ 任务列表为空, 原始响应: {str(data)[:200]}", "yellow")
        return items or []

    def fetch_statuses(self, codes: List[str]) -> Dict[str, Any]:
        """批量查询任务完成状态。"""
        if not codes:
            return {}
        base = self._task_base()
        self.session.headers["X-Requested-With"] = "XMLHttpRequest"
        try:
            resp = self.session.post(
                f"{base}/modules/ufscmcmall/loyalty/task/status",
                params=self._task_params(),
                json={"codes": codes, "extra": {}},
                timeout=20,
            )
            cprint(f"🔎 [status] 原始响应: {str(resp.json())[:600]}", "blue")
            return resp.json()
        except Exception as exc:
            cprint(f"❌ 查询任务状态失败: {exc}", "red")
            return {}

    def simple_complete(self, code: str) -> bool:
        base = self._task_base()
        self.session.headers["X-Requested-With"] = "XMLHttpRequest"
        try:
            resp = self.session.post(
                f"{base}/modules/ufscmcmall/loyalty/task/simple-complete",
                params=self._task_params(),
                json={"code": code},
                timeout=20,
            )
            data = resp.json()
        except Exception as exc:
            cprint(f"   ⚠️ simple-complete[{code}] 失败: {exc}", "yellow")
            return False
        cprint(f"🔎 [simple-complete:{code}] 原始响应: {str(data)[:400]}", "blue")
        # 成功响应: 返回完整记录对象 (含 id/accountId/createdAt), 无 message 报错
        # 失败响应: {"message":"Invalid task code"} 或 {"code":4xx,...}
        # 判据: 含 id 字段且无 message 报错 => 成功
        if isinstance(data, dict) and data.get("id") and not data.get("message"):
            return True
        if isinstance(data, dict):
            if data.get("success") is False:
                return False
            if data.get("message"):  # 含报错 message => 失败
                return False
            if data.get("code") not in (None, 0, 200, "0", "200"):
                return False
        return False

    # ---------- 菜谱域(community)自动化: 查看菜谱任务(ULTKRL) ----------
    def _get_aid(self):
        """菜谱域用 aid(用户id) 鉴权, 优先 member_id, 其次 JWT 解码, 再 fallback 配置."""
        if getattr(self, "member_id", None):
            return self.member_id
        tok = self.access_token or ""
        if tok.count(".") == 2:
            try:
                payload = tok.split(".")[1]
                payload += "=" * (-len(payload) % 4)
                d = json.loads(base64.urlsafe_b64decode(payload))
                for k in ("uid", "sub", "memberId", "id", "userId"):
                    if d.get(k):
                        return str(d[k])
            except Exception:
                pass
        return os.getenv("UFS_AID", "")

    def complete_recipe_view(self, artid: str = DEFAULT_RECIPE_ARTID):
        """访问菜谱详情页 + 视频播放状态上报, 触发 ULTKRL 查看菜谱任务完成.

        菜谱域(community)与 loyalty 任务域是两套独立鉴权, 仅用
        sign + timestamp + appid(aem-ufs-extg) + aid(用户id) 鉴权, 无需 JWT.
        算法已逆向 sgin.js 并用真实抓包样本验证一致.

        关键: 逆向 recipes/app-service.js 后确认 ULTKRL 翻转的真实链路是:
          1. GET  /member/log-on/{userId}            初始化菜谱域会话
          2. POST /recipe/getRecipeReleteDetails      浏览菜谱详情(body 注入 aid)
          3. GET  /adam/recipe/richMedia/video/...    视频播放埋点上报
          4. POST /adam/recipe/api-task-log            ★ 前端倒计时10秒后调用,
                 body={source:<MPSource>, status:1}   —— 这才是真正把任务置为
                 isCompleted=True 的接口(jrsxTaskFinish 的前置上报).
        仅前3步(详情/上报)服务端虽返回200, 但任务状态不会翻转; 必须补第4步.
        返回 (ok, detail_msg)  —— ok 仅当关键上报(api-task-log)成功且为合法 JSON.
        """
        aid = self._get_aid()
        if not aid:
            return False, "缺少 aid(用户id), 无法访问菜谱域 (可设 UFS_AID 环境变量)"
        cprint(f"  · 菜谱域 aid = {aid[:6]}*** (共 {len(aid)} 字符)", "blue")
        headers = {
            "client-type": "minProgramMember",
            "content-type": "application/json",
        }

        def _is_html(t: str) -> bool:
            return t.lstrip().lower().startswith("<!doctype") or t.lstrip().lower().startswith("<html")

        def _sig(url_path: str, extra_query: str = "") -> str:
            sg = gen_sgin_params()
            return (
                f"{COMMUNITY_BASE}{COMMUNITY_VERSION}{url_path}"
                f"?sign={sg['sign']}&timestamp={quote(sg['timestamp'])}&appid={sg['appid']}{extra_query}"
            )

        # 0) 菜谱域独立登录初始化
        try:
            r0 = self.session.get(_sig(f"/member/log-on/{quote(aid)}"), headers=headers, timeout=20)
            cprint(f"🔎 [log-on] HTTP {r0.status_code} | {str(r0.text)[:160]}", "blue")
        except Exception as exc:
            cprint(f"   ⚠️ log-on 请求失败: {exc}", "yellow")

        # 1) 菜谱详情页 POST
        try:
            r1 = self.session.post(
                _sig("/recipe/getRecipeReleteDetails"),
                json={"artId": artid, "aid": aid, "language": "cn", "instanceId": ""},
                headers=headers, timeout=20,
            )
            cprint(f"🔎 [菜谱详情] HTTP {r1.status_code} | {str(r1.text)[:160]}", "blue")
        except Exception as exc:
            cprint(f"   ⚠️ 菜谱详情请求失败: {exc}", "yellow")
        time.sleep(2 + random.random() * 2)

        # 2) 视频播放状态上报 GET
        try:
            r2 = self.session.get(
                _sig("/adam/recipe/richMedia/video/is-play/get-relay/2", f"&aid={aid}"),
                headers=headers, timeout=20,
            )
            cprint(f"🔎 [视频播放上报] HTTP {r2.status_code} | {str(r2.text)[:160]}", "blue")
        except Exception as exc:
            cprint(f"   ⚠️ 视频播放上报失败: {exc}", "yellow")
        time.sleep(8 + random.random() * 4)  # 模拟停留10秒, 等前端倒计时走完

        # 3) ★ 任务完成上报: 前端 jrsxTaskFinish 前置接口, 真正翻转 isCompleted
        #    source 取 config.MPSource (逆向 config/index.js: e(189) -> t()[4] = "GrossProfit")
        ok3 = False
        try:
            r3 = self.session.post(
                _sig("/adam/recipe/api-task-log"),
                json={"source": "GrossProfit", "status": 1},
                headers=headers, timeout=20,
            )
            txt = str(r3.text)
            cprint(f"🔎 [任务完成上报] HTTP {r3.status_code} | {txt[:160]}", "blue")
            ok3 = (r3.status_code == 200) and (not _is_html(txt))
            if ok3:
                try:
                    j = r3.json()
                    if isinstance(j, dict) and j.get("code") not in (200, "200", 0, "0"):
                        ok3 = False
                        cprint(f"   ⚠️ 任务完成上报业务失败: {j.get('message')}", "yellow")
                except Exception:
                    pass
        except Exception as exc:
            cprint(f"   ⚠️ 任务完成上报请求失败: {exc}", "yellow")

        if ok3:
            return True, "菜谱域任务完成上报成功 (api-task-log)"
        detail_ok = ('r1' in locals() and r1.status_code == 200) or ('r2' in locals() and r2.status_code == 200)
        if detail_ok:
            return False, "菜谱详情/上报已发但任务完成上报未成功(ULTKRL 可能未翻转)"
        return False, "菜谱域请求未成功(返回 error 页或未授权, 可能缺菜谱域登录态)"

    def claim_reward(self, code: str):
        """领取奖励。

        返回 (ok: bool, reason: str)，reason 用于细化提示:
          - "ok"                : 领取成功
          - "invalid_code"      : simple-complete 阶段服务端不认该 code (业务任务, 需真人)
          - "not_completed"     : 任务条件未满足 (Invalid task status)
          - "rate_limit"        : 触发频率限制, 重试仍失败
          - "need_interaction"  : 需真人交互 (订阅弹窗/加企微等)
          - "unknown"           : 其它
        """
        base = self._task_base()
        self.session.headers["X-Requested-With"] = "XMLHttpRequest"
        data = None
        try:
            resp = self.session.post(
                f"{base}/modules/ufscmcmall/loyalty/task/reward",
                params=self._task_params(),
                json={"code": code},
                timeout=20,
            )
            data = resp.json()
        except Exception as exc:
            cprint(f"   ⚠️ reward[{code}] 请求异常: {exc}", "yellow")
            return False, "unknown"

        cprint(f"🔎 [reward:{code}] 原始响应: {str(data)[:400]}", "blue")

        # 统一重试辅助: 针对限流 / 状态同步延迟 (Invalid task status) 各重试一次
        def _retry_once():
            time.sleep(10)
            try:
                r2 = self.session.post(
                    f"{base}/modules/ufscmcmall/loyalty/task/reward",
                    params=self._task_params(),
                    json={"code": code},
                    timeout=20,
                )
                d2 = r2.json()
            except Exception:
                return None
            cprint(f"🔎 [reward:{code}] 重试响应: {str(d2)[:400]}", "blue")
            return d2

        # 限流识别: 操作过于频繁 / 频率限制 => 重试一次
        #   (注意: 重试后若返回其它业务错误, 必须以末次响应 message 为准, 不再沿用 rate_limit)
        if isinstance(data, dict):
            raw = str(data.get("message") or data.get("msg") or "").lower()
            if "频繁" in raw or "frequency" in raw or "too many" in raw:
                cprint(f"   ⏳ [reward:{code}] 触发限流, 10s 后重试...", "yellow")
                data = _retry_once() or data

        # 成功判据 (message 优先于 code, 因为存在 {code:0, message:"Invalid task status"} 的坑):
        #   1) 含报错 message => 失败 (Invalid task status / 操作过于频繁 等均在此)
        #   2) success=true 或 code 为 0/200 => 成功
        #   3) 累计已领标志 => 成功:
        #        isRewarded        : 本请求是否新发放 (瞬时)
        #        rewardedCount>=1  : 累计已领取次数 (真实已领证据, 抓包实测菜谱任务领奖成功时为
        #                            {isCompleted:true,isRewarded:false,completedCount:1,rewardedCount:1})
        #        isAllRewarded     : 全部奖励已领
        if isinstance(data, dict):
            msg = str(data.get("message") or data.get("msg") or "")
            if msg:
                # 根据 message 细化失败原因 (以末次响应为准)
                if "Invalid task status" in msg:
                    # 刚 simple-complete 成功后, 服务端状态可能未即时同步, 重试一次
                    cprint(f"   ⏳ [reward:{code}] 状态未同步, 10s 后重试...", "yellow")
                    data = _retry_once() or data
                    return self._eval_reward(data, code)
                if "Invalid task code" in msg:
                    return False, "invalid_code"
                if "频繁" in msg or "frequency" in msg or "too many" in msg:
                    return False, "rate_limit"
                if "从业者" in msg or "资质" in msg or "专业餐饮" in msg:
                    cprint(f"   ⚠️ [reward:{code}] 账号资质受限: {msg}", "yellow")
                    return False, "forbidden"
                return False, "need_interaction"
            return self._eval_reward(data, code)
        return False, "unknown"

    @staticmethod
    def _eval_reward(data, code) -> tuple:
        """根据 reward 响应判定是否领取成功 (无报错 message 分支)。"""
        if not isinstance(data, dict):
            return False, "unknown"
        if data.get("rewardedCount"):
            try:
                if int(data.get("rewardedCount")) >= 1:
                    return True, "ok"
            except (TypeError, ValueError):
                pass
        if data.get("isAllRewarded") is True:
            return True, "ok"
        if data.get("isRewarded") is True:
            return True, "ok"
        if data.get("success") is True:
            return True, "ok"
        if data.get("code") in (0, 200, "0", "200"):
            return True, "ok"
        return False, "unknown"

    def get_member_score(self) -> Optional[int]:
        """查询会员当前积分。

        抓包确认接口 (来自 HAR 13:28):
          GET {consumerApi}/modules/ufscmcmall/member/score
          头: X-Access-Token=<JWT>, X-Account-Id=<accountId>
          响应: {"score":25, "isActivated":true}
        """
        base = self._task_base()
        try:
            resp = self.session.get(
                f"{base}/modules/ufscmcmall/member/score", timeout=20)
            data = resp.json()
            if isinstance(data, dict) and data.get("score") is not None:
                return int(float(data.get("score")))
        except Exception as exc:
            cprint(f"  ⚠️ 查询积分失败: {exc}", "yellow")
        return None

    def get_score_history(self, page: int = 1, per_page: int = 5) -> list:
        """查询最近积分变动明细 (用于核对领取是否到账)。

        抓包确认接口 (来自 HAR 13:30):
          GET {consumerApi}/modules/ufscmcmall/member/score-history?page=1&per-page=5&type=2
          响应: {"items":[{...}], "_meta":{"totalCount":N}}
        注意: page 从 1 开始, 翻到第 4 页等空页会返回 items:[] (并非无记录)。
        """
        base = self._task_base()
        try:
            resp = self.session.get(
                f"{base}/modules/ufscmcmall/member/score-history",
                params={"page": page, "per-page": per_page, "type": 2},
                timeout=20,
            )
            data = resp.json()
            if isinstance(data, dict):
                return data.get("items") or []
        except Exception as exc:
            cprint(f"  ⚠️ 查询积分明细失败: {exc}", "yellow")
        return []


def run_account(wxid: str) -> bool:
    cprint(f"\n========== 账号: {wxid} ==========", "cyan")

    # 1. 优先环境变量 token 兜底
    token = os.getenv("UFS_TOKEN", "").strip()
    member_id = os.getenv("UFS_MEMBER_ID", "").strip()
    client = UFSClient(token, member_id)

    if not token:
        code = get_code(wxid)
        if not code:
            cprint("❌ 无法获取登录 code (请检查 getCode / WX_ID 配置)", "red")
            return False
        if not client.login(code):
            return False
    else:
        client._apply_auth()
        cprint("ℹ️ 使用环境变量 UFS_TOKEN 兜底登录", "blue")

    # 2. 拉取任务
    tasks = client.fetch_tasks()
    if not tasks:
        cprint("⚠️ 未获取到任务列表", "yellow")
        return False

    cprint(f"📋 共发现 {len(tasks)} 个任务", "blue")
    cprint(f"🤖 自动完成白名单 AUTO_CODES = {sorted(AUTO_CODES)}", "blue")

    # 提取 task code 与名称/积分
    task_map = {}
    for t in tasks:
        code = t.get("code") or t.get("taskCode") or t.get("id")
        if not code:
            continue
        name = t.get("name") or t.get("title") or code
        score = t.get("score") or t.get("points") or t.get("rewardScore") or 0
        task_map[str(code)] = {"name": name, "score": score}

    codes = list(task_map.keys())

    # 3. 查询状态
    status_resp = client.fetch_statuses(codes)
    # 接口返回结构: 直接以 code 为 key 的 dict, 如 {'ULTKRL': {isCompleted:...}, ...}
    #   (兼容历史 items/data/list 列表形式)
    if isinstance(status_resp, dict):
        # 优先: 以 code 为 key 的扁平结构
        first_val = next(iter(status_resp.values()), None)
        if isinstance(first_val, dict) and ("isCompleted" in first_val or "isRewarded" in first_val
                                            or "completed" in first_val or "rewarded" in first_val):
            status_by_code = {str(k): v for k, v in status_resp.items() if isinstance(v, dict)}
        else:
            # 退化: 可能是 {items:[...]} 包裹
            listed = status_resp.get("items") or status_resp.get("data") or status_resp.get("list") or []
            status_by_code = {}
            for s in listed:
                if isinstance(s, dict):
                    sc = s.get("code") or s.get("taskCode")
                    if sc:
                        status_by_code[str(sc)] = s
    else:
        status_by_code = {}
    cprint(f"🔎 [status] 解析到 {len(status_by_code)} 个任务状态", "blue")

    def _is_completed(s: dict) -> bool:
        """兼容多种字段命名: isCompleted / completed / status=='completed' / done。"""
        if not isinstance(s, dict):
            return False
        if s.get("isCompleted") is True:
            return True
        if s.get("completed") is True:
            return True
        if s.get("status") == "completed":
            return True
        if s.get("done") is True:
            return True
        return False

    def _is_rewarded(s: dict) -> bool:
        if not isinstance(s, dict):
            return False
        if s.get("isRewarded") is True:
            return True
        if s.get("rewarded") is True:
            return True
        if s.get("claimed") is True:
            return True
        if s.get("rewardClaimed") is True:
            return True
        return False

    # 策略:
    #   - 领奖: 对所有"已完成且未领取"的任务都尝试 reward (含订阅等真人完成的任务),
    #           不再限于白名单, 避免"已手动完成却没自动领"的漏领。
    #   - 完成: 仅对白名单任务尝试 simple-complete 去把它置为完成 (业务任务无接口可伪造)。
    auto_codes = [c for c in task_map if c in AUTO_CODES]
    cprint(f"🐞 task_map 含白名单任务: {sorted(set(task_map) & AUTO_CODES)}", "blue")
    cprint(f"🐞 status_by_code 含白名单任务: {sorted(set(status_by_code) & AUTO_CODES)}", "blue")
    for _c in ("ULTKRL", "ULTSAMPD"):
        _st = status_by_code.get(_c, "缺失")
        cprint(f"🐞 [{_c}] status = {str(_st)[:200]}", "blue")

    # 收集: 已完成未领取 (直接领) + 白名单未完成 (先完成再领)
    claim_ready = []   # 已完成未领取 -> 直接 reward
    need_complete = []  # 白名单内且未完成 -> simple 完成后再 reward
    skipped = []        # 既不在白名单也未完成 -> 需真人, 跳过

    for code, info in task_map.items():
        st = status_by_code.get(code, {})
        if _is_completed(st) and not _is_rewarded(st):
            claim_ready.append(code)
        elif code in AUTO_CODES and not _is_completed(st):
            need_complete.append(code)
        else:
            skipped.append(code)

    total_gained = 0
    account_forbidden = False  # 账号资质受限 (仅限专业餐饮从业者), 终止后续领奖

    # A) 已完成未领取的任务: 直接领 (含订阅等手动完成但漏领的)
    # 注意: 账号资质受限(forbidden)只阻止"领奖", 不阻止 B 段的"完成"动作
    #       (菜谱自动化走菜谱域签名, 非 JWT, 不受该风控影响), 故 forbidden 用 continue 而非 break。
    for code in claim_ready:
        if account_forbidden:
            cprint(f"  · {task_map.get(code, {}).get('name', code)} 跳过领奖(账号资质受限)", "yellow")
            continue
        info = task_map[code]
        name = info["name"]
        score = info["score"]
        ok, reason = client.claim_reward(code)
        if reason == "forbidden":
            account_forbidden = True
            cprint(f"  ⚠️ 账号资质受限, 本账号后续领奖将跳过 (但菜谱自动化仍会尝试)", "yellow")
            continue
        if ok:
            score_disp = f" +{score}" if int(score or 0) else ""
            cprint(f"  ✅ {name} 领取成功{score_disp}", "green")
            total_gained += int(score or 0)
        elif reason == "rate_limit":
            cprint(f"  · {name} 领取受限流 (稍后重试)", "yellow")
        else:
            cprint(f"  · {name} 暂不可领取 ({reason})", "blue")
        time.sleep(5 + random.random() * 4)

    # B) 白名单内未完成: 先完成, 再领
    # 注意: 此处不因 account_forbidden 而整体跳过, 因为"完成"动作(尤其菜谱域签名)
    #       与领奖风控无关, 即便账号领奖受限也应尝试把任务置为完成。
    for code in need_complete:
        info = task_map[code]
        name = info["name"]
        score = info["score"]
        # 菜谱任务(ULTKRL)的"完成"由前端停留行为上报, 需走菜谱域(community)接口,
        # simple-complete 不认该 code 会返回失败, 故单独走 complete_recipe_view。
        if code in ("ULTKRL",):
            cprint(f"  … {name} (菜谱域自动化: 访问菜谱详情+播放上报)", "yellow")
            rv_ok, rv_msg = client.complete_recipe_view()
            cprint(f"  · 菜谱域结果: {rv_msg}", "blue")
            # 二次校验: 重新拉取 ULTKRL 状态, 确认是否从执行前快照翻转为已完成
            _before = _is_completed(status_by_code.get("ULTKRL", {}))
            try:
                _recheck = client.fetch_statuses(["ULTKRL"]) or {}
                _recheck_flat = {}
                if isinstance(_recheck, dict):
                    _fv = next(iter(_recheck.values()), None)
                    if isinstance(_fv, dict) and ("isCompleted" in _fv or "isRewarded" in _fv):
                        _recheck_flat = {str(k): v for k, v in _recheck.items() if isinstance(v, dict)}
                _after = _is_completed(_recheck_flat.get("ULTKRL", {}))
            except Exception as _e:
                _after = _before
                cprint(f"  · 菜谱状态二次校验失败(忽略): {_e}", "yellow")
            if _after and not _before:
                cprint(f"  ✅ [二次校验] ULTKRL 已翻转为已完成 (执行前: 未完成)", "green")
            elif _after and _before:
                cprint(f"  · [二次校验] ULTKRL 执行前即已完成", "blue")
            else:
                cprint(f"  ⚠️ [二次校验] ULTKRL 仍未标记为已完成 (执行前: {'已完成' if _before else '未完成'})", "yellow")
        else:
            # 普通浏览类任务: simple-complete 置为完成 (业务任务无接口可伪造)。
            # 注意: simple 失败不作为终止条件, 部分任务已完成态下直接 reward 也能领。
            cprint(f"  … {name} (尝试自动完成)", "yellow")
            sc_ok = client.simple_complete(code)
            if not sc_ok:
                cprint(f"  · {name} simple-complete 未命中 (将直接尝试领奖, 若已完成可领)", "blue")
        time.sleep(8 + random.random() * 4)  # 完成->领奖 冷却, 规避同任务时序限流
        if account_forbidden:
            cprint(f"  · {name} 跳过领奖(账号资质受限)", "yellow")
            continue
        ok, reason = client.claim_reward(code)
        if reason == "forbidden":
            account_forbidden = True
            cprint(f"  ⚠️ 账号资质受限, 本账号后续领奖将跳过 (但菜谱自动化仍会尝试)", "yellow")
            continue
        if ok:
            score_disp = f" +{score}" if int(score or 0) else ""
            cprint(f"  ✅ {name} 领取成功{score_disp}", "green")
            total_gained += int(score or 0)
        elif reason == "rate_limit":
            cprint(f"  · {name} 领取受限流 (稍后重试)", "yellow")
        else:
            cprint(f"  · {name} 暂不可领取 ({reason})", "blue")
        time.sleep(5 + random.random() * 4)

    if skipped and not account_forbidden:
        cprint(f"  ⊘ 跳过 {len(skipped)} 个需真人操作的任务 (业务任务, 既非白名单也未完成)", "blue")

    # 4. 查询积分
    score_now = client.get_member_score()
    if score_now is not None:
        cprint(f"💰 当前积分: {score_now}", "green")

    # 4.1 最近积分变动明细 (核对领取是否到账)
    history = client.get_score_history(page=1, per_page=5)
    if history:
        cprint("📜 最近积分变动:", "green")
        for h in history:
            if not isinstance(h, dict):
                continue
            desc = (h.get("description") or h.get("remark") or h.get("title")
                    or h.get("name") or h.get("type") or "—")
            delta = h.get("score") or h.get("point") or h.get("changeScore") or h.get("amount") or 0
            when = h.get("createdAt") or h.get("createTime") or h.get("date") or ""
            try:
                delta_disp = f"{int(float(delta)):+d}"
            except (TypeError, ValueError):
                delta_disp = str(delta)
            cprint(f"   · {desc}  {delta_disp}  {when}", "blue")
    else:
        cprint("📜 暂无积分变动明细 (items 为空, 可能本页无记录)", "blue")

    cprint(f"🎉 本次预计获得积分: +{total_gained}", "cyan")
    return True


@capture_output("家乐会员 积分任务")
def main():
    parser = argparse.ArgumentParser(description="家乐会员 (UFS) 积分任务自动脚本")
    parser.add_argument("--no-code", action="store_true",
                        help="仅使用环境变量 UFS_TOKEN/UFS_MEMBER_ID, 不取 code")
    args = parser.parse_args()

    if args.no_code:
        global get_single_code
        get_single_code = None

    if not WX_IDS and not os.getenv("UFS_TOKEN", "").strip():
        cprint("❌ 未配置 WX_ID 或 UFS_TOKEN 环境变量", "red")
        cprint("   多账号示例: WX_ID=wxid_xxx#备注&wxid_yyy#备注2", "yellow")
        return

    accounts = WX_IDS if WX_IDS else ["__env_token__"]
    ok = 0
    for wxid in accounts:
        if wxid == "__env_token__":
            run_account("ENV_TOKEN")
        else:
            if run_account(wxid):
                ok += 1
            time.sleep(2 + random.random() * 2)

    cprint(f"\n========== 完成: {ok}/{len([a for a in accounts if a!='__env_token__'])} 个账号执行成功 ==========", "cyan")


if __name__ == "__main__":
    main()
