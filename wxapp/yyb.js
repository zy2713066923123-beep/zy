// name: YYB-Go 微信全能力通用工具库 (Node.js SDK) —— 统一入口
/**
 * yyb-go 微信协议通用工具库 (Node.js) —— 统一入口
 *
 * 这是 wxapp 下所有脚本统一引用的唯一工具库。完整封装 yyb-go 服务端提供的
 * 所有微信小程序/公众号/云托管能力：
 *   1. 账号管理: 存活账号发现、WX_ID 筛选、状态检测
 *   2. 小程序核心: wx.login 取码、手机号授权(code/encryptedData/iv/mobile)、用户信息(getUserInfo)
 *   3. 加密与安全: 用户加密密钥(webapi_getuserencryptkey)、数据签名、微信步数(getWeRunData)
 *   4. 云开发与托管: 云函数(cloudCallFunction)、云托管容器(cloudCallContainer)
 *   5. 公众号网页授权: OAuth2 授权码换取(oauthAuthorize/oauthConfirm)
 *   6. 云托管 GatewayV3: Gateway 鉴权与微服务调用(gatewayV3Mint/gatewayV3Call)
 *
 * 使用方式（所有脚本统一引用本文件即可）：
 *   const yyb = require('./yyb.js');
 *   const code = await yyb.getSingleCode(APPID, wxid);
 *
 * 环境变量配置（只需一个 WX_SERVER 即可）：
 *   WX_SERVER: yyb-go 服务端地址（默认 http://127.0.0.1:8000），兼容 YYB_SERVER / WECHAT_SERVER
 *   WX_ID:     可选，账号过滤白名单（支持 id / openid / wxid，多个用换行或 & 分隔，支持 #备注）
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

    async _request(method, endpoint, data = null, params = null) {
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
                const errMsg = resp.data?.msg || resp.data?.error || `404 资源或接口不存在`;
                throw new Error(`[404] ${errMsg}`);
            }
            if (resp.status === 401 || resp.status === 409) {
                throw new Error(`账号登录态已过期，请在 yyb_go 中重新扫码`);
            }

            const body = resp.data;
            if (body && typeof body === 'object') {
                if (body.code !== undefined && body.code !== 0) {
                    throw new Error(`[${body.code}] ${body.msg || JSON.stringify(body)}`);
                }
                return body.data !== undefined ? body.data : body;
            }
            return body;
        } catch (e) {
            throw new Error(`[YYB-SDK] 请求 ${endpoint} 失败: ${e.message || e}`);
        }
    }

    async _resolveRef(ref, expectLoginType = null) {
        const parsed = parseIdentifier(ref);
        const raw = parsed.rawId;
        const targetLt = parsed.loginType || (expectLoginType ? normalizeLoginType(expectLoginType) : null);

        // 如果是纯数字 ID，直接使用
        if (/^\d+$/.test(raw)) return raw;

        const accounts = await this.getAccounts();
        if (!accounts || accounts.length === 0) {
            return raw;
        }

        // 精确匹配 openid / wxid
        for (const acc of accounts) {
            const accLt = normalizeLoginType(acc.login_type);
            if (targetLt && accLt !== targetLt) continue;
            if (acc.openid === raw || acc.wxid === raw || String(acc.id) === raw) {
                return String(acc.id);
            }
        }

        // 若只有一个账号，默认使用它
        if (accounts.length === 1 && (!targetLt || normalizeLoginType(accounts[0].login_type) === targetLt)) {
            return String(accounts[0].id);
        }

        return raw;
    }

    // ---------- 账号管理 ----------

    async getAccounts(forceRefresh = false) {
        const now = Date.now();
        if (!forceRefresh && this._cachedAccounts && now - this._cacheTime < 5000) {
            return this._cachedAccounts;
        }
        const data = await this._request('GET', '/accounts');
        const list = Array.isArray(data) ? data : (data?.data || []);
        this._cachedAccounts = list;
        this._cacheTime = now;
        return list;
    }

    async getOnlineAccounts() {
        const accounts = await this.getAccounts(true);
        // 黑名单：仅排除明确离线/失效的账号；其余（含空值、非标准值）均视为可用，避免误杀
        const OFFLINE = new Set(['offline', 'expired', 'invalid', 'disabled', 'error', 'dead', 'logout']);
        return accounts.filter(acc => {
            const st = (acc.status || '').toLowerCase();
            return !OFFLINE.has(st);
        });
    }

    // ---------- 小程序核心能力 ----------

    /**
     * 获取微信小程序登录 Code (wx.login)
     */
    async getCode(ref, appId) {
        const resolvedRef = await this._resolveRef(ref);
        const res = await this._request('POST', '/wxapp/getCode', {
            ref: resolvedRef,
            app_id: appId,
        });
        const code = res?.code || (res?.result && res.result.code) || (typeof res === 'string' ? res : null);
        if (!code) throw new Error(`未拿到有效小程序 code: ${JSON.stringify(res)}`);
        return String(code);
    }

    /**
     * 批量获取微信小程序 Code
     */
    async getCodes(refs, appId) {
        const resolvedRefs = await Promise.all(refs.map(r => this._resolveRef(r)));
        return await this._request('POST', '/wxapp/getCodes', {
            refs: resolvedRefs,
            app_id: appId,
        });
    }

    /**
     * 获取手机号授权数据 (getPhoneNumber)
     * 返回 { code, mobile, masked_phone, encryptedData, iv, cloudId }
     */
    async getPhoneNumber(ref, appId) {
        const resolvedRef = await this._resolveRef(ref);
        const res = await this._request('POST', '/wxapp/getPhoneNumber', {
            ref: resolvedRef,
            app_id: appId,
        });
        const inner = res?.result || res || {};
        return {
            code: inner.code ? String(inner.code) : null,
            mobile: inner.mobile || null,
            masked_phone: inner.masked_phone || null,
            encryptedData: inner.encryptedData || inner.encrypted_data || null,
            iv: inner.iv || inner.IV || null,
            cloudId: inner.cloudId || null,
        };
    }

    /**
     * 获取手机号加密数据包 (兼容别名)
     */
    async getPhoneEncrypted(ref, appId) {
        return await this.getPhoneNumber(ref, appId);
    }

    /**
     * 通用 operateWxData 调用（支持任意插件、基础库交互、用户信息）
     */
    async operateWxData(ref, appId, payload) {
        const resolvedRef = await this._resolveRef(ref);
        const res = await this._request('POST', '/wxapp/operateWxData', {
            ref: resolvedRef,
            app_id: appId,
            payload: payload || {},
        });
        return res?.result !== undefined ? res.result : res;
    }

    /**
     * 获取用户信息 (getUserInfo)
     */
    async getUserInfo(ref, appId, lang = 'zh_CN') {
        const resolvedRef = await this._resolveRef(ref);
        return await this._request('POST', '/wxapp/getUserInfo', {
            ref: resolvedRef,
            app_id: appId,
            lang,
        });
    }

    /**
     * 获取用户加密密钥 (webapi_getuserencryptkey)
     */
    async getUserEncryptKey(ref, appId) {
        return await this.operateWxData(ref, appId, { api_name: 'webapi_getuserencryptkey' });
    }

    /**
     * 获取微信运动步数数据 (getWeRunData)
     */
    async getWeRunData(ref, appId) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._request('POST', '/wxapp/getWeRunData', {
            ref: resolvedRef,
            app_id: appId,
        });
    }

    /**
     * 获取小程序设置信息 (getSetting)
     */
    async getSetting(ref, appId) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._request('POST', '/wxapp/getSetting', {
            ref: resolvedRef,
            app_id: appId,
        });
    }

    /**
     * 获取系统设备信息 (getSystemInfo)
     */
    async getSystemInfo(ref, appId) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._request('POST', '/wxapp/getSystemInfo', {
            ref: resolvedRef,
            app_id: appId,
        });
    }

    /**
     * 获取地理位置 (getLocation)
     */
    async getLocation(ref, appId, type = 'wgs84') {
        const resolvedRef = await this._resolveRef(ref);
        return await this._request('POST', '/wxapp/getLocation', {
            ref: resolvedRef,
            app_id: appId,
            type,
        });
    }

    // ---------- 云开发与云托管 ----------

    /**
     * 调用小程序云函数 (cloud.callFunction)
     */
    async cloudCallFunction(ref, appId, env, name, data = {}) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._request('POST', '/wxapp/cloud/function', {
            ref: resolvedRef,
            app_id: appId,
            env,
            name,
            data,
        });
    }

    /**
     * 调用小程序云托管容器服务 (cloud.callContainer)
     */
    async cloudCallContainer(ref, appId, env, path, service, header = {}, body = null) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._request('POST', '/wxapp/cloud/container', {
            ref: resolvedRef,
            app_id: appId,
            env,
            path,
            service,
            header,
            body,
        });
    }

    // ---------- 微信公众号网页授权 (OAuth2) ----------

    /**
     * 公众号网页授权取 code
     */
    async oauthAuthorize(ref, appId, redirectUri, scope = 'snsapi_userinfo', state = '') {
        const resolvedRef = await this._resolveRef(ref);
        return await this._request('POST', '/wxapp/oauth/authorize', {
            ref: resolvedRef,
            app_id: appId,
            redirect_uri: redirectUri,
            scope,
            state,
        });
    }

    /**
     * 确认公众号网页授权并提取重定向 URL
     */
    async oauthConfirm(ref, appId, oauthUrl) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._request('POST', '/wxapp/oauth/confirm', {
            ref: resolvedRef,
            app_id: appId,
            oauth_url: oauthUrl,
        });
    }

    // ---------- 云托管 GatewayV3 加密接口 ----------

    /**
     * 生成 GatewayV3 鉴权 Token
     */
    async gatewayV3Mint(ref, appId, env) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._request('POST', '/wxapp/gateway/v3/mint', {
            ref: resolvedRef,
            app_id: appId,
            env,
        });
    }

    /**
     * 调用 GatewayV3 加密微服务接口
     */
    async gatewayV3Call(ref, appId, env, path, service, header = {}, body = null) {
        const resolvedRef = await this._resolveRef(ref);
        return await this._request('POST', '/wxapp/gateway/v3/call', {
            ref: resolvedRef,
            app_id: appId,
            env,
            path,
            service,
            header,
            body,
        });
    }
}

// 别名兼容
const WeChatCodeGetter = YYBClient;
const YYBAdapter = YYBClient;
const WechatAdapter = YYBClient;

// ============================================================
// 4. 便捷导出函数 (直接 1 行调用)
// ============================================================

/**
 * 加载并过滤账号列表（支持从 yyb_go 服务端拉取存活账号，或按 WX_ID 过滤）
 */
async function loadAccounts(filterEnvName = null) {
    const client = new YYBClient();
    let onlineAccounts = [];
    try {
        onlineAccounts = await client.getOnlineAccounts();
    } catch (e) {
        console.log(`[yyb] 从 yyb_go 获取账号列表异常: ${e.message || e}`);
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
    return matched;
}

async function getAccounts() {
    return await loadAccounts();
}

/**
 * 统一账号解析入口（所有脚本统一调用）：
 * 1) 若配置了 WX_ID（或指定 env 变量），按原格式解析为 wxid 列表；
 * 2) 否则自动从 yyb_go 拉取存活账号，返回 wxid 列表（openid/wxid/id）。
 * 无论哪种方式，统一的“拿 code”入口都是 getSingleCode(appid, ref)。
 */
async function resolveAccounts(envName) {
    const val = process.env.WX_ID || (envName ? process.env[envName] : '') || '';
    if (val && val.trim()) {
        return val
            .split(/[\n&]+/)
            .map(v => String(v).split('#')[0].trim())
            .filter(Boolean);
    }
    try {
        const accs = await loadAccounts();
        if (accs && accs.length) {
            const ids = accs.map(a => String(a.openid || a.wxid || a.id)).filter(Boolean);
            console.log(`[yyb] 自动从 yyb_go 同步到 ${ids.length} 个存活账号`);
            return ids;
        }
    } catch (e) {
        console.log(`[yyb] 自动拉取账号失败: ${e.message || e}`);
    }
    console.log('[yyb] 未配置 WX_ID，且 yyb_go 无存活账号');
    return [];
}

/**
 * 打印当前在线账号状态
 */
async function printOnlineStatus() {
    const client = new YYBClient();
    try {
        const accounts = await client.getOnlineAccounts();
        console.log(`\n[yyb-go] 当前有 ${accounts.length} 个账号在线 (@ ${client.serverUrl}):`);
        accounts.forEach((acc, idx) => {
            const name = acc.nickname || acc.alias || acc.wxid || `账号_${idx + 1}`;
            const lt = loginTypeLabel(acc.login_type);
            console.log(`  - [${lt}] ${name} (id=${acc.id}, openid=${acc.openid || '无'})`);
        });
    } catch (e) {
        console.log(`[yyb-go] 获取账号状态失败: ${e.message || e}`);
    }
}

/**
 * 获取所有存活账号的 Code 字典
 */
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

/**
 * 获取单个账号的小程序 Code (wx.login)
 */
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

/**
 * 获取单个账号的手机号授权 Code
 */
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

/**
 * 获取单个账号的手机号加密数据包 (encryptedData, iv, code, mobile, cloudId)
 */
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

/**
 * 获取通用 operateWxData 数据（如 webapi_getuserencryptkey / 云函数 / 用户数据等）
 */
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

/**
 * 获取单个账号的加密密钥 (webapi_getuserencryptkey)
 */
async function getSingleUserEncryptKey(appId, identifier) {
    return await getSingleOperateWxData(appId, identifier, { api_name: 'webapi_getuserencryptkey' });
}

/**
 * 获取单个账号的用户信息 (getUserInfo)
 */
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

/**
 * 获取单个账号的微信步数加密数据 (getWeRunData)
 */
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

/**
 * 调用小程序云函数 (cloudCallFunction)
 */
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

/**
 * 调用公众号网页授权 (OAuth2)
 */
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
// 5. 全局挂载与模块导出
// ============================================================

// 挂载到全局 global，确保引入 require('./yyb.js') 后即可无感直接调用
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
    LOGIN_TYPE_WX,
    LOGIN_TYPE_SYZS,
    LOGIN_TYPE_WMPF,
};
