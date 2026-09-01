import yyb  # 自动同步 yyb_go 存活账号
# cron: 44 12,00 * * *
"""
# name: 汤星球
作者: 吉吉国王大人
日期: 2026/6/30
name: ꧁༺ 汤汤༒星球 ༻꧂ (微信协议版)
入口: 微信小程序 - 汤臣倍健 (wx9bb6d5ac457bd69d)
后端: vip.by-health.com
功能: 自动签到（含7/14/21/28天宝箱自动领取+补签）

环境变量配置:
  WX_ID           账号配置，格式：wxid#备注，多账号换行 / & 分隔
  WX_SERVER       yyb_go 协议服务地址（例如：http://127.0.0.1:18273）
  txq             手动模式兼容，每行 备注#Authorization
  LY_NOTIFY       (可选) 是否推送通知

说明:
  自动登录模式：通过微信协议服务器获取 OAuth code，再换取 Authorization（JWT）
  手动模式：直接填写抓包获取的 Authorization，跳过登录步骤

  宝箱机制（7/14/21/28天节点）：
    1. 签到前先调 detail 检查进度，自动领取漏领的宝箱
    2. 签到返回 undrawnFlag=1 时，先领宝箱再补签
    3. 已签到状态下残留的待领宝箱也会尝试领取

  如果自动登录失败，切换手动模式：
    1. 微信打开「汤星球」小程序 → 抓包找到 Authorization 请求头
    2. 青龙面板添加环境变量 txq，格式：备注#Authorization值
    3. 多账号换行分割
"""

import json
import os
import random
import re
import time
import traceback

import requests


try:
    from notify import send as notify_send
except ImportError:
    def notify_send(title, content):
        print(f"--- 通知 ---\n{title}\n{content}\n-------------")

retrycount = 3
name = "꧁༺ 汤汤༒星球 ༻꧂"

WX_APPID = "wx9bb6d5ac457bd69d"
HOST = "https://vip.by-health.com"
DEFAULT_WECHAT_SERVER = os.environ.get("WX_SERVER") or os.environ.get("YYB_SERVER") or os.environ.get("WECHAT_SERVER") or "http://127.0.0.1:18273"

SIGN_PATH = "/vip-api/sign/daily/create"
DRAW_PATH = "/vip-api/sign/daily/draw"
DETAIL_PATH = "/vip-api/sign/activity/detail"
SIGN_ACTIVITY_ID = 11
LOGIN_PATH = "/vip-api/auth/ma/login"

# token 缓存名（与 yyb.py 共享缓存机制，减少取码频率、规避限流）
TOKEN_CACHE_NAME = "tangxingqiu"

# 宝箱奖励类型映射
REWARD_TYPE_MAP = {0: "积分", 1: "微信红包", 2: "实物"}


# build_code_url 和 get_code 已统一到 yyb.py，此处保留兼容
def build_code_url(raw_url):
    """已废弃，保留兼容"""
    return ""


def get_code(wxid, _server=None):
    """通过 yyb.py 统一接口获取微信 code"""
    try:
        return yyb.get_single_code(WX_APPID, wxid)
    except Exception as exc:
        print(f"微信: 获取 code 异常: {exc}")
        return None


def get_nested(data, path, default=None):
    """按点号路径取嵌套字段，如 data.token"""
    current = data
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def build_headers(authorization="", appid=WX_APPID):
    headers = {
        "Host": "vip.by-health.com",
        "Content-Type": "application/json;charset=utf-8",
        "Referer": f"https://servicewechat.com/{appid}/devtools/page-frame.html",
        "sec-ch-ua-mobile": "?1",
        "Accept": "*/*",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; MI 8 Build/QKQ1.190828.002; wv) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.136 "
            "Mobile Safari/537.36 XWEB/1340129 MMWEBSDK/20250201 MMWEBID/6533 "
            "MicroMessenger/8.0.60.2860(0x28003C51) WeChat/arm64 Weixin NetType/WIFI "
            "Language/zh_CN ABI/arm64 miniProgram/wx9bb6d5ac457bd69d"
        ),
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "sec-ch-ua-platform": "Android",
        "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Android WebView";v="134"',
        "x-requested-with": "com.tencent.mm",
        "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if authorization:
        headers["Authorization"] = authorization
        headers["Origin"] = "https://vip.by-health.com"
    return headers


def login_by_code(wx_id, wechat_server):
    """用微信 OAuth code 换取 Authorization token。返回 token 字符串或 None。"""
    # 优先使用缓存 token，减少取码频率、规避限流
    cached = yyb.get_cached_token(TOKEN_CACHE_NAME, wx_id)
    if cached:
        print(f"🔑 命中 token 缓存，跳过取码")
        return cached["token"]

    url = f"{HOST}{LOGIN_PATH}"
    print(f"🔑 获取微信授权 code...")
    code = get_code(wx_id, wechat_server)
    if not code:
        print("❌ 获取 code 失败")
        return None

    body = {"appId": WX_APPID, "code": code}
    print(f"🔑 登录: {LOGIN_PATH}")

    try:
        resp = requests.post(url, headers=build_headers(), json=body, timeout=10)
        data = resp.json() if resp.text else {}
    except (json.JSONDecodeError, requests.RequestException) as e:
        print(f"❌ 登录请求异常: {e}")
        return None

    if not data.get("success"):
        print(f"❌ 登录失败: {json.dumps(data, ensure_ascii=False)[:200]}")
        return None

    token = get_nested(data, "data.result.token")
    if token:
        token = str(token)
        print(f"✅ 登录成功! token={token[:8]}...")
        # 缓存 token，供下次复用
        try:
            yyb.save_cached_token(TOKEN_CACHE_NAME, wx_id, token)
        except Exception:
            pass
        return token

    print(f"❌ 未找到 token: {json.dumps(data, ensure_ascii=False)[:200]}")
    return None


def _do_draw(authorization, reward_record_id, label=""):
    """领取宝箱奖励，返回 reward 信息字符串或 None。"""
    url = f"{HOST}{DRAW_PATH}"
    header = build_headers(authorization)
    try:
        resp = requests.post(url, headers=header, json={"rewardRecordId": reward_record_id}, timeout=10)
        data = resp.json()
    except Exception as e:
        print(f"{label}⭕ 领取宝箱异常: {e}")
        return None

    if not data.get("success"):
        print(f"{label}⚠️ 领取宝箱失败: {json.dumps(data, ensure_ascii=False)[:120]}")
        return None

    rsp_code = get_nested(data, "data.rspCode", "")
    rsp_msg = get_nested(data, "data.rspMsg", "")
    result = get_nested(data, "data.result", {})

    if rsp_code == "00" and result:
        reward_name = result.get("msg") or f"奖励类型{result.get('rewardType', '?')} x{result.get('rewardValue', '?')}"
        print(f"{label}🎁 宝箱领取成功：{reward_name}")
        return reward_name

    print(f"{label}⚠️ 宝箱领取：{rsp_msg}")
    return None


def _check_and_draw_pending(authorization, label=""):
    """调用 detail 接口检查签到进度 & 领取漏领的宝箱。

    detail 返回 rewardList，包含 7/14/21/28 天四个宝箱节点：
      finishFlag=1 drawnFlag=0 rewardRecordId=<ID> → 已达成但未领取 → 自动 draw
      finishFlag=1 drawnFlag=1 → 已领取
      finishFlag=0 → 未达成

    返回 (sign_flag, drew_any):
      sign_flag: detail 中的 signFlag（1=今日已签到）
      drew_any: 是否领取了宝箱
    """
    url = f"{HOST}{DETAIL_PATH}"
    try:
        resp = requests.post(url, headers=build_headers(authorization), json={}, timeout=10)
        data = resp.json()
    except Exception as e:
        print(f"{label}⚠️ 获取签到详情失败: {e}")
        return None, False

    if not data.get("success"):
        return None, False

    result = get_nested(data, "data.result") or {}
    current_count = result.get("currentCount", "?")
    sign_flag = result.get("signFlag", 0)
    reward_list = result.get("rewardList") or []

    # 找出所有待领取的宝箱
    pending = []
    for reward in reward_list:
        day = reward.get("day", "?")
        finish_flag = reward.get("finishFlag", 0)
        drawn_flag = reward.get("drawnFlag", 0)
        record_id = reward.get("rewardRecordId")
        reward_name = reward.get("rewardName") or ""
        reward_type = REWARD_TYPE_MAP.get(reward.get("rewardType"), "未知")
        reward_value = reward.get("rewardValue", "")

        if finish_flag and not drawn_flag and record_id:
            display = reward_name or f"{reward_type} x{reward_value}"
            pending.append((day, record_id, display))

    if pending:
        for day, record_id, display in pending:
            print(f"{label}🎁 第{day}天宝箱待领取：{display}，正在领取...")
            _do_draw(authorization, record_id, label)
        return sign_flag, True

    # 没有待领取的，打印进度信息
    # 找下一个未达成的宝箱
    next_milestone = None
    for reward in reward_list:
        if not reward.get("finishFlag", 0):
            next_milestone = reward
            break

    if next_milestone:
        next_day = next_milestone.get("day", "?")
        remaining = next_milestone.get("remainingDay", "?")
        next_name = next_milestone.get("rewardName") or ""
        next_type = REWARD_TYPE_MAP.get(next_milestone.get("rewardType"), "")
        next_value = next_milestone.get("rewardValue", "")
        next_display = next_name or f"{next_type} x{next_value}"
        print(f"{label}📋 签到进度：第{current_count}天，距第{next_day}天宝箱（{next_display}）还有{remaining}天")
    else:
        print(f"{label}📋 签到进度：第{current_count}天，本期宝箱已全部领取")

    return sign_flag, False


def _create_sign(authorization):
    """调用签到接口，返回 JSON dict。"""
    url = f"{HOST}{SIGN_PATH}"
    resp = requests.post(url, headers=build_headers(authorization), json={"activityId": SIGN_ACTIVITY_ID}, timeout=10)
    return resp.json()


def _log_sign_success(result, label="", prefix=""):
    """打印签到成功日志。"""
    coins = result.get("dailyPointReward")
    accumulate = result.get("accumulateDay", "?")
    remaining = result.get("remainingDay", "?")
    print(f"{label}☁️ {prefix}签到成功：+{coins} 积分（累计{accumulate}天，距下次宝箱{remaining}天）")


def do_sign(authorization, label=""):
    """执行签到，返回 True/False。

    完整流程（抓包确认）：
    1. 先调 detail 检查签到进度 & 领取漏领的宝箱（7/14/21/28天节点）
    2. 调 create 签到：
       - 宝箱挡签（undrawnFlag=1）：先 draw 再补 create
       - 正常签到：dailyPointReward 有值
       - 今日已签：dailyPointReward=null 无宝箱
    """
    # 步骤1：detail 预检，领取漏领宝箱
    sign_flag, drew_any = _check_and_draw_pending(authorization, label)

    # 步骤2：签到
    data = None
    for retry in range(int(retrycount)):
        try:
            data = _create_sign(authorization)
            break
        except Exception as e:
            if retry >= int(retrycount) - 1:
                print(f"{label}⭕ 签到异常: {e}")
                return False
            time.sleep(1)
    if data is None:
        return False

    if not data.get("success"):
        msg = json.dumps(data, ensure_ascii=False)[:120]
        print(f"{label}⚠️ 签到失败: {msg}")
        return False

    result = get_nested(data, "data.result") or {}
    rsp_msg = get_nested(data, "data.rspMsg", "")
    rsp_code = get_nested(data, "data.rspCode", "")

    if rsp_code != "00":
        if "已签" in rsp_msg or "已完成" in rsp_msg:
            print(f"{label}☁️ 签到：{rsp_msg}")
            return True
        print(f"{label}⚠️ {rsp_msg or json.dumps(data, ensure_ascii=False)[:80]}")
        return False

    coins = result.get("dailyPointReward")
    # 宝箱ID在 undrawnRecordId 字段（rewardRecordId 此时恒为 null）
    undrawn_flag = result.get("undrawnFlag", 0)
    undrawn_record_id = result.get("undrawnRecordId")

    # 情况1：签到成功
    if coins is not None:
        _log_sign_success(result, label)
        # 已签到状态下可能残留待领宝箱记录，尝试领取，失败不影响签到结果
        if undrawn_flag and undrawn_record_id:
            undrawn_name = result.get("undrawnRewardName", "宝箱奖励")
            print(f"{label}🎁 发现待领取宝箱：{undrawn_name}")
            _do_draw(authorization, undrawn_record_id, label)
        return True

    # 情况2：dailyPointReward 为 null 且有宝箱ID → 宝箱挡在签到前，先领宝箱再补签
    if undrawn_flag and undrawn_record_id:
        undrawn_name = result.get("undrawnRewardName", "宝箱奖励")
        print(f"{label}🎁 到达宝箱节点，签到前先领宝箱：{undrawn_name}")
        _do_draw(authorization, undrawn_record_id, label)

        # 领完宝箱后再次签到（本次才是真正的签到）
        time.sleep(random.uniform(1, 2))
        try:
            data2 = _create_sign(authorization)
        except Exception as e:
            print(f"{label}⭕ 领取宝箱后补签异常: {e}")
            return False

        if data2.get("success") and get_nested(data2, "data.rspCode", "") == "00":
            result2 = get_nested(data2, "data.result") or {}
            if result2.get("dailyPointReward") is not None:
                _log_sign_success(result2, label, prefix="宝箱领取后")
                return True
        print(f"{label}☁️ 宝箱已处理，今日签到状态以服务端为准")
        return True

    # 情况3：全字段 null 且无宝箱 → 今日已签到过
    print(f"{label}☁️ 今日已签到过")
    return True


def main():
    wechat_server = os.environ.get("WX_SERVER") or os.environ.get("YYB_SERVER") or os.environ.get("WECHAT_SERVER") or os.environ.get("YINGYONGBAO_SERVER") or DEFAULT_WECHAT_SERVER

    log_lines = []
    log_lines.append(f"\n{' ' * 7}{name}")
    log_lines.append("-------- ☁️ 开 始  执 行 ☁️ --------")

    # 解析账号
    accounts = []
    wxid_raw = (os.getenv("WX_ID") or "").strip()
    if not wxid_raw:
        # 未配置 WX_ID 时，自动从 yyb_go 拉取存活账号
        wxid_raw = "\n".join(yyb.resolve_accounts())
    if wxid_raw:
        items = [x.strip() for x in re.split(r"[\n&@]", wxid_raw) if x.strip()]
        for item in items:
            idx = item.rfind("#")
            if idx > 0:
                accounts.append({"mode": "auto", "wxid": item[:idx].strip(), "note": item[idx + 1:].strip()})
            else:
                accounts.append({"mode": "auto", "wxid": item, "note": ""})

    # 手动模式
    ck_raw = (os.getenv("txq") or "").strip()
    if ck_raw and not accounts:
        items = [x.strip() for x in ck_raw.split("\n") if x.strip()]
        for item in items:
            try:
                mark, arg1 = item.split("#", 1)
                accounts.append({"mode": "manual", "note": mark.strip(), "authorization": arg1.strip()})
            except ValueError:
                print(f"⚠️ txq 格式错误，跳过: {item}")

    if not accounts:
        print("⭕ 未找到账号变量，请设置 WX_ID（自动登录）或 txq（手动模式）")
        return

    log_lines.append(f"共 {len(accounts)} 个账号")

    for i, acc in enumerate(accounts, 1):
        note = acc.get("note", "")
        label = f"☁️ 账号 [{i}/{len(accounts)}]"
        mask = (note[:3] + "*****" + note[-3:]) if len(note) >= 7 else note
        log_lines.append(f"\n{label}")
        log_lines.append(f"☁️ 当前账号：{mask or f'账号{i}'}")
        print(f"\n{label}")
        print(f"☁️ 当前账号：{mask or f'账号{i}'}")

        if acc["mode"] == "manual":
            authorization = acc["authorization"]
            log_lines.append("📌 手动模式，跳过登录直接签到")
            print("📌 手动模式，跳过登录直接签到")
            ok = do_sign(authorization, label="  ")
            log_lines.append(f"{'签到成功' if ok else '签到失败'}")
        else:
            wx_id = acc["wxid"]
            time.sleep(random.randint(1, 2))
            authorization = login_by_code(wx_id, wechat_server)
            if not authorization:
                msg = "❌ 自动登录失败，可切换手动模式：设置环境变量 txq = 备注#Authorization值"
                log_lines.append(msg)
                print(msg)
                continue

            log_lines.append("✅ 登录成功，获取 Authorization")
            print("✅ 登录成功，获取 Authorization")
            time.sleep(random.randint(1, 2))
            ok = do_sign(authorization, label="  ")
            log_lines.append(f"{'签到成功' if ok else '签到失败'}")

        time.sleep(random.randint(1, 2))

    log_lines.append("\n-------- ☁️ 执 行  结 束 ☁️ --------")
    print("\n-------- ☁️ 执 行  结 束 ☁️ --------")

    # 推送
    if os.getenv("LY_NOTIFY"):
        try:
            notify_send(f"{name} 运行日志", "作者：吉吉国王大人\n\n" + "\n".join(log_lines))
        except Exception:
            pass


if __name__ == "__main__":
    main()