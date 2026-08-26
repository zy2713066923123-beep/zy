require('./yyb.js'); // 自动同步 yyb_go 存活账号
﻿// name:美信优选
/*
美信优选签到
cron: 44 9,13 * * *
环境变量：
MEIXINhd='手机号&密码#备注'
多账号换行分隔，例如：
MEIXINhd='13800000000&123456#账号1
13900000000&abcdef#账号2'
*/
const https = require('https');

const base = 'https://mixonbest.com/api/v2';
const UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.70(0x18004629) NetType/4G Language/zh_CN';
const ENV_NAME = 'MEIXINhd';

function parseAccounts(raw) {
  return raw.split(/\n+/).map(s => s.trim()).filter(Boolean).map(line => {
    let remark = '';
    let pair = line;
    const idx = line.indexOf('#');
    if (idx >= 0) {
      pair = line.slice(0, idx).trim();
      remark = line.slice(idx + 1).trim();
    }
    const m = pair.match(/^([^&\s]+)&(.+)$/);
    if (!m) return null;
    return { phone: m[1].trim(), password: m[2].trim(), remark };
  }).filter(Boolean);
}

function request(api, data = {}, token = '') {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(data);
    const url = new URL(base + '/' + api);
    const req = https.request({
      hostname: url.hostname,
      path: url.pathname,
      method: 'POST',
      timeout: 15000,
      headers: {
        'content-type': 'application/json',
        'content-length': Buffer.byteLength(body),
        'http-token': token,
        'is-mini': '1',
        'app-version': '3.6.4',
        'user-agent': UA,
        'referer': 'https://servicewechat.com/wx1ee8dccc0e2c978d/89/page-frame.html'
      }
    }, res => {
      let chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => {
        let text = Buffer.concat(chunks).toString('utf8').trim();
        text = text.replace(/^([0-9a-fA-F]+)\s*/, '').replace(/\s*0\s*$/, '').trim();
        try {
          resolve({ status: res.statusCode, data: JSON.parse(text), raw: text });
        } catch (e) {
          resolve({ status: res.statusCode, data: null, raw: text });
        }
      });
    });
    req.on('timeout', () => req.destroy(new Error('请求超时')));
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

async function login(phone, password) {
  const r = await request('merchant.member/login', { phone, password, registration_id: '', mobile_model: '' }, '');
  if (!r.data) throw new Error('登录返回非JSON: ' + r.raw.slice(0, 200));
  return r.data;
}

async function userInfo(token) {
  const r = await request('Member/userInfo', {}, token);
  if (!r.data) throw new Error('userInfo返回非JSON: ' + r.raw.slice(0, 200));
  return r.data;
}

async function doSign(token) {
  const r = await request('Member/sign', {}, token);
  if (!r.data) throw new Error('sign返回非JSON: ' + r.raw.slice(0, 200));
  return r.data;
}

function safeNum(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function pickScore(data = {}) {
  const list = [
    data.score,
    data.current_score,
    data.total_score,
    data.user_score,
    data.today_score
  ];
  for (const item of list) {
    const n = safeNum(item);
    if (n !== null) return n;
  }
  return null;
}

function pickContinuity(data = {}) {
  const list = [data.continuity_sign_day, data.sign_day, data.sign_days];
  for (const item of list) {
    const n = safeNum(item);
    if (n !== null) return n;
  }
  return null;
}

function pickGain(signData = {}, beforeInfo = {}, afterInfo = {}) {
  const directList = [
    signData.score,
    signData.reward_score,
    signData.get_score,
    signData.add_score,
    signData.today_score
  ];
  for (const item of directList) {
    const n = safeNum(item);
    if (n !== null) return n;
  }

  const beforeScore = pickScore(beforeInfo);
  const afterScore = pickScore(afterInfo);
  if (beforeScore !== null && afterScore !== null) {
    return afterScore - beforeScore;
  }
  return null;
}

async function main() {
  const raw = process.env[ENV_NAME];
  if (!raw) {
    console.log(`未设置环境变量 ${ENV_NAME}`);
    console.log('格式: 手机号&密码#备注，多账号换行');
    process.exit(1);
  }
  const accounts = parseAccounts(raw);
  if (!accounts.length) {
    console.log('未解析到有效账号，请按“手机号&密码#备注”多行填写');
    process.exit(1);
  }

  const msgs = [];
  for (const acc of accounts) {
    const title = acc.remark || acc.phone.replace(/^(\d{3})\d{4}(\d{4})$/, '$1****$2');
    try {
      const lg = await login(acc.phone, acc.password);
      if (![1, 2, 3].includes(Number(lg.code)) || !lg.data || !lg.data.token) {
        msgs.push(`❌ ${title} 登录失败: ${lg.msg || JSON.stringify(lg)}`);
        continue;
      }

      const token = lg.data.token;
      const before = await userInfo(token);
      const beforeInfo = (before && before.data) || {};
      const beforeScore = pickScore(beforeInfo);
      const beforeContinuity = pickContinuity(beforeInfo);

      if (Number(beforeInfo.is_sign) === 1) {
        msgs.push(`✅ ${title} 今日已签到 | 连签:${beforeContinuity ?? '-'}天 | 当前积分:${beforeScore ?? '-'}`);
        continue;
      }

      const sg = await doSign(token);
      const after = await userInfo(token).catch(() => ({ data: {} }));
      const afterInfo = after.data || {};
      const afterScore = pickScore(afterInfo);
      const afterContinuity = pickContinuity(afterInfo);
      const gain = pickGain((sg && sg.data) || {}, beforeInfo, afterInfo);
      const signMsg = (sg && sg.msg) ? sg.msg : '签到成功';

      msgs.push(`✅ ${title} 签到结果:${signMsg} | 本次获得:${gain ?? '未知'}积分 | 连签:${afterContinuity ?? beforeContinuity ?? '-'}天 | 当前积分:${afterScore ?? beforeScore ?? '-'}`);
    } catch (e) {
      msgs.push(`❌ ${title} 异常: ${e.message}`);
    }
  }

  console.log(msgs.join('\n'));
}

main();