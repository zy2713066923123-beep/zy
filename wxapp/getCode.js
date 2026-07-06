/**
 * 微信小程序登录Code获取模块（双协议支持）
 * 支持两种服务：
 *   1) YYB (应用宝) - yyb_go 微信扫码代理服务
 *   2) Wechat (牛子) - 微信iPad/iPhone协议服务
 * 
 * 环境变量：
 *     WECHAT_SERVER: 牛子协议服务地址（默认 http://192.168.6.222:8011）
 *     YYB_SERVER:    应用宝服务地址（默认 http://127.0.0.1:8000）
 *     SERVER_TYPE:   强制指定: yyb / wechat（不设则自动检测）
 *     ADMIN_KEY:     牛子管理密钥（仅WeChatPadPro/iwechat需要）
 *     WX_ID:         可选，指定要获取Code的微信账号ID
 */

const axios = require('axios');
const fs = require('fs');
const path = require('path');

// ============================================================
//  YYB Server（应用宝）适配器
// ============================================================

class YYBAdapter {
    constructor(serverUrl) {
        this.serverUrl = serverUrl.replace(/\/+$/, '');
    }

    async healthCheck() {
        try {
            const r = await axios.get(`${this.serverUrl}/health`, { timeout: 5000 });
            return r.status === 200 && r.data?.code === 0;
        } catch {
            return false;
        }
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
            
            // 只返回存活账号
            return list
                .filter(acc => {
                    const s = String(acc.status || '').toLowerCase();
                    return ['alive', '', 'unknown'].includes(s);
                })
                .map(acc => ({
                    wxid: acc.openid || '',
                    openid: acc.openid || '',
                    uin: acc.uin,
                    nickname: acc.nickname,
                    alias: acc.alias,
                    avatar: acc.avatar,
                    status: 1,
                    loginState: 1,
                    _ref: String(acc.id || '') || acc.openid || '',
                }));
        } catch (e) {
            throw new Error(`[YYB] 获取账号列表失败: ${e.message}`);
        }
    }

    async getCode(ref, appId) {
        const url = `${this.serverUrl}/wxapp/getCode`;
        
        try {
            const r = await axios.post(url, { ref, app_id: appId }, { 
                headers: { 'Content-Type': 'application/json' },
                timeout: 30000 
            });
            
            const result = r.data;
            
            if (r.status === 409) {
                throw new Error('账号login_buffer已过期，需要重新扫码登录');
            }
            
            const codeVal = result?.code ?? -1;
            if (codeVal !== 0) {
                throw new Error(`[${codeVal}] ${result?.msg || `HTTP ${r.status}`}`);
            }
            
            // 从 data.result.code 提取
            const data = result?.data;
            if (!data || typeof data !== 'object') {
                throw new Error(`响应data异常: ${JSON.stringify(data).slice(0, 100)}`);
            }
            
            const inner = data.result;
            if (!inner || typeof inner !== 'object') {
                throw new Error(`result异常: ${JSON.stringify(inner).slice(0, 100)}`);
            }
            
            const code = inner.code;
            if (!code || typeof code !== 'string' || code.length < 5) {
                throw new Error(`未拿到有效code: ${JSON.stringify(result).slice(0, 150)}`);
            }
            
            return code;
        } catch (e) {
            if (e.message.includes('[YYB]') || e.message.includes('login_buffer')) throw e;
            throw new Error(`[YYB] 请求code失败: ${e.message}`);
        }
    }
}


// ============================================================
//  Wechat (牛子协议) 适配器
// ============================================================

class WechatAdapter {
    constructor(serverUrl, adminKey) {
        this.serverUrl = serverUrl.replace(/\/+$/, '');
        this.adminKey = adminKey;
        this.subType = null; // Niuzi | WeChatPadPro | iwechat
    }

    async _detectSubProtocol() {
        if (this.subType) return this.subType;
        
        const params = this.adminKey ? { key: this.adminKey } : {};
        
        try {
            let r = await axios.get(`${this.serverUrl}/admin/GetAuthKey`, { params, timeout: 5000, validateStatus: () => true });
            if (r.status === 200) { this.subType = 'iwechat'; return this.subType; }
            
            r = await axios.get(`${this.serverUrl}/admin/GetAllDevices`, { params, timeout: 5000, validateStatus: () => true });
            if (r.status === 200) { this.subType = 'WeChatPadPro'; return this.subType; }
        } catch (e) {}
        
        // 默认 Niuzi
        try {
            await axios.get(`${this.serverUrl}/api/v1/wx/user/status`, { timeout: 5000 });
            this.subType = 'Niuzi';
        } catch (e) {
            this.subType = 'Niuzi';
        }
        return this.subType;
    }

    async healthCheck() {
        try {
            const r = await axios.get(`${this.serverUrl}/api/v1/wx/user/status`, { timeout: 5000 });
            return r.status === 200;
        } catch {
            return false;
        }
    }

    async getAccounts() {
        const subType = await this._detectSubProtocol();
        
        switch (subType) {
            case 'Niuzi': return this._getNiuziAccounts();
            case 'WeChatPadPro': return this._getPadproAccounts();
            case 'iwechat': return this._getIwechatAccounts();
            default: return [];
        }
    }

    async _getNiuziAccounts() {
        const url = `${this.serverUrl}/api/v1/wx/user/status`;
        try {
            const r = await axios.get(url, { timeout: 60000 });
            const result = r.data;
            
            if (!result.status) throw new Error(result.message || '未知错误');
            
            const accountsData = result.data || {};
            if (typeof accountsData !== 'object') throw new Error('API返回格式错误');
            
            const accounts = [];
            for (const [wxid, info] of Object.entries(accountsData)) {
                if (typeof info === 'object' && info.wxid && info.nickname && info.survival === 1) {
                    accounts.push({
                        wxid: info.wxid,
                        openid: info.wxid,
                        nickname: info.nickname,
                        alias: null,
                        avatar: null,
                        status: 1,
                        loginState: 1,
                        _ref: info.wxid,
                    });
                }
            }
            return accounts;
        } catch (e) {
            throw new Error(`[牛子] 获取账号列表失败: ${e.message}`);
        }
    }

    async _getIwechatAccounts() {
        try {
            const r = await axios.get(`${this.serverUrl}/admin/GetAuthKey`, { 
                params: { key: this.adminKey }, timeout: 60000 
            });
            const authData = r.data;
            if (!Array.isArray(authData)) throw new Error('响应格式错误');
            
            return authData
                .filter(a => (a.status || 0) === 1)
                .map(a => ({
                    wxid: a.wx_id || '',
                    openid: a.wx_id || '',
                    nickname: a.nick_name,
                    alias: null,
                    avatar: null,
                    status: 1,
                    loginState: 1,
                    _ref: a.license || a.authKey || '',
                }));
        } catch (e) {
            throw new Error(`[iwechat] 获取账号失败: ${e.message}`);
        }
    }

    async _getPadproAccounts() {
        try {
            const r = await axios.get(`${this.serverUrl}/admin/GetAllDevices`, { 
                params: { key: this.adminKey }, timeout: 60000 
            });
            let devices = [];
            const d = r.data;
            
            if (typeof d === 'object' && d.Data?.devices) devices = d.Data.devices;
            else if (d.data) devices = d.data;
            else if (d.devices) devices = d.devices;
            else if (Array.isArray(d)) devices = d;
            else devices = [d];
            
            if (!Array.isArray(devices)) throw new Error('响应格式错误');
            
            return devices
                .filter(a => (a.status || 0) === 1)
                .map(a => ({
                    wxid: a.deviceId || '',
                    openid: a.deviceId || '',
                    nickname: a.deviceName,
                    alias: null,
                    avatar: null,
                    status: 1,
                    loginState: 1,
                    _ref: a.license || a.authKey || '',
                }));
        } catch (e) {
            throw new Error(`[WeChatPadPro] 获取账号失败: ${e.message}`);
        }
    }

    async getCode(identifier, appId) {
        const subType = await this._detectSubProtocol();
        return subType === 'Niuzi' ? this._niuziGetCode(identifier, appId) : this._legacyGetCode(identifier, appId);
    }

    async _niuziGetCode(wxid, appId) {
        const actualWxid = String(wxid).split('#')[0].trim();
        const endpoints = ['/api/v1/wx/app/get/code', '/api/v1/wx/app/get/code/', '/api/v1/wx/get/code'];
        
        let lastError = null;
        for (const ep of endpoints) {
            try {
                const r = await axios.post(`${this.serverUrl}${ep}`, { wxid: actualWxid, appid: appId }, { timeout: 20000 });
                const result = r.data;
                
                let code = result?.code ||
                          (typeof result?.data === 'object' ? result.data.code : null) ||
                          (typeof result?.Data === 'object' ? result.Data.code : null) ||
                          (typeof result?.data === 'string' ? result.data : null) ||
                          (typeof result?.Data === 'string' ? result.Data : null);
                
                if (code && typeof code === 'string' && code.length > 5) return code;
                
                lastError = new Error(`无有效code: ${JSON.stringify(result).slice(0, 150)}`);
            } catch (e) {
                lastError = e;
            }
        }
        throw lastError || new Error('牛子获取code失败');
    }

    async _legacyGetCode(license, appId) {
        try {
            const r = await axios.post(
                `${this.serverUrl}/applet/JsLogin`,
                { AppId: appId, Data: "", Opt: 1, PackageName: "", SdkName: "" },
                { params: { key: license }, timeout: 60000 }
            );
            const result = r.data;
            
            if (result.Code !== 200) throw new Error(result.Text || '未知错误');
            
            const code = result.Data?.Code;
            if (!code) throw new Error('响应中无Code字段');
            
            return code;
        } catch (e) {
            throw new Error(`[传统协议] 请求失败: ${e.message}`);
        }
    }
}


// ============================================================
//  统一入口类
// ============================================================

class WeChatCodeGetter {
    constructor(forceType = null) {
        this.yybServer = process.env.YYB_SERVER || process.env.YINGYOGBAO_SERVER || 'http://127.0.0.1:8000';
        this.wechatServer = process.env.WECHAT_SERVER || 'http://192.168.6.222:8011';
        this.adminKey = process.env.ADMIN_KEY;
        this.wxIdFilter = process.env.WX_ID;
        this.protocolType = 'Unknown';
        this.adapter = null;
        this.serverUrl = '';
        
        this.scriptDir = __dirname;
        this.envCheckFile = path.join(this.scriptDir, 'env_check.json');
        
        this.targetWxIds = [];
        if (this.wxIdFilter) {
            this.targetWxIds = this.wxIdFilter.split('&').map(id => id.trim()).filter(id => id);
            console.log(`[getCode] WX_ID筛选: ${this.targetWxIds.join(', ')}`);
        }
        
        this._forceType = forceType;
    }

    async init() {
        // 强制类型优先
        let protocolType = this._forceType;
        
        if (!protocolType) {
            const envType = (process.env.SERVER_TYPE || '').toLowerCase();
            if (envType) {
                protocolType = {
                    'yyb': 'YYB', 'yingyongbao': 'YYB', '应用宝': 'YYB',
                    'wechat': 'Wechat', 'niuzi': 'Wechat', '牛子': 'Wechat',
                }[envType] || 'Unknown';
            }
        }
        
        if (!protocolType && fs.existsSync(this.envCheckFile)) {
            try {
                const saved = JSON.parse(fs.readFileSync(this.envCheckFile, 'utf-8'));
                if (saved.protocol_type && saved.protocol_type !== 'Unknown') {
                    protocolType = saved.protocol_type;
                }
            } catch (e) {}
        }
        
        // 自动检测
        if (!protocolType || protocolType === 'Unknown') {
            console.log('[getCode] 正在自动检测服务类型...');
            
            const testYyb = new YYBAdapter(this.yybServer);
            if (await testYyb.healthCheck()) {
                protocolType = 'YYB';
                console.log(`[getCode] ✓ 检测到 应用宝 服务: ${this.yybServer}`);
            } else {
                const testWx = new WechatAdapter(this.wechatServer, this.adminKey);
                if (await testWx.healthCheck()) {
                    protocolType = 'Wechat';
                    console.log(`[getCode] ✓ 检测到 牛子 服务: ${this.wechatServer}`);
                } else {
                    console.log(`[getCode] ✗ 未检测到可用服务`);
                    console.log(`[getCode]   应用宝(${this.yybServer}): 不可达`);
                    console.log(`[getCode]   牛子(${this.wechatServer}): 不可达`);
                }
            }
        }
        
        this.protocolType = protocolType;
        
        if (protocolType === 'YYB') {
            this.adapter = new YYBAdapter(this.yybServer);
            this.serverUrl = this.yybServer;
        } else if (protocolType === 'Wechat') {
            this.adapter = new WechatAdapter(this.wechatServer, this.adminKey);
            this.serverUrl = this.wechatServer;
        } else {
            throw new Error(
                '无法确定服务类型！请设置环境变量：\n' +
                '  WECHAT_SERVER=http://你的牛子地址:端口\n' +
                '  YYB_SERVER=http://你的应用宝地址:端口\n' +
                '  或设置 SERVER_TYPE=wechat / SERVER_TYPE=yyb 强制指定'
            );
        }
        
        // 缓存检测结果
        try {
            fs.writeFileSync(this.envCheckFile, JSON.stringify({ protocol_type: protocolType }), 'utf-8');
        } catch (e) {}
        
        console.log(`[getCode] 当前服务: ${protocolType} @ ${this.serverUrl}`);
    }

    _filterAccounts(accounts) {
        if (!this.targetWxIds || this.targetWxIds.length === 0) return accounts;
        
        const filtered = accounts.filter(acc => {
            const ref = acc._ref || '';
            const wxid = acc.wxid || '';
            const openid = acc.openid || '';
            return this.targetWxIds.some(t => [ref, wxid, openid].includes(t));
        });
        
        if (filtered.length > 0) {
            console.log(`[getCode] 筛选后剩余 ${filtered.length} 个账号`);
        } else {
            console.log(`[getCode] 警告：WX_ID筛选无匹配账号`);
        }
        return filtered;
    }

    async getOnlineAccounts() {
        const accounts = await this.adapter.getAccounts();
        const filtered = this._filterAccounts(accounts);
        
        return filtered.map(acc => ({
            account: acc,
            status: { loginState: acc.loginState || 1, onlineTime: acc.last_checked_at || 0, device: acc.avatar || '' }
        }));
    }

    async printOnlineStatus() {
        const online = await this.getOnlineAccounts();
        console.log(`\n当前有 ${online.length} 个账号在线 (${this.protocolType})`);
        
        for (const { account } of online) {
            const name = account.nickname || account.alias || account.wxid?.slice(0, 12) || '未知';
            console.log(`  ${name}`);
        }
    }

    async getAppletCode(appId, identifier) {
        return await this.adapter.getCode(identifier, appId);
    }

    async getCodesForAllOnlineAccounts(appId) {
        const online = await this.getOnlineAccounts();
        const codes = {};
        
        for (let i = 0; i < online.length; i++) {
            const acc = online[i].account;
            let baseName = acc.nickname || acc.alias || `账号_${i + 1}`;
            
            if (!baseName.trim() || baseName.trim() === '\u3164') {
                baseName = acc.wxid ? `账号_${acc.wxid.slice(-6)}` : `账号_${i + 1}`;
            }
            
            let name = baseName;
            let counter = 1;
            while (codes[name] !== undefined) {
                name = `${baseName}_${counter}`;
                counter++;
            }
            
            const ref = acc._ref;
            if (!ref) {
                console.log(`[getCode] ${name}: 缺少标识符，跳过`);
                continue;
            }
            
            try {
                const code = await this.adapter.getCode(ref, appId);
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
//  便捷函数（向后兼容）
// ============================================================

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
 * 为单个账号获取code
 */
async function getSingleCode(appId, identifier) {
    const getter = new WeChatCodeGetter();
    await getter.init();
    try {
        return await getter.getAppletCode(appId, identifier);
    } catch (e) {
        console.log(`[getCode] 获取失败（可能需重新登录）: ${e.message}`);
        throw e;
    }
}

module.exports = {
    WeChatCodeGetter,
    getWechatCodes,
    printOnlineStatus,
    getSingleCode,
    YYBAdapter,
    WechatAdapter
};
