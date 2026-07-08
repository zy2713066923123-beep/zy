// name: 同程旅行里程
// cron: 21 8 * * *

const axios = require("axios");
// ====================== WX_ID 账号（环境变量 WX_ID = identifier#alias，多行换行或&分隔） ======================
const ACCOUNTS = (process.env.WX_ID || "")
    .split(/\r?\n|&/)
    .map(s => s.trim())
    .filter(Boolean)
    .map(s => {
        const [identifier, alias] = s.split("#").map(item => item.trim());
        return { identifier: identifier || s, alias: alias || "" };
    });
if (!ACCOUNTS.length) {
    console.error("未配置环境变量 WX_ID，请设置后重试（格式：identifier#alias，多行换行或&分隔）");
    process.exit(1);
}

const WECHAT_SERVER = (process.env.WECHAT_SERVER || process.env.YYB_SERVER || "http://192.168.6.222:8011").replace(/\/+$/, "");

const APPID = "wx336dcaf6a1ecf632";

async function getWxCode(identifier) {
    if (!identifier) return null;
    const url = `${WECHAT_SERVER}/wxapp/getCode`;
    try {
        const { data } = await axios.post(url, { ref: identifier, app_id: APPID }, { timeout: 20000, proxy: false });
        const code = data && data.data && data.data.result && data.data.result.code;
        if (!data || data.code !== 0 || !code) {
            console.log(WECHAT_SERVER + " 获取code失败: " + JSON.stringify(data));
            return null;
        }
        console.log(WECHAT_SERVER + " 获取code成功");
        return code;
    } catch (e) {
        console.log(WECHAT_SERVER + " 获取code异常: " + e.message);
        return null;
    }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
let userIdx = 1;

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
    constructor({ identifier, alias }, index) {
        this.identifier = identifier;
        this.alias = alias;
        this.index = index;
        this.openid = identifier;
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
        const code = await getWxCode(this.identifier);
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
        return `会员=${short(content.memberBanner || content.memberRights || content, 100)} 里程=${remain ?? short(mileage.data, 100)}`;
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
        if (info.todaySigned || cal.todaySigned) return `今日已签到，连续=${info.periodContinuedSignDays ?? cal.periodContinuedSignDays ?? "未知"}天`;
        const sign = await request({
            method: "POST",
            url: "https://wx.17u.cn/wxmpsign/sign/saveSignInfo",
            headers: this.headers({ "content-type": "application/json" }),
            data: {},
        });
        return `签到接口返回: ${short(sign.data)}`;
    }
}

async function runAccount(account, index) {
    const { identifier, alias } = account;
    console.log(`\n========== ${APP.name} 账号[${index}]${alias ? `[${alias}]` : ""} ${identifier} ==========`);
    const runner = new Tongcheng(account, index);
    try {
        console.log(`登录：${await runner.login()}`);
        console.log(`查询：${await runner.query()}`);
        console.log(`签到：${await runner.sign()}`);
    } catch (e) {
        console.log(`执行失败：${e.message || e}`);
    }
}

(async () => {
    if (!ACCOUNTS.length) {
        console.log(`未配置 WX_ID`);
        return;
    }
    console.log(`共找到${ACCOUNTS.length}个账号`);
    for (let i = 0; i < ACCOUNTS.length; i++) {
        await runAccount(ACCOUNTS[i], i + 1);
        await sleep(800);
    }
})().catch((e) => {
    console.log(`脚本异常：${e.stack || e.message || e}`);
});
