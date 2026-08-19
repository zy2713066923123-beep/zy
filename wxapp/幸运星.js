// -*- coding: utf-8 -*-
/**
 * qinglong-ele-luckystar.js — 饿了么「幸运星/闪购」青龙面板一键脚本（单文件、自包含）
 *
 * 功能（全部纯 Node 接口调用，无需浏览器 / 真实浏览 / App WebView）：
 *   1. 每日签到（signinandreceive）
 *   2. 自动完成所有 PAGEVIEW 任务（pageview 上报 → RUNNING→FINISH）
 *   3. 自动领取全部已完成任务的奖励（receiveprize）
 *   4. 支持多账号逐个处理
 *   5. 支持青龙通知（sendNotify）
 *
 * ===================== 部署与运行说明 =====================
 *
 * 【目录依赖】本文件所在目录（wxapp/）需包含：
 *   - getCode.js      取码模块（连微信协议服务拉取 login code，必需）
 *   - eleme_assets/   阿里 fireye/AWSC 算法资源，生成 bx-ua/mini-janus 等风控头
 *                     （必需；缺少时 getcode 自动兑换会被风控拦截）
 *   运行前请确保整目录随本脚本一起部署（青龙脚本目录）。
 *
 * 【登录方式】三种，按优先级自动选择：
 *   方式 A（推荐·自动）：WX_ID 配置微信账号 → getCode 取 code → login.do 兑换 Cookie
 *   方式 B（注入）：      ELEME_LOGIN_RESULT=<抓包得到的有效 cookie 或 x-smallstc JSON>
 *   方式 C（兼容旧）：    ELEME_COOKIE=<H5 Cookie>（老用户平滑迁移）
 *
 * 【环境变量】
 *   WX_ID               微信账号标识（openid 或 wxid#备注），多账号换行 或 & 分隔（必填）
 *   WECHAT_SERVER       牛子协议服务地址，默认 http://192.168.6.222:8011（可选）
 *   YYB_SERVER          应用宝服务地址（可选）
 *   ELEME_APPID         饿了么小程序 AppID，默认 wxece3a9a4c82f58c9（可选）
 *   ELEME_LOGIN_RESULT  直接注入有效登录态（可选，走方式 B）
 *   ELEME_COOKIE        H5 Cookie（可选，走方式 C）
 *
 * 【青龙面板】
 *   1. 配置 WX_ID 等环境变量（见上）。
 *   2. 「脚本管理」上传整个 wxapp 目录。
 *   3. 新建定时任务指向 幸运星.js，任务类型选「node」或 shell 命令：
 *        node 幸运星.js
 *   4. （可选）配置青龙通知渠道，运行结束自动推送结果。
 *
 * 【命令行参数】
 *   --dry          只查询不完成/不领取
 *   --view-ms <ms> 每次浏览模拟时长（默认 30000）
 *   --only <id>    仅处理指定 missionDefId
 *   --no-notify    禁用通知
 */
'use strict';

/* =====================================================================
 * 第 1 部分：饿了么 mtop 纯算核心（内联，避免青龙 require 本地模块）
 * ===================================================================== */
const crypto = require('crypto');
const https = require('https');

const DEFAULT_CONFIG = {
  appKey: '12574478',
  ua: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 AliApp(TB/10.59.40) WindVane/8.7.2',
  referer: 'https://tb.ele.me/app/TBTakeout/engage-hub/home',
  bizScene: 'interact_center',
  accountPlan: 'HAVANA_COMMON',
  longitude: 119.842406,
  latitude: 31.276809,
  missionCollectionId: 3112,
  ASAC: {
    PAGEVIEW: 'alscFS8BNTO6jivYS7XOAM',
    PRIZE: 'alscadOjfleDPawx9zVoT0',
    SIGNIN: 'alsc3Lhy681SA5TT4iHgL3',
    EXCHANGE: 'alsc5KvbdX5mHl3sdv4guV'
  }
};

class EleMtop {
  constructor(cookieStr, config = {}) {
    this.cfg = { ...DEFAULT_CONFIG, ...config };
    // 清理 Cookie：去除所有换行/回车/多余空白，避免 HTTP header 报错
    this.cookieJar = (cookieStr || '').replace(/[\r\n\t]+/g, '; ').replace(/;+/g, ';').replace(/\s*;\s*/g, '; ').replace(/;\s*$/, '').trim();
    this._tokenRefreshed = false;
  }

  getCookie(name) {
    const m = new RegExp('(?:^|;\\s*)' + name + '=([^;]*)').exec(this.cookieJar);
    return m ? decodeURIComponent(m[1]) : '';
  }
  _absorbSetCookie(arr) {
    if (!arr) return;
    for (const sc of arr) {
      const first = sc.split(';')[0];
      const eq = first.indexOf('=');
      if (eq <= 0) continue;
      const name = first.slice(0, eq).trim();
      const val = first.slice(eq + 1).trim();
      this.cookieJar = this.cookieJar.replace(new RegExp('(?:^|;\\s*)' + name + '=[^;]*'), '');
      this.cookieJar = (this.cookieJar.replace(/^;|;$/g, '').replace(/;;+/g, ';') + '; ' + name + '=' + val).trim();
    }
  }
  setCookie(str) { this.cookieJar = str; }

  _md5(s) { return crypto.createHash('md5').update(s, 'utf8').digest('hex'); }
  _request(url, headers) {
    return new Promise((resolve, reject) => {
      const u = new URL(url);
      const req = https.request(u, { method: 'GET', headers }, (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString('utf8') }));
      });
      req.on('error', reject);
      req.end();
    });
  }
  _baseHeaders(extra = {}) {
    return { 'User-Agent': this.cfg.ua, 'Referer': this.cfg.referer, 'Cookie': this.cookieJar, ...extra };
  }

  async refreshToken() {
    // 注意: mtop.common.getTimestamp 不下发 _m_h5_tk, 必须用会 set-cookie 的接口
    // 实测 mtop.alsc.user.session.ele.check 会下发 _m_h5_tk/_m_h5_tk_enc
    const t = Date.now();
    const sign = this._md5(`-1&${t}&${this.cfg.appKey}&{}`);
    const url = `https://waimai-guide.ele.me/h5/mtop.alsc.user.session.ele.check/1.0/?jsv=2.7.5&appKey=${this.cfg.appKey}&t=${t}&sign=${sign}&api=mtop.alsc.user.session.ele.check&v=1.0&type=originaljson&dataType=json&data=${encodeURIComponent('{}')}`;
    const res = await this._request(url, this._baseHeaders());
    this._absorbSetCookie(res.headers['set-cookie']);
    this._tokenRefreshed = true;
    return this.getCookie('_m_h5_tk');
  }
  async ensureToken() {
    let token = this.getCookie('_m_h5_tk').split('_')[0];
    if (!token || !this._tokenRefreshed) {
      await this.refreshToken();
      token = this.getCookie('_m_h5_tk').split('_')[0];
    }
    return token;
  }

  async call(apiName, data = {}, v = '1.0', headers = {}) {
    const token = await this.ensureToken();
    const t = String(Date.now());
    const dataStr = JSON.stringify(data);
    const sign = this._md5(`${token}&${t}&${this.cfg.appKey}&${dataStr}`);
    const url = new URL(`https://waimai-guide.ele.me/h5/${apiName}/${v}/5.0/`);
    url.searchParams.set('jsv', '2.7.5');
    url.searchParams.set('appKey', this.cfg.appKey);
    url.searchParams.set('mainDomain', 'ele.me');
    url.searchParams.set('subDomain', 'waimai-guide');
    url.searchParams.set('pageDomain', 'ele.me');
    url.searchParams.set('H5Request', 'true');
    url.searchParams.set('ttid', 'h5@Web_android_11.22.143');
    url.searchParams.set('SV', '5.0');
    url.searchParams.set('type', 'originaljson');
    url.searchParams.set('dataType', 'json');
    url.searchParams.set('timeout', '10000');
    url.searchParams.set('t', t);
    url.searchParams.set('sign', sign);
    url.searchParams.set('data', dataStr);
    const res = await this._request(url.toString(), this._baseHeaders(headers));
    this._absorbSetCookie(res.headers['set-cookie']);
    let json;
    try { json = JSON.parse(res.body); } catch (e) { json = { raw: res.body }; }
    return { status: res.status, json, body: res.body };
  }

  commonParams(extra = {}) {
    return {
      bizScene: this.cfg.bizScene,
      accountPlan: this.cfg.accountPlan,
      longitude: this.cfg.longitude,
      latitude: this.cfg.latitude,
      locationInfos: JSON.stringify([JSON.stringify({ lng: this.cfg.longitude, lat: this.cfg.latitude })]),
      ...extra
    };
  }

  async homepage() {
    return this.call('mtop.alsc.interact.et.interact.center.homepage', this.commonParams());
  }
  async querytask() {
    return this.call('mtop.ele.biz.growth.task.core.querytask', this.commonParams({ missionCollectionId: this.cfg.missionCollectionId }));
  }
  async pageview(opt) {
    const data = this.commonParams({
      sync: true,
      collectionId: opt.collectionId || this.cfg.missionCollectionId,
      missionId: opt.missionId,
      pageFrom: opt.pageFrom || 'a2ogi.bx1500380',
      asac: this.cfg.ASAC.PAGEVIEW,
      actionCode: opt.actionCode || 'PAGEVIEW',
      viewTime: opt.viewTime || 30000
    });
    return this.call('mtop.ele.biz.growth.task.event.pageview', data, '1.1');
  }
  async receiveprize(opt) {
    const o = {
      missionCollectionId: opt.missionCollectionId || this.cfg.missionCollectionId,
      missionId: opt.missionId,
      asac: this.cfg.ASAC.PRIZE
    };
    if (opt.instanceId) o.instanceId = opt.instanceId;
    if (opt.count != null) o.count = opt.count;
    if (opt.sum != null) o.sum = opt.sum;
    return this.call('mtop.ele.biz.growth.task.core.receiveprize', this.commonParams(o));
  }
  async receivetask(opt) {
    const o = {
      missionCollectionId: opt.missionCollectionId || this.cfg.missionCollectionId,
      missionId: opt.missionId
    };
    return this.call('mtop.ele.biz.growth.task.core.receivetask', this.commonParams(o));
  }
  async signinandreceive(copyId, actId) {
    const data = this.commonParams({ copyId, actId: actId || '' });
    return this.call('mtop.alsc.interact.playapp.signin.component.signinandreceive', data, '1.0', { asac: this.cfg.ASAC.SIGNIN });
  }
}

/* =====================================================================
 * 第 2 部分：青龙兼容封装（环境变量读取 / 多账号 / 通知）
 * ===================================================================== */
const fs = require('fs');
const path = require('path');
// 共享微信小程序 code 获取模块（同目录 wxapp/getCode.js），自动路由牛子/应用宝
let getSingleCode = null;
try {
  getSingleCode = require('./getCode.js').getSingleCode;
} catch (e) {
  try { getSingleCode = require('./wxapp/getCode.js').getSingleCode; } catch (e2) { getSingleCode = null; }
}

// 饿了么小程序 AppID（点餐小程序）。若实际取码用不同 AppID 可通过环境变量覆盖：
//   ELEME_APPID=wxXXXXXXXX
const ELEME_APPID = (process.env.ELEME_APPID || '').trim() || 'wx8a92323f9a6a5f7a';
const TOKEN_CACHE_FILE = path.join(__dirname, 'luckystar_token_cache.json');

function getArg(name) {
  const i = process.argv.indexOf(name);
  return i !== -1 ? process.argv[i + 1] : undefined;
}

// 本地测试辅助：--ck <文件> 从文件读 H5 Cookie（不影响青龙环境变量读取）
function readCkFile() {
  const p = getArg('--ck');
  if (!p) return null;
  try {
    return fs.readFileSync(path.resolve(p), 'utf8').trim();
  } catch (e) {
    console.error('[!] 读取 --ck 文件失败:', e.message);
    return null;
  }
}

// 环境变量名优先级（H5 Cookie 兜底模式，青龙推荐 ELEME_COOKIE）
const COOKIE_ENV_KEYS = ['ELEME_COOKIE', 'ELM_COOKIE', 'elemeCookie', 'ELEME_STR', 'COOKIE', 'JD_COOKIE'];

/** 从各种环境变量来源收集原始 H5 Cookie 字符串（可含多账号分隔符） */
function collectEnvCookies() {
  const sources = [];
  if (typeof __ENV__ !== 'undefined') {
    for (const k of COOKIE_ENV_KEYS) if (__ENV__[k]) sources.push(__ENV__[k]);
  }
  try {
    const ql = require('qinglong');
    if (ql && typeof ql.getCookie === 'function') {
      for (const k of COOKIE_ENV_KEYS) { const c = ql.getCookie(k); if (c) sources.push(c); }
    }
  } catch (e) {}
  for (const k of COOKIE_ENV_KEYS) {
    if (process.env[k]) sources.push(process.env[k]);
  }
  return sources;
}

/** 将原始 cookie 字符串按常见多账号分隔符拆分成数组 */
function splitAccounts(raw) {
  if (!raw) return [];
  return raw
    .replace(/\r/g, '')
    .split(/\n|@@|&&|&/)
    .map((s) => s.trim())
    .filter((s) => s && s.includes('=') && s.includes(';'));
}

/** 从 cookie 中提取账号标识（优先 USERID，便于日志区分） */
function accountName(cookie) {
  const m = new RegExp('USERID=([^;]+)').exec(cookie);
  return m ? ('用户' + m[1]) : ('账号' + crypto.createHash('md5').update(cookie).digest('hex').slice(0, 6));
}

/** 读取 WX_ID（微信账号），多账号换行或 & 分隔，支持 wxid#备注 */
function getWxIds() {
  const raw = (process.env.WX_ID || '').trim();
  if (!raw) return [];
  return raw
    .split(/[\n&]+/)
    .map((v) => String(v).split('#')[0].trim())
    .filter(Boolean);
}

/** ---- token 缓存（getCode 登录态复用，避免每次跑都重新取码登录）---- */
function readTokenCache() {
  try {
    if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
    return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, 'utf8')) || {};
  } catch (e) { return {}; }
}
function writeTokenCache(cache) {
  try { fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), 'utf8'); } catch (e) {}
}

/**
 * 账号对象：区分两种模式。
 *  - 模式 getcode: 由 WX_ID 提供 openid/wxid，登录态通过 getCode 换 Cookie 后缓存
 *  - 模式 cookie:  直接使用 H5 Cookie（老用户 / --ck 本地测试）
 */
function buildAccounts() {
  const accounts = [];
  const seen = new Set();
  const pushCookie = (c) => {
    if (!c || seen.has(c)) return;
    seen.add(c);
    accounts.push({ mode: 'cookie', cookie: c, label: accountName(c) });
  };
  const pushWxid = (wxid) => {
    if (!wxid || seen.has(wxid)) return;
    seen.add(wxid);
    accounts.push({ mode: 'getcode', wxid, label: wxid });
  };

  const ckFile = readCkFile();
  if (ckFile) for (const c of splitAccounts(ckFile)) pushCookie(c);

  const wxIds = getWxIds();
  if (wxIds.length) {
    for (const wxid of wxIds) pushWxid(wxid);
  } else {
    // 无 WX_ID 时回退到 H5 Cookie 模式
    for (const raw of collectEnvCookies()) {
      for (const c of splitAccounts(raw)) pushCookie(c);
    }
  }
  return accounts;
}

/**
 * getcode 模式登录：用微信 login code 换饿了么登录态 Cookie。
 *
 * 登录链路（已确认）：code → https://ipassport.ele.me/mini_program/login.do → session → 组装 cookie。
 * login.do 请求体含 authorizationCode={"authorizationCode": 微信code}，返回 content.data 为 session
 * （含 sid/cookie2/SID/user_id/open_id/union_id/sgcookie/munb/UTUSER/st）。
 *
 * 注意：login.do 需要阿里 fireye/AWSC 风控头（bx-ua / mini-janus / bx-umidtoken），
 * 由 eleme_assets/awsc_bridge.cjs（Node 桥）生成。若项目缺少该资源，将退化为
 * ELEME_LOGIN_RESULT 注入模式。
 *
 * 返回：饿了么 Cookie 字符串；失败返回 null。
 */
async function wxCodeToElemeCookie(wxid, code) {
  // 方式一：直接注入抓包得到的完整登录 cookie（最稳，不需要 awsc_bridge）
  const injected = (process.env.ELEME_LOGIN_RESULT || '').trim();
  if (injected) {
    if (injected.includes(';') && /[A-Za-z0-9_]+=[^;]+/.test(injected)) {
      console.log('  [登录] 使用 ELEME_LOGIN_RESULT 注入的登录 Cookie');
      return injected;
    }
    try {
      const obj = JSON.parse(injected);
      return loginResultToCookie(obj);
    } catch (e) {
      throw new Error('ELEME_LOGIN_RESULT 无法解析：需为 cookie 字符串或 x-smallstc JSON');
    }
  }

  // 方式二：走 login.do 自动兑换（需本地 awsc_bridge.cjs 生成风控头）
  const login = await havanaCodeLogin(code);
  if (login.ok) return login.cookie;
  throw new Error('饿了么 code 登录失败：' + login.error);
}

/** 把抓包得到的 x-smallstc / loginResult 对象转成饿了么 cookie 字符串 */
function loginResultToCookie(obj) {
  const map = {
    sid: 'sid', cookie2: 'cookie2', SID: 'SID', st: 'st', sgcookie: 'sgcookie',
    csg: 'csg', UTUSER: 'UTUSER', USERID: 'USERID', user_id: 'user_id',
    unb: 'unb', munb: 'munb', open_id: 'open_id', union_id: 'union_id',
    loginSucResultAction: 'loginSucResultAction', loginType: 'loginType',
    loginScene: 'loginScene', appEntrance: 'appEntrance', resultCode: 'resultCode',
    smartlock: 'smartlock', snsType: 'snsType', bindTag: 'bindTag', expires: 'expires',
    elemeExt: 'elemeExt', loginResult: 'loginResult'
  };
  const parts = [];
  for (const [k, ck] of Object.entries(map)) {
    if (obj[k] !== undefined && obj[k] !== null) {
      const val = typeof obj[k] === 'object' ? JSON.stringify(obj[k]) : String(obj[k]);
      parts.push(`${ck}=${encodeURIComponent(val)}`);
    }
  }
  return parts.join('; ');
}

/* =====================================================================
 * 饿了么小程序 code 自动兑换（ipassport login.do）
 * ===================================================================== */

// 账号 Cookie 字段映射（输出键名 -> session 候选取值键），顺序即输出顺序
const ACCOUNT_COOKIE_FIELDS = [
  ['cookie2', ['cookie2', 'sid']],
  ['sid', ['sid']],
  ['SID', ['SID']],
  ['userId', ['user_id', 'userId', 'USERID']],
  ['openId', ['open_id', 'openId']],
  ['unionId', ['union_id', 'unionId']],
  ['sgcookie', ['sgcookie']],
  ['munb', ['munb']],
  ['UTUSER', ['UTUSER']],
  ['st', ['st']]
];

const LOGIN_ENDPOINT = (process.env.ELEME_LOGIN_ENDPOINT || '').trim() || 'https://ipassport.ele.me/mini_program/login.do';
const ELEME_UA = (process.env.ELEME_USER_AGENT || '').trim() ||
  `Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 MicroMessenger/8.0.58 miniProgram/${ELEME_APPID}`;
const ELEME_REFERER = (process.env.ELEME_REFERER || '').trim() || `https://servicewechat.com/${ELEME_APPID}/831/page-frame.html`;
const ELEME_ASSETS_DIR = path.join(__dirname, 'eleme_assets');
const AWSC_BRIDGE = path.join(ELEME_ASSETS_DIR, 'awsc_bridge.cjs');

const URI_SAFE = new Set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()");
const FORM_SAFE = new Set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789*-._');
function pct(s, safeSet, spaceChar) {
  let out = '';
  for (const ch of String(s)) {
    if (ch === ' ') out += spaceChar;
    else if (safeSet.has(ch)) out += ch;
    else {
      for (const b of Buffer.from(ch, 'utf8')) out += '%' + b.toString(16).toUpperCase().padStart(2, '0');
    }
  }
  return out;
}
function encUriComponent(s) { return pct(s, URI_SAFE, '%20'); }
function formEncode(pairs) {
  return Object.entries(pairs).map(([k, v]) => `${pct(k, FORM_SAFE, '+')}=${pct(v, FORM_SAFE, '+')}`).join('&');
}
function buildAccountCookie(session) {
  session = session || {};
  const parts = [];
  for (const [outKey, srcKeys] of ACCOUNT_COOKIE_FIELDS) {
    let value = null;
    for (const sk of srcKeys) {
      const v = session[sk];
      if (v !== undefined && v !== null && String(v) !== '') { value = v; break; }
    }
    if (value === null) continue;
    if (outKey === 'SID') parts.push(`${outKey}=${value}`); // SID 不编码
    else parts.push(`${outKey}=${encUriComponent(String(value))}`);
  }
  return parts.join('; ');
}

// 调用本地 awsc_bridge.cjs 生成 bx-ua/mini-janus/bx-umidtoken
async function buildAwscParams(url, session = {}, umidToken = '') {
  const bridge = AWSC_BRIDGE;
  if (!fs.existsSync(bridge)) {
    return { ok: false, error: `缺少 ${bridge}（awsc_bridge.cjs），无法生成 bx-ua/mini-janus，请放置 eleme_assets 资源或用 ELEME_LOGIN_RESULT 注入` };
  }
  const { execFile } = require('child_process');
  const args = { url, session, umidToken, debug: false, noNetwork: false };
  const argsTmp = path.join(ELEME_ASSETS_DIR, `_awsc_args_${Date.now()}.json`);
  const outTmp = path.join(ELEME_ASSETS_DIR, `_awsc_out_${Date.now()}.json`);
  try {
    fs.writeFileSync(argsTmp, JSON.stringify(args));
    await new Promise((resolve, reject) => {
      execFile('node', [bridge, argsTmp, outTmp], { cwd: ELEME_ASSETS_DIR, timeout: 90000 }, (err) => err ? reject(err) : resolve());
    });
    if (!fs.existsSync(outTmp)) return { ok: false, error: 'awsc_bridge 无输出文件' };
    const result = JSON.parse(fs.readFileSync(outTmp, 'utf8'));
    return (result && typeof result === 'object') ? result : { ok: false, error: 'awsc_bridge 输出格式异常' };
  } catch (e) {
    return { ok: false, error: `awsc_bridge 调用失败：${e.message}` };
  } finally {
    try { fs.unlinkSync(argsTmp); } catch (e) {}
    try { fs.unlinkSync(outTmp); } catch (e) {}
  }
}

// code -> login.do -> session -> cookie
async function havanaCodeLogin(code) {
  const awsc = await buildAwscParams(LOGIN_ENDPOINT, {}, '');
  const awscOk = !!awsc.ok;
  const params = awsc.params || {};
  const autoUmid = params.bxUmidToken || '';

  const authorizationCode = JSON.stringify({ authorizationCode: code });
  const requestData = {
    type: 'weixin_mini_program',
    appId: ELEME_APPID,
    appName: 'eleme',
    appEntrance: 'weixin',
    lang: 'zh_CN',
    isMobile: true,
    returnUrl: '',
    needPassWebViewCookie: false,
    authorizationCode: authorizationCode
  };
  if (autoUmid) requestData.umidToken = autoUmid;
  const body = formEncode(requestData);

  const headers = {
    'Accept': 'application/json,text/plain,*/*',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'User-Agent': ELEME_UA,
    'Referer': ELEME_REFERER,
    'x-tap': 'wx'
  };
  for (const [k, v] of Object.entries(awsc.headers || {})) {
    if (v !== undefined && v !== null && v !== '') headers[k] = String(v);
  }

  const res = await new Promise((resolve, reject) => {
    const u = new URL(LOGIN_ENDPOINT);
    const req = https.request(u, { method: 'POST', headers }, (r) => {
      const c = [];
      r.on('data', (d) => c.push(d));
      r.on('end', () => resolve({ status: r.statusCode, body: Buffer.concat(c).toString('utf8') }));
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });

  let j = null;
  try { j = JSON.parse(res.body); } catch (e) { j = null; }
  let contentData = {};
  if (j && j.content && typeof j.content === 'object' && j.content.data && typeof j.content.data === 'object') {
    contentData = j.content.data;
  }
  const session = { ...contentData };
  if (session.sid && !session.cookie2) session.cookie2 = session.sid;
  const cookie = buildAccountCookie(session);
  const ok = res.status >= 200 && res.status < 300 && !!(session.cookie2 || session.sid || session.st);

  let err = '';
  if (!ok) {
    if (!j) err = `接口未返回 JSON（HTTP ${res.status}）`;
    else if (j.hasError) err = `接口错误：${(j.content && (j.content.errorMsg || j.content.msg)) || j.msg || '未知错误'}`;
    else if (contentData.titleMsg) err = `业务错误：${contentData.titleMsg}`;
    else if (['redirect', 'iframeRedirect', 'redirectUrl', 'iframeRedirectUrl'].some((k) => contentData[k])) err = '返回跳转/核身/绑定流程，未直接下发 cookie（可能触发风控或需绑定）';
    else err = `登录未成功：响应无 sid/st/cookie2（HTTP ${res.status}）`;
    if (!awscOk) err += `；且算法参数(bx-ua)未生成：${awsc.error || '未知'}`;
  }

  return { ok, status: res.status, error: err, cookie, session, username: session.username || '', xSmallstc: JSON.stringify(session) };
}

/** 把抓包得到的 x-smallstc / loginResult 对象转成饿了么 cookie 字符串 */
function loginResultToCookie(obj) {
  const map = {
    sid: 'sid', cookie2: 'cookie2', SID: 'SID', st: 'st', sgcookie: 'sgcookie',
    csg: 'csg', UTUSER: 'UTUSER', USERID: 'USERID', user_id: 'user_id',
    unb: 'unb', munb: 'munb', open_id: 'open_id', union_id: 'union_id',
    loginSucResultAction: 'loginSucResultAction', loginType: 'loginType',
    loginScene: 'loginScene', appEntrance: 'appEntrance', resultCode: 'resultCode',
    smartlock: 'smartlock', snsType: 'snsType', bindTag: 'bindTag', expires: 'expires',
    elemeExt: 'elemeExt', loginResult: 'loginResult'
  };
  const parts = [];
  for (const [k, ck] of Object.entries(map)) {
    if (obj[k] !== undefined && obj[k] !== null) {
      const val = typeof obj[k] === 'object' ? JSON.stringify(obj[k]) : String(obj[k]);
      parts.push(`${ck}=${encodeURIComponent(val)}`);
    }
  }
  return parts.join('; ');
}

/**
 * 取单个 getcode 账号的登录 Cookie。
 * 优先读缓存；缓存失效或取码失败则通过 getCode + wxCodeToElemeCookie 登录。
 */
async function getCookieForWxid(wxid) {
  // 1. 读缓存
  const cache = readTokenCache();
  const cached = cache[wxid];
  if (cached && cached.cookie) {
    console.log(`  [${wxid}] 使用缓存的饿了么登录态`);
    return cached.cookie;
  }
  // 2. 取码
  if (!getSingleCode) {
    throw new Error('未找到 getCode.js，请确认脚本在 wxapp 目录下运行或已安装依赖');
  }
  console.log(`  [${wxid}] 通过 getCode 获取微信 code...`);
  const code = await getSingleCode(ELEME_APPID, wxid);
  if (!code) throw new Error('getCode 获取微信 code 失败');
  // 3. 换登录态
  const cookie = await wxCodeToElemeCookie(wxid, code);
  if (!cookie) throw new Error('微信 code 换饿了么登录态失败');
  // 4. 写缓存
  cache[wxid] = { cookie, updatedAt: new Date().toISOString() };
  writeTokenCache(cache);
  return cookie;
}

/** 收集所有待处理账号，为 getcode 账号解析出登录 Cookie */
async function getAllAccounts() {
  const accounts = buildAccounts();
  const ready = [];
  for (const acc of accounts) {
    if (acc.mode === 'getcode') {
      try {
        const cookie = await getCookieForWxid(acc.wxid);
        ready.push({ ...acc, cookie });
      } catch (e) {
        console.error(`  [!] 账号 [${acc.wxid}] 登录失败: ${e.message}`);
      }
    } else {
      ready.push(acc);
    }
  }
  return ready;
}

/* =====================================================================
 * 第 3 部分：任务执行逻辑（单账号）
 * ===================================================================== */
function retCode(json) {
  return (json && json.ret && json.ret[0]) || '';
}
function canReceive(task) {
  return task.status === 'FINISH' && task.receiveStatus === 'TORECEIVE';
}
function canComplete(task) {
  const at = task.actionConfig && task.actionConfig.actionType;
  const op = task.actionConfig && task.actionConfig.actionValue && task.actionConfig.actionValue.executeOpportunity;
  return task.status === 'RUNNING' && at === 'PAGEVIEW' && op;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 处理单个账号，返回 { ok, done, received, skipped, stars } */
async function runAccount(cookie, opts) {
  const { dry, viewMs, onlyMission, log } = opts;
  const m = new EleMtop(cookie);
  const result = { ok: false, done: 0, received: 0, skipped: 0, stars: null };

  // 0. 首页：拿任务/签到/余额
  const hp = await m.homepage();
  if (!hp.json.ret || !hp.json.ret[0].startsWith('SUCCESS')) {
    log.error(`首页调用失败: ${retCode(hp.json)}`);
    return result;
  }
  const hd = hp.json.data && hp.json.data.data;
  try { result.stars = hd.property.data.STAR.amount; } catch (e) {}
  log.info(`幸运星余额: ${result.stars}`);

  // 签到
  let signInfo = null;
  try {
    const s = hd.signIn && hd.signIn.data;
    signInfo = {
      status: s && s.status,
      copyId: s && s.extInfo && s.extInfo.copyId,
      actId: s && s.actId
    };
  } catch (e) {}
  log.info(`签到状态: ${signInfo && signInfo.status}`);

  if (!dry && signInfo && signInfo.status !== 'HAS_SIGNIN' && signInfo.copyId) {
    const sr = await m.signinandreceive(signInfo.copyId, signInfo.actId || '');
    log.info(`每日签到: ${retCode(sr.json)}`);
  } else {
    log.info((signInfo && signInfo.status === 'HAS_SIGNIN') ? '今日已签到，跳过' : (dry ? '干跑模式，跳过签到' : '无签到组件'));
  }

  // 收集任务：cardMission（首页任务卡）+ querytask（任务列表）
  const cardTasks = (hd.cardMission && hd.cardMission.data) || [];
  const qt = await m.querytask();
  if (!qt.json.ret || !qt.json.ret[0].startsWith('SUCCESS')) {
    log.error(`querytask 失败: ${retCode(qt.json)}`);
    return result;
  }
  const mlist = (qt.json.data && qt.json.data.mlist) || [];
  log.info(`首页任务卡: ${cardTasks.length} | 任务列表: ${mlist.length}`);

  // 合并两组任务（去重），作为统一处理集合
  let tasks = [];
  const seen = new Set();
  for (const t of [...cardTasks, ...mlist]) {
    if (seen.has(t.missionDefId)) continue;
    seen.add(t.missionDefId);
    tasks.push(t);
  }

  // 刷新任务快照：重新 querytask + homepage，合并成最新状态
  const refresh = async () => {
    const [q2, h2] = [await m.querytask(), await m.homepage()];
    const fresh = [];
    const s = new Set();
    const push = (arr) => { for (const t of arr || []) { if (!s.has(t.missionDefId)) { s.add(t.missionDefId); fresh.push(t); } } };
    if (h2.json.ret && h2.json.ret[0].startsWith('SUCCESS') && h2.json.data && h2.json.data.data) {
      push(h2.json.data.data.cardMission && h2.json.data.data.cardMission.data);
    }
    if (q2.json.ret && q2.json.ret[0].startsWith('SUCCESS')) push(q2.json.data.mlist);
    return fresh;
  };

  // 阶段A：完成 PAGEVIEW 任务
  log.info('--- [阶段A] 完成 PAGEVIEW 任务 ---');
  const completes = tasks.filter(canComplete);
  log.info(`  可完成(PAGEVIEW): ${completes.length}`);
  for (const task of completes) {
    if (onlyMission && String(task.missionDefId) !== String(onlyMission)) continue;
    const name = task.name || task.showTitle || ('任务' + task.missionDefId);
    log.info(`▶ 完成 [${name}] (${task.missionDefId})`);
    if (dry) { result.skipped++; continue; }
    const pv = await m.pageview({ missionId: task.missionDefId, viewTime: viewMs });
    const code = retCode(pv.json);
    log.info(`   pageview: ${code}${code.startsWith('SUCCESS') ? ' (成功)' : ''}`);
    if (code.startsWith('SUCCESS')) result.done++;
    await sleep(800);
  }

  // 完成后刷新任务状态
  if (result.done > 0) {
    log.info('等待服务端更新任务状态...');
    await sleep(2500);
    tasks = await refresh();
  }

  // 阶段B：领取已完成任务
  log.info('--- [阶段B] 领取已完成任务奖励 ---');
  const receives = tasks.filter(canReceive);
  log.info(`  可领取(FINISH): ${receives.length}`);
  for (const task of receives) {
    if (onlyMission && String(task.missionDefId) !== String(onlyMission)) continue;
    const name = task.name || task.showTitle || ('任务' + task.missionDefId);
    const stage = task.missionStageDTOS && task.missionStageDTOS[0];
    const stageCount = stage ? stage.stageCount : null;
    const reward = stage && stage.rewards && stage.rewards[0];
    const desc = reward ? `${reward.name}+${reward.value}` : '';
    log.info(`★ 领取 [${name}] (${task.missionDefId})  奖励:${desc}`);
    if (dry) { result.skipped++; continue; }
    const rpOpts = { missionId: task.missionDefId, count: stageCount != null ? stageCount : undefined };
    if (task.id) rpOpts.instanceId = task.id;
    const rp = await m.receiveprize(rpOpts);
    const code = retCode(rp.json);
    log.info(`   receiveprize: ${code}${code.startsWith('SUCCESS') ? ' (领取成功)' : ''}`);
    if (code.startsWith('SUCCESS')) result.received++;
    await sleep(800);
  }

  // 最终余额
  if (!dry) {
    const hp2 = await m.homepage();
    try { result.stars = hp2.json.data.data.property.data.STAR.amount; } catch (e) {}
  }

  result.ok = true;
  return result;
}

/* =====================================================================
 * 第 4 部分：青龙通知
 * ===================================================================== */
function loadQingLongNotify() {
  try {
    const mod = require('/ql/scripts/sendNotify.js');
    if (mod && typeof mod.sendNotify === 'function') return mod.sendNotify;
  } catch (e) {}
  try {
    const mod = require('sendNotify');
    if (mod && typeof mod.sendNotify === 'function') return mod.sendNotify;
  } catch (e) {}
  return null;
}

async function sendNotify(title, body) {
  const fn = loadQingLongNotify();
  if (fn) {
    try { await fn(title, body); return; } catch (e) { console.warn('[notify] 发送失败:', e.message); }
  }
  // 无青龙通知渠道则打印到日志
  console.log(`[通知] ${title}`);
  console.log(body);
}

/* =====================================================================
 * 第 5 部分：入口 main（青龙调用 & 命令行直跑）
 * ===================================================================== */
/**
 * 青龙面板会 require 本文件并调用 main()。
 * 也可直接 node qinglong-ele-luckystar.js 运行。
 */
async function main() {
  const dry = process.argv.includes('--dry');
  const noNotify = process.argv.includes('--no-notify');
  const viewMs = parseInt(getArg('--view-ms') || '30000', 10);
  const onlyMission = getArg('--only');

  const accounts = await getAllAccounts();
  if (accounts.length === 0) {
    console.error('[!] 未检测到任何可用账号。');
    console.error('    方式一（推荐）：在青龙「环境变量」中新建 WX_ID，值为微信账号标识');
    console.error('      wxid#备注 或 openid，多账号用 换行 或 & 分隔。');
    console.error('    方式二（H5 Cookie 兼容）：新建 ELEME_COOKIE，值为饿了么 H5 Cookie。');
    console.error('    getcode 模式需在 getCookieForWxid/wxCodeToElemeCookie 中配置饿了么登录接口。');
    process.exitCode = 1;
    return;
  }

  console.log(`[*] 检测到 ${accounts.length} 个账号，模式: ${dry ? '干跑(只查询)' : '自动(完成+领取)'}`);
  const lines = [];
  const summaries = [];

  for (let i = 0; i < accounts.length; i++) {
    const acc = accounts[i];
    const cookie = acc.cookie;
    const name = acc.label || accountName(cookie || '');
    console.log(`\n========== 账号 ${i + 1}/${accounts.length}: ${name} ==========`);
    const log = {
      info: (s) => console.log('  ' + s),
      error: (s) => console.error('  ' + s)
    };
    try {
      const r = await runAccount(cookie, { dry, viewMs, onlyMission, log });
      const status = r.ok ? '成功' : '失败';
      const line = `${name}: ${status} | 完成 ${r.done} | 领取 ${r.received} | 余额 ${r.stars}`;
      console.log(`  [账号结果] ${line}`);
      lines.push(line);
      summaries.push({ name, ...r });
    } catch (e) {
      console.error(`  [!] 账号处理异常: ${e.message}`);
      lines.push(`${name}: 异常 (${e.message})`);
      summaries.push({ name, ok: false, error: e.message });
    }
  }

  // 汇总
  console.log('\n========== 全部账号汇总 ==========');
  lines.forEach((l) => console.log('  ' + l));

  // 通知
  if (!noNotify) {
    const totalDone = summaries.reduce((s, x) => s + (x.done || 0), 0);
    const totalReceived = summaries.reduce((s, x) => s + (x.received || 0), 0);
    const allOk = summaries.every((x) => x.ok);
    await sendNotify(
      allOk ? '⭐ 闪购幸运星任务完成' : '⚠️ 闪购幸运星任务部分失败',
      [`账号数: ${summaries.length}`, `完成任务: ${totalDone}`, `领取奖励: ${totalReceived}`, '', ...lines].join('\n')
    );
  }

  console.log('\n[全部完成]');
}

// 支持 require 方式（青龙）与直接 node 运行
if (require.main === module) {
  main().catch((e) => { console.error('[!] 致命错误:', e); process.exit(1); });
}

module.exports = { main, EleMtop, getAllAccounts, getWxIds, wxCodeToElemeCookie };
