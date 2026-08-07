/*
 * 艾瑞调研问卷 - 小程序艾瑞调研问卷每日签到
 * cron: 30 8-10 * * *
 * 变量名：airui   变量值：token，多账号用 & 或换行分隔
 * 完善：统一通知(sendNotify) + 结果汇总 + 空行过滤 + 签到参数修正
 */

const axios = require("axios");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { sendNotify } = require("../sendNotify.js");

const ckName = "airui";
const ENV_STR = process.env[ckName] || "";
let userList = ENV_STR.split(/&|\n/).map((v) => v.trim()).filter((v) => v);

const MINI_APP_ID = "wx342d760f674b013b";
const API_BASE = "https://api.ikbang.cn/v2";
const APP_KEY = "A749380BBD5A4D93B55B4BE245A42988";
const TOKEN_CACHE_FILE = path.join(__dirname, "airui_token_cache.json");

const UA_POOL = [
    "Mozilla/5.0 (Linux; Android 13; SM-G998B Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.5672.126 Mobile Safari/537.36 MicroMessenger/8.0.39",
    "Mozilla/5.0 (Linux; Android 14; Mi 14 Build/UKQ1.230804.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36 MicroMessenger/8.0.42",
    "Mozilla/5.0 (Linux; Android 14; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.0.0 Mobile Safari/537.36 MicroMessenger",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.29",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile MicroMessenger",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541c18) XWEB/25297"
];

const log = console.log;

function getRandomUA() {
    return UA_POOL[Math.floor(Math.random() * UA_POOL.length)];
}
function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
function readCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
    } catch {
        return {};
    }
}
function writeCache(cache) {
    try {
        fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
    } catch (e) {
        log(`token缓存写入失败: ${e.message || e}`);
    }
}
function mask(value = "") {
    value = String(value);
    if (!value) return "";
    if (value.length <= 12) return `${value.slice(0, 3)}***`;
    return `${value.slice(0, 6)}***${value.slice(-6)}`;
}
function stringifyQuery(params = {}) {
    return new URLSearchParams(params).toString();
}
function makeSign(urlPath, method, params, timestamp, token = "") {
    let payload = "";
    if (params && Object.keys(params).length > 0) {
        payload = method === "POST" ? JSON.stringify(params) : stringifyQuery(params);
    }
    const rawStr = `${API_BASE}${urlPath}${timestamp}${payload}${APP_KEY}${token || ""}`;
    return crypto.createHash("md5").update(rawStr).digest("hex");
}
async function apiRequest(method, urlPath, { token = "", params = null, retry = 2 } = {}) {
    let lastErr;
    for (let i = 0; i <= retry; i++) {
        try {
            const timestamp = String(Date.now());
            const sign = makeSign(urlPath, method, params, timestamp, token);
            const reqOpt = {
                method,
                url: `${API_BASE}${urlPath}`,
                timeout: 15000,
                validateStatus: () => true,
                headers: {
                    token,
                    sign,
                    timestamp,
                    "Content-Type": "application/json",
                    "User-Agent": getRandomUA(),
                    Referer: `https://servicewechat.com/${MINI_APP_ID}/127/page-frame.html`,
                },
            };
            if (method === "POST" && params) reqOpt.data = params;
            if (method === "GET" && params) reqOpt.params = params;
            const res = await axios(reqOpt);
            return res.data;
        } catch (err) {
            lastErr = err;
            if (i < retry) {
                log(`请求异常，${i + 1}/${retry}次重试...`);
                await sleep(1200);
            }
        }
    }
    throw lastErr;
}
function assertOk(res, action) {
    if (!res) throw new Error(`${action}失败：接口无返回`);
    if ([401, -1001].includes(Number(res.code))) {
        throw new Error(`token已失效｜${res?.description || res?.msg || JSON.stringify(res)}`);
    }
    if (Number(res.code) !== 1) {
        throw new Error(`${action}失败: ${res?.description || res?.msg || JSON.stringify(res)}`);
    }
    return res.result;
}

class Task {
    constructor(raw, idx) {
        this.index = idx;
        const account = parseAccount(raw);
        this.token = account.token || "";
        this.userId = "";
        this.cacheKey = crypto.createHash("md5").update(this.token).digest("hex").slice(0, 16);
    }
    getCached() {
        return readCache()[this.cacheKey] || {};
    }
    saveCache(extra = {}) {
        const cache = readCache();
        cache[this.cacheKey] = {
            ...(cache[this.cacheKey] || {}),
            ...(this.userId ? { userId: this.userId } : {}),
            ...extra,
            updatedAt: new Date().toISOString(),
        };
        writeCache(cache);
    }
    async getUserInfo() {
        try {
            const info = assertOk(
                await apiRequest("GET", "/iclick-new/usercenter/getUserDetails", { token: this.token }),
                "查询用户信息"
            );
            this.userId = info.userId || this.userId;
            this.saveCache({ userName: info.userName || "", totalPoints: info.totalPoints || "" });
            log(`账号[${this.index}] 用户: ${info.userName || mask(info.userId || "")}，积分 ${info.totalPoints ?? "未知"}`);
            return info;
        } catch (e) {
            log(`账号[${this.index}] 用户信息查询失败: ${e.message || e}`);
            return {};
        }
    }
    async getSignInfo() {
        return assertOk(
            await apiRequest("GET", "/iclick-new/signIn/getSignInInfo", { token: this.token }),
            "查询签到信息"
        );
    }
    async submitSign() {
        return assertOk(await apiRequest("POST", "/iclick-new/signIn/sign", { token: this.token }), "签到");
    }
    async run() {
        log(`\n账号[${this.index}] token:${mask(this.token)}`);
        if (!this.token) {
            log(`账号[${this.index}] 缺少token，跳过`);
            return { status: "skip", msg: "缺少token" };
        }
        await this.getUserInfo();
        const before = await this.getSignInfo();
        if (before.currentSignIn) {
            log(`账号[${this.index}] 今日已签到，连续 ${before.continuityDay ?? "未知"} 天，总签到积分 ${before.totalSignInScore ?? "未知"}`);
            return { status: "done", msg: `已签到(连续${before.continuityDay ?? "?"}天)` };
        }
        await this.submitSign();
        const after = await this.getSignInfo();
        log(`账号[${this.index}] 签到成功，连续 ${after.continuityDay ?? "未知"} 天，总签到积分 ${after.totalSignInScore ?? "未知"}`);
        return { status: "ok", msg: `签到成功(连续${after.continuityDay ?? "?"}天)` };
    }
}
function parseAccount(raw) {
    const text = String(raw || "").trim();
    if (!text) return { token: "" };
    return { token: text };
}

!(async () => {
    if (!userList.length) {
        log("❌未读取到airui环境变量，请配置airui=token，多账号&或者换行分隔");
        return;
    }
    const summary = [];
    for (let i = 0; i < userList.length; i++) {
        const item = userList[i];
        try {
            const gap = Math.floor(Math.random() * 3000) + 2000;
            log(`等待 ${gap / 1000}s 切换账号`);
            await sleep(gap);
            const r = await new Task(item, i + 1).run();
            summary.push(`账号[${i + 1}] ${r.status === "ok" ? "✅" : r.status === "done" ? "☑️" : "⚠️"} ${r.msg}`);
        } catch (e) {
            summary.push(`账号[${i + 1}] ❌ ${e.message || e}`);
            log(`账号[${i + 1}]执行失败: ${e.message || e}`);
        }
    }
    if (summary.length) {
        const content = `艾瑞调研签到结果 (${summary.length}个账号)\n\n` + summary.join("\n");
        log("\n" + content);
        try {
            await sendNotify("艾瑞调研签到", content);
        } catch (e) {
            log(`通知推送失败(忽略): ${e.message || e}`);
        }
    }
})().catch((e) => log(`脚本异常: ${e.message || e}`));
