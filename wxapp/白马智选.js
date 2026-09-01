require('./yyb.js'); // 自动同步 yyb_go 存活账号
﻿// name:白马智选
/**
 * 白马智选（白马严选）
 *
 * cron: 0 14,02 * * * 
 * 环境变量：
 *   WX_ID           必填，格式：wxid#备注，多账号换行或 & 分隔
 *   WECHAT_SERVER   必填，微信协议服务地址
 */
const getWxCode = (wxid, appid) => getSingleCode(appid, String(wxid).split('#')[0].trim());
const https = require('https');
const http = require('http');
const zlib = require('zlib');
const WX_APPID = 'wx51f8cb2a7578f42f';
let ckName = "WX_ID";
let WXID_RAW = (process.env.WX_ID || '').trim();
const WECHAT_SERVER = (process.env.WX_SERVER || process.env.YYB_SERVER || process.env.WECHAT_SERVER || process.env.YINGYONGBAO_SERVER || '').replace(/\/$/, '');

const SCRIPT_NAME = '白马智选';
const MULTI_SPLIT = ['\n', '&', '@'];

// ==================== 通知模块 ====================
let _logMessages = [];
function log(str) {
    console.log(str);
    _logMessages.push(str);
}
async function push_notification() {
    let notify;
    try { notify = require('./notify'); } catch (e) { notify = null; }
    const title = "白马智选";
    const content = _logMessages.join('\n');
    if (notify && typeof notify.send === 'function') {
        try {
            await notify.send(title, content);
            log('✅ 通知发送成功');
        } catch (e) {
            log('⚠️ 通知发送失败: ' + e.message);
        }
    } else {
        log("--- 通知 ---\n" + title + "\n" + content + "\n-------------");
    }
}

// ==================== Node.js HTTP 请求引擎 ====================
function httpRequest(opts) {
    return new Promise((resolve, reject) => {
        const urlStr = opts.url;
        if (!urlStr) { resolve({ status: 0, body: '', error: 'no url' }); return; }

        const parsed = new URL(urlStr);
        const isHttps = parsed.protocol === 'https:';
        const lib = isHttps ? https : http;

        const reqOpts = {
            hostname: parsed.hostname,
            port: parsed.port || (isHttps ? 443 : 80),
            path: parsed.pathname + parsed.search,
            method: opts.method || 'POST',
            headers: opts.headers || {}
        };

        const req = lib.request(reqOpts, (res) => {
            const chunks = [];
            let stream = res;
            const encoding = res.headers['content-encoding'];
            if (encoding === 'gzip') stream = res.pipe(zlib.createGunzip());
            else if (encoding === 'deflate') stream = res.pipe(zlib.createInflate());
            else if (encoding === 'br') stream = res.pipe(zlib.createBrotliDecompress());

            stream.on('data', (chunk) => chunks.push(chunk));
            stream.on('end', () => {
                const body = Buffer.concat(chunks).toString('utf-8');
                resolve({ status: res.statusCode, headers: res.headers, body: body });
            });
            stream.on('error', (e) => resolve({ status: res.statusCode, body: '', error: e.message }));
        });

        req.on('error', (e) => {
            log(`[HTTP] 请求失败: ${e.message}`);
            resolve({ status: 0, body: '', error: e.message });
        });

        if (opts.body) req.write(opts.body);
        req.end();
    });
}

// JSON POST（协议服务器用）
async function jsonPost(url, headers = {}, body = {}) {
    const resp = await httpRequest({
        url: url,
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    if (resp.error) { log(`[jsonPost] 错误: ${resp.error}`); return null; }
    try { return JSON.parse(resp.body); }
    catch { log(`[jsonPost] 解析失败: ${resp.body.substring(0, 80)}`); return null; }
}

// BMYX API POST（form-urlencoded）
const BMYX_HEADERS = {
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Host': 'min.51afa.com',
    'Referer': `https://servicewechat.com/${WX_APPID}/440/page-frame.html`,
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'cross-site',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541a35) XWEB/19977',
    'xweb_xhr': '1'
};

async function commonPost(action, body = '') {
    const resp = await httpRequest({
        url: `https://min.51afa.com/module/integralApi/${action}.html?`,
        method: 'POST',
        headers: BMYX_HEADERS,
        body: body
    });
    if (resp.error) { log(`[commonPost] 网络错误: ${resp.error}`); return null; }
    if (resp.status === 404) return { status: 404 };
    try { return JSON.parse(resp.body); }
    catch { log(`[commonPost] 解析失败: ${resp.body.substring(0, 80)}`); return null; }
}

// ==================== 微信协议 ====================
// 使用 yyb.js 统一接口

// ==================== 登录逻辑 ====================
async function loginByCode(code) {
    log('🔐 使用code登录白马严选...');
    const result = await commonPost('login', `code=${code}&company_id=1&_cache_=1`);
    if (!result) { log(`❌ 登录请求失败`); return false; }
    if (result.status === 404) { log(`❌ 登录路径404`); return false; }
    const token = extractToken(result);
    if (token) {
        const phone = result.data?.userInfo?.phone || '';
        log(`✅ 登录成功 (手机号: ${phone})`);
        return token;
    }
    log(`⚠️ 有响应但未提取到token: ${JSON.stringify(result).substring(0, 120)}`);
    return false;
}

function extractToken(result) {
    if (!result || !result.data) return false;
    const data = result.data;
    for (const key of ['token', 'accessToken', 'access_token', 'Token', 'auth_token', 'session_token', 'sessionId']) {
        if (data[key] !== undefined && data[key] !== null && data[key] !== '') return String(data[key]);
    }
    if (data.userInfo?.token) return String(data.userInfo.token);
    if (data.memberInfo?.token) return String(data.memberInfo.token);
    return false;
}

// ==================== 账号解析 ====================
function parseAccounts(raw) {
    let sep = null;
    for (const s of MULTI_SPLIT) { if (raw.includes(s)) { sep = s; break; } }
    const items = sep ? raw.split(sep) : [raw];
    return items.map(item => {
        item = (item || '').trim();
        if (!item) return null;
        const idx = item.lastIndexOf('#');
        if (idx > 0) return { wxid: item.substring(0, idx).trim(), note: item.substring(idx + 1).trim() };
        return { wxid: item, note: '' };
    }).filter(x => x && x.wxid);
}

// ==================== 延时 ====================
function wait(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

// ==================== 主流程 ====================
async function main() {
    log(`🔔${SCRIPT_NAME}, 开始!`);

    // 优先从 yyb 拉取全部存活账号（不受 WX_ID 过滤，配 N 条只跑 N 个）
    try {
        const online = await new YYBClient().getOnlineAccounts();
        if (online && online.length) {
            WXID_RAW = online
                .map(acc => {
                    const id = acc.openid || acc.wxid || String(acc.id || '');
                    const note = acc.nickname || acc.alias || acc.remark || '';
                    return id ? `wx:${id}#${note}` : '';
                })
                .filter(Boolean)
                .join('\n');
            log(`✅ 从 yyb 服务拉取到 ${online.length} 个存活账号`);
        }
    } catch (e) {
        log(`[yyb] 拉取账号列表失败: ${e.message || e}`);
    }
    if (!WXID_RAW) {
        // 回退：WX_ID 环境变量
        WXID_RAW = (process.env.WX_ID || '').trim();
    }
    if (!WXID_RAW) {
        // 兜底：自动从 yyb_go 拉取存活账号
        const auto = await resolveAccounts();
        if (auto && auto.length) {
            WXID_RAW = auto.join('\n');
        } else {
            log('❌ 未找到 ' + ckName + ' 环境变量');
            await push_notification();
            return;
        }
    }
    if (!WECHAT_SERVER) {
        log('❌ 未找到 WECHAT_SERVER 环境变量');
        await push_notification();
        return;
    }

    const accounts = parseAccounts(WXID_RAW);
    log(`共 ${accounts.length} 个账号\n`);

    for (let i = 0; i < accounts.length; i++) {
        const { wxid, note } = accounts[i];
        const label = note ? `[账号${i + 1}](${note})` : `[账号${i + 1}]`;
        log(`────── ${label} 开始执行 ──────`);

        // Step 1: 获取微信授权 code
        // token 缓存：有效期内复用，避免每次运行都重新取 code（规避微信限流）
        let token = null;
        const cached = getCachedToken('baima', wxid, { maxAgeMs: 6 * 3600 * 1000 });
        if (cached) {
            token = cached.token;
            log(`${label} 🧩 命中token缓存，跳过取code`);
        } else {
            log(`${label} 🔑 获取微信授权code...`);
            let code;
            try { code = await getWxCode(wxid, WX_APPID); } catch (e) { log(`${label} ❌ ${e.message}`); continue; }
            if (!code) { log(`${label} ❌ 获取code失败`); continue; }

            // Step 2: code 登录获取 token
            await wait(2000);
            log(`${label} 🔐 使用code登录白马严选...`);
            token = await loginByCode(code);
            if (!token) { log(`${label} ❌ 登录失败，跳过`); continue; }
            saveCachedToken('baima', wxid, token);
        }

        // Step 3: 签到（先 do_sign 执行签到，再 get_date 查日历）
        await wait(2000);
        log(`${label} 开始签到`);

        // 3a: 执行签到
        const ts = Date.now();
        const doSignHeaders = { ...BMYX_HEADERS, 'act': 'do_sign' };
        const doSignResp = await httpRequest({
            url: `https://min.51afa.com/module/integralApi/sign.html?`,
            method: 'POST',
            headers: doSignHeaders,
            body: `token=${token}&timestamp=${ts}&company_id=1`
        });
        let doSignData = null;
        try { doSignData = JSON.parse(doSignResp.body); } catch {}
        if (!doSignData) {
            log(`${label} ❌ 签到请求失败`);
            continue;
        }
        log(`${label} 签到结果: ${doSignData.msg || '未知'} (status=${doSignData.status})`);

        // 3b: 查签到日历
        await wait(1000);
        const calHeaders = { ...BMYX_HEADERS, 'act': 'get_date' };
        const calResp = await httpRequest({
            url: `https://min.51afa.com/module/integralApi/sign.html?`,
            method: 'POST',
            headers: calHeaders,
            body: `token=${token}&timestamp=${Date.now()}&company_id=1`
        });
        let calData = null;
        try { calData = JSON.parse(calResp.body); } catch {}
        if (calData && calData.data) {
            const d = calData.data;
            log(`${label} 本周已签: ${d.signed_counts || 0} 天 | 上次签到: ${d.last_signed_time || '无'}`);
        }

        // Step 4: 积分查询
        await wait(2000);
        log(`${label} 积分查询`);
        const pointResult = await commonPost('member_center_info', `token=${token}&action=current&company_id=1&_cache_=1`);
        if (pointResult && pointResult.data) {
            const info = pointResult.data.memberInfo || pointResult.data.userInfo || {};
            const points = info.integral_member_point || info.memberPoints || '未知';
            const pointsAll = info.integral_member_point_all || '';
            log(`${label} 当前积分: ${points}${pointsAll ? ` | 累计: ${pointsAll}` : ''}`);
        }

        log(`────── ${label} 执行完成 ──────\n`);

        if (i < accounts.length - 1) {
            const delay = Math.floor(Math.random() * 45) + 45;
            log(`⏳ 等待 ${delay} 秒`);
            await wait(delay * 1000);
        }
    }

    // 推送通知
    await push_notification();

    const endTime = ((new Date()).getTime() - startTime) / 1000;
    log(`🔔${SCRIPT_NAME}, 结束! 🕛 ${endTime} 秒`);
}

const startTime = (new Date()).getTime();

// ==================== 入口 ====================
main().catch((e) => { log(`❌ 运行出错: ${e.message}`); });