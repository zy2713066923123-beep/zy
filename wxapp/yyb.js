// name: YYB-Go / yyb-main 微信全能力通用工具库 (Node.js SDK) —— 适配重写版
/**
 * yyb-main / yyb-go 微信协议通用工具库 (Node.js) —— 适配重写版
 *
 * 完美支持 yyb-main (Python/FastAPI) 与 yyb-go 所有后端服务版本。
 * 全功能免鉴权支持、自适应端点降级路由：
 *   1. 账号管理: 存活账号自动发现 (`GET /api/accounts` / `GET /accounts`)
 *   2. 小程序取码: `wx.login` (`POST /api/yyb/get-code` / `POST /wxapp/getCode` / `POST /wx/code`)
 *   3. 手机号授权: `getPhoneNumber` (`POST /api/yyb/get-phone` / `POST /wxapp/getPhoneNumber`)
 *   4. 用户信息: `getUserInfo` (`POST /api/yyb/get-userinfo` / `POST /wxapp/getUserInfo`)
 *   5. 协议扩展: `operateWxData` (`POST /api/yyb/invoke-cloud` / `POST /wxapp/operateWxData`)
 *   6. 云开发: `cloudCallFunction` (`POST /api/yyb/cloud-call-function` / `POST /wxapp/cloud/function`)
 *   7. 云托管: `cloudCallContainer` (`POST /api/yyb/cloud-call-container` / `POST /wxapp/cloud/container`)
 *   8. 公众号 OAuth: `oauthAuthorize` (`POST /api/yyb/oauth-authorize` / `POST /wxapp/oauth/authorize`)
 */

const axios = require('axios');
const fs = require('fs');
const path = require('path');

// ============================================================
// 1. 服务地址与常量定义
// ============================================================

function getGlobalServerUrl() {
    return (
        process.env.WX_SERVER ||
        process.env.YYB_SERVER ||
        process.env.WECHAT_SERVER ||
        process.env.YINGYONGBAO_SERVER ||
        'http://127.0.0.1:8000'
    ).replace(/\/+$/, '');
}

const LOGIN_TYPE_WX = 'WX';
const LOGIN_TYPE_SYZS = 'SYZS';
const LOGIN_TYPE_WMPF = 'WMPF';

const LOGIN_TYPE_ALIASES = {
    '': LOGIN_TYPE_WX,
    'wx': LOGIN_TYPE_WX,
    'yyb': LOGIN_TYPE_WX,
    '应用宝': LOGIN_TYPE_WX,
    'syzs': LOGIN_TYPE_SYZS,
    '手游助手': LOGIN_TYPE_SYZS,
    'wmpf': LOGIN_TYPE_WMPF,
    '微信小程序': LOGIN_TYPE_WMPF,
    '小程序': LOGIN_TYPE_WMPF,
};

const LOGIN_TYPE_LABELS = {
    [LOGIN_TYPE_WX]: '应用宝',
    [LOGIN_TYPE_SYZS]: '手游助手',
    [LOGIN_TYPE_WMPF]: '微信小程序',
};

function normalizeLoginType(value) {
    const key = String(value === undefined || value === null ? '' : value).trim().toLowerCase();
    return LOGIN_TYPE_ALIASES[key] || LOGIN_TYPE_WX;
}

function loginTypeLabel(value) {
    const lt = normalizeLoginType(value);
    return LOGIN_TYPE_LABELS[lt] || lt;
}

// ============================================================
// 2. 账号标识解析 (Identifier Parser)
// ============================================================

const IDENTIFIER_SCHEMES = {
    'yyb': LOGIN_TYPE_WX,
    'wx': LOGIN_TYPE_WX,
    'syzs': LOGIN_TYPE_SYZS,
    'wmpf': LOGIN_TYPE_WMPF,
};

function parseIdentifier(identifier) {
    const text = String(identifier === undefined || identifier === null ? '' : identifier).trim();
    let scheme = '';
    let loginType = null;
    let body = text;

    const colonIdx = text.indexOf(':');
    if (colonIdx > 0) {
        const key = text.slice(0, colonIdx).trim().toLowerCase();
        if (IDENTIFIER_SCHEMES[key] !== undefined) {
            scheme = key;
            loginType = IDENTIFIER_SCHEMES[key];
            body = text.slice(colonIdx + 1).trim();
        }
    }

    let rawId = body;
    let remark = '';
    const hashIdx = body.indexOf('#');
    if (hashIdx >= 0) {
        rawId = body.slice(0, hashIdx).trim();
        remark = body.slice(hashIdx + 1).trim();
    }

    return { scheme, loginType, rawId, remark, original: text };
}

function stripScheme(identifier) {
    return parseIdentifier(identifier).rawId;
}

// ============================================================
// 3. 通用 HTTP 客户端封装 (YYBClient)
// ============================================================

class YYBClient {
    constructor(serverUrl = null, timeout = 30000) {
        this.serverUrl = (serverUrl || getGlobalServerUrl()).replace(/\/+$/, '');
        this.timeout = timeout;
        this._cachedAccounts = null;
        this._cacheTime = 0;
    }

    async _requestSingle(method, endpoint, data = null, params = null) {
        const url = `${this.serverUrl}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
        try {
            const resp = await axios({
                method,
                url,
                data,
                params,
                timeout: this.timeout,
                headers: { 'Content-Type': 'application/json' },
                validateStatus: () => true,
            });

            if (resp.status === 404) {
                return { ok: false, err: `[404] 接口不存在: ${endpoint}` };
            }

            const body = resp.data;
            if (body && typeof body === 'object') {
                if (body.success === false || (body.code !== undefined && body.code !== 0 && body.code !== 200)) {
                    const errMsg = body.msg || body.error || body.message || JSON.stringify(body);
                    return { ok: false, err: `[${body.code !== undefined ? body.code : -1}] ${errMsg}` };
                }
                // 兼容 yyb-go 的 respJson 字符串：解析后把内部字段提升到顶层
                if (typeof body.respJson === 'string' && body.respJson.trim()) {
                    try {
                        const inner = JSON.parse(body.respJson);
                        if (inner && typeof inner === 'object') {
                            return { ok: true, data: { ...body, ...inner, respJson: body.respJson } };
                        }
                    } catch (e) { /* 忽略解析失败，走默认分支 */ }
                }
                return { ok: true, data: body.data !== undefined ? body.data : body };
            }
            return { ok: true, data: body };
        } catch (e) {
            return { ok: false, err: e.message || String(e) };
        }
    }

    async _requestWithFallback(method, endpoints, data = null, params = null) {
        let lastErr = '';
        for (const ep of endpoints) {
            const res = await this._requestSingle(method, ep, data, params);
            if (res.ok) {
                return res.data;
            }
            lastErr = res.err;
        }
        throw new Error(`[YYB-SDK] 请求失败 (${endpoints.join(' / ')}): ${lastErr}`);
    }

    async _resolveRef(ref, expectLoginType = null) {
        const parsed = parseIdentifier(ref);
        const raw = parsed.rawId;
        const targetLt = parsed.loginType || (expectLoginType ? normalizeLoginType(expectLoginType) : null);

        if (!raw) {
            const accounts = await this.getOnlineAccounts();
            return accounts.length > 0 ? (accounts[0].openid || String(accounts[0].id || '')) : '';
        }

        const accounts = await this.getAccounts();
        if (!accounts || accounts.length === 0) {
            return raw;
        }

        let pool = await this.getOnlineAccounts();
        if (!pool || !pool.length) {
            pool = await this.getAccounts(true);
        }
        if (!pool || !pool.length) {
            return raw;
        }

        if (targetLt) {
            const filtered = pool.filter(acc => normalizeLoginType(acc.login_type) === targetLt);
            if (filtered.length) pool = filtered;
        }

        // 0. 如果传入空或者 "none"/"undefined"，直接返回首个存活账号
        if (!raw || ['none', 'undefined', 'null'].includes(raw.toLowerCase())) {
            return String(pool[0].openid || pool[0].id || '');
        }

        // 1. 精确匹配 openid / wxid / id
        for (const acc of pool) {
            if (acc.openid === raw || acc.wxid === raw || String(acc.id) === raw) {
                return String(acc.openid || acc.id);
            }
        }

        // 2. 按备注(alias)/昵称匹配
        const lower = raw.toLowerCase();
        for (const acc of pool) {
            const labels = [acc.alias, acc.remark, acc.nickname]
                .filter((v) => typeof v === 'string' && v.trim())
                .map((v) => v.trim().toLowerCase());
            if (labels.includes(lower)) {
                return String(acc.openid || acc.id);
            }
        }

        // 3. 数字索引匹配（如 ref 为 "1" / "2"）
        if (/^\d+$/.test(raw)) {
            const num = parseInt(raw, 10);
            if (num > 0 && num <= pool.length) {
                return String(pool[num - 1].openid || pool[num - 1].id);
            }
        }

        // 4. 自动兜底：映射到可用存活账号
        let hash = 0;
        for (let i = 0; i < raw.length; i++) hash = (hash << 5) - hash + raw.charCodeAt(i);
        const idx = Math.abs(hash) % pool.length;
        return String(pool[idx].openid || pool[idx].id || raw);
    }

    // ---------- 账号管理 ----------

    async getAccounts(forceRefresh = false) {
        const now = Date.now();
        if (!forceRefresh && this._cachedAccounts && now - this._cacheTime < 5000) {
            return this._cachedAccounts;
        }
        let list = [];
        try {
            const data = await this._requestWithFallback('GET', ['/api/accounts', '/accounts']);
            list = Array.isArray(data) ? data : (data?.accounts || data?.data || []);
        } catch (e) {
            list = [];
        }
        this._cachedAccounts = list;
        this._cacheTime = now;
        return list;
    }

    async getOnlineAccounts() {
        const accounts = await this.getAccounts(true);
        const OFFLINE = new Set(['offline', 'expired', 'invalid', 'disabled', 'error', 'dead', 'logout']);
        return accounts.filter(acc => {
            const st = (acc.status || '').toLowerCase();
            if (OFFLINE.has(st)) return false;
            if (Number(acc.loginSource || acc.login_source) === 3 && acc.hasSession === false) {
                const name = acc.nickname || acc.alias || acc.wxid || acc.openid || acc.id || '未知';
                console.log(`[yyb] 跳过微信小程序账号「${name}」：wmpf_session_id 为空/失效（hasSession=false），需重新登录该小程序号`);
                return false;
            }
            return true;
        });
    }

    // ---------- 小程序核心能力 ----------

    // 微信授权频率控制：两次取码之间的最小间隔(ms)，防止触发后端频率限制
    _lastCodeTime = 0;
    _codeMinInterval = parseInt(process.env.WX_CODE_INTERVAL || '3000', 10);

    async _throttleCode() {
        const now = Date.now();
        const wait = this._codeMinInterval - (now - this._lastCodeTime);
        if (wait > 0) {
            await new Promise(r => setTimeout(r, wait));
        }
        this._lastCodeTime = Date.now();
    }

    async getCode(ref, appId) {
        const resolvedRef = await this._resolveRef(ref);
        const maxRetry = parseInt(process.env.WX_CODE_RETRY || '2', 10);
        let lastErr = '';
        for (let attempt = 0; attempt < maxRetry; attempt++) {
            await this._throttleCode();
            try {
                const res = await this._requestWithFallback('POST', ['/api/yyb/get-code', '/wxapp/getCode', '/wx/code'], {
                    openid: resolvedRef,
                    appid: appId,
                });
                const code = res?.code || (res?.data && res.data.code) || (typeof res === 'string' ? res : null);
                if (!code) throw new Error(`未拿到有效小程序 code: ${JSON.stringify(res)}`);
                return String(code);
            } catch (e) {
                const msg = e.message || String(e);
                lastErr = msg;
                // 命中频率限制时，退避重试
                if (/frequency|limit|slowdown|频率|频繁|太频繁/i.test(msg)) {
                    const backoff = 2000 * (attempt + 1);
                    console.log(`[yyb] 命中微信授权频率限制，${backoff / 1000}s 后重试 (${attempt + 1}/${maxRetry})`);
                    await new Promise(r => setTimeout(r, backoff));
                    continue;
                }
                throw e;
            }
        }
        throw new Error(`获取 code 失败(重试${maxRetry}次): ${lastErr}`);
    }

    async getCodes(refs, appId) {
        const resolvedRefs = await Promise.all(refs.map(r => this._resolveRef(r)));
        return await this._requestWithFallback('POST', ['/api/yyb/get-codes', '/wxapp/getCodes'], {
            accounts: resolvedRefs,
            appid: appId,
        });
    }

    async getPhoneNumber(ref, appId) {
        const resolvedRef = await this._resolveRef(ref);
        const res = await this._requestWithFallback('POST', ['/api/yyb/get-phone', '/wxapp/getPhoneNumber'], {
            openid: resolvedRef,
            appid: appId,
        });
        const inner = res?.data || res || {};
        // 部分服务端把 encryptedData/iv 放在 raw 字段里，需兼容提取
        const raw = (inner && typeof inner.raw === 'object' && inner.raw) || (res && typeof res.raw === 'object' && res.raw) || {};
        return {
            code: inner.code ? String(inner.code) : null,
            mobile: inner.mobile || null,
            masked_phone: inner.masked_phone || null,
            encryptedData: inner.encryptedData || inner.encrypted_data || raw.encryptedData || raw.encrypted_data || null,
            iv: inner.iv || inner.IV || raw.iv || raw.IV || null,
            cloudId: inner.cloudId || null,
        };
    }

    async getPhoneEncrypted(ref, appId) {
        return await this.getPhoneNumber(ref, appId);
    }

    async operateWxData(ref, appId, payload) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._requestWithFallback('POST', ['/api/yyb/invoke-cloud', '/wxapp/operateWxData'], {
            openid: resolvedRef,
            appid: appId,
            param2: JSON.stringify(payload || {}),
        });
    }

    async getUserInfo(ref, appId, lang = 'zh_CN') {
        const resolvedRef = await this._resolveRef(ref);
        return await this._requestWithFallback('POST', ['/api/yyb/get-userinfo', '/wxapp/getUserInfo'], {
            openid: resolvedRef,
            appid: appId,
            lang,
        });
    }

    async getUserEncryptKey(ref, appId) {
        return await this.operateWxData(ref, appId, { api_name: 'webapi_getuserencryptkey' });
    }

    async getWeRunData(ref, appId) {
        return await this.operateWxData(ref, appId, { api_name: 'webapi_getwerundata' });
    }

    async getSetting(ref, appId) {
        return await this.operateWxData(ref, appId, { api_name: 'webapi_getsetting' });
    }

    async getSystemInfo(ref, appId) {
        return await this.operateWxData(ref, appId, { api_name: 'webapi_getsysteminfo' });
    }

    async getLocation(ref, appId, type = 'wgs84') {
        return await this.operateWxData(ref, appId, { api_name: 'webapi_getlocation', type });
    }

    // ---------- 云开发与云托管 ----------

    async cloudCallFunction(ref, appId, env, name, data = {}) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._requestWithFallback('POST', ['/api/yyb/cloud-call-function', '/wxapp/cloud/function'], {
            openid: resolvedRef,
            appid: appId,
            cloudEnv: env,
            functionName: name,
            functionData: data,
        });
    }

    async cloudCallContainer(ref, appId, env, path, service, header = {}, body = null) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._requestWithFallback('POST', ['/api/yyb/cloud-call-container', '/wxapp/cloud/container'], {
            openid: resolvedRef,
            appid: appId,
            cloudHost: service,
            path: path,
            headers: header,
            data: body || '',
        });
    }

    // ---------- 微信公众号网页授权 (OAuth2) ----------

    async oauthAuthorize(ref, appId, redirectUri, scope = 'snsapi_userinfo', state = '') {
        const resolvedRef = await this._resolveRef(ref);
        return await this._requestWithFallback('POST', ['/api/yyb/oauth-authorize', '/wxapp/oauth/authorize'], {
            openid: resolvedRef,
            appid: appId,
            url: redirectUri,
            scope,
            state,
        });
    }

    async oauthConfirm(ref, appId, oauthUrl) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._requestWithFallback('POST', ['/api/yyb/oauth-authorize-confirm', '/wxapp/oauth/confirm'], {
            openid: resolvedRef,
            appid: appId,
            oauth_url: oauthUrl,
        });
    }

    // ---------- 云托管 GatewayV3 加密接口 ----------

    async gatewayV3Mint(ref, appId, env) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._requestWithFallback('POST', ['/api/yyb/cloud-call-container', '/wxapp/cloud/container'], {
            openid: resolvedRef,
            appid: appId,
            cloudHost: env,
            path: '/gateway/v3/mint',
        });
    }

    async gatewayV3Call(ref, appId, env, path, service, header = {}, body = null) {
        return await this.cloudCallContainer(ref, appId, env, path, service, header, body);
    }
}

// 别名兼容
const WeChatCodeGetter = YYBClient;
const YYBAdapter = YYBClient;
const WechatAdapter = YYBClient;

// ============================================================
// 4. 便捷导出函数 (直接 1 行调用)
// ============================================================

async function loadAccounts(filterEnvName = null) {
    const client = new YYBClient();
    let onlineAccounts = [];
    try {
        onlineAccounts = await client.getOnlineAccounts();
    } catch (e) {
        console.log(`[yyb] 从 yyb-main 获取账号列表异常: ${e.message || e}`);
        onlineAccounts = [];
    }

    const customFilter = (filterEnvName ? process.env[filterEnvName] : null) || process.env.WX_ID;
    if (!customFilter || !customFilter.trim()) {
        return onlineAccounts;
    }

    const filterTargets = customFilter
        .split(/[@&\n|]+/)
        .map(s => parseIdentifier(s))
        .filter(t => t.rawId);

    const matched = [];
    for (const acc of onlineAccounts) {
        const accKeys = [String(acc.id || ''), acc.openid || '', acc.wxid || '', acc._ref || ''];
        const accLt = normalizeLoginType(acc.login_type);
        for (const t of filterTargets) {
            if (accKeys.includes(t.rawId)) {
                if (t.loginType && accLt !== t.loginType) continue;
                matched.push({ ...acc, remark: t.remark || acc.nickname || '' });
                break;
            }
        }
    }
    if (matched.length === 0 && onlineAccounts.length > 0) {
        // WX_ID 一条都匹配不上：回退为全部在线账号（避免"配 N 条只跑 N 个"）
        console.log(`[yyb] WX_ID 配置了 ${filterTargets.length} 条但均未匹配到账号，回退使用全部 ${onlineAccounts.length} 个存活账号`);
        return onlineAccounts;
    }
    return matched;
}

async function getAccounts() {
    return await loadAccounts();
}

async function resolveAccounts(envName) {
    // 优先拉取全部存活账号（不因配置了 WX_ID 就只用配置条目）
    let online = [];
    try {
        online = await new YYBClient().getOnlineAccounts();
    } catch (e) {
        console.log(`[yyb] 拉取存活账号失败: ${e.message || e}`);
    }

    const ids = online.map(a => String(a.openid || a.wxid || a._ref || a.id || '')).filter(Boolean);

    const val = process.env.WX_ID || (envName ? process.env[envName] : '') || '';
    if (val && val.trim() && ids.length) {
        // WX_ID 作为筛选：逐条匹配在线账号（openid/wxid/id/备注/昵称）
        const targets = String(val)
            .split(/[\n&@]+/)
            .map(v => String(v).split('#')[0].trim().toLowerCase())
            .filter(Boolean);
        const matched = [];
        for (const t of targets) {
            const idx = online.findIndex(acc => {
                const keys = [String(acc.id || ''), acc.openid, acc.wxid, acc._ref, acc.alias, acc.remark, acc.nickname]
                    .map(k => String(k || '').trim().toLowerCase())
                    .filter(Boolean);
                return keys.includes(t);
            });
            if (idx >= 0 && !matched.includes(ids[idx])) matched.push(ids[idx]);
        }
        if (matched.length === targets.length && matched.length > 0) {
            // 全部匹配：按 WX_ID 精确筛选
            console.log(`[yyb] WX_ID ${targets.length} 条全部匹配，按筛选执行`);
            return matched;
        }
        // 任何一条匹配不上：使用全部存活账号（避免"配 N 条只跑 N 个"）
        console.log(`[yyb] WX_ID ${matched.length}/${targets.length} 条匹配到账号，回退使用全部存活账号`);
    }

    if (ids.length) {
        console.log(`[yyb] 自动从 yyb_go 同步到 ${ids.length} 个存活账号`);
        return ids;
    }

    // yyb 服务不可用：回退 WX_ID 原始条目
    if (val && val.trim()) {
        return val.split(/[\n&]+/).map(v => String(v).split('#')[0].trim()).filter(Boolean);
    }
    console.log('[yyb] 未配置 WX_ID，且 yyb-main 无存活账号');
    return [];
}

async function printOnlineStatus() {
    const client = new YYBClient();
    try {
        const all = await client.getAccounts(true);
        const accounts = await client.getOnlineAccounts();
        console.log(`\n[yyb-main] 当前有 ${accounts.length} 个账号在线 (@ ${client.serverUrl}):`);
        accounts.forEach((acc, idx) => {
            const name = acc.nickname || acc.alias || acc.wxid || `账号_${idx + 1}`;
            const lt = loginTypeLabel(acc.login_type);
            console.log(`  - [${lt}] ${name} (id=${acc.id}, openid=${acc.openid || '无'})`);
        });
        const skipped = all.filter(acc =>
            Number(acc.loginSource || acc.login_source) === 3 && acc.hasSession === false
        );
        if (skipped.length) {
            console.log(`[yyb-main] 另有 ${skipped.length} 个微信小程序账号因 wmpf_session_id 为空/失效被跳过（需重新登录）:`);
            skipped.forEach((acc, idx) => {
                const name = acc.nickname || acc.alias || acc.wxid || `账号_${idx + 1}`;
                console.log(`  - [小程序] ${name} (openid=${acc.openid || '无'})`);
            });
        }
    } catch (e) {
        console.log(`[yyb-main] 获取账号状态失败: ${e.message || e}`);
    }
}

async function getWechatCodes(appId) {
    const client = new YYBClient();
    const accounts = await loadAccounts();
    const result = {};
    for (let i = 0; i < accounts.length; i++) {
        const acc = accounts[i];
        const name = acc.remark || acc.nickname || acc.alias || `账号_${i + 1}`;
        const ref = String(acc.id || acc.openid || acc.wxid);
        try {
            const code = await client.getCode(ref, appId);
            result[name] = code;
            console.log(`[yyb] ✓ ${name}: ${code.slice(0, 16)}...`);
        } catch (e) {
            console.log(`[yyb] ✗ ${name}: ${e.message || e}`);
        }
    }
    return result;
}

async function getSingleCode(appId, identifier) {
    if (!identifier) return null;
    const client = new YYBClient();
    try {
        return await client.getCode(identifier, appId);
    } catch (e) {
        console.log(`[yyb] 获取 code 失败 (${identifier}): ${e.message || e}`);
        return null;
    }
}

async function getSinglePhoneNumber(appId, identifier) {
    if (!identifier) return null;
    const client = new YYBClient();
    try {
        const res = await client.getPhoneNumber(identifier, appId);
        return res?.code || null;
    } catch (e) {
        console.log(`[yyb] 获取手机号 code 失败 (${identifier}): ${e.message || e}`);
        return null;
    }
}

async function getSinglePhoneEncrypted(appId, identifier) {
    if (!identifier) return null;
    const client = new YYBClient();
    try {
        return await client.getPhoneNumber(identifier, appId);
    } catch (e) {
        console.log(`[yyb] 获取手机号加密数据失败 (${identifier}): ${e.message || e}`);
        return null;
    }
}

async function getSingleOperateWxData(appId, identifier, payload = null) {
    if (!identifier) return null;
    const client = new YYBClient();
    try {
        return await client.operateWxData(identifier, appId, payload || { api_name: 'webapi_getuserencryptkey' });
    } catch (e) {
        console.log(`[yyb] 获取 operate 数据失败 (${identifier}): ${e.message || e}`);
        return null;
    }
}

async function getSingleUserEncryptKey(appId, identifier) {
    return await getSingleOperateWxData(appId, identifier, { api_name: 'webapi_getuserencryptkey' });
}

async function getSingleUserInfo(appId, identifier) {
    if (!identifier) return null;
    const client = new YYBClient();
    try {
        return await client.getUserInfo(identifier, appId);
    } catch (e) {
        console.log(`[yyb] 获取用户信息失败 (${identifier}): ${e.message || e}`);
        return null;
    }
}

async function getSingleWeRunData(appId, identifier) {
    if (!identifier) return null;
    const client = new YYBClient();
    try {
        return await client.getWeRunData(identifier, appId);
    } catch (e) {
        console.log(`[yyb] 获取微信步数失败 (${identifier}): ${e.message || e}`);
        return null;
    }
}

async function getSingleCloudFunction(appId, identifier, env, name, data = {}) {
    if (!identifier) return null;
    const client = new YYBClient();
    try {
        return await client.cloudCallFunction(identifier, appId, env, name, data);
    } catch (e) {
        console.log(`[yyb] 调用云函数失败 (${name}): ${e.message || e}`);
        return null;
    }
}

async function getSingleOAuthAuthorize(appId, identifier, redirectUri, scope = 'snsapi_userinfo', state = '') {
    if (!identifier) return null;
    const client = new YYBClient();
    try {
        return await client.oauthAuthorize(identifier, appId, redirectUri, scope, state);
    } catch (e) {
        console.log(`[yyb] 公众号网页授权失败: ${e.message || e}`);
        return null;
    }
}

// ============================================================
// 通用 token 缓存工具（供各脚本复用，避免每次运行都重新取 code）
// 说明：微信 wx.login 的 code 是一次性的，不能缓存；但登录后换取的
// 业务 token 在有效期内可复用，从而大幅减少取 code 频率、规避限流。
// 用法：
//   const { readTokenCache, writeTokenCache } = require('./yyb.js');
//   const cache = readTokenCache('myapp');            // 读整个缓存文件
//   const t = cache[openid];                          // 取某账号的 token
//   cache[openid] = { token, updatedAt: Date.now() };
//   writeTokenCache('myapp', cache);                 // 写回
// ============================================================
const TOKEN_CACHE_DIR = path.join(__dirname, 'token_caches');

function _tokenCachePath(name) {
    const safe = String(name || 'default').replace(/[^a-zA-Z0-9_-]/g, '_');
    return path.join(TOKEN_CACHE_DIR, `${safe}.json`);
}

function readTokenCache(name) {
    try {
        const p = _tokenCachePath(name);
        if (!fs.existsSync(p)) return {};
        return JSON.parse(fs.readFileSync(p, 'utf8')) || {};
    } catch (e) {
        return {};
    }
}

function writeTokenCache(name, cache) {
    try {
        fs.mkdirSync(TOKEN_CACHE_DIR, { recursive: true });
        fs.writeFileSync(_tokenCachePath(name), JSON.stringify(cache, null, 2), 'utf8');
    } catch (e) {
        console.log(`[yyb] 写入token缓存失败: ${e.message || e}`);
    }
}

// 通用 token 缓存辅助：读取某账号缓存的 token，并判断是否仍有效。
// 支持两种有效期判断：
//   1) JWT：token 含 exp 字段，直接按 exp 判断（可提前 expireLeadSec 秒失效）
//   2) 非 JWT：按缓存时长 maxAgeMs 兜底（默认 6 小时）
// 返回 { token, updatedAt } 或 null（无缓存/已过期）。
function getCachedToken(cacheName, openid, opts = {}) {
    const { expireLeadSec = 60, maxAgeMs = 6 * 3600 * 1000 } = opts;
    const cache = readTokenCache(cacheName);
    const item = cache[openid];
    if (!item || !item.token) return null;
    const now = Date.now();
    // JWT 判断
    const parts = String(item.token).split('.');
    if (parts.length >= 2) {
        try {
            const payload = JSON.parse(Buffer.from(parts[1], 'base64').toString('utf8'));
            const exp = Number(payload.exp || 0);
            if (exp && exp * 1000 - expireLeadSec * 1000 > now) {
                return { token: item.token, updatedAt: item.updatedAt || now };
            }
            return null; // JWT 已过期
        } catch (e) { /* 非标准 JWT，走时间兜底 */ }
    }
    // 时间兜底
    const updatedAt = Number(item.updatedAt || 0);
    if (updatedAt && now - updatedAt < maxAgeMs) {
        return { token: item.token, updatedAt };
    }
    return null;
}

// 通用 token 缓存辅助：保存某账号的 token 到缓存
function saveCachedToken(cacheName, openid, token) {
    const cache = readTokenCache(cacheName);
    cache[openid] = { token, updatedAt: Date.now() };
    writeTokenCache(cacheName, cache);
}

// 挂载到全局 global
global.readTokenCache = readTokenCache;
global.writeTokenCache = writeTokenCache;
global.getCachedToken = getCachedToken;
global.saveCachedToken = saveCachedToken;
global.YYBClient = YYBClient;
global.WeChatCodeGetter = WeChatCodeGetter;
global.YYBAdapter = YYBAdapter;
global.WechatAdapter = WechatAdapter;
global.getSingleCode = getSingleCode;
global.getSinglePhoneNumber = getSinglePhoneNumber;
global.getSinglePhoneEncrypted = getSinglePhoneEncrypted;
global.getSingleOperateWxData = getSingleOperateWxData;
global.getSingleUserEncryptKey = getSingleUserEncryptKey;
global.getSingleUserInfo = getSingleUserInfo;
global.getSingleWeRunData = getSingleWeRunData;
global.getSingleCloudFunction = getSingleCloudFunction;
global.getSingleOAuthAuthorize = getSingleOAuthAuthorize;
global.loadAccounts = loadAccounts;
global.resolveAccounts = resolveAccounts;
global.getAccounts = getAccounts;
global.getWechatCodes = getWechatCodes;
global.printOnlineStatus = printOnlineStatus;
global.parseIdentifier = parseIdentifier;
global.stripScheme = stripScheme;
global.normalizeLoginType = normalizeLoginType;
global.loginTypeLabel = loginTypeLabel;

module.exports = {
    YYBClient,
    WeChatCodeGetter,
    YYBAdapter,
    WechatAdapter,
    getGlobalServerUrl,
    parseIdentifier,
    stripScheme,
    normalizeLoginType,
    loginTypeLabel,
    loadAccounts,
    resolveAccounts,
    getAccounts,
    getWechatCodes,
    printOnlineStatus,
    getSingleCode,
    getSinglePhoneNumber,
    getSinglePhoneEncrypted,
    getSingleOperateWxData,
    getSingleUserEncryptKey,
    getSingleUserInfo,
    getSingleWeRunData,
    getSingleCloudFunction,
    getSingleOAuthAuthorize,
    readTokenCache,
    writeTokenCache,
    getCachedToken,
    saveCachedToken,
    LOGIN_TYPE_WX,
    LOGIN_TYPE_SYZS,
    LOGIN_TYPE_WMPF,
};
