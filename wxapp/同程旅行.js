require('./yyb.js'); // 自动同步 yyb_go 存活账号
// name: 同程旅行
// cron: 56 08,20 * * *
const axios = require("axios");

// ====== 标准Env模式 ======
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

// ====== 引入 yyb.js 模块（支持双协议：牛子+应用宝）======
const getWxCode = (wxid, appid) => getSingleCode(appid, String(wxid).split('#')[0].trim());

const $ = new Env("同程旅行");

// 里程签到：同程旅行小程序
const APPID = "wx336dcaf6a1ecf632";

// 签到领现金：H5/公众号活动页（getopenid.html 使用的 AppID，非小程序 AppID）
const CASH_APPID = "wx3827070276e49e30";
const CASH_CACHE = "tongcheng_signin_cash";
const ACT_ID = "c60c3ca52ec79260203998db4578c913";
const ACTIVITY_URL =
    "https://wx.17u.cn/cvgzt/20260819dailyCheckIn/index/?fromShareId=99c4cc5db188d952e708ba3826cac37b5c3ff63ec81d86e24bf97fe6d64e2773b4a72f4f6e775a3f7233f9ea47a164f43a1abe68fb1e92481b932cd8e3e3f52ef733cec7608064dcfd7195843bf18634#";
const SHARE_ID =
    "99c4cc5db188d952e708ba3826cac37b5c3ff63ec81d86e24bf97fe6d64e2773f62635fd593ce3c2577d6bd001f10403da69f502106a89dcfd57ff30f9b6898830082b7c3c8e0943065d93eedd03b63e";
const CASH_API = "https://cvg.17usoft.com/activity/signInCash";

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

// ====== 签到领现金：H5 登录态换取 ======
// 302 Location 中的 code 即业务 idenId；同时兼容 Set-Cookie 中的 openid/token
function extractIdenFromRedirect(loc, setCookies) {
    let idenId = "";
    let token = "";

    if (loc) {
        try {
            const u = new URL(loc, "https://wx.17u.cn");
            idenId = u.searchParams.get("code") || "";
            token = u.searchParams.get("token") || "";
        } catch (_) {}
    }

    const cookies = Array.isArray(setCookies) ? setCookies : setCookies ? [setCookies] : [];
    for (const c of cookies) {
        const str = String(c || "");
        if (!idenId) {
            const m =
                str.match(/(?:^|;\s*|,?\s*)(?:WxUser|cookieOpenSource|CooperateWxUser)=[^;]*openid=([^&;]+)/i) ||
                str.match(/openid=([^&;]+)/i);
            if (m) {
                try {
                    idenId = decodeURIComponent(m[1]);
                } catch (_) {
                    idenId = m[1];
                }
            }
        }
        if (!token) {
            const m = str.match(/(?:^|[;&])token=([^&;]+)/i);
            if (m) {
                try {
                    token = decodeURIComponent(m[1]);
                } catch (_) {
                    token = m[1];
                }
            }
        }
    }

    return { idenId, token };
}

// 用公众号 code 换取 H5 业务登录态（idenId）
async function exchangeCode(code) {
    const url =
        "https://wx.17u.cn/flight/getopenid.html?url=" +
        encodeURIComponent(ACTIVITY_URL) +
        `&code=${encodeURIComponent(code)}&state=123`;

    const handle = (res) => {
        const loc = res.headers.location || res.headers.Location || "";
        const setCookie = res.headers["set-cookie"] || res.headers["Set-Cookie"] || [];
        const body = typeof res.data === "string" ? res.data : "";
        if (!loc && body) {
            const m = body.match(/href=["']([^"']+)["']/i);
            if (m) return extractIdenFromRedirect(m[1], setCookie);
        }
        return extractIdenFromRedirect(loc, setCookie);
    };

    try {
        const res = await axios({
            method: "GET",
            url,
            timeout: 20000,
            maxRedirects: 0,
            validateStatus: (status) => status >= 200 && status < 400,
            headers: {
                "User-Agent":
                    "Mozilla/5.0 (Linux; Android 16; PJZ110) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/121.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.71",
                Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        });
        return handle(res);
    } catch (e) {
        if (e.response) return handle(e.response);
        throw e;
    }
}

function isNotLoggedInResponse(res) {
    if (!res) return false;
    if (res.status === 401 || res.status === 403) return true;

    const data = res.data;
    if (!data) return false;

    const code = data.code ?? data.errCode ?? data.errorCode ?? data.RspCode;
    if ([401, 403, 1001, 1002, 1003, 40001, 40003, 40101].includes(Number(code))) return true;

    const msg = String(data.message || data.msg || data.errMsg || data.Message || "").toLowerCase();
    return [
        "未登录",
        "请登录",
        "登录失效",
        "token失效",
        "token expired",
        "unauthorized",
        "not login",
        "not_logged_in",
        "invalid token",
        "token invalid",
    ].some((keyword) => msg.includes(keyword.toLowerCase()));
}

class Tongcheng {
    constructor(wxid) {
        this.wxid = wxid;
        this.index = $.userIdx++;
        this.openid = wxid;
        this.loginInfo = {};
        this.cashIdenId = "";
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
        // token 缓存：有效期内复用，避免每次运行都重新取 code（规避微信限流）
        const cached = getCachedToken('tongcheng', this.wxid, { maxAgeMs: 6 * 3600 * 1000 });
        if (cached && cached.loginInfo) {
            this.loginInfo = cached.loginInfo;
            $.log(`命中登录缓存，跳过取code`);
            return;
        }
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
        saveCachedToken('tongcheng', this.wxid, { loginInfo: this.loginInfo });
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

    // ================= 签到领现金（H5 活动）=================
    cashHeaders(extra = {}) {
        return {
            "content-type": "application/json",
            "User-Agent": `${USER_AGENT} miniProgram/${APPID}`,
            Origin: "https://wx.17u.cn",
            Referer: "https://wx.17u.cn/",
            Accept: "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            ...extra,
        };
    }

    cashBaseData() {
        return {
            actId: ACT_ID,
            unionId: this.loginInfo.unionId || "",
            idenId: this.cashIdenId || "",
        };
    }

    // 登录态缓存复用，失效时才重新取 code（规避微信限流）
    async cashLogin(force = false) {
        if (!force) {
            const cached = getCachedToken(CASH_CACHE, this.wxid, { maxAgeMs: 6 * 3600 * 1000 });
            if (cached && cached.idenId) {
                this.cashIdenId = cached.idenId;
                return;
            }
        }
        const code = await getWxCode(this.wxid, CASH_APPID);
        if (!code) throw new Error("签到领现金：获取微信 code 失败");
        const { idenId, token } = await exchangeCode(code);
        if (!idenId || idenId === "0") throw new Error("签到领现金：未获取到 idenId，登录失败");
        this.cashIdenId = idenId;
        saveCachedToken(CASH_CACHE, this.wxid, { idenId, token });
        $.log(`账号[${this.index}] 签到领现金登录成功`);
    }

    // 统一请求：登录态失效时自动重新登录并重试一次
    async cashRequest(options) {
        let retried = false;
        while (true) {
            const req = { ...options };
            if (req.data && req.data.actId) req.data = { ...req.data, ...this.cashBaseData() };
            let res;
            try {
                res = await request({
                    ...req,
                    headers: { ...(req.headers || {}), ...this.cashHeaders() },
                });
            } catch (e) {
                // 网络异常不中断整体流程，交由上层按失败处理
                return { status: 0, headers: {}, data: null };
            }
            if (!retried && isNotLoggedInResponse(res)) {
                retried = true;
                removeCachedToken(CASH_CACHE, this.wxid);
                await this.cashLogin(true);
                continue;
            }
            return res;
        }
    }

    async cashIndexInfo() {
        const res = await this.cashRequest({
            method: "POST",
            url: `${CASH_API}/getIndexInfo`,
            data: this.cashBaseData(),
        });
        const info = res.data?.code === 1000 ? res.data.data : null;
        if (info) {
            $.log(
                `账号[${this.index}] 积分余额=${info.pointsBalance || 0} 已签到=${info.signedDays || 0}/${info.requiredSignedDays || 0} 状态=${info.actionStatus || "未知"}`
            );
        } else {
            $.log(`账号[${this.index}] 获取签到信息失败: ${res.data?.message || short(res.data)}`);
        }
        return info;
    }

    async cashTaskInfo() {
        const res = await this.cashRequest({
            method: "POST",
            url: `${CASH_API}/getTaskInfo`,
            data: this.cashBaseData(),
        });
        if (res.data?.code === 1000) return res.data.data || null;
        $.log(`账号[${this.index}] 获取任务信息失败: ${res.data?.message || short(res.data)}`);
        return null;
    }

    async cashSignIn() {
        const res = await this.cashRequest({
            method: "POST",
            url: `${CASH_API}/signIn`,
            data: this.cashBaseData(),
        });
        if (res.data?.code === 1000) {
            $.log(`账号[${this.index}] 签到成功 +${res.data.data?.rewardPoints || 0}分，积分余额=${res.data.data?.pointsBalance || 0}`);
            return true;
        }
        $.log(`账号[${this.index}] 签到失败: ${res.data?.message || short(res.data)}`);
        return false;
    }

    async cashCompleteTask(taskType) {
        const res = await this.cashRequest({
            method: "POST",
            url: `${CASH_API}/completeTask`,
            data: { ...this.cashBaseData(), taskType },
        });
        if (res.data?.code !== 1000) return null;
        const d = res.data.data;
        if (typeof d === "string") return d;
        return d?.taskRecordId || d?.recordId || "";
    }

    async cashClaimReward(taskRecordId) {
        const res = await this.cashRequest({
            method: "POST",
            url: `${CASH_API}/claimTaskReward`,
            data: { ...this.cashBaseData(), taskRecordId },
        });
        if (res.data?.code === 1000) {
            $.log(`账号[${this.index}] 领取奖励成功 +${res.data.data?.rewardPoints || 0}分，积分余额=${res.data.data?.pointsBalance || 0}`);
            return true;
        }
        $.log(`账号[${this.index}] 领取奖励结果: ${res.data?.message || short(res.data)}`);
        return false;
    }

    // 分享上报
    async cashHelp() {
        const res = await this.cashRequest({
            method: "POST",
            url: `${CASH_API}/help`,
            data: { ...this.cashBaseData(), shareId: SHARE_ID },
        });
        $.log(
            `账号[${this.index}] 上报事件${res.data?.code === 1000 ? "成功" : "结果: " + (res.data?.message || short(res.data))}`
        );
    }

    async cashTasks() {
        const taskData = await this.cashTaskInfo();
        if (!taskData) return;

        const taskList = taskData.taskList || [];
        const pendingRewards = taskData.pendingRewardList || [];
        $.log(`账号[${this.index}] 共${taskList.length}个任务，待领取奖励${pendingRewards.length}个`);

        for (const task of taskList) {
            const statusText = task.completed ? "已完成" : task.couldComplete ? "可完成" : "未完成";
            $.log(`账号[${this.index}] [${task.title}] ${statusText} (${task.progress}/${task.targetCount}) +${task.rewardPoints}分`);
        }

        for (const reward of pendingRewards) {
            if (!reward.taskRecordId) continue;
            await this.cashClaimReward(reward.taskRecordId);
            await sleep(2000);
        }

        for (const task of taskList) {
            if (task.completed || !task.couldComplete) continue;
            if (task.completionMode === "BROWSE") {
                const taskRecordId = await this.cashCompleteTask(task.type);
                if (taskRecordId) {
                    await sleep(2000);
                    await this.cashClaimReward(taskRecordId);
                }
                await sleep(3000);
            }
            if (task.completionMode === "SIGN" && task.progress >= task.targetCount) {
                const taskRecordId = await this.cashCompleteTask(task.type);
                if (taskRecordId) {
                    await sleep(2000);
                    await this.cashClaimReward(taskRecordId);
                }
                await sleep(2000);
            }
        }
    }

    async cashRun() {
        await this.cashLogin();
        const info = await this.cashIndexInfo();
        if (info && info.actionStatus === "SIGN") {
            await this.cashSignIn();
        } else if (info) {
            $.log(`账号[${this.index}] 今日已签到，跳过`);
        }
        await sleep(2000);
        await this.cashTasks();
        await sleep(2000);
        await this.cashHelp();
        await sleep(2000);
        const finalInfo = await this.cashIndexInfo();
        if (finalInfo) $.log(`账号[${this.index}] 最终积分: ${finalInfo.pointsBalance || 0}`);
    }
}

!(async () => {
    await $.checkEnv("WX_ID");
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
        // 签到领现金（H5 活动）：依赖小程序登录拿到的 unionId，失败不影响里程签到
        if (runner.loginInfo && runner.loginInfo.sectoken) {
            try {
                await sleep(2000);
                await runner.cashRun();
            } catch (e) {
                $.log(`签到领现金执行失败：${e.message || e}`);
            }
        }
        if (i < $.userList.length - 1) await sleep(800);
    }
})()
    .catch((e) => $.log(`脚本异常：${e.stack || e.message || e}`))
    .finally(() => $.done());