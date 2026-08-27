# name:芳华未来app
# cron:10 2 * * *

import requests
import time
import random
import sys
import os
import json
import threading
import base64
import signal
import string
from datetime import datetime, timedelta

# ====================================== 【apiSecurity 加密签名层（v1.8.1 新增）】 ======================================
# 新版 App 全站 /app/* 接口改为「RSA 封装 AES」混合加密+签名（原生插件 apiSecurity）：
#   请求：随机16位ASCII做AES key → AES-128-CBC(IV=key) 加密 body/参数 → 密文(base64)
#         POST 放 body(text/plain)，GET 放 ?data=<urlencode(密文)>；
#         "timestamp=<ms>&aesKey=<key>" 经 RSA/ECB/PKCS1 公钥加密 → X-Api-Sign 头
#   响应：{encryptedKey,encryptedData}，私钥解 encryptedKey 得裸16B key，AES 解 encryptedData
#   公私钥为同一对 RSA-2048，脚本内嵌私钥并派生公钥（离线抓包已验证自洽）。
APP_RSA_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDBWM3x7tL1iCDa
PNz6VpARgPVjFJGmnBSXV8SN+lXwIX8q9DkiBNzJRgN7c7v/jX6LseNfZm7ANc86
GGhXLqgPZ781L/5eZRgu31oTOj56turb67GPAr3e3RqQzkL3FkNrgmLQzkgJ9kzH
ym3np9MgiLmbwLezt+GHxFJVSnvxcrTnhnB5bbld7e1AgIXpS66owARJ9MZ+E/n3
WESKRslPFSFd9HLCNquXDOJnI/3Bpli7wPRADtnzjFoM9TWHeSDFvoa3kNQB0I6D
R0zG6ILbiCWdQRP3LMdrdsiCVkwzGkGIYj4H2MNiMprTcgXU1+xCfx43Wf4mUfJ4
xe0hOuCpAgMBAAECggEAdMfOnHJDuUmfjjF0xz/BhND/ZfjmgFuFlGPOtHKftYqF
5MveNk35jRhcwhQFWTV9WaL4UobsHexiXhSf8QidObDQLK/wU9N759O/9B0Z38Tb
1jll5ZsiU5n4kb4DdHpd/nGifbwahundNk9uUp1rSBtNAGZGjqZh8j8B+8IhWpOA
1090lPiqcbnCMueSVF3VghNPAYBYE/VpS1zQnkx54FiS/ojvhZNmW9rSnXtci3fi
QkLOg2GHI5ZTIxbFzOVb1F+TTGxtHcwOddOXz6DuaQmysXEmavcw7PrmeibWhc/J
ggBiBBcYLEUbnDdYIwnPmP+ymaQfxYUv+wQ/fjvgAQKBgQDqBGY8/pMTngWRnipA
S0ciI2to17oor1ovutAjMEEHXmHFeKVCh3NFkd0xscUF4wqqkZm8VdRz9QEANlfR
gy/CRSPTHGxZcBwjwdgr0f946XL5E2RGfNChWjECTSCxxHKktfuIrjDR1bkDIWwY
gpGUncnAL8crn+Iosqlo4YeTSQKBgQDTgl+olhYL6rg3VeiNqbWi30w3+Xn8QOBN
BnpKXBxdsUD/CBqIFyYJnvG3y2yqbNv0JwQijxC7o7VsF72eJYij3zYSufrsU6nI
filMMFpBIy5zJARiGEev3ugbIQyE09BIeizxVmOsZ6exJFhej4UipTr7xTOqulmB
Vtjg8omCYQKBgEcDBL83hQvr5Ma2Vx3heflrBBnxdIUKCPT43FYBO4pv4n1YydUx
YxJWW+fLiPzrU35E5oDXDrwNObuFwgpKo8Bw2JkkQ+Cz+2YCWYWamMppFMFuV/xn
vatowfxvyR8IfL1sl6J3MUtLbnP7vWCGpoSRiPovxWGAh9FPvcacwVY5AoGAOjvf
Eo+gKk/JwJKKoNZlCB7q4U5y450JJKvv56FMvg8bkhwtEeMtueBlNPFxTcsDFEnZ
vZoeRUthnA09S9mRsWy3ephyGbc/O9BglnWJo/2HwHPeMRP2SNnalf2XcMrQwePB
lADxGHrBlOgo3IAva8aKYt98xjjgg9fhhq3AZoECgYEA14vIL+vdzsvgIMT1mNRq
pDOTNEh9STOFPI2qD+UR0GMcPyoqsMb6ySkgPw+Evrx3W+SZASAFDxTFcIWQ2Ok3
ZKzq9nZMNbSerd+lQ7KUmunBORVGatuE1etOWIeXl63G05Rz31ElZBxi03g9/FdP
p5ImE+NFdpN3pOvjTddv7KM=
-----END PRIVATE KEY-----"""

# 双后端：优先 cryptography，缺失时回退 pycryptodome（青龙面板兼容）
try:
    from cryptography.hazmat.primitives.asymmetric import padding as _rsa_pad
    from cryptography.hazmat.primitives.serialization import load_pem_private_key as _load_priv
    from cryptography.hazmat.primitives.ciphers import Cipher as _Cipher, algorithms as _algo, modes as _modes

    _PRIV = _load_priv(APP_RSA_PRIVATE_KEY_PEM.encode(), password=None)
    _PUB = _PRIV.public_key()

    def _rsa_encrypt(data):
        return _PUB.encrypt(data, _rsa_pad.PKCS1v15())

    def _rsa_decrypt(data):
        return _PRIV.decrypt(data, _rsa_pad.PKCS1v15())

    def _aes_cbc_encrypt(pt, key):
        p = 16 - len(pt) % 16
        pt = pt + bytes([p]) * p
        c = _Cipher(_algo.AES(key), _modes.CBC(key)).encryptor()
        return c.update(pt) + c.finalize()

    def _aes_cbc_decrypt(ct, key):
        c = _Cipher(_algo.AES(key), _modes.CBC(key)).decryptor()
        pt = c.update(ct) + c.finalize()
        return pt[:-pt[-1]]
except ImportError:
    try:
        from Crypto.PublicKey import RSA as _RSA
        from Crypto.Cipher import PKCS1_v1_5 as _PK, AES as _AES

        _PRIVK = _RSA.import_key(APP_RSA_PRIVATE_KEY_PEM)
        _PUBK = _PRIVK.publickey()

        def _rsa_encrypt(data):
            return _PK.new(_PUBK).encrypt(data)

        def _rsa_decrypt(data):
            return _PK.new(_PRIVK).decrypt(data, None)

        def _aes_cbc_encrypt(pt, key):
            p = 16 - len(pt) % 16
            return _AES.new(key, _AES.MODE_CBC, key).encrypt(pt + bytes([p]) * p)

        def _aes_cbc_decrypt(ct, key):
            pt = _AES.new(key, _AES.MODE_CBC, key).decrypt(ct)
            return pt[:-pt[-1]]
    except ImportError as _e:
        raise RuntimeError("缺少加密库，请执行： pip install cryptography  (或 pip install pycryptodome)") from _e

# App 固定业务头（整场不变）
APP_VERSION = "1.8.1"
APP_VERSION_CODE = "1810"
APP_PLATFORM = "android"


def _rand_aes_key():
    """随机16位可打印ASCII作为AES-128密钥（IV=key）。"""
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(16))


def _rand_nonce():
    """随机11位base36字符串，对应 App 的 X-Api-Nonce。"""
    return "".join(random.choice("0123456789abcdefghijklmnopqrstuvwxyz") for _ in range(11))


def _new_device_id():
    """生成32位hex设备号，对应 X-Api-DeviceId（每账号固定一枚）。"""
    return "".join(random.choice("0123456789abcdef") for _ in range(32))


def build_secure_request(method, biz_payload):
    """按 apiSecurity 生成加密请求要素：返回 (加密头dict, POST的data字节或None, GET的params或None)。"""
    ts = str(int(time.time() * 1000))
    aes_key = _rand_aes_key()
    key_bytes = aes_key.encode()
    plain = json.dumps(biz_payload or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    aes_data = base64.b64encode(_aes_cbc_encrypt(plain, key_bytes)).decode()
    sign = base64.b64encode(_rsa_encrypt(f"timestamp={ts}&aesKey={aes_key}".encode())).decode()
    sec_headers = {
        "X-Api-Timestamp": ts,
        "X-Api-Nonce": _rand_nonce(),
        "X-Api-Sign": sign,
        "Content-Type": "text/plain",
    }
    if str(method).upper() == "GET":
        return sec_headers, None, {"data": aes_data}
    return sec_headers, aes_data.encode("utf-8"), None


def decrypt_secure_response(response):
    """将 {encryptedKey,encryptedData} 信封原地解密为明文，供后续 response.json() 直接使用。"""
    if response is None:
        return response
    try:
        env = response.json()
    except (ValueError, TypeError):
        return response
    if isinstance(env, dict) and env.get("encryptedKey") and env.get("encryptedData"):
        try:
            resp_key = _rsa_decrypt(base64.b64decode(env["encryptedKey"]))
            plaintext = _aes_cbc_decrypt(base64.b64decode(env["encryptedData"]), resp_key)
            response._content = plaintext
            response.encoding = "utf-8"
        except Exception:
            pass
    return response


def secure_request(method, url, biz_payload, base_headers, device_id, timeout=None):
    """一次性加密请求（登录/校验用，不依赖 Session），返回已解密的 response。"""
    headers = dict(base_headers or {})
    headers.update({
        "AppVersion": APP_VERSION,
        "AppVersionCode": APP_VERSION_CODE,
        "AppPlatform": APP_PLATFORM,
        "X-Api-DeviceId": device_id,
    })
    sec_headers, data_bytes, params = build_secure_request(method, biz_payload)
    headers.update(sec_headers)
    kwargs = {"headers": headers, "timeout": timeout or (REQUEST_CONNECT_TIMEOUT, REQUEST_READ_TIMEOUT)}
    if data_bytes is not None:
        kwargs["data"] = data_bytes
    if params is not None:
        kwargs["params"] = params
    return decrypt_secure_response(requests.request(method, url, **kwargs))
# ==================================================================================================


# ====================================== 【防检测核心配置区】 ======================================
BASE_URL = "https://api.cdwjyyh.com"

# -------------------------- 【多账号登录配置】 --------------------------
ENV_VAR_NAME = "fhb"

# -------------------------- 【观看节奏配置（坐实真实抓包，中心值+随机抖动）】 --------------------------
# 真实链路：每个视频 track PLAY -> PLAY_3S ->(COMPLETE)-> addIntegral 领一次（非“10秒一领”）。
# 领币真正门槛 = PLAY_3S 事件（视频播放满3秒）；抓包实测 PLAY_3S 后最短 1.2s 即领到。
# 下列为各等待的“中心值”，每次在中心值上叠加 ±TIMING_JITTER 抖动模拟真人（总观看约 13 秒）。
PLAY_TO_3S_SECONDS = 5      # PLAY -> PLAY_3S 的等待中心值（缓冲+满3秒播放，抓包 2~9s）
WATCH_AFTER_3S_SECONDS = 8  # PLAY_3S -> 领币 的等待中心值（抓包最短 1.2s，留足余量）
NEXT_VIDEO_DELAY = 3        # 两个视频之间的间隔中心值（秒）
TIMING_JITTER = 2.0         # 各观看等待的随机抖动幅度（±秒）；设 0 则固定不抖动
SEND_COMPLETE = True        # 领币前发送 COMPLETE（表示完整看完，抓包约 3/5 会发）

# -------------------------- 【芳华币领取配置】 --------------------------
INTEGRAL_TYPE = 2
MIN_CLAIM_INTERVAL = 25     # 两次领币最短间隔(秒)；抓包真机约22~26s，低于此值服务端报"访问过于频繁"
INTEGRAL_LIMIT_MESSAGE = "今天的浏览短视频获得芳华币领取已达到上限"
INTEGRAL_RESULT_SUCCESS = "success"
INTEGRAL_RESULT_LIMIT = "limit"
INTEGRAL_RESULT_FAILED = "failed"
AUTH_EXPIRED_KEYWORDS = ("AppToken退出", "请重新登录")
SESSION_AUTH_REFRESH_ATTR = "fhb_refresh_auth"
SESSION_AUTH_FAILED_ATTR = "fhb_auth_failed"

# -------------------------- 【课程学习刷分配置（+50/小节，实证见 reverse-skill/work/芳华/analysis/课程学习+50分-实证.md）】 --------------------------
# 链路：addStudyCourse(注册会话) -> heartbeat(保活) -> getIntegral(领分，duration≥总时长90%得+50)。课程优先，剩余时间再刷短视频。
ENABLE_COURSE_STUDY = True          # 总开关：是否启用「学习科普课程」刷分阶段
ENABLE_COURSE_BUY = True            # 是否用芳华币兑换(购买)未拥有(isBuy=0)的课程视频以解锁学习
COURSE_MAX_BUY_INTEGRAL = 100       # 只兑换「芳华币价 < 该值」的课程（用户规则：<100 可购买）
COURSE_INTEGRAL_PER_SECTION = 50    # 每个视频小节看满领取的芳华币（服务端固定 50）
COURSE_PROGRESS_RATIO = 0.9         # 领分门槛：观看时长需达视频总时长的 90%
COURSE_WATCH_BUFFER = 6             # 在 90% 基础上多看的秒数，稳过阈值
COURSE_HEARTBEAT_INTERVAL = 30      # 观看期间每隔多少秒发一次心跳+进度上报（真机约 30~70s）
COURSE_NEXT_VIDEO_DELAY = 4         # 两个视频小节之间的间隔中心值（秒）
COURSE_LIST_PAGE_SIZE = 10          # 课程列表分页大小
COURSE_CLAIM_MAX_RETRY = 3          # 领分报"不满90%"时的补看重试次数
COURSE_LIMIT_KEYWORDS = ("上限",)   # 课程日限关键字，命中则结束课程阶段
COURSE_RESULT_SUCCESS = "success"   # 领分结果码：成功 +50
COURSE_RESULT_ALREADY = "already"   # 该小节已领过
COURSE_RESULT_LIMIT = "limit"       # 达每日上限
COURSE_RESULT_FAILED = "failed"     # 失败/跳过

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
# ==================================================================================================

# 全局变量（已去重）
global_exit_flag = False
all_threads = []
all_accounts_data = []
data_lock = threading.Lock()
token_lock = threading.Lock()
print_lock = threading.Lock()


def mask_phone(phone):
    """手机号中间4位打码，如 150****4697。"""
    phone = str(phone or "")
    if len(phone) >= 8:
        return f"{phone[:3]}****{phone[-4:]}"
    return phone


def build_notify_content(results):
    """生成运行简报：每账号仅展示本次获得币数与当前总币数（无敏感信息、不做合计）。"""
    if not results:
        return "本次没有账号完成执行"

    lines = []
    for index, data in enumerate(results, 1):
        actual_gain = data.get("actual_gain", -1)
        gain_known = isinstance(actual_gain, (int, float)) and actual_gain >= 0
        gain_text = f"+{actual_gain}" if gain_known else "未知"
        current = data.get("current_integral")
        total_text = f"{current}" if current is not None else "查询失败"
        lines.append(
            f"{index}. {mask_phone(data.get('phone'))} | 获得 {gain_text} 币 | 共 {total_text} 币"
        )
    return "\n".join(lines)


def send_notify(title, content):
    """使用青龙面板 notify 模块发送通知。"""
    if not content:
        return
    try:
        if "/ql/data/scripts" not in sys.path:
            sys.path.insert(0, "/ql/data/scripts")
        from notify import send

        send(title, content)
        with print_lock:
            print("✅ 青龙简报推送成功")
    except ImportError:
        with print_lock:
            print("ℹ️ 未找到青龙 notify 模块，跳过推送")
    except Exception as e:
        with print_lock:
            print(f"⚠️ 青龙简报推送失败: {e}")

# ============================== 【终极强制退出函数（核心修复）】 ==============================
def force_exit(signum, frame):
    """
    收到停止信号时的终极处理函数
    收集所有账号数据，统一推送青龙简报，然后终止进程
    """
    global global_exit_flag
    
    with print_lock:
        print("\n\n🛑 收到停止信号，正在强制终止所有线程...")
    
    # 设置全局退出标志
    global_exit_flag = True
    
    # 等待10秒让所有线程完成数据收集
    time.sleep(10)
    
    with data_lock:
        results = list(all_accounts_data)

    with print_lock:
        print("📤 正在推送青龙运行简报...")

    send_notify("芳华未来运行简报（已停止）", build_notify_content(results))
    
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


def update_token_cache_entry(phone, token, jpush_id, device_id):
    """线程安全地更新单个账号缓存（token/jpushId/deviceId），避免并发登录互相覆盖。"""
    with token_lock:
        try:
            cache = {}
            if os.path.exists(TOKEN_CACHE_FILE):
                try:
                    with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                        cache = json.load(f)
                except (OSError, ValueError, TypeError):
                    cache = {}
            cache[phone] = {
                "token": token,
                "jpushId": jpush_id,
                "deviceId": device_id
            }
            with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            with print_lock:
                print("✅ 缓存已更新")
        except Exception as e:
            with print_lock:
                print(f"❌ 更新账号 {phone} 缓存失败: {e}")


def get_or_create_device_id(phone):
    """获取账号固定设备号 X-Api-DeviceId：缓存已有则复用，否则新生成一枚。"""
    cache = load_token_cache()
    device_id = cache.get(phone, {}).get("deviceId")
    return device_id or _new_device_id()


def login(phone, password, jpush_id, device_id, random_instance):
    """使用手机号+密码+对应jpushId登录（apiSecurity 加密提交）"""
    try:
        login_headers = {
            "User-Agent": random_instance.choice(USER_AGENT_POOL),
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        data = {
            "phone": phone,
            "password": password,
            "jpushId": jpush_id,
            "loginType": LOGIN_TYPE,
            "source": LOGIN_SOURCE
        }
        response = secure_request(
            "POST", f"{BASE_URL}/app/app/login", data, login_headers, device_id
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

def verify_token(token, device_id, random_instance):
    """验证Token是否有效（apiSecurity 加密请求）"""
    try:
        test_headers = {
            "User-Agent": random_instance.choice(USER_AGENT_POOL),
            "AppToken": token,
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        response = secure_request(
            "GET", f"{BASE_URL}/app/user/getUserInfo", {}, test_headers, device_id
        )
        return response.status_code == 200 and response.json().get("code") == 200
    except Exception:
        return False

def get_valid_credentials(phone, password, jpush_id, random_instance):
    """获取有效凭证：优先缓存，失效自动重登（含固定设备号）"""
    cache = load_token_cache()
    cached_data = cache.get(phone, {})
    cached_token = cached_data.get("token")
    cached_jpush_id = cached_data.get("jpushId", jpush_id)
    device_id = cached_data.get("deviceId") or _new_device_id()

    if cached_token:
        with print_lock:
            print(f"🔍 账号 {phone} 检测到缓存Token，正在验证有效性...")
        if verify_token(cached_token, device_id, random_instance):
            with print_lock:
                print(f"✅ 账号 {phone} 缓存Token有效")
            test_headers = {"User-Agent": random_instance.choice(USER_AGENT_POOL), "AppToken": cached_token}
            response = secure_request(
                "GET", f"{BASE_URL}/app/user/getUserInfo", {}, test_headers, device_id, timeout=10
            )
            user_id = response.json().get("user", {}).get("userId")
            return cached_token, user_id, cached_jpush_id, device_id
        with print_lock:
            print(f"⚠️  账号 {phone} 缓存Token已失效，正在重新登录...")

    token, user_id = login(phone, password, jpush_id, device_id, random_instance)
    if token:
        update_token_cache_entry(phone, token, jpush_id, device_id)
    return token, user_id, jpush_id, device_id


def refresh_session_auth(session, phone, password, jpush_id, random_instance):
    """运行中Token失效时重新登录，并替换当前Session的身份凭证。"""
    with print_lock:
        print(f"\n⚠️  账号 {phone} 登录状态已失效，正在重新登录...")

    device_id = getattr(session, "device_id", None) or _new_device_id()
    token, user_id = login(phone, password, jpush_id, device_id, random_instance)
    if not token or not user_id:
        setattr(session, SESSION_AUTH_FAILED_ATTR, True)
        with print_lock:
            print(f"❌ 账号 {phone} 重新登录失败，停止该账号任务")
        return False

    session.headers.update({"AppToken": token})
    update_token_cache_entry(phone, token, jpush_id, device_id)
    setattr(session, SESSION_AUTH_FAILED_ATTR, False)
    with print_lock:
        print(f"✅ 账号 {phone} 已重新登录，继续执行原请求")
    return True


def get_token_identity(token, device_id, random_instance):
    """验证环境变量中的 Token，并返回 (user_id, phone)。"""
    try:
        headers = {
            "User-Agent": random_instance.choice(USER_AGENT_POOL),
            "AppToken": token,
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        response = secure_request(
            "GET", f"{BASE_URL}/app/user/getUserInfo", {}, headers, device_id, timeout=10
        )
        if response.status_code != 200:
            return None, None
        result = response.json()
        if result.get("code") != 200:
            return None, None
        user = result.get("user") or result.get("data") or {}
        return user.get("userId"), user.get("phone") or user.get("mobile")
    except Exception:
        return None, None


def token_expired(session, account_label):
    """Token 模式无法自动续期；标记账号停止并提示重新配置。"""
    setattr(session, SESSION_AUTH_FAILED_ATTR, True)
    with print_lock:
        print(f"\n❌ {account_label} 的 Token 已失效，请更新环境变量 {ENV_VAR_NAME}")
    return False


def is_auth_expired_response(response):
    """判断HTTP成功响应是否表示AppToken已退出。"""
    if response is None or response.status_code != 200:
        return False
    try:
        result = response.json()
    except (TypeError, ValueError):
        return False
    if not isinstance(result, dict) or result.get("code") == 200:
        return False
    message = str(result.get("msg") or "")
    return any(keyword in message for keyword in AUTH_EXPIRED_KEYWORDS)

# ============================== 【基础请求与接口模块（独立随机）】 ==============================
def request_with_retry(session, method, url, random_instance, **kwargs):
    """带随机超时和重试的请求函数（独立随机，自动 apiSecurity 加密+响应解密）"""
    # 提取业务明文：json(POST) 或 params(GET)，统一交给加密层
    biz_json = kwargs.pop("json", None)
    biz_params = kwargs.pop("params", None)
    biz_payload = biz_json if biz_json is not None else (biz_params if biz_params is not None else {})
    caller_headers = dict(kwargs.pop("headers", {}) or {})

    for attempt in range(MAX_RETRIES):
        if global_exit_flag:
            return None

        try:
            auth_refresh_attempted = False
            while True:
                # 每次发送重新生成签名（时间戳需新鲜，避免重试时过期）
                sec_headers, data_bytes, sec_params = build_secure_request(method, biz_payload)
                req_headers = dict(caller_headers)
                req_headers.update(sec_headers)
                send_kwargs = dict(kwargs)
                send_kwargs["headers"] = req_headers
                if data_bytes is not None:
                    send_kwargs["data"] = data_bytes
                if sec_params is not None:
                    send_kwargs["params"] = sec_params

                timeout = (
                    REQUEST_CONNECT_TIMEOUT,
                    random_instance.uniform(REQUEST_READ_TIMEOUT, REQUEST_READ_TIMEOUT + 2)
                )
                response = session.request(method, url, timeout=timeout, **send_kwargs)

                decrypt_secure_response(response)  # 信封响应原地解密为明文

                if is_auth_expired_response(response) and not auth_refresh_attempted:
                    auth_refresh_attempted = True
                    refresh_auth = getattr(session, SESSION_AUTH_REFRESH_ATTR, None)
                    if callable(refresh_auth) and refresh_auth():
                        continue
                    setattr(session, SESSION_AUTH_FAILED_ATTR, True)

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
        params = {"isRandom": 1, "pageSize": page_size, "keyword": "", "pageNum": page_num}
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
        if response is None or response.status_code != 200:
            return False
        result = response.json()
        return isinstance(result, dict) and result.get("code") == 200
    except Exception:
        return False

def add_integral(session, phone, video_id, random_instance):
    try:
        response = request_with_retry(
            session, "POST", f"{BASE_URL}/app/integral/addIntegral", random_instance,
            json={"videoId": str(video_id), "type": INTEGRAL_TYPE}
        )
        if response and response.status_code == 200:
            result = response.json()
            if result.get("code") == 200:
                with print_lock:
                    print(f"   ├─ 💰 账号 {phone} {result.get('msg', '领取成功')}")
                return INTEGRAL_RESULT_SUCCESS
            message = str(result.get("msg") or "未知错误")
            with print_lock:
                print(f"   ├─ ⚠️  账号 {phone} 领取失败: {message}")
            if INTEGRAL_LIMIT_MESSAGE in message:
                return INTEGRAL_RESULT_LIMIT
        return INTEGRAL_RESULT_FAILED
    except Exception as e:
        with print_lock:
            print(f"   ├─ ❌ 账号 {phone} 领取请求失败: {e}")
        return INTEGRAL_RESULT_FAILED

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

def interruptible_sleep(seconds):
    """可被停止信号打断的睡眠：收到退出标志立即返回 False。"""
    whole = int(seconds)
    for _ in range(whole):
        if global_exit_flag:
            return False
        time.sleep(1)
    frac = seconds - whole
    if frac > 0 and not global_exit_flag:
        time.sleep(frac)
    return not global_exit_flag


def jittered(base, random_instance):
    """在中心值上叠加 ±TIMING_JITTER 随机抖动，最小 0.5 秒，模拟真人节奏。"""
    return max(0.5, base + random_instance.uniform(-TIMING_JITTER, TIMING_JITTER))


# ============================== 【最终报告模块（仅控制台打印）】 ==============================
def send_final_report(session, phone, total_videos, total_integral, initial_integral, start_time, exit_reason, random_instance, all_accounts):
    """
    生成并打印最终运行报告，同时收集数据到全局变量
    """
    current_integral = (
        None
        if getattr(session, SESSION_AUTH_FAILED_ATTR, False)
        else get_user_integral(session, random_instance)
    )
    course_claimed = getattr(session, "course_claimed", 0)  # 课程学习领分小节数
    run_time = round((time.time() - start_time) / 3600, 2)
    actual_gain = (
        current_integral - initial_integral
        if current_integral is not None and initial_integral is not None
        else -1
    )

    # 生成控制台打印的报告（无敏感信息）
    console_report = f"""📊 自动刷芳华币运行报告
👤 账号: {phone}
⏰ 运行时长: {run_time} 小时
📚 课程领分: {course_claimed} 小节 (+{course_claimed * COURSE_INTEGRAL_PER_SECTION} 芳华币)
🎬 完成视频: {total_videos} 个
💰 领币次数: {total_integral} 次
💵 初始余额: {initial_integral if initial_integral is not None else '查询失败'} 芳华币
💵 当前余额: {current_integral if current_integral is not None else '查询失败'} 芳华币
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
            "course_claimed": course_claimed,
            "initial_integral": initial_integral,
            "current_integral": current_integral,
            "actual_gain": actual_gain,
            "exit_reason": exit_reason
        })

# ============================== 【课程学习刷分模块（每个视频小节 +50 芳华币）】 ==============================
def get_course_list(session, random_instance, page_num=1, cate_id=""):
    """拉取课程列表：返回 (课程数组, 总数)；isIntegral==1 的课程可领分。"""
    try:
        response = request_with_retry(
            session, "GET", f"{BASE_URL}/app/course/getCourseList", random_instance,
            params={"cateId": cate_id, "pageSize": COURSE_LIST_PAGE_SIZE, "pageNum": page_num}
        )
        if response and response.status_code == 200:
            result = response.json()
            if result.get("code") == 200:
                data = result.get("data") or {}
                return data.get("list", []), data.get("total", 0)
        return [], 0
    except Exception as e:
        with print_lock:
            print(f"❌ 获取课程列表失败: {e}")
        return [], 0


def get_course_video_list(session, course_id, random_instance):
    """拉取某课程下的视频小节数组（含 videoId、seconds 时长）。"""
    try:
        response = request_with_retry(
            session, "GET", f"{BASE_URL}/app/course/getCourseVideoList", random_instance,
            params={"pageSize": 50, "courseId": str(course_id), "pageNum": 1}
        )
        if response and response.status_code == 200:
            result = response.json()
            if result.get("code") == 200:
                return (result.get("data") or {}).get("list", [])
        return []
    except Exception as e:
        with print_lock:
            print(f"❌ 获取课程视频失败(course {course_id}): {e}")
        return []


def get_course_price(session, course_id, random_instance):
    """读取课程芳华币兑换价：返回 integral（None 视为 0/免费，用于 <100 过滤）。"""
    try:
        response = request_with_retry(
            session, "GET", f"{BASE_URL}/app/course/getCourseById?courseId={course_id}", random_instance,
            params={}
        )
        if response and response.status_code == 200:
            result = response.json()
            if result.get("code") == 200:
                return (result.get("data") or {}).get("integral")
        return None
    except Exception:
        return None


def buy_course_video(session, course_id, video_id, random_instance):
    """用芳华币兑换(购买)单个课程视频以解锁。返回 (是否成功, 消息)。"""
    try:
        response = request_with_retry(
            session, "POST", f"{BASE_URL}/app/courseOrder/createIntegralOrder", random_instance,
            json={"videoId": int(video_id), "courseId": str(course_id)}
        )
        if response is None:
            return False, "无响应"
        result = response.json()
        message = str(result.get("msg") or "")
        # 已拥有再次兑换也返回"兑换成功"，视为成功；余额不足等返回失败
        return (result.get("code") == 200), message
    except Exception as e:
        return False, str(e)


def add_study_course(session, course_id, video_id, duration, random_instance):
    """上报学习进度/注册学习会话（getIntegral 领分前置，缺失会报"您还未看课"）。"""
    try:
        response = request_with_retry(
            session, "POST", f"{BASE_URL}/app/course/addStudyCourse", random_instance,
            json={"duration": int(duration), "videoId": int(video_id), "courseId": int(course_id)}
        )
        return bool(response and response.status_code == 200 and response.json().get("code") == 200)
    except Exception:
        return False


def course_heartbeat(session, random_instance):
    """发送课程观看保活心跳（全局，无 videoId）。"""
    try:
        request_with_retry(
            session, "POST", f"{BASE_URL}/app/portrait/heartbeat", random_instance,
            json={"action": "HEARTBEAT"}
        )
    except Exception:
        pass


def claim_course_integral(session, video_id, duration, random_instance):
    """领取某视频小节的课程积分(+50)。返回 (结果码, 消息)。"""
    try:
        response = request_with_retry(
            session, "POST", f"{BASE_URL}/app/course/getIntegral", random_instance,
            json={"duration": int(duration), "videoId": int(video_id)}
        )
        if response is None:
            return COURSE_RESULT_FAILED, "无响应"
        result = response.json()
        code = result.get("code")
        message = str(result.get("msg") or "")
        if code == 200:
            return COURSE_RESULT_SUCCESS, message
        if "已获取此小节" in message or "已领取" in message:
            return COURSE_RESULT_ALREADY, message
        if any(k in message for k in COURSE_LIMIT_KEYWORDS):
            return COURSE_RESULT_LIMIT, message
        return COURSE_RESULT_FAILED, message
    except Exception as e:
        return COURSE_RESULT_FAILED, str(e)


def study_one_course_video(session, phone, course_id, video, deadline, random_instance):
    """兑换(购买)+查漏补缺观看+领分单个视频小节。返回结果码。"""
    video_id = video.get("videoId")
    seconds = int(video.get("seconds") or 0)
    if not video_id or seconds <= 0:
        return COURSE_RESULT_FAILED
    title = str(video.get("title") or "").strip()[:18]
    need = int(seconds * COURSE_PROGRESS_RATIO) + COURSE_WATCH_BUFFER  # 需达 90% 并留缓冲
    already = min(int(video.get("studyTime") or 0), seconds)           # 服务端已记录的观看断点

    # 1) 未拥有(isBuy≠1)则先用芳华币兑换解锁
    if ENABLE_COURSE_BUY and video.get("isBuy") != 1:
        ok, msg = buy_course_video(session, course_id, video_id, random_instance)
        if not ok:
            with print_lock:
                print(f"   ├─ 🔒 账号 {phone} 小节《{title}》兑换失败({msg})，跳过")
            return COURSE_RESULT_FAILED
        with print_lock:
            print(f"   ├─ 🛒 账号 {phone} 已兑换《{title}》")

    # 2) 注册学习会话（用已看断点做初始 duration，贴合真机）
    add_study_course(session, course_id, video_id, min(max(already, 10), seconds), random_instance)

    # 3) 断点已看满 → 直接尝试领分（查漏补缺：不重复观看已看部分）
    if already >= need:
        result, message = claim_course_integral(session, video_id, max(already, need), random_instance)
        if result == COURSE_RESULT_SUCCESS:
            with print_lock:
                print(f"   ├─ 💰 账号 {phone} 《{title}》{message}(断点续领)")
            return COURSE_RESULT_SUCCESS
        if result == COURSE_RESULT_ALREADY:
            with print_lock:
                print(f"   ├─ ⏭️  账号 {phone} 小节《{title}》已领过，跳过")
            return COURSE_RESULT_ALREADY
        if result == COURSE_RESULT_LIMIT:
            return COURSE_RESULT_LIMIT
    else:
        # 4) 探测是否已领（duration=1 不满90%不会误领），已领则秒跳
        result, _ = claim_course_integral(session, video_id, 1, random_instance)
        if result == COURSE_RESULT_ALREADY:
            with print_lock:
                print(f"   ├─ ⏭️  账号 {phone} 小节《{title}》已领过，跳过")
            return COURSE_RESULT_ALREADY
        if result == COURSE_RESULT_LIMIT:
            return COURSE_RESULT_LIMIT

    # 5) 拟真续看：从断点 already 补看到 need（只补未看部分，查漏补缺）
    remain = max(0, need - already)
    with print_lock:
        print(f"   ├─ 📖 账号 {phone} 学习《{title}》时长{seconds}s，已看{already}s，续看约{remain}s…")
    watched = already
    while watched < need:
        if global_exit_flag or getattr(session, SESSION_AUTH_FAILED_ATTR, False) or time.time() > deadline:
            return COURSE_RESULT_FAILED
        chunk = min(COURSE_HEARTBEAT_INTERVAL, need - watched)
        if not interruptible_sleep(jittered(chunk, random_instance)):
            return COURSE_RESULT_FAILED
        watched += chunk
        course_heartbeat(session, random_instance)
        add_study_course(session, course_id, video_id, watched, random_instance)

    # 6) 领分（duration≥90%）；报"不满90%/未看课"则补看再试
    for _ in range(COURSE_CLAIM_MAX_RETRY):
        result, message = claim_course_integral(session, video_id, watched, random_instance)
        if result == COURSE_RESULT_SUCCESS:
            with print_lock:
                print(f"   ├─ 💰 账号 {phone} 《{title}》{message}")
            return COURSE_RESULT_SUCCESS
        if result in (COURSE_RESULT_ALREADY, COURSE_RESULT_LIMIT):
            return result
        if "不满" in message or "未看课" in message:  # 补看再试
            if global_exit_flag or getattr(session, SESSION_AUTH_FAILED_ATTR, False) or time.time() > deadline:
                return COURSE_RESULT_FAILED
            add_study_course(session, course_id, video_id, watched, random_instance)
            if not interruptible_sleep(jittered(COURSE_HEARTBEAT_INTERVAL, random_instance)):
                return COURSE_RESULT_FAILED
            watched += COURSE_HEARTBEAT_INTERVAL
            course_heartbeat(session, random_instance)
            continue
        with print_lock:
            print(f"   ├─ ⚠️  账号 {phone} 《{title}》领分失败: {message}")
        return COURSE_RESULT_FAILED
    return COURSE_RESULT_FAILED


def study_courses(session, phone, account_start, random_instance):
    """课程学习刷分阶段：遍历课程→逐视频拟真观看领分。返回 (领分小节数, 是否达上限)。"""
    deadline = account_start + MAX_RUN_HOURS_PER_ACCOUNT * 3600
    claimed = 0
    page_num = 1

    with print_lock:
        print(f"\n📚 账号 {phone} 进入【课程学习刷分】阶段（每小节 +{COURSE_INTEGRAL_PER_SECTION} 芳华币）\n")

    while True:
        if global_exit_flag or getattr(session, SESSION_AUTH_FAILED_ATTR, False) or time.time() > deadline:
            break
        courses, total = get_course_list(session, random_instance, page_num=page_num)
        if not courses:
            break  # 课程翻到底

        for course in courses:
            if global_exit_flag or getattr(session, SESSION_AUTH_FAILED_ATTR, False) or time.time() > deadline:
                return claimed, False
            if course.get("isIntegral") != 1:
                continue  # 非积分课程跳过
            course_id = course.get("courseId")
            course_name = str(course.get("courseName") or "").strip()[:20]
            # 仅兑换「芳华币价 < COURSE_MAX_BUY_INTEGRAL」的课程（integral 为 None 视为免费）
            if ENABLE_COURSE_BUY:
                price = get_course_price(session, course_id, random_instance)
                if price is not None and price >= COURSE_MAX_BUY_INTEGRAL:
                    with print_lock:
                        print(f"⏭️  账号 {phone} 课程《{course_name}》兑换价 {price} ≥ {COURSE_MAX_BUY_INTEGRAL} 芳华币，跳过")
                    continue
            videos = get_course_video_list(session, course_id, random_instance)
            if not videos:
                continue
            with print_lock:
                print(f"📗 账号 {phone} 学习课程《{course_name}》({len(videos)} 小节)")

            for video in videos:
                if global_exit_flag or getattr(session, SESSION_AUTH_FAILED_ATTR, False) or time.time() > deadline:
                    return claimed, False
                result = study_one_course_video(session, phone, course_id, video, deadline, random_instance)
                if result == COURSE_RESULT_SUCCESS:
                    claimed += 1
                    with print_lock:
                        print(f"✅ 账号 {phone} 课程累计领分: {claimed} 小节 (+{claimed * COURSE_INTEGRAL_PER_SECTION} 芳华币)\n")
                elif result == COURSE_RESULT_LIMIT:
                    with print_lock:
                        print(f"\n🛑 账号 {phone} 课程积分已达每日上限，结束课程阶段")
                    return claimed, True
                interruptible_sleep(jittered(COURSE_NEXT_VIDEO_DELAY, random_instance))

        page_num += 1
        if total and page_num > (total + COURSE_LIST_PAGE_SIZE - 1) // COURSE_LIST_PAGE_SIZE:
            break  # 已翻完所有课程页

    with print_lock:
        print(f"\n📚 账号 {phone} 课程学习阶段结束，共领 {claimed} 小节 (+{claimed * COURSE_INTEGRAL_PER_SECTION} 芳华币)\n")
    return claimed, False


# ============================== 【单账号独立运行逻辑】 ==============================
def run_single_account(account_label, token, device_id, random_instance, all_accounts):
    """单个账号：验证 Token -> 签到 -> 执行业务任务。"""
    user_id, phone = get_token_identity(token, device_id, random_instance)
    phone = mask_phone(phone) if phone else account_label
    with print_lock:
        print(f"\n{'='*60}")
        print(f"🚀 账号 {phone} 已启动")
        print(f"{'='*60}\n")

    if not user_id:
        with print_lock:
            print(f"❌ {account_label} 的 Token 无效或已过期，跳过")
        return

    session = requests.Session()
    user_agent = random_instance.choice(USER_AGENT_POOL)
    session.headers.update({
        "User-Agent": user_agent,
        "AppToken": token,
        "AppVersion": APP_VERSION,
        "AppVersionCode": APP_VERSION_CODE,
        "AppPlatform": APP_PLATFORM,
        "X-Api-DeviceId": device_id,
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    })
    session.device_id = device_id  # 供 refresh_session_auth 复用
    setattr(session, SESSION_AUTH_FAILED_ATTR, False)
    session.course_claimed = 0  # 课程学习领分小节数（供最终报告统计）
    setattr(
        session,
        SESSION_AUTH_REFRESH_ATTR,
        lambda: token_expired(session, account_label)
    )

    account_start = time.time()
    total_videos = 0
    total_integral = 0
    last_claim_time = 0.0  # 上次领币时间，用于控制最短领币间隔
    integral_limit_reached = False

    with print_lock:
        print(f"🔍 账号 {phone} 正在查询初始芳华币余额...")
    initial_integral = get_user_integral(session, random_instance)
    if initial_integral is not None:
        with print_lock:
            print(f"✅ 账号 {phone} 初始芳华币余额: {initial_integral}\n")
    else:
        with print_lock:
            print(f"⚠️  账号 {phone} 初始芳华币查询失败\n")

    # 每日签到（保留，接口沿用现有）
    interruptible_sleep(random_instance.uniform(1, 3))
    daily_sign(session, random_instance)

    # ========== 阶段一：课程学习刷分（课程优先，每小节 +50 芳华币）==========
    if (
        ENABLE_COURSE_STUDY
        and not global_exit_flag
        and not getattr(session, SESSION_AUTH_FAILED_ATTR, False)
        and time.time() - account_start < MAX_RUN_HOURS_PER_ACCOUNT * 3600
    ):
        course_claimed, _course_limit = study_courses(session, phone, account_start, random_instance)
        session.course_claimed = course_claimed

    # ========== 阶段二：剩余时间刷短视频领芳华币（现有逻辑）==========
    page_num = 1
    try:
        while True:
            if getattr(session, SESSION_AUTH_FAILED_ATTR, False):
                with print_lock:
                    print(f"\n🛑 账号 {phone} 重新登录失败，停止任务")
                send_final_report(session, phone, total_videos, total_integral, initial_integral, account_start, "登录状态失效，重新登录失败", random_instance, all_accounts)
                break

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

            video_list = get_video_list(session, random_instance, page_num=page_num)
            if not video_list:
                if page_num > 1:
                    page_num = 1  # 翻到底，回到第1页重新随机取
                    continue
                with print_lock:
                    print(f"⚠️  账号 {phone} 没有获取到视频，等待30秒后重试")
                interruptible_sleep(30)
                continue

            for video in video_list:
                if (
                    global_exit_flag
                    or getattr(session, SESSION_AUTH_FAILED_ATTR, False)
                    or time.time() - account_start > MAX_RUN_HOURS_PER_ACCOUNT * 3600
                ):
                    break

                video_id = video["id"]
                video_title = video["title"][:18] + "..." if len(video["title"]) > 18 else video["title"]
                with print_lock:
                    print(f"📺 账号 {phone} 正在观看: {video_title}")

                # 完全按抓包链路：PLAY -> 满3秒 PLAY_3S ->(COMPLETE)-> addIntegral 领一次
                report_video_event(session, video_id, "PLAY", random_instance)
                if not interruptible_sleep(jittered(PLAY_TO_3S_SECONDS, random_instance)):
                    break
                report_video_event(session, video_id, "PLAY_3S", random_instance)
                if not interruptible_sleep(jittered(WATCH_AFTER_3S_SECONDS, random_instance)):
                    break
                # 控制两次领币最短间隔，避免服务端"访问过于频繁"（不足则继续观看补足）
                deficit = MIN_CLAIM_INTERVAL - (time.time() - last_claim_time)
                if deficit > 0 and not interruptible_sleep(deficit):
                    break
                if getattr(session, SESSION_AUTH_FAILED_ATTR, False):
                    break
                if SEND_COMPLETE:
                    report_video_event(session, video_id, "COMPLETE", random_instance)

                # 领币：每个视频一次（type=2 带 videoId）
                integral_result = add_integral(session, phone, video_id, random_instance)
                last_claim_time = time.time()
                if integral_result == INTEGRAL_RESULT_SUCCESS:
                    total_integral += 1
                elif integral_result == INTEGRAL_RESULT_LIMIT:
                    integral_limit_reached = True
                    with print_lock:
                        print(f"\n🛑 账号 {phone} 今日浏览短视频领币已达上限，停止观看视频")
                    send_final_report(session, phone, total_videos, total_integral, initial_integral, account_start, "今日浏览短视频领币已达上限", random_instance, all_accounts)
                    break
                elif getattr(session, SESSION_AUTH_FAILED_ATTR, False):
                    break

                total_videos += 1
                with print_lock:
                    print(f"✅ 账号 {phone} 累计完成: {total_videos} 个视频 | 累计领币: {total_integral} 次\n")

                interruptible_sleep(jittered(NEXT_VIDEO_DELAY, random_instance))

            if integral_limit_reached:
                break
            page_num += 1  # 每批看完翻页取新一批随机视频

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
    print(f"📌 观看节奏: 每视频约 {PLAY_TO_3S_SECONDS + WATCH_AFTER_3S_SECONDS} 秒 (PLAY→PLAY_3S→COMPLETE→领币一次)")
    print(f"📌 芳华币规则: 每看完一个视频领取一次 (服务端按视频计，金额递减)")
    print("📌 运行方式: 直接使用环境变量中的 Token，不需要手机号和密码")
    print("📌 环境变量格式: Token1@Token2；可选格式 Token#deviceId")
    print("="*60 + "\n")
    
    env_str = os.environ.get(ENV_VAR_NAME, "")
    if not env_str:
        print(f"❌ 未找到环境变量 {ENV_VAR_NAME}")
        print(f"💡 配置格式: export {ENV_VAR_NAME}='Token1@Token2'")
        sys.exit(1)
    
    accounts = []
    for index, item in enumerate(env_str.split("@"), 1):
        parts = [part.strip() for part in item.strip().split("#", 1)]
        token = parts[0] if parts else ""
        device_id = parts[1] if len(parts) == 2 else _new_device_id()
        if token:
            accounts.append((f"账号 {index}", token, device_id))
    
    if not accounts:
        print("❌ 没有解析到有效的账号")
        print(f"💡 请按 Token1@Token2 的格式配置环境变量 {ENV_VAR_NAME}")
        sys.exit(1)
    
    print(f"✅ 共解析到 {len(accounts)} 个账号，即将并发运行\n")
    
    all_threads = []
    for idx, (account_label, token, device_id) in enumerate(accounts, 1):
        random_seed = int(time.time() * 1000000) + idx * 12345
        thread_random = random.Random(random_seed)
        
        start_delay = thread_random.uniform(START_DELAY_MIN, START_DELAY_MAX)
        print(f"🔄 {account_label} 将在 {start_delay:.1f} 秒后启动")
        
        thread = threading.Thread(
            target=run_single_account,
            args=(account_label, token, device_id, thread_random, accounts),
            daemon=True,
            name=f"Account-{idx}"
        )
        all_threads.append(thread)
        
        time.sleep(start_delay)
        thread.start()
    
    print(f"\n✅ 所有账号已启动，正在并发运行...\n")
    
    max_wait_seconds = MAX_RUN_HOURS_PER_ACCOUNT * 3600 + 600
    for thread in all_threads:
        thread.join(timeout=max_wait_seconds)
    
    print("\n🎉 所有账号任务已全部完成")
    
    with data_lock:
        results = list(all_accounts_data)
    send_notify("芳华未来运行简报", build_notify_content(results))
    
    # 强制退出主进程
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 脚本全局运行出错: {e}")
        sys.exit(1)
