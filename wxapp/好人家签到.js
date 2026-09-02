require('./yyb.js'); // 自动同步 yyb_go 存活账号
/*
------------------------------------------
@Author: sm
@Date: 2026.05.31
@Description: 好人家签到+抽奖
cron: 56 09,21 * * *
变量名：hrj
变量值：wx_server 里的 openid/账号标识，多账号用 & 或换行
------------------------------------------

变量：
  WX_SERVER      yyb_go 协议服务地址（例如：http://127.0.0.1:18273）
  WX_ID         (可选白名单) 微信账号，多账号支持换行、& 分隔，留空自动拉取 yyb_go 所有存活账号
  HRJ_BIRTHDAY  抽奖会员年龄分析用的生日（默认 1995-09-02）

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

const $ = new Env("好人家签到");
const axios = require("axios");
const fs = require("fs");
const path = require("path");


const MINI_APP_ID = "wx160c589739c6f8b0";
const PAGE_VERSION = "116";
const API_HOST = "https://xapi.weimob.com";
const API_BASE = `${API_HOST}/api3`;
const TOKEN_CACHE_FILE = path.join(__dirname, "hrj_token_cache.json");
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

const DRAW_ACTIVITY = {
    activityId: "30000159706",
    templateId: 808,
    templateKey: "armbandit",
    activityIdentity: "20",
    playSourceCode: "lcode",
    productId: 344,
    productInstanceId: 8687699273,
    productVersionId: "12028",
    merchantId: 2000210519273,
    cid: 505934273,
    vid: 6015869513273,
    vidType: 2,
    bosId: 4021565647273,
    openIdField: true,
};
const DRAW_BIRTHDAY = process.env.HRJ_BIRTHDAY || "1995-09-02";

const FORM_BASIC_INFO = {
    bosId: "4021565647273",
    cid: "505934273",
    productInstanceId: "8689235273",
    tcode: "weimob",
    vid: "6015869513273",
};

const ONECRM_BASIC_INFO = {
    bosId: "4021565647273",
    cid: "505934273",
    productId: 146,
    productInstanceId: "8689224273",
    tcode: "weimob",
    vid: "6015869513273",
};

const EXTEND_INFO = {
    analysis: [],
    bosTemplateId: 1000002218,
    childTemplateIds: [
        { customId: 90004, version: "crm@0.1.90" },
        { customId: 90002, version: "ec@84.0" },
        { customId: 90006, version: "hudong@0.0.251" },
        { customId: 90008, version: "cms@0.0.529" },
        { customId: 90070, version: "1.0.19y" },
    ],
    quickdeliver: { enable: false },
    wxTemplateId: 8169,
    youshu: { enable: false },
    source: 1,
    channelsource: 1,
    mpScene: 1001,
};

let ckName = "WX_ID";

const wechat = new WeChatServer({
    url: process.env.WX_SERVER || process.env.YYB_SERVER || process.env.WECHAT_SERVER || process.env.YINGYONGBAO_SERVER || "http://127.0.0.1:18273",
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

function isTokenError(message) {
    return /token|登录|授权|invalid|expire|过期|1041|401|403/i.test(String(message || ""));
}

function rewardText(items) {
    if (!Array.isArray(items) || !items.length) return "";
    return items.map((item) => `${item.key || "奖励"}${item.value || ""}`).join(" ");
}

class Task {
    constructor(openid) {
        this.index = $.userIdx++;
        this.openid = String(openid || "").split('#')[0].trim();
        this.session = {};
    }

    async run() {
        const cached = this.getCachedToken();
        if (cached) {
            this.session = cached;
            $.log(`账号[${this.index}] 使用缓存token`);
            if (!(await this.checkToken())) {
                this.removeCachedToken();
                $.log(`账号[${this.index}] 缓存token失效，重新登录`);
            }
        }

        if (!this.session.token) {
            try { await this.loginByWxCode(); } catch (e) { $.log(`账号[${this.index}] 登录失败: ${e.message || e}`); }
            if (!this.session.token) return;
        }

        await this.doSign();
        await this.doDraw();
        this.saveCachedToken();
    }

    getCachedToken() {
        const cache = readTokenCache();
        return cache[this.openid] || null;
    }

    saveCachedToken() {
        if (!this.session.token) return;
        const cache = readTokenCache();
        cache[this.openid] = {
            uuid: this.session.uuid,
            bosId: this.session.bosId,
            wid: this.session.wid,
            appId: this.session.appId,
            cid: this.session.cid,
            scope: this.session.scope,
            status: this.session.status,
            sourceType: this.session.sourceType,
            source: this.session.source,
            token: this.session.token,
            expireTime: this.session.expireTime,
            latestExpireTime: this.session.latestExpireTime,
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
        this.session = {};
    }

    getHeaders() {
        return {
            "Content-Type": "application/json",
            "X-WX-Token": this.session.token || "",
            "User-Agent": USER_AGENT,
            "Referer": `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
            "weimob-bosId": ONECRM_BASIC_INFO.bosId,
            "weimob-pid": "N/A",
        };
    }

    buildWosBody(data = {}) {
        return {
            appid: MINI_APP_ID,
            basicInfo: { ...ONECRM_BASIC_INFO },
            extendInfo: { ...EXTEND_INFO },
            i18n: {
                language: "zh",
                timezone: "8",
            },
            ...data,
        };
    }

    async request(apiPath, data = {}) {
        const res = await axios.post(`${API_BASE}${apiPath}`, this.buildWosBody(data), {
            headers: this.getHeaders(),
            timeout: 20000,
            validateStatus: () => true,
        });
        if (res.status !== 200) throw new Error(`HTTP ${res.status}`);
        if (`${res.data?.errcode}` !== "0") {
            const error = new Error(res.data?.errmsg || `接口错误: ${res.data?.errcode || "unknown"}`);
            error.data = res.data;
            throw error;
        }
        return res.data?.data;
    }

    buildDrawHeaders(extra = {}) {
        const now = Date.now();
        return {
            "content-type": "application/json",
            "x-cmssdk-vidticket": `${Math.floor(Math.random() * 9000 + 1000)}-${Math.floor(now / 1000)}.${String(now).slice(-3)}-saas-w1-${Math.floor(Math.random() * 9000 + 1000)}-${Math.random().toString(16).slice(2, 14)}`,
            "x-wmsdk-close-store": "v2",
            "x-apm-page-id": `${Math.random().toString(16).slice(2, 10)}-${Math.random().toString(16).slice(2, 6)}-${Math.random().toString(16).slice(2, 6)}-${Math.random().toString(16).slice(2, 6)}-${Math.random().toString(16).slice(2, 14)}`,
            "weimob-pid": "N/A",
            "weimob-bosid": String(DRAW_ACTIVITY.bosId),
            "x-wmsdk-bc": `2 ${now}`,
            "x-req-from": extra.reqFrom || "hd_lego",
            "x-page-route": extra.pageRoute || "hd_lego/index",
            "cloud-bosid": String(DRAW_ACTIVITY.bosId),
            "x-tp-uuid": Math.random().toString(16).slice(2, 42).padEnd(40, "0").slice(0, 40),
            "x-apm-conversation-id": `${Math.random().toString(16).slice(2, 10)}-${Math.random().toString(16).slice(2, 6)}-${Math.random().toString(16).slice(2, 6)}-${Math.random().toString(16).slice(2, 6)}-${Math.random().toString(16).slice(2, 14)}`,
            "x-component-is": extra.componentIs || "hd_lego/RAW/games/stage/stage",
            "x-wmsdk-vid": String(DRAW_ACTIVITY.vid),
            "x-biz-id": String(extra.bizId || DRAW_ACTIVITY.productId),
            "x-tp-signature": Math.random().toString(16).slice(2, 42).padEnd(40, "0").slice(0, 40),
            "cloud-project-name": "newrabbitpre",
            "x-wx-token": this.session.token || "",
            "cookie": `rprm_cuid=${Math.random().toString(16).slice(2, 22)}`,
            "parentrpcid": Math.random().toString(16).slice(2, 18),
            "x-cms-sdk-request": "1.5.151",
            "wos-x-channel": "0:TITAN",
            "user-agent": USER_AGENT,
            "referer": `https://servicewechat.com/${MINI_APP_ID}/121/page-frame.html`,
            "accept-encoding": "gzip,compress,br,deflate",
        };
    }

    buildDrawBody(extra = {}) {
        return {
            appid: MINI_APP_ID,
            basicInfo: {
                vid: DRAW_ACTIVITY.vid,
                vidType: DRAW_ACTIVITY.vidType,
                bosId: DRAW_ACTIVITY.bosId,
                productId: DRAW_ACTIVITY.productId,
                productInstanceId: DRAW_ACTIVITY.productInstanceId,
                productVersionId: DRAW_ACTIVITY.productVersionId,
                merchantId: DRAW_ACTIVITY.merchantId,
                tcode: "weimob",
                cid: DRAW_ACTIVITY.cid,
            },
            extendInfo: {
                wxTemplateId: 8265,
                childTemplateIds: [
                    { customId: 90004, version: "crm@0.1.101" },
                    { customId: 90002, version: "ec@90.0" },
                    { customId: 90006, version: "hudong@0.0.255" },
                    { customId: 90008, version: "cms@0.0.537" },
                    { customId: 90070, version: "1.0.43" },
                ],
                analysis: [],
                quickdeliver: { enable: false },
                bosTemplateId: 1000002317,
                youshu: { enable: false },
                source: 1,
                channelsource: 5,
                refer: "hd-lego-index",
                mpScene: 1005,
            },
            queryParameter: null,
            i18n: { language: "zh", timezone: "8" },
            pid: "",
            storeId: "",
            _transformBasicInfo: true,
            _requrl: "/orchestration/mobile/activity/draw/play",
            templateId: DRAW_ACTIVITY.templateId,
            templateKey: DRAW_ACTIVITY.templateKey,
            activityId: DRAW_ACTIVITY.activityId,
            bussinessType: 1,
            channel: 1,
            channelType: 1,
            source: 1,
            _version: "2.5.4",
            activityIdentity: DRAW_ACTIVITY.activityIdentity,
            openId: this.session.openid || this.session.openId || "",
            wid: this.session.wid || "",
            appId: MINI_APP_ID,
            playSourceCode: DRAW_ACTIVITY.playSourceCode,
            vid: DRAW_ACTIVITY.vid,
            vidType: DRAW_ACTIVITY.vidType,
            bosId: DRAW_ACTIVITY.bosId,
            productId: DRAW_ACTIVITY.productId,
            productInstanceId: DRAW_ACTIVITY.productInstanceId,
            productVersionId: DRAW_ACTIVITY.productVersionId,
            merchantId: DRAW_ACTIVITY.merchantId,
            tcode: "weimob",
            cid: DRAW_ACTIVITY.cid,
            vidTypes: [2],
            openid: this.session.openid || this.session.openId || "",
            ...extra,
        };
    }

    buildActivityInfoBody() {
        return {
            ...this.buildDrawBody({
                _requrl: "/orchestration/mobile/activity/info",
                templateId: "",
                "$level": 1,
            }),
        };
    }

    buildAgeBody() {
        return {
            appid: MINI_APP_ID,
            basicInfo: {
                vid: DRAW_ACTIVITY.vid,
                vidType: DRAW_ACTIVITY.vidType,
                bosId: DRAW_ACTIVITY.bosId,
                productId: DRAW_ACTIVITY.productId,
                productInstanceId: DRAW_ACTIVITY.productInstanceId,
                productVersionId: DRAW_ACTIVITY.productVersionId,
                merchantId: DRAW_ACTIVITY.merchantId,
                tcode: "weimob",
                cid: DRAW_ACTIVITY.cid,
            },
            extendInfo: {
                wxTemplateId: 8265,
                childTemplateIds: [
                    { customId: 90004, version: "crm@0.1.101" },
                    { customId: 90002, version: "ec@90.0" },
                    { customId: 90006, version: "hudong@0.0.255" },
                    { customId: 90008, version: "cms@0.0.537" },
                    { customId: 90070, version: "1.0.43" },
                ],
                analysis: [],
                quickdeliver: { enable: false },
                bosTemplateId: 1000002317,
                youshu: { enable: false },
                source: 1,
                channelsource: 5,
                refer: "hd-lego-index",
                mpScene: 1005,
            },
            queryParameter: null,
            i18n: { language: "zh", timezone: "8" },
            pid: "",
            storeId: "",
            targetBasicInfo: {
                productInstanceId: 8689224273,
                productId: 146,
                vid: 6015869513273,
            },
            integrated: true,
            birthday: DRAW_BIRTHDAY,
        };
    }

    async drawPlay() {
        const res = await axios.post(`${API_BASE}/orchestration/mobile/activity/draw/play`, this.buildDrawBody(), {
            headers: this.buildDrawHeaders({ bizId: DRAW_ACTIVITY.productId }),
            timeout: 20000,
            validateStatus: () => true,
        });
        if (res.status !== 200) throw new Error(`抽奖HTTP ${res.status}`);
        return res.data || {};
    }

    async activityInfo() {
        const res = await axios.post(`${API_BASE}/orchestration/mobile/activity/info`, this.buildActivityInfoBody(), {
            headers: this.buildDrawHeaders({
                bizId: DRAW_ACTIVITY.productId,
                componentIs: "hd_lego/RAW/components/design-page/design-page",
            }),
            timeout: 20000,
            validateStatus: () => true,
        });
        if (res.status !== 200) throw new Error(`活动信息HTTP ${res.status}`);
        return res.data || {};
    }

    async analysisAge() {
        const res = await axios.post(`${API_BASE}/user/info/web/guardian/info/analysisAge`, this.buildAgeBody(), {
            headers: this.buildDrawHeaders({
                reqFrom: "onecrm_extension_package",
                componentIs: "onecrm_extension_package/RAW/components/onecrmPublishRegister/index",
                pageRoute: "hd_lego/index",
                bizId: 146,
            }),
            timeout: 20000,
            validateStatus: () => true,
        });
        if (res.status !== 200) throw new Error(`年龄分析HTTP ${res.status}`);
        return res.data || {};
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
            const loginBody = {
                appid: MINI_APP_ID,
                basicInfo: { ...FORM_BASIC_INFO },
                env: "production",
                extendInfo: { ...EXTEND_INFO },
                is_pre_fetch_open: true,
                parentVid: 0,
                pid: "",
                storeId: "",
                code,
                queryAuthConfig: true,
            };
            delete loginBody.basicInfo.productInstanceId;

            const res = await axios.post(`${API_HOST}/fe/mapi/user/loginX`, loginBody, {
                headers: {
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT,
                    "Referer": `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
                    "weimob-bosId": FORM_BASIC_INFO.bosId,
                    "weimob-cid": FORM_BASIC_INFO.cid,
                },
                timeout: 20000,
                validateStatus: () => true,
            });
            if (res.status !== 200 || Number(res.data?.errcode) !== 0) {
                throw new Error(res.data?.errmsg || res.data?.errormsg || `HTTP ${res.status}`);
            }
            this.session = res.data.data || {};
            this.saveCachedToken();
            $.log(`账号[${this.index}] 登录成功: wid ${this.session.wid || ""}`);
        } catch (e) {
            $.log(`账号[${this.index}] 登录失败: ${e.message || e}`);
        }
    }

    async checkToken() {
        try {
            await this.getSignMainInfo(true);
            return true;
        } catch (e) {
            return false;
        }
    }

    customInfo(extra = {}) {
        return {
            ...ONECRM_BASIC_INFO,
            source: 0,
            wid: this.session.wid,
            ...extra,
        };
    }

    async getSignMainInfo(silent = false) {
        const data = await this.request("/onecrm/mactivity/sign/misc/sign/activity/c/signMainInfo", {
            customInfo: this.customInfo(),
        });
        if (!silent) {
            $.log(`账号[${this.index}] 签到状态: ${data?.hasSign ? "今日已签" : "今日未签"} ${rewardText(data?.signForwardMsg)}`);
        }
        return data || {};
    }

    async doSign() {
        try {
            const info = await this.getSignMainInfo();
            if (info.hasSign) {
                $.log(`账号[${this.index}] 今日已签到`);
                return;
            }

            const data = await this.request("/onecrm/mactivity/sign/misc/sign/activity/core/c/sign", {
                customInfo: this.customInfo(),
            });
            const rewards = [
                rewardText(data?.fixedReward),
                rewardText(data?.extraReward),
            ].filter(Boolean).join(" ");
            $.log(`账号[${this.index}] 签到成功${rewards ? `: ${rewards}` : ""}`);
        } catch (e) {
            const message = e.message || e;
            if (/已签|重复|今日已|60070013000332/.test(String(message))) {
                $.log(`账号[${this.index}] 今日已签到`);
                return;
            }
            $.log(`账号[${this.index}] 签到失败: ${message}`);
            if (isTokenError(message)) this.removeCachedToken();
        }
    }

    drawText(data) {
        if (String(data?.errcode) === "100200002") return "今日次数已用完";
        if (String(data?.errcode) === "100200003") return "次数已用完";
        if (String(data?.errcode) !== "0") return `抽奖失败：${data?.errmsg || data?.errcode || "未知"}`;
        const prizes = data?.data?.prizes || [];
        if (!Array.isArray(prizes) || !prizes.length) return "无奖品返回";
        return prizes
            .map((item) => String(item.id) === "-111" ? "未中奖" : `中奖：${item.name || item.prizeName || item.id}`)
            .join("；");
    }

    activityInfoText(res) {
        if (String(res?.errcode) !== "0") return `活动信息失败：${res?.errmsg || res?.errcode || "未知"}`;
        const data = res?.data || {};
        const name = data.name || "抽奖活动";
        const remain = data.remainCount ?? data.leftCount ?? data.chanceCount ?? data.drawCount ?? data.count ?? "";
        const joined = data.joinCount ?? data.usedCount ?? "";
        const parts = [name];
        if (remain !== "") parts.push(`剩余${remain}次`);
        if (joined !== "") parts.push(`已用${joined}次`);
        return parts.join("，");
    }

    async doDraw() {
        try {
            const info = await this.activityInfo();
            $.log(`账号[${this.index}] 活动信息: ${this.activityInfoText(info)}`);

            const data = await this.drawPlay();
            if (String(data?.errcode) === "1011003001" || /会员参与/.test(String(data?.errmsg || ""))) {
                $.log(`账号[${this.index}] 抽奖提示需会员，先走年龄分析`);
                const age = await this.analysisAge();
                $.log(`账号[${this.index}] 年龄分析结果: ${age?.errmsg || "success"}`);
                const retry = await this.drawPlay();
                $.log(`账号[${this.index}] 抽奖结果: ${this.drawText(retry)}`);
                return;
            }
            if (String(data?.errcode) === "100200002") {
                $.log(`账号[${this.index}] 抽奖结果: 今日次数已用完`);
                return;
            }
            $.log(`账号[${this.index}] 抽奖结果: ${this.drawText(data)}`);
        } catch (e) {
            const message = e.message || e;
            $.log(`账号[${this.index}] 抽奖失败: ${message}`);
        }
    }
}

!(async () => {
    await $.checkEnv(ckName);
    for (const openid of $.userList) {
        await new Task(openid).run();
    }
})()
    .catch((e) => $.log(e.message || e))
    .finally(() => $.done());