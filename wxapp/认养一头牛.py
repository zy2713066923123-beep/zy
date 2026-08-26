#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import yyb  # 自动同步 yyb_go 存活账号
# name: 认养一头牛
# cron: 17 9,22 * * *

"""
认养一头牛签到（YYB Go 版）

功能：
  1. YYB_SERVER 获取微信 code + 手机号加密数据
  2. minilogin 换取 token（本地缓存 + 自动续期）
  3. 每日签到
  4. 试用申请
  5. 中奖记录查询
  6. 社区答题（智能缓存正确答案）
  7. 发帖种草后自动删帖

环境变量：
  YYB_SERVER    必填：YYB Go 服务地址@微信账号标识，多账号换行分隔

依赖：
  pip install requests
"""

import json
import os
import random
import time
import re
from datetime import datetime, timezone, timedelta

try:
    from SendNotify import capture_output
except Exception as exc:
    print(f"[警告] 通知模块 SendNotify.py 导入失败：{exc}，将跳过通知推送。")

    def capture_output(title: str = "脚本运行结果"):
        def decorator(func):
            return func

        return decorator

import sys

# 允许从仓库根目录导入统一的通知模块 SendNotify（与根目录 ikuuu.py 共用一份）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests


BASE_URL = "https://www.milkcard.mall.ryytngroup.com"
APP_ID = "wx0408f3f20d769a2f"
ACCOUNT_FILE = "token_caches/ryytncookie.json"

# 答题正确答案缓存（内存级，跨账号共享）
ANSWER_CACHE = {}


# ============ 统一取码（WX_ID + getCode，支持牛子/YYB 双协议自动路由）============
# 环境变量：
#   WX_ID         微信账号标识（wxid 或 openid），多账号换行或 & 分隔。
#                 不配置时，自动从 YYB 服务拉取全部在线账号。
#   YYB_SERVER    应用宝取码服务地址（手机号获取 + 自动拉取账号需要）
#   WECHAT_SERVER 牛子取码服务地址（可选）
#   WXAPP_SERVICE_URL  兼容别名，等价于 YYB_SERVER
WX_IDS = [s.strip() for s in os.getenv("WX_ID", "").replace("&", "\n").splitlines() if s.strip()]
YYB_HOST = (
    (os.getenv("WX_SERVER") or os.getenv("YYB_SERVER") or "").strip()
    or os.getenv("WXAPP_SERVICE_URL", "").strip()
    or (os.getenv("WX_SERVER") or os.getenv("WECHAT_SERVER") or "").strip()
)
if YYB_HOST:
    YYB_HOST = YYB_HOST.replace("http://", "").replace("https://", "").rstrip("/")
if not WX_IDS:
    print("ℹ️  未配置环境变量 WX_ID，将尝试从 YYB 服务自动拉取全部在线账号")
    if not YYB_HOST:
        print("❌ 未配置 WX_ID，也未配置 YYB_SERVER，无法获取账号")
        print("格式：wxid#备注 或 openid，多账号换行或 & 分隔")


def mask_token(token: str) -> str:
    if len(token) <= 12:
        return token
    return f"{token[:6]}****{token[-4:]}"


def mask_phone(phone: str) -> str:
    if len(phone) >= 11:
        return f"{phone[:3]}****{phone[-4:]}"
    return phone


# ============ 业务请求 ============

def request_json(token: str, method: str, path: str, payload: dict | None = None) -> tuple[bool, str, dict | None]:
    url = f"{BASE_URL}{path}"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.61(0x18003d24) NetType/4G Language/zh_CN",
        "Referer": "https://servicewechat.com/wx0408f3f20d769a2f/305/page-frame.html",
        "X-Auth-Token": token,
        "Accept": "application/json",
    }

    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, timeout=30)
        else:
            response = requests.post(url, headers=headers, json=payload or {}, timeout=30)
    except Exception as exc:
        return False, f"请求异常: {exc}", None

    text = response.text
    if not response.ok:
        return False, f"HTTP {response.status_code}: {text[:200]}", None

    try:
        data = response.json()
    except Exception as exc:
        return False, f"JSON解析失败: {exc}; body={text[:500]}", None

    if not isinstance(data, dict):
        return False, f"响应不是 JSON 对象: {text[:200]}", data
    if data.get("code") != 200:
        return False, f"请求失败: code={data.get('code')} msg={data.get('msg') or '未知错误'}", data
    return True, "ok", data


def check_checkin_status(token: str):
    return request_json(token, "POST", "/mall/xhr/task/checkin/save")


def get_checkin_rule(token: str):
    return request_json(token, "GET", "/mall/xhr/task/checkin/getRule")


def get_address_list(token: str):
    return request_json(token, "POST", "/mall/xhr/address/receive/list")


def get_trial_list(token: str):
    return request_json(token, "POST", "/mall/xhr/freeTrial/getList", {"pageNum": 1, "pageSize": 10, "statusList": [1, 2]})


def apply_trial(token: str, trial_id: int, address_id: int):
    return request_json(token, "POST", "/mall/xhr/freeTrial/apply", {"id": trial_id, "addressId": address_id})


def get_winning_records(token: str):
    return request_json(token, "POST", "/mall/xhr/freeTrialUser/getList", {"parentTabStatus": 1, "pageNum": 1, "pageSize": 10, "subTabStatus": 1})


def get_quiz_activities(token: str):
    return request_json(token, "GET", "/mall/xhr/quizActivity/activities")


def submit_quiz_answer(token: str, quiz_activity_id: int, user_answer: str):
    return request_json(token, "POST", "/mall/xhr/quizActivity/submit", {"quizActivityId": quiz_activity_id, "userAnswer": user_answer})


def get_quiz_records(token: str):
    return request_json(token, "GET", "/mall/xhr/quizActivity/records")


def get_recommend_items(token: str):
    return request_json(
        token,
        "POST",
        "/mall/xhr/community/home/recommend/item",
        {"recommendationId": 7, "sort": "personalized", "direction": "desc", "pageNum": 1, "pageSize": 3},
    )


def push_community_post(token: str, content: str, image_urls: list):
    return request_json(
        token,
        "POST",
        "/mall/xhr/community/posts/push",
        {
            "postId": None,
            "title": "",
            "content": content,
            "imageUrls": image_urls,
            "topicLabelNames": [],
            "communityTopicActivityId": None,
            "communitPostDraftId": None,
            "freeTrialCommentId": None,
            "productIds": [],
        },
    )


def delete_community_post(token: str, post_id: int):
    return request_json(token, "GET", f"/mall/xhr/community/posts/delete?postId={post_id}")


def beijing_today_0am() -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    return now.strftime("%Y-%m-%d 00:00:00")


# ============ YYB Go token 获取 ============

def refresh_token(openid: str) -> str | None:
    """通过 YYB Go 获取 code + 手机号数据，调用 minilogin 换 token"""
    try:
        # yyb_go 的 getPhoneNumber 按 ref 精确匹配账号：纯数字按 UIN/ID，否则按 openid 精确匹配。
        # 传入带 #手机号 后缀的原始串会 404 account not found，这里剥成纯 openid。
        pure_openid = str(openid).split('#')[0].strip()

        # 1. 获取 wx.login code（统一 getCode 模块）
        wx_code = get_single_code(APP_ID, openid)

        # 2. 获取手机号数据（统一 getCode 模块）
        phone_info = get_single_phone_encrypted(APP_ID, openid)
        if not phone_info:
            print("  [REFRESH] get_single_phone_encrypted 获取手机号失败")
            return None
        encrypted_data = phone_info.get("encryptedData")
        iv = phone_info.get("iv")
        phone_code = phone_info.get("code", "")

        if not encrypted_data or not iv:
            print("  [REFRESH] 缺少 encryptedData 或 iv")
            return None

        # 3. 调用 minilogin
        login_payload = {
            "encryptedData": encrypted_data,
            "offset": iv,
            "wxCode": wx_code,
            "code": phone_code,
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.61(0x18003d24) NetType/4G Language/zh_CN",
            "Referer": "https://servicewechat.com/wx0408f3f20d769a2f/323/page-frame.html",
        }
        login_resp = requests.post(
            f"{BASE_URL}/mall/xhr/minilogin",
            headers=headers,
            json=login_payload,
            timeout=30,
        )
        token = login_resp.headers.get("X-Auth-Token")
        if not token:
            try:
                body = login_resp.json()
                if body.get("code") == 200 and "data" in body:
                    token = body["data"].get("token") or body["data"].get("x-auth-token")
            except Exception:
                pass
        if token:
            return token
        else:
            print(f"  [REFRESH] minilogin 未返回 token, 响应: {login_resp.text[:200]}")
            return None
    except Exception as e:
        print(f"  [REFRESH] 刷新 token 异常: {e}")
        return None


# ============ 本地缓存管理 ============

def load_accounts() -> list[dict]:
    if not os.path.exists(ACCOUNT_FILE):
        return []
    try:
        with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict) and "ref" in item and "token" in item]
    except Exception as e:
        print(f"[CACHE] 读取缓存文件失败: {e}")
    return []


def save_accounts(accounts: list[dict]):
    os.makedirs(os.path.dirname(ACCOUNT_FILE), exist_ok=True)
    try:
        with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:
            json.dump(accounts, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[CACHE] 保存缓存文件失败: {e}")


# ============ 核心业务 ============

def run_once(account: dict) -> bool:
    token = account["token"]
    ref = account.get("ref", "unknown")
    server = account.get("server", "")
    nickname = account.get("nickname", ref)

    print(f"\n{'='*15}")
    print(f"账号 {nickname} (ref:{ref}) token:{mask_token(token)}")
    print(f"{'='*15}")

    ok, message, checkin = check_checkin_status(token)
    if not ok:
        print(f"[FAIL] token 失效: {message}")
        print("[RETRY] 尝试刷新 token...")
        new_token = refresh_token(ref)
        if not new_token:
            print(f"[FAIL] 刷新 token 失败，跳过该账号")
            return False
        account["token"] = new_token
        token = new_token
        print(f"[INFO] 新 token: {mask_token(new_token)}")
        ok, message, checkin = check_checkin_status(new_token)
        if not ok:
            print(f"[FAIL] 刷新后仍失败: {message}")
            return False

    checkin_data = checkin.get("data") or {}
    grade = checkin_data.get("grade")
    phone = str(checkin_data.get("phone") or "")
    point = checkin_data.get("point", 0)
    print(f"手机号: {mask_phone(phone)}  当前积分: {point}")

    # 签到（check_checkin_status 已完成 checkin/save 签到动作，这里读取签到规则确认状态）
    ok, msg, _ = get_checkin_rule(token)
    if ok:
        print("✅ 签到成功（已领取今日签到）")
    else:
        print(f"❌ 签到状态查询失败: {msg}")

    # 收货地址
    ok, msg, addr = get_address_list(token)
    address_id = None
    city_name = ""
    if not ok:
        print(f"获取收货地址失败: {msg}")
    else:
        addresses = addr.get("data") if isinstance(addr.get("data"), list) else []
        if addresses:
            address_id = int(addresses[0].get("id"))
            city_name = str(addresses[0].get("cityName") or "")
        else:
            print("需要先在小程序 我的-收货地址 中填写地址")

    # 试用申请
    if address_id:
        ok, msg, trial = get_trial_list(token)
        if not ok:
            print(f"获取试用商品列表失败: {msg}")
        else:
            trial_list = ((trial.get("data") or {}).get("list") or [])
            for item in trial_list:
                if item.get("freeTrialButton") != 3:
                    continue
                grade_list = [str(x) for x in (item.get("gradeList") or [])]
                if grade is None or str(grade) not in grade_list:
                    continue
                trial_id = int(item.get("id"))
                product_name = str(item.get("productName") or "")
                draw_time = str(item.get("drawTime") or "")
                print(f"【{product_name}】可申请试用，开奖时间 {draw_time}")
                ok, msg, _ = apply_trial(token, trial_id, address_id)
                if ok:
                    print(f"✅ 试用申请成功，收货地址 {city_name}")
                else:
                    print(f"❌ 试用申请失败: {msg}")

    # 中奖记录
    ok, msg, win = get_winning_records(token)
    if ok:
        records = ((win.get("data") or {}).get("list") or [])
        if not records:
            print("暂无中奖记录")
        else:
            for item in records:
                print(f"恭喜中奖【{item.get('productName') or ''}】，完成试用后需要提交试用报告")
    else:
        print(f"查询中奖记录失败: {msg}")

    # 社区答题
    try:
        run_quiz(token)
    except Exception as e:
        print(f"❌ 社区答题异常: {e}")

    # 发帖删帖
    try:
        run_community_post(token)
    except Exception as e:
        print(f"❌ 发帖种草异常: {e}")

    return True


def run_quiz(token: str):
    global ANSWER_CACHE

    ok, msg, quiz_res = get_quiz_activities(token)
    if not ok:
        print(f"获取社区答题题库失败: {msg}")
        return

    activities = quiz_res.get("data") if isinstance(quiz_res.get("data"), list) else []
    today = beijing_today_0am()
    today_quiz = next((item for item in activities if item.get("relatedDate") == today), None)
    if not today_quiz:
        print("今日暂无社区答题题目")
        return

    print(f"获取到社区答题题目：{today_quiz.get('questionTitle')}")
    try:
        options = json.loads(today_quiz.get("options") or "[]")
    except Exception:
        print("❌ 解析答题选项失败")
        return
    if not options:
        print("未获取到题目选项，跳过答题")
        return

    today_related_date = today_quiz.get("relatedDate")
    selected_key = ANSWER_CACHE.get(today_related_date)

    if selected_key:
        print(f"使用缓存的正确答案：{selected_key}")
    else:
        ok_rec, msg_rec, records_res = get_quiz_records(token)
        if ok_rec:
            records = records_res.get("data", [])
            today_record = next(
                (r for r in records if r.get("relatedDate") == today_related_date and r.get("isCorrect") == 1),
                None
            )
            if today_record:
                selected_key = today_record.get("correctAnswer")
                if selected_key:
                    ANSWER_CACHE[today_related_date] = selected_key
                    print(f"从答题记录获取正确答案：{selected_key}，已缓存")
        else:
            print(f"获取答题记录失败: {msg_rec}")

        if not selected_key:
            selected = random.choice(options)
            selected_key = selected.get("key")
            print(f"随机选择答案：{selected_key}，提交后将获取正确答案")
            time.sleep(6 + random.random() * 2)

            ok_sub, msg_sub, submit = submit_quiz_answer(token, int(today_quiz.get("id")), selected_key)
            if ok_sub:
                data = submit.get("data") or {}
                correct_answer = data.get("correctAnswer")
                if correct_answer:
                    ANSWER_CACHE[today_related_date] = correct_answer
                    print(f"正确答案是：{correct_answer}，已缓存")
                if data.get("isCorrect") == 1:
                    print(f"回答正确，获得{data.get('point', 0)}积分")
                else:
                    print(f"答案错误，今日未获得积分")
            else:
                print(f"❌ 提交答题失败: {msg_sub}")
            return

    time.sleep(6 + random.random() * 2)
    ok_sub, msg_sub, submit = submit_quiz_answer(token, int(today_quiz.get("id")), selected_key)
    if ok_sub:
        data = submit.get("data") or {}
        if data.get("isCorrect") == 1:
            print(f"回答正确，获得{data.get('point', 0)}积分")
        else:
            correct = data.get("correctAnswer", "")
            print(f"答案错误{'，正确答案是' + str(correct) if correct else ''}，今日未获得积分")
    else:
        print(f"❌ 提交答题失败: {msg_sub}")


def run_community_post(token: str):
    ok, msg, recommend = get_recommend_items(token)
    if not ok:
        print(f"获取推荐内容失败: {msg}")
        return

    items = ((recommend.get("data") or {}).get("list") or [])
    if not items:
        print("未获取到推荐帖子内容，跳过发帖")
        return

    item = random.choice(items)
    content = item.get("content") or ""
    image_urls = item.get("imageUrls") or []
    print(f"准备发帖，内容：{content[:10]}...")
    time.sleep(6 + random.random() * 2)

    ok, msg, push_res = push_community_post(token, content, image_urls)
    if not ok:
        print(f"❌ 发帖失败: {msg}")
        return

    post_id = (push_res.get("data") or None)
    print("发帖成功，准备删帖...")
    if not post_id:
        print("❌ 发帖响应中未获取到 postId，取消删帖")
        return

    ok, msg, _ = delete_community_post(token, int(post_id))
    if ok:
        print("帖子删除成功")
        ok, _, final = check_checkin_status(token)
        if ok:
            print(f"操作完成，当前积分 {(final.get('data') or {}).get('point', 0)}")
    else:
        print(f"❌ 删帖失败: {msg}")


@capture_output("认养一头牛签到运行结果")
def main():
    # 1. 加载本地缓存
    cached = load_accounts()
    cache_map = {item["ref"]: item for item in cached}

    # 2. 收集待处理账号
    accounts = []

    if WX_IDS:
        print(f"✅ 读取到 {len(WX_IDS)} 个微信账号（WX_ID），自动路由牛子/YYB 双协议")
        for openid in WX_IDS:
            if not openid:
                print(f"[SKIP] 格式无效: {openid}")
                continue

            cached_acc = cache_map.get(openid)
            if cached_acc and cached_acc.get("token"):
                acc = {
                    "ref": openid,
                    "server": YYB_HOST,
                    "nickname": cached_acc.get("nickname", openid),
                    "token": cached_acc["token"],
                }
            else:
                print(f"[LOGIN] 正在为 {openid} 获取 token...")
                token = refresh_token(openid)
                if token:
                    acc = {"ref": openid, "server": YYB_HOST, "nickname": openid, "token": token}
                    print(f"[LOGIN] token 获取成功: {mask_token(token)}")
                else:
                    print(f"[LOGIN] {openid} token 获取失败，跳过")
                    continue
                time.sleep(1.5)

            accounts.append(acc)
    else:
        # 无 WX_ID：从 YYB 服务自动拉取全部在线账号并登录（用户版能力）
        fetched = fetch_all_accounts_from_service()
        for acc in fetched:
            cached_acc = cache_map.get(acc["ref"])
            if cached_acc and cached_acc.get("token"):
                accounts.append({
                    "ref": acc["ref"],
                    "server": acc.get("server", YYB_HOST),
                    "nickname": cached_acc.get("nickname", acc.get("nickname", acc["ref"])),
                    "token": cached_acc["token"],
                })
            else:
                accounts.append(acc)

    if not accounts:
        print("[MAIN] 无可用账号，退出")
        return

    print(f"[MAIN] 共 {len(accounts)} 个账号待处理")

    for idx, acc in enumerate(accounts):
        try:
            run_once(acc)
        except Exception as e:
            print(f"[{acc.get('nickname')}] 异常: {e}")
        if idx < len(accounts) - 1:
            time.sleep(2 + random.random() * 2)

    save_accounts(accounts)
    print("\n所有账号处理完成，缓存已更新")


def fetch_all_accounts_from_service() -> list:
    """无 WX_ID 时，从 YYB 服务拉取全部在线账号并登录生成 token。
    返回 [{"ref", "server", "nickname", "token"}]
    """
    if not YYB_HOST:
        print("[ACCOUNT] 未配置 YYB_SERVER，无法自动拉取账号")
        return []

    accounts = []
    print(f"[ACCOUNT] 从 YYB 服务获取账号列表: {YYB_HOST}")
    try:
        resp = requests.get(f"http://{YYB_HOST}/accounts", timeout=15)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"API 返回错误: {data}")
        raw_accounts = data.get("data", [])
        if not raw_accounts:
            raise Exception("账号列表为空")
        print(f"[ACCOUNT] 获取到 {len(raw_accounts)} 个账号")
    except Exception as e:
        print(f"[ACCOUNT] 获取账号列表失败: {e}")
        return accounts

    for acc in raw_accounts:
        acc_id = acc.get("id")
        nickname = acc.get("nickname", "未知")
        status = acc.get("status", "")
        if status and status != "alive":
            print(f"[SKIP] 账号 {acc_id} ({nickname}) 状态非 alive: {status}")
            continue

        ref = str(acc_id)
        print(f"[LOGIN] 正在为 {nickname} 获取 token...")

        # 登录前先校验 YYB 在线状态
        try:
            state_resp = requests.get(f"http://{YYB_HOST}/state?id={ref}", timeout=10)
            state_data = state_resp.json()
            if state_data.get("code") != 0 or not state_data.get("data"):
                print(f"  [SKIP] 账号 {nickname} 在 YYB 服务中未在线，跳过")
                continue
        except Exception:
            pass  # 服务不支持 state 接口时直接尝试登录

        token = refresh_token(ref)
        if token:
            accounts.append({
                "ref": ref,
                "server": YYB_HOST,
                "nickname": nickname,
                "token": token,
            })
            print(f"[LOGIN] {nickname} token 获取成功: {mask_token(token)}")
        else:
            print(f"[LOGIN] {nickname} token 获取失败，跳过")
        time.sleep(1.5)

    return accounts


if __name__ == "__main__":
    main()