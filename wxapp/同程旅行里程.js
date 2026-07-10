// name: 同程旅行里程
// cron: 11 10,19 * * *

const axios = require("axios");

// ====== 标准Env模式 ======
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

// ====== 引入 getCode.js 模块（支持双协议：牛子+应用宝）======
const { getSingleCode } = require('./getCode.js');
const getWxCode = (wxid, appid) => getSingleCode(appid, String(wxid).split('#')[0].trim());

const $ = new Env("同程旅行里程签到");
$.checkEnv("WX_ID");

const APPID = "wx336dcaf6a1ecf632";

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

const APP = { name: "同程旅行里程签到", appid: APPID };

const USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

function short(value, max = 220) {
    if (value === undefined || value === null) return "";
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return text.length > max ? `${text.slice(0, max)}...` : text;
}

function formatDate(date = new Date()) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function getFiveDays() {
    const days = [];
    for (let i = -2; i <= 2; i++) {
        const d = new Date();
        d.setDate(d.getDate() + i);
        days.push(formatDate(d));
    }
    return days;
}

async function request(options) {
    const res = await axios.request({
        timeout: 20000,
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

class Tongcheng {
    constructor(wxid) {
        this.wxid = wxid;
        this.index = $.userIdx++;
        this.openid = wxid;
        this.loginInfo = {};
    }

    headers(extra = {}) {
        const sectoken = this.loginInfo.sectoken || "";
        return {
            apmat: `${this.loginInfo.openId || this.openid}|${new Date().toISOString().slice(0, 16).replace(/[-T:]/g, "")}|${Math.floor(Math.random() * 1000000)}`,
            TCSecTk: sectoken,
            TCxcxVersion: "10.8.7",
            platform: "WX_MP",
            osType: "2",
            secToken: sectoken,
            "TC-MALL-PLATFORM-CODE": "WX_MP",
            "TC-MALL-USER-TOKEN": sectoken,
            ...extra,
        };
    }

    async login() {
        const code = await getWxCode(this.wxid, APPID);
        const res = await request({
            method: "POST",
            url: "https://wx.17u.cn/wechatappapi/wxUser/login",
            headers: { "content-type": "application/json" },
            data: { code, scene: 1001 },
        });
        const content = res.data?.content || res.data?.data || {};
        if (res.status !== 200 || !content.openId) throw new Error(`登录失败 HTTP ${res.status}: ${short(res.data)}`);
        this.loginInfo = {
            openId: content.openId,
            encryOpenId: content.encryOpenId,
            aesOpenId: content.aesOpenId,
            unionId: content.unionId,
            aesUnionId: content.aesUnionId,
            memberId: content.memberId,
            sectoken: content.sectoken,
        };
        $.log(`账号[${this.index}] 登录成功: openId=${content.openId} memberId=${content.memberId || ""}`);
        return `openId=${content.openId} memberId=${content.memberId || ""}`;
    }

    async query() {
        const member = await request({
            method: "GET",
            url: "https://wx.17u.cn/wechatmypubapi/myInfo/memberInfo",
            headers: this.headers(),
        });
        const mileage = await request({
            method: "POST",
            url: "https://tcmobileapi.17usoft.com/mallgatewayapi/userApi/mileages/remain",
            headers: this.headers({
                "content-type": "application/json",
                "TC-MALL-DEPT-CODE": "iH3PGf9ZucSMMEYi4keylA==",
                "TC-MALL-CLIENT": "API_CLIENT",
                "TC-MALL-OS-TYPE": "Android",
            }),
            data: { osType: 2 },
        });
        const remain = mileage.data?.data?.remainBalance ?? mileage.data?.data?.balance ?? mileage.data?.remainBalance;
        const content = member.data?.content || member.data?.data?.content || {};
        const result = `会员=${short(content.memberBanner || content.memberRights || content, 100)} 里程=${remain ?? short(mileage.data, 100)}`;
        $.log(`账号[${this.index}] ${result}`);
        return result;
    }

    async sign() {
        const days = getFiveDays();
        const calendar = await request({
            method: "POST",
            url: "https://wx.17u.cn/wxmpsign/sign/signCalendar",
            headers: this.headers({ "content-type": "application/json" }),
            data: { beginDate: days[0], endDate: days[4] },
        });
        const signInfo = await request({
            method: "POST",
            url: "https://wx.17u.cn/wxmpsign/sign/getSignInfo",
            headers: this.headers({ "content-type": "application/json" }),
            data: {},
        });
        const info = signInfo.data?.data || {};
        const cal = calendar.data?.data || {};
        if (info.todaySigned || cal.todaySigned) {
            const result = `今日已签到，连续=${info.periodContinuedSignDays ?? cal.periodContinuedSignDays ?? "未知"}天`;
            $.log(`账号[${this.index} ${result}`);
            return result;
        }
        const sign = await request({
            method: "POST",
            url: "https://wx.17u.cn/wxmpsign/sign/saveSignInfo",
            headers: this.headers({ "content-type": "application/json" }),
            data: {},
        });
        const result = `签到接口返回: ${short(sign.data)}`;
        $.log(`账号[${this.index}] ${result}`);
        return result;
    }
}

!(async () => {
    if (!$.userList.length) {
        $.log(`未配置 WX_ID`);
        return;
    }
    $.log(`共找到${$.userList.length}个账号`);
    for (let i = 0; i < $.userList.length; i++) {
        const wxid = $.userList[i];
        $.log(`\n========== ${APP.name} 账号[${i + 1}] ${wxid} ==========`);
        const runner = new Tongcheng(wxid);
        try {
            await runner.login();
            await runner.query();
            await runner.sign();
        } catch (e) {
            $.log(`执行失败：${e.message || e}`);
        }
        if (i < $.userList.length - 1) await sleep(800);
    }
})()
    .catch((e) => $.log(`脚本异常：${e.stack || e.message || e}`))
    .finally(() => $.done());
