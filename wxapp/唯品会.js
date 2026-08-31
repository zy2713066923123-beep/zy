require('./yyb.js'); // 自动同步 yyb_go 存活账号
// name: 唯品会
// cron: 12 09,21 * * *
const axios = require("axios");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

// ====================== 标准环境模块 ======================
class Env {
    constructor(name) { 
        this.name = name; 
        this.userList = []; 
        this.userIdx = 1; 
        this.logs = []; 
        const originalLog = console.log; 
        console.log = (...args) => { 
            this.logs.push(args.join(" ")); 
            originalLog.apply(console, args); 
        }; 
    }
    log(...args) { console.log(...args); this.logs.push(args.join(" ")); }
    async checkEnv(ckName) {
        // 优先从 yyb_go 服务端同步存活账号（参考霖久智服.js 的做法：拉取账号对象而非纯字符串）
        this.userList = await buildYybGoAccounts();
        if (!this.userList.length) console.log('未找到环境变量 WX_ID，且 yyb_go 无存活账号');
    }
    async done() { 
        try { 
            const notify = require('../sendNotify'); 
            await notify.sendNotify(this.name, this.logs.join('\n')); 
        } catch(e) { 
            console.log('通知发送失败', e); 
        } 
    }
}

// 引入 yyb.js 标准模块（支持双协议：牛子+应用宝）
const getWxCode = (wxid, appid) => getSingleCode(appid, String(wxid).split('#')[0].trim());

const $ = new Env("唯品会签到");

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

const MINI_APP_ID = "wxe9714e742209d35f";
const PACKAGE_VERSION = "1371";
const API_KEY = "ce29a51aa5c94a318755b2529dcb8e0b";
const HASH = "ptx26";
const ACT_ID = "H3gRnE1Xi18=";
const SIGN_SECRET_ENC = "Ql4mW09F3urBNdzBLfK6UuRTqj22Bta7eEKTO7n5jFf9uU6FZZmcfe/gurOAOB+o";

const CACHE_FILE = path.join(__dirname, "vipshop_token_cache.json");
const DEFAULT_MARS_CID = process.env.vipshop_mars_cid || "104104";
const DEFAULT_WAREHOUSE = "VIP_NH";
const DEFAULT_AREA = "104104";

function splitAccounts(value = "") {
  return String(value)
    .split(/\n|&/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function readCache() {
  try {
    if (!fs.existsSync(CACHE_FILE)) return {};
    return JSON.parse(fs.readFileSync(CACHE_FILE, "utf8")) || {};
  } catch {
    return {};
  }
}

function writeCache(cache) {
  try {
    fs.writeFileSync(CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
  } catch (e) {
    console.log(`缓存写入失败: ${e.message || e}`);
  }
}

function short(value, max = 600) {
  if (value === undefined || value === null) return "";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function mask(value = "") {
  value = String(value || "");
  if (!value) return "";
  if (value.length <= 12) return `${value.slice(0, 3)}***`;
  return `${value.slice(0, 6)}***${value.slice(-6)}`;
}

function sha1(text) {
  return crypto.createHash("sha1").update(String(text)).digest("hex");
}

function md5(text) {
  return crypto.createHash("md5").update(String(text)).digest("hex");
}

function aesDecryptBase64(text) {
  const key = Buffer.from("weixin_smallmina");
  const iv = Buffer.concat([Buffer.from("weixin"), Buffer.alloc(10)]);
  const decipher = crypto.createDecipheriv("aes-128-cbc", key, iv);
  let out = decipher.update(text, "base64", "utf8");
  out += decipher.final("utf8");
  return out;
}

function form(data = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(data)) {
    if (value === undefined || value === null) continue;
    params.append(key, typeof value === "object" ? JSON.stringify(value) : String(value));
  }
  return params.toString();
}

function parseAccount(raw = "") {
  const text = String(raw || "").trim();
  if (!text) return {};
  if (text.startsWith("{")) {
    const data = JSON.parse(text);
    return {
      openid: data.openid || data.openId || data.rawOpenid || "",
      token: data.token || data.VIP_TANK || data.vipTank || "",
      userId: data.userId || data.uid || "",
      vipOpenid: data.vipOpenid || data.vip_openid || data.encryptedOpenid || "",
      unionid: data.unionid || data.unionId || "",
      marsCid: data.marsCid || data.mars_cid || "",
      remark: data.remark || data.name || "",
    };
  }

  const [openid, token, userId, vipOpenid, remark] = text.split("#").map((item) => item.trim());
  if (!token && /^[A-F0-9]{32,}$/i.test(openid)) { return { token: openid }; }
  return { openid, token, userId, vipOpenid, remark };
}

function isSuccess(data) {
  return Number(data?.code) === 1 || Number(data?.code) === 0;
}

async function request(options) {
  const res = await axios.request({
    timeout: 30000,
    validateStatus: () => true,
    ...options,
    headers: {
      Accept: "application/json, text/plain, */*",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 MicroMessenger MiniProgramEnv/Windows",
      Referer: `https://servicewechat.com/${MINI_APP_ID}/${PACKAGE_VERSION}/page-frame.html`,
      ...(options.headers || {}),
    },
  });
  return { status: res.status, data: res.data, headers: res.headers || {} };
}


class Vipshop {
  constructor(account) {
    // account 支持两种形式：
    //   1) yyb_go 账号对象：{ openid, wxid, id, remark, ... }
    //   2) 纯字符串（wxid / openid）
    const acc = (account && typeof account === "object") ? account : { wxid: String(account || "") };
    // 优先 openid（应用宝），其次 wxid，再次数字 id；与 getWxCode 解析保持一致
    this.wxid = acc.openid || acc.wxid || (acc.id != null ? String(acc.id) : "") || "";
    this.remark = acc.remark || acc.nickname || acc.alias || "";
    this.account = acc;
    this.openid = this.wxid;
    this.token = acc.token || acc.VIP_TANK || acc.vipTank || "";
    this.userId = acc.userId || acc.uid || "";
    this.vipOpenid = acc.vipOpenid || acc.vip_openid || acc.encryptedOpenid || "";
    this.unionid = acc.unionid || acc.unionId || "";
    this.marsCid = acc.marsCid || acc.mars_cid || DEFAULT_MARS_CID;
    this.cacheKey = this.openid || (this.vipOpenid ? md5(this.vipOpenid).slice(0, 16) : `account_${$.userIdx}`);
  }

  log(message) {
    $.log(`账号[${$.userIdx}] ${message}`);
  }

  baseData() {
    return {
      app_name: "shop_weixin_mina",
      client: "wechat_mini_program",
      source_app: "shop_weixin_mina",
      api_key: API_KEY,
      app_version: "4.0",
      client_type: "wap",
      format: "json",
      mobile_platform: "2",
      ver: "2.0",
      standby_id: "native",
      union_mark: "",
      sd_tuijian: "",
      mobile_channel: "nature",
      mars_cid: this.marsCid,
      warehouse: DEFAULT_WAREHOUSE,
      fdc_area_id: DEFAULT_AREA,
      province_id: DEFAULT_AREA,
      wap_consumer: "A1",
      t: Math.floor(Date.now() / 1000),
      net: "WIFI",
      width: 375,
      height: 667,
      phone_model: "Windows",
      phone_brand: "",
      sys_version: "Windows 10",
      is_default_area: "1",
      app_theme_mode: "0",
      app_theme_action: "0",
      req_scene: 0,
    };
  }

  cookie() {
    const items = [
      `mars_cid=${this.marsCid}`,
      this.userId ? `userId=${this.userId}` : "",
      `warehouse=${DEFAULT_WAREHOUSE}`,
      this.token ? `VIP_TANK=${this.token}` : "",
      "wap_consumer=A1",
    ].filter(Boolean);
    return items.join("; ");
  }

  paramHash(data = {}, method = "POST") {
    const sorted = Object.keys(data)
      .sort()
      .reduce((obj, key) => {
        obj[key] = data[key];
        return obj;
      }, {});
    const text = Object.keys(sorted)
      .filter((key) => key !== "api_key")
      .map((key) => {
        let value = sorted[key];
        if (typeof value === "object" && String(method).toLowerCase() === "post") value = JSON.stringify(value);
        return `${key}=${value}`;
      })
      .join("&");
    return sha1(text);
  }

  signHeader(url, data = {}, method = "POST") {
    const pathOnly = url.replace(/^http(s)?:\/\/.*?\//, "/");
    const secret = aesDecryptBase64(SIGN_SECRET_ENC);
    const apiSign = sha1(`${pathOnly}${this.paramHash(data, method)}${this.token}${this.marsCid}${secret}`);
    return `OAuth api_sign=${apiSign}`;
  }

  signedHeaders(url, data) {
    const cookie = this.cookie();
    return {
      "Content-Type": "application/x-www-form-urlencoded",
      Cookie: cookie,
      "X-Traceid": `${cookie};__need_sign=1`,
      Authorization: this.signHeader(url, data, "POST"),
    };
  }

  getCached() {
    return readCache()[this.cacheKey] || {};
  }

  saveCache(extra = {}) {
    const cache = readCache();
    cache[this.cacheKey] = {
      ...(cache[this.cacheKey] || {}),
      ...(this.openid ? { openid: this.openid } : {}),
      ...(this.vipOpenid ? { vipOpenid: this.vipOpenid } : {}),
      ...(this.unionid ? { unionid: this.unionid } : {}),
      ...(this.token ? { token: this.token } : {}),
      ...(this.userId ? { userId: this.userId } : {}),
      marsCid: this.marsCid,
      ...extra,
      updatedAt: new Date().toISOString(),
    };
    writeCache(cache);
  }

  removeLoginCache() {
    const cache = readCache();
    if (cache[this.cacheKey]) {
      delete cache[this.cacheKey].token;
      delete cache[this.cacheKey].userId;
      writeCache(cache);
    }
  }

  loadCache() {
    const cached = this.getCached();
    this.token = this.token || cached.token || "";
    this.userId = this.userId || cached.userId || "";
    this.vipOpenid = this.vipOpenid || cached.vipOpenid || "";
    this.unionid = this.unionid || cached.unionid || "";
    this.marsCid = this.account.marsCid || cached.marsCid || this.marsCid;
  }

  async getVipWechatInfo(code) {
    const data = { ...this.baseData(), code, iv: "", encryptedData: "", hash: HASH };
    const { status, data: res } = await request({
      method: "POST",
      url: `https://weixin-api.vip.com/v4/LiteApp/getUserInfo?api_key=${API_KEY}`,
      headers: { "Content-Type": "application/x-www-form-urlencoded", Cookie: this.cookie() },
      data: form(data),
    });
    if (status !== 200 || Number(res?.code) !== 0 || !res?.data?.openid) {
      throw new Error(`获取唯品会openid失败 HTTP ${status}: ${short(res)}`);
    }
    this.vipOpenid = res.data.openid;
    this.unionid = res.data.unionid || this.unionid;
    this.log(`唯品会openid获取成功: ${mask(this.vipOpenid)}`);
  }

  async autoLogin(code) {
    const data = {
      ...this.baseData(),
      hash: HASH,
      code,
      event: 2,
      deviceId: this.marsCid,
      context: JSON.stringify({ iv: "", encryptedData: "" }),
      source_app_type: "shop_weixin_mina",
      login_type: "WEIXIN_SMALL_APP",
      third_type: "WEIXIN",
    };
    const { status, data: res } = await request({
      method: "POST",
      url: `https://mapi.vip.com/vips-mobile/rest/auth/third_party/trylogin/v1?api_key=${API_KEY}`,
      headers: { "Content-Type": "application/x-www-form-urlencoded", Cookie: this.cookie() },
      data: form(data),
    });
    if (status !== 200 || Number(res?.code) !== 1 || !res?.data?.tokenId) {
      // 命中唯品会第三方登录限流（fds limit）：保留已获取的 vipOpenid，下次只需补登录
      const msg = String(res?.msg || "");
      if (/fds limit|third login|频率|频繁|limit/i.test(msg)) {
        if (this.vipOpenid) this.saveCache();
        throw new Error(`自动登录被限流(third login fds limit)，请稍后重试或降低同时登录账号数: ${short(res)}`);
      }
      throw new Error(`自动登录失败 HTTP ${status}: ${short(res)}`);
    }
    this.token = res.data.tokenId;
    this.userId = String(res.data.userId || "");
    this.log(`登录成功 userId=${this.userId || "-"} VIP_TANK=${mask(this.token)}`);
  }

  async ensureLogin() {
    this.loadCache();
    if (this.token && this.userId && this.vipOpenid) {
      this.log(`使用缓存登录态 userId=${this.userId} VIP_TANK=${mask(this.token)}`);
      return;
    }
    // 已有 vipOpenid 也先缓存，避免重复取 code 触发限流
    if (this.vipOpenid) this.saveCache();

    const code = await getWxCode(this.wxid, MINI_APP_ID);
    if (!code) {
      // code 获取失败（微信 token 失效），若有 vipOpenid 则保留缓存，下次只需补登录
      if (this.vipOpenid) this.saveCache();
      throw new Error('获取微信 code 失败，请检查 yyb_go 中该账号登录态是否失效（token 过期/被抢新）');
    }
    if (!this.vipOpenid) await this.getVipWechatInfo(code);
    if (!this.token || !this.userId) await this.autoLogin(code);
    this.saveCache();
  }

  async signInfo() {
    const url = "https://act-ug.vip.com/checkInAward/withSign/info";
    const data = { ...this.baseData(), openid: this.vipOpenid, actId: ACT_ID, biz_code: "old" };
    const { status, data: res } = await request({
      method: "POST",
      url: `${url}?api_key=${API_KEY}`,
      headers: this.signedHeaders(url, data),
      data: form(data),
    });
    if (status !== 200 || Number(res?.code) !== 1) {
      if (Number(res?.code) === 10013 || Number(res?.code) === -2) this.removeLoginCache();
      throw new Error(`签到查询失败 HTTP ${status}: ${short(res)}`);
    }
    const info = res.data || {};
    const today = (info.checkInList || []).find((item) => Number(item.isCheckInDay) === 1) || {};
    this.log(
      `签到信息: 今日${Number(today.isCheckIn) === 1 ? "已签" : "未签"}，累计${info.numTotal ?? "-"}天，连续${
        info.nonStopNum ?? "-"
      }天，已得唯品币${info.awardVipcoinTotal ?? "-"}，下次奖励${info.nextTimeAwardAmount ?? "-"}`
    );
    return info;
  }

  async sign() {
    const before = await this.signInfo();
    const today = (before.checkInList || []).find((item) => Number(item.isCheckInDay) === 1) || {};
    if (Number(today.isCheckIn) === 1) {
      this.log("签到结果: 今日已签到");
      return before;
    }

    const url = "https://act-ug.vip.com/checkInAward/withSign/checkin";
    const data = { ...this.baseData(), openid: this.vipOpenid, actId: ACT_ID, biz_code: "old" };
    const { status, data: res } = await request({
      method: "POST",
      url: `${url}?api_key=${API_KEY}`,
      headers: this.signedHeaders(url, data),
      data: form(data),
    });
    if (status !== 200 || Number(res?.code) !== 1) {
      const message = String(res?.msg || "");
      if (/已签|重复|already/i.test(message)) {
        this.log("签到结果: 今日已签到");
        return this.signInfo();
      }
      throw new Error(`签到失败 HTTP ${status}: ${short(res)}`);
    }
    const result = res.data || {};
    this.log(
      `签到结果: 成功，获得${result.awardAmount ?? result.awardValDesc ?? "-"}，累计${result.numTotal ?? "-"}天，连续${
        result.nonStopNum ?? "-"
      }天`
    );
    return this.signInfo();
  }

  async run() {
    try {
      const label = this.remark ? `${this.remark}(${mask(this.wxid)})` : mask(this.wxid || this.vipOpenid || this.token);
      this.log(`开始执行 ${label}`);
      await this.ensureLogin();
      await this.sign();
      this.saveCache();
    } catch (e) {
      this.log(`执行失败: ${e.message || e}`);
    }
  }
}

// 当 WX_ID 未配置时，自动从 yyb_go 服务端拉取存活账号（参考霖久智服.js）
async function buildYybGoAccounts() {
  let list = [];
  try {
    list = await global.loadAccounts(); // WX_ID 留空时返回 yyb_go 所有存活账号
  } catch (e) {
    console.log(`[yyb] 从 yyb_go 拉取账号失败: ${e.message || e}`);
    return [];
  }
  if (!Array.isArray(list) || !list.length) return [];

  const mapped = list
    .map((acc, i) => {
      // openid 优先（应用宝），其次 wxid，再次数字 id；缓存键与 getWxCode 解析保持一致
      const wxid = acc.openid || acc.wxid || (acc.id != null ? String(acc.id) : '');
      if (!wxid) {
        console.log(`[yyb] 账号 ${i + 1} 缺少 openid/wxid/id，跳过: ${JSON.stringify(acc).slice(0, 120)}`);
        return null;
      }
      return {
        wxid,
        openid: wxid,
        id: acc.id,
        remark: acc.remark || acc.nickname || acc.alias || `yyb_${i + 1}`,
        unionid: acc.unionid || acc.unionId || '',
      };
    })
    .filter(Boolean);
  console.log(`[yyb] 自动从 yyb_go 同步到 ${mapped.length} 个存活账号`);
  return mapped;
}

!(async () => {
  await $.checkEnv("WX_ID");
  if ($.userList.length === 0) { $.log('未找到有效账号'); return; }
  for (let i = 0; i < $.userList.length; i++) {
    $.userIdx = i + 1;
    await new Vipshop($.userList[i]).run();
    if (i < $.userList.length - 1) await sleep(1500);
  }
  await $.done();
})()
  .catch((e) => $.log(`脚本异常: ${e.message || e}`))