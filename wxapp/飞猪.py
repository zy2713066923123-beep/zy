"""
name: 飞猪签到
入口: 飞猪微信小程序
功能: 飞猪里程每日签到
变量: 自动从 yyb_go 同步存活账号（与其他脚本一致，无需单独配置 YYB_SERVER）
定时: 每天一次
cron: 16 8 * * *
依赖: requests, yyb
------------更新日志------------
2026/8/21 V1.0 基于微信小程序 HAR 初始化，接入 YYB-Go-Enhanced 多账号取码
2026/8/21 V1.1 修正飞猪登录成功码为 3，增加登录凭据完整性校验
2026/8/21 V1.2 按 HAR 包装 wrapperCode，补齐普通账号登录参数
2026/8/28 V1.3 改用统一 yyb 模块拉取账号与取码（与其他脚本一致）
"""

import hashlib
import json
import os
import random
import sys
import time
import uuid
from typing import Any, Dict, Iterator, Optional

import requests
import yyb  # 自动同步 yyb_go 存活账号（与其他脚本一致）

# 将脚本所在目录加入搜索路径（确保能找到 yyb.py 等同目录模块）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


APP_ID = "wx6a96c49f29850eb5"
APP_KEY = "12574478"
LOGIN_URL = "https://passport.feizhu.com/mini_program/login.do"
MTOP_BASE = "https://acs-m.feizhu.com/h5"
MILEAGE_GET_API = "mtop.fliggy.ffatouch.mileage.channel.v2024.get"
MILEAGE_SIGN_API = "mtop.fliggy.ffatouch.mileage.channel.v2024.clickcollect"
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.75 NetType/WIFI Language/zh_CN"
)


class FliggyTask:
    def __init__(self) -> None:
        self.logs = []
        self.success_count = 0
        self.failed_count = 0

    def log(self, message: str) -> None:
        print(message)
        self.logs.append(message)

    def accounts(self) -> Iterator[Dict[str, Any]]:
        """从 yyb_go 拉取存活账号（统一使用 yyb.load_accounts）"""
        try:
            accounts = yyb.load_accounts()
        except Exception as exc:
            self.log(f"❌ 拉取 yyb_go 账号失败：{exc}")
            return
        if not accounts:
            self.log("❌ 未获取到任何在线账号，请确认 yyb_go 服务已配置且有存活账号")
            return
        self.log(f"✅ 从 yyb_go 同步到 {len(accounts)} 个存活账号")
        for acc in accounts:
            yield acc

    def get_wx_code(self, account: Dict[str, Any]) -> Optional[str]:
        ref = str(account.get("id") or account.get("openid") or account.get("wxid") or "")
        if not ref:
            self.log("❌ 账号缺少 id/openid/wxid，无法取码")
            return None
        code = yyb.get_single_code(APP_ID, ref)
        if not code:
            self.log("❌ 获取微信 code 失败")
            return None
        self.log("✅ 获取微信 code 成功")
        return code

    def new_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh-Hans;q=0.9",
                "Origin": "https://proxy.feizhu.com",
                "Referer": f"https://servicewechat.com/{APP_ID}/475/page-frame.html",
            }
        )
        return session

    def login(self, session: requests.Session, code: str) -> bool:
        authorization = json.dumps(
            {"authorizationCode": code}, ensure_ascii=False, separators=(",", ":")
        )
        payload = {
            "appEntrance": "weixin",
            "appId": "undefined",
            "appName": "trip",
            "authorizationCode": authorization,
            "bizPassParams": "undefined",
            "isMobile": "true",
            "lang": "zh_CN",
            "needPassWebViewCookie": "false",
            "pageTraceId": str(uuid.uuid4()),
            "returnUrl": "",
            "sellerAppId": "",
            "type": "weixin_mini_program",
        }
        try:
            response = session.post(LOGIN_URL, data=payload, timeout=20)
            response.raise_for_status()
            body = response.json()
            content = body.get("content") or {}
            data = content.get("data") or {}
            if body.get("hasError") or not content.get("success") or data.get("resultCode") != 100:
                self.log(
                    "❌ 飞猪登录失败："
                    f"hasError={body.get('hasError')}，"
                    f"contentSuccess={content.get('success')}，"
                    f"contentStatus={content.get('status')}，"
                    f"resultCode={data.get('resultCode')}"
                )
                return False

            if not data.get("cookie2") or not data.get("sgcookie"):
                if data.get("redirect") is True:
                    self.log("❌ 飞猪账号需要在微信小程序内完成手机号绑定后再运行")
                else:
                    self.log("❌ 飞猪登录响应缺少 cookie2 或 sgcookie")
                return False

            cookie_map = {
                "cookie2": data.get("cookie2"),
                "sgcookie": data.get("sgcookie"),
                "sid": data.get("sid"),
                "csg": data.get("csg"),
                "unb": data.get("unb"),
                "munb": data.get("munb"),
            }
            for name, value in cookie_map.items():
                if value is not None and value != "":
                    session.cookies.set(name, str(value), domain=".feizhu.com")
                    session.cookies.set(name, str(value), domain=".taobao.com")
            if data.get("sgcookie"):
                session.headers["sgcookie"] = str(data["sgcookie"])
            if data.get("unb"):
                session.headers["x-uid"] = str(data["unb"])
            self.log("✅ 飞猪登录成功")
            return True
        except Exception as exc:
            self.log(f"❌ 飞猪登录异常：{exc}")
            return False

    @staticmethod
    def token_from_cookie(session: requests.Session) -> str:
        token_cookie = session.cookies.get("_m_h5_tk") or ""
        return token_cookie.split("_", 1)[0]

    def mtop_request(
        self, session: requests.Session, api: str, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        data_text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        url = f"{MTOP_BASE}/{api.lower()}/1.0/"
        last_body: Optional[Dict[str, Any]] = None
        for attempt in range(2):
            timestamp = str(int(time.time() * 1000))
            token = self.token_from_cookie(session)
            sign_source = f"{token}&{timestamp}&{APP_KEY}&{data_text}"
            sign = hashlib.md5(sign_source.encode("utf-8")).hexdigest()
            params = {
                "jsv": "2.7.2",
                "appKey": APP_KEY,
                "t": timestamp,
                "sign": sign,
                "api": api,
                "v": "1.0",
                "type": "originaljson",
                "dataType": "json",
                "ttid": "2022@travel_h5_1.0.0",
                "data": data_text,
            }
            try:
                response = session.get(url, params=params, timeout=20)
                response.raise_for_status()
                last_body = response.json()
            except Exception as exc:
                self.log(f"❌ MTop 请求异常：{exc}")
                return None

            ret = last_body.get("ret") or []
            ret_text = " ".join(str(item) for item in ret)
            if any(key in ret_text for key in ("TOKEN_EMPTY", "TOKEN_EXPIRED", "FAIL_SYS_TOKEN")):
                if attempt == 0 and self.token_from_cookie(session):
                    continue
            return last_body
        return last_body

    @staticmethod
    def is_mtop_success(body: Optional[Dict[str, Any]]) -> bool:
        if not body:
            return False
        return any(str(item).startswith("SUCCESS::") for item in body.get("ret") or [])

    def sign_in(self, session: requests.Session) -> bool:
        page = self.mtop_request(session, MILEAGE_GET_API, {"channel": "WX"})
        if not self.is_mtop_success(page):
            ret = (page or {}).get("ret") or []
            self.log(f"❌ 查询签到状态失败：{' '.join(map(str, ret))}")
            return False

        page_data = (page or {}).get("data") or {}
        sign_module = page_data.get("signInDataModule") or {}
        today = sign_module.get("signInDetailTodayInfoVO") or {}
        if today.get("signInStatus") is True:
            self.log(
                f"✅ 今日已签到，连续 {today.get('continuousDays', 0)} 天，"
                f"累计 {today.get('cumulativeDays', 0)} 天"
            )
            return True

        bubble_module = page_data.get("bubbleDataModule") or {}
        bubbles = bubble_module.get("bubbleList") or []
        bubble = bubbles[0] if bubbles else {}
        static_data = page_data.get("staticDataModule") or {}
        nodes = ((static_data.get("tbCashConfig") or {}).get("actNodeInfos") or [])
        asac = nodes[0].get("asac", "") if nodes else ""
        mileage = today.get("mileage")
        if mileage is None:
            mileage = ((bubble.get("mileageUiConfig") or {}).get("extraParams") or {}).get(
                "signInType", 1
            )
        payload = {
            "taoCash": False,
            "doubleMileage": False,
            "channel": "WX",
            "sceneId": bubble_module.get("sceneId"),
            "clickType": 2,
            "playId": sign_module.get("playId") or bubble.get("playId"),
            "taskRecordId": None,
            "currentTimeMillis": int(time.time() * 1000),
            "currentMileage": mileage,
            "asac": asac,
            "issec": "0",
            "isSec": 0,
        }
        if not payload["sceneId"] or not payload["playId"]:
            self.log("❌ 签到页响应缺少 sceneId 或 playId")
            return False

        result = self.mtop_request(session, MILEAGE_SIGN_API, payload)
        if not self.is_mtop_success(result):
            ret = (result or {}).get("ret") or []
            self.log(f"❌ 签到请求失败：{' '.join(map(str, ret))}")
            return False
        result_data = (result or {}).get("data") or {}
        inner = (((result_data.get("clickCollectSignInResult") or {}).get("result")) or {})
        if result_data.get("allSuccess") is True and inner.get("success") is True:
            stats = ((inner.get("resultData") or {}).get("signInStatisticInfo") or {})
            self.log(
                f"✅ 签到成功，连续 {stats.get('continuousDays', 0)} 天，"
                f"累计 {stats.get('cumulativeDays', 0)} 天"
            )
            return True
        self.log(
            "❌ 签到业务结果失败，"
            f"allSuccess={result_data.get('allSuccess')}，success={inner.get('success')}"
        )
        return False

    def notify(self) -> None:
        title = "飞猪签到"
        content = "\n".join(self.logs)
        try:
            from notify import send

            send(title, content)
            self.log("✅ 青龙通知调用完成")
        except Exception as exc:
            self.log(f"⚠️ 青龙通知未发送：{exc}")

    def run(self) -> int:
        self.log("===== 飞猪签到开始 =====")
        account_list = list(self.accounts())
        if not account_list:
            self.failed_count = 1
        for index, account in enumerate(account_list, 1):
            name = account.get("remark") or account.get("nickname") or f"账号{index}"
            self.log(f"\n----- 账号 {index}（{name}） -----")
            session = self.new_session()
            code = self.get_wx_code(account)
            ok = bool(code) and self.login(session, code)
            if ok:
                time.sleep(random.uniform(1, 2))
                ok = self.sign_in(session)
            if ok:
                self.success_count += 1
            else:
                self.failed_count += 1
            time.sleep(random.uniform(1, 2))

        self.log(
            f"\n===== 执行完成：成功 {self.success_count}，失败 {self.failed_count} ====="
        )
        self.notify()
        return 0 if self.failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(FliggyTask().run())
