require('./yyb.js'); // 自动同步 yyb_go 存活账号
/**
// name: 影视飓风
------------------------------------------
@Author: sm
@Date: 2026.07.24
@Description: 影视飓风 微信小程序每日签到（微信协议版，适配青龙）
cron: 48 10,22 * * *
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

const MINI_APP_ID = "wx92782ef90ebc836d";
const CLIENT_ID = "4d65249d377b2c3ed8";
const CLIENT_SECRET = "1cdc05151d64f3a4a6ebd0e9de64422a";
const GRANT_TYPE = "yz_union";
const CLIENT_BIZ = "weapp_wsc";
const KDT_ID = "149536603";
const USER_VERSION = "2.226.7.101";
const PAGE_VERSION = "17";
const API_BASE = "https://h5.youzan.com";
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "yingshijufeng_token_cache.json");
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

function maskPhone(phone = "") {
    return String(phone).replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2");
}

function pickToken(data = {}) {
    return data.accessToken || data.access_token || "";
}

function isTokenError(message) {
    return /access_token|token|登录|授权|invalid session|session/i.test(String(message || ""));
}

class Task {
    constructor(openid) {
        this.server = openid;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.index = userIdx++;
        this.openid = String(openid || "").trim();
        this.token = "";
        this.sessionId = "";
        this.cookie = "";
        this.kdtId = KDT_ID;
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

        if (!this.token) {
            await this.loginByWxCode();
            if (!this.token) return;
        }

        await this.showCheckinPage();
        await this.doCheckin();
        await this.getPoints();
    }

    getCachedToken() {
        const cache = readTokenCache();
        return cache[this.openid] || null;
    }

    saveCachedToken() {
        if (!this.token) return;
        const cache = readTokenCache();
        cache[this.openid] = {
            accessToken: this.token,
            sessionId: this.sessionId,
            kdtId: this.kdtId,
            cookie: this.cookie,
            mobile: this.userInfo.mobile || "",
            nickName: this.userInfo.nick_name || this.userInfo.nickName || "",
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
        this.token = "";
        this.sessionId = "";
        this.cookie = "";
    }

    applyToken(data = {}) {
        this.token = pickToken(data);
        this.sessionId = data.sessionId || data.session_id || "";
        this.kdtId = String(data.kdtId || data.kdt_id || KDT_ID);
        this.cookie = data.cookie || "";
    }

    getHeaders(extra = {}) {
        const headers = {
            "User-Agent": USER_AGENT,
            "Referer": `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
            "Accept": "*/*",
            "Extra-Data": JSON.stringify({
                sid: this.sessionId || "",
                version: USER_VERSION,
                clientType: "weapp-miniprogram",
                client: "weapp",
                bizEnv: "wsc",
            }),
            ...extra,
        };
        if (this.cookie) headers.Cookie = this.cookie;
        return headers;
    }

    getBaseParams(params = {}) {
        return {
            app_id: MINI_APP_ID,
            kdt_id: this.kdtId,
            access_token: this.token,
            ...params,
        };
    }

    async request({ method = "GET", path: apiPath, params = {}, data = {}, skipToken = false }) {
        const options = {
            method,
            url: `${API_BASE}${apiPath.startsWith("/") ? apiPath : `/${apiPath}`}`,
            headers: this.getHeaders(method === "POST" ? { "Content-Type": "application/json" } : {}),
            timeout: 15000,
            validateStatus: () => true,
        };
        options.params = skipToken ? params : this.getBaseParams(params);
        if (method !== "GET") options.data = data;

        const { data: result, status, headers } = await axios.request(options);
        if (headers["set-cookie"]) {
            this.cookie = headers["set-cookie"].map((item) => item.split(";")[0]).join("; ");
        }
        if (status !== 200) throw new Error(`HTTP ${status}: ${JSON.stringify(result)}`);
        if (!result || result.code !== 0) throw new Error(result?.msg || JSON.stringify(result));
        return result.data;
    }

    async getLoginCode() {
        return await getCode(this.server);
    }

    async authorize(code, data) {
        return this.request({
            method: "POST",
            path: "/wscshop/weapp/authorize.json",
            skipToken: true,
            data: { ...data, code },
        });
    }

    async loginByWxCode() {
        try {
            const code = await this.getLoginCode();
            let data;
            try {
                data = await this.authorize(code, {
                    appId: MINI_APP_ID,
                    clientId: CLIENT_ID,
                    clientSecret: CLIENT_SECRET,
                    grantType: GRANT_TYPE,
                });
            } catch (e) {
                data = await this.authorize(code, {
                    appId: MINI_APP_ID,
                    clientBiz: CLIENT_BIZ,
                });
            }
            this.applyToken(data);
            this.userInfo = data || {};
            this.saveCachedToken();
            console.log(`账号[${this.index}] 登录成功: ${data.nick_name || data.nickName || ""} ${maskPhone(data.mobile) || ""}`);
        } catch (e) {
            console.log(`账号[${this.index}] 登录失败: ${e.message || e}`);
        }
    }

    async checkToken() {
        try {
            await this.request({ path: "/wscump/checkin/show_checkin_page_v2.json" });
            return true;
        } catch (e) {
            return false;
        }
    }

    async showCheckinPage() {
        try {
            const data = await this.request({ path: "/wscump/checkin/show_checkin_page_v2.json" });
            this.checkinId = data?.checkinId;
            this.isShow = !!data?.isShow;
            console.log(`账号[${this.index}] 签到活动: checkinId=${this.checkinId || "未获取"} isShow=${this.isShow}`);
        } catch (e) {
            console.log(`账号[${this.index}] 获取签到活动失败: ${e.message || e}`);
            if (isTokenError(e.message || e)) this.removeCachedToken();
        }
    }

    async doCheckin() {
        if (!this.checkinId) {
            console.log(`账号[${this.index}] 未获取到 checkinId，跳过签到`);
            return;
        }
        try {
            const data = await this.request({
                path: "/wscump/checkin/checkinV2.json",
                params: { checkinId: this.checkinId },
            });
            const awards = (data?.list || []).map((item) => item?.infos?.title).filter(Boolean).join(", ");
            console.log(`账号[${this.index}] 签到成功: ${data?.desc || ""}${awards ? ` ${awards}` : ""}`);
        } catch (e) {
            const message = String(e.message || e);
            if (/已达最大参与次数|已签到|重复签到/.test(message)) {
                console.log(`账号[${this.index}] 今日已签到`);
                return;
            }
            console.log(`账号[${this.index}] 签到失败: ${message}`);
            if (isTokenError(message)) this.removeCachedToken();
        }
    }

    async getPoints() {
        try {
            const data = await this.request({ path: "/wscump/integral/user_points.json" });
            console.log(`账号[${this.index}] 当前积分: ${data?.current_points ?? data?.real_points ?? "未知"}`);
        } catch (e) {
            console.log(`账号[${this.index}] 查询积分失败: ${e.message || e}`);
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