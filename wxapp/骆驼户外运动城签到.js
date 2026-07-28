/*
 * name: 骆驼户外运动城签到
 * cron: 20 8,19 * * *
 *
 * 功能：微盟小程序「骆驼户外运动城」每日签到（签到有礼）。
 *       双协议登录：牛子(Wechat) + 应用宝(YYB)，统一走 ./getCode.js 路由获取 wx.login code。
 *       移植自统一梦时代.py（同为微盟小程序），签到接口路径与请求体已用抓包 HAR 校验。
 *
 * 环境变量：
 *   WX_ID（推荐）
 *     多账号用 & 或换行分隔，支持：
 *       wxid_xxx#备注            牛子协议（微信 wxid）
 *       openid#备注              应用宝 YYB 协议（openid 或数字 id）
 *       wx:xxx#备注              牛子协议
 *       yyb:openid#备注          应用宝 YYB 协议（兼容旧写法）
 *     路由规则：openid/数字 id 自动走 YYB，其余走牛子，与 ./getCode.js 一致。
 *
 * 可选：
 *   WECHAT_SERVER=http://127.0.0.1:8011   牛子协议服务（默认，由 getCode.js 读取）
 *   YYB_SERVER=http://127.0.0.1:8000      应用宝服务（由 getCode.js 读取）
 *   LUOTUO_DO_SIGNIN=1                    是否签到，默认 1
 *   LUOTUO_QUERY_POINT=1                  是否查询积分，默认 1
 *   LUOTUO_CONCURRENCY=3                  多账号并发数，默认 3
 *   LUOTUO_CACHE=骆驼户外运动城_cache.json  缓存文件
 *   LUOTUO_DEBUG=1                        打印完整接口响应
 *
 * 说明：签到活动由 wid 自动匹配，无需配置 activityId。
 *       若签到返回 status=3（不符合条件），通常是未激活会员；如需自动激活会员，
 *       请提供抓包到的会员开卡接口参数（本脚本默认跳过该类账号的签到）。
 */

const axios = require('axios');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
require('events').defaultMaxListeners = 50;

const getCode = require('./getCode.js');
const getSingleCode = getCode.getSingleCode;
const { sendNotify } = require('../sendNotify.js');

// ============================================================
//  商户配置（已用抓包 HAR 校验）
// ============================================================
const APPID = 'wx3d2bdbf67041d80e';
const XAPI = 'https://xapi.weimob.com';           // :authority 实测为 xapi.weimob.com
const BOS_ID = 4021451615601;
const VID = 6016716403601;                          // 抓包真实值（≠源码误提取的 6015691407601）
const CID = 420878601;
const MERCHANT_ID = 2000170906601;
const WX_TEMPLATE_ID = 8225;
const BIZ_ID = 146;                                 // crm 产品 productId
const PRODUCT_ID = 146;
const PRODUCT_INSTANCE_ID = 7133098601;             // 抓包真实值
const PRODUCT_VERSION_ID = '14026';
const BOS_TEMPLATE_ID = 1000002277;
const DEFAULT_AVATAR = 'https://image-c.weimobwmc.com/wrz/35389c90f9254cdd811561c18ab95daa.png';

const SIGN_QUERY_API = '/api3/onecrm/mactivity/sign/misc/sign/activity/c/signMainInfo';
const SIGN_API = '/api3/onecrm/mactivity/sign/misc/sign/activity/core/c/sign';
const POINTS_API = '/api3/onecrm/point/myPoint/getSimpleAccountInfo';
const LOGIN_API = '/fe/mapi/user/loginUserInfoX';

const DO_SIGNIN = envFlag('LUOTUO_DO_SIGNIN', true);
const QUERY_POINT = envFlag('LUOTUO_QUERY_POINT', true);
const CONCURRENCY = Math.max(1, Number(process.env.LUOTUO_CONCURRENCY || 3));
const DEBUG = envFlag('LUOTUO_DEBUG', false);
const CACHE_FILE = String(process.env.LUOTUO_CACHE || path.join(__dirname, '骆驼户外运动城_cache.json'));

const UA = `Mozilla/5.0 (Linux; Android 15; M2012K11AC Build/AQ3A.250226.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.178 Mobile Safari/537.36 XWEB/1460249 MMWEBSDK/20260502 MicroMessenger/8.0.76.3141(0x28004C38) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN MiniProgramEnv/android`;

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
const uuid = () => crypto.randomUUID();
const genCuid = () => `${Date.now()}${crypto.randomBytes(3).toString('hex')}`;
const short = (x, n = 300) => {
  try {
    const s = JSON.stringify(x);
    return s.length > n ? s.slice(0, n) + '...' : s;
  } catch (e) {
    return String(x).slice(0, n);
  }
};

function isOk(x) {
  if (!x || typeof x !== 'object') return false;
  if (x.errcode === 0 || x.errcode === '0') return true;
  if (x.code === 0 || x.code === '0') return true;
  return x.success === true && !x.error;
}

// ============================================================
//  请求体 / 请求头（对齐抓包 HAR）
// ============================================================
function buildBody(extra, refer) {
  const body = {
    appid: APPID,
    basicInfo: {
      vid: VID,
      vidType: 10,
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
      childTemplateIds: [
        { customId: 90004, version: 'crm@0.1.98' },
        { customId: 90002, version: 'ec@88.1' },
        { customId: 90006, version: 'hudong@0.0.255' },
        { customId: 90008, version: 'cms@0.0.534' },
        { customId: 90070, version: 'v1.0.42-20260622' },
      ],
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
  const ticket = (account && account.globalTicket) ||
    `${17504}-${Math.floor(Date.now() / 1000)}.083-saas-w1-1684-${Math.floor(Math.random() * 1e11)}`;
  return {
    'Content-Type': 'application/json',
    'Accept': '*/*',
    'User-Agent': UA,
    'Referer': `https://servicewechat.com/${APPID}/93/page-frame.html`,
    'Cookie': `rprm_cuid=${(account && account.cuid) || genCuid()}`,
    'X-WX-Token': (account && account.token) || '',
    'weimob-bosid': String(BOS_ID),
    'weimob-pid': 'N/A',
    'wos-x-channel': '0:TITAN',
    'x-biz-id': String(opts.bizId || BIZ_ID),
    'x-wmsdk-vid': String(VID),
    'x-wmsdk-close-store': 'v2',
    'x-cms-sdk-request': '1.5.147',
    'x-req-from': opts.reqFrom || 'onecrm',
    'x-page-route': opts.pageRoute || 'onecrm/signgift',
    'x-component-is': opts.componentIs || 'onecrm/signgift',
    'x-apm-conversation-id': uuid(),
    'x-apm-page-id': uuid(),
    'x-apm-parent-page-id': uuid(),
    'x-wmsdk-bc': `1 ${Date.now()}`,
    'x-cmssdk-vidticket': ticket,
  };
}

async function weimobPost(apiPath, body, account, opts) {
  opts = opts || {};
  const headers = buildHeaders(account, opts);
  try {
    const resp = await axios.post(XAPI + apiPath, body, { headers, timeout: 15000 });
    const parsed = resp.data;
    if (parsed && parsed.globalTicket) account.globalTicket = parsed.globalTicket;
    if (DEBUG) log(`【微盟】${apiPath} => ${short(parsed, 600)}`);
    return parsed;
  } catch (e) {
    const status = e.response && e.response.status;
    const data = e.response && e.response.data;
    throw new Error(`请求 ${apiPath} 失败(${status || 'net'})：${short(data || e.message)}`);
  }
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

function isProtocolIdentifier(id) {
  const raw = String(id || '');
  return raw.startsWith('wxid_') || raw.startsWith('wx:') || raw.startsWith('yyb:') || isYybOpenid(raw);
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
      if (!isProtocolIdentifier(first)) {
        log(`账号 ${index} 不是协议账号标识（应形如 wxid_xxx#备注 或 openid#备注），已跳过`);
        return null;
      }
      let protocolType;
      let identifier;
      if (first.startsWith('yyb:')) {
        protocolType = 'yyb';
        identifier = first.slice('yyb:'.length);
      } else if (isYybOpenid(first)) {
        protocolType = 'yyb';
        identifier = first;
      } else {
        protocolType = 'wechat';
        identifier = first;
      }
      const remark = line.split('#').slice(1).join('#').trim() || identifier;
      return {
        index, raw: line, accountId: identifier, cacheKey: identifier,
        remark, isWechatProtocol: true, protocolType, identifier,
        token: '', wid: '', openId: '', globalTicket: '', cuid: genCuid(),
      };
    })
    .filter(Boolean);
}

// ============================================================
//  微盟登录：wx.login code -> loginUserInfoX（返回 token/wid/openId）
// ============================================================
async function login(account) {
  const code = await getSingleCode(APPID, account.identifier);
  const body = buildBody({
    code,
    getUserProfile: true,
    nickName: account.remark || '微信用户',
    avatarUrl: DEFAULT_AVATAR,
  }, 'cms-usercenter');

  const resp = await weimobPost(LOGIN_API, body, account, {
    bizId: BIZ_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/membership', componentIs: 'onecrm/membership',
  });
  if (!isOk(resp) || !resp.data || !resp.data.token) {
    throw new Error(`微盟登录失败：${short(resp)}`);
  }
  const d = resp.data;
  account.token = d.token;
  account.wid = String(d.wid || (d.userInfo && d.userInfo.wid) || account.wid);
  account.openId = String(d.openId || d.openid || (d.userInfo && d.userInfo.openId) || account.openId);
  const expire = Number(d.expireTime || d.latestExpireTime || (Date.now() + 24 * 3600 * 1000));
  account.tokenExpire = expire;
  log(`[${account.remark}] 登录成功：wid=${account.wid || '-'}, openId=${account.openId || '-'}`);
  CACHE[account.cacheKey] = {
    token: account.token, wid: account.wid, openId: account.openId,
    globalTicket: account.globalTicket, expire, cuid: account.cuid,
  };
  saveCache(CACHE);
}

async function ensureLogin(account) {
  const cached = CACHE[account.cacheKey];
  if (cached && cached.token && cached.wid && Number(cached.expire) > Date.now() + 10 * 60 * 1000) {
    account.token = cached.token;
    account.wid = cached.wid;
    account.openId = cached.openId;
    account.globalTicket = cached.globalTicket;
    account.cuid = cached.cuid || account.cuid;
    // 用签到查询作为 token 有效性探针
    try {
      const probe = await signMainInfo(account);
      if (isOk(probe)) {
        log(`[${account.remark}] 缓存有效：wid=${account.wid}`);
        return;
      }
    } catch (e) {
      log(`[${account.remark}] 缓存探测异常，重新登录：${e.message}`);
    }
    log(`[${account.remark}] 缓存失效，重新协议登录`);
  }
  await login(account);
}

// ============================================================
//  签到 / 积分
// ============================================================
async function signMainInfo(account) {
  const body = buildBody({ customInfo: { source: 0, wid: Number(account.wid) } }, 'onecrm-signgift');
  return weimobPost(SIGN_QUERY_API, body, account, {
    bizId: BIZ_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/signgift', componentIs: 'onecrm/signgift',
  });
}

async function signAction(account) {
  const body = buildBody({ customInfo: { source: 0, wid: Number(account.wid) } }, 'onecrm-signgift');
  return weimobPost(SIGN_API, body, account, {
    bizId: BIZ_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/signgift', componentIs: 'onecrm/signgift',
  });
}

async function queryPoint(account) {
  const body = buildBody({ targetBasicInfo: { productInstanceId: PRODUCT_INSTANCE_ID }, request: {} }, 'cms-usercenter');
  const resp = await weimobPost(POINTS_API, body, account, {
    bizId: BIZ_ID, reqFrom: 'onecrm', pageRoute: 'onecrm/membership', componentIs: 'onecrm/membership',
  });
  if (!isOk(resp)) throw new Error(`积分查询失败：${short(resp)}`);
  return resp.data || {};
}

async function doSignin(account) {
  const info = await signMainInfo(account);
  if (!isOk(info)) throw new Error(`查询签到信息失败：${short(info)}`);
  const d = info.data || {};
  if (d.hasSign) {
    log(`[${account.remark}] 今日已签到（连续 ${d.keepSignDate || 0} 天）`);
    return { alreadySigned: true, keepSignDate: d.keepSignDate };
  }
  if (d.status === 3) {
    log(`[${account.remark}] 不符合签到条件（可能需激活会员），跳过签到`);
    return { skipped: true, reason: 'member' };
  }
  await sleep(800 + Math.floor(Math.random() * 800));
  const sign = await signAction(account);
  if (!isOk(sign)) {
    const msg = (sign && sign.errmsg) || '';
    if (msg.includes('不符合') || (sign && sign.status === 3)) {
      log(`[${account.remark}] 签到不符合条件（可能需激活会员），跳过`);
      return { skipped: true, reason: 'member' };
    }
    throw new Error(`签到失败：${short(sign)}`);
  }
  const sd = sign.data || {};
  const pts = (sd.fixedReward && sd.fixedReward.points) || 0;
  log(`[${account.remark}] 签到成功：积分+${pts}`);
  return { success: true, points: pts };
}

// ============================================================
//  单账号执行
// ============================================================
async function runAccount(account) {
  const result = { remark: account.remark, identifier: account.identifier, status: '失败', detail: '', point: '-' };
  try {
    log(`\n====== 账号 ${account.index} ${account.remark} ${account.identifier} [${account.protocolType}] ======`);
    await ensureLogin(account);

    if (QUERY_POINT) {
      try {
        const pts = await queryPoint(account);
        result.point = pts.availablePoint != null ? pts.availablePoint : (pts.sumAvailablePoint != null ? pts.sumAvailablePoint : '-');
        log(`[${account.remark}] 当前积分：${result.point}`);
      } catch (e) {
        log(`[${account.remark}] 积分查询出错：${e.message}`);
      }
    }

    if (DO_SIGNIN) {
      const r = await doSignin(account);
      result.detail = r.alreadySigned ? '今日已签到' : (r.skipped ? '跳过(需会员)' : `签到+${r.points || 0}分`);
    } else {
      result.detail = '未启用签到';
    }
    result.status = '成功';
  } catch (e) {
    result.status = '失败';
    result.detail = e.message.slice(0, 200);
    log(`[${account.remark}] 执行出错：${e.message}`);
  }
  return result;
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
  for (const r of results) {
    const line = `账号 ${r.remark}（${r.identifier}）：${r.status} 积分=${r.point} ${r.detail}`;
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
 *  已校验的关键参数（来自抓包 HAR，2026-07-28）
 * ============================================================
 * 请求 URL：https://xapi.weimob.com/api3/onecrm/mactivity/sign/misc/sign/activity/c/signMainInfo
 * 登录接口：/fe/mapi/user/loginUserInfoX
 * 签到动作：/api3/onecrm/mactivity/sign/misc/sign/activity/core/c/sign
 * 积分接口：/api3/onecrm/point/myPoint/getSimpleAccountInfo
 *
 * 固定商户参数：
 *   AppID            = wx3d2bdbf67041d80e
 *   bosId            = 4021451615601
 *   vid              = 6016716403601
 *   cid              = 420878601
 *   merchantId       = 2000170906601
 *   productId        = 146
 *   productInstanceId= 7133098601
 *   productVersionId = 14026
 *   wxTemplateId     = 8225
 *   bosTemplateId    = 1000002277
 *
 * 签到请求体核心：customInfo.wid（来自登录态），活动由 wid 自动匹配，无需 activityId。
 */
