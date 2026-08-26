require('./yyb.js'); // 自动同步 yyb_go 存活账号
/*
 * name: 天乐短剧
 * cron: 41 8,16 * * *
 *
 * 功能：查询状态、签到、视频奖励任务、观看时长任务、领取观看红包、提现。
 *
 * 环境变量（双协议：牛子 Wechat + 应用宝 YYB，统一走 ./yyb.js 路由）：
 *   WX_ID（推荐）或 REELIX_AUTH
 *     多账号用 & 或换行分隔。
 *     账号标识支持：
 *       wxid_xxx#备注            牛子协议（微信 wxid）
 *       openid#备注              应用宝 YYB 协议（openid 或数字 id）
 *       wx:xxx#备注              牛子协议
 *       yyb:openid#备注          应用宝 YYB 协议（兼容旧写法）
 *     路由规则：openid/数字 id 自动走 YYB，其余走牛子，与 ./yyb.js 一致。
 *     仍支持直接填 token：
 *       token#deviceId
 *       token#deviceId#userAgent#clientBuild#encryptKey#iv#version
 *
 * 可选：
 *   WECHAT_SERVER=http://127.0.0.1:xxxx   牛子协议服务（默认 http://127.0.0.1:8000）
 *   YYB_SERVER=http://127.0.0.1:8000      应用宝服务
 *   REELIX_INVITE_CODE=xxxx               邀请码，可选
 *   REELIX_USER_KEY=encryptKey#iv#version  全局微信用户加密 key，不配置时会跳过签到/红包领取/提现
 *   REELIX_DO_SIGNIN=1                   是否签到，默认 1
 *   REELIX_DO_VIDEO_TASK=1               是否领取视频阶段奖励，默认 1
 *   REELIX_VIDEO_STAGES=3                视频阶段奖励次数，默认 3
 *   REELIX_DO_WATCH=1                    是否上报观看时长，默认 1
 *   REELIX_WATCH_UNTIL_UNLOCK=1          是否持续上报到解锁可领取红包，默认 1
 *   REELIX_WATCH_SECONDS=180             固定观看秒数；关闭持续解锁时使用，默认 180
 *   REELIX_WATCH_MAX_SECONDS=900         单账号最多上报观看秒数，默认 900
 *   REELIX_WATCH_CHUNK_SECONDS=10        单次上报秒数，默认 10
 *   REELIX_WATCH_SLEEP_MS=10000          单次上报间隔，默认 10000
 *   REELIX_SWITCH_ON_ZERO=1              单段认可 0 秒时切换短剧，默认 1
 *   REELIX_DO_CLAIM=1                    是否领取可领红包，默认 1
 *   REELIX_CLAIM_ALL_ENVELOPES=1         是否持续刷完当天 20 个红包，默认 1
 *   REELIX_ENVELOPE_MAX_ROUNDS=20        单账号最多解锁/领取红包轮数，默认 20
 *   REELIX_ENVELOPE_ROUND_SLEEP_MS=1000  每轮红包领取后等待，默认 1000
 *   REELIX_WITHDRAW=0                    提现总开关，默认 0 关闭；也兼容 REELIX_DO_WITHDRAW=1
 *   REELIX_WITHDRAW_POINTS=              每次提多少金币；不填则按余额提全部可提现金币
 *   REELIX_WITHDRAW_MIN_POINTS=1000      最低/步进提现金币，默认 1000
 *   REELIX_WITHDRAW_DAILY_LIMIT=2        单账号每天最多提交提现次数，默认 2
 *   REELIX_WITHDRAW_MAX_ROUNDS=10        单账号最多连续提现轮数，默认 10
 *   REELIX_WITHDRAW_SLEEP_MS=1000        每次提现后重新查金币前等待，默认 1000
 *   REELIX_WITHDRAW_DRY_RUN=0            提现测试模式，只检查余额/记录，不提交，默认 0
 *   REELIX_CONCURRENCY=3                 多账号并发数，默认 3
 *   REELIX_TX_PAGE_SIZE=10
 *   REELIX_WITHDRAW_PAGE_SIZE=10
 *   REELIX_DEBUG=1
 */

const axios = require('axios');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
require('events').defaultMaxListeners = 50;

const yyb = require('./yyb.js');
const getSingleCode = yyb.getSingleCode;

const ENV_NAME = 'REELIX_AUTH';
const APPID = 'wx82b9bc71fff22c52';
const BASE_URL = 'https://live.mkjsy.com/reelix/api/v1/app';
const WECHAT_SERVER = String(process.env.WX_SERVER || process.env.WECHAT_SERVER || '').replace(/\/$/, '');
const REELIX_INVITE_CODE = String(process.env.REELIX_INVITE_CODE || 'JEL3OH').trim();
const DEFAULT_BUILD = '2026-07-25 17:41:50';
const DEFAULT_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.75(0x18004b47) NetType/4G Language/zh_CN';
const REFERER = 'https://servicewechat.com/wx82b9bc71fff22c52/16/page-frame.html';
const CACHE_DIR = path.join(process.cwd(), '.cache');
const PROTOCOL_CACHE_FILE = path.join(CACHE_DIR, 'reelix_protocol_cache.json');
const DO_SIGNIN = envFlag('REELIX_DO_SIGNIN', true);
const DO_VIDEO_TASK = envFlag('REELIX_DO_VIDEO_TASK', true);
const VIDEO_STAGES = Number(process.env.REELIX_VIDEO_STAGES || 3);
const DO_WATCH = envFlag('REELIX_DO_WATCH', true);
const WATCH_UNTIL_UNLOCK = envFlag('REELIX_WATCH_UNTIL_UNLOCK', true);
const WATCH_SECONDS = Number(process.env.REELIX_WATCH_SECONDS || 180);
const WATCH_MAX_SECONDS = Number(process.env.REELIX_WATCH_MAX_SECONDS || 900);
const WATCH_CHUNK_SECONDS = Number(process.env.REELIX_WATCH_CHUNK_SECONDS || 10);
const WATCH_SLEEP_MS = Number(process.env.REELIX_WATCH_SLEEP_MS || 10000);
const SWITCH_ON_ZERO = envFlag('REELIX_SWITCH_ON_ZERO', true);
const DO_CLAIM = envFlag('REELIX_DO_CLAIM', true);
const CLAIM_ALL_ENVELOPES = envFlag('REELIX_CLAIM_ALL_ENVELOPES', true);
const ENVELOPE_MAX_ROUNDS = Number(process.env.REELIX_ENVELOPE_MAX_ROUNDS || 20);
const ENVELOPE_ROUND_SLEEP_MS = Number(process.env.REELIX_ENVELOPE_ROUND_SLEEP_MS || 1000);
const DO_WITHDRAW = envFlag('REELIX_WITHDRAW', envFlag('REELIX_DO_WITHDRAW', false));
const WITHDRAW_POINTS_RAW = String(process.env.REELIX_WITHDRAW_POINTS || '').trim();
const WITHDRAW_POINTS = WITHDRAW_POINTS_RAW ? Number(WITHDRAW_POINTS_RAW) : 0;
const WITHDRAW_MIN_POINTS = Number(process.env.REELIX_WITHDRAW_MIN_POINTS || 1000);
const WITHDRAW_DAILY_LIMIT = Number(process.env.REELIX_WITHDRAW_DAILY_LIMIT || 2);
const WITHDRAW_MAX_ROUNDS = Number(process.env.REELIX_WITHDRAW_MAX_ROUNDS || 10);
const WITHDRAW_SLEEP_MS = Number(process.env.REELIX_WITHDRAW_SLEEP_MS || 1000);
const WITHDRAW_DRY_RUN = envFlag('REELIX_WITHDRAW_DRY_RUN', false);
const TX_PAGE_SIZE = Number(process.env.REELIX_TX_PAGE_SIZE || 10);
const WITHDRAW_PAGE_SIZE = Number(process.env.REELIX_WITHDRAW_PAGE_SIZE || 10);
const ACCOUNT_CONCURRENCY = Math.max(1, Number(process.env.REELIX_CONCURRENCY || 3));
const DEBUG = String(process.env.REELIX_DEBUG || '') === '1';

let notifyText = '';
const summaries = [];

function log(message) {
  console.log(message);
}

function appendNotify(message) {
  notifyText += `${message}\n`;
}

function mask(value) {
  const text = String(value || '');
  if (text.length <= 12) return text ? `${text.slice(0, 3)}***` : '';
  return `${text.slice(0, 8)}...${text.slice(-6)}`;
}

function envFlag(name, defaultValue) {
  const value = process.env[name];
  if (value === undefined || value === '') return defaultValue;
  return ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase());
}

async function parseAccounts() {
  const globalUserKey = parseUserKey(process.env.REELIX_USER_KEY || '');
  const sources = [];
  const wxIdRaw = String(process.env.WX_ID || '').trim();
  const authRaw = String(process.env[ENV_NAME] || '').trim();
  if (wxIdRaw) sources.push(wxIdRaw);
  if (authRaw) sources.push(authRaw);
  let raw = sources.join('\n');
  if (!raw.trim()) {
    // 未配置 WX_ID 时，自动从 yyb_go 拉取存活账号
    const auto = await resolveAccounts();
    if (auto && auto.length) {
      sources.push(auto.join('\n'));
      raw = sources.join('\n');
    }
  }
  if (!raw.trim()) {
    log(`未配置环境变量 WX_ID 或 ${ENV_NAME}`);
    return [];
  }

  let index = 0;
  return raw
    .split(/[&\n]/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      index += 1;
      return parseAccountLine(line, index, globalUserKey);
    })
    .filter(Boolean)
    .filter((account) => {
      if (account.isWechatProtocol) return true;
      if (!account.token || !account.deviceId) {
        log(`账号 ${account.index} 格式错误，应为 wxid_xxx#备注 / openid#备注 / token#deviceId`);
        return false;
      }
      return true;
    });
}

function isYybOpenid(id) {
  const raw = String(id || '').split('#')[0].trim();
  if (!raw) return false;
  if (/^\d+$/.test(raw)) return true;
  if (/^o[a-zA-Z0-9_-]{20,}$/.test(raw)) return true;
  return false;
}

// 微信自定义号（alias）：字母开头，6-20 位，可含字母/数字/下划线/减号
// 用于区分「协议账号标识」与「直接填 token」：非 token 形式即视为协议标识
function isWechatAlias(id) {
  const raw = String(id || '').split('#')[0].trim();
  if (!raw) return false;
  return /^[a-zA-Z][-_a-zA-Z0-9]{5,19}$/.test(raw);
}

function isProtocolIdentifier(id) {
  const raw = String(id || '');
  return raw.startsWith('wxid_') ||
    raw.startsWith('wx:') ||
    raw.startsWith('yyb:') ||
    isYybOpenid(raw) ||
    isWechatAlias(raw);
}

// 协议路由：应用宝 openid/数字 id → yyb；其余（wxid_、wx:、用户自定义微信号）→ wechat（牛子）
// 与 ./yyb.js 的 _detectProtocolForIdentifier 一致：正向识别应用宝 openid，其余一律当微信号。
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

function parseAccountLine(line, index, globalUserKey) {
  const parts = line.split('#').map((item) => item.trim());
  const first = parts[0] || '';
  if (!first) return null;

  if (isProtocolIdentifier(first)) {
    // 路由判断：应用宝 openid → yyb，其余（含用户自定义微信号）→ wechat
    const protocolType = detectProtocol(first);
    const identifier = stripProtocolPrefix(first);
    const remark = parts.slice(1).join('#').trim() || identifier;
    return {
      index,
      raw: line,
      accountId: identifier,
      cacheKey: identifier,
      remark,
      isWechatProtocol: true,
      protocolType,
      protocolId: first,
      identifier,
      token: '',
      deviceId: '',
      userAgent: DEFAULT_UA,
      clientBuild: DEFAULT_BUILD,
      userKey: globalUserKey,
    };
  }

  return {
    index,
    raw: line,
    accountId: first,
    cacheKey: first,
    remark: `账号${index}`,
    isWechatProtocol: false,
    token: normalizeToken(first),
    deviceId: parts[1] || '',
    userAgent: parts[2] || DEFAULT_UA,
    clientBuild: parts[3] || DEFAULT_BUILD,
    userKey: parseUserKey(parts.slice(4, 7).join('#')) || globalUserKey,
  };
}

function parseUserKey(raw) {
  const text = String(raw || '').trim();
  if (!text) return null;
  const parts = text.split('#').map((item) => item.trim());
  if (!parts[0] || !parts[1]) return null;
  return {
    encryptKey: parts[0],
    iv: parts[1],
    version: Number(parts[2] || 1),
  };
}

function ensureCacheDir() {
  if (!fs.existsSync(CACHE_DIR)) fs.mkdirSync(CACHE_DIR, { recursive: true });
}

function loadProtocolCache() {
  try {
    if (fs.existsSync(PROTOCOL_CACHE_FILE)) {
      return JSON.parse(fs.readFileSync(PROTOCOL_CACHE_FILE, 'utf8'));
    }
  } catch (error) {
    log(`读取协议缓存失败：${error.message}`);
  }
  return {};
}

function saveProtocolCache(cache) {
  try {
    ensureCacheDir();
    fs.writeFileSync(PROTOCOL_CACHE_FILE, JSON.stringify(cache, null, 2), 'utf8');
  } catch (error) {
    log(`保存协议缓存失败：${error.message}`);
  }
}

function normalizeToken(token) {
  return String(token || '').replace(/^Bearer\s+/i, '').trim();
}

function createClient(account) {
  const headers = {
    'X-Device-ID': account.deviceId,
    'X-Client-Build': account.clientBuild,
    'x-promopixis-platform': 'miniprogram',
    Referer: REFERER,
    'User-Agent': account.userAgent,
    Accept: '*/*',
  };
  if (account.token) headers.Authorization = `Bearer ${account.token}`;
  return axios.create({
    baseURL: BASE_URL,
    timeout: 30000,
    validateStatus: () => true,
    headers,
  });
}

async function request(client, method, url, options = {}) {
  try {
    const resp = await client.request({ method, url, ...options });
    if (DEBUG) {
      log(`[DEBUG] ${method} ${url} => ${resp.status} ${JSON.stringify(resp.data).slice(0, 300)}`);
    }
    if (resp.status < 200 || resp.status >= 300) {
      return { ok: false, status: resp.status, data: resp.data };
    }
    return { ok: true, status: resp.status, data: resp.data };
  } catch (error) {
    return { ok: false, status: 0, data: { message: error.message } };
  }
}

async function api(client, method, url, options = {}) {
  const resp = await request(client, method, url, options);
  if (!resp.ok) {
    const message = typeof resp.data === 'object' ? JSON.stringify(resp.data).slice(0, 200) : String(resp.data);
    throw new Error(`${method} ${url} 失败：${resp.status} ${message}`);
  }
  return resp.data;
}

async function wechatApi(pathname, data) {
  if (!WECHAT_SERVER) throw new Error('未配置 WECHAT_SERVER');
  const client = axios.create({
    baseURL: WECHAT_SERVER,
    timeout: 30000,
    validateStatus: () => true,
    headers: { 'Content-Type': 'application/json' },
  });
  const resp = await client.post(pathname, data);
  if (DEBUG) {
    log(`[DEBUG] WECHAT ${pathname} => ${resp.status} ${JSON.stringify(resp.data).slice(0, 300)}`);
  }
  if (resp.status < 200 || resp.status >= 300) {
    throw new Error(`WECHAT_SERVER ${pathname} 失败：${resp.status} ${JSON.stringify(resp.data).slice(0, 200)}`);
  }
  const ok = resp.data && (
    resp.data.Code === 0 ||
    resp.data.code === 0 ||
    resp.data.Success === true ||
    resp.data.success === true ||
    resp.data.status === true
  );
  if (!ok) {
    throw new Error(`WECHAT_SERVER ${pathname} 返回失败：${JSON.stringify(resp.data).slice(0, 260)}`);
  }
  return resp.data;
}

function decodeMaybeJsonBase64(value, depth = 0) {
  if (depth > 8 || value == null) return value;
  if (typeof value === 'string') {
    try {
      return decodeMaybeJsonBase64(JSON.parse(value), depth + 1);
    } catch (_) {}
    try {
      return decodeMaybeJsonBase64(JSON.parse(Buffer.from(value, 'base64').toString('utf8')), depth + 1);
    } catch (_) {}
    return value;
  }
  if (Array.isArray(value)) return value.map((item) => decodeMaybeJsonBase64(item, depth + 1));
  if (typeof value === 'object') {
    const out = {};
    for (const [key, item] of Object.entries(value)) out[key] = decodeMaybeJsonBase64(item, depth + 1);
    return out;
  }
  return value;
}

function findField(node, fieldNames, depth = 0) {
  if (depth > 10 || node == null) return '';
  if (typeof node === 'string') {
    try {
      return findField(JSON.parse(node), fieldNames, depth + 1);
    } catch (_) {}
    try {
      return findField(JSON.parse(Buffer.from(node, 'base64').toString('utf8')), fieldNames, depth + 1);
    } catch (_) {}
    return '';
  }
  if (Array.isArray(node)) {
    for (const item of node) {
      const value = findField(item, fieldNames, depth + 1);
      if (value !== '') return value;
    }
    return '';
  }
  if (typeof node === 'object') {
    for (const [key, value] of Object.entries(node)) {
      if (fieldNames.includes(key.toLowerCase()) && value !== undefined && value !== null && value !== '') {
        return value;
      }
    }
    for (const value of Object.values(node)) {
      const found = findField(value, fieldNames, depth + 1);
      if (found !== '') return found;
    }
  }
  return '';
}

async function fetchWxLoginCode(account) {
  let code;
  try {
    code = await getSingleCode(APPID, account.identifier);
  } catch (error) {
    throw new Error(`获取微信登录 code 失败[${account.protocolType}]：${error.message}`);
  }
  if (!code) throw new Error(`未从协议服务提取到 wx.login code`);
  return code;
}

async function fetchWxUserKey(account) {
  if (account.protocolType === 'yyb') {
    log(`[${account.remark}] YYB 协议不支持自动获取加密 key，请配置 REELIX_USER_KEY`);
    return null;
  }
  const resp = await wechatApi('/api/v1/wx/app/operate/wxdata', {
    Wxid: account.protocolId,
    Appid: APPID,
    Opt: 1,
    Data: JSON.stringify({
      api_name: 'webapi_getuserencryptkey',
      data: {},
      with_credentials: true,
    }),
  });
  const decoded = decodeMaybeJsonBase64(resp);
  const encryptKey = findField(decoded, ['encryptkey', 'encrypt_key']);
  const iv = findField(decoded, ['iv']);
  const version = findField(decoded, ['version', 'key_version']) || 1;
  if (!encryptKey || !iv) {
    log(`[${account.remark}] 未从协议服务提取到 encryptKey/iv，加密任务会跳过`);
    return null;
  }
  return { encryptKey: String(encryptKey), iv: String(iv), version: Number(version || 1) };
}

async function loginWithWxCode(account) {
  const code = await fetchWxLoginCode(account);
  const body = {
    code,
    scene: process.env.REELIX_SCENE || 'share',
    appId: APPID,
  };
  if (REELIX_INVITE_CODE) body.inviteCode = REELIX_INVITE_CODE;
  const loginAccount = {
    ...account,
    token: '',
    deviceId: account.deviceId || generateDeviceId(),
  };
  const resp = await api(createClient(loginAccount), 'POST', '/auth/login', { data: body });
  if (!resp.token) throw new Error(`业务登录未返回 token：${JSON.stringify(resp).slice(0, 200)}`);
  account.token = normalizeToken(resp.token);
  account.deviceId = loginAccount.deviceId;
  account.customer = resp.customer || null;
  log(`[${account.remark}] 协议 code 登录成功`);
  return resp;
}

async function validateAccountToken(account) {
  if (!account.token || !account.deviceId) return false;
  const resp = await request(createClient(account), 'GET', '/customer/profile');
  return resp.ok;
}

async function ensureBusinessLogin(account) {
  if (!account.isWechatProtocol) return;
  const cache = loadProtocolCache();
  const cached = cache[account.cacheKey] || {};
  if (cached.token) {
    account.token = cached.token;
    account.deviceId = cached.deviceId || account.deviceId || generateDeviceId();
    account.userAgent = cached.userAgent || account.userAgent;
    account.clientBuild = cached.clientBuild || account.clientBuild;
    account.userKey = account.userKey || cached.userKey || null;
    if (await validateAccountToken(account)) {
      log(`[${account.remark}] 缓存 token 有效`);
      return;
    }
    log(`[${account.remark}] 缓存 token 失效，重新协议登录`);
  }

  await loginWithWxCode(account);
  if (!account.userKey) {
    try {
      account.userKey = await fetchWxUserKey(account);
    } catch (error) {
      log(`[${account.remark}] 获取用户加密 key 失败：${error.message}`);
    }
  }
  cache[account.cacheKey] = {
    remark: account.remark,
    token: account.token,
    deviceId: account.deviceId,
    userAgent: account.userAgent,
    clientBuild: account.clientBuild,
    userKey: account.userKey || null,
    customer: account.customer || null,
    updateTime: Date.now(),
  };
  saveProtocolCache(cache);
}

function pickNumber(data, keys) {
  for (const key of keys) {
    const value = data && data[key];
    if (value !== undefined && value !== null && value !== '') return value;
  }
  return '-';
}

function summarizeProfile(data) {
  const name = data.nickname || data.nickName || data.name || data.username || data.mobile || data.id || '未知用户';
  const points = pickNumber(data, ['pointsBalance', 'points', 'balance', 'pointBalance', 'availablePoints']);
  return { name, points };
}

function summarizeList(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data.records)) return data.records;
  if (Array.isArray(data.items)) return data.items;
  if (Array.isArray(data.list)) return data.list;
  if (data.data) return summarizeList(data.data);
  return [];
}

function parseKeyMaterial(value, expectedBytes, name) {
  const text = String(value || '').trim();
  const candidates = [];
  if (/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(text)) {
    candidates.push(Buffer.from(text, 'base64'));
  }
  candidates.push(Buffer.from(text, 'utf8'));
  if (/^[0-9a-fA-F]+$/.test(text)) {
    candidates.push(Buffer.from(text, 'hex'));
  }
  const matched = candidates.find((buf) => buf.length === expectedBytes);
  if (!matched) throw new Error(`${name} 长度不符合要求`);
  return matched;
}

function parseAesKey(value) {
  for (const bytes of [16, 24, 32]) {
    try {
      return parseKeyMaterial(value, bytes, 'encryptKey');
    } catch (_) {}
  }
  throw new Error('encryptKey 长度不符合 AES-CBC 要求');
}

function encryptWithUserKey(account, data) {
  if (!account.userKey) throw new Error('未配置 REELIX_USER_KEY，无法执行加密提交');
  const key = parseAesKey(account.userKey.encryptKey);
  const iv = parseKeyMaterial(account.userKey.iv, 16, 'iv');
  const cipher = crypto.createCipheriv(`aes-${key.length * 8}-cbc`, key, iv);
  const ciphertext = Buffer.concat([cipher.update(String(data), 'utf8'), cipher.final()]);
  return {
    encryptedData: Buffer.concat([iv, ciphertext]).toString('base64'),
    version: Number(account.userKey.version || 1),
  };
}

function buildSecurePayload(account, operation, payload, intent) {
  const encrypted = encryptWithUserKey(account, JSON.stringify({
    schemaVersion: 1,
    operation,
    intentId: intent.intentId,
    nonce: intent.nonce,
    issuedAt: Math.floor(Date.now() / 1000),
    payload,
  }));
  return {
    intentId: intent.intentId,
    encryptedData: encrypted.encryptedData,
    version: encrypted.version,
  };
}

async function doSignIn(client, account, statusData) {
  if (!DO_SIGNIN) return;
  if (statusData && statusData.hasSignedIn) {
    const points = statusData.todaySignIn && statusData.todaySignIn.points;
    log(`签到：今日已完成${points ? `，已得 ${points}` : ''}`);
    return;
  }
  if (!account.userKey) {
    log('签到：缺少用户加密 key，已跳过');
    return;
  }
  const intent = await api(client, 'POST', '/points/sign-in/intent');
  const body = buildSecurePayload(account, 'points.sign_in', {}, intent);
  const result = await api(client, 'POST', '/points/sign-in', { data: body });
  log(`签到：成功，获得 ${result.points || 0}，余额 ${result.balance || '-'}`);
}

async function doVideoTask(client) {
  if (!DO_VIDEO_TASK) return;
  log('广告：开始旧版视频奖励检测');
  const session = await api(client, 'POST', '/points/video/reward/start');
  const sessionId = session.sessionId || session.id || session.videoRewardSessionId;
  if (!sessionId) {
    log(`视频奖励：开启会话失败 ${JSON.stringify(session).slice(0, 160)}`);
    return;
  }
  for (let stageNo = 1; stageNo <= VIDEO_STAGES; stageNo += 1) {
    const result = await api(client, 'POST', '/points/video/reward/claim', {
      data: { sessionId, stageNo },
    });
    const points = result.points || result.rewardPoints || result.amount || 0;
    log(`广告：旧版视频奖励第 ${stageNo} 阶段完成，获得 ${points}`);
    await sleep(500);
  }
}

async function getDramaContexts(client) {
  const data = await api(client, 'GET', '/dramas/recommend?pageSize=100');
  const list = summarizeList(data);
  const contexts = list.map((item) => ({
    dramaId: String(item.dramaId || item.id || '160509'),
    episodeNo: 1,
    contentDurationMs: Number(item.durationMs || item.duration || 159360),
    title: item.videoTitle || item.title || item.name || '',
  })).filter((item) => item.dramaId);
  return contexts.length ? contexts : [{
    dramaId: '160509',
    episodeNo: 1,
    contentDurationMs: 159360,
    title: '默认短剧',
  }];
}

async function doWatchTask(client, account) {
  let today = await api(client, 'GET', '/points/watch-envelope/today');
  log(`红包：${summarizeWatchEnvelope(today)}`);
  if (isAllEnvelopesClaimed(today)) {
    log('红包：今日红包已全部领取');
    return today;
  }
  if (!DO_WATCH) return today;
  if (hasClaimableEnvelope(today) && account.userKey) {
    log('时长：已有可领取红包，跳过观看上报');
    return today;
  }
  if (hasClaimableEnvelope(today) && !account.userKey) {
    log('时长：已有可领取红包，但缺少加密 key 无法领取，继续观看上报以赚积分');
  }

  const contexts = await getDramaContexts(client);
  const sessionResp = await api(client, 'POST', '/points/watch-envelope/session', {
    data: {
      deviceId: account.deviceId,
      source: 'drama_feed',
      sourceBuild: 'watch-envelope-v2',
    },
  });
  const sessionId = sessionResp.watchSessionId;
  today = sessionResp.today || today;
  if (!sessionId) {
    log('观看时长：开启会话失败');
    return today;
  }

  // 缺加密 key 时无法领红包解锁，改用固定时长观看而非"持续解锁"模式
  const useUnlock = WATCH_UNTIL_UNLOCK && Boolean(account.userKey);
  const maxSeconds = useUnlock ? WATCH_MAX_SECONDS : WATCH_SECONDS;
  const baseChunks = Math.max(1, Math.ceil(maxSeconds / WATCH_CHUNK_SECONDS));
  const chunks = useUnlock ? baseChunks * 3 : baseChunks;
  let contextIndex = 0;
  let context = contexts[contextIndex % contexts.length];
  let positionMs = 0;
  let acceptedTotalMs = 0;
  log(`时长：准备上报，短剧池 ${contexts.length} 个，单段 ${WATCH_CHUNK_SECONDS} 秒，目标解锁=${WATCH_UNTIL_UNLOCK ? '是' : '否'}`);
  for (let index = 1; index <= chunks; index += 1) {
    if (useUnlock && hasClaimableEnvelope(today)) break;
    if (useUnlock && acceptedTotalMs >= WATCH_MAX_SECONDS * 1000) break;
    const remainingAttemptSeconds = maxSeconds - (index - 1) * WATCH_CHUNK_SECONDS;
    const elapsedSeconds = WATCH_UNTIL_UNLOCK
      ? WATCH_CHUNK_SECONDS
      : Math.min(WATCH_CHUNK_SECONDS, remainingAttemptSeconds);
    const elapsedMs = elapsedSeconds * 1000;
    if (elapsedMs <= 0) break;
    const toPositionMs = positionMs + elapsedMs;
    const event = {
      watchSessionId: sessionId,
      deviceId: account.deviceId,
      eventId: randomId(),
      sequence: index,
      eventType: index === chunks ? 'pause' : 'checkpoint',
      dramaId: context.dramaId,
      episodeNo: context.episodeNo,
      fromPositionMs: positionMs,
      toPositionMs,
      elapsedMs,
      contentDurationMs: context.contentDurationMs,
      playing: true,
      foreground: true,
      visible: true,
      online: true,
    };
    const progress = await api(client, 'POST', '/points/watch-envelope/progress', { data: event });
    today = progress.today || today;
    const accepted = progress.acceptedDeltaMs || 0;
    acceptedTotalMs += accepted;
    const unlocked = Array.isArray(progress.unlockedSlots) ? progress.unlockedSlots.join(',') : '';
    const title = context.title ? `《${context.title}》` : context.dramaId;
    log(`时长：${index}/${chunks} ${title} 上报 ${Math.round(elapsedMs / 1000)} 秒，认可 ${Math.round(accepted / 1000)} 秒，累计认可 ${Math.round(acceptedTotalMs / 1000)} 秒${unlocked ? `，解锁 ${unlocked}` : ''}`);
    if (accepted <= 0 && SWITCH_ON_ZERO && contexts.length > 1) {
      contextIndex += 1;
      context = contexts[contextIndex % contexts.length];
      positionMs = 0;
      log(`时长：本段认可 0 秒，通常是服务端未认可该播放段；已切换短剧 -> ${context.title ? `《${context.title}》` : context.dramaId}`);
    } else if (accepted <= 0 && SWITCH_ON_ZERO) {
      log('时长：本段认可 0 秒，但短剧池只有 1 个，继续换播放位置尝试');
      positionMs = toPositionMs + WATCH_CHUNK_SECONDS * 1000;
    } else {
      positionMs = toPositionMs;
    }
    if (useUnlock && hasClaimableEnvelope(today)) break;
    if (index < chunks && WATCH_SLEEP_MS > 0) await sleep(WATCH_SLEEP_MS);
  }
  try {
    today = await api(client, 'GET', '/points/watch-envelope/today');
  } catch (_) {}
  log(`红包：${summarizeWatchEnvelope(today)}`);
  return today;
}

async function claimWatchEnvelopes(client, account, today) {
  if (!DO_CLAIM) return today;
  if (!account.userKey) {
    log('领取红包：缺少用户加密 key，已跳过');
    return today;
  }
  const slots = Array.isArray(today && today.slots) ? today.slots : [];
  const claimable = slots.filter((slot) => slot && slot.canClaim);
  if (!claimable.length) {
    log('领取红包：暂无可领取红包');
    return today;
  }
  for (const slot of claimable) {
    const mode = Array.isArray(slot.availableClaimModes) && slot.availableClaimModes.includes('direct') ? 'direct' : 'direct';
    const intent = await api(client, 'POST', '/points/watch-envelope/claim-intent', {
      data: { slotNo: slot.slotNo, mode, deviceId: account.deviceId },
    });
    const encrypted = encryptWithUserKey(account, intent.onceCode);
    const result = await api(client, 'POST', '/points/watch-envelope/claim-complete', {
      data: {
        claimIntentId: intent.claimIntentId,
        encryptedData: encrypted.encryptedData,
        version: encrypted.version,
      },
    });
    log(`红包：第 ${slot.slotNo} 个领取成功，获得 ${result.totalPoints || result.basePoints || 0}，余额 ${result.balance || '-'}`);
    await sleep(500);
  }
  try {
    return await api(client, 'GET', '/points/watch-envelope/today');
  } catch (_) {
    return today;
  }
}

async function processWatchEnvelopeRewards(client, account) {
  let today = null;
  // 缺加密 key 时无法领红包，只观看一轮赚积分即可，避免 20 轮空转
  const maxRounds = (CLAIM_ALL_ENVELOPES && account.userKey) ? ENVELOPE_MAX_ROUNDS : 1;
  let stoppedReason = '';
  for (let round = 1; round <= maxRounds; round += 1) {
    today = await doWatchTask(client, account);
    today = await claimWatchEnvelopes(client, account, today);
    log(`红包：第 ${round}/${maxRounds} 轮结束，${summarizeWatchEnvelope(today)}`);

    if (!CLAIM_ALL_ENVELOPES) break;
    if (isAllEnvelopesClaimed(today)) {
      log('红包：今日 20 个红包已全部领取完');
      break;
    }
    if (!DO_WATCH && !hasClaimableEnvelope(today)) {
      stoppedReason = '观看上报关闭，无法继续解锁后续红包';
      log(`红包：${stoppedReason}`);
      break;
    }
    if (ENVELOPE_ROUND_SLEEP_MS > 0) await sleep(ENVELOPE_ROUND_SLEEP_MS);
  }
  if (CLAIM_ALL_ENVELOPES && !isAllEnvelopesClaimed(today) && account.userKey) {
    const reason = stoppedReason || `已达到最大轮数 ${maxRounds}`;
    log(`红包：${reason}，仍未全部领取，当前 ${summarizeWatchEnvelope(today)}`);
  } else if (!account.userKey && !isAllEnvelopesClaimed(today)) {
    log('红包：缺少用户加密 key，未能领取；观看积分已上报');
  }
  return today;
}

function hasClaimableEnvelope(today) {
  const slots = Array.isArray(today && today.slots) ? today.slots : [];
  return slots.some((slot) => slot && slot.canClaim);
}

function isAllEnvelopesClaimed(today) {
  const slots = Array.isArray(today && today.slots) ? today.slots : [];
  return slots.length > 0 && slots.every((slot) => slot && slot.state === 'claimed');
}

function summarizeWatchEnvelope(today) {
  const slots = Array.isArray(today && today.slots) ? today.slots : [];
  const claimed = slots.filter((slot) => slot && slot.state === 'claimed').length;
  const claimable = slots.filter((slot) => slot && slot.canClaim).length;
  const nextSlot = today && today.nextSlotNo ? today.nextSlotNo : '-';
  const ratio = Number(today && today.nextProgressRatio || 0);
  const percent = Number.isFinite(ratio) ? `${(ratio * 100).toFixed(1)}%` : '-';
  const remainingMs = Number(today && (today.nextSlotRemainingMs || today.nextCheckpointMs) || 0);
  const remaining = remainingMs > 0 ? `${Math.ceil(remainingMs / 1000)}秒` : '-';
  return `已领 ${claimed}/${slots.length || '-'}，可领 ${claimable}，下一个 ${nextSlot}，进度 ${percent}，剩余约 ${remaining}`;
}

async function doWithdraw(client, account) {
  if (!DO_WITHDRAW) {
    log('提现：开关关闭，跳过；开启请设置 REELIX_WITHDRAW=1');
    return;
  }
  if (!account.userKey) {
    log('提现：缺少用户加密 key，已跳过');
    return;
  }
  if (WITHDRAW_POINTS_RAW && (!Number.isFinite(WITHDRAW_POINTS) || WITHDRAW_POINTS <= 0)) {
    log(`提现：REELIX_WITHDRAW_POINTS=${WITHDRAW_POINTS_RAW} 不是有效金额，已跳过`);
    return;
  }
  if (!Number.isFinite(WITHDRAW_MIN_POINTS) || WITHDRAW_MIN_POINTS <= 0) {
    log('提现：REELIX_WITHDRAW_MIN_POINTS 配置无效，已跳过');
    return;
  }

  const modeText = WITHDRAW_POINTS > 0
    ? `每次固定 ${WITHDRAW_POINTS} 金币`
    : `不填金额，按余额提全部可提现金币（${WITHDRAW_MIN_POINTS} 的整数倍）`;
  log(`提现：开关已开启，${modeText}，今日最多 ${WITHDRAW_DAILY_LIMIT} 次`);

  let todayWithdrawCount = await getTodayWithdrawCount(client);
  if (todayWithdrawCount >= WITHDRAW_DAILY_LIMIT) {
    log(`提现：今日已提交 ${todayWithdrawCount}/${WITHDRAW_DAILY_LIMIT} 次，停止提现`);
    return;
  }
  for (let round = 1; round <= WITHDRAW_MAX_ROUNDS; round += 1) {
    if (todayWithdrawCount >= WITHDRAW_DAILY_LIMIT) {
      log(`提现：今日已提交 ${todayWithdrawCount}/${WITHDRAW_DAILY_LIMIT} 次，停止提现`);
      return;
    }
    const balanceResp = await request(client, 'GET', '/points/balance');
    const balance = balanceResp.ok && balanceResp.data ? Number(balanceResp.data.balance || 0) : NaN;
    if (!Number.isFinite(balance)) {
      log(`提现：第 ${round} 轮余额查询失败，停止提现`);
      return;
    }

    const amount = getWithdrawAmount(balance);
    if (amount <= 0) {
      log(`提现：余额 ${balance}，暂无可提现金币，停止提现`);
      return;
    }

    if (WITHDRAW_DRY_RUN) {
      log(`提现：测试模式，第 ${round} 轮可提交 ${amount} 金币，当前余额 ${balance}，未提交`);
      return;
    }

    try {
      const intent = await api(client, 'POST', '/withdraw/intent');
      const body = buildSecurePayload(account, 'withdraw.create', { points: amount }, intent);
      const result = await api(client, 'POST', '/withdraw', { data: body });
      const item = result.withdrawal || result;
      const submitted = item.pointsAmount || amount;
      log(`提现：第 ${round} 轮已提交 ${submitted} 金币，现金 ${item.cashAmount || '-'}，状态 ${item.status || '-'}`);
      todayWithdrawCount += 1;
    } catch (error) {
      log(`提现：第 ${round} 轮失败：${error.message}`);
      return;
    }

    if (WITHDRAW_SLEEP_MS > 0) await sleep(WITHDRAW_SLEEP_MS);
  }
  log(`提现：已达到最大轮数 ${WITHDRAW_MAX_ROUNDS}，停止提现`);
}

async function getTodayWithdrawCount(client) {
  const resp = await request(client, 'GET', `/withdraw?page=1&pageSize=${Math.max(WITHDRAW_PAGE_SIZE, 20)}`);
  if (!resp.ok) {
    log(`提现：今日次数查询失败 ${resp.status}，按 0 次继续`);
    return 0;
  }
  const todayKey = formatDateKey(new Date());
  return summarizeList(resp.data).filter((item) => {
    const status = String(item.status || item.state || '').toLowerCase();
    if (!['pending', 'success'].includes(status)) return false;
    const rawTime = item.createdAt || item.createTime || item.created_at || '';
    const time = new Date(rawTime);
    return Number.isFinite(time.getTime()) && formatDateKey(time) === todayKey;
  }).length;
}

function formatDateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function getWithdrawAmount(balance) {
  if (!Number.isFinite(balance) || balance < WITHDRAW_MIN_POINTS) return 0;
  if (WITHDRAW_POINTS > 0) {
    return balance >= WITHDRAW_POINTS ? WITHDRAW_POINTS : 0;
  }
  return Math.floor(balance / WITHDRAW_MIN_POINTS) * WITHDRAW_MIN_POINTS;
}

async function runAccount(account) {
  await ensureBusinessLogin(account);
  const client = createClient(account);
  log(`\n====== 账号 ${account.index} ${account.remark || ''} ${account.isWechatProtocol ? account.accountId : mask(account.token)} ======`);

  const profileResp = await request(client, 'GET', '/customer/profile');
  if (!profileResp.ok) {
    const msg = `账号 ${account.index} 登录态可能失效：${profileResp.status} ${JSON.stringify(profileResp.data).slice(0, 120)}`;
    log(msg);
    appendNotify(msg);
    pushSummary({
      account: account.accountId,
      remark: account.remark,
      error: msg,
    });
    account._summarized = true;
    return false;
  }

  const profile = summarizeProfile(profileResp.data || {});
  let beforeTotalEarned = Number(profileResp.data.totalEarnedPoints || 0);
  log(`用户：${profile.name}`);
  log(`资料内积分/余额：${profile.points}`);
  log(`提现开关：${DO_WITHDRAW ? '已开启，任务全部完成后统一提现' : '已关闭'}`);

  const balanceResp = await request(client, 'GET', '/points/balance');
  let beforeBalanceData = null;
  if (balanceResp.ok) {
    beforeBalanceData = balanceResp.data || {};
    beforeTotalEarned = Number(beforeBalanceData.totalEarnedPoints || beforeTotalEarned || 0);
    const balance = typeof balanceResp.data === 'object' ? JSON.stringify(balanceResp.data) : String(balanceResp.data);
    log(`积分余额：${balance}`);
  } else {
    log(`积分余额查询失败：${balanceResp.status}`);
  }

  const signResp = await request(client, 'GET', '/points/sign-in/status');
  let signStatus = null;
  if (signResp.ok) {
    signStatus = signResp.data;
    const signed = signStatus.hasSignedIn ? '已签' : '未签';
    const days = signStatus.consecutiveDays || 0;
    log(`签到：${signed}，连续 ${days} 天`);
  } else {
    log(`签到状态查询失败：${signResp.status}`);
  }
  try {
    await doSignIn(client, account, signStatus);
  } catch (error) {
    log(`签到失败：${error.message}`);
  }

  try {
    await doVideoTask(client);
  } catch (error) {
    if (String(error.message).includes('LEGACY_REWARD_DISABLED')) {
      log('广告：旧版视频奖励已关闭，当前账号使用新版观看红包');
    } else {
      log(`广告：视频奖励失败：${error.message}`);
    }
  }

  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const calendarResp = await request(client, 'GET', `/points/sign-in/calendar?year=${year}&month=${month}`);
  if (calendarResp.ok) {
    const signedDays = calendarResp.data && calendarResp.data.signInMap
      ? Object.keys(calendarResp.data.signInMap).length
      : summarizeList(calendarResp.data).length;
    log(`${year}-${month} 签到日历记录数：${signedDays}`);
  } else {
    log(`签到日历查询失败：${calendarResp.status}`);
  }

  let today = null;
  try {
    today = await processWatchEnvelopeRewards(client, account);
  } catch (error) {
    log(`观看/领取红包失败：${error.message}`);
  }

  try {
    if (DO_WITHDRAW) log('提现：任务已完成，开始最终提现检测');
    await doWithdraw(client, account);
  } catch (error) {
    log(`提现：失败：${error.message}`);
  }

  const txResp = await request(client, 'GET', `/points/transactions?page=1&pageSize=${TX_PAGE_SIZE}`);
  if (txResp.ok) {
    const records = summarizeList(txResp.data);
    log(`最近积分流水：${records.length} 条`);
    records.slice(0, 5).forEach((item, idx) => {
      const type = item.type || item.transactionType || item.reason || 'unknown';
      const amount = item.amount || item.points || item.value || '';
      const time = item.createdAt || item.createTime || item.created_at || '';
      log(`  ${idx + 1}. ${type} ${amount} ${time}`);
    });
  } else {
    log(`积分流水查询失败：${txResp.status}`);
  }

  const withdrawResp = await request(client, 'GET', `/withdraw?page=1&pageSize=${WITHDRAW_PAGE_SIZE}`);
  if (withdrawResp.ok) {
    const records = summarizeList(withdrawResp.data);
    log(`最近提现记录：${records.length} 条`);
    records.slice(0, 5).forEach((item, idx) => {
      const points = item.pointsAmount || item.points || item.amount || item.money || '';
      const cash = item.cashAmount ? `/${item.cashAmount}` : '';
      const status = item.status || item.state || '';
      const time = item.createdAt || item.createTime || item.created_at || '';
      log(`  ${idx + 1}. ${points}${cash} ${status} ${time}`);
    });
  } else {
    log(`提现记录查询失败：${withdrawResp.status}`);
  }

  let currentPoints = profile.points;
  let earned = 0;
  const finalBalanceResp = await request(client, 'GET', '/points/balance');
  if (finalBalanceResp.ok && finalBalanceResp.data) {
    currentPoints = finalBalanceResp.data.balance ?? currentPoints;
    const finalTotalEarned = Number(finalBalanceResp.data.totalEarnedPoints || beforeTotalEarned || 0);
    earned = Math.max(0, finalTotalEarned - beforeTotalEarned);
  } else if (beforeBalanceData) {
    currentPoints = beforeBalanceData.balance ?? currentPoints;
  }

  pushSummary({
    account: account.accountId,
    remark: account.remark,
    value: currentPoints,
    reward: earned,
  });
  account._summarized = true;

  appendNotify(`账号 ${account.index}：${profile.name}，资料积分/余额 ${currentPoints}`);
  return true;
}

function randomId() {
  return `${Date.now().toString(36)}-${crypto.randomBytes(6).toString('hex')}-${Math.random().toString(36).slice(2, 8)}`;
}

function generateDeviceId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function pushSummary(item) {
  summaries.push({
    account: item.account,
    remark: item.remark || item.account,
    value: item.value ?? '-',
    reward: item.reward ?? 0,
    error: item.error || '',
  });
}

function printSummary() {
  log('\n======== 本次汇总 ========');
  for (const item of summaries) {
    if (item.error) {
      log(`当前账号：${item.account} 当前备注：${item.remark} 当前积分：- 本次获得：0 失败：${item.error}`);
    } else {
      log(`当前账号：${item.account} 当前备注：${item.remark} 当前积分：${item.value} 本次获得：${item.reward}`);
    }
  }
}

async function main() {
  const accounts = await parseAccounts();
  if (!accounts.length) return;

  let success = 0;
  const concurrency = Math.min(ACCOUNT_CONCURRENCY, accounts.length);
  log(`账号执行：共 ${accounts.length} 个账号，并发 ${concurrency}`);
  await runWithConcurrency(accounts, concurrency, async (account) => {
    try {
      const ok = await runAccount(account);
      if (ok) success += 1;
    } catch (error) {
      const msg = `账号 ${account.index} 异常：${error.message}`;
      log(msg);
      appendNotify(msg);
      if (!account._summarized) {
        pushSummary({
          account: account.accountId,
          remark: account.remark,
          error: error.message,
        });
      }
    }
  });

  log(`\n完成：${success}/${accounts.length}`);
  printSummary();
  if (notifyText.trim()) {
    log('\n通知摘要：');
    log(notifyText.trim());
  }
}

async function runWithConcurrency(items, limit, worker) {
  let cursor = 0;
  const runners = Array.from({ length: limit }, async () => {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      await worker(items[index], index);
    }
  });
  await Promise.all(runners);
}

main().catch((error) => {
  log(`脚本异常：${error.message}`);
  if (error.stack) log(error.stack);
});