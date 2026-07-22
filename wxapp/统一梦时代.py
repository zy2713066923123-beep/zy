# -*- coding: utf-8 -*-
"""
统一梦时代（微盟小程序 wx532ecb3bdaaf92f9）自动任务

功能：
  1. 微信登录（loginUserInfoX）+ token 缓存 + 失效自动重登
  2. 积分签到（非会员自动走会员激活兜底）
  3. 会员激活（协议取手机号 → 绑卡入会）
  4. 抽奖（保留原逻辑）
  5. 茄皇农场（登录 / 首页 / 任务 / 好友偷能量 / 消耗能量，RSA-OAEP(SHA256)+AES-256-GCM 加密）

依赖：requests、pycryptodome（Crypto），以及本目录的 getCode.py
环境变量：WX_ID（多账号支持换行、& 分隔）
"""

import os
import sys
import json
import time
import random
import re
import base64
import hashlib
import hmac
import uuid

import requests
from Crypto.Cipher import AES, PKCS1_OAEP, PKCS1_v1_5
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import unpad

from getCode import get_single_code, get_single_phone_number


# ============================================================
#  配置
# ============================================================
WX_APPID = "wx532ecb3bdaaf92f9"
HOST = "https://xapi.weimob.com"
SIGN_KEY = "b53ca184bcd458ef"
V = "1.0.0"
SRC = "web"
VER = "4.5.13"
PRODUCT_ID = "dingjin"
TID_KEY = "w" + SIGN_KEY  # 与 JS 保持一致：'w' + SIGN_KEY

# 茄皇农场相关（以下两项为「替换为实际值」占位符，需从你的小程序实际配置填入，农场才能真正跑通）
WM_TENANT_ID = "1948@..."    # TODO: 替换为实际租户ID（wmessage-tenant-id）
WM_TEMPLATE_ID = "1948@..."  # TODO: 替换为实际模板ID

# 农场请求用的 RSA 公钥（RSA-OAEP / SHA-256 + AES-256-GCM），来自前端实现，无需改动
FARM_PUBLIC_KEY = 'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA70sK419vy3MabW3lEGlk7Zh1u78OdnVlioVazp5Y46eBh+/TDqo/wZ9VrQ/4MmAtoP0vJ2vmwP5gqO3WPojb07WddXfF1eU+5M+Rj3s0eSRrvZvBcGZ3qK0dOgZJScK66IDQazt/c4xqhDcsItIyNRahUqB/IKc6E80GZJvMvFtZVSCseAXC0mAJXhi1AdUOlP+3Pv0fiUVejTJp1j7LBNWJ7Z5/8mRcclQH0vmxsdYsaV3qZiJ2d/CfNoKcwmI2IWmeZy8NP5U8Hn0AsxPEwjdHoEqG/iy/SoA46TZL+RLtWqUSHXpaKR/VFN0rbl25SE91X8FTfLqyD8LfGMCwRQIDAQAB'

# 会员激活用 RSA 私钥（PKCS#1 v1.5）。仅当 getUserPhoneGrant 返回加密手机号(encryptedData+iv)时才需要。
# 若你的协议服务直接返回 phone 字段，则无需此密钥。留空即可，脚本会自动跳过解密步骤。
PRIVATE_KEY = ""  # TODO(可选): 填入小程序 RSA 私钥(PEM) 以解密加密手机号

UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 7 Build/UP1A.231005.007) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.50(0x28003237)")
REFERER = f"https://servicewechat.com/{WX_APPID}/port/"

AUTH_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "梦时代auth.json")
LOGIN_MAX_RETRY = 3


# ============================================================
#  日志
# ============================================================
def log(msg):
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = f"{ts} | {msg}"
    print(line, flush=True)
    return line


# ============================================================
#  工具函数
# ============================================================
def rand_hex(n):
    return ''.join(random.choice('0123456789abcdef') for _ in range(n))


def tid():
    # w<32hex>-<13位时间戳>
    return 'w' + rand_hex(32) + '-' + str(int(time.time() * 1000))


def hmac_sign(msg, key):
    return hmac.new(key.encode('utf-8'), msg.encode('utf-8'), hashlib.md5).hexdigest()


def now_ms():
    return int(time.time() * 1000)


def load_auth_cache():
    try:
        with open(AUTH_CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_auth_cache(d):
    try:
        with open(AUTH_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def pem_from_b64(b64):
    s = b64.strip()
    chunks = [s[i:i + 64] for i in range(0, len(s), 64)]
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(chunks) + "\n-----END PUBLIC KEY-----"


# ============================================================
#  加密：农场请求体（RSA-OAEP / SHA-256 + AES-256-GCM）
# ============================================================
def encrypt_farm_data(plain: str) -> str:
    aes_key = get_random_bytes(32)
    iv = get_random_bytes(12)
    cipher = AES.new(aes_key, AES.MODE_GCM, nonce=iv)
    ct = cipher.encrypt(plain.encode('utf-8'))
    tag = cipher.digest()
    enc = ct + tag
    pub = RSA.import_key(pem_from_b64(FARM_PUBLIC_KEY))
    rsa = PKCS1_OAEP.new(pub, hashAlgo=SHA256)  # OAEP + MGF1 均使用 SHA-256，对应 Node oaepHash:'sha256'
    enc_key = rsa.encrypt(aes_key)
    out = {
        'data': base64.b64encode(enc).decode('ascii'),
        'key': base64.b64encode(enc_key).decode('ascii'),
        'iv': base64.b64encode(iv).decode('ascii'),
    }
    return json.dumps(out, ensure_ascii=False, separators=(',', ':'))


def decrypt_phone(encrypted_data_b64, iv_b64, private_key_pem):
    """RSA 私钥(PKCS#1 v1.5) + AES-128-CBC 解密微信标准加密手机号。"""
    if not private_key_pem:
        raise ValueError("未配置 PRIVATE_KEY，无法解密加密手机号")
    em = base64.b64decode(encrypted_data_b64)
    key = RSA.import_key(private_key_pem)
    cipher = PKCS1_v1_5.new(key)
    sentinel = b'DECRYPT_FAIL'
    result = cipher.decrypt(em, sentinel)
    if result == sentinel:
        raise ValueError("RSA 解密失败")
    key16 = (result + b'\x00' * 16)[:16]
    iv = base64.b64decode(iv_b64)
    cipher2 = AES.new(key16, AES.MODE_CBC, iv)
    dec = cipher2.decrypt(base64.b64decode(encrypted_data_b64))
    dec = unpad(dec, 16)
    info = json.loads(dec.decode('utf-8'))
    return info.get('phoneNumber')


# ============================================================
#  PCA 代理（保持原样）
# ============================================================
def set_pca_proxy(session, pca):
    if not pca:
        return
    if pca.get('enable') is True and pca.get('proxy'):
        session.proxies.update({'http': pca['proxy'], 'https': pca['proxy']})
        log(f"🌐 已启用 PCA 代理: {pca['proxy']}")
    elif pca.get('enable') is True and pca.get('client') and pca.get('secret') and pca.get('gw'):
        log(f"🌐 已启用 PCA 网关代理: {pca['gw']}")
        session.proxies.update({'http': pca['gw'], 'https': pca['gw']})


def get_pca_config():
    pca_enable = os.environ.get('PCA_ENABLE', 'false').lower() == 'true'
    pca_proxy = os.environ.get('PCA_PROXY', '')
    pca_client = os.environ.get('PCA_CLIENT', '')
    pca_secret = os.environ.get('PCA_SECRET', '')
    pca_gw = os.environ.get('PCA_GW', '')
    pca = {}
    if pca_enable:
        if pca_proxy:
            pca = {'enable': True, 'proxy': pca_proxy}
        elif pca_client and pca_secret and pca_gw:
            pca = {'enable': True, 'client': pca_client, 'secret': pca_secret, 'gw': pca_gw}
    return pca


# ============================================================
#  主任务类
# ============================================================
class AutoTask:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        set_pca_proxy(self.session, get_pca_config())
        self.wx_appid = WX_APPID
        self.client_id = str(uuid.uuid4())
        self.token = ''
        self.wid = ''
        self.openid = ''
        self.wx_id = ''
        self.is_member_flag = None

    # ---------- 请求封装 ----------
    def wheaders(self, farm=False, is_login=False):
        t = now_ms()
        sign = hmac_sign(f"{self.client_id}{TID_KEY}{t}", SIGN_KEY)
        h = {
            't': str(t),
            'sign': sign,
            'clientId': self.client_id,
            'traceparent': rand_hex(32),
            'traceid': f"{t}{random.randint(0, 999999)}",
            'apmConversationId': str(uuid.uuid4()),
            'vid': str(uuid.uuid4()),
            'v_device': str(uuid.uuid4()),
            'x-requested-with': 'XMLHttpRequest',
            'User-Agent': UA,
            'Referer': REFERER,
            'Accept': 'application/json, text/plain, */*',
            'Cookie': f"wmessage-token-{self.client_id}={self.token}; wmessage-wid-{self.client_id}={self.wid}",
        }
        if farm:
            h['Content-Type'] = 'application/json;charset=UTF-8'
            h['wm-tid'] = tid()
            h['wm-tenant-id'] = WM_TENANT_ID
        else:
            h['Content-Type'] = 'application/x-www-form-urlencoded'
            if is_login:
                h['wm-tid'] = tid()
                h['wm-tenant-id'] = WM_TENANT_ID
        return h

    def wpost(self, path, body, use_farm=False, return_full=False, retries=3):
        url = HOST + path
        is_login = path.startswith('/common/user/login')
        # /common/user/login 虽然是表单体，但需带 wm-tid / wm-tenant-id 头
        farm_headers = use_farm and not is_login

        common = {
            "v": V, "src": SRC, "ver": VER,
            "productId": PRODUCT_ID, "cache": False, "clientId": self.client_id,
        }
        if farm_headers:
            post_data = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, separators=(',', ':'))
            headers = self.wheaders(farm=True)
        else:
            req = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, separators=(',', ':'))
            post_data = {**common, "gw": "0", "t": str(now_ms()), "isEncode": "1", "request": req}
            headers = self.wheaders(farm=False, is_login=is_login)

        last_err = None
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.post(url, data=post_data, headers=headers, timeout=30)
                try:
                    return resp.json()
                except Exception:
                    return {}
            except requests.RequestException as e:
                last_err = e
                self.log(f"  ⚠️ 请求失败（{attempt}/{retries}）: {e}")
                if attempt < retries:
                    time.sleep(2 + random.randint(0, 2))
        raise last_err or Exception("请求失败")

    # ---------- 微信 code ----------
    def get_wx_code(self, wx_id):
        try:
            return get_single_code(self.wx_appid, wx_id)
        except Exception as e:
            raise Exception(f"获取微信code失败: {e}")

    # ---------- 登录 ----------
    def wxlogin(self, code):
        try:
            r = self.wpost('/fe/mapi/user/loginUserInfoX', {"code": code, "getUserProfile": True}, return_full=True)
            if r and r.get('code') in ('200', 200) and r.get('data'):
                d = r['data']
                return {'token': d.get('token'), 'wid': d.get('wid', ''), 'openid': d.get('openid', '')}
        except Exception as e:
            self.log(f"  ⚠️ loginUserInfoX 失败: {e}")
        return None

    def get_user_info(self):
        try:
            r = self.wpost('/fe/mapi/user/loginUserInfo', {}, return_full=True)
            if r and r.get('code') in ('200', 200) and r.get('data'):
                return r['data'].get('userInfo', {}) or {}
        except Exception:
            pass
        return None

    def ensure_login(self):
        cache = load_auth_cache()
        cached = cache.get(self.wx_id)
        self.token = ''
        self.wid = ''
        self.openid = ''
        self.is_member_flag = None

        if cached and cached.get('token'):
            self.token = cached['token']
            self.wid = cached.get('wid', '')
            info = self.get_user_info()
            if info is not None:
                self.is_member_flag = bool(info.get('isMember'))
                self.openid = info.get('openid', '')
                self.log("✅ 使用缓存 token 登录成功")
                return True

        last_err = None
        for attempt in range(1, LOGIN_MAX_RETRY + 1):
            try:
                code = self.get_wx_code(self.wx_id)
                res = self.wxlogin(code)
                if res and res.get('token'):
                    self.token = res['token']
                    self.wid = res.get('wid', '')
                    self.openid = res.get('openid', '')
                    cache[self.wx_id] = {'token': self.token, 'wid': self.wid, 'openid': self.openid}
                    save_auth_cache(cache)
                    info = self.get_user_info()
                    if info is not None:
                        self.is_member_flag = bool(info.get('isMember'))
                        self.openid = info.get('openid', self.openid)
                    self.log("✅ 登录成功" + (f"（第{attempt}次重试）" if attempt > 1 else ""))
                    return True
                last_err = Exception("登录未返回 token")
            except Exception as e:
                last_err = e
                self.log(f"  ⚠️ 登录失败（{attempt}/{LOGIN_MAX_RETRY}）: {e}")
            if attempt < LOGIN_MAX_RETRY:
                time.sleep(3 + random.randint(0, 3))
        self.log(f"❌ 登录重试 {LOGIN_MAX_RETRY} 次仍失败: {last_err}")
        raise last_err or Exception("登录失败")

    def is_member(self):
        if self.is_member_flag is None:
            info = self.get_user_info()
            self.is_member_flag = bool(info.get('isMember')) if info else False
        return self.is_member_flag

    # ---------- 会员激活 ----------
    def activate_member(self):
        if self.is_member():
            return True
        try:
            self.log("  📱 获取手机号授权...")
            phone_code = get_single_phone_number(self.wx_appid, self.wx_id)
            if not phone_code:
                self.log("  ❌ 获取手机号 code 失败")
                return False
            resp = self.wpost('/fe/mapi/user/getUserPhoneGrant', {"code": phone_code}, return_full=True)
            phone = None
            if isinstance(resp, dict):
                d = resp.get('data', resp)
                if d.get('phone'):
                    phone = d['phone']
                elif d.get('encryptedData') and d.get('iv'):
                    if PRIVATE_KEY:
                        try:
                            phone = decrypt_phone(d['encryptedData'], d['iv'], PRIVATE_KEY)
                        except Exception as e:
                            self.log(f"  ❌ 解密手机号失败: {e}")
                    else:
                        self.log("  ⚠️ getUserPhoneGrant 返回加密手机号，但未配置 PRIVATE_KEY，无法解密（请填入小程序 RSA 私钥）")
            if not phone:
                self.log("  ❌ 未能解析手机号")
                return False
            add_resp = self.wpost('user/addV2',
                                  {"phoneNumber": phone, "source": "MINI_PROGRAM", "registerSource": "MINI_PROGRAM"},
                                  return_full=True)
            self.log(f"  ✅ 会员激活请求已发送: {json.dumps(add_resp, ensure_ascii=False)[:200]}")
            return True
        except Exception as e:
            self.log(f"  ❌ 会员激活异常: {e}")
            return False

    # ---------- 积分签到 ----------
    def get_sign_info(self):
        r = self.wpost('/fe/mapi/credits/sign/getSignInfo', {})
        if r and r.get('code') in ('200', 200):
            return r.get('data') or {}
        return None

    def sign_in(self):
        return self.wpost('/fe/mapi/credits/signIn', {"taskId": "signIn"})

    @staticmethod
    def _ok(r):
        return bool(r) and r.get('code') in ('200', 200, 0, '0')

    def do_sign_in(self):
        info = self.get_sign_info()
        if info and info.get('isSigned'):
            self.log("✅ 今日已签到")
            return
        r = self.sign_in()
        if self._ok(r):
            self.log("✅ 签到成功")
            return
        # 失败：非会员则尝试激活后重新登录再签到
        if not self.is_member():
            self.log("⚠️ 签到失败且非会员，尝试会员激活")
            if self.activate_member():
                self.ensure_login()
                r2 = self.sign_in()
                if self._ok(r2):
                    self.log("✅ 激活并签到成功")
                    return
                self.log("⚠️ 激活后签到仍失败")
        else:
            self.log("⚠️ 签到失败: %s" % (json.dumps(r, ensure_ascii=False)[:200] if r else '无响应'))

    # ---------- 抽奖（保留原逻辑） ----------
    def lottery(self):
        try:
            list_data = self.wpost('/fe/mapi/operate/list', {"taskName": "签到抽奖"})
            if not list_data or list_data.get('code') != '200':
                self.log("⚠️ 获取抽奖活动失败")
                return
            data = list_data.get('data', [])
            if not data:
                self.log("⚠️ 未找到抽奖活动")
                return
            activityId = data[0].get('activityId')
            if not activityId:
                self.log("⚠️ 未获取到 activityId")
                return
            self.log(f"🎁 开始抽奖 (activityId={activityId})")
            for i in range(20):
                do_data = self.wpost('/fe/mapi/operate/create', {
                    "api方法": json.dumps({"method": "get", "url": "/campaign/ability/lottery/doLottery",
                                            "data": {"activityId": activityId}}, ensure_ascii=False),
                    "taskName": "签到抽奖"
                })
                if do_data and do_data.get('code') == '200':
                    res = (do_data.get('data') or {}).get('result') or {}
                    self.log(f"  🎉 第{i + 1}次抽奖: {res.get('title') or res.get('name') or '成功'}")
                else:
                    self.log(f"  ⏹ 第{i + 1}次抽奖结束: {do_data.get('message') if do_data else '无响应'}")
                    break
                time.sleep(1.5)
        except Exception as e:
            self.log(f"⚠️ 抽奖异常: {e}")

    # ---------- 茄皇农场 ----------
    def farm_common_plain(self, extra):
        return {
            'wmPid': '0',
            'wmTenantId': WM_TENANT_ID,
            'wmTemplateId': WM_TEMPLATE_ID,
            't': now_ms(),
            'wid': self.wid,
            **extra,
        }

    def farm_post(self, path, plain):
        enc = encrypt_farm_data(json.dumps(plain, ensure_ascii=False, separators=(',', ':')))
        use_farm = not path.startswith('/common/user/login')
        return self.wpost(path, enc, use_farm=use_farm, return_full=True)

    def ensure_farm_login(self):
        plain = {'openId': self.openid, 'businessCode': ''}
        r = self.farm_post('/common/user/login', plain)
        if self._ok(r):
            self.log("🌱 农场登录成功")
        else:
            self.log(f"⚠️ 农场登录响应异常: {json.dumps(r, ensure_ascii=False)[:150]}")

    def farm_home(self):
        r = self.farm_post('/spa/member/queryHomeInfo', self.farm_common_plain({}))
        if self._ok(r):
            return r.get('data') or {}
        self.log(f"⚠️ 农场首页获取失败: {json.dumps(r, ensure_ascii=False)[:150]}")
        return {}

    def farm_handle_tasks(self):
        r = self.farm_post('/spa/task/list', self.farm_common_plain({}))
        tasks = ((r.get('data') or {}).get('taskInfo') or []) if self._ok(r) else []
        for t in tasks:
            if t.get('status') == 2:  # 可领取
                tid_ = t.get('taskId')
                if not tid_:
                    continue
                rr = self.farm_post('/spa/task/getAward', self.farm_common_plain({'taskId': tid_}))
                self.log(f"  🎯 领取任务奖励 {tid_}: {rr.get('message') if rr else '无响应'}")
                time.sleep(1)

    def farm_handle_friends(self):
        r = self.farm_post('/spa/friend/list', self.farm_common_plain({}))
        friends = ((r.get('data') or {}).get('friendList') or []) if self._ok(r) else []
        for f in friends:
            fid = f.get('userId') or f.get('friendId')
            if not fid:
                continue
            rr = self.farm_post('/spa/friend/steal', self.farm_common_plain({'friendId': fid}))
            self.log(f"  🤝 偷取好友 {fid} 能量: {rr.get('message') if rr else '无响应'}")
            time.sleep(1)

    def farm_handle_use(self):
        home = self.farm_home()
        energy = home.get('energy', 0) if isinstance(home, dict) else 0
        try:
            energy = int(energy or 0)
        except Exception:
            energy = 0
        if energy >= 50:
            rr = self.farm_post('/spa/member/useEnergy', self.farm_common_plain({'useNum': 50}))
            self.log(f"  💡 消耗能量 50（当前 {energy}）: {rr.get('message') if rr else '无响应'}")
        else:
            self.log(f"  💡 能量不足（当前 {energy}），暂不消耗")

    def farm_all(self):
        try:
            self.ensure_farm_login()
            self.farm_handle_tasks()
            self.farm_handle_friends()
            self.farm_handle_use()
            self.log("🌱 茄皇农场执行完成")
        except Exception as e:
            self.log(f"⚠️ 茄皇农场执行异常: {e}")

    # ---------- 单账号主流程 ----------
    def run(self, wx_id):
        self.wx_id = wx_id
        self.client_id = str(uuid.uuid4())
        self.token = ''
        self.wid = ''
        self.openid = ''
        self.is_member_flag = None
        mask = wx_id[-6:] if wx_id else "未知"
        log(f"👤 账号: ****{mask}")
        try:
            self.ensure_login()
            self.do_sign_in()
            self.lottery()
            self.farm_all()
        except Exception as e:
            log(f"❌ 账号执行异常: {e}")


# ============================================================
#  入口
# ============================================================
def main():
    soy_wxid_data = os.environ.get("WX_ID", "")
    if not soy_wxid_data:
        log("❌ 未配置 WX_ID 环境变量")
        return
    accounts = [a.strip() for a in re.split(r'[\n&]', soy_wxid_data) if a.strip()]
    if not accounts:
        log("❌ WX_ID 为空或解析失败")
        return

    log(f"🔔 统一梦时代, 开始! 共 {len(accounts)} 个账号")
    log("─" * 50)
    for i, wx_id in enumerate(accounts, 1):
        log(f"──────────── 账号[{i}/{len(accounts)}] ────────────")
        try:
            task = AutoTask()
            task.run(wx_id)
        except Exception as e:
            log(f"❌ 账号[{i}] 异常: {e}")
        if i < len(accounts):
            time.sleep(random.randint(3, 6))
    log("═" * 50)
    log("🏁 全部账号执行完毕")


if __name__ == "__main__":
    main()
