// cron: 20 11,14 * * * cron: 54 12,16 * * *

class Env {
    constructor(name) { this.name = name; this.userList = []; this.userIdx = 1; this.logs = []; const originalLog = console.log; console.log = (...args) => { this.logs.push(args.join(" ")); originalLog.apply(console, args); }; }
    log(...args) { console.log(...args); this.logs.push(args.join(" ")); }
    checkEnv(ckName) {
        const val = process.env.WX_ID || process.env[ckName];
        if (val) this.userList = val.split(/[\n&]+/).map(v => String(v).split('#')[0].trim()).filter(Boolean);
        else console.log('未找到环境变量 WX_ID');
    }
    async done() { try { const notify = require('./sendNotify'); await notify.sendNotify(this.name, this.logs.join('\n')); } catch(e) { console.log('通知发送失败', e); } }
}
/*
------------------------------------------
@Author: sm
@Date: 2026.06.01
@Description: 飞鹤微信小程序签到
cron: 33 10,23 * * *
变量名：feihe
变量值：wx_server 里的 openid/账号标识，多账号用 & 或换行
  wxid#备注  多个换行
------------------------------------------

变量：
  WECHAT_SERVER  微信协议服务地址，默认 http://192.168.6.222:8011
  WX_ID         微信账号，多账号支持换行、& 分隔，必须配置

WX_ID 格式：
  wxid#备注  多个换行
*/


const { getSingleCode } = require('./getCode.js');
const getWxCode = (wxid, appid) => getSingleCode(appid, String(wxid).split('#')[0].trim());
const $ = new Env("飞鹤微信小程序签到");
const axios = require("axios");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const MINI_APP_ID = "wx4205ec55b793245e";
const API_BASE = "https://www.feihevip.com";
const APP_ID = "xmyx";
const APP_KEY = "TwUQ01lKS1Km5zlV2f7amsZc5EQYkTbv";
const SIGN_TASK_TYPE = "DJSYQD";
const TOKEN_CACHE_FILE = path.join(__dirname, "feihe_token_cache.json");
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

let ckName = "WX_ID";

function readCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
    } catch (e) {
        return {};
    }
}

function writeCache(cache) {
    try {
        fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
    } catch (e) {
        $.log(`写入token缓存失败: ${e.message || e}`);
    }
}

function maskToken(token = "") {
    if (!token) return "";
    return token.length > 16 ? `${token.slice(0, 8)}***${token.slice(-8)}` : `${token.slice(0, 4)}***`;
}

function randomString(length) {
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    let result = "";
    for (let i = 0; i < length; i++) {
        result += chars[Math.floor(Math.random() * chars.length)];
    }
    return result;
}

function md5Upper(text) {
    return crypto.createHash("md5").update(text).digest("hex").toUpperCase();
}

function buildSignedHeaders({ data = null, token = "" } = {}) {
    const headers = {
        fhAppid: APP_ID,
        fhNonceStr: randomString(16),
        fhTimestamp: Math.floor(Date.now() / 1000),
        token,
        source: 1,
        "Content-Type": "application/json",
        OrderUpdate: 1,
        visit: "",
    };
    const dataSignValue = data && typeof data === "object" ? JSON.stringify(data) : data ? String(data) : "";
    const signKeys = ["fhAppid", "fhNonceStr", "fhTimestamp", dataSignValue].sort();
    const signText = signKeys.reduce((text, key) => {
        if (Object.prototype.hasOwnProperty.call(headers, key)) {
            return text + key + headers[key];
        }
        return text + key;
    }, "");

    return {
        ...headers,
        fhSign: md5Upper(signText + APP_KEY),
        Referer: `https://servicewechat.com/${MINI_APP_ID}/420/page-frame.html`,
        "User-Agent": USER_AGENT,
        Accept: "application/json, text/plain, */*",
    };
}

function buildUrl(apiPath, query = {}) {
    const params = new URLSearchParams();
    Object.entries(query || {}).forEach(([key, value]) => {
        if (value !== undefined && value !== null) params.append(key, String(value));
    });
    return `${API_BASE}${apiPath}${params.toString() ? `?${params.toString()}` : ""}`;
}

class Task {
    constructor(account) {
        this.index = $.userIdx++;
        this.account = String(account || "").split('#')[0].trim();
        this.token = "";
        this.userInfo = {};
    }

    async run() {
        const cached = this.getCachedToken();
        if (cached) {
            this.token = cached.token || "";
            $.log(`账号[${this.index}] 使用缓存token: ${maskToken(this.token)}`);
            if (!(await this.checkToken())) {
                $.log(`账号[${this.index}] 缓存token失效，重新code登录`);
                this.removeCachedToken();
                this.token = "";
            }
        }

        if (!this.token) {
            await this.loginByCode();
        }
        if (!this.token) return;

        await this.getIndexInfo();
        await this.signIn();
    }

    getCachedToken() {
        const cache = readCache();
        return cache[this.account] || null;
    }

    saveCachedToken() {
        if (!this.token) return;
        const cache = readCache();
        cache[this.account] = {
            token: this.token,
            userInfo: this.userInfo,
            updatedAt: new Date().toISOString(),
        };
        writeCache(cache);
    }

    removeCachedToken() {
        const cache = readCache();
        if (cache[this.account]) {
            delete cache[this.account];
            writeCache(cache);
        }
    }

    async request({ method = "GET", apiPath, query = {}, data = null, token = this.token, allowFail = false }) {
        const options = {
            method,
            url: buildUrl(apiPath, query),
            headers: buildSignedHeaders({ data: method === "GET" ? null : data, token }),
            timeout: 15000,
            validateStatus: () => true,
        };
        if (method !== "GET") options.data = data || {};

        const { status, data: result } = await axios.request(options);
        const ok = status === 200 && String(result?.code) === "200";
        if (!ok && !allowFail) {
            throw new Error(`HTTP ${status} ${JSON.stringify(result)}`);
        }
        return result;
    }

    /** 通过 getCode.js 统一接口获取微信 login code */
    async getWxCode() {
        return getSingleCode(MINI_APP_ID, this.openid);
    }

    async loginByCode() {
        const code = await this.getWxCode();
        const result = await this.request({
            apiPath: "/api/starMember/getUserToken",
            query: { code },
            token: "",
        });
        const data = result.data || {};
        this.token = result.token || data.token || "";
        this.userInfo = {
            crmId: data.crmId,
            openId: data.openId,
            unionId: data.unionId,
            loginStatus: data.loginStatus,
            expireTime: data.expireTime,
        };
        if (!this.token) throw new Error(`登录成功但未返回token: ${JSON.stringify(result)}`);
        this.saveCachedToken();
        $.log(`账号[${this.index}] code登录成功: ${data.crmId || data.openId || ""} token=${maskToken(this.token)}`);
    }

    async checkToken() {
        try {
            const result = await this.request({
                method: "POST",
                apiPath: "/api/structures/index",
                data: { id: "" },
                allowFail: true,
            });
            return String(result?.code) === "200";
        } catch (e) {
            return false;
        }
    }

    async getIndexInfo() {
        const result = await this.request({
            method: "POST",
            apiPath: "/api/structures/index",
            data: { id: "" },
            allowFail: true,
        });
        if (String(result?.code) === "200") {
            const signModule = (result.data?.modules || []).find((item) => String(item.moduleType) === "17");
            $.log(`账号[${this.index}] 首页签到入口: ${signModule ? "已发现" : "未发现"}`);
        } else {
            $.log(`账号[${this.index}] 首页信息查询失败: ${result?.msg || JSON.stringify(result)}`);
        }
    }

    async signIn() {
        const finish = await this.request({
            apiPath: "/api/member/signin/tofinish",
            query: { taskType: SIGN_TASK_TYPE },
            allowFail: true,
        });
        if (String(finish?.code) === "200" && finish.data === true) {
            $.log(`账号[${this.index}] 签到任务已上报`);
        } else if (String(finish?.code) === "200") {
            $.log(`账号[${this.index}] 签到接口返回: ${JSON.stringify(finish.data)}`);
        } else {
            throw new Error(`签到失败: ${finish?.msg || JSON.stringify(finish)}`);
        }

        const complete = await this.request({
            apiPath: "/api/member/signin/completeTask",
            query: { taskType: SIGN_TASK_TYPE },
            allowFail: true,
        });
        if (String(complete?.code) === "200") {
            const points = complete.data?.awardSendPoints || complete.data?.awardPoint || "";
            $.log(`账号[${this.index}] 签到完成${points ? `，获得${points}积分` : ""}`);
        } else if (complete?.msg) {
            $.log(`账号[${this.index}] 完成确认返回: ${complete.msg}`);
        }
    }
}

!(async () => {
    $.checkEnv(ckName);
    if (!$.userList.length) return;

    for (const account of $.userList) {
        const task = new Task(account);
        try {
            await task.run();
        } catch (e) {
            $.log(`账号[${task.index}] 运行失败: ${e.message || e}`);
        }
    }
})()
    .catch((e) => $.log(`运行异常: ${e.message || e}`))
    .finally(() => $.done && $.done());
