require('./yyb.js'); // 自动同步 yyb_go 存活账号
/*
================================================================================
脚本名称: 飞鹤|北纬47度好物（原星妈优选）
脚本作者: Leiyiyan
创建日期: 2024-10-08
最后更新: 2024-12-03
================================================================================

【功能说明】
飞鹤|北纬47度好物小程序 每日签到、自动完成任务

【使用方法】
方式A（推荐，标准模式）：yyb_go 自动拉取存活账号 + yyb.js 自动获取 code
   - 服务端地址（参考霖久智服，按优先级取值，全都没有才回退本地默认）：
       WX_SERVER → YYB_SERVER → WECHAT_SERVER → YINGYONGBAO_SERVER → WX_SERVICE → http://127.0.0.1:18273
   - 只要 yyb.js 可用，脚本即自动从 yyb_go 拉取全部存活账号执行

方式B（兜底）：直接填 token
   - 环境变量名：xmtoken
   - 变量值：每行一个 token（支持多账号）

说明：yyb_go 自动拉取账号与 xmtoken 会合并后统一去重，重复账号只执行一次。

环境变量格式（多账号分隔符任选）：换行 / & / @

【获取Token】
方法1：抓包获取
- 抓包地址：https://www.feihevip.com/api/starMember/getMemberInfo
- 抓取请求头中的 token 字段

方法2：使用抓包工具（推荐使用 Quantumult X 或 Surge）
[Script]
http-response ^https?:\/\/www\.feihevip\.com\/api\/starMember\/getMemberInfo script-path=xmyx.js, requires-body=true, timeout=60, tag=飞鹤北纬47度好物小程序获取Cookie

[MITM]
hostname = www.feihevip.com

【定时任务】
建议每天早上0点30分执行
cron: 20 17,05 * * *

【图标】
https://raw.githubusercontent.com/leiyiyan/resource/main/icons/xmyx.png

================================================================================
⚠️【免责声明】
================================================================================
1、此脚本仅用于学习研究，不保证其合法性、准确性、有效性，请根据情况自行判断，
   本人对此不承担任何保证责任。
2、由于此脚本仅用于学习研究，您必须在下载后 24 小时内将所有内容从您的计算机
   或手机或任何存储设备中完全删除，若违反规定引起任何事件本人对此均不负责。
3、请勿将此脚本用于任何商业或非法目的，若违反规定请自行对此负责。
4、此脚本涉及应用与本人无关，本人对因此引起的任何隐私泄漏或其他后果不承担
   任何责任。
5、本人对任何脚本引发的问题概不负责，包括但不限于由脚本错误引起的任何损失
   和损害。
6、如果任何单位或个人认为此脚本可能涉嫌侵犯其权利，应及时通知并提供身份证明，
   所有权证明，我们将在收到认证文件确认后删除此脚本。
7、所有直接或间接使用、查看此脚本的人均应该仔细阅读此声明。本人保留随时更改
   或补充此声明的权利。一旦您使用或复制了此脚本，即视为您已接受此免责声明。
================================================================================
*/


const $ = new Env("飞鹤北纬47度好物小程序");
const ckName = "xmtoken";

//-------------------- 一般不动变量区域 -------------------------------------
$.appid = "wx4205ec55b793245e";
const Notify = 1;//0为关闭通知,1为打开通知,默认为1
// 优先使用青龙面板自带的 sendNotify，如果不存在则使用本地的
const notify = $.isNode() ? (() => {
  try {
    // 尝试加载青龙面板的 sendNotify
    return require('../sendNotify');
  } catch (e) {
    try {
      // 如果青龙的不存在，尝试加载本地的
      return require('../sendNotify');
    } catch (err) {
      console.log('⚠️ sendNotify 加载失败，通知功能将不可用');
      return null;
    }
  }
})() : '';
// 初始化 got 库
if ($.isNode()) {
  try {
    $.initGotEnv();
  } catch (e) {
    console.log('⚠️ got 库初始化失败，部分功能可能受限');
  }
}

// ========== 引入 yyb.js 标准模块（牛子 + 应用宝 双协议） ==========
// 自动适配脚本所在目录（根目录或 wxapp 子目录）
function __loadGetCode() {
  if (typeof require === 'undefined') return null; // 非 Node 环境（QuantumultX/Surge）无需加载
  const candidates = ['./yyb.js', './wxapp/yyb.js'];
  for (const p of candidates) {
    try { return require(p); } catch (e) {}
  }
  try { return require(require('path').join(__dirname, 'yyb.js')); } catch (e) {}
  return null;
}
const getCodeModule = __loadGetCode();
const getSingleCode = getCodeModule ? getCodeModule.getSingleCode : null;
if (!getCodeModule) {
  console.log('⚠️ yyb.js 模块加载失败，yyb_go 自动拉取将不可用（请确认 yyb.js 与本脚本同目录）');
}

let envSplitor = ["\n", "&", "@"]; //多账号分隔符，优先使用换行符
// 从环境变量读取 token，支持多账号
// 环境变量名: xmtoken
// 格式: 多个token用@或换行分隔，例如: token1@token2@token3
var userCookie = ($.isNode() ? process.env[ckName] : $.getdata(ckName)) || '';
let userList = [];
let userIdx = 0;
let userCount = 0;
// 调试
$.is_debug = ($.isNode() ? process.env.IS_DEDUG : $.getdata('is_debug')) || 'false';
// 为多用户准备的通知数组
$.notifyList = [];
// 为通知准备的空数组
$.notifyMsg = [];

//---------------------- 自定义变量区域 -----------------------------------
const appid = 'xmyx'
const appKey = 'TwUQ01lKS1Km5zlV2f7amsZc5EQYkTbv'

//---------------------- 脚本入口函数 -----------------------------------
async function main() {
  try {
    $.log('\n' + '='.repeat(50));
    $.log('🎯 开始执行任务');
    $.log('='.repeat(50) + '\n');
    
    // 仅调用一次 getTaskList
    let taskList = [];
    if (userList.length > 0) {
      taskList = await userList[0].getTaskList();
      $.log(`📋 获取到 ${taskList.length} 个任务\n`);
    }
    
    for (let user of userList) {
      $.log(`\n${'─'.repeat(50)}`);
      $.log(`📱 账号 ${user.index} 开始执行`);
      $.log('─'.repeat(50));
      
      // 先获取用户信息
      const userInfoBefore = await user.getUserInfo();
      if (userInfoBefore) {
        const { userName, score, level, mobile } = userInfoBefore;
        user.userName = userName;
        user.avatar = userInfoBefore.avatar;
        user.mobile = mobile;
        $.log(`�  用户: ${userName || '未知'}${mobile ? ` (${mobile})` : ''}`);
        $.log(`💰 当前积分: ${score} | 等级: ${level}`);
      }
      
      const flag = await user.getSignInfo();
      
      if (user.ckStatus) {
        // 完成任务
        if (taskList.length > 0) {
          $.log(`\n📝 开始执行任务列表...`);
          for(let task of taskList) {
            await user.tofinish(task.taskName, task.taskType);
            await $.wait(1000 * (task.completeTaskDuration?task.completeTaskDuration:3))
            await user.completeTask(task.taskName, task.taskType);
            await $.wait(user.getRandomTime());
          }
        }
        
        // 查询最终用户信息
        const userInfoAfter = await user.getUserInfo();
        if (userInfoAfter) {
          const { score, level, userName, avatar, mobile } = userInfoAfter;
          user.avatar = avatar;
          user.userName = userName;
          user.mobile = mobile;
          await user.refreshToken(user.token);
          
          const earnedPoints = userInfoBefore ? score - userInfoBefore.score : 0;
          $.log(`\n✨ 任务完成`);
          $.log(`� 用户:分 ${userName}${mobile ? ` (${mobile})` : ''}`);
          $.log(`💰 最终积分: ${score} ${earnedPoints > 0 ? `(+${earnedPoints})` : ''}`);
          $.log(`⭐ 等级: ${level}`);
          
          $.title = `今日任务已全部完成`;
          // 通知消息包含手机号/fullName
          const displayName = mobile ? `${userName} (${mobile})` : userName;
          DoubleLog(`「${displayName}」积分: ${score}${earnedPoints > 0 ? ` (+${earnedPoints})` : ''}, 等级: ${level}`);
        }
      } else {
        //将ck过期消息存入消息数组
        $.notifyMsg.push(`❌账号${user.userName || user.index} >> Token已失效`)
      }
      
      //账号通知
      $.notifyList.push({ "id": user.index, "avatar": user.avatar, "message": $.notifyMsg });
      //清空数组
      $.notifyMsg = [];
    }
    
    $.log(`\n${'='.repeat(50)}`);
    $.log(`✅ 所有账号执行完成`);
    $.log('='.repeat(50) + '\n');
  } catch (e) {
    $.log(`⛔️ main run error => ${e}`);
    throw new Error(`⛔️ main run error => ${e}`);
  }
}
class UserInfo {
  constructor(user) {
    //默认属性
    this.index = ++userIdx;
    this.token = user.token || user;
    this.userId = user.userId;
    this.userName = user.userName;
    this.avatar = user.avatar;
    this.ckStatus = true;
    this.doFlag = { "true": "✅", "false": "⛔️" };
    
    //请求封装
    this.baseUrl = ``;
    this.host = "https://www.feihevip.com/api";
    this.headers = {
      "Host": "www.feihevip.com",
      "token": this.token,
      "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.48(0x1800302b) NetType/4G Language/zh_CN",
      "Referer": "https://servicewechat.com/wx4205ec55b793245e/366/page-frame.html",
      "fhAppid": appid,
      "source": 1
    }
    
    this.getRandomTime = () => randomInt(1e3, 3e3);
    this.fetch = async (o) => {
      try {
        if (typeof o === 'string') o = { url: o };
        if (o?.url?.startsWith("/")) o.url = this.host + o.url
        const res = await Request({ ...o, headers: o.headers || this.headers, url: o.url || this.baseUrl })
        // debug(res, o?.url?.replace(/\/+$/, '').substring(o?.url?.lastIndexOf('/') + 1));
        if (res?.code == 40001) throw new Error(res?.message || `用户需要去登录`);
        return res;
      } catch (e) {
        this.ckStatus = false;
        $.log(`⛔️ 请求发起失败！${e}`);
      }
    }
  }
  
  // 签到
  async getSignInfo() {
    try {
      const { fhNonceStr, fhTimestamp, fhSign } = getSignature();
      const opts = {
        url: '/member/signin/getSignInfo',
        type: "get",
        params: {
          signType: 1
        },
        headers: Object.assign({}, this.headers, {
          fhNonceStr,
          fhTimestamp,
          fhSign
        })
      }
      const res = await this.fetch(opts);
      if (!res?.data) {
        $.log(`⚠️ 签到信息获取失败`);
        return;
      }
      const { signStatus } = res.data;
      if (signStatus === 1) {
        $.log(`✅ 今日已签到`);
      }

      if (signStatus === 2) {
        await this.signin();
      }
    } catch (e) {
      this.ckStatus = false;
      $.log(`⛔️ 签到失败: ${e}`);
    }
  }

  // 签到
  async signin() {
    try {
      const { fhNonceStr, fhTimestamp, fhSign } = getSignature();
      const res = await this.fetch({
        url: '/member/signin/sign',
        type: 'post',
        params: {},
        headers: Object.assign({}, this.headers, {
          fhNonceStr,
          fhTimestamp,
          fhSign
        })
      });
      if (res.code === '200') {
        $.log(`✅ 签到成功`);
      } else {
        $.log(`✅ 签到失败：${res.msg}`);
      }
    } catch (e) {
      this.ckStatus = false;
      $.log(`⛔️ 执行任务今日签到失败! ${e}`);
    }
  }
// 获取任务列表
 async getTaskList() {
  try {
    const { fhNonceStr, fhTimestamp, fhSign } = getSignature();
    const opts = {
      url: '/member/signin/getTaskList',
      type: "get",
      headers: Object.assign({}, this.headers, {
        fhNonceStr,
        fhTimestamp,
        fhSign
      })
    }
    const res = await this.fetch(opts);
    debug(res, `获取任务列表`);
    if (res?.code == '200' && res?.data) {
      return res.data;
    } else {
      $.log(`⛔️ 获取任务列表失败! ${res?.msg}\n`);
      return [];
    }
  } catch (e) {
    this.ckStatus = false;
    $.log(`⛔️ 获取任务列表失败! ${e}`);
    return [];
  }
}
  // 执行任务
  async tofinish(taskName, taskType) {
    try {
      const { fhNonceStr, fhTimestamp, fhSign } = getSignature();
      const opts = {
        url: '/member/signin/tofinish',
        type: "get",
        params: {
          taskType
        },
        headers: Object.assign({}, this.headers, {
          fhNonceStr,
          fhTimestamp,
          fhSign
        })
      }
      const res = await this.fetch(opts);
      debug(res, `执行任务: ${taskName}`)
      if (res?.code == '200') {
        $.log(`  🚀 开始: ${taskName}`);
      } else {
        $.log(`  ⚠️ ${taskName}: ${res?.msg}`);
      }
    } catch (e) {
      this.ckStatus = false;
      $.log(`  ⛔️ ${taskName} 失败: ${e}`);
    }
  }
  
  // 完成任务
  async completeTask(taskName, taskType) {
    try {
      const { fhNonceStr, fhTimestamp, fhSign } = getSignature();
      const opts = {
        url: '/member/signin/completeTask',
        type: "get",
        params: {
          taskType
        },
        headers: Object.assign({}, this.headers, {
          fhNonceStr,
          fhTimestamp,
          fhSign
        })
      }
      const res = await this.fetch(opts);
      debug(res, `完成任务: ${taskName}`)
      if(res?.code == '200') {
        if(res?.data) {
          const point = res?.data?.awardSendPoints;
          $.log(`  ✅ 完成: ${taskName} +${point}积分`);
        }else{
          $.log(`  ℹ️ ${taskName} 已完成`);
        }
      }else{
        $.log(`  ⛔️ ${taskName} 失败: ${res?.msg}`);
      }
    } catch (e) {
      this.ckStatus = false;
      $.log(`  ⛔️ ${taskName} 异常: ${e}`);
    }
  }
  // 获取用户信息
  async getUserInfo() {
    try {
      const { fhNonceStr, fhTimestamp, fhSign } = getSignature({});
      const opts = {
        url: '/starMember/getMemberInfo',
        type: "post",
        dataType: "json",
        headers: Object.assign({}, this.headers, {
          fhNonceStr,
          fhTimestamp,
          fhSign
        }),
        body: {}
      }
      const res = await this.fetch(opts);
      debug(res, `查询用户信息`)
      
      if(res?.code == '200' && res?.data) {
        // 积分
        const score = res?.data?.memberPoints?.scoreValue;
        // 等级
        const level = res?.data?.memberGrade?.currentGrade;
        // 用户名
        const userName = res?.data?.baseInfo?.nickName;
        // 头像
        const avatar = res?.data?.baseInfo?.headImgUrl;
        
        // 手机号（从多个可能的字段中获取，优先使用看起来像手机号的）
        let mobile = '';
        const possibleFields = [
          res?.data?.baseInfo?.mobile,
          res?.data?.baseInfo?.fullName,
          res?.data?.mobile
        ];
        
        // 找到第一个看起来像手机号的字段（11位数字）
        for (const field of possibleFields) {
          if (field && /^1\d{10}$/.test(field)) {
            mobile = field;
            break;
          }
        }
        
        // 如果没找到手机号格式的，就用 fullName 或 crmId
        if (!mobile) {
          mobile = res?.data?.baseInfo?.fullName || res?.data?.crmId || '';
        }
        
        return { score, level, userName, avatar, mobile };
      }else{
        $.log(`⛔️ 查询用户信息失败! ${res?.msg}\n`);
      }
    } catch (e) {
      this.ckStatus = false;
      $.log(`⛔️ 查询用户信息失败! ${e}`);
    }
  }
  // 刷新token
  async refreshToken(token) {
    try {
      const { fhNonceStr, fhTimestamp, fhSign } = getSignature2();
      const options = {
        url: `https://mom.feihe.com/program/token/refreshToken`,
        type: "get",
        headers: {
          "Host": "mom.feihe.com",
          "token": token,
          "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.48(0x1800302b) NetType/4G Language/zh_CN",
          "Referer": "https://servicewechat.com/wx4205ec55b793245e/366/page-frame.html",
          "fhAppid": 'xmh',
          "source": 1,
          fhNonceStr,
          fhTimestamp,
          fhSign
        }
      };
      //post方法
      let result = await Request(options);
      let refreshToken = result?.data;
      
      if (refreshToken) {
        // 更新当前用户的token
        this.token = refreshToken;
        this.headers.token = refreshToken;
        $.log(`🎉 刷新 token 成功`)
        debug(result, '获取token');
      } else {
        $.log(`⚠️ 刷新 token 返回为空`)
      }
    } catch (e) {
      $.log(`⛔️ 刷新 Token 失败: ${e}`)
    }
  }
}
async function getCookie() {
  if ($request && $request.method === 'OPTIONS') return;

  const header = ObjectKeys2LowerCase($request.headers);
  const token = header.token;
  const body = $.toObj($response.body);
  if (!(body?.data)) {
    $.msg($.name, `❌获取Cookie失败!`, "")
    return;
  }
  // 积分
  const score = body?.data?.memberPoints?.scoreValue;
  // ID
  const unionId = body?.data?.unionId;
  // 用户名
  const userName = body?.data?.baseInfo?.nickName;
  // 头像
  const avatar = body?.data?.baseInfo?.headImgUrl;

  const newData = {
    "userId": unionId,
    "avatar": avatar,
    "token": token,
    "userName": userName,
  }

  userCookie = userCookie ? JSON.parse(userCookie) : [];
  const index = userCookie.findIndex(e => e.userId == newData.userId);

  userCookie[index] ? userCookie[index] = newData : userCookie.push(newData);

  $.setjson(userCookie, ckName);
  $.msg($.name, `🎉${newData.userName}更新token成功!`, ``);
}
//自动生成token
async function getWxToken(code) {
  try {
    const { fhNonceStr, fhTimestamp, fhSign } = getSignature({code});
    const options = {
      url: `https://www.feihevip.com/api/wechat/auth/miniAssets`,
      type: "post",
      dataType: "json",
      headers: {
        "Host": "www.feihevip.com",
        "token": '',
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.48(0x1800302b) NetType/4G Language/zh_CN",
        "Referer": "https://servicewechat.com/wx4205ec55b793245e/366/page-frame.html",
        "fhAppid": appid,
        "source": 1,
        fhNonceStr,
        fhTimestamp,
        fhSign
      },
      body: {
        code
      }
    };
    //post方法
    let result = await Request(options);
    let token = result?.data?.token;
    debug(result, '获取token');
    return token;
  } catch (e) {
    $.log(`❌getWxToken run error => ${e}`)
  }
}

// 服务端地址：参考霖久智服的环境变量模式，按优先级取值，全都没有才回退本地默认
function getServerUrl() {
  return (
    process.env.WX_SERVER ||
    process.env.YYB_SERVER ||
    process.env.WECHAT_SERVER ||
    process.env.YINGYONGBAO_SERVER ||
    process.env.WX_SERVICE ||
    'http://127.0.0.1:18273'
  ).replace(/\/+$/, '');
}

//检查 yyb_go 存活账号（自动拉取，返回 token 数组，供入口统一去重）
async function checkCodeServer(appid) {
  if (!getSingleCode) {
    $.log(`❌ yyb.js 模块加载失败，无法自动拉取账号`);
    return [];
  }
  // 从 yyb_go 拉取全部存活账号
  let rawList = [];
  try {
    const client = new YYBClient();
    $.log(`[yyb] 服务端地址: ${client.serverUrl}`);
    const online = await client.getOnlineAccounts();
    if (online && online.length) {
      rawList = online
        .map(acc => {
          const id = acc.openid || acc.wxid || String(acc.id || '');
          return id ? id.trim() : '';
        })
        .filter(Boolean);
      $.log(`✅ 从 yyb 服务拉取到 ${rawList.length} 个存活账号`);
    } else {
      $.log(`[yyb] yyb_go 无存活账号（可能全部离线或 hasSession 失效）`);
    }
  } catch (e) {
    $.log(`[yyb] 拉取账号列表失败: ${e.message || e}`);
  }
  if (!rawList.length) {
    $.log(`❌ yyb_go 无存活账号`);
    return [];
  }
  // 逐个获取 code → token（token 缓存：有效期内复用，避免每次运行都取 code 规避微信限流）
  const tokens = [];
  for (const identifier of rawList) {
    const cached = getCachedToken('feihe', identifier, { maxAgeMs: 6 * 3600 * 1000 });
    if (cached && cached.token) {
      $.log(`✅ ${identifier} 命中token缓存，跳过取code`);
      tokens.push(cached.token);
      continue;
    }
    try {
      const code = await getSingleCode(appid, identifier);
      if (!code) {
        $.log(`❌获取code失败: ${identifier}`);
        continue;
      }
      const token = await getWxToken(code);
      if (!token) {
        $.log(`❌获取token失败: ${identifier}`);
        continue;
      }
      const newToken = await refreshTokenStandalone(token);
      if (!newToken) {
        $.log(`❌刷新token失败: ${identifier}`);
        continue;
      }
      saveCachedToken('fh', identifier, { token: newToken });
      tokens.push(newToken);
    } catch (e) {
      $.log(`❌获取code失败: ${identifier} => ${e.message || e}`);
    }
  }
  return tokens;
}

// 独立 refreshToken（供 checkCodeServer 调用，换取长期 token）
async function refreshTokenStandalone(token) {
  try {
    const { fhNonceStr, fhTimestamp, fhSign } = getSignature2();
    const options = {
      url: `https://mom.feihe.com/program/token/refreshToken`,
      type: "get",
      headers: {
        "Host": "mom.feihe.com",
        "token": token,
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.48(0x1800302b) NetType/4G Language/zh_CN",
        "Referer": "https://servicewechat.com/wx4205ec55b793245e/366/page-frame.html",
        "fhAppid": 'xmh',
        "source": 1,
        fhNonceStr,
        fhTimestamp,
        fhSign
      }
    };
    let result = await Request(options);
    let refreshToken = result?.data;
    return refreshToken || null;
  } catch (e) {
    $.log(`⛔️ 刷新 Token 失败: ${e}`)
    return null;
  }
}
// 解析 xmtoken 环境变量，返回 token 数组（支持 JSON 数组 / 换行 & @ 分隔）
function parseXmToken(raw) {
  if (!raw) return [];
  let usersToAdd = [];
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        usersToAdd = parsed;
      } else {
        usersToAdd = [parsed];
      }
    } catch (e) {
      const separator = envSplitor.find(s => raw.includes(s)) || envSplitor[0];
      const tokens = raw.split(separator).map(t => t.trim()).filter(Boolean);
      usersToAdd = tokens.map(token => ({ token }));
    }
  } else if (Array.isArray(raw)) {
    usersToAdd = raw;
  } else {
    usersToAdd = [raw];
  }
  return usersToAdd
    .map(u => String((u && u.token) || u || '').trim())
    .filter(Boolean);
}
//请求二次封装
async function Request(o) {
  if (typeof o === 'string') o = { url: o };
  try {
    if (!o?.url) throw new Error('[发送请求] 缺少 url 参数');
    // type => 因为env中使用method处理post的特殊请求(put/delete/patch), 所以这里使用type
    let { url: u, type, headers = {}, body: b, params, dataType = 'form', resultType = 'data' } = o;
    // post请求需要处理params参数(get不需要, env已经处理)
    const method = type ? type?.toLowerCase() : ('body' in o ? 'post' : 'get');
    const url = u.concat(method === 'post' ? '?' + $.queryStr(params) : '');

    const timeout = o.timeout ? ($.isSurge() ? o.timeout / 1e3 : o.timeout) : 1e4
    // 根据jsonType处理headers
    if (dataType === 'json') headers['Content-Type'] = 'application/json;charset=UTF-8';
    // post请求处理body
    const body = b && dataType == 'form' ? $.queryStr(b) : $.toStr(b);
    const request = { ...o, ...(o?.opts ? o.opts : {}), url, headers, ...(method === 'post' && { body }), ...(method === 'get' && params && { params }), timeout: timeout }
    const httpPromise = $.http[method.toLowerCase()](request)
      .then(response => resultType == 'data' ? ($.toObj(response.body) || response.body) : ($.toObj(response) || response))
      .catch(err => $.log(`❌请求发起失败！原因为：${err}`));
    // 使用Promise.race来强行加入超时处理
    return Promise.race([
      new Promise((_, e) => setTimeout(() => e('当前请求已超时'), timeout)),
      httpPromise
    ]);
  } catch (e) {
    console.log(`❌请求发起失败！原因为：${e}`);
  }
};
//生成随机数
function randomInt(n, r) {
  return Math.round(Math.random() * (r - n) + n)
};
//控制台打印
function DoubleLog(data) {
  if (data && $.isNode()) {
    console.log(`${data}`);
    $.notifyMsg.push(`${data}`)
  } else if (data) {
    console.log(`${data}`);
    $.notifyMsg.push(`${data}`)
  }
};
//调试
function debug(t, l = 'debug') {
  if ($.is_debug === 'true') {
    $.log(`\n-----------${l}------------\n`);
    $.log(typeof t == "string" ? t : $.toStr(t) || `debug error => t=${t}`);
    $.log(`\n-----------${l}------------\n`)
  }
};
//对多账号通知进行兼容
async function SendMsgList(l) {
  await Promise.allSettled(l?.map(u => SendMsg(u.message.join('\n'), u.avatar)));
};
//账号通知
async function SendMsg(n, o) {
  n && (0 < Notify ? $.isNode() ? await notify.sendNotify($.name, n) : $.msg($.name, $.title || "", n, {
    "media-url": o
  }) : console.log(n))
};
//转换为小写
function ObjectKeys2LowerCase(obj) { return Object.fromEntries(Object.entries(obj).map(([k, v]) => [k.toLowerCase(), v])) };

// 获取签名
function getSignature(data) {
  const json = data ? JSON.stringify(data) : ''
  const fhNonceStr = getFhNonceStr({ length: 16 })
  const fhTimestamp = getTimestamp()
  const signString = `fhAppid${appid}fhNonceStr${fhNonceStr}fhTimestamp${fhTimestamp}${json}${appKey}`
  // debug(signString + '->' + md5(signString).toUpperCase(), '签名字符串')
  return {
    fhNonceStr,
    fhTimestamp,
    fhSign: md5(signString).toUpperCase()
  }
}
function getSignature2() {
  const fhNonceStr = getFhNonceStr({ length: 16 })
  const fhTimestamp = getTimestamp()
  const signString = `fhAppidxmhfhNonceStr${fhNonceStr}fhTimestamp${fhTimestamp}98d9fe9b613a479dbcb111ca261e3ce1`
  // debug(signString + '->' + md5(signString).toUpperCase(), '签名字符串')
  return {
    fhNonceStr,
    fhTimestamp,
    fhSign: md5(signString).toUpperCase()
  }
}
// 获取10位时间戳
function getTimestamp() {
  return +String(Date.now()).slice(0, 10)
}
// 获取随机字符串
function getFhNonceStr(t) { var e, r, n = "", o = (t = function (t) { return t || (t = {}), { length: t.length || 8, numeric: "boolean" != typeof t.numeric || t.numeric, letters: "boolean" != typeof t.letters || t.letters, special: "boolean" == typeof t.special && t.special, exclude: Array.isArray(t.exclude) ? t.exclude : [] } }(t)).length; t.exclude; var i = function (t) { var e = ""; t.numeric && (e += "0123456789"), t.letters && (e += "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"), t.special && (e += "!$%^&*()_+|~-=`{}[]:;<>?,./"); for (var r = 0; r <= t.exclude.length; r++)e = e.replace(t.exclude[r], ""); return e }(t); for (e = 1; e <= o; e++)n += i.substring(r = Math.floor(Math.random() * i.length), r + 1); return n }

//---------------------- 主程序执行入口 -----------------------------------
!(async () => {
  if (typeof $request != "undefined") {
    await getCookie();
  } else {
    // yyb_go 自动拉取存活账号 + xmtoken 合并后统一去重
    const allTokens = [];
    // 1. yyb_go 自动拉取存活账号 → token
    if (getSingleCode) {
      const yybTokens = await checkCodeServer($.appid); // 返回 token 数组
      allTokens.push(...yybTokens);
    }
    // 2. xmtoken 环境变量
    if (userCookie) {
      const xmTokens = parseXmToken(userCookie);
      allTokens.push(...xmTokens);
    }
    // 3. 合并后统一去重（按 token）
    const seen = new Set();
    const finalTokens = [];
    for (const t of allTokens) {
      const token = String(t || '').trim();
      if (!token) continue;
      if (seen.has(token)) {
        $.log(`⚠️ 去重跳过重复账号: ${token.slice(0, 8)}...`);
        continue;
      }
      seen.add(token);
      finalTokens.push(token);
    }
    if (finalTokens.length === 0) {
      throw new Error(`❌未检测到 yyb_go 存活账号 / xmtoken 环境变量，请先配置`);
    }
    userList = finalTokens.map(t => new UserInfo({ token: t }));
    $.log(`✅ 合计待执行账号: ${userList.length} 个（yyb_go 自动拉取 + xmtoken，已去重）\n`);
    if (userList.length > 0) await main();
  }
})()
  .catch(e => $.notifyMsg.push(e.message || e))
  .finally(async () => {
    // 新增：获取随机古诗词
    let poetry = await getRandomPoetry();
    
    // 合并所有通知消息
    let finalMessage = [poetry]; // 将诗词放在开头
    let avatars = [];
    
    // 处理账号通知
    for (const user of $.notifyList) {
      if (user.message.length > 0) {
        finalMessage.push(`📱 账号${user.id}\n${user.message.join('\n')}`);
        avatars.push(user.avatar);
      }
    }
    
    // 添加错误通知
    if ($.notifyMsg.length > 0) {
      finalMessage.push(`❌ 错误信息：\n${$.notifyMsg.join('\n')}`);
    }

    if (finalMessage.length > 0) {
      // 合并消息并发送
      const combinedMessage = finalMessage.join('\n\n──────────────\n\n');
      const firstValidAvatar = avatars.find(avatar => avatar) || '';
      
      await SendMsg(combinedMessage, firstValidAvatar);
    }
    
    $.done({ ok: 1 });
  });

// 新增：获取随机古诗词函数
async function getRandomPoetry() {
  try {
    const url = 'https://v2.jinrishici.com/sentence';
    const res = await Request({
      url,
      headers: {
        'X-User-Token': '+SBGb0hF88lM7xdBcWe4t4jQCMeBXBzJ' // 示例token，建议申请自己的
      }
    });
    
    if (res?.data?.content) {
      return `📜 ${res.data.content}\n   —— ${res.data.origin.author}《${res.data.origin.title}》`;
    }
  } catch (e) {
    $.log('获取诗词失败，使用默认句子');
  }
  
  // 备用默认句子
  const defaultPoems = [
    '及时当勉励，岁月不待人。——陶渊明《杂诗》',
    '会当凌绝顶，一览众山小。——杜甫《望岳》',
    '长风破浪会有时，直挂云帆济沧海。——李白《行路难》'
  ];
  return `📜 ${defaultPoems[Math.floor(Math.random() * defaultPoems.length)]}`;
}
/** ---------------------------------固定不动区域----------------------------------------- */
// prettier-ignore
//From chavyleung's Env.js
function Env(t, e) { class s { constructor(t) { this.env = t } send(t, e = "GET") { t = "string" == typeof t ? { url: t } : t; let s = this.get; return "POST" === e && (s = this.post), new Promise(((e, r) => { s.call(this, t, ((t, s, a) => { t ? r(t) : e(s) })) })) } get(t) { return this.send.call(this.env, t) } post(t) { return this.send.call(this.env, t, "POST") } } return new class { constructor(t, e) { this.name = t, this.http = new s(this), this.data = null, this.dataFile = "box.dat", this.logs = [], this.isMute = !1, this.isNeedRewrite = !1, this.logSeparator = "\n", this.encoding = "utf-8", this.startTime = (new Date).getTime(), Object.assign(this, e), this.log("", `🔔${this.name}, 开始!`) } getEnv() { return "undefined" != typeof $environment && $environment["surge-version"] ? "Surge" : "undefined" != typeof $environment && $environment["stash-version"] ? "Stash" : "undefined" != typeof module && module.exports ? "Node.js" : "undefined" != typeof $task ? "Quantumult X" : "undefined" != typeof $loon ? "Loon" : "undefined" != typeof $rocket ? "Shadowrocket" : void 0 } isNode() { return "Node.js" === this.getEnv() } isQuanX() { return "Quantumult X" === this.getEnv() } isSurge() { return "Surge" === this.getEnv() } isLoon() { return "Loon" === this.getEnv() } isShadowrocket() { return "Shadowrocket" === this.getEnv() } isStash() { return "Stash" === this.getEnv() } toObj(t, e = null) { try { return JSON.parse(t) } catch { return e } } toStr(t, e = null) { try { return JSON.stringify(t) } catch { return e } } getjson(t, e) { let s = e; if (this.getdata(t)) try { s = JSON.parse(this.getdata(t)) } catch { } return s } setjson(t, e) { try { return this.setdata(JSON.stringify(t), e) } catch { return !1 } } getScript(t) { return new Promise((e => { this.get({ url: t }, ((t, s, r) => e(r))) })) } runScript(t, e) { return new Promise((s => { let r = this.getdata("@chavy_boxjs_userCfgs.httpapi"); r = r ? r.replace(/\n/g, "").trim() : r; let a = this.getdata("@chavy_boxjs_userCfgs.httpapi_timeout"); a = a ? 1 * a : 20, a = e && e.timeout ? e.timeout : a; const [i, o] = r.split("@"), n = { url: `http://${o}/v1/scripting/evaluate`, body: { script_text: t, mock_type: "cron", timeout: a }, headers: { "X-Key": i, Accept: "*/*" }, timeout: a }; this.post(n, ((t, e, r) => s(r))) })).catch((t => this.logErr(t))) } loaddata() { if (!this.isNode()) return {}; { this.fs = this.fs ? this.fs : require("fs"), this.path = this.path ? this.path : require("path"); const t = this.path.resolve(this.dataFile), e = this.path.resolve(process.cwd(), this.dataFile), s = this.fs.existsSync(t), r = !s && this.fs.existsSync(e); if (!s && !r) return {}; { const r = s ? t : e; try { return JSON.parse(this.fs.readFileSync(r)) } catch (t) { return {} } } } } writedata() { if (this.isNode()) { this.fs = this.fs ? this.fs : require("fs"), this.path = this.path ? this.path : require("path"); const t = this.path.resolve(this.dataFile), e = this.path.resolve(process.cwd(), this.dataFile), s = this.fs.existsSync(t), r = !s && this.fs.existsSync(e), a = JSON.stringify(this.data); s ? this.fs.writeFileSync(t, a) : r ? this.fs.writeFileSync(e, a) : this.fs.writeFileSync(t, a) } } lodash_get(t, e, s = void 0) { const r = e.replace(/\[(\d+)\]/g, ".$1").split("."); let a = t; for (const t of r) if (a = Object(a)[t], void 0 === a) return s; return a } lodash_set(t, e, s) { return Object(t) !== t || (Array.isArray(e) || (e = e.toString().match(/[^.[\]]+/g) || []), e.slice(0, -1).reduce(((t, s, r) => Object(t[s]) === t[s] ? t[s] : t[s] = Math.abs(e[r + 1]) >> 0 == +e[r + 1] ? [] : {}), t)[e[e.length - 1]] = s), t } getdata(t) { let e = this.getval(t); if (/^@/.test(t)) { const [, s, r] = /^@(.*?)\.(.*?)$/.exec(t), a = s ? this.getval(s) : ""; if (a) try { const t = JSON.parse(a); e = t ? this.lodash_get(t, r, "") : e } catch (t) { e = "" } } return e } setdata(t, e) { let s = !1; if (/^@/.test(e)) { const [, r, a] = /^@(.*?)\.(.*?)$/.exec(e), i = this.getval(r), o = r ? "null" === i ? null : i || "{}" : "{}"; try { const e = JSON.parse(o); this.lodash_set(e, a, t), s = this.setval(JSON.stringify(e), r) } catch (e) { const i = {}; this.lodash_set(i, a, t), s = this.setval(JSON.stringify(i), r) } } else s = this.setval(t, e); return s } getval(t) { switch (this.getEnv()) { case "Surge": case "Loon": case "Stash": case "Shadowrocket": return $persistentStore.read(t); case "Quantumult X": return $prefs.valueForKey(t); case "Node.js": return this.data = this.loaddata(), this.data[t]; default: return this.data && this.data[t] || null } } setval(t, e) { switch (this.getEnv()) { case "Surge": case "Loon": case "Stash": case "Shadowrocket": return $persistentStore.write(t, e); case "Quantumult X": return $prefs.setValueForKey(t, e); case "Node.js": return this.data = this.loaddata(), this.data[e] = t, this.writedata(), !0; default: return this.data && this.data[e] || null } } initGotEnv(t) { this.got = this.got ? this.got : require("got"), this.cktough = this.cktough ? this.cktough : require("tough-cookie"), this.ckjar = this.ckjar ? this.ckjar : new this.cktough.CookieJar, t && (t.headers = t.headers ? t.headers : {}, void 0 === t.headers.Cookie && void 0 === t.cookieJar && (t.cookieJar = this.ckjar)) } get(t, e = (() => { })) { switch (t.headers && (delete t.headers["Content-Type"], delete t.headers["Content-Length"], delete t.headers["content-type"], delete t.headers["content-length"]), t.params && (t.url += "?" + this.queryStr(t.params)), void 0 === t.followRedirect || t.followRedirect || ((this.isSurge() || this.isLoon()) && (t["auto-redirect"] = !1), this.isQuanX() && (t.opts ? t.opts.redirection = !1 : t.opts = { redirection: !1 })), this.getEnv()) { case "Surge": case "Loon": case "Stash": case "Shadowrocket": default: this.isSurge() && this.isNeedRewrite && (t.headers = t.headers || {}, Object.assign(t.headers, { "X-Surge-Skip-Scripting": !1 })), $httpClient.get(t, ((t, s, r) => { !t && s && (s.body = r, s.statusCode = s.status ? s.status : s.statusCode, s.status = s.statusCode), e(t, s, r) })); break; case "Quantumult X": this.isNeedRewrite && (t.opts = t.opts || {}, Object.assign(t.opts, { hints: !1 })), $task.fetch(t).then((t => { const { statusCode: s, statusCode: r, headers: a, body: i, bodyBytes: o } = t; e(null, { status: s, statusCode: r, headers: a, body: i, bodyBytes: o }, i, o) }), (t => e(t && t.error || "UndefinedError"))); break; case "Node.js": let s = require("iconv-lite"); this.initGotEnv(t), this.got(t).on("redirect", ((t, e) => { try { if (t.headers["set-cookie"]) { const s = t.headers["set-cookie"].map(this.cktough.Cookie.parse).toString(); s && this.ckjar.setCookieSync(s, null), e.cookieJar = this.ckjar } } catch (t) { this.logErr(t) } })).then((t => { const { statusCode: r, statusCode: a, headers: i, rawBody: o } = t, n = s.decode(o, this.encoding); e(null, { status: r, statusCode: a, headers: i, rawBody: o, body: n }, n) }), (t => { const { message: r, response: a } = t; e(r, a, a && s.decode(a.rawBody, this.encoding)) })) } } post(t, e = (() => { })) { const s = t.method ? t.method.toLocaleLowerCase() : "post"; switch (t.body && t.headers && !t.headers["Content-Type"] && !t.headers["content-type"] && (t.headers["content-type"] = "application/x-www-form-urlencoded"), t.headers && (delete t.headers["Content-Length"], delete t.headers["content-length"]), void 0 === t.followRedirect || t.followRedirect || ((this.isSurge() || this.isLoon()) && (t["auto-redirect"] = !1), this.isQuanX() && (t.opts ? t.opts.redirection = !1 : t.opts = { redirection: !1 })), this.getEnv()) { case "Surge": case "Loon": case "Stash": case "Shadowrocket": default: this.isSurge() && this.isNeedRewrite && (t.headers = t.headers || {}, Object.assign(t.headers, { "X-Surge-Skip-Scripting": !1 })), $httpClient[s](t, ((t, s, r) => { !t && s && (s.body = r, s.statusCode = s.status ? s.status : s.statusCode, s.status = s.statusCode), e(t, s, r) })); break; case "Quantumult X": t.method = s, this.isNeedRewrite && (t.opts = t.opts || {}, Object.assign(t.opts, { hints: !1 })), $task.fetch(t).then((t => { const { statusCode: s, statusCode: r, headers: a, body: i, bodyBytes: o } = t; e(null, { status: s, statusCode: r, headers: a, body: i, bodyBytes: o }, i, o) }), (t => e(t && t.error || "UndefinedError"))); break; case "Node.js": let r = require("iconv-lite"); this.initGotEnv(t); const { url: a, ...i } = t; this.got[s](a, i).then((t => { const { statusCode: s, statusCode: a, headers: i, rawBody: o } = t, n = r.decode(o, this.encoding); e(null, { status: s, statusCode: a, headers: i, rawBody: o, body: n }, n) }), (t => { const { message: s, response: a } = t; e(s, a, a && r.decode(a.rawBody, this.encoding)) })) } } time(t, e = null) { const s = e ? new Date(e) : new Date; let r = { "M+": s.getMonth() + 1, "d+": s.getDate(), "H+": s.getHours(), "m+": s.getMinutes(), "s+": s.getSeconds(), "q+": Math.floor((s.getMonth() + 3) / 3), S: s.getMilliseconds() }; /(y+)/.test(t) && (t = t.replace(RegExp.$1, (s.getFullYear() + "").substr(4 - RegExp.$1.length))); for (let e in r) new RegExp("(" + e + ")").test(t) && (t = t.replace(RegExp.$1, 1 == RegExp.$1.length ? r[e] : ("00" + r[e]).substr(("" + r[e]).length))); return t } queryStr(t) { let e = ""; for (const s in t) { let r = t[s]; null != r && "" !== r && ("object" == typeof r && (r = JSON.stringify(r)), e += `${s}=${r}&`) } return e = e.substring(0, e.length - 1), e } msg(e = t, s = "", r = "", a) { const i = t => { switch (typeof t) { case void 0: return t; case "string": switch (this.getEnv()) { case "Surge": case "Stash": default: return { url: t }; case "Loon": case "Shadowrocket": return t; case "Quantumult X": return { "open-url": t }; case "Node.js": return }case "object": switch (this.getEnv()) { case "Surge": case "Stash": case "Shadowrocket": default: return { url: t.url || t.openUrl || t["open-url"] }; case "Loon": return { openUrl: t.openUrl || t.url || t["open-url"], mediaUrl: t.mediaUrl || t["media-url"] }; case "Quantumult X": return { "open-url": t["open-url"] || t.url || t.openUrl, "media-url": t["media-url"] || t.mediaUrl, "update-pasteboard": t["update-pasteboard"] || t.updatePasteboard }; case "Node.js": return }default: return } }; if (!this.isMute) switch (this.getEnv()) { case "Surge": case "Loon": case "Stash": case "Shadowrocket": default: $notification.post(e, s, r, i(a)); break; case "Quantumult X": $notify(e, s, r, i(a)); case "Node.js": }if (!this.isMuteLog) { let t = ["", "==============📣系统通知📣=============="]; t.push(e), s && t.push(s), r && t.push(r), console.log(t.join("\n")), this.logs = this.logs.concat(t) } } log(...t) { t.length > 0 && (this.logs = [...this.logs, ...t]), console.log(t.join(this.logSeparator)) } logErr(t, e) { switch (this.getEnv()) { case "Surge": case "Loon": case "Stash": case "Shadowrocket": case "Quantumult X": default: this.log("", `❗️${this.name}, 错误!`, t); break; case "Node.js": this.log("", `❗️${this.name}, 错误!`, t.stack) } } wait(t) { return new Promise((e => setTimeout(e, t))) } done(t = {}) { const e = ((new Date).getTime() - this.startTime) / 1e3; switch (this.log("", `🔔${this.name}, 结束! 🕛 ${e} 秒`), this.log(), this.getEnv()) { case "Surge": case "Loon": case "Stash": case "Shadowrocket": case "Quantumult X": default: $done(t); break; case "Node.js": process.exit(1) } } }(t, e) }

// md5
function md5(md5str) {
  var createMD5String = function (string) { var x = Array(); var k, AA, BB, CC, DD, a, b, c, d; var S11 = 7, S12 = 12, S13 = 17, S14 = 22; var S21 = 5, S22 = 9, S23 = 14, S24 = 20; var S31 = 4, S32 = 11, S33 = 16, S34 = 23; var S41 = 6, S42 = 10, S43 = 15, S44 = 21; string = uTF8Encode(string); x = convertToWordArray(string); a = 1732584193; b = 4023233417; c = 2562383102; d = 271733878; for (k = 0; k < x.length; k += 16) { AA = a; BB = b; CC = c; DD = d; a = FF(a, b, c, d, x[k + 0], S11, 3614090360); d = FF(d, a, b, c, x[k + 1], S12, 3905402710); c = FF(c, d, a, b, x[k + 2], S13, 606105819); b = FF(b, c, d, a, x[k + 3], S14, 3250441966); a = FF(a, b, c, d, x[k + 4], S11, 4118548399); d = FF(d, a, b, c, x[k + 5], S12, 1200080426); c = FF(c, d, a, b, x[k + 6], S13, 2821735955); b = FF(b, c, d, a, x[k + 7], S14, 4249261313); a = FF(a, b, c, d, x[k + 8], S11, 1770035416); d = FF(d, a, b, c, x[k + 9], S12, 2336552879); c = FF(c, d, a, b, x[k + 10], S13, 4294925233); b = FF(b, c, d, a, x[k + 11], S14, 2304563134); a = FF(a, b, c, d, x[k + 12], S11, 1804603682); d = FF(d, a, b, c, x[k + 13], S12, 4254626195); c = FF(c, d, a, b, x[k + 14], S13, 2792965006); b = FF(b, c, d, a, x[k + 15], S14, 1236535329); a = GG(a, b, c, d, x[k + 1], S21, 4129170786); d = GG(d, a, b, c, x[k + 6], S22, 3225465664); c = GG(c, d, a, b, x[k + 11], S23, 643717713); b = GG(b, c, d, a, x[k + 0], S24, 3921069994); a = GG(a, b, c, d, x[k + 5], S21, 3593408605); d = GG(d, a, b, c, x[k + 10], S22, 38016083); c = GG(c, d, a, b, x[k + 15], S23, 3634488961); b = GG(b, c, d, a, x[k + 4], S24, 3889429448); a = GG(a, b, c, d, x[k + 9], S21, 568446438); d = GG(d, a, b, c, x[k + 14], S22, 3275163606); c = GG(c, d, a, b, x[k + 3], S23, 4107603335); b = GG(b, c, d, a, x[k + 8], S24, 1163531501); a = GG(a, b, c, d, x[k + 13], S21, 2850285829); d = GG(d, a, b, c, x[k + 2], S22, 4243563512); c = GG(c, d, a, b, x[k + 7], S23, 1735328473); b = GG(b, c, d, a, x[k + 12], S24, 2368359562); a = HH(a, b, c, d, x[k + 5], S31, 4294588738); d = HH(d, a, b, c, x[k + 8], S32, 2272392833); c = HH(c, d, a, b, x[k + 11], S33, 1839030562); b = HH(b, c, d, a, x[k + 14], S34, 4259657740); a = HH(a, b, c, d, x[k + 1], S31, 2763975236); d = HH(d, a, b, c, x[k + 4], S32, 1272893353); c = HH(c, d, a, b, x[k + 7], S33, 4139469664); b = HH(b, c, d, a, x[k + 10], S34, 3200236656); a = HH(a, b, c, d, x[k + 13], S31, 681279174); d = HH(d, a, b, c, x[k + 0], S32, 3936430074); c = HH(c, d, a, b, x[k + 3], S33, 3572445317); b = HH(b, c, d, a, x[k + 6], S34, 76029189); a = HH(a, b, c, d, x[k + 9], S31, 3654602809); d = HH(d, a, b, c, x[k + 12], S32, 3873151461); c = HH(c, d, a, b, x[k + 15], S33, 530742520); b = HH(b, c, d, a, x[k + 2], S34, 3299628645); a = II(a, b, c, d, x[k + 0], S41, 4096336452); d = II(d, a, b, c, x[k + 7], S42, 1126891415); c = II(c, d, a, b, x[k + 14], S43, 2878612391); b = II(b, c, d, a, x[k + 5], S44, 4237533241); a = II(a, b, c, d, x[k + 12], S41, 1700485571); d = II(d, a, b, c, x[k + 3], S42, 2399980690); c = II(c, d, a, b, x[k + 10], S43, 4293915773); b = II(b, c, d, a, x[k + 1], S44, 2240044497); a = II(a, b, c, d, x[k + 8], S41, 1873313359); d = II(d, a, b, c, x[k + 15], S42, 4264355552); c = II(c, d, a, b, x[k + 6], S43, 2734768916); b = II(b, c, d, a, x[k + 13], S44, 1309151649); a = II(a, b, c, d, x[k + 4], S41, 4149444226); d = II(d, a, b, c, x[k + 11], S42, 3174756917); c = II(c, d, a, b, x[k + 2], S43, 718787259); b = II(b, c, d, a, x[k + 9], S44, 3951481745); a = addUnsigned(a, AA); b = addUnsigned(b, BB); c = addUnsigned(c, CC); d = addUnsigned(d, DD) } var tempValue = wordToHex(a) + wordToHex(b) + wordToHex(c) + wordToHex(d); return tempValue.toLowerCase() }; var rotateLeft = function (lValue, iShiftBits) { return (lValue << iShiftBits) | (lValue >>> (32 - iShiftBits)) }; var addUnsigned = function (lX, lY) { var lX4, lY4, lX8, lY8, lResult; lX8 = (lX & 2147483648); lY8 = (lY & 2147483648); lX4 = (lX & 1073741824); lY4 = (lY & 1073741824); lResult = (lX & 1073741823) + (lY & 1073741823); if (lX4 & lY4) { return (lResult ^ 2147483648 ^ lX8 ^ lY8) } if (lX4 | lY4) { if (lResult & 1073741824) { return (lResult ^ 3221225472 ^ lX8 ^ lY8) } else { return (lResult ^ 1073741824 ^ lX8 ^ lY8) } } else { return (lResult ^ lX8 ^ lY8) } }; var F = function (x, y, z) { return (x & y) | ((~x) & z) }; var G = function (x, y, z) { return (x & z) | (y & (~z)) }; var H = function (x, y, z) { return (x ^ y ^ z) }; var I = function (x, y, z) { return (y ^ (x | (~z))) }; var FF = function (a, b, c, d, x, s, ac) { a = addUnsigned(a, addUnsigned(addUnsigned(F(b, c, d), x), ac)); return addUnsigned(rotateLeft(a, s), b) }; var GG = function (a, b, c, d, x, s, ac) { a = addUnsigned(a, addUnsigned(addUnsigned(G(b, c, d), x), ac)); return addUnsigned(rotateLeft(a, s), b) }; var HH = function (a, b, c, d, x, s, ac) { a = addUnsigned(a, addUnsigned(addUnsigned(H(b, c, d), x), ac)); return addUnsigned(rotateLeft(a, s), b) }; var II = function (a, b, c, d, x, s, ac) { a = addUnsigned(a, addUnsigned(addUnsigned(I(b, c, d), x), ac)); return addUnsigned(rotateLeft(a, s), b) }; var convertToWordArray = function (string) { var lWordCount; var lMessageLength = string.length; var lNumberOfWordsTempOne = lMessageLength + 8; var lNumberOfWordsTempTwo = (lNumberOfWordsTempOne - (lNumberOfWordsTempOne % 64)) / 64; var lNumberOfWords = (lNumberOfWordsTempTwo + 1) * 16; var lWordArray = Array(lNumberOfWords - 1); var lBytePosition = 0; var lByteCount = 0; while (lByteCount < lMessageLength) { lWordCount = (lByteCount - (lByteCount % 4)) / 4; lBytePosition = (lByteCount % 4) * 8; lWordArray[lWordCount] = (lWordArray[lWordCount] | (string.charCodeAt(lByteCount) << lBytePosition)); lByteCount++ } lWordCount = (lByteCount - (lByteCount % 4)) / 4; lBytePosition = (lByteCount % 4) * 8; lWordArray[lWordCount] = lWordArray[lWordCount] | (128 << lBytePosition); lWordArray[lNumberOfWords - 2] = lMessageLength << 3; lWordArray[lNumberOfWords - 1] = lMessageLength >>> 29; return lWordArray }; var wordToHex = function (lValue) {
    var WordToHexValue = "", WordToHexValueTemp = "", lByte, lCount; for (lCount = 0; lCount <= 3; lCount++) {
      lByte = (lValue >>> (lCount * 8)) & 255; WordToHexValueTemp = "0" + lByte.toString(16);
      WordToHexValue = WordToHexValue + WordToHexValueTemp.substr(WordToHexValueTemp.length - 2, 2)
    } return WordToHexValue
  }; var uTF8Encode = function (string) { string = string.toString().replace(/\x0d\x0a/g, "\x0a"); var output = ""; for (var n = 0; n < string.length; n++) { var c = string.charCodeAt(n); if (c < 128) { output += String.fromCharCode(c) } else { if ((c > 127) && (c < 2048)) { output += String.fromCharCode((c >> 6) | 192); output += String.fromCharCode((c & 63) | 128) } else { output += String.fromCharCode((c >> 12) | 224); output += String.fromCharCode(((c >> 6) & 63) | 128); output += String.fromCharCode((c & 63) | 128) } } } return output }; return createMD5String(md5str)
};