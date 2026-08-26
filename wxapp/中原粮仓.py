# name:中原粮仓
# cron:10 9,15 * * *
import yyb  # 自动同步 yyb_go 存活账号（与其他脚本一致）
# 当前脚本整合自 wxapp 下的 1.py（抽奖）与 2.py（签到/跳一跳/冲浪）

import os
import sys
import json
import time
import random
from urllib.parse import quote

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 将脚本所在目录加入搜索路径（确保能找到 yyb.py 等同目录模块）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------- SSL 补丁 ----------
_ORIG_REQUEST = requests.Session.request


def _patched_request(self, *args, **kwargs):
    kwargs.setdefault("verify", False)
    return _ORIG_REQUEST(self, *args, **kwargs)


requests.Session.request = _patched_request


def _mount_retry(session, retries=2):
    retry = urllib3.util.retry.Retry(
        total=retries, backoff_factor=0.5,
        status_forcelist=[502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)


# ---------- 配置 ----------
APPID = "wx295fd924e45e6cc1"          # 中原粮仓 公众号 AppID
BASE_URL = "http://wechat.zygfpt.com:8090"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.30(0x18001e22) "
      "NetType/WIFI Language/zh_CN")

# 抽奖开关（默认开启，次数上限由 LOTTERY_TIMES 控制，0 表示无限）
LOTTERY_ENABLED = os.environ.get("LOTTERY", "1") != "0"
LOTTERY_TIMES = int(os.environ.get("LOTTERY_TIMES", "9999"))

QYWX_KEY = os.environ.get("QYWX_KEY", "")

# yyb 客户端（统一调用 yyb_go 服务端，与其他脚本一致）
_yyb_client = yyb.YYBClient()


def log(msg=""):
    print(msg, flush=True)


def random_delay(min_s=1, max_s=3):
    time.sleep(random.uniform(min_s, max_s))


# =====================================================================
# yyb 账号与授权（统一调用 yyb）
# =====================================================================
def get_yyb_accounts():
    """从 yyb_go 拉取存活账号（统一使用 yyb.load_accounts）"""
    server = yyb.get_global_server_url()
    log(f"[yyb] 连接 yyb_go 服务端: {server}")
    # 诊断：打印原始在线账号数，便于排查“拉不到”问题
    try:
        raw = yyb.YYBClient().get_online_accounts()
        log(f"[yyb] get_online_accounts 原始返回 {len(raw) if isinstance(raw, list) else '非数组'} 个")
        if isinstance(raw, list) and raw:
            log(f"[yyb] 首个账号字段: {','.join(raw[0].keys())}")
            log(f"[yyb] 示例: {json.dumps(raw[0], ensure_ascii=False)[:200]}")
    except Exception as e:
        log(f"[yyb] get_online_accounts 诊断异常: {e}")
    try:
        accounts = yyb.load_accounts()
    except Exception as e:
        log(f"[yyb] 拉取账号失败: {e}")
        log("[yyb] 请确认环境变量 WX_SERVER / WECHAT_SERVER 指向可用的 yyb_go 服务，且该服务有在线账号")
        return []
    log(f"[yyb] load_accounts 返回 {len(accounts) if isinstance(accounts, list) else '非数组'} 个")
    if not accounts:
        log("[yyb] 未获取到任何在线账号")
        log("[yyb] 请确认：1) WX_SERVER/WECHAT_SERVER 已配置且可达；2) yyb_go 中存在 status=online 的存活账号")
    return accounts


def get_yyb_oauth_code(account):
    """通过 yyb 获取公众号网页授权 code（snsapi_userinfo）

    使用 yyb_go 新版路由 /wxapp/oauth/authorize（旧版 /wx/oauth 已不存在）。
    oauth_authorize 内部会按 ref 解析账号并请求微信授权，返回原始授权结果
    （含 code / openid / unionid / 等微信字段，或 redirect_url）。
    """
    ref = str(account.get("id") or account.get("openid") or account.get("wxid"))
    oauth_url = (
        "https://open.weixin.qq.com/connect/oauth2/authorize"
        "?appid=" + APPID +
        "&redirect_uri=" + quote("https://wechat.zygfpt.com:8090/grain-bag-api/user/wechatLogin", safe="") +
        "&response_type=code&scope=snsapi_userinfo&state=&connect_redirect=1#wechat_redirect"
    )
    res = _yyb_client.oauth_authorize(ref, APPID, oauth_url)
    if not isinstance(res, dict):
        raise Exception(f"获取公众号授权失败: {res}")
    # code 优先取返回里的 code，其次从 redirect_url 的 query 解析
    code = res.get("code")
    redirect_url = res.get("redirect_url") or ""
    if not code and redirect_url:
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(redirect_url).query)
        code = (q.get("code") or [None])[0]
    openid = res.get("openid")
    unionid = res.get("unionid")
    nickname = res.get("nickname") or account.get("nickname") or account.get("remark") or ""
    if not code:
        raise Exception(f"未获取到授权 code: {res}")
    return code, openid, unionid, nickname


# =====================================================================
# 中原粮仓 登录
# =====================================================================
def get_yyb_token(account):
    """用公众号授权信息登录中原粮仓，换取登录 token"""
    code, openid, unionid, nickname = get_yyb_oauth_code(account)
    remark = account.get("remark") or account.get("nickname") or openid or ""
    payload = {
        "code": code,
        "encryptedData": "",
        "iv": "",
        "openId": openid or "",
        "unionId": unionid or "",
        "nickName": nickname or remark,
        "headUrl": "",
        "inviteCode": "",
    }
    r = requests.post(
        f"{BASE_URL}/grain-bag-api/user/wechatLogin",
        json=payload,
        headers={"User-Agent": UA, "Content-Type": "application/json"},
        timeout=20,
    )
    try:
        data = r.json()
    except Exception:
        raise Exception(f"wechatLogin 响应解析失败: {r.status_code} {r.text[:120]}")
    if not data.get("success"):
        raise Exception(f"wechatLogin 失败: {data}")
    token = data["data"]["token"]
    log(f"  - 登录成功: {remark} (openid={openid})")
    return token


def get_access_token(token):
    """用登录 token 换取业务 accessToken + customerId"""
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "token": token,
    }
    r = requests.post(
        f"{BASE_URL}/grain-bag-api/user/accessToken",
        json={},
        headers=headers,
        timeout=20,
    )
    try:
        data = r.json()
    except Exception:
        raise Exception(f"accessToken 响应解析失败: {r.status_code} {r.text[:120]}")
    if not data.get("success"):
        raise Exception(f"accessToken 失败: {data}")
    return data


def get_user_info(access):
    """拉取用户资料（userId / point / customerId 等）"""
    token = access["data"]["accessToken"]
    customer_id = access["data"]["customerId"]
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "token": token,
        "customer": str(customer_id),
    }
    r = requests.post(
        f"{BASE_URL}/grain-bag-api/user/getUserInfo",
        json={},
        headers=headers,
        timeout=20,
    )
    try:
        data = r.json()
    except Exception:
        raise Exception(f"getUserInfo 响应解析失败: {r.status_code} {r.text[:120]}")
    if not data.get("success"):
        raise Exception(f"getUserInfo 失败: {data}")
    return data


# =====================================================================
# 业务：签到 / 跳一跳 / 冲浪
# =====================================================================
def do_sign(access, user):
    token = access["data"]["accessToken"]
    customer_id = access["data"]["customerId"]
    user_id = user["data"]["userId"]
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "token": token,
        "customer": str(customer_id),
    }
    payload = {"userId": user_id}
    r = requests.post(
        f"{BASE_URL}/grain-bag-api/sign/signIn",
        json=payload,
        headers=headers,
        timeout=20,
    )
    try:
        data = r.json()
    except Exception:
        log(f"  - 签到响应解析失败: {r.status_code} {r.text[:120]}")
        return
    if data.get("success"):
        log(f"  - 签到成功: {data.get('message')}")
    else:
        log(f"  - 签到返回: {data.get('message')}")


def do_jump(access, user):
    token = access["data"]["accessToken"]
    customer_id = access["data"]["customerId"]
    user_id = user["data"]["userId"]
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "token": token,
        "customer": str(customer_id),
    }
    payload = {"userId": user_id, "num": 1}
    r = requests.post(
        f"{BASE_URL}/grain-bag-api/jump/play",
        json=payload,
        headers=headers,
        timeout=20,
    )
    try:
        data = r.json()
    except Exception:
        log(f"  - 跳一跳响应解析失败: {r.status_code} {r.text[:120]}")
        return
    if data.get("success"):
        log(f"  - 跳一跳成功: {data.get('message')}")
    else:
        log(f"  - 跳一跳返回: {data.get('message')}")


def do_surf(access, user):
    token = access["data"]["accessToken"]
    customer_id = access["data"]["customerId"]
    user_id = user["data"]["userId"]
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "token": token,
        "customer": str(customer_id),
    }
    payload = {"userId": user_id, "num": 1}
    r = requests.post(
        f"{BASE_URL}/grain-bag-api/surf/play",
        json=payload,
        headers=headers,
        timeout=20,
    )
    try:
        data = r.json()
    except Exception:
        log(f"  - 冲浪响应解析失败: {r.status_code} {r.text[:120]}")
        return
    if data.get("success"):
        log(f"  - 冲浪成功: {data.get('message')}")
    else:
        log(f"  - 冲浪返回: {data.get('message')}")


# =====================================================================
# 业务：抽奖（来自 1.py）
# =====================================================================
def get_point(access):
    """查询当前积分"""
    token = access["data"]["accessToken"]
    customer_id = access["data"]["customerId"]
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "token": token,
        "customer": str(customer_id),
    }
    r = requests.post(
        f"{BASE_URL}/grain-bag-api/point/getPoint",
        json={},
        headers=headers,
        timeout=20,
    )
    try:
        data = r.json()
    except Exception:
        return None
    if data.get("success"):
        return data["data"].get("point")
    return None


def draw_lottery(access):
    """执行一次抽奖，返回是否成功"""
    token = access["data"]["accessToken"]
    customer_id = access["data"]["customerId"]
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "token": token,
        "customer": str(customer_id),
    }
    r = requests.post(
        f"{BASE_URL}/grain-bag-api/lottery/draw",
        json={},
        headers=headers,
        timeout=20,
    )
    try:
        data = r.json()
    except Exception:
        log(f"  - 抽奖响应解析失败: {r.status_code} {r.text[:120]}")
        return False
    if data.get("success"):
        msg = data.get("message") or "ok"
        gain = ""
        try:
            gain = data["data"].get("awardName", "")
        except Exception:
            gain = ""
        log(f"  - 抽奖成功: {msg} {gain}".strip())
        return True
    else:
        log(f"  - 抽奖结束: {data.get('message')}")
        return False


# =====================================================================
# 主流程
# =====================================================================
def main():
    accounts = get_yyb_accounts()
    if not accounts:
        raise Exception("未配置账号：请检查 WX_SERVER / WX_ID")

    log(f"中原粮仓 启动，账号数: {len(accounts)}")
    log(f"抽奖: {'开启' if LOTTERY_ENABLED else '关闭'}")

    ok = 0
    fail = 0

    for idx, account in enumerate(accounts, 1):
        remark = account.get("remark") or account.get("nickname") or account.get("openid") or f"账号{idx}"
        log(f"\n=== 处理 {remark} ({idx}/{len(accounts)}) ===")
        try:
            token = get_yyb_token(account)
            access = get_access_token(token)
            user = get_user_info(access)

            point_before = user["data"].get("point")
            log(f"  - 当前积分: {point_before}")

            # 签到 + 跳一跳 + 冲浪
            do_sign(access, user)
            random_delay()
            do_jump(access, user)
            random_delay()
            do_surf(access, user)
            random_delay()

            # 抽奖
            if LOTTERY_ENABLED:
                drawn = 0
                while drawn < LOTTERY_TIMES:
                    if not draw_lottery(access):
                        break
                    drawn += 1
                    random_delay(1, 2)
                log(f"  - 本次抽奖次数: {drawn}")

            point_after = get_point(access)
            log(f"  - 积分变化: {point_before} -> {point_after}")
            ok += 1
        except Exception as e:
            fail += 1
            log(f"  - 账号失败: {e}")

    log(f"\n中原粮仓 结束: 成功 {ok}，失败 {fail}")


if __name__ == "__main__":
    main()
