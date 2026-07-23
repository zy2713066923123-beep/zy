# cron: 19 12,15 * * *
import requests
# name: 芳华未来
import time
import random
import sys
import os
import json
import threading
import base64
import signal
from datetime import datetime, timedelta

try:
    from notify import send as notify_send
except ImportError:
    print("未找到 notify.py，将仅在控制台输出日志。")
    def notify_send(title, content):
        print(f"--- 通知 ---\n{title}\n{content}\n-------------")

# ====================================== 【防检测核心配置区】 ======================================
BASE_URL = "https://api.cdwjyyh.com"

# -------------------------- 【多账号登录配置】 --------------------------
TOKEN_CACHE_FILE = "fhb_tokens.json"
ENV_VAR_NAME = "fhb"
LOGIN_TYPE = 1
LOGIN_SOURCE = "yyb"

# -------------------------- 【行为模拟配置（最重要）】 --------------------------
WATCH_TIME_MIN = 12    # 最短观看12秒
WATCH_TIME_MAX = 65    # 最长观看65秒
PLAY_3S_DELAY_MIN = 3.2
PLAY_3S_DELAY_MAX = 7.5
NEXT_VIDEO_DELAY_MIN = 1.5
NEXT_VIDEO_DELAY_MAX = 12.0
SKIP_VIDEO_PROBABILITY = 15  # 15%概率看3秒跳过
EXIT_MIDWAY_PROBABILITY = 8  # 8%概率中途退出
BATCH_VIDEO_COUNT_MIN = 5
BATCH_VIDEO_COUNT_MAX = 18
BATCH_REST_TIME_MIN = 14
BATCH_REST_TIME_MAX = 300

# -------------------------- 【芳华币领取配置】 --------------------------
INTEGRAL_INTERVAL = 10  # 每10秒领取一次（仅完整观看）
INTEGRAL_TYPE = 2

# -------------------------- 【请求特征配置】 --------------------------
REQUEST_CONNECT_TIMEOUT = 3
REQUEST_READ_TIMEOUT = 5
MAX_RETRIES = 2
USER_AGENT_POOL = [
       "Mozilla/5.0 (Linux; Android 16; 2509FPN0BC Build/BP2A.250605.031.A3; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/140.0.7339.207 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 16; 24117RN2BC Build/BP2A.250610.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/141.0.7355.116 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 16; 23127PN0CC Build/BP2A.250520.015; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/142.0.7362.103 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 15; 22101320C Build/TKQ1.221114.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/139.0.7296.136 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 15; 2304FPN6DC Build/TKQ1.230405.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/140.0.7339.118 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 15; 24069PN2DC Build/TKQ1.240610.003; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/141.0.7355.78 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 14; 22081212C Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/139.0.7296.98 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 14; 23013RK75C Build/TP1A.230105.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/140.0.7339.86 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 14; V2359A Build/TP1A.220905.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/141.0.7355.56 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 14; PHM110 Build/TP1A.221013.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/142.0.7362.67 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 16; 24031PN0DC Build/BP2A.250415.022; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/139.0.7296.152 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 16; 23090RAC6C Build/BP2A.250501.009; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/140.0.7339.156 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 15; 2211133G Build/TKQ1.221128.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/141.0.7355.101 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 15; 23116PN5BC Build/TKQ1.231108.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/142.0.7362.89 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 14; 2112123AC Build/TP1A.211212.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/139.0.7296.76 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 14; 2206122SC Build/TP1A.220624.003; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/140.0.7339.64 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 16; 2503FPN0BC Build/BP2A.250320.011; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/141.0.7355.34 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 16; 24090PN2AC Build/BP2A.250601.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/142.0.7362.45 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 15; 23076PN3CC Build/TKQ1.230710.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/139.0.7296.114 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 15; 24041PN0DC Build/TKQ1.240415.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/140.0.7339.132 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0",
    "Mozilla/5.0 (Linux; Android 16; 2509FPN0BC Build/BP2A.250605.031.A3; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/140.0.7339.207 Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0"
]

# -------------------------- 【脚本运行配置】 --------------------------
MAX_RUN_HOURS_PER_ACCOUNT = 2  # 每个账号最多运行2小时
START_DELAY_MIN = 0  # 账号启动最小延迟（秒）
START_DELAY_MAX = 15  # 账号启动最大延迟（秒）- 避免同时启动
HEARTBEAT_INTERVAL_BASE = 600
HEARTBEAT_INTERVAL_JITTER = 120
# ==================================================================================================

# 全局变量（已去重）
global_exit_flag = False
all_threads = []
all_accounts_data = []
data_lock = threading.Lock()
token_lock = threading.Lock()
print_lock = threading.Lock()

# ============================== 【终极强制退出函数（核心修复）】 ==============================
def force_exit(signum, frame):
    """
    收到停止信号时的终极处理函数
    收集所有账号数据，统一推送完整报告，然后暴力自毁
    """
    global global_exit_flag
    
    with print_lock:
        print("\n\n🛑 收到停止信号，正在强制终止所有线程...")
    
    # 设置全局退出标志
    global_exit_flag = True
    
    # 等待10秒让所有线程完成数据收集
    time.sleep(10)
    
    # 生成完整的统一报告
    full_report = "📊 芳华币多账号运行汇总报告\n"
    full_report += "="*40 + "\n\n"
    
    total_gain = 0
    total_videos_all = 0
    total_integral_all = 0
    
    # 遍历所有账号的数据
    for idx, data in enumerate(all_accounts_data, 1):
        full_report += f"👤 账号 {idx}: {data['phone']}\n"
        full_report += f"   ⏰ 运行时长: {data['run_time']} 小时\n"
        full_report += f"   🎬 完成视频: {data['total_videos']} 个\n"
        full_report += f"   💰 领币次数: {data['total_integral']} 次\n"
        full_report += f"   💵 本次获得: {data['actual_gain'] if data['actual_gain'] >= 0 else '计算失败'} 芳华币\n"
        full_report += f"   🚪 退出原因: {data['exit_reason']}\n\n"
        
        # 统计总和
        if data['actual_gain'] >= 0:
            total_gain += data['actual_gain']
        total_videos_all += data['total_videos']
        total_integral_all += data['total_integral']
    
    # 添加汇总信息
    full_report += "📈 本次运行汇总\n"
    full_report += "="*40 + "\n"
    full_report += f"✅ 运行账号数: {len(all_accounts_data)} 个\n"
    full_report += f"🎬 总完成视频: {total_videos_all} 个\n"
    full_report += f"💰 总领币次数: {total_integral_all} 次\n"
    full_report += f"💵 总获得芳华币: {total_gain} 个\n"
    full_report += f"🕐 结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    # 添加账号配置信息
    full_report += "📋 所有账号密码:\n"
    # 从环境变量重新解析所有账号
    env_str = os.environ.get(ENV_VAR_NAME, "")
    for item in env_str.replace("&", "\n").splitlines():
        parts = item.strip().split("#")
        if len(parts) >= 2:
            full_report += f"{parts[0]}#{parts[1]}\n"
    
    # 统一推送完整报告
    with print_lock:
        print("📤 正在推送运行报告...")
    
    try:
        notify_send(f"芳华币脚本已停止 | 共获得 {total_gain} 币", full_report)
        with print_lock:
            print("✅ 推送成功")
    except Exception as e:
        with print_lock:
            print(f"❌ 推送异常: {str(e)}")
    
    # 等待3秒让推送完全完成
    time.sleep(3)
    
    # 终极杀招：暴力自毁
    with print_lock:
        print("💥 执行进程自毁，确保无任何残留")
    os.kill(os.getpid(), signal.SIGKILL)

# 注册所有退出信号
signal.signal(signal.SIGTERM, force_exit)  # 青龙面板停止信号
signal.signal(signal.SIGINT, force_exit)   # Ctrl+C停止信号
signal.signal(signal.SIGQUIT, force_exit)  # 强制退出信号

# ============================== 【Token+JPushId缓存模块（线程安全）】 ==============================
def load_token_cache():
    """加载本地缓存文件，包含token和jpushId"""
    with token_lock:
        if not os.path.exists(TOKEN_CACHE_FILE):
            return {}
        try:
            with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            with print_lock:
                print(f"⚠️  加载缓存失败: {e}")
            return {}

def save_token_cache(cache):
    """保存token和jpushId到本地缓存文件"""
    with token_lock:
        try:
            with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            with print_lock:
                print("✅ 缓存已更新")
        except Exception as e:
            with print_lock:
                print(f"❌ 保存缓存失败: {e}")

def login(phone, password, random_instance):
    """使用手机号+密码登录，jpushId自动填充"""
    try:
        login_headers = {
            "User-Agent": random_instance.choice(USER_AGENT_POOL),
            "Content-Type": "application/json;charset=UTF-8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        data = {
            "phone": phone,
            "password": password,
            "jpushId": "local_notify_mode",
            "loginType": LOGIN_TYPE,
            "source": LOGIN_SOURCE
        }
        response = requests.post(
            f"{BASE_URL}/app/app/login",
            headers=login_headers,
            json=data,
            timeout=(REQUEST_CONNECT_TIMEOUT, REQUEST_READ_TIMEOUT)
        )
        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 200:
                token = result.get("token")
                user_id = result.get("user", {}).get("userId")
                with print_lock:
                    print(f"✅ 账号 {phone} 登录成功")
                return token, user_id
            else:
                with print_lock:
                    print(f"❌ 账号 {phone} 登录失败: {result.get('msg', '账号/密码/jpushId错误')}")
                return None, None
        with print_lock:
            print(f"❌ 账号 {phone} 登录请求失败: 状态码 {response.status_code}")
        return None, None
    except Exception as e:
        with print_lock:
            print(f"❌ 账号 {phone} 登录异常: {e}")
        return None, None

def verify_token(token, random_instance):
    """验证Token是否有效"""
    try:
        test_headers = {
            "User-Agent": random_instance.choice(USER_AGENT_POOL),
            "AppToken": token,
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        response = requests.get(
            f"{BASE_URL}/app/user/getUserInfo",
            headers=test_headers,
            timeout=(REQUEST_CONNECT_TIMEOUT, REQUEST_READ_TIMEOUT)
        )
        return response.status_code == 200 and response.json().get("code") == 200
    except Exception:
        return False

def get_valid_credentials(phone, password, random_instance):
    """获取有效凭证：优先缓存，失效自动重登"""
    cache = load_token_cache()
    cached_data = cache.get(phone, {})
    cached_token = cached_data.get("token")
    
    if cached_token:
        with print_lock:
            print(f"🔍 账号 {phone} 检测到缓存Token，正在验证有效性...")
        if verify_token(cached_token, random_instance):
            with print_lock:
                print(f"✅ 账号 {phone} 缓存Token有效")
            test_headers = {"User-Agent": random_instance.choice(USER_AGENT_POOL), "AppToken": cached_token}
            response = requests.get(f"{BASE_URL}/app/user/getUserInfo", headers=test_headers, timeout=10)
            user_id = response.json().get("user", {}).get("userId")
            return cached_token, user_id
        with print_lock:
            print(f"⚠️  账号 {phone} 缓存Token已失效，正在重新登录...")
    
    token, user_id = login(phone, password, random_instance)
    if token:
        cache[phone] = {"token": token}
        save_token_cache(cache)
    return token, user_id

# ============================== 【基础请求与接口模块（独立随机）】 ==============================
def request_with_retry(session, method, url, random_instance, **kwargs):
    """带随机超时和重试的请求函数（独立随机）"""
    for attempt in range(MAX_RETRIES):
        if global_exit_flag:
            return None
            
        try:
            timeout = (
                REQUEST_CONNECT_TIMEOUT,
                random_instance.uniform(REQUEST_READ_TIMEOUT, REQUEST_READ_TIMEOUT + 2)
            )
            response = session.request(method, url, timeout=timeout, **kwargs)
            
            if random_instance.random() < 0.01:
                raise requests.exceptions.ConnectionError("模拟网络波动")
            
            return response
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                with print_lock:
                    print(f"❌ 请求失败，已重试{MAX_RETRIES}次: {e}")
                return None
            retry_delay = (2 ** attempt) + random_instance.uniform(1, 3)
            with print_lock:
                print(f"⚠️  请求失败，{retry_delay:.1f}秒后重试...")
            time.sleep(retry_delay)
    return None

def create_logs(session, user_id, random_instance):
    try:
        response = request_with_retry(
            session, "POST", f"{BASE_URL}/app/common/createLogs", random_instance,
            json={"userId": str(user_id)}
        )
        return response and response.status_code == 200
    except Exception:
        return False

def get_app_config(session, random_instance):
    try:
        response = request_with_retry(session, "GET", f"{BASE_URL}/app/common/getAppPageConfig", random_instance)
        return response and response.status_code == 200
    except Exception:
        return False

def daily_sign(session, random_instance):
    try:
        response = request_with_retry(session, "POST", f"{BASE_URL}/app/integral/sign", random_instance, json={})
        if response and response.status_code == 200:
            result = response.json()
            if result.get("code") == 200:
                with print_lock:
                    print("✅ 每日签到成功")
                return True
            with print_lock:
                print(f"⚠️  签到失败: {result.get('msg', '今日已签到')}")
        return False
    except Exception as e:
        with print_lock:
            print(f"❌ 签到请求失败: {e}")
        return False

def get_video_list(session, random_instance, page_num=1, page_size=10):
    try:
        params = {"keyword": "", "isRandom": 1, "videoId": "", "pageNum": page_num, "pageSize": page_size}
        response = request_with_retry(
            session, "GET", f"{BASE_URL}/app/video/getVideoList-new", random_instance, params=params
        )
        if response and response.status_code == 200:
            result = response.json()
            if result.get("code") == 200:
                return result["data"]["list"]
        return []
    except Exception as e:
        with print_lock:
            print(f"❌ 获取视频列表失败: {e}")
        return []

def report_video_event(session, video_id, event, random_instance):
    try:
        data = {"videoId": str(video_id), "event": event}
        response = request_with_retry(
            session, "POST", f"{BASE_URL}/app/video/track", random_instance, json=data
        )
        return response and response.status_code == 200
    except Exception:
        return False

def send_heartbeat(session, random_instance):
    try:
        response = request_with_retry(
            session, "POST", f"{BASE_URL}/app/portrait/heartbeat", random_instance,
            json={"action": "HEARTBEAT"}
        )
        if response and response.status_code == 200:
            with print_lock:
                print("💓 心跳包发送成功")
            return True
        return False
    except Exception as e:
        with print_lock:
            print(f"❌ 心跳包发送失败: {e}")
        return False

def add_integral(session, phone, random_instance):
    try:
        response = request_with_retry(
            session, "POST", f"{BASE_URL}/app/integral/addIntegral", random_instance,
            json={"type": INTEGRAL_TYPE}
        )
        if response and response.status_code == 200:
            result = response.json()
            if result.get("code") == 200:
                with print_lock:
                    print(f"   ├─ 💰 账号 {phone} {result.get('msg', '领取成功')}")
                return True
            with print_lock:
                print(f"   ├─ ⚠️  账号 {phone} 领取失败: {result.get('msg', '未知错误')}")
        return False
    except Exception as e:
        with print_lock:
            print(f"   ├─ ❌ 账号 {phone} 领取请求失败: {e}")
        return False

def get_user_integral(session, random_instance):
    try:
        response = request_with_retry(session, "GET", f"{BASE_URL}/app/user/getUserInfo", random_instance)
        if response and response.status_code == 200:
            result = response.json()
            if result.get("code") == 200:
                return result["user"]["integral"]
        return None
    except Exception as e:
        with print_lock:
            print(f"❌ 查询芳华币失败: {e}")
        return None

# ============================== 【最终报告模块（仅控制台打印）】 ==============================
def send_final_report(session, phone, total_videos, total_integral, initial_integral, start_time, exit_reason, random_instance, all_accounts):
    """
    生成并打印最终运行报告，同时收集数据到全局变量
    """
    current_integral = get_user_integral(session, random_instance)
    run_time = round((time.time() - start_time) / 3600, 2)
    actual_gain = current_integral - initial_integral if (current_integral and initial_integral) else -1
    
    # 生成控制台打印的报告（无敏感信息）
    console_report = f"""📊 自动刷芳华币运行报告
👤 账号: {phone}
⏰ 运行时长: {run_time} 小时
🎬 完成视频: {total_videos} 个
💰 领币次数: {total_integral} 次
💵 初始余额: {initial_integral if initial_integral else '查询失败'} 芳华币
💵 当前余额: {current_integral if current_integral else '查询失败'} 芳华币
📈 本次获得: {actual_gain if actual_gain >= 0 else '计算失败'} 芳华币
🚪 退出原因: {exit_reason}
🕐 结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    # 在控制台打印报告
    with print_lock:
        print("\n" + "="*60)
        print(console_report)
        print("="*60 + "\n")
    
    # 收集当前账号的运行数据到全局变量
    with data_lock:
        all_accounts_data.append({
            "phone": phone,
            "run_time": run_time,
            "total_videos": total_videos,
            "total_integral": total_integral,
            "initial_integral": initial_integral,
            "current_integral": current_integral,
            "actual_gain": actual_gain,
            "exit_reason": exit_reason
        })

# ============================== 【单账号独立运行逻辑】 ==============================
def run_single_account(phone, password, random_instance, all_accounts):
    """单个账号的完整运行流程（完全独立）"""
    with print_lock:
        print(f"\n{'='*60}")
        print(f"🚀 账号 {phone} 已启动")
        print(f"{'='*60}\n")
    
    token, user_id = get_valid_credentials(phone, password, random_instance)
    if not token or not user_id:
        with print_lock:
            print(f"❌ 账号 {phone} 获取身份凭证失败，跳过")
        return
    
    session = requests.Session()
    user_agent = random_instance.choice(USER_AGENT_POOL)
    session.headers.update({
        "User-Agent": user_agent,
        "AppToken": token,
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    })
    
    account_start = time.time()
    last_heartbeat = time.time()
    total_videos = 0
    total_integral = 0
    batch_count = 0
    batch_target = random_instance.randint(BATCH_VIDEO_COUNT_MIN, BATCH_VIDEO_COUNT_MAX)
    
    with print_lock:
        print(f"🔍 账号 {phone} 正在查询初始芳华币余额...")
    initial_integral = get_user_integral(session, random_instance)
    if initial_integral is not None:
        with print_lock:
            print(f"✅ 账号 {phone} 初始芳华币余额: {initial_integral}\n")
    else:
        with print_lock:
            print(f"⚠️  账号 {phone} 初始芳华币查询失败\n")
    
    time.sleep(random_instance.uniform(2, 5))
    create_logs(session, user_id, random_instance)
    time.sleep(random_instance.uniform(1, 3))
    get_app_config(session, random_instance)
    time.sleep(random_instance.uniform(1, 2))
    daily_sign(session, random_instance)
    
    try:
        while True:
            if global_exit_flag:
                with print_lock:
                    print(f"\n🛑 账号 {phone} 收到退出信号，立即停止")
                send_final_report(session, phone, total_videos, total_integral, initial_integral, account_start, "收到停止信号", random_instance, all_accounts)
                break
            
            if time.time() - account_start > MAX_RUN_HOURS_PER_ACCOUNT * 3600:
                with print_lock:
                    print(f"\n⏰ 账号 {phone} 已到达最大运行时间")
                send_final_report(session, phone, total_videos, total_integral, initial_integral, account_start, "到达最大运行时间", random_instance, all_accounts)
                break
            
            if batch_count >= batch_target:
                rest_time = random_instance.uniform(BATCH_REST_TIME_MIN, BATCH_REST_TIME_MAX)
                with print_lock:
                    print(f"\n😴 账号 {phone} 连续看了 {batch_count} 个视频，休息 {rest_time:.1f} 秒...")
                
                for _ in range(int(rest_time)):
                    if global_exit_flag:
                        break
                    time.sleep(1)
                
                batch_count = 0
                batch_target = random_instance.randint(BATCH_VIDEO_COUNT_MIN, BATCH_VIDEO_COUNT_MAX)
                with print_lock:
                    print(f"🔄 账号 {phone} 下一批将连续看 {batch_target} 个视频\n")
            
            video_list = get_video_list(session, random_instance)
            if not video_list:
                with print_lock:
                    print(f"⚠️  账号 {phone} 没有获取到视频，等待1分钟后重试")
                
                for _ in range(60):
                    if global_exit_flag:
                        break
                    time.sleep(1)
                continue
            
            random_instance.shuffle(video_list)
            
            for video in video_list:
                if global_exit_flag or time.time() - account_start > MAX_RUN_HOURS_PER_ACCOUNT * 3600:
                    break
                
                video_id = video["id"]
                video_title = video["title"][:18] + "..." if len(video["title"]) > 18 else video["title"]
                with print_lock:
                    print(f"📺 账号 {phone} 正在观看: {video_title}")
                
                if report_video_event(session, video_id, "PLAY", random_instance):
                    with print_lock:
                        print("   ├─ 开始播放 ✓")
                
                wait_3s = random_instance.uniform(PLAY_3S_DELAY_MIN, PLAY_3S_DELAY_MAX)
                time.sleep(wait_3s)
                if report_video_event(session, video_id, "PLAY_3S", random_instance):
                    with print_lock:
                        print(f"   ├─ 3秒观看 ✓ (等待了 {wait_3s:.1f} 秒)")
                
                if random_instance.random() < SKIP_VIDEO_PROBABILITY / 100:
                    with print_lock:
                        print("   └─ ⏭️  不喜欢这个视频，直接跳过")
                    total_videos += 1
                    batch_count += 1
                    with print_lock:
                        print(f"✅ 账号 {phone} 累计完成: {total_videos} 个视频 | 累计领币: {total_integral} 次\n")
                    time.sleep(random_instance.uniform(NEXT_VIDEO_DELAY_MIN * 1.5, NEXT_VIDEO_DELAY_MAX * 1.5))
                    continue
                
                watch_time = random_instance.uniform(WATCH_TIME_MIN, WATCH_TIME_MAX)
                
                if random_instance.random() < EXIT_MIDWAY_PROBABILITY / 100:
                    watch_time = watch_time * random_instance.uniform(0.3, 0.7)
                    with print_lock:
                        print(f"   ├─ 模拟中途退出，只看 {watch_time:.1f} 秒")
                    time.sleep(watch_time)
                    with print_lock:
                        print("   └─ ❌ 未完成观看（不领取芳华币）")
                    total_videos += 1
                    batch_count += 1
                    with print_lock:
                        print(f"✅ 账号 {phone} 累计完成: {total_videos} 个视频 | 累计领币: {total_integral} 次\n")
                    time.sleep(random_instance.uniform(NEXT_VIDEO_DELAY_MIN, NEXT_VIDEO_DELAY_MAX))
                    continue
                
                elapsed = 0
                last_claim = 0
                while elapsed < watch_time:
                    if global_exit_flag:
                        break
                        
                    time.sleep(1)
                    elapsed += 1
                    
                    if elapsed - last_claim >= INTEGRAL_INTERVAL:
                        if add_integral(session, phone, random_instance):
                            total_integral += 1
                        last_claim = elapsed
                    
                    if time.time() - account_start > MAX_RUN_HOURS_PER_ACCOUNT * 3600:
                        break
                
                if report_video_event(session, video_id, "COMPLETE", random_instance):
                    with print_lock:
                        print(f"   └─ 完成观看 ✓ (观看了 {elapsed:.1f} 秒)")
                
                total_videos += 1
                batch_count += 1
                with print_lock:
                    print(f"✅ 账号 {phone} 累计完成: {total_videos} 个视频 | 累计领币: {total_integral} 次\n")
                
                next_delay = random_instance.uniform(NEXT_VIDEO_DELAY_MIN, NEXT_VIDEO_DELAY_MAX)
                with print_lock:
                    print(f"⏳ 账号 {phone} 等待 {next_delay:.1f} 秒后进入下一个视频...\n")
                time.sleep(next_delay)
                
                heartbeat_interval = HEARTBEAT_INTERVAL_BASE + random_instance.uniform(-HEARTBEAT_INTERVAL_JITTER, HEARTBEAT_INTERVAL_JITTER)
                if time.time() - last_heartbeat > heartbeat_interval:
                    send_heartbeat(session, random_instance)
                    last_heartbeat = time.time()
                    with print_lock:
                        print()
    
    except Exception as e:
        with print_lock:
            print(f"\n❌ 账号 {phone} 运行出错: {e}")
        send_final_report(session, phone, total_videos, total_integral, initial_integral, account_start, f"运行出错: {str(e)}", random_instance, all_accounts)
    finally:
        session.close()
        with print_lock:
            print(f"\n👋 账号 {phone} 任务已结束")

# ============================== 【主程序入口（并发调度）】 ==============================
def main():
    global all_threads
    
    print("="*60)
    print("🚀 多账号并发自动刷芳华币脚本")
    print(f"📌 单账号最大运行时间: {MAX_RUN_HOURS_PER_ACCOUNT} 小时")
    print(f"📌 随机跳过概率: {SKIP_VIDEO_PROBABILITY}% | 中途退出概率: {EXIT_MIDWAY_PROBABILITY}%")
    print(f"📌 芳华币规则: 仅完整观看每{INTEGRAL_INTERVAL}秒领取一次")
    print(f"📌 缓存文件: {TOKEN_CACHE_FILE} (自动保存token和jpushId)")
    print(f"📌 环境变量格式: 手机号#密码 (多账号换行或&分割)")
    print("="*60 + "\n")
    
    env_str = os.environ.get(ENV_VAR_NAME, "")
    if not env_str:
        print(f"❌ 未找到环境变量 {ENV_VAR_NAME}")
        print(f"💡 配置格式: export {ENV_VAR_NAME}='手机号1#密码1\\n手机号2#密码2'")
        sys.exit(1)
    
    accounts = []
    for item in env_str.replace("&", "\n").splitlines():
        parts = item.strip().split("#")
        if len(parts) >= 2:
            phone, pwd = parts[0].strip(), parts[1].strip()
            accounts.append((phone, pwd))
    
    if not accounts:
        print("❌ 没有解析到有效的账号")
        print("💡 配置格式: 手机号#密码  (多账号换行或&分割)")
        sys.exit(1)
    
    print(f"✅ 共解析到 {len(accounts)} 个账号，即将并发运行\n")
    
    all_threads = []
    for idx, (phone, pwd) in enumerate(accounts, 1):
        random_seed = int(time.time() * 1000000) + idx * 12345
        thread_random = random.Random(random_seed)
        
        start_delay = thread_random.uniform(START_DELAY_MIN, START_DELAY_MAX)
        print(f"🔄 账号 {phone} 将在 {start_delay:.1f} 秒后启动")
        
        thread = threading.Thread(
            target=run_single_account,
            args=(phone, pwd, thread_random, accounts),
            daemon=True,
            name=f"Account-{phone}"
        )
        all_threads.append(thread)
        
        time.sleep(start_delay)
        thread.start()
    
    print(f"\n✅ 所有账号已启动，正在并发运行...\n")
    
    max_wait_seconds = MAX_RUN_HOURS_PER_ACCOUNT * 3600 + 600
    for thread in all_threads:
        thread.join(timeout=max_wait_seconds)
    
    print("\n🎉 所有账号任务已全部完成")
    
    # 生成汇总报告
    full_report = "📊 芳华币多账号运行汇总报告\n"
    full_report += "="*40 + "\n\n"
    
    total_gain = 0
    total_videos_all = 0
    total_integral_all = 0
    
    for idx, data in enumerate(all_accounts_data, 1):
        full_report += f"👤 账号 {idx}: {data['phone']}\n"
        full_report += f"   ⏰ 运行时长: {data['run_time']} 小时\n"
        full_report += f"   🎬 完成视频: {data['total_videos']} 个\n"
        full_report += f"   💰 领币次数: {data['total_integral']} 次\n"
        full_report += f"   💵 本次获得: {data['actual_gain'] if data['actual_gain'] >= 0 else '计算失败'} 芳华币\n"
        full_report += f"   🚪 退出原因: {data['exit_reason']}\n\n"
        
        if data['actual_gain'] >= 0:
            total_gain += data['actual_gain']
        total_videos_all += data['total_videos']
        total_integral_all += data['total_integral']
    
    full_report += "📈 本次运行汇总\n"
    full_report += "="*40 + "\n"
    full_report += f"✅ 运行账号数: {len(all_accounts_data)} 个\n"
    full_report += f"🎬 总完成视频: {total_videos_all} 个\n"
    full_report += f"💰 总领币次数: {total_integral_all} 次\n"
    full_report += f"💵 总获得芳华币: {total_gain} 个\n"
    full_report += f"🕐 结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    
    # 正常结束时也推送汇总报告
    try:
        notify_send(f"芳华币脚本已完成 | 共获得 {total_gain} 币", full_report)
        print("✅ 完整运行报告已推送")
    except Exception as e:
        print(f"❌ 推送异常: {str(e)}")
    
    # 强制退出主进程
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 脚本全局运行出错: {e}")
        sys.exit(1)