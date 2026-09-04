/*
 * name: 华银康智医
 * cron: 56 18,08 * * *
 *
 * 账号来源：与其余脚本一致，统一走 yyb 账号服务（同目录 yyb.js）
 *   - 默认自动拉取 yyb_go 全部存活账号，无需配置账号变量
 *   - 只想跑指定账号时才配置 WX_ID / HYK_WX_ACCOUNTS
 *
 * 环境变量:
 *   WX_SERVER=http://127.0.0.1:18273   yyb 协议服务地址（兼容 YYB_SERVER / WECHAT_SERVER）
 *   WX_ID='openid#备注'                可选白名单，换行或 & 分隔
 *   HYK_WX_ACCOUNTS='openid#备注'
 *                   兼容 HUAYINKANG_WX_ACCOUNTS / WX_ACCOUNTS，换行或 & 分隔
 *   HYK_APPID       可选，默认 wx1be9d6de200feb56
 *   HYK_TASK_ROUNDS 可选，默认 2，>1 时会复查任务是否可重复领取
 *   HYK_FILL_ARCHIVE=1 可选，自动填写健康档案以解锁「完善健康档案」任务（会写入账号资料）
 *   HYK_TRY_DISABLED=1 可选，连后台 enabled=false 的任务 id 一起试（第 32-60 天打卡）
 *   HYK_TASK_DELAY  可选，任务之间的固定间隔毫秒；不设置时随机 600-1600ms
 *   HYK_NOTIFY=0    可选，关闭推送
 *
 * 缓存 key 使用 yyb 返回的账号标识（openid），避免串号。
 */

const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');

const yyb = require('./yyb.js'); // 自动同步 yyb_go 存活账号
const { YYBClient, getSingleCode, getSinglePhoneEncrypted, getSinglePhoneCode, resolveAccounts } = yyb;

const APP_NAME = '华银康智医';
const APPID = process.env.HYK_APPID || 'wx1be9d6de200feb56';
const API_BASE = 'https://cduan.huayinhealth.com:31231/api/';
const REFERER = `https://servicewechat.com/${APPID}/45/page-frame.html`;
const UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.75(0x18004b66) NetType/4G Language/zh_CN';

const ACCOUNT_ENV =
  process.env.HYK_WX_ACCOUNTS ||
  process.env.HUAYINKANG_WX_ACCOUNTS ||
  process.env.WX_ID ||
  process.env.WX_ACCOUNTS ||
  '';
const CACHE_FILE = path.join(__dirname, 'hykzy_cache.json');

// 与小程序 taskCenter 的 types 常量一致，覆盖打卡 + 日常 + 一次性 + 拉新
const TASK_TYPES = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '11'];
const TASK_ROUNDS = Math.max(1, Number(process.env.HYK_TASK_ROUNDS || 2));
const FILL_ARCHIVE = process.env.HYK_FILL_ARCHIVE === '1';
const TRY_DISABLED = process.env.HYK_TRY_DISABLED === '1';

const summaries = [];
const taskNotices = [];
let cache = readJson(CACHE_FILE, {});

class TokenInvalidError extends Error {}

// ====================== 账号解析 ======================

// 环境变量条目：openid#备注（兼容 wxid_xxx / wx:xxx / yyb:openid 写法）
function parseWxAccount(line) {
  const raw = String(line || '').trim();
  const parts = raw.split('#');
  const id = String(parts[0] || '').trim().replace(/^(wx|yyb|wmpf|syzs):/i, '');
  const remark = (parts.slice(1).join('#') || id).trim();
  return { raw, id, remark: remark || id };
}

// 账号来源：优先从 yyb_go 拉取全部存活账号，拉取不到再回退环境变量
async function loadYybAccounts() {
  try {
    const online = await new YYBClient().getOnlineAccounts();
    const accounts = (online || [])
      .map((acc) => {
        const id = String(acc.openid || acc.wxid || acc.id || '').trim();
        if (!id) return null;
        const remark = acc.remark || acc.nickname || acc.alias || id;
        return { id, remark };
      })
      .filter(Boolean);
    if (accounts.length) {
      console.log(`[yyb] 自动从 yyb_go 同步到 ${accounts.length} 个存活账号`);
      return accounts;
    }
  } catch (e) {
    console.log(`[yyb] 拉取存活账号失败: ${e.message || e}`);
  }

  const auto = await resolveAccounts();
  if (auto && auto.length) return auto.map(parseWxAccount).filter((x) => x.id);

  return ACCOUNT_ENV.split(/[\n&]+/).map(parseWxAccount).filter((x) => x.id);
}

// ====================== 基础请求 ======================

function request(method, url, options = {}) {
  const target = new URL(url);
  const body = options.body == null
    ? null
    : (typeof options.body === 'string' ? options.body : JSON.stringify(options.body));
  const headers = Object.assign({}, options.headers || {});
  const hasContentType = Object.keys(headers).some((k) => k.toLowerCase() === 'content-type');
  if (body != null && !hasContentType) headers['Content-Type'] = 'application/json';
  if (body != null) headers['Content-Length'] = Buffer.byteLength(body);
  else if (method === 'POST') headers['Content-Length'] = 0;

  return new Promise((resolve, reject) => {
    const lib = target.protocol === 'https:' ? https : http;
    const req = lib.request({
      method,
      hostname: target.hostname,
      port: target.port || undefined,
      path: `${target.pathname}${target.search}`,
      headers,
      timeout: options.timeout || 20000,
    }, (res) => {
      const chunks = [];
      res.on('data', (d) => chunks.push(d));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        let data = text;
        try { data = JSON.parse(text); } catch {}
        resolve({ status: res.statusCode, headers: res.headers, data, text });
      });
    });
    req.on('timeout', () => req.destroy(new Error('request timeout')));
    req.on('error', reject);
    if (body != null) req.write(body);
    req.end();
  });
}

function encodeForm(obj) {
  return Object.entries(obj)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&');
}

// ====================== 微信协议侧（统一走 yyb.js） ======================

async function getWxCode(account) {
  const code = await getSingleCode(APPID, account.id);
  if (!code) throw new Error('未取到 wx.login code');
  return code;
}

// 手机号授权：优先取 encryptedData/iv 三件套，拿不到再退化为 phoneCode
async function getPhoneAuth(account) {
  let res = null;
  try {
    res = await getSinglePhoneEncrypted(APPID, account.id);
  } catch (e) {
    console.log(`[${account.remark}] 获取手机号加密数据失败: ${e.message || e}`);
  }
  if (res && (res.code || (res.encryptedData && res.iv))) {
    return {
      phoneCode: res.code || '',
      encryptedData: res.encryptedData || '',
      iv: res.iv || '',
      mobile: res.mobile || '',
    };
  }
  const code = await getSinglePhoneCode(APPID, account.id);
  if (!code) throw new Error('未取到手机号授权数据');
  return { phoneCode: code, encryptedData: '', iv: '', mobile: '' };
}

// ====================== 业务侧 ======================

function bizHeaders(token, extra = {}) {
  const headers = {
    'content-type': 'application/json',
    userType: 'PATIENT',
    'User-Agent': UA,
    Referer: REFERER,
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return Object.assign(headers, extra);
}

function isBizOk(data) {
  return !!data && typeof data === 'object' && String(data.code) === '0';
}

function isTokenInvalid(status, data) {
  if (status === 401 || status === 403) return true;
  if (!data || typeof data !== 'object') return false;
  const code = String(data.code == null ? '' : data.code);
  if (code === '-1') return true;
  if (code === '0003' && String(data.message || '').includes('登录')) return true;
  return false;
}

// 业务接口统一入口：透传 code != "0" 的原始响应，token 失效抛 TokenInvalidError
async function bizRequest(method, url, token, body, options = {}) {
  let lastErr = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await request(method, `${API_BASE}${url}`, {
        body,
        headers: bizHeaders(token),
        timeout: options.timeout || 20000,
      });
      if (isTokenInvalid(res.status, res.data)) {
        throw new TokenInvalidError(`token 失效: ${short(res.data)}`);
      }
      return res.data;
    } catch (e) {
      if (e instanceof TokenInvalidError) throw e;
      lastErr = e;
      if (attempt < 2) await sleep(2000);
    }
  }
  throw new Error(`请求 ${url} 失败: ${(lastErr && lastErr.message) || lastErr}`);
}

function bizGet(url, token, options) {
  return bizRequest('GET', url, token, undefined, options);
}

function bizPost(url, token, body, options) {
  return bizRequest('POST', url, token, body, options);
}

async function getSession(account) {
  const saved = cache[account.id];
  if (saved && saved.token) {
    const profile = await getPatientProfile(saved.token).catch((e) => {
      if (e instanceof TokenInvalidError) return null;
      throw e;
    });
    if (profile) {
      console.log(`[${account.remark}] 缓存 token 有效，跳过协议登录`);
      return { token: saved.token, profile, fresh: false };
    }
    console.log(`[${account.remark}] 缓存 token 失效，重新走协议登录`);
    dropCache(account.id);
  }
  return businessLogin(account);
}

// 授权注册/登录：wx.login code + 手机号授权 -> oauth2/access_token
async function businessLogin(account) {
  console.log(`[${account.remark}] 请求微信协议 wx.login code`);
  const code = await getWxCode(account);
  console.log(`[${account.remark}] 请求手机号授权数据`);
  const phone = await getPhoneAuth(account);

  const form = {
    grant_type: 'miniprogram_code',
    ex_fmt: 'daoben',
    code,
    iv: phone.iv,
    encryptedData: phone.encryptedData,
    phoneCode: phone.phoneCode,
    userType: 'PATIENT',
  };
  const res = await request('POST', `${API_BASE}app/oauth2/access_token`, {
    body: encodeForm(form),
    headers: {
      'content-type': 'application/x-www-form-urlencoded',
      userType: 'PATIENT',
      'User-Agent': UA,
      Referer: REFERER,
    },
  });
  const data = res.data;
  if (!isBizOk(data) || !(data.data && data.data.access_token)) {
    throw new Error(`授权登录失败: ${short(data)}`);
  }

  const token = data.data.access_token;
  const registerFlag = !!(data.data.details && data.data.details.registerFlag);
  console.log(`[${account.remark}] ${registerFlag ? '首次授权注册成功' : '授权登录成功'}，uid=${data.data.uid || '-'}`);

  // 小程序端每次登录成功都会确认协议版本，新注册账号必须调用
  await confirmAgreement(token, account.remark);

  const profile = await getPatientProfile(token);
  if (!profile) throw new Error('登录后 getPatientProfile 校验未通过');

  cache[account.id] = {
    remark: account.remark,
    token,
    refreshToken: data.data.refresh_token || '',
    uid: data.data.uid || '',
    mobile: maskMobile(profile.mobile || phone.mobile),
    registerFlag,
    updateTime: Date.now(),
  };
  writeJson(CACHE_FILE, cache);
  return { token, profile, fresh: true };
}

async function confirmAgreement(token, remark) {
  try {
    const conf = await bizGet('patient/agreementConfig/queryEnableAgreementConfig', token);
    const list = isBizOk(conf) && Array.isArray(conf.data) ? conf.data : [];
    const pick = (type) => {
      const hit = list.find((x) => x && x.agreementType === type);
      return hit && hit.version ? hit.version : '';
    };
    const body = {
      data: {
        userAgreementVersion: pick('USER_AGREEMENT'),
        privacyAgreementVersion: pick('PRIVACY_AGREEMENT'),
      },
    };
    const res = await bizPost('patient/profile/confirmLoginAgreement', token, body);
    if (isBizOk(res)) {
      console.log(`[${remark}] 协议确认完成 (用户${body.data.userAgreementVersion || '-'} / 隐私${body.data.privacyAgreementVersion || '-'})`);
    } else {
      console.log(`[${remark}] 协议确认返回异常: ${short(res)}`);
    }
  } catch (e) {
    if (e instanceof TokenInvalidError) throw e;
    console.log(`[${remark}] 协议确认失败: ${e.message}`);
  }
}

async function getPatientProfile(token) {
  const data = await bizGet('patient/profile/getPatientProfile', token);
  if (!isBizOk(data) || !data.data) return null;
  return data.data;
}

async function getServerTime(token) {
  try {
    const data = await bizPost('patient/taskManage/getServerTime', token);
    if (isBizOk(data) && typeof data.data === 'string') return data.data;
  } catch (e) {
    if (e instanceof TokenInvalidError) throw e;
  }
  return formatLocalTime(new Date());
}

// 对齐小程序 auth.getTaskRender：list -> 过滤 enabled -> checkTaskFinish 打 complete
async function getTaskRender(token, types) {
  const listResp = await bizPost('patient/taskManage/list', token, { data: types });
  const list = isBizOk(listResp) && Array.isArray(listResp.data) ? listResp.data : [];
  // 默认只要后台开启的任务；HYK_TRY_DISABLED=1 时把 enabled=false 的 id 也拉进来试
  const enabled = list.filter((x) => x && (x.enabled || TRY_DISABLED));
  if (!enabled.length) return [];
  const query = enabled.map((x) => ({ taskId: x.id, type: x.type }));
  const finishResp = await bizPost('patient/taskManage/checkTaskFinish', token, { data: query });
  const finished = isBizOk(finishResp) && finishResp.data && typeof finishResp.data === 'object'
    ? finishResp.data
    : {};
  return enabled.map((x) => Object.assign({}, x, { complete: finished[x.id] || false }));
}

// 注册天数：与小程序 util.registrationDays 一致
function calcRegisterDays(baseDay, serverTime) {
  const base = new Date(String(baseDay).replace(/-/g, '/'));
  const now = serverTime ? new Date(String(serverTime).replace(/-/g, '/')) : new Date();
  if (Number.isNaN(base.getTime()) || Number.isNaN(now.getTime())) return 0;
  base.setHours(0, 0, 0, 0);
  now.setHours(0, 0, 0, 0);
  return Math.ceil(Math.abs(now - base) / 864e5) + 1;
}

// 打卡任务有 31 条，压成 id 区间打印；其余任务逐条列出
function describeTasks(tasks) {
  const lines = [];
  const checkin = tasks.filter((t) => String(t.type) === '1');
  const others = tasks.filter((t) => String(t.type) !== '1');
  if (checkin.length) {
    const total = checkin.reduce((sum, t) => sum + (toNumberOrNull(t.amount) || 0), 0);
    const todo = checkin.filter((t) => !t.complete).map((t) => t.id);
    const done = checkin.filter((t) => t.complete).map((t) => t.id);
    lines.push(`打卡 type=1 共 ${checkin.length} 条，合计 ${total} 分`);
    lines.push(`  待完成 id: ${formatIdRanges(todo)}`);
    lines.push(`  已完成 id: ${formatIdRanges(done)}`);
  }
  others.sort((a, b) => Number(a.type) - Number(b.type));
  for (const t of others) {
    lines.push(`${t.complete ? '已完成' : '待完成'} | id=${t.id} type=${t.type} ${t.amount}分 | ${t.name}`);
  }
  return lines;
}

function formatIdRanges(ids) {
  const sorted = ids.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return '无';
  const parts = [];
  let start = sorted[0];
  let prev = sorted[0];
  for (const n of sorted.slice(1)) {
    if (n === prev + 1) {
      prev = n;
      continue;
    }
    parts.push(start === prev ? String(start) : `${start}-${prev}`);
    start = n;
    prev = n;
  }
  parts.push(start === prev ? String(start) : `${start}-${prev}`);
  return parts.join(',');
}

// 一轮结束后的聚合日志，只打有内容的分类
function describeRound(stat) {
  const label = {
    ok: '领取成功',
    done: '已完成',
    gate: '条件未达成',
    skip: '前置未满足跳过',
    fail: '领取失败',
  };
  const lines = [];
  for (const key of ['ok', 'done', 'gate', 'skip', 'fail']) {
    const ids = stat[key] || [];
    if (ids.length) lines.push(`${label[key]} ${ids.length} 个：id ${formatIdRanges(ids)}`);
  }
  return lines;
}

async function runTasks(account, session) {
  const token = session.token;
  const remark = account.remark;
  const beforePoint = toNumberOrNull(session.profile.patientPointAmount);

  try {
    await bizPost('patient/profile/updateLastLoginTime', token);
  } catch (e) {
    if (e instanceof TokenInvalidError) throw e;
  }

  const serverTime = await getServerTime(token);
  const base = session.profile.effectiveDay || session.profile.createTime;
  const registerDays = calcRegisterDays(base, serverTime);
  const dayText = registerDays ? `注册第 ${registerDays} 天` : `注册天数未知（effectiveDay=${base || '-'}）`;
  console.log(`[${remark}] 服务器时间 ${serverTime}，${dayText}，当前积分 ${beforePoint == null ? 0 : beforePoint}`);

  if (FILL_ARCHIVE) await fillHealthArchive(account, session);

  const tasks = await getTaskRender(token, TASK_TYPES);
  if (!tasks.length) throw new Error('未取到任务列表');

  const pending = tasks.filter((t) => !t.complete).length;
  console.log(`[${remark}] 获取到 ${tasks.length} 个任务，待完成 ${pending} 个`);
  for (const line of describeTasks(tasks)) console.log(`  ${line}`);

  // 全 id 尝试：服务端不按注册天数限制打卡 id，已完成的也过一遍看能否重复领
  const ordered = tasks.slice().sort((a, b) => Number(a.id) - Number(b.id));
  let reward = 0;
  let claimed = 0;
  let repeatable = 0;
  let prevOk = new Set();

  for (let round = 1; round <= TASK_ROUNDS; round++) {
    // 第一轮打全部，之后只复领上一轮成功的，用来判断任务是否可重复
    const batch = round === 1 ? ordered : ordered.filter((t) => prevOk.has(t.id));
    if (!batch.length) {
      if (round > 1) console.log(`[${remark}] 第 ${round} 轮复领：上一轮无成功任务，结束`);
      break;
    }
    if (round > 1) console.log(`[${remark}] 第 ${round} 轮复领：对上一轮成功的 ${batch.length} 个任务再打一次`);

    const roundOk = new Set();
    let roundGain = 0;
    const stat = { ok: [], done: [], gate: [], skip: [], fail: [] };
    for (const task of batch) {
      // 打卡 31 条逐条打日志会刷屏，按状态聚合后一行输出
      const r = await claimTask(account, session, task, String(task.type) !== '1');
      (stat[r.status] || stat.fail).push(task.id);
      if (r.claimed) {
        roundOk.add(task.id);
        reward += r.reward;
        roundGain += r.reward;
        claimed += 1;
        if (round > 1) repeatable += 1;
      }
      await taskSleep();
    }

    for (const line of describeRound(stat)) console.log(`[${remark}] 第 ${round} 轮 ${line}`);
    prevOk = roundOk;
    if (!roundGain) break;
  }

  console.log(`[${remark}] 本次共领取 ${claimed} 次，累计 ${reward} 积分${repeatable ? `（其中 ${repeatable} 次为重复领取）` : ''}`);
  return { reward, claimed };
}

// 单个任务领取：type 4 需服务端确认企微好友，type 6 需档案完整度 100%
async function claimTask(account, session, task, verbose = true) {
  const token = session.token;
  const remark = account.remark;
  const label = `${task.name}(id=${task.id} type=${task.type})`;
  const log = (text) => { if (verbose) console.log(text); };

  if (String(task.type) === '4') {
    const ok = await checkAddFriend(token);
    if (!ok) {
      log(`[${remark}] 跳过 ${label}：需先加华医生企微`);
      addNotice(`当前账号：${account.id} 当前备注：${remark} 跳过：${task.name} 需加企微好友`);
      return { claimed: false, reward: 0, status: 'skip' };
    }
  }

  if (String(task.type) === '6') {
    const percent = await getArchivePercent(token);
    if (!(percent >= 100)) {
      log(`[${remark}] 跳过 ${label}：健康档案完整度 ${percent}%（需 100%）`);
      addNotice(`当前账号：${account.id} 当前备注：${remark} 跳过：${task.name} 档案完整度 ${percent}%`);
      return { claimed: false, reward: 0, status: 'skip' };
    }
  }

  let result = await finishTask(token, task);
  if (result.code === '3002') {
    // 后台任务表已更新，重新确认这条任务还在再打一次
    log(`[${remark}] ${label} 返回任务已更新，重新确认后重试`);
    const fresh = await getTaskRender(token, [String(task.type)]);
    const again = fresh.find((x) => x.id === task.id);
    if (!again) {
      log(`[${remark}] ${label} 已从任务列表移除，跳过`);
      return { claimed: false, reward: 0, status: 'skip' };
    }
    if (again.complete) {
      log(`[${remark}] ${label} 已完成`);
      return { claimed: false, reward: 0, status: 'done' };
    }
    await sleep(randInt(1000, 2000));
    result = await finishTask(token, again);
  }

  if (!result.ok) {
    if (/已打卡|已完成|重复|已领取|不可重复/.test(result.message)) {
      log(`[${remark}] ${label} 已完成：${result.message}`);
      return { claimed: false, reward: 0, status: 'done' };
    }
    if (/暂无|未达成|不满足|无可领取|未满足|尚未|未开启|未启用|已结束|已过期/.test(result.message)) {
      // 服务端条件未达成（拉新类、需真实行为、后台未开启的任务），属预期结果，不当失败上报
      log(`[${remark}] ${label} 条件未达成：${result.message}`);
      return { claimed: false, reward: 0, status: 'gate' };
    }
    log(`[${remark}] ${label} 领取失败：${result.message}`);
    addNotice(`当前账号：${account.id} 当前备注：${remark} 失败：${label} ${result.message}`);
    return { claimed: false, reward: 0, status: 'fail' };
  }

  const gain = parsePoint(result.text) || toNumberOrNull(task.amount) || 0;
  log(`[${remark}] ${label} 领取成功：${result.text || `获得${gain}积分`}`);
  return { claimed: true, reward: gain, status: 'ok' };
}

async function finishTask(token, task) {
  const data = await bizPost('patient/taskManage/finishTask', token, { data: { id: task.id } });
  const code = data && typeof data === 'object' ? String(data.code) : '';
  return {
    ok: isBizOk(data),
    code,
    text: data && typeof data.data === 'string' ? data.data : '',
    message: data && typeof data === 'object' ? (data.message || short(data)) : short(data),
  };
}

async function checkAddFriend(token) {
  try {
    const data = await bizPost('patient/taskManage/checkAddFriend', token);
    return isBizOk(data) && data.data === true;
  } catch (e) {
    if (e instanceof TokenInvalidError) throw e;
    return false;
  }
}

async function getArchivePercent(token) {
  const profile = await getPatientProfile(token);
  const hr = profile && profile.healthRecords;
  const percent = hr && hr.completePercent != null ? Number(hr.completePercent) : 0;
  return Number.isFinite(percent) ? percent : 0;
}

// 对齐 health-archives.onSaveHealthInfo 的字段集，把档案补到 100% 以解锁 type=6
async function fillHealthArchive(account, session) {
  const token = session.token;
  const remark = account.remark;
  const before = await getArchivePercent(token);
  if (before >= 100) {
    console.log(`[${remark}] 健康档案已完整（${before}%），无需填写`);
    return before;
  }

  const profile = session.profile || {};
  const hr = profile.healthRecords || {};
  const pick = (value, fallback) => (value == null || value === '' ? fallback : value);
  const body = {
    data: {
      patientName: pick(hr.patientName, `用户${String(profile.mobile || '').slice(-4) || '0000'}`),
      sex: pick(hr.sex, '男'),
      birthday: pick(hr.birthday, '1995-01-01'),
      height: String(pick(hr.height, 172)),
      weight: String(pick(hr.weight, 65)),
      medicalRecord: JSON.stringify([]),
      personalHistory: pick(hr.personalHistory, ''),
      pastHistory: pick(hr.pastHistory, '0'),
      pastHistoryDesc: pick(hr.pastHistoryDesc, ''),
      epidemiologicalHistory: pick(hr.epidemiologicalHistory, '0'),
      allergyHistory: pick(hr.allergyHistory, '无'),
      allergyHistoryDesc: pick(hr.allergyHistoryDesc, ''),
      pregnancyStatus: pick(hr.pregnancyStatus, '无'),
    },
  };

  const data = await bizPost('patient/profile/updateHealthRecords', token, body);
  if (!isBizOk(data)) {
    console.log(`[${remark}] 健康档案填写失败：${short(data)}`);
    return before;
  }
  const after = data.data && data.data.completePercent != null ? Number(data.data.completePercent) : before;
  console.log(`[${remark}] 健康档案已提交，完整度 ${before}% -> ${after}%`);
  return after;
}

// ====================== 账号流程 ======================

async function runAccount(account) {
  let currentPoint = '-';
  let reward = 0;
  try {
    let session = await getSession(account);
    let result;
    try {
      result = await runTasks(account, session);
    } catch (e) {
      if (!(e instanceof TokenInvalidError) || session.fresh) throw e;
      console.log(`[${account.remark}] 执行中 token 失效，重登一次`);
      dropCache(account.id);
      session = await businessLogin(account);
      result = await runTasks(account, session);
    }
    reward = result.reward;

    const after = await getPatientProfile(session.token);
    const afterPoint = after ? toNumberOrNull(after.patientPointAmount) : null;
    const beforePoint = toNumberOrNull(session.profile.patientPointAmount);
    currentPoint = afterPoint == null ? (beforePoint == null ? 0 : beforePoint) : afterPoint;
    if (!reward && afterPoint != null && beforePoint != null) {
      reward = Math.max(0, afterPoint - beforePoint);
    }
    console.log(`[${account.remark}] 当前积分 ${currentPoint}，本次获得 ${reward}`);

    pushSummary({ account: account.id, remark: account.remark, value: currentPoint, reward });
  } catch (e) {
    console.log(`[${account.remark || account.raw}] 执行失败: ${e.message}`);
    pushSummary({
      account: account.id || account.raw,
      remark: account.remark || account.raw,
      value: currentPoint,
      reward,
      error: e.message,
    });
  }
}

// ====================== 汇总与工具 ======================

function pushSummary(item) {
  summaries.push({
    account: item.account,
    remark: item.remark || item.account,
    value: item.value == null ? '-' : item.value,
    reward: item.reward == null ? 0 : item.reward,
    error: item.error || '',
  });
}

// 任务提醒去重，避免多轮复领把同一条提示刷进汇总
function addNotice(text) {
  if (!taskNotices.includes(text)) taskNotices.push(text);
}

function printSummary() {
  const lines = ['', '======== 本次汇总 ========'];
  console.log('\n======== 本次汇总 ========');
  for (const s of summaries) {
    const line = s.error
      ? `当前账号：${s.account} 当前备注：${s.remark} 当前积分：- 本次获得：0 失败：${s.error}`
      : `当前账号：${s.account} 当前备注：${s.remark} 当前积分：${s.value} 本次获得：${s.reward}`;
    lines.push(line);
    console.log(line);
  }
  if (taskNotices.length) {
    lines.push('', '======== 任务提醒 ========');
    console.log('\n======== 任务提醒 ========');
    for (const notice of taskNotices) {
      lines.push(notice);
      console.log(notice);
    }
  }
  return lines.join('\n').trim();
}

async function sendNotify(title, content) {
  if (!content || process.env.HYK_NOTIFY === '0') return;
  try {
    const notify = require('./sendNotify');
    if (notify && typeof notify.sendNotify === 'function') {
      await notify.sendNotify(title, content);
    }
  } catch (e) {
    console.log(`通知发送失败: ${e.message}`);
  }
}

function dropCache(accountId) {
  if (!accountId || !cache[accountId]) return;
  delete cache[accountId];
  writeJson(CACHE_FILE, cache);
}

function readJson(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return fallback; }
}

function writeJson(file, data) {
  try { fs.writeFileSync(file, JSON.stringify(data, null, 2)); } catch (e) {
    console.log(`写缓存失败: ${e.message}`);
  }
}

function maskMobile(mobile) {
  const s = String(mobile || '');
  return /^1\d{10}$/.test(s) ? `${s.slice(0, 3)}****${s.slice(7)}` : '';
}

function toNumberOrNull(value) {
  if (value == null || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function parsePoint(text) {
  const hit = String(text || '').match(/(\d+)/);
  return hit ? Number(hit[1]) : 0;
}

function formatLocalTime(date) {
  const p = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())} ` +
    `${p(date.getHours())}:${p(date.getMinutes())}:${p(date.getSeconds())}`;
}

function short(x) {
  return (typeof x === 'string' ? x : JSON.stringify(x) || String(x)).slice(0, 500);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

// 任务间隔：默认随机，HYK_TASK_DELAY 可压低以便批量测试
function taskSleep() {
  const fixed = Number(process.env.HYK_TASK_DELAY);
  return sleep(Number.isFinite(fixed) && fixed >= 0 ? fixed : randInt(600, 1600));
}

async function main() {
  const accounts = await loadYybAccounts();
  if (!accounts.length) {
    throw new Error('未配置 HYK_WX_ACCOUNTS / WX_ID，且 yyb_go 无存活账号');
  }
  console.log(`${APP_NAME}：共 ${accounts.length} 个账号`);
  for (let i = 0; i < accounts.length; i++) {
    console.log(`\n---------- 第 ${i + 1}/${accounts.length} 个账号：${accounts[i].remark} ----------`);
    await runAccount(accounts[i]);
    if (i < accounts.length - 1) await sleep(randInt(3000, 8000));
  }
  const text = printSummary();
  await sendNotify(APP_NAME, text);
}

main().catch(async (e) => {
  console.log(`脚本异常: ${e.message}`);
  const text = printSummary();
  await sendNotify(`${APP_NAME}脚本异常`, [e.message, text].filter(Boolean).join('\n\n'));
  process.exitCode = 1;
});
