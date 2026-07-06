/**
 * 微信小程序登录Code获取模块（双协议支持）
 * 
 * 默认策略: 双协议 Fallback 模式
 *   优先使用牛子(Wechat)获取code，失败后自动切换到应用宝(YYB)重试
 * 
 * 环境变量：
 *     WECHAT_SERVER: 牛子协议服务地址（默认 http://192.168.6.222:8011）
 *     YYB_SERVER:    应用宝服务地址（默认 http://127.0.0.1:8000）
 *     SERVER_TYPE:   强制指定: yyb / wechat / auto（默认 auto = 双协议fallback）
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
        this._accountCache = null;  // 缓存账号列表
        this._accountCacheTime = 0;
    }

    async healthCheck() {
        try {
            const r = await axios.get(`${this.serverUrl}/health`, { timeout: 5000 });
            return r.status === 200 && r.data?.ok === true;
        } catch {
            return false;
        }
    }
    
    /**
     * 获取并缓存账号列表
     */
    async _getAccountList() {
        const now = Date.now();
        // 缓存5分钟
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
     * 根据 wxid/openid 查找 YYB 数据库中的 ref (优先用 id)
     */
    async _resolveRef(wxidOrOpenid) {
        const accounts = await this._getAccountList();
        
        // 精确匹配 openid
        for (const acc of accounts) {
            if (acc.openid === wxidOrOpenid) {
                console.log(`[YYB] 匹配成功: ${wxidOrOpenid} → id=${acc.id}, openid=${acc.openid}`);
                // 优先使用 id（数字），其次用 openid
                return String(acc.id);
            }
        }
        
        // 模糊匹配（部分包含）
        for (const acc of accounts) {
            if (acc.openid?.includes(wxidOrOpenid) || wxidOrOpenid.includes(acc.openid || '')) {
                console.log(`[YYB] 模糊匹配: ${wxidOrOpenid} → id=${acc.id}, openid=${acc.openid}`);
                return String(acc.id);
            }
        }
        
        // 打印所有可用账号帮助诊断
        if (accounts.length > 0) {
            console.log(`[YYB] 可用账号: ${accounts.map(a => `${a.id}:${a.openid}`).join(', ')}`);
        } else {
            console.log(`[YYB] ⚠ 无可用账号！请先在应用宝扫码登录`);
        }
        
        // 返回原始值，让服务端报错以便调试
        return wxidOrOpenid;
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
        
        // 先将 wxid/openid 转换为 YYB 数据库中的 ref（账号 ID）
        const resolvedRef = await this._resolveRef(ref);
        
        try {
            console.log(`[YYB] 请求code: ref=${resolvedRef}, app_id=${appId}`);
            const r = await axios.post(url, { ref: resolvedRef, app_id: appId }, { 
                headers: { 'Content-Type': 'application/json' },
                timeout: 30000,
                validateStatus: () => true
            });
            
            console.log(`[YYB] 响应状态: ${r.status}`);
            
            if (r.status === 404) {
                throw new Error('接口不存在(404)');
            }
            
            if (r.status === 400) {
                throw new Error(`参数错误 - 可能账号不存在: ${JSON.stringify(r.data)}`);
            }
            
            if (r.status === 409) {
                throw new Error('账号login_buffer已过期，需要重新扫码登录');
            }
            
            const result = r.data;
            const codeVal = result?.code ?? -1;
            if (codeVal !== 0) {
                throw new Error(`[${codeVal}] ${result?.msg || `HTTP ${r.status}`}`);
            }
            
            // 从 data.result.code 提取
            const data = result?.data;
            if (!data || typeof data !== 'object') {
                // YYB 新版格式可能直接返回 { openid, result: { code: "xxx" } }
                if (data?.result?.code) {
                    return data.result.code;
                }
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
        
        // 防御性检查：appid 不能为空
        if (!appId || appId === 'undefined') {
            throw new Error(`appid 参数缺失！调用方必须传入有效的 appid。当前值: ${appId}`);
        }
        
        // 尝试多个可能的 API 端点
        const endpoints = [
            '/api/v1/wx/app/get/code',
            '/api/v1/wx/app/get/code/',
            '/api/v1/wx/get/code',
            '/wx/app/get/code',       // 某些变体
            '/api/wx/app/get/code',    // 某些变体
        ];
        
        console.log(`[牛子] 尝试获取code: wxid=${actualWxid}, appid=${appId}`);
        
        for (const ep of endpoints) {
            const fullUrl = `${this.serverUrl}${ep}`;
            try {
                console.log(`[牛子] 请求: POST ${fullUrl}`);
                const r = await axios.post(fullUrl, { wxid: actualWxid, appid: appId }, { timeout: 20000, validateStatus: () => true });
                console.log(`[牛子] 响应状态: ${r.status}`);
                
                if (r.status === 404) {
                    console.log(`[牛子] ⚠ 端点不存在: ${ep}`);
                    continue;  // 尝试下一个端点
                }
                
                const result = r.data;
                
                // 防御性检查：result 为 null/undefined 时直接跳过
                if (!result || typeof result !== 'object') {
                    console.log(`[牛子] 响应数据无效(非对象): ${JSON.stringify(result)}`);
                    continue;
                }
                
                let code = result.code ||
                          (typeof result.data === 'object' ? result.data.code : null) ||
                          (typeof result.Data === 'object' ? result.Data.code : null) ||
                          (typeof result.data === 'string' ? result.data : null) ||
                          (typeof result.Data === 'string' ? result.Data : null);
                
                if (code && typeof code === 'string' && code.length > 5) return code;
                
                console.log(`[牛子] 无有效code: ${JSON.stringify(result).slice(0, 100)}`);
            } catch (e) {
                console.log(`[牛子] 请求失败(${ep}): ${e.message}`);
            }
        }
        throw new Error('所有API端点均不可达或返回无效数据(404)');
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
        
        // 双协议适配器（fallback模式）
        this.primaryAdapter = null;   // 主适配器
        this.fallbackAdapter = null;  // 备用适配器
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
                    'auto': 'Auto',  // 显式指定自动模式
                }[envType] || 'Auto';  // 默认 Auto = 双协议 fallback
            }
        }
        
        // 默认使用 Auto（双协议 fallback）模式
        if (!protocolType || protocolType === 'Unknown') {
            protocolType = 'Auto';
        }

        if (protocolType === 'Auto') {
            // 双协议 Fallback 模式：牛子优先 + 应用宝备用
            await this._initAutoMode();
        } else if (protocolType === 'YYB') {
            // 纯应用宝模式
            this.primaryAdapter = new YYBAdapter(this.yybServer);
            this.fallbackAdapter = null;
            this.protocolType = 'YYB';
            this.serverUrl = this.yybServer;
            console.log(`[getCode] 当前服务: YYB(应用宝) @ ${this.yybServer}`);
        } else if (protocolType === 'Wechat') {
            // 纯牛子模式
            this.primaryAdapter = new WechatAdapter(this.wechatServer, this.adminKey);
            this.fallbackAdapter = null;
            this.protocolType = 'Wechat';
            this.serverUrl = this.wechatServer;
            console.log(`[getCode] 当前服务: Wechat(牛子) @ ${this.wechatServer}`);
        }
        
        // 缓存检测结果
        try {
            fs.writeFileSync(this.envCheckFile, JSON.stringify({ 
                protocol_type: protocolType,
                primary: this.primaryAdapter ? this.protocolType : null,
                fallback: this.fallbackAdapter ? (this.protocolType === 'Wechat' ? 'YYB' : 'Wechat') : null
            }), 'utf-8');
        } catch (e) {}
    }

    /**
     * 初始化双协议 Fallback 模式
     * 策略：牛子优先获取code → 失败自动切换到应用宝重试
     */
    async _initAutoMode() {
        this.protocolType = 'Auto(Fallback)';
        
        const wechatOk = await new WechatAdapter(this.wechatServer, this.adminKey).healthCheck();
        const yybOk = await new YYBAdapter(this.yybServer).healthCheck();

        let services = [];
        if (wechatOk) services.push('Wechat');
        if (yybOk) services.push('YYB');

        if (services.length === 0) {
            throw new Error(
                '无法确定服务类型！请设置环境变量：\n' +
                '  WECHAT_SERVER=http://你的牛子地址:端口\n' +
                '  YYB_SERVER=http://你的应用宝地址:端口\n' +
                '  或设置 SERVER_TYPE=wechat / SERVER_TYPE=yyb 强制指定'
            );
        }

        // 牛子优先作为主适配器
        if (wechatOk) {
            this.primaryAdapter = new WechatAdapter(this.wechatServer, this.adminKey);
            this.serverUrl = `${this.wechatServer}(主)`;
        } else {
            this.primaryAdapter = new YYBAdapter(this.yybServer);
            this.serverUrl = `${this.yybServer}(主)`;
        }

        // 配置备用适配器
        if (wechatOk && yybOk) {
            this.fallbackAdapter = new YYBAdapter(this.yybServer);
            this.serverUrl = `${this.wechatServer}→${this.yybServer}`;
            console.log(`[getCode] 双协议Fallback模式: 牛子(主) + 应用宝(备)`);
        } else if (!wechatOk && yybOk) {
            this.fallbackAdapter = null;  // 只有YYB可用，不需要fallback
            this.serverUrl = this.yybServer;
            console.log(`[getCode] 仅应用宝可用 @ ${this.yybServer}`);
        } else {
            this.fallbackAdapter = null;  // 只有牛子可用
            console.log(`[getCode] 仅牛子可用 @ ${this.wechatServer}`);
        }
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
        const accounts = await this.primaryAdapter.getAccounts();
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

    /**
     * 获取单个账号的code（支持双协议fallback）
     * 优先使用主适配器，失败后自动切换到备用适配器重试
     * 如果没有预配置备用适配器，会尝试动态创建应用宝适配器
     */
    async getAppletCode(appId, identifier) {
        // 先尝试主适配器（牛子）
        try {
            const code = await this.primaryAdapter.getCode(identifier, appId);
            return code;
        } catch (primaryError) {
            // 1. 优先使用已配置的备用适配器
            if (this.fallbackAdapter) {
                console.log(`[getCode] ⚠ 主服务获取失败，切换到备用服务重试...`);
                try {
                    const code = await this.fallbackAdapter.getCode(identifier, appId);
                    console.log(`[getCode] ✓ 备用服务获取成功`);
                    return code;
                } catch (fallbackError) {
                    throw new Error(
                        `主服务和备用服务均失败:\n` +
                        `  [主] ${primaryError.message}\n` +
                        `  [备] ${fallbackError.message}`
                    );
                }
            }

            // 2. 动态 fallback：即使初始化时应用宝检测失败，运行时再尝试一次
            const isPrimaryWechat = this.primaryAdapter instanceof WechatAdapter;
            if (isPrimaryWechat) {
                console.log(`[getCode] ⚠ 牛子服务失败，动态尝试应用宝服务...`);
                try {
                    const dynamicYyb = new YYBAdapter(this.yybServer);
                    const yybHealthOk = await dynamicYyb.healthCheck();
                    
                    if (yybHealthOk) {
                        console.log(`[getCode] ✓ 应用宝服务可用，切换获取code`);
                        const code = await dynamicYyb.getCode(identifier, appId);
                        console.log(`[getCode] ✓ 应用宝获取成功`);
                        
                        // 缓存成功的服务实例供后续使用
                        if (!this.fallbackAdapter) {
                            this.fallbackAdapter = dynamicYyb;
                        }
                        return code;
                    } else {
                        console.log(`[getCode] ✗ 应用宝服务不可用`);
                    }
                } catch (dynamicError) {
                    console.log(`[getCode] ✗ 应用宝动态请求失败: ${dynamicError.message}`);
                }
            }

            // 所有方式都失败
            throw primaryError;
        }
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
