require('./yyb.js'); // 自动同步 yyb_go 存活账号
// name: 拾绿旧衣回收
// cron: 22 7 * * *
/*
------------------------------------------
@Description: 拾绿旧衣回收 - 微信小程序静默登录 + 每日签到
------------------------------------------
变量名：slhsck
变量值：yyb_go 存活账号的 openid/账号标识，多账号用 & 或换行分隔（可加 #备注）

变量：
  WX_SERVER      yyb_go 协议服务地址（例如：http://127.0.0.1:18273）
  WX_ID          (可选白名单) 微信账号 openid/wxid，多账号用 & 或换行分隔；留空自动拉取 yyb_go 所有存活账号
------------------------------------------
契约（appid wxe417414e03e537aa，host lm.api.sujh.net，appid头 shilv）：
（以下路径与参数均来自 Reqable 实抓，2026-09-09 验证通过：签到前 signIn=0/score=30，
  签到后 signIn=1/score=40，单次 +10 积分）

登录  GET  /app/login/wechatLogin?encryptedData=&iv=&code=
        -> {code:200, token:"eyJ...", userId}
用户  GET  /app/user/index?platform=1
        -> {code:200, data:{score, money, ...}}
积分  GET  /app/score/index?platform=1
        -> {code:200, data:{signIn:0|1, score}}   signIn=1 表示今日已签到
模板  GET  /app/msgTemplate/list?platform=1&type=6
        -> {code:200, rows:[{templateId}]}        签到提交需要携带
签到  POST /app/score/sign      body {tmplIds:[...], platform:1}
        -> {code:200, msg:"操作成功"}

token 用法：authorization: <裸JWT>（不带 bearer 前缀）；请求头须带 appid: shilv
------------------------------------------
*/

class WeChatServer {
    constructor(config) { this.config = config || {}; }
    async getCode(wxid) {
        try {
            const ref = String(wxid).split('#')[0].trim();
            const code = await getSingleCode(this.config.appid, ref);
            return { data: { status: true, code, data: { code } } };
        } catch (e) {
            return { data: { status: false, message: e.message || String(e) } };
        }
    }
}

class Env {
    constructor(name) { this.name = name; this.userList = []; this.userIdx = 1; this.userCount = 0; this.logs = []; const originalLog = console.log; console.log = (...args) => { this.logs.push(args.join(" ")); originalLog.apply(console, args); }; }
    log(...args) { console.log(...args); this.logs.push(args.join(" ")); }
    async wait(minMs, maxMs) { const ms = maxMs ? Math.floor(minMs + Math.random() * (maxMs - minMs)) : minMs; await new Promise(r => setTimeout(r, ms)); }
    async checkEnv(ckName) {
        const list = await global.resolveAccounts(ckName);
        this.userList = list;
        this.userCount = list.length;
        if (!this.userList.length) console.log('未找到环境变量 WX_ID，且 yyb_go 无存活账号');
    }
    async done() { try { const notify = require('../sendNotify'); await notify.sendNotify(this.name, this.logs.join('\n')); } catch (e) { console.log('通知发送失败', e); } }
}

const $ = new Env("拾绿旧衣回收");
const axios = require("axios");
const fs = require("fs");
const path = require("path");

const ckName = "slhsck";
const MINI_APP_ID = "wxe417414e03e537aa";
const BASE = "https://lm.api.sujh.net";
const TOKEN_CACHE_FILE = path.join(__dirname, "slhsck_token_cache.json");
const USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " +
    "Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI " +
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541c37) XWEB/25364";

// 订阅消息模板ID兜底值（/app/msgTemplate/list?type=6 拉取失败时使用，抓包实测值）
const DEFAULT_TMPL_IDS = [
    "KBO3hu2sg9uAf1jE5mw7sH9EMwULMKNfPhNG-qE2zec",
    "lrG7AIJCOfa8D1YZvmHgRnIAlVlHUjSYmcf4oCOYI-4",
    "wAoZ0p2GpZYRrguH1JB1xWyqdL1kgnGP-XDvoYxlLhc",
];

const wechat = new WeChatServer({ appid: MINI_APP_ID });

function readCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
    } catch (e) {
        return {};
    }
}

function writeCache(cache) {
    try {
        fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
    } catch (e) {
        $.log(`写入token缓存失败: ${e.message || e}`);
    }
}

function parseAccount(raw = "") {
    const [id, remark] = String(raw).split("#").map((s) => (s || "").trim());
    return { openid: id, remark: remark || "" };
}

function short(v, n = 200) {
    const t = typeof v === "string" ? v : JSON.stringify(v);
    return !t ? "" : t.length > n ? `${t.slice(0, n)}...` : t;
}

const isOk = (res) => res && Number(res.code) === 200;
const codeOf = (res) => Number(res?.code);
const msgOf = (res) => res?.message || res?.msg || short(res);
const isAlreadyDone = (t) => /已签|已经签|签到过|重复|已完成|already/i.test(String(t || ""));

class Task {
    constructor(raw) {
        this.index = $.userIdx++;
        this.account = parseAccount(raw);
        this.token = "";
    }

    log(text) {
        $.log(`账号[${this.index}]${this.account.remark ? `[${this.account.remark}]` : ""} ${text}`);
    }

    async request(apiPath, { method = "GET", body = null, params = null, withAuth = true } = {}) {
        const headers = {
            "Content-Type": "application/json",
            Accept: "*/*",
            "User-Agent": USER_AGENT,
            Referer: `https://servicewechat.com/${MINI_APP_ID}/10/page-frame.html`,
            appid: "shilv",
            "xweb_xhr": "1",
        };
        headers.authorization = withAuth ? this.token : "";
        const res = await axios.request({
            method,
            url: `${BASE}${apiPath}`,
            params,
            data: method === "GET" ? undefined : body || {},
            headers,
            timeout: 20000,
            validateStatus: () => true,
        });
        if (res.status !== 200) {
            if (res.data && typeof res.data === "object") return res.data;
            throw new Error(`${apiPath} HTTP ${res.status}: ${short(res.data)}`);
        }
        return res.data;
    }

    async getCode() {
        const { data } = await wechat.getCode(this.account.openid);
        if (data && data.status === false) {
            throw new Error(`wx_server 取code失败: ${data.message || short(data)}`);
        }
        const code = data?.data?.code || data?.code;
        if (!code || typeof code !== "string") throw new Error(`wx_server 未返回 code: ${short(data)}`);
        return code;
    }

    async getOperateData() {
        const ref = String(this.account.openid).split('#')[0].trim();
        return await getSingleOperateWxData(MINI_APP_ID, ref);
    }

    /** 登录：需要 code + encryptedData + iv（拾绿 wechatLogin 要求三个参数） */
    async login() {
        const ref = String(this.account.openid).split('#')[0].trim();
        // 1) wx.login code
        const code = await this.getCode();
        // 2) encryptedData + iv（先尝试 operateWxData，退化为手机号加密数据）
        let wxData = await this.getOperateData();
        let edata = wxData?.encryptedData || wxData?.encrypted_data || wxData?.data?.encryptedData || wxData?.Data?.encryptedData || "";
        let iv = wxData?.iv || wxData?.IV || wxData?.data?.iv || wxData?.Data?.iv || "";
        if (!edata || !iv) {
            const phone = await getSinglePhoneEncrypted(MINI_APP_ID, ref);
            if (phone) {
                edata = edata || phone.encryptedData || phone.encrypted_data || "";
                iv = iv || phone.iv || phone.IV || "";
            }
        }
        if (!edata || !iv) throw new Error(`未提取到 encryptedData/iv: ${short(wxData)}`);
        // 3) 调登录接口
        const res = await this.request("/app/login/wechatLogin", {
            params: { encryptedData: edata, iv, code },
        });
        if (!isOk(res)) throw new Error(`登录失败: ${msgOf(res)}`);
        const token = String(res.token || "");
        if (!token) throw new Error(`登录响应缺少 token: ${short(res)}`);
        this.token = token;
        const cache = readCache();
        cache[this.account.openid] = { token: this.token, updatedAt: new Date().toISOString() };
        writeCache(cache);
        this.log("登录成功");
    }

    async getUserInfo() {
        const res = await this.request("/app/user/index", { params: { platform: 1 } });
        if (isOk(res)) {
            const d = res.data || {};
            if (d.score !== undefined) this.log(`积分: ${d.score}`);
            if (d.money !== undefined) this.log(`余额: ${d.money}`);
            return;
        }
        // 非 200 视为 token 失效，交给上层触发重新登录
        throw new Error(`用户信息获取失败: ${msgOf(res)}`);
    }

    async ensureLogin() {
        const cached = readCache()[this.account.openid] || {};
        if (!this.token && cached.token) {
            this.token = cached.token;
            try {
                await this.getUserInfo();
                this.log("使用缓存token");
                return;
            } catch {
                this.log("缓存token失效，重新登录");
                this.token = "";
            }
        }
        if (!this.token) await this.login();
    }

    /** 积分首页：signIn=1 表示今日已签到 */
    async getScoreInfo() {
        const res = await this.request("/app/score/index", { params: { platform: 1 } });
        if (!isOk(res)) return null;
        const d = res.data || {};
        return { signIn: Number(d.signIn ?? -1), score: d.score };
    }

    /** 订阅消息模板ID，签到接口要求携带 tmplIds */
    async getTmplIds() {
        const res = await this.request("/app/msgTemplate/list", { params: { platform: 1, type: 6 } });
        const rows = res?.rows;
        if (Array.isArray(rows) && rows.length) {
            const ids = rows.map((r) => r.templateId).filter(Boolean);
            if (ids.length) return ids;
        }
        return DEFAULT_TMPL_IDS.slice();
    }

    async sign() {
        const before = await this.getScoreInfo();
        if (before && before.signIn === 1) {
            this.log(`✅ 今日已签到（积分 ${before.score ?? "-"}）`);
            return;
        }
        const tmplIds = await this.getTmplIds();
        const res = await this.request("/app/score/sign", {
            method: "POST",
            body: { tmplIds, platform: 1 },
        });
        if (isOk(res)) {
            const after = await this.getScoreInfo();
            const score = after?.score;
            this.log(`✅ 签到成功${score !== undefined ? `，当前积分 ${score}` : ""}`);
            return;
        }
        if (isAlreadyDone(msgOf(res))) return this.log(`✅ 今日已签到（${msgOf(res)}）`);
        // 签到失败时输出完整响应以便诊断路径/参数是否正确
        this.log(`❌ 签到失败: ${short(res, 300)}`);
    }

    async run() {
        if (!this.account.openid) {
            this.log("跳过：变量值里没有 openid");
            return;
        }
        try {
            await this.ensureLogin();
            await this.sign();
        } catch (e) {
            this.log(`执行失败: ${e.message || e}`);
        }
    }
}

!(async () => {
    await $.checkEnv(ckName);
    if (!$.userCount) {
        $.log(`未找到变量 ${ckName}`);
        return;
    }
    for (let i = 0; i < $.userList.length; i++) {
        await new Task($.userList[i]).run();
        if (i < $.userList.length - 1) await $.wait(1500, 3000);
    }
})()
    .catch((e) => $.log(e.message || e))
    .finally(() => $.done());
