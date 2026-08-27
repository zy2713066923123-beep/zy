require('./yyb.js'); // 自动同步 yyb_go 存活账号
/**
// name: 梦想家TSE
------------------------------------------
@Author: sm
@Date: 2026.07.24
@Description: 梦想家TSE 微信小程序每日签到（微信协议版，适配青龙）
cron: 20 12,00 * * *
变量名：WX_ID
变量值：微信账号（openid/wxid），多账号支持换行、& 分隔，必须配置

------------------------------------------

变量：
  WX_ID          (可选白名单) 微信账号，多账号换行/&分隔，留空自动拉取 yyb_go 所有存活账号
  WX_SERVER      yyb_go 统一协议服务地址（例如：http://127.0.0.1:8000）
  YYB_SERVER     (兼容别名) yyb_go 服务地址

WX_ID 格式：
  wxid#备注  多个换行
------------------------------------------
*/

const axios = require("axios");
const fs = require("fs");
const path = require("path");
// ====================== 账号（环境变量 WX_ID = wxid#备注，换行或&；留空自动从 yyb_go 拉取存活账号） ======================
let SERVERS = (process.env.WX_ID || "")
    .split(/\r?\n|&/)
    .map(s => s.trim())
    .filter(Boolean);
function parseYybGoEntry(rawValue) {
    const value = String(rawValue || "").trim();
    if (!value) return { server: "", ref: "" };
    const ref = value.split("#")[0].trim();
    return { server: "", ref };
}
async function getCode(server) {
    const __id = String(server).split("#")[0].trim();
    if (!__id) return null;
    try {
        return await getSingleCode(MINI_APP_ID, __id);
    } catch (e) {
        console.log(__id + " 获取code异常: " + (e && e.message ? e.message : e));
        return null;
    }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
let userIdx = 1;

const MINI_APP_ID = "wx696605f7e70c1e24";
const VERSION = "2.30.6";
const API_BASE = "https://smp-api.iyouke.com/dtapi";
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "mengxiangjia_token_cache.json");
try { fs.mkdirSync(path.dirname(TOKEN_CACHE_FILE), { recursive: true }); } catch (e) {}
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
    } catch (e) {
        return {};
    }
}

function writeTokenCache(cache) {
    try {
        fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
    } catch (e) {
        console.log(`写入token缓存失败: ${e.message || e}`);
    }
}

function maskToken(token = "") {
    const value = String(token || "");
    return value ? `${value.slice(0, 6)}***${value.slice(-6)}` : "";
}

function formatSignDate(date = new Date()) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}/${month}/${day}`;
}

function isTokenError(message = "") {
    return /401|403|token|登录|授权|未登录|invalid/i.test(String(message));
}

class Task {
    constructor(openid) {
        this.server = openid;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.index = userIdx++;
        this.openid = String(openid || "").trim();
        this.loginResult = {};
    }

    get accessToken() {
        return this.loginResult.access_token || this.loginResult.accessToken || "";
    }

    async run() {
        try {
            const cached = this.getCachedToken();
            if (cached?.access_token || cached?.accessToken) {
                this.loginResult = cached;
                console.log(`账号[${this.index}] 使用缓存token: ${maskToken(this.accessToken)}`);
                if (!(await this.checkToken())) {
                    this.removeCachedToken();
                    console.log(`账号[${this.index}] 缓存token失效，重新code登录`);
                }
            }

            if (!this.accessToken) {
                await this.loginByWxCode();
                if (!this.accessToken) return;
            }

            await this.getPointsInfo("签到前");
            await this.getSignConfig();
            const today = await this.getTodaySignItem();
            if (today?.daySignStatus === 2) {
                console.log(`账号[${this.index}] 今日已签到`);
            } else {
                await this.signIn(today?.dateStr);
            }
            await this.getPointsInfo("签到后");
        } catch (e) {
            console.log(`账号[${this.index}] 执行异常: ${e.message || e}`);
        }
    }

    getCachedToken() {
        const cache = readTokenCache();
        return cache[this.openid] || null;
    }

    saveCachedToken() {
        if (!this.accessToken) return;
        const cache = readTokenCache();
        cache[this.openid] = {
            ...this.loginResult,
            updatedAt: new Date().toISOString(),
        };
        writeTokenCache(cache);
    }

    removeCachedToken() {
        const cache = readTokenCache();
        if (cache[this.openid]) {
            delete cache[this.openid];
            writeTokenCache(cache);
        }
        this.loginResult = {};
    }

    headers(withToken = true) {
        const headers = {
            "User-Agent": USER_AGENT,
            "Referer": `https://servicewechat.com/${MINI_APP_ID}/5/page-frame.html`,
            "Accept": "application/json, text/plain, */*",
            "appId": MINI_APP_ID,
            "version": VERSION,
            "envVersion": "release",
        };
        if (withToken && this.accessToken) headers.Authorization = `Bearer ${this.accessToken}`;
        return headers;
    }

    async request({ method = "GET", apiPath, data = {}, params = {}, needToken = true }) {
        const options = {
            method,
            url: `${API_BASE}${apiPath}`,
            headers: this.headers(needToken),
            timeout: 15000,
            validateStatus: () => true,
        };
        if (method.toUpperCase() === "GET") options.params = params;
        else options.data = data;

        const { status, data: result } = await axios.request(options);
        if (status !== 200) throw new Error(`HTTP ${status}: ${typeof result === "string" ? result.slice(0, 200) : JSON.stringify(result)}`);
        if (result && Object.prototype.hasOwnProperty.call(result, "error") && Number(result.error) !== 0) {
            const err = new Error(result.errorMsg || result.error_msg || result.message || JSON.stringify(result));
            err.code = result.error;
            throw err;
        }
        return result;
    }

    async getWxCode() {
        return await getCode(this.server);
    }

    async loginByWxCode() {
        try {
            const code = await this.getWxCode();
            const data = await this.request({
                method: "POST",
                apiPath: "/appLogin",
                needToken: false,
                data: {
                    principal: code,
                    appType: 1,
                },
            });
            this.loginResult = data || {};
            this.saveCachedToken();
            console.log(`账号[${this.index}] 登录成功: userId=${data?.userId || ""} token=${maskToken(this.accessToken)}`);
        } catch (e) {
            console.log(`账号[${this.index}] 登录失败: ${e.message || e}`);
        }
    }

    async checkToken() {
        try {
            await this.getPointsInfo("缓存校验");
            return true;
        } catch (e) {
            return false;
        }
    }

    async getSignConfig() {
        try {
            const result = await this.request({ apiPath: "/pointsSign/config/query" });
            const data = result?.data || {};
            console.log(`账号[${this.index}] 签到配置: ${Number(data.signEnable) === 1 ? "已开启" : "未开启"} 日签${data.signReward ?? ""}积分`);
            return data;
        } catch (e) {
            console.log(`账号[${this.index}] 获取签到配置失败: ${e.message || e}`);
            return {};
        }
    }

    async getTodaySignItem() {
        try {
            const result = await this.request({
                apiPath: "/pointsSign/user/sign/list",
                params: { v4Flag: true },
            });
            const list = Array.isArray(result?.data) ? result.data : [];
            const today = list.find((item) => item?.isToday) || {};
            console.log(`账号[${this.index}] 今日签到状态: ${today.dateStr || ""} status=${today.daySignStatus ?? "未知"}`);
            return today;
        } catch (e) {
            console.log(`账号[${this.index}] 获取签到列表失败: ${e.message || e}`);
            return {};
        }
    }

    async getPointsInfo(label = "积分") {
        const result = await this.request({ apiPath: "/pointsSign/user/pointsInfo/query" });
        const data = result?.data || {};
        console.log(`账号[${this.index}] ${label}: ${data.pointsNums ?? "未知"}积分 连签${data.seriesDays ?? 0}天 今日${data.signTodayResult ? "已签" : "未签"}`);
        return data;
    }

    async signIn(dateStr) {
        const date = dateStr ? dateStr.replace(/-/g, "/") : formatSignDate();
        try {
            const result = await this.request({
                apiPath: "/pointsSign/user/sign",
                params: { date },
            });
            const data = result?.data || {};
            console.log(`账号[${this.index}] 签到成功: +${data.signReward ?? 0}积分${data.extraSignReward ? ` 额外+${data.extraSignReward}` : ""}`);
        } catch (e) {
            const message = String(e.message || e);
            if (/已签到|重复签到/.test(message)) {
                console.log(`账号[${this.index}] 今日已签到`);
                return;
            }
            console.log(`账号[${this.index}] 签到失败: ${message}`);
            if (isTokenError(message)) this.removeCachedToken();
        }
    }
}

!(async () => {
    // 未配置 WX_ID 时，自动从 yyb_go 拉取所有存活账号
    if (!SERVERS.length) {
        try {
            const _accs = await loadAccounts();
            SERVERS = _accs.map(a => a.openid || a.wxid || a._ref || String(a.id)).filter(Boolean);
        } catch (e) {
            console.log(`从 yyb_go 拉取账号失败: ${e.message || e}`);
        }
    }
    if (!SERVERS.length) {
        console.log(`未找到可用账号（WX_ID 未配置且 yyb_go 无存活账号）`);
        return;
    }
    for (const openid of SERVERS) {
        await new Task(openid).run();
    }
})()
    .catch((e) => console.log(e.message || e))