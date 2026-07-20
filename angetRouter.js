#!/usr/bin/env node
'use strict';

/**
 * AgentRouter (agentrouter.org) 每日登录签到脚本
 *
 * 网站说明：
 *   每天首次用 邮箱号+密码 登录 agentrouter.org，会自动完成每日签到并增加额度。
 *   登录接口内置签到逻辑：响应 data.checked_in=true 即表示签到成功，新增额度已到账。
 *   余额需通过登录后调用 /api/user/self 获取（登录响应里的 quota 是旧值 0）。
 *
 * 逆向结论（基于抓包 + 前端 JS 分析）：
 *   1. 登录接口：POST https://agentrouter.org/api/user/login?turnstile=
 *      请求体：{"username":"邮箱","password":"明文密码"}   （密码无加密，明文传输）
 *      Turnstile 人机验证当前站点已关闭，turnstile 参数留空即可。
 *   2. 签到：登录即签到，无需单独调用签到接口。
 *      前端逻辑：ce.checked_in ? 提示"签到成功，新增额度已到账" : 提示"登录成功！"
 *   3. 余额：GET https://agentrouter.org/api/user/self，取 data.quota。
 *      额度单位：quota / QuotaPerUnit(默认 500000) = 美元。
 *   4. 鉴权：登录成功后服务端通过 Set-Cookie 下发 session，后续请求携带该 Cookie 即可。
 *
 * 青龙环境变量：
 *   agentrouter=邮箱#密码
 *   多账号可用换行、& 分隔（注意：因邮箱含 @，故不支持用 @ 作为账号分隔符）：
 *     agentrouter=a@b.com#pass1&c@d.com#pass2
 *   也可每行一个账号写入面板的"多行值"。
 *
 * 可选控制变量：
 *   AGENTROUTER_NOTIFY=0   关闭青龙 notify.py 消息推送，默认开启
 *   AGENTROUTER_QUOTA_PER_UNIT=500000  额度兑换美元的单位，默认 500000
 *
 * 定时建议：每天执行一次，例如 cron: 30 8 * * *
 */

const https = require('https');
const { spawnSync } = require('child_process');
const os = require('os');

const BASE_HOST = 'agentrouter.org';
const LOGIN_PATH = '/api/user/login?turnstile=';
const SELF_PATH = '/api/user/self';
const USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36';

const CONFIG = {
  notify: process.env.AGENTROUTER_NOTIFY !== '0' && !isTruthy(process.env.AGENTROUTER_NO_NOTIFY),
  quotaPerUnit: toNumber(process.env.AGENTROUTER_QUOTA_PER_UNIT, 500000),
};

const NOTIFY_TITLE = 'AgentRouter 签到';
const notifyLines = [];

function isTruthy(value) {
  return /^(1|true|yes|on)$/i.test(String(value || '').trim());
}

function toNumber(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

function nowText() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/**
 * 邮箱脱敏：保留用户名前 2 位 + 域名，中间用 4 个 * 代替。
 * 例：582600319@qq.com -> 58****@qq.com；ab@x.com -> ab****@x.com
 */
function maskEmail(email) {
  const s = String(email || '');
  const at = s.indexOf('@');
  if (at < 1) return s;
  const user = s.slice(0, at);
  const domain = s.slice(at);
  const keep = user.length <= 2 ? user.slice(0, 1) : user.slice(0, 2);
  return `${keep}****${domain}`;
}

/**
 * 发送 HTTPS 请求并返回 { statusCode, headers, body }。
 * @param {string} method  GET / POST
 * @param {string} path     接口路径（含 querystring）
 * @param {object} opts     { body, cookie, newApiUser }
 */
function request(method, path, opts = {}) {
  return new Promise((resolve, reject) => {
    const headers = {
      'User-Agent': USER_AGENT,
      Accept: 'application/json, text/plain, */*',
      'Accept-Language': 'zh-CN,zh;q=0.9',
      'Cache-Control': 'no-store',
      Referer: 'https://agentrouter.org/login',
      Origin: 'https://agentrouter.org',
    };
    if (opts.cookie) headers.Cookie = opts.cookie;
    if (opts.newApiUser !== undefined) headers['New-API-User'] = String(opts.newApiUser);

    let bodyStr = '';
    if (opts.body !== undefined) {
      bodyStr = typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body);
      headers['Content-Type'] = 'application/json';
      headers['Content-Length'] = Buffer.byteLength(bodyStr);
    }

    const req = https.request(
      { host: BASE_HOST, path, method, headers },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          resolve({
            statusCode: res.statusCode,
            headers: res.headers,
            body: Buffer.concat(chunks).toString('utf8'),
          });
        });
      }
    );
    req.on('error', reject);
    if (bodyStr) req.write(bodyStr);
    req.end();
  });
}

/** 从 Set-Cookie 头里提取 session=xxx 的值，组装成可回传的 Cookie 字符串。 */
function extractSession(setCookie) {
  if (!setCookie) return '';
  const list = Array.isArray(setCookie) ? setCookie : [setCookie];
  for (const item of list) {
    const m = /session=([^;]+)/i.exec(item);
    if (m) return `session=${m[1]}`;
  }
  return '';
}

/** 额度 -> 美元显示。 */
function quotaToUsd(quota) {
  const usd = quota / CONFIG.quotaPerUnit;
  return `$${usd.toFixed(2)}`;
}

/**
 * 解析账号环境变量：邮箱#密码，多账号用换行或 & 分隔。
 * 注意：因邮箱含 @，故不支持 @ 作为账号分隔符。
 */
function parseAccounts() {
  const raw = process.env.agentrouter || process.env.AGENTROUTER || '';
  return String(raw || '')
    .split(/[\n&]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item, index) => {
      const parts = item.split('#');
      const username = (parts[0] || '').trim();
      const password = (parts[1] || '').trim();
      if (!username || !password) {
        throw new Error(`第 ${index + 1} 个账号格式错误，应为 邮箱#密码`);
      }
      return { username, password };
    });
}

/** 单账号执行：登录 -> 查询余额，返回结果摘要。 */
async function runAccount(account, index) {
  const masked = maskEmail(account.username);
  const tag = `【账号${index + 1}】${masked}`;
  console.log(`\n=== ${tag} 开始 ===`);

  // 1. 登录（登录即签到，请求体里仍用真实邮箱）
  const loginRes = await request('POST', LOGIN_PATH, {
    body: { username: account.username, password: account.password },
    newApiUser: -1,
  });

  if (loginRes.statusCode !== 200) {
    throw new Error(`登录接口返回 HTTP ${loginRes.statusCode}`);
  }

  let loginJson;
  try {
    loginJson = JSON.parse(loginRes.body);
  } catch {
    throw new Error(`登录响应解析失败: ${loginRes.body.slice(0, 200)}`);
  }

  if (!loginJson.success) {
    throw new Error(loginJson.message || '登录失败');
  }

  const userData = loginJson.data || {};
  const userId = userData.id;
  const checkedIn = !!userData.checked_in;
  const sessionCookie = extractSession(loginRes.headers['set-cookie']);
  if (!sessionCookie) {
    throw new Error('登录成功但未拿到 session Cookie，无法继续查询余额');
  }

  console.log(`登录成功，用户ID=${userId}，签到状态=${checkedIn ? '已签到' : '未签到'}`);

  // 2. 查询余额（登录响应里的 quota 是旧值，需重新拉取 /api/user/self）
  const selfRes = await request('GET', SELF_PATH, {
    cookie: sessionCookie,
    newApiUser: userId,
  });

  let quota = 0;
  let usedQuota = 0;
  let requestCount = 0;
  let displayName = '';
  let email = '';

  if (selfRes.statusCode === 200) {
    try {
      const selfJson = JSON.parse(selfRes.body);
      if (selfJson.success && selfJson.data) {
        quota = selfJson.data.quota || 0;
        usedQuota = selfJson.data.used_quota || 0;
        requestCount = selfJson.data.request_count || 0;
        displayName = selfJson.data.display_name || '';
        email = maskEmail(selfJson.data.email || account.username);
      }
    } catch (e) {
      console.log(`查询余额响应解析失败: ${e.message}`);
    }
  } else {
    console.log(`查询余额接口返回 HTTP ${selfRes.statusCode}`);
  }

  const summary = {
    tag,
    success: true,
    checkedIn,
    displayName,
    email,
    quota,
    usedQuota,
    requestCount,
  };
  console.log(`${tag} 完成：余额 ${quota} (${quotaToUsd(quota)})，签到=${checkedIn ? '成功' : '今日已签到/未触发'}`);
  return summary;
}

/** 调用青龙 notify.py 推送，兼容 /ql/data/scripts、/ql/scripts 等常见路径。 */
function pushNotify(title, content) {
  if (!CONFIG.notify || !content.trim()) return;

  const script = String.raw`
import importlib.util, os, sys

title = os.environ.get('AGENTROUTER_NOTIFY_TITLE', '')
content = os.environ.get('AGENTROUTER_NOTIFY_CONTENT', '')
search_dirs = []
ql_dir = os.environ.get('QL_DIR', '')
if ql_dir:
    search_dirs += [ql_dir, os.path.join(ql_dir, 'scripts'), os.path.join(ql_dir, 'data', 'scripts'), os.path.join(ql_dir, 'data', 'public')]
search_dirs += [os.getcwd(), os.path.dirname(os.getcwd()), '/ql', '/ql/scripts', '/ql/data/scripts', '/ql/data/public']
seen = set()
for directory in search_dirs:
    if not directory or directory in seen:
        continue
    seen.add(directory)
    notify_path = os.path.join(directory, 'notify.py')
    if not os.path.exists(notify_path):
        continue
    spec = importlib.util.spec_from_file_location('ql_notify', notify_path)
    if not spec or not spec.loader:
        continue
    module = importlib.util.module_from_spec(spec)
    sys.modules['ql_notify'] = module
    spec.loader.exec_module(module)
    send = getattr(module, 'send', None) or getattr(module, 'sendNotify', None)
    if send:
        send(title, content)
        print('消息推送完成')
        sys.exit(0)
print('未找到青龙 notify.py，跳过消息推送')
`;

  const env = {
    ...process.env,
    AGENTROUTER_NOTIFY_TITLE: title,
    AGENTROUTER_NOTIFY_CONTENT: content,
  };
  const result = spawnSync(process.env.PYTHON_BIN || 'python', ['-c', script], {
    cwd: process.cwd(),
    env,
    encoding: 'utf8',
    timeout: 30000,
  });
  if (result.error && result.error.code === 'ENOENT') {
    const fallback = spawnSync('python3', ['-c', script], { cwd: process.cwd(), env, encoding: 'utf8', timeout: 30000 });
    if (fallback.stdout.trim()) console.log(fallback.stdout.trim());
    if (fallback.stderr.trim()) console.log(`消息推送失败：${fallback.stderr.trim()}`);
    return;
  }
  if (result.stdout.trim()) console.log(result.stdout.trim());
  if (result.stderr.trim()) console.log(`消息推送失败：${result.stderr.trim()}`);
}

async function main() {
  console.log(`AgentRouter 每日登录签到  时间：${nowText()}`);

  const accounts = parseAccounts();
  if (!accounts.length) {
    console.log('未配置账号，请在青龙环境变量 agentrouter 中填入 邮箱#密码（多账号用换行或 & 分隔）。');
    return;
  }
  console.log(`共 ${accounts.length} 个账号待执行`);

  const summaries = [];
  for (let i = 0; i < accounts.length; i++) {
    try {
      const s = await runAccount(accounts[i], i);
      summaries.push(s);
    } catch (e) {
      const masked = maskEmail(accounts[i].username);
      console.log(`【账号${i + 1}】${masked} 执行失败：${e.message}`);
      summaries.push({
        tag: `【账号${i + 1}】${masked}`,
        success: false,
        message: e.message,
      });
    }
  }

  // 汇总推送
  const successCount = summaries.filter((s) => s.success).length;
  const failCount = summaries.length - successCount;

  for (const s of summaries) {
    if (s.success) {
      notifyLines.push(s.tag);
      notifyLines.push(`结果：${s.checkedIn ? '签到成功，新增额度已到账' : '登录成功（今日已签到）'}`);
      if (s.displayName) notifyLines.push(`昵称：${s.displayName}`);
      notifyLines.push(`余额：${s.quota} (${quotaToUsd(s.quota)})`);
      notifyLines.push(`已用：${s.usedQuota} (${quotaToUsd(s.usedQuota)})`);
      notifyLines.push(`请求次数：${s.requestCount}`);
    } else {
      notifyLines.push(s.tag);
      notifyLines.push(`结果：失败`);
      notifyLines.push(`说明：${s.message}`);
    }
    notifyLines.push('');
  }

  const content = [
    'AgentRouter 每日登录签到',
    `成功：${successCount}  失败：${failCount}`,
    `时间：${nowText()}`,
    '',
    ...notifyLines,
  ]
    .join('\n')
    .trim();

  console.log('\n========== 推送内容 ==========');
  console.log(content);
  console.log('==============================');

  pushNotify(NOTIFY_TITLE, content);

  if (failCount > 0) process.exitCode = 1;
}

main().catch((e) => {
  console.log(`运行异常：${e && e.stack ? e.stack : e}`);
  process.exitCode = 1;
});
