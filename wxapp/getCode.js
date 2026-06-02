/**
 * 微信小程序登录Code获取模块
 * 用于通过微信iPad协议接口获取小程序登录Code值
 * 模块作者：3iXi (JS版)
 * 创建时间：2025/08/08 (适配JS版)
 * ！！需要先搭建WeChatPadPro、iwechat或牛子协议才能使用此模块！！
 * 环境变量：
 *     WECHAT_SERVER: 协议服务IP地址和端口
 *     ADMIN_KEY: 与搭建时设置的ADMIN_KEY一致（仅WeChatPadPro或iwechat需要，牛子协议不需要）
 *     WX_ID: 可选，指定要获取Code的微信账号ID，多个用&分隔
 *            对应iwechat接口的wx_id字段或WeChatPadPro接口的deviceId字段或牛子协议的wxid字段
 *            如果不设置则获取所有有效账号的Code
 */

const axios = require('axios');
const fs = require('fs');
const path = require('path');

class WeChatCodeGetter {
    constructor() {
        this.wechatServer = (process.env.WECHAT_SERVER || 'http://192.168.6.222:8011').replace(/\/+$/, '');
        this.adminKey = process.env.ADMIN_KEY;
        this.wxIdFilter = process.env.WX_ID;
        
        this.scriptDir = __dirname;
        this.envCheckFile = path.join(this.scriptDir, 'env_check.json');
        this.protocolType = 'Unknown';
        
        if (!this.wechatServer) {
            throw new Error('环境变量 WECHAT_SERVER 未设置');
        }
        
        if (!this.wechatServer.toLowerCase().startsWith('http://') && !this.wechatServer.toLowerCase().startsWith('https://')) {
            this.wechatServer = `http://${this.wechatServer}`;
        }
        
        this.targetWxIds = [];
        if (this.wxIdFilter) {
            this.targetWxIds = this.wxIdFilter.split('&').map(id => id.trim()).filter(id => id);
            console.log(`检测到WX_ID环境变量，将筛选指定账号: ${this.targetWxIds.join(', ')}`);
        }
    }
    
    async init() {
        await this._determineProtocolType();
    }

    async _determineProtocolType() {
        if (fs.existsSync(this.envCheckFile)) {
            try {
                const data = JSON.parse(fs.readFileSync(this.envCheckFile, 'utf-8'));
                if (data.protocol_type) {
                    this.protocolType = data.protocol_type;
                    console.log(`从配置文件读取到协议服务类型: ${this.protocolType}`);
                    if (this.protocolType === 'Unknown') {
                        try {
                            fs.unlinkSync(this.envCheckFile);
                            console.log('配置文件中标记为 Unknown，将重新检测协议服务类型');
                        } catch (e) {
                            console.log(`无法删除配置文件 env_check.json: ${e.message}`);
                        }
                    } else {
                        return;
                    }
                }
            } catch (e) {
                console.log(`读取配置文件失败: ${e.message}`);
            }
        }
        
        try {
            let response = await axios.get(`${this.wechatServer}/admin/GetAuthKey`, {
                params: { key: this.adminKey },
                timeout: 5000,
                validateStatus: function (status) {
                    return status >= 200 && status < 500; 
                }
            });
            if (response.status === 200) {
                this.protocolType = 'iwechat';
            } else if (response.status === 404) {
                response = await axios.get(`${this.wechatServer}/admin/GetAllDevices`, {
                    params: { key: this.adminKey },
                    timeout: 5000,
                    validateStatus: function (status) {
                        return status >= 200 && status < 500; 
                    }
                });
                if (response.status === 200) {
                    this.protocolType = 'WeChatPadPro';
                } else if (response.status === 404) {
                    response = await axios.get(`${this.wechatServer}/api/v1/wx/user/status`, {
                        timeout: 5000,
                        validateStatus: function (status) {
                            return status >= 200 && status < 500; 
                        }
                    });
                    if (response.status === 200) {
                        this.protocolType = 'Niuzi';
                    }
                }
            }
        } catch (e) {
            // ignore
        }

        try {
            fs.writeFileSync(this.envCheckFile, JSON.stringify({ protocol_type: this.protocolType }, null, 2), 'utf-8');
            console.log(`当前使用的协议服务: ${this.protocolType}`);
        } catch (e) {
            console.log(`保存配置文件失败: ${e.message}`);
        }

        if (['WeChatPadPro', 'iwechat'].includes(this.protocolType) && !this.adminKey) {
            throw new Error('环境变量 ADMIN_KEY 未设置');
        }
    }

    _isAccountValid(account) {
        return (account.status || 0) === 1;
    }

    _filterAccountsByWxId(accounts) {
        if (!this.targetWxIds || this.targetWxIds.length === 0) {
            return accounts;
        }

        const filteredAccounts = accounts.filter(account => {
            const wxId = account.wx_id || account.deviceId || '';
            return this.targetWxIds.includes(wxId);
        });

        if (filteredAccounts.length > 0) {
            console.log(`根据WX_ID筛选后获得${filteredAccounts.length}个账号`);
        } else {
            console.log(`警告：根据WX_ID筛选后没有找到匹配的账号`);
        }

        return filteredAccounts;
    }

    async getAuthKeys() {
        if (this.protocolType === 'Niuzi') {
            return await this._getNiuziAccounts();
        } else if (this.protocolType === 'WeChatPadPro') {
            return await this._getDevicesAuthKeys();
        } else if (this.protocolType === 'iwechat') {
            return await this._getIwechatAuthKeys();
        } else {
            throw new Error('未知的协议服务类型');
        }
    }

    async _getNiuziAccounts() {
        const url = `${this.wechatServer}/api/v1/wx/user/status`;
        try {
            const response = await axios.get(url, { timeout: 60000 });
            const result = response.data;
            if (!result.status) {
                throw new Error(`获取在线账号失败: ${result.message || '未知错误'}`);
            }
            
            const accountsData = result.data || {};
            if (typeof accountsData !== 'object') {
                throw new Error('API返回的数据格式错误，data应为对象');
            }
            
            const accounts = [];
            for (const [wxid, accountInfo] of Object.entries(accountsData)) {
                if (typeof accountInfo === 'object' && accountInfo.wxid && accountInfo.nickname && accountInfo.survival === 1) {
                    accountInfo.status = 1;
                    accountInfo.nick_name = accountInfo.nickname;
                    accountInfo.wx_id = accountInfo.wxid;
                    accountInfo.license = accountInfo.wxid;
                    accountInfo.authKey = accountInfo.wxid;
                    accountInfo.loginState = 1;
                    accountInfo.onlineTime = accountInfo.loginDate || 0;
                    accounts.push(accountInfo);
                }
            }
            
            console.log(`从牛子协议获取到${accounts.length}个在线账号`);
            return this._filterAccountsByWxId(accounts);
        } catch (e) {
            throw new Error(`获取账号列表失败: ${e.message}`);
        }
    }

    async _getIwechatAuthKeys() {
        const url = `${this.wechatServer}/admin/GetAuthKey`;
        try {
            const response = await axios.get(url, { params: { key: this.adminKey }, timeout: 60000 });
            const authData = response.data;
            
            if (!Array.isArray(authData)) {
                throw new Error('获取授权码响应格式错误');
            }
            
            const validAccounts = authData.filter(account => this._isAccountValid(account));
            return this._filterAccountsByWxId(validAccounts);
        } catch (e) {
            throw new Error(`获取授权码失败: ${e.message}`);
        }
    }

    async _getDevicesAuthKeys() {
        const url = `${this.wechatServer}/admin/GetAllDevices`;
        try {
            const response = await axios.get(url, { params: { key: this.adminKey }, timeout: 60000 });
            const devicesData = response.data;
            
            let authData;
            if (typeof devicesData === 'object' && devicesData.Data) {
                if (devicesData.Data.devices) {
                    authData = devicesData.Data.devices;
                } else {
                    throw new Error('GetAllDevices响应中Data部分缺少devices字段');
                }
            } else if (Array.isArray(devicesData)) {
                authData = devicesData;
            } else if (typeof devicesData === 'object') {
                if (devicesData.data) {
                    authData = devicesData.data;
                } else if (devicesData.devices) {
                    authData = devicesData.devices;
                } else {
                    authData = [devicesData];
                }
            } else {
                throw new Error('GetAllDevices响应格式错误');
            }
            
            if (!Array.isArray(authData)) {
                throw new Error('GetAllDevices响应格式错误');
            }
            
            const validAccounts = authData.filter(account => this._isAccountValid(account));
            console.log(`通过GetAllDevices接口获取到${validAccounts.length}个有效账号`);
            
            return this._filterAccountsByWxId(validAccounts);
        } catch (e) {
            throw new Error(`通过GetAllDevices获取授权码失败: ${e.message}`);
        }
    }

    async getLoginStatus(license) {
        const url = `${this.wechatServer}/login/GetLoginStatus`;
        try {
            const response = await axios.get(url, { params: { key: license }, timeout: 60000 });
            const statusData = response.data;
            
            if (statusData.Code !== 200) {
                throw new Error(`获取登录状态失败: ${statusData.Text || '未知错误'}`);
            }
            return statusData.Data || {};
        } catch (e) {
            throw new Error(`获取登录状态失败: ${e.message}`);
        }
    }

    async getOnlineAccounts() {
        const accounts = await this.getAuthKeys();
        const onlineAccounts = [];

        if (this.protocolType === 'Niuzi') {
            for (const account of accounts) {
                const loginStatus = {
                    loginState: 1,
                    onlineTime: account.loginDate || 0,
                    device: account.device || ''
                };
                onlineAccounts.push({ account, status: loginStatus });
            }
        } else {
            for (const account of accounts) {
                const license = account.license || account.authKey;
                if (!license) continue;

                try {
                    const loginStatus = await this.getLoginStatus(license);
                    if (loginStatus.loginState === 1) {
                        onlineAccounts.push({ account, status: loginStatus });
                    }
                } catch (e) {
                    const nickName = account.nick_name || account.deviceName || '未知';
                    console.log(`检查账号 ${nickName} 登录状态失败: ${e.message}`);
                }
            }
        }

        return onlineAccounts;
    }

    async printOnlineStatus() {
        const onlineAccounts = await this.getOnlineAccounts();
        console.log(`当前有${onlineAccounts.length}个账号在线`);
        for (const { account, status } of onlineAccounts) {
            const nickName = account.nick_name || account.deviceName || '未知昵称';
            const onlineTime = status.onlineTime || '未知在线时间';
            console.log(`${nickName} ${onlineTime}`);
        }
    }

    async getAppletCode(appId, licenseOrWxid) {
        if (this.protocolType === 'Niuzi') {
            return await this._getNiuziAppletCode(appId, licenseOrWxid);
        } else {
            return await this._getLegacyAppletCode(appId, licenseOrWxid);
        }
    }

    async _getNiuziAppletCode(appId, wxid) {
        const endpoints = ['/api/v1/wx/app/get/code', '/api/v1/wx/app/get/code/', '/api/v1/wx/get/code'];
        const payload = {
            wxid: wxid,
            appid: appId
        };
        
        let lastError = null;
        for (const endpoint of endpoints) {
            const url = `${this.wechatServer}${endpoint}`;
            try {
                const response = await axios.post(url, payload, { timeout: 20000 });
                const result = response.data;
                
                let code = null;
                if (result?.Data?.code) code = result.Data.code;
                else if (result?.data?.code) code = result.data.code;
                else if (result?.code) code = result.code;
                
                if (code && typeof code === 'string') {
                    return code;
                }
                
                lastError = new Error(`未找到code，服务端返回: ${JSON.stringify(result)}`);
            } catch (e) {
                lastError = e;
            }
        }
        throw new Error(`获取小程序Code失败: ${lastError ? (lastError.message || lastError) : '未知错误'}`);
    }

    async _getLegacyAppletCode(appId, license) {
        const url = `${this.wechatServer}/applet/JsLogin`;
        const payload = {
            AppId: appId,
            Data: "",
            Opt: 1,
            PackageName: "",
            SdkName: ""
        };
        
        try {
            const response = await axios.post(url, payload, { params: { key: license }, timeout: 60000 });
            const result = response.data;
            
            if (result.Code !== 200) {
                throw new Error(`获取小程序Code失败: ${result.Text || '未知错误'}`);
            }
            
            const data = result.Data || {};
            const code = data.Code;
            if (!code) {
                throw new Error('响应中未找到Code值');
            }
            
            return code;
        } catch (e) {
            throw new Error(`请求小程序Code失败: ${e.message}`);
        }
    }

    async getCodesForAllOnlineAccounts(appId) {
        const codes = {};
        const onlineAccounts = await this.getOnlineAccounts();

        if (this.protocolType === 'Niuzi') {
            let i = 1;
            for (const { account } of onlineAccounts) {
                const wxid = account.wxid;
                let baseNickName = account.nickname || account.nick_name || '未知昵称';

                if (!baseNickName.trim() || baseNickName.trim() === 'ㅤ') {
                    if (wxid) {
                        baseNickName = `账号_${wxid.slice(-6)}`;
                    } else {
                        baseNickName = `账号_${i}`;
                    }
                }
                
                let nickName = baseNickName;
                let counter = 1;
                while (codes[nickName] !== undefined) {
                    nickName = `${baseNickName}_${counter}`;
                    counter++;
                }

                if (!wxid) {
                    console.log(`账号 ${nickName} 缺少wxid，跳过`);
                    i++;
                    continue;
                }

                try {
                    const code = await this.getAppletCode(appId, wxid);
                    codes[nickName] = code;
                    console.log(`获取 ${nickName} 的Code成功: ${code}`);
                } catch (e) {
                    console.log(`获取 ${nickName} 的Code失败: ${e.message}`);
                    console.log(`提示：如果持续获取失败，账号 ${nickName} 可能需要重新登录`);
                }
                i++;
            }
        } else {
            let i = 1;
            for (const { account } of onlineAccounts) {
                const license = account.license || account.authKey;
                let baseNickName = account.nick_name || account.deviceName || '未知昵称';
                const deviceId = account.deviceId || '';

                if (!baseNickName.trim() || baseNickName.trim() === 'ㅤ') {
                    if (deviceId) {
                        baseNickName = `设备_${deviceId.slice(-6)}`;
                    } else {
                        baseNickName = `账号_${i}`;
                    }
                }
                
                let nickName = baseNickName;
                let counter = 1;
                while (codes[nickName] !== undefined) {
                    nickName = `${baseNickName}_${counter}`;
                    counter++;
                }

                if (!license) {
                    console.log(`账号 ${nickName} 缺少license/authKey，跳过`);
                    i++;
                    continue;
                }

                try {
                    const code = await this.getAppletCode(appId, license);
                    codes[nickName] = code;
                    console.log(`获取 ${nickName} 的Code成功: ${code}`);
                } catch (e) {
                    console.log(`获取 ${nickName} 的Code失败: ${e.message}`);
                    console.log(`提示：如果持续获取失败，账号 ${nickName} 可能需要重新登录`);
                }
                i++;
            }
        }

        return codes;
    }
}

/**
 * 获取所有在线微信账号的小程序登录Code
 * @param {string} appId - 小程序AppId
 * @returns {Promise<Object>} 账号昵称到Code的映射字典
 */
async function getWechatCodes(appId) {
    const getter = new WeChatCodeGetter();
    await getter.init();
    return await getter.getCodesForAllOnlineAccounts(appId);
}

/**
 * 打印当前在线账号状态
 */
async function printOnlineStatus() {
    const getter = new WeChatCodeGetter();
    await getter.init();
    await getter.printOnlineStatus();
}

/**
 * 为指定授权码获取小程序登录Code
 * @param {string} appId - 小程序AppId
 * @param {string} license - 微信账号授权码
 * @returns {Promise<string>} 小程序登录Code
 */
async function getSingleCode(appId, license) {
    const getter = new WeChatCodeGetter();
    await getter.init();
    try {
        return await getter.getAppletCode(appId, license);
    } catch (e) {
        console.log(`提示：如果持续获取失败，该账号可能需要重新登录`);
        throw e;
    }
}

module.exports = {
    WeChatCodeGetter,
    getWechatCodes,
    printOnlineStatus,
    getSingleCode
};
