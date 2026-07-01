"""
每天跑之前需要打开小程序如果跑起来就是2积分就是黑号/黑号无解
跑起来抽奖抽到现金显示待解锁需要购买码子去兑换
购买码子地址:https://www.jcw6.cn/login.php
本子支持所有功能任务+抽奖 CK有效期7天
环境变量mpcbh=备注#auth_token
#小程序://毛铺草本荟/lxJAUyTkGwBivyj
"""
import requests, json, re, os, sys, time, random, datetime, threading, hashlib, base64, urllib3, certifi
retrycount = 1 
environ = "mpcbh"
name = "꧁༺ 毛铺༒草本 ༻꧂"

def calculate_appsign(data, auth_token, sign_secret, param_order):
    """计算appsign"""
    apptime = str(int(datetime.datetime.now().timestamp()))
    sign_str = apptime
    for key in param_order:
        if key in data:
            sign_str += f"{key}{data[key]}"
    sign_str += sign_secret + auth_token
    md5_obj = hashlib.md5(sign_str.encode("utf-8"))
    md5_hex = md5_obj.hexdigest().upper()
    appsign = md5_hex[-10:]
    return apptime, appsign

def random_wait(min_sec=3, max_sec=8, print_log=False):
    """随机等待"""
    wait_time = random.randint(min_sec, max_sec)
    if print_log:
        print(f"⏳ 随机等待 {wait_time} 秒...")
    time.sleep(wait_time)

def daily_sign_in(auth_token, session):
    """每日签到"""
    try:
        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        sign_data = {"date": current_date}
        #print(f"☁️签到日期：{current_date}")
        apptime, appsign = calculate_appsign(sign_data, auth_token, SIGN_SECRET, ["date"])
        base_headers["apptime"] = apptime
        base_headers["appsign"] = appsign
        url = "https://mpb.jingjiu.com/proxy-he/api/FlanSignInDaily/adds"
        response = session.post(url=url,headers=base_headers,data=json.dumps(sign_data, ensure_ascii=False),timeout=15)
        result = response.json()
        if result.get("code") != 0:
            print(f"❌ 签到失败：{result.get('message', '未知错误')}")
            return result.get('message', '未知错误')
        point_today = result["data"].get("point_today", 0)
        point_tomorrow = result["data"].get("point_tomorrow", 0)
        if point_today > 0 or point_tomorrow > 0:
            print(f"☁️签到状态：{point_today} 积分")
        else:
            print(f"☁️签到状态：今日已签到")
        return "ok"
    except Exception as e:
        print(f"⭕签到异常：{str(e)}")

def haoyoubangbang_draw(auth_token, session):
    """好友帮帮"""
    try:
        print("☼ ――――  帮  帮  ―――― ☼")
        current_timestamp = int(datetime.datetime.now().timestamp())
        # 获取抽奖资格
        draw_get_data = {"activity_id": "5001","latitude":30.032270431518555,"longitude":120.86858367919922,"play_time_start": current_timestamp}
        apptime, appsign = calculate_appsign(draw_get_data, auth_token, SIGN_SECRET, ["activity_id", "latitude", "longitude", "play_time_start"])
        base_headers["apptime"] = apptime
        base_headers["appsign"] = appsign
        url_get = "https://mpb.jingjiu.com/proxy-he/api/BlzLongcaobenActivity/bangOnlineUserDrawGet"
        response_get = session.post(url=url_get,headers=base_headers,data=json.dumps(draw_get_data, ensure_ascii=False),timeout=15)
        result_get = response_get.json()
        if result_get.get("code") != 0:
            if "今日已参与" in result_get.get('message', '未知错误'):
                print(f"☁️活动游戏：已完成")
            else:
                print(f"⭕活动游戏：{result_get.get('message', '未知错误')}")
            return
        user_record_id = result_get["data"].get("user_record_id")
        if not user_record_id:
            print("⭕活动游戏：未获取到user_record_id，无法继续抽奖")
            return
        print(f"☁️活动游戏：游戏完成")
        #print(f"⏳ 等待{wait_time}秒，满足活动时间要求...")
        time.sleep(random.randint(3, 8))
        # 执行抽奖
        draw_do_data = {"user_record_id": user_record_id,"play_time_finish": int(datetime.datetime.now().timestamp())}
        apptime, appsign = calculate_appsign(draw_do_data, auth_token, SIGN_SECRET, ["user_record_id", "play_time_finish"])
        base_headers["apptime"] = apptime
        base_headers["appsign"] = appsign
        url_do = "https://mpb.jingjiu.com/proxy-he/api/BlzLongcaobenActivity/bangOnlineUserDraws"
        response_do = session.post(url=url_do,headers=base_headers,data=json.dumps(draw_do_data, ensure_ascii=False),timeout=15)
        result_do = response_do.json()
        if result_do.get("code") != 0:
            print(f"⭕抽奖失败：{result_do.get('message', '未知错误')}")
            return
        award_title = result_do["data"].get("awardLocal", {}).get("title", "")
        if not award_title:
            award_title = result_do["data"].get("award", {}).get("AwardName", "未知奖励")
        award_money = result_do["data"].get("awardLocal", {}).get("money", "0")
        print(f"🌈抽奖获得：{award_title}（{award_money}元）")
        try:
            award_code = result_do["data"].get("ucodeAward", {}).get("code", "")
            if award_code:
                #print(f"📌 奖励编码：{award_code}")
                pass
        except:
            #print(f"{result_do}")
            pass
    except Exception as e:
        print(f"❌ 抽奖任务异常：{str(e)}")

def shicaoxunyuan_draw(auth_token, session):
    """识草寻源"""
    try:
        print("☼ ――――  识  草  ―――― ☼")
        current_timestamp = int(datetime.datetime.now().timestamp())
        # 获取抽奖资格
        draw_get_data = {"play_time_start": current_timestamp,"use_type": "free"}
        apptime, appsign = calculate_appsign(draw_get_data, auth_token, SIGN_SECRET, ["play_time_start", "use_type"])
        base_headers["apptime"] = apptime
        base_headers["appsign"] = appsign
        url_get = "https://mpb.jingjiu.com/proxy-he/api/BlzLonglActivity/shicaoxunyuanUserDrawGet"
        response_get = session.post(url=url_get,headers=base_headers,data=json.dumps(draw_get_data, ensure_ascii=False),timeout=10)
        result_get = response_get.json()
        if result_get.get("code") != 0:
            if "今日游戏已完成" in result_get.get('message', '未知错误'):
                print(f"☁️活动游戏：已完成")
            else:
                print(f"⭕活动游戏：{result_get.get('message', '未知错误')}")
            return
        user_record_id = result_get["data"].get("user_record_id")
        if not user_record_id:
            print("⭕活动游戏：未获取到user_record_id，无法继续抽奖")
            return
        print(f"☁️活动游戏：游戏完成")
        #print(f"⏳ 等待{wait_time}秒，满足活动时间要求...")
        time.sleep(36)
        # 执行抽奖
        draw_do_data = {"play_time_finish": int(datetime.datetime.now().timestamp()),"user_record_id": user_record_id}
        apptime, appsign = calculate_appsign(draw_do_data, auth_token, SIGN_SECRET, ["play_time_finish", "user_record_id"])
        base_headers["apptime"] = apptime
        base_headers["appsign"] = appsign
        url_do = "https://mpb.jingjiu.com/proxy-he/api/BlzLonglActivity/shicaoxunyuanUserDraws"
        response_do = session.post(url=url_do,headers=base_headers,data=json.dumps(draw_do_data, ensure_ascii=False),timeout=15)
        result_do = response_do.json()
        if result_do.get("code") != 0:
            print(f"⭕抽奖失败：{result_do.get('message', '未知错误')}")
            return
        award_title = result_do["data"].get("awardLocal", {}).get("title", "")
        if not award_title:
            award_title = result_do["data"].get("award", {}).get("AwardName", "未知奖励")
        award_money = result_do["data"].get("awardLocal", {}).get("money", "0")
        print(f"🌈抽奖获得：{award_title}（{award_money}元）")
        try:
            award_code = result_do["data"].get("ucodeAward", {}).get("code", "")
            if award_code:
                #print(f"📌 奖励编码：{award_code}")
                pass
        except:
            #print(f"{result_do}")
            pass
    except Exception as e:
        print(f"⭕抽奖任务异常：{str(e)}")


def caobenshiyanshi_draw(auth_token, session):
    """草本实验室"""
    try:
        print("☼ ――――  草  本  ―――― ☼")
        current_timestamp = int(datetime.datetime.now().timestamp())
        # 获取抽奖资格
        draw_get_data = {"play_time_start": current_timestamp,"use_type": "free"}
        apptime, appsign = calculate_appsign(draw_get_data, auth_token, SIGN_SECRET, ["play_time_start", "use_type"])
        base_headers["apptime"] = apptime
        base_headers["appsign"] = appsign
        url_get = "https://mpb.jingjiu.com/proxy-he/api/BlzLonglActivity/caobenshiyanshiUserDrawGet"
        response_get = session.post(url=url_get,headers=base_headers,data=json.dumps(draw_get_data, ensure_ascii=False),timeout=15)
        result_get = response_get.json()
        if result_get.get("code") != 0:
            if "今日游戏已完成" in result_get.get('message', '未知错误'):
                print(f"☁️活动游戏：已完成")
            else:
                print(f"⭕活动游戏：{result_get.get('message', '未知错误')}")
            return
        user_record_id = result_get["data"].get("user_record_id")
        if not user_record_id:
            print("⭕活动游戏：未获取到user_record_id，无法继续抽奖")
            return
        print(f"☁️活动游戏：游戏完成")
        #print(f"⏳ 等待{wait_time}秒，满足活动时间要求...")
        time.sleep(36)
        # 执行抽奖
        draw_do_data = {"play_time_finish": int(datetime.datetime.now().timestamp()),"user_record_id": user_record_id}
        apptime, appsign = calculate_appsign(draw_do_data, auth_token, SIGN_SECRET, ["play_time_finish", "user_record_id"])
        base_headers["apptime"] = apptime
        base_headers["appsign"] = appsign
        url_do = "https://mpb.jingjiu.com/proxy-he/api/BlzLonglActivity/caobenshiyanshiUserDraws"
        response_do = session.post(url=url_do,headers=base_headers,data=json.dumps(draw_do_data, ensure_ascii=False),timeout=15)
        result_do = response_do.json()
        if result_do.get("code") != 0:
            print(f"⭕抽奖失败：{result_do.get('message', '未知错误')}")
            return
        award_title = result_do["data"].get("awardLocal", {}).get("title", "")
        if not award_title:
            award_title = result_do["data"].get("award", {}).get("AwardName", "未知奖励")
        award_jifen = result_do["data"].get("awardLocal", {}).get("jifen", "0")
        print(f"🌈抽奖获得：{award_title}（{award_jifen}积分）")
        try:
            award_code = result_do["data"].get("ucodeAward", {}).get("code", "")
            if award_code:
                #print(f"📌 奖励编码：{award_code}")
                pass
        except:
            #print(f"{result_do}")
            pass
    except Exception as e:
        print(f"⭕抽奖任务异常：{str(e)}")


def wumian_draw(auth_token, session):
    """无冕之王"""
    try:
        print("☼ ――――  无  冕  ―――― ☼")
        current_timestamp = int(datetime.datetime.now().timestamp())
        # 获取抽奖资格
        draw_get_data = {"activity_id": "1001","play_time_start": current_timestamp}
        apptime, appsign = calculate_appsign(draw_get_data, auth_token, SIGN_SECRET, ["activity_id", "play_time_start"])
        base_headers["apptime"] = apptime
        base_headers["appsign"] = appsign
        url_get = "https://mpb.jingjiu.com/proxy-he/api/BlzLongcaobenActivity/wumianUserDrawGet"
        response_get = session.post(url=url_get,headers=base_headers,data=json.dumps(draw_get_data, ensure_ascii=False),timeout=15)
        result_get = response_get.json()
        if result_get.get("code") != 0:
            if "今日游戏已完成" in result_get.get('message', '未知错误'):
                print(f"☁️活动游戏：已完成")
            else:
                print(f"⭕活动游戏：{result_get.get('message', '未知错误')}")
            return
        user_record_id = result_get["data"].get("user_record_id")
        if not user_record_id:
            print("⭕活动游戏：未获取到user_record_id，无法继续抽奖")
            return
        print(f"☁️活动游戏：游戏完成")
        #print(f"⏳ 等待{wait_time}秒，满足活动时间要求...")
        time.sleep(random.randint(3, 8))
        # 执行抽奖
        draw_do_data = {"user_record_id": user_record_id,"play_time_finish": int(datetime.datetime.now().timestamp())}
        apptime, appsign = calculate_appsign(draw_do_data, auth_token, SIGN_SECRET, ["user_record_id", "play_time_finish"])
        base_headers["apptime"] = apptime
        base_headers["appsign"] = appsign
        url_do = "https://mpb.jingjiu.com/proxy-he/api/BlzLongcaobenActivity/wumianUserDraws"
        response_do = session.post(url=url_do,headers=base_headers,data=json.dumps(draw_do_data, ensure_ascii=False),timeout=15)
        result_do = response_do.json()
        if result_do.get("code") != 0:
            print(f"⭕抽奖失败：{result_do.get('message', '未知错误')}")
            return
        award_title = result_do["data"].get("awardLocal", {}).get("title", "")
        if not award_title:
            award_title = result_do["data"].get("award", {}).get("AwardName", "未知奖励")
        award_money = result_do["data"].get("awardLocal", {}).get("money", "0")
        print(f"🌈抽奖获得：{award_title}（{award_money}元）")
        try:
            award_code = result_do["data"].get("ucodeAward", {}).get("code", "")
            if award_code:
                #print(f"📌 奖励编码：{award_code}")
                pass
        except:
            #print(f"{result_do}")
            pass
    except Exception as e:
        print(f"❌ 抽奖任务异常：{str(e)}")


def subscribe_task(auth_token, session, tag):
    """订阅任务"""
    try:
        url = "https://mpb.jingjiu.com/proxy-he/api/BlzAppletIndex/taskSubscribeMessage"
        data = {"tag": tag}
        apptime, appsign = calculate_appsign(data, auth_token,SIGN_SECRET,["tag"])
        base_headers["apptime"] = apptime
        base_headers["appsign"] = appsign
        response = session.post(url, headers=base_headers, data=json.dumps(data), timeout=10)
        result = response.json()
        if result.get("code") == 0:
            if "data" in result and "task" in result["data"]:
                task_name = result["data"]["task"].get("name", "未知任务")
                point = result["data"].get("point", 0)
                print(f"☁️【订阅_{task_name[-6:]}】： {point} 积分")
            else:
                print(f"⭕【订阅_{tag[-6:]}】：缺少数据字段")
        else:
            if "已达到上限" in result.get('message', '未知错误'):
                print(f"☁️【订阅_{tag[-6:]}】：已订阅")
            else:
                print(f"⭕【订阅_{tag[-6:]}】：{result.get('message', '未知错误')}")
    except Exception as e:
        print(f"⭕【订阅_{tag[-6:]}】：{str(e)}")


def view_video_task(auth_token, session, video_id):
    """观看视频任务"""
    try:
        url = "https://mpb.jingjiu.com/proxy-he/api/BlzAppletIndex/taskViewVideoView"
        data = {"video_id": video_id}
        apptime, appsign = calculate_appsign(data, auth_token,SIGN_SECRET,["video_id"])
        base_headers["apptime"] = apptime
        base_headers["appsign"] = appsign
        response = session.post(url, headers=base_headers, data=json.dumps(data), timeout=10)
        result = response.json()
        if result.get("code") != 0:
            print(f"⭕【视频_{video_id[-6:]}】：{result.get('message', '接口返回错误')}")
            return
        if "data" not in result:
            print(f"⭕【视频_{video_id[-6:]}】：缺少data字段")
            return
        data = result["data"]
        if "task" not in data :
            if "point" in data:
                print(f"☁️【视频_{video_id[-6:]}】：已观看")
            else:
                print(f"⭕【视频_{video_id[-6:]}】：缺少task字段")
                print(f"⭕【视频_{video_id[-6:]}】接口返回内容：{json.dumps(result, ensure_ascii=False)}")
            return
        task_name = data["task"].get("name", "未知视频任务")
        point = data.get("point", 0)
        print(f"☁️【视频_{task_name[-6:]}】：{point} 积分")
    except Exception as e:
        print(f"⭕【视频_{video_id[-6:]}】：{str(e)}")


def query_user_points(auth_token, session):
    """查询用户积分"""
    try:
        user_info_data = {}
        apptime, appsign = calculate_appsign(user_info_data, auth_token, SIGN_SECRET, [])
        base_headers["apptime"] = apptime
        base_headers["appsign"] = appsign
        url = "https://mpb.jingjiu.com/proxy-he/api/BlzAppletIndex/userInfoV2025"
        response = session.post(url=url,headers=base_headers,data=json.dumps(user_info_data, ensure_ascii=False),timeout=15)
        result = response.json()
        if result.get("code") != 0:
            print(f"⭕当前积分：{result.get('message', '未知错误')}")
            return "未知"
        return result["data"].get("user_show", {}).get("point", "未知")
    except Exception as e:
        print(f"⭕积分查询异常：{str(e)}")
        return "查询失败"

def lottery(auth_token, session):
    """抽奖"""
    try:
        for _ in range(5):
            user_info_data = {}
            url = "https://mpb.jingjiu.com/proxy-he/api/game/FlanTurntable/awardDraw"
            response = session.post(url=url,headers=base_headers,data=json.dumps(user_info_data, ensure_ascii=False),timeout=15)
            result = response.json()
            #print(result)
            if "成功" in result["message"]:
                name = result["data"]["award"]["name"]
                if "积分" in name:
                    print(f"☁️【积分抽奖】：{name}")
                elif "谢谢参与" in name:
                    print(f"☁️【积分抽奖】：谢谢参与")
                else:
                    print(f"🌈【积分抽奖】：{name}")
                time.sleep(3)
            else:
                print(f"☁️【积分抽奖】：次数用尽")
                break
    except Exception as e:
        print(f"⭕积分查询异常：{str(e)}")
        return "查询失败"


def run(auth_token, session):
    """执行单个账号的所有任务"""
    # 执行签到任务
    result = daily_sign_in(auth_token, session)
    if "授权过期" in result:
        return
    #------------活动-----------
    #好友帮帮
    random_wait()
    haoyoubangbang_draw(auth_token, session)
    #识草寻源
    random_wait()
    shicaoxunyuan_draw(auth_token, session)
    #草本实验室
    random_wait()
    caobenshiyanshi_draw(auth_token, session)
    #无冕之王
    random_wait()
    wumian_draw(auth_token, session)
    #------------日常-----------
    print("☼ ――――  订  阅  ―――― ☼")
    random_wait()
    SUBSCRIBE_TAGS = ["subscribe_message_202410","subscribe_message_suyuan","subscribe_message_applet"]
    for tag in SUBSCRIBE_TAGS:
        subscribe_task(auth_token, session, tag)
        if tag != SUBSCRIBE_TAGS[-1]:
            random_wait(1, 3)
    print("☼ ――――  视  频  ―――― ☼")
    random_wait()
    VIDEO_IDS = ["video-117"]
    for video_id in VIDEO_IDS:
        view_video_task(auth_token, session, video_id)
        if video_id != VIDEO_IDS[-1]:
            random_wait(1, 3)
    print("☼ ――――  抽  奖  ―――― ☼")
    # 抽奖
    random_wait(1, 3)
    lottery(auth_token, session)
    print("☼ ――――  信  息  ―――― ☼")
    # 查询最终积分
    points = query_user_points(auth_token, session)
    print(f"☁️当前积分：{points} 积分")

def main():
    global id,base_headers
    if os.environ.get(environ):
        ck = os.environ.get(environ)
    else:
        ck = ""
        if ck == "":
            print("⭕请设置变量")
            sys.exit()
    ck_run = ck.split('\n')
    ck_run = [item for item in ck_run if item]
    print(f"{' ' * 7}{name}\n\n")
    print(f"-------- ☁️ 开 始  执 行 ☁️ --------")
    base_headers = {
        "content-length": "2",
        "content-type": "application/json",
        "x-version": "0.0.1",
        "authorization": "",
        "charset": "utf-8",
        "user-agent": "Mozilla/5.0 (Linux; Android 10; MI 8 Build/QKQ1.190828.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/138.0.7204.180 Mobile Safari/537.36 XWEB/1380327 MMWEBSDK/20250904 MMWEBID/6533 MicroMessenger/8.0.65.2960(0x28004151) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android",
    }
    for i, ck_run_n in enumerate(ck_run):
        try:
            session = requests.session()
            comment,auth_token = ck_run_n.strip().split("#", 1)
            base_headers["Authorization"] = auth_token
            print(f"\n\n 账号 [{i + 1}/{len(ck_run)}]:")
            id = comment[:3] + "*****" + comment[-3:] if len(comment) > 6 else comment
            print(f"☁️当前账号：{id}")
            run(auth_token, session)
        except Exception as e:
            print(f"❌ 账号处理异常：{str(e)}")
    print(f"\n\n-------- ☁️ 执 行  结 束 ☁️ --------\n\n")


if __name__ == '__main__':
    SIGN_SECRET = "DYSHJS^M&.YXZRGS"
    main()