#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大潮

cron: 12 8 * * *
new Env("大潮")

青龙环境变量:
  DaChao="手机号&密码"
  DaChao="手机号&密码&微信member"              # 账号+红包领取 token
  DaChao_OCR_SERVER=http://你的OCR主机:端口   # 滑块 OCR 服务基址 yangxiao6/stupidocr:main
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import importlib.util
import json
import math
import os
import random
import re
import secrets
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib import error, parse, request


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


TMUYUN_BASE = "https://vapp.tmuyun.com"
PASSPORT_BASE = "https://passport.tmuyun.com"
TENANT_ID = "94"
CLIENT_ID = "10048"
TMUYUN_SALT = "FR*r!isE5W"
APP_VERSION = "14.1.6"
SDK_VERSION = "6.11.0"
APP_SIGN = "xsb_hn"
AIHOGE_BASE = "https://m.aihoge.com"
AGED_BASE = "https://aged.tmuyun.com"
AGED_DEFAULT_DRAMA_ID = "1279"
AGED_DEFAULT_VIDEO_TIERS = [
    {"duration": 5, "prompt": "观看满5分钟，快来抽奖吧", "activityId": "24346f5cafbcb334c969d4e9458cac69", "claim_index": 0},
    {"duration": 15, "prompt": "观看满 15分钟，快来抽奖吧", "activityId": "f8eda50d6d4e84b1f5f70e2dfbd8d9e6", "claim_index": 1},
    {"duration": 30, "prompt": "观看满 30分钟，快来抽奖吧", "activityId": "d5ce80329ab20786782ab31429b495d0", "claim_index": 2},
    {"duration": 60, "prompt": "观看满 60分钟，快来抽奖吧", "activityId": "f7ae8506f58bc8f2aeaa3520852139fb", "claim_index": 3},
]
AGED_AES_KEY = b"0EoJUm6Ayw8W8jud"
AGED_AES_IV = b"0102530405460708"
AIHOGE_SIGNATURE_PREFIX = " &id&mobile&nick_name&&"
AIHOGE_SIGNATURE_SALT = "KO>N<O5&3^L1%23YH0H1#G91*2H"
AIHOGE_DEFAULT_SIGN_ACTIVITY_ID = "5d0346cd550e4a169f63b678114aba98"
AIHOGE_DEFAULT_LIMIT_ID = "1fe39c6dbcf24e1ca641b472369a07d1"
AIHOGE_DEFAULT_READ_ACTIVITY_ID = "1fe39c6dbcf24e1ca641b472369a07d1"
AIHOGE_DEFAULT_LOTTERY_ID = "1ebd2eed6cbadcb8474cda9b07d761c9"
AIHOGE_DEFAULT_OCR_SERVER = ""  # 不写死服务器；请用环境变量 DaChao_OCR_SERVER
DAILY_MATCH_BASE = "https://active.hndachao.cn"
DAILY_MATCH_DEFAULT_PATH = "/open/xxdtest/dailyMatchTest"
DAILY_MATCH_FANS_PATH = "/open/xxdtest/dailyMatchFans"
DAILY_MATCH_LEGACY_PATH = "/open/xxdtest/dailyMatch"
DAILY_MATCH_DEFAULT_LOTTERY_ID = "d0c488f4510398915cd6d3a5d95af635"
DAILY_MATCH_LOTTERY_IDS = {
    20: "b9e4724f92999927d91cc089bdb0c58e",
    40: "abf6dcf9e9c746db0fcb081ccaa09f7e",
    60: "d0c488f4510398915cd6d3a5d95af635",
}
DAILY_MATCH_ALIASES = {
    "test": DAILY_MATCH_DEFAULT_PATH,
    "dailymatchtest": DAILY_MATCH_DEFAULT_PATH,
    "dailyMatchTest": DAILY_MATCH_DEFAULT_PATH,
    "fans": DAILY_MATCH_FANS_PATH,
    "dailymatchfans": DAILY_MATCH_FANS_PATH,
    "dailyMatchFans": DAILY_MATCH_FANS_PATH,
    "有缘": DAILY_MATCH_FANS_PATH,
    "有缘对对碰": DAILY_MATCH_FANS_PATH,
    "match": DAILY_MATCH_LEGACY_PATH,
    "dailymatch": DAILY_MATCH_LEGACY_PATH,
    "dailyMatch": DAILY_MATCH_LEGACY_PATH,
    "legacy": DAILY_MATCH_LEGACY_PATH,
}
REDPACKET_CLAIM_LINK = "https://m.aihoge.com/lottery/rotor/drawRedPacket?CHECK_CODE={code}"
CLAIM_SKIP_STATUS = {2, 6}
SCRIPT_NAME = "大潮"
FALSE_VALUES = {"0", "false", "no", "off", "disable", "disabled"}

# =============================================================================
# 手动开关区（改这里最方便；优先级高于青龙环境变量）
# 约定：
#   True  = 强制开启该模块
#   False = 强制关闭该模块
#   None  = 不强制，继续读取环境变量（默认逻辑）
# 场景示例：
#   1) 调试排错时先开 DEBUG     -> MANUAL_DEBUG = True
#   2) APP 当前没有对对碰新活动 -> MANUAL_ENABLE_MATCH = False
#   3) 只想跑登录/签到/阅读     -> 关闭 MATCH / LOTTERY / CLAIM
#   4) 临时指定新阅读活动 ID    -> MANUAL_READ_ACTIVITY_ID = "新ID"
# =============================================================================

# 调试开关：默认关闭，日志精简
# True  = 详细日志，并自动开启 SHOW_TOKEN / SAVE_SESSION / GET_MEMBER
# False = 正常运行（默认）
# None  = 跟随环境变量 DaChao_DEBUG（未设置则关闭）
MANUAL_DEBUG = False

# 对对碰：当前 APP 无新活动时可改 False，避免空跑旧活动
MANUAL_ENABLE_MATCH = False

# 阅读有礼：有新活动时保持 True / None；无活动可改 False
MANUAL_ENABLE_READ = None

# 签到 / 抽奖 / 红包
MANUAL_ENABLE_SIGN = None
MANUAL_ENABLE_LOTTERY = None
MANUAL_ENABLE_CLAIM = None

# 阅读活动 ID 手动覆盖：
#   None/"" = 不强制；优先环境变量，其次 buoy/list 动态发现，最后默认常量
#   填新活动 tid 时优先使用该值
MANUAL_READ_ACTIVITY_ID = None

# 是否启用 buoy/list 动态发现阅读活动：
#   True/False 强制；None 跟随 DaChao_READ_DISCOVER（默认开启）
MANUAL_READ_DISCOVER = None

# 对对碰活动覆盖（None 表示走环境变量/默认）
# 可填：test / fans / all / 完整 URL / 逗号多活动
MANUAL_MATCH_URL = None

# 大潮视频（aged 短剧观看上报 + 分档领取抽奖）
# True/False 强制；None 跟随 DaChao_VIDEO（默认开启）
MANUAL_ENABLE_VIDEO = None

# 视频目标秒数覆盖（None 跟随环境变量，默认 3600）
MANUAL_VIDEO_TARGET_SECONDS = None

# 视频剧集 ID 覆盖（None 跟随环境变量/默认 1279）
MANUAL_VIDEO_DRAMA_ID = None

# 多账号并发线程数覆盖：
#   None = 跟随 DaChao_THREADS；环境变量也未设时自动=账号数（上限16）
#   整数 = 强制线程数（例如 1 强制串行）
MANUAL_THREADS = None

AIHOGE_ACT_SIGN_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0G25Cq2HxQQ+gX9H2dzb
6sbRtHzD8JbHRmOrAFzaWI2kdzbPuga4ZlqxOAyoAm8ucIAeKD4joUn+dN1wYC03
qCgloNU21KUJUls/Htp2RwxpmoncSIAOZvSQQ6Kl3vLPYlG6GetwYYN83sG85K+3
w4D89hBGHuYqKQyQsUvntxi5UVoNfo674QsCvqxHxZAuEXKoEagzUoSu8gWrDTuh
RK4aQcDpnCslwKycaO63UBvfTlBG0Jc7sqzXxapTArbqaA58XCM8dRIZdp7DR/V7
qucn/PwIOGJrOu09/cjndwIpeki8HXa9rvgWwiwZCy289vgRoxzIcLrQJ2oC1MK2
RwIDAQAB
-----END PUBLIC KEY-----"""

PASSPORT_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQD6XO7e9YeAOs+cFqwa7ETJ+WXizPqQeXv68i5vqw9pFREsrqiBTRcg7wB0RIp3rJkDpaeVJLsZqYm5TW7FWx/iOiXFc+zCPvaKZric2dXCw27EvlH5rq+zwIPDAJHGAfnn1nmQH7wR3PCatEIb8pz5GFlTHMlluw4ZYmnOwg+thwIDAQAB
-----END PUBLIC KEY-----"""


def env_truthy(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value)
    return default


def env_int(*names: str, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = env_first(*names)
    try:
        value = int(str(raw).strip()) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def env_int_list(*names: str, default: list[int] | None = None) -> list[int]:
    raw = env_first(*names)
    if not raw:
        return list(default or [])
    values: list[int] = []
    for part in re.split(r"[,，\\s|/]+", raw):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            continue
    return values or list(default or [])


def env_falsey_value(value: str | None) -> bool:
    return str(value or "").strip().lower() in FALSE_VALUES


def resolve_manual_enabled(manual_value: Any, *env_names: str, default: str = "1") -> bool:
    """手动开关优先：True/False 强制；None 则回退环境变量。"""
    if manual_value is True:
        return True
    if manual_value is False:
        return False
    return not env_falsey_value(env_first(*env_names, default=default))


def resolve_manual_text(manual_value: Any, *env_names: str, default: str = "") -> str:
    """手动文本优先；空/None 时回退环境变量。"""
    if manual_value is not None and str(manual_value).strip():
        return str(manual_value).strip()
    return env_first(*env_names, default=default).strip()


def is_debug_enabled() -> bool:
    """调试模式：默认关闭。MANUAL_DEBUG 优先，其次 DaChao_DEBUG。"""
    if MANUAL_DEBUG is True:
        return True
    if MANUAL_DEBUG is False:
        return False
    return env_truthy("DaChao_DEBUG") or env_truthy("DACHAO_DEBUG")


_print_lock = threading.Lock()


def locked_print(*args: Any, **kwargs: Any) -> None:
    with _print_lock:
        print(*args, **kwargs)


def debug_print(*args: Any) -> None:
    if is_debug_enabled():
        locked_print("[DEBUG]", *args)


def progress_print(*args: Any) -> None:
    """过程日志：仅 DEBUG 时输出（OCR/等待/逐篇等）。"""
    if is_debug_enabled():
        locked_print(*args)


def is_cash_redpacket_text(text: Any) -> bool:
    """判断奖品文案是否像现金红包（用于推送附提现链接）。"""
    s = str(text or "").strip()
    if not s:
        return False
    if "积分" in s and "现金" not in s and "元" not in s:
        return False
    if "现金" in s:
        return True
    if re.search(r"\d+(?:\.\d+)?\s*元", s):
        return True
    return "红包" in s and "积分" not in s


def extract_tid_from_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        raw = parse.unquote(raw)
    except Exception:
        pass
    if "%3" in raw.upper() or "%2" in raw.upper():
        try:
            raw = parse.unquote(raw)
        except Exception:
            pass
    query = ""
    if "?" in raw:
        query = raw.split("?", 1)[1]
    elif "tid=" in raw:
        query = raw[raw.find("tid=") :]
    params = parse.parse_qs(query, keep_blank_values=True)
    for key in ("tid", "activity_id", "activityId", "id"):
        values = params.get(key) or []
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    m = re.search(r"(?:tid|activity_id|activityId)=([A-Za-z0-9]+)", raw)
    return m.group(1) if m else ""


def extract_mark_from_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        raw = parse.unquote(raw)
    except Exception:
        pass
    query = raw.split("?", 1)[1] if "?" in raw else raw
    params = parse.parse_qs(query, keep_blank_values=True)
    values = params.get("mark") or []
    if values:
        return str(values[0] or "").strip()
    m = re.search(r"mark=([^&]+)", raw)
    return parse.unquote(m.group(1)).strip() if m else ""


def score_read_activity_candidate(url: str, title: str = "", source: str = "") -> int:
    text_blob = f"{url} {title} {source}".lower()
    title_blob = f"{url}{title}{source}"
    score = 0
    mark = extract_mark_from_url(url).lower()
    if "news-read" in mark or "news-read" in text_blob:
        score += 100
    if "阅读" in title_blob or "有礼" in title_blob:
        score += 40
    if "designh5" in text_blob:
        score += 10
    if "sign@" in mark or "raffle@" in mark:
        score -= 50
    if extract_tid_from_url(url):
        score += 5
    return score


def strip_env_assignment(raw: str, *names: str) -> str:
    raw = str(raw or "").strip()
    if raw.startswith("export "):
        raw = raw[len("export ") :].strip()
    for name in names:
        prefix = f"{name}="
        if raw.startswith(prefix):
            raw = raw[len(prefix) :].strip()
            break
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        raw = raw[1:-1]
    return raw.strip()


def normalize_base_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def strip_url_path_suffix(url: str, suffix: str) -> str:
    parts = parse.urlsplit(url)
    path = parts.path.rstrip("/")
    if not path.lower().endswith(suffix.lower()):
        return url
    new_path = path[: -len(suffix)].rstrip("/")
    return parse.urlunsplit((parts.scheme, parts.netloc, new_path, parts.query, parts.fragment)).rstrip("/")


def normalize_slide_ocr_base_url(value: str) -> str:
    url = normalize_base_url(value)
    if not url:
        return ""
    lower_path = parse.urlsplit(url).path.rstrip("/").lower()
    if lower_path.endswith("/select"):
        raise RuntimeError(
            "当前 OCR 配置是 /select 点选接口，不支持大潮阅读滑块；"
            "请把 DaChao_OCR_SERVER 改为滑块 OCR 服务基址"
        )
    for suffix in (
        "/crop",
        "/slidecomparison",
        "/api.slider_move",
        "/api.slider_comparison",
        "/docs",
        "/openapi.json",
    ):
        url = strip_url_path_suffix(url, suffix)
    return url


def resolve_daily_match_alias(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    # exact alias
    if raw in DAILY_MATCH_ALIASES:
        return DAILY_MATCH_ALIASES[raw]
    lower = raw.lower()
    for key, path in DAILY_MATCH_ALIASES.items():
        if key.lower() == lower:
            return path
    # bare activity folder name
    bare = raw.strip("/").split("/")[-1]
    bare_lower = bare.lower()
    for key, path in DAILY_MATCH_ALIASES.items():
        if key.lower() == bare_lower:
            return path
    if bare_lower == "dailymatchtest":
        return DAILY_MATCH_DEFAULT_PATH
    if bare_lower == "dailymatchfans":
        return DAILY_MATCH_FANS_PATH
    if bare_lower == "dailymatch":
        return DAILY_MATCH_LEGACY_PATH
    return raw


def normalize_daily_match_base(value: str = "") -> str:
    raw = normalize_base_url(value)
    if not raw:
        raw = DAILY_MATCH_DEFAULT_PATH
    else:
        aliased = resolve_daily_match_alias(raw)
        if aliased != raw or raw in DAILY_MATCH_ALIASES or raw.lower() in {
            k.lower() for k in DAILY_MATCH_ALIASES
        }:
            # only replace when alias hit or bare name
            if resolve_daily_match_alias(raw) != raw or "/" not in raw.strip("/"):
                maybe = resolve_daily_match_alias(raw)
                if maybe.startswith("/"):
                    raw = maybe

    if "app.hndachao.cn/webPrivate/jumpApp" in raw:
        query = parse.parse_qs(parse.urlsplit(raw).query)
        back_url = (query.get("backUrl") or [""])[0]
        if back_url:
            raw = parse.unquote(back_url)

    if raw.startswith("http://") or raw.startswith("https://"):
        parts = parse.urlsplit(raw)
        path = parts.path
    else:
        # alias may already be absolute path
        aliased = resolve_daily_match_alias(raw)
        path = aliased if aliased.startswith("/") and "://" not in aliased else raw

    path = "/" + str(path).lstrip("/")
    for suffix in (
        "/bookflip.php",
        "/bookflip2.php",
        "/bookflip3.php",
        "/controller.php",
        "/level_selection.php",
    ):
        if path.lower().endswith(suffix.lower()):
            path = path[: -len(suffix)]
            break
    return DAILY_MATCH_BASE + path.rstrip("/")


def daily_match_activity_name(match_base: str) -> str:
    base = normalize_daily_match_base(match_base)
    name = base.rstrip("/").rsplit("/", 1)[-1]
    return name or "dailyMatch"


def is_daily_match_test(match_base: str) -> bool:
    return normalize_daily_match_base(match_base).endswith("/dailyMatchTest")


def is_daily_match_fans(match_base: str) -> bool:
    return normalize_daily_match_base(match_base).endswith("/dailyMatchFans")


def default_scores_for_match_base(match_base: str) -> list[int]:
    """Test 三关递进；Fans/其它默认单关 60（JS 有缘对对碰直接 score=60）。"""
    if is_daily_match_test(match_base):
        return [20, 40, 60]
    return [60]


def parse_daily_match_bases(value: str = "") -> list[str]:
    """解析对对碰活动列表。支持 test/fans/all，或 URL/目录逗号分隔。"""
    raw = (value or "").strip()
    if not raw:
        return [normalize_daily_match_base(DAILY_MATCH_DEFAULT_PATH)]
    lower = raw.lower()
    if lower in {"all", "both", "*", "全部"}:
        return [
            normalize_daily_match_base(DAILY_MATCH_DEFAULT_PATH),
            normalize_daily_match_base(DAILY_MATCH_FANS_PATH),
        ]
    parts = [item.strip() for item in re.split(r"[,;|\n]+", raw) if item.strip()]
    bases: list[str] = []
    seen: set[str] = set()
    for item in parts:
        base = normalize_daily_match_base(item)
        if base not in seen:
            seen.add(base)
            bases.append(base)
    return bases or [normalize_daily_match_base(DAILY_MATCH_DEFAULT_PATH)]


def daily_match_url(match_base: str, filename: str) -> str:
    return normalize_daily_match_base(match_base) + "/" + filename.lstrip("/")


def is_stupidocr_server(base_url: str) -> bool:
    parts = parse.urlsplit(base_url)
    return parts.port == 6688 or parts.path.rstrip("/").lower().endswith("/stupidocr")


def read_accounts_env() -> str:
    raw = env_first("DaChao", "DACHAO", "dachao")
    return strip_env_assignment(raw, "DaChao", "DACHAO", "dachao")


def qinglong_notify_enabled() -> bool:
    notify_flag = env_first("DaChao_NOTIFY", "DACHAO_NOTIFY", default="1")
    if env_falsey_value(notify_flag):
        return False
    return not (
        env_truthy("DaChao_NO_NOTIFY")
        or env_truthy("DACHAO_NO_NOTIFY")
        or env_truthy("QL_NO_NOTIFY")
    )


def call_notify_send(module: Any, title: str, content: str) -> bool:
    send = getattr(module, "send", None) or getattr(module, "sendNotify", None)
    if not callable(send):
        return False
    send(title, content)
    return True


def qinglong_notify(title: str, content: str) -> None:
    if not qinglong_notify_enabled() or not str(content or "").strip():
        return

    safe_content = str(content).strip()
    if len(safe_content) > 3500:
        safe_content = safe_content[:3500] + "\n...(内容过长已截断)"

    script_dir = Path(__file__).resolve().parent
    module_dirs = [
        "/ql/data/scripts",
        "/ql/scripts",
        "/ql/data/deps",
        str(script_dir),
    ]
    for directory in module_dirs:
        if os.path.isdir(directory) and directory not in sys.path:
            sys.path.insert(0, directory)

    try:
        import notify  # type: ignore

        if call_notify_send(notify, title, safe_content):
            print("[推送] notify.py 推送完成")
            return
    except Exception:
        pass

    candidates = [
        env_first("QL_NOTIFY_PY"),
        "/ql/data/scripts/notify.py",
        "/ql/scripts/notify.py",
        str(script_dir / "notify.py"),
    ]
    last_error: Exception | None = None
    for candidate in [item for item in candidates if item]:
        notify_path = Path(candidate)
        if not notify_path.exists():
            continue
        try:
            spec = importlib.util.spec_from_file_location("ql_notify", notify_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules["ql_notify"] = module
            spec.loader.exec_module(module)
            if call_notify_send(module, title, safe_content):
                print(f"[推送] 已调用 {notify_path}")
                return
        except Exception as exc:
            last_error = exc

    if last_error:
        print(f"[推送] notify.py 调用失败: {last_error}")
    else:
        print("[推送] 未找到青龙 notify.py，跳过")


def mask(value: str, left: int = 3, right: int = 4) -> str:
    value = str(value or "")
    if len(value) <= left + right:
        return value[:1] + "***" if value else ""
    return value[:left] + "****" + value[-right:]


def short_text(value: Any, limit: int = 28) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def format_match_status_value(status: Any) -> str:
    mapping = {
        1: "成功",
        "1": "成功",
        -1: "失败",
        "-1": "失败",
        -2: "状态不符",
        "-2": "状态不符",
        "skipped_existing": "已完成",
        "no_chance": "无次数",
        "lottery_id_error": "抽奖ID失败",
    }
    return str(mapping.get(status, status))


def format_match_score_status(score_results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in score_results or []:
        score = item.get("_score") if isinstance(item, dict) else None
        if score is None:
            continue
        parts.append(f"{score}:{format_match_status_value(item.get('status'))}")
    return ", ".join(parts)


def format_match_page_state(state: dict[str, Any]) -> str:
    if not state:
        return ""
    return (
        f"{state.get('page', '')}:"
        f"次数={state.get('chouResets', '?')} "
        f"登录={state.get('loged', '?')} "
        f"成绩={state.get('scores', '?')} "
        f"openid={mask(str(state.get('openid') or ''), 6, 6)}"
    )


def split_accounts(raw: str) -> list[str]:
    items: list[str] = []
    for part in raw.replace("\r", "\n").replace("@", "\n").split("\n"):
        part = part.strip()
        if part:
            items.append(part)
    return items


def parse_account(raw: str) -> tuple[str, str, str]:
    """返回 (mobile, password, wechat_member)。

    兼容:
      手机&密码
      手机&密码&微信member
      手机#密码#微信member   # 大潮提现.js dcck
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("账号为空")
    if "&" in text:
        parts = [p.strip() for p in text.split("&")]
        rest_sep = "&"
    elif "#" in text:
        parts = [p.strip() for p in text.split("#")]
        rest_sep = "#"
    else:
        raise ValueError("账号格式应为 手机号&密码[ &微信member ]，多个账号用 @ 或换行分隔")
    if len(parts) < 2:
        raise ValueError("账号格式应为 手机号&密码[ &微信member ]")
    mobile = parts[0]
    password = parts[1]
    wechat_member = rest_sep.join(parts[2:]).strip() if len(parts) >= 3 else ""
    if not mobile or not password:
        raise ValueError("手机号或密码为空")
    return mobile, password, wechat_member



def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def aihoge_member_signature(timestamp: str | int | None = None) -> tuple[str, str]:
    """Return (timestamp_seconds, signature) for /api/memberhy/tm/signature."""
    ts = str(timestamp if timestamp is not None else int(time.time()))
    raw = f"{AIHOGE_SIGNATURE_PREFIX}{ts}&&{AIHOGE_SIGNATURE_SALT}"
    return ts, sha256_hex(raw)


def js_encode_uri(value: Any) -> str:
    return parse.quote(str(value or ""), safe=";/?:@&=+$,#-_.!~*'()")


def read_asn1_length(data: bytes, offset: int) -> tuple[int, int]:
    first = data[offset]
    offset += 1
    if first < 0x80:
        return first, offset
    count = first & 0x7F
    length = int.from_bytes(data[offset : offset + count], "big")
    return length, offset + count


def read_asn1_tlv(data: bytes, offset: int) -> tuple[int, bytes, int]:
    tag = data[offset]
    length, start = read_asn1_length(data, offset + 1)
    end = start + length
    return tag, data[start:end], end


def parse_asn1_integer(data: bytes, offset: int) -> tuple[int, int]:
    tag, value, end = read_asn1_tlv(data, offset)
    if tag != 0x02:
        raise ValueError("RSA public key parse failed: expected INTEGER")
    return int.from_bytes(value.lstrip(b"\x00"), "big"), end


def parse_rsa_public_key(pem: str) -> tuple[int, int]:
    body = "".join(line.strip() for line in pem.splitlines() if "-----" not in line)
    der = base64.b64decode(body)
    tag, spki, _ = read_asn1_tlv(der, 0)
    if tag != 0x30:
        raise ValueError("RSA public key parse failed: expected SEQUENCE")

    offset = 0
    first_tag, first_value, offset_after_first = read_asn1_tlv(spki, offset)
    if first_tag == 0x30 and offset_after_first < len(spki):
        bit_tag, bit_value, _ = read_asn1_tlv(spki, offset_after_first)
        if bit_tag != 0x03 or not bit_value:
            raise ValueError("RSA public key parse failed: expected BIT STRING")
        rsa_der = bit_value[1:]
    else:
        rsa_der = spki

    tag, rsa_seq, _ = read_asn1_tlv(rsa_der, 0)
    if tag != 0x30:
        raise ValueError("RSA public key parse failed: expected RSA SEQUENCE")
    modulus, offset = parse_asn1_integer(rsa_seq, 0)
    exponent, _ = parse_asn1_integer(rsa_seq, offset)
    return modulus, exponent


def rsa_pkcs1_v15_encrypt_base64(public_key_pem: str, plaintext: str) -> str:
    modulus, exponent = parse_rsa_public_key(public_key_pem)
    key_len = (modulus.bit_length() + 7) // 8
    message = plaintext.encode("utf-8")
    if len(message) > key_len - 11:
        raise ValueError("明文过长，无法用 RSA/PKCS#1 v1.5 加密")

    ps_len = key_len - len(message) - 3
    padding = bytearray()
    while len(padding) < ps_len:
        b = secrets.token_bytes(1)
        if b != b"\x00":
            padding.extend(b)
    block = b"\x00\x02" + bytes(padding) + b"\x00" + message
    encrypted = pow(int.from_bytes(block, "big"), exponent, modulus).to_bytes(key_len, "big")
    return base64.b64encode(encrypted).decode("ascii")


@dataclass
class DeviceProfile:
    uuid: str
    model: str = "Xiaomi 23127PN0CC"
    android_version: str = "11"

    @property
    def tmuyun_ua(self) -> str:
        return f"{APP_VERSION};{self.uuid};{self.model};Android;{self.android_version};{SDK_VERSION}"

    @property
    def passport_ua(self) -> str:
        return f"ANDROID;{self.android_version};{CLIENT_ID};{APP_VERSION};1.0;null;{self.model.split()[-1]}"

    @property
    def webview_ua(self) -> str:
        return (
            "Mozilla/5.0 (Linux; Android 11; 21091116AC Build/RP1A.200720.011; wv) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/94.0.4606.85 "
            f"Mobile Safari/537.36;{APP_SIGN};{APP_SIGN};{APP_VERSION};native_app;{SDK_VERSION}"
        )


class DachaoClient:
    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout
        self.device = DeviceProfile(uuid=str(uuid.uuid4()))
        self.daily_match_cookies: dict[str, str] = {}

    def tmuyun_headers(
        self,
        path: str,
        session_id: str = "",
        account_id: str = "",
        content_type: str | None = None,
    ) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        request_id = str(uuid.uuid4())
        signature = sha256_hex(
            f"{path}&&{session_id}&&{request_id}&&{timestamp}&&{TMUYUN_SALT}&&{TENANT_ID}"
        )
        headers = {
            "Connection": "Keep-Alive",
            "X-TIMESTAMP": timestamp,
            "X-SESSION-ID": session_id,
            "X-REQUEST-ID": request_id,
            "X-SIGNATURE": signature,
            "X-TENANT-ID": TENANT_ID,
            "X-ACCOUNT-ID": account_id,
            "Cache-Control": "no-cache",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "user-agent": self.device.tmuyun_ua,
        }
        if content_type:
            headers["content-type"] = content_type
        return headers

    def request_text(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | str | None = None,
    ) -> str:
        data: bytes | None
        if isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body
        req = request.Request(url, data=data, method=method.upper())
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            raw = exc.read()
            text = raw.decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} {url}: {text[:300]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"请求失败 {url}: {exc.reason}") from exc

        return text

    def request_text_with_headers(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | str | None = None,
    ) -> tuple[str, Any]:
        data: bytes | None
        if isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body
        req = request.Request(url, data=data, method=method.upper())
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8", errors="replace")
                return text, resp.headers
        except error.HTTPError as exc:
            raw = exc.read()
            text = raw.decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} {url}: {text[:300]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"请求失败 {url}: {exc.reason}") from exc

    def request_binary(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | str | None = None,
    ) -> bytes:
        data: bytes | None
        if isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body
        req = request.Request(url, data=data, method=method.upper())
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except error.HTTPError as exc:
            raw = exc.read()
            text = raw.decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} {url}: {text[:300]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"请求失败 {url}: {exc.reason}") from exc

    def request_json(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | str | None = None,
    ) -> dict[str, Any]:
        text = self.request_text(url, method=method, headers=headers, body=body)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"响应不是 JSON {url}: {text[:300]}") from exc

    def account_init(self) -> dict[str, Any]:
        path = "/api/account/init"
        res = self.request_json(
            TMUYUN_BASE + path,
            method="POST",
            headers=self.tmuyun_headers(path),
            body=b"",
        )
        self.ensure_code0(res, path)
        return res["data"]

    def credential_auth(self, mobile: str, password: str) -> str:
        encrypted_password = rsa_pkcs1_v15_encrypt_base64(PASSPORT_PUBLIC_KEY, password)
        body = parse.urlencode(
            {
                "client_id": CLIENT_ID,
                "password": encrypted_password,
                "phone_number": mobile,
            }
        )
        headers = {
            "Connection": "Keep-Alive",
            "X-REQUEST-ID": str(uuid.uuid4()),
            "Cache-Control": "no-cache",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "user-agent": self.device.passport_ua,
        }
        res = self.request_json(
            PASSPORT_BASE + "/web/oauth/credential_auth",
            method="POST",
            headers=headers,
            body=body,
        )
        self.ensure_code0(res, "credential_auth")
        try:
            return res["data"]["authorization_code"]["code"]
        except KeyError as exc:
            raise RuntimeError(f"credential_auth 缺少 authorization_code: {res}") from exc

    def zbtxz_login(self, anonymous_session_id: str, code: str) -> dict[str, Any]:
        path = "/api/zbtxz/login"
        body = parse.urlencode(
            {
                "check_token": "",
                "code": code,
                "token": "",
                "type": "-1",
                "union_id": "",
            }
        )
        res = self.request_json(
            TMUYUN_BASE + path,
            method="POST",
            headers=self.tmuyun_headers(
                path,
                session_id=anonymous_session_id,
                content_type="application/x-www-form-urlencoded",
            ),
            body=body,
        )
        self.ensure_code0(res, path)
        return res["data"]

    def account_detail(self, session_id: str, account_id: str) -> dict[str, Any] | None:
        path = "/api/user_mumber/account_detail"
        try:
            res = self.request_json(
                TMUYUN_BASE + path,
                method="GET",
                headers=self.tmuyun_headers(path, session_id=session_id, account_id=account_id),
            )
            self.ensure_code0(res, path)
            return res.get("data")
        except Exception as exc:
            print(f"[详情] 获取 account_detail 失败，保留登录返回数据: {exc}")
            return None

    def buoy_list(self, session_id: str, account_id: str) -> dict[str, Any]:
        path = "/api/buoy/list"
        res = self.request_json(
            TMUYUN_BASE + path,
            method="GET",
            headers=self.tmuyun_headers(path, session_id=session_id, account_id=account_id),
        )
        self.ensure_code0(res, path)
        data = res.get("data")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def iter_buoy_nodes(node: Any, path: str = "data"):
        if isinstance(node, dict):
            yield path, node
            for key, value in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                yield from DachaoClient.iter_buoy_nodes(value, child_path)
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                child_path = f"{path}[{idx}]"
                yield from DachaoClient.iter_buoy_nodes(item, child_path)

    @staticmethod
    def extract_read_activity_candidates(buoy_data: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for path, node in DachaoClient.iter_buoy_nodes(buoy_data, "data"):
            if not isinstance(node, dict):
                continue
            title = str(
                node.get("title")
                or node.get("name")
                or node.get("text")
                or node.get("label")
                or ""
            )
            url_candidates: list[str] = []
            for key in ("url", "link", "jump_url", "jumpUrl", "path", "href"):
                val = node.get(key)
                if isinstance(val, str) and val.strip():
                    url_candidates.append(val.strip())
            turn_to = node.get("turn_to") or node.get("turnTo") or {}
            if isinstance(turn_to, dict):
                for key in ("url", "link", "path", "href"):
                    val = turn_to.get(key)
                    if isinstance(val, str) and val.strip():
                        url_candidates.append(val.strip())
            for key in ("value", "content", "desc"):
                val = node.get(key)
                if isinstance(val, str) and ("tid=" in val or "news-read" in val):
                    url_candidates.append(val.strip())

            for url in url_candidates:
                tid = extract_tid_from_url(url)
                if not tid or tid in seen:
                    continue
                mark = extract_mark_from_url(url)
                score = score_read_activity_candidate(url, title=title, source=path)
                if score < 5 and "tid=" not in url and "news-read" not in url:
                    continue
                seen.add(tid)
                candidates.append(
                    {
                        "tid": tid,
                        "url": url,
                        "title": title,
                        "mark": mark,
                        "source": path,
                        "score": score,
                    }
                )
        candidates.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("tid") or "")))
        return candidates

    def discover_read_activity_id(
        self,
        login_result: dict[str, Any],
        progress: Any = None,
    ) -> dict[str, Any]:
        session_id = str(login_result.get("sessionId") or "")
        account_id = str(login_result.get("accountId") or "")
        if not session_id or not account_id:
            raise RuntimeError("缺少 sessionId/accountId，无法 buoy/list 动态发现")
        buoy_data = self.buoy_list(session_id, account_id)
        candidates = self.extract_read_activity_candidates(buoy_data)
        if callable(progress):
            progress(f"[阅读] buoy/list 候选 {len(candidates)} 个")
            if is_debug_enabled():
                for item in candidates[:5]:
                    progress(
                        f"[阅读] 候选 tid={item.get('tid')} score={item.get('score')} "
                        f"mark={item.get('mark') or '-'} title={short_text(item.get('title'), 16)}"
                    )
                if candidates:
                    best = candidates[0]
                    progress(f"[DEBUG] best_url={short_text(best.get('url'), 80)}")
        if not candidates:
            return {
                "activity_id": "",
                "source": "buoy/list",
                "candidates": [],
                "message": "buoy/list 未解析到阅读活动 tid",
            }
        best = candidates[0]
        return {
            "activity_id": str(best.get("tid") or ""),
            "source": f"buoy/list:{best.get('source') or ''}",
            "url": best.get("url") or "",
            "title": best.get("title") or "",
            "mark": best.get("mark") or "",
            "score": best.get("score") or 0,
            "candidates": candidates,
            "message": "ok",
        }

    def aihoge_headers(
        self,
        session_id: str,
        account_id: str,
        member: str = "",
        limit_id: str = "",
        referer: str | None = None,
    ) -> dict[str, str]:
        if referer is None:
            referer = "https://m.aihoge.com/h5?mark=news-read@designh5&tid=&path=index&isNeedLogin=true"
        return {
            "Connection": "keep-alive",
            "X-DEVICE-SIGN": APP_SIGN,
            "X-CLIENT-VERSION": "1314",
            "Content-Type": "application/json;charset=UTF-8",
            "accept": "application/json, text/plain, */*",
            "user-agent": self.device.webview_ua,
            "HTTP-X-H5-VERSION": "1",
            "member": member,
            "Limit": limit_id,
            "sessionId": session_id,
            "X-DEVICE-ID": "000",
            "accountId": account_id,
            "x-requested-with": "com.hoge.android.app.dachao",
            "Referer": referer,
            "accept-encoding": "gzip, deflate",
            "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def build_aihoge_signature_body(self, login_result: dict[str, Any], timestamp: str | int | None = None) -> dict[str, Any]:
        account = login_result["raw"]["account"]
        session_id = login_result["sessionId"]
        account_id = login_result["accountId"]
        ts, signature = aihoge_member_signature(timestamp)
        return {
            "accountId": account_id,
            "signature": signature,
            "mobile": "1",
            "sessionId": session_id,
            "login": "1",
            "user": {
                "realName": "",
                "image_url": account.get("image_url", ""),
                "nick_name": account.get("nick_name", ""),
                "is_face_verify": 0,
                "idcard": "",
                "id": account_id,
            },
            "timestamp": ts,
            "sign": APP_SIGN,
        }

    def get_aihoge_member(self, login_result: dict[str, Any]) -> dict[str, Any]:
        body = self.build_aihoge_signature_body(login_result)
        res = self.request_json(
            AIHOGE_BASE + "/api/memberhy/tm/signature",
            method="POST",
            headers=self.aihoge_headers(login_result["sessionId"], login_result["accountId"]),
            body=json.dumps(body, ensure_ascii=False, separators=(",", ":")),
        )
        if "token" not in res:
            raise RuntimeError(f"memberhy/tm/signature 失败: {json.dumps(res, ensure_ascii=False)[:500]}")
        return res

    def build_aihoge_member_header(self, member: dict[str, Any]) -> str:
        body = {
            "id": member.get("id", ""),
            "black": member.get("black", 0),
            "btoken": member.get("btoken", ""),
            "expire": member.get("expire", ""),
            "token": member.get("token", ""),
            "source": APP_SIGN,
            "mobile": member.get("mobile", ""),
            "mark": member.get("mark", ""),
            "mtoken": member.get("mtoken", ""),
            "stoken": member.get("stoken", ""),
            "nick_name": js_encode_uri(member.get("nick_name", "")),
            "avatar": member.get("avatar", ""),
        }
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    def build_act_sign_params(
        self,
        activity_id: str,
        timestamp: str | int | None = None,
    ) -> tuple[str, str, str]:
        ts = str(timestamp if timestamp is not None else int(time.time() + 0.5))
        plaintext = json.dumps(
            {
                "activity_id": activity_id,
                "timestamp": ts,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        encrypted = rsa_pkcs1_v15_encrypt_base64(AIHOGE_ACT_SIGN_PUBLIC_KEY, plaintext)
        return ts, plaintext, encrypted

    def act_sign(
        self,
        login_result: dict[str, Any],
        member: dict[str, Any],
        activity_id: str = AIHOGE_DEFAULT_SIGN_ACTIVITY_ID,
        limit_id: str = AIHOGE_DEFAULT_LIMIT_ID,
    ) -> dict[str, Any]:
        _, _, params = self.build_act_sign_params(activity_id)
        referer = f"{AIHOGE_BASE}/h5?mark=news-read@designh5&tid={limit_id}&path=index&isNeedLogin=true"
        res = self.request_json(
            AIHOGE_BASE + "/api/signhy/client/actSign/actSign",
            method="POST",
            headers=self.aihoge_headers(
                login_result["sessionId"],
                login_result["accountId"],
                member=self.build_aihoge_member_header(member),
                limit_id=limit_id,
                referer=referer,
            ),
            body=json.dumps({"params": params}, ensure_ascii=False, separators=(",", ":")),
        )
        return res

    @staticmethod
    def act_sign_token_ok(res: dict[str, Any]) -> bool:
        if res.get("code") in {0, "0"}:
            return True
        if "error_code" not in res and "error_message" not in res:
            return True
        return res.get("error_code") in {0, "0", "OK", "SUCCESS", "LIMIT_PASS"}

    @staticmethod
    def aihoge_api_url(path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return AIHOGE_BASE + "/api" + path

    def daily_match_cookie_header(self, account_id: str) -> str:
        cookie_value = json.dumps(
            {"openid": account_id, "platform": 3},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        cookies = {"dachaogo": cookie_value}
        cookies.update(self.daily_match_cookies)
        return "; ".join(f"{key}={value}" for key, value in cookies.items())

    def remember_daily_match_cookies(self, headers: Any) -> None:
        get_all = getattr(headers, "get_all", None)
        set_cookie_headers = get_all("Set-Cookie") if callable(get_all) else None
        if not set_cookie_headers:
            single = headers.get("Set-Cookie") if hasattr(headers, "get") else None
            set_cookie_headers = [single] if single else []
        for header in set_cookie_headers:
            try:
                parsed = SimpleCookie()
                parsed.load(header)
                for key, morsel in parsed.items():
                    self.daily_match_cookies[key] = morsel.value
            except Exception:
                continue

    def daily_match_headers(self, account_id: str, referer: str | None = None, match_base: str = "") -> dict[str, str]:
        if referer is None:
            referer = daily_match_url(match_base, "bookflip.php")
        return {
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "accept": "application/json, text/javascript, */*; q=0.01",
            "x-requested-with": "XMLHttpRequest",
            "user-agent": self.device.webview_ua,
            "origin": DAILY_MATCH_BASE,
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "referer": referer,
            "accept-encoding": "gzip, deflate",
            "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "cookie": self.daily_match_cookie_header(account_id),
        }

    def daily_match_post(
        self,
        login_result: dict[str, Any],
        form: dict[str, Any],
        match_base: str = "",
        referer: str | None = None,
    ) -> dict[str, Any]:
        url = daily_match_url(match_base, "controller.php")
        text, headers = self.request_text_with_headers(
            daily_match_url(match_base, "controller.php"),
            method="POST",
            headers=self.daily_match_headers(login_result["accountId"], referer=referer, match_base=match_base),
            body=parse.urlencode(form),
        )
        self.remember_daily_match_cookies(headers)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"响应不是 JSON {url}: {text[:300]}") from exc

    def daily_match_get_text(
        self,
        login_result: dict[str, Any],
        filename: str,
        match_base: str = "",
        referer: str | None = None,
    ) -> str:
        text, headers = self.request_text_with_headers(
            daily_match_url(match_base, filename),
            method="GET",
            headers=self.daily_match_headers(login_result["accountId"], referer=referer, match_base=match_base),
        )
        self.remember_daily_match_cookies(headers)
        return text

    @staticmethod
    def extract_match_js_var(html: str, name: str) -> str:
        match = re.search(rf"var\s+{re.escape(name)}\s*=\s*(.*?);", html)
        if not match:
            return ""
        raw = match.group(1).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
            raw = raw[1:-1]
        return raw.strip()

    @staticmethod
    def int_or_none(value: Any) -> int | None:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    def daily_match_page_state(
        self,
        login_result: dict[str, Any],
        match_base: str = "",
        filename: str = "bookflip.php",
        referer: str | None = None,
    ) -> dict[str, Any]:
        html = self.daily_match_get_text(login_result, filename, match_base=match_base, referer=referer)
        state = {
            "page": filename,
            "chouResets": self.int_or_none(self.extract_match_js_var(html, "chouResets")),
            "shareNums": self.int_or_none(self.extract_match_js_var(html, "shareNums")),
            "restShareNums": self.int_or_none(self.extract_match_js_var(html, "restShareNums")),
            "openid": self.extract_match_js_var(html, "openid"),
            "loged": self.int_or_none(self.extract_match_js_var(html, "loged")),
            "scores": self.int_or_none(self.extract_match_js_var(html, "scores")),
        }
        lottery_match = re.search(r"mark=raffle@designh5(?:&amp;|&|\\u0026)tid=([a-zA-Z0-9]+)", html)
        if lottery_match:
            state["lottery_id"] = lottery_match.group(1)
        return state

    def daily_match_find_lottery_id(self, login_result: dict[str, Any], match_base: str = "") -> str:
        html = self.daily_match_get_text(
            login_result,
            "bookflip3.php?source=bookflip2",
            match_base=match_base,
            referer=daily_match_url(match_base, "bookflip.php"),
        )
        match = re.search(r"mark=raffle@designh5(?:&amp;|&|\\u0026)tid=([a-zA-Z0-9]+)", html)
        return match.group(1) if match else ""

    @staticmethod
    def daily_match_referer_for_score(match_base: str, score: int) -> str:
        if score >= 60:
            return daily_match_url(match_base, "bookflip3.php?source=bookflip2")
        if score >= 40:
            return daily_match_url(match_base, "bookflip2.php?source=bookflip")
        return daily_match_url(match_base, "bookflip.php")

    def daily_match_lottery_id_for_score(self, login_result: dict[str, Any], match_base: str, score: int) -> str:
        if score >= 60:
            filename = "bookflip3.php?source=bookflip2"
            fallback = DAILY_MATCH_LOTTERY_IDS.get(60, "")
        elif score >= 40:
            filename = "bookflip2.php?source=bookflip"
            fallback = DAILY_MATCH_LOTTERY_IDS.get(40, "")
        else:
            filename = "bookflip.php"
            fallback = DAILY_MATCH_LOTTERY_IDS.get(20, "")
        try:
            state = self.daily_match_page_state(
                login_result,
                match_base=match_base,
                filename=filename,
                referer=daily_match_url(match_base, "bookflip.php"),
            )
            return str(state.get("lottery_id") or fallback)
        except Exception:
            return fallback

    def run_daily_match(
        self,
        login_result: dict[str, Any],
        max_rounds: int = 5,
        score: int = 60,
        score_sequence: list[int] | None = None,
        match_base: str = "",
    ) -> dict[str, Any]:
        resolved_match_base = normalize_daily_match_base(match_base)
        activity_name = daily_match_activity_name(resolved_match_base)
        fans_mode = is_daily_match_fans(resolved_match_base)
        test_mode = is_daily_match_test(resolved_match_base)
        # progressive: Test 三关 20/40/60；retry: Fans 等同 JS 对同一分数最多打 max_rounds 次
        custom_scores = list(score_sequence or [])
        if custom_scores:
            scores = custom_scores[:max_rounds]
            submit_mode = "sequence"
        elif test_mode:
            scores = default_scores_for_match_base(resolved_match_base)[:max_rounds]
            submit_mode = "progressive"
        else:
            # dailyMatchFans / dailyMatch：对齐 大潮对对碰3.js，默认 score=60 并可重试
            scores = [int(score)]
            submit_mode = "retry"

        before_state: dict[str, Any] = {}
        after_state: dict[str, Any] = {}
        try:
            before_state = self.daily_match_page_state(
                login_result,
                match_base=resolved_match_base,
                filename="bookflip.php",
            )
        except Exception as exc:
            before_state = {"page": "bookflip.php", "error": str(exc)}
        start_res = self.daily_match_post(
            login_result,
            {
                "appid": login_result["sessionId"],
                "openid": login_result["accountId"],
                "type": "101",
            },
            match_base=resolved_match_base,
            referer=daily_match_url(resolved_match_base, "bookflip.php"),
        )
        try:
            after_state = self.daily_match_page_state(
                login_result,
                match_base=resolved_match_base,
                filename="bookflip.php",
            )
        except Exception as exc:
            after_state = {"page": "bookflip.php", "error": str(exc)}

        page_scores = self.int_or_none(after_state.get("scores"))
        if page_scores is None:
            page_scores = self.int_or_none(before_state.get("scores")) or 0
        page_chances = self.int_or_none(after_state.get("chouResets"))
        if page_chances is None:
            page_chances = self.int_or_none(before_state.get("chouResets"))

        score_results: list[dict[str, Any]] = []

        if submit_mode == "retry":
            # 对齐 大潮对对碰3.js：type=105&score=60 最多 max_rounds，status!=1 停止
            target_score = scores[0] if scores else 60
            if page_chances == 0 and not page_scores:
                score_results.append({"status": "no_chance", "message": "页面显示今日可参与次数为 0"})
            else:
                for round_idx in range(max_rounds):
                    res = self.daily_match_post(
                        login_result,
                        {"type": "105", "score": str(target_score)},
                        match_base=resolved_match_base,
                        referer=self.daily_match_referer_for_score(resolved_match_base, target_score),
                    )
                    res.setdefault("_score", target_score)
                    res.setdefault("_round", round_idx + 1)
                    score_results.append(res)
                    if res.get("status") != 1:
                        break
        else:
            existing_scores = [item for item in scores if page_scores and item <= page_scores]
            for existing_score in existing_scores:
                score_results.append({"_score": existing_score, "status": "skipped_existing"})

            pending_scores = [item for item in scores if not page_scores or item > page_scores]
            if page_chances == 0 and not page_scores:
                score_results.append({"status": "no_chance", "message": "页面显示今日可参与次数为 0"})
                pending_scores = []

            for current_score in pending_scores:
                res = self.daily_match_post(
                    login_result,
                    {"type": "105", "score": str(current_score)},
                    match_base=resolved_match_base,
                    referer=self.daily_match_referer_for_score(resolved_match_base, current_score),
                )
                res.setdefault("_score", current_score)
                score_results.append(res)
                if res.get("status") != 1:
                    break

        lottery_id = ""
        best_score = page_scores or 0
        for item in score_results:
            if item.get("status") == 1 and item.get("_score"):
                best_score = max(best_score, int(item["_score"]))
        # 页面已有成绩时也尝试取抽奖 ID（Fans 可能当天已完成但仍有抽奖）
        effective_score = best_score or page_scores or 0
        if test_mode and effective_score:
            lottery_id = self.daily_match_lottery_id_for_score(
                login_result, resolved_match_base, effective_score
            )
        elif fans_mode or effective_score:
            try:
                lottery_id = self.daily_match_find_lottery_id(
                    login_result, match_base=resolved_match_base
                )
            except Exception as exc:
                score_results.append({"status": "lottery_id_error", "message": str(exc)})
                lottery_id = ""
        else:
            lottery_id = ""

        ok_scores = sum(1 for item in score_results if item.get("status") == 1)
        stop_status = score_results[-1].get("status") if score_results else start_res.get("status")
        return {
            "match_base": resolved_match_base,
            "activity": activity_name,
            "submit_mode": submit_mode,
            "score_sequence": scores if submit_mode != "retry" else [scores[0] if scores else 60] * max(
                1, len([x for x in score_results if x.get("_score") is not None]) or [1]
            ),
            "page_state_before": before_state,
            "page_state_after": after_state,
            "existing_score": page_scores,
            "completed_score": best_score or page_scores or 0,
            "chances": page_chances,
            "start": start_res,
            "score_results": score_results,
            "success_scores": ok_scores,
            "stop_status": stop_status,
            "lottery_id": lottery_id,
        }

    def lottery_referer(self, lottery_id: str) -> str:
        return f"{AIHOGE_BASE}/h5?mark=raffle@designh5&tid={lottery_id}&path=index&isNeedLogin=true"

    def lottery_info(
        self,
        login_result: dict[str, Any],
        member: dict[str, Any],
        lottery_id: str,
        limit_id: str = "",
    ) -> dict[str, Any]:
        # DaChao.js activity* 用 Limit=阅读 tid；独立抽奖时回退 lottery_id
        return self.request_json(
            self.aihoge_api_url(f"/lotteryhy/designh5/client/activity/{lottery_id}"),
            method="GET",
            headers=self.aihoge_headers(
                login_result["sessionId"],
                login_result["accountId"],
                member=self.build_aihoge_member_header(member),
                limit_id=limit_id or lottery_id,
                referer=self.lottery_referer(lottery_id),
            ),
        )

    def lottery_draw(
        self,
        login_result: dict[str, Any],
        member: dict[str, Any],
        lottery_id: str,
        limit_id: str = "",
    ) -> dict[str, Any]:
        return self.request_json(
            self.aihoge_api_url(f"/lotteryhy/api/client/cj/awd/drw/{lottery_id}"),
            method="POST",
            headers=self.aihoge_headers(
                login_result["sessionId"],
                login_result["accountId"],
                member=self.build_aihoge_member_header(member),
                limit_id=limit_id or lottery_id,
                referer=self.lottery_referer(lottery_id),
            ),
            body="{}",
        )

    def run_lottery(
        self,
        login_result: dict[str, Any],
        member: dict[str, Any],
        lottery_id: str,
        max_draws: int = 5,
        limit_id: str = "",
    ) -> dict[str, Any]:
        """抽奖生命周期：详情 -> 次数 -> 抽奖。

        对齐 DaChao.js：以 remain_counts 为准发起抽奖。
        软结束文案 is_activity_end 仅在 remain<=0 时作为最终结论；
        remain>0 时仍尝试 draw，由抽奖接口真实返回裁决。
        """
        effective_limit = limit_id or lottery_id
        info_res = self.lottery_info(login_result, member, lottery_id, limit_id=effective_limit)
        response = info_res.get("response") if isinstance(info_res.get("response"), dict) else {}
        title = response.get("title") or lottery_id
        status = str(response.get("activity_vp_status") or "")
        end_message = str(response.get("is_activity_end") or info_res.get("error_message") or "")
        try:
            remain_counts = int(response.get("remain_counts") or 0)
        except (TypeError, ValueError):
            remain_counts = 0

        soft_ended = status == "activity_end" or ("结束" in end_message)
        result: dict[str, Any] = {
            "lottery_id": lottery_id,
            "limit_id": effective_limit,
            "title": title,
            "info": info_res,
            "remain_counts": remain_counts,
            "status": status,
            "is_activity_end": end_message,
            "soft_ended": soft_ended,
            "draws": [],
        }

        if info_res.get("error_code") not in {0, "0", None}:
            result["message"] = info_res.get("error_message") or "详情接口返回异常"
            return result
        # 有次数优先抽；无次数才把“已结束”当最终态（JS 只看 remain_counts）
        if remain_counts <= 0:
            if soft_ended:
                result["message"] = end_message or "活动已结束"
            else:
                result["message"] = end_message or "无可用抽奖机会"
            return result
        if soft_ended:
            debug_print(
                f"lottery soft_ended but remain={remain_counts}, still draw: "
                f"status={status} end={end_message}"
            )

        attempts = min(remain_counts, max_draws)
        for _ in range(attempts):
            draw_res = self.lottery_draw(
                login_result,
                member,
                lottery_id,
                limit_id=effective_limit,
            )
            result["draws"].append(draw_res)
            if draw_res.get("error_code") not in {0, "0", None} and not draw_res.get("award_name"):
                break

        if result["draws"]:
            last = result["draws"][-1]
            result["message"] = last.get("award_name") or last.get("error_message") or last.get("message") or "已尝试抽奖"
        else:
            result["message"] = "未尝试抽奖"
        return result

    def wechat_aihoge_headers(self, wechat_member: str, referer: str | None = None) -> dict[str, str]:
        """红包领取专用头：对齐 大潮提现.js hongbaoPost / 对对碰3 function T。"""
        if referer is None:
            referer = "https://m.aihoge.com/lottery/rotor/drawRedPacket?title=%E9%A2%86%E5%8F%96%E7%BA%A2%E5%8C%85"
        return {
            "Connection": "keep-alive",
            "X-DEVICE-SIGN": "wechat",
            "X-CLIENT-VERSION": "1314",
            "Content-Type": "application/json;charset=UTF-8",
            "accept": "application/json, text/plain, */*",
            "user-agent": self.device.webview_ua,
            "HTTP-X-H5-VERSION": "1",
            "member": wechat_member,
            "Limit": "default",
            "X-DEVICE-ID": "000",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "Referer": referer,
            "accept-encoding": "gzip, deflate",
            "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    @staticmethod
    def extract_prize_code(prize: dict[str, Any]) -> str:
        info = prize.get("prize_info")
        if isinstance(info, str):
            try:
                info = json.loads(info)
            except json.JSONDecodeError:
                return ""
        if isinstance(info, dict):
            code = info.get("code")
            return str(code) if code is not None else ""
        return ""

    @staticmethod
    def redpacket_claim_link(code: str) -> str:
        return REDPACKET_CLAIM_LINK.format(code=parse.quote(str(code or ""), safe=""))

    def list_member_prizes(
        self,
        login_result: dict[str, Any],
        member: dict[str, Any],
        prize_type: int = 3,
        page: int = 1,
        count: int = 20,
        limit_id: str = "",
        lottery_id: str = "",
    ) -> dict[str, Any]:
        """GET /lotteryhy/api/client/cj/member/prize/info 对齐 大潮提现.js。

        Limit 优先：阅读 tid / 抽奖 tid（JS activityGet 用 buoy 的 tid，不是 default）。
        """
        effective_limit = (limit_id or lottery_id or "default").strip() or "default"
        referer_tid = effective_limit if effective_limit != "default" else ""
        path = (
            f"/lotteryhy/api/client/cj/member/prize/info"
            f"?prize_type={prize_type}&page={page}&count={count}"
        )
        return self.request_json(
            self.aihoge_api_url(path),
            method="GET",
            headers=self.aihoge_headers(
                login_result["sessionId"],
                login_result["accountId"],
                member=self.build_aihoge_member_header(member),
                limit_id=effective_limit,
                referer=f"{AIHOGE_BASE}/h5?mark=news-read@designh5&tid={referer_tid}&path=index&isNeedLogin=true",
            ),
        )

    def list_lottery_prizes(
        self,
        login_result: dict[str, Any],
        member: dict[str, Any],
        lottery_id: str,
        page: int = 1,
        count: int = 100,
        limit_id: str = "",
    ) -> dict[str, Any]:
        """GET /lotteryhy/api/client/cj/my/prize/info/{lottery_id} 对齐 DaChao.js 抽奖后查奖。"""
        lottery_id = str(lottery_id or "").strip()
        if not lottery_id:
            return {}
        effective_limit = (limit_id or lottery_id).strip()
        path = f"/lotteryhy/api/client/cj/my/prize/info/{lottery_id}?page={page}&count={count}"
        return self.request_json(
            self.aihoge_api_url(path),
            method="GET",
            headers=self.aihoge_headers(
                login_result["sessionId"],
                login_result["accountId"],
                member=self.build_aihoge_member_header(member),
                limit_id=effective_limit,
                referer=self.lottery_referer(lottery_id),
            ),
        )

    @staticmethod
    def _extract_prize_items(list_res: dict[str, Any]) -> list[dict[str, Any]]:
        raw_items = list_res.get("data")
        if isinstance(raw_items, list):
            return [x for x in raw_items if isinstance(x, dict)]
        response = list_res.get("response")
        if isinstance(response, list):
            return [x for x in response if isinstance(x, dict)]
        if isinstance(response, dict) and isinstance(response.get("data"), list):
            return [x for x in response.get("data") if isinstance(x, dict)]
        return []

    def claim_redpacket(
        self,
        wechat_member: str,
        code: str,
    ) -> dict[str, Any]:
        """POST /lotteryhy/api/client/cj/send/pak 使用微信 H5 member 头。"""
        return self.request_json(
            self.aihoge_api_url("/lotteryhy/api/client/cj/send/pak"),
            method="POST",
            headers=self.wechat_aihoge_headers(wechat_member),
            body=json.dumps({"code": code}, ensure_ascii=False),
        )

    def run_claim_redpackets(
        self,
        login_result: dict[str, Any],
        member: dict[str, Any] | None,
        wechat_member: str = "",
        prize_type: int = 3,
        page: int = 1,
        count: int = 50,
        limit_id: str = "",
        lottery_id: str = "",
    ) -> dict[str, Any]:
        """列出待领红包；有微信 member 则 send/pak，否则输出领取链接。"""
        if member is None:
            return {
                "success": False,
                "message": "缺少业务 member token，无法查询奖品列表",
                "prizes": [],
                "claimed": 0,
                "links": [],
            }

        # 多源汇总：member 全局列表 + 指定抽奖活动奖品列表
        sources: list[tuple[str, dict[str, Any]]] = []
        list_res = self.list_member_prizes(
            login_result,
            member,
            prize_type=prize_type,
            page=page,
            count=count,
            limit_id=limit_id,
            lottery_id=lottery_id,
        )
        sources.append(("member_prize_info", list_res))
        if lottery_id:
            lottery_res = self.list_lottery_prizes(
                login_result,
                member,
                lottery_id,
                page=page,
                count=max(count, 100),
                limit_id=limit_id or lottery_id,
            )
            sources.append(("lottery_my_prize_info", lottery_res))
            # 再试一次 Limit=lottery_id 的 member 列表
            list_res2 = self.list_member_prizes(
                login_result,
                member,
                prize_type=prize_type,
                page=page,
                count=count,
                limit_id=lottery_id,
                lottery_id=lottery_id,
            )
            sources.append(("member_prize_info_lottery_limit", list_res2))

        raw_items: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for source_name, res in sources:
            for prize in self._extract_prize_items(res):
                code = self.extract_prize_code(prize)
                key = code or json.dumps(prize, ensure_ascii=False, sort_keys=True)[:120]
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                prize = dict(prize)
                prize["_source"] = source_name
                raw_items.append(prize)
        # 列表偶发延迟：空列表时短重试
        if not raw_items:
            for retry in range(1, 4):
                time.sleep(2 + retry)
                retry_res = self.list_member_prizes(
                    login_result,
                    member,
                    prize_type=prize_type,
                    page=page,
                    count=count,
                    limit_id=limit_id,
                    lottery_id=lottery_id,
                )
                sources.append((f"member_prize_info_retry{retry}", retry_res))
                for prize in self._extract_prize_items(retry_res):
                    code = self.extract_prize_code(prize)
                    key = code or json.dumps(prize, ensure_ascii=False, sort_keys=True)[:120]
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    prize = dict(prize)
                    prize["_source"] = f"member_prize_info_retry{retry}"
                    raw_items.append(prize)
                if lottery_id:
                    lr = self.list_lottery_prizes(
                        login_result,
                        member,
                        lottery_id,
                        page=page,
                        count=max(count, 100),
                        limit_id=limit_id or lottery_id,
                    )
                    sources.append((f"lottery_my_prize_info_retry{retry}", lr))
                    for prize in self._extract_prize_items(lr):
                        code = self.extract_prize_code(prize)
                        key = code or json.dumps(prize, ensure_ascii=False, sort_keys=True)[:120]
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        prize = dict(prize)
                        prize["_source"] = f"lottery_my_prize_info_retry{retry}"
                        raw_items.append(prize)
                if raw_items:
                    break

        if is_debug_enabled():
            for source_name, res in sources:
                preview = short_text(json.dumps(res, ensure_ascii=False), 240)
                debug_print(f"prize source {source_name}: {preview}")
            type_counts: dict[str, int] = {}
            for prize in raw_items:
                t = str(prize.get("prize_type"))
                type_counts[t] = type_counts.get(t, 0) + 1
            debug_print(f"prize raw_count={len(raw_items)} by_type={type_counts}")

        wechat_member = (wechat_member or "").strip()
        items: list[dict[str, Any]] = []
        other_prizes: list[dict[str, Any]] = []
        claimed = 0
        links: list[str] = []
        for prize in raw_items:
            if not isinstance(prize, dict):
                continue
            try:
                ptype = int(prize.get("prize_type") or 0)
            except (TypeError, ValueError):
                ptype = 0
            try:
                status = int(prize.get("status") or 0)
            except (TypeError, ValueError):
                status = 0
            content = str(prize.get("prize_content") or prize.get("award_name") or "").strip()
            if ptype != prize_type:
                other_prizes.append(
                    {
                        "prize_type": ptype,
                        "prize_content": content or f"type{ptype}",
                        "status": status,
                    }
                )
                continue
            if status in CLAIM_SKIP_STATUS:
                continue
            code = self.extract_prize_code(prize)
            content = content or code or "红包"
            entry: dict[str, Any] = {
                "prize_content": content,
                "status": status,
                "code": code,
            }
            if not code:
                entry["result"] = "missing_code"
                items.append(entry)
                continue
            link = self.redpacket_claim_link(code)
            entry["link"] = link
            if wechat_member:
                try:
                    claim_res = self.claim_redpacket(wechat_member, code)
                    entry["response"] = claim_res
                    # 大潮提现.js: hongbao?.success
                    if claim_res.get("success") is True:
                        entry["result"] = "claimed"
                        claimed += 1
                    else:
                        entry["result"] = "failed"
                        entry["message"] = (
                            claim_res.get("error_message")
                            or claim_res.get("message")
                            or "领取失败（微信 member 可能过期）"
                        )
                        links.append(link)
                except Exception as exc:
                    entry["result"] = "error"
                    entry["message"] = str(exc)
                    links.append(link)
            else:
                entry["result"] = "link_only"
                links.append(link)
            items.append(entry)

        other_names = []
        for op in other_prizes:
            name = str(op.get("prize_content") or "").strip()
            if name and name not in other_names:
                other_names.append(name)
        other_text = "、".join(short_text(n, 20) for n in other_names[:5])

        if not raw_items and list_res.get("error_message"):
            message = str(list_res.get("error_message"))
        elif not items:
            if other_text:
                message = f"无可领取红包；获得: {other_text}"
            else:
                message = "无可领取红包"
        elif wechat_member:
            message = f"领取成功 {claimed}/{len(items)}"
            if other_text:
                message += f"；其他: {other_text}"
        else:
            message = f"待微信领取 {len(items)} 个"
            if other_text:
                message += f"；其他: {other_text}"

        return {
            "success": True,
            "message": message,
            "list_response": list_res,
            "prizes": items,
            "other_prizes": other_prizes,
            "claimed": claimed,
            "links": links,
            "has_wechat_member": bool(wechat_member),
        }


    def lottery_remaining_counts(
        self,
        login_result: dict[str, Any],
        member: dict[str, Any],
        lottery_id: str,
        limit_id: str = "",
    ) -> int:
        info_res = self.lottery_info(login_result, member, lottery_id, limit_id=limit_id or lottery_id)
        response = info_res.get("response") if isinstance(info_res.get("response"), dict) else {}
        try:
            return int(response.get("remain_counts") or 0)
        except (TypeError, ValueError):
            return 0


    def aged_headers(self, login_result: dict[str, Any], drama_id: str) -> dict[str, str]:
        return {
            "X-USER-ID": f"xsb_94_{login_result['accountId']}",
            "X-APP-TENANT-ID": TENANT_ID,
            "X-DEVICE-ID": self.device.uuid,
            "Content-Type": "application/json",
            "Origin": AGED_BASE,
            "Referer": (
                f"{AGED_BASE}/silver/swipePlayPage?id={drama_id}"
                f"&tenantId={TENANT_ID}&gaze_control=022"
            ),
            "User-Agent": self.device.webview_ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "identity",
        }

    def aged_home_headers(self) -> dict[str, str]:
        return {
            "X-APP-TENANT-ID": TENANT_ID,
            "Content-Type": "application/json",
            "Origin": AGED_BASE,
            "Referer": f"{AGED_BASE}/silver/home?tenantId={TENANT_ID}&gaze_open=2",
            "User-Agent": self.device.webview_ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "identity",
        }

    @staticmethod
    def aged_response_error(res: dict[str, Any]) -> str:
        error_text = str(res.get("error_message") or res.get("error") or "").strip()
        if error_text.lower() in {"success", "ok"}:
            return ""
        code = res.get("code")
        if code not in {0, "0", 200, "200", None}:
            return str(res.get("message") or res.get("msg") or error_text or f"code={code}")
        if res.get("success") is False:
            return str(res.get("message") or res.get("msg") or error_text or "success=false")
        if error_text:
            return error_text
        return ""

    @staticmethod
    def encrypt_aged_watch_record(plaintext: str) -> str:
        try:
            from Crypto.Cipher import AES
        except ImportError as exc:
            raise RuntimeError("大潮视频上报缺少依赖，请安装 pycryptodome") from exc
        raw = plaintext.encode("utf-8")
        padding = AES.block_size - len(raw) % AES.block_size
        encrypted = AES.new(AGED_AES_KEY, AES.MODE_CBC, AGED_AES_IV).encrypt(raw + bytes([padding]) * padding)
        return base64.b64encode(encrypted).decode("ascii")

    def aged_video_detail(
        self,
        login_result: dict[str, Any],
        drama_id: str,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        headers = headers or self.aged_headers(login_result, drama_id)
        detail_res = self.request_json(
            AGED_BASE + "/aged/h5/agedDrama/video/detail",
            method="POST",
            headers=headers,
            body=json.dumps({"dramaId": drama_id}, separators=(",", ":")),
        )
        detail_error = self.aged_response_error(detail_res)
        if detail_error:
            raise RuntimeError(f"视频 detail 失败: {detail_error}")
        data = detail_res.get("data")
        if not isinstance(data, dict):
            raise RuntimeError(f"视频 detail 缺少 data: {json.dumps(detail_res, ensure_ascii=False)[:500]}")
        return detail_res, data

    def aged_tenant_host_info(
        self,
        login_result: dict[str, Any],
        drama_id: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = headers or self.aged_home_headers()
        res = self.request_json(
            AGED_BASE + "/aged/h5/tenant/host/info",
            method="POST",
            headers=headers,
            body=json.dumps({"appTenantId": TENANT_ID}, separators=(",", ":")),
        )
        host_error = self.aged_response_error(res)
        if host_error:
            raise RuntimeError(f"tenant host info 失败: {host_error}")
        data = res.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("tenantPromptConfig"), list):
            raise RuntimeError("tenant host info 缺少 data.tenantPromptConfig")
        return res

    @staticmethod
    def aged_video_tiers(configs: list[Any]) -> list[dict[str, Any]]:
        """解析视频分档。

        claim_index 优先：
        1) 配置项自带 claim_index / index / tenantPromptConfigIndex
        2) 与 HAR 默认 activityId 对齐的 0..3
        3) 在 tenantPromptConfig 全量数组中的绝对下标
        另存 lottery_order 为仅 AIX-LOTTERY 的顺序下标（0..n-1）供失败重试。
        """
        default_by_activity = {
            str(item.get("activityId")): int(item.get("claim_index"))
            for item in AGED_DEFAULT_VIDEO_TIERS
            if item.get("activityId") is not None and item.get("claim_index") is not None
        }
        default_by_minutes = {
            int(item.get("duration")): int(item.get("claim_index"))
            for item in AGED_DEFAULT_VIDEO_TIERS
            if item.get("duration") is not None and item.get("claim_index") is not None
        }
        tiers: list[dict[str, Any]] = []
        lottery_order = 0
        for abs_index, item in enumerate(configs):
            if not isinstance(item, dict):
                continue
            ac_code = str(item.get("acCode") or item.get("ac_code") or "").strip().upper()
            if ac_code and ac_code != "AIX-LOTTERY":
                continue
            # 无 acCode 时：有 activityId/duration 也尝试识别
            lottery_id = str(item.get("activityId") or item.get("activity_id") or "").strip()
            if not lottery_id:
                query = parse.parse_qs(parse.urlsplit(str(item.get("link") or "")).query)
                lottery_id = str((query.get("tid") or [""])[0]).strip()
            try:
                minutes = int(float(item.get("duration")))
            except (TypeError, ValueError):
                continue
            if minutes <= 0 or not lottery_id:
                continue
            raw_idx = item.get("claim_index", item.get("index", item.get("tenantPromptConfigIndex")))
            try:
                explicit_idx = int(raw_idx) if raw_idx is not None and str(raw_idx).strip() != "" else None
            except (TypeError, ValueError):
                explicit_idx = None
            mapped_idx = default_by_activity.get(lottery_id)
            if mapped_idx is None:
                mapped_idx = default_by_minutes.get(minutes)
            # 领取接口对 HAR 四档通常是 0..3；绝对下标作候选
            primary = explicit_idx if explicit_idx is not None else (
                mapped_idx if mapped_idx is not None else abs_index
            )
            candidates: list[int] = []
            for idx in (primary, mapped_idx, lottery_order, abs_index, explicit_idx):
                if idx is None:
                    continue
                try:
                    iv = int(idx)
                except (TypeError, ValueError):
                    continue
                if iv not in candidates:
                    candidates.append(iv)
            tiers.append(
                {
                    "minutes": minutes,
                    "required_seconds": minutes * 60,
                    "claim_index": primary,
                    "claim_index_candidates": candidates,
                    "lottery_order": lottery_order,
                    "config_abs_index": abs_index,
                    "lottery_id": lottery_id,
                    "prompt": str(item.get("prompt") or "").strip(),
                }
            )
            lottery_order += 1
        return sorted(tiers, key=lambda item: item["required_seconds"])

    def aged_claim_video_tier(self, headers: dict[str, str], claim_index: int) -> dict[str, Any]:
        result = {
            "claim_success": False,
            "already_claimed": False,
            "claim_error": "",
            "claim_index_used": claim_index,
        }
        try:
            claim_res = self.request_json(
                AGED_BASE + "/aged/h5/activity/lottery/add",
                method="POST",
                headers=headers,
                body=json.dumps({"tenantPromptConfigIndex": int(claim_index)}, separators=(",", ":")),
            )
        except RuntimeError as exc:
            message = str(exc)
            if "Duplicate entry" in message and "uk_user_config_lottery_date" in message:
                result.update({"already_claimed": True, "claim": {"message": "今日该档已领取"}})
            else:
                result["claim_error"] = message
            return result

        result["claim"] = claim_res
        result["claim_preview"] = short_text(json.dumps(claim_res, ensure_ascii=False), 220)
        claim_text = json.dumps(claim_res, ensure_ascii=False)
        if "Duplicate entry" in claim_text and "uk_user_config_lottery_date" in claim_text:
            result["already_claimed"] = True
            return result
        if any(k in claim_text for k in ("已领取", "已经领取", "已参与", "重复领取", "今日已领")):
            result["already_claimed"] = True
            return result
        claim_data = claim_res.get("data") if isinstance(claim_res.get("data"), dict) else {}
        link = str(claim_data.get("link") or claim_res.get("link") or "").strip()
        tid = ""
        if link:
            result["raffle_link"] = link
            try:
                tid = str((parse.parse_qs(parse.urlsplit(link).query).get("tid") or [""])[0]).strip()
            except Exception:
                tid = ""
            if tid:
                result["raffle_tid"] = tid
        task_values = [claim_res.get("taskCompleted"), claim_data.get("taskCompleted")]
        explicit_false = any(value is False for value in task_values)
        explicit_true = any(value is True for value in task_values)
        claim_error = self.aged_response_error(claim_res)
        if claim_error and not tid:
            result["claim_error"] = claim_error
            return result
        if explicit_true:
            result["claim_success"] = True
            return result
        if explicit_false:
            # 接口常返回 code=0 + 抽奖 link，同时 taskCompleted=false
            result["claim_error"] = "taskCompleted=false"
            result["soft_raffle"] = bool(tid)
            return result
        if tid or not claim_error:
            result["claim_success"] = True
            return result
        result["claim_error"] = claim_error or "领取结果未知"
        return result

    def aged_claim_video_tier_with_fallback(
        self,
        headers: dict[str, str],
        tier: dict[str, Any],
        used_indexes: set[int] | None = None,
        login_result: dict[str, Any] | None = None,
        member: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """按候选 index 依次领取；避免误用其它档已占用的 index。"""
        used_indexes = used_indexes if used_indexes is not None else set()
        candidates: list[int] = []
        for key in ("claim_index_candidates",):
            for idx in tier.get(key) or []:
                try:
                    iv = int(idx)
                except (TypeError, ValueError):
                    continue
                if iv not in candidates:
                    candidates.append(iv)
        for key in ("claim_index", "lottery_order", "config_abs_index"):
            if tier.get(key) is None:
                continue
            try:
                iv = int(tier.get(key))
            except (TypeError, ValueError):
                continue
            if iv not in candidates:
                candidates.append(iv)
        # 按分钟映射 HAR 默认 index（5->0,15->1,30->2,60->3）
        minute_map = {5: 0, 15: 1, 30: 2, 60: 3}
        mapped = minute_map.get(int(tier.get("minutes") or 0))
        if mapped is not None and mapped not in candidates:
            candidates.insert(0, mapped)
        # 仅补 0..3
        for iv in range(4):
            if iv not in candidates:
                candidates.append(iv)

        last: dict[str, Any] = {
            "claim_success": False,
            "already_claimed": False,
            "claim_error": "无可用 claim_index",
            "claim_attempts": [],
        }
        attempts: list[dict[str, Any]] = []
        for idx in candidates:
            if idx in used_indexes and idx != mapped and idx != tier.get("claim_index"):
                # 已被其它档占用的 index 跳过，减少误领
                continue
            # 主 headers + home headers 各试一次
            header_variants = [("play", headers)]
            try:
                header_variants.append(("home", self.aged_home_headers()))
                # home 也带上用户身份
                home = dict(header_variants[-1][1])
                if login_result:
                    home["X-USER-ID"] = f"xsb_94_{login_result['accountId']}"
                    home["X-DEVICE-ID"] = headers.get("X-DEVICE-ID") or self.device.uuid
                    home["Referer"] = headers.get("Referer") or home.get("Referer")
                header_variants[-1] = ("home", home)
            except Exception:
                pass

            for hname, hdrs in header_variants:
                one = self.aged_claim_video_tier(hdrs, idx)
                attempts.append(
                    {
                        "index": idx,
                        "headers": hname,
                        "success": bool(one.get("claim_success")),
                        "already_claimed": bool(one.get("already_claimed")),
                        "error": one.get("claim_error") or "",
                        "preview": one.get("claim_preview") or "",
                    }
                )
                if one.get("claim_success") or one.get("already_claimed"):
                    one["claim_attempts"] = attempts
                    one["claim_index"] = idx
                    return one
                last = one

        # 领取接口失败时：若 aihoge 侧已有抽奖次数，视为已具备资格
        lottery_id = str(tier.get("lottery_id") or "").strip()
        if login_result is not None and member is not None and lottery_id:
            try:
                remain = self.lottery_remaining_counts(login_result, member, lottery_id)
                attempts.append({"index": "remain_check", "remain": remain})
                if remain > 0:
                    return {
                        "claim_success": True,
                        "already_claimed": True,
                        "claim_error": "",
                        "claim_index": tier.get("claim_index"),
                        "claim_attempts": attempts,
                        "claim_verified_by_remain": True,
                        "lottery_remain_counts": remain,
                    }
            except Exception as exc:
                attempts.append({"index": "remain_check", "error": str(exc)})

        last["claim_attempts"] = attempts
        return last

    def run_aged_video_task(
        self,
        login_result: dict[str, Any],
        drama_id: str,
        target_seconds: int,
        report_seconds: int = 7,
        progress: Any = None,
        member: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = self.aged_headers(login_result, drama_id)
        config_source = "dynamic"
        try:
            host_info = self.aged_tenant_host_info(login_result, drama_id)
            tiers = self.aged_video_tiers(host_info["data"]["tenantPromptConfig"])
            if not tiers:
                raise RuntimeError("动态配置中没有有效的 AIX-LOTTERY 视频档位")
        except Exception as exc:
            config_source = "fallback"
            host_info = None
            fallback_configs = [{"acCode": "AIX-LOTTERY", **item} for item in AGED_DEFAULT_VIDEO_TIERS]
            tiers = self.aged_video_tiers(fallback_configs)
            for tier, default in zip(tiers, AGED_DEFAULT_VIDEO_TIERS):
                tier["claim_index"] = default["claim_index"]
                cands = list(tier.get("claim_index_candidates") or [])
                for idx in (default["claim_index"], tier.get("lottery_order")):
                    if idx is not None and int(idx) not in cands:
                        cands.insert(0, int(idx))
                tier["claim_index_candidates"] = cands
            if callable(progress):
                progress(f"[视频] tenant 配置获取异常，使用 HAR 确认的四档兜底: {short_text(exc, 80)}")

        selected_tiers = [{**tier, "reached": False, "claim_success": False, "already_claimed": False, "claim_error": ""}
                          for tier in tiers if tier["required_seconds"] <= target_seconds]
        used_claim_indexes: set[int] = set()
        if callable(progress):
            tier_text = ", ".join(f"{item['minutes']}分钟(index={item['claim_index']})" for item in selected_tiers)
            progress(f"[视频] {'动态' if config_source == 'dynamic' else '兜底'}档位: {tier_text or '目标内无可领取档位'}")

        detail_res, data = self.aged_video_detail(login_result, drama_id, headers=headers)
        try:
            detail_drama_id = str(data.get("dramaId") or drama_id)
            video_num = max(1, int(float(data.get("watchVideoNum") or 1)))
            video_count = max(0, int(float(data.get("videoCount") or 0)))
            current_progress = float(math.ceil(max(0.0, float(data.get("progress") or 0))))
            video_duration = float(math.ceil(max(0.0, float(data.get("videoDuration") or 0))))
            watched_seconds = max(0, int(float(data.get("userDayDuration") or 0)))
            version = data["version"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"视频 detail 字段异常: {json.dumps(data, ensure_ascii=False)[:500]}") from exc

        target_seconds = max(0, int(target_seconds))
        remaining = max(0, target_seconds - watched_seconds)
        report_seconds = max(1, int(report_seconds))
        reports: list[dict[str, Any]] = []
        reported_seconds = 0
        waited_seconds = 0.0
        verified_watched_seconds = watched_seconds
        verified_detail_res = detail_res
        report_url = AGED_BASE + "/aged/h5/agedDrama/watch/record/report?" + parse.urlencode({"version": version})
        log_every = max(1, math.ceil(30 / report_seconds))

        def watch_until(required_seconds: int) -> None:
            nonlocal video_num, current_progress, reported_seconds, waited_seconds
            nonlocal verified_watched_seconds, verified_detail_res
            estimated_seconds = verified_watched_seconds
            while verified_watched_seconds < required_seconds:
                while estimated_seconds < required_seconds:
                    if video_duration > 0 and current_progress >= video_duration:
                        video_num = video_num % video_count + 1 if video_count else video_num + 1
                        current_progress = 0.0
                    chunk = min(report_seconds, required_seconds - estimated_seconds)
                    if video_duration > 0:
                        chunk = min(chunk, max(1, math.ceil(video_duration - current_progress)))
                    sleep_seconds = chunk + random.random()
                    time.sleep(sleep_seconds)
                    waited_seconds += sleep_seconds
                    current_progress += chunk
                    reported_seconds += chunk
                    estimated_seconds += chunk
                    plaintext = f"{detail_drama_id} {video_num} {math.ceil(current_progress)} {chunk} {int(time.time() * 1000)}"
                    report_res = self.request_json(
                        report_url,
                        method="POST",
                        headers=headers,
                        body=json.dumps({"data": self.encrypt_aged_watch_record(plaintext)}, separators=(",", ":")),
                    )
                    report_error = self.aged_response_error(report_res)
                    if report_error:
                        raise RuntimeError(f"视频 report 失败: {report_error}")
                    reports.append(report_res)
                    if callable(progress) and len(reports) % log_every == 0:
                        progress(f"[视频] 已等待 {waited_seconds:.1f}s，上报 {reported_seconds}s/{remaining}s，共 {len(reports)} 次")
                time.sleep(1 + random.random() * 0.2)
                verified_detail_res, verified_data = self.aged_video_detail(
                    login_result, detail_drama_id, headers=headers
                )
                try:
                    verified_watched_seconds = max(0, int(float(verified_data.get("userDayDuration") or 0)))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("视频 detail 最新 userDayDuration 异常") from exc
                estimated_seconds = verified_watched_seconds

        for tier in selected_tiers:
            watch_until(tier["required_seconds"])
            # 档位临界点稍等，避免服务端累计延迟
            time.sleep(1.5 + random.random())
            _, verified_data = self.aged_video_detail(login_result, detail_drama_id, headers=headers)
            try:
                verified_watched_seconds = max(0, int(float(verified_data.get("userDayDuration") or 0)))
            except (TypeError, ValueError):
                pass
            tier["reached"] = verified_watched_seconds >= tier["required_seconds"]
            if tier["reached"]:
                claim_res = self.aged_claim_video_tier_with_fallback(
                    headers,
                    tier,
                    used_indexes=used_claim_indexes,
                    login_result=login_result,
                    member=member,
                )
                tier.update(claim_res)
                if claim_res.get("claim_index") is not None:
                    tier["claim_index"] = claim_res.get("claim_index")
                    try:
                        used_claim_indexes.add(int(claim_res.get("claim_index")))
                    except (TypeError, ValueError):
                        pass
            if callable(progress):
                if tier.get("already_claimed") and tier.get("claim_verified_by_remain"):
                    claim_status = f"已有抽奖次数(remain) index={tier.get('claim_index')}"
                elif tier.get("already_claimed"):
                    claim_status = f"今日已领取 index={tier.get('claim_index')}"
                elif tier.get("claim_success"):
                    claim_status = f"领取成功(index={tier.get('claim_index')})"
                else:
                    claim_status = f"领取失败: {tier.get('claim_error') or '未达到'} index={tier.get('claim_index')}"
                progress(
                    f"[视频{tier['minutes']}分钟] 服务端确认 {verified_watched_seconds}s，{claim_status}"
                )
                if is_debug_enabled() and not tier.get("claim_success") and not tier.get("already_claimed"):
                    for att in (tier.get("claim_attempts") or [])[:8]:
                        progress(
                            f"[视频DEBUG] {tier['minutes']}分 try index={att.get('index')} "
                            f"hdr={att.get('headers') or '-'} err={short_text(att.get('error'), 40)} "
                            f"resp={short_text(att.get('preview'), 120)}"
                        )

        if verified_watched_seconds < target_seconds:
            watch_until(target_seconds)

        # 全部看完后再补领失败档（常见：中途 taskCompleted 延迟）
        time.sleep(2 + random.random())
        _, verified_data = self.aged_video_detail(login_result, detail_drama_id, headers=headers)
        try:
            verified_watched_seconds = max(0, int(float(verified_data.get("userDayDuration") or 0)))
        except (TypeError, ValueError):
            pass
        for tier in selected_tiers:
            if tier.get("claim_success") or tier.get("already_claimed"):
                continue
            if verified_watched_seconds < int(tier.get("required_seconds") or 0):
                continue
            tier["reached"] = True
            claim_res = self.aged_claim_video_tier_with_fallback(
                headers,
                tier,
                used_indexes=used_claim_indexes,
                login_result=login_result,
                member=member,
            )
            # 仅在更好结果时覆盖
            if claim_res.get("claim_success") or claim_res.get("already_claimed"):
                tier.update(claim_res)
                if claim_res.get("claim_index") is not None:
                    tier["claim_index"] = claim_res.get("claim_index")
                    try:
                        used_claim_indexes.add(int(claim_res.get("claim_index")))
                    except (TypeError, ValueError):
                        pass
                if callable(progress):
                    status = "今日已领取" if claim_res.get("already_claimed") else "补领成功"
                    progress(f"[视频{tier['minutes']}分钟] {status}(index={tier.get('claim_index')})")
            elif claim_res.get("claim_error"):
                tier["claim_error"] = claim_res.get("claim_error")

        lottery_ids: list[str] = []
        for tier in selected_tiers:
            if not tier.get("reached"):
                continue
            # 固定优先档位 activityId，避免多 index 试领回包 tid 串档
            lottery_id = str(tier.get("lottery_id") or "").strip()
            raffle_tid = str(tier.get("raffle_tid") or "").strip()
            used_idx = tier.get("claim_index_used", tier.get("claim_index"))
            mapped = {5: 0, 15: 1, 30: 2, 60: 3}.get(int(tier.get("minutes") or 0))
            if raffle_tid and mapped is not None and used_idx is not None:
                try:
                    if int(used_idx) == int(mapped):
                        lottery_id = raffle_tid
                        tier["lottery_id"] = raffle_tid
                except (TypeError, ValueError):
                    pass
            if lottery_id and lottery_id not in lottery_ids:
                lottery_ids.append(lottery_id)
            if not tier.get("claim_success") and not tier.get("already_claimed"):
                if lottery_id:
                    tier["lottery_ready_by_duration"] = True
        return {
            "drama_id": detail_drama_id,
            "watch_video_num": video_num,
            "progress": current_progress,
            "video_duration": video_duration,
            "video_count": video_count,
            "version": version,
            "target_seconds": target_seconds,
            "watched_seconds": watched_seconds,
            "verified_watched_seconds": verified_watched_seconds,
            "remaining_seconds": remaining,
            "waited_seconds": waited_seconds,
            "reported_seconds": reported_seconds,
            "report_count": len(reports),
            "detail": detail_res,
            "verified_detail": verified_detail_res,
            "reports": reports,
            "last_report": reports[-1] if reports else None,
            "tiers": selected_tiers,
            "lottery_ids": lottery_ids,
            "tier_config_source": config_source,
            "tenant_host_info": host_info,
        }

    def build_read_article_params(
        self,
        activity_id: str,
        item_id: str,
        request_id: str,
        tn_x: int | str,
        timestamp: str | int | None = None,
    ) -> tuple[str, str, str]:
        ts = str(timestamp if timestamp is not None else int(time.time() + 0.5))
        plaintext = json.dumps(
            {
                "news_id": activity_id,
                "item_id": item_id,
                "request_id": request_id,
                "timestamp": ts,
                "tn_x": tn_x,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        encrypted = rsa_pkcs1_v15_encrypt_base64(AIHOGE_ACT_SIGN_PUBLIC_KEY, plaintext)
        return ts, plaintext, encrypted

    def read_referer(self, activity_id: str) -> str:
        return f"{AIHOGE_BASE}/h5?mark=news-read@designh5&tid={activity_id}&path=index&isNeedLogin=true"

    def get_read_tncode(
        self,
        login_result: dict[str, Any],
        member: dict[str, Any],
        activity_id: str,
    ) -> dict[str, Any]:
        return self.request_json(
            self.aihoge_api_url(f"/newshy/api/client/news/getTnCode?t={random.random()}"),
            method="GET",
            headers=self.aihoge_headers(
                login_result["sessionId"],
                login_result["accountId"],
                member=self.build_aihoge_member_header(member),
                limit_id=activity_id,
                referer=self.read_referer(activity_id),
            ),
        )

    @staticmethod
    def extract_ocr_x(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(round(value))
        if isinstance(value, str):
            match = re.search(r"-?\d+(?:\.\d+)?", value)
            return int(round(float(match.group(0)))) if match else None
        if isinstance(value, (list, tuple)):
            # StupidOCR 常见: [x, y] 或 bbox [x1, y1, x2, y2]
            nums: list[float] = []
            for item in value:
                if isinstance(item, bool):
                    continue
                if isinstance(item, (int, float)):
                    nums.append(float(item))
                elif isinstance(item, str):
                    match = re.search(r"-?\d+(?:\.\d+)?", item)
                    if match:
                        nums.append(float(match.group(0)))
            if len(nums) >= 4:
                x1, _y1, x2, _y2 = nums[:4]
                # 全宽/异常框不要当滑动距离
                if (x2 - x1) >= 200:
                    return None
                return int(round(x1))
            if len(nums) >= 1:
                return int(round(nums[0]))
            for item in value:
                found = DachaoClient.extract_ocr_x(item)
                if found is not None:
                    return found
            return None
        if isinstance(value, dict):
            # 优先明确的 x 字段，避免先吃到 target_y=0
            for key in (
                "target_x",
                "targetX",
                "tn_x",
                "x",
                "X",
                "left",
                "offset",
                "target",
                "result",
                "coordinate",
                "coordinates",
                "data",
                "res",
            ):
                if key in value:
                    found = DachaoClient.extract_ocr_x(value.get(key))
                    if found is not None:
                        return found
            for key, item in value.items():
                if str(key).lower() in {"target_y", "y", "bilibili", "supports"}:
                    continue
                found = DachaoClient.extract_ocr_x(item)
                if found is not None:
                    return found
        return None

    @staticmethod
    def is_valid_tn_x(value: Any, min_x: int = 1, max_x: int = 220) -> bool:
        """大潮滑块 tn_x=0 几乎必失败，视为 OCR 无效。"""
        try:
            x = int(value)
        except (TypeError, ValueError):
            return False
        return min_x <= x <= max_x

    @staticmethod
    def normalize_ocr_result(ocr_res: Any) -> dict[str, Any]:
        if not isinstance(ocr_res, dict):
            ocr_res = {"raw": ocr_res}
        tn_x = DachaoClient.extract_ocr_x(ocr_res)
        out = dict(ocr_res)
        out["result"] = tn_x
        return out

    def load_image_bytes(self, image_url: str) -> bytes:
        image_url = str(image_url or "").strip()
        if image_url.startswith("data:") and "," in image_url:
            return base64.b64decode(image_url.split(",", 1)[1])
        return self.request_binary(
            image_url,
            headers={
                "User-Agent": self.device.webview_ua,
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
        )

    def _png_b64(self, image: Any) -> str:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def load_tncode_image(self, image_url: str, progress: Any = None):
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "使用 StupidOCR 需要 Pillow；青龙可先安装依赖: pip3 install pillow"
            ) from exc
        if callable(progress):
            progress("[阅读] OCR 下载滑块图")
        raw = self.load_image_bytes(image_url)
        if callable(progress):
            progress(f"[阅读] OCR 裁图，原图 {len(raw)} bytes")
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        return img, raw

    def split_tncode_strips(self, img: Any, y_coordinate: int = 150) -> dict[str, Any]:
        """大潮 tncode 竖拼图: strip0=缺口图, strip1=滑块条, strip2=完整图。"""
        width, height = img.size
        strip_h = 0
        if height % 150 == 0 and height // 150 >= 3:
            strip_h = 150
        elif height >= 300 and height % 3 == 0:
            strip_h = height // 3
        info: dict[str, Any] = {
            "width": width,
            "height": height,
            "strip_h": strip_h,
            "layout": "unknown",
        }
        if strip_h > 0 and height >= strip_h * 3:
            info.update(
                {
                    "layout": "tncode_3strip",
                    "gap": img.crop((0, 0, width, strip_h)),
                    "piece": img.crop((0, strip_h, width, strip_h * 2)),
                    "full": img.crop((0, strip_h * 2, width, strip_h * 3)),
                }
            )
            return info
        split_y = max(1, min(int(y_coordinate or 150), height - 1))
        info.update(
            {
                "layout": "split_y",
                "split_y": split_y,
                "top": img.crop((0, 0, width, split_y)),
                "bottom": img.crop((0, split_y, width, height)),
            }
        )
        return info

    def crop_tncode_for_stupidocr(self, image_url: str, y_coordinate: int, progress: Any = None) -> tuple[str, str]:
        img, _raw = self.load_tncode_image(image_url, progress=progress)
        parts = self.split_tncode_strips(img, y_coordinate=y_coordinate)
        if parts.get("layout") == "tncode_3strip":
            return self._png_b64(parts["piece"]), self._png_b64(parts["gap"])
        return self._png_b64(parts["top"]), self._png_b64(parts["bottom"])

    def call_stupidocr_slider_comparison(
        self,
        base_url: str,
        image_url: str,
        y_coordinate: int = 150,
        progress: Any = None,
    ) -> dict[str, Any]:
        img, _raw = self.load_tncode_image(image_url, progress=progress)
        parts = self.split_tncode_strips(img, y_coordinate=y_coordinate)
        if parts.get("layout") != "tncode_3strip":
            raise RuntimeError(
                f"当前滑块图不是 tncode 三拼图，无法走 Slider_Comparison: size={parts.get('width')}x{parts.get('height')}"
            )
        if callable(progress):
            progress("[阅读] OCR 提交 StupidOCR /api.Slider_Comparison（缺口图 vs 完整图）")
        res = self.request_json(
            base_url + "/api.Slider_Comparison",
            method="POST",
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "Accept": "application/json",
            },
            body=json.dumps(
                {
                    "HaveGap_ImageBase64": self._png_b64(parts["gap"]),
                    "Full_ImageBase64": self._png_b64(parts["full"]),
                },
                ensure_ascii=False,
            ),
        )
        tn_x = self.extract_ocr_x(res)
        if tn_x is None:
            raise RuntimeError(
                f"StupidOCR /api.Slider_Comparison 返回异常: {json.dumps(res, ensure_ascii=False)[:300]}"
            )
        return {
            "result": tn_x,
            "engine": "stupidocr_slider_comparison",
            "layout": "tncode_3strip",
            "raw": res,
        }

    def call_stupidocr_slider_move(
        self,
        base_url: str,
        image_url: str,
        y_coordinate: int,
        progress: Any = None,
    ) -> dict[str, Any]:
        move_b64, background_b64 = self.crop_tncode_for_stupidocr(image_url, y_coordinate, progress=progress)
        if callable(progress):
            progress("[阅读] OCR 提交 StupidOCR /api.Slider_Move")
        res = self.request_json(
            base_url + "/api.Slider_Move",
            method="POST",
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "Accept": "application/json",
            },
            body=json.dumps(
                {
                    "MovePicture": move_b64,
                    "Background": background_b64,
                },
                ensure_ascii=False,
            ),
        )
        tn_x = self.extract_ocr_x(res)
        if tn_x is None:
            raise RuntimeError(f"StupidOCR /api.Slider_Move 返回异常: {json.dumps(res, ensure_ascii=False)[:300]}")
        return {
            "result": tn_x,
            "engine": "stupidocr_slider_move",
            "raw": res,
        }

    def call_stupidocr(
        self,
        base_url: str,
        image_url: str,
        y_coordinate: int = 150,
        progress: Any = None,
    ) -> dict[str, Any]:
        """大潮 tncode 优先 Slider_Comparison；失败再回退 Slider_Move。"""
        last_err = ""
        try:
            res = self.call_stupidocr_slider_comparison(
                base_url, image_url, y_coordinate=y_coordinate, progress=progress
            )
            if self.is_valid_tn_x(res.get("result")):
                return res
            last_err = f"Slider_Comparison tn_x 无效: {res.get('result')}"
            if callable(progress):
                progress(f"[阅读] {last_err}，回退 Slider_Move")
        except Exception as exc:
            last_err = str(exc)
            if callable(progress):
                progress(f"[阅读] Slider_Comparison 失败: {short_text(exc, 80)}，回退 Slider_Move")
        res = self.call_stupidocr_slider_move(base_url, image_url, y_coordinate, progress=progress)
        if not self.is_valid_tn_x(res.get("result")) and last_err:
            res["warning"] = last_err
        return res

    def call_slide_ocr(
        self,
        ocr_server: str,
        image_url: str,
        y_coordinate: int = 150,
        progress: Any = None,
        fallback_server: str = "",
    ) -> dict[str, Any]:
        base_url = normalize_slide_ocr_base_url(ocr_server)
        if not base_url or env_falsey_value(base_url):
            raise RuntimeError("未配置 OCR_SERVER/DaChao_OCR_SERVER")

        def _run_one(server: str) -> dict[str, Any]:
            if is_stupidocr_server(server):
                return self.normalize_ocr_result(
                    self.call_stupidocr(server, image_url, y_coordinate, progress=progress)
                )
            headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "Accept": "application/json",
            }
            try:
                if callable(progress):
                    progress("[阅读] OCR 提交 /crop")
                crop_res = self.request_json(
                    server + "/crop",
                    method="POST",
                    headers=headers,
                    body=json.dumps({"image": image_url, "y_coordinate": y_coordinate}, ensure_ascii=False),
                )
            except RuntimeError as exc:
                if "HTTP 404" in str(exc):
                    return self.normalize_ocr_result(
                        self.call_stupidocr(server, image_url, y_coordinate, progress=progress)
                    )
                raise
            sliding_image = crop_res.get("slidingImage")
            back_image = crop_res.get("backImage")
            if not sliding_image or not back_image:
                raise RuntimeError(f"OCR crop 返回异常: {json.dumps(crop_res, ensure_ascii=False)[:300]}")
            if callable(progress):
                progress("[阅读] OCR 提交 /slideComparison")
            raw = self.request_json(
                server + "/slideComparison",
                method="POST",
                headers=headers,
                body=json.dumps(
                    {
                        "slidingImage": sliding_image,
                        "backImage": back_image,
                    },
                    ensure_ascii=False,
                ),
            )
            out = self.normalize_ocr_result(raw)
            out["engine"] = out.get("engine") or "crop_slideComparison"
            return out

        primary = _run_one(base_url)
        if self.is_valid_tn_x(primary.get("result")):
            return primary

        fb = normalize_slide_ocr_base_url(fallback_server or "")
        # 不再回退到写死的默认 OCR 主机；仅使用显式 fallback / 环境变量
        if fb and fb.rstrip("/") != base_url.rstrip("/"):
            if callable(progress):
                progress(f"[阅读] 主 OCR tn_x 无效({primary.get('result')})，回退 {fb}")
            try:
                secondary = _run_one(fb)
                secondary["fallback_from"] = base_url
                secondary["primary_result"] = primary.get("result")
                if self.is_valid_tn_x(secondary.get("result")):
                    return secondary
                primary["fallback_result"] = secondary
            except Exception as fb_exc:
                primary["fallback_error"] = str(fb_exc)
        return primary

    def read_activity_detail(
        self,
        login_result: dict[str, Any],
        member: dict[str, Any],
        activity_id: str,
    ) -> dict[str, Any]:
        return self.request_json(
            self.aihoge_api_url(f"/newshy/api/client/news/list/{activity_id}"),
            method="GET",
            headers=self.aihoge_headers(
                login_result["sessionId"],
                login_result["accountId"],
                member=self.build_aihoge_member_header(member),
                limit_id=activity_id,
                referer=self.read_referer(activity_id),
            ),
        )

    @staticmethod
    def extract_read_items(detail_res: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for activity in detail_res.get("data") or []:
            for block in activity.get("information_content_data") or []:
                for item in block.get("data") or []:
                    if item.get("item_id") and item.get("is_read_task", 1):
                        items.append(item)
        return items

    @staticmethod
    def extract_read_draw_id(detail_res: dict[str, Any]) -> str:
        data = detail_res.get("data") or []
        if not data or not isinstance(data[0], dict):
            return ""
        draw = data[0].get("draw")
        if isinstance(draw, dict):
            return str(draw.get("activity_id") or "")
        return str(data[0].get("draw_activity_id") or "")

    @staticmethod
    def read_response_message(res: dict[str, Any]) -> str:
        return str(
            res.get("error_message")
            or res.get("message")
            or res.get("msg")
            or res.get("errmsg")
            or res.get("success")
            or ""
        )

    @staticmethod
    def is_read_success_response(res: dict[str, Any]) -> bool:
        return res.get("success") in {1, "1", True} or res.get("error_code") in {0, "0"}

    @staticmethod
    def is_read_throttle_response(res: dict[str, Any]) -> bool:
        message = DachaoClient.read_response_message(res)
        return "慢点" in message or "频繁" in message or "too fast" in message.lower()

    @staticmethod
    def is_read_not_started_response(res: dict[str, Any]) -> bool:
        message = DachaoClient.read_response_message(res)
        return "未开始" in message

    @staticmethod
    def is_read_ended_response(res: dict[str, Any]) -> bool:
        message = DachaoClient.read_response_message(res)
        return "已结束" in message or "活动结束" in message or "敬请关注后续" in message

    def read_article_once(
        self,
        login_result: dict[str, Any],
        member: dict[str, Any],
        activity_id: str,
        item_id: str,
        request_id: str,
        tn_x: int | str,
    ) -> dict[str, Any]:
        _, _, params = self.build_read_article_params(activity_id, item_id, request_id, tn_x)
        return self.request_json(
            self.aihoge_api_url("/newshy/api/client/news/readArticle"),
            method="POST",
            headers=self.aihoge_headers(
                login_result["sessionId"],
                login_result["accountId"],
                member=self.build_aihoge_member_header(member),
                limit_id=activity_id,
                referer=self.read_referer(activity_id),
            ),
            body=json.dumps({"params": params}, ensure_ascii=False, separators=(",", ":")),
        )

    def run_read_articles(
        self,
        login_result: dict[str, Any],
        member: dict[str, Any],
        activity_id: str = AIHOGE_DEFAULT_READ_ACTIVITY_ID,
        ocr_server: str = AIHOGE_DEFAULT_OCR_SERVER,
        ocr_fallback_server: str = "",
        max_articles: int = 20,
        read_delay: int = 8,
        throttle_retry_delay: int = 25,
        throttle_retry_times: int = 1,
        throttle_stop_count: int = 3,
        ocr_retry_times: int = 3,
        ocr_min_x: int = 1,
        ocr_max_x: int = 220,
        progress: Any = None,
    ) -> dict[str, Any]:
        request_id = ""
        image_url = ""
        tn_x: int | str | None = None
        ocr_attempts: list[dict[str, Any]] = []
        last_ocr_error = ""
        total_ocr_tries = max(1, int(ocr_retry_times) + 1)
        for ocr_try in range(1, total_ocr_tries + 1):
            if callable(progress):
                progress(f"[阅读] 获取滑块 ({ocr_try}/{total_ocr_tries})")
            tn_res = self.get_read_tncode(login_result, member, activity_id)
            request_id = str(tn_res.get("request_id") or "")
            image_url = str(tn_res.get("img") or "")
            if not request_id or not image_url:
                last_ocr_error = f"滑块接口返回异常: {json.dumps(tn_res, ensure_ascii=False)[:300]}"
                ocr_attempts.append({"try": ocr_try, "error": last_ocr_error})
                continue
            if callable(progress):
                progress(f"[阅读] OCR 识别中 ({ocr_try}/{total_ocr_tries})")
            try:
                ocr_res = self.call_slide_ocr(
                    ocr_server,
                    image_url,
                    progress=progress,
                    fallback_server=ocr_fallback_server,
                )
            except Exception as ocr_exc:
                last_ocr_error = str(ocr_exc)
                ocr_attempts.append({"try": ocr_try, "error": last_ocr_error})
                if callable(progress):
                    progress(f"[阅读] OCR 异常: {short_text(ocr_exc, 80)}")
                continue
            tn_x = ocr_res.get("result")
            ocr_attempts.append(
                {
                    "try": ocr_try,
                    "request_id": request_id,
                    "tn_x": tn_x,
                    "ocr_preview": short_text(json.dumps(ocr_res, ensure_ascii=False), 180),
                }
            )
            if self.is_valid_tn_x(tn_x, min_x=ocr_min_x, max_x=ocr_max_x):
                if callable(progress):
                    progress(f"[阅读] OCR 完成 tn_x={tn_x}")
                break
            last_ocr_error = f"OCR tn_x 无效: {tn_x}（要求 {ocr_min_x}~{ocr_max_x}）"
            if callable(progress):
                progress(f"[阅读] {last_ocr_error}，准备重取滑块")
            tn_x = None
            time.sleep(1 + random.random())
        if not self.is_valid_tn_x(tn_x, min_x=ocr_min_x, max_x=ocr_max_x):
            raise RuntimeError(
                f"OCR 滑块识别失败，已重试 {total_ocr_tries} 次；最后错误: {last_ocr_error or 'tn_x 无效'}"
            )

        if callable(progress):
            progress("[阅读] 获取文章列表")
        detail_res = self.read_activity_detail(login_result, member, activity_id)
        items = self.extract_read_items(detail_res)
        selected_items = items[:max_articles]
        if callable(progress):
            progress(f"[阅读] 准备阅读 {len(selected_items)}/{len(items)} 篇")
        result: dict[str, Any] = {
            "activity_id": activity_id,
            "request_id": request_id,
            "tn_x": tn_x,
            "ocr_attempts": ocr_attempts,
            "ocr_retry_times": ocr_retry_times,
            "ocr_min_x": ocr_min_x,
            "ocr_max_x": ocr_max_x,
            "total_items": len(items),
            "max_articles": max_articles,
            "read_delay": read_delay,
            "throttle_retry_delay": throttle_retry_delay,
            "throttle_retry_times": throttle_retry_times,
            "throttle_stop_count": throttle_stop_count,
            "success": 0,
            "results": [],
            "draw_activity_id": self.extract_read_draw_id(detail_res),
        }
        consecutive_throttle = 0
        for item in selected_items:
            item_result: dict[str, Any] = {
                "title": item.get("title", ""),
                "item_id": item.get("item_id", ""),
                "attempts": 0,
            }
            try:
                if read_delay > 0:
                    if callable(progress):
                        progress(f"[阅读] 等待 {read_delay}s 后阅读: {short_text(item.get('title'), 24)}")
                    time.sleep(read_delay + random.random() * 2)
                final_res: dict[str, Any] = {}
                for attempt in range(throttle_retry_times + 1):
                    item_result["attempts"] = attempt + 1
                    final_res = self.read_article_once(
                        login_result,
                        member,
                        activity_id,
                        str(item.get("item_id", "")),
                        request_id,
                        tn_x,
                    )
                    if self.is_read_success_response(final_res):
                        break
                    if not self.is_read_throttle_response(final_res) or attempt >= throttle_retry_times:
                        break
                    time.sleep(throttle_retry_delay + random.random() * 3)
                item_result["response"] = final_res
                if self.is_read_success_response(final_res):
                    result["success"] += 1
                    consecutive_throttle = 0
                elif self.is_read_not_started_response(final_res):
                    result["stopped_reason"] = "not_started"
                    result["stopped_message"] = "阅读活动未开始，已停止后续文章"
                elif self.is_read_ended_response(final_res):
                    result["stopped_reason"] = "ended"
                    result["stopped_message"] = "阅读活动已结束，已停止后续文章"
                elif self.is_read_throttle_response(final_res):
                    consecutive_throttle += 1
                else:
                    consecutive_throttle = 0
            except Exception as exc:
                item_result["error"] = str(exc)
            result["results"].append(item_result)
            if result.get("stopped_reason") in {"not_started", "ended"}:
                break
            if throttle_stop_count > 0 and consecutive_throttle >= throttle_stop_count:
                result["stopped_reason"] = "throttle"
                result["stopped_message"] = "连续返回“您请慢点~”，已停止阅读，避免继续触发节流"
                break
        return result

    @staticmethod
    def ensure_code0(res: dict[str, Any], label: str) -> None:
        if res.get("code") != 0:
            raise RuntimeError(f"{label} 失败: {json.dumps(res, ensure_ascii=False)[:500]}")

    def login(self, mobile: str, password: str) -> dict[str, Any]:
        init_data = self.account_init()
        anonymous_session_id = init_data["session"]["id"]
        code = self.credential_auth(mobile, password)
        login_data = self.zbtxz_login(anonymous_session_id, code)
        session = login_data["session"]
        account = login_data["account"]
        session_id = session["id"]
        account_id = session.get("account_id") or account["id"]
        detail = self.account_detail(session_id, account_id)
        if detail and isinstance(detail.get("rst"), dict):
            account.update(detail["rst"])
        return {
            "mobile": mobile,
            "sessionId": session_id,
            "accountId": account_id,
            "nickName": account.get("nick_name", ""),
            "imageUrl": account.get("image_url", ""),
            "raw": {
                "session": session,
                "account": account,
            },
        }


def save_sessions(results: list[dict[str, Any]]) -> Path:
    output_dir = Path(__file__).resolve().parents[1] / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "dachao_login_sessions.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    raw = read_accounts_env()
    accounts = split_accounts(raw)
    if not accounts:
        message = "缺少环境变量 DaChao，格式: 手机号&密码，多账号用 @ 或换行分隔"
        print(message)
        qinglong_notify(SCRIPT_NAME, message)
        return 2

    debug_enabled = is_debug_enabled()
    show_token = (
        debug_enabled
        or env_truthy("DaChao_SHOW_TOKEN")
        or env_truthy("DACHAO_SHOW_TOKEN")
    )
    save_session = (
        debug_enabled
        or env_truthy("DaChao_SAVE_SESSION")
        or env_truthy("DACHAO_SAVE_SESSION")
    )
    get_member = (
        debug_enabled
        or env_truthy("DaChao_GET_MEMBER")
        or env_truthy("DACHAO_GET_MEMBER")
    )
    # 顶部 MANUAL_* 优先于环境变量
    sign_enabled = resolve_manual_enabled(MANUAL_ENABLE_SIGN, "DaChao_SIGN", "DACHAO_SIGN", default="1")
    match_enabled = resolve_manual_enabled(MANUAL_ENABLE_MATCH, "DaChao_MATCH", "DACHAO_MATCH", default="1")
    read_enabled = resolve_manual_enabled(MANUAL_ENABLE_READ, "DaChao_READ", "DACHAO_READ", default="1")
    lottery_enabled = resolve_manual_enabled(MANUAL_ENABLE_LOTTERY, "DaChao_LOTTERY", "DACHAO_LOTTERY", default="1")
    claim_enabled = resolve_manual_enabled(
        MANUAL_ENABLE_CLAIM,
        "DaChao_CLAIM",
        "DACHAO_CLAIM",
        "DaChao_HONGBAO",
        "DACHAO_HONGBAO",
        default="1",
    )
    video_enabled = resolve_manual_enabled(
        MANUAL_ENABLE_VIDEO,
        "DaChao_VIDEO",
        "DACHAO_VIDEO",
        default="1",
    )
    video_drama_id = resolve_manual_text(
        MANUAL_VIDEO_DRAMA_ID,
        "DaChao_VIDEO_DRAMA_ID",
        "DACHAO_VIDEO_DRAMA_ID",
        default=AGED_DEFAULT_DRAMA_ID,
    ) or AGED_DEFAULT_DRAMA_ID
    if MANUAL_VIDEO_TARGET_SECONDS is not None:
        video_target_seconds = max(0, int(MANUAL_VIDEO_TARGET_SECONDS))
    else:
        video_target_seconds = env_int(
            "DaChao_VIDEO_TARGET_SECONDS",
            "DACHAO_VIDEO_TARGET_SECONDS",
            default=3600,
            minimum=0,
        )
    video_report_seconds = env_int(
        "DaChao_VIDEO_REPORT_SECONDS",
        "DACHAO_VIDEO_REPORT_SECONDS",
        default=7,
        minimum=7,
        maximum=60,
    )
    global_wechat_member = env_first(
        "DaChao_WECHAT_MEMBER",
        "DACHAO_WECHAT_MEMBER",
        "DaChao_HONGBAO_TOKEN",
        "DACHAO_HONGBAO_TOKEN",
        "DaChao_MEMBER_HONGBAO",
        default="",
    ).strip()
    needs_member = get_member or sign_enabled or match_enabled or read_enabled or lottery_enabled or claim_enabled or video_enabled

    sign_activity_id = env_first(
        "DaChao_SIGN_ACTIVITY_ID",
        "DACHAO_SIGN_ACTIVITY_ID",
        default=AIHOGE_DEFAULT_SIGN_ACTIVITY_ID,
    ).strip()
    sign_limit_id = env_first("DaChao_LIMIT_ID", "DACHAO_LIMIT_ID", default=AIHOGE_DEFAULT_LIMIT_ID).strip()
    # 阅读活动优先级：手动 > 环境变量 > buoy/list 动态发现 > 默认常量
    configured_read_activity_id = resolve_manual_text(
        MANUAL_READ_ACTIVITY_ID,
        "DaChao_READ_ACTIVITY_ID",
        "DACHAO_READ_ACTIVITY_ID",
        default="",
    )
    read_activity_id = configured_read_activity_id
    read_activity_source = "manual_or_env" if configured_read_activity_id else ""
    read_discover_enabled = resolve_manual_enabled(
        MANUAL_READ_DISCOVER,
        "DaChao_READ_DISCOVER",
        "DACHAO_READ_DISCOVER",
        default="1",
    )
    configured_lottery_id = env_first("DaChao_LOTTERY_ID", "DACHAO_LOTTERY_ID").strip()
    ocr_server = normalize_base_url(
        env_first(
            "DaChao_OCR_SERVER",
            "DACHAO_OCR_SERVER",
            "DaChao_DDDDOCR_URL",
            "DDDDOCR_URL",
            "OCR_SERVER",
            default=AIHOGE_DEFAULT_OCR_SERVER,
        )
    )
    ocr_fallback_server = normalize_base_url(
        env_first(
            "DaChao_OCR_FALLBACK",
            "DACHAO_OCR_FALLBACK",
            default="",
        )
    )
    read_max_articles = env_int("DaChao_READ_MAX", "DACHAO_READ_MAX", default=20, minimum=1, maximum=50)
    read_delay = env_int("DaChao_READ_DELAY", "DACHAO_READ_DELAY", default=8, minimum=0, maximum=120)
    read_retry_delay = env_int("DaChao_READ_RETRY_DELAY", "DACHAO_READ_RETRY_DELAY", default=25, minimum=5, maximum=300)
    read_retry_times = env_int("DaChao_READ_RETRY", "DACHAO_READ_RETRY", default=1, minimum=0, maximum=3)
    read_throttle_stop = env_int(
        "DaChao_READ_THROTTLE_STOP",
        "DACHAO_READ_THROTTLE_STOP",
        default=3,
        minimum=0,
        maximum=20,
    )
    ocr_retry_times = env_int("DaChao_OCR_RETRY", "DACHAO_OCR_RETRY", default=3, minimum=0, maximum=8)
    ocr_min_x = env_int("DaChao_OCR_MIN_X", "DACHAO_OCR_MIN_X", default=1, minimum=0, maximum=300)
    ocr_max_x = env_int("DaChao_OCR_MAX_X", "DACHAO_OCR_MAX_X", default=220, minimum=1, maximum=500)
    if ocr_max_x < ocr_min_x:
        ocr_max_x = ocr_min_x
    match_bases = parse_daily_match_bases(
        resolve_manual_text(
            MANUAL_MATCH_URL,
            "DaChao_MATCH_URL",
            "DACHAO_MATCH_URL",
            "DaChao_MATCH_BASE",
            "DACHAO_MATCH_BASE",
            "DaChao_MATCH_URLS",
            "DACHAO_MATCH_URLS",
            default=DAILY_MATCH_DEFAULT_PATH,
        )
    )
    match_base = match_bases[0]
    match_rounds = env_int("DaChao_MATCH_ROUNDS", "DACHAO_MATCH_ROUNDS", default=5, minimum=1, maximum=10)
    configured_match_scores = env_int_list("DaChao_MATCH_SCORES", "DACHAO_MATCH_SCORES")
    display_match_scores = configured_match_scores or default_scores_for_match_base(match_base)
    lottery_max_draws = env_int("DaChao_LOTTERY_MAX_DRAWS", "DACHAO_LOTTERY_MAX_DRAWS", default=5, minimum=1, maximum=20)
    if read_enabled and not (ocr_server or "").strip():
        print("[配置] 未设置 DaChao_OCR_SERVER，阅读滑块 OCR 将失败；请在青龙环境变量配置你的 OCR 服务地址")

    print(f"[大潮登录] 共 {len(accounts)} 个账号")
    print(
        "[配置] "
        f"签到={'开' if sign_enabled else '关'} "
        f"对对碰={'开' if match_enabled else '关'} "
        f"阅读={'开' if read_enabled else '关'} "
        f"视频={'开' if video_enabled else '关'} "
        f"抽奖={'开' if lottery_enabled else '关'} "
        f"红包={'开' if claim_enabled else '关'} "
        f"通知={'开' if qinglong_notify_enabled() else '关'} "
        f"DEBUG={'开' if debug_enabled else '关'}"
    )
    if debug_enabled:
        print(
            "[手动开关] "
            f"DEBUG={MANUAL_DEBUG}  "
            f"MATCH={MANUAL_ENABLE_MATCH}  "
            f"READ={MANUAL_ENABLE_READ}  "
            f"SIGN={MANUAL_ENABLE_SIGN}  "
            f"LOTTERY={MANUAL_ENABLE_LOTTERY}  "
            f"CLAIM={MANUAL_ENABLE_CLAIM}  "
            f"VIDEO={MANUAL_ENABLE_VIDEO}  "
            f"READ_ID={MANUAL_READ_ACTIVITY_ID or '-'}  "
            f"READ_DISCOVER={MANUAL_READ_DISCOVER}  "
            f"MATCH_URL={MANUAL_MATCH_URL or '-'}"
        )
        print("[DEBUG] 已开启：详细日志 + SHOW_TOKEN + SAVE_SESSION + GET_MEMBER")
        debug_print(
            f"read_activity_id={read_activity_id}  "
            f"sign_activity_id={sign_activity_id}  "
            f"lottery_id={configured_lottery_id or '-'}  "
            f"match_bases={match_bases}  "
            f"ocr={ocr_server}"
        )
        if configured_read_activity_id:
            print(f"[阅读] 预配置活动ID={configured_read_activity_id}")
        elif read_enabled:
            print(f"[阅读] 未预配置活动ID，动态发现={'开启' if read_discover_enabled else '关闭'}")
        if read_enabled:
            try:
                ocr_display = normalize_slide_ocr_base_url(ocr_server) or "未配置"
            except RuntimeError as exc:
                ocr_display = f"{ocr_server or '未配置'}（不兼容: {exc}）"
            print(
                f"[配置] 阅读上限={read_max_articles}  间隔={read_delay}s  "
                f"慢点重试={read_retry_times}次/{read_retry_delay}s  "
                f"OCR重试={ocr_retry_times}次  tn_x范围={ocr_min_x}~{ocr_max_x}  "
                f"OCR={ocr_display}  回退={ocr_fallback_server or '-'}"
            )
        if match_enabled:
            activity_labels = []
            for base in match_bases:
                name = daily_match_activity_name(base)
                scores = configured_match_scores or default_scores_for_match_base(base)
                if is_daily_match_fans(base) and not configured_match_scores:
                    score_text = f"{scores[0]}x{match_rounds}"
                else:
                    score_text = ",".join(str(item) for item in scores[:match_rounds])
                activity_labels.append(f"{name}({score_text})")
            print(f"[配置] 对对碰活动={' | '.join(activity_labels)}")
            print(f"[配置] 对对碰目录={', '.join(match_bases)}")

    account_count = len(accounts)
    auto_threads = min(16, max(1, account_count))
    if MANUAL_THREADS is not None:
        try:
            configured_threads = max(1, int(MANUAL_THREADS))
        except (TypeError, ValueError):
            configured_threads = auto_threads
        thread_source = "manual"
    else:
        raw_threads = env_first("DaChao_THREADS", "DACHAO_THREADS", default="").strip()
        if raw_threads:
            try:
                configured_threads = max(1, int(raw_threads))
                thread_source = "env"
            except ValueError:
                configured_threads = auto_threads
                thread_source = "auto"
        else:
            # 未配置 DaChao_THREADS：按账号数自动并发，无需再写环境变量
            configured_threads = auto_threads
            thread_source = "auto"
    configured_threads = min(16, max(1, configured_threads))
    thread_workers = min(account_count, configured_threads)
    if thread_source == "auto":
        thread_label = "自动=账号数"
    elif thread_source == "env":
        thread_label = "环境变量"
    else:
        thread_label = "手动开关"
    locked_print(
        f"[配置] 并发线程={thread_workers}（{thread_label}"
        + (f" 配置{configured_threads}" if configured_threads != thread_workers else "")
        + (" 串行" if thread_workers == 1 else " 多账号并行")
        + ")"
    )

    results: list[dict[str, Any] | None] = [None] * len(accounts)
    notify_buckets: list[list[str]] = [[] for _ in accounts]

    def run_one_account(index: int, raw_account: str) -> dict[str, Any]:
        """单账号完整流程；返回 {ok, result?, notify_lines}。"""
        account_notify: list[str] = []
        account_logs: list[str] = []

        def alog(*args: Any) -> None:
            """账号内日志先缓存，结束时整块输出，避免多账号交错。"""
            account_logs.append(" ".join(str(a) for a in args))

        def flush_account_logs() -> None:
            if not account_logs:
                return
            locked_print("\n".join(account_logs))
            account_logs.clear()

        # 每账号独立阅读活动 ID，避免并发互相覆盖
        account_read_activity_id = configured_read_activity_id
        account_read_activity_source = "manual_or_env" if configured_read_activity_id else ""

        account_label = f"账号{index}"
        try:
            mobile, password, account_wechat_member = parse_account(raw_account)
            account_label = mask(mobile)
            client = DachaoClient()
            alog(f"========== 账号 {index} {account_label} ==========")
            alog(f"[登录] {account_label}")
            # 并发时先提示开始，便于知道谁在跑
            locked_print(f"[账号{index}] 开始 {account_label}")
            result = client.login(mobile, password)
        except Exception as exc:
            alog(f"[失败] {exc}")
            flush_account_logs()
            account_notify = [f"【{index}】{account_label}", f"  · 失败: {exc}", ""]
            return {"index": index, "ok": False, "result": None, "notify_lines": account_notify}

        member: dict[str, Any] | None = None
        task_summaries: list[str] = []
        drawn_lottery_ids: set[str] = set()
        match_lottery_id = ""
        read_lottery_id = ""

        if needs_member:
            try:
                member = client.get_aihoge_member(result)
                result["aihogeMember"] = member
                debug_print(f"member token={mask(member.get('token', ''), 6, 6)}")
                if get_member and not (sign_enabled or read_enabled or lottery_enabled):
                    task_summaries.append("业务 token: 已获取")
            except Exception as exc:
                alog(f"[业务] member token 获取失败: {exc}")
                task_summaries.append(f"业务 token: 失败 {short_text(exc, 30)}")


        account_video_lottery_ids: list[tuple[int, str]] = []
        if video_enabled:
            try:
                video_res = client.run_aged_video_task(
                    result,
                    drama_id=video_drama_id,
                    target_seconds=video_target_seconds,
                    report_seconds=video_report_seconds,
                    progress=progress_print,
                    member=member,
                )
                result["agedVideo"] = video_res
                watched = video_res.get("watched_seconds", 0)
                remaining = video_res.get("remaining_seconds", 0)
                verified = video_res.get("verified_watched_seconds", 0)
                alog(
                    f"[视频] 初始{watched}s 需补{remaining}s → "
                    f"完成{verified}/{video_res.get('target_seconds', video_target_seconds)}s "
                    f"等待{float(video_res.get('waited_seconds') or 0):.0f}s"
                )
                tier_summaries: list[str] = []
                lottery_id_set = set(video_res.get("lottery_ids") or [])
                for tier in video_res.get("tiers") or []:
                    if tier.get("claim_success"):
                        status = "领取成功"
                    elif tier.get("already_claimed") or tier.get("claim_verified_by_remain"):
                        status = "今日已领取/已有次数"
                    elif tier.get("reached") and (tier.get("lottery_ready_by_duration") or tier.get("soft_raffle")):
                        status = "时长已达标(可抽奖)"
                    elif tier.get("reached"):
                        status = f"领取失败({short_text(tier.get('claim_error'), 18)})"
                    else:
                        status = "未达到"
                    tier_summaries.append(f"{tier.get('minutes')}分{status}")
                    extra = ""
                    if is_debug_enabled():
                        extra = f" index={tier.get('claim_index')}"
                        if tier.get("claim_attempts"):
                            extra += f" tries={len(tier.get('claim_attempts') or [])}"
                    alog(f"[视频] {tier.get('minutes')}分钟 {status}{extra}")
                    if is_debug_enabled() and not tier.get("claim_success") and not tier.get("already_claimed"):
                        for att in (tier.get("claim_attempts") or [])[:6]:
                            alog(
                                f"[视频DEBUG] {tier.get('minutes')}分 index={att.get('index')} "
                                f"hdr={att.get('headers') or '-'} "
                                f"err={short_text(att.get('error'), 36)} "
                                f"resp={short_text(att.get('preview'), 140)}"
                            )
                if lottery_enabled and member is not None:
                    for tier in video_res.get("tiers") or []:
                        lottery_id = str(tier.get("lottery_id") or "")
                        if not lottery_id or not tier.get("reached"):
                            continue
                        if lottery_id not in lottery_id_set:
                            lottery_id_set.add(lottery_id)
                        try:
                            remain = client.lottery_remaining_counts(result, member, lottery_id)
                            tier["lottery_remain_counts"] = remain
                            if remain > 0:
                                tier["claim_verified_by_remain"] = True
                                if is_debug_enabled():
                                    alog(f"[视频] {tier.get('minutes')}分钟 已有抽奖次数={remain}")
                        except Exception as exc:
                            tier["lottery_check_error"] = str(exc)
                account_video_lottery_ids = [
                    (int(tier["minutes"]), str(tier["lottery_id"]))
                    for tier in video_res.get("tiers") or []
                    if tier.get("lottery_id") in lottery_id_set
                ]
                task_summaries.append(f"视频: {', '.join(tier_summaries) or '无目标档位'}")
            except Exception as exc:
                alog(f"[视频] 失败: {exc}")
                task_summaries.append(f"视频: 失败 {short_text(exc, 30)}")

        if sign_enabled:
            if member is None:
                alog("[签到] 跳过: 缺少 member token")
                task_summaries.append("签到: 跳过")
            else:
                try:
                    sign_res = client.act_sign(result, member, sign_activity_id, sign_limit_id)
                    result["actSign"] = sign_res
                    if not client.act_sign_token_ok(sign_res):
                        raise RuntimeError(f"actSign 失败: {json.dumps(sign_res, ensure_ascii=False)[:500]}")
                    sign_msg = sign_res.get("error_message") or sign_res.get("message") or "OK"
                    alog(f"[签到] 业务 token 有效: {sign_msg}")
                    task_summaries.append(f"签到: {sign_msg}")
                except Exception as exc:
                    alog(f"[签到] 失败: {exc}")
                    task_summaries.append(f"签到: 失败 {short_text(exc, 30)}")

        match_lottery_ids: list[str] = []
        if match_enabled:
            daily_matches: list[dict[str, Any]] = []
            for current_match_base in match_bases:
                activity_name = daily_match_activity_name(current_match_base)
                try:
                    match_res = client.run_daily_match(
                        result,
                        max_rounds=match_rounds,
                        score_sequence=configured_match_scores or None,
                        match_base=current_match_base,
                    )
                    daily_matches.append(match_res)
                    result["dailyMatch"] = match_res  # 兼容旧字段：最后一次
                    result["dailyMatches"] = daily_matches
                    current_lottery = str(match_res.get("lottery_id") or "")
                    if current_lottery:
                        if current_lottery not in match_lottery_ids:
                            match_lottery_ids.append(current_lottery)
                        if not match_lottery_id:
                            match_lottery_id = current_lottery
                    completed_score = int(match_res.get("completed_score") or 0)
                    alog(
                        f"[对对碰/{activity_name}] 成绩={completed_score} "
                        f"新提交={match_res.get('success_scores', 0)} "
                        f"状态={match_res.get('stop_status')}"
                    )
                    if is_debug_enabled():
                        before_state_text = format_match_page_state(match_res.get("page_state_before") or {})
                        after_state_text = format_match_page_state(match_res.get("page_state_after") or {})
                        if before_state_text or after_state_text:
                            alog(
                                f"[对对碰/{activity_name}] 页面状态="
                                f"{before_state_text or '读取失败'} -> {after_state_text or '读取失败'}"
                            )
                        start_res = match_res.get("start") or {}
                        if start_res:
                            start_msg = start_res.get("msg") or start_res.get("message") or ""
                            alog(
                                f"[对对碰/{activity_name}] 初始化状态="
                                f"{start_res.get('status')} {short_text(start_msg, 32)}".rstrip()
                            )
                        score_status = format_match_score_status(match_res.get("score_results") or [])
                        if score_status:
                            alog(f"[对对碰/{activity_name}] 分数状态={score_status}")
                        alog(f"[对对碰/{activity_name}] 活动目录={match_res.get('match_base')}")
                        if current_lottery:
                            alog(f"[对对碰/{activity_name}] 抽奖ID={current_lottery}")
                    if completed_score:
                        task_summaries.append(
                            f"对对碰/{activity_name}: 已完成{completed_score}/"
                            f"新提交{match_res.get('success_scores', 0)}"
                        )
                    else:
                        task_summaries.append(
                            f"对对碰/{activity_name}: {match_res.get('success_scores', 0)}次/"
                            f"状态{match_res.get('stop_status')}"
                        )
                except Exception as exc:
                    alog(f"[对对碰/{activity_name}] 失败: {exc}")
                    task_summaries.append(f"对对碰/{activity_name}: 失败 {short_text(exc, 30)}")

        def run_lottery_task(lottery_id: str, label: str, limit_id: str = "") -> dict[str, Any]:
            """执行一次抽奖；返回 {label, awards, tip, message} 便于汇总。"""
            empty = {"label": label, "awards": [], "tip": "", "message": ""}
            if not lottery_enabled or not lottery_id:
                return empty
            if lottery_id in drawn_lottery_ids:
                return empty
            if member is None:
                alog(f"[{label}] 跳过: 缺少 member token")
                task_summaries.append(f"{label}: 跳过")
                return {**empty, "tip": "跳过"}
            drawn_lottery_ids.add(lottery_id)
            try:
                lottery_res = client.run_lottery(
                    result,
                    member,
                    lottery_id,
                    max_draws=lottery_max_draws,
                    limit_id=limit_id,
                )
                result.setdefault("lotteries", []).append({"label": label, **lottery_res})
                title = short_text(lottery_res.get("title") or lottery_id, 22)
                message = str(lottery_res.get("message") or "OK")
                draws = lottery_res.get("draws") or []
                awards: list[str] = []
                for dr in draws:
                    if not isinstance(dr, dict):
                        continue
                    nested = dr.get("response") if isinstance(dr.get("response"), dict) else {}
                    award = str(
                        dr.get("award_name")
                        or dr.get("prize_content")
                        or nested.get("award_name")
                        or nested.get("prize_content")
                        or ""
                    ).strip()
                    if award and award not in awards:
                        awards.append(award)
                # 接口有时把奖品只写在 message 里（如 15积分）
                if not awards:
                    msg_s = message.strip()
                    if any(k in msg_s for k in ("积分", "元", "红包", "券", "币")) and not any(
                        k in msg_s for k in ("结束", "关注", "无可用", "次数", "失败")
                    ):
                        awards.append(msg_s)
                award_text = "、".join(short_text(a, 18) for a in awards[:5])
                remain = lottery_res.get("remain_counts", 0)
                try:
                    remain_n = int(remain or 0)
                except (TypeError, ValueError):
                    remain_n = 0
                end_like = any(
                    k in message for k in ("已结束", "活动结束", "敬请关注", "无可用", "没有抽奖", "次数不足")
                )
                if award_text:
                    tip = f"获得:{award_text}"
                elif draws:
                    tip = f"结果:{short_text(message, 20)}"
                elif remain_n <= 0:
                    tip = "已抽完" if end_like else "无次数"
                else:
                    tip = short_text(message, 20)

                if is_debug_enabled():
                    alog(
                        f"[{label}] {title} 次数={remain_n} 抽={len(draws)} "
                        f"status={lottery_res.get('status') or '-'} {tip}"
                    )
                else:
                    # 正常模式：突出获得；无奖品时短提示，不刷长活动名
                    if award_text:
                        alog(f"[{label}] 获得:{award_text}")
                    else:
                        alog(f"[{label}] {tip}")

                task_summaries.append(
                    f"{label}: {award_text}" if award_text else f"{label}: {tip}"
                )
                return {"label": label, "awards": awards, "tip": tip, "message": message}
            except Exception as exc:
                alog(f"[{label}] 失败: {exc}")
                task_summaries.append(f"{label}: 失败 {short_text(exc, 30)}")
                return {**empty, "tip": f"失败 {short_text(exc, 20)}"}

        video_lottery_hits: list[str] = []
        video_lottery_done = 0
        for minutes, lottery_id in account_video_lottery_ids:
            lr = run_lottery_task(lottery_id, f"视频{minutes}分抽奖")
            video_lottery_done += 1
            if lr.get("awards"):
                video_lottery_hits.append(
                    f"{minutes}分:" + "、".join(short_text(a, 14) for a in lr["awards"][:3])
                )
        if account_video_lottery_ids:
            if video_lottery_hits:
                alog(f"[视频抽奖汇总] 获得 {'；'.join(video_lottery_hits)}")
            elif video_lottery_done:
                alog(f"[视频抽奖汇总] {video_lottery_done}档均无新中奖（已抽完/无次数）")
        if configured_lottery_id:
            run_lottery_task(configured_lottery_id, "抽奖")
        elif match_lottery_ids:
            for idx, lottery_id in enumerate(match_lottery_ids):
                label = "对对碰抽奖" if len(match_lottery_ids) == 1 else f"对对碰抽奖{idx + 1}"
                run_lottery_task(lottery_id, label)
        elif match_lottery_id:
            run_lottery_task(match_lottery_id, "对对碰抽奖")

        if read_enabled:
            if member is None:
                alog("[阅读] 跳过: 缺少 member token")
                task_summaries.append("阅读: 跳过")
            else:
                try:
                    current_read_activity_id = configured_read_activity_id
                    current_read_source = "manual_or_env" if configured_read_activity_id else ""
                    if not current_read_activity_id and read_discover_enabled:
                        try:
                            if is_debug_enabled():
                                alog("[阅读] buoy/list 动态发现活动中")
                            discovered = client.discover_read_activity_id(
                                result,
                                progress=progress_print,
                            )
                            current_read_activity_id = str(discovered.get("activity_id") or "").strip()
                            current_read_source = str(discovered.get("source") or "buoy/list")
                            if current_read_activity_id:
                                if is_debug_enabled():
                                    alog(
                                        f"[阅读] 活动ID={current_read_activity_id} "
                                        f"来源={current_read_source}"
                                    )
                                else:
                                    alog(f"[阅读] 活动ID={current_read_activity_id}")
                            else:
                                alog(f"[阅读] 动态发现失败: {discovered.get('message') or '无候选'}")
                        except Exception as discover_exc:
                            alog(f"[阅读] 动态发现异常: {discover_exc}")
                    if not current_read_activity_id:
                        current_read_activity_id = AIHOGE_DEFAULT_READ_ACTIVITY_ID
                        current_read_source = "default_constant"
                        alog(f"[阅读] 回退默认活动ID={current_read_activity_id}")
                    elif configured_read_activity_id or not read_discover_enabled:
                        if is_debug_enabled():
                            alog(
                                f"[阅读] 活动ID={current_read_activity_id} "
                                f"来源={current_read_source or '-'}"
                            )
                        else:
                            alog(f"[阅读] 活动ID={current_read_activity_id}")
                    account_read_activity_id = current_read_activity_id
                    account_read_activity_source = current_read_source

                    if is_debug_enabled():
                        alog("[阅读] 滑块验证中")
                    read_res = client.run_read_articles(
                        result,
                        member,
                        activity_id=current_read_activity_id,
                        ocr_server=ocr_server,
                        ocr_fallback_server=ocr_fallback_server,
                        max_articles=read_max_articles,
                        read_delay=read_delay,
                        throttle_retry_delay=read_retry_delay,
                        throttle_retry_times=read_retry_times,
                        throttle_stop_count=read_throttle_stop,
                        ocr_retry_times=ocr_retry_times,
                        ocr_min_x=ocr_min_x,
                        ocr_max_x=ocr_max_x,
                        progress=progress_print,
                    )
                    result["readArticles"] = read_res
                    read_lottery_id = str(read_res.get("draw_activity_id") or "")
                    for read_item in read_res.get("results") or []:
                        title = short_text(read_item.get("title"), 24)
                        if read_item.get("error"):
                            alog(f"[阅读] {title}: 失败 {short_text(read_item.get('error'), 36)}")
                        elif is_debug_enabled():
                            response = read_item.get("response") or {}
                            msg = response.get("error_message") or response.get("message") or response.get("success")
                            alog(f"[阅读] {title}: {msg}")
                        else:
                            response = read_item.get("response") or {}
                            if not DachaoClient.is_read_success_response(response):
                                msg = (
                                    response.get("error_message")
                                    or response.get("message")
                                    or response.get("success")
                                )
                                alog(f"[阅读] {title}: {msg}")
                    done_count = read_res.get("success", 0)
                    total_count = len(read_res.get("results") or [])
                    alog(f"[阅读] 成功 {done_count}/{total_count}（共{read_res.get('total_items', 0)}篇）")
                    if read_res.get("stopped_message"):
                        alog(f"[阅读] {read_res.get('stopped_message')}")
                    if is_debug_enabled():
                        if read_lottery_id:
                            alog(f"[阅读] 抽奖ID={read_lottery_id}")
                        alog(f"[阅读] 活动来源={account_read_activity_source or '-'}")
                    task_summaries.append(f"阅读: {done_count}/{total_count}")
                except Exception as exc:
                    alog(f"[阅读] 失败: {exc}")
                    task_summaries.append(f"阅读: 失败 {short_text(exc, 30)}")

        run_lottery_task(read_lottery_id, "阅读抽奖", limit_id=account_read_activity_id)
        if lottery_enabled and not drawn_lottery_ids and not configured_lottery_id and not match_lottery_id:
            run_lottery_task(AIHOGE_DEFAULT_LOTTERY_ID, "抽奖")

        if claim_enabled:
            wechat_member = account_wechat_member or global_wechat_member
            # 抽中红包后列表偶发延迟，稍等再查
            if drawn_lottery_ids:
                time.sleep(2 + random.random())
            try:
                claim_res = client.run_claim_redpackets(
                    result,
                    member,
                    wechat_member=wechat_member,
                    limit_id=account_read_activity_id or match_lottery_id or configured_lottery_id,
                    lottery_id=read_lottery_id or match_lottery_id or configured_lottery_id,
                )
                result["redPackets"] = claim_res
                prizes = claim_res.get("prizes") or []
                other_prizes = claim_res.get("other_prizes") or []
                cash_notify_lines: list[str] = []
                msg = str(claim_res.get("message") or "无可领取红包")
                # 正常模式不刷微信token；有现金红包或 DEBUG 时再提示
                if is_debug_enabled() or prizes:
                    token_flag = "有" if claim_res.get("has_wechat_member") else "无"
                    alog(f"[红包] {msg}  微信token={token_flag}")
                else:
                    alog(f"[红包] {msg}")
                for item in prizes:
                    content = str(item.get("prize_content") or "")
                    content_short = short_text(content, 24)
                    link = str(item.get("link") or "").strip()
                    if not link and item.get("code"):
                        link = client.redpacket_claim_link(str(item.get("code")))
                        item["link"] = link
                    is_cash = is_cash_redpacket_text(content)
                    if item.get("result") == "claimed":
                        alog(f"[红包] 领取成功: {content_short}")
                    elif item.get("result") == "link_only":
                        alog(f"[红包] 待领取: {content_short}")
                        if link:
                            alog(f"[红包] 提现: {link}")
                    else:
                        emsg = item.get("message") or item.get("result")
                        alog(f"[红包] {content_short}: {emsg}")
                        if link and is_cash:
                            alog(f"[红包] 提现: {link}")
                        elif is_debug_enabled() and link:
                            alog(f"[红包] 链接: {link}")
                    if is_cash and link:
                        status_tag = {
                            "claimed": "已领",
                            "link_only": "待领",
                            "failed": "失败",
                            "error": "异常",
                        }.get(str(item.get("result") or ""), str(item.get("result") or "待领"))
                        cash_notify_lines.append(f"现金红包[{status_tag}] {content_short}")
                        cash_notify_lines.append(f"提现: {link}")
                if is_debug_enabled() and other_prizes and prizes:
                    for op in other_prizes[:5]:
                        alog(f"[奖品] {short_text(op.get('prize_content'), 24)}")
                if prizes:
                    task_summaries.append(
                        f"红包: 成功{claim_res.get('claimed', 0)}/{len(prizes)}"
                        if claim_res.get("has_wechat_member")
                        else f"红包: 待领{len(prizes)}"
                    )
                else:
                    # 推送摘要里也带积分文案
                    task_summaries.append(f"奖品: {short_text(msg, 28)}")
                if cash_notify_lines:
                    result["_cash_notify_lines"] = cash_notify_lines
            except Exception as exc:
                alog(f"[红包] 失败: {exc}")
                task_summaries.append(f"红包: 失败 {short_text(exc, 30)}")

        mobile_m = mask(result["mobile"])
        nick = str(result.get("nickName") or "").strip()
        # 昵称与脱敏手机号相同时不重复
        if nick and nick not in {mobile_m, str(result.get("mobile") or "")}:
            alog(f"[成功] {nick} {mobile_m}")
            head = f"【{index}】{mobile_m} {nick}"
        else:
            alog(f"[成功] {mobile_m}")
            head = f"【{index}】{mobile_m}"

        account_notify = [head]
        for item in task_summaries:
            account_notify.append(f"  · {item}")
        cash_lines = result.get("_cash_notify_lines") or []
        for cash in cash_lines:
            account_notify.append(f"  · {cash}")
        account_notify.append("")  # 账号之间空行，推送更清晰

        if show_token or is_debug_enabled():
            sid = result["sessionId"] if show_token else mask(result["sessionId"], 6, 6)
            aid = result["accountId"] if show_token else mask(result["accountId"], 6, 6)
            alog(f"sessionId={sid}")
            alog(f"accountId={aid}")
        flush_account_logs()
        locked_print(f"[账号{index}] 完成 {mobile_m}")
        return {"index": index, "ok": True, "result": result, "notify_lines": account_notify}

    if thread_workers == 1:
        for index, raw_account in enumerate(accounts, 1):
            outcome = run_one_account(index, raw_account)
            idx0 = outcome["index"] - 1
            notify_buckets[idx0] = list(outcome.get("notify_lines") or [])
            if outcome.get("result") is not None:
                results[idx0] = outcome["result"]
    else:
        with ThreadPoolExecutor(max_workers=thread_workers, thread_name_prefix="dachao") as pool:
            futures = {
                pool.submit(run_one_account, index, raw_account): index
                for index, raw_account in enumerate(accounts, 1)
            }
            for fut in as_completed(futures):
                index = futures[fut]
                try:
                    outcome = fut.result()
                except Exception as exc:
                    locked_print(f"[失败] 账号 {index} 未捕获异常: {exc}")
                    outcome = {
                        "index": index,
                        "ok": False,
                        "result": None,
                        "notify_lines": [f"账号{index} 失败: {exc}"],
                    }
                idx0 = outcome["index"] - 1
                notify_buckets[idx0] = list(outcome.get("notify_lines") or [])
                if outcome.get("result") is not None:
                    results[idx0] = outcome["result"]

    ordered_results = [item for item in results if item is not None]
    notify_lines = [line for bucket in notify_buckets for line in bucket]

    if save_session and ordered_results:
        out = save_sessions(ordered_results)
        locked_print(f"\n[保存] 登录结果已写入 {out}")

    success = len(ordered_results)
    summary = f"成功 {success}/{len(accounts)}"
    locked_print(f"\n[汇总] {summary}")
    notify_content = "\n".join([summary, *notify_lines]).strip()
    qinglong_notify(SCRIPT_NAME, notify_content)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
