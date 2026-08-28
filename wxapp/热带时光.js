require('./yyb.js'); // 自动同步 yyb_go 存活账号
/**
// name: 热带时光
------------------------------------------
@Author: sm
@Date: 2026.07.24
@Description: 热带时光 微信小程序每日签到（微信协议版，适配青龙）
cron: 24 13,01 * * *
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
        return await getSingleCode('wx0a73bcd6f11e05e3', __id);
    } catch (e) {
        console.log(__id + " 获取code异常: " + (e && e.message ? e.message : e));
        return null;
    }
}

// ====================== 本地登录态缓存（先走缓存，失效后再 getCode） ======================
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "rdtg_token_cache.json");
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

function getCachedToken(ref) {
    const cache = readTokenCache();
    return cache[ref] || null;
}

function saveCachedToken(ref, value) {
    if (!value || !value.shiruanKey) return;
    const cache = readTokenCache();
    cache[ref] = { ...value, updatedAt: new Date().toISOString() };
    writeTokenCache(cache);
}

function removeCachedToken(ref) {
    const cache = readTokenCache();
    if (cache[ref]) {
        delete cache[ref];
        writeTokenCache(cache);
    }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
let userIdx = 1;

const CK_NAME = "ytb2_all";
const API_BASE = "https://ytb2.zs-shiruan.cn/api";
const LOGIN_BASE = "https://ytb2.zs-shiruan.cn/api-v2";
const USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

const APPS = [
    {
        ck: "rdsgyjd",
        name: "热带时光家庭娱乐中心阳江店",
        appid: "wx0a73bcd6f11e05e3",
        storeId: "2014496",
        signActId: "13417",
    },
].map((app) => ({
    apiBase: process.env[`${app.ck}_api_base`] || API_BASE,
    loginBase: process.env[`${app.ck}_login_base`] || LOGIN_BASE,
    ...app,
    appid: process.env[`${app.ck}_appid`] || app.appid,
    storeId: process.env[`${app.ck}_store_id`] || app.storeId,
    signActId: process.env[`${app.ck}_sign_act_id`] || app.signActId,
}));

function splitAccounts(value = "") {
    return String(value)
        .split(/\n|&/)
        .map((item) => item.trim())
        .filter(Boolean);
}

function unique(items = []) {
    return [...new Set(items.map((item) => String(item || "").trim()).filter(Boolean))];
}

function parseUnifiedEnv() {
    const raw = process.env[CK_NAME] || "";
    const result = { global: [], byKey: {} };
    for (const item of splitAccounts(raw)) {
        const idx = item.indexOf("=");
        if (idx === -1) {
            result.global.push(item);
            continue;
        }
        const key = item.slice(0, idx).trim().toLowerCase();
        const value = item.slice(idx + 1).trim();
        if (!key || !value) continue;
        result.byKey[key] = result.byKey[key] || [];
        result.byKey[key].push(value);
    }
    result.global = unique(result.global);
    return result;
}

const unifiedEnv = parseUnifiedEnv();

function getAccounts(app) {
    const keys = [app.ck, app.appid, app.name].map((item) => item.toLowerCase());
    const accounts = [];
    accounts.push(...SERVERS);
    if (unifiedEnv.global.length) accounts.push(...unifiedEnv.global);
    for (const key of keys) accounts.push(...(unifiedEnv.byKey[key] || []));
    accounts.push(...splitAccounts(process.env[app.ck] || ""));
    return unique(accounts);
}

function maskPhone(phone = "") {
    return String(phone).replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2");
}

function assetValue(memberInfo = {}, keys = [], names = []) {
    const assets = Array.isArray(memberInfo.assets) ? memberInfo.assets : [];
    for (const item of assets) {
        if (keys.includes(item.key) || names.includes(item.name)) return item.num ?? 0;
    }
    return 0;
}

function findSignActId(source) {
    let found = "";
    const walk = (value) => {
        if (found || value === null || value === undefined) return;
        if (typeof value === "string") {
            const match = value.match(/sign-in\/sign-in\?[^"']*actid=(\d+)/i);
            if (match) found = match[1];
            return;
        }
        if (Array.isArray(value)) {
            for (const item of value) walk(item);
            return;
        }
        if (typeof value === "object") {
            for (const item of Object.values(value)) walk(item);
        }
    };
    walk(source);
    return found;
}

class Task {
    constructor(app, account, index) {
        this.server = account;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.app = app;
        this.account = account;
        this.index = index;
        this.shiruanKey = "";
        this.mobile = "";
        this.templateUrl = "";
        this.signActId = app.signActId || "";
        this.summary = {
            appName: app.name,
            member: "未查询",
            assets: "未查询",
            sign: "未执行",
        };

    }

    log(message) {
        console.log(`[${this.app.name}][账号${this.index}] ${message}`);
    }

    headers(extra = {}) {
        return {
            "content-type": "application/json",
            "User-Agent": USER_AGENT,
            ...extra,
        };
    }

    authHeaders(extra = {}) {
        return this.headers({
            shiruanKey: this.shiruanKey,
            miniAppid: this.app.appid,
            ...extra,
        });
    }

    async getWxCode() {
        return await getCode(this.server);
    }

    get cacheKey() {
        return String(this.server).split("#")[0].trim();
    }

    getCachedSession() {
        return getCachedToken(this.cacheKey);
    }

    saveCachedSession() {
        saveCachedToken(this.cacheKey, {
            shiruanKey: this.shiruanKey,
            openid: this.openid,
            mobile: this.mobile,
            templateUrl: this.templateUrl,
        });
    }

    removeCachedSession() {
        removeCachedToken(this.cacheKey);
        this.shiruanKey = "";
    }

    async pingAuth() {
        try {
            const { data } = await axios.post(
                `${this.app.apiBase}/mini/user-asset`,
                {},
                { headers: this.authHeaders(), timeout: 30000 }
            );
            return data?.code === 200;
        } catch (e) {
            return false;
        }
    }

    async login() {
        // 先走缓存: 本地缓存的登录态仍有效则直接使用, 不调用 getCode
        const cached = this.getCachedSession();
        if (cached && cached.shiruanKey) {
            this.shiruanKey = cached.shiruanKey;
            this.openid = cached.openid || this.openid;
            this.mobile = cached.mobile || "";
            this.templateUrl = cached.templateUrl || "";
            if (await this.pingAuth()) {
                this.log(`使用缓存登录态: ${this.openid || maskPhone(this.mobile)}`);
                return;
            }
            this.log(`缓存登录态失效, 重新登录`);
            this.removeCachedSession();
        }
        const code = await this.getWxCode();
        if (!code) throw new Error("获取code失败");
        const { data } = await axios.post(
            `${this.app.loginBase}/mini/preLogin-new`,
            {
                app_id: this.app.appid,
                store_id: this.app.storeId || "",
                code,
            },
            {
                headers: this.headers(),
                timeout: 30000,
            }
        );
        if (data?.code !== 200) throw new Error(`登录失败: ${data?.msg || JSON.stringify(data)}`);
        this.shiruanKey = data.data?.shiruan_key || "";
        this.openid = data.data?.openid || "";
        this.mobile = data.data?.mobile || "";
        this.templateUrl = data.data?.templateUrl || "";
        this.saveCachedSession();
        this.log(`登录成功: ${maskPhone(this.mobile)} openId=${this.openid}`);
    }

    async detectSignActId() {
        if (this.signActId) return this.signActId;
        if (!this.templateUrl) return "";
        try {
            const { data } = await axios.get(this.templateUrl, {
                headers: this.headers(),
                timeout: 30000,
            });
            this.signActId = findSignActId(data);
            if (this.signActId) this.log(`识别签到活动ID: ${this.signActId}`);
        } catch (e) {
            this.log(`读取模板失败: ${e.message || e}`);
        }
        return this.signActId;
    }

    async queryAssets() {
        const { data } = await axios.post(
            `${this.app.apiBase}/mini/user-asset`,
            {},
            {
                headers: this.authHeaders(),
                timeout: 30000,
            }
        );
        if (data?.code !== 200) throw new Error(`查询失败: ${data?.msg || JSON.stringify(data)}`);
        const info = data.data?.member_info || {};
        const phone = info.leag_tel || data.data?.mobile || this.mobile;
        const card = info.card_no || info.leag_no || "未知会员";
        const coin = assetValue(info, ["coin_bal"], ["代币"]);
        const point = assetValue(info, ["score"], ["积分", "娃娃积分"]);
        const ticket = assetValue(info, ["tick_bal", "new_ticket"], ["奖票", "特殊奖票"]);
        const gateTicket = assetValue(info, ["ticket_amount"], ["门票"]);
        this.summary.member = `${card} ${maskPhone(phone)}`;
        this.summary.assets = `代币=${coin} 积分=${point} 彩票=${ticket} 门票=${gateTicket}`;
        this.log(`会员: ${this.summary.member} ${this.summary.assets}`);
    }

    async sign() {
        const actId = await this.detectSignActId();
        if (!actId) {
            this.summary.sign = "未找到签到活动ID";
            this.log(this.summary.sign);
            return;
        }
        try {
            const info = await axios.get(`${this.app.apiBase}/marketing/sign-info?marketing_activity_id=${actId}`, {
                headers: this.authHeaders(),
                timeout: 30000,
            });
            if (info.data?.code === 200) {
                const d = info.data.data || {};
                const activityName = d.activity?.name || actId;
                this.log(`签到活动: ${activityName} 已签=${d.is_sign_today || 0} 累计=${d.sign_day || 0}天`);
                if (Number(d.is_sign_today) === 1) {
                    this.summary.sign = `今日已签到 累计=${d.sign_day || 0}天`;
                    return;
                }
            } else {
                this.log(`签到状态查询: ${info.data?.msg || JSON.stringify(info.data)}`);
            }

            const { data } = await axios.get(`${this.app.apiBase}/marketing/new-sign?marketing_activity_id=${actId}`, {
                headers: this.authHeaders(),
                timeout: 30000,
            });
            const gifts = Array.isArray(data?.data?.gifts)
                ? data.data.gifts.map((item) => `${item.num ?? item.gift_num ?? ""}${item.asset_name || item.name || ""}`.trim()).filter(Boolean)
                : [];
            this.summary.sign = `${data?.msg || "签到返回"}${gifts.length ? `: ${gifts.join("、")}` : ""}`;
            this.log(this.summary.sign);
        } catch (e) {
            this.summary.sign = `签到失败: ${e.message || e}`;
            this.log(this.summary.sign);
        }
    }

    async run() {
        try {
            await this.login();
            await this.queryAssets();
            await this.sign();
            await this.queryAssets();
        } catch (e) {
            this.summary.sign = `执行失败: ${e.message || e}`;
            this.log(this.summary.sign);
        }
        return this.summary;
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
    const plan = APPS.map((app) => ({ app, accounts: getAccounts(app) })).filter((item) => item.accounts.length);
    const totalAccounts = plan.reduce((sum, item) => sum + item.accounts.length, 0);
    console.log(`共找到${plan.length}个小程序，${totalAccounts}个执行账号`);
    if (!plan.length) {
        console.log(`未配置 WX_ID 或 ${CK_NAME} 变量`);
        return;
    }

    const summaries = [];
    for (const { app, accounts } of plan) {
        console.log(`\n========== ${app.name} (${app.ck}) ==========`);
        let index = 1;
        for (const account of accounts) {
            summaries.push(await new Task(app, account, index++).run());
        }
    }

    console.log("\n========== 执行汇总 ==========");
    for (const item of summaries) {
        console.log(`${item.appName}: ${item.member} ${item.assets} 签到=${item.sign}`);
    }
})()
    .catch((e) => console.log(e.message || e))