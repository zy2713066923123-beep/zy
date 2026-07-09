// name:金典代言人挑战活动
// cron:30 20 * * *

/**
 * 金典代言人官宣会员营销互动 - 鲜活挑战（翻牌）
 *
 * 分享逻辑（两两配对）:
 *   账号A → userShare（A分享）
 *   账号B → drawShare({id: A.shareId})（B领取A的分享奖励）
 *   → 双方 handlePop（领取任务完成奖励弹窗）
 *   → 无需反向操作（A分享后B领取即可使双方任务完成）
 *   奇数末尾账号独立处理（分享但无人领取）
 *   所有账号分享完成后统一翻牌
 *
 * 变量:
 *   WX_ID                   账号列表，wxid#备注，多账号换行或@分隔（兼容旧名 wxjindian）
 *   WECHAT_SERVER           协议服务地址（getCode 内部使用）
 *   JINDIAN_XH_APP_KEY      活动 app_key（默认 zd123a10187c995e97）
 *   JINDIAN_XH_MAX_DRAW     最大翻牌次数（默认 20）
 *
 * 缓存文件: jindian_cache.json（与金典鲜活挑战.js 共用）
 */

const fs   = require('fs');
const path = require('path');
const https = require('https');
const http  = require('http');
const { URL } = require('url');

// ── 常量 ──────────────────────────────────────────────────────────────────

const SCRIPT_NAME   = '金典代言人挑战活动';
const APPID         = 'wxf32616183fb4511e';
const APP_KEY       = String(process.env.JINDIAN_XH_APP_KEY || process.env.JINDIAN_APP_KEY || 'zd123a10187c995e97').trim();
const TENANT_ID     = '1718857849685876737';
const MS_BASE       = 'https://msmarket.msx.digitalyili.com';
const API_BASE      = 'https://wx-camp-hc-api-01.mscampapi.digitalyili.com/wx-camp-jddyr/stage';
const WECHAT_SERVER = String(process.env.WECHAT_SERVER || '').trim();
const MAX_DRAW      = Math.max(1, Number(process.env.JINDIAN_XH_MAX_DRAW || 20));
const CACHE_FILE    = path.join(__dirname, 'jindian_cache.json');  // 与鲜活挑战共用
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254186b) XWEB/19481';

// ── 工具 ──────────────────────────────────────────────────────────────────

const sleep = ms => new Promise(r => setTimeout(r, ms));
const rand  = (a, b) => Math.floor(Math.random() * (b - a + 1)) + a;
const log   = (s = '') => console.log(s);

function readJson(file, def = {}) { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return def; } }
function writeJson(file, obj) { fs.writeFileSync(file, JSON.stringify(obj, null, 2), 'utf8'); }

function parseAccounts(raw) {
  return String(raw || '').split(/[\n@]+/).map(x => x.trim()).filter(Boolean).map(x => {
    const i = x.indexOf('#');
    return i >= 0 ? { wxid: x.slice(0, i).trim(), remark: x.slice(i + 1).trim() } : { wxid: x, remark: x };
  }).filter(x => x.wxid);
}

function getMsg(d) {
  if (!d) return '未知';
  if (typeof d === 'string') return d.slice(0, 200);
  return d.msg || d.message || d.error?.msg || JSON.stringify(d).slice(0, 200);
}

function jwtExp(token) {
  try {
    const p = String(token || '').split('.')[1];
    const obj = JSON.parse(Buffer.from(p.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8'));
    return Number(obj.exp || 0) * 1000;
  } catch { return 0; }
}
function tokenValid(token) {
  const exp = jwtExp(token);
  return !!token && (!exp || exp - Date.now() > 5 * 60 * 1000);
}
function isTokenBad(data) {
  return data?.code === -1 || /TOKEN已失效|token.*失效|登录过期/i.test(getMsg(data));
}

// ── HTTP ──────────────────────────────────────────────────────────────────

function request({ url, method = 'POST', headers = {}, body = null, timeout = 25000 }) {
  return new Promise(resolve => {
    let u; try { u = new URL(url); } catch { return resolve({ status: 0, data: null }); }
    const buf = body == null ? null : Buffer.from(JSON.stringify(body), 'utf8');
    if (buf) headers['Content-Length'] = buf.length;
    const mod  = u.protocol === 'http:' ? http : https;
    const port = Number(u.port) || (u.protocol === 'http:' ? 80 : 443);
    const req  = mod.request(
      { method, hostname: u.hostname, port, path: u.pathname + u.search, headers, timeout },
      res => {
        const c = [];
        res.on('data', x => c.push(x));
        res.on('end', () => {
          const text = Buffer.concat(c).toString('utf8');
          let data = text;
          if (/json/i.test(res.headers['content-type'] || '')) { try { data = JSON.parse(text); } catch {} }
          resolve({ status: res.statusCode, data });
        });
      }
    );
    req.on('timeout', () => req.destroy());
    req.on('error',   () => resolve({ status: 0, data: null }));
    if (buf) req.write(buf);
    req.end();
  });
}

// ── 金典主站 ──────────────────────────────────────────────────────────────

function msH(token = '') {
  return {
    Host: 'msmarket.msx.digitalyili.com', Connection: 'keep-alive',
    'register-source': '', shareid: '', xweb_xhr: '1', scene: '1000',
    'access-token': token, 'User-Agent': UA, channel: 'copyUrl',
    'Content-Type': 'application/json',
    // TAB 前缀绕过部分 WAF 字面规则，服务端会 trim 得到正确值
    'tenant-id': '\t' + TENANT_ID,
    Accept: '*/*', Referer: `https://servicewechat.com/${APPID}/815/page-frame.html`,
  };
}

async function wxCode(wxid) {
  if (!WECHAT_SERVER) throw new Error('未配置 WECHAT_SERVER');
  const base = WECHAT_SERVER.replace(/\/$/, '');
  for (const p of ['/api/v1/wx/app/get/code', '/api/v1/wx/app/get/jscode']) {
    try {
      const { data } = await request({ url: base + p, headers: { 'Content-Type': 'application/json' }, body: { wxid, appid: APPID } });
      const code = data?.Data?.code || data?.data?.code || data?.code;
      if (code) return String(code);
    } catch {}
  }
  throw new Error('协议接口未返回code');
}

async function msLogin(jsCode) {
  const { status, data } = await request({ url: `${MS_BASE}/gateway/api/auth/account/login`, headers: msH(''), body: { jsCode } });
  const token = data?.data?.accessToken || data?.data?.access_token || data?.data?.token;
  if (!token) throw new Error(`ms登录失败(${status}): ${getMsg(data)}`);
  return String(token);
}

async function msAuthCode(msToken) {
  const { data } = await request({ url: `${MS_BASE}/developer/oauth2/buyer/authorize?app_key=${encodeURIComponent(APP_KEY)}`, method: 'GET', headers: msH(msToken) });
  const d = data?.data;
  const code = (typeof d === 'string' && /^[0-9a-f]{32}$/i.test(d) ? d : null)
    || d?.authorizationCode || d?.authorization_code || data?.authorization_code;
  if (!code) throw new Error(`授权码失败: ${getMsg(data)}`);
  return String(code);
}

// ── 活动客户端 ────────────────────────────────────────────────────────────

class Client {
  constructor(acc, cache) {
    this.wxid   = acc.wxid;
    this.remark = acc.remark;
    this.cache  = cache;
    const c = cache[this.wxid] || cache[this.remark] || {};
    this.token  = c.jddyrToken || '';
    this.msToken = c.msToken || '';
    this.openId = c.jddyrOpenId || '';
    this.awards = [];
  }

  save() {
    const old = this.cache[this.wxid] || {};
    this.cache[this.wxid] = {
      ...old, wxid: this.wxid, remark: this.remark,
      msToken: this.msToken || old.msToken || '',
      jddyrToken: this.token || '',
      jddyrOpenId: this.openId || '',
      jddyrUpdateAt: new Date().toLocaleString('zh-CN', { hour12: false }),
    };
    writeJson(CACHE_FILE, this.cache);
  }

  campH() {
    return {
      Host: 'wx-camp-hc-api-01.mscampapi.digitalyili.com', Connection: 'keep-alive',
      Authorization: this.token || '', 'User-Agent': UA,
      Accept: 'application/json, text/plain, */*', xweb_xhr: '1',
      'Content-Type': 'application/json',
      Referer: `https://servicewechat.com/${APPID}/815/page-frame.html`,
    };
  }

  async api(pathname, body = {}, retry = true) {
    const { status, data } = await request({ url: `${API_BASE}${pathname}`, headers: this.campH(), body });
    if (retry && (status === 401 || status === 403 || isTokenBad(data))) {
      log(`♻️ ${this.remark} token失效，重新登录`);
      this.token = '';
      await this.login(true);
      return this.api(pathname, body, false);
    }
    return data;
  }

  async login(force = false, byOpenId = '') {
    if (!force && tokenValid(this.token)) {
      log(`🔑 ${this.remark} 使用缓存CK`);
      return;
    }
    log(`🔄 ${this.remark} 协议登录...`);
    const jsCode   = await wxCode(this.wxid);
    this.msToken   = await msLogin(jsCode);
    const authCode = await msAuthCode(this.msToken);
    const { status, data } = await request({
      url: `${API_BASE}/userLogin`, headers: this.campH(),
      body: { code: authCode, byOpenId: byOpenId || '' },
    });
    const d = data?.data || {};
    if (!d.token) throw new Error(`活动登录失败(${status}): ${getMsg(data)}`);
    this.token  = String(d.token);
    this.openId = d.openId || this.openId || '';
    this.save();
    log(`✅ ${this.remark} 登录成功 openId:${this.openId}`);
  }

  async queryUser() {
    const d = await this.api('/qryUserInfo', {});
    if (d?.code === 1 && d.data) {
      this.openId = d.data.openId || this.openId;
      this.save();
      return d.data;
    }
    return {};
  }

  async taskList() {
    const d = await this.api('/task/list', {});
    return Array.isArray(d?.data) ? d.data : [];
  }

  // 处理任务完成的奖励弹窗（领取积分等奖励）
  async handlePop() {
    const d = await this.api('/task/isPop', {});
    const arr = Array.isArray(d?.data) ? d.data : [];
    for (const p of arr) {
      if (p?.id) {
        await this.api('/closePop', { popType: 3, userTaskId: p.id });
        log(`  🎁 ${this.remark} 领取任务奖励: ${p.taskName || p.id}`);
        await sleep(rand(300, 600));
      }
    }
    return arr.length;
  }

  // A分享：提交分享，返回 shareId
  async doShare() {
    const tasks = await this.taskList();
    const shareTask = tasks.find(t => /分享/.test(t.name || ''));
    if (shareTask?.taskStatus === 1 || Number(shareTask?.finishNum || 0) >= Number(shareTask?.taskNum || 1)) {
      log(`  ✅ ${this.remark} 分享任务已完成，跳过`);
      return null;
    }
    const d = await this.api('/userShare', {});
    if (d?.code === 1) {
      const shareId = d.data?.id || '';
      log(`  🔗 ${this.remark} 分享成功 shareId:${shareId}`);
      await this.handlePop();
      return shareId;
    }
    log(`  ⚠️ ${this.remark} 分享失败: ${getMsg(d)}`);
    return null;
  }

  // B领取A的分享：触发双方分享任务完成
  async drawShare(shareId) {
    if (!shareId) return;
    const d = await this.api('/drawShare', { id: shareId });
    if (d?.code === 1) {
      log(`  🎁 ${this.remark} 领取分享奖励成功: ${getMsg(d)}`);
      await this.handlePop();  // 领取完成后处理弹窗（可能有额外积分）
    } else {
      log(`  ⚠️ ${this.remark} 领取分享奖励: ${getMsg(d)}`);
    }
  }

  // 执行一次翻牌
  async drawOnce() {
    const b = await this.api('/beginChallenger', {});
    const id = b?.data;
    if (b?.code !== 1 || !id) { log(`  ⚠️ ${this.remark} 开始挑战失败: ${getMsg(b)}`); return false; }
    await sleep(rand(2500, 4500));
    const e = await this.api('/endChallenger', { id, status: 1 });
    if (e?.code === 1) {
      const aw = e.data?.award;
      const name = aw?.awardName || aw?.prizeName || '';
      if (name) { this.awards.push(name); log(`  🎉 ${this.remark} 翻牌奖品: ${name}`); }
      else log(`  ✅ ${this.remark} 翻牌完成 id:${id}`);
      return true;
    }
    log(`  ⚠️ ${this.remark} 结束挑战失败: ${getMsg(e)}`);
    return false;
  }

  async drawAll() {
    let u = await this.queryUser();
    let n = Number(u.lotteryNum || 0);
    log(`🎰 ${this.remark} 可翻牌次数: ${n}`);
    let cnt = 0;
    while (n > 0 && cnt < MAX_DRAW) {
      cnt++;
      await this.drawOnce();
      await sleep(rand(800, 1500));
      u = await this.queryUser();
      n = Number(u.lotteryNum || 0);
    }
    if (cnt === 0) log(`${this.remark} 无可用翻牌次数`);
    return cnt;
  }
}

// ── 主逻辑 ────────────────────────────────────────────────────────────────

async function main() {
  const accounts = parseAccounts(process.env.wxjindian || '');
  if (!accounts.length) throw new Error('未配置 wxjindian');
  log(`${SCRIPT_NAME} 开始，共 ${accounts.length} 个账号，app_key=${APP_KEY}`);

  const cache   = readJson(CACHE_FILE, {});
  const clients = accounts.map(a => new Client(a, cache));

  // ── 阶段一：所有账号登录 ─────────────────────────────────────────────
  log('\n══ 阶段一：登录 ══');
  for (const c of clients) {
    try {
      await c.login(false);
      const u = await c.queryUser();
      log(`📊 ${c.remark} 次数:${u.lotteryNum || 0} 总:${u.totalLotteryNum || 0}`);
    } catch (e) {
      log(`❌ ${c.remark} 登录失败: ${e.message}`);
      c._loginFailed = true;
    }
    await sleep(rand(1000, 2000));
  }

  const valid = clients.filter(c => !c._loginFailed);

  // ── 阶段二：分享任务（两两配对）────────────────────────────────────────
  // 逻辑：A分享 → B领取（双方分享任务完成）
  // 注意：B领取后双方均完成，无需B再分享给A
  log('\n══ 阶段二：分享任务 ══');

  for (let i = 0; i + 1 < valid.length; i += 2) {
    const A = valid[i];
    const B = valid[i + 1];
    log(`\n📌 ${A.remark} 分享 → ${B.remark} 领取`);

    // A 分享
    let shareId = null;
    try {
      shareId = await A.doShare();
    } catch (e) { log(`  ❌ ${A.remark} 分享异常: ${e.message}`); }
    await sleep(rand(500, 1000));

    // B 领取 A 的分享（即使 shareId 为 null 也尝试，可能任务已完成）
    if (shareId) {
      try {
        await B.drawShare(shareId);
      } catch (e) { log(`  ❌ ${B.remark} 领取异常: ${e.message}`); }
      await sleep(rand(500, 1000));
    } else {
      // A 分享返回 null（可能已完成），B 直接处理自己的弹窗
      await B.handlePop();
    }

    // 双方均处理弹窗（确保积分到账）
    await A.handlePop();

    log(`  ✅ ${A.remark} 与 ${B.remark} 分享任务处理完毕`);
    await sleep(rand(1000, 2000));
  }

  // 奇数末尾账号单独处理分享（无人领取）
  if (valid.length % 2 !== 0) {
    const last = valid[valid.length - 1];
    log(`\n⚠️ ${last.remark} 无配对账号`);
    try { await last.doShare(); } catch (e) { log(`  ❌ ${last.remark}: ${e.message}`); }
  }

  // ── 阶段三：统一翻牌 ──────────────────────────────────────────────────
  log('\n══ 阶段三：翻牌挑战 ══');

  // 刷新次数
  for (const c of valid) {
    try { await c.queryUser(); } catch {}
  }

  const summaries = [];
  for (const c of clients) {
    if (c._loginFailed) { summaries.push(`【${c.remark}】登录失败`); continue; }
    try {
      const cnt = await c.drawAll();
      const prizes = c.awards.length ? c.awards.join('、') : '无';
      summaries.push(`【${c.remark}】翻牌${cnt}次 | ${prizes}`);
    } catch (e) {
      summaries.push(`【${c.remark}】翻牌失败: ${e.message}`);
    }
    await sleep(rand(1000, 2000));
  }

  log('\n══ 汇总 ══');
  summaries.forEach(s => log(s));

  try {
    const notify = require('./sendNotify');
    await notify.sendNotify(SCRIPT_NAME, summaries.join('\n\n'));
  } catch {}
}

main().catch(e => { console.log('FATAL: ' + e.message); process.exit(1); });
