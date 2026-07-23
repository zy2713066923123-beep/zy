# -*- coding: utf-8 -*-
# cron: 11 10,19 * * *
"""
统一梦时代（微盟小程序 wx532ecb3bdaaf92f9）：积分签到 + 茄皇农场
Python 移植自统一梦时代.js（全量）

环境变量：
  WX_ID           多账号，换行或 & 分隔。格式：wxid_...#备注 / openid#phone#备注
                 兼容读取 qhdwq 变量名
  （协议层走 getCode.py：WX_ID 里放 getCode 协议账号，脚本通过 getCode 获取 wx.login code / 手机号）

可选变量：
  QHDWQ_DELAY_MIN=3       单接口/任务最小延迟秒
  QHDWQ_DELAY_MAX=5       单接口/任务最大延迟秒
  QHDWQ_CACHE=qhdwq.json  缓存文件
  QHDWQ_DEBUG=1           打印调试响应
  QHDWQ_NO_MEMBER_BIND=1  不自动获取手机号/激活会员
  QHDWQ_NO_USE_ENERGY=1   农场不自动使用能量
  QHDWQ_SHARE_ID=515      农场登录携带 shareTomatoUserId（默认不带）
  QHDWQ_TIMEOUT=25000     单接口超时(ms)
  QHDWQ_RETRY=2           失败重试次数

说明：
  - 缓存业务 token/wid/openId/农场 token；校验失效后自动重登。
  - 茄皇农场 POST 按前端实现：RSA-OAEP(SHA-256) + AES-256-GCM，加密体 {data,key,iv}。
"""

import os
import sys
import json
import traceback
import time
import random
import re
import base64
import uuid
import urllib.parse

import requests
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes

from getCode import get_single_code, get_single_phone_number


# ============================================================
#  配置（来自 HAR 与源码）
# ============================================================
APPID = 'wx532ecb3bdaaf92f9'
XAPI = 'https://xapi.weimob.com'
FARM = 'https://farmgames.ioutu.cn'
BOS_ID = 4020112618957
VID = 6013753979957
CID = 176205957
MERCHANT_ID = 2000020692957
WX_TEMPLATE_ID = 8225
TRACE_ID = '100315589'
YOUSHU_TOKEN = 'bicbd2929b97584cb7'
DEFAULT_AVATAR = 'https://image-c.weimobwmc.com/wrz/35389c90f9254cdd811561c18ab95daa.png'

PRODUCT = {
    'crm': {'productId': 146, 'productInstanceId': 3168798957, 'productVersionId': '14026'},
    'mall': {'productId': 1, 'productInstanceId': 3171023957, 'productVersionId': '42838'},
}

MEMBER_CONST = {
    'memberPlanId': 610257909,
    'memberSkuId': 347718,
    'levelId': 6681583,
    'groupId': 2089353,
    'fieldId': 2950187,
}

FARM_PUBLIC_KEY = 'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA70sK419vy3MabW3lEGlk7Zh1u78OdnVlioVazp5Y46eBh+/TDqo/wZ9VrQ/4MmAtoP0vJ2vmwP5gqO3WPojb07WddXfF1eU+5M+Rj3s0eSRrvZvBcGZ3qK0dOgZJScK66IDQazt/c4xqhDcsItIyNRahUqB/IKc6E80GZJvMvFtZVSCseAXC0mAJXhi1AdUOlP+3Pv0fiUVejTJp1j7LBNWJ7Z5/8mRcclQH0vmxsdYsaV3qZiJ2d/CfNoKcwmI2IWmeZy8NP5U8Hn0AsxPEwjdHoEqG/iy/SoA46TZL+RLtWqUSHXpaKR/VFN0rbl25SE91X8FTfLqyD8LfGMCwRQIDAQAB'

UA_WX = 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.75(0x18004b42) NetType/WIFI Language/zh_CN'
UA_FARM = UA_WX + ' miniProgram/' + APPID

# ---- 可调环境变量 ----
ENV = os.environ
DEBUG = re.match(r'^(1|true|on|yes)$', ENV.get('QHDWQ_DEBUG', ''), re.I) is not None
NO_MEMBER_BIND = re.match(r'^(1|true|on|yes)$', ENV.get('QHDWQ_NO_MEMBER_BIND', ''), re.I) is not None
NO_USE_ENERGY = re.match(r'^(1|true|on|yes)$', ENV.get('QHDWQ_NO_USE_ENERGY', ''), re.I) is not None
DELAY_MIN = int(re.match(r'^\d+$', ENV.get('QHDWQ_DELAY_MIN', '3') or '3') and re.match(r'^\d+$', ENV.get('QHDWQ_DELAY_MIN', '3')).group() or 3) or 3
_delay_max_raw = ENV.get('QHDWQ_DELAY_MAX', '5')
DELAY_MAX = max(DELAY_MIN, int(re.match(r'^\d+$', _delay_max_raw or '5') and re.match(r'^\d+$', _delay_max_raw).group() or 5) or 5)
TIMEOUT_MS = int(re.match(r'^\d+$', ENV.get('QHDWQ_TIMEOUT', '25000') or '25000') and re.match(r'^\d+$', ENV.get('QHDWQ_TIMEOUT', '25000')).group() or 25000) or 25000
RETRY = int(re.match(r'^\d+$', ENV.get('QHDWQ_RETRY', '2') or '2') and re.match(r'^\d+$', ENV.get('QHDWQ_RETRY', '2')).group() or 2) or 2
SHARE_ID = (ENV.get('QHDWQ_SHARE_ID') or '').strip()
CACHE_FILE = os.path.abspath(ENV.get('QHDWQ_CACHE', 'qhdwq.json'))

_session = requests.Session()


# ============================================================
#  工具
# ============================================================
def log(msg):
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = "%s | %s" % (ts, msg)
    print(line, flush=True)
    return line


def uuid_str():
    return str(uuid.uuid4())


def gen_cuid():
    return "%d%s" % (int(time.time() * 1000), uuid.uuid4().hex[:6])


def rand_int(minv, maxv):
    return random.randint(minv, maxv)


def mask(s):
    s = str(s or '')
    return s if len(s) <= 10 else s[:5] + '***' + s[-4:]


def _short(x, n=500):
    try:
        return json.dumps(x, ensure_ascii=False, separators=(',', ':'))[:n]
    except Exception:
        return str(x)[:n]


def load_cache():
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_cache(obj):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log('保存缓存失败：%s' % e)


CACHE = load_cache()
SUMMARIES = []


def wait_random(label):
    ms = rand_int(DELAY_MIN * 1000, DELAY_MAX * 1000)
    log('等待%d秒：%s' % (round(ms / 1000), label))
    time.sleep(ms / 1000.0)


# ============================================================
#  请求体 / 判定
# ============================================================
def wm_body(product_key, extra=None, refer=''):
    extra = extra or {}
    p = PRODUCT[product_key or 'crm']
    body = {
        'appid': APPID,
        'basicInfo': {
            'vid': VID,
            'vidType': 2,
            'bosId': BOS_ID,
            'productId': p['productId'],
            'productInstanceId': p['productInstanceId'],
            'productVersionId': p['productVersionId'],
            'merchantId': MERCHANT_ID,
            'tcode': 'weimob',
            'cid': CID,
        },
        'extendInfo': {
            'wxTemplateId': WX_TEMPLATE_ID,
            'childTemplateIds': [
                {'customId': 90004, 'version': 'crm@0.1.98'},
                {'customId': 90002, 'version': 'ec@88.1'},
                {'customId': 90006, 'version': 'hudong@0.0.255'},
                {'customId': 90008, 'version': 'cms@0.0.534'},
                {'customId': 90070, 'version': 'v1.0.42-20260622'},
            ],
            'analysis': [{'channelStatus': True, 'channelCode': 'youshu', 'token': YOUSHU_TOKEN}],
            'quickdeliver': {'enable': False},
            'bosTemplateId': 1000002277,
            'youshu': {'enable': True, 'token': YOUSHU_TOKEN},
            'source': 1,
            'channelsource': 5,
            'mpScene': 1044,
        },
        'queryParameter': {'tracePromotionId': TRACE_ID, 'tracepromotionid': TRACE_ID},
        'i18n': {'language': 'zh', 'timezone': '8'},
        'pid': str(BOS_ID),
        'storeId': '0',
        'tracePromotionId': TRACE_ID,
        'tracepromotionid': TRACE_ID,
        'currentTracePromotionId': TRACE_ID,
    }
    if refer:
        body['extendInfo']['refer'] = refer
    body.update(extra)
    return body


def is_weimob_ok(x):
    if not isinstance(x, dict):
        return False
    if x.get('errcode') in (0, '0'):
        return True
    if x.get('code') in (0, '0'):
        return True
    return x.get('success') is True and not x.get('error')


def is_farm_ok(x):
    return isinstance(x, dict) and x.get('code') == 200


def has_current_member_level(data):
    s = json.dumps(data or {}, ensure_ascii=False)
    return '"isCurrentUserLevel":true' in s or '"isObtained":true' in s


# ============================================================
#  HTTP 封装
# ============================================================
def _clean_headers(h):
    return {k: v for k, v in h.items() if v is not None and v != ''}


def ensure_apm(c):
    if not c.get('apmConversationId'):
        c['apmConversationId'] = uuid_str()
    return c['apmConversationId']


def weimob_post(api_path, body, c, opt=None):
    opt = opt or {}
    product = opt.get('product', 'crm')
    ensure_apm(c)
    headers = _clean_headers({
        'Content-Type': 'application/json',
        'Accept': '*/*',
        'User-Agent': UA_WX,
        'Referer': 'https://servicewechat.com/%s/288/page-frame.html' % APPID,
        'Cookie': 'rprm_cuid=%s' % (c.get('cuid') or gen_cuid()),
        'X-WX-Token': c.get('wxToken') or '',
        'x-biz-id': str(opt.get('bizId', PRODUCT[product]['productId'])),
        'x-wmsdk-vid': str(VID),
        'x-wmsdk-close-store': 'v2',
        'x-cms-sdk-request': '1.5.147',
        'x-req-from': opt.get('reqFrom') or ('onecrm' if product == 'crm' else 'cms_design_components'),
        'x-page-route': opt.get('pageRoute') or ('onecrm/membership' if product == 'crm' else 'cms_design/usercenter'),
        'x-component-is': opt.get('componentIs') or ('onecrm/membership' if product == 'crm' else 'cms_design_components/RAW/miniprogram_npm/@design-onecrm/wx-user-center-header/index'),
        'x-apm-conversation-id': c['apmConversationId'],
        'x-apm-page-id': uuid_str(),
        'x-apm-parent-page-id': uuid_str(),
        'x-wmsdk-bc': '1 %d' % int(time.time() * 1000),
        'x-cmssdk-vidticket': c.get('globalTicket'),
    })
    last_err = None
    for attempt in range(1, RETRY + 1):
        try:
            resp = _session.post(XAPI + api_path, headers=headers, json=body, timeout=TIMEOUT_MS / 1000.0)
            try:
                parsed = resp.json()
            except Exception:
                parsed = None
            if parsed and isinstance(parsed, dict) and parsed.get('globalTicket'):
                c['globalTicket'] = parsed['globalTicket']
            if DEBUG:
                log('【微盟】%s => %s' % (api_path, _short(parsed)))
            return parsed
        except requests.RequestException as e:
            last_err = e
            if attempt < RETRY:
                time.sleep(0.8 + random.random() * 0.8)
    raise last_err or Exception('weimob_post 失败: ' + api_path)


def farm_headers(c, post):
    params = {}
    if c.get('wid'):
        params['wid'] = str(c['wid'])
    if c.get('openId'):
        params['openId'] = str(c['openId'])
    if SHARE_ID:
        params['shareTomatoUserId'] = str(SHARE_ID)
    referer = '%s/?%s' % (FARM, urllib.parse.urlencode(params))
    token = c.get('farmToken') or ''
    h = _clean_headers({
        'Accept': '*/*',
        'Content-Type': 'application/json',
        'User-Agent': UA_FARM,
        'Referer': referer,
        'Cookie': ('authorization=%s' % token) if token else '',
        'Authorization': token,
        'Origin': FARM if post else None,
    })
    return h


def farm_get(api_path, c, params=None):
    url = FARM + api_path
    if params:
        url += '?' + urllib.parse.urlencode({k: str(v) for k, v in params.items()})
    headers = farm_headers(c, False)
    last_err = None
    for attempt in range(1, RETRY + 1):
        try:
            resp = _session.get(url, headers=headers, timeout=TIMEOUT_MS / 1000.0)
            try:
                parsed = resp.json()
            except Exception:
                parsed = None
            if DEBUG:
                log('【农场GET】%s => %s' % (api_path, _short(parsed)))
            return parsed
        except requests.RequestException as e:
            last_err = e
            if attempt < RETRY:
                time.sleep(0.8 + random.random() * 0.8)
    raise last_err or Exception('farm_get 失败: ' + api_path)


def farm_post(api_path, body, c, opt=None):
    opt = opt or {}
    headers = farm_headers(c, True)
    payload = body
    if opt.get('encrypt') and body and len(body):
        payload = encrypt_farm_body(body)
        headers['X-Request-Encrypted'] = 'true'
    last_err = None
    for attempt in range(1, RETRY + 1):
        try:
            resp = _session.post(FARM + api_path, headers=headers, json=payload, timeout=TIMEOUT_MS / 1000.0)
            try:
                parsed = resp.json()
            except Exception:
                parsed = None
            if DEBUG:
                log('【农场POST】%s 明文=%s 响应=%s' % (api_path, _short(body), _short(parsed)))
            return parsed
        except requests.RequestException as e:
            last_err = e
            if attempt < RETRY:
                time.sleep(0.8 + random.random() * 0.8)
    raise last_err or Exception('farm_post 失败: ' + api_path)


def public_key_pem(b64):
    clean = re.sub(r'-----[^-]+-----', '', b64 or '')
    clean = re.sub(r'\s+', '', clean)
    return '-----BEGIN PUBLIC KEY-----\n' + '\n'.join([clean[i:i + 64] for i in range(0, len(clean), 64)]) + '\n-----END PUBLIC KEY-----'


def encrypt_farm_body(obj):
    aes_key = get_random_bytes(32)
    iv = get_random_bytes(12)
    cipher = AES.new(aes_key, AES.MODE_GCM, nonce=iv)
    plaintext = json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    ct, tag = cipher.encrypt_and_digest(plaintext)
    data = base64.b64encode(ct + tag).decode('ascii')
    pub = RSA.import_key(public_key_pem(FARM_PUBLIC_KEY))
    enc_key = PKCS1_OAEP.new(pub, hashAlgo=SHA256).encrypt(aes_key)
    return {
        'data': data,
        'key': base64.b64encode(enc_key).decode('ascii'),
        'iv': base64.b64encode(iv).decode('ascii'),
    }


# ============================================================
#  协议（getCode.py）
# ============================================================
def get_wx_login_code(acc):
    code = get_single_code(APPID, acc['id'])
    if code:
        log('【%s】wx.login code 获取成功：%s' % (acc['remark'], mask(code)))
        return code
    raise Exception('获取 wx.login code 失败')


def get_wx_phone_grant(acc):
    """返回 {'code','encryptedData','iv','phone'}；getCode 直接返回明文手机号时填 phone"""
    phone = get_single_phone_number(APPID, acc['id'])
    if isinstance(phone, dict):
        return phone
    return {'code': '', 'encryptedData': '', 'iv': '', 'phone': phone or ''}


# ============================================================
#  微盟登录
# ============================================================
def ensure_weimob_login(acc, c):
    if c.get('wxToken') and c.get('openId') and c.get('wid') \
            and (int(c.get('wxTokenExpire') or 0) > int(time.time() * 1000) + 10 * 60 * 1000):
        if verify_weimob_token(c):
            log('【%s】微盟缓存有效：wid=%s openId=%s' % (acc['remark'], c['wid'], mask(c['openId'])))
            return c
        log('【%s】微盟缓存失效，重新协议登录' % acc['remark'])

    code = get_wx_login_code(acc)
    body = wm_body('mall', {
        'code': code,
        'getUserProfile': True,
        'nickName': acc['remark'] or '微信用户',
        'avatarUrl': c.get('avatar') or DEFAULT_AVATAR,
    }, 'cms-usercenter')
    resp = weimob_post('/fe/mapi/user/loginUserInfoX', body, c, {
        'product': 'mall', 'bizId': 1, 'refer': 'cms-usercenter', 'pageRoute': 'cms_design/usercenter'})
    if not is_weimob_ok(resp) or not resp.get('data') or not resp['data'].get('token'):
        raise Exception('微盟登录失败：' + _short(resp))
    d = resp['data']
    c['wxToken'] = d['token']
    c['wxTokenExpire'] = int(d.get('expireTime') or d.get('latestExpireTime') or (time.time() * 1000 + 24 * 3600 * 1000))
    c['wid'] = d.get('wid') or (d.get('userInfo') or {}).get('wid') or c.get('wid')
    c['openId'] = d.get('openId') or d.get('openid') or (d.get('userInfo') or {}).get('openId') or c.get('openId')
    c['unionId'] = d.get('unionId') or d.get('unionid') or (d.get('userInfo') or {}).get('unionId') or c.get('unionId')
    c['nickname'] = d.get('nickName') or d.get('nickname') or acc['remark']
    c['avatar'] = d.get('avatarUrl') or d.get('headurl') or (d.get('userInfo') or {}).get('avatarUrl') or c.get('avatar') or DEFAULT_AVATAR
    c['updateTime'] = int(time.time() * 1000)
    log('【%s】微盟登录成功：wid=%s openId=%s' % (acc['remark'], c['wid'], mask(c['openId'])))
    save_cache(CACHE)
    return c


def verify_weimob_token(c):
    try:
        resp = weimob_post('/api3/onecrm/user/center/usercenter/queryUserInfo',
                           wm_body('crm', {'request': {}}, 'onecrm-membership'), c,
                           {'product': 'crm', 'bizId': 146, 'refer': 'onecrm-membership', 'pageRoute': 'onecrm/membership'})
        return is_weimob_ok(resp) and isinstance(resp.get('data'), dict) and str(resp['data'].get('wid', '')) == str(c.get('wid') or resp['data'].get('wid') or '')
    except Exception:
        return False


# ============================================================
#  积分签到 / 会员
# ============================================================
def sign_main_info(c):
    return weimob_post('/api3/onecrm/mactivity/sign/misc/sign/activity/c/signMainInfo',
                       wm_body('crm', {'customInfo': {'source': 0, 'wid': int(c['wid'])}}, 'onecrm-signgift'), c,
                       {'product': 'crm', 'bizId': 146, 'refer': 'onecrm-signgift', 'pageRoute': 'onecrm/signgift'})


def query_point(c):
    return weimob_post('/api3/onecrm/point/myPoint/getSimpleAccountInfo',
                       wm_body('mall', {'targetBasicInfo': {'productInstanceId': PRODUCT['crm']['productInstanceId']}, 'request': {}}, 'cms-usercenter'), c,
                       {'product': 'mall', 'bizId': 1, 'refer': 'cms-usercenter', 'pageRoute': 'cms_design/usercenter'})


def do_point_sign(acc, c, sum_):
    log('【%s】开始积分签到' % acc['remark'])
    info = sign_main_info(c)
    if not is_weimob_ok(info):
        raise Exception('查询签到信息失败：' + _short(info))

    if (info.get('data') or {}).get('hasSign'):
        log('【%s】积分签到：今日已签到' % acc['remark'])
    else:
        if (info.get('data') or {}).get('status') == 3:
            log('【%s】当前不符合签到条件，先检查/激活会员' % acc['remark'])
            ensure_member(acc, c)
            wait_random('会员后刷新签到')
            info = sign_main_info(c)

        if not (info.get('data') or {}).get('hasSign'):
            # 绑定手机号关联（部分活动需要，失败可忽略）
            try:
                weimob_post('/api3/onecrm/mactivity/center/account/getRelevancePhonesByWid',
                            wm_body('crm', {'customInfo': {'source': 0, 'wid': int(c['wid'])}}, 'onecrm-signgift'), c,
                            {'product': 'crm', 'bizId': 146, 'refer': 'onecrm-signgift', 'pageRoute': 'onecrm/signgift'})
            except Exception:
                pass
            wait_random('准备签到')
            sign = weimob_post('/api3/onecrm/mactivity/sign/misc/sign/activity/core/c/sign',
                               wm_body('crm', {'customInfo': {'source': 0, 'wid': int(c['wid'])}}, 'onecrm-signgift'), c,
                               {'product': 'crm', 'bizId': 146, 'refer': 'onecrm-signgift', 'pageRoute': 'onecrm/signgift'})
            if not is_weimob_ok(sign):
                errmsg = str(sign.get('errmsg') or '')
                if '不符合' in errmsg and not NO_MEMBER_BIND:
                    log('【%s】签到仍不符合，重试会员激活后再签' % acc['remark'])
                    ensure_member(acc, c, True)
                    wait_random('重试签到')
                    retry = weimob_post('/api3/onecrm/mactivity/sign/misc/sign/activity/core/c/sign',
                                        wm_body('crm', {'customInfo': {'source': 0, 'wid': int(c['wid'])}}, 'onecrm-signgift'), c,
                                        {'product': 'crm', 'bizId': 146, 'refer': 'onecrm-signgift', 'pageRoute': 'onecrm/signgift'})
                    if not is_weimob_ok(retry):
                        raise Exception('积分签到失败：' + _short(retry))
                    log('【%s】积分签到成功：%s' % (acc['remark'], reward_text(retry.get('data'))))
                    sum_['reward'] += int((retry.get('data') or {}).get('fixedReward', {}).get('points') or 0)
                else:
                    raise Exception('积分签到失败：' + _short(sign))
            else:
                log('【%s】积分签到成功：%s' % (acc['remark'], reward_text(sign.get('data'))))
                sum_['reward'] += int((sign.get('data') or {}).get('fixedReward', {}).get('points') or 0)
        else:
            log('【%s】积分签到：会员刷新后显示已签到' % acc['remark'])

    wait_random('查询积分')
    point = query_point(c)
    if is_weimob_ok(point):
        sum_['point'] = point.get('data', {}).get('availablePoint', point.get('data', {}).get('sumAvailablePoint', '-'))
        log('【%s】当前积分：%s' % (acc['remark'], sum_['point']))
    else:
        log('【%s】积分查询失败：%s' % (acc['remark'], _short(point)))


def reward_text(d):
    if not d:
        return ''
    f = d.get('fixedReward') or {}
    e = d.get('extraReward') or {}
    return '积分+%d 成长值+%d' % (int(f.get('points') or 0) + int(e.get('points') or 0),
                                  int(f.get('growth') or 0) + int(e.get('growth') or 0))


def ensure_member(acc, c, force=False):
    if NO_MEMBER_BIND:
        log('【%s】已设置 QHDWQ_NO_MEMBER_BIND=1，跳过会员激活' % acc['remark'])
        return False

    lack = weimob_post('/api3/onecrm/user/center/bindcard/queryLackBridgeField',
                       wm_body('crm', {}, 'onecrm-membership'), c,
                       {'product': 'crm', 'bizId': 146, 'refer': 'onecrm-membership', 'pageRoute': 'onecrm/membership'})
    if not force and is_weimob_ok(lack) and (lack.get('data') or {}).get('isMembership'):
        log('【%s】会员已激活' % acc['remark'])
        return True

    home = weimob_post('/api3/onecrm/user/center/member/center/queryCardCenterHomePage',
                       wm_body('crm', {'miniVersion': 1390}, 'onecrm-membership'), c,
                       {'product': 'crm', 'bizId': 146, 'refer': 'onecrm-membership', 'pageRoute': 'onecrm/membership'})
    if not force and is_weimob_ok(home) and has_current_member_level(home.get('data')):
        log('【%s】会员中心显示已入会' % acc['remark'])
        return True

    log('【%s】尝试协议手机号授权并激活会员' % acc['remark'])
    grant = get_wx_phone_grant(acc)
    phone = grant.get('phone') or c.get('phone') or ''
    if not phone and (grant.get('code') or grant.get('encryptedData')):
        phone_resp = weimob_post('/api3/user/getPhoneNumber',
                                 wm_body('crm', {
                                     'encryptedData': grant.get('encryptedData') or '',
                                     'iv': grant.get('iv') or '',
                                     'errMsg': 'getPhoneNumber:ok',
                                     'code': grant.get('code') or '',
                                 }, 'onecrm-membership'), c,
                                 {'product': 'crm', 'bizId': 146, 'refer': 'onecrm-membership',
                                  'pageRoute': 'onecrm/membership',
                                  'componentIs': 'onecrm/RAW/pages/membership/blocks/membership-form/member-form'})
        if is_weimob_ok(phone_resp):
            phone = (phone_resp.get('data') or {}).get('phoneNumber') or (phone_resp.get('data') or {}).get('purePhoneNumber') or ''
        else:
            log('【%s】业务手机号解密失败：%s' % (acc['remark'], _short(phone_resp)))
        wait_random('手机号后')
    if not phone:
        raise Exception('没有拿到手机号，无法自动激活会员')
    c['phone'] = phone

    bind_body = wm_body('crm', build_bind_card_payload(phone), 'onecrm-membership')
    bind = weimob_post('/api3/onecrm/user/center/bindcard/manuaUserlBindCard', bind_body, c,
                       {'product': 'crm', 'bizId': 146, 'refer': 'onecrm-membership',
                        'pageRoute': 'onecrm/membership', 'componentIs': 'onecrm/membership'})
    if not is_weimob_ok(bind):
        raise Exception('会员激活失败：' + _short(bind))
    log('【%s】会员激活成功：cardNo=%s customCardNo=%s' % (
        acc['remark'], (bind.get('data') or {}).get('cardNo', '-'), (bind.get('data') or {}).get('customCardNo', '-')))
    return True


def build_bind_card_payload(phone):
    now = int(time.time() * 1000)
    return {
        'memberPlanId': MEMBER_CONST['memberPlanId'],
        'groupFieldInfos': [{
            'fieldInfo': {
                'groupWholeFieldInfos': [{
                    'fieldValues': [{
                        'fieldId': MEMBER_CONST['fieldId'],
                        'fieldKey': 'phone',
                        'fieldName': '手机号',
                        'fieldStatus': 1,
                        'fieldType': 1,
                        'fieldValue': str(phone),
                        'groupId': MEMBER_CONST['groupId'],
                        'groupNum': 0,
                        'guardian': '',
                        'isRequired': 1,
                        'isValueModifiable': 1,
                        'isValueUnique': 1,
                        'operationType': None,
                        'optionList': [],
                        'originalValue': '',
                        'ruleList': [{'limitType': None, 'max': 32, 'min': 0, 'ruleType': 3}],
                        'sort': None,
                        'templateFieldId': None,
                        'tips': '请填写正确的手机号',
                        'valueType': 7,
                    }],
                }],
            },
            'groupId': MEMBER_CONST['groupId'],
            'groupName': '基础信息',
            'key': 'basic',
            'maxLimitGroup': None,
            'repeatCount': 1,
            'sort': 1,
        }],
        'regionCode': '',
        'inviteCode': '',
        'memberSkuId': MEMBER_CONST['memberSkuId'],
        'levelId': MEMBER_CONST['levelId'],
        'pmcParamsInfo': {
            'tracepromotionid': {'paramName': 'tracepromotionid', 'value': TRACE_ID, 'type': [2, 5], 'ttl': 2592000, 'initPmcTime': now},
            'share_vid': {'paramName': 'share_vid', 'value': str(VID), 'type': [2, 3, 5], 'ttl': 86400, 'initPmcTime': now},
        },
        'urlParamsInfo': {'isqdzz': '1', 'vid': '0', 'share_vid': str(VID),
                          'productInstanceId': str(PRODUCT['crm']['productInstanceId']), 'tracepromotionid': TRACE_ID},
        'guardianRecordId': '',
        'miniVersion': '13160',
    }


# ============================================================
#  茄皇农场
# ============================================================
def decode_jwt_ms(token, key):
    try:
        seg = str(token).split('.')[1].replace('-', '+').replace('_', '/')
        p = json.loads(base64.b64decode(seg + '=' * (-len(seg) % 4)).decode('utf-8'))
        return int(p.get(key) or (p.get('exp') and p.get('exp') * 1000) or 0)
    except Exception:
        return 0


def farm_token_valid(token):
    eff = decode_jwt_ms(token, 'eff')
    return eff and eff > int(time.time() * 1000) + 10 * 60 * 1000


def ensure_farm_login(acc, c, force=False):
    if not force and c.get('farmToken') and farm_token_valid(c['farmToken']):
        chk = farm_get('/api/web/member/tomato/home', c)
        if is_farm_ok(chk):
            log('【%s】农场缓存有效：tomatoUserId=%s' % (acc['remark'], (chk.get('data') or {}).get('tomatoUserId', '-')))
            return c['farmToken']
    if not c.get('openId') or not c.get('wid'):
        raise Exception('缺少 openId/wid，无法登录农场')
    payload = {'openId': c['openId'], 'wid': c['wid'], 'queryCardStatus': True}
    if SHARE_ID:
        payload['shareTomatoUserId'] = str(SHARE_ID)
    login = farm_post('/api/web/open/tomato/login', payload, c, {'encrypt': True, 'allowNoToken': True})
    if not is_farm_ok(login) or not (login.get('data') or {}).get('token'):
        raise Exception('农场登录失败：' + _short(login))
    c['farmToken'] = login['data']['token']
    c['farmTomatoUserId'] = login['data'].get('tomatoUserId')
    c['farmTokenExpire'] = decode_jwt_ms(login['data']['token'], 'eff') or (int(time.time() * 1000) + 7 * 24 * 3600 * 1000)
    log('【%s】农场登录成功：tomatoUserId=%s cardStatus=%s' % (
        acc['remark'], c['farmTomatoUserId'], login['data'].get('cardStatus', '-')))
    save_cache(CACHE)
    return c['farmToken']


def do_farm_all(acc, c, sum_):
    log('【%s】开始茄子^_^皇农场' % acc['remark'])
    ensure_farm_login(acc, c)

    home = farm_get('/api/web/member/tomato/home', c)
    if not is_farm_ok(home):
        log('【%s】农场缓存失效，重新登录' % acc['remark'])
        c['farmToken'] = ''
        ensure_farm_login(acc, c, True)
        home = farm_get('/api/web/member/tomato/home', c)
    if not is_farm_ok(home):
        raise Exception('农场首页失败：' + _short(home))
    hd = home.get('data') or {}
    log('【%s】农场首页：能量=%s 茄币=%s 阶段=%s' % (
        acc['remark'], hd.get('energyBalance', '-'), hd.get('tomatoBalance', '-'), hd.get('stageName', '-')))

    wait_random('农场任务前')
    farm_tasks(acc, c)

    wait_random('好友任务前')
    farm_friends(acc, c)

    wait_random('能量使用前')
    home = farm_get('/api/web/member/tomato/home', c)
    if is_farm_ok(home) and not NO_USE_ENERGY and int(home.get('data', {}).get('energyBalance') or 0) > 0:
        use = farm_post('/api/web/member/tomato/energy/use', None, c, {'encrypt': False})
        if is_farm_ok(use):
            log('【%s】使用能量成功：消耗=%s 当前经验=%s' % (
                acc['remark'], (use.get('data') or {}).get('usedEnergyAmount', '-'), (use.get('data') or {}).get('currentExp', '-')))
            home = use
        else:
            log('【%s】使用能量失败：%s' % (acc['remark'], _short(use)))
    elif NO_USE_ENERGY:
        log('【%s】已设置 QHDWQ_NO_USE_ENERGY=1，跳过使用能量' % acc['remark'])

    final_home = home if is_farm_ok(home) else farm_get('/api/web/member/tomato/home', c)
    if is_farm_ok(final_home):
        fd = final_home.get('data') or {}
        sum_['farmEnergy'] = fd.get('energyBalance', '-')
        sum_['farmTomato'] = fd.get('tomatoBalance', '-')
        log('【%s】农场完成：能量=%s 茄币=%s 经验=%s/%s' % (
            acc['remark'], sum_['farmEnergy'], sum_['farmTomato'], fd.get('currentExp', '-'), fd.get('stageRequiredExp', '-')))


def farm_tasks(acc, c):
    lst = farm_get('/api/web/member/tomato/tasks', c)
    if not is_farm_ok(lst) or not isinstance(lst.get('data'), list):
        log('【%s】农场任务列表失败：%s' % (acc['remark'], _short(lst)))
        return
    for t in lst['data']:
        name = t.get('taskName') or t.get('taskType') or t.get('taskCode') or t.get('taskId')
        if str(t.get('completed')) == '1' and str(t.get('rewardClaimed')) == '1':
            log('【%s】任务已完成：%s' % (acc['remark'], name))
            continue
        if t.get('taskType') == 'FRIEND_STEAL_ENERGY':
            log('【%s】好友能量任务稍后单独处理：%s' % (acc['remark'], t.get('rewardText', '')))
            continue
        try:
            if t.get('taskType') == 'SHARE':
                if c.get('farmTomatoUserId'):
                    try:
                        farm_post('/api/web/member/tomato/miniprogram/qrcode/create',
                                  {'page': 'packages/wm-cloud-qiehuang/home/index', 'scene': str(c['farmTomatoUserId'])},
                                  c, {'encrypt': True})
                    except Exception:
                        pass
                    wait_random('分享二维码')
                r = farm_post('/api/web/member/tomato/tasks/complete', {'taskType': 'SHARE'}, c, {'encrypt': True})
                if is_farm_ok(r):
                    log('【%s】任务完成：%s %s' % (acc['remark'], name, (r.get('data') or {}).get('rewardText', '')))
                else:
                    log('【%s】任务失败：%s %s' % (acc['remark'], name, _short(r)))
            else:
                body = {'taskType': t.get('taskType')}
                if t.get('browseTarget'):
                    body['browseTarget'] = t['browseTarget']
                r = farm_post('/api/web/member/tomato/tasks/complete', body, c, {'encrypt': True})
                if is_farm_ok(r):
                    log('【%s】任务完成：%s %s' % (acc['remark'], name, (r.get('data') or {}).get('rewardText', '')))
                else:
                    log('【%s】任务失败：%s %s' % (acc['remark'], name, _short(r)))
        except Exception as e:
            log('【%s】任务异常：%s %s' % (acc['remark'], name, e))
        wait_random('农场任务间隔')


def farm_friends(acc, c):
    page = 1
    total_steal = 0
    while page <= 5:
        res = farm_get('/api/web/member/tomato/friends', c, {'pageNum': page, 'pageSize': 20})
        if not is_farm_ok(res) or not isinstance(res.get('rows'), list):
            if page == 1:
                log('【%s】好友列表失败或为空：%s' % (acc['remark'], _short(res)))
            break
        if not res['rows']:
            break
        for f in res['rows']:
            fid = f.get('friendTomatoUserId')
            if not fid:
                continue
            detail = None
            if str(f.get('canSteal')) == '1' or int(f.get('friendEnergyBalance') or 0) > 0:
                try:
                    detail = farm_get('/api/web/member/tomato/friends/%s/home' % urllib.parse.quote(str(fid), safe=''), c)
                except Exception:
                    detail = None
                wait_random('好友详情')
            d = (detail.get('data') if (detail and is_farm_ok(detail)) else f)
            if str(d.get('canCollectTomato')) == '1':
                try:
                    r = farm_post('/api/web/member/tomato/friends/growth-gift/collect', {'friendTomatoUserId': fid}, c, {'encrypt': True})
                except Exception as e:
                    r = {'code': 0, 'msg': str(e)}
                if is_farm_ok(r):
                    log('【%s】收取好友成长礼：%s +%s' % (acc['remark'], d.get('friendNickName') or fid, r.get('data') or d.get('collectTomatoAmount') or 1))
                else:
                    log('【%s】收取好友成长礼失败：%s %s' % (acc['remark'], d.get('friendNickName') or fid, _short(r)))
                wait_random('好友礼物')
            if str(d.get('canSteal')) == '1' and int(d.get('stealAmount') or f.get('friendEnergyBalance') or 0) > 0:
                try:
                    r = farm_post('/api/web/member/tomato/friends/steal', {'friendTomatoUserId': fid}, c, {'encrypt': True})
                except Exception as e:
                    r = {'code': 0, 'msg': str(e)}
                if is_farm_ok(r):
                    amount = int(d.get('stealAmount') or 0) or max(0, int(f.get('friendEnergyBalance') or 0) - int((r.get('data') or {}).get('friendEnergyBalance') or 0))
                    total_steal += amount
                    log('【%s】收取好友能量：%s +%s' % (acc['remark'], d.get('friendNickName') or fid, amount))
                else:
                    log('【%s】收取好友能量失败：%s %s' % (acc['remark'], d.get('friendNickName') or fid, _short(r)))
                wait_random('好友能量')
        total = int(res.get('total') or 0)
        if not total or page * 20 >= total:
            break
        page += 1
    log('【%s】好友能量处理完成，本次约收取：%s' % (acc['remark'], total_steal))


# ============================================================
#  账号解析 / 主流程
# ============================================================
def parse_accounts(raw):
    out = []
    for i, line in enumerate(re.split(r'[&\n\r]+', raw or '')):
        line = line.strip()
        if not line:
            continue
        parts = line.split('#')
        aid = (parts.pop(0) or '').strip()
        remark = ('#'.join(parts) or aid or ('账号%d' % (i + 1))).strip()
        if aid:
            out.append({'raw': line, 'id': aid, 'remark': remark})
    return out


def run_account(acc):
    c = CACHE.get(acc['id']) or {'remark': acc['remark'], 'cuid': gen_cuid()}
    c['remark'] = acc['remark']
    if not c.get('cuid'):
        c['cuid'] = gen_cuid()
    CACHE[acc['id']] = c
    sum_ = {'account': acc['id'], 'remark': acc['remark'], 'point': '-', 'farmEnergy': '-', 'farmTomato': '-', 'reward': 0, 'error': ''}
    try:
        ensure_weimob_login(acc, c)
        wait_random('登录后')
        do_point_sign(acc, c, sum_)
        wait_random('进入农场')
        do_farm_all(acc, c, sum_)
    except Exception as e:
        sum_['error'] = str(e)
        log('【%s】账号异常：%s' % (acc['remark'], sum_['error']))
    SUMMARIES.append(sum_)
    save_cache(CACHE)


def print_summary():
    log('\n======== 本次汇总 ========')
    for s in SUMMARIES:
        if s['error']:
            log('当前账号：%s 当前备注：%s 当前积分：%s 农场能量：%s 茄币：%s 失败：%s' % (
                s['account'], s['remark'], s['point'], s['farmEnergy'], s['farmTomato'], s['error']))
        else:
            log('当前账号：%s 当前备注：%s 当前积分：%s 农场能量：%s 茄币：%s 本次积分签到获得：%s' % (
                s['account'], s['remark'], s['point'], s['farmEnergy'], s['farmTomato'], s['reward']))


def main():
    raw = ENV.get('WX_ID') or ENV.get('qhdwq') or ''
    accounts = parse_accounts(raw)
    if not accounts:
        log('未配置 WX_ID / qhdwq，格式：wxid_...#备注，多账号换行或 & 分隔')
        return
    log('统一梦时代：积分签到 + 茄子^_^皇农场全任务')
    log('账号变量：WX_ID；延迟：%d-%d 秒；缓存：%s' % (DELAY_MIN, DELAY_MAX, CACHE_FILE))
    for i, acc in enumerate(accounts):
        log('\n========== 账号 %d/%d：%s (%s) ==========' % (i + 1, len(accounts), acc['remark'], acc['id']))
        run_account(acc)
        if i < len(accounts) - 1:
            wait_random('账号间隔')
    print_summary()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log('脚本异常：%s' % (getattr(e, '__traceback__', None) and ''.join(traceback.format_exception(type(e), e, e.__traceback__)) or e))
        print_summary()
