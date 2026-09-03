// name: 云朵充电
// cron: 24 07,19 * * *
// 说明: 自动从 yyb 获取存活账号 -> 自动登录 -> 自动签到 -> 自动看广告(完成任务) -> 自动补签 -> 自动查积分
// 依赖: 本地 yyb-main/yyb-go 服务 (默认 http://127.0.0.1:18273, 可用 WX_SERVER/YYB_SERVER 覆盖)
// 变量: WX_ID (可选, 筛选账号, 不配则跑全部存活账号)

const axios = require('axios');
const { sendNotify } = require('../sendNotify');
const yyb = require('./yyb.js');

const APPID = 'wxe1ad7e88bd93ee4d';
const BASE = 'https://api.szyunduo.cn';
const CACHE_NAME = 'yunduo';

// ================= 积分来源(来自源码 PointSourceEnum) =================
// 1=平台签到  2=完成任务(广告)  3=商城赠送  4=优惠券  5=单车充电  6=汽车充电  7=积分兑换
// 经实测后端仅接受 pointSource=1(签到/补签) 与 pointSource=2(广告任务), 其余返回失败
// =====================================================================

const getToday = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
const getWeekDay = () => new Date().getDay(); // 0=周日 ... 6=周六
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const getHeaders = (tk, openid) => ({
    'content-type': 'application/json',
    'Host': 'api.szyunduo.cn',
    'x-giklinks-wx-miniprogram-openid': openid,
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.66(0x1800422e) NetType/WIFI Language/zh_CN',
    'xy-consumer-token': tk
});

// 通用请求封装
async function api(tk, openid, method, path, data = null) {
    try {
        const res = await axios({ method, url: BASE + path, data, headers: getHeaders(tk, openid), timeout: 20000 });
        return res.data;
    } catch (e) {
        return { code: 'ERR', message: e.message };
    }
}

// 查积分余额
async function queryPoint(tk, openid, uid) {
    const r = await api(tk, openid, 'GET', `/consumer-service/v1/mgr/consumerPoint/getConsumerPoint/${uid}`);
    return (r.code === "000000" && r.data) ? (r.data.points || 0) : null;
}

// 查周签到记录 (返回本周7天, 每条含 pointWeek/points/signStatus/weekDay)
async function queryWeekSign(tk, openid, uid) {
    const r = await api(tk, openid, 'GET', `/consumer-service/v1/mgr/consumerPoint/weekSign/${uid}`);
    return (r.code === "000000" && Array.isArray(r.data)) ? r.data : [];
}

// 查今日剩余广告/任务次数 (实时, 每次调用返回当前剩余)
async function queryTaskNum(tk, openid, uid) {
    const r = await api(tk, openid, 'GET', `/consumer-service/v1/mgr/consumerPoint/getTaskNum/${uid}`);
    return (r.code === "000000" && r.data) ? Number(r.data) : 0;
}

// 查系统配置
async function getCodeList(tk, openid, category, code) {
    const r = await api(tk, openid, 'GET', `/system-service/v1/mgr/systemCodeTable/getCodeList?category=${encodeURIComponent(category)}&code=${encodeURIComponent(code)}`);
    if (r.code === "000000" && Array.isArray(r.data) && r.data.length) return r.data[0].value;
    return null;
}

// 创建积分记录
async function createPoint(tk, openid, uid, point, pointWeek, source) {
    const r = await api(tk, openid, 'POST', `/consumer-service/v1/mgr/consumerPoint/createPointLog`, {
        consumerId: uid, point, pointWeek, pointSource: source, type: "income"
    });
    return r.code === "000000";
}

// 自动登录: 用 yyb 取 wx.login code -> 换 jwtToken
async function login(openid) {
    const client = new yyb.YYBClient();
    const code = await client.getCode(openid, APPID);
    if (!code) throw new Error('获取 wx.login code 失败');
    const r = await axios.post(`${BASE}/consumer-service/v1/consumer/wx/login`, { code }, {
        headers: { 'content-type': 'application/json', 'User-Agent': 'Mozilla/5.0' }, timeout: 20000
    });
    const d = r.data;
    if (d.code !== "000000" || !d.data) throw new Error(`登录失败: ${d.message || JSON.stringify(d)}`);
    return d.data; // { consumerId, jwtToken, openid, ... }
}

// 跑单个账号
async function runAccount(openid, idx) {
    const log = [];
    let tk = null, uid = null;

    // 1. 尝试用缓存 token
    const cached = yyb.getCachedToken(CACHE_NAME, openid);
    if (cached && cached.token) {
        tk = cached.token;
        uid = Number(cached.consumerId);
    }

    // 2. 无缓存或 token 失效则重新登录
    if (!tk || !uid) {
        try {
            const info = await login(openid);
            tk = info.jwtToken;
            uid = Number(info.consumerId);
            yyb.saveCachedToken(CACHE_NAME, openid, { token: tk, consumerId: uid });
            log.push('🔑 新登录');
        } catch (e) {
            console.log(`   ✗ 登录失败: ${e.message}`);
            return `账号${idx}: 登录失败 ${e.message}`;
        }
    }

    console.log(`\n========== 账号${idx} (ID:${uid}) ==========`);

    // 3. 查配置
    const taskPoint = await getCodeList(tk, openid, 'PointSetting', 'Task');
    const adOn = await getCodeList(tk, openid, 'ADPlatform', 'WeChat');
    const taskPointVal = taskPoint ? Number(taskPoint) : 10;
    console.log(`   任务单次积分: ${taskPointVal}, 广告平台: ${adOn === '1' ? '开' : '关'}`);

    const today = getToday();
    const week = await queryWeekSign(tk, openid, uid);
    const todaySign = week.find(w => w.pointWeek === today);

    // 4. 自动签到 (pointSource=1)
    let signed = todaySign && todaySign.signStatus;
    if (!signed) {
        const ok = await createPoint(tk, openid, uid, taskPointVal, today, 1);
        console.log(`📅 签到: ${ok ? '成功' : '失败'}`);
        log.push(`签到${ok ? '✅' : '⛔'}`);
        await sleep(300);
    } else {
        console.log(`📅 今日已签到`);
        log.push(`签到(已签)`);
    }

    // 5. 自动补签 (pointSource=1, 对本周过去未签的日期)
    // 源码 againSign: 对 weekDay < 今天星期 且 !signStatus 的记录, 用该天 points 补签
    const curDay = getWeekDay();
    let backfill = 0;
    for (const w of week) {
        if (w.signStatus) continue;                 // 已签跳过
        if (!w.weekDay || w.weekDay >= curDay) continue; // 只补过去
        const pt = Number(w.points) || taskPointVal;
        const ok = await createPoint(tk, openid, uid, pt, w.pointWeek, 1);
        if (ok) backfill++;
        await sleep(300);
    }
    if (backfill > 0) {
        console.log(`📌 补签成功 ${backfill} 天`);
        log.push(`补签${backfill}天`);
    }

    // 6. 自动看广告 (pointSource=2), 循环查 taskNum 直到 0
    let adOk = 0, adTotal = 0;
    for (let i = 0; i < 20; i++) { // 上限保护
        const n = await queryTaskNum(tk, openid, uid);
        if (n <= 0) break;
        adTotal += n;
        const ok = await createPoint(tk, openid, uid, taskPointVal, today, 2);
        if (ok) adOk++;
        await sleep(300);
    }
    console.log(`  广告任务: 成功 ${adOk} 次`);
    log.push(`广告${adOk}次`);

    // 7. 查余额
    await sleep(1000);
    const bal = await queryPoint(tk, openid, uid);
    log.push(`💰余额:${bal}`);

    const res = `账号${idx}: ${log.join(' | ')}`;
    console.log(`\n${res}`);
    return res;
}

(async () => {
    // 1. 自动获取 yyb 存活账号
    let accounts = [];
    try {
        accounts = await yyb.resolveAccounts('WX_ID');
    } catch (e) {
        console.log(`[yyb] 获取账号失败: ${e.message}`);
    }
    if (!accounts.length) {
        console.log('未从 yyb 获取到存活账号');
        return;
    }
    console.log(`共 ${accounts.length} 个账号`);

    const results = [];
    for (let i = 0; i < accounts.length; i++) {
        try {
            results.push(await runAccount(accounts[i], i + 1));
        } catch (e) {
            results.push(`账号${i + 1}: 异常 ${e.message}`);
        }
        await sleep(1000);
    }

    if (sendNotify) await sendNotify('云朵充电统计', results.join('\n'));
})();