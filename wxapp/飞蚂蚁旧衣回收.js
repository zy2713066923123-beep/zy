require('./yyb.js'); // 自动同步 yyb_go 存活账号
// name: 飞蚂蚁旧衣回收
// cron: 16 17,05 * * *
class Env {
    constructor(name) {
        this.name = name;
        this.userList = [];
        this.userIdx = 1;
        this.logs = [];
        const originalLog = console.log;
        console.log = (...args) => {
            this.logs.push(args.join(" "));
            originalLog.apply(console, args);
        };
    }
    log(...args) { console.log(...args); this.logs.push(args.join(" ")); }
    async checkEnv(ckName) {
        const list = await global.resolveAccounts(ckName);
        this.userList = list;
        if (!this.userList.length) console.log('未找到环境变量 WX_ID，且 yyb_go 无存活账号');
    }
    async done() {
        try {
            const notify = require('../sendNotify');
            await notify.sendNotify(this.name, this.logs.join('\n'));
        } catch (e) {
            console.log('通知发送失败', e);
        }
    }
}

const axios = require("axios");
const qs = require('querystring');

// 代理模块(https/socks/http-proxy-agent v9+)是 ESM-only，CommonJS 下 require 会报 ERR_REQUIRE_ESM
// 改用动态 import() 加载（保留完整代理功能）
let SocksProxyAgent, HttpsProxyAgent, HttpProxyAgent;
async function loadProxyAgents() {
    if (SocksProxyAgent) return;
    const sm = await import('socks-proxy-agent');
    const hm = await import('https-proxy-agent');
    const hpm = await import('http-proxy-agent');
    SocksProxyAgent = sm.SocksProxyAgent || sm.default;
    HttpsProxyAgent = hm.HttpsProxyAgent || hm.default;
    HttpProxyAgent = hpm.HttpProxyAgent || hpm.default;
}

const getWxCode = (wxid, appid) => getSingleCode(appid, String(wxid).split('#')[0].trim());

const $ = new Env("飞蚂蚁旧衣回收");

// 强制全局禁用系统代理环境变量，避免干扰
delete process.env.HTTP_PROXY;
delete process.env.HTTPS_PROXY;
delete process.env.http_proxy;
delete process.env.https_proxy;

// ===================== 配置项 =====================
// PushPlus 通知Token（青龙环境变量）
const PLUSPLUS_TOKEN = process.env.PLUSPLUS_TOKEN || "";

// 品赞代理配置（青龙环境变量）
const PROXY_API = process.env.PROXY_API || ""; // 代理提取API链接
const PROXY_TYPE = process.env.PROXY_TYPE || "http"; // 代理类型: http 或 socks5
const PROXY_RETRY_TIMES = 3; // 单个账号代理获取重试次数
const PROXY_VALIDATE_URL = "http://httpbin.org/ip"; // 代理验证地址
// 核心开关：每个账号独立获取专属代理（true=每个账号一个新IP，false=所有账号共用一个IP）
const ENABLE_PER_ACCOUNT_PROXY = true;
// 账号间代理获取间隔（毫秒，避免频繁调用代理API被限流）
const PROXY_FETCH_INTERVAL = 3000;
// 兜底开关：代理请求失败后，自动切换直连重试
const ENABLE_DIRECT_FALLBACK = true;
// 调试开关：开启后打印完整请求和响应
const DEBUG_MODE = false;
// 固定配置（已修正为最新正确值）
const APPID = "wx501990400906c9ff"; // 飞蚂蚁最新APPID
const PLATFORM_KEY = "F2EE24892FBF66F0AFF8C0EB532A9394"; // 固定平台密钥
const APP_VERSION = "V2.00.01"; // 应用版本号
// UA池（已添加Windows微信小程序UA）
const USER_AGENT_LIST = [
    "Mozilla/5.0 (Linux; Android 14; 2512BPNDAC Build/UKQ1.230917.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.153 Mobile Safari/537.36 XWEB/1460043 MMWEBSDK/20251006 MiniProgramEnv/android",
    "Mozilla/5.0 (Linux; Android 13; Redmi K60 Build/TKQ1.221114.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0.6723.102 Mobile Safari/537.36 XWEB/1300003 MMWEBSDK/20250901 MiniProgramEnv/android",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541885) XWEB/19463"
];

// ===================== 工具函数 =====================
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function random(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
}

function getUA() {
    return USER_AGENT_LIST[Math.floor(Math.random() * USER_AGENT_LIST.length)];
}

// 调试日志函数
function debugLog(title, data) {
    if (DEBUG_MODE) {
        $.log(`\n[调试] ${title}:`);
        $.log(JSON.stringify(data, null, 2));
    }
}

// ====================== 品赞IP代理系统（每个账号独立获取）======================
function parseProxyResponse(text) {
    text = text.trim();
    if (!text) return null;
    try {
        const data = JSON.parse(text);
        let proxyObj = null;
        if (data.data && Array.isArray(data.data) && data.data.length > 0) {
            proxyObj = data.data[0];
        } else if (data.ip && data.port) {
            proxyObj = data;
        } else if (data.result && data.result.ip && data.result.port) {
            proxyObj = data.result;
        }
        if (proxyObj) {
            return {
                host: proxyObj.ip,
                port: proxyObj.port,
                username: proxyObj.user || proxyObj.username || "",
                password: proxyObj.pass || proxyObj.password || ""
            };
        }
    } catch (e) {}
    if (text.includes(":")) {
        const parts = text.split(":");
        if (parts.length >= 2) {
            return {
                host: parts[0],
                port: parseInt(parts[1]),
                username: parts[2] || "",
                password: parts[3] || ""
            };
        }
    }
    return null;
}

function buildProxyAgent(proxyInfo) {
    if (!proxyInfo) return null;
    const { host, port, username, password } = proxyInfo;
    let auth = "";
    if (username && password) {
        auth = `${encodeURIComponent(username)}:${encodeURIComponent(password)}@`;
    }
    try {
        if (PROXY_TYPE === "socks5") {
            const proxyUrl = `socks5://${auth}${host}:${port}`;
            $.log(`生成SOCKS5代理：socks5://${auth}${host}:${port}`);
            return {
                httpAgent: new SocksProxyAgent(proxyUrl),
                httpsAgent: new SocksProxyAgent(proxyUrl)
            };
        } else {
            const httpProxyUrl = `http://${auth}${host}:${port}`;
            const httpsProxyUrl = `http://${auth}${host}:${port}`;
            $.log(`生成HTTP代理：${httpProxyUrl}`);
            return {
                httpAgent: new HttpProxyAgent(httpProxyUrl),
                httpsAgent: new HttpsProxyAgent(httpsProxyUrl)
            };
        }
    } catch (e) {
        $.log(`生成代理Agent失败：${e.message}`);
        return null;
    }
}

async function validateProxy(agent) {
    if (!agent) return false;
    try {
        const axiosConfig = {
            method: "get",
            url: PROXY_VALIDATE_URL,
            timeout: 15000,
            ...agent,
            maxRedirects: 5
        };
        const response = await axios(axiosConfig);
        const isSuccess = response.status === 200;
        if (isSuccess) {
            $.log(`代理验证通过，出口IP：${response.data?.origin || "未知"}`);
        }
        return isSuccess;
    } catch (e) {
        $.log(`代理验证失败，原因：${e.message}`);
        return false;
    }
}

async function getValidProxy(accountName) {
    if (!PROXY_API) {
        $.log(`[${accountName}] 未配置代理API，使用直连`);
        return null;
    }
    $.log(`[${accountName}] 正在从品赞API获取专属代理 (${PROXY_TYPE})...`);
    for (let i = 0; i < PROXY_RETRY_TIMES; i++) {
        try {
            const response = await axios.get(PROXY_API, {
                timeout: 15000,
                proxy: false
            });
            const proxyInfo = parseProxyResponse(response.data);
            if (!proxyInfo) {
                $.log(`[${accountName}] 第${i+1}次获取代理失败：响应格式无法解析`);
                continue;
            }
            $.log(`[${accountName}] 提取到专属代理：${proxyInfo.host}:${proxyInfo.port}`);
            const agent = buildProxyAgent(proxyInfo);
            const isValid = await validateProxy(agent);
            if (isValid) {
                return agent;
            } else {
                $.log(`[${accountName}] 第${i+1}次获取的代理不可用，正在重试...`);
            }
        } catch (e) {
            $.log(`[${accountName}] 第${i+1}次获取代理异常：${e.message}`);
        }
        if (i < PROXY_RETRY_TIMES - 1) {
            await new Promise(r => setTimeout(r, 2000));
        }
    }
    $.log(`[${accountName}] 连续多次获取代理失败，使用直连`);
    return null;
}

function addProxyToAxiosConfig(axiosConfig, proxyAgent) {
    if (!proxyAgent) return axiosConfig;
    return {
        ...axiosConfig,
        ...proxyAgent,
        timeout: axiosConfig.timeout || 20000
    };
}

// ===================== PushPlus通知函数 =====================
async function sendPlusPlusNotification(title, content) {
    if (!PLUSPLUS_TOKEN) return;
    try {
        await axios.post("https://www.pushplus.plus/send", {
            token: PLUSPLUS_TOKEN,
            title: title,
            content: content,
            template: "txt"
        }, { timeout: 5000 });
        $.log("通知推送成功");
    } catch (e) {
        $.log("通知推送失败：", e.message);
    }
}

// ===================== 业务逻辑函数 =====================
// 登录获取token 【支持手机号授权：phone_code + mini_scene】
async function wxLogin(jsCode, UA, proxyAgent, accountAlias, phone_code = '', mini_scene = '1256') {
    const loginData = {
        code: jsCode,
        platformKey: PLATFORM_KEY,
        version: APP_VERSION,
        vital: '',
        partner_platform_key: '',
        mini_scene: mini_scene
    };
    if (phone_code) {
        loginData.phone_code = phone_code;
    }
    const baseConfig = {
        method: 'post',
        url: 'https://openapp.fmy90.com/auth/wx/login',
        headers: {
            'Host': 'openapp.fmy90.com',
            'Connection': 'keep-alive',
            'device-version': 'Windows 10 x64',
            'User-Agent': UA,
            'xweb_xhr': '1',
            'Content-Type': 'application/x-www-form-urlencoded',
            'device-model': 'microsoft',
            'Accept': '*/*',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': `https://servicewechat.com/${APPID}/506/page-frame.html`,
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'zh-CN,zh;q=0.9'
        },
        data: qs.stringify(loginData),
        timeout: 20000
    };

    debugLog("登录请求配置", baseConfig);

    try {
        let response = null;
        if (proxyAgent) {
            $.log(`[${accountAlias}] 正在使用专属代理发起登录请求...`);
            try {
                response = await axios(addProxyToAxiosConfig(baseConfig, proxyAgent));
            } catch (e) {
                $.log(`[${accountAlias}] 代理登录失败，切换直连重试...`);
                response = await axios({ ...baseConfig, proxy: false });
            }
        } else {
            response = await axios({ ...baseConfig, proxy: false });
        }

        debugLog("登录完整响应", response.data);
        return response.data;
    } catch (e) {
        $.log(`[${accountAlias}] 登录异常: ${e.message}`);
        if (e.response) {
            debugLog("登录错误响应", e.response.data);
        }
        return null;
    }
}

// 通用请求 【已添加调试日志】
async function commonPost(url, body, token, UA, proxyAgent, accountAlias) {
    const baseConfig = {
        method: 'post',
        url: `https://openapp.fmy90.com${url}`,
        headers: {
            'Host': 'openapp.fmy90.com',
            'Connection': 'keep-alive',
            'device-version': 'Windows 10 x64',
            'User-Agent': UA,
            'xweb_xhr': '1',
            'Content-Type': 'application/json',
            'device-model': 'microsoft',
            'Accept': '*/*',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': `https://servicewechat.com/${APPID}/506/page-frame.html`,
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'authorization': `Bearer ${token}`
        },
        data: body,
        timeout: 20000
    };

    debugLog(`业务请求${url}配置`, { ...baseConfig, data: body });

    try {
        let response = null;
        if (proxyAgent) {
            try {
                response = await axios(addProxyToAxiosConfig(baseConfig, proxyAgent));
            } catch (e) {
                $.log(`[${accountAlias}] 代理请求失败，切换直连重试...`);
                response = await axios({ ...baseConfig, proxy: false });
            }
        } else {
            response = await axios({ ...baseConfig, proxy: false });
        }

        debugLog(`业务请求${url}响应`, response.data);
        return response.data;
    } catch (e) {
        $.log(`[${accountAlias}] 请求异常: ${e.message}`);
        if (e.response) {
            debugLog(`业务请求${url}错误响应`, e.response.data);
        }
        return null;
    }
}

// 从登录响应中提取 token（兼容多种结构）
function extractToken(login) {
    if (!login) return null;
    if (login.data?.userInfo?.token) return login.data.userInfo.token;
    if (login.data?.token) return login.data.token;
    if (login.token) return login.token;
    if (login.data?.access_token) return login.data.access_token;
    return null;
}

// 验证 token 有效性并获取余额（总获得 - 总使用）
async function getAccountBalance(token, UA, proxyAgent, accountAlias) {
    const headers = {
        'Host': 'openapp.fmy90.com',
        'Connection': 'keep-alive',
        'device-version': 'Windows 10 x64',
        'User-Agent': UA,
        'xweb_xhr': '1',
        'Content-Type': 'application/json',
        'device-model': 'microsoft',
        'Accept': '*/*',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        'Referer': `https://servicewechat.com/${APPID}/506/page-frame.html`,
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'authorization': `Bearer ${token}`
    };
    const base = { method: 'get', headers, timeout: 20000 };
    try {
        const earn = await axios(addProxyToAxiosConfig({ ...base, url: 'https://openapp.fmy90.com/user/new/beans/info', params: { type: '1', version: APP_VERSION, platformKey: PLATFORM_KEY, mini_scene: '1027', partner_ext_infos: '' } }, proxyAgent));
        const use = await axios(addProxyToAxiosConfig({ ...base, url: 'https://openapp.fmy90.com/user/new/beans/info', params: { type: '2', version: APP_VERSION, platformKey: PLATFORM_KEY, mini_scene: '1027', partner_ext_infos: '' } }, proxyAgent));
        const ed = earn.data || {};
        const ud = use.data || {};
        if (ed.code != 200 && ed.code != 0) return { valid: false, balance: 0, msg: `总积分接口错误: ${ed.message || '未知'}` };
        const totalEarned = parseInt(ed.data?.totalCount || 0);
        const totalUsed = parseInt(ud.data?.totalCount || 0);
        return { valid: true, balance: totalEarned - totalUsed, msg: `总得:${totalEarned}, 总用:${totalUsed}` };
    } catch (e) {
        return { valid: false, balance: 0, msg: `验证异常: ${e.message}` };
    }
}

// 获取积分统计（总获得、总使用、当前余额、今日获得）
async function getStatistics(token, UA, proxyAgent, accountAlias) {
    const stats = { total_earned: 0, total_used: 0, current_balance: 0, income_today: 0 };
    const headers = {
        'Host': 'openapp.fmy90.com',
        'Connection': 'keep-alive',
        'device-version': 'Windows 10 x64',
        'User-Agent': UA,
        'xweb_xhr': '1',
        'Content-Type': 'application/json',
        'device-model': 'microsoft',
        'Accept': '*/*',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        'Referer': `https://servicewechat.com/${APPID}/506/page-frame.html`,
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'authorization': `Bearer ${token}`
    };
    const base = { method: 'get', headers, timeout: 20000 };
    try {
        const earn = await axios(addProxyToAxiosConfig({ ...base, url: 'https://openapp.fmy90.com/user/new/beans/info', params: { type: '1', version: APP_VERSION, platformKey: PLATFORM_KEY, mini_scene: '1027', partner_ext_infos: '' } }, proxyAgent));
        if (earn?.data?.code == 200 || earn?.data?.code == 0) stats.total_earned = parseInt(earn.data.data?.totalCount || 0);
        const use = await axios(addProxyToAxiosConfig({ ...base, url: 'https://openapp.fmy90.com/user/new/beans/info', params: { type: '2', version: APP_VERSION, platformKey: PLATFORM_KEY, mini_scene: '1027', partner_ext_infos: '' } }, proxyAgent));
        if (use?.data?.code == 200 || use?.data?.code == 0) stats.total_used = parseInt(use.data.data?.totalCount || 0);
        stats.current_balance = stats.total_earned - stats.total_used;
        const now = new Date();
        const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
        const log = await axios(addProxyToAxiosConfig({ ...base, url: 'https://openapp.fmy90.com/user/beans/log', params: { pageSize: '20', type: '1', platformKey: PLATFORM_KEY } }, proxyAgent));
        if (log?.data?.code == 200 || log?.data?.code == 0) {
            const list = log.data.data?.data || [];
            for (const item of list) {
                if (String(item.addTime || '').includes(todayStr)) {
                    stats.income_today += Math.abs(parseInt(item.beanNum || 0));
                }
            }
        }
    } catch (e) {
        $.log(`[${accountAlias}] 统计异常: ${e.message}`);
    }
    return stats;
}

// 获取商品列表（按兑换积分升序）
async function fetchProductList(token, UA, proxyAgent) {
    const headers = {
        'Host': 'openapp.fmy90.com',
        'Connection': 'keep-alive',
        'device-version': 'Windows 10 x64',
        'User-Agent': UA,
        'xweb_xhr': '1',
        'Content-Type': 'application/json',
        'device-model': 'microsoft',
        'Accept': '*/*',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        'Referer': `https://servicewechat.com/${APPID}/506/page-frame.html`,
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'authorization': `Bearer ${token}`
    };
    try {
        const resp = await axios(addProxyToAxiosConfig({
            method: 'get',
            url: 'https://openapp.fmy90.com/shop/new/list',
            headers,
            params: { page: 1, pageSize: 12, goodsCategoryId: '', st: 0, ps: '0,99999', version: APP_VERSION, platformKey: PLATFORM_KEY, mini_scene: '1000', partner_ext_infos: '' },
            timeout: 20000
        }, proxyAgent));
        const data = resp?.data || {};
        if (data.code != 200 && data.code != 0) return null;
        const goods = data.data?.goods_data?.data || [];
        return goods.map(g => ({ integralValue: g.integralValue || 0, goodsInventory: g.goodsInventory || 0, goodsTitle: g.goodsTitle || '未知商品' }));
    } catch (e) {
        $.log(`获取商品列表异常: ${e.message}`);
        return null;
    }
}

// 打印商品列表（按兑换积分升序）
function printProductList(products) {
    if (!products || !products.length) {
        $.log('\n⚠️ 无商品数据');
        return;
    }
    const sorted = [...products].sort((a, b) => a.integralValue - b.integralValue);
    $.log('\n' + '='.repeat(80));
    $.log('📦 飞蚂蚁商城商品列表（按兑换积分升序）');
    $.log('='.repeat(80));
    $.log(`${'序号'.padEnd(6)} ${'兑换积分'.padEnd(10)} ${'库存'.padEnd(10)} 商品名称`);
    $.log('-'.repeat(80));
    sorted.forEach((p, idx) => {
        const stock = p.goodsInventory > 0 ? String(p.goodsInventory) : '已售罄';
        $.log(`${String(idx + 1).padEnd(6)} ${String(p.integralValue).padEnd(10)} ${stock.padEnd(10)} ${p.goodsTitle}`);
    });
    $.log('='.repeat(80));
}

// 单个账号执行：参数改为纯wxid字符串，保留品赞代理和PushPlus逻辑
async function runAccount(wxid, globalProxyAgent) {
    // 从 wxid 中提取别名（支持 wxid#alias 格式）
    const alias = wxid.includes('#') ? wxid.split('#')[1]?.trim() || wxid : wxid;
    let result = {
        alias: alias,
        success: false,
        signMsg: "",
        exchangeMsgs: [],
        error: "",
        proxyStatus: "未使用代理",
        token: null,
        stats: null
    };
    $.log(`\n===== 飞蚂蚁旧衣回收 - ${alias} 账号 =====`);
    const UA = getUA();
    let proxyAgent = globalProxyAgent;
    if (ENABLE_PER_ACCOUNT_PROXY) {
        proxyAgent = await getValidProxy(alias);
        result.proxyStatus = proxyAgent ? "使用专属代理" : "使用直连";
        await sleep(PROXY_FETCH_INTERVAL);
    }
    try {
        let startDelay = random(2000, 6000);
        $.log(`[${alias}] 启动延迟 ${startDelay / 1000}s`);
        await sleep(startDelay);

        // ===== 本地存储 token，自动续期（过期/失效则重新登录）=====
        let token = null;
        const cached = getCachedToken('feimayi', wxid, { maxAgeMs: 6 * 3600 * 1000 });
        if (cached) {
            token = cached.token;
            $.log(`[${alias}] 命中token缓存，验证有效性...`);
            // 用余额接口验证 token 是否仍有效（CK 过期则重新登录）
            const check = await getAccountBalance(token, UA, proxyAgent, alias);
            if (check.valid) {
                $.log(`[${alias}] 缓存token有效（${check.msg}），跳过取code`);
            } else {
                $.log(`[${alias}] 缓存token已失效（${check.msg}），重新登录...`);
                token = null;
            }
        }

        if (!token) {
            // 1. 获取code（wxid 标准 yyb.js 模块）
            let code = await getWxCode(wxid, APPID);
            if (!code) {
                result.error = "获取code失败";
                return result;
            }

            // 2. 登录获取token
            let login = await wxLogin(code, UA, proxyAgent, alias);
            if (!login) {
                result.error = "登录请求无响应";
                $.log(`[${alias}] 登录失败：无响应数据`);
                return result;
            }

            if (login.code != 200) {
                result.error = `登录失败：${login.message || "未知错误"}`;
                $.log(`[${alias}] ${result.error}`);
                return result;
            }

            token = extractToken(login);

            // 3. 自动授权：登录未返回 token 或 token 无效时，走手机号授权流程
            if (!token) {
                $.log(`[${alias}] 登录未返回token，尝试手机号授权...`);
                const phoneCode = await getSinglePhoneNumber(APPID, String(wxid).split('#')[0].trim());
                if (!phoneCode) {
                    result.error = "获取手机号授权code失败";
                    $.log(`[${alias}] ${result.error}`);
                    return result;
                }
                // 授权后重新取 code 并登录（mini_scene=1008）
                const newCode = await getWxCode(wxid, APPID);
                if (!newCode) {
                    result.error = "授权后重新取code失败";
                    $.log(`[${alias}] ${result.error}`);
                    return result;
                }
                $.log(`[${alias}] 已获取手机号授权，重新登录...`);
                const login2 = await wxLogin(newCode, UA, proxyAgent, alias, phoneCode, '1008');
                if (!login2 || login2.code != 200) {
                    result.error = `授权后登录失败：${login2?.message || "无响应"}`;
                    $.log(`[${alias}] ${result.error}`);
                    return result;
                }
                token = extractToken(login2);
                if (!token) {
                    result.error = "授权后仍无法提取token";
                    $.log(`[${alias}] ${result.error}`);
                    return result;
                }
            }

            $.log(`[${alias}] 登录成功，获取到有效token`);
            debugLog("提取到的token", token);
            saveCachedToken('feimayi', wxid, token);
        }
        await sleep(random(3000, 8000));

        // 3. 签到
        let sign = await commonPost('/sign/new/do', {
            "version": APP_VERSION,
            "platformKey": PLATFORM_KEY,
            "mini_scene": 1089,
            "partner_ext_infos": ""
        }, token, UA, proxyAgent, alias);
        if (sign?.code == 200) {
            result.signMsg = `签到成功：${sign.message}`;
            $.log(`[${alias}] 签到成功：${sign.message}`);
        } else if (sign?.code == 400 && /已经签到|已签到|签到过|今日已/.test(sign?.message || "")) {
            // 业务幂等：当天已签到过，视为已完成，不报错
            result.signMsg = `今日已签到（${sign.message}），无需重复签到`;
            $.log(`[${alias}] 今日已签到：${sign.message}`);
        } else {
            result.signMsg = `签到失败：${sign?.message || "未知错误"}`;
            $.log(`[${alias}] 签到失败：${sign?.message || "未知错误"}`);
        }
        await sleep(random(2000, 5000));

        // 4. 步数兑换（循环3次）
        for (let i = 0; i < 3; i++) {
            $.log(`[${alias}] 开始第${i+1}次步数兑换（50000步）...`);
            let exchange = await commonPost('/step/exchange', {
                "steps": 50000,
                "version": APP_VERSION,
                "platformKey": PLATFORM_KEY,
                "mini_scene": 1089,
                "partner_ext_infos": ""
            }, token, UA, proxyAgent, alias);
            if (exchange?.code == 200) {
                let msg = `第${i+1}次步数兑换成功：${exchange.message}`;
                result.exchangeMsgs.push(msg);
                $.log(`[${alias}] ${msg}`);
            } else if (exchange?.code == 400 && /每天最多兑换|兑换次数|已兑换|次数已用完|今日已兑换/.test(exchange?.message || "")) {
                // 业务幂等：当天兑换额度已用完，视为已完成，跳出循环避免无谓请求
                let msg = `今日步数兑换已达上限（${exchange.message}），无需重复执行`;
                result.exchangeMsgs.push(msg);
                $.log(`[${alias}] ${msg}`);
                break;
            } else {
                let msg = `第${i+1}次步数兑换失败：${exchange?.message || "未知错误"}`;
                result.exchangeMsgs.push(msg);
                $.log(`[${alias}] ${msg}`);
            }
            if (i < 2) {
                await sleep(random(3000, 5000));
            }
        }

        // 5. 积分统计（总获得、总使用、当前余额、今日获得）
        const stats = await getStatistics(token, UA, proxyAgent, alias);
        result.stats = stats;
        result.token = token;
        $.log(`[${alias}] 积分统计：总获得 ${stats.total_earned} | 总使用 ${stats.total_used} | 当前余额 ${stats.current_balance} | 今日获得 +${stats.income_today}`);

        result.success = true;
        $.log(`[${alias}] 账号执行完成`);
    } catch (e) {
        result.error = `执行异常：${e.message}`;
        $.log(`[${alias}] 执行异常：`, e.message);
        $.log(`[${alias}] 异常堆栈：`, e.stack);
    }
    return result;
}

// ===================== 主程序 =====================
(async () => {
  await $.checkEnv("WX_ID");
    $.log('===== 飞蚂蚁旧衣回收动态code签到（调试版）=====\n');
    $.log('调试模式已开启，将打印完整请求和响应数据\n');

    // 预加载 ESM 代理模块（动态 import）——仅在真正需要代理时才加载
    if (PROXY_API) {
        try {
            await loadProxyAgents();
        } catch (e) {
            $.log(`代理模块加载失败，将使用直连：${e.message}`);
        }
    } else {
        $.log('未配置代理API（PROXY_API），跳过代理模块加载，全程使用直连');
    }

    let globalProxyAgent = null;
    if (!ENABLE_PER_ACCOUNT_PROXY) {
        globalProxyAgent = await getValidProxy("全局共用");
    }
    const results = [];
    for (const wxid of $.userList) {
        const res = await runAccount(wxid, globalProxyAgent);
        results.push(res);
        await sleep(2000);
    }

    // 汇总结果并推送
    let notifyContent = "### 飞蚂蚁旧衣回收多账号任务执行结果\n";
    results.forEach(res => {
        notifyContent += `\n#### ${res.alias}
- 代理状态：${res.proxyStatus}
- 执行状态：${res.success ? "成功" : "失败"}
`;
        if (res.success) {
            notifyContent += `- 签到结果：${res.signMsg}
- 步数兑换结果：
`;
            res.exchangeMsgs.forEach(msg => {
                notifyContent += `  - ${msg}
`;
            });
            if (res.stats) {
                notifyContent += `- 积分统计：总获得 ${res.stats.total_earned} | 总使用 ${res.stats.total_used} | 当前余额 ${res.stats.current_balance} | 今日获得 +${res.stats.income_today}
`;
            }
        } else {
            notifyContent += `- 失败原因：${res.error}
`;
        }
    });
    await sendPlusPlusNotification("飞蚂蚁旧衣回收任务完成", notifyContent);

    // 达标提醒：CK过期 或 余额 > 1200 时聚合推送
    const targetAliases = [];
    results.forEach(res => {
        const isExpired = !res.success && /token|认证|无效|过期|登录失败/.test(res.error || "");
        const isHighBalance = res.stats && res.stats.current_balance > 1200;
        if (isExpired || isHighBalance) targetAliases.push(res.alias);
    });
    if (targetAliases.length) {
        const pushTitle = "飞蚂蚁达标提醒";
        const pushContent = `以下账号已达标（CK过期 或 余额>1200）：\n${targetAliases.join("、")}`;
        $.log(`\n📢 检测到 ${targetAliases.length} 个达标账号: ${targetAliases.join(", ")}`);
        await sendPlusPlusNotification(pushTitle, pushContent);
    }

    // 商品列表打印（使用第一个成功账号的 token）
    const firstValid = results.find(r => r.success && r.token);
    if (firstValid) {
        $.log("\n📦 正在获取商品列表...");
        const products = await fetchProductList(firstValid.token, getUA(), globalProxyAgent);
        if (products) {
            printProductList(products);
        } else {
            $.log("⚠️ 获取商品列表失败");
        }
    }

    $.log('\n===== 所有账号执行完成 =====');

    await $.done();
})();