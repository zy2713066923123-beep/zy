// cron "34 10,18 * * *"
/*
 * 💊 大参林健康小程序
 * * * 📝 变量说明:
 * 变量名: daslm
 * 值格式: 手机号&mini_token
 * * * 🛠 依赖: npm install axios crypto-js
 */

const axios = require('axios');
const CryptoJS = require('crypto-js');

// ================= 核心配置 =================
const ENV_NAME = 'daslm';        
const SALT = "LYq76ucaPg2nsO7E"; 
const STORE_NO = "2000014533";   // 你的门店ID
const ACTIVITY_ID = "1654405290741305345";
// ===========================================

const commonHeaders = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.65(0x18004132) NetType/WIFI Language/zh_CN",
    "Content-Type": "application/json",
    "Referer": "https://servicewechat.com/wx16ed9a8bbb188228/967/page-frame.html"
};

const waitRandom = (min, max) => new Promise(r => setTimeout(r, Math.floor(Math.random() * (max - min + 1)) + min));
const getTs = () => Math.floor(Date.now() / 1000).toString();
function getSign(mobile, ts) { return CryptoJS.MD5(`${mobile}${ts}${SALT}`).toString(); }

class DSLUser {
    constructor(index, str) {
        this.index = index;
        const parts = str.split('&');
        this.mobile = parts[0];
        this.token = parts[1];
        this.valid = !!(this.mobile && this.token);
        this.logs = [];
    }

    log(msg) { console.log(msg); this.logs.push(msg); }

    // 1. 每日签到
    async sign() {
        const ts = getTs();
        const sign = getSign(this.mobile, ts);
        const url = `https://crmweixin.dslbuy.com/integralmall/userSign/sign.do`;
        const params = { mobile: this.mobile, timestamp: ts, sign: sign, storeNo: STORE_NO, type: "1", mini_token: this.token };
        try {
            const { data } = await axios.get(url, { headers: { ...commonHeaders, Host: 'crmweixin.dslbuy.com' }, params });
            if (data.status === 200) this.log(`✅ [每日签到]: 成功! 积分+${data.data?.integral || 0}`);
            else this.log(`🔵 [每日签到]: ${data.message || '已签到或失败'}`);
        } catch (e) { this.log(`❌ [每日签到]: 请求异常`); }
    }

    // 2. 任务系统 (自动做任务 -> 自动领水)
    async doTasks() {
        this.log(`📋 [任务系统]: 获取列表...`);
        const listUrl = `https://dcapi.dslbuy.com/dc-biz-activity/applet/ginsengTask/userTasks`;
        const params = { activityId: ACTIVITY_ID, storeNo: STORE_NO, type: 1, mini_token: this.token };
        
        try {
            const { data } = await axios.get(listUrl, { headers: { ...commonHeaders, Host: 'dcapi.dslbuy.com' }, params });
            
            if (data.resp_code !== "0000" || !data.datas || !data.datas.userTaskInfos) {
                this.log(`⚠️ [任务列表]: 获取失败 ${data.resp_msg || ''}`);
                return;
            }

            // 只要没做满次数，就去做
            const pendingTasks = data.datas.userTaskInfos.filter(t => t.completeNum < t.timeDripNum);
            
            if (pendingTasks.length === 0) {
                this.log(`✅ [任务系统]: 所有任务已全部完成`);
                return;
            }

            this.log(`🔍 发现 ${pendingTasks.length} 个未完成任务`);

            for (const task of pendingTasks) {
                const needDoCount = task.timeDripNum - task.completeNum;
                this.log(`👉 [执行任务]: ${task.showTaskName} (需执行 ${needDoCount} 次)`);
                
                for(let k=0; k < needDoCount; k++) {
                    // 执行一次任务
                    await this.finishTask(task.taskId, task.showTaskName);
                    // 稍作等待
                    await waitRandom(2000, 3000); 
                }
            }

        } catch (e) {
            console.log(e);
            this.log(`❌ [任务系统]: 异常`);
        }
    }

    // 执行单个任务 (做完任务 -> 拿到ID -> 立即领水)
    async finishTask(taskId, taskName) {
        const url = `https://dcapi.dslbuy.com/dc-biz-activity/applet/gameTask/addTaskRecord?mini_token=${this.token}`;
        const body = { "activityId": ACTIVITY_ID, "taskId": taskId, "storeNo": STORE_NO, "mini_token": this.token };

        try {
            const { data } = await axios.post(url, body, { headers: { ...commonHeaders, Host: 'dcapi.dslbuy.com' } });
            
            if (data.resp_code === "0000") {
                const awardNum = data.datas?.awardNum || 0;
                const recordId = data.datas?.taskRecordId; // 获取生成的记录ID
                
                this.log(`  🎉 [任务完成]: ${taskName} (生成记录: ${recordId})`);
                
                // ★★★ 核心修改: 立即领水 ★★★
                if (recordId) {
                    await this.claimDrip(recordId, awardNum);
                } else {
                    this.log(`  ⚠️ [无法领水]: 未返回 recordId`);
                }

            } else {
                this.log(`  ⚠️ [任务失败]: ${taskName} -> ${data.resp_msg}`);
            }
        } catch (e) {
            this.log(`  ❌ [任务异常]: 网络错误`);
        }
    }

    // 新增: 领取水滴接口 (对应你提供的 getDrip)
    async claimDrip(recordId, num) {
        const url = `https://dcapi.dslbuy.com/dc-biz-activity/applet/ginsengDripRecord/getDrip?mini_token=${this.token}`;
        // 注意: dripRecordIds 是数组格式
        const body = { "dripRecordIds": [recordId], "mini_token": this.token };

        try {
            await waitRandom(500, 1000); // 稍微延迟一下，模拟点击
            const { data } = await axios.post(url, body, { headers: { ...commonHeaders, Host: 'dcapi.dslbuy.com' } });
            
            if (data.resp_code === "0000") {
                this.log(`    💧 [领水成功]: 获得 ${num}g 水滴!`);
            } else {
                this.log(`    ⚠️ [领水失败]: ${data.resp_msg}`);
            }
        } catch (e) {
            this.log(`    ❌ [领水异常]: 请求失败`);
        }
    }

    // 3. 智能浇水
    async startWatering() {
        const infoUrl = `https://dcapi.dslbuy.com/dc-biz-activity/applet/ginsengGameRecord/userLevelInfo?mini_token=${this.token}&activityId=${ACTIVITY_ID}`;
        let times = 0;
        
        try {
            const { data } = await axios.get(infoUrl, { headers: { ...commonHeaders, Host: 'dcapi.dslbuy.com' } });
            if (data.resp_code === "0000" && data.datas) {
                const d = data.datas;
                this.log(`\n🌱 [农场状态]: Lv.${d.level} ${d.levelName} | 当前水量: ${d.dripTotal}g`);
                times = Math.floor(d.dripTotal / 10);
            }
        } catch (e) { return; }

        if (times <= 0) {
            this.log(`🛑 [停止浇水]: 水量不足 10g`);
            return;
        }

        this.log(`🚀 [开始浇水]: 预计 ${times} 次...`);
        const waterUrl = `https://dcapi.dslbuy.com/dc-biz-activity/applet/ginsengDripRecord/watering?mini_token=${this.token}`;
        
        for (let i = 1; i <= times; i++) {
            try {
                await waitRandom(1500, 3000); 
                const { data } = await axios.post(waterUrl, { activityId: ACTIVITY_ID, dripNum: 10, storeNo: STORE_NO, mini_token: this.token }, { headers: { ...commonHeaders, Host: 'dcapi.dslbuy.com' } });
                if (data.code === 200 || data.resp_code === "0000") this.log(`✅ [浇水]: 第 ${i} 次成功`);
                else if ((data.message || "").includes("不足")) { this.log(`🛑 [浇水]: 水量耗尽`); break; }
            } catch (e) { break; }
        }
    }

    async run() {
        if (!this.valid) return;
        this.log(`\n========= 👤 ${this.mobile.replace(/(\d{3})\d{4}(\d{4})/, '$1****$2')} =========`);
        await this.sign();
        await waitRandom(1000, 2000);
        await this.doTasks(); 
        await waitRandom(1000, 2000);
        await this.startWatering();
    }
}

(async () => {
    console.log(`🚀 大参林(Daslm) v3.7 (做一领一版)...`);
    const envStr = process.env[ENV_NAME];
    if (!envStr) { console.log(`❌ 未找到变量 ${ENV_NAME}`); return; }
    const accounts = envStr.split(/[\n@#]/).filter(i => i && i.trim());
    for (let i = 0; i < accounts.length; i++) await new DSLUser(i + 1, accounts[i].trim()).run();
    console.log(`\n🎉 结束`);
})();
