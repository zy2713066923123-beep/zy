require('./yyb.js'); // 自动同步 yyb_go 存活账号
// name: 复游会
// cron: 25 8 * * *
/*
复游会 - 签到活动

变量名：fuyouhui
变量值：
  1. yyb_go 存活账号的 openid/账号标识，多账号用 & 或换行分隔（可加 #备注）
  2. openid#folidayMallToken，可首次写入/刷新本地缓存
  3. 仅 folidayMallToken，也可查询/签到，但不会携带当天 wxcode

变量：
  WX_SERVER      yyb_go 协议服务地址（例如：http://127.0.0.1:18273）
  WX_ID          (可选白名单) 微信账号 openid/wxid，多账号用 & 或换行分隔；留空自动拉取 yyb_go 所有存活账号
可选变量：fuyouhui_token（单账号 token 兜底）
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

const $ = new Env("复游会");
const axios = require("axios");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const ckName = "fuyouhui";
const MINI_APP_ID = "wx1fa4da2889526a37";
const API_BASE = "https://apis.folidaymall.com";
const SIGN_SALT = "3d83f7d9";
const TOKEN_CACHE_FILE = path.join(__dirname, "fuyouhui_token_cache.json");

const wechat = new WeChatServer({ appid: MINI_APP_ID });

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
    $.log(`token缓存写入失败: ${e.message || e}`);
  }
}

function md5(text) {
  return crypto.createHash("md5").update(String(text)).digest("hex");
}

function uuid() {
  return crypto.randomUUID
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === "x" ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      });
}

function mask(value = "") {
  value = String(value);
  if (!value) return "";
  if (value.length <= 12) return `${value.slice(0, 3)}***`;
  return `${value.slice(0, 6)}***${value.slice(-6)}`;
}

function clientInfo() {
  return JSON.stringify({
    app_version: "4.0.5",
    client_key: "wx_mini_tc",
    client_name: encodeURIComponent("复游会微信小程序"),
    os: "windows",
    app_key: "WX_MINI_TC",
  });
}

function parseAccount(raw) {
  const text = String(raw || "").trim();
  if (!text) return { openid: "", token: "" };

  if (text.startsWith("{")) {
    try {
      const data = JSON.parse(text);
      return {
        openid: data.openid || data.openId || data.account || "",
        token: data.token || data.folidayMallToken || "",
      };
    } catch {}
  }

  for (const sep of ["#", "|"]) {
    if (text.includes(sep)) {
      const [openid, ...rest] = text.split(sep);
      return { openid: openid.trim(), token: rest.join(sep).trim() };
    }
  }

  if (text.includes(".") || text.startsWith("eyJ")) return { openid: "", token: text };
  return { openid: text, token: "" };
}

async function request(method, urlPath, { token = "", data = null, params = null, headers = {} } = {}) {
  const res = await axios({
    method,
    url: `${API_BASE}${urlPath}`,
    data,
    params,
    timeout: 15000,
    validateStatus: () => true,
    headers: {
      version: "1.0",
      "User-Agent": "Mozilla/5.0 MicroMessenger MiniProgramEnv/Windows",
      Referer: `https://servicewechat.com/${MINI_APP_ID}/250/page-frame.html`,
      "X-Call-Client-Info": clientInfo(),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  });
  return res.data;
}

function assertOk(res, action) {
  if (!res || res.hasError || String(res.responseCode) !== "0") {
    throw new Error(`${action}失败: ${res?.errorMessage || res?.message || JSON.stringify(res)}`);
  }
  return res.data || {};
}

class Task {
  constructor(raw) {
    this.index = $.userIdx++;
    const account = parseAccount(raw);
    this.openid = account.openid;
    this.token = account.token || process.env.fuyouhui_token || "";
    this.member = {};
    this.wxcode = "";
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
      ...(this.member?.id ? { memberId: this.member.id } : {}),
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
    if (!this.openid) return "";
    const { data } = await wechat.getCode(this.openid);
    if (!data?.status) throw new Error(data?.message || "wx_server 获取 code 失败");
    const code = data.data?.code || data.code;
    if (!code) throw new Error(`wx_server 未返回 code: ${JSON.stringify(data)}`);
    this.wxcode = code;
    return code;
  }

  async getOperateData() {
    if (!this.openid) throw new Error("缺少 openid，无法自动授权");
    const ref = String(this.openid).split('#')[0].trim();
    // 1) 单独获取 wx.login code（operateWxData 不返回 code）
    const code = await getSingleCode(MINI_APP_ID, ref);
    // 2) 获取加密数据 encryptedData/iv（默认 webapi_getuserencryptkey，兼容多种返回结构）
    const wxData = await getSingleOperateWxData(MINI_APP_ID, ref);
    let encryptedData = wxData?.encryptedData || wxData?.encrypted_data || wxData?.data?.encryptedData || wxData?.Data?.encryptedData || "";
    let iv = wxData?.iv || wxData?.IV || wxData?.data?.iv || wxData?.Data?.iv || "";
    // 3) YYB 协议无 operate 加密载荷，退化为手机号加密数据接口
    if (!encryptedData || !iv) {
      const phone = await getSinglePhoneEncrypted(MINI_APP_ID, ref);
      if (phone) {
        encryptedData = phone.encryptedData || phone.encrypted_data || "";
        iv = phone.iv || phone.IV || "";
      }
    }
    if (!code || !encryptedData || !iv) {
      throw new Error(`自动授权数据不完整: code=${!!code}, encryptedData=${!!encryptedData}, iv=${!!iv}`);
    }
    return { code, encryptedData, iv };
  }

  async loginByOperateData() {
    const op = await this.getOperateData();
    const data = assertOk(
      await request("post", "/usercenter/online/wxmp/registerWxUserInfo", {
        data: {
          code: op.code,
          appChannel: "",
          appKey: "WX_MINI_TC",
          memberCode: "foryouclub_minipro_regs",
          iv: op.iv,
          encryptedData: op.encryptedData,
          joinXingXuan: false,
        },
      }),
      "自动授权"
    );
    const token = data.token || "";
    if (!token) throw new Error(`自动授权未返回 token: ${JSON.stringify(data)}`);
    this.token = token;
    this.saveCache({
      hasMobile: data.hasMobile,
      fkMember: data.fkMember || "",
    });
    $.log(`账号[${this.index}] 自动授权成功: ${mask(token)}`);
  }

  ensureToken() {
    if (!this.token) this.token = this.getCached().token || "";
    if (!this.token) {
      throw new Error("缺少 folidayMallToken。请将变量设置为 openid#token，或设置 fuyouhui_token。");
    }
  }

  async getMemberInfo() {
    const data = assertOk(
      await request("post", "/usercenter/online/mem/getMemberDetails", { token: this.token }),
      "查询会员信息"
    );
    this.member = data || {};
    if (data.refreshToken) this.token = data.refreshToken;
    this.saveCache({
      member: {
        id: data.id || "",
        phone: data.phone || "",
        openId: data.openId || "",
        account: data.account || "",
      },
    });
    return data;
  }

  signHeaders() {
    const timestamp = Date.now();
    const nonce = uuid();
    const memberId = this.member.id || this.getCached().memberId || "";
    if (!memberId) throw new Error("缺少会员ID，无法生成签到签名");
    return {
      "X-Sign-Timestamp": timestamp,
      "X-Sign-Nonce": nonce,
      "X-Sign-Signature": md5(`${memberId}${timestamp}${nonce}${SIGN_SALT}`),
      "X-Wx-Code": this.wxcode || "",
    };
  }

  async getUserSign() {
    const data = assertOk(
      await request("get", "/online/cms-api/sign/userSign", {
        token: this.token,
        headers: this.signHeaders(),
      }),
      "签到/查询状态"
    );
    return data.signInfo || {};
  }

  async queryAllRewards() {
    try {
      const data = assertOk(
        await request("get", "/online/cms-api/sign/queryAllRewards", { token: this.token }),
        "查询奖励列表"
      );
      return Array.isArray(data) ? data : data.queryAllRewards || data.rewards || [];
    } catch (e) {
      $.log(`账号[${this.index}] 奖励列表查询失败: ${e.message || e}`);
      return [];
    }
  }

  async queryScrollScreen() {
    try {
      const data = assertOk(
        await request("get", "/online/cms-api/sign/queryScrollScreen", { token: this.token }),
        "查询活动滚屏"
      );
      return Array.isArray(data) ? data : data.list || data.records || [];
    } catch (e) {
      $.log(`账号[${this.index}] 活动滚屏查询失败: ${e.message || e}`);
      return [];
    }
  }

  async queryPhoto() {
    try {
      const data = assertOk(await request("get", "/online/cms-api/sign/getPhoto"), "查询活动背景");
      return data.sign || {};
    } catch {
      return {};
    }
  }

  async receiveCoupon(cpId) {
    if (!cpId) return;
    try {
      const data = assertOk(
        await request("get", `/online/capi/cp/receiveCoupon?cpId=${encodeURIComponent(cpId)}`, {
          token: this.token,
        }),
        "领取优惠券"
      );
      $.log(`账号[${this.index}] 优惠券领取结果: ${JSON.stringify(data).slice(0, 120)}`);
    } catch (e) {
      $.log(`账号[${this.index}] 优惠券领取失败: ${e.message || e}`);
    }
  }

  printSignInfo(signInfo) {
    const parts = [
      `连续${signInfo.continousSignDays ?? "未知"}天`,
      `积分${signInfo.currentIntegral ?? "未知"}`,
    ];
    if (signInfo.changeIntegeral) parts.push(`本次+${signInfo.changeIntegeral}`);
    if (signInfo.couponName) parts.push(`券:${signInfo.couponName}`);
    if (signInfo.signRewardMsg) parts.push(String(signInfo.signRewardMsg).replace(/<[^>]+>/g, ""));

    const signedNow = signInfo.hasSign === false;
    const signedBefore = signInfo.hasSign === true;
    $.log(`账号[${this.index}] ${signedNow ? "签到成功" : signedBefore ? "今日已签到" : "签到状态"}，${parts.join("，")}`);
  }

  async run() {
    $.log(`\n账号[${this.index}] ${mask(this.openid || this.cacheKey)}`);

    if (this.openid) {
      try {
        await this.getWxCode();
      } catch (e) {
        $.log(`账号[${this.index}] 获取 wxcode 失败，继续使用 token: ${e.message || e}`);
      }
    }

    if (!this.token) this.token = this.getCached().token || "";
    if (!this.token) await this.loginByOperateData();
    this.ensureToken();

    try {
      const member = await this.getMemberInfo();
      $.log(`账号[${this.index}] 会员: ${mask(member.phone || member.account || member.id || "")}`);
    } catch (e) {
      this.removeToken();
      throw e;
    }

    if (this.openid) {
      try {
        await this.getWxCode();
      } catch (e) {
        $.log(`账号[${this.index}] 刷新签到 wxcode 失败: ${e.message || e}`);
      }
    }

    const signInfo = await this.getUserSign();
    this.printSignInfo(signInfo);
    await this.receiveCoupon(signInfo.cpId);

    const rewards = await this.queryAllRewards();
    if (rewards.length) $.log(`账号[${this.index}] 奖励列表: ${rewards.length}条`);

    const scroll = await this.queryScrollScreen();
    if (scroll.length) $.log(`账号[${this.index}] 滚屏记录: ${scroll.length}条`);

    const photo = await this.queryPhoto();
    if (photo.activityImg) $.log(`账号[${this.index}] 活动背景已获取`);
  }
}

!(async () => {
  await $.checkEnv(ckName);
  if (!$.userCount) return;
  for (const account of $.userList) {
    try {
      await new Task(account).run();
    } catch (e) {
      $.log(`账号执行失败: ${e.message || e}`);
    }
  }
})()
  .catch((e) => $.log(`脚本异常: ${e.message || e}`))
  .finally(() => $.done && $.done());
