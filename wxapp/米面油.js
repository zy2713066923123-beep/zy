/*
米面油百科 - 微信协议登录 + 内容积分

环境变量（微信协议账号统一走 ./getCode.js 路由，与其他脚本共用 WX_ID）：
  WX_ID='wxid_xxx#备注&yyb:openid#备注'         // 推荐
  mmy / MMY                                     // 兼容旧变量，格式同 WX_ID
  WX_ID='user_id:token#备注'                    // 业务 token 直登，推荐写法，不需要 mmy: 前缀
  WX_ID='user_id#token#备注'                    // 同上，另一种分隔写法
  WX_ID='mmy:user_id:token#备注'                // 旧写法，仍保留兼容
  WX_ID='ck:user_id#token#备注'                 // 旧写法，仍保留兼容
  WX_ID='bearer:抓包Authorization里的BearerToken#备注'  // 新登录包 test.yfxiniao.com 可用这种格式先检测

任务控制：
  // 以下核心参数已经写死在脚本里，青龙里不用再额外配置次数、等待或奖励变量。
  // 默认浏览/上报 100 次；每次等待 32 秒；每次奖励目标在 212-1300 之间随机。
  // 内容列表默认从 50 页里取 id，避免每次只跑第一页前几个文章。
  MMY_LIST_LIMIT='20'            // 每页拉取数量；和 /api/content/list?page=&limit= 对应
  MMY_LIST_START_PAGE='1'        // 从第几页开始取；不配置时自动轮换起始页
  MMY_RANDOM_IDS='1'             // 是否从列表池随机取 id，1=随机，0=按列表顺序
  MMY_ID_CACHE_DAYS='7'          // 已浏览 id 记忆天数，避免短期内重复
  MMY_DIRECT_AD_ONLY='0'         // 1=只上报停留金币，不获取文章 id，不调用 earnPoints

广告结算参数：
  MMY_AD_REPORT_TYPE='feed'      // 上报广告类型；HAR 中结算成功的是 feed
  MMY_AD_PLATFORM_CODE='sigmob'  // 广告平台；来自 HAR 的 reportShow
  MMY_AD_SDK_NAME='gdt'          // SDK 名；来自 HAR 的 reportShow

说明：
  - 微信协议账号（wxid_ / yyb:openid / openid / 自定义微信号）统一走 ./getCode.js 智能路由，
    WECHAT_SERVER / YYB_SERVER 在 getCode.js 中配置，本脚本不再直连协议服务。
  - user_id:token / user_id#token 会跳过微信协议登录，直接检测 /api/user/index。
  - mmy:user_id:token / ck:user_id#token 是旧格式，仍然兼容。
  - bearer:token / token:token 会跳过微信协议登录，直接用抓包里的 Authorization Bearer token。
  - 新登录包域名是 test.yfxiniao.com/reelix，和旧的 mimianyou.hongxiu88.com 不是同一套接口。
  - 缓存 key 使用完整账号标识，例如 wxid_xxx / yyb:openid / wx:wxid_xxx。
  - wx.login code 只临时使用，不缓存。
  - 浏览停留金币链路来自抓包：
      /api/content/detail?id=文章id -> 停留 -> /api/content/earnPoints -> /api/ad/reportShow
  - reportShow 的 slot_id 会从 /api/ad/remaining 返回的广告配置里自动取，不硬编码。
*/

const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const crypto = require('crypto');
const { URL, URLSearchParams } = require('url');
const { getSingleCode } = require('./getCode.js');

const $ = new Env('米面油百科');
const log = console.log;

// WX_ID 为推荐变量，与其他脚本共用；mmy/MMY 保留兼容
const ACCOUNT_VAR = readEnv('WX_ID') || readEnv('mmy') || readEnv('MMY') || '';
const BASE_URL = 'https://mimianyou.hongxiu88.com';
const YFX_BASE_URL = readEnv('MMY_YFX_BASE_URL') || 'https://test.yfxiniao.com/reelix/api/v1/app';
const YFX_APPID = readEnv('MMY_YFX_APPID') || 'wx82b9bc71fff22c52';
const YFX_CLIENT_BUILD = readEnv('MMY_YFX_CLIENT_BUILD') || '2026-08-20 14:20:49';
const YFX_DEVICE_ID = readEnv('MMY_YFX_DEVICE_ID') || 'ms2skrbk-3ttyclbz0cv-50lagacyae7';
const APPID = 'wxa6bd2711a95f2e26';
const USER_AGENT = 'Dart/3.12 (dart:io)';
const YFX_USER_AGENT = readEnv('MMY_YFX_UA') || 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.75(0x18004b62) NetType/4G Language/zh_CN';
const INVITE_CODE = readEnv('MMY_INVITE_CODE') || '8B98028196';
// 核心测试参数写死：避免青龙旧环境变量覆盖，导致次数/等待/奖励不符合本次测试。
const READ_COUNT = 60;  // 浏览文章数从 100 降到 60，避免连续行为过于规律
const LIST_PAGES = 50;
const LIST_LIMIT = Math.max(1, parseInt(readEnv('MMY_LIST_LIMIT') || '20', 10) || 20);
const LIST_START_PAGE_RAW = readEnv('MMY_LIST_START_PAGE');
const RANDOM_IDS = String(readEnv('MMY_RANDOM_IDS') ?? '1') !== '0';
const ID_CACHE_DAYS = Math.max(0, parseInt(readEnv('MMY_ID_CACHE_DAYS') || '7', 10) || 0);
const DIRECT_AD_ONLY = String(readEnv('MMY_DIRECT_AD_ONLY') || '0') === '1';
// 真人化浏览：停留时长不再写死，按区间 + 高斯漂移随机生成，避免被识别为脚本重放。
const STAY_SECONDS_MIN = 22;
const STAY_SECONDS_MAX = 55;
const STAY_SECONDS_BIG_PAUSE_PROB = 0.08;        // 8% 概率模拟走神/切换，长停留 60~120 秒
const STAY_SECONDS_BIG_PAUSE_MIN = 60;
const STAY_SECONDS_BIG_PAUSE_MAX = 120;
const AD_REPORT_COUNT = 50;  // 降到 50 次，配合随机跳过和长停留节奏，避免被识别批量作弊
const AD_REPORT_TYPE = readEnv('MMY_AD_REPORT_TYPE') || 'feed';
const AD_PLATFORM_CODE = readEnv('MMY_AD_PLATFORM_CODE') || 'sigmob';
const AD_SDK_NAME = readEnv('MMY_AD_SDK_NAME') || 'gdt';
const AD_ECPM = '';
const AD_REWARD_MIN = 180;                       // 范围略微放大，让 ecpm 取值更分散
const AD_REWARD_MAX = 1500;
const AD_SKIP_PROB = 0.12;                       // 12% 文章不上报广告，模拟真人翻页行为
const AD_FAIL_BACKOFF_MS = 45000;                // 检测到封禁/失败信号后的全局冷却时间
const BATCH_BREAK_PROB = 0.07;                   // 每篇之后有概率进入短间歇（3~10 秒）
const BATCH_BREAK_MIN_MS = 3000;
const BATCH_BREAK_MAX_MS = 10000;
const CACHE_DIR = path.join(process.cwd(), '.cache');
const CACHE_FILE = path.join(CACHE_DIR, 'mmy_accounts.json');
const READ_HISTORY_FILE = path.join(CACHE_DIR, 'mmy_read_history.json');

const summaries = [];

async function main() {
  const accounts = parseAccounts(ACCOUNT_VAR);
  if (!accounts.length) {
    log('未配置账号变量 WX_ID，格式：wxid_xxx#备注 或 yyb:openid#备注（兼容 mmy/MMY）');
    return;
  }

  log(`共找到 ${accounts.length} 个账号`);
  for (let i = 0; i < accounts.length; i++) {
    const account = accounts[i];
    try {
      log(`\n==== 账号 ${i + 1}/${accounts.length} ${account.remark} ====`);
      const result = await runAccount(account);
      summaries.push({
        account: account.id,
        remark: account.remark,
        points: result.points,
        gained: result.gained,
        error: '',
      });
    } catch (e) {
      const msg = e && e.message ? e.message : String(e);
      log(`[${account.remark}] 失败：${msg}`);
      summaries.push({
        account: account.id,
        remark: account.remark,
        points: '-',
        gained: 0,
        error: msg,
      });
    }

    if (i < accounts.length - 1) await sleep(randomInt(3000, 6000));
  }

  printSummary();
}

async function runAccount(account) {
  if (account.type === 'mmyToken') return runMmyTokenAccount(account);
  if (account.type === 'bearer') return runBearerAccount(account);

  const cache = loadCache();
  let session = cache[account.id] || {};
  session.remark = account.remark;

  if (!(await isSessionValid(session))) {
    log(`[${account.remark}] 缓存无效，开始协议登录`);
    const wxidForServer = normalizeProtocolWxid(account.id);
    const code = await getWxLoginCode(wxidForServer);
    session = await appLogin(code, account.remark, wxidForServer);
    session.remark = account.remark;
    session.updateTime = Date.now();
    cache[account.id] = session;
    saveCache(cache);
  } else {
    log(`[${account.remark}] 缓存命中 user_id=${session.user_id}`);
  }

  const beforeInfo = await getUserInfo(session);
  const beforePoints = readPoints(beforeInfo);
  let gained = 0;

  if (DIRECT_AD_ONLY) {
    gained += await runDirectAdReports(session, account.remark);
  }

  if (!DIRECT_AD_ONLY && READ_COUNT > 0) {
    const items = await getContentItems(session, READ_COUNT, account.id);
    let adReports = 0;
    let consecutiveBanned = 0;  // 连续上报失败计数；超过阈值自动降频，防止被封禁
    for (const item of items) {
      // 浏览链路第一步：打开文章详情，让服务端记录文章访问。
      log(`[${account.remark}] 浏览 ${item.id}${item.title ? ' - ' + item.title : ''}`);
      await getContentDetail(session, item.id);

      // 浏览链路第二步：随机停留时间，模拟真人节奏（带偶发长停顿），而非固定秒数。
      const staySeconds = makeStaySeconds();
      if (staySeconds > 0) {
        log(`[${account.remark}] 停留 ${staySeconds} 秒`);
        await sleep(staySeconds * 1000);
      }

      // 浏览链路第三步：领取内容阅读积分。抓包里该接口可能返回 0，属正常现象。
      const contentPoint = await earnContentPoints(session, item.id);
      let adPoint = 0;

      // 浏览链路第四步：上报广告展示，HAR 中"阅读停留奖励/看文章奖励"由这里结算。
      // 加概率跳过 + 失败冷却，降低被广告反作弊系统识别的风险。
      if (adReports < AD_REPORT_COUNT && Math.random() >= AD_SKIP_PROB) {
        adPoint = await reportBrowseAdShow(session);
        adReports += 1;
        if (isBannedResponse(adPoint)) {
          consecutiveBanned += 1;
          if (consecutiveBanned >= 2) {
            log(`[${account.remark}] 连续检测到封禁信号，全局冷却 ${AD_FAIL_BACKOFF_MS / 1000} 秒后恢复`);
            await sleep(AD_FAIL_BACKOFF_MS);
            consecutiveBanned = 0;
          }
        } else if (adPoint > 0) {
          consecutiveBanned = 0;
        }
      }

      const point = contentPoint + adPoint;
      gained += point;
      markReadHistory(account.id, item.id);
      log(`[${account.remark}] 阅读 ${item.id} 获得 ${point}（内容 ${contentPoint} / 停留 ${adPoint}）`);

      // 模拟真人翻页节奏：基础等待 + 偶发批次间歇（3~10 秒），让上报间隔更分散。
      await sleep(randomInt(1200, 2500));
      if (Math.random() < BATCH_BREAK_PROB) {
        const breakMs = randomInt(BATCH_BREAK_MIN_MS, BATCH_BREAK_MAX_MS);
        log(`[${account.remark}] 模拟真人间歇 ${Math.round(breakMs / 1000)} 秒`);
        await sleep(breakMs);
      }
    }
  }

  const afterInfo = await getUserInfo(session);
  const afterPoints = readPoints(afterInfo);
  return { points: afterPoints, gained: Math.max(gained, afterPoints - beforePoints) };
}

async function runMmyTokenAccount(account) {
  const session = { user_id: String(account.user_id), token: String(account.token), remark: account.remark };
  log(`[${account.remark}] 使用业务 token 直登 user_id=${session.user_id}`);

  const info = await getUserInfo(session);
  if (!info || info.code !== 1 || !info.data || !info.data.userInfo) {
    throw new Error('业务 token 检测失败: ' + stringifyShort(info));
  }

  const beforePoints = readPoints(info);
  let gained = 0;

  if (DIRECT_AD_ONLY) {
    gained += await runDirectAdReports(session, account.remark);
  }

  if (!DIRECT_AD_ONLY && READ_COUNT > 0) {
    const items = await getContentItems(session, READ_COUNT, account.id);
    let adReports = 0;
    for (const item of items) {
      log(`[${account.remark}] 浏览 ${item.id}${item.title ? ' - ' + item.title : ''}`);
      await getContentDetail(session, item.id);
      if (READ_STAY_SECONDS > 0) {
        log(`[${account.remark}] 停留 ${READ_STAY_SECONDS} 秒`);
        await sleep(READ_STAY_SECONDS * 1000);
      }

      const contentPoint = await earnContentPoints(session, item.id);
      let adPoint = 0;
      if (adReports < AD_REPORT_COUNT) {
        adPoint = await reportBrowseAdShow(session);
        adReports++;
      }

      const point = contentPoint + adPoint;
      gained += point;
      markReadHistory(account.id, item.id);
      log(`[${account.remark}] 阅读 ${item.id} 获得 ${point}（内容 ${contentPoint} / 停留 ${adPoint}）`);
      await sleep(randomInt(1200, 2500));
    }
  }

  const afterInfo = await getUserInfo(session);
  const afterPoints = readPoints(afterInfo);
  return { points: afterPoints, gained: Math.max(gained, afterPoints - beforePoints) };
}

async function runDirectAdReports(session, remark) {
  const count = AD_REPORT_COUNT || READ_COUNT;
  let gained = 0;
  if (count <= 0) {
    log(`[${remark}] 已开启只上报停留金币，但次数为 0`);
    return 0;
  }

  log(`[${remark}] 只上报停留金币模式，共 ${count} 次`);
  let consecutiveBanned = 0;
  for (let i = 0; i < count; i++) {
    // 跳过概率模拟真人节奏
    if (Math.random() < AD_SKIP_PROB) {
      log(`[${remark}] 第 ${i + 1}/${count} 次跳过（模拟真人翻页）`);
      await sleep(randomInt(2000, 5000));
      continue;
    }
    const staySeconds = makeStaySeconds();
    if (staySeconds > 0) {
      log(`[${remark}] 第 ${i + 1}/${count} 次等待 ${staySeconds} 秒`);
      await sleep(staySeconds * 1000);
    }
    const point = await reportBrowseAdShow(session);
    gained += point;
    log(`[${remark}] 第 ${i + 1}/${count} 次停留金币 ${point}`);
    if (isBannedResponse(point)) {
      consecutiveBanned += 1;
      if (consecutiveBanned >= 2) {
        log(`[${remark}] 连续检测到封禁信号，全局冷却 ${AD_FAIL_BACKOFF_MS / 1000} 秒后恢复`);
        await sleep(AD_FAIL_BACKOFF_MS);
        consecutiveBanned = 0;
      }
    } else if (point > 0) {
      consecutiveBanned = 0;
    }
    if (i < count - 1) {
      await sleep(randomInt(1200, 2500));
      if (Math.random() < BATCH_BREAK_PROB) {
        const breakMs = randomInt(BATCH_BREAK_MIN_MS, BATCH_BREAK_MAX_MS);
        log(`[${remark}] 模拟真人间歇 ${Math.round(breakMs / 1000)} 秒`);
        await sleep(breakMs);
      }
    }
  }
  return gained;
}

async function runBearerAccount(account) {
  log(`[${account.remark}] 使用 Bearer token 检测新接口登录态`);
  const profile = await yfxRequest('GET', '/customer/profile', null, account.token);
  if (!profile || !profile.id) {
    throw new Error('Bearer 登录态检测失败: ' + stringifyShort(profile));
  }
  log(`[${account.remark}] 新接口登录成功 customerId=${profile.id} openId=${profile.openId || ''}`);

  const overview = await yfxRequest('GET', '/points/earn-page/overview', null, account.token);
  const accountInfo = overview && overview.account ? overview.account : {};
  const points = Number(accountInfo.pointsBalance ?? profile.pointsBalance ?? 0) || 0;
  const today = Number(accountInfo.todayEarnedPoints ?? 0) || 0;
  log(`[${account.remark}] 当前积分 ${points} 今日获得 ${today}`);

  return { points, gained: 0 };
}

async function getWxLoginCode(wxid) {
  const code = await getSingleCode(APPID, wxid);
  if (!code) throw new Error('获取 wx.login code 失败，协议服务未返回有效 code');
  return code;
}

async function appLogin(code, remark, wxidForServer) {
  const data = await apiRequest('POST', '/api/wechat/appLogin', {
    form: { code, invite_code: INVITE_CODE },
    auth: null,
  });
  if (!data || data.code !== 1 || !data.data || !data.data.token || !data.data.user_id) {
    throw new Error(`业务登录失败 wx=${wxidForServer || ''} code=${maskCode(code)} 返回=${stringifyShort(data)}`);
  }
  log(`[${remark}] 业务登录成功 user_id=${data.data.user_id} is_new=${!!data.data.is_new}`);
  return {
    user_id: String(data.data.user_id),
    token: data.data.token,
    expiretime: data.data.userinfo && data.data.userinfo.expiretime,
    userinfo: data.data.userinfo || {},
  };
}

async function isSessionValid(session) {
  if (!session || !session.user_id || !session.token) return false;
  if (session.expiretime && Date.now() / 1000 > Number(session.expiretime) - 3600) return false;
  const info = await getUserInfo(session).catch(() => null);
  return !!(info && info.code === 1 && info.data && info.data.userInfo);
}

async function getUserInfo(session) {
  return apiRequest('GET', '/api/user/index', { auth: session });
}

async function getContentList(session) {
  return apiRequest('GET', `/api/content/list?page=1&limit=${LIST_LIMIT}`, { auth: session });
}

async function getContentItems(session, targetCount, accountKey) {
  const items = [];
  const seen = new Set();
  const recentIds = loadRecentReadIds(accountKey);
  const startPage = getListStartPage(accountKey);

  // 扩大 id 池：按页拉取列表，去重后取到 MMY_READ_COUNT 个文章。
  // 这样不会只反复打第一页前几个 id，测试不同次数时更灵活。
  for (let offset = 0; offset < LIST_PAGES; offset++) {
    const page = startPage + offset;
    const list = await apiRequest('GET', `/api/content/list?page=${page}&limit=${LIST_LIMIT}`, { auth: session });
    const pageItems = (((list || {}).data || {}).data || []);
    if (!pageItems.length) break;
    for (const item of pageItems) {
      if (!item || item.id == null || seen.has(String(item.id))) continue;
      seen.add(String(item.id));
      items.push(item);
    }
  }

  let candidates = items.filter((item) => !recentIds.has(String(item.id)));
  if (candidates.length < targetCount) {
    log(`新 id 不足 ${targetCount} 个，允许使用历史 id 补足`);
    const candidateSet = new Set(candidates.map((item) => String(item.id)));
    candidates = candidates.concat(items.filter((item) => !candidateSet.has(String(item.id))));
  }
  if (RANDOM_IDS) shuffle(candidates);

  const selected = candidates.slice(0, targetCount);
  log(`已从第 ${startPage} 页起 ${LIST_PAGES} 页整理 ${items.length} 个内容 id，跳过近期 ${recentIds.size} 个，选中 ${selected.map((x) => x.id).join(',')}`);
  saveListCursor(accountKey, startPage + LIST_PAGES);
  return selected;
}

async function getContentDetail(session, id) {
  const data = await apiRequest('GET', `/api/content/detail?id=${encodeURIComponent(id)}`, { auth: session });
  if (!data || data.code !== 1) log(`detail ${id} 返回异常：${stringifyShort(data)}`);
  return data;
}

async function earnContentPoints(session, id) {
  const data = await apiRequest('POST', '/api/content/earnPoints', {
    auth: session,
    form: { id },
  });
  if (!data || data.code !== 1) {
    if (data && String(data.msg || '').includes('已获得过阅读积分')) {
      log(`earnPoints ${id} 已领取过，跳过内容积分`);
    } else {
      log(`earnPoints ${id} 返回异常：${stringifyShort(data)}`);
    }
    return 0;
  }
  return Number(data.data && data.data.points) || 0;
}

async function reportBrowseAdShow(session) {
  // 先读取广告配置，动态提取 feed/interstitial 等广告位 slot_id。
  // HAR 中成功结算的参数为：ad_type=feed, platform_code=sigmob, sdk_name=gdt。
  const remaining = await getAdRemaining(session);
  const placement = findAdPlacement(remaining, AD_REPORT_TYPE);
  const slotId = placement && (placement.placement_id || placement.rit_id || placement.fallback_placement_id);
  if (!slotId) {
    log(`未找到 ${AD_REPORT_TYPE} 广告位，跳过停留金币上报`);
    return 0;
  }

  const rewardPlan = makeAdRewardPlan();
  // show_time 做 ±120 秒抖动，避免每次上报时间戳规律性过强。
  const showTime = Math.floor(Date.now() / 1000) + randomInt(-120, 120);
  const data = await apiRequest('POST', '/api/ad/reportShow', {
    auth: session,
    form: {
      ad_type: AD_REPORT_TYPE,
      platform_code: AD_PLATFORM_CODE,
      slot_id: slotId,
      // 每次上报都生成新的 request_id，避免同一个请求 id 被服务端判重复。
      request_id: makeRequestId(),
      ecpm: rewardPlan.ecpm,
      ecpm_unit: 'fen',
      show_time: showTime,
      sdk_name: AD_SDK_NAME,
    },
  });
  if (!data || data.code !== 1) {
    const msg = String((data && (data.msg || data.message)) || '');
    log(`reportShow 返回异常：${stringifyShort(data)}`);
    // 标记 -1 表示检测到封禁/限流信号，让主循环触发全局冷却。
    if (/封禁|作弊|违规|限流|频繁|黑名单/i.test(msg)) return -1;
    return 0;
  }
  const coin = Number(data.data && (data.data.user_coin ?? data.data.coin ?? data.data.points)) || 0;
  const balance = data.data && data.data.balance != null ? ` 余额=${data.data.balance}` : '';
  log(`停留金币结算成功：${coin}${balance} 目标=${rewardPlan.target} ecpm=${rewardPlan.ecpm}`);
  return coin;
}

function isBannedResponse(point) {
  return typeof point === 'number' && point < 0;
}

async function getAdRemaining(session) {
  return apiRequest('GET', '/api/ad/remaining', { auth: session });
}

function findAdPlacement(resp, adType) {
  const platforms = (((resp || {}).data || {}).ad_platforms || []);
  for (const platform of platforms) {
    const placements = platform && Array.isArray(platform.placements) ? platform.placements : [];
    const hit = placements.find((x) => x && x.enabled !== 0 && x.placement_type === adType);
    if (hit) return hit;
  }
  return null;
}

async function apiRequest(method, urlPath, opts = {}) {
  const headers = {
    accept: 'application/json',
    'content-type': 'application/x-www-form-urlencoded',
    'user-agent': USER_AGENT,
    'x-app-version': '1.0.2',
  };
  if (opts.auth) {
    headers.user_id = String(opts.auth.user_id);
    headers.token = String(opts.auth.token);
  }

  const fullUrl = BASE_URL + urlPath;
  const body = opts.form ? new URLSearchParams(opts.form).toString() : '';
  return requestJson(fullUrl, {
    method,
    headers,
    body: method === 'GET' ? '' : body,
    timeout: 30000,
  });
}

async function yfxRequest(method, urlPath, data, token) {
  const headers = {
    accept: 'application/json',
    'content-type': 'application/json',
    'user-agent': YFX_USER_AGENT,
    'x-promopixis-platform': 'miniprogram',
    'x-client-build': YFX_CLIENT_BUILD,
    'x-device-id': YFX_DEVICE_ID,
    referer: `https://servicewechat.com/${YFX_APPID}/36/page-frame.html`,
    authorization: token.startsWith('Bearer ') ? token : `Bearer ${token}`,
  };
  return requestJson(YFX_BASE_URL + urlPath, {
    method,
    headers,
    body: method === 'GET' || data == null ? '' : JSON.stringify(data),
    timeout: 30000,
  });
}

function requestJson(url, options) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const client = u.protocol === 'http:' ? http : https;
    const body = options.body || '';
    const headers = Object.assign({}, options.headers || {});
    if (body && !headers['Content-Length']) headers['Content-Length'] = Buffer.byteLength(body);

    const req = client.request({
      protocol: u.protocol,
      hostname: u.hostname,
      port: u.port || undefined,
      path: u.pathname + u.search,
      method: options.method || 'GET',
      headers,
      timeout: options.timeout || 30000,
    }, (res) => {
      const chunks = [];
      res.on('data', (x) => chunks.push(x));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        let data = text;
        try { data = JSON.parse(text); } catch {}
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`HTTP ${res.statusCode}: ${stringifyShort(data)}`));
          return;
        }
        resolve(data);
      });
    });
    req.on('timeout', () => req.destroy(new Error('请求超时')));
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

function parseAccounts(raw) {
  return String(raw || '')
    .split(/[&@\n]/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map(parseWxAccount)
    .filter((x) => {
      if (x.type === 'mmyToken' || x.type === 'bearer') return true;
      if (!isWechatProtocolId(x.id)) {
        log(`账号格式错误，跳过：${x.raw}`);
        return false;
      }
      return true;
    });
}

function parseWxAccount(line) {
  const parts = String(line || '').trim().split('#');
  const id = (parts.shift() || '').trim();
  const mmyToken = parseMmyTokenAccount(id, parts);
  if (mmyToken) {
    const remark = (mmyToken.remark || id).trim();
    delete mmyToken.remark;
    return Object.assign({ raw: line, remark, type: 'mmyToken' }, mmyToken);
  }
  const remark = (parts.join('#') || id).trim();
  const bearerToken = parseBearerToken(id);
  if (bearerToken) return { raw: line, id: 'bearer:' + maskToken(bearerToken), token: bearerToken, remark, type: 'bearer' };
  return { raw: line, id, remark, type: 'wechat' };
}

function isWechatProtocolId(x) {
  const s = String(x || '').trim();
  if (!s) return false;
  if (s.startsWith('wxid_') || s.startsWith('yyb:') || s.startsWith('wx:')) return true;
  if (parseBearerToken(s) || parseMmyTokenAccount(s, [])) return true;
  // 与 ./getCode.js 路由一致：应用宝 openid（o 开头 20+ 位）当协议账号
  if (/^o[a-zA-Z0-9_-]{20,}$/.test(s)) return true;
  // 微信自定义号（alias）：字母开头 6-20 位
  if (/^[a-zA-Z][-_a-zA-Z0-9]{5,19}$/.test(s)) return true;
  return false;
}

function parseMmyTokenAccount(id, restParts) {
  const s = String(id || '').trim();
  // 推荐直登格式 1：28148:f378c781-a7a7-4581-a121-e15493999cc1#备注
  // 只要冒号前面是纯数字 user_id，就按业务 token 直登解析，不再需要 mmy: 前缀。
  if (/^\d+:/.test(s)) {
    const idx = s.indexOf(':');
    const userId = s.slice(0, idx).trim();
    const token = s.slice(idx + 1).trim();
    const remark = restParts && restParts.length ? restParts.join('#') : '';
    if (userId && token) return { id: 'uid:' + userId + ':' + maskToken(token), user_id: userId, token, remark };
  }

  // 推荐直登格式 2：28148#f378c781-a7a7-4581-a121-e15493999cc1#备注
  if (/^\d+$/.test(s)) {
    const token = restParts && restParts[0] ? String(restParts[0]).trim() : '';
    const remark = restParts && restParts.length > 1 ? restParts.slice(1).join('#') : '';
    if (token) return { id: 'uid:' + s + '#' + maskToken(token), user_id: s, token, remark };
  }

  if (s.startsWith('mmy:')) {
    const arr = s.split(':');
    if (arr.length >= 3 && arr[1] && arr.slice(2).join(':')) {
      const token = arr.slice(2).join(':').trim();
      const remark = restParts && restParts.length ? restParts.join('#') : '';
      return { id: 'mmy:' + arr[1] + ':' + maskToken(token), user_id: arr[1].trim(), token, remark };
    }
  }
  if (s.startsWith('ck:')) {
    const userId = s.slice(3).trim();
    const token = restParts && restParts[0] ? String(restParts[0]).trim() : '';
    const remark = restParts && restParts.length > 1 ? restParts.slice(1).join('#') : '';
    if (userId && token) return { id: 'ck:' + userId + '#' + maskToken(token), user_id: userId, token, remark };
  }
  return null;
}

function parseBearerToken(x) {
  const s = String(x || '').trim();
  if (s.startsWith('bearer:')) return s.slice(7).trim();
  if (s.startsWith('token:')) return s.slice(6).trim();
  if (s.startsWith('Bearer ')) return s.slice(7).trim();
  if (/^eyJ[^#\s]+\.[^#\s]+$/.test(s)) return s;
  return '';
}

function maskToken(token) {
  const s = String(token || '');
  return s.length <= 16 ? '***' : s.slice(0, 8) + '...' + s.slice(-6);
}

function maskCode(code) {
  const s = String(code || '');
  return s.length <= 10 ? s : s.slice(0, 6) + '...' + s.slice(-4);
}

// 剥离协议前缀，得到传给 getCode.js 的真实 identifier（yyb:openid → openid 自动路由应用宝）
function normalizeProtocolWxid(x) {
  const s = String(x || '').trim();
  if (s.startsWith('wx:')) return s.slice(3);
  if (s.startsWith('yyb:')) return s.slice(4);
  return s;
}

function readPoints(info) {
  const u = info && info.data && info.data.userInfo;
  if (!u) return 0;
  return Number(u.coin_balance ?? u.score ?? u.today_earned ?? 0) || 0;
}

function loadCache() {
  try {
    if (fs.existsSync(CACHE_FILE)) return JSON.parse(fs.readFileSync(CACHE_FILE, 'utf8'));
  } catch (e) {
    log('读取缓存失败：' + e.message);
  }
  return {};
}

function saveCache(data) {
  try {
    if (!fs.existsSync(CACHE_DIR)) fs.mkdirSync(CACHE_DIR, { recursive: true });
    fs.writeFileSync(CACHE_FILE, JSON.stringify(data, null, 2));
  } catch (e) {
    log('保存缓存失败：' + e.message);
  }
}

function loadReadHistory() {
  try {
    if (fs.existsSync(READ_HISTORY_FILE)) return JSON.parse(fs.readFileSync(READ_HISTORY_FILE, 'utf8'));
  } catch (e) {
    log('读取浏览历史失败：' + e.message);
  }
  return {};
}

function saveReadHistory(data) {
  try {
    if (!fs.existsSync(CACHE_DIR)) fs.mkdirSync(CACHE_DIR, { recursive: true });
    fs.writeFileSync(READ_HISTORY_FILE, JSON.stringify(data, null, 2));
  } catch (e) {
    log('保存浏览历史失败：' + e.message);
  }
}

function getHistoryKey(accountKey) {
  return String(accountKey || 'default').replace(/[^\w:.-]/g, '_');
}

function loadRecentReadIds(accountKey) {
  const history = loadReadHistory();
  const key = getHistoryKey(accountKey);
  const now = Date.now();
  const keepMs = ID_CACHE_DAYS * 86400000;
  const recent = {};
  const set = new Set();

  for (const [id, ts] of Object.entries((history[key] && history[key].ids) || {})) {
    if (!keepMs || now - Number(ts) <= keepMs) {
      recent[id] = Number(ts) || now;
      set.add(String(id));
    }
  }

  if (!history[key]) history[key] = {};
  history[key].ids = recent;
  saveReadHistory(history);
  return set;
}

function markReadHistory(accountKey, id) {
  const history = loadReadHistory();
  const key = getHistoryKey(accountKey);
  if (!history[key]) history[key] = {};
  if (!history[key].ids) history[key].ids = {};
  history[key].ids[String(id)] = Date.now();
  saveReadHistory(history);
}

function getListStartPage(accountKey) {
  if (LIST_START_PAGE_RAW) return Math.max(1, parseInt(LIST_START_PAGE_RAW, 10) || 1);
  const history = loadReadHistory();
  const key = getHistoryKey(accountKey);
  return Math.max(1, parseInt(history[key] && history[key].nextPage, 10) || 1);
}

function saveListCursor(accountKey, nextPage) {
  if (LIST_START_PAGE_RAW) return;
  const history = loadReadHistory();
  const key = getHistoryKey(accountKey);
  if (!history[key]) history[key] = {};
  history[key].nextPage = Math.max(1, Number(nextPage) || 1);
  saveReadHistory(history);
}

function printSummary() {
  log('\n======== 本次汇总 ========');
  for (const s of summaries) {
    if (s.error) {
      log(`当前账号：${s.account} 当前备注：${s.remark} 当前积分：- 本次获得：0 失败：${s.error}`);
    } else {
      log(`当前账号：${s.account} 当前备注：${s.remark} 当前积分：${s.points} 本次获得：${s.gained}`);
    }
  }
}

function stringifyShort(x) {
  if (typeof x === 'string') return x.slice(0, 500);
  try { return JSON.stringify(x).slice(0, 500); } catch { return String(x).slice(0, 500); }
}

function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function makeAdRewardPlan() {
  if (AD_ECPM) {
    return { target: '固定', ecpm: String(AD_ECPM) };
  }
  // 不再用 target*1000/60 这种容易被风控识别的整数比例。
  // 改为在区间内均匀采样，再叠加 0.5~1.5 倍随机抖动，得到更离散的 ecpm 取值。
  const target = randomInt(AD_REWARD_MIN, AD_REWARD_MAX);
  const ratio = 0.5 + Math.random();
  const baseEcpm = (target * 1000 / 60) * ratio;
  // 保留两位小数 + 偶尔抖动到一位小数，让小数位分布更随机
  const decimals = Math.random() < 0.4 ? 1 : 2;
  const ecpm = baseEcpm.toFixed(decimals);
  return { target, ecpm };
}

// 真人节奏停留时长：大部分 22~55 秒（接近阅读 + 拉到最后），8% 概率走神 60~120 秒。
function makeStaySeconds() {
  if (Math.random() < STAY_SECONDS_BIG_PAUSE_PROB) {
    return randomInt(STAY_SECONDS_BIG_PAUSE_MIN, STAY_SECONDS_BIG_PAUSE_MAX);
  }
  return randomInt(STAY_SECONDS_MIN, STAY_SECONDS_MAX);
}

function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = randomInt(0, i);
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function makeRequestId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return [4, 2, 2, 2, 6].map((len) => crypto.randomBytes(len).toString('hex')).join('-');
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readEnv(name) {
  return $.isNode() ? process.env[name] : $.getdata(name);
}

function Env(name) {
  this.name = name;
  this.isNode = () => typeof module !== 'undefined' && !!module.exports;
  this.getdata = () => '';
}

main().catch((e) => {
  log('脚本异常：' + (e && e.stack ? e.stack : e));
  printSummary();
});
