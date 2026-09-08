require('./yyb.js'); // 自动同步 yyb_go 存活账号
// name: 漫鸟旧衣回收
// cron: 22 6 * * *
/*
------------------------------------------
@Description: 漫鸟旧衣上门回收 - 微信小程序静默登录 + 每日签到
------------------------------------------
变量名：mnhs
变量值：yyb_go 存活账号的 openid/账号标识，多账号用 & 或换行分隔（可加 #备注）

变量：
  WX_SERVER      yyb_go 协议服务地址（例如：http://127.0.0.1:18273）
  WX_ID          (可选白名单) 微信账号 openid/wxid，多账号用 & 或换行分隔；留空自动拉取 yyb_go 所有存活账号
------------------------------------------
契约（appid wxa587f7c3393d3d2f，host openapp.huishoujiuwu.com）：

登录  POST /auth/wx/paid/login
        {fmy_v:"1.0.00", platformKey:"wxa587f7c3393d3d2f", scope:"auth_base", mini_scene:1232, authCode:<wx code>}
        -> {code:200, data:{token:"eyJ...", openid, expire}}
签到  POST /active/sign-in/do
        {platformKey:"wxa587f7c3393d3d2f", mini_scene:1007}
        -> {code:200, message:"操作成功"}
余额  GET  /user/paid/base/info?platformKey=&mini_scene=&fmy_v=
        -> {data:{unfreeze_balance, base_info:{...}}}
token 用法：authorization: bearer <JWT>（登录返回的 token 前面带 bearer 前缀）
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

const $ = new Env("漫鸟旧衣回收");
const axios = require("axios");
const fs = require("fs");
const path = require("path");

const ckName = "mnhs";
const MINI_APP_ID = "wxa587f7c3393d3d2f";
const PLATFORM_KEY = "wxa587f7c3393d3d2f";
const BASE = "https://openapp.huishoujiuwu.com";
const TOKEN_CACHE_FILE = path.join(__dirname, "mnhs_token_cache.json");
const USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " +
    "Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI " +
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541c37) XWEB/25364";

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
            Referer: `https://servicewechat.com/${MINI_APP_ID}/48/page-frame.html`,
            "xweb_xhr": "1",
        };
        headers.authorization = withAuth ? (this.token.startsWith("bearer ") ? this.token : `bearer ${this.token}`) : "";
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

    async login() {
        const code = await this.getCode();
        const res = await this.request("/auth/wx/paid/login", {
            method: "POST",
            withAuth: false,
            body: {
                fmy_v: "1.0.00",
                platformKey: PLATFORM_KEY,
                scope: "auth_base",
                mini_scene: 1232,
                authCode: code,
            },
        });
        if (!isOk(res)) throw new Error(`登录失败: ${msgOf(res)}`);
        const token = String(res.data?.token || "");
        if (!token) throw new Error(`登录响应缺少 token: ${short(res)}`);
        this.token = token;
        const cache = readCache();
        cache[this.account.openid] = { token: this.token, updatedAt: new Date().toISOString() };
        writeCache(cache);
        this.log("登录成功");
    }

    async getBalance() {
        const res = await this.request("/user/paid/base/info", {
            params: { platformKey: PLATFORM_KEY, mini_scene: 1007, fmy_v: "1.0.00" },
        });
        if (isOk(res)) {
            const balance = res.data?.unfreeze_balance;
            if (balance !== undefined) this.log(`余额: ${balance}`);
        }
    }

    async ensureLogin() {
        const cached = readCache()[this.account.openid] || {};
        if (!this.token && cached.token) {
            this.token = cached.token;
            try {
                await this.getBalance();
                this.log("使用缓存token");
                return;
            } catch {
                this.log("缓存token失效，重新登录");
                this.token = "";
            }
        }
        if (!this.token) await this.login();
    }

    async sign() {
        const res = await this.request("/active/sign-in/do", {
            method: "POST",
            body: { platformKey: PLATFORM_KEY, mini_scene: 1007 },
        });
        if (isOk(res)) {
            this.log("✅ 签到成功");
            await this.getBalance();
            return;
        }
        if (isAlreadyDone(msgOf(res))) return this.log(`✅ 今日已签到（${msgOf(res)}）`);
        if (codeOf(res) === 401) {
            this.log(`❌ token 失效: ${msgOf(res)}`);
            return;
        }
        this.log(`❌ 签到失败: ${msgOf(res)}`);
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
