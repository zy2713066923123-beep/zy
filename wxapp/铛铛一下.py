import getCode  # 自动同步 yyb_go 存活账号
# name: 铛铛一下 (微信协议版)
"""
作者: 临渊
日期: 2025/6/24
name: 铛铛一下 (微信协议版)
入口: 微信小程序
功能: 签到、抽奖
变量: WX_ID 账号配置，格式：wxid/openid#备注，多账号换行 / @ / & 分隔
    WX_SERVER      yyb_go 协议服务地址（例如：http://127.0.0.1:8000）
    PROXY_API_URL (代理api，返回一条txt文本，内容为代理ip:端口)
定时: 一天两次
cron: 4 8,16 * * *
更新日志------------
2025/6/24   V1.0    初始化脚本
2025/6/30   V1.1    修复提现问题
2025/7/7    V1.2    适配更多协议
2025/7/21   V1.3    适配更多协议
2025/7/22   V1.4    修改协议适配器导入方式
2025/7/28   V1.5    修改头部注释，以便拉库
2026/7/7    V2.0    统一使用getCode + notify标准模式
"""

import random
import time
import requests
import os
import traceback


try:
    from notify import send as notify_send
except ImportError:
    def notify_send(title, content):
        print(f"--- 通知 ---\n{title}\n{content}\n-------------")

DEFAULT_WITHDRAW_BALANCE = 0.3  # 默认超过该金额进行提现，需大于等于0.3
MULTI_ACCOUNT_SPLIT = ["\n", "@", "&"]  # 分隔符列表
MULTI_ACCOUNT_PROXY = False  # 是否使用多账号代理，默认不使用，True则使用多账号代理

SCRIPT_NAME = "铛铛一下"
WX_APPID = "wxe378d2d7636c180e"
DEFAULT_WECHAT_SERVER = os.environ.get("WX_SERVER") or os.environ.get("YYB_SERVER") or os.environ.get("WECHAT_SERVER") or "http://127.0.0.1:8000"
HOST = "vues.dd1x.cn"
USER_AGENT = "Mozilla/5.0 (Linux; Android 12; M2012K11AC Build/SKQ1.220303.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.136 Mobile Safari/537.36 XWEB/1340129 MMWEBSDK/20240301 MMWEBID/9871 MicroMessenger/8.0.48.2580(0x28003036) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android"


def log_print(msg, label=""):
    """同时打印和记录日志"""
    line = f"{label}{msg}" if label else msg
    print(line)
    return line


def get_proxy(proxy_url):
    """
    获取代理
    :return: 代理
    """
    if not proxy_url:
        print("[获取代理]没有找到环境变量PROXY_API_URL，不使用代理")
        return None
    response = requests.get(proxy_url, timeout=10)
    proxy = response.text.strip()
    print(f"[获取代理]: {proxy}")
    return proxy


def check_proxy(proxy, session, host):
    """
    检查代理是否可用
    :param proxy: 代理
    :param session: session
    :param host: 主机地址
    :return: 是否可用
    """
    try:
        url = f"http://{host}/api/v2/get_sign_list"
        session.headers["Token"] = ""
        response = session.get(url, timeout=5)
        if response.status_code == 200:
            print(f"[检查代理]: {proxy} 应该可用")
            return True
        else:
            print(f"[检查代理]: {response.text}")
            return False
    except Exception as e:
        return False


def parse_accounts():
    """
    解析环境变量中的账号列表
    :return: 账号列表 [{"id": wxid, "note": 备注}, ...]
    """
    accounts = []
    wx_id_raw = os.getenv("WX_ID", "").strip()
    if not wx_id_raw:
        print("⭕ 未找到环境变量 WX_ID，请设置账号变量")
        return accounts

    for sep in MULTI_ACCOUNT_SPLIT:
        if sep in wx_id_raw:
            items = [x.strip() for x in wx_id_raw.split(sep) if x.strip()]
            break
    else:
        items = [wx_id_raw] if wx_id_raw else []

    for item in items:
        # 处理 key=value 格式兼容
        if "=" in item:
            item = item.split("=", 1)[1].strip()
        # 处理 wxid#备注 格式
        idx = item.rfind("#")
        if idx > 0:
            accounts.append({"id": item[:idx].strip(), "note": item[idx + 1:].strip()})
        else:
            accounts.append({"id": item, "note": ""})

    return accounts


def wxlogin(session, code):
    """
    微信code登录换取token
    :param session: requests session
    :param code: 微信登录code
    :return: (成功与否, 手机号, token或None)
    """
    try:
        url = f"https://{HOST}/wechat/login"
        params = {"code": code, "channelId": 154}
        response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
        response_json = response.json()
        if response_json['code'] == 0:
            tel = response_json['data']['tel']
            tel_masked = tel[:3] + "****" + tel[-4:]
            token = response_json['data']['token']
            session.headers["Token"] = token
            return True, tel_masked, token
        else:
            return False, None, None
    except Exception as e:
        print(f"[登录]发生错误: {e}")
        return False, None, None


def sign_in(session):
    """
    签到
    :param session: session
    :return: (成功与否, 日志消息)
    """
    try:
        url = f"https://{HOST}/api/v2/sign_join"
        response = session.get(url, timeout=15)
        response_json = response.json()
        if response_json['code'] == 0:
            return True, "[签到]: 成功"
        else:
            return False, f"[签到]: {response_json['msg']}"
    except Exception as e:
        return False, f"[签到]发生错误: {e}"


def add_lottery_count(session):
    """
    增加抽奖次数
    :param session: session
    :return: (成功与否, 日志消息)
    """
    try:
        url = f"https://{HOST}/front/activity/add_lottery_count"
        response = session.get(url, timeout=15)
        response_json = response.json()
        if response_json['code'] == 0:
            return True, "[增加抽奖次数]: 成功"
        elif "达到上限" in response_json.get('msg', ''):
            return False, f"[增加抽奖次数]: {response_json['msg']}"
        else:
            return False, f"[增加抽奖次数]错误: {response_json.get('msg', '')}"
    except Exception as e:
        return False, f"[增加抽奖次数]异常: {e}"


def update_lottery_result(session):
    """
    抽奖
    :param session: session
    :return: (成功与否, 日志消息)
    """
    try:
        url = f"https://{HOST}/front/activity/update_lottery_result"
        params = {"id": 3438615}
        response = session.get(url, params=params, timeout=15)
        response_json = response.json()
        if not isinstance(response_json, dict):
            return False, f"[抽奖]: 响应格式异常: {response_json}"
        if response_json.get('code') == 0:
            data = response_json.get('data') or {}
            good_name = data.get('goodName', '未知') if isinstance(data, dict) else '未知'
            return True, f"[抽奖]: 获得{good_name}"
        else:
            return False, f"[抽奖]: {response_json.get('msg', '未知错误')}"
    except Exception as e:
        return False, f"[抽奖]异常: {e}"


def get_withdrawal_trade_list(session):
    """
    获取提现相关数据
    :param session: session
    :return: (余额, 提现数据列表 or None)
    """
    try:
        url = f"https://{HOST}/api/h/get_withdrawal_trade_list"
        response = session.get(url, timeout=15)
        response_json = response.json()
        if isinstance(response_json, dict) and response_json.get('code') == 0:
            data = response_json.get('data') or []
            if isinstance(data, list) and data:
                balance = data[0].get('money')
                return balance, data
            return None, None
        else:
            return None, None
    except Exception as e:
        print(f"[获取提现数据]异常: {e}")
        return None, None


def withdraw(session, balance, withdrawal_trade_list):
    """
    提现
    :param session: session
    :param balance: 余额
    :param withdrawal_trade_list: 提现相关数据
    :return: (成功与否, 日志消息)
    """
    try:
        url = f"https://{HOST}/api/h/withdrawal"
        payload = {
            "totalMoney": balance,
            "type": 1,
            "withdrawalDetailPojoList": withdrawal_trade_list
        }
        response = session.post(url, json=payload, timeout=15)
        response_json = response.json()
        if response_json['code'] == 0:
            return True, f"[提现]: {response_json['msg']}"
        else:
            return False, f"[提现]: {response_json['msg']}"
    except Exception as e:
        return False, f"[提现]异常: {e}"


def run_account(account, index, total, proxy_url):
    """
    执行单个账号的所有任务
    :param account: 账号信息 dict
    :param index: 账号序号
    :param total: 总账号数
    :param proxy_url: 代理API地址
    :return: 日志行列表
    """
    lines = []
    note = account.get("note", "")
    mask = (note[:3] + "*****" + note[-3:]) if len(note) >= 7 else note or f"账号{index}"

    def log(msg):
        lines.append(log_print(msg))

    log(f"------ 【账号{index}】{mask} 开始执行任务 ------")

    # 创建session
    if MULTI_ACCOUNT_PROXY and proxy_url:
        proxy = get_proxy(proxy_url)
        session = requests.Session()
        if proxy:
            session.proxies.update({"http": f"http://{proxy}", "https": f"http://{proxy}"})
            while not check_proxy(proxy, session, HOST):
                proxy = get_proxy(proxy_url)
                session.proxies.update({"http": f"http://{proxy}", "https": f"http://{proxy}"})
    else:
        session = requests.Session()

    session.headers["User-Agent"] = USER_AGENT

    # 获取微信code并登录
    wx_id = account["id"]
    log(f"[登录] 正在获取微信code: {wx_id}")
    try:
        code = get_single_code(WX_APPID, wx_id)
    except Exception as e:
        log(f"[登录] 获取code失败: {e}")
        log(f"------ 【账号{index}】执行任务完成 ------")
        return lines

    if not code:
        log("[登录] 未获取到有效code，可能需要重新扫码登录")
        log(f"------ 【账号{index}】执行任务完成 ------")
        return lines

    time.sleep(random.randint(1, 2))
    ok, tel, _ = wxlogin(session, code)
    if ok:
        log(f"[登录] 成功: 当前账号 {tel}")
    else:
        log("[登录] 失败")
        log(f"------ 【账号{index}】执行任务完成 ------")
        return lines

    time.sleep(random.randint(1, 3))

    # 签到
    sign_ok, sign_msg = sign_in(session)
    log(sign_msg)
    time.sleep(random.randint(1, 3))

    # 抽奖
    lottery_ok, lottery_msg = update_lottery_result(session)
    log(lottery_msg)
    while lottery_ok:
        time.sleep(random.randint(3, 5))
        lottery_ok, lottery_msg = update_lottery_result(session)
        log(lottery_msg)

    # 增加抽奖次数
    add_ok, add_msg = add_lottery_count(session)
    log(add_msg)
    while add_ok:
        l_ok, l_msg = update_lottery_result(session)
        log(l_msg)
        time.sleep(random.randint(3, 5))
        add_ok, add_msg = add_lottery_count(session)
        log(add_msg)

    # 提现相关
    balance, trade_list = get_withdrawal_trade_list(session)
    if balance is not None:
        log(f"[余额]: {balance}元")
        if float(balance) >= DEFAULT_WITHDRAW_BALANCE:
            w_ok, w_msg = withdraw(session, balance, trade_list)
            log(w_msg)
            time.sleep(random.randint(1, 3))
        else:
            log(f"[提现]: 余额不足{DEFAULT_WITHDRAW_BALANCE}元，不进行提现")

    log(f"------ 【账号{index}】执行任务完成 ------")
    return lines


def main():
    """主函数"""
    log_lines = []
    log_lines.append(log_print(f"\n{' ' * 7}{SCRIPT_NAME}"))
    log_lines.append(log_print("-------- 开 始  执 行 --------"))

    accounts = parse_accounts()
    if not accounts:
        log_lines.append(log_print("⭕ 未找到账号，请设置 WX_ID 环境变量"))
        notify_send(f"{SCRIPT_NAME} 运行日志", "作者：临渊\n\n" + "\n".join(log_lines))
        return

    log_lines.append(log_print(f"共 {len(accounts)} 个账号"))
    proxy_url = os.getenv("PROXY_API_URL")

    all_lines = list(log_lines)
    for i, acc in enumerate(accounts, 1):
        acc_lines = run_account(acc, i, len(accounts), proxy_url)
        all_lines.extend(acc_lines)
        time.sleep(random.randint(2, 4))

    all_lines.append(log_print("\n-------- 执 行  结 束 --------"))

    # 推送通知
    try:
        notify_send(f"{SCRIPT_NAME} 运行日志", "作者：临渊\n\n" + "\n".join(all_lines))
    except Exception:
        pass


if __name__ == "__main__":
    main()