require('./yyb.js'); // 自动同步 yyb_go 存活账号
/**
// name: 腾讯地图
------------------------------------------
@Author: sm
@Date: 2026.07.24
@Description: 腾讯地图 微信小程序每日签到（微信协议版，适配青龙）
cron: 24 15,03 * * *
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
const crypto = require("crypto");
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
        return await getSingleCode('wx7643d5f831302ab0', __id);
    } catch (e) {
        console.log(__id + " 获取code异常: " + (e && e.message ? e.message : e));
        return null;
    }
}

// ====================== 本地登录态缓存（先走缓存，失效后再 getCode） ======================
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "tmap_token_cache.json");
try { fs.mkdirSync(path.dirname(TOKEN_CACHE_FILE), { recursive: true }); } catch (e) {}

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
        console.log(`写入登录态缓存失败: ${e.message || e}`);
    }
}

function getCachedLoginInfo(ref) {
    const cache = readTokenCache();
    return cache[ref] || null;
}

function saveCachedLoginInfo(ref, loginInfo, openid) {
    if (!loginInfo || !loginInfo.user_id) return;
    const cache = readTokenCache();
    cache[ref] = { loginInfo, openid, updatedAt: new Date().toISOString() };
    writeTokenCache(cache);
}

function removeCachedLoginInfo(ref) {
    const cache = readTokenCache();
    if (cache[ref]) {
        delete cache[ref];
        writeTokenCache(cache);
    }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
let userIdx = 1;

const APP = {
    name: "腾讯地图",
    appid: "wx7643d5f831302ab0",
    version: 545,
    withdrawGameId: 4,
    withdrawRuleId: "tencent_map_withdraw",
    checkinGameId: 1,
    checkinRuleId: "tencent_map_checkin",
    defaultMinWithdrawThreshold: 1500, // 默认满15元(分)自动提现
};

const MINI_LOGIN_BASE = "https://miniapp.map.qq.com";
const MAP_BASE = "https://mmapgwh.map.qq.com";
const LOGIN_ACCESS_KEY = "1";
const LOGIN_SECRET_KEY = "4300eec60bedec22a73408a0d76b03ec";
const TMAP_SECRET = "3a9875e795c3ecff15f617085e72d4cc";
const CHECKIN_TOKEN = "e643d512f085d621bf6c9e80310d0498";
const ACTIVITY_ID = 1721983577;
const USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

function splitAccounts(value = "") {
    return String(value)
        .split(/\n|&/)
        .map((item) => item.trim())
        .filter(Boolean);
}

function short(value, max = 320) {
    if (value === undefined || value === null) return "";
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return text.length > max ? `${text.slice(0, max)}...` : text;
}

function md5(value) {
    return crypto.createHash("md5").update(String(value)).digest("hex");
}

function sha256(value) {
    return crypto.createHash("sha256").update(String(value)).digest("hex");
}

function uuid() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
        const n = (Math.random() * 16) | 0;
        return (char === "x" ? n : (n & 3) | 8).toString(16);
    });
}

function sortedQuery(data) {
    const normalized = {};
    Object.keys(data)
        .sort()
        .forEach((key) => {
            if (data[key] !== undefined && data[key] !== null) normalized[key] = data[key];
        });
    return Object.keys(normalized)
        .map((key) => `${key}=${normalized[key]}`)
        .join("&");
}

function formatCoin(value) {
    const num = Number(value || 0);
    return `${num}(${(num / 100).toFixed(2)})`;
}

function parseAccount(raw) {
    const text = String(raw || "").trim();
    if (!text) return {};
    if (text.startsWith("{")) {
        try {
            const data = JSON.parse(text);
            return {
                raw: text,
                openid: data.openid || data.openId || "",
                remark: data.remark || data.name || "",
                auto_withdraw: data.auto_withdraw !== false, // JSON不写false即默认开启提现
                min_withdraw_amount: Number(data.min_withdraw_amount || APP.defaultMinWithdrawThreshold),
            };
        } catch (err) {
            console.log(`账号JSON解析失败 ${raw}：${err.message}`);
            return {};
        }
    }
    // 普通 openid#备注 格式默认开启自动提现
    const [openid, remark] = text.split("#").map((item) => item.trim());
    return {
        raw: text,
        openid,
        remark: remark || "未备注账号",
        auto_withdraw: true,
        min_withdraw_amount: APP.defaultMinWithdrawThreshold,
    };
}

async function request(options) {
    const res = await axios.request({
        timeout: 20000,
        validateStatus: () => true,
        ...options,
        headers: {
            "User-Agent": USER_AGENT,
            Accept: "application/json, text/plain, */*",
            Referer: `https://servicewechat.com/${APP.appid}/${APP.version}/page-frame.html`,
            ...(options.headers || {}),
        },
    });
    return { status: res.status, headers: res.headers || {}, data: res.data };
}

async function getWxCode(server) {
        return await getCode(server);
    }


function loginSign({ appId, sessionId = "-1", openId, userId, postBody }) {
    const reqId = md5(`${Math.random()} ${Date.now()}`);
    const reqTime = Date.now().toString().slice(0, 10);
    const signParams = {
        appId,
        reqId,
        reqTime,
        userId,
        openID: openId,
        sessionID: sessionId,
        accessKey: LOGIN_ACCESS_KEY,
        businessStr: JSON.stringify(postBody),
    };
    const signText = `${sortedQuery(signParams)}&secretKey=${LOGIN_SECRET_KEY}`;
    const headers = {
        "mapservice-sign-version": "v2",
        "mapservice-sign": sha256(signText),
        "mapservice-reqid": reqId,
        "mapservice-reqtime": reqTime,
        "mapservice-appid": appId,
        "mapservice-accesskey": LOGIN_ACCESS_KEY,
        "mapservice-sessionid": sessionId,
    };
    if (sessionId && sessionId !== "-1") {
        headers["mapservice-openid"] = openId;
        headers["mapservice-userid"] = userId;
    }
    return headers;
}

function mapH5Sign(apiPath, user) {
    const reqId = uuid();
    const reqTime = Date.now();
    const normalizedPath = apiPath.split("?")[0];
    const signBase = `mapinst=0&mapnonce=0&reqid=${reqId}&reqtime=${reqTime}`;
    const defaultSign = md5(`${signBase}${normalizedPath}0${TMAP_SECRET}`);
    const headers = {
        "tmap-reqid": reqId,
        "tmap-reqtime": reqTime,
        "tmap-userid": Number(user.user_id) || Number(user.userId) || 0,
        "tmap-login-ssid": user.session_id || user.sessionId || 0,
        "tmap-imei": 0,
        "tmap-qimei": 0,
        "tmap-qimei36": 0,
        "tmap-nonce": 0,
        "tmap-install-id": 0,
        "tmap-sign": 0,
        "tmap-default-sign": defaultSign,
        "tmap-app-version": 0,
        "tmap-channel": 0,
        "tmap-engine": "web",
        "tmap-mini-login-ssid": user.map_session_id || user.mapSessionId || "",
        "tmap-app-id": user.appId || APP.appid,
    };
    if (user.openid || user.openId) headers["tmap-openid"] = user.openid || user.openId;
    return headers;
}

function checkinHeader(user) {
    const requestId = uuid();
    const timestamp = Math.floor(Date.now() / 1000);
    const signText = `request_id=${requestId}&from_source=${APP.appid}&timestamp=${timestamp}&token=${CHECKIN_TOKEN}`;
    return {
        user_id: user.openid || user.openId,
        from_source: APP.appid,
        request_id: requestId,
        timestamp,
        sign: sha256(signText).toUpperCase(),
    };
}

class TencentMap {
    constructor(rawAccount, index) {
        this.server = rawAccount;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.index = index;
        this.account = parseAccount(rawAccount);
        this.loginInfo = {};
        this.userInfo = {};
    }

    async miniLogin() {
        const code = await getWxCode(this.server);
        const body = {
            seqid: uuid(),
            app_id: APP.appid,
            auth_code: code,
            devHeader: {},
        };
        const { status, data } = await request({
            method: "POST",
            url: `${MINI_LOGIN_BASE}/minLogin/v2/login`,
            headers: {
                "content-type": "application/json",
                ...loginSign({ appId: APP.appid, postBody: body }),
            },
            data: body,
        });
        if (status !== 200 || Number(data?.err_code) !== 0) throw new Error(`登录失败 HTTP ${status}: ${short(data)}`);
        this.loginInfo = { ...data, appId: APP.appid };
        console.log(`登录：成功 userId=${data.user_id || "未知"}，openid=${data.openid || "未知"}`);
    }

    async queryUser() {
        const user = this.loginInfo;
        const body = {
            seqid: uuid(),
            app_id: APP.appid,
            userId: user.user_id,
            openId: user.openid,
            source: "mini-tencentmap",
        };
        const { status, data } = await request({
            method: "POST",
            url: `${MINI_LOGIN_BASE}/minLogin/v2/getUserInfo`,
            headers: {
                "content-type": "application/json",
                ...loginSign({
                    appId: APP.appid,
                    sessionId: user.session_id,
                    userId: user.user_id,
                    openId: user.openid,
                    postBody: body,
                }),
            },
            data: body,
        });
        if (status !== 200 || Number(data?.err_code) !== 0) {
            console.log(`用户信息：查询失败 HTTP ${status}: ${short(data)}`);
            return;
        }
        this.userInfo = data || {};
        console.log(`用户信息：${data.nickname || "微信用户"}，userId=${data.userid || user.user_id}`);
    }

    async mapApi(apiPath, data) {
        const { status, data: body } = await request({
            method: "POST",
            url: `${MAP_BASE}${apiPath}`,
            headers: {
                "content-type": "application/json",
                ...checkinHeader(this.loginInfo),
                ...mapH5Sign(apiPath, this.loginInfo),
            },
            data,
        });
        if (status !== 200 || Number(body?.code) !== 0) throw new Error(`${apiPath} HTTP ${status}: ${short(body)}`);
        return body.data || {};
    }

    async queryBalance(prefix = "现金余额") {
        const data = await this.mapApi("/activity/v1/withdraw/home", {
            activity_id: ACTIVITY_ID,
            game_id: APP.withdrawGameId,
            rule_id: APP.withdrawRuleId,
        });
        console.log(
            `${prefix}：金币=${formatCoin(data.coins)}，可提现=${formatCoin(data.withdrawable_amount)}，门槛=${formatCoin(data.current_withdraw_threshold)}，奖池=${formatCoin(data.jackpot_amount)}`
        );
        return data;
    }

    async queryAssets() {
        const data = await this.mapApi("/activity/v1/assert/home", { activity_id: ACTIVITY_ID });
        console.log(
            `资产信息：金币=${formatCoin(data.coins)}，优惠券=${data.coupons_total || 0}，抽奖券=${data.lottery_ticket_total || 0}`
        );
        return data;
    }

    todayKey() {
        const now = new Date();
        const year = now.getFullYear();
        const month = `${now.getMonth() + 1}`.padStart(2, "0");
        const day = `${now.getDate()}`.padStart(2, "0");
        return `${year}${month}${day}`;
    }

    async queryCalendar(prefix = "签到状态") {
        const data = await this.mapApi("/activity/v1/checkin/calendar", {
            activity_id: ACTIVITY_ID,
            game_id: APP.checkinGameId,
            rule_id: APP.checkinRuleId,
        });
        const today = data.calendar?.[this.todayKey()] || {};
        const prizes = Array.isArray(today.prizes)
            ? today.prizes.map((item) => `${item.name || item.type || "奖励"}:${item.amount ?? ""}`).join("，")
            : "";
        console.log(`${prefix}：今日${today.checkin ? "已签" : "未签"}，周期已签=${data.checkin_days || 0}/${data.period || 0}${prizes ? `，奖励=${prizes}` : ""}`);
        return { data, today };
    }

    async checkin() {
        const { today } = await this.queryCalendar("签到前");
        if (today.checkin) {
            console.log("签到：今日已签到");
            return;
        }
        const data = await this.mapApi("/activity/v1/checkin", {
            activity_id: ACTIVITY_ID,
            game_id: APP.checkinGameId,
            rule_id: APP.checkinRuleId,
            nick: this.userInfo.nickname || "微信用户",
        });
        const prizes = Array.isArray(data.prizes)
            ? data.prizes.map((item) => `${item.name || item.type || "奖励"}:${item.amount ?? ""}`).join("，")
            : short(data);
        console.log(`签到：成功${prizes ? `，${prizes}` : ""}`);
    }

    async autoWithdraw() {
        if (!this.account.auto_withdraw) {
            console.log("提现：该账号已关闭自动提现，跳过");
            return;
        }
        console.log("提现：开始校验可提现余额");
        const balanceData = await this.queryBalance("提现前余额校验");
        const withdrawable = Number(balanceData.withdrawable_amount || 0);
        const currentThreshold = Number(balanceData.current_withdraw_threshold || APP.defaultMinWithdrawThreshold);
        const triggerAmount = Math.max(this.account.min_withdraw_amount, currentThreshold);
        if (withdrawable < triggerAmount) {
            console.log(`提现：可提现${formatCoin(withdrawable)}未达${formatCoin(triggerAmount)}阈值，暂不提现`);
            return;
        }
        const validItems = (balanceData.withdraw_items || []).filter((item) => Number(item.amount) > 0 && item.status === 0);
        if (!validItems.length) {
            console.log("提现：未找到可发起的有效档位，跳过");
            return;
        }
        let targetItem = validItems.find((i) => Number(i.amount) === triggerAmount);
        if (!targetItem) {
            targetItem = validItems.sort((a, b) => Number(a.amount) - Number(b.amount))[0];
        }
        const withdrawRes = await this.mapApi("/activity/v1/withdraw/apply", {
            activity_id: ACTIVITY_ID,
            game_id: APP.withdrawGameId,
            rule_id: APP.withdrawRuleId,
            amount: targetItem.amount,
            withdraw_item_id: targetItem.id,
            pay_channel: 1,
        });
        console.log(`提现：申请提交成功，金额${formatCoin(targetItem.amount)}，单号${withdrawRes.order_id || "无"}`);
    }

    get cacheKey() {
        return this.ref || String(this.server).split("#")[0].trim();
    }

    getCachedLogin() {
        return getCachedLoginInfo(this.cacheKey);
    }

    saveCachedLogin() {
        saveCachedLoginInfo(this.cacheKey, this.loginInfo, this.openid);
    }

    removeCachedLogin() {
        removeCachedLoginInfo(this.cacheKey);
    }

    async run() {
        console.log(`\n========== ${APP.name} 账号[${this.index}] ${this.account.remark || this.openid} ==========`);
        // 先走缓存: 本地缓存登录态仍有效则直接使用, 不调用 getCode
        const cached = this.getCachedLogin();
        if (cached && cached.loginInfo) {
            this.loginInfo = cached.loginInfo;
            this.openid = cached.openid || this.openid;
            await this.queryUser();
            if (this.userInfo && this.userInfo.userid) {
                console.log(`使用缓存登录态 openid=${this.openid}`);
                this._userQueried = true;
            } else {
                console.log(`缓存登录态失效，重新登录`);
                this.removeCachedLogin();
                await this.miniLogin();
            }
        } else {
            await this.miniLogin();
        }
        this.saveCachedLogin();
        if (!this._userQueried) await this.queryUser();
        await this.queryBalance("签到前现金余额");
        await this.queryAssets();
        await this.checkin();
        await this.autoWithdraw();
        await this.queryBalance("签到后现金余额");
        await this.queryCalendar("签到后");
    }
}

(async () => {
    let accounts = SERVERS;
    // 未配置 WX_ID 时，自动从 yyb_go 拉取所有存活账号
    if (!accounts.length) {
        try {
            const _accs = await loadAccounts();
            accounts = _accs.map(a => a.openid || a.wxid || a._ref || String(a.id)).filter(Boolean);
        } catch (e) {
            console.log(`从 yyb_go 拉取账号失败: ${e.message || e}`);
        }
    }
    if (!accounts.length) {
        console.log(`未找到可用账号（WX_ID 未配置且 yyb_go 无存活账号）`);
        return;
    }
    console.log(`共找到${accounts.length}个账号`);
    for (let i = 0; i < accounts.length; i++) {
        const runner = new TencentMap(accounts[i], i + 1);
        try {
            await runner.run();
        } catch (e) {
            console.log(`账号[${i + 1}] 执行失败：${e.message || e}`);
        }
        await await sleep(800);
    }
    
})().catch(async (e) => {
    console.log(`脚本异常：${e.stack || e.message || e}`);
    
});