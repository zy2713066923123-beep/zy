/*
 * name: 骆驼户外运动城签到
 * cron: 20 8 * * *
 *
 * 功能：微盟小程序「骆驼户外运动城」每日签到（签到有礼）。
 *       双协议登录：牛子(Wechat) + 应用宝(YYB)，统一走 ./getCode.js 路由获取 wx.login code / 手机号授权。
 *       参考 ./骆驼.js（同为微盟 wx3d2bdbf67041d80e）完善：loginX 登录 → 协议签署 → 会员激活 → 签到有礼 → 积分查询。
 *       签到业务参数已用抓包 HAR 校验（signMainInfo 实测成功）。
 *
 * 环境变量：
 *   WX_ID（推荐，与天乐短剧/getCode 一致）
 *     多账号用 & 或换行分隔，支持：
 *       wxid_xxx#备注            牛子协议（微信 wxid）
 *       openid#备注              应用宝 YYB 协议（openid 或数字 id）
 *       wx:xxx#备注 / yyb:openid#备注  兼容写法
 *     路由：openid/数字 id 自动走 YYB，其余走牛子。
 *
 * 可选：
 *   LUOTUO_DO_SIGNIN=1       是否签到，默认 1
 *   LUOTUO_QUERY_POINT=1     是否查询积分，默认 1
 *   LUOTUO_CONCURRENCY=3     多账号并发数，默认 3
 *   LUOTUO_CACHE=...json     缓存文件
 *   LUOTUO_DEBUG=1           打印完整接口响应
 *   LUOTUO_NO_MEMBER_BIND=1  不自动获取手机号/激活会员（status=3 时跳过签到）
 *   LUOTUO_DELAY_MIN=3       单步最小延迟秒，默认 3
 *   LUOTUO_DELAY_MAX=5       单步最大延迟秒，默认 5
 *   LUOTUO_TIMEOUT=25000     请求超时毫秒，默认 25000
 *   LUOTUO_RETRY=2           请求失败重试次数，默认 2
 *
 * 说明：签到活动由 wid 自动匹配，无需配置 activityId；
 *       若签到返回 status=3（不符合条件），自动尝试协议手机号授权并激活会员（WXLT 同款逻辑）。
 */

const axios = require('axios');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
require('events').defaultMaxListeners = 50;

const getCode = require('./getCode.js');
const getSingleCode = getCode.getSingleCode;
const getSinglePhoneEncrypted = getCode.getSinglePhoneEncrypted;
const { sendNotify } = require('../sendNotify.js');

// ============================================================
//  商户配置（loginX 来自 骆驼.js；业务参数来自抓包 HAR）
// ============================================================
const APPID = 'wx3d2bdbf67041d80e';
const XAPI = 'https://xapi.weimob.com';
const MP_VERSION = 93;
const BOS_ID = 4021451615601;
const LOGIN_VID = 6015691407601;    // loginX 登录 basicInfo 用（骆驼.js 确认）
const VID = 6016716403601;          // 业务接口用（抓包 HAR 实测成功）
const VID_TYPE = 10;
const CID = 420878601;
const MERCHANT_ID = 2000170906601;
const WX_TEMPLATE_ID = 8225;
const BOS_TEMPLATE_ID = 1000002277;
const PRODUCT_ID = 146;
const PRODUCT_INSTANCE_ID = 7133098601;
const PRODUCT_VERSION_ID = '14026';
const DEFAULT_AVATAR = 'https://image-c.weimobwmc.com/wrz/35389c90f9254cdd811561c18ab95daa.png';

// 会员激活常量（骆驼.js，同商户 wx3d2bdbf67041d80e）
const MEMBER_CONST = {
  memberPlanId: 800907451,
  memberSkuId: 351908,
  levelId: 514604451,
  groupId: 2214650,
  fieldId: 4216299,
  miniVersion: '13160',
  homeMiniVersion: 1390,
};

const CHILD_TEMPLATE_IDS = [
  { customId: 90004, version: 'crm@0.1.98' },
  { customId: 90002, version: 'ec@88.1' },
  { customId: 90006, version: 'hudong@0.0.255' },
  { customId: 90008, version: 'cms@0.0.534' },
  { customId: 90070, version: 'v1.0.42-20260622' },
];

// 接口路径
const LOGIN_API = '/fe/mapi/user/loginX';
const SIGN_QUERY_API = '/api3/onecrm/mactivity/sign/misc/sign/activity/c/signMainInfo';
const SIGN_API = '/api3/onecrm/mactivity/sign/misc/sign/activity/core/c/sign';
const POINTS_API = '/api3/onecrm/point/myPoint/getSimpleAccountInfo';
const PROTOCOL_LATEST = '/api3/passport/access/v2.0/protocol/hadSignedLatest';
const PROTOCOL_SIGN = '/api3/passport/access/v2.0/protocol/batchSign';
const MEMBER_LACK = '/api3/onecrm/user/center/bindcard/queryLackBridgeField';
const MEMBER_HOME = '/api3/onecrm/user/center/member/center/queryCardCenterHomePage';
const MEMBER_BIND = '/api3/onecrm/user/center/bindcard/manuaUserlBindCard';
const PHONE_DECRYPT = '/api3/user/getPhoneNumber';
const RELEVANCE_PHONES = '/api3/onecrm/mactivity/center/account/getRelevancePhonesByWid';
const GET_ACTIVITY_INFO = '/api3/onecrm/mactivity/sign/misc/sign/activity/core/c/getActivityInfo';

// 环境开关
const DO_SIGNIN = envFlag('LUOTUO_DO_SIGNIN', true);
const QUERY_POINT = envFlag('LUOTUO_QUERY_POINT', true);
const CONCURRENCY = Math.max(1, Number(process.env.LUOTUO_CONCURRENCY || 3));
const DEBUG = envFlag('LUOTUO_DEBUG', false);
const NO_MEMBER_BIND = envFlag('LUOTUO_NO_MEMBER_BIND', false);
const DELAY_MIN = Math.max(1, Number(process.env.LUOTUO_DELAY_MIN || 3));
const DELAY_MAX = Math.max(DELAY_MIN, Number(process.env.LUOTUO_DELAY_MAX || 5));
const TIMEOUT_MS = Number(process.env.LUOTUO_TIMEOUT || 25000);
const RETRY = Math.max(0, Number(process.env.LUOTUO_RETRY || 2));
const CACHE_FILE = String(process.env.LUOTUO_CACHE || path.join(__dirname, '骆驼户外运动城_cache.json'));

const UA = `Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.60(0x18003c2f) NetType/WIFI Language/zh_CN`;
const REFERER = `https://servicewechat.com/${APPID}/${MP_VERSION}/page-frame.html`;

// ============================================================
//  工具
// ============================================================
function log(message) {
  const ts = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  console.log(`${ts} ${message}`);
}

function envFlag(name, def) {
  const v = process.env[name];
  if (v === undefined || v === '') return def;
  return !(v === '0' || v === 'false' || v === 'off' || v === 'no');
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const randInt = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : crypto.randomBytes(16).toString('hex'));
const genCuid = () => `${Date.now()}${Math.random().toString(36).slice(2, 8)}`;
const short = (x, n = 500) => {
  try {
    const s = typeof x === 'string' ? x : JSON.stringify(x);
    return s.length > n ? s.slice(0, n) + '...' : s;
  } catch (e) {
    return String(x).slice(0, n);
  }
};

async function waitRandom(label) {
  const ms = randInt(DELAY_MIN * 1000, DELAY_MAX * 1000);
  if (DEBUG) log(`等待 ${Math.round(ms / 1000)}s：${label}`);
  await sleep(ms);
}

function isOk(x) {
  if (x === true) return true;
  if (!x || typeof x !== 'object') return false;
  if (x.errcode === 0 || x.errcode === '0') return true;
  if (x.code === 0 || x.code === '0') return true;
  return x.success === true && !x.error;
}

function firstNumber(...args) {
  for (const a of args) {
    const n = Number(a);
    if (Number.isFinite(n) && n >= 0) return n;
  }
  return null;
}

function rewardText(d) {
  if (!d) return '签到完成';
  const f = d.fixedReward || {};
  const e = d.extraReward || {};
  const points = Number(f.points || 0) + Number(e.points || 0);
  const growth = Number(f.growth || 0) + Number(e.growth || 0);
  const amount = Number(f.amount || 0) + Number(e.amount || 0);
  const coupon = Number(f.couponCount || 0) + Number(e.couponCount || 0);
  const parts = [];
  if (points) parts.push(`积分+${points}`);
  if (growth) parts.push(`成长值+${growth}`);
  if (amount) parts.push(`金额+${amount}`);
  if (coupon) parts.push(`券+${coupon}`);
  return parts.length ? parts.join(' ') : '签到完成（无额外奖励）';
}

function hasCurrentMemberLevel(data) {
  const s = JSON.stringify(data || {});
  return /"isCurrentUserLevel"\s*:\s*true/.test(s) || /"isObtained"\s*:\s*true/.test(s) || /"isMembership"\s*:\s*true/.test(s);
}

// ============================================================
//  请求体 / 请求头
// ============================================================
function buildBody(extra, refer) {
  const body = {
    appid: APPID,
    basicInfo: {
      vid: VID,
      vidType: VID_TYPE,
      bosId: BOS_ID,
      productId: PRODUCT_ID,
      productInstanceId: PRODUCT_INSTANCE_ID,
      productVersionId: PRODUCT_VERSION_ID,
      merchantId: MERCHANT_ID,
      tcode: 'weimob',
      cid: CID,
    },
    extendInfo: {
      wxTemplateId: WX_TEMPLATE_ID,
      childTemplateIds: CHILD_TEMPLATE_IDS,
      quickdeliver: { enable: false },
      analysis: [],
      youshu: { enable: false },
      bosTemplateId: BOS_TEMPLATE_ID,
      source: 1,
      channelsource: 5,
      refer: refer || 'onecrm-signgift',
      mpScene: 1005,
    },
    queryParameter: null,
    i18n: { language: 'zh', timezone: '8' },
    pid: '',
    storeId: '',
    customInfo: { source: 0, wid: 0 },
  };
  if (refer) body.extendInfo.refer = refer;
  if (extra) Object.assign(body, extra);
  return body;
}

function buildHeaders(account, opts) {
  opts = opts || {};
  const headers = {
    'Content-Type': 'application/json',
    'Accept': '*/*',
    'User-Agent': UA,
    'Referer': REFERER,
    'Cookie': `rprm_cuid=${(account && account.cuid) || genCuid()}`,
    'weimob-bosid': String(BOS_ID),
    'x-biz-id': String(opts.bizId || PRODUCT_ID),
    'x-wmsdk-vid': String(VID),
    'x-wmsdk-close-store': 'v2',
    'x-cms-sdk-request': '1.5.147',
    'x-req-from': opts.reqFrom || 'onecrm',
    'x-page-route': opts.pageRoute || 'onecrm/signgift',
    'x-component-is': opts.componentIs || 'onecrm/signgift',
    'x-apm-conversation-id': (account && account.apmConversationId) || (account && (account.apmConversationId = uuid())),
    'x-apm-page-id': uuid(),
    'x-apm-parent-page-id': uuid(),
    'x-wmsdk-bc': `1 ${Date.now()}`,
    'wos-x-channel': '0:TITAN',
  };
  if (account && account.token) headers['X-WX-Token'] = account.token;
  if (account && account.globalTicket) headers['x-cmssdk-vidticket'] = account.globalTicket;
  return headers;
}

async function weimobPost(apiPath, body, account, opts) {
  opts = opts || {};
  const headers = buildHeaders(account, opts);
  for (const k of Object.keys(headers)) {
    if (headers[k] == null || headers[k] === '') delete headers[k];
  }
  let lastErr;
  for (let attempt = 0; attempt <= RETRY; attempt += 1) {
    try {
      const resp = await axios.post(XAPI + apiPath, body, { headers, timeout: TIMEOUT_MS });
      const parsed = resp.data;
      if (parsed && parsed.globalTicket) account.globalTicket = parsed.globalTicket;
      if (DEBUG) log(`【微盟】${apiPath} => ${short(parsed, 600)}`);
      return parsed;
    } catch (e) {
      lastErr = e;
      const status = e.response && e.response.status;
      const data = e.response && e.response.data;
      if (attempt < RETRY) {
        if (DEBUG) log(`【微盟】${apiPath} 失败(${status || 'net'}) 重试 ${attempt + 1}`);
        await sleep(800 + randInt(0, 800));
      } else {
        lastErr = new Error(`请求 ${apiPath} 失败(${status || 'net'})：${short(data || e.message)}`);
      }
    }
  }
  throw lastErr;
}

// ============================================================
//  缓存
// ============================================================
function loadCache() {
  try {
    if (fs.existsSync(CACHE_FILE)) return JSON.parse(fs.readFileSync(CACHE_FILE, 'utf-8'));
  } catch (e) {
    log(`读取缓存失败：${e.message}`);
  }
  return {};
}

function saveCache(obj) {
  try {
    fs.writeFileSync(CACHE_FILE, JSON.stringify(obj, null, 2), 'utf-8');
  } catch (e) {
    log(`保存缓存失败：${e.message}`);
  }
}

let CACHE = loadCache();

// ============================================================
//  账号解析（双协议：牛子 + 应用宝）
// ============================================================
function isYybOpenid(id) {
  const raw = String(id || '').split('#')[0].trim();
  if (!raw) return false;
  if (/^\d+$/.test(raw)) return true;
  if (/^o[a-zA-Z0-9_-]{20,}$/.test(raw)) return true;
  return false;
}

// 协议路由：应用宝 openid/数字 id → yyb；其余（wxid_、wx:、用户自定义微信号等）→ wechat（牛子）
// 与 ./getCode.js 的 _detectProtocolForIdentifier 一致：正向识别应用宝 openid，其余一律当微信号，不做拒绝。
function detectProtocol(id) {
  const raw = String(id || '').split('#')[0].trim();
  if (raw.startsWith('yyb:')) return 'yyb';
  if (raw.startsWith('wx:') || raw.startsWith('wxid_')) return 'wechat';
  return isYybOpenid(raw) ? 'yyb' : 'wechat';
}

// 剥离协议前缀，得到传给 getCode 的真实 identifier
function stripProtocolPrefix(id) {
  const raw = String(id || '').trim();
  if (raw.startsWith('yyb:')) return raw.slice('yyb:'.length);
  if (raw.startsWith('wx:')) return raw.slice('wx:'.length);
  return raw;
}

function parseAccounts() {
  const raw = String(process.env.WX_ID || '').trim();
  if (!raw) {
    log('未配置环境变量 WX_ID');
    return [];
  }
  let index = 0;
  return raw
    .split(/[&\n]/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      index += 1;
      const first = line.split('#')[0].trim();
      if (!first) return null;
      // 路由判断：应用宝 openid → yyb，其余（含用户自定义微信号）→ wechat，不再拒绝账号
      const protocolType = detectProtocol(first);
      const identifier = stripProtocolPrefix(first);
      const remark = line.split('#').slice(1).join('#').trim() || identifier;
      return {
        index, raw: line, accountId: identifier, cacheKey: identifier,
        remark, isWechatProtocol: true, protocolType, identifier,
        token: '', wid: '', openId: '', globalTicket: '', cuid: genCuid(),
        apmConversationId: uuid(),
      };
    })
    .filter(Boolean);
}

// ============================================================
//  微盟登录：wx.login code -> loginX（返回 token/wid/openId）
// ============================================================
async function login(account) {
  const code = await getSingleCode(APPID, account.identifier);
  const body = {
    pid: '',
    extendInfo: { source: 1 },
    parentVid: 0,
    is_pre_fetch_open: true,
    env: 'production',
    storeId: '',
    appid: APPID,
    basicInfo: {
      bosId: String(BOS_ID),
      vid: String(LOGIN_VID),
      tcode: 'weimob',
      cid: String(CID),
    },
    code,
    queryAuthConfig: true,
    relevanceAuthRequest: null,
  };
  const resp = await weimobPost(LOGIN_API, body, account, { bizId: 1, reqFrom: 'cms', pageRoute: '', componentIs: '', skipToken: true });
  if (!isOk(resp) || !resp.data || !resp.data.token) {
    throw new Error(`微盟登录失败：${short(resp)}`);
  }
  const d = resp.data;
  account.token = d.token;
  account.wid = String(d.wid || (d.userInfo && d.userInfo.wid) || account.wid);
  account.openId = String(d.openId || d.openid || (d.userInfo && d.userInfo.openId) || account.openId);
  account.tokenExpire = Number(d.expireTime || d.latestExpireTime || (Date.now() + 24 * 3600 * 1000));
  log(`[${account.remark}] 登录成功：wid=${account.wid || '-'}, openId=${account.openId || '-'}`);
  CACHE[account.cacheKey] = {
    token: account.token, wid: account.wid, openId: account.openId,
    globalTicket: account.globalTicket, expire: account.tokenExpire, cuid: account.cuid,
    apmConversationId: account.apmConversationId,
  };
  saveCache(CACHE);
}

async function verifyToken(account) {
  const info = await signMainInfo(account);
  if (isOk(info) && info.data && typeof info.data.hasSign !== 'undefined') return true;
  const pt = await queryPoint(account);
  return isOk(pt);
}

async function ensureLogin(account) {
  const cached = CACHE[account.cacheKey];
  if (cached && cached.token && cached.wid && Number(cached.expire) > Date.now() + 10 * 60 * 1000) {
    account.token = cached.token;
    account.wid = cached.wid;
    account.openId = cached.openId;
    account.globalTicket = cached.globalTicket;
    account.cuid = cached.cuid || account.cuid;
    account.apmConversationId = cached.apmConversationId || account.apmConversationId;
    try {
      if (await verifyToken(account)) {
        log(`[${account.remark}] 缓存有效：wid=${account.wid}`);
        return;
      }
    } catch (e) {
      log(`[${account.remark}] 缓存探测异常，重新登录：${e.message}`);
    }
    log(`[${account.remark}] 缓存失效，重新登录`);
  }
  await login(account);
}

// ============================================================
//  协议签署（用户协议，非致命）
// ============================================================
async function ensureProtocolSigned(account) {
  try {
    const latest = await weimobPost(PROTOCOL_LATEST, buildBody({ displayScene: 1 }, 'cms-usercenter'), account, {
      bizId: 1, reqFrom: 'cms_design_components', pageRoute: 'cms_design/usercenter', componentIs: 'cms_design_components',
    });
    if (!isOk(latest)) {
      if (DEBUG) log(`[${account.remark}] 协议查询失败：${short(latest)}`);
      return;
    }
    if (latest.data && latest.data.hadSigned) return;
    const ids = (latest.data && latest.data.protocolIds) || [4602, 4603];
    const sign = await weimobPost(PROTOCOL_SIGN, buildBody({ protocolIdList: ids }, 'cms-usercenter'), account, {
      bizId: 1, reqFrom: 'cms_design_components', pageRoute: 'cms_design/usercenter', componentIs: 'cms_design_components',
    });
    if (isOk(sign) || sign === true || (sign && sign.data === true)) {
      log(`[${account.remark}] 已补签协议`);
    } else if (DEBUG) {
      log(`[${account.remark}] 协议签署失败：${short(sign)}`);
    }
  } catch (e) {
    if (DEBUG) log(`[${account.remark}] 协议签署异常：${e.message}`);
  }
}

// ============================================================
//  会员激活（status=3 时调用）
// ============================================================
async function ensureMember(account, force) {
  force = !!force;
  if (NO_MEMBER_BIND) {
    log(`[${account.remark}] 已设置 LUOTUO_NO_MEMBER_BIND=1，跳过会员激活`);
    return false;
  }

  const lack = await weimobPost(MEMBER_LACK, buildBody({}, 'onecrm-membership'), account, {
    bizId: PRODUCT_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/membership', componentIs: 'onecrm/membership',
  });
  if (!force && isOk(lack) && lack.data && lack.data.isMembership) {
    log(`[${account.remark}] 会员已激活`);
    return true;
  }

  const home = await weimobPost(MEMBER_HOME, buildBody({ miniVersion: MEMBER_CONST.homeMiniVersion }, 'onecrm-membership'), account, {
    bizId: PRODUCT_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/membership', componentIs: 'onecrm/membership',
  });
  if (!force && isOk(home) && hasCurrentMemberLevel(home.data)) {
    log(`[${account.remark}] 会员中心显示已入会`);
    return true;
  }

  log(`[${account.remark}] 尝试协议手机号授权并激活会员`);
  const grant = await getSinglePhoneEncrypted(APPID, account.identifier);
  let phone = grant.phone || account.phone || '';
  if (!phone && (grant.code || grant.encryptedData)) {
    const phoneResp = await weimobPost(PHONE_DECRYPT, buildBody({
      encryptedData: grant.encryptedData || '',
      iv: grant.iv || '',
      errMsg: 'getPhoneNumber:ok',
      code: grant.code || '',
    }, 'onecrm-membership'), account, {
      bizId: PRODUCT_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/membership', componentIs: 'onecrm/membership',
    });
    if (isOk(phoneResp)) {
      phone = (phoneResp.data && (phoneResp.data.phoneNumber || phoneResp.data.purePhoneNumber)) || '';
    } else {
      log(`[${account.remark}] 业务手机号解密失败：${short(phoneResp)}`);
    }
    await waitRandom('手机号后');
  }
  if (!phone) throw new Error('没有拿到手机号，无法自动激活会员');
  account.phone = phone;

  const bind = await weimobPost(MEMBER_BIND, buildBody(buildBindCardPayload(phone), 'onecrm-membership'), account, {
    bizId: PRODUCT_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/membership', componentIs: 'onecrm/membership',
  });
  if (!isOk(bind)) throw new Error('会员激活失败：' + short(bind));
  log(`[${account.remark}] 会员激活成功：cardNo=${(bind.data && bind.data.cardNo) || '-'} customCardNo=${(bind.data && bind.data.customCardNo) || '-'}`);
  saveCache(CACHE);
  return true;
}

function buildBindCardPayload(phone) {
  return {
    memberPlanId: MEMBER_CONST.memberPlanId,
    groupFieldInfos: [{
      fieldInfo: {
        groupWholeFieldInfos: [{
          fieldValues: [{
            fieldId: MEMBER_CONST.fieldId,
            fieldKey: 'phone',
            fieldName: '手机号',
            fieldStatus: 1,
            fieldType: 1,
            fieldValue: String(phone),
            groupId: MEMBER_CONST.groupId,
            groupNum: 0,
            guardian: '',
            isRequired: 1,
            isValueModifiable: 1,
            isValueUnique: 1,
            operationType: null,
            optionList: [],
            originalValue: '',
            ruleList: [{ limitType: null, max: 32, min: 0, ruleType: 3 }],
            sort: null,
            templateFieldId: null,
            tips: '请填写正确的手机号',
            valueType: 7,
          }],
        }],
      },
      groupId: MEMBER_CONST.groupId,
      groupName: '基础信息',
      key: 'basic',
      maxLimitGroup: null,
      repeatCount: 1,
      sort: 1,
    }],
    regionCode: '',
    inviteCode: '',
    memberSkuId: MEMBER_CONST.memberSkuId,
    levelId: MEMBER_CONST.levelId,
    pmcParamsInfo: {},
    urlParamsInfo: {
      productInstanceId: String(PRODUCT_INSTANCE_ID),
      vid: String(VID),
    },
    guardianRecordId: '',
    miniVersion: MEMBER_CONST.miniVersion,
  };
}

// ============================================================
//  签到 / 积分
// ============================================================
async function signMainInfo(account) {
  const body = buildBody({ customInfo: { source: 0, wid: Number(account.wid) } }, 'onecrm-signgift');
  return weimobPost(SIGN_QUERY_API, body, account, {
    bizId: PRODUCT_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/signgift', componentIs: 'onecrm/signgift',
  });
}

async function signAction(account) {
  const body = buildBody({ customInfo: { source: 0, wid: Number(account.wid) } }, 'onecrm-signgift');
  return weimobPost(SIGN_API, body, account, {
    bizId: PRODUCT_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/signgift', componentIs: 'onecrm/signgift',
  });
}

async function queryPoint(account) {
  const body = buildBody({ targetBasicInfo: { productInstanceId: PRODUCT_INSTANCE_ID }, request: {} }, 'cms-usercenter');
  const resp = await weimobPost(POINTS_API, body, account, {
    bizId: PRODUCT_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/membership', componentIs: 'onecrm/membership',
  });
  if (!isOk(resp)) throw new Error(`积分查询失败：${short(resp)}`);
  return resp.data || {};
}

function fillSignSummary(sum, data) {
  if (!data) return;
  const cont = firstNumber(
    data.activityCumulativeSignDays,
    data.signedDate,
    data.monthCumulativeSignDays,
    data.yearCumulativeSignDays,
    data.maxActivityContinueSignDays
  );
  if (cont != null) sum.continueDays = cont;
  if (data.keepSignDate != null) sum.nextRewardLeft = data.keepSignDate;
  sum.today = data.hasSign ? '已签' : '未签';
}

async function doSignin(account, sum) {
  let info = await signMainInfo(account);
  if (!isOk(info)) throw new Error(`查询签到信息失败：${short(info)}`);
  fillSignSummary(sum, info.data);

  if (info.data && info.data.hasSign) {
    sum.reward = '今日已签';
    log(`[${account.remark}] 今日已签 | 连续${sum.continueDays}天 | 距下一档奖励还差${sum.nextRewardLeft}天`);
    return;
  }

  if (Number(info.data && info.data.status) === 3) {
    log(`[${account.remark}] 未满足签到条件，尝试激活会员`);
    await ensureMember(account, false);
    await waitRandom('会员后刷新签到');
    info = await signMainInfo(account);
    fillSignSummary(sum, info.data);
  }

  if (!(info.data && info.data.hasSign)) {
    // 非致命的关联查询，部分商户需要
    await weimobPost(RELEVANCE_PHONES, buildBody({ customInfo: { source: 0, wid: Number(account.wid) } }, 'onecrm-signgift'), account, {
      bizId: PRODUCT_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/signgift', componentIs: 'onecrm/signgift',
    }).catch(() => null);
    await weimobPost(GET_ACTIVITY_INFO, buildBody({ customInfo: { source: 0, wid: Number(account.wid) } }, 'onecrm-signgift'), account, {
      bizId: PRODUCT_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/signgift', componentIs: 'onecrm/signgift',
    }).catch(() => null);

    await waitRandom('准备签到');
    let sign = await signAction(account);

    if (!isOk(sign) && !NO_MEMBER_BIND) {
      log(`[${account.remark}] 签到失败，重试会员后签到`);
      await ensureMember(account, true);
      await waitRandom('重试签到');
      sign = await signAction(account);
    }

    if (!isOk(sign)) throw new Error('签到失败：' + short(sign));
    sum.reward = rewardText(sign.data);
    sum.today = '已签';
    log(`[${account.remark}] 签到成功 | ${sum.reward}`);
  } else {
    sum.reward = '今日已签';
    sum.today = '已签';
    log(`[${account.remark}] 今日已签`);
  }
}

// ============================================================
//  单账号执行
// ============================================================
async function runAccount(account) {
  const sum = {
    account: account.identifier, remark: account.remark, point: '-',
    continueDays: '-', nextRewardLeft: '-', today: '-', reward: '-', error: '',
  };
  log(`\n====== 账号 ${account.index} ${account.remark} ${account.identifier} [${account.protocolType}] ======`);
  try {
    await ensureLogin(account);
    await waitRandom('进入签到');
    await ensureProtocolSigned(account);
    await waitRandom('签到前');

    if (DO_SIGNIN) {
      await doSignin(account, sum);
    } else {
      sum.reward = '未启用签到';
    }

    if (QUERY_POINT) {
      try {
        const pts = await queryPoint(account);
        sum.point = (pts.availablePoint != null ? pts.availablePoint : pts.sumAvailablePoint) != null
          ? (pts.availablePoint != null ? pts.availablePoint : pts.sumAvailablePoint)
          : '-';
        log(`[${account.remark}] 当前积分：${sum.point}`);
      } catch (e) {
        log(`[${account.remark}] 积分查询出错：${e.message}`);
      }
    }

    const after = await signMainInfo(account).catch(() => null);
    if (isOk(after)) fillSignSummary(sum, after.data);

    log(`[${account.remark}] 结果：积分 ${sum.point} | 连续 ${sum.continueDays} 天 | 今日 ${sum.today} | ${sum.reward}`);
  } catch (e) {
    sum.error = e.message.slice(0, 200);
    log(`[${account.remark}] 执行出错：${e.message}`);
  }
  return sum;
}

// ============================================================
//  并发控制
// ============================================================
async function runWithConcurrency(items, worker, concurrency) {
  const results = [];
  let cursor = 0;
  async function next() {
    while (cursor < items.length) {
      const current = cursor;
      cursor += 1;
      results[current] = await worker(items[current]);
    }
  }
  const pool = [];
  for (let i = 0; i < Math.min(concurrency, items.length); i += 1) pool.push(next());
  await Promise.all(pool);
  return results;
}

// ============================================================
//  主流程
// ============================================================
async function main() {
  const accounts = parseAccounts();
  if (accounts.length === 0) {
    log('没有可执行的账号，结束。');
    return;
  }
  log(`开始执行... 共 ${accounts.length} 个账号，并发 ${CONCURRENCY}`);

  const results = await runWithConcurrency(accounts, runAccount, CONCURRENCY);

  log('\n======== 本次汇总 ========');
  const lines = [];
  for (const s of results) {
    let line;
    if (s.error) {
      line = `当前账号：${s.account} 当前备注：${s.remark} 当前积分：${s.point} 连续签到：${s.continueDays}天 今日：${s.today} 失败：${s.error}`;
    } else {
      line = `当前账号：${s.account} 当前备注：${s.remark} 当前积分：${s.point} 连续签到：${s.continueDays}天 今日：${s.today} 本次：${s.reward}`;
    }
    log(line);
    lines.push(line);
  }

  if (typeof sendNotify === 'function') {
    try {
      await sendNotify('骆驼户外运动城签到', lines.join('\n'));
    } catch (e) {
      log(`通知发送失败：${e.message}`);
    }
  }
  log('\n完成 ✅');
}

main().catch((e) => {
  log(`运行异常：${e.message}`);
  process.exit(1);
});

/*
 * ============================================================
 *  HAR 校验 + 骆驼.js 参考 要点
 * ============================================================
 * 登录：/fe/mapi/user/loginX（basicInfo.vid = 6015691407601）
 * 查询：/api3/onecrm/mactivity/sign/misc/sign/activity/c/signMainInfo（vid = 6016716403601，HAR 实测成功）
 * 签到：/api3/onecrm/mactivity/sign/misc/sign/activity/core/c/sign
 * 积分：/api3/onecrm/point/myPoint/getSimpleAccountInfo
 * 协议：/api3/passport/access/v2.0/protocol/{hadSignedLatest,batchSign}
 * 会员：/api3/onecrm/user/center/bindcard/{queryLackBridgeField,manuaUserlBindCard}
 *       /api3/onecrm/user/center/member/center/queryCardCenterHomePage
 * 手机号解密：/api3/user/getPhoneNumber
 * 签到连续天数取 activityCumulativeSignDays；keepSignDate 为距下一档奖励剩余天数。
 * 签到活动由 customInfo.wid 自动匹配，无需 activityId。
 */
