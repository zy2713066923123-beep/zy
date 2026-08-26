require('./yyb.js'); // 自动同步 yyb_go 存活账号
// name: 战马万里行
// cron: 16 7,17 * * *

const axios = require('axios');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://whjourney.campaign-design.com';
const APP_API = 'https://warhorsechina.cojoy.com.cn/app/api';
const ENV_NAME = 'wxwhmlx';
const APPID = 'wx94dca6ef07a54c55';
const SIGN_KEY = '7k3xq2mfp9wberz4tvug';
const SIGN_IV = 'h5n8c2vq6rtwea3zkxpl';
const CUSTOM_APPID = APPID;
const SKEY_HEADER = 'cGvnZetrWSWfLcdYaN40mLdFx6ObkRltdZmhS5hQkgDbuZd9bLcQevwBVEjx-war-horse-zm-2025';
const UA = process.env.WHMLX_UA || 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.75(0x18004b61) NetType/4G Language/zh_CN miniProgram/wx94dca6ef07a54c55';
const DEVICE_FP = process.env.WHMLX_FP || '99b86cf2f6051e62c0caf71c2794f7df';
const GAME_WAIT_MS = parseInt(process.env.WHMLX_WAIT_MS || '30500', 10);
const MAX_CITY = parseInt(process.env.WHMLX_MAX_CITY || '20', 10);
const COMPLETE_CITY_COUNT = parseInt(process.env.WHMLX_COMPLETE_CITY_COUNT || '16', 10);
const DRAW = process.env.WHMLX_DRAW !== '0';
const STATUS_ONLY = process.env.WHMLX_STATUS_ONLY === '1';
const DEBUG = process.env.debug === '1' || process.env.WHMLX_DEBUG === '1';
const ACCOUNT_GAP_MS = Math.max(1000, parseInt(process.env.WHMLX_ACCOUNT_GAP_MS || '3000', 10));
const CONCURRENCY = Math.max(1, parseInt(process.env.WHMLX_CONCURRENCY || '0', 10) || 0);
const ACCOUNT_RAW = String(process.env.WX_ID || process.env[ENV_NAME] || process.env.WHMLX_ACCOUNTS || process.env.whmlx || '').trim();
const CACHE_FILE = path.join(process.cwd(), '.cache', 'warhorse_journey.json');

let msg = '';
const summaries = [];
function log(s) { console.log(s); }
function addNotify(s) { log(s); msg += s + '\n'; }
function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

function brief(data, max = 320) {
  if (data == null) return '空响应';
  if (typeof data === 'string') return data.slice(0, max);
  try {
    return JSON.stringify(data).slice(0, max);
  } catch {
    return String(data).slice(0, max);
  }
}

function isProtocolAccountId(id) {
  const s = String(id || '').trim();
  // 支持三种账号格式：
  // 1. 牛子：wxid_ 开头
  // 2. 应用宝显式前缀：yyb: 开头
  // 3. 应用宝 openid：o 开头 + 20+ 位字母数字（可含 - _），如 owNAX6...
  return s.startsWith('wxid_') || s.startsWith('yyb:') || /^o[a-zA-Z0-9_-]{20,}$/.test(s);
}

function parseAccounts(raw) {
  return String(raw || '')
    .split(/[\n&]+/)
    .map(x => x.trim())
    .filter(Boolean)
    .map((line, idx) => {
      const p = line.indexOf('#');
      const id = (p >= 0 ? line.slice(0, p) : line).trim();
      const remark = ((p >= 0 ? line.slice(p + 1) : '') || `账号${idx + 1}`).trim();
      if (!id) return null;
      if (!isProtocolAccountId(id)) {
        log('[警告] 非协议账号格式，跳过: ' + line);
        return null;
      }
      return { id, remark, raw: line };
    })
    .filter(Boolean);
}

function accountTag(account) {
  return account ? `${account.id}(${account.remark})` : '单账号';
}

function ensureCacheDir() {
  const dir = path.dirname(CACHE_FILE);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function loadCache() {
  try {
    if (fs.existsSync(CACHE_FILE)) return JSON.parse(fs.readFileSync(CACHE_FILE, 'utf8'));
  } catch (e) {
    log('读取缓存失败: ' + e.message);
  }
  return {};
}

function saveCache(data) {
  try {
    ensureCacheDir();
    fs.writeFileSync(CACHE_FILE, JSON.stringify(data, null, 2), 'utf8');
  } catch (e) {
    log('保存缓存失败: ' + e.message);
  }
}

function getAccountCache(cache, account) {
  if (!account) return cache.default || cache;
  return cache[account.id] || {};
}

function setAccountCache(cache, account, value) {
  if (!account) {
    cache.default = value;
    return;
  }
  cache[account.id] = value;
}

function saveAccountCache(account, value) {
  const latest = loadCache();
  setAccountCache(latest, account, value);
  saveCache(latest);
}

function addSummary(item) {
  summaries.push({
    account: item.account,
    remark: item.remark || item.account,
    current: item.current || '-',
    passed: item.passed ?? '-',
    normalChance: item.normalChance ?? '-',
    reward: item.reward || 0,
    error: item.error || ''
  });
}

function printSummary() {
  log('\n======== 本次汇总 ========');
  if (!summaries.length) {
    log('无账号结果');
    return;
  }
  for (const s of summaries) {
    if (s.error) {
      log(`当前账号：${s.account} 当前备注：${s.remark} 当前城市：${s.current} 已通关：${s.passed} 当前抽奖次数：${s.normalChance} 本次获得：${s.reward} 失败：${s.error}`);
    } else {
      log(`当前账号：${s.account} 当前备注：${s.remark} 当前城市：${s.current} 已通关：${s.passed} 当前抽奖次数：${s.normalChance} 本次获得：${s.reward}`);
    }
  }
}

function isJwtValid(token) {
  try {
    const payload = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString());
    return payload.exp && Date.now() < payload.exp * 1000 - 60000;
  } catch {
    return false;
  }
}

function md5Buffer(str) {
  return crypto.createHash('md5').update(str).digest();
}

function makeSignatureGuard() {
  const plain = Date.now() + ':' + crypto.randomUUID();
  const cipher = crypto.createCipheriv('aes-128-cbc', md5Buffer(SIGN_KEY), md5Buffer(SIGN_IV));
  return Buffer.concat([cipher.update(plain, 'utf8'), cipher.final()]).toString('base64');
}

function parseAuthParams(input) {
  const raw = input.trim();
  const url = raw.includes('://') ? new URL(raw) : new URL(BASE_URL + '?' + raw.replace(/^\?/, ''));
  const keys = ['tel', 'safe_code', 'timestamp', 'request_id', 'sign'];
  const data = {};
  for (const key of keys) data[key] = url.searchParams.get(key);
  if (keys.some(key => !data[key])) throw new Error('H5授权URL缺少参数: ' + keys.filter(key => !data[key]).join(', '));
  return data;
}

async function appRequest(method, url, data, skey) {
  try {
    const resp = await axios({
      method,
      url,
      data,
      timeout: 30000,
      headers: {
        'content-type': 'application/json',
        [SKEY_HEADER]: skey,
        CUSTOMAPPID: CUSTOM_APPID,
        'User-Agent': UA,
        Referer: 'https://servicewechat.com/wx94dca6ef07a54c55/182/page-frame.html'
      }
    });
    if (DEBUG) log('[APP] ' + url + ' => ' + JSON.stringify(resp.data).slice(0, 300));
    return resp.data;
  } catch (e) {
    log('APP请求失败: ' + url + ' - ' + e.message);
    return null;
  }
}

async function getWxCode(accountId) {
  const wxid = String(accountId || '').trim().split('#')[0].trim();
  const code = await getSingleCode(APPID, wxid);
  if (!code) throw new Error('getCode 未提取到 wx code');
  return code;
}

async function getPhoneEncrypted(accountId) {
  const wxid = String(accountId || '').trim().split('#')[0].trim();
  // 优先走 getCode 智能路由（牛子 → operate 完整数据；应用宝 → 仅 code）
  const operate = await getSingleOperateWxData(APPID, wxid);
  if (operate && operate.encryptedData && operate.iv) {
    return { encryptedData: operate.encryptedData, iv: operate.iv };
  }
  // 应用宝(YYB)协议无 operate 加密载荷，退化为手机号加密数据接口
  const phone = await getSinglePhoneEncrypted(APPID, wxid);
  if (phone && phone.encryptedData && phone.iv) {
    return { encryptedData: phone.encryptedData, iv: phone.iv };
  }
  throw new Error('未提取到手机号 encryptedData/iv（getCode 仅返回手机号 code，需换 YYB 账号或检查服务）');
}

async function wxPhoneLoginByCode(code, phonePair) {
  try {
    const resp = await axios({
      method: 'post',
      url: APP_API + '/wxphonelogin',
      data: { profile: {} },
      timeout: 30000,
      validateStatus: () => true,
      headers: {
        'content-type': 'application/json',
        [SKEY_HEADER]: SKEY_HEADER,
        CUSTOMAPPID: CUSTOM_APPID,
        'X-WX-Code': code,
        'X-WX-Encrypted-Data': phonePair.encryptedData,
        'X-WX-IV': phonePair.iv,
        'User-Agent': UA,
        Referer: 'https://servicewechat.com/wx94dca6ef07a54c55/182/page-frame.html'
      }
    });
    if (DEBUG) log('[APP] wxphonelogin => ' + resp.status + ' ' + brief(resp.data));
    if (resp.status >= 200 && resp.status < 300 && resp.data && resp.data.status === 'ok' && resp.data.desc && resp.data.desc.data) {
      return resp.data.desc.data;
    }
    throw new Error(brief(resp.data || resp.status));
  } catch (e) {
    throw new Error('wxphonelogin失败: ' + e.message);
  }
}

async function getSkeyByProtocol(account) {
  if (!account) return process.env.WHMLX_SKEY || '';
  log('[' + accountTag(account) + '] 协议取手机号密文...');
  const phonePair = await getPhoneEncrypted(account.id);
  log('[' + accountTag(account) + '] 协议取 wx.login code...');
  const code = await getWxCode(account.id);
  const data = await wxPhoneLoginByCode(code, phonePair);
  if (!data.skey) throw new Error('登录返回缺少 skey: ' + brief(data));
  return data;
}

async function fetchH5AuthUrlBySkey(skey) {
  const resp = await appRequest('post', APP_API + '/user', { action: 'h5authn2' }, skey);
  if (resp && resp.status === 'ok' && resp.desc && resp.desc.url) return resp.desc.url;
  throw new Error('获取H5授权URL失败: ' + JSON.stringify(resp));
}

function createJourneyClient(token, referer) {
  const client = axios.create({
    baseURL: BASE_URL,
    timeout: 30000,
    headers: {
      'Content-Type': 'application/json',
      Origin: BASE_URL,
      Referer: referer || BASE_URL + '/',
      'User-Agent': UA
    }
  });
  client.interceptors.request.use(config => {
    config.headers.Authorization = 'Bearer ' + (token || '');
    config.headers['X-Device-Fingerprint'] = DEVICE_FP;
    config.headers['X-Signature-Guard'] = makeSignatureGuard();
    return config;
  });
  return client;
}

async function journeyRequest(client, method, url, data, retries = 1) {
  try {
    const config = { method, url };
    if (method.toLowerCase() !== 'get') config.data = data || {};
    const resp = await client(config);
    if (DEBUG) log('[H5] ' + method.toUpperCase() + ' ' + url + ' => ' + JSON.stringify(resp.data).slice(0, 300));
    return resp.data;
  } catch (e) {
    if (retries > 0) {
      await sleep(1000);
      return journeyRequest(client, method, url, data, retries - 1);
    }
    const body = e.response && e.response.data ? ' ' + JSON.stringify(e.response.data) : '';
    log('H5请求失败: ' + method.toUpperCase() + ' ' + url + ' - ' + e.message + body);
    return null;
  }
}

async function getToken(account) {
  const cache = loadCache();
  const accountCache = getAccountCache(cache, account);
  if (!account && process.env.WHMLX_TOKEN && isJwtValid(process.env.WHMLX_TOKEN)) {
    accountCache.token = process.env.WHMLX_TOKEN;
    saveAccountCache(account, accountCache);
    return { token: process.env.WHMLX_TOKEN, referer: accountCache.referer };
  }
  if (accountCache.token && isJwtValid(accountCache.token)) return { token: accountCache.token, referer: accountCache.referer };

  let authUrl = process.env.WHMLX_AUTH_URL || process.env.WHMLX_AUTH_QUERY || '';
  let skey = process.env.WHMLX_SKEY || accountCache.skey || '';
  if (!authUrl && !skey && account) {
    log('[' + accountTag(account) + '] 协议登录获取 skey...');
    const loginData = await getSkeyByProtocol(account);
    skey = loginData.skey;
    accountCache.skey = loginData.skey;
    accountCache.f1safe = loginData.f1safe || accountCache.f1safe || '';
    accountCache.expire = loginData.expire || 0;
    accountCache.type = loginData.type || '';
    accountCache.remark = account.remark;
    saveAccountCache(account, accountCache);
  }
  if (!authUrl && skey) {
    try {
      authUrl = await fetchH5AuthUrlBySkey(skey);
    } catch (e) {
      if (!account) throw e;
      log('[' + accountTag(account) + '] 缓存 skey 失效，重新协议登录: ' + e.message);
      const loginData = await getSkeyByProtocol(account);
      skey = loginData.skey;
      accountCache.skey = loginData.skey;
      accountCache.f1safe = loginData.f1safe || accountCache.f1safe || '';
      accountCache.expire = loginData.expire || 0;
      accountCache.type = loginData.type || '';
      accountCache.remark = account.remark;
      saveAccountCache(account, accountCache);
      authUrl = await fetchH5AuthUrlBySkey(skey);
    }
  }
  if (!authUrl) throw new Error('请设置账号变量 ' + ENV_NAME + '，或 WHMLX_SKEY，或 WHMLX_AUTH_URL/WHMLX_AUTH_QUERY，或有效 WHMLX_TOKEN');

  const params = parseAuthParams(authUrl);
  const referer = authUrl.includes('://') ? authUrl : BASE_URL + '?' + authUrl.replace(/^\?/, '');
  const client = createJourneyClient('', referer);
  const login = await journeyRequest(client, 'post', '/api/auth/h5/login', params);
  if (!login || login.code !== 200 || !login.data) throw new Error('H5登录失败: ' + JSON.stringify(login));

  accountCache.token = login.data;
  accountCache.referer = referer;
  accountCache.updateTime = Date.now();
  if (account) accountCache.remark = account.remark;
  saveAccountCache(account, accountCache);
  return { token: login.data, referer };
}

async function getUser(client) {
  const resp = await journeyRequest(client, 'get', '/api/users');
  return resp && resp.code === 200 ? resp.data : null;
}

async function drawOnce(client, label, runStat) {
  const resp = await journeyRequest(client, 'post', '/api/prize', { pool_type: 1 });
  if (!resp || resp.code !== 200 || !resp.data) {
    log('抽奖失败: ' + JSON.stringify(resp));
    return null;
  }
  const p = resp.data;
  addNotify(label + '中奖: ' + p.prize_name + (p.coupon_code ? ' 券码: ' + p.coupon_code : ''));
  if (runStat) runStat.reward += 1;
  return p;
}

async function drawAndShare(client, runStat, minDraws = 0) {
  if (!DRAW) return;
  let forcedDraws = Math.max(0, Number(minDraws || 0));
  let user = await getUser(client);
  let count = user ? user.normal_chance_count : 0;
  while (count > 0 || forcedDraws > 0) {
    const prize = await drawOnce(client, '普通抽奖', runStat);
    if (forcedDraws > 0) forcedDraws--;
    if (prize && prize.can_share && prize.chance_id) {
      const share = await journeyRequest(client, 'post', '/api/prize/prize_share', {
        city_code: prize.city_code,
        chance_id: prize.chance_id
      });
      if (share && share.code === 200) {
        log('分享领奖成功，获得额外抽奖机会');
        await sleep(800);
        await drawOnce(client, '分享抽奖', runStat);
      } else {
        log('分享领奖失败: ' + JSON.stringify(share));
      }
    }
    await sleep(1200);
    user = await getUser(client);
    count = user ? user.normal_chance_count : 0;
  }
}

async function runOneCity(client, user, runStat) {
  const city = user.current_city_code;
  addNotify('当前城市: ' + city + '，已通关城市数: ' + user.passed_city_count + '，本城机会: ' + user.current_city_chance);

  if (Number(user.passed_city_count || 0) >= COMPLETE_CITY_COUNT) {
    addNotify('已通关 ' + user.passed_city_count + ' 城，停止挑战，避免消耗最终城残余机会');
    await drawAndShare(client, runStat);
    return false;
  }

  if (user.current_city_chance <= 0) {
    if (user.share_count < 3) {
      const share = await journeyRequest(client, 'post', '/api/game/share', { city_code: city });
      log('游戏分享补机会: ' + JSON.stringify(share && share.data ? share.data : share));
      await sleep(800);
    } else {
      addNotify('本城机会已用完，且分享次数已达上限');
      return false;
    }
  }

  const start = await journeyRequest(client, 'post', '/api/game/start', { city_code: city });
  if (!start || start.code !== 200) {
    addNotify('开始游戏失败: ' + JSON.stringify(start));
    return false;
  }
  log('游戏已开始，等待 ' + GAME_WAIT_MS + 'ms 后提交通关');
  await sleep(GAME_WAIT_MS);

  const end = await journeyRequest(client, 'post', '/api/game/end', { city_code: city });
  if (!end || end.code !== 200 || !end.data || !end.data.passed) {
    addNotify('通关失败: ' + JSON.stringify(end));
    return false;
  }
  addNotify('通关成功: ' + city + ' -> ' + end.data.next_city_code + '，新增抽奖次数: ' + end.data.add_chance);
  await sleep(1000);
  const terminalSameCity = String(end.data.next_city_code || '') === String(city);
  const minDraws = Math.max(Number(end.data.add_chance || 0), terminalSameCity ? 1 : 0);
  if (terminalSameCity && Number(end.data.add_chance || 0) <= 0) {
    addNotify('终点通关未返回新增次数，兜底尝试抽奖一次');
  }
  await drawAndShare(client, runStat, minDraws);
  if (terminalSameCity && Number(end.data.add_chance || 0) <= 0) {
    addNotify('下一城市仍为 ' + city + ' 且未新增抽奖次数，判定已到终点，停止继续挑战');
    return false;
  }
  return true;
}

async function runAccount(account) {
  const tag = accountTag(account);
  const runStat = { reward: 0 };
  addNotify('开始账号: ' + tag);
  const { token, referer } = await getToken(account);
  const client = createJourneyClient(token, referer);

  if (STATUS_ONLY) {
    const user = await getUser(client);
    if (!user) throw new Error('获取用户状态失败');
    addNotify('当前状态: 手机 ' + user.mobile + '，已通关 ' + user.passed_city_count + '，当前城市 ' + user.current_city_code + '，本城机会 ' + user.current_city_chance + '，普通抽奖次数 ' + user.normal_chance_count + '，分享次数 ' + user.share_count);
    addSummary({
      account: account ? account.id : '单账号',
      remark: account ? account.remark : '单账号',
      current: user.current_city_code,
      passed: user.passed_city_count,
      normalChance: user.normal_chance_count,
      reward: 0
    });
    return;
  }

  for (let i = 0; i < MAX_CITY; i++) {
    const user = await getUser(client);
    if (!user) throw new Error('获取用户状态失败');
    if (!user.current_city_code) {
      addNotify('没有待通关城市，任务结束');
      break;
    }
    if (Number(user.passed_city_count || 0) >= COMPLETE_CITY_COUNT) {
      addNotify('已通关 ' + user.passed_city_count + ' 城，任务结束');
      await drawAndShare(client, runStat);
      break;
    }
    const ok = await runOneCity(client, user, runStat);
    if (!ok) break;
    await sleep(1500);
  }

  const finalUser = await getUser(client);
  if (finalUser) {
    addNotify('最终状态: 已通关 ' + finalUser.passed_city_count + '，当前城市 ' + finalUser.current_city_code + '，普通抽奖次数 ' + finalUser.normal_chance_count);
    addSummary({
      account: account ? account.id : '单账号',
      remark: account ? account.remark : '单账号',
      current: finalUser.current_city_code,
      passed: finalUser.passed_city_count,
      normalChance: finalUser.normal_chance_count,
      reward: runStat.reward
    });
  } else {
    addSummary({
      account: account ? account.id : '单账号',
      remark: account ? account.remark : '单账号',
      reward: runStat.reward,
      error: '最终状态获取失败'
    });
  }
}

async function runAccountsConcurrent(accounts, limit) {
  let cursor = 0;
  async function worker(workerId) {
    while (true) {
      const index = cursor++;
      if (index >= accounts.length) return;
      const account = accounts[index];
      try {
        log('[并发' + workerId + '] 开始第 ' + (index + 1) + '/' + accounts.length + ' 个账号');
        await runAccount(account);
      } catch (e) {
        log('[' + accountTag(account) + '] 账号异常: ' + e.message);
        if (DEBUG) log(e.stack);
        addSummary({
          account: account.id,
          remark: account.remark,
          error: e.message
        });
      }
    }
  }

  const size = Math.max(1, Math.min(limit || accounts.length, accounts.length));
  await Promise.all(Array.from({ length: size }, (_, i) => worker(i + 1)));
}

async function main() {
  addNotify('战马万里行脚本启动');
  const accounts = parseAccounts(ACCOUNT_RAW);

  if (accounts.length) {
    log('账号数: ' + accounts.length);
    log('取码方式: getCode(WX_ID) 智能路由');
    const concurrency = CONCURRENCY || accounts.length;
    log('并发数: ' + Math.min(concurrency, accounts.length));
    await runAccountsConcurrent(accounts, concurrency);
  } else {
    if (!process.env.WHMLX_SKEY && !process.env.WHMLX_AUTH_URL && !process.env.WHMLX_AUTH_QUERY && !process.env.WHMLX_TOKEN) {
      log('未找到账号。请设置环境变量 ' + ENV_NAME + '(或 WX_ID)，格式：wxid_xxx#备注 / yyb:openid#备注 / 应用宝openid#备注');
    }
    try {
      await runAccount(null);
    } catch (e) {
      log('脚本异常: ' + e.message);
      if (DEBUG) log(e.stack);
      addSummary({ account: '单账号', remark: '单账号', error: e.message });
    }
  }

  printSummary();
}

main().catch(e => {
  log('脚本异常: ' + e.message);
  if (DEBUG) log(e.stack);
  printSummary();
});