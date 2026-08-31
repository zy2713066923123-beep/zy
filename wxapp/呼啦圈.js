require('./yyb.js'); // 自动同步 yyb_go 存活账号
/**
// name: 呼啦圈
------------------------------------------
@Author: sm
@Date: 2026.07.24
@Description: 呼啦圈 微信小程序每日签到（微信协议版，适配青龙）
cron: 8 09,21 * * *
变量名：WX_ID
变量值：微信账号（openid/wxid），多账号支持换行、& 分隔，必须配置

------------------------------------------

变量：
  WX_ID          (可选白名单) 微信账号，多账号换行/&分隔，留空自动拉取 yyb_go 所有存活账号
  WX_SERVER      yyb_go 统一协议服务地址（例如：http://127.0.0.1:18273）
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

const MINI_APP_ID = "wx89a714fb03b61b99";
const APP_VERSION = "2.30.3";
const ENV_VERSION = "release";
const API_BASE = "https://smp-api.iyouke.com/dtapi";
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "parkson_token_cache.json");
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

function formatDate(date = new Date(), separator = "-") {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return [y, m, d].join(separator);
}

class Task {
    constructor(openid) {
        this.server = openid;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.index = userIdx++;
        this.openid = String(openid || "").trim();
        this.accessToken = "";
        this.authorization = "";
        this.userInfo = {};
    }

    async run() {
        const cached = this.getCachedToken();
        if (cached) {
            this.applyToken(cached);
            console.log(`账号[${this.index}] 使用缓存token`);
            if (!(await this.checkToken())) {
                this.removeCachedToken();
                console.log(`账号[${this.index}] 缓存token失效，重新登录`);
            }
        }

        if (!this.accessToken) {
            await this.loginByWxCode();
            if (!this.accessToken) return;
        }

        await this.getPointsInfo();
        await this.getSignList();
        await this.doSign();
        await this.getPointsInfo();
    }

    getCachedToken() {
        const cache = readTokenCache();
        return cache[this.openid] || null;
    }

    saveCachedToken() {
        if (!this.accessToken) return;
        const cache = readTokenCache();
        cache[this.openid] = {
            accessToken: this.accessToken,
            authorization: this.authorization,
            userId: this.userInfo.userId || "",
            nickName: this.userInfo.nickName || "",
            userMobile: this.userInfo.userMobile || "",
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
        this.accessToken = "";
        this.authorization = "";
    }

    applyToken(data = {}) {
        this.accessToken = data.accessToken || data.access_token || "";
        this.authorization = data.authorization || (this.accessToken ? `bearer${this.accessToken}` : "");
        this.userInfo = data;
    }

    getHeaders(extra = {}) {
        const headers = {
            "User-Agent": USER_AGENT,
            "Referer": `https://servicewechat.com/${MINI_APP_ID}/42/page-frame.html`,
            "Accept": "application/json, text/plain, */*",
            appId: MINI_APP_ID,
            version: APP_VERSION,
            envVersion: ENV_VERSION,
            "xy-extra-data": `appid=${MINI_APP_ID};version=${APP_VERSION};envVersion=${ENV_VERSION};`,
            ...extra,
        };
        if (this.authorization) headers.Authorization = this.authorization;
        return headers;
    }

    async request({ method = "POST", apiPath, params = {}, data = {}, skipToken = false }) {
        const options = {
            method,
            url: `${API_BASE}${apiPath}`,
            headers: this.getHeaders(method === "POST" ? { "Content-Type": "application/json" } : {}),
            timeout: 15000,
            validateStatus: () => true,
        };
        if (method === "GET") options.params = params;
        else options.data = data;
        if (skipToken) delete options.headers.Authorization;

        const { status, data: result } = await axios.request(options);
        if (status !== 200) throw new Error(`HTTP ${status}: ${JSON.stringify(result)}`);
        if (result && typeof result === "object" && result.error !== undefined && result.error !== 0) {
            const err = new Error(result.errorMsg || result.msg || JSON.stringify(result));
            err.code = result.error;
            throw err;
        }
        return result?.data ?? result;
    }

    async getLoginCode() {
        return await getCode(this.server);
    }

    async loginByWxCode() {
        try {
            const code = await this.getLoginCode();
            if (!code) throw new Error("获取code失败");
            const data = await this.request({
                apiPath: "/appLogin",
                skipToken: true,
                data: {
                    appType: 1,
                    principal: code,
                },
            });
            this.applyToken(data);
            if (!this.accessToken) {
                const keys = Object.keys(data).join(",");
                const subKeys = data && typeof data.data === "object" ? `, data内: ${Object.keys(data.data).join(",")}` : "";
                console.log(`账号[${this.index}] 登录响应缺少 accessToken（响应字段: ${keys}${subKeys}）`);
                throw new Error("登录响应缺少 accessToken");
            }
            // 登录后立即校验 token 是否真实可用，避免拿到无效 token 后级联 401
            if (!(await this.checkToken())) {
                const keys = Object.keys(data).join(",");
                const subKeys = data && typeof data.data === "object" ? `, data内: ${Object.keys(data.data).join(",")}` : "";
                console.log(`账号[${this.index}] 登录响应字段: ${keys}${subKeys}，token 无效（账号可能未注册/未绑定呼啦圈）`);
                throw new Error("登录成功但 token 无效（账号可能未注册/未绑定呼啦圈）");
            }
            this.saveCachedToken();
            const uid = this.userInfo.userId || data.userId || "";
            console.log(`账号[${this.index}] 登录成功: userId=${uid}`);
        } catch (e) {
            // 登录/校验失败则清空 token，使 run() 的守卫能提前退出，避免级联 401
            this.accessToken = "";
            this.authorization = "";
            console.log(`账号[${this.index}] 登录失败: ${e.message || e}`);
        }
    }

    async checkToken() {
        try {
            await this.getUserInfo(false);
            return true;
        } catch (e) {
            return false;
        }
    }

    async getUserInfo(log = true) {
        const data = await this.request({
            method: "GET",
            apiPath: "/p/user/userInfo",
        });
        this.userInfo = {
            ...this.userInfo,
            ...data,
        };
        this.saveCachedToken();
        if (log) console.log(`账号[${this.index}] 用户: ${data.nickName || ""} ${data.memberName || ""}`);
        return data;
    }

    async getPointsInfo() {
        try {
            const data = await this.request({
                method: "GET",
                apiPath: "/pointsSign/user/pointsInfo/query",
            });
            console.log(`账号[${this.index}] 积分: ${data?.pointsNums ?? "未知"} 连签=${data?.seriesDays ?? 0} 今日=${data?.signTodayResult ? "已签" : "未签"}`);
            return data;
        } catch (e) {
            console.log(`账号[${this.index}] 查询积分失败: ${e.message || e}`);
            if (/token|登录|授权|401/i.test(String(e.message || e))) this.removeCachedToken();
        }
    }

    async getSignList() {
        try {
            const data = await this.request({
                method: "GET",
                apiPath: "/pointsSign/user/sign/list",
                params: { v4Flag: true },
            });
            const today = formatDate();
            const todayItem = Array.isArray(data) ? data.find((item) => item?.isToday || item?.dateStr === today) : null;
            this.todayDate = todayItem?.dateStr || today;
            this.isTodaySign = Number(todayItem?.daySignStatus) === 2;
            console.log(`账号[${this.index}] 签到状态: ${this.todayDate} ${this.isTodaySign ? "已签" : "未签"}`);
        } catch (e) {
            console.log(`账号[${this.index}] 查询签到状态失败: ${e.message || e}`);
            if (/token|登录|授权|401/i.test(String(e.message || e))) this.removeCachedToken();
        }
    }

    async doSign() {
        if (this.isTodaySign) {
            console.log(`账号[${this.index}] 今日已签到`);
            return;
        }
        try {
            const date = (this.todayDate || formatDate()).replace(/-/g, "/");
            const data = await this.request({
                method: "GET",
                apiPath: "/pointsSign/user/sign",
                params: { date },
            });
            console.log(`账号[${this.index}] 签到成功: +${data?.signReward ?? "未知"}积分`);
        } catch (e) {
            const message = String(e.message || e);
            if (/已签|重复|今日.*签/i.test(message)) {
                console.log(`账号[${this.index}] 今日已签到`);
                return;
            }
            console.log(`账号[${this.index}] 签到失败: ${message}`);
            if (/token|登录|授权|401/i.test(message)) this.removeCachedToken();
        }
    }
}

!(async () => {
    // 优先从 yyb 拉取全部存活账号（不受 WX_ID 过滤，配 N 条只跑 N 个）
    try {
        const online = await new YYBClient().getOnlineAccounts();
        if (online && online.length) {
            SERVERS = online.map(a => a.openid || a.wxid || a._ref || String(a.id)).filter(Boolean);
            console.log(`✅ 从 yyb 服务拉取到 ${online.length} 个存活账号`);
        }
    } catch (e) {
        console.log(`[yyb] 拉取账号列表失败: ${e.message || e}`);
    }
    // 回退：WX_ID 环境变量
    if (!SERVERS.length) {
        SERVERS = (process.env.WX_ID || "")
            .split(/\r?\n|&/)
            .map(s => s.trim())
            .filter(Boolean);
    }
    // 兜底：从 yyb_go 拉取所有存活账号
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