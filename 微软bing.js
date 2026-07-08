/**
 * cron: 59 10,20 * * * const $ = new Env("微软浏览器积分");
export MS_COOKIES_1="your_cookies_1"
export MS_REFRESH_TOKEN_1="your_refresh_token_1"
export MS_ALIAS_1="Account 1"
export MS_PROXY_1="proxym:8080"
抓取 https://rewards.bing.com/welcome?rh=F5F34605&ref=rafsrchae 下的cookie即可
 只需要MS_COOKIES_1 即可运行
 */


var _0x4badbc = 14;
const axios = require("axios"),
  moment =
    ((_0x4badbc = "noeifi".split("").reverse().join("")), require("moment"));
let _0x75d;
const notify = require("./sendNotify");
_0x75d = "qphieo".split("").reverse().join("");
let _0x4fbb1f;
const fs = require("fs"),
  path = ((_0x4fbb1f = 9), require("path"));
let exec = require("child_process").exec,
  _0x18965e;
const os = require("os");
_0x18965e = "gofgig".split("").reverse().join("");
var _0x9da68b = 14;
const crypto = require("crypto"),
  AUTH_SERVER = ((_0x9da68b = 7), "https://mr.5886666.xyz"),
  LICENSE_KEY = process.env.LICENSE_KEY;
function generateFallbackMac(s, e, t) {
  (s = "0123456789ABCDEF"),
    "kicdjm"
      .split((t = ""))
      .reverse()
      .join("");
  for (let e = 0; e < 6; e++)
    (t =
      (t += s[Math.floor(16 * Math.random())]) +
      s[Math.floor(16 * Math.random())]),
      e < 5 && (t += ":");
  return t;
}
async function saveFallbackMac(e) {
  try {
    var s = path.join(__dirname, "fallback_mac.json"),
      t = { mac: e, updatedAt: new Date().toISOString() };
    return (
      fs.writeFileSync(s, JSON.stringify(t, null, 2), "utf8"),
      console.log("备用MAC地址已保存到文件"),
      !0
    );
  } catch (e) {
    return (
      console.error(":败失址地CAM用备存保".split("").reverse().join(""), e), !1
    );
  }
}
async function loadFallbackMac() {
  try {
    var e = path.join(__dirname, "fallback_mac.json");
    if (fs.existsSync(e)) {
      var s = JSON.parse(fs.readFileSync(e, "utf8"));
      if (
        s.mac &&
        new RegExp("^([0-9a-f]{2}:){5}[0-9a-f]{2}$", "").test(
          s.mac.toLowerCase()
        )
      )
        return (
          console.log("址地CAM用备载加件文从已".split("").reverse().join("")),
          s.mac.toLowerCase()
        );
    }
    return null;
  } catch (e) {
    return (
      console.error(":败失址地CAM用备取读".split("").reverse().join(""), e),
      null
    );
  }
}
async function getMacAddress() {
  return new Promise(async (a) => {
    try {
      var s = os.networkInterfaces();
      let e = null;
      for (const i of Object.keys(s)) {
        var t = s[i].find(
          (e) =>
            e.family === "4vPI".split("").reverse().join("") &&
            !e.internal &&
            e.mac &&
            "00:00:00:00:00:00" !== e.mac
        );
        if (t) {
          e = t.mac.toLowerCase();
          break;
        }
      }
      if (e) a(e);
      else {
        let e = "";
        switch (process.platform) {
          case "win32":
            e = "getmac /fo csv /nh";
            break;
          case "niwrad".split("").reverse().join(""):
            e = "ifconfig en0 | grep ether";
            break;
          default:
            e = "ip addr | grep ether";
        }
        exec(e, async (s, t) => {
          if (!s && t) {
            let e = "";
            if (
              ("win32" === process.platform
                ? (s = t.match(
                    new RegExp('")+]"^[("'.split("").reverse().join(""), "")
                  )) &&
                  s[1] &&
                  (e = s[1].replace(new RegExp("-", "g"), ":").toLowerCase())
                : (s = t.match(
                    new RegExp("([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})", "")
                  )) &&
                  (e = s[0].replace(new RegExp("-", "g"), ":").toLowerCase()),
              e && new RegExp("^([0-9a-f]{2}:){5}[0-9a-f]{2}$", "").test(e))
            )
              return void a(e);
          }
          t = await loadFallbackMac();
          t ? a(t) : (await saveFallbackMac((s = generateFallbackMac())), a(s));
        });
      }
    } catch (e) {
      console.error(":误错生发时址地CAM取获".split("").reverse().join(""), e);
      var o = await loadFallbackMac();
      o ? a(o) : (await saveFallbackMac((o = generateFallbackMac())), a(o));
    }
  });
}
async function getDeviceInfo() {
  try {
    var e = await getMacAddress();
    return { mac: e, cpuId: e, boardId: e, deviceId: e };
  } catch (e) {
    throw (console.error("获取设备信息失败:", e), e);
  }
}
const verifyLicense = async () => {
    if (!LICENSE_KEY)
      return console.log("未配置授权码，请设置环境变量 LICENSE_KEY"), !1;
    try {
      var s = await getMacAddress(),
        e = Date.now().toString(),
        t = { license: LICENSE_KEY, mac: s },
        a = e + LICENSE_KEY + JSON.stringify(t),
        o = crypto.createHash("652ahs".split("").reverse().join("")),
        i = (o.update(a), o.digest("46esab".split("").reverse().join(""))),
        r =
          (console.log("正在验证授权..."),
          await axios.post(AUTH_SERVER + "/api/verify-license", t, {
            headers: {
              "X-Timestamp": e,
              "X-Signature": i,
              "X-Admin-Key": LICENSE_KEY,
            },
          }));
      return r.data.success
        ? (console.log("授权验证成功！剩余运行次数：" + r.data.remainingRuns),
          !0)
        : (console.log("授权验证失败：" + (r.data.error || "未知错误")), !1);
    } catch (e) {
      if (e.response && e.response.data) {
        s = e.response.data.error || "未知错误";
        switch ((console.log("授权验证失败：" + s), s)) {
          case "授权码无效":
            console.log("请检查授权码是否正确，或联系管理员获取新的授权码");
            break;
          case "期过已码权授".split("").reverse().join(""):
            console.log("授权码已过期，请联系管理员续期");
            break;
          case "制限量数备设大最到达已".split("").reverse().join(""):
            console.log(
              "员理管系联请，制限量数备设大最到达已码权授该"
                .split("")
                .reverse()
                .join("")
            );
            break;
          case "制限数次行运大最到达已".split("").reverse().join(""):
            console.log(
              "员理管系联请，制限数次行运大最到达已码权授该"
                .split("")
                .reverse()
                .join("")
            );
            break;
          case "定绑码权授他其被已备设此".split("").reverse().join(""):
            console.log(
              "码权授的确正用使请，定绑码权授他其被已备设前当"
                .split("")
                .reverse()
                .join("")
            );
            break;
          case "授权码已被禁用":
            console.log(
              "员理管系联请，用禁员理管被已码权授该"
                .split("")
                .reverse()
                .join("")
            );
            break;
          case "无效的请求签名或已过期":
            console.log(
              "员理管系联或接连络网查检请，败失证验求请"
                .split("")
                .reverse()
                .join("")
            );
            break;
          default:
            console.log("请检查网络连接或联系管理员");
        }
      } else
        console.log("授权验证失败：无法连接到授权服务器"),
          console.log(
            "确正否是址地器务服权授认确或接连络网查检请"
              .split("")
              .reverse()
              .join("")
          );
      return !1;
    }
  },
  globalResults = {
    summary: [],
    success: 0,
    failed: 0,
    totalEarned: 0,
    executionDate: new Date(),
  },
  Env = function (e) {
    this.name = e;
  },
  getAccounts = () => {
    const s = [];
    let e = 1;
    for (;;) {
      var t = process.env["MS_COOKIES_" + e],
        a = process.env["MS_REFRESH_TOKEN_" + e],
        o = process.env["MS_ALIAS_" + e] || "账号" + e,
        i = process.env["MS_PROXY_" + e] || "";
      if (!t && !a) break;
      s.push({
        alias: o,
        cookies: t || "",
        refreshToken: a || "",
        proxy: i || "",
      }),
        e++;
    }
    if (0 === s.length)
      try {
        var r,
          n = path.join(__dirname, "accounts.json");
        fs.existsSync(n) &&
          ((r = JSON.parse(
            fs.readFileSync(n, "8ftu".split("").reverse().join(""))
          )),
          "adhfhi".split("").reverse().join(""),
          r.accounts) &&
          Array.isArray(r.accounts) &&
          r.accounts.forEach((e) => {
            e.cookies &&
              e.refreshToken &&
              s.push({
                alias: e.alias || "账号" + (s.length + 1),
                cookies: e.cookies,
                refreshToken: e.refreshToken,
                proxy: e.proxy || "",
              });
          });
      } catch (e) {
        console.error(":败失件文置配号账取读".split("").reverse().join(""), e);
      }
    n =
      process.env.MS_TOKEN_FILE ||
      path.join(
        __dirname,
        "nosj.snekot_hserfer_sm".split("").reverse().join("")
      );
    if (fs.existsSync(n))
      try {
        const c = JSON.parse(fs.readFileSync(n, "utf8"));
        s.forEach((e) => {
          c[e.alias] &&
            c[e.alias].refreshToken &&
            (console.log(`为账号 [${e.alias}] 加载保存的刷新令牌`),
            (e.refreshToken = c[e.alias].refreshToken));
        });
      } catch (e) {
        console.error(
          ":败失牌令新刷的存保取读".split("").reverse().join(""),
          e
        );
      }
    return s;
  };
class MSRewards {
  constructor(e = {}) {
    (this.account = {
      alias: e.alias || "号账认默".split("").reverse().join(""),
      cookies: e.cookies || process.env.MS_COOKIES || "",
      refreshToken: e.refreshToken || process.env.MS_REFRESH_TOKEN || "",
      proxy: e.proxy || process.env.MS_PROXY || "",
      ...e,
    }),
      this.account.proxy
        ? (console.log(
            `[${this.account.alias}] 使用代理: ` + this.account.proxy
          ),
          (this.axiosInstance = axios.create({
            proxy: this.parseProxyString(this.account.proxy),
          })))
        : (this.axiosInstance = axios),
      (this.data = {
        time: {
          task: 3e3,
          pcSearchInterval: 7e4,
          mobileSearchInterval: 13e4,
          hoursNow: new Date().getHours(),
          dateNow: moment().format("DD-MM-YYYY".split("").reverse().join("")),
        },
        auth: {
          code: "https://login.live.com/oauth20_authorize.srf",
          token: "https://login.live.com/oauth20_token.srf",
          clientId: "0000000040170455",
          scope: "service::prod.rewardsplatform.microsoft.com::MBI_SSL",
          redirectUri: "https://login.live.com/oauth20_desktop.srf",
        },
        ua: {
          pc: [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.2478.131",
            "601.5632.0.221/gdE 1.406/irafaS 0.0.0.221/emorhC )okceG ekil ,LMTHK( 51.1.506/tiKbeWelppA )1_4_41 X SO caM letnI ;amonoS( 0.5/allizoM"
              .split("")
              .reverse()
              .join(""),
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.2210.181",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
          ],
          m: [
            "Mozilla/5.0 (Linux; Android 14; 2210132C Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.52 Mobile Safari/537.36 EdgA/125.0.2535.51",
            "Mozilla/5.0 (iPad; CPU OS 16_7_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/120.0.2210.150 Version/16.0 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/123.0.2420.108 Version/18.0 Mobile/15E148 Safari/604.1",
            "56.0242.0.321/AgdE 63.735/irafaS eliboM 04.2136.0.321/emorhC )okceG ekil ,LMTHK( 63.735/tiKbeWelppA )B199G-MS ;31 diordnA ;xuniL( 0.5/allizoM"
              .split("")
              .reverse()
              .join(""),
            "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.44 Mobile Safari/537.36 EdgA/124.0.2478.49",
            "51.1.506/irafaS 841E51/eliboM 45.8742.421/SOigdE 0.71/noisreV )okceG ekil ,LMTHK( 51.1.506/tiKbeWelppA )X SO caM ekil 5_71 SO enohPi UPC ;enohPi( 0.5/allizoM"
              .split("")
              .reverse()
              .join(""),
            "Mozilla/5.0 (Linux; Android 14; Mi 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.40 Mobile Safari/537.36 EdgA/123.0.2420.65",
            "94.8742.0.421/AgdE 63.735/irafaS eliboM 44.7636.0.421/emorhC )okceG ekil ,LMTHK( 63.735/tiKbeWelppA )8 etoN imdeR ;11 diordnA ;xuniL( 0.5/allizoM"
              .split("")
              .reverse()
              .join(""),
            "56.0242.0.321/AgdE 63.735/irafaS eliboM 04.2136.0.321/emorhC )okceG ekil ,LMTHK( 63.735/tiKbeWelppA )B635A-MS GNUSMAS ;31 diordnA ;xuniL( 0.5/allizoM"
              .split("")
              .reverse()
              .join(""),
          ],
        },
        web: 0,
        app: 0,
        api: {
          arr: [
            [
              "hot.eray.cc",
              {
                url: "https://dailyapi.eray.cc/",
                hot: [
                  "obiew".split("").reverse().join(""),
                  "niyuod".split("").reverse().join(""),
                  "udiab".split("").reverse().join(""),
                  "toutiao",
                  "repapeht".split("").reverse().join(""),
                  "qq-news",
                  "netease-news",
                  "uhihz".split("").reverse().join(""),
                ],
              },
            ],
            [
              "hot.baiwumm.com",
              {
                url: "https://hot.baiwumm.com/api/",
                hot: [
                  "weibo",
                  "douyin",
                  "baidu",
                  "toutiao",
                  "thepaper",
                  "qq".split("").reverse().join(""),
                  "esaeten".split("").reverse().join(""),
                  "uhihz".split("").reverse().join(""),
                ],
              },
            ],
            [
              "hot.cnxiaobai.com",
              {
                url: "https://cnxiaobai.com/DailyHotApi/",
                hot: [
                  "weibo",
                  "douyin",
                  "udiab".split("").reverse().join(""),
                  "toutiao",
                  "thepaper",
                  "qq-news",
                  "netease-news",
                  "uhihz".split("").reverse().join(""),
                ],
              },
            ],
            [
              "hot.zhusun.top",
              {
                url: "https://hotapi.zhusun.top/",
                hot: [
                  "obiew".split("").reverse().join(""),
                  "douyin",
                  "baidu",
                  "toutiao",
                  "repapeht".split("").reverse().join(""),
                  "swen-qq".split("").reverse().join(""),
                  "netease-news",
                  "uhihz".split("").reverse().join(""),
                ],
              },
            ],
            [
              "pot.yysmi.toh".split("").reverse().join(""),
              {
                url: "https://api-hot.imsyy.top/",
                hot: [
                  "weibo",
                  "niyuod".split("").reverse().join(""),
                  "baidu",
                  "oaituot".split("").reverse().join(""),
                  "repapeht".split("").reverse().join(""),
                  "qq-news",
                  "netease-news",
                  "zhihu",
                ],
              },
            ],
            [
              "cc.lootnn.toh".split("").reverse().join(""),
              {
                url: "https://hotapi.nntool.cc/",
                hot: [
                  "weibo",
                  "douyin",
                  "udiab".split("").reverse().join(""),
                  "oaituot".split("").reverse().join(""),
                  "repapeht".split("").reverse().join(""),
                  "swen-qq".split("").reverse().join(""),
                  "swen-esaeten".split("").reverse().join(""),
                  "zhihu",
                ],
              },
            ],
          ],
        },
      }),
      (this.task = {
        sign: { times: 0, point: 1, end: 0 },
        read: { times: 0, point: 0, end: 0 },
        promo: { times: 0, token: 0, end: 0, point: 0 },
        search: {
          word: { list: [], index: 0 },
          times: 0,
          progressNow: 0,
          pc: {
            progress: 0,
            max: 60,
            limit: 60,
            lastPoints: 0,
            singlePoints: 0,
          },
          m: {
            progress: 0,
            max: 50,
            limit: 50,
            lastPoints: 0,
            singlePoints: 0,
          },
          index: 0,
          end: 0,
        },
        token: 0,
        startTime: new Date(),
        userInfo: {
          name: "",
          availablePoints: 0,
          lifetimePoints: 0,
          dailyPoints: { current: 0, max: 0 },
          startPoints: 0,
          earnedPoints: 0,
          streakDays: 0,
        },
      }),
      (this.config = {
        app: "true" === process.env.MS_APP,
        span: parseInt(process.env.MS_SPAN || "15"),
        api: process.env.MS_API || "单机模式",
      });
  }
  parseProxyString(e) {
    try {
      var s, t, a, o, i, r, n;
      return e
        ? (s = e.match(
            new RegExp(
              "^(http|https|socks4|socks5):\\/\\/(?:(.+):(.+)@)?([^:]+):(\\d+)$",
              "i"
            )
          ))
          ? ((t = s[1]),
            "hjdnae".split("").reverse().join(""),
            (a = s[2]),
            (o = s[3]),
            (i = s[4]),
            (r = parseInt(s[5])),
            (n = { protocol: t, host: i, port: r }),
            "dnlkpl".split("").reverse().join(""),
            a && o && (n.auth = { username: a, password: o }),
            n)
          : (console.log(`[${this.account.alias}] 代理格式无效: ` + e), null)
        : null;
    } catch (e) {
      return (
        console.log(`[${this.account.alias}] 解析代理字符串出错: ` + e.message),
        null
      );
    }
  }
  getRandomNum(e) {
    return Math.floor(Math.random() * e);
  }
  getScopeRandomNum(e, s) {
    return Math.floor(Math.random() * (s + 1 - e) + e);
  }
  getRandomArr(e) {
    return e.sort(() => Math.random() - 0.5);
  }
  getRandomChineseChar() {
    var e = Math.floor(20992 * Math.random()) + 19968;
    return String.fromCodePoint(e);
  }
  generateRandomChineseStr(e = 6, s = 32) {
    var t = Math.floor(Math.random() * (s - e + 1)) + e;
    let a = "";
    for (let e = 0; e < t; e++) a += this.getRandomChineseChar();
    return a;
  }
  getEstimatedCompletionTime() {
    var e = Math.max(0, this.task.search.pc.max - this.task.search.pc.progress),
      s = Math.max(0, this.task.search.m.max - this.task.search.m.progress),
      e =
        ("jbijdl".split("").reverse().join(""),
        e * this.data.time.pcSearchInterval +
          s * this.data.time.mobileSearchInterval);
    return 0 == e
      ? "成完已".split("").reverse().join("")
      : `约${Math.ceil(e / 6e4)}分钟`;
  }
  printTaskStatus() {
    this.task.userInfo;
    var e = this.task;
    console.log(
      `
[${this.account.alias}] 状态：本次任务 PC搜索上限${
        e.search.pc.max || 60
      }次 移动搜索上限${e.search.m.max || 50}次 预计` +
        this.getEstimatedCompletionTime()
    );
  }
  addToSummary(e = !0) {
    var s = this.task.userInfo;
    e && s.name
      ? (globalResults.success++,
        (globalResults.totalEarned += s.earnedPoints),
        globalResults.summary.push({
          alias: this.account.alias,
          level: s.level || "Level2",
          points: s.availablePoints || 0,
          earned: s.earnedPoints || 0,
          pcSearch:
            `${this.task.search.pc.progress || 0}/` +
            (this.task.search.pc.max || 60),
          mobileSearch:
            `${this.task.search.m.progress || 0}/` +
            (this.task.search.m.max || 50),
          runTime: Math.floor((new Date() - this.task.startTime) / 1e3),
          streakDays: s.streakDays || 0,
          readPoint: this.task.read.point || 0,
          signPoint: this.task.sign.point || 0,
          promoPoint: this.task.promo.point || 0,
        }))
      : globalResults.failed++;
  }
  async pushMsg(e, s, t = !0) {
    var a = `[${this.account.alias}] `;
    console.log(a + e + ": " + s), t && (await notify.sendNotify(a + e, s));
  }
  async beforeStart() {
    var e = new Date(),
      s = e.getFullYear(),
      t = ("0" + (e.getMonth() + 1)).slice(-2),
      a = ("0" + e.getDate()).slice(-2);
    (this.data.time.hoursNow = Number(e.getHours())),
      (this.data.time.dateNow = t + `/${a}/` + s),
      (this.data.time.dateNowNum = Number("" + s + t + a)),
      this.config.api !== "式模机单".split("").reverse().join("") &&
        ((this.data.api.hot = []),
        (e = new Map(this.data.api.arr).get(this.config.api))
          ? ((this.data.api.url = e.url),
            (this.data.api.hot = e.hot),
            console.log(
              `[${this.account.alias}] 使用搜索API: ` + this.config.api
            ))
          : (console.log(
              `[${this.account.alias}] 当前搜索词接口失效！已替换成单机模式！`
            ),
            (this.config.api = "单机模式")));
  }
  async isExpired() {
    try {
      if (this.account.refreshToken) if (1 === (await this.getToken())) return;
      this.task.sign.end++,
        this.task.read.end++,
        await this.pushMsg(
          "微软积分商城App任务🔴",
          "nekoThserfer置设中置配号账多在或NEKOT_HSERFER_SM量变境环置设并取获动手请，效无牌令新刷"
            .split("")
            .reverse()
            .join("")
        );
    } catch (e) {
      throw (console.error(`[${this.account.alias}] 认证过程出错:`, e), e);
    }
  }
  async getToken(e) {
    try {
      var s = new URLSearchParams(),
        t =
          (s.append("client_id", this.data.auth.clientId),
          s.append(
            "nekot_hserfer".split("").reverse().join(""),
            this.account.refreshToken
          ),
          s.append("scope", this.data.auth.scope),
          s.append("grant_type", "NEKOT_HSERFER".split("").reverse().join("")),
          await this.axiosInstance.post(this.data.auth.token, s, {
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
          }));
      if (200 === t.status) {
        var a = t.data;
        if (a.refresh_token && a.access_token)
          return (
            (this.task.token = a.access_token),
            this.account.refreshToken !== a.refresh_token &&
              (console.log(`[${this.account.alias}] 刷新令牌已更新`),
              (this.account.refreshToken = a.refresh_token),
              await this.saveRefreshToken(a.refresh_token)),
            1
          );
      }
      return 0;
    } catch (e) {
      return (
        console.error(`[${this.account.alias}] 获取令牌失败:`, e),
        e.response ? e.response.status : 0
      );
    }
  }
  async saveRefreshToken(s) {
    try {
      var t =
          process.env.MS_TOKEN_FILE ||
          path.join(__dirname, "ms_refresh_tokens.json"),
        a = ("mkleml".split("").reverse().join(""), path.dirname(t));
      fs.existsSync(a) || fs.mkdirSync(a, { recursive: !0 });
      let e = {};
      if (fs.existsSync(t))
        try {
          var o = fs.readFileSync(t, "utf8");
          e = JSON.parse(o);
        } catch (e) {
          console.log(`[${this.account.alias}] 读取令牌文件失败，将创建新文件`);
        }
      return (
        (e[this.account.alias] = {
          refreshToken: s,
          updatedAt: new Date().toISOString(),
        }),
        fs.writeFileSync(
          t,
          JSON.stringify(e, null, 2),
          "8ftu".split("").reverse().join("")
        ),
        console.log(`[${this.account.alias}] 成功保存刷新令牌到文件`),
        !0
      );
    } catch (e) {
      return console.error(`[${this.account.alias}] 保存刷新令牌失败:`, e), !1;
    }
  }
  async getRewardsInfo() {
    try {
      var e = {};
      this.account.cookies && (e.Cookie = this.account.cookies);
      let s = 0;
      for (; s < 3; )
        try {
          var t,
            a,
            o = await this.axiosInstance.get(
              "https://rewards.bing.com/api/getuserinfo?type=1",
              {
                headers: e,
                timeout: 3e4,
                validateStatus: function (e) {
                  return 200 <= e && e < 500;
                },
              }
            );
          if (200 === o.status)
            return (t = o.data).dashboard
              ? (t.dashboard.userStatus &&
                  (this.task.userInfo.availablePoints,
                  0 === this.task.userInfo.startPoints &&
                    (this.task.userInfo.startPoints =
                      t.dashboard.userStatus.availablePoints || 0),
                  t.dashboard.userStatus.levelInfo &&
                    (this.task.userInfo.level =
                      t.dashboard.userStatus.levelInfo.activeLevel?.replace(
                        "Level",
                        ""
                      ) || "2"),
                  t.dashboard.userStatus.levelInfo &&
                    (this.task.userInfo.streakDays =
                      t.dashboard.userStatus.levelInfo
                        .levelUpActivityDailySetStreakDays || 0),
                  (a = [
                    t.dashboard.userStatus.name,
                    t.dashboard.userStatus.accountName,
                    t.dashboard.userStatus.profile?.name,
                    t.dashboard.userStatus.profile?.accountName,
                    t.dashboard.userStatus.levelInfo?.levelName,
                    t.dashboard.userStatus.levelInfo?.currentLevelName,
                    t.dashboard.profile?.name,
                    t.dashboard.profile?.accountName,
                  ]),
                  (this.task.userInfo.name =
                    a.find(
                      (e) =>
                        e && typeof e === "gnirts".split("").reverse().join("")
                    ) || "户用知未".split("").reverse().join("")),
                  (this.task.userInfo.availablePoints =
                    t.dashboard.userStatus.availablePoints || 0),
                  (this.task.userInfo.lifetimePoints =
                    t.dashboard.userStatus.lifetimePoints || 0),
                  (this.task.userInfo.earnedPoints =
                    this.task.userInfo.availablePoints -
                    this.task.userInfo.startPoints),
                  t.dashboard.userStatus?.counters?.dailyPoint) &&
                  t.dashboard.userStatus.counters.dailyPoint[0] &&
                  ((this.task.userInfo.dailyPoints.current =
                    t.dashboard.userStatus.counters.dailyPoint[0]
                      .pointProgress || 0),
                  (this.task.userInfo.dailyPoints.max =
                    t.dashboard.userStatus.counters.dailyPoint[0]
                      .pointProgressMax || 0)),
                0 === this.task.search.pc.progress &&
                  0 === this.task.search.m.progress &&
                  this.printTaskStatus(),
                t.dashboard)
              : (this.task.sign.end++,
                this.task.read.end++,
                this.task.promo.end++,
                this.task.search.end++,
                0 === this.data.web &&
                  (await this.pushMsg(
                    "All任务🔴",
                    "账号状态失效，请检查Microsoft Cookies或重新登录！"
                  )),
                this.data.web++,
                0);
          console.log(
            `[${this.account.alias}] 微软积分商城Web任务🟡微软Rewards信息获取出错（状态码：${o.status}），正在重试...`
          ),
            ++s < 3 && (await new Promise((e) => setTimeout(e, 5e3)));
        } catch (e) {
          if (
            (e.code !== "TUODEMITE".split("").reverse().join("") &&
              e.code !== "DETROBANNOCE".split("").reverse().join("")) ||
            !(++s < 3)
          )
            throw e;
          await new Promise((e) => setTimeout(e, 5e3));
        }
      return (
        console.log(`[${this.account.alias}] 获取Rewards信息失败，已重试3次`), 0
      );
    } catch (e) {
      return (
        console.log(
          `[${this.account.alias}] 获取Rewards信息失败: ` + e.message
        ),
        0
      );
    }
  }
  async getTopKeyword() {
    let e = this.generateRandomChineseStr();
    if (this.config.api !== "式模机单".split("").reverse().join(""))
      try {
        if (
          this.task.search.word.index < 1 ||
          this.task.search.word.list.length < 1
        ) {
          var s = this.getRandomNum(this.data.api.hot.length),
            t = this.data.api.hot[s],
            a = await this.axiosInstance.get(this.data.api.url + t, {
              timeout: 9999,
            });
          if (200 === a.status) {
            var o = a.data;
            if (200 === o.code) {
              (this.task.search.word.index = 1),
                (this.task.search.word.list = []);
              for (let e = 0; e < o.data.length; e++)
                this.task.search.word.list.push(o.data[e].title);
              (this.task.search.word.list = this.getRandomArr(
                this.task.search.word.list
              )),
                (e = this.task.search.word.list[this.task.search.word.index]);
            } else
              console.log(
                `[${this.account.alias}] 微软积分商城必应搜索🟣当前搜索词接口服务异常（状态码：${o.code}），已使用随机汉字组句`
              );
          } else
            console.log(
              `[${this.account.alias}] 微软积分商城必应搜索🟣当前搜索词接口获取失败（状态码：${a.status}），已使用随机汉字组句`
            );
        } else
          this.task.search.word.index++,
            this.task.search.word.index >
              this.task.search.word.list.length - 1 &&
              (this.task.search.word.index = 0),
            (e = this.task.search.word.list[this.task.search.word.index]);
      } catch (e) {
        console.log(
          `[${this.account.alias}] 微软积分商城必应搜索🟣当前搜索词接口获取异常，已使用随机汉字组句`
        ),
          console.error(e);
      }
    return e;
  }
  async taskSearch() {
    if (0 < this.task.search.end) return !0;
    var e = await this.getRewardsInfo();
    if (0 === e) return !1;
    if (
      (e.userStatus.counters.pcSearch &&
        ((this.task.search.pc.progress =
          e.userStatus.counters.pcSearch[0].pointProgress),
        (this.task.search.pc.max =
          e.userStatus.counters.pcSearch[0].pointProgressMax),
        e.userStatus.counters.dailyPoint) &&
        e.userStatus.counters.dailyPoint[0] &&
        e.userStatus.counters.dailyPoint[0].pointProgress >=
          e.userStatus.counters.dailyPoint[0].pointProgressMax &&
        (console.log(
          `[${this.account.alias}] PC端已达到每日积分上限，停止PC端搜索`
        ),
        (this.task.search.pc.max = this.task.search.pc.progress)),
      e.userStatus.counters.mobileSearch
        ? ((this.task.search.m.progress =
            e.userStatus.counters.mobileSearch[0].pointProgress),
          (this.task.search.m.max =
            e.userStatus.counters.mobileSearch[0].pointProgressMax),
          e.userStatus.counters.dailyPoint &&
            e.userStatus.counters.dailyPoint[0] &&
            e.userStatus.counters.dailyPoint[0].pointProgress >=
              e.userStatus.counters.dailyPoint[0].pointProgressMax &&
            (console.log(
              `[${this.account.alias}] 移动端已达到每日积分上限，停止移动端搜索`
            ),
            (this.task.search.m.max = this.task.search.m.progress)))
        : (this.task.search.m.max = 0),
      this.task.search.pc.progress >= this.task.search.pc.max &&
        this.task.search.m.progress >= this.task.search.m.max)
    )
      return this.task.search.end++, await this.getRewardsInfo(), !0;
    {
      let e = !1;
      var t = await this.getTopKeyword(),
        a =
          "https://bing.com/search?" +
          `q=${encodeURIComponent(t)}&qs=ds&form=QBLH`,
        o = {};
      if (
        (this.account.cookies && (o.Cookie = this.account.cookies),
        this.task.search.pc.progress < this.task.search.pc.max)
      ) {
        await this.getRewardsInfo();
        var i = this.task.userInfo.availablePoints,
          r = this.data.ua.pc[this.getRandomNum(this.data.ua.pc.length)];
        let s = 0;
        for (; s < 3; )
          try {
            await this.axiosInstance.get(a, {
              headers: { "User-Agent": r, ...o },
              timeout: 3e4,
              validateStatus: function (e) {
                return 200 <= e && e < 500;
              },
            }),
              (e = !0),
              this.task.search.index++,
              await this.getRewardsInfo();
            var n = this.task.userInfo.availablePoints,
              c = Math.max(0, n - i);
            this.task.search.pc.progress++,
              console.log(
                `[${this.account.alias}] PC端："${t}"（第${this.task.search.pc.progress}次搜索）本次获取积分：${c} 进度：${this.task.search.pc.progress}/` +
                  this.task.search.pc.max
              );
            const d = this.getScopeRandomNum(
              this.data.time.pcSearchInterval - 1e4,
              this.data.time.pcSearchInterval + 1e4
            );
            console.log(
              `[${this.account.alias}] PC搜索完成，等待${Math.floor(
                d / 1e3
              )}秒后继续...`
            ),
              await new Promise((e) => setTimeout(e, d));
            break;
          } catch (e) {
            3 === ++s
              ? (console.error(
                  `[${this.account.alias}] PC搜索失败(已重试3次):`,
                  e.message
                ),
                await new Promise((e) => setTimeout(e, 6e4)))
              : (console.log(
                  `[${this.account.alias}] PC搜索失败，${s}秒后重试...`
                ),
                await new Promise((e) => setTimeout(e, 1e3 * s)));
          }
      }
      if (this.task.search.m.progress < this.task.search.m.max) {
        await this.getRewardsInfo();
        var l = this.task.userInfo.availablePoints,
          h = this.data.ua.m[this.getRandomNum(this.data.ua.m.length)];
        let s = 0;
        for (; s < 3; )
          try {
            await this.axiosInstance.get(a, {
              headers: { "User-Agent": h, ...o },
              timeout: 3e4,
              validateStatus: function (e) {
                return 200 <= e && e < 500;
              },
            }),
              (e = !0),
              this.task.search.index++,
              await this.getRewardsInfo();
            var p = this.task.userInfo.availablePoints,
              u = Math.max(0, p - l);
            this.task.search.m.progress++,
              console.log(
                `[${this.account.alias}] 手机端："${t}"（第${this.task.search.m.progress}次搜索）本次获取积分：${u} 进度：${this.task.search.m.progress}/` +
                  this.task.search.m.max
              );
            const m = this.getScopeRandomNum(
              this.data.time.mobileSearchInterval - 1e4,
              this.data.time.mobileSearchInterval + 1e4
            );
            console.log(
              `[${this.account.alias}] 移动端搜索完成，等待${Math.floor(
                m / 1e3
              )}秒后继续...`
            ),
              await new Promise((e) => setTimeout(e, m));
            break;
          } catch (e) {
            3 === ++s
              ? (console.error(
                  `[${this.account.alias}] 移动搜索失败(已重试3次):`,
                  e.message
                ),
                await new Promise((e) => setTimeout(e, 6e4)))
              : (console.log(
                  `[${this.account.alias}] 移动搜索失败，${s}秒后重试...`
                ),
                await new Promise((e) => setTimeout(e, 1e3 * s)));
          }
      }
      return e
        ? this.taskSearch()
        : (this.task.search.end++, await this.getRewardsInfo(), !0);
    }
  }
  async getRewardsToken() {
    try {
      var e,
        s = {},
        t =
          (this.account.cookies && (s.Cookie = this.account.cookies),
          await this.axiosInstance.get(
            "moc.gnib.sdrawer//:sptth".split("").reverse().join(""),
            { headers: s }
          ));
      return 200 === t.status
        ? (e = t.data
            .replace(new RegExp("\\s", "g"), "")
            .match(
              new RegExp(
                '>/\\")?*.("=eulav"neddih"=epyt"nekoTnoitacifireVtseuqeR'
                  .split("")
                  .reverse()
                  .join(""),
                ""
              )
            )) && e[1]
          ? e[1]
          : (console.log(
              `[${this.account.alias}] 获取RewardsToken失败：未找到验证令牌`
            ),
            0)
        : (console.log(
            `[${this.account.alias}] 获取RewardsToken出错（状态码：${t.status}）`
          ),
          0);
    } catch (e) {
      return (
        console.error(`[${this.account.alias}] 获取RewardsToken出错:`, e), 0
      );
    }
  }
  async taskPromo() {
    if (0 < this.task.promo.end) return !0;
    if (this.data.time.hoursNow < 12)
      return (
        this.task.promo.end++,
        console.log(
          `[${this.account.alias}] 活动推广任务：在早上12点前暂不执行活动任务，避免任务刷新问题`
        ),
        !0
      );
    if (2 < this.task.promo.times) return this.task.promo.end++, !0;
    try {
      var e = await this.getRewardsInfo();
      if (0 === e) return !1;
      var s = [];
      if (e.dailySetPromotions && e.dailySetPromotions[this.data.time.dateNow])
        for (const o of e.dailySetPromotions[this.data.time.dateNow])
          !1 === o.complete &&
            s.push({
              offerId: o.offerId,
              hash: o.hash,
              type: "每日活动",
              points: o.points || 0,
            });
      if (e.morePromotions)
        for (const i of e.morePromotions)
          !1 === i.complete &&
            s.push({
              offerId: i.offerId,
              hash: i.hash,
              type: "更多活动",
              points: i.points || 0,
            });
      if (
        ((this.task.promo.token = await this.getRewardsToken()),
        0 === this.task.promo.token)
      )
        this.task.promo.times++,
          await new Promise((e) => setTimeout(e, this.data.time.task));
      else {
        if (
          e.streakProtectionPromo &&
          "False" === e.streakProtectionPromo.streakProtectionStatus
        ) {
          console.log(`[${this.account.alias}] 正在开启连续签到保护...`);
          try {
            var t = {
              "Content-Type": "application/x-www-form-urlencoded",
              Referer: "https://rewards.bing.com/",
            };
            "eipafm".split("").reverse().join("");
            this.account.cookies && (t.Cookie = this.account.cookies),
              await this.axiosInstance.post(
                "https://rewards.bing.com/api/togglestreakasync",
                "isOn=true&activityAmount=1&form=&__RequestVerificationToken=" +
                  this.task.promo.token,
                { headers: t }
              ),
              console.log(`[${this.account.alias}] 连续签到保护开启成功`);
          } catch (e) {
            console.error(
              `[${this.account.alias}] 开启连续签到保护失败: 应该是第一次登录，明天再次运行就OK了`
            );
          }
        }
        if (0 === s.length) return this.task.promo.end++, !0;
        console.log(
          `[${this.account.alias}] 发现${s.length}个未完成活动，开始自动完成...`
        ),
          (this.task.promo.point = 0);
        for (const r of s) {
          console.log(
            `[${this.account.alias}] 正在完成${r.type}: ` + r.offerId
          );
          try {
            var a = {
              "Content-Type": "application/x-www-form-urlencoded",
              Referer: "https://rewards.bing.com/",
            };
            this.account.cookies && (a.Cookie = this.account.cookies),
              await this.axiosInstance.post(
                "ytivitcatroper/ipa/moc.gnib.sdrawer//:sptth"
                  .split("")
                  .reverse()
                  .join(""),
                `id=${r.offerId}&hash=${r.hash}&__RequestVerificationToken=` +
                  this.task.promo.token,
                { headers: a }
              ),
              (this.task.promo.point += r.points),
              await new Promise((e) =>
                setTimeout(e, this.getScopeRandomNum(1e3, 3e3))
              );
          } catch (e) {
            e.response &&
              e.response.data &&
              e.response.data.error &&
              e.response.data.error.description &&
              e.response.data.error.description.includes("already") &&
              console.log(`[${this.account.alias}] 活动${r.offerId}已完成`);
          }
        }
        this.task.promo.times++;
      }
      return this.taskPromo();
    } catch (e) {
      return (
        console.error(`[${this.account.alias}] 活动推广任务出错:`, e),
        this.task.promo.times++,
        await new Promise((e) => setTimeout(e, this.data.time.task)),
        this.taskPromo()
      );
    }
  }
  async getReadPro() {
    let s = 0;
    for (; s < 3; )
      try {
        if (!this.task.token)
          return (
            console.log(
              `[${this.account.alias}] 获取阅读任务进度失败：无访问令牌`
            ),
            { max: 1, progress: 0 }
          );
        var e = await this.axiosInstance.get(
          "https://prod.rewardsplatform.microsoft.com/dapi/me?channel=SAAndroid&options=613",
          {
            headers: { authorization: "Bearer " + this.task.token },
            timeout: 3e4,
            validateStatus: function (e) {
              return 200 <= e && e < 500;
            },
          }
        );
        if (200 === e.status) {
          var t = e.data;
          if (t.response && t.response.promotions)
            for (const a of t.response.promotions)
              if (
                a.attributes &&
                a.attributes.offerid ===
                  "stniop03_3elcitradaer_SUNE".split("").reverse().join("")
              )
                return {
                  max: Number(a.attributes.max) || 3,
                  progress: Number(a.attributes.progress) || 0,
                };
          return { max: 1, progress: 0 };
        }
        if (
          (console.log(
            `[${this.account.alias}] 获取阅读任务进度失败（状态码：${e.status}）`
          ),
          !(++s < 3))
        )
          return { max: 1, progress: 0 };
        console.log(`[${this.account.alias}] 将在5秒后重试...`),
          await new Promise((e) => setTimeout(e, 5e3));
      } catch (e) {
        if (
          ("ETIMEDOUT" === e.code || "ECONNABORTED" === e.code) &&
          (console.log(
            `[${this.account.alias}] 获取阅读任务进度超时，正在重试...`
          ),
          ++s < 3)
        )
          console.log(`[${this.account.alias}] 将在5秒后重试...`),
            await new Promise((e) => setTimeout(e, 5e3));
        else {
          if (
            (console.error(
              `[${this.account.alias}] 获取阅读任务进度出错:`,
              e.message
            ),
            !(++s < 3))
          )
            return { max: 1, progress: 0 };
          console.log(`[${this.account.alias}] 将在5秒后重试...`),
            await new Promise((e) => setTimeout(e, 5e3));
        }
      }
    return (
      console.log(`[${this.account.alias}] 获取阅读任务进度失败，已重试3次`),
      { max: 1, progress: 0 }
    );
  }
  async taskRead() {
    if (0 < this.task.read.end) return !0;
    if (this.data.time.hoursNow < 12)
      return (
        this.task.read.end++,
        console.log(
          `[${this.account.alias}] 文章阅读任务：在早上12点前暂不执行阅读任务，避免任务刷新问题`
        ),
        !0
      );
    if (2 < this.task.read.times) return this.task.read.end++, !0;
    if (!this.task.token)
      return (
        this.task.read.end++,
        console.log(
          `[${this.account.alias}] 文章阅读任务：无有效访问令牌，跳过任务`
        ),
        !0
      );
    try {
      var e = await this.getReadPro();
      if (
        (e.progress > this.task.read.point
          ? ((this.task.read.times = 0), (this.task.read.point = e.progress))
          : this.task.read.times++,
        e.max <= e.progress)
      )
        return (
          this.task.read.end++,
          await this.pushMsg(
            "文章阅读🟢",
            `哇！${this.account.alias}好棒！文章阅读完成了！`,
            !1
          ),
          !0
        );
      console.log(
        `[${this.account.alias}] 正在执行文章阅读任务: ${e.progress}/` + e.max
      );
      try {
        var s = await this.axiosInstance.post(
          "https://prod.rewardsplatform.microsoft.com/dapi/me/activities",
          {
            amount: 1,
            country: "cn",
            id: "",
            type: 101,
            attributes: { offerid: "ENUS_readarticle3_30points" },
          },
          {
            headers: {
              "Content-Type": "application/json",
              authorization: "Bearer " + this.task.token,
            },
          }
        );
        200 === s.status
          ? console.log(`[${this.account.alias}] 文章阅读提交成功`)
          : console.log(
              `[${this.account.alias}] 文章阅读提交失败（状态码：${s.status}）`
            );
      } catch (e) {
        console.error(`[${this.account.alias}] 文章阅读提交出错:`, e);
      }
      const t = this.getScopeRandomNum(5e3, 1e4);
      return (
        console.log(
          `[${this.account.alias}] 文章阅读操作完成，等待${Math.floor(
            t / 1e3
          )}秒后继续...`
        ),
        await new Promise((e) => setTimeout(e, t)),
        this.taskRead()
      );
    } catch (e) {
      return e.response &&
        e.response.data &&
        e.response.data.error &&
        e.response.data.error.description &&
        e.response.data.error.description.includes("already")
        ? (console.log(`[${this.account.alias}] 文章阅读任务已完成`),
          this.task.read.end++,
          await this.pushMsg(
            "文章阅读🟢",
            `哇！${this.account.alias}好棒！文章阅读完成了！`,
            !1
          ),
          !0)
        : (this.task.read.times++,
          await new Promise((e) => setTimeout(e, this.data.time.task)),
          this.taskRead());
    }
  }
  async taskSign() {
    if (0 < this.task.sign.end) return !0;
    if (this.data.time.hoursNow < 12)
      return (
        this.task.sign.end++,
        console.log(
          `[${this.account.alias}] App签到任务：在早上12点前暂不执行签到任务，避免任务刷新问题`
        ),
        !0
      );
    if (2 < this.task.sign.times) return this.task.sign.end++, !0;
    if (!this.task.token)
      return (
        this.task.sign.end++,
        console.log(
          `[${this.account.alias}] App签到任务：无有效访问令牌，跳过任务`
        ),
        !0
      );
    try {
      console.log(`[${this.account.alias}] 正在执行App签到任务...`);
      var e,
        s,
        t = this.data.time.dateNowNum,
        a = await this.axiosInstance.post(
          "https://prod.rewardsplatform.microsoft.com/dapi/me/activities",
          {
            amount: 1,
            attributes: {
              offerid: "Gamification_Sapphire_DailyCheckIn",
              date: t,
              signIn: !1,
              timezoneOffset: "08:00:00",
            },
            id: "",
            type: 101,
            country: "cn",
            risk_context: {},
            channel: "SAAndroid",
          },
          {
            headers: {
              "Content-Type": "application/json",
              authorization: "Bearer " + this.task.token,
            },
          }
        );
      return 200 === a.status
        ? ((e = a.data).response && e.response.activity && e.response.activity.p
            ? ((s = e.response.activity.p),
              (this.task.sign.point = s),
              console.log(`[${this.account.alias}] App签到成功，获得${s}积分`),
              this.task.sign.end++,
              await this.pushMsg(
                "App签到🟢",
                `哇！${this.account.alias}好棒！App签到完成了！获得${s}积分`,
                !1
              ))
            : (console.log(
                `[${this.account.alias}] App签到响应异常，可能已经签到过`
              ),
              (this.task.sign.point = 0),
              this.task.sign.end++,
              await this.pushMsg(
                "\udfe2\ud83d到签ppA".split("").reverse().join(""),
                this.account.alias + "今日已签到，无需重复签到",
                !1
              )),
          !0)
        : (console.log(
            `[${this.account.alias}] App签到请求失败（状态码：${a.status}）`
          ),
          this.task.sign.times++,
          await new Promise((e) => setTimeout(e, this.data.time.task)),
          this.taskSign());
    } catch (e) {
      return e.response &&
        e.response.data &&
        e.response.data.error &&
        e.response.data.error.description &&
        e.response.data.error.description.includes("already")
        ? (console.log(`[${this.account.alias}] App今日已签到，无需重复签到`),
          (this.task.sign.point = 0),
          this.task.sign.end++,
          await this.pushMsg(
            "App签到🟢",
            this.account.alias + "今日已签到，无需重复签到",
            !1
          ),
          !0)
        : (this.task.sign.times++,
          await new Promise((e) => setTimeout(e, this.data.time.task)),
          this.taskSign());
    }
  }
  async start() {
    try {
      console.log(`
[${this.account.alias}] 开始任务`),
        await this.beforeStart(),
        this.config.app
          ? await this.isExpired()
          : (this.task.sign.end++, this.task.read.end++),
        await Promise.all([
          this.taskPromo(),
          this.taskSign(),
          this.taskRead(),
          this.taskSearch(),
        ]),
        console.log(`[${this.account.alias}] 任务完成`),
        this.printTaskStatus(),
        this.addToSummary(!0);
    } catch (e) {
      console.error(`[${this.account.alias}] 任务失败:`, e),
        await this.pushMsg(
          "城商分积软微".split("").reverse().join(""),
          "任务执行失败: " + e.message
        ),
        this.addToSummary(!1);
    }
  }
}
(async () => {
  /*(await verifyLicense()) ||
    (console.log("出退序程，败失证验权授".split("").reverse().join("")),
    process.exit(1));*/
    //
  var s = getAccounts(),
    t = process.env.MS_PARALLEL === "eurt".split("").reverse().join("");
  if (
    (console.log(
      "账号执行模式: " +
        (t ? "行执行并".split("").reverse().join("") : "串行执行")
    ),
    s && 0 !== s.length)
  )
    if (t) {
      console.log(`检测到${s.length}个账号配置，开始并行执行所有账号`);
      t = s.map((e) => {
        return (
          console.log("准备执行账号: " + e.alias), new MSRewards(e).start()
        );
      });
      await Promise.all(t);
    } else {
      console.log(`检测到${s.length}个账号配置，开始顺序执行`);
      for (let e = 0; e < s.length; e++) {
        var a = s[e];
        if (
          (console.log(`开始执行第${e + 1}个账号: ` + a.alias),
          await new MSRewards(a).start(),
          e < s.length - 1)
        ) {
          const i = Math.floor(1e4 * Math.random()) + 5e3;
          console.log(`账号任务完成，等待${i / 1e3}秒后执行下一个账号...`),
            await new Promise((e) => setTimeout(e, i));
        }
      }
    }
  else {
    console.log(
      "行执号账认默用使，置配号账到测检未".split("").reverse().join("")
    );
    t = path.join(__dirname, "default_account.json");
    let e = { alias: "默认账号", cookies: "", refreshToken: "", proxy: "" };
    if (fs.existsSync(t))
      try {
        var o = JSON.parse(fs.readFileSync(t, "utf8"));
        o.cookies &&
          o.refreshToken &&
          (e = {
            alias: o.alias || "号账认默".split("").reverse().join(""),
            cookies: o.cookies,
            refreshToken: o.refreshToken,
            proxy: o.proxy || "",
          });
      } catch (e) {
        console.error("读取默认账号配置失败:", e);
      }
    await new MSRewards(e).start();
  }
  if (
    (console.log("所有账号任务执行完毕！"),
    0 < globalResults.summary.length || 0 < globalResults.failed)
  ) {
    t = moment(globalResults.executionDate).format("YYYY-MM-DD HH:mm:ss");
    let e = `微软积分商城任务汇总
`;
    "lmcccp".split("").reverse().join(""),
      (e =
        (e =
          (e =
            (e += `📅 执行时间: ${t}

`) +
            `✅ 成功用户: ${globalResults.success}个
`) +
          `❌ 失败用户: ${globalResults.failed}个
`) +
        `🔢 总获取积分: ${globalResults.totalEarned}分

` +
        `========== 详情 ==========

`);
    for (const r of globalResults.summary)
      e =
        (e =
          (e =
            (e =
              (e =
                (e =
                  (e =
                    (e =
                      (e +=
                        r.alias +
                        `
`) +
                      `👑 用户等级: ${r.level}
`) +
                    `💰 当前积分: ${r.points} 分
`) +
                  `⬆️ 本次获得: ${r.earned} 分
`) +
                `💻 PC搜索: ${r.pcSearch}
`) +
              `📱 手机搜索: ${r.mobileSearch}
`) +
            `📖 文章阅读: ${r.readPoint || 0}分
`) +
          `📱 App签到: ${r.signPoint || 0}分
`) +
        `🎯 活动推广: ${r.promoPoint || 0}分

` +
        `------------------------

`;
    await notify.sendNotify(
      "总汇务任城商分积软微".split("").reverse().join(""),
      e
    );
  }
})();
