require('./getCode.js'); // 自动同步 yyb_go 存活账号
/*
------------------------------------------
@Author: sm
@Date: 2026.05.31
@Update: 2026.08.06 (merge v1.1.3 社区互动重做逻辑)
@Description: 顾家小程序签到 + 社区互动赚积分
cron: 20 8 * * *
变量名：gujiajiaju / WX_ID
变量值：wx_server 里的 openid/账号标识，多账号用 & 或换行
------------------------------------------

变量：
  WX_SERVER      yyb_go 协议服务地址（例如：http://127.0.0.1:8000）
  WX_ID         (可选白名单) 微信账号，多账号支持换行、& 分隔，留空自动拉取 yyb_go 所有存活账号
  GJJJ_COMMUNITY    社区互动开关，=0 关闭（默认开）
  GJJJ_COMMUNITY_FORCE  社区互动强制重做开关，=1 跳过"找未互动帖子"，
                       直接取列表首条做取消重做（每天多次执行均计新分，默认关）

WX_ID 格式：
  openid#手机号  或  openid  多个换行
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
    let val = process.env.WX_ID || process.env[ckName];
    if (!val) {
      try {
        const adapter = new YYBAdapter();
        const accounts = await adapter.getAccounts();
        if (accounts && accounts.length > 0) {
          const alive = accounts.filter(a => ['alive', '', 'unknown'].includes(String(a.status || '').toLowerCase()));
          if (alive.length > 0) {
            val = alive.map(a => `${a.openid || a.id}#${a.nickname || a.alias || a.id}`).join('\n');
            process.env.WX_ID = val;
            console.log(`[getCode] 自动从 yyb_go (${adapter.serverUrl}) 成功获取到 ${alive.length} 个存活账号`);
          }
        }
      } catch (e) {
        console.log(`[getCode] 连接 yyb_go 获取账号失败: ${e.message}`);
      }
    }
    if (val) this.userList = val.split(/[\n&]+/).map(v => String(v).split('#')[0].trim()).filter(Boolean);
    else console.log('未找到环境变量 WX_ID');
  }
  async done() { try { const notify = require('../sendNotify'); await notify.sendNotify(this.name, this.logs.join('\n')); } catch(e) { console.log('通知发送失败', e); } }
}

const $ = new Env("顾家家居会员俱乐部");
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");


// ====================== 配置常量 ======================
const MINI_APP_ID = "wx0770280d160f09fe";
const PAGE_VERSION = "293";
const API_BASE = "https://mc.kukahome.com/club-server";
const INTEGRAL_BASE = "https://mc.kukahome.com/integral-server";
const BRAND_CODE = "K001";
const SMALL_APPLICATION_ID = "667516";
const SMALL_CRYPTO = "FH3yRrHG2RfexND8";
const VERSION_NUMBER = "2.0.184";
const TOKEN_CACHE_FILE = path.join(__dirname, "gujiajiaju_token_cache.json");
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

let ckName = "WX_ID";

const wechat = new WeChatServer({
  url: process.env.WX_SERVER || process.env.WECHAT_SERVER || "http://127.0.0.1:8000",
  appid: MINI_APP_ID,
  WX_ID: process.env.WX_ID || "",
});

// ====================== 工具函数 ======================
function md5(input) {
  return crypto.createHash("md5").update(String(input)).digest("hex");
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function readTokenCache() {
  try {
    if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
    return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
  } catch {
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

function isObject(val) {
  return Object.prototype.toString.call(val) === "[object Object]";
}

function buildParameterBase(data) {
  if (!data) return null;
  if (Array.isArray(data) || typeof data === "string") return null;
  if (!isObject(data)) return null;
  const keys = Object.keys(data).sort((a, b) => {
    const ac = [...a].map((ch) => ch.charCodeAt(0));
    const bc = [...b].map((ch) => ch.charCodeAt(0));
    for (let i = 0; i < Math.min(ac.length, bc.length); i++) {
      if (ac[i] !== bc[i]) return ac[i] - bc[i];
    }
    return ac.length - bc.length;
  });
  const pairs = [];
  for (const key of keys) {
    const value = data[key];
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) continue;
    if (typeof value === "object" && value !== null) {
      pairs.push(`${key}=${JSON.stringify(value)}`);
      continue;
    }
    if (typeof value === "number" && value === 0) {
      pairs.push(`${key}=0`);
      continue;
    }
    pairs.push(`${key}=${value}`);
  }
  return pairs.length ? pairs.join("&") : null;
}

function buildParameterSign(data, timestamp) {
  const base = buildParameterBase(data);
  if (!base) return "";
  const salt = String(timestamp).substring(4, 10);
  return md5(md5(base) + salt);
}

// ====================== Task ======================
class Task {
  constructor(openid) {
    this.index = $.userIdx++;
    this.openid = String(openid || "").split('#')[0].trim();
    this.tmpToken = "";
    this.accessToken = "";
    this.memberId = "";
    this.userInfo = {};
  }

  cacheKey() { return this.openid; }

  getCachedToken() {
    const cache = readTokenCache();
    return cache[this.cacheKey()] || null;
  }

  saveCachedToken() {
    if (!this.accessToken || !this.memberId) return;
    const cache = readTokenCache();
    cache[this.cacheKey()] = {
      accessToken: this.accessToken,
      memberId: this.memberId,
      nickName: this.userInfo.nickName || "",
      mobile: this.userInfo.mobile || "",
      updatedAt: new Date().toISOString(),
    };
    writeTokenCache(cache);
  }

  clearCachedToken() {
    const cache = readTokenCache();
    delete cache[this.cacheKey()];
    writeTokenCache(cache);
    this.tmpToken = "";
    this.accessToken = "";
    this.memberId = "";
    this.userInfo = {};
  }

  applyToken(data = {}) {
    this.accessToken = data.accessToken || data.token || this.accessToken;
    this.memberId = String(data.memberId || this.memberId || "");
  }

  async request({ method = "POST", url, data = {}, params = {}, withAuth = true, withTmpToken = true }) {
    const timestamp = Date.now();
    const sign = md5(`${SMALL_APPLICATION_ID}${SMALL_CRYPTO}${timestamp}`).toLowerCase();
    const bodyForSign = method.toUpperCase() === "GET" ? params : data;
    const parameterSign = buildParameterSign(bodyForSign, timestamp);
    const headers = {
      "User-Agent": USER_AGENT,
      Referer: `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
      Accept: "application/json, text/plain, */*",
      "Content-Type": "application/json",
      "X-Customer": this.memberId || "",
      brandCode: BRAND_CODE,
      appid: SMALL_APPLICATION_ID,
      "E-Opera": "",
      "xweb_xhr": "1",
      sign,
      timestamp,
      versionNumber: VERSION_NUMBER,
    };
    if (parameterSign) headers.parameterSign = parameterSign;
    if (withAuth && this.accessToken) headers.AccessToken = this.accessToken;
    if (withTmpToken && this.tmpToken) headers.tmpToken = this.tmpToken;

    const res = await axios.request({
      method,
      url,
      data,
      params,
      headers,
      timeout: 20000,
      validateStatus: () => true,
    });

    if (res.status !== 200) {
      throw new Error(`HTTP ${res.status}: ${JSON.stringify(res.data)}`);
    }
    const result = res.data || {};
    if (result.code !== undefined && ![0, 401, 402, 515].includes(Number(result.code))) {
      const err = new Error(result.message || result.msg || JSON.stringify(result));
      err.rawResponse = result;
      throw err;
    }
    return result;
  }

  /** 通过 getCode.js 统一接口获取微信 login code */
  async getWxCode() {
    return getSingleCode(MINI_APP_ID, this.openid);
  }

  async login() {
    const code = await this.getWxCode();
    const identify = await this.request({
      method: "POST",
      url: `${API_BASE}/api/user/identify`,
      params: { code },
      withAuth: false,
      withTmpToken: false,
    });
    if (identify.code !== 0 || !identify.data) {
      throw new Error(`identify失败: ${identify.message || JSON.stringify(identify)}`);
    }
    if (Number(identify.data.status) !== 4) {
      throw new Error(`登录状态异常: status=${identify.data.status}`);
    }
    this.tmpToken = identify.data.token || "";
    if (!this.tmpToken) throw new Error("identify未返回tmpToken");

    const auth = await this.request({
      method: "POST",
      url: `${API_BASE}/api/user/authorizeLogin`,
      data: { source: "顾家小程序", contentName: "" },
      withAuth: false,
      withTmpToken: true,
    });
    if (auth.code !== 0 || !auth.data?.token) {
      throw new Error(`authorizeLogin失败: ${auth.message || JSON.stringify(auth)}`);
    }
    this.accessToken = auth.data.token;
    this.memberId = String(auth.data.memberId || "");
    this.tmpToken = "";
  }

  async getUserInfo() {
    const info = await this.request({
      method: "POST",
      url: `${API_BASE}/api/user/info`,
      data: {},
      withAuth: true,
      withTmpToken: false,
    });
    if (!info.data) throw new Error("user/info返回为空");
    this.userInfo = info.data;
    this.applyToken(info.data);
    const openidMask = this.openid.length >= 12
      ? this.openid.slice(0, 6) + "..." + this.openid.slice(-6)
      : this.openid;
    const nick = this.userInfo.nickName || this.userInfo.name || "";
    const mobile = this.userInfo.mobile || "";
    let label = `【${openidMask}】`;
    if (nick) label += `(${nick})`;
    if (mobile) label += ` 手机：${mobile}`;
    console.log(`账号[${this.index}] 👤 用户: ${label}`);
  }

  async ensureLogin() {
    const cached = this.getCachedToken();
    if (cached) {
      this.applyToken(cached);
      console.log(`账号[${this.index}] 使用缓存token`);
      try {
        await this.getUserInfo();
        return;
      } catch {
        this.clearCachedToken();
        console.log(`账号[${this.index}] 缓存失效，重新登录`);
      }
    }
    await this.login();
    await this.getUserInfo();
    this.saveCachedToken();
    console.log(`账号[${this.index}] ✅ 登录成功`);
  }

  async getPoints() {
    const ret = await this.request({
      method: "POST",
      url: `${API_BASE}/front/member/personalCenter`,
      data: { t: Date.now() },
      withAuth: true,
      withTmpToken: false,
    });
    if (!ret || ret.point === undefined) throw new Error("查询积分失败");
    return Number(ret.point || 0);
  }

  async getSignCalendar() {
    const ret = await this.request({
      method: "GET",
      url: `${INTEGRAL_BASE}/user/sign/calendar`,
      params: {},
      withAuth: true,
      withTmpToken: false,
    });
    if (ret.code !== 0) throw new Error(ret.message || ret.msg || "查询签到日历失败");
    return ret.data || {};
  }

  async sign() {
    let ret;
    try {
      ret = await this.request({
        method: "POST",
        url: `${INTEGRAL_BASE}/scenePoint/scene/point`,
        data: {
          scene: "sign",
          brandCode: BRAND_CODE,
        },
        withAuth: true,
        withTmpToken: false,
      });

      if (ret.code === 0) {
        const gain = typeof ret.data === "number" ? ret.data : null;
        return { status: "success", ret, gain };
      }

      const msg = ret.message || ret.msg || JSON.stringify(ret);
      if (/已签|重复|already|今日/.test(msg)) {
        return { status: "already", ret, gain: null };
      }

      throw new Error(msg);
    } catch (e) {
      const msg = e.message || String(e);
      if (/已签|重复|already|今日/.test(msg)) {
        return { status: "already", ret: e.rawResponse, gain: null };
      }
      console.log(`账号[${this.index}] ❌ 签到接口返回失败: ${msg}`);
      throw e;
    }
  }

  // ---- 做任务：社区互动（点赞/收藏/分享晒家帖子赚积分）----
  async getTaskList() {
    const ret = await this.request({
      method: "GET",
      url: `${API_BASE}/front/member/selectPointTask`,
      params: { brandCode: BRAND_CODE },
      withAuth: true,
      withTmpToken: false,
    });
    if (ret.code === 0 && Array.isArray(ret.data) && ret.data.length) {
      const names = ret.data
        .map((t) => t.taskName || t.name || t.title || JSON.stringify(t))
        .join("、");
      console.log(`账号[${this.index}] 📋 可接任务(${ret.data.length}): ${names}`);
    } else {
      console.log(`账号[${this.index}] 📋 无可用任务列表或查询失败`);
    }
    return ret.data || [];
  }

  async findPost() {
    for (let pageNum = 1; pageNum <= 5; pageNum++) {
      const ret = await this._safe("帖子列表", () =>
        this.request({
          method: "POST",
          url: `${API_BASE}/applet/waterfall/newWaterfall`,
          data: { source: 1, pageNum, pageSize: 6 },
          withAuth: true,
          withTmpToken: false,
        })
      );
      if (!ret || ret.code !== 0) break;
      const items = Array.isArray(ret.data) ? ret.data : (ret.data && ret.data.list) || [];
      if (!items.length) break;
      for (const post of items) {
        const detail = await this._safe("帖子详情", () =>
          this.request({
            method: "POST",
            url: `${API_BASE}/front/postOrder/postOrderDetail`,
            data: { id: Number(post.id) },
            withAuth: true,
            withTmpToken: false,
          })
        );
        if (detail && detail.code === 0 && detail.data) {
          const likeStatus = detail.data.likeStatus;
          const collectStatus = detail.data.collectStatus;
          const untouched =
            (likeStatus == null && collectStatus == null) ||
            (String(likeStatus) === "0" && String(collectStatus) === "0");
          if (untouched) {
            const show = (post.title || "").toString().replace(/[\r\n]+/g, " ").trim();
            console.log(`账号[${this.index}] 🔍 找到可互动帖子: 「${show}」`);
            return post;
          }
        }
      }
    }
    return null;
  }

  async _safe(marker, fn) {
    try {
      return await fn();
    } catch (e) {
      console.log(`账号[${this.index}] ⚠️ ${marker}: ${e.message || e}`);
      return null;
    }
  }

  async pushEvent(eventId, content, targetId, targetName, businessId, businessName) {
    return this._safe("事件上报", () =>
      this.request({
        method: "POST",
        url: `${API_BASE}/front/member/pushEvent`,
        data: { eventId, content, targetId, targetName, businessId, businessName },
        withAuth: true,
        withTmpToken: false,
      })
    );
  }

  async insertFootPoint(buriedPointLogo, subordinateTerminal, businessName, businessCode, currentPageLink) {
    return this._safe("埋点上报", () =>
      this.request({
        method: "POST",
        url: `${API_BASE}/front/foot/point/insertFootPoint`,
        data: {
          brandCode: BRAND_CODE,
          buriedPointLogo,
          subordinateTerminal,
          businessName: businessName || "",
          businessCode: businessCode || "",
          currentPageLink: currentPageLink || "",
        },
        withAuth: true,
        withTmpToken: false,
      })
    );
  }

  async likeSendPoint(postOrderId, triggerType, content, forwardType) {
    const data = { postOrderId: Number(postOrderId), triggerType, content };
    if (forwardType !== undefined) data.forwardType = forwardType;
    try {
      const ret = await this.request({
        method: "POST",
        url: `${API_BASE}/front/member/likeSendPoint`,
        data,
        withAuth: true,
        withTmpToken: false,
      });
      if (Number(ret.code) !== 0) {
        console.log(`账号[${this.index}] ⚠️ 送积分未成功: ${content} (code=${ret.code}, msg=${ret.message || ret.msg || ""})`);
      }
      return ret;
    } catch (e) {
      console.log(`账号[${this.index}] ❌ 送积分异常: ${content} (${e.message || e})`);
      return null;
    }
  }

  // 点赞流程：先查当前点赞态，已赞则先取消（toggle 成 0），确保后续点赞能重新计新分；
  // 未点赞则直接点赞。送分接口对点赞不做按天去重，故重复执行会重复计分（符合每天多次执行预期）。
  async likePost(post) {
    const postId = Number(post.id);
    const title = (post.title || post.id).toString().replace(/[\r\n]+/g, " ").trim();
    const cur = await this._safe("帖子详情", () =>
      this.request({ method: "POST", url: `${API_BASE}/front/postOrder/postOrderDetail`, data: { id: postId }, withAuth: true, withTmpToken: false })
    );
    if (cur && cur.data && String(cur.data.likeStatus) === "1") {
      await this._safe("取消点赞", () =>
        this.request({ method: "POST", url: `${API_BASE}/front/postOrder/like`, data: { id: postId }, withAuth: true, withTmpToken: false })
      );
    }
    console.log(`账号[${this.index}] 👍 点赞: 「${title}」`);
    await this.pushEvent("c_showhome_like", "晒家-点赞", "300001", "晒家-点赞", String(postId), title);
    const likeRet = await this._safe("点赞", () =>
      this.request({ method: "POST", url: `${API_BASE}/front/postOrder/like`, data: { id: postId }, withAuth: true, withTmpToken: false })
    );
    if (!likeRet || Number(likeRet.code) !== 0) {
      console.log(`账号[${this.index}] ⚠️ 点赞接口未返回成功: ${JSON.stringify(likeRet && likeRet.data !== undefined ? likeRet.data : likeRet)}`);
    }
    await this.insertFootPoint("do_good_btn", "会员小程序", "", "", "");
    await this.likeSendPoint(postId, 1, "点赞");
  }

  // 收藏流程：已藏则先取消（toggle 成 0）再重做，保证本次仍能计新分。
  async collectPost(post) {
    const postId = Number(post.id);
    const title = (post.title || post.id).toString().replace(/[\r\n]+/g, " ").trim();
    const cur = await this._safe("帖子详情", () =>
      this.request({ method: "POST", url: `${API_BASE}/front/postOrder/postOrderDetail`, data: { id: postId }, withAuth: true, withTmpToken: false })
    );
    if (cur && cur.data && String(cur.data.collectStatus) === "1") {
      await this._safe("取消收藏", () =>
        this.request({ method: "POST", url: `${API_BASE}/front/postOrder/collect`, data: { id: postId }, withAuth: true, withTmpToken: false })
      );
    }
    console.log(`账号[${this.index}] ⭐ 收藏: 「${title}」`);
    const collectRet = await this._safe("收藏", () =>
      this.request({ method: "POST", url: `${API_BASE}/front/postOrder/collect`, data: { id: postId }, withAuth: true, withTmpToken: false })
    );
    if (!collectRet || Number(collectRet.code) !== 0) {
      console.log(`账号[${this.index}] ⚠️ 收藏接口未返回成功: ${JSON.stringify(collectRet && collectRet.data !== undefined ? collectRet.data : collectRet)}`);
    }
    await this.insertFootPoint("buriedPointLogo", "会员小程序", "", "", "");
    await this.likeSendPoint(postId, 2, "收藏");
  }

  async sharePost(post) {
    const postId = Number(post.id);
    const title = (post.title || post.id).toString().replace(/[\r\n]+/g, " ").trim();
    console.log(`账号[${this.index}] 🔁 分享: 「${title}」`);
    const shareRet = await this._safe("分享", () =>
      this.request({ method: "POST", url: `${API_BASE}/front/postOrder/share`, data: { id: postId }, withAuth: true, withTmpToken: false })
    );
    if (!shareRet || Number(shareRet.code) !== 0) {
      console.log(`账号[${this.index}] ⚠️ 分享接口未返回成功: ${JSON.stringify(shareRet && shareRet.data !== undefined ? shareRet.data : shareRet)}`);
    }
    await this.insertFootPoint("share_friend_btn", "会员小程序", "", "", "");
    await this.likeSendPoint(postId, 3, "微信好友转发", 2);
  }

  async communityTasks() {
    if (String(process.env.GJJJ_COMMUNITY) === "0") {
      console.log(`账号[${this.index}] ℹ️ 已关闭社区互动(GJJJ_COMMUNITY=0)`);
      return;
    }
    // GJJJ_COMMUNITY_FORCE=1：跳过"找未互动帖子"逻辑，直接取列表第一条做取消重做（每天多次执行都计新分）
    const force = String(process.env.GJJJ_COMMUNITY_FORCE) === "1";
    try {
      let post = null;
      if (!force) {
        post = await this.findPost(); // 优先取未点赞/未收藏的自然帖子
      }
      if (!post) {
        // 找不到未互动帖子（或全部已互动）→ 取 newWaterfall 第一条，由 likePost/collectPost 内部
        // 先做"取消"再重做，保证本次仍能计新分；分享由服务端按天去重天然幂等。
        const ret = await this._safe("帖子列表", () =>
          this.request({ method: "POST", url: `${API_BASE}/applet/waterfall/newWaterfall`, data: { source: 1, pageNum: 1, pageSize: 6 }, withAuth: true, withTmpToken: false })
        );
        const items = ret && ret.code === 0 ? (Array.isArray(ret.data) ? ret.data : (ret.data && ret.data.list) || []) : [];
        post = items[0] || null;
        if (post) console.log(`账号[${this.index}] 📝 无未互动帖子，取首条做取消重做: 「${(post.title || post.id).toString().slice(0, 30)}」`);
      }
      if (!post) {
        console.log(`账号[${this.index}] ⚠️ 社区无可用帖子`);
        return;
      }
      const title = (post.title || post.id).toString().replace(/[\r\n]+/g, " ").trim();
      if (!force && post.__fromFind) console.log(`账号[${this.index}] 📝 社区互动帖子: 「${title}」`);

      await this.likePost(post);
      await this.collectPost(post);
      await this.sharePost(post);

      console.log(`账号[${this.index}] 🎉 社区互动结束 (赞1/藏1/享1)`);
    } catch (e) {
      console.log(`账号[${this.index}] ❌ 社区互动异常: ${e.message || e}`);
    }
  }

  async run() {
    try {
      await this.ensureLogin();
      const pStart = await this.getPoints().catch(() => null);
      if (pStart !== null) console.log(`账号[${this.index}] 💰 当前积分: 【${pStart}】`);

      const cal = await this.getSignCalendar().catch(() => null);
      if (cal === null) {
        console.log(`账号[${this.index}] ⚠️ 签到日历查询失败，将尝试执行签到`);
      }

      let signRes = null;
      let cal2 = cal;
      const signed = cal ? !!cal.isTodaySigned : null;
      if (signed !== true) {
        signRes = await this.sign();
        cal2 = await this.getSignCalendar().catch(() => null);
      }

      if ((signRes && signRes.status === "already") || (signed === true && !signRes)) {
        console.log(`账号[${this.index}] 📝 每日签到： ⚠️ 今日已签到`);
      } else {
        const signConfirmed = cal2 ? !!cal2.isTodaySigned : true;
        if (!signConfirmed) {
          if (cal2 === null) {
            console.log(`账号[${this.index}] 📝 每日签到： ⚠️ 签到后日历查询失败，无法确认是否生效`);
          } else {
            console.log(`账号[${this.index}] 📝 每日签到： ❌ 签到接口返回成功但日历未确认`);
          }
        } else if (signRes && typeof signRes.gain === "number" && signRes.gain > 0) {
          console.log(`账号[${this.index}] 📝 每日签到： 🎉 签到成功 (+${signRes.gain}积分)`);
        } else {
          console.log(`账号[${this.index}] 📝 每日签到： 🎉 签到成功`);
        }
      }

      if (cal2 && cal2.signCount !== undefined && cal2.signCount !== null) {
        console.log(`账号[${this.index}] 📅 累计签到: 【${cal2.signCount}】天`);
      }

      await this.getTaskList().catch(() => {});
      await this.communityTasks().catch(() => {});

      let pEnd = pStart;
      let lastP = pStart;
      let stable = 0;
      for (let i = 0; i < 8; i++) {
        if (i > 0) await sleep(2500);
        const pTry = await this.getPoints().catch(() => null);
        if (pTry === null) continue;
        pEnd = pTry;
        if (pTry === lastP) {
          stable++;
          if (pTry !== pStart && stable >= 2) break;
          if (stable >= 3) break;
        } else {
          stable = 0;
          lastP = pTry;
        }
      }
      if (pStart !== null) {
        const delta = pEnd - pStart;
        const signGain = signRes && typeof signRes.gain === "number" ? signRes.gain : 0;
        const communityGain = delta - signGain;
        const parts = [];
        if (signGain !== 0) parts.push(`签到+${signGain}积分`);
        if (communityGain !== 0) parts.push(`社区+${communityGain}积分`);
        const detail = parts.length ? `（${parts.join("，")}）` : "";
        const arrow = delta === 0 ? `【${pEnd}】` : `【${pStart}】→【${pEnd}】 本次 +${delta}积分${detail}`;
        console.log(`账号[${this.index}] 💰 积分: ${arrow}`);
      }
      this.saveCachedToken();
    } catch (e) {
      const msg = e.message || String(e);
      console.log(`账号[${this.index}] 执行失败: ${msg}`);
      if (/401|token|登录|失效|过期/i.test(msg)) this.clearCachedToken();
    }
  }
}

// ====================== 主入口 ======================
!(async () => {
  console.log(`============ 顾家家居会员俱乐部 ============`);
  await $.checkEnv(ckName);
  console.log(`共 ${$.userList.length} 个账号`);
  for (const openid of $.userList) {
    await new Task(openid).run();
    if ($.userList.indexOf(openid) < $.userList.length - 1) await sleep(3000);
  }
  console.log(`============ 顾家家居会员俱乐部 执行结束 ============`);
})()
  .catch((e) => $.log(e.message || e))
  .finally(() => $.done());