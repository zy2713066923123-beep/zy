# cron "51 11,20 * * *"
'''
「极元健康」App 的自动化签到+刷视频积分脚本
环境变量 jyjk，格式为：
手机号#密码#备注
手机号#密码#备注
多账号换行分隔
'''

import requests
import time
import os

try:
    from notify import send as notify_send
except ImportError:
    def notify_send(title, content):
        print(f"--- 通知 ---\n{title}\n{content}\n-------------")

# ===================== 公共配置 =====================
BASE_HEADERS = {
    "Accept-Serial": "",
    "Accept-Platform": "Android",
    "Accept-Language": "zh-Hans",
    "user-agent": "Mozilla/5.0 (Linux; Android 16; 2509FPN0BC Build/BP2A.250605.031.A3; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/140.0.7339.207 Mobile Safari/537.36 uni-app Html5Plus/1.0 (Immersed/48.0)",
    "Content-Type": "application/json; charset=utf-8",
    "Host": "app.jiyuanjk.com",
    "Connection": "Keep-Alive",
    "Accept-Encoding": "gzip"
}

# 接口地址（全部来自抓包）
LOGIN_URL = "https://app.jiyuanjk.com/api/m9442/5c78dbfd977cf"
SIGN_URL = "https://app.jiyuanjk.com/api/m9442/6419244390830"
INFO_URL = "https://app.jiyuanjk.com/api/m9442/5c78c4772da97"
CATEGORY_LIST_URL = "https://app.jiyuanjk.com/api/m9442/6421a00e4fa4e"
VIDEO_LIST_URL = "https://app.jiyuanjk.com/api/m9442/64219a95b6200"
VIDEO_DETAIL_URL = "https://app.jiyuanjk.com/api/m9442/64219c5dc8d0d"

TARGET_CATEGORY_NAME = "每日必看"
WATCH_DELAY = 4
# ====================================================


def login(phone_num, passwd):
    payload = {
        "account": phone_num,
        "account_type": "mobile",
        "password": passwd,
        "user_source": "Android"
    }
    try:
        resp = requests.post(LOGIN_URL, headers=BASE_HEADERS, json=payload, timeout=15)
        res = resp.json()
        if res.get("code") == "1":
            token = res["data"]["userinfo"]["user_token"]
            print(f"【登录成功】手机号:{phone_num}")
            return token
        else:
            print(f"【登录失败】{res.get('msg')}")
            return None
    except Exception as e:
        print(f"【登录异常】{str(e)}")
        return None


def sign(token):
    headers = BASE_HEADERS.copy()
    headers["user-token"] = token
    payload = {"type": "2"}
    try:
        resp = requests.post(SIGN_URL, headers=headers, json=payload, timeout=15)
        res = resp.json()
        if res.get("code") == "1":
            data = res["data"]
            print(f"【签到成功】连续签到{data['days']}天，积分+{data['score']}，经验+{data['empirical']}")
            return int(data["score"])
        else:
            print(f"【签到结果】{res.get('msg')}")
            return 0
    except Exception as e:
        print(f"【签到异常】{str(e)}")
        return 0


def get_target_category_id(token):
    headers = BASE_HEADERS.copy()
    headers["user-token"] = token
    params = {"category_id": 8}
    try:
        resp = requests.get(CATEGORY_LIST_URL, headers=headers, params=params, timeout=15)
        res = resp.json()
        if res.get("code") != "1":
            print(f"【获取分类失败】{res.get('msg')}")
            return None

        category_list = res["data"]
        for cate in category_list:
            if cate.get("category_name") == TARGET_CATEGORY_NAME:
                cate_id = cate["category_id"]
                print(f"【匹配分类】找到「{TARGET_CATEGORY_NAME}」，分类ID：{cate_id}")
                return cate_id

        print(f"【匹配失败】未找到名为「{TARGET_CATEGORY_NAME}」的分类")
        return None
    except Exception as e:
        print(f"【获取分类异常】{str(e)}")
        return None


def get_video_list(token, category_id):
    headers = BASE_HEADERS.copy()
    headers["user-token"] = token
    params = {
        "page": 1,
        "pagesize": 15,
        "list_rows": 15,
        "category_id": category_id
    }
    try:
        resp = requests.get(VIDEO_LIST_URL, headers=headers, params=params, timeout=15)
        res = resp.json()
        if res.get("code") == "1":
            video_data = res["data"]["data"]
            print(f"【获取视频】该分类下共 {len(video_data)} 个视频")
            return video_data
        else:
            print(f"【获取视频失败】{res.get('msg')}")
            return []
    except Exception as e:
        print(f"【获取视频异常】{str(e)}")
        return []


def watch_video(token, aid):
    headers = BASE_HEADERS.copy()
    headers["user-token"] = token
    params = {"article_id": aid}
    try:
        resp = requests.get(VIDEO_DETAIL_URL, headers=headers, params=params, timeout=15)
        res = resp.json()
        if res.get("code") == "1":
            data = res["data"]
            give_score = int(data.get("give_score", 0))
            title = data.get("title", "未知视频")
            if give_score > 0:
                print(f"  ✅ 《{title}》 获得积分 +{give_score}")
            else:
                print(f"  ⏭️  《{title}》 无积分奖励")
            return give_score
        else:
            print(f"  ❌ 观看失败：{res.get('msg')}")
            return 0
    except Exception as e:
        print(f"  ❌ 观看异常：{str(e)}")
        return 0


def get_user_info(token):
    headers = BASE_HEADERS.copy()
    headers["user-token"] = token
    try:
        resp = requests.get(INFO_URL, headers=headers, timeout=15)
        res = resp.json()
        if res.get("code") == "1":
            score = res["data"]["score"]
            print(f"【账户总积分】{score}")
            return score
    except Exception as e:
        print(f"【查询积分异常】{str(e)}")
    return None


def main():
    print("===== 极元健康 签到+每日必看视频 脚本启动 =====")
    env_data = os.getenv("jyjk", "")
    if not env_data:
        print("错误：未配置环境变量 jyjk！")
        print("环境变量格式：")
        print("手机号#密码#备注")
        print("手机号#密码#备注")
        return

    log_msgs = []

    # 按换行分割账号
    line_list = env_data.splitlines()
    for line in line_list:
        line = line.strip()
        if not line:
            continue
        if line.count("#") < 2:
            msg = f"账号格式错误：{line}，格式必须为：手机号#密码#备注"
            print(msg)
            log_msgs.append(msg)
            continue
        # 分割三段：手机号#密码#备注
        phone_num, passwd, remark = line.split("#", 2)
        phone_num = phone_num.strip()
        passwd = passwd.strip()
        remark = remark.strip()

        print(f"\n========== 账号 {phone_num} 【{remark}】 ==========")
        token = login(phone_num, passwd)
        if not token:
            continue

        time.sleep(1)
        sign_score = sign(token)

        time.sleep(1)
        category_id = get_target_category_id(token)
        if not category_id:
            print("跳过视频任务")
            continue

        time.sleep(1)
        video_list = get_video_list(token, category_id)
        total_video_score = 0

        if video_list:
            print(f"\n开始观看视频，每个间隔 {WATCH_DELAY} 秒...")
            for idx, video in enumerate(video_list, 1):
                aid = video["aid"]
                print(f"  [{idx}/{len(video_list)}]", end="")
                score = watch_video(token, aid)
                total_video_score += score
                if idx < len(video_list):
                    time.sleep(WATCH_DELAY)
            print(f"\n【视频任务完成】本次观看共获得积分 +{total_video_score}")

        total_score = sign_score + total_video_score
        print(f"\n【本次总计获得】签到 +{sign_score}，视频 +{total_video_score}，合计 +{total_score}")

        time.sleep(1)
        get_user_info(token)

    print("\n===== 全部账号执行完毕 =====")

    try:
        notify_send("极元健康签到结果", "\n".join(log_msgs) if log_msgs else "执行完成")
        print("消息推送完成")
    except Exception as e:
        print(f"推送异常：{e}")


if __name__ == "__main__":
    main()