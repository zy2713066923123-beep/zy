/**
// name: 艾瑞调研问卷
------------------------------------------
@Author: sm
@Date: 2026.07.24
@Description: 艾瑞调研问卷 微信小程序每日签到（微信协议版，适配青龙）
cron: 45 8,14 * * *

变量名：WX_ID
变量值：微信账号（openid/wxid），多账号支持换行、& 分隔，必须配置

------------------------------------------

变量：
  WX_ID          微信账号（openid/wxid），多账号换行 / & 分隔，必须配置
  WECHAT_SERVER  牛子协议服务地址（可选，getCode.js 内配置）
  YYB_SERVER     应用宝服务地址（可选）

WX_ID 格式：
  wxid#备注  多个换行
------------------------------------------
*/

const axios = require("axios");
const { getSingleCode } = require("./getCode.js");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
// ====================== 账号（环境变量 WX_ID = wxid#备注，换行或&） ======================
const SERVERS = (process.env.WX_ID || "")
    .split(/\r?\n|&/)
    .map(s => s.trim())
    .filter(Boolean);
if (!SERVERS.length) {
    console.error("未配置环境变量 WX_ID，请设置后重试（格式：wxid#备注，换行或&）");
    process.exit(1);
}
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
        return await getSingleCode(MINI_APP_ID, __id);
    } catch (e) {
        console.log(__id + " 获取code异常: " + (e && e.message ? e.message : e));
        return null;
    }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
let userIdx = 1;

const MINI_APP_ID = "wx342d760f674b013b";
const API_BASE = "https://api.ikbang.cn/v2";
const APP_KEY = "A749380BBD5A4D93B55B4BE245A42988";
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "airui_token_cache.json");
try { fs.mkdirSync(path.dirname(TOKEN_CACHE_FILE), { recursive: true }); } catch (e) {}

function readCache() {
  try {
    if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
    return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
  } catch {
    return {};
  }
}

function writeCache(cache) {
  try {
    fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
  } catch (e) {
    console.log(`token缓存写入失败: ${e.message || e}`);
  }
}

function md5(text) {
  return crypto.createHash("md5").update(String(text)).digest("hex");
}

function mask(value = "") {
  value = String(value);
  if (!value) return "";
  if (value.length <= 12) return `${value.slice(0, 3)}***`;
  return `${value.slice(0, 6)}***${value.slice(-6)}`;
}

function parseAccount(raw) {
  const text = String(raw || "").trim();
  if (!text) return { openid: "", token: "" };

  if (text.startsWith("{")) {
    try {
      const data = JSON.parse(text);
      return {
        openid: data.openid || data.openId || data.account || "",
        token: data.token || "",
      };
    } catch {}
  }

  for (const sep of ["#", "|"]) {
    if (text.includes(sep)) {
      const [openid, ...rest] = text.split(sep);
      return { openid: openid.trim(), token: rest.join(sep).trim() };
    }
  }

  if (/^[A-F0-9]{64,}$/i.test(text)) return { openid: "", token: text };
  return { openid: text, token: "" };
}

function stringifyQuery(params = {}) {
  return new URLSearchParams(params).toString();
}

function makeSign(urlPath, method, params, timestamp, token = "") {
  let payload = "";
  if (params) {
    payload = method === "POST" ? JSON.stringify(params) : stringifyQuery(params);
  }
  return md5(`${API_BASE}${urlPath}${timestamp}${payload}${APP_KEY}${token || ""}`);
}

async function apiRequest(method, urlPath, { token = "", params = null } = {}) {
  const timestamp = String(Date.now());
  const sign = makeSign(urlPath, method, params, timestamp, token);
  const res = await axios({
    method,
    url: `${API_BASE}${urlPath}`,
    data: method === "POST" ? params : undefined,
    params: method === "GET" ? params : undefined,
    timeout: 15000,
    validateStatus: () => true,
    headers: {
      token,
      sign,
      timestamp,
      "Content-Type": "application/json",
      "User-Agent": "Mozilla/5.0 MicroMessenger MiniProgramEnv/Windows",
      Referer: `https://servicewechat.com/${MINI_APP_ID}/127/page-frame.html`,
    },
  });
  return res.data;
}

function assertOk(res, action) {
  if (!res || Number(res.code) !== 1) {
    throw new Error(`${action}失败: ${res?.description || res?.msg || JSON.stringify(res)}`);
  }
  return res.result;
}

class Task {
  constructor(raw) {
        this.server = raw;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
    this.index = userIdx++;
    const account = parseAccount(raw);
    this.openid = account.openid;
    this.token = account.token || "";
    this.userId = "";
    this.cacheKey = this.openid || (this.token ? md5(this.token).slice(0, 16) : `account_${this.index}`);
  }

  getCached() {
    return readCache()[this.cacheKey] || {};
  }

  saveCache(extra = {}) {
    const cache = readCache();
    cache[this.cacheKey] = {
      ...(cache[this.cacheKey] || {}),
      ...(this.token ? { token: this.token } : {}),
      ...(this.userId ? { userId: this.userId } : {}),
      ...extra,
      updatedAt: new Date().toISOString(),
    };
    writeCache(cache);
  }

  removeToken() {
    const cache = readCache();
    if (cache[this.cacheKey]) {
      delete cache[this.cacheKey].token;
      writeCache(cache);
    }
  }

  async getWxCode() {
        return await getCode(this.server);
    }

  async login() {
    const code = await this.getWxCode();
    const result = assertOk(
      await apiRequest("POST", "/app/auth/authorization", {
        params: {
          code,
          type: "register",
          acceptCode: "",
        },
      }),
      "登录授权"
    );

    if (Number(result.mobileAuthStatus) !== 1 || !result.token) {
      throw new Error("账号未完成手机号授权，需先在小程序登录一次");
    }

    this.token = result.token;
    this.userId = result.userId || "";
    this.saveCache({
      openid: result.openid || "",
      unionid: result.unionid || "",
      userName: result.userName || "",
      inviteCode: result.inviteCode || "",
    });
    console.log(`账号[${this.index}] 登录成功: ${mask(this.userId || this.token)}`);
  }

  async ensureLogin() {
    if (!this.token) this.token = this.getCached().token || "";
    if (this.token) return;
    await this.login();
  }

  async requestWithRelogin(method, urlPath, options = {}) {
    await this.ensureLogin();
    const res = await apiRequest(method, urlPath, { ...options, token: this.token });
    if (Number(res?.code) === -3 && this.openid) {
      console.log(`账号[${this.index}] token失效，重新登录`);
      this.removeToken();
      await this.login();
      return apiRequest(method, urlPath, { ...options, token: this.token });
    }
    return res;
  }

  async getUserInfo() {
    try {
      const info = assertOk(
        await this.requestWithRelogin("GET", "/iclick-new/usercenter/getUserDetails"),
        "查询用户信息"
      );
      this.userId = info.userId || this.userId;
      this.saveCache({ userName: info.userName || "", totalPoints: info.totalPoints || "" });
      console.log(`账号[${this.index}] 用户: ${info.userName || mask(info.userId || "")}，积分 ${info.totalPoints ?? "未知"}`);
      return info;
    } catch (e) {
      console.log(`账号[${this.index}] 用户信息查询失败: ${e.message || e}`);
      return {};
    }
  }

  async getSignInfo() {
    return assertOk(
      await this.requestWithRelogin("GET", "/iclick-new/signIn/getSignInInfo"),
      "查询签到信息"
    );
  }

  async submitSign() {
    return assertOk(await this.requestWithRelogin("POST", "/iclick-new/signIn/sign", { params: {} }), "签到");
  }

  async run() {
    console.log(`\n账号[${this.index}] ${mask(this.openid || this.cacheKey)}`);
    await this.ensureLogin();
    await this.getUserInfo();

    const before = await this.getSignInfo();
    if (before.currentSignIn) {
      console.log(`账号[${this.index}] 今日已签到，连续 ${before.continuityDay ?? "未知"} 天，总签到积分 ${before.totalSignInScore ?? "未知"}`);
      return;
    }

    const score = await this.submitSign();
    const after = await this.getSignInfo();
    console.log(`账号[${this.index}] 签到成功，获得 ${score ?? "未知"} 积分，连续 ${after.continuityDay ?? "未知"} 天，总签到积分 ${after.totalSignInScore ?? "未知"}`);
  }
}

!(async () => {
  
  if (!SERVERS.length) return;
  for (const account of SERVERS) {
    try {
      await new Task(account).run();
    } catch (e) {
      console.log(`账号执行失败: ${e.message || e}`);
    }
  }
})()
  .catch((e) => console.log(`脚本异常: ${e.message || e}`))
