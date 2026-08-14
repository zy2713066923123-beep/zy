#!/usr/bin/env node
/**
 * name:幸运星
 *  cron:0 10,15 * * *

 * =========================================================
 * 原理: 业务走 H5 mtop 网关 (waimai-guide.ele.me/h5), 签名可完全用 Node 复现:
 *         x-sign = md5(_m_h5_tk_token & t & appKey & JSON.stringify(data))
 *       无需 x-mini-wua / 签名代理, 无需 App 环境。
 *
 * 功能: 1.查星 2.每日签到 3.日常任务(服务端有则做) 4.兑换(到点抢购)
 *
 * 青龙部署:
 *   1. 脚本管理新建 lucky_star_auto.js, 粘贴本文件
 *   2. 环境变量(都可选, 不填用默认值):
 *        ELEME_COOKIE        饿了么 H5 Cookie (必填, 多账号用 & 或换行分隔)
 *        LUCKY_LAT         纬度 (默认广州)
 *        LUCKY_LNG         经度
 *        LUCKY_EXCHANGE_ID 默认要抢的商品 exchangeId (填了就会自动去兑)
 *        LUCKY_FORCE       1=跳过前端状态预检直接打兑换接口(抢秒杀推荐)
 *        LUCKY_RETRY       兑换失败重试次数 (默认 5)
 *        LUCKY_SNAP_HOUR   整点抢购小时, 如 10 则脚本等到 10:00:00 才开打 (可选)
 *        LUCKY_NOTIFY      1=强制用青龙 sendNotify 推送 (默认自动探测)
 * 
 *
 * CLI 参数(优先级高于同名环境变量):
 *   --exchange <id>   兑换指定商品
 *   --auto            自动兑第一个 AVAILABLE 商品
 *   --force           跳过状态预检
 *   --mission         仅做日常任务
 *   --snap <hour>     等到指定整点再开打 (如 --snap 10)
 *   --retry <n>       重试次数
 */
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

// ======================= 配置 (环境变量优先) =======================
const APPKEY = "12574478";
const GW = "https://waimai-guide.ele.me/h5";
const VERSION = "1.3.6";
const REFERER = "https://tb.ele.me/app/TBTakeout/engage-hub/home";
const UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1";
const LOCATION = {
  latitude: process.env.LUCKY_LAT || "23.285497",
  longitude: process.env.LUCKY_LNG || "113.305108",
};
const ASAC = {
  exchange: "alsc5KvbdX5mHl3sdv4guV",
  signin: "alsc3Lhy681SA5TT4iHgL3",
};
const SOURCE = "ENGAGE_HUB"; // 兑换"业务来源"字段

// ======================= 青龙环境探测 =======================
const isQinglong = fs.existsSync("/ql") || !!process.env.QINGLONG || !!process.env.QL_DIR;
let sendNotify = null;
if (isQinglong && process.env.LUCKY_NOTIFY !== "0") {
  try {
    // 青龙自带通知模块
    const qlNotify = path.join("/ql", "data", "scripts", "sendNotify.js");
    if (fs.existsSync(qlNotify)) sendNotify = require(qlNotify);
  } catch (e) { sendNotify = null; }
}

// ======================= 工具 =======================
function md5(s) { return crypto.createHash("md5").update(s, "utf8").digest("hex"); }
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

/**
 * 读取 Cookie, 支持多账号: 环境变量用 & 或换行分隔, 文件每行一个
 */
function readCookies() {
  let raw = "";
  if (process.env.ELEME_COOKIE) {
    raw = process.env.ELEME_COOKIE.trim();
  } else {
    const f = path.join(__dirname, "ele_cookie.txt");
    if (fs.existsSync(f)) raw = fs.readFileSync(f, "utf8").trim();
  }
  if (!raw) throw new Error("未找到 Cookie: 请在青龙环境变量设置 ELEME_COOKIE (多账号用 & 或换行分隔)");
  // 按 & 或换行分隔, 过滤空行
  const cookies = raw.split(/[&\n\r]+/).map((s) => s.trim()).filter(Boolean);
  // 防止误把单个 Cookie 中的 & 当分隔符: 如果分割后的片段不含 = 则说明不是独立 Cookie
  // 判断依据: 有效 Cookie 至少包含 userId= 或 sid= 等关键字段
  if (cookies.length > 1 && !cookies.every((c) => /userId=|sid=|SID=|cookie2=/i.test(c))) {
    // 不是多账号, 可能是单个 Cookie 中包含 &, 回退为整体
    return [raw];
  }
  return cookies;
}

function getToken(cookie) {
  const m = cookie.match(/_m_h5_tk=([^;]+)/);
  if (!m) return null; // 不再抛错, 返回 null 以便后续自动获取
  return m[1].split("_")[0];
}

/**
 * 从 Set-Cookie 响应头中提取 _m_h5_tk / _m_h5_tk_enc
 */
function extractTokensFromHeaders(res) {
  const raw = res.headers.getSetCookie ? res.headers.getSetCookie() : (res.headers.get("set-cookie") || "").split(/,(?=[^ ])/); 
  const tokens = {};
  for (const c of raw) {
    const m1 = c.match(/_m_h5_tk=([^;]+)/);
    if (m1) tokens._m_h5_tk = m1[1];
    const m2 = c.match(/_m_h5_tk_enc=([^;]+)/);
    if (m2) tokens._m_h5_tk_enc = m2[1];
  }
  return tokens;
}

/**
 * Cookie 中缺少 _m_h5_tk 时, 发预请求让网关下发 token
 * 返回: 追加了 _m_h5_tk / _m_h5_tk_enc 后的完整 Cookie 字符串
 */
async function acquireH5Token(cookie) {
  if (getToken(cookie)) {
    log("token", "Cookie 已含 _m_h5_tk, 跳过预请求");
    return cookie;
  }
  log("token", "Cookie 缺少 _m_h5_tk, 发起预请求获取...");
  const t = Date.now();
  // 用空 token 计算签名 (网关会返回新 token)
  const dummySign = md5(`&${t}&${APPKEY}&{}`);
  const url = `${GW}/mtop.alsc.user.session.ele.check/1.0/?jsv=2.7.2&appKey=${APPKEY}&t=${t}&api=mtop.alsc.user.session.ele.check&v=1.0&data=${encodeURIComponent("{}")}&sign=${dummySign}`;
  const res = await fetch(url, {
    headers: { "user-agent": UA, referer: REFERER, cookie },
    redirect: "manual",  // 保留 Set-Cookie
  });
  const tokens = extractTokensFromHeaders(res);
  if (!tokens._m_h5_tk) {
    // 再试一次, 用 GET 请求首页接口
    const t2 = Date.now();
    const sign2 = md5(`&${t2}&${APPKEY}&{}`);
    const url2 = `${GW}/mtop.common.getTimestamp/1.0/?jsv=2.7.2&appKey=${APPKEY}&t=${t2}&sign=${sign2}&api=mtop.common.getTimestamp&v=1.0&dataType=json&type=originaljson&data=${encodeURIComponent("{}")}`;
    const res2 = await fetch(url2, {
      headers: { "user-agent": UA, referer: REFERER, cookie },
      redirect: "manual",
    });
    const tokens2 = extractTokensFromHeaders(res2);
    Object.assign(tokens, tokens2);
  }
  if (!tokens._m_h5_tk) {
    throw new Error("预请求未能获取 _m_h5_tk, 请检查 Cookie 是否有效 (需包含有效的登录态: SID/userId/sgcookie 等)");
  }
  // 把获取到的 token 追加到 cookie 字符串中
  let newCookie = cookie;
  newCookie += `; _m_h5_tk=${tokens._m_h5_tk}`;
  if (tokens._m_h5_tk_enc) newCookie += `; _m_h5_tk_enc=${tokens._m_h5_tk_enc}`;
  log("token", `已获取 _m_h5_tk=${tokens._m_h5_tk.substring(0, 12)}...`);
  return newCookie;
}

// 青龙友好日志: 同时收集到 notifyLines 用于推送
let notifyLines = [];
function log(tag, msg) {
  const line = `[${tag}] ${msg}`;
  console.log(line);
  notifyLines.push(line);
}
async function notify(title, body) {
  if (sendNotify) {
    try { await sendNotify(title, body); return; } catch (e) {}
  }
  // 非青龙/通知失败: 直接打印, 青龙仍会抓取日志
  console.log(`\n===== ${title} =====\n${body}`);
}

function statusText(st, star, need) {
  switch (st) {
    case "SECKILL_ENDED": return "秒杀已结束";
    case "INVENTORY_NOT_ENOUGH": return "库存不足";
    case "PROPERTY_NOT_ENOUGH": return star < need ? "星数不足" : "不可兑换";
    case "EXCHANGED": return "已兑换";
    default: return st;
  }
}

// ======================= mtop H5 请求 =======================
class MtopH5 {
  constructor(cookie) {
    this.cookie = cookie;
    this.tk = getToken(cookie) || "";
  }

  /** 工厂方法: 自动获取 token 后再构造 */
  static async create(rawCookie) {
    const fullCookie = await acquireH5Token(rawCookie);
    return new MtopH5(fullCookie);
  }

  async call(api, data, headers = {}, method = "POST", retry = true, useBody = false) {
    const t = Date.now();
    const ds = JSON.stringify(data);
    const sign = md5(`${this.tk}&${t}&${APPKEY}&${ds}`);
    const p = new URLSearchParams({
      jsv: "2.7.2", appKey: APPKEY, t: String(t), sign, api, v: "1.0",
      dataType: "json", timeout: "10000", mainDomain: "ele.me",
      subDomain: "waimai-guide", pageDomain: "ele.me", H5Request: "true",
      type: "originaljson",
    });
    const url = `${GW}/${api}/1.0/?${p.toString()}`;
    const opts = {
      method,
      headers: {
        accept: "application/json",
        "content-type": "application/x-www-form-urlencoded",
        "user-agent": UA, referer: REFERER, cookie: this.cookie, ...headers,
      },
    };
    let finalUrl = url;
    if (useBody) opts.body = "data=" + encodeURIComponent(ds);
    else { p.set("data", ds); finalUrl = `${GW}/${api}/1.0/?${p.toString()}`; }
    const res = await fetch(finalUrl, opts);
    let js;
    try { js = await res.json(); } catch { js = { ret: ["FAIL_SYS_HTTP_RESPONSE"], data: null }; }
    const ret = (js.ret || []).join("|");

    // token 失效自动刷新: 从响应头重新获取 _m_h5_tk
    if (retry && (ret.includes("FAIL_SYS_TOKEN_EMPTY") || ret.includes("FAIL_SYS_TOKEN_EXOIRED") || ret.includes("TOP_UNAUTHORIZED"))) {
      log("网关", "token 失效, 尝试从响应头刷新...");
      try {
        const t2 = Date.now();
        const refreshSign = md5(`${this.tk}&${t2}&${APPKEY}&{}`);
        const refreshRes = await fetch(`${GW}/mtop.alsc.user.session.ele.check/1.0/?jsv=2.7.2&appKey=${APPKEY}&t=${t2}&api=mtop.alsc.user.session.ele.check&v=1.0&data=${encodeURIComponent("{}")}&sign=${refreshSign}`, {
          headers: { "user-agent": UA, referer: REFERER, cookie: this.cookie },
          redirect: "manual",
        });
        const newTokens = extractTokensFromHeaders(refreshRes);
        if (newTokens._m_h5_tk) {
          // 更新 cookie 中的 _m_h5_tk
          this.cookie = this.cookie.replace(/_m_h5_tk=[^;]+/, `_m_h5_tk=${newTokens._m_h5_tk}`);
          if (newTokens._m_h5_tk_enc) {
            this.cookie = this.cookie.replace(/_m_h5_tk_enc=[^;]+/, `_m_h5_tk_enc=${newTokens._m_h5_tk_enc}`);
          }
          this.tk = newTokens._m_h5_tk.split("_")[0];
          log("网关", `token 已刷新: ${this.tk.substring(0, 12)}...`);
        } else {
          // fallback: 尝试从 cookie 中读取 (兼容旧逻辑)
          this.tk = getToken(this.cookie) || this.tk;
        }
      } catch (e) {
        log("网关", `刷新异常: ${e.message}`);
        this.tk = getToken(this.cookie) || this.tk;
      }
      return this.call(api, data, headers, method, false);
    }
    return js;
  }
}

// ======================= 业务 =======================
async function homepage(m) {
  return m.call("mtop.alsc.interact.et.interact.center.homepage", {
    bizScene: "interact_center", ...LOCATION,
  });
}

async function signIn(m, copyId) {
  return m.call("mtop.alsc.interact.playapp.signin.component.signinandreceive",
    { copyId, bizScene: "interact_center", ...LOCATION },
    { asac: ASAC.signin }, "POST");
}

async function itemDetail(m, exchangeId) {
  const r = await m.call("mtop.alsc.interact.playapp.reward.right.mallitemdetail",
    { bizScene: "interact_center", version: VERSION, exchangeId });
  return (r.data || {}).data || null;
}

async function exchange(m, item, copyId) {
  const detail = await itemDetail(m, item.exchangeId);
  const sceneCode = (detail && detail.sceneCode) || "D649FXQR3H5";
  const data = {
    bizScene: "interact_center",
    version: VERSION,
    exchangeId: item.exchangeId,
    actCode: item.actCode,
    rightId: item.rightId,
    exchangeCollectionId: item.exchangeCollectionId || "",
    exchangeActId: item.exchangeActId || "",
    itemName: item.materialInfo.title,
    requiredAmount: item.exchangeInfo.consumeAmount,
    actId: item.exchangeActId,
    copyId,
    rightConsultSource: (detail && detail.rightConsultSource) || "DOWNSTREAM",
    sceneCode,
    source: SOURCE,
    ...LOCATION,
  };
  return m.call("mtop.alsc.interact.playapp.reward.right.exchange", data, { asac: ASAC.exchange }, "POST");
}

// ======================= 任务 =======================
async function queryMissionCollectionId(m, hpData) {
  const res = (hpData && hpData.resource && hpData.resource.data) || {};
  const cpn = res.INTERACT_RESOURCE_CPN;
  if (Array.isArray(cpn) && cpn[0] && cpn[0].missionCollectionId) return cpn[0].missionCollectionId;
  return "";
}

async function queryTasks(m, missionCollectionId) {
  if (!missionCollectionId) return [];
  const js = await m.call("mtop.ele.biz.growth.task.core.querytask",
    { missionCollectionId, bizScene: "interact_center", ...LOCATION }, {}, "POST", true, true);
  const ret = (js.ret || []).join("|");
  if (!ret.includes("SUCCESS")) { log("任务", `查询失败: ${ret}`); return []; }
  return (js.data && js.data.missionList) || (js.data && js.data.data && js.data.data.missionList) || [];
}

async function doMission(m, missionCollectionId, mission) {
  const base = { missionCollectionId, missionId: mission.missionDefId || mission.missionId, ...LOCATION };
  if (mission.instanceId) base.instanceId = mission.instanceId;
  try {
    await m.call("mtop.ele.biz.growth.task.event.pageview",
      { ...base, eventType: "MISSION_VIEW" }, {}, "POST", true, true);
  } catch {}
  try {
    await m.call("mtop.ele.biz.growth.task.core.receivetask", base, {}, "POST", true, true);
  } catch {}
  const r = await m.call("mtop.ele.biz.growth.task.core.receiveprize", base, {}, "POST", true, true);
  return (r.ret || []).join("|");
}

// ======================= 到点抢购 =======================
function waitUntil(hour) {
  const now = new Date();
  const target = new Date(now);
  target.setHours(hour, 0, 0, 0);
  if (target <= now) target.setDate(target.getDate() + 1); // 已过则等明天
  const ms = target - now;
  log("抢购", `等待到 ${hour}:00:00 开打 (还有 ${Math.round(ms / 1000)} 秒)`);
  return sleep(ms);
}

// ======================= 单账号执行 =======================
async function runAccount(cookie, acctIndex, opts) {
  const label = `账号${acctIndex}`;
  notifyLines = [];  // 每个账号独立的通知行
  log(label, `========== 开始 ==========`);

  let m;
  try {
    m = await MtopH5.create(cookie);
  } catch (e) {
    log(label, `初始化失败: ${e.message}`);
    await notify(`幸运星 ${label} 初始化失败`, notifyLines.join("\n"));
    return;
  }
  log(label, `脚本启动 (H5 网关 v${VERSION}${isQinglong ? ", 青龙环境" : ""})`);

  // 1. 查星 / 签到状态 / 商品列表
  const hp = await homepage(m);
  const ret = (hp.ret || []).join("|");
  if (!ret.includes("SUCCESS")) {
    log(label, `首页获取失败: ${ret}`);
    await notify(`幸运星 ${label} 任务失败`, `首页获取失败: ${ret}`);
    return;
  }
  const d = hp.data.data;
  const nickname = d.shareInfo?.data?.nickname || "";
  if (nickname) log(label, `昵称: ${nickname}`);
  const star = d.property?.data?.STAR?.amount ?? 0;
  log(label, `当前 ${star} 颗幸运星`);

  // 签到: 首页可能返回签到数据, 也可能返回 SIGN_IN_QUERY_FAILED
  let signInData = d.signIn?.data;
  let copyId = signInData?.extInfo?.copyId || signInData?.copyId || "";
  let signStatus = signInData?.status || "";

  // 首页签到查询失败时, 尝试从整个首页数据中搜索 copyId
  if (!copyId && (d.signIn?.errorCode || !d.signIn?.success)) {
    log("签到", `服务端签到查询失败 (${d.signIn?.errorCode || "success=false"})`);
    log("签到", "提示: Cookie 缺少追踪字段(cna/isg/l等)可能导致签到风控拦截");
    // 尝试从首页其他字段递归搜索 copyId (兜底)
    (function findCopyId(obj, depth) {
      if (!obj || typeof obj !== "object" || depth > 5 || copyId) return;
      if (obj.copyId) { copyId = obj.copyId; return; }
      for (const v of Object.values(obj)) findCopyId(v, depth + 1);
    })(d, 0);
  }

  if (!signStatus) signStatus = copyId ? "NOT_SIGNIN" : "QUERY_FAILED";
  log("签到", `状态: ${signStatus === "HAS_SIGNIN" ? "今日已签到" : signStatus}`);

  // 2. 签到 (未签才签)
  if (signStatus !== "HAS_SIGNIN" && signStatus !== "QUERY_FAILED" && copyId) {
    log("签到", "今日未签到, 开始签到...");
    const s = await signIn(m, copyId);
    const sret = (s.ret || []).join("|");
    if (sret.includes("SUCCESS")) log("签到", "签到成功!");
    else log("签到", `签到结果: ${sret}`);
    await sleep(800);
  } else if (signStatus === "HAS_SIGNIN") {
    log("签到", "跳过 (今日已签到)");
  } else {
    log("签到", "跳过 (签到查询失败, 无法获取 copyId)");
  }

  // 2.5 日常任务
  if (opts.autoMission) {
    const mcId = await queryMissionCollectionId(m, d);
    if (mcId) {
      const missions = await queryTasks(m, mcId);
      log("任务", `共 ${missions.length} 个任务`);
      for (const ms of missions) {
        const title = ms.missionName || ms.title || ms.missionDefId || "?";
        const status = ms.status;
        console.log(`  [${status}] ${title}`);
        if (status === "INIT" || status === "CAN_RECEIVE" || status === "UNCLAIMED" || status === "TODO") {
          const r = await doMission(m, mcId, ms);
          log("任务", `${title} => ${r}`);
          await sleep(500);
        }
      }
    } else {
      log("任务", "本账号当前无任务集合 (服务端未下发)");
    }
  }

  // 3. 列出商品
  const items = d.exchange?.data || [];
  log("商城", `共 ${items.length} 个商品:`);
  const available = [];
  for (const it of items) {
    const st = it.exchangeInfo.exchangeStatus;
    const starNeed = it.exchangeInfo.consumeAmount;
    console.log(`  [${st}] ${it.materialInfo.title} (${starNeed}星) ${statusText(st, star, starNeed)} | id=${it.exchangeId}`);
    if (st === "AVAILABLE") available.push(it);
  }

  // 4. 兑换 (带重试)
  let target = null;
  if (opts.exchangeTarget) {
    target = items.find((it) => it.exchangeId === opts.exchangeTarget) || null;
    if (!target) { log("兑换", `未找到商品: ${opts.exchangeTarget}`); }
  } else if (available.length) {
    target = available[0];
  }

  if (!target) {
    log("兑换", "无目标商品 (用 --exchange <id> 或环境变量 LUCKY_EXCHANGE_ID 指定)");
    await notify(`幸运星 ${label} 签到完成`, notifyLines.join("\n"));
    return;
  }

  if (target.exchangeInfo.exchangeStatus !== "AVAILABLE" && !opts.force) {
    log("兑换", `${target.materialInfo.title} 当前不可兑换 (${target.exchangeInfo.exchangeStatus}), 跳过`);
    await notify(`幸运星 ${label} 运行结束`, notifyLines.join("\n"));
    return;
  }
  if (target.exchangeInfo.consumeAmount > star && !opts.force) {
    log("兑换", `${target.materialInfo.title} 需要 ${target.exchangeInfo.consumeAmount} 星, 当前 ${star} 星, 星数不足`);
    await notify(`幸运星 ${label} 星数不足`, notifyLines.join("\n"));
    return;
  }

  log("兑换", `开始兑换: ${target.materialInfo.title} (${target.exchangeInfo.consumeAmount}星), 重试 ${opts.retryN} 次`);
  let ok = false, lastRet = "";
  for (let i = 1; i <= opts.retryN; i++) {
    const r = await exchange(m, target, copyId);
    const rret = (r.ret || []).join("|");
    lastRet = rret;
    if (rret.includes("SUCCESS")) {
      ok = true;
      log("兑换", `兑换成功! (第${i}次) ${rret}`);
      log("兑换", `结果: ${JSON.stringify(r.data || r).slice(0, 300)}`);
      break;
    }
    // 参数类/业务终态错误不必重试
    if (/ILLEGAL_ARGUMENT|业务来源|活动id不能为空/.test(rret)) {
      log("兑换", `参数错误, 终止重试: ${rret}`);
      break;
    }
    log("兑换", `第${i}次未成功: ${rret}${i < opts.retryN ? ", 重试..." : ""}`);
    await sleep(300);
  }

  const title = ok ? `幸运星 ${label} 兑换成功 🎉` : `幸运星 ${label} 兑换失败`;
  await notify(title, notifyLines.join("\n"));
  if (!ok) log("兑换", `最终失败: ${lastRet}`);
  log(label, `========== 结束 ==========`);
}

// ======================= 主流程 =======================
async function main() {
  const args = process.argv.slice(2);
  const wantValue = (flag) => {
    const i = args.indexOf(flag);
    return i >= 0 && args[i + 1] ? args[i + 1] : null;
  };
  const opts = {
    exchangeTarget: wantValue("--exchange") || process.env.LUCKY_EXCHANGE_ID || null,
    force: args.includes("--force") || process.env.LUCKY_FORCE === "1",
    autoMission: args.includes("--mission"),
    retryN: parseInt(wantValue("--retry") || process.env.LUCKY_RETRY || "5", 10),
  };
  const snapHour = wantValue("--snap") || process.env.LUCKY_SNAP_HOUR || null;
  const snapHourNum = snapHour ? parseInt(snapHour, 10) : null;

  // 到点抢购: 先睡到整点再开始
  if (snapHourNum !== null && !Number.isNaN(snapHourNum)) {
    await waitUntil(snapHourNum);
  }

  const cookies = readCookies();
  log("幸运星", `共 ${cookies.length} 个账号`);

  let hasError = false;
  for (let i = 0; i < cookies.length; i++) {
    try {
      await runAccount(cookies[i], i + 1, opts);
    } catch (e) {
      log(`账号${i + 1}`, `异常: ${e.message}`);
      await notify(`幸运星 账号${i + 1} 异常`, e.message);
      hasError = true;
    }
    // 多账号间间隔, 避免频率限制
    if (i < cookies.length - 1) {
      log("幸运星", `等待 2 秒后执行下一个账号...`);
      await sleep(2000);
    }
  }

  if (hasError) process.exit(1);
}

main().catch(async (e) => {
  log("错误", e.message);
  await notify("幸运星脚本异常", e.message);
  process.exit(1);
});
