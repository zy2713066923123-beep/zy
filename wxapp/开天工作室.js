require('./yyb.js'); // 自动同步 yyb_go 存活账号
/**
 * #小程序://开天工作室/cBFFdQoybN35EEh
 *
 * 抓包 Host：https://api.box.vipinfinity.com 获取请求头 Authorization 的值
 * export KTGZS_TOKEN = 'vqGjEixxxxx'
 * 多账号用 & 或换行
 *
 * @author Telegram@sudojia
 * @site https://blog.imzjw.cn
 * @date 2024/08/19
 *
 * 变量名：KTGZS_TOKEN
 * cron: 44 10,22 * * * */
const axios = require('axios');

// ---- 轻量运行时（替代 ../utils/initScript）----
class Env {
    constructor(name) {
        this.name = name;
        this.logs = [];
    }
    log(...args) {
        console.log(...args);
        this.logs.push(args.join(' '));
    }
    logErr(e) {
        const msg = (e && (e.message || e.stack)) || String(e);
        console.error(msg);
        this.logs.push(msg);
    }
    wait(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }
    async done() {
        try {
            await notify.sendNotify(`「${this.name}」`, this.logs.join('\n'));
        } catch (e) {
            console.log('通知发送失败', e.message || e);
        }
    }
}

const UA_LIST = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.10 MiniProgramEnv/Windows WindowsWechat/WMPF',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49(0x18003128) NetType/WIFI Language/zh_CN',
];

const sudojia = {
    getRandomUserAgent() {
        return UA_LIST[Math.floor(Math.random() * UA_LIST.length)];
    },
    getRandomWait(min, max) {
        return Math.floor(Math.random() * (max - min + 1)) + min;
    },
    async sendRequest(url, method = 'get', headers = {}, data = undefined) {
        const resp = await axios.request({
            url,
            method,
            headers,
            data,
            timeout: 15000,
            validateStatus: () => true,
        });
        return resp.data;
    },
};

const notify = require('../sendNotify');
// 原脚本的 checkUpdate 在本项目不适用，置为空操作
async function checkUpdate() {}

const $ = new Env('开天工作室');
// ----------------------------------------------

const ktgzsList = process.env.KTGZS_TOKEN ? process.env.KTGZS_TOKEN.split(/[\n&]/).map((v) => v.trim()).filter(Boolean) : [];
let message = '';
// 接口地址
const baseUrl = 'https://api.box.vipinfinity.com'
// 请求头
const headers = {
    'User-Agent': sudojia.getRandomUserAgent(),
    'Accept-Encoding': 'gzip, deflate, br',
    'Client-Name': 'default',
    'Referer': 'https://servicewechat.com/wxa1ff7cf5ddff1da2/9/page-frame.html',
    'Client-Type': 'wechat--miniapp-windows',
    'Content-Type': 'application/json',
    'Accept': '*/*',
    'Host': 'api.box.vipinfinity.com',
};

!(async () => {
    if (!ktgzsList.length) {
        return $.log('未找到环境变量 KTGZS_TOKEN');
    }
    await checkUpdate($.name, ktgzsList);
    console.log(`\n已随机分配 User-Agent\n\n${headers['user-agent'] || headers['User-Agent']}`);
    for (let i = 0; i < ktgzsList.length; i++) {
        const index = i + 1;
        headers.Authorization = ktgzsList[i];
        console.log(`\n*****第[${index}]个${$.name}账号*****`);
        message += `📣====${$.name}账号[${index}]====📣\n`;
        await $.wait(sudojia.getRandomWait(800, 1200));
        await main();
        await $.wait(sudojia.getRandomWait(2000, 2500));
    }
    if (message) {
        await notify.sendNotify(`「${$.name}」`, `${message}`);
    }
})().catch((e) => $.logErr(e)).finally(() => $.done());

async function main() {
    await getUserInfo();
    await $.wait(sudojia.getRandomWait(1000, 1500));
    await sign();
    await $.wait(sudojia.getRandomWait(1000, 1500));
    await pointsInfo();
}

/**
 * 获取用户信息
 *
 * @return {Promise<void>}
 */
async function getUserInfo() {
    try {
        const data = await sudojia.sendRequest(`${baseUrl}/user`, 'get', headers);
        if (0 !== data.code) {
            return $.log(data.message);
        }
        const {name, phone} = data.data.user
        console.log(`${name}(${phone})`);
        message += `${name}(${phone})\n`;
    } catch (e) {
        console.error(`获取用户信息时发生异常：`, e.response ? e.response.data : (e.message || e));
    }
}

/**
 * 签到
 * @return {Promise<void>}
 */
async function sign() {
    try {
        const data = await sudojia.sendRequest(`${baseUrl}/sign-in`, 'post', headers);
        if (0 !== data.code) {
            return $.log(data.message);
        }
        const {continuous_days, award_score} = data.data;
        console.log(`签到成功，积分+${award_score}`);
        console.log(`已连续签到${continuous_days}天`);
        message += `签到成功\n已连续签到${continuous_days}天\n`;
    } catch (e) {
        console.error(`签到时发生异常：`, e.response ? e.response.data : (e.message || e));
    }
}

/**
 * 查询积分
 *
 * @return {Promise<void>}
 */
async function pointsInfo() {
    try {
        const data = await sudojia.sendRequest(`${baseUrl}/asset-records/score?page=1&per_page=20`, 'get', headers);
        if (0 !== data.code) {
            return $.log(data.message);
        }
        console.log(`当前积分：${data.data.list[0].after}`);
        message += `当前积分：${data.data.list[0].after}\n\n`;
    } catch (e) {
        console.error(`积分查询时发生异常：`, e.response ? e.response.data : (e.message || e));
    }
}