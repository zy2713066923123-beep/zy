require('./yyb.js'); // 自动同步 yyb_go 存活账号
/*
------------------------------------------
@Author: sm
@Date: 2026.05.31
@Description: 日清食品小程序签到
cron: 48 11,15 * * *
变量名：nissin
变量值：wx_server 里的 openid/账号标识，多账号用 & 或换行
------------------------------------------

变量：
  WX_SERVER      yyb_go 协议服务地址（例如：http://127.0.0.1:8000）
  WX_ID         (可选白名单) 微信账号，多账号支持换行、& 分隔，留空自动拉取 yyb_go 所有存活账号

WX_ID 格式：
  wxid#备注  多个换行
*/

class WeChatServer {
    constructor(config) { this.config = config; }
    async getCode(wxid) {
        try {
            const actualWxid = String(wxid).split('#')[0].trim();
            const code = await getSingleCode(this.config.appid, actualWxid);
            return { data: { status: true, code, data: { code } } };
        } catch (e) {
            return { data: {} };
        }
    }
}

class Env {
    constructor(name) { this.name = name; this.userList = []; this.userIdx = 1; this.logs = []; const originalLog = console.log; console.log = (...args) => { this.logs.push(args.join(" ")); originalLog.apply(console, args); }; }
    log(...args) { console.log(...args); this.logs.push(args.join(" ")); }
    async checkEnv(ckName) {
        const list = await global.resolveAccounts(ckName);
        this.userList = list;
        if (!this.userList.length) console.log('未找到环境变量 WX_ID，且 yyb_go 无存活账号');
    }
    async done() { try { const notify = require('../sendNotify'); await notify.sendNotify(this.name, this.logs.join('\n')); } catch(e) { console.log('通知发送失败', e); } }
}



const $ = new Env("日清食品签到");
const axios = require("axios");
const fs = require("fs");
const path = require("path");


const MINI_APP_ID = "wx21b71db59d93bd6d";
const API_BASE = "https://foodhall-prod-api.nissinfoodium.com.cn/miniapp";
const PAGE_VERSION = "74";
const TOKEN_CACHE_FILE = path.join(__dirname, "nissin_token_cache.json");
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

let ckName = "WX_ID";

// 小游戏配置
const GAME_PLAY = process.env.NISSIN_PLAY_GAME !== "0" && process.env.NISSIN_PLAY_GAME !== "false";
const GAME_TIMES = parseInt(process.env.NISSIN_GAME_TIMES, 10) || 1;
const GAME_SCORE_MIN = parseInt(process.env.NISSIN_GAME_SCORE_MIN, 10) || 14600;
const GAME_SCORE_MAX = parseInt(process.env.NISSIN_GAME_SCORE_MAX, 10) || 14999;
const GAME_DELAY = parseInt(process.env.NISSIN_GAME_DELAY, 10) || 3;

// 兼容旧版固定分数（优先使用 NISSIN_GAME_SCORE）
function getGameScore() {
    const fixedScore = parseInt(process.env.NISSIN_GAME_SCORE, 10);
    if (fixedScore > 0) return fixedScore;
    // 随机分数 [GAME_SCORE_MIN, GAME_SCORE_MAX]
    return Math.floor(Math.random() * (GAME_SCORE_MAX - GAME_SCORE_MIN + 1)) + GAME_SCORE_MIN;
}
const GAME_REFERER = "https://foodhall-prod.nissinfoodium.com.cn/";

const wechat = new WeChatServer({
    url: process.env.WX_SERVER || process.env.WECHAT_SERVER || "http://127.0.0.1:8000",
    appid: MINI_APP_ID,
    WX_ID: process.env.WX_ID || "",
});

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
        $.log(`写入token缓存失败: ${e.message || e}`);
    }
}

function maskPhone(phone = "") {
    return String(phone).replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2");
}

function isTokenError(e) {
    const message = String(e?.message || e || "");
    return e?.code === 401 || e?.code === 900001 || /401|900001|token|登录|授权|Auth-Status|invalid/i.test(message);
}

class Task {
    constructor(openid) {
        this.index = $.userIdx++;
        this.openid = String(openid || "").split('#')[0].trim();
        this.token = "";
        this.redOpenId = "";
        this.userId = "";
        this.user = {};
    }

    async run() {
        const cached = this.getCachedToken();
        if (cached) {
            this.applyToken(cached);
            $.log(`账号[${this.index}] 使用缓存token`);
            if (!(await this.checkToken())) {
                this.removeCachedToken();
                $.log(`账号[${this.index}] 缓存token失效，重新登录`);
            }
        }

        if (!this.token) {
            try { await this.loginByWxCode(); } catch (e) { $.log(`账号[${this.index}] 登录失败: ${e.message || e}`); }
            if (!this.token) return;
        }

        await this.getUser();
        await this.getSignInInfo();
        await this.doSign();
        await this.runGame();
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
            redOpenId: this.redOpenId,
            userId: this.userId,
            mobile: this.user.mobile || "",
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
        this.redOpenId = "";
        this.userId = "";
    }

    applyToken(data = {}) {
        this.token = data.accessToken || data.access_token || "";
        this.redOpenId = data.redOpenId || data.openId || data.open_id || "";
        this.userId = data.userId || data.user_id || "";
    }

    getHeaders(extra = {}, refererOverride) {
        const referer = refererOverride || `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`;
        const headers = {
            "User-Agent": USER_AGENT,
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
            ...extra,
        };
        if (this.token) headers.Authorization = `Bearer ${this.token}`;
        return headers;
    }

    async request({ method = "GET", apiPath, data, params, skipToken = false, refererOverride }) {
        const options = {
            method,
            url: `${API_BASE}${apiPath.startsWith("/") ? apiPath : `/${apiPath}`}`,
            headers: this.getHeaders(method === "POST" ? { "Content-Type": "application/json" } : {}, refererOverride),
            timeout: 15000,
            validateStatus: () => true,
        };
        if (params) options.params = params;
        if (data !== undefined) options.data = data;
        if (skipToken) delete options.headers.Authorization;

        const { status, data: result, headers } = await axios.request(options);
        if (status !== 200) throw new Error(`HTTP ${status}: ${JSON.stringify(result)}`);
        if (headers && headers["auth-status"] === "false") {
            const err = new Error("Auth-Status=false");
            err.code = 900001;
            throw err;
        }
        if (!result || result.code !== 0) {
            const err = new Error(result?.msg || result?.message || JSON.stringify(result));
            err.code = result?.code;
            throw err;
        }
        return result.data;
    }

    async getLoginCode() {
        const { data } = await wechat.getCode(this.openid);
        const code = data?.code || data?.data?.code;
        if (!code) throw new Error(`wx_server 未返回 code: ${JSON.stringify(data)}`);
        return code;
    }

    async loginByWxCode() {
        try {
            const code = await this.getLoginCode();
            const openData = await this.request({
                method: "POST",
                apiPath: "/auth/getOpenId",
                skipToken: true,
                data: {
                    code,
                    invitorMemberId: 0,
                },
            });
            this.redOpenId = openData.openId || "";
            if (!this.redOpenId) throw new Error(`auth/getOpenId 未返回 openId: ${JSON.stringify(openData)}`);

            const loginData = await this.request({
                method: "POST",
                apiPath: "/auth/login",
                skipToken: true,
                data: {
                    openId: this.redOpenId,
                },
            });
            this.applyToken({
                ...loginData,
                redOpenId: this.redOpenId,
            });
            this.saveCachedToken();
            $.log(`账号[${this.index}] 登录成功: userId=${this.userId || "未知"}`);
        } catch (e) {
            $.log(`账号[${this.index}] 登录失败: ${e.message || e}`);
        }
    }

    async checkToken() {
        try {
            await this.getSignInInfo(true);
            return true;
        } catch (e) {
            return false;
        }
    }

    async getUser() {
        try {
            const data = await this.request({ apiPath: "/auth/user/current" });
            this.user = data || {};
            // 兼容多种字段名
            const nick = data?.nickname || data?.nickName || data?.name || data?.memberName || "";
            const phone = data?.mobile || data?.phone || data?.phoneNumber || "";
            const uid = data?.id || data?.userId || data?.memberId || "";
            $.log(`账号[${this.index}] 用户: ${nick || "未知"} ${maskPhone(phone) || ""} ID:${uid || "未知"}`);
            if (uid) this.userId = String(uid);
            this.saveCachedToken();
        } catch (e) {
            $.log(`账号[${this.index}] 查询用户失败: ${e.message || e}`);
            if (isTokenError(e)) this.removeCachedToken();
        }
    }

    async getSignInInfo(silent = false) {
        const data = await this.request({ apiPath: "/sign-in/statistics" });
        this.signInfo = data || {};
        if (!silent) {
            $.log(`账号[${this.index}] 签到状态: ${data?.hasSignedToday ? "已签" : "未签"} 连续${data?.continuousDays || 0}天 总${data?.totalDays || 0}天 今日${data?.todayPoints ?? "未知"}积分`);
        }
        return data;
    }

    async doSign() {
        if (this.signInfo?.hasSignedToday) {
            $.log(`账号[${this.index}] 今日已签到`);
            return;
        }
        try {
            const data = await this.request({
                method: "POST",
                apiPath: "/sign-in",
                data: {},
            });
            $.log(`账号[${this.index}] 签到成功: +${data ?? "未知"}积分`);
            await this.getSignInInfo();
        } catch (e) {
            const message = String(e.message || e);
            if (/已签到|重复|今日.*签/i.test(message)) {
                $.log(`账号[${this.index}] 今日已签到`);
                return;
            }
            $.log(`账号[${this.index}] 签到失败: ${message}`);
            if (isTokenError(e)) this.removeCachedToken();
        }
    }

    async getTaskList() {
        try {
            const data = await this.request({ apiPath: "/taskCenter/getEffectiveTask" });
            return Array.isArray(data) ? data : [];
        } catch (e) {
            $.log(`账号[${this.index}] 查询任务列表失败: ${e.message || e}`);
            if (isTokenError(e)) this.removeCachedToken();
            return [];
        }
    }

    // ---- 小游戏相关方法 ----

    async gameCount() {
        return await this.request({ apiPath: "/game/count", refererOverride: GAME_REFERER });
    }

    async gameProp() {
        try {
            return await this.request({ apiPath: "/game/prop", refererOverride: GAME_REFERER });
        } catch (e) {
            $.log(`账号[${this.index}] 查询游戏道具失败: ${e.message || e}`);
            return null;
        }
    }

    async gameBegin() {
        return await this.request({
            method: "POST",
            apiPath: "/game/begin",
            data: { loginIp: "" },
            refererOverride: GAME_REFERER,
        });
    }

    async gameEnd(playId, score) {
        return await this.request({
            method: "POST",
            apiPath: "/game/end",
            data: { score, playId },
            refererOverride: GAME_REFERER,
        });
    }

    async runGame() {
        if (!GAME_PLAY) {
            $.log(`账号[${this.index}] 小游戏已关闭 (NISSIN_PLAY_GAME=0)`);
            return;
        }
        $.log(`账号[${this.index}] ☼ ――――  小 游 戏  ―――― ☼`);

        // 先登录游戏（这是获取次数的前提）
        try {
            const loginRes = await this.request({
                method: "POST",
                apiPath: "/game/login",
                data: { loginIp: "", loginLocation: "" },
                refererOverride: GAME_REFERER,
            });
            $.log(`账号[${this.index}] 游戏登录成功: ${JSON.stringify(loginRes)}`);
        } catch (e) {
            $.log(`账号[${this.index}] 游戏登录失败: ${e.message || e}`);
        }

        // 查询剩余次数
        let remainCount = 0;
        let runTimes = GAME_TIMES;  // 声明在 try 外面，确保 for 循环能访问
        try {
            const countData = await this.gameCount();
            // /game/count 可能返回纯数字(如 1) 或对象({ count: 1 })
            if (typeof countData === "number") {
                remainCount = countData;
            } else {
                remainCount = countData?.count ?? countData?.num ?? countData?.remainCount ?? countData?.remainingCount ?? 0;
            }
            if (typeof remainCount !== "number") remainCount = 0;
            runTimes = Math.min(GAME_TIMES, remainCount);
            if (remainCount <= 0) {
                $.log(`账号[${this.index}] 小游戏次数: 0，跳过`);
                return;
            }
            $.log(`账号[${this.index}] 小游戏剩余 ${remainCount} 次，本次执行 ${runTimes} 次`);
        } catch (e) {
            $.log(`账号[${this.index}] 查询游戏次数失败，按配置尝试执行: ${e.message || e}`);
        }

        // 查询道具
        try {
            const propData = await this.gameProp();
            if (propData) $.log(`账号[${this.index}] 游戏道具: ${JSON.stringify(propData)}`);
        } catch (e) {}

        // 循环执行小游戏
        for (var i = 1; i <= runTimes; i++) {
            try {
                const beginData = await this.gameBegin();
                const playId = beginData?.playId || beginData?.id || beginData;
                if (!playId) {
                    $.log(`账号[${this.index}] 小游戏第${i}次开始失败: 未返回playId`);
                    continue;
                }
                $.log(`账号[${this.index}] 小游戏第${i}次开始成功: playId=${playId}`);
                if (GAME_DELAY > 0) await new Promise(r => setTimeout(r, GAME_DELAY * 1000));
                const score = getGameScore();
                const endData = await this.gameEnd(String(playId), score);
                const msg = endData?.msg || endData?.message || "成功";
                $.log(`账号[${this.index}] 小游戏第${i}次提交: score=${score}, ${msg}`);
                await new Promise(r => setTimeout(r, 1000));
            } catch (e) {
                $.log(`账号[${this.index}] 小游戏第${i}次失败: ${e.message || e}`);
            }
        }
    }

    async enterGame() {
        // 保留用于单独检查任务状态（runGame 中已包含实际游戏逻辑）
        try {
            const tasks = await this.getTaskList();
            const gameTask = tasks.find((item) => item?.ruleType === "PLAY_GAME");
            if (gameTask) $.log(`账号[${this.index}] 玩游戏任务: ${gameTask.complete ? "已完成" : "未完成"}`);
        } catch (e) {}
    }
}

(async () => {
    $.checkEnv(ckName);
    for (const openid of $.userList) {
        await new Task(openid).run();
    }
})()
    .catch((e) => $.log(e.message || e))
    .finally(() => $.done());