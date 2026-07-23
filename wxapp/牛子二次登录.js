// 青龙脚本：微信账号状态检查与二次登录
//
// 建议定时：6点检查一次
// cron: 44 11,16 * * *
//
// 青龙环境变量：
// WX_STATUS_BASE   接口地址，默认：http://192.168.6.222:8011
// WX_STATUS_COOKIE 登录 Cookie，必填，例如：
//                  language=zh-CN; fnos-token=xxx; fnos-long-token=xxx
//
// 可选环境变量：
// WX_STATUS_NOTIFY       掉线/二次登录结果是否通知，默认 1；填 0 关闭
// WX_STATUS_NOTIFY_ALL   全部在线时是否通知，默认 1；填 0 只在掉线/失败/异常时通知
// WX_STATUS_RETRY        二次登录失败后的重试次数，默认 1
// WX_STATUS_RETRY_DELAY  重试间隔毫秒，默认 1500
// WX_STATUS_TIMEOUT      请求超时毫秒，默认 15000

const path = require('path');
const http = require('http');
const https = require('https');
const { URL } = require('url');

const CONFIG = {
  baseUrl: trimRightSlash(process.env.WX_STATUS_BASE || 'http://192.168.6.222:8011'),
  cookie: process.env.WX_STATUS_COOKIE || 'token=eYd9ENLb+2mWdh92Hq/1DprgFWO9BEWYTFrNMnjCq/U=; fnos-long-token=j1KkTOgDAADSaCNqAAAAADDKh7JKPDMzPZyPQJ8r3zNlKOqwTCTDMQ==',
  notify: process.env.WX_STATUS_NOTIFY !== '0',
  notifyAll: process.env.WX_STATUS_NOTIFY_ALL !== '0',
  retry: toNonNegativeInt(process.env.WX_STATUS_RETRY, 1),
  retryDelay: toNonNegativeInt(process.env.WX_STATUS_RETRY_DELAY, 1500),
  timeout: toNonNegativeInt(process.env.WX_STATUS_TIMEOUT, 15000),
};

const COMMON_HEADERS = {
  Accept: '*/*',
  'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
  Connection: 'keep-alive',
  Referer: `${CONFIG.baseUrl}/`,
  'User-Agent':
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0',
};

main().catch(async (error) => {
  const message = error && error.stack ? error.stack : String(error);
  console.log(`[异常] ${message}`);
  await sendNotify('微信账号状态检查异常', message);
  process.exitCode = 1;
});

async function main() {
  if (!CONFIG.cookie) {
    throw new Error('缺少环境变量 WX_STATUS_COOKIE，请在青龙环境变量中填写登录 Cookie');
  }

  console.log(`[开始] 检查账号状态：${CONFIG.baseUrl}`);

  const statusResult = await apiRequest('/api/v1/wx/user/status');
  if (!statusResult || statusResult.status !== true || !statusResult.data) {
    throw new Error(`账号状态接口返回异常：${JSON.stringify(statusResult)}`);
  }

  const accounts = Object.values(statusResult.data);
  if (!accounts.length) {
    console.log('[结果] 未获取到账号列表');
    return;
  }

  const offlineAccounts = accounts.filter((account) => Number(account.survival) === 0);
  const onlineAccounts = accounts.filter((account) => Number(account.survival) !== 0);
  const summary = `共 ${accounts.length} 个，在线 ${onlineAccounts.length} 个，掉线 ${offlineAccounts.length} 个`;

  console.log(`[账号] ${summary}`);
  for (const account of accounts) {
    const statusText = Number(account.survival) === 0 ? '掉线' : '在线';
    console.log(`- ${displayName(account)}：${statusText}，刷新时间 ${formatTime(account.refreshDate)}`);
  }

  if (!offlineAccounts.length) {
    console.log('[完成] 没有掉线账号，无需二次登录');
    await sendNotify(
      '微信账号状态检查',
      buildStatusNotifyMessage(summary, accounts, []),
      { force: CONFIG.notifyAll },
    );
    return;
  }

  const loginResults = [];
  for (const account of offlineAccounts) {
    const result = await twiceLoginWithRetry(account);
    loginResults.push(result);
  }

  const notifyMessage = loginResults
    .map((item) => {
      const prefix = item.ok ? '成功' : '失败';
      const suffix = item.message ? `：${item.message}` : '';
      return `${prefix} ${displayName(item.account)}${suffix}`;
    })
    .join('\n');

  console.log('[二次登录结果]');
  console.log(notifyMessage);
  await sendNotify('微信账号掉线二次登录', buildStatusNotifyMessage(summary, accounts, loginResults), { force: true });
}

async function twiceLoginWithRetry(account) {
  const maxAttempts = CONFIG.retry + 1;
  let lastError = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      console.log(`[二次登录] ${displayName(account)}，第 ${attempt}/${maxAttempts} 次`);
      const result = await apiRequest('/api/v1/wx/login/twice', {
        method: 'POST',
        body: { wxid: account.wxid },
      });

      if (result && result.status === true) {
        return { ok: true, account, message: extractMessage(result) };
      }

      lastError = new Error(`接口返回失败：${JSON.stringify(result)}`);
    } catch (error) {
      lastError = error;
    }

    if (attempt < maxAttempts) {
      console.log(`[重试] ${displayName(account)} ${CONFIG.retryDelay}ms 后重试`);
      await sleep(CONFIG.retryDelay);
    }
  }

  return {
    ok: false,
    account,
    message: lastError ? lastError.message : '未知错误',
  };
}

function apiRequest(pathname, options = {}) {
  const url = new URL(pathname, CONFIG.baseUrl);
  const body = options.body ? JSON.stringify(options.body) : '';
  const isHttps = url.protocol === 'https:';
  const client = isHttps ? https : http;

  const headers = {
    ...COMMON_HEADERS,
    Cookie: CONFIG.cookie,
    ...(options.headers || {}),
  };

  if (body) {
    headers['Content-Type'] = 'application/json';
    headers['Content-Length'] = Buffer.byteLength(body);
    headers.Origin = CONFIG.baseUrl;
  }

  return new Promise((resolve, reject) => {
    const request = client.request(
      url,
      {
        method: options.method || (body ? 'POST' : 'GET'),
        headers,
        timeout: CONFIG.timeout,
        rejectUnauthorized: false,
      },
      (response) => {
        const chunks = [];
        response.on('data', (chunk) => chunks.push(chunk));
        response.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          if (response.statusCode < 200 || response.statusCode >= 300) {
            reject(new Error(`HTTP ${response.statusCode}：${text}`));
            return;
          }

          try {
            resolve(text ? JSON.parse(text) : {});
          } catch (error) {
            reject(new Error(`响应不是合法 JSON：${text}`));
          }
        });
      },
    );

    request.on('timeout', () => {
      request.destroy(new Error(`请求超时：${CONFIG.timeout}ms`));
    });
    request.on('error', reject);

    if (body) request.write(body);
    request.end();
  });
}

async function sendNotify(title, message, options = {}) {
  if (!CONFIG.notify || !message) return;
  if (options.force === false) return;

  try {
    const notify = loadNotifyModule();
    if (notify && typeof notify.sendNotify === 'function') {
      await notify.sendNotify(title, message);
    } else if (typeof notify === 'function') {
      await notify(title, message);
    } else {
      console.log('[通知] sendNotify 模块格式不支持');
    }
  } catch (error) {
    console.log(`[通知] 未发送通知：${error.message}`);
  }
}

function loadNotifyModule() {
  const candidates = [
    './sendNotify',
    './sendNotify.js',
    '/ql/data/scripts/sendNotify',
    '/ql/data/scripts/sendNotify.js',
    '/ql/scripts/sendNotify',
    '/ql/scripts/sendNotify.js',
    path.join(process.cwd(), 'sendNotify'),
    path.join(process.cwd(), 'sendNotify.js'),
  ];

  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (error) {
      if (error && error.code !== 'MODULE_NOT_FOUND') throw error;
    }
  }

  throw new Error('未找到 sendNotify.js，请确认青龙通知依赖已安装');
}

function buildStatusNotifyMessage(summary, accounts, loginResults) {
  const lines = [`账号状态：${summary}`];

  lines.push('');
  lines.push('账号明细：');
  for (const account of accounts) {
    const statusText = Number(account.survival) === 0 ? '掉线' : '在线';
    lines.push(`${statusText} ${displayName(account)}`);
  }

  if (loginResults.length) {
    lines.push('');
    lines.push('二次登录：');
    for (const item of loginResults) {
      const prefix = item.ok ? '成功' : '失败';
      const suffix = item.message ? `：${item.message}` : '';
      lines.push(`${prefix} ${displayName(item.account)}${suffix}`);
    }
  }

  return lines.join('\n');
}

function extractMessage(result) {
  if (!result) return '';
  if (typeof result.message === 'string') return result.message;
  if (typeof result.msg === 'string') return result.msg;
  if (typeof result.data === 'string') return result.data;
  return '';
}

function displayName(account) {
  const nickname = account.nickname || '未命名';
  return `${nickname}(${account.wxid})`;
}

function formatTime(timestamp) {
  const number = Number(timestamp);
  if (!number) return '未知';
  return new Date(number * 1000).toLocaleString('zh-CN', { hour12: false });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function trimRightSlash(value) {
  return String(value || '').replace(/\/+$/, '');
}

function toNonNegativeInt(value, fallback) {
  const number = Number.parseInt(value, 10);
  return Number.isFinite(number) && number >= 0 ? number : fallback;
}
