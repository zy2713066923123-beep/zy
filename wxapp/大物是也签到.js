require('./yyb.js'); // 自动同步 yyb_go 存活账号
/*
------------------------------------------
@Author: sm
@Date: 2026.07.29
@Description:  大物是也小程序签到
cron: 20 9,13 * * *
------------------------------------------

变量：
  WX_SERVER      yyb_go 协议服务地址（例如：http://127.0.0.1:8000）
  YYB_SERVER     (兼容别名) yyb_go 服务地址
  WX_ID         (可选白名单) 微信账号，多账号支持换行、& 分隔，留空自动拉取 yyb_go 所有存活账号

WX_ID 格式：
  wxid#备注   多个换行
  openid#备注（应用宝协议）
*/

const axios = require("axios");

// ============ 配置 ============
const APP_ID = "wx9d7354501dec9fe8";
const API_BASE = "https://api.dawushiye.com/api";
const USER_AGENT =
    "Mozilla/5.0 (Linux; Android 15; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.178 Mobile Safari/537.36 XWEB/1460249 MMWEBSDK/20260502 MicroMessenger/8.0.76.3141(0x28004C38) WeChat/arm64 Weixin MiniProgramEnv/android";
const REFERER = `https://servicewechat.com/${APP_ID}/23/page-frame.html`;

// ============ 环境 & 日志 ============
class Env {
    constructor(name) {
        this.name = name;
        this.userList = [];
        this.logs = [];
    }
    log(...args) {
        const msg = args.join(" ");
        this.logs.push(msg);
        console.log(msg);
    }
    async checkEnv(ckName) {
        const list = await global.resolveAccounts(ckName);
        this.userList = list;
        if (!this.userList.length) this.log("未找到环境变量 WX_ID，且 yyb_go 无存活账号");
    }
    async done() {
        try {
            const notify = require("../sendNotify");
            await notify.sendNotify(this.name, this.logs.join("\n"));
        } catch (e) {
            this.log("通知发送失败", e.message || e);
        }
    }
}

const $ = new Env("大物是也签到");

// ============ 微信 Code 获取 ============
async function getCode(wxid) {
    const actualWxid = String(wxid).split("#")[0].trim();
    return await getSingleCode(APP_ID, actualWxid);
}

// ============ 单账号任务 ============
class Task {
    constructor(wxid, index) {
        this.wxid = wxid;
        this.remark = String(wxid).split("#")[1] || `账号${index}`;
        this.index = index;
        this.token = "";
    }

    async request({ path, method = "post", body = null, auth = true }) {
        const headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": USER_AGENT,
            Referer: REFERER,
        };
        if (auth) headers["Authorization"] = this.token;

        const resp = await axios({
            url: API_BASE + path,
            method,
            headers,
            data: body,
            timeout: 20000,
        });

        const d = resp.data || {};
        if (d.resultCode === 0) return d.data;
        throw new Error(d.errorMessage || `resultCode=${d.resultCode}`);
    }

    async login() {
        const code = await getCode(this.wxid);
        if (!code) throw new Error("获取微信 code 失败");
        const data = await this.request({
            path: "/Wechat/Member/CheckMemberReg",
            method: "post",
            auth: false,
            body: {
                appId: APP_ID,
                jsCode: code,
                introId: null,
                introOpenId: null,
            },
        });
        if (!data || !data.token) throw new Error("登录未返回 token");
        this.token = data.token;
        this.needReg = !!data.needReg;
    }

    async getMemberDetail() {
        try {
            const data = await this.request({
                path: "/Wechat/Member/GetMemberDetail",
                method: "get",
                auth: true,
            });
            return data;
        } catch (e) {
            return null;
        }
    }

    async sign() {
        const data = await this.request({
            path: "/MarketingWechat/Sign/MiniUserSign",
            method: "post",
            auth: true,
            body: null,
        });
        return data;
    }

    async run() {
        $.log(`\n───── ${this.remark} ─────`);
        try {
            await this.login();
            if (this.needReg) {
                $.log(`⚠️ 该账号未注册会员，无法签到`);
                return;
            }
            const member = await this.getMemberDetail();
            if (member) {
                $.log(`🔑 登录成功 | 昵称: ${member.nickName || member.name || "未知"}`);
            } else {
                $.log(`🔑 登录成功`);
            }

            const result = await this.sign();
            const integral = result?.integral ?? 0;
            const rewardDay = result?.rewardDay ?? 0;
            const couponCnt = (result?.couponList || []).length;
            let msg = `✅ 签到成功 | 积分 +${integral}`;
            if (rewardDay) msg += ` | 连签 ${rewardDay} 天`;
            if (couponCnt) msg += ` | 优惠券 x${couponCnt}`;
            $.log(msg);
        } catch (e) {
            const em = e.message || String(e);
            if (/已签到|重复|already/i.test(em)) {
                $.log(`⚠️ 今日已签到`);
            } else {
                $.log(`❌ 失败: ${em}`);
            }
        }
    }
}

// ============ 主流程 ============
!(async () => {
    $.log(`## 大物是也签到开始 ${new Date().toLocaleString()}`);
    await $.checkEnv("WX_ID");
    $.log(`📋 账号总数：${$.userList.length}`);
    let idx = 1;
    for (const wxid of $.userList) {
        await new Task(wxid, idx++).run();
    }
})()
    .catch((e) => $.log(e.message || e))
    .finally(() => $.done());