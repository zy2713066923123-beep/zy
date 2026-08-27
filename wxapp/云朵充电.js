require('./yyb.js'); // 自动同步 yyb_go 存活账号
/*
cron: 24 07,19 * * *name: 云朵充电
变量: YUNDUO_TOKEN
值格式: 仅Token 或 Token&OpenID
*/

const axios = require('axios');
const { sendNotify } = require('../sendNotify');

const ENV_NAME = 'YUNDUO_TOKEN';
const DEFAULT_OPENID = 'ob_EJ5WQ_4KSkgjdWIzuPZXRYCa4';

// ================= 任务配置 =================
// 格式: { id: 任务ID, count: 次数, name: 日志名 }
const TASKS = [
    { id: 2, count: 10, name: "任务2" },
    { id: 3, count: 10, name: "任务3" },
    { id: 4, count: 1,  name: "任务4" },
    { id: 5, count: 1,  name: "任务5" },
    { id: 6, count: 1,  name: "任务6" },
    { id: 7, count: 1,  name: "任务7" },
    { id: 8, count: 50, name: "任务8" },
    { id: 9, count: 50, name: "任务9" }
];
// ===========================================

const tokens = process.env[ENV_NAME] ? process.env[ENV_NAME].split(/[\n&]/) : [];
const getToday = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
const getUid = (tk) => { try { return Number(JSON.parse(Buffer.from(tk.split('.')[1], 'base64').toString()).aud.split('_')[1]); } catch { return null; } };

const getHeaders = (tk, openid) => ({
    'content-type': 'application/json',
    'Host': 'api.szyunduo.cn',
    'x-giklinks-wx-miniprogram-openid': openid,
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.66(0x1800422e) NetType/WIFI Language/zh_CN',
    'xy-consumer-token': tk
});

// 通用请求
async function req(uid, tk, openid, source) {
    try {
        const res = await axios.post(
            `https://api.szyunduo.cn/consumer-service/v1/mgr/consumerPoint/createPointLog`,
            { "consumerId": uid, "point": 10, "pointWeek": getToday(), "pointSource": source, "type": "income" },
            { headers: getHeaders(tk, openid) }
        );
        return res.data.code === "000000";
    } catch { return false; }
}

// 批量执行器
async function runBatch(uid, tk, openid) {
    let log = [];
    console.log(`🚀 开始执行批量任务...`);
    
    for (const task of TASKS) {
        let success = 0;
        process.stdout.write(`   ${task.name}(${task.id}): `);
        
        for (let i = 0; i < task.count; i++) {
            const isOk = await req(uid, tk, openid, task.id);
            if (isOk) success++;
            await new Promise(r => setTimeout(r, 200)); // 间隔0.2秒
        }
        
        console.log(`${success}/${task.count}`);
        log.push(`Src${task.id}:${success}/${task.count}`);
    }
    return log.join(' ');
}

// 查余额
async function query(uid, tk, openid) {
    try {
        const res = await axios.get(`https://api.szyunduo.cn/consumer-service/v1/mgr/consumerPoint/getConsumerPoint/${uid}`, { headers: getHeaders(tk, openid) });
        return (res.data.code === "000000" && res.data.data) ? (res.data.data.points || 0) : "Fail";
    } catch { return "Err"; }
}

(async () => {
    if (!tokens.length) return console.log(`未找到 ${ENV_NAME}`);
    let msg = [];
    console.log(`共 ${tokens.length} 个账号`);

    for (let i = 0; i < tokens.length; i++) {
        const raw = tokens[i].trim();
        if (!raw) continue;
        const [tk, oid] = raw.includes('&') ? raw.split('&') : [raw, DEFAULT_OPENID];
        const uid = getUid(tk);

        if (!uid) { msg.push(`账号${i+1}: Token无效`); continue; }
        
        console.log(`\n========== 账号${i+1} (ID:${uid}) ==========`);
        
        // 1. 签到 (Source 1)
        const s1 = await req(uid, tk, oid, 1);
        console.log(`📅 签到: ${s1 ? '成功' : '已签或失败'}`);

        // 2. 跑任务
        const taskLog = await runBatch(uid, tk, oid);

        // 3. 查分
        await new Promise(r => setTimeout(r, 1000));
        const bal = await query(uid, tk, oid);
        
        const res = `账号${i+1}: 签到${s1?'✅':'⛔'} | ${taskLog} | 💰余额:${bal}`;
        console.log(`\n${res}`);
        msg.push(res);
    }

    if (sendNotify) await sendNotify('云朵任务统计', msg.join('\n'));
})();