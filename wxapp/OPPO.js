require('./yyb.js'); // 自动同步 yyb_go 存活账号
/**
// name: OPPO
------------------------------------------
@Author: sm
@Date: 2026.07.24
@Description: OPPO 微信小程序每日签到（微信协议版，适配青龙）
cron: 8 06,18 * * *
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
let ACCOUNTS_RAW = (process.env.WX_ID || "")
    .split(/\r?\n|&/)
    .map(s => s.trim())
    .filter(Boolean);
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
let userIdx = 1;

const CK_NAME = "oppo";
const APP = {
    name: "OPPO",
    appid: "wxe705c556754a1de2",
    version: 361,
};

const MINI_API = "https://omoapplet-api-cn.heytap.com";
const H5_API = "https://hd.opposhop.cn";
const SIGN_ACTIVITY_ID = "2061050217641549824";
const CREDITS_ADD_ACTION_ID = "1788913e6d9e4683b8b9ab0088733560";
const BUSINESS = 1;
const SIGN_PAGE =
    "https://hd.opposhop.cn/bp/b371ce270f7509f0?nightModelEnable=true&utm_source=huiyuanwx&utm_medium=me_qiandao";
const USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

function splitAccounts(value = "") {
    return String(value)
        .split(/\n|&/)
        .map((item) => item.trim())
        .filter(Boolean);
}

function short(value, max = 500) {
    if (value === undefined || value === null) return "";
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return text.length > max ? `${text.slice(0, max)}...` : text;
}

function parseAccount(raw = "") {
    const text = String(raw || "").trim();
    if (!text) return {};
    if (text.startsWith("{")) {
        const data = JSON.parse(text);
        return {
            openid: data.openid || data.openId || "",
            remark: data.remark || data.name || "",
        };
    }
    const [openid, remark] = text.split("#").map((item) => item.trim());
    return { openid, remark };
}

function awardTypeName(type) {
    const map = {
        0: "无奖励",
        1: "积分",
        2: "优惠券",
        3: "抽奖机会",
    };
    return map[Number(type)] || `类型${type}`;
}

function todayText() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const d = String(now.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

async function request(options) {
    const res = await axios.request({
        timeout: 25000,
        validateStatus: () => true,
        ...options,
        headers: {
            "User-Agent": USER_AGENT,
            Accept: "application/json, text/plain, */*",
            ...(options.headers || {}),
        },
    });
    return { status: res.status, headers: res.headers || {}, data: res.data };
}

async function getWxCode(identifier) {
    return await getSingleCode(APP.appid, String(identifier).split("#")[0].trim());
}

// ====================== 本地登录态缓存（先走缓存，失效后再 getCode） ======================
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "oppo_token_cache.json");
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


class OppoTask {
    constructor(rawAccount, index) {
        this.index = index;
        this.account = parseAccount(rawAccount);
        this.wxid = this.account.openid || "";
        this.sessionId = "";
        this.encryptedSession = "";
        this.openId = "";
        this.memberInfo = {};
        this.baseInfo = {};
    }

    log(message) {
        console.log(`账号[${this.index}]${this.account.remark ? `[${this.account.remark}]` : ""} ${message}`);
    }

    miniHeaders(extra = {}) {
        return {
            "content-type": "application/json",
            s_channel: "oppo",
            source_type: "2",
            s_version: "010000",
            spCallSource: "oppohy",
            Referer: `https://servicewechat.com/${APP.appid}/${APP.version}/page-frame.html`,
            sessionId: this.sessionId || "",
            NEWOPPOSID: this.encryptedSession || "",
            openid: this.openId || "",
            sa_distinct_id: this.openId || "",
            constToken: this.sessionId || "",
            ...extra,
        };
    }

    h5Headers(extra = {}) {
        return {
            "content-type": "application/json",
            Origin: H5_API,
            Referer: SIGN_PAGE,
            sessionId: this.sessionId || "",
            NEWOPPOSID: this.encryptedSession || "",
            openid: this.openId || "",
            sa_distinct_id: this.openId || "",
            constToken: this.sessionId || "",
            Cookie: [
                `NEWOPPOSID=${encodeURIComponent(this.encryptedSession || "")}`,
                `sessionId=${encodeURIComponent(this.sessionId || "")}`,
                `openid=${encodeURIComponent(this.openId || "")}`,
            ].join("; "),
            ...extra,
        };
    }

    async miniRequest(method, path, data = {}) {
        const upperMethod = method.toUpperCase();
        const { status, data: result } = await request({
            method: upperMethod,
            url: `${MINI_API}${path}`,
            headers: this.miniHeaders(),
            params: upperMethod === "GET" ? data : undefined,
            data: upperMethod === "GET" ? undefined : data,
        });
        if (status !== 200) throw new Error(`${path} HTTP ${status}: ${short(result)}`);
        if (result?.ret && String(result.ret) !== "1") {
            throw new Error(`${path} 失败: ${result.errMsg || result.message || short(result)}`);
        }
        return result;
    }

    async h5Request(method, path, data = {}) {
        const upperMethod = method.toUpperCase();
        const { status, data: result } = await request({
            method: upperMethod,
            url: `${H5_API}${path}`,
            headers: this.h5Headers(),
            params: upperMethod === "GET" ? data : undefined,
            data: upperMethod === "GET" ? undefined : data,
        });
        if (status !== 200) throw new Error(`${path} HTTP ${status}: ${short(result)}`);
        if (Number(result?.code) !== 200 && result?.succeed !== true) {
            throw new Error(`${path} 失败: ${result?.message || result?.errorMessage || short(result)}`);
        }
        return result;
    }

    get cacheKey() {
        return this.wxid || String(this.account.openid || "").trim();
    }

    getCachedSession() {
        const cache = readTokenCache();
        return cache[this.cacheKey] || null;
    }

    saveCachedSession() {
        if (!this.sessionId) return;
        const cache = readTokenCache();
        cache[this.cacheKey] = {
            sessionId: this.sessionId,
            encryptedSession: this.encryptedSession,
            openId: this.openId,
            updatedAt: new Date().toISOString(),
        };
        writeTokenCache(cache);
    }

    removeCachedSession() {
        const cache = readTokenCache();
        if (cache[this.cacheKey]) {
            delete cache[this.cacheKey];
            writeTokenCache(cache);
        }
        this.sessionId = "";
        this.encryptedSession = "";
        this.openId = "";
    }

    async checkSession() {
        try {
            const base = await this.miniRequest("GET", "/member/baseInfo", { sessionId: this.sessionId });
            return !!(base && base.data);
        } catch (e) {
            return false;
        }
    }

    async login() {
        // 先走缓存: 本地缓存的登录态仍有效则直接使用, 不调用 getCode
        const cached = this.getCachedSession();
        if (cached && cached.sessionId) {
            this.sessionId = cached.sessionId;
            this.encryptedSession = cached.encryptedSession || "";
            this.openId = cached.openId || "";
            if (await this.checkSession()) {
                this.log(`使用缓存登录态 openId=${this.openId || "未知"}`);
                return;
            }
            this.log(`缓存登录态失效, 重新登录`);
            this.removeCachedSession();
        }
        const code = await getWxCode(this.wxid);
        if (!code) throw new Error("获取code失败");
        const { status, data } = await request({
            method: "POST",
            url: `${MINI_API}/user/pre/auth`,
            headers: {
                "content-type": "application/json",
                Referer: `https://servicewechat.com/${APP.appid}/${APP.version}/page-frame.html`,
            },
            data: { code },
        });
        if (status !== 200 || String(data?.ret) !== "1") throw new Error(`登录失败 HTTP ${status}: ${short(data)}`);
        const info = data.data || {};
        this.sessionId = info.sessionId || "";
        this.encryptedSession = info.encryptedSession || "";
        this.openId = info.openId || "";
        if (!this.sessionId) throw new Error(`登录响应缺少 sessionId: ${short(data)}`);
        this.saveCachedSession();
        this.log(`登录成功 openId=${this.openId || "未知"}`);
    }

    async queryMember() {
        const member = await this.miniRequest("GET", "/member/info", { sessionId: this.sessionId });
        const base = await this.miniRequest("GET", "/member/baseInfo", { sessionId: this.sessionId }).catch(() => ({}));
        this.memberInfo = member.data || {};
        this.baseInfo = base.data || {};
        const userName = this.memberInfo.userName || this.baseInfo.userName || "未知";
        const phone = this.baseInfo.pnumber ? `，手机号: ${this.baseInfo.pnumber}` : "";
        this.log(
            `用户信息: ${userName}${phone}，积分: ${this.memberInfo.pointAmount ?? 0}，成长值: ${
                this.memberInfo.growthValue ?? 0
            }，等级: ${this.memberInfo.gradeCode || "未知"}`
        );
    }

    async queryEntrance() {
        const result = await this.miniRequest("GET", "/activity/signIn/entrance", { sessionId: this.sessionId });
        const data = result.data || {};
        this.log(`签到入口: ${data.signInIsStarted ? "已开启" : "未开启"}，连续/累计天数: ${data.signInDays ?? "-"}`);
    }

    async getSignDetail() {
        const result = await this.h5Request("GET", "/api/cn/oapi/marketing/cumulativeSignIn/getSignInDetail", {
            activityId: SIGN_ACTIVITY_ID,
            creditsAddActionId: CREDITS_ADD_ACTION_ID,
            business: BUSINESS,
        });
        return result.data || {};
    }

    todayAward(detail = {}) {
        const today = todayText();
        const awards = Array.isArray(detail.baseAwards) ? detail.baseAwards : [];
        return awards.find((item) => String(item.signTime || "").slice(0, 10) === today) || awards[0] || {};
    }

    async querySignDetail() {
        const detail = await this.getSignDetail();
        const award = this.todayAward(detail);
        const signed = Number(award.status) === 1;
        this.log(
            `签到详情: ${signed ? "今日已签" : "今日未签"}，已签天数: ${detail.signInDayNum ?? 0}，今日奖励: ${
                award.awardValue ?? "-"
            }${award.awardType !== undefined ? awardTypeName(award.awardType) : ""}`
        );
        return { detail, signed };
    }

    async signIn() {
        const { signed } = await this.querySignDetail();
        if (signed) return this.log("签到结果: 今日已签到，跳过");
        const result = await this.h5Request("POST", "/api/cn/oapi/marketing/cumulativeSignIn/signIn", {
            activityId: SIGN_ACTIVITY_ID,
            captchaCode: "",
            creditsAddActionId: CREDITS_ADD_ACTION_ID,
            business: BUSINESS,
        });
        const data = result.data || {};
        if (data.receiveStatus === false) {
            this.log(`签到结果: 失败，${data.receiveFailMsg || result.message || "未知原因"}`);
            return;
        }
        this.log(`签到结果: 成功，获得 ${data.awardValue ?? "-"}${awardTypeName(data.awardType)}`);
        await this.querySignDetail();
    }

    async run() {
        try {
            this.log(`开始执行 ${APP.name}`);
            await this.login();
            await this.queryMember();
            await this.queryEntrance();
            await this.signIn();
            await this.queryMember();
        } catch (e) {
            this.log(`执行失败: ${e.message || e}`);
        }
    }
}

async function main() {
    // 未配置 WX_ID 时，自动从 yyb_go 拉取所有存活账号
    if (!ACCOUNTS_RAW.length) {
        try {
            const _accs = await loadAccounts();
            ACCOUNTS_RAW = _accs.map(a => a.openid || a.wxid || a._ref || String(a.id)).filter(Boolean);
        } catch (e) {
            console.log(`从 yyb_go 拉取账号失败: ${e.message || e}`);
        }
    }
    if (!ACCOUNTS_RAW.length) {
        console.log(`未找到可用账号（WX_ID 未配置且 yyb_go 无存活账号）`);
        return;
    }
    for (let i = 0; i < ACCOUNTS_RAW.length; i++) {
        const task = new OppoTask(ACCOUNTS_RAW[i], i + 1);
        await task.run();
        if (i < ACCOUNTS_RAW.length - 1) await sleep(2000);
    }
}

main()
    .catch((e) => console.log(`脚本异常: ${e.message || e}`))