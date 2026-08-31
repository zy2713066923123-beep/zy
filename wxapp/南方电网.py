import yyb  # 自动同步 yyb_go 存活账号
"""
 name: 南方电网
 cron: 40 08,20 * * *南方电网「南网在线」APP 积分任务 + 每日签到 自动化脚本

功能：
  1. 通过 getCode 统一接口获取微信 code（与项目其它脚本一致，WX_ID + 牛子/YYB 双协议自动路由）
  2. 南网登录接口用 code 换 x-auth-token
  3. 自动领取积分任务（查看电费账单等），已完成/已领取的自动跳过
  4. 自动签到：每天 1 次，7 天一循环（第 1~7 天分别 +1~+7 积分）
  5. 预存电费任务需实际充值，默认跳过
  6. 统一通知推送（青龙 notify，由 SendNotify.py 桥接；无 notify 环境自动降级为仅打印）

环境变量：
  WX_ID               微信账号，多账号换行或 & 分隔，格式：wxid#备注 或 openid
  NF_DIANWANG_TOKEN    备用 token（getCode 不可用时回退），可选
  CSG_X_AUTH_TOKEN     同上，可选

依赖：
  pip install requests
"""

import requests
import json
import os
import sys
import time
import re
import random
import logging
import argparse
from datetime import datetime
from typing import Optional, Dict, Any, List
import base64
from urllib.parse import quote

# 允许从仓库根目录导入统一的通知模块 SendNotify（与根目录 ikuuu.py / 认养一头牛.py 共用一份）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 统一取码（与项目其它脚本一致：WX_ID + getCode 双协议自动路由）

# 统一通知：桥接青龙内置 notify（无环境则降级为仅打印，绝不抛异常）
try:
    from SendNotify import capture_output
except Exception as exc:
    print(f"[警告] 通知模块 SendNotify.py 导入失败：{exc}，将跳过通知推送。")

    def capture_output(title: str = "脚本运行结果"):
        def decorator(func):
            return func

        return decorator

# 终端中文乱码修复: 把 stdout/stderr 强制成 UTF-8, 避免 Windows 控制台(GBK)把中文显示成乱码。
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============ 终端样式 ============
# 是否启用彩色输出: 仅在支持的终端启用, 重定向到文件时自动关闭, 避免乱码。
_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


class C:
    """ANSI 颜色 / 样式代码 (统一收口, 关闭彩色时全部为空)。"""
    RESET = "\033[0m" if _USE_COLOR else ""
    BOLD = "\033[1m" if _USE_COLOR else ""
    DIM = "\033[2m" if _USE_COLOR else ""
    CYAN = "\033[36m" if _USE_COLOR else ""
    GREEN = "\033[32m" if _USE_COLOR else ""
    YELLOW = "\033[33m" if _USE_COLOR else ""
    RED = "\033[31m" if _USE_COLOR else ""
    BLUE = "\033[34m" if _USE_COLOR else ""
    MAGENTA = "\033[35m" if _USE_COLOR else ""
    WHITE = "\033[37m" if _USE_COLOR else ""


def cwrap(text, color):
    """给文本加颜色 (未启用彩色时原样返回)。"""
    return "%s%s%s" % (color, text, C.RESET) if _USE_COLOR else text


def now_ts():
    """当前时间串, 用于日志时间戳。"""
    return datetime.now().strftime("%H:%M:%S")


def banner(title, width=56):
    """顶部大标题栏 (彩色 + 等宽边框)。"""
    bar = "━" * width
    line = f"┃ {cwrap(title, C.BOLD + C.CYAN)}".ljust(width - 1) + "┃"
    return "\n".join([cwrap(bar, C.CYAN), line, cwrap(bar, C.CYAN)])


def section(title, width=56):
    """阶段分隔栏 (带左侧标记)。"""
    return cwrap(f"\n┏{'─' * (width - 2)}┓\n┣─ {title} {'─' * (width - 5 - len(title))}┫", C.BLUE)


def hrule(width=56, color=C.DIM):
    return cwrap("─" * width, color)


# ============ 常量 ============
BASE_URL = "https://95598.csg.cn"

# 不再内置写死 token。脚本通过本地 code 服务用微信 code 自动换取 x-auth-token。
# 仅当 code 服务不可用、且用户自己配置了 NF_DIANWANG_TOKEN / config.json 时才回退。
X_AUTH_TOKEN = ""

# 青龙等容器环境下, 请求头 / Cookie 的值必须能被 latin-1 编码,
# 否则 http.client 会抛 UnicodeEncodeError 直接崩。这里把所有要写进
# 请求头 / Cookie 的字符串统一收口成 latin-1 安全的 ASCII, 非 ASCII 字符直接丢弃。
def _ascii(value):
    """把任意字符串转成 latin-1 安全的 ASCII, 用于请求头 / Cookie 值。"""
    if value is None:
        return ""
    s = str(value)
    return "".join(ch for ch in s if ord(ch) < 256)


DEFAULT_CONFIG = {
    "x_auth_token": "",
    "user_agent": (
        "Mozilla/5.0 (Linux; Android 14; 2512BPNDAC Build/UKQ1.230917.001; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/105.0.5195.148 "
        "MYWeb/0.11.0.250728104400 UWS/3.22.2.9999 UCBS/3.22.2.9999_220000000000 "
        "Mobile Safari/537.36 AlipayDefined AriverApp(mPaaSClient/10.2.8) MiniProgram Language/zh-Hans"
    ),
    "referer": "https://0000000000000141.95598.csg.cn/0000000000000141/1.0.3.1/index.html#pages/task/index",
    "timeout": 30,
}
# ============ 品赞代理 (Pinzan proxy) ============
# 业务请求优先走品赞代理, 获取失败则硬落直连 (与铛铛一下同构)。
# 代理只用于单个账号的业务层 (business) 请求; 不走 code 服务登录 (内网)。
PROXY_API = os.getenv("PROXY_API", "")                 # 品赞代理提取 API，非空才启用
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()   # http / socks5
PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"
PROXY_FETCH_INTERVAL = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

def parse_proxy_response(text):
    """解析品赞代理提取接口返回的 JSON/文本, 提取 {host, port, username, password}。"""
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        proxy_obj = None
        if isinstance(data.get("data"), list) and data["data"]:
            proxy_obj = data["data"][0]
        elif isinstance(data.get("data"), dict):
            proxy_obj = data["data"]
        elif data.get("ip") and data.get("port"):
            proxy_obj = data
        elif isinstance(data.get("result"), dict):
            proxy_obj = data["result"]
        if proxy_obj:
            host = proxy_obj.get("ip") or proxy_obj.get("host")
            port = proxy_obj.get("port")
            if host and port:
                return {
                    "host": str(host),
                    "port": int(port),
                    "username": proxy_obj.get("user") or proxy_obj.get("username") or "",
                    "password": proxy_obj.get("pass") or proxy_obj.get("password") or "",
                }
    except Exception:
        pass
    if ":" in text:
        parts = text.split(":")
        if len(parts) >= 2:
            try:
                return {
                    "host": parts[0],
                    "port": int(parts[1]),
                    "username": parts[2] if len(parts) > 2 else "",
                    "password": parts[3] if len(parts) > 3 else "",
                }
            except ValueError:
                pass
    return None

def build_proxy_dict(proxy_info):
    """根据代理信息生成 requests 用的 proxies 字典 (http + https)。"""
    if not proxy_info:
        return None
    host = proxy_info["host"]
    port = proxy_info["port"]
    username = proxy_info.get("username", "")
    password = proxy_info.get("password", "")
    auth = ""
    if username and password:
        auth = "%s:%s@" % (quote(username), quote(password))
    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = "%s://%s%s:%s" % (scheme, auth, host, port)
    print(cwrap("🌐 生成 %s 代理 %s:%s" % (scheme.upper(), host, port), C.CYAN))
    return {"http": proxy_url, "https": proxy_url}

def validate_proxy(proxies):
    """验证代理可用: 访问 PROXY_VALIDATE_URL 检查 200。"""
    if not proxies:
        return False, ""
    try:
        response = requests.get(PROXY_VALIDATE_URL, proxies=proxies, timeout=15)
        if response.status_code == 200:
            try:
                ip = response.json().get("origin", "未知")
            except Exception:
                ip = "未知"
            print(cwrap("✅ 代理验证通过, 出口 IP: %s" % ip, C.GREEN))
            return True, ip
    except Exception as exc:
        print(cwrap("⚠️ 代理验证失败: %s" % exc, C.YELLOW))
    return False, ""

def get_valid_proxy(account_name):
    """获取一个可用的品赞代理, 失败返回 (None, "") 表示使用直连。"""
    if not PROXY_API:
        print(cwrap("⚠️ [代理] %s 未配置 PROXY_API，使用直连" % account_name, C.YELLOW))
        return None, ""
    print(cwrap("🔌 [代理] %s 正在获取品赞代理..." % account_name, C.CYAN))
    for index in range(1, PROXY_RETRY_TIMES + 1):
        try:
            response = direct_session().get(PROXY_API, timeout=15)
            proxy_info = parse_proxy_response(response.text)
            if not proxy_info:
                print(cwrap("⚠️ [代理] 第 %s 次代理解析失败" % index, C.YELLOW))
                continue
            print(cwrap("✅ [代理] 提取到 %s:%s" % (proxy_info["host"], proxy_info["port"]), C.GREEN))
            proxies = build_proxy_dict(proxy_info)
            ok, ip = validate_proxy(proxies)
            if ok:
                return proxies, ip
            print(cwrap("⚠️ [代理] 第 %s 次代理不可用" % index, C.YELLOW))
        except Exception as exc:
            print(cwrap("⚠️ [代理] 第 %s 次获取代理异常 %s" % (index, exc), C.YELLOW))
        if index < PROXY_RETRY_TIMES:
            time.sleep(2)
    print(cwrap("⚠️ [代理] 获取失败, 使用直连", C.YELLOW))
    return None, ""

def request_with_proxy(method, url, proxies=None, server="", **kwargs):
    """发起一次带代理缓冲的 HTTP 请求; 代理不可用时硬落直连。

    业务请求需要鉴权 (x-auth-token 头 + CAMSID cookie), 由调用方通过
    kwargs 的 headers/cookies 传入, 这里原样透传, 避免丢失导致 403。
    """
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    if proxies:
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            print(cwrap("⚠️ [代理] %s 代理请求失败: %s" % (server, exc), C.YELLOW))
            if not ENABLE_DIRECT_FALLBACK:
                raise
            print(cwrap("🔁 [兜底] 切换直连重试", C.YELLOW))
    session = direct_session()
    return session.request(method, url, **kwargs)


# ============ Code 换 Token (统一 getCode 双协议取码) ============
# 南网在线微信小程序 appId (来自登录请求 Referer: servicewechat.com/wx325a533aedaafe35)
APPID = "wx325a533aedaafe35"

# 账号来自环境变量 WX_ID, 格式: wxid#备注 或 openid, 多账号换行或 & 分隔。
# 与项目其它脚本一致, 经 getCode 自动路由牛子/YYB 协议取 code。
# ============ 账号来源：优先从 yyb-go 拉取存活账号，WX_ID 仅作兜底 ============
WX_IDS = []
try:
    accs = load_accounts()
    if accs:
        WX_IDS = [str(acc.get("openid") or acc.get("wxid") or acc.get("id") or "") for acc in accs
                  if (acc.get("openid") or acc.get("wxid") or acc.get("id"))]
        print(f"ℹ️  已从 yyb-go 同步 {len(WX_IDS)} 个存活账号")
except Exception:
    pass

if not WX_IDS:
    WX_IDS = [s.strip() for s in os.getenv("WX_ID", "").replace("&", "\n").splitlines() if s.strip()]
    if WX_IDS:
        print(f"ℹ️  yyb-go 无存活账号，回退使用 WX_ID 配置的 {len(WX_IDS)} 个账号")
if not WX_IDS:
    print("ℹ️  未配置环境变量 WX_ID，将尝试使用环境变量/config.json 中的 token 兜底")

# 用 code 换 token 的登录接口 (南网在线微信小程序)
LOGIN_URL = "https://95598.csg.cn/w2/wx/user/app/AppCore/login"
LOGIN_CHANNEL = "xcx"
LOGIN_REFERER = "https://servicewechat.com/wx325a533aedaafe35/537/page-frame.html"
LOGIN_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13)"
)


def direct_session() -> requests.Session:
    """不走系统代理的直连 session (与铛铛一下一致)。"""
    session = requests.Session()
    session.trust_env = False
    return session


def get_code(wxid: str) -> str | None:
    """通过 getCode 统一接口获取微信登录 code (与项目其它脚本一致)。

    wxid 可带备注 (格式 wxid#备注), 这里只取 # 之前的标识。
    """
    if not get_single_code:
        print(cwrap("❌ [授权] getCode 不可用, 无法取 code", C.RED))
        return None
    identifier = wxid.split("#", 1)[0].strip()
    print(cwrap(f"🔐 [授权] 通过 getCode 请求 code (账号: {wxid})", C.CYAN))
    try:
        code = get_single_code(APPID, identifier)
        if not code:
            print(cwrap("❌ [授权] code 获取失败", C.RED))
            return None
        print("✅ [授权] code 获取成功")
        return code
    except Exception as exc:
        print(f"❌ [授权] code 获取异常: {exc}")
        return None


def login_by_code(server: str, code: str) -> str | None:
    """用 code 换取 x-auth-token (南网在线登录接口)。"""
    print(cwrap("🔐 [登录] 使用 code 换 token", C.CYAN))
    try:
        # 南网登录接口要求 code 为 base64 编码 (HAR 中 body 即 code=<base64>)；
        # code 服务返回的是原始微信 code, 这里先 base64 编码再提交。
        code_b64 = base64.b64encode((code or "").encode("utf-8")).decode("ascii")
        # 南网登录请求也随携品赞代理 (code 服务本身是内网, 代理不影响其可用性)。
        proxies, _ = get_valid_proxy(server)
        response = direct_session().post(
            LOGIN_URL,
            headers={
                "User-Agent": LOGIN_USER_AGENT,
                "xweb_xhr": "1",
                "channel": LOGIN_CHANNEL,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": LOGIN_REFERER,
                "Accept": "*/*",
            },
            data={"code": code_b64},
            timeout=20,
        )
        try:
            data = response.json()
        except Exception:
            print(f"❌ [登录] 响应解析失败: {response.text[:200]}")
            return None
        if data.get("sta") != "00":
            print(f"❌ [登录] 换 token 失败: {data.get('message')} (sta={data.get('sta')}, data={data.get('data')})")
            return None
        token = (data.get("data") or {}).get("token") or (data.get("data") or {}).get("access_token")
        if not token:
            print(f"❌ [登录] 响应中未找到 token: {data}")
            return None
        print(f"✅ [登录] token 获取成功: {token[:8]}****")
        return token
    except Exception as exc:
        print(f"❌ [登录] 请求异常: {exc}")
        return None


# 任务类型
TASK_TYPE_VIEW_BILL = "14"     # 查看电费账单
TASK_TYPE_PREPAID = "15"       # 预存电费 (跳过)

# 任务状态
TASK_STATUS_NOT_DONE = "0"     # 未完成
TASK_STATUS_DONE_UNCLAIMED = "1"  # 已完成未领取
TASK_STATUS_CLAIMED = "2"      # 已领取


def load_config(config_file="config.json"):
    """加载配置: 环境变量 > config.json > 默认值。

    config.json / token.txt 优先从脚本所在目录查找, 其次当前工作目录,
    这样无论从哪个目录 (任务计划 / cron / 青龙) 启动都能找到配置。
    """
    # 把传入的相对路径解析为"脚本目录优先, 其次 cwd"的绝对路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    if not os.path.isabs(config_file):
        candidates.append(os.path.join(script_dir, config_file))
        candidates.append(os.path.join(os.getcwd(), config_file))
    else:
        candidates.append(config_file)
    resolved = next((p for p in candidates if os.path.exists(p)), candidates[0])

    config = dict(DEFAULT_CONFIG)

    # 1. 从 config.json 加载
    if os.path.exists(resolved):
        try:
            with open(resolved, "r", encoding="utf-8-sig") as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception as e:
            print(f"[警告] 读取 {resolved} 失败: {e}")

    # 2. 环境变量覆盖 (青龙 / 容器环境主要走这里)
    # 依次尝试这些变量名, 取第一个非空值。青龙里在"环境变量"里加任意一个即可,
    # 推荐用 NF_DIANWANG_TOKEN 或 CSG_X_AUTH_TOKEN, 值为抓包到的 x-auth-token。
    env_map = {
        "NF_DIANWANG_TOKEN": "x_auth_token",
        "CSG_X_AUTH_TOKEN": "x_auth_token",
        "NANFANGDIANWANG_TOKEN": "x_auth_token",
        "NFDW_TOKEN": "x_auth_token",
        "X_AUTH_TOKEN": "x_auth_token",
    }
    for env_key, config_key in env_map.items():
        val = os.environ.get(env_key, "").strip()
        if val:
            config[config_key] = val

    # 2b. (原 PushPlus 环境变量分支已移除, 统一走 SendNotify 通知)

    # 3. 单独的 token.txt (一行一个 token, 取第一行非空行)
    # 同样优先脚本目录
    token_candidates = []
    if not os.path.isabs("token.txt"):
        token_candidates.append(os.path.join(script_dir, "token.txt"))
        token_candidates.append(os.path.join(os.getcwd(), "token.txt"))
    else:
        token_candidates.append("token.txt")
    token_path = next((p for p in token_candidates if os.path.exists(p)), None)
    if not config["x_auth_token"] and token_path:
        try:
            with open(token_path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    t = line.strip()
                    if t and not t.startswith("#"):
                        config["x_auth_token"] = t
                        break
        except Exception:
            pass

    # 注意: 这里不再因为缺少 token 而退出。
    # 默认走本地 code 服务自动换取 token; 仅在 --no-code 模式下才必须依赖
    # 环境变量 / config.json 中的 token, 那种情况在 main() 里单独温和提示。
    return config


def _strip_ansi(text):
    """去掉 ANSI 转义, 用于写日志文件时保持纯文本。"""
    return re.sub(r"\033\[[0-9;]*m", "", text)


# 通知推送已统一接入 SendNotify.capture_output：
# 直接装饰 main(), 自动捕获全部 print 输出并在结束后桥接青龙 notify 推送；
# 无 notify 环境时自动降级为仅打印, 不影响主流程。无需单独调用推送函数。


class NanFangDianWang:
    """南方电网积分任务自动化客户端"""

    def __init__(self, config):
        self.config = config
        self.base_url = BASE_URL
        self.token = config["x_auth_token"]
        self.timeout = config["timeout"]

        self.session = requests.Session()
        # 业务请求随携品赞代理: 每个账号取一次; 失败时 _post 内部硬落直连。
        self.proxies, self.proxy_ip = get_valid_proxy("南方电网")
        # 所有写进请求头 / Cookie 的值都先过 _ascii, 避免青龙等环境下
        # 非 ASCII 字符触发 http.client 的 latin-1 编码崩溃。
        self.session.headers.update({
            "Content-Type": "application/json",
            "x-auth-token": _ascii(self.token),
            "Accept-Charset": "UTF-8",
            "User-Agent": _ascii(config["user_agent"]),
            "Referer": _ascii(config["referer"]),
        })
        self.session.cookies.set("CAMSID", _ascii(self.token))

        # 运行时状态
        self.account_id = None
        self.area_code = None
        self.area_name = None
        self.user_id = None
        self.elec_accounts = []
        self.log_data = []

    def log(self, msg, level="INFO"):
        """记录一条日志 (带时间戳 + 彩色级别标签), 同时留存到 log_data。"""
        style = {
            "INFO": (C.WHITE, "ℹ "),
            "SUCCESS": (C.GREEN, "✔ "),
            "ERROR": (C.RED, "✘ "),
            "WARN": (C.YELLOW, "▲ "),
            "DEBUG": (C.DIM, "· "),
        }.get(level, (C.WHITE, "  "))
        prefix, mark = style
        # 终端显示带颜色, 留存文本去掉 ANSI 转义, 保证日志文件干净。
        plain = f"[{now_ts()}] {mark} {msg}"
        colored = f"[{cwrap(now_ts(), C.DIM)}] {cwrap(mark, prefix)}{cwrap(' ', C.RESET)}{msg}"
        print(colored)
        self.log_data.append(plain)

    def log_step(self, idx, total, name):
        """步骤小标题, 如'步骤 2/5  获取绑定户号'。"""
        head = cwrap(f"步骤 {idx}/{total}", C.MAGENTA) + cwrap(f"  {name}", C.BOLD)
        self.log(head, "DEBUG")

    def panel(self, title, rows, width=56):
        """渲染一个简单的面板 (用于汇总)。"""
        out = [cwrap(f"┏{'─' * (width - 2)}┓", C.GREEN)]
        out.append(cwrap(f"┣─ {title}", C.GREEN) + cwrap(" " + "─" * (width - 5 - len(title)) + "┫", C.GREEN))
        for k, v in rows:
            out.append(f"┃{cwrap(k, C.CYAN)}: {v}")
        out.append(cwrap(f"┗{'─' * (width - 2)}┛", C.GREEN))
        block = "\n".join(out)
        print(block)
        for line in block.splitlines():
            self.log_data.append(_strip_ansi(line))

    def task_table(self, rows, width=56):
        """渲染任务表格: rows = [(名称, 状态, 奖励, 结果)]。固定列宽, 对齐干净。"""
        # 列宽: 任务名 16 / 状态 12 / 奖励 8 / 结果 自适应
        w_name, w_status, w_reward = 16, 12, 8

        def clip(text, n):
            text = str(text)
            return text[: n - 1] + "…" if len(text) > n else text

        top = cwrap("┏" + "─" * (width - 2) + "┓", C.BLUE)
        hdr = (
            cwrap("┣─ ", C.BLUE)
            + cwrap(clip("任务名", w_name).ljust(w_name), C.BLUE)
            + cwrap(" ", C.BLUE)
            + cwrap(clip("状态", w_status).ljust(w_status), C.BLUE)
            + cwrap(" ", C.BLUE)
            + cwrap(clip("奖励", w_reward).ljust(w_reward), C.BLUE)
            + cwrap(" ", C.BLUE)
            + cwrap("结果", C.BLUE)
            + cwrap(" ┫", C.BLUE)
        )
        print(top)
        print(hdr)
        for name, status, reward, result in rows:
            line = (
                f"┃{clip(name, w_name).ljust(w_name)} "
                f"{clip(status, w_status).ljust(w_status)} "
                f"{str(reward).ljust(w_reward)} "
                f"{result}"
            )
            print(line)
            self.log_data.append(_strip_ansi(line))
        foot = cwrap("┗" + "─" * (width - 2) + "┛", C.BLUE)
        print(foot)
        self.log_data.append(_strip_ansi(foot))

    def _post(self, path, data=None):
        """发送 POST 请求 (业务请求随携品赞代理, 失败硬落直连)。"""
        url = f"{self.base_url}{path}"
        body = data or {}
        try:
            r = request_with_proxy(
                "POST", url,
                proxies=self.proxies, server="南方电网",
                headers=dict(self.session.headers),
                cookies=dict(self.session.cookies),
                json=body, timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            self.log(f"请求超时: {path}", "ERROR")
            return {"sta": "99", "message": "请求超时"}
        except requests.exceptions.ConnectionError:
            self.log(f"连接失败: {path}", "ERROR")
            return {"sta": "99", "message": "连接失败"}
        except requests.RequestException as e:
            self.log(f"网络错误: {e}", "ERROR")
            return {"sta": "99", "message": str(e)}
        except json.JSONDecodeError:
            self.log(f"响应解析失败: {path}", "ERROR")
            return {"sta": "99", "message": "JSON解析失败"}

    def _check(self, result, action):
        """检查 API 响应"""
        sta = result.get("sta", "")
        if sta == "00":
            return True
        # 非 00 一律视为未成功; 调用方对已知的终态(已签到/已领取/单日完成)单独处理。
        return False

    @staticmethod
    def _is_terminal(result):
        """非 00 返回中属于"已做/做不了"的终态时返回 True (正常跳过)。"""
        if result.get("sta") == "00":
            return False
        msg = result.get("message", "")
        terminal_keywords = ("已签到", "已领取", "已完成", "不能领取", "不可重复", "无需", "已经")
        return any(k in msg for k in terminal_keywords)

    # ==================== 账户相关 ====================
    def get_account_info(self):
        """获取账户信息"""
        self.log("获取账户信息...", "INFO")
        result = self._post("/mp/w2/szfw-points-txhsj/account/info")
        if not self._check(result, "获取账户信息"):
            return None

        data = result.get("data", {})
        self.account_id = data.get("accountId")
        self.area_code = data.get("areaCode")
        self.area_name = data.get("areaName", "未知")
        self.user_id = data.get("userId")
        points = data.get("myPoints", 0)

        self.log(f"账户ID: {self.account_id}")
        self.log(f"区域: {self.area_name} ({self.area_code})")
        self.log(f"当前积分: {points}")
        return data

    def get_bind_ele_users(self):
        """获取绑定的电户账号"""
        self.log("获取绑定户号列表...", "INFO")
        result = self._post("/mp/w2/wx/portal/eleCustNumber/queryBindEleUsers")
        if not self._check(result, "获取绑定户号"):
            return []

        self.elec_accounts = result.get("data", [])
        # 真实接口里 elecCustNumber 有时为 null, 回退用 custNumber
        for acct in self.elec_accounts:
            acct["_elec_no"] = acct.get("elecCustNumber") or acct.get("custNumber") or ""
        for acct in self.elec_accounts:
            self.log(
                f"户号: {acct.get('_elec_no') or acct.get('elecCustNumber') or acct.get('custNumber')} "
                f"({acct.get('userName')}) "
                f"- {acct.get('eleAddress')} "
                f"[areaCode:{acct.get('areaCode')}]"
            )
        return self.elec_accounts

    def get_points(self):
        """获取当前积分"""
        result = self._post("/mp/ucs/ma/zt/AccountManageApi/getUserPoints")
        if self._check(result, "获取积分"):
            return result.get("data", 0)
        return -1

    # ==================== 任务相关 ====================
    def get_task_list(self):
        """获取任务列表"""
        self.log("获取任务列表...", "INFO")
        result = self._post("/mp/w2/szfw-points-txhsj/taskInfo/taskInfoList")
        if not self._check(result, "获取任务列表"):
            return []
        return result.get("data", [])

    def do_view_electricity_task(self, elec_cust_no):
        """执行"查看电费账单"任务

        流程: viewElectricityCheck(view, elecCustNo) -> viewElectricityCheck(get)
        """
        self.log(f"  执行查看电费账单 (户号:{elec_cust_no})...")

        # 第一步: view
        result = self._post(
            "/mp/w2/szfw-points-txhsj/taskDock/viewElectricityCheck",
            {"getOrView": "view", "elecCustNo": elec_cust_no}
        )
        if not self._check(result, "查看电费账单(view)"):
            return False

        view_data = result.get("data", {})
        if view_data and view_data.get("result") == 1:
            self.log("  -> view标记成功", "SUCCESS")
        else:
            self.log(f"  -> view返回: {view_data}", "WARN")

        # 第二步: get
        time.sleep(1)
        result2 = self._post(
            "/mp/w2/szfw-points-txhsj/taskDock/viewElectricityCheck",
            {"getOrView": "get"}
        )
        if not self._check(result2, "查看电费账单(get)"):
            return False

        self.log("  -> 任务执行完毕", "SUCCESS")
        return True

    def receive_task_reward(self, task_id, task_name=""):
        """领取任务奖励。返回: 'ok' 成功 / 'terminal' 已领过等终态 / 'fail' 真实失败。"""
        self.log(f"  领取奖励: {task_name} (ID:{task_id})...")
        result = self._post(
            "/mp/w2/szfw-points-txhsj/taskInfo/receive",
            {"taskId": task_id}
        )
        if result.get("sta") == "00":
            self.log(f"  领取成功!", "SUCCESS")
            return "ok"
        if self._is_terminal(result):
            self.log(f"  跳过: {result.get('message', '')}", "INFO")
            return "terminal"
        self.log(f"  领取失败 [sta={result.get('sta')}]: {result.get('message', '')}", "WARN")
        return "fail"

    # ==================== 签到相关 ====================
    def get_sign_status(self):
        """获取签到状态"""
        result = self._post("/mp/w2/szfw-points-txhsj/taskInfo/taskSignList")
        if not self._check(result, "获取签到状态"):
            return None
        return result.get("data", {})

    def do_sign(self, task_id, points):
        """执行签到"""
        self.log(f"  执行签到 (本次预期 {points} 积分)...")
        result = self._post(
            "/mp/w2/szfw-points-txhsj/taskInfo/signOperate",
            {"taskId": task_id, "thisGainPoints": points}
        )
        if result.get("sta") == "00":
            gained = result.get("data", 0)
            self.log(f"  签到成功! 获得 {gained} 积分", "SUCCESS")
            return gained
        if self._is_terminal(result):
            self.log(f"  跳过: {result.get('message', '')}", "INFO")
        else:
            self.log(f"  签到失败 [sta={result.get('sta')}]: {result.get('message', '')}", "WARN")
        return 0
    # ==================== 主流程 ====================
    def run(self, task_only=False, sign_only=False):
        """主流程入口 (带美化日志 / 步骤 / 汇总面板)。

        task_only / sign_only 由命令行参数控制, 二选一可跳过另一半。
        """
        title = "南方电网 · 任务 + 签到"
        print(banner(title))
        print(cwrap(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", C.DIM))
        print(cwrap("  账号: " + (self.token[:8] + "****" if self.token else "未配置"), C.DIM))

        # Step 1: 获取账户信息
        self.log_step(1, 5, "获取账户信息")
        account = self.get_account_info()
        if not account:
            error_msg = "无法获取账户信息! token 可能已过期或被限制"
            self.log(error_msg, "ERROR")
            # 失败详情会由 @capture_output 统一捕获并推送, 这里无需单独推送
            return False

        # Step 2: 获取绑定户号
        self.log_step(2, 5, "获取绑定户号")
        self.get_bind_ele_users()
        if not self.elec_accounts:
            self.log("未找到绑定的户号!", "WARN")

        # Step 3: 处理积分任务 (--sign-only 时跳过)
        self.log_step(3, 5, "处理积分任务")
        if sign_only:
            self.log("  (--sign-only 已指定, 跳过任务处理)", "INFO")
            tasks = []
        else:
            tasks = self.get_task_list()
        task_points = 0
        task_rows = []
        for task in tasks:
            task_name = task.get("taskName", "未知任务")
            task_id = task.get("taskId", "")
            finish_status = task.get("taskFinishStatus", "0")
            each_points = task.get("eachGainPoints") or 0
            task_busi_type = task.get("taskBusiType", "")
            task_link_url = task.get("taskLinkUrl", "")

            status_map = {"0": "未完成", "1": "已完成未领取", "2": "已领取"}
            status_text = status_map.get(finish_status, finish_status)
            reward = f"+{each_points}" if each_points else "-"
            result_text = ""

            if task_busi_type == TASK_TYPE_PREPAID:
                result_text = "需充值·跳过"
                self.log(f"  {task_name}: 预存电费任务需要实际充值, 跳过", "WARN")
            elif finish_status == TASK_STATUS_DONE_UNCLAIMED:
                rc = self.receive_task_reward(task_id, task_name)
                if rc == "ok":
                    task_points += each_points
                    result_text = cwrap(f"领取 +{each_points}", C.GREEN)
                elif rc == "terminal":
                    result_text = "已领过·跳过"
                else:
                    result_text = "领取失败"
            elif finish_status == TASK_STATUS_CLAIMED:
                result_text = "已领取"
                self.log(f"  {task_name}: 已领取, 跳过", "INFO")
            elif finish_status == TASK_STATUS_NOT_DONE:
                if task_link_url == "/houseNumDetail" and task_busi_type == TASK_TYPE_VIEW_BILL:
                    target_area = (self.area_code or "0401")[:4]
                    matched = [a for a in self.elec_accounts
                               if (a.get("areaCode") or "").startswith(target_area)] or self.elec_accounts
                    if matched:
                        elec_no = matched[0].get("_elec_no") or matched[0].get("elecCustNumber") or matched[0].get("custNumber") or ""
                        self.do_view_electricity_task(elec_no)
                        time.sleep(2)
                        rc = self.receive_task_reward(task_id, task_name)
                        if rc == "ok":
                            task_points += each_points
                            result_text = cwrap(f"执行并领取 +{each_points}", C.GREEN)
                        elif rc == "terminal":
                            result_text = "已领过·跳过"
                        else:
                            result_text = "执行后领取失败"
                    else:
                        result_text = "无户号·跳过"
                        self.log(f"  {task_name}: 无可用户号执行", "WARN")
                else:
                    result_text = "暂不支持"
                    self.log(f"  {task_name}: 未知任务类型, 暂不支持自动执行", "WARN")
            else:
                result_text = "未知状态"
            task_rows.append((task_name, status_text, reward, _strip_ansi(result_text)))
            time.sleep(1)
        if task_rows:
            self.task_table(task_rows)

        # Step 4: 每日签到
        self.log_step(4, 5, "每日签到")
        sign_points = 0
        sign_result = "未执行"
        sign_status = ""  # 提前声明, task_only 时不触发 NameError
        if task_only:
            self.log("  (--task-only 已指定, 跳过签到)", "INFO")
            sign_data = None
            sign_result = "已跳过(--task-only)"
        else:
            sign_data = self.get_sign_status()
            if not sign_data:
                sign_result = "状态获取失败"
                self.log("  获取签到状态失败", "ERROR")
            else:
                sign_status = sign_data.get("taskFinishStatus", "0")
                task_id = sign_data.get("taskId", "")
                sign_count = sign_data.get("singCount", 0)
                rule_list = sign_data.get("taskRuleSignList", [])
                if sign_status == "0":
                    day_index = sign_count % 7
                    if day_index < len(rule_list):
                        rule = rule_list[day_index]
                        expected_points = rule.get("signGainPoints", 1)
                        gained = self.do_sign(task_id, expected_points)
                        if gained:
                            sign_points = gained
                            sign_count += 1
                            extra = rule.get("extraPointFlag")
                            if extra and (sign_count - 1) % 7 == 2:
                                self.log(f"  第 3 天 (平台额外赠送积分由服务端发放)", "INFO")
                            elif extra and sign_count % 7 == 0:
                                self.log(f"  第 7 天 (平台额外赠送积分由服务端发放)", "INFO")
                            sign_result = cwrap(f"签到 +{gained} (第{sign_count}天)", C.GREEN)
                        else:
                            sign_result = "签到失败"
                    else:
                        sign_result = "索引异常"
                        self.log(f"  签到索引异常, signCount={sign_count}", "ERROR")
                else:
                    sign_result = cwrap(f"今日已签到 (连续第{sign_count}天)", C.YELLOW)
                    if sign_count > 0:
                        day_index = (sign_count - 1) % 7
                        if day_index < len(rule_list):
                            earned = rule_list[day_index].get("signGainPoints", "?")
                            self.log(f"  今日已获得: {earned} 积分", "SUCCESS")

        # Step 5: 汇总
        self.log_step(5, 5, "结果汇总")
        total_gained = task_points + sign_points
        latest_points = self.get_points()
        points_text = str(latest_points) if latest_points >= 0 else "获取失败"
        self.panel("运行汇总", [
            ("任务积分", cwrap(f"+{task_points}", C.GREEN) if task_points else "+0"),
            ("签到积分", cwrap(f"+{sign_points}", C.GREEN) if sign_points else "+0"),
            ("本次共获得", cwrap(f"+{total_gained}", C.BOLD + C.GREEN) if total_gained else "+0"),
            ("当前总积分", points_text),
            ("签到结果", _strip_ansi(sign_result)),
        ])

        # 通知推送统一由 @capture_output 装饰器在 main() 结束时桥接青龙 notify；
        # 这里不再单独推送, 仅保留本地日志。

        # 保存本地日志
        self.save_log_file(title)
        return True

    def save_log_file(self, title):
        """把本次运行日志写入本地文件 (带日期), 便于回看。"""
        try:
            date_str = datetime.now().strftime("%Y-%m-%d")
            # 日志写到脚本所在目录, 避免从其他目录启动时散落到 cwd
            script_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(script_dir, f"run_log_{date_str}.txt")
            with open(path, "a", encoding="utf-8") as f:
                f.write("=" * 60 + "\n")
                f.write(f"{title}  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n")
                f.write("\n".join(self.log_data) + "\n\n")
            self.log(f"运行日志已写入 {path}", "DEBUG")
        except Exception as e:  # 写日志失败不应影响主流程
            self.log(f"写入本地日志失败: {e}", "WARN")


# ==================== 入口 ====================
@capture_output("南方电网 任务+签到")
def main():
    parser = argparse.ArgumentParser(description="南方电网 任务+签到 自动化脚本 (code 换 token 版)")
    parser.add_argument(
        "-c", "--config", default="config.json",
        help="配置文件路径 (默认: config.json)"
    )
    parser.add_argument(
        "-t", "--task-only", action="store_true",
        help="只处理任务, 跳过签到"
    )
    parser.add_argument(
        "-s", "--sign-only", action="store_true",
        help="只做签到, 跳过任务"
    )
    args = parser.parse_args()

    base_config = load_config(args.config)
    results = []

    if not WX_IDS:
        # 无 WX_ID: 仅使用环境变量 / config.json 中的 token (与其他脚本的兜底一致)
        if not base_config.get("x_auth_token"):
            print(cwrap("⚠️ [提示] 未配置 WX_ID, 也未在环境变量/config.json 中找到 token。", C.YELLOW))
            print(cwrap("   请在环境变量 WX_ID 中填入 wxid#备注 (多账号换行或 & 分隔), 或提供 NF_DIANWANG_TOKEN 等 token。", C.DIM))
        else:
            nfdw = NanFangDianWang(base_config)
            ok = nfdw.run(task_only=args.task_only, sign_only=args.sign_only)
            results.append({"server": "env/config", "success": bool(ok)})
    else:
        # 有 WX_ID: 逐个经 getCode 取 code -> 换 token -> 做任务+签到
        for index, wxid in enumerate(WX_IDS, 1):
            try:
                result = run_account(index, len(WX_IDS), wxid, base_config, args)
                results.append(result)
            except Exception as exc:
                print(f"❌ [主程序] {wxid} 执行异常: {exc}")
                results.append({"server": wxid, "success": False, "error": str(exc)})
            if index < len(WX_IDS):
                time.sleep(2 + random.random() * 2)

    success = [r for r in results if r.get("success")]
    print(cwrap(f"\n━━ 执行完毕: 成功 {len(success)}/{len(results)} 个账号 ━━", C.BOLD + C.CYAN))


def run_account(index: int, total: int, wxid: str, base_config: dict, args) -> dict:
    """单个账号的完整流程: 取 code -> 换 token -> 做任务+签到。"""
    print(cwrap(f"\n########## 账号 {index}/{total}  (WX_ID: {wxid}) ##########", C.BOLD + C.MAGENTA))

    config = dict(base_config)
    token = None

    # 1. 通过 getCode 取 code
    code = get_code(wxid)
    if code:
        # 2. 用 code 换 x-auth-token
        token = login_by_code(wxid, code)

    if not token:
        # 兜底: 使用环境变量 / config.json 里已有的 token (若有)
        fallback = base_config.get("x_auth_token", "")
        if fallback:
            print(cwrap("⚠️ [授权] code 换 token 失败, 回退使用环境变量/config.json 的 token", C.YELLOW))
            token = fallback
        else:
            print(cwrap("❌ [授权] 未获取到 token, 跳过该账号", C.RED))
            return {"server": wxid, "success": False, "token": "-"}

    config["x_auth_token"] = token
    nfdw = NanFangDianWang(config)
    ok = nfdw.run(task_only=args.task_only, sign_only=args.sign_only)
    return {"server": wxid, "success": bool(ok), "token": token[:8] + "****"}


if __name__ == "__main__":
    main()