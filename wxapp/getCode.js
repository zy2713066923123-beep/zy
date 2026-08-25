// name: 微信Code获取模块
/**
 * 微信小程序登录Code获取模块（yyb_go 统一协议网关）
 *
 * 对接 yyb_go 服务，自动从服务端获取存活账号，并根据账号的 login_type 自适应走不同的底层协议：
 *   - WX   (应用宝 iLink/MMTLS): 支持全功能取码、手机号、云函数、运动步数，服务端自动续期
 *   - SYZS (手游助手 login_buffer): 支持标准小程序取码
 *   - WMPF (微信小程序 transfer): 支持标准小程序取码、手机号，失效时提示重扫
 *
 * 环境变量：
 *     WX_SERVER:     yyb_go 服务地址（推荐，默认 http://127.0.0.1:8000）
 *                    同时兼容 YYB_SERVER / WECHAT_SERVER / YINGYONGBAO_SERVER
 *     WX_ID:         可选，默认留空自动拉取 yyb_go 上所有存活账号。
 *                    若配置则作为白名单过滤（支持 id/openid，多个用 & 或换行分隔，支持 #备注）。
 */

const axios = require('axios');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

// ============================================================
//  服务地址解析（首选 WX_SERVER）
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

// ============================================================
//  YYB 登录模式（与 yyb_go internal/qr 的 LoginType 常量对齐）
// ============================================================
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

/** 把任意写法的登录模式归一化为 WX / SYZS / WMPF，未知值一律回退 WX */
function normalizeLoginType(value) {
    const key = String(value === undefined || value === null ? '' : value).trim().toLowerCase();
    return LOGIN_TYPE_ALIASES[key] || LOGIN_TYPE_WX;
}

/** 返回登录模式的中文展示名 */
function loginTypeLabel(value) {
    const lt = normalizeLoginType(value);
    return LOGIN_TYPE_LABELS[lt] || lt;
}

// ============================================================
//  账号标识解析与前缀语法
// ============================================================
const IDENTIFIER_SCHEMES = {
    'yyb': LOGIN_TYPE_WX,
    'wx': LOGIN_TYPE_WX,
    'syzs': LOGIN_TYPE_SYZS,
    'wmpf': LOGIN_TYPE_WMPF,
    'niuzi': null,
    'wxid': null,
    'wechat': null,
};

/**
 * 解析账号标识，拆出前缀(scheme)、真实ID与备注。
 * 支持 `scheme:id#备注`，也兼容无前缀的 `id#备注`。
 */
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

    const hashIdx = body.indexOf('#');
    const rawId = (hashIdx >= 0 ? body.slice(0, hashIdx) : body).trim();
    const note = hashIdx >= 0 ? body.slice(hashIdx + 1).trim() : '';

    return { original: text, scheme, loginType, rawId, note, idWithNote: body };
}

/** 去掉 scheme 前缀，保留 `id#备注` */
function stripScheme(identifier) {
    return parseIdentifier(identifier).idWithNote;
}

// ============================================================
//  启动阶段：自动从 yyb_go 拉取账号并同步至 process.env.WX_ID
// ============================================================
function bootstrapAccountsSync() {
    // 若用户显式配置了 WX_ID，则尊重用户配置（作为白名单/目标指定）
    if (process.env.WX_ID && process.env.WX_ID.trim()) {
        return;
    }

    const serverUrl = getGlobalServerUrl();
    if (!serverUrl) return;

    try {
        let stdout = '';
        // 优先尝试 curl（青龙 Linux Docker 和 Windows 10+ 均内置且极快）
        const curlRes = spawnSync('curl', ['-s', '--max-time', '3', `${serverUrl}/accounts`], {
            encoding: 'utf8',
            timeout: 4000,
        });

        if (curlRes.status === 0 && curlRes.stdout && curlRes.stdout.trim()) {
            stdout = curlRes.stdout.trim();
        } else {
            // 备用方案：通过 node 执行微脚本同步请求
            const nodeCode = `
                const http = require(${JSON.stringify(serverUrl)}.startsWith('https') ? 'https' : 'http');
                http.get(${JSON.stringify(serverUrl + '/accounts')}, { timeout: 3000 }, (res) => {
                    let d = '';
                    res.on('data', (c) => d += c);
                    res.on('end', () => process.stdout.write(d));
                }).on('error', () => {});
            `;
            const nodeRes = spawnSync(process.execPath, ['-e', nodeCode], {
                encoding: 'utf8',
                timeout: 4000,
            });
            if (nodeRes.status === 0 && nodeRes.stdout && nodeRes.stdout.trim()) {
                stdout = nodeRes.stdout.trim();
            }
        }

        if (!stdout) return;

        const res = JSON.parse(stdout);
        if (res && res.code === 0 && Array.isArray(res.data)) {
            // 过滤出未失效的存活账号
            const aliveAccounts = res.data.filter(acc => {
                const s = String(acc.status || '').toLowerCase();
                return ['alive', '', 'unknown'].includes(s);
            });

            if (aliveAccounts.length > 0) {
                const formatted = aliveAccounts.map(acc => {
                    const ident = acc.openid || String(acc.id);
                    const note = acc.nickname || acc.alias || `账号_${acc.id}`;
                    return `${ident}#${note}`;
                }).join('\n');

                process.env.WX_ID = formatted;
                console.log(`[getCode] 自动从 yyb_go (${serverUrl}) 同步到 ${aliveAccounts.length} 个存活账号:`);
                aliveAccounts.forEach(acc => {
                    const name = acc.nickname || acc.alias || '未知';
                    const lt = normalizeLoginType(acc.login_type);
                    console.log(`  - [${loginTypeLabel(lt)}] ${name} (id=${acc.id}, openid=${acc.openid})`);
                });
            } else {
                console.log(`[getCode] 提示: yyb_go (${serverUrl}) 当前无存活账号，请先在 yyb_go 扫码登录`);
            }
        }
    } catch (e) {
        // 静默捕获，不影响单账号手动调用的场景
    }
}

// 模块加载时执行同步拉取
bootstrapAccountsSync();

// ============================================================
//  YYB Server（yyb_go 网关）适配器
// ============================================================

class YYBAdapter {
    constructor(serverUrl) {
        this.serverUrl = (serverUrl || getGlobalServerUrl()).replace(/\/+$/, '');
        this._accountCache = null;
        this._accountCacheTime = 0;
    }

    async healthCheck() {
        try {
            const url = `${this.serverUrl}/health`;
            const r = await axios.get(url, { timeout: 5000 });
            if (r.status !== 200) return false;
            const d = r.data;
            return d?.code === 0 || d?.data?.ok === true || d?.ok === true;
        } catch (e) {
            console.log(`[YYB] 健康检查异常: ${e.message}`);
            return false;
        }
    }

    /**
     * 获取并缓存账号列表（5分钟缓存）
     */
    async _getAccountList() {
        const now = Date.now();
        if (this._accountCache && (now - this._accountCacheTime) < 5 * 60 * 1000) {
            return this._accountCache;
        }

        try {
            const r = await axios.get(`${this.serverUrl}/accounts`, { timeout: 15000 });
            if (r.data?.code !== 0 || !Array.isArray(r.data?.data)) {
                return [];
            }
            this._accountCache = r.data.data;
            this._accountCacheTime = now;
            return this._accountCache;
        } catch (e) {
            console.log(`[YYB] 获取账号列表失败: ${e.message}`);
            return [];
        }
    }

    /**
     * 根据 wxid/openid 查找 YYB 数据库中的账号记录
     */
    async _resolveAccount(wxidOrOpenid, expectLoginType = null) {
        if (wxidOrOpenid === undefined || wxidOrOpenid === null || wxidOrOpenid === '') {
            throw new Error('identifier 未提供（WX_ID 解析为空），请检查服务状态或调用参数');
        }

        const parsed = parseIdentifier(wxidOrOpenid);
        const rawId = parsed.rawId;
        const wantLoginType = expectLoginType || parsed.loginType;

        let accounts = await this._getAccountList();

        if (wantLoginType) {
            const label = loginTypeLabel(wantLoginType);
            const scoped = accounts.filter(a => normalizeLoginType(a.login_type) === wantLoginType);
            if (scoped.length > 0) {
                accounts = scoped;
            }
        }

        // 1. 精确匹配 openid
        for (const acc of accounts) {
            if (acc.openid === rawId) {
                return acc;
            }
        }

        // 2. 匹配 id / uin (数字)
        if (/^\d+$/.test(rawId)) {
            for (const acc of accounts) {
                if (String(acc.id) === rawId || String(acc.uin) === rawId) {
                    return acc;
                }
            }
        }

        // 3. 唯一前缀匹配
        if (rawId.length >= 8) {
            const prefixHits = accounts.filter(a => String(a.openid || '').startsWith(rawId));
            if (prefixHits.length === 1) {
                return prefixHits[0];
            }
        }

        // 4. 匹配昵称/备注
        if (parsed.note) {
            for (const acc of accounts) {
                if (acc.nickname === parsed.note || acc.alias === parsed.note) {
                    return acc;
                }
            }
        }

        // 5. 备注序号匹配 (e.g. #1, #2)
        if (/^\d+$/.test(parsed.note)) {
            const idx = parseInt(parsed.note, 10) - 1;
            if (idx >= 0 && idx < accounts.length) {
                return accounts[idx];
            }
        }

        // 6. 如果环境变量 WX_ID 中配置的是旧版 wxid_xxx（在 yyb_go 中不存在对应 openid）：
        // 自动按配置项顺序匹配到 yyb_go 中的存活账号
        const wxIdEnv = (process.env.WX_ID || "").trim();
        if (wxIdEnv) {
            const rawEntries = wxIdEnv.split(/[@&\n\r|]+/).map(x => parseIdentifier(x).rawId).filter(Boolean);
            const idx = rawEntries.indexOf(rawId);
            if (idx >= 0 && idx < accounts.length) {
                const mapped = accounts[idx];
                console.log(`[getCode] 智能映射: 旧版标识 [${rawId}] 自动匹配 yyb_go 账号 [${idx + 1}: ${mapped.nickname || mapped.id}]`);
                return mapped;
            }
        }

        // 7. 唯一可用账号
        if (accounts.length === 1) {
            return accounts[0];
        }

        if (accounts.length > 0) {
            return accounts[0];
        }

        return null;
    }

    async _resolveRef(wxidOrOpenid, expectLoginType = null) {
        const parsed = parseIdentifier(wxidOrOpenid);
        const acc = await this._resolveAccount(wxidOrOpenid, expectLoginType);
        const fallback = parsed.rawId || String(wxidOrOpenid);
        if (!acc) return fallback;
        if (acc.id !== undefined && acc.id !== null) {
            return String(acc.id);
        }
        if (acc.openid) {
            return String(acc.openid);
        }
        return fallback;
    }

    async getAccounts() {
        try {
            const r = await axios.get(`${this.serverUrl}/accounts`, { timeout: 15000 });
            if (r.data?.code !== 0) {
                throw new Error(r.data?.msg || '获取账号失败');
            }

            const list = r.data?.data;
            if (!Array.isArray(list)) {
                throw new Error(`返回格式错误: ${typeof list}`);
            }

            return list
                .filter(acc => {
                    const s = String(acc.status || '').toLowerCase();
                    return ['alive', '', 'unknown'].includes(s);
                })
                .map(acc => ({
                    id: acc.id,
                    wxid: acc.openid || '',
                    openid: acc.openid || '',
                    uin: acc.uin,
                    nickname: acc.nickname,
                    alias: acc.alias,
                    avatar: acc.avatar,
                    status: 1,
                    loginState: 1,
                    login_type: normalizeLoginType(acc.login_type),
                    _ref: String(acc.id || '') || acc.openid || '',
                }));
        } catch (e) {
            throw new Error(`[YYB] 获取账号列表失败: ${e.message}`);
        }
    }

    /**
     * 获取小程序登录 code（对应 yyb_go 的 POST /wxapp/getCode）
     */
    async getCode(ref, appId, expectLoginType = null) {
        const url = `${this.serverUrl}/wxapp/getCode`;
        const resolvedRef = await this._resolveRef(ref, expectLoginType);

        try {
            console.log(`[YYB] 请求code: ref=${resolvedRef}, app_id=${appId}`);
            const r = await axios.post(url, { ref: resolvedRef, app_id: appId }, {
                headers: { 'Content-Type': 'application/json' },
                timeout: 30000,
                validateStatus: () => true
            });

            if (r.status === 404) {
                const errMsg = r.data?.msg || r.data?.error || JSON.stringify(r.data).slice(0, 80);
                throw new Error(`接口/账号不存在(404): ${errMsg}`);
            }

            if (r.status === 400) {
                throw new Error(`参数错误 - 可能账号不存在: ${JSON.stringify(r.data).slice(0, 100)}`);
            }

            if (r.status === 409) {
                throw new Error('账号登录态已过期，需在 yyb_go 重新扫码登录');
            }

            const result = r.data;
            const codeVal = result?.code ?? -1;
            if (codeVal !== 0) {
                throw new Error(`[${codeVal}] ${result?.msg || `HTTP ${r.status}`}`);
            }

            const data = result?.data;
            if (data?.result?.code) {
                return data.result.code;
            }
            if (data?.result?.login_buffer) {
                return data.result.login_buffer;
            }
            if (data?.code && typeof data.code === 'string') {
                return data.code;
            }
            if (data?.login_buffer && typeof data.login_buffer === 'string') {
                return data.login_buffer;
            }

            throw new Error(`未拿到有效code: ${JSON.stringify(result).slice(0, 150)}`);
        } catch (e) {
            const msg = (e && e.message) ? e.message : String(e);
            if (msg.includes('[YYB]') || msg.includes('登录态')) throw e;
            throw new Error(`[YYB] 请求code失败: ${msg}`);
        }
    }

    /**
     * 获取手机号 code（对应 yyb_go 的 POST /wxapp/getPhoneNumber）
     */
    async getPhoneNumber(ref, appId, expectLoginType = null) {
        const url = `${this.serverUrl}/wxapp/getPhoneNumber`;
        const resolvedRef = await this._resolveRef(ref, expectLoginType);

        try {
            console.log(`[YYB] 请求手机号code: ref=${resolvedRef}, app_id=${appId}`);
            const r = await axios.post(url, { ref: resolvedRef, app_id: appId }, {
                headers: { 'Content-Type': 'application/json' },
                timeout: 30000,
                validateStatus: () => true
            });

            if (r.status === 404) {
                const errMsg = r.data?.msg || r.data?.error || JSON.stringify(r.data).slice(0, 80);
                throw new Error(`接口/账号不存在(404): ${errMsg}`);
            }

            if (r.status === 409) {
                throw new Error('账号登录态已过期，需在 yyb_go 重新扫码登录');
            }

            const result = r.data;
            const codeVal = result?.code ?? -1;
            if (codeVal !== 0) {
                throw new Error(`[${codeVal}] ${result?.msg || `HTTP ${r.status}`}`);
            }

            const data = result?.data;
            const inner = data?.result || data;
            const code = inner?.code;
            if (!code || typeof code !== 'string' || code.length < 5) {
                throw new Error(`未拿到有效手机号code: ${JSON.stringify(result).slice(0, 150)}`);
            }
            return code;
        } catch (e) {
            const msg = (e && e.message) ? e.message : String(e);
            if (msg.includes('[YYB]') || msg.includes('登录态')) throw e;
            throw new Error(`[YYB] 请求手机号code失败: ${msg}`);
        }
    }

    /**
     * 获取手机号加密数据（encryptedData/iv）
     */
    async getPhoneEncrypted(ref, appId, expectLoginType = null) {
        const url = `${this.serverUrl}/wxapp/getPhoneNumber`;
        const resolvedRef = await this._resolveRef(ref, expectLoginType);
        try {
            console.log(`[YYB] 请求手机号加密数据: ref=${resolvedRef}, app_id=${appId}`);
            const r = await axios.post(url, { ref: resolvedRef, app_id: appId }, {
                headers: { 'Content-Type': 'application/json' },
                timeout: 30000,
                validateStatus: () => true
            });
            if (r.status === 404) {
                const errMsg = r.data?.msg || r.data?.error || JSON.stringify(r.data).slice(0, 80);
                throw new Error(`接口/账号不存在(404): ${errMsg}`);
            }
            if (r.status === 409) {
                throw new Error('账号登录态已过期，需在 yyb_go 重新扫码登录');
            }
            const result = r.data;
            const codeVal = result?.code ?? -1;
            if (codeVal !== 0) {
                throw new Error(`[${codeVal}] ${result?.msg || `HTTP ${r.status}`}`);
            }
            const data = result?.data;
            const inner = data?.result ?? data;
            const encryptedData = inner?.encryptedData ?? inner?.encrypted_data;
            const iv = inner?.iv ?? inner?.IV;
            if (!encryptedData || !iv) {
                if (inner?.code) {
                    return { encryptedData: null, iv: null, code: String(inner.code) };
                }
                throw new Error(`未拿到 encryptedData/iv: ${JSON.stringify(result).slice(0, 150)}`);
            }
            return { encryptedData: String(encryptedData), iv: String(iv), code: inner.code ? String(inner.code) : null };
        } catch (e) {
            const msg = (e && e.message) ? e.message : String(e);
            throw new Error(`[YYB] 请求手机号加密数据失败: ${msg}`);
        }
    }

    /**
     * 调用通用 operateWxData（如云函数、微信步数、用户信息等）
     */
    async operateWxData(ref, appId, payload, expectLoginType = null) {
        const url = `${this.serverUrl}/wxapp/operateWxData`;
        const resolvedRef = await this._resolveRef(ref, expectLoginType);
        try {
            console.log(`[YYB] 请求operateWxData: ref=${resolvedRef}, app_id=${appId}`);
            const r = await axios.post(url, { ref: resolvedRef, app_id: appId, payload }, {
                headers: { 'Content-Type': 'application/json' },
                timeout: 30000,
                validateStatus: () => true
            });
            if (r.status !== 200 || r.data?.code !== 0) {
                throw new Error(r.data?.msg || `HTTP ${r.status}`);
            }
            return r.data?.data?.result ?? r.data?.data;
        } catch (e) {
            const msg = (e && e.message) ? e.message : String(e);
            throw new Error(`[YYB] operateWxData失败: ${msg}`);
        }
    }
}

// 兼容别名：旧脚本若显式引用 WechatAdapter 时无缝桥接
class WechatAdapter extends YYBAdapter {
    constructor(serverUrl, adminKey = null) {
        super(serverUrl);
        this.adminKey = adminKey;
    }
    async getOperateWxData(identifier, appId) {
        return this.operateWxData(identifier, appId, {});
    }
}

// ============================================================
//  统一入口类
// ============================================================

class WeChatCodeGetter {
    constructor(forceType = null) {
        this.serverUrl = getGlobalServerUrl();
        this.adapter = new YYBAdapter(this.serverUrl);
        this.targetWxIds = [];

        if (process.env.WX_ID) {
            this.targetWxIds = process.env.WX_ID.split(/[@&\n|]+/).map(id => id.trim()).filter(Boolean);
        }
    }

    async init() {
        return true;
    }

    async getOnlineAccounts() {
        const accounts = await this.adapter.getAccounts();
        if (!this.targetWxIds || this.targetWxIds.length === 0) {
            return accounts.map(acc => ({
                account: acc,
                status: { loginState: 1, onlineTime: 0, device: acc.avatar || '' }
            }));
        }

        const targets = this.targetWxIds.map(t => parseIdentifier(t));
        const filtered = accounts.filter(acc => {
            const keys = [String(acc.id || ''), acc._ref || '', acc.wxid || '', acc.openid || ''].filter(Boolean);
            const accLoginType = acc.login_type ? normalizeLoginType(acc.login_type) : null;
            return targets.some(t => {
                if (!keys.includes(t.rawId)) return false;
                if (t.loginType && accLoginType && accLoginType !== t.loginType) return false;
                return true;
            });
        });

        return filtered.map(acc => ({
            account: acc,
            status: { loginState: 1, onlineTime: 0, device: acc.avatar || '' }
        }));
    }

    async printOnlineStatus() {
        const online = await this.getOnlineAccounts();
        console.log(`\n当前有 ${online.length} 个账号在线 (@ ${this.serverUrl})`);
        for (const { account } of online) {
            const name = account.nickname || account.alias || account.wxid?.slice(0, 12) || '未知';
            const lt = loginTypeLabel(account.login_type);
            console.log(`  [${lt}] ${name} (id=${account.id}, openid=${account.openid})`);
        }
    }

    async getAppletCode(appId, identifier) {
        if (!identifier) {
            throw new Error('identifier 未提供，请检查 WX_ID 环境变量或调用参数');
        }
        const parsed = parseIdentifier(identifier);
        return this.adapter.getCode(identifier, appId, parsed.loginType);
    }

    async getAppletPhoneNumber(appId, identifier) {
        if (!identifier) return null;
        const parsed = parseIdentifier(identifier);
        return this.adapter.getPhoneNumber(identifier, appId, parsed.loginType);
    }

    async getAppletPhoneEncrypted(appId, identifier) {
        if (!identifier) return null;
        const parsed = parseIdentifier(identifier);
        return this.adapter.getPhoneEncrypted(identifier, appId, parsed.loginType);
    }

    async getCodesForAllOnlineAccounts(appId) {
        const online = await this.getOnlineAccounts();
        const codes = {};

        for (let i = 0; i < online.length; i++) {
            const acc = online[i].account;
            let baseName = acc.nickname || acc.alias || `账号_${i + 1}`;
            let name = baseName;
            let counter = 1;
            while (codes[name] !== undefined) {
                name = `${baseName}_${counter}`;
                counter++;
            }

            const ref = acc._ref || String(acc.id) || acc.openid;
            try {
                const code = await this.getAppletCode(appId, ref);
                codes[name] = code;
                console.log(`[getCode] ✓ ${name}: ${code.slice(0, 20)}...`);
            } catch (e) {
                console.log(`[getCode] ✗ ${name}: ${e.message}`);
            }
        }
        return codes;
    }
}

// ============================================================
//  全局进程兜底
// ============================================================
let _getCodeFatalHandlerInstalled = false;
function installGetCodeFatalHandler() {
    if (_getCodeFatalHandlerInstalled) return;
    _getCodeFatalHandlerInstalled = true;
    process.on('uncaughtException', (err) => {
        console.log(`[getCode] 未捕获异常(已兜底，脚本安全退出): ${err && err.message ? err.message : err}`);
    });
    process.on('unhandledRejection', (reason) => {
        console.log(`[getCode] 未处理的 Promise 拒绝(已兜底，脚本安全退出): ${reason && reason.message ? reason.message : reason}`);
    });
}
installGetCodeFatalHandler();

// ============================================================
//  便捷导出函数
// ============================================================

/**
 * 动态加载账号列表（支持从 yyb_go 服务端拉取存活账号）
 * @param {string|null} filterEnvName 脚本专用环境变量名（可选白名单）
 * @returns {Promise<Array<{id: number, ref: string, openid: string, nickname: string, loginType: string, login_type: string}>>}
 */
async function loadAccounts(filterEnvName = null) {
    const getter = new WeChatCodeGetter();
    await getter.init();
    const onlineList = await getter.getOnlineAccounts();

    const customFilter = (filterEnvName ? process.env[filterEnvName] : null) || process.env.WX_ID;
    let result = onlineList.map(({ account }) => ({
        id: account.id,
        ref: account._ref || String(account.id) || account.openid,
        openid: account.openid,
        nickname: account.nickname || account.alias || `用户_${account.id}`,
        loginType: normalizeLoginType(account.login_type),
        login_type: normalizeLoginType(account.login_type),
        status: account.status,
    }));

    if (customFilter) {
        const filters = customFilter.split(/[\n&]+/).map(v => parseIdentifier(v)).filter(v => v.rawId);
        result = result.filter(acc => {
            return filters.some(f => {
                const matchId = String(acc.id) === f.rawId || acc.openid === f.rawId || acc.ref === f.rawId;
                if (!matchId) return false;
                if (f.loginType && acc.loginType !== f.loginType) return false;
                return true;
            });
        });
    }

    return result;
}

/**
 * 获取所有在线账号的code
 */
async function getWechatCodes(appId) {
    const getter = new WeChatCodeGetter();
    await getter.init();
    return getter.getCodesForAllOnlineAccounts(appId);
}

/**
 * 打印在线状态
 */
async function printOnlineStatus() {
    const getter = new WeChatCodeGetter();
    await getter.init();
    return getter.printOnlineStatus();
}

/**
 * 为单个账号获取code（失败返回 null，不会中断脚本）
 */
async function getSingleCode(appId, identifier) {
    if (!identifier) {
        console.log(`[getCode] 缺少 identifier，跳过获取 code`);
        return null;
    }
    const getter = new WeChatCodeGetter();
    await getter.init();
    try {
        return await getter.getAppletCode(appId, identifier);
    } catch (e) {
        console.log(`[getCode] 获取失败: ${e && e.message ? e.message : e}`);
        return null;
    }
}

/**
 * 为指定账号获取手机号Code
 */
async function getSinglePhoneNumber(appId, identifier) {
    if (!identifier) return null;
    const getter = new WeChatCodeGetter();
    await getter.init();
    try {
        return await getter.getAppletPhoneNumber(appId, identifier);
    } catch (e) {
        console.log(`[getCode] 获取手机号失败: ${e && e.message ? e.message : e}`);
        return null;
    }
}

/**
 * 为指定账号获取手机号加密数据（encryptedData/iv）
 */
async function getSinglePhoneEncrypted(appId, identifier) {
    if (!identifier) return null;
    const getter = new WeChatCodeGetter();
    await getter.init();
    try {
        return await getter.getAppletPhoneEncrypted(appId, identifier);
    } catch (e) {
        console.log(`[getCode] 获取手机号加密数据失败: ${e && e.message ? e.message : e}`);
        return null;
    }
}

/**
 * 为单个账号获取登录用的 operate 数据
 */
async function getSingleOperateWxData(appId, identifier) {
    if (!identifier) return null;
    const getter = new WeChatCodeGetter();
    await getter.init();
    try {
        const code = await getter.getAppletCode(appId, identifier);
        return { code, encryptedData: null, iv: null };
    } catch (e) {
        console.log(`[getCode] 获取 operate 数据失败: ${e && e.message ? e.message : e}`);
        return null;
    }
}

module.exports = {
    WeChatCodeGetter,
    loadAccounts,
    getWechatCodes,
    printOnlineStatus,
    getSingleCode,
    getSinglePhoneNumber,
    getSinglePhoneEncrypted,
    getSingleOperateWxData,
    YYBAdapter,
    WechatAdapter,
    getGlobalServerUrl,
    parseIdentifier,
    stripScheme,
    normalizeLoginType,
    loginTypeLabel,
    LOGIN_TYPE_WX,
    LOGIN_TYPE_SYZS,
    LOGIN_TYPE_WMPF
};