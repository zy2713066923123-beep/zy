require('./yyb.js'); // 自动同步 yyb_go 存活账号
/*
------------------------------------------
@Author: sm
@Date: 2026.09.02
@Description: 友羊玩
cron: 20 09,21 * * *
------------------------------------------

变量：
  WX_SERVER      yyb_go 协议服务地址（例如：http://127.0.0.1:18273）
  YYB_SERVER     (兼容别名) yyb_go 服务地址
  WX_ID         (可选白名单) 微信账号，多账号支持换行、& 分隔，留空自动拉取 yyb_go 所有存活账号

WX_ID 格式：
  wxid#备注   多个换行
  openid#备注（应用宝协议）

说明：
  基于解包源码 wx5ea3041cb47942b9_unpacked 分析：
  - 登录接口：POST /login?code=<wx.login code>&shareUserId=<可选>
  - 浇水签到接口：POST /pointsUserDetail/signIn?token=<token>
  - 返回 { point, totalPoints }，point 为本次获得积分，totalPoints 为总积分
*/

const axios = require("axios");

// ============ 配置 ============
const APP_ID = "wx5ea3041cb47942b9";
const API_BASE = "https://www.gblvyou.com/api";
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

const $ = new Env("友盈浇水签到");

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

    // 通用请求：token 作为 query 参数（与小程序 request.js 一致）
    async request({ path, method = "post", body = null, token = this.token }) {
        const headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": USER_AGENT,
            Referer: REFERER,
        };
        const sep = path.includes("?") ? "&" : "?";
        const url = API_BASE + path + (token ? `${sep}token=${encodeURIComponent(token)}` : "");

        const resp = await axios({
            url,
            method,
            headers,
            data: body,
            timeout: 20000,
        });

        const d = resp.data || {};
        if (d.code === 200) return d.data;
        throw new Error(d.message || `code=${d.code}`);
    }

    async login() {
        // token 缓存：有效期内复用，避免每次运行都重新取 code（规避微信限流）
        const cached = getCachedToken('youying', this.wxid, { maxAgeMs: 6 * 3600 * 1000 });
        if (cached && typeof cached.token === 'string' && cached.token) {
            this.token = cached.token;
            this.fromCache = true;
            $.log(`✅ ${this.remark} 命中token缓存，跳过取code`);
            return;
        }
        await this.loginByCode();
    }

    async loginByCode() {
        this.fromCache = false;
        const code = await getCode(this.wxid);
        if (!code) throw new Error("获取微信 code 失败");
        // 登录接口：POST /login?code=<code>&shareUserId=<shareUserId>
        const data = await this.request({
            path: `/login?code=${encodeURIComponent(code)}&shareUserId=`,
            method: "post",
            token: "",
        });
        if (!data || !data.token) throw new Error("登录未返回 token");
        this.token = data.token;
        saveCachedToken('youying', this.wxid, { token: this.token });
    }

    // 探测 token 是否仍被服务端接受
    async checkToken() {
        try {
            await this.request({
                path: "/pointsUserDetail/total",
                method: "post",
            });
            return true;
        } catch (e) {
            const em = String(e.message || e);
            if (/token|登录|授权|401|过期|失效|未登录/i.test(em)) return false;
            return true;
        }
    }

    // 浇水签到
    async sign() {
        const data = await this.request({
            path: "/pointsUserDetail/signIn",
            method: "post",
        });
        return data;
    }

    async run() {
        $.log(`\n───── ${this.remark} ─────`);
        try {
            await this.login();
            // 缓存 token 可能已在服务端失效：先探测，失效则清缓存重新取 code 登录
            if (this.fromCache && !(await this.checkToken())) {
                $.log(`⚠️ 缓存token已失效，重新登录`);
                removeCachedToken('youying', this.wxid);
                await this.loginByCode();
            }

            const result = await this.sign();
            const point = result?.point ?? 0;
            const totalPoints = result?.totalPoints ?? 0;
            let msg = `✅ 浇水签到成功 | 本次积分 +${point}`;
            if (totalPoints) msg += ` | 总积分 ${totalPoints}`;
            $.log(msg);
        } catch (e) {
            const em = e.message || String(e);
            if (/已签到|重复|已达上限|already/i.test(em)) {
                $.log(`⚠️ 今日已签到`);
            } else {
                if (/token|登录|授权|401/i.test(em)) removeCachedToken('youying', this.wxid);
                $.log(`❌ 失败: ${em}`);
            }
        }
    }
}

// ============ 主流程 ============
!(async () => {
    $.log(`## 友盈浇水签到开始 ${new Date().toLocaleString()}`);
    await $.checkEnv("WX_ID");
    $.log(`📋 账号总数：${$.userList.length}`);
    let idx = 1;
    for (const wxid of $.userList) {
        await new Task(wxid, idx++).run();
    }
})()
    .catch((e) => $.log(e.message || e))
    .finally(() => $.done());