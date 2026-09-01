require('./yyb.js'); // 自动同步 yyb_go 存活账号
/*
 * name: 芝秋堂
 * cron: 36 15,03 * * * 
 * 芝秋堂 小程序（appId: wxaf8488e1dfc13384）积分任务脚本
 * 能力：每日签到、看视频时长(taskType=2)、看课程时长(taskType=3) 等所有可自动化奖励接口
 *
 * 依赖微信协议服务获取 wx.login code（统一走 yyb.js，自动路由 牛子/应用宝），
 * 再用业务接口 authLogin 换 token。
 * 账号变量 WX_ID（与其他脚本统一），支持换行 或 @ 分隔，格式：
 *     wxid_xxxx#备注
 *     openid#备注         <-- 应用宝协议虚拟 wxid，由 yyb.js 自动路由
 *
 * 青龙环境：只用 axios，不使用 fetch。中文日志，UTF-8。
 *
 * 环境变量：
 *   WX_ID          账号列表（换行 或 @，由 yyb.js 读取并智能路由）
 *   ZQT_VIDEO_MAX  看视频最多领取次数（默认按接口 remainNum 自动，全领）
 *   ZQT_DELAY      每次领取间隔毫秒（默认 1500）
 *   协议服务地址（WECHAT_SERVER / YYB_SERVER / SERVER_TYPE）在 yyb.js 中配置
 */

const axios = require('axios');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// ==================== 头部集中配置 ====================
const ACCOUNT_ENV = 'WX_ID';
const CACHE_FILE = path.join(__dirname, 'wxzqt.json');

const APPID = 'wxaf8488e1dfc13384';
const SALT = '1fe18d439ffb1548ae29e6e9f3c775739278';
const PSOURCE = '100002';
const CLIENT_CODE = 'LG333Q180I11';
const PARTNER_CODE = '10020';
const MINI_VER = '1.0.0';

const BASE_MALL = 'https://bjgw.iqcyx.com/mall';                 // 默认业务(登录/积分余额/shopId)
const BASE_POINT = 'https://bjgw.iqcyx.com/point';               // 积分任务(签到/看视频/看课程)
const BASE_VROOM = 'https://bjgw.iqcyx.com/bjm-platform-content'; // 视频内容(列表/上报)

const VIDEO_MAX = parseInt(process.env.ZQT_VIDEO_MAX || '0', 10); // 0=按接口 remainNum 全领
const DELAY = parseInt(process.env.ZQT_DELAY || '1500', 10);
const TIMEOUT = 15000;

const summaries = [];

// ==================== 工具函数 ====================
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function md5(s) { return crypto.createHash('md5').update(s, 'utf8').digest('hex'); }
function b64(s) { return Buffer.from(String(s), 'utf8').toString('base64'); }

function readCache() {
  try { return JSON.parse(fs.readFileSync(CACHE_FILE, 'utf8')); } catch (e) { return {}; }
}
function writeCache(obj) {
  try { fs.writeFileSync(CACHE_FILE, JSON.stringify(obj, null, 2), 'utf8'); } catch (e) {}
}

// 账号解析：兼容 wxid_ / yyb: / wx: / openid#备注，统一由 yyb.js 智能路由
function parseWxAccount(line) {
  const raw = String(line || '').trim();
  const parts = raw.split('#');
  const id = (parts[0] || '').trim();
  const remark = (parts.slice(1).join('#') || id).trim();
  return { raw, id, remark };
}

function getAccounts() {
  const v = process.env[ACCOUNT_ENV] || '';
  return v.split(/[@\n]/).map(s => s.trim()).filter(Boolean);
}

// 优先从 yyb 拉取全部存活账号（不受 WX_ID 过滤，配 N 条只跑 N 个）
async function fetchOnlineAccounts() {
  try {
    const online = await new YYBClient().getOnlineAccounts();
    if (online && online.length) {
      const raw = online
        .map(acc => {
          const id = acc.openid || acc.wxid || String(acc.id || '');
          const note = acc.nickname || acc.alias || acc.remark || '';
          return id ? `wx:${id}#${note}` : '';
        })
        .filter(Boolean)
        .join('\n');
      console.log(`✅ 从 yyb 服务拉取到 ${online.length} 个存活账号`);
      return raw.split(/[@\n]/).map(s => s.trim()).filter(Boolean);
    }
  } catch (e) {
    console.log(`[yyb] 拉取账号列表失败: ${e.message || e}`);
  }
  return [];
}

// ==================== 业务签名 ====================
// signature = md5( base64(timestamp) + token + salt + 排序拼接后的参数 )
function makeSign(data, ts, token) {
  const e = data ? Object.assign({}, data) : {};
  let s = '';
  Object.keys(e).sort().forEach(k => {
    if (typeof e[k] === 'object') e[k] = '';
    s += k + e[k];
  });
  s = String(s);
  if (s) s = s.replace(/\[/g, '').replace(/]/g, '').replace(/"/g, '');
  return md5(b64(String(ts)) + (token || '') + SALT + s);
}

// 统一业务请求
async function bizRequest(baseUrl, apiPath, data, opt) {
  opt = opt || {};
  const method = opt.method || 'POST';
  const token = opt.token || '';
  const shopId = opt.shopId || '';
  const ts = parseInt(Date.now() / 1000, 10);
  const headers = {
    'Content-Type': 'application/json;charset=UTF-8',
    token: token,
    partnerCode: PARTNER_CODE,
    pSource: PSOURCE,
    appId: APPID,
    timestamp: ts,
    signature: makeSign(data, ts, token),
    miniAppVer: MINI_VER,
    clientCode: CLIENT_CODE,
    shopId: shopId,
  };
  const url = `${baseUrl}${apiPath}`;
  const cfg = { method, url, headers, timeout: TIMEOUT, validateStatus: () => true };
  if (method === 'GET') {
    cfg.params = data || {};
  } else {
    cfg.data = data || {};
  }
  const r = await axios(cfg);
  return r.data;
}

// 账号统一来自 WX_ID，由 yyb.js 智能路由（牛子/应用宝）获取 wx.login code
async function getWxCode(wxid) {
  const code = await getSingleCode(APPID, wxid);
  if (!code) throw new Error('未提取到 wx.login code (WX_ID=' + wxid + ')');
  return code;
}

// ==================== 业务登录 / 校验 ====================
async function authLogin(code) {
  const body = { code, sourceCode: '', materialId: '', reference: '', salesId: '', courseId: '' };
  const res = await bizRequest(BASE_MALL, '/api/v1/auth/authLogin', body, { method: 'POST', token: '' });
  if (!res || res.code !== 0 || !res.data) {
    throw new Error('业务登录失败: ' + JSON.stringify(res).slice(0, 300));
  }
  const d = res.data;
  const token = d.token || d.Token || '';
  if (!token) throw new Error('登录响应缺少 token: ' + JSON.stringify(d).slice(0, 300));
  return {
    token,
    openid: d.openId || d.openid || '',
    unionId: d.unionId || '',
    mobile: d.mobile || '',
    userId: d.id || d.userId || '',
  };
}

async function getShopId(token) {
  const res = await bizRequest(BASE_MALL, '/api/systemconfig/get/shopId', {}, { method: 'POST', token });
  if (res && res.code === 0 && res.data) return String(res.data);
  return '';
}

// 用轻量业务接口校验 token 是否有效
async function checkToken(token, shopId) {
  try {
    const res = await bizRequest(BASE_POINT, '/api/v1/userPoint/info', {}, { method: 'GET', token, shopId });
    return res && res.code === 0;
  } catch (e) { return false; }
}

// ==================== 积分查询 ====================
async function getUserPoint(token, shopId) {
  const res = await bizRequest(BASE_POINT, '/api/v1/userPoint/info', {}, { method: 'GET', token, shopId });
  if (res && res.code === 0 && res.data) {
    return { usable: res.data.usablePoint, cumulative: res.data.cumulativePoint };
  }
  return { usable: '-', cumulative: '-' };
}

// ==================== 任务：所有奖励接口 ====================

// 任务列表（了解各任务状态）
async function listTasks(token, shopId) {
  const res = await bizRequest(BASE_POINT, '/api/v1/pointTask/listTask', {}, { method: 'POST', token, shopId });
  return (res && res.code === 0 && Array.isArray(res.data)) ? res.data : [];
}

// 签到
async function taskSign(token, shopId, log) {
  try {
    const res = await bizRequest(BASE_POINT, '/api/v1/userSign/mark', {}, { method: 'POST', token, shopId });
    if (res && res.code === 0 && res.data) {
      const p = Number(res.data.signPoint || 0) + Number(res.data.extraSignPoint || 0);
      log(`签到成功，获得 ${p} 积分`);
      return p;
    }
    log(`签到无奖励/已签到：${res && (res.message || res.code)}`);
    return 0;
  } catch (e) {
    log(`签到异常：${e.message}`);
    return 0;
  }
}

// 从视频列表取一个 videoId，用于自然上报观看事件
async function pickVideoId(token, shopId) {
  try {
    const res = await bizRequest(BASE_VROOM, '/api/v1/video/homeList',
      { pageNum: 1, pageSize: 5, id: '', firstEntry: true }, { method: 'POST', token, shopId });
    const list = res?.data?.videoList?.dataList || [];
    return list.length ? String(list[0].id) : '';
  } catch (e) { return ''; }
}

// 上报观看事件（模拟真实观看，尽量避免服务端时长校验）
async function reportVideoEvent(token, shopId, videoId) {
  if (!videoId) return;
  try {
    await bizRequest(BASE_VROOM, '/api/v1/video/report/event', {
      pageId: '', eventType: 4, videoId,
      deviceId: '', deviceModel: 'iPhone 15 pro max<iPhone16,2>',
      osName: 'iOS 26.1', osVersion: '8.0.75',
      appChannel: 'weixinmini', appVersion: '3.17.0',
      reportTime: String(Date.now()),
    }, { method: 'POST', token, shopId });
  } catch (e) {}
}

// 看视频/看课程 领取时长积分
// taskType: 2=看视频(每满1分钟领5积分, 上限20次), 3=看课程(每满15分钟领20积分)
async function taskLearn(token, shopId, taskType, name, videoId, log) {
  let got = 0;
  try {
    const d = await bizRequest(BASE_POINT, '/api/v1/pointTask/learnTaskDetail',
      { taskType }, { method: 'POST', token, shopId });
    if (!d || d.code !== 0 || !d.data) {
      log(`${name} 详情获取失败：${d && (d.message || d.code)}`);
      return 0;
    }
    let { remainNum, pointValue, limitNum } = d.data;
    remainNum = Number(remainNum || 0);
    pointValue = Number(pointValue || 0);
    log(`${name} 单次 ${pointValue} 积分，剩余可领 ${remainNum}/${limitNum} 次`);
    if (remainNum <= 0) { log(`${name} 今日已领满/已结束`); return 0; }

    let times = remainNum;
    if (VIDEO_MAX > 0) times = Math.min(times, VIDEO_MAX);

    for (let i = 0; i < times; i++) {
      await reportVideoEvent(token, shopId, videoId);
      await sleep(DELAY);
      const r = await bizRequest(BASE_POINT, '/api/v1/pointTask/finishLearnTask',
        { taskType }, { method: 'POST', token, shopId });
      if (r && r.code === 0 && r.data) {
        got += pointValue;
        log(`${name} 第 ${i + 1} 次领取成功 +${pointValue}，剩余 ${r.data.remainNum} 次`);
        if (Number(r.data.remainNum) <= 0) break;
      } else {
        log(`${name} 第 ${i + 1} 次领取失败：${r && (r.message || r.code)}`);
        break;
      }
    }
  } catch (e) {
    log(`${name} 异常：${e.message}`);
  }
  return got;
}

// ==================== 单账号执行 ====================
async function runAccount(acc, cache) {
  const { id, remark } = acc;
  const log = (m) => console.log(`[${remark}] ${m}`);

  const summary = { account: id, remark, label: '当前积分', value: '-', rewardLabel: '本次获得', reward: 0, error: '' };

  if (!id) {
    summary.error = '账号解析为空';
    summaries.push(summary);
    return;
  }

  // 缓存 key 使用完整账号标识
  const cacheKey = id;
  let cached = cache[cacheKey] || {};
  let token = cached.token || '';
  let shopId = cached.shopId || '';
  let logged = false;

  // 1) 先用缓存 token 校验
  if (token) {
    log('检测到缓存 token，校验中…');
    if (await checkToken(token, shopId)) {
      log('缓存有效，直接执行任务');
      logged = true;
    } else {
      log('缓存失效，重新协议登录');
      token = '';
    }
  }

  // 2) 缓存无效 → 协议登录（统一走 yyb.js 路由 牛子/应用宝）
  if (!logged) {
    try {
      log('调用协议服务获取 wx.login code (WX_ID=' + id + ')…');
      const code = await getWxCode(id);
      log('获取 code 成功，业务登录中…');
      const info = await authLogin(code);
      token = info.token;
      shopId = await getShopId(token);
      log(`业务登录成功${shopId ? '，shopId=' + shopId : ''}`);
      // 写回缓存（key 用完整账号标识）
      cache[cacheKey] = {
        remark,
        token,
        shopId,
        openid: info.openid,
        unionId: info.unionId,
        mobile: info.mobile,
        userId: info.userId,
        updateTime: Date.now(),
      };
      writeCache(cache);
      logged = true;
    } catch (e) {
      summary.error = '登录失败:' + e.message;
      summaries.push(summary);
      return;
    }
  } else if (!shopId) {
    shopId = await getShopId(token);
    if (shopId) { cache[cacheKey].shopId = shopId; writeCache(cache); }
  }

  // 3) 执行任务
  let totalReward = 0;
  try {
    const tasks = await listTasks(token, shopId);
    if (tasks.length) {
      log('任务列表：' + tasks.map(t => `${t.taskTitle}(${t.pointValue}分)`).join('、'));
    }

    // 签到
    totalReward += await taskSign(token, shopId, log);

    // 看视频（taskType=2）
    const videoId = await pickVideoId(token, shopId);
    totalReward += await taskLearn(token, shopId, 2, '看视频', videoId, log);

    // 看课程（taskType=3）
    totalReward += await taskLearn(token, shopId, 3, '看课程', videoId, log);
  } catch (e) {
    summary.error = '任务执行异常:' + e.message;
  }

  // 4) 查询最终积分
  try {
    const pt = await getUserPoint(token, shopId);
    summary.value = pt.usable;
  } catch (e) {}

  summary.reward = totalReward;
  summaries.push(summary);
}

// ==================== 汇总输出 ====================
function printSummary() {
  console.log('\n======== 本次汇总 ========');
  for (const s of summaries) {
    if (s.error) {
      console.log(`当前账号：${s.account} 当前备注：${s.remark} ${s.label}：- ${s.rewardLabel}：0 失败：${s.error}`);
    } else {
      console.log(`当前账号：${s.account} 当前备注：${s.remark} ${s.label}：${s.value} ${s.rewardLabel}：${s.reward}`);
    }
  }
}

// ==================== 主流程 ====================
(async () => {
  let accounts = await fetchOnlineAccounts();
  if (!accounts.length) {
    // 回退：WX_ID 环境变量
    accounts = getAccounts();
  }
  if (!accounts.length) {
    console.log(`未检测到账号，请配置环境变量 ${ACCOUNT_ENV}（换行 或 @ 分隔）`);
    return;
  }
  console.log(`芝秋堂积分脚本启动，共 ${accounts.length} 个账号`);
  const cache = readCache();

  for (let i = 0; i < accounts.length; i++) {
    const acc = parseWxAccount(accounts[i]);
    console.log(`\n>>>>>> 账号 ${i + 1}/${accounts.length} [${acc.remark}] <<<<<<`);
    try {
      await runAccount(acc, cache);
    } catch (e) {
      summaries.push({ account: acc.id, remark: acc.remark, label: '当前积分', value: '-', rewardLabel: '本次获得', reward: 0, error: e.message });
    }
    if (i < accounts.length - 1) await sleep(1000);
  }

  printSummary();
})();