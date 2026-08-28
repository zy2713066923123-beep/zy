require('./yyb.js'); // 自动同步 yyb_go 存活账号
/*
------------------------------------------
@Author: sm (Modified by AI)
@Date: 2024.06.07 19:15
@Description:  
cron: 12 14,02 * * *#Notice:   
米其林会员 每日任务
变量名称：miqilin
⚠️【免责声明】
------------------------------------------
1、此脚本仅用于学习研究，不保证其合法性、准确性、有效性，请根据情况自行判断，本人对此不承担任何保证责任。
2、由于此脚本仅用于学习研究，您必须在下载后 24 小时内将所有内容从您的计算机或手机或任何存储设备中完全删除，若违反规定引起任何事件本人对此均不负责。
3、请勿将此脚本用于任何商业或非法目的，若违反规定请自行对此负责。
4、此脚本涉及应用与本人无关，本人对因此引起的任何隐私泄漏或其他后果不承担任何责任。
5、本人对任何脚本引发的问题概不负责，包括但不限于由脚本错误引起的任何损失和损害。
6、如果任何单位或个人认为此脚本可能涉嫌侵犯其权利，应及时通知并提供身份证明，所有权证明，我们将在收到认证文件确认后删除此脚本。
7、所有直接或间接使用、查看此脚本的人均应该仔细阅读此声明。本人保留随时更改或补充此声明的权利。一旦您使用或复制了此脚本，即视为您已接受此免责声明。

变量：
  WX_SERVER      yyb_go 协议服务地址（例如：http://127.0.0.1:8000）
  WX_ID         (可选白名单) 微信账号，多账号支持换行、& 分隔，留空自动拉取 yyb_go 所有存活账号

WX_ID 格式：
  wxid#备注  多个换行
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
        const list = await global.resolveAccounts(ckName);
        this.userList = list;
        if (!this.userList.length) console.log('未找到环境变量 WX_ID，且 yyb_go 无存活账号');
    }
    wait(time) { return new Promise(resolve => setTimeout(resolve, time)); }
    async done() { try { const notify = require('../sendNotify'); await notify.sendNotify(this.name, this.logs.join('\n')); } catch(e) { console.log('通知发送失败', e); } }
}

const $ = new Env("米其林会员小程序");

let ckName = `miqilin`;
const strSplitor = "#";
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const defaultUserAgent = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.31(0x18001e31) NetType/WIFI Language/zh_CN miniProgram"
let wechat = new WeChatServer({
    url: process.env.WX_SERVER || process.env.WECHAT_SERVER || "http://127.0.0.1:8000",
    appid: 'wx14413dafd16b9540',
    WX_ID: process.env.WX_ID || "",
}
);

global.goodsList = [];

class Task {
    constructor(env) {
        this.index = $.userIdx++
        this.user = env.split(strSplitor);
        this.token = null
        this.wcsid = this.user[0]
        this.isSign = false
        this.points = 0
        this.findBibNum = 0
        this.lastBanner = ""
    }

    loadQuestionBanner() {
        const bannerCacheFile = path.join(__dirname, 'miqilin_banner.json');
        let data = {};
        if (fs.existsSync(bannerCacheFile)) {
            try { data = JSON.parse(fs.readFileSync(bannerCacheFile, 'utf8')); } catch(e){}
        }
        this.lastBanner = data["last_banner"] || "";
    }

    saveQuestionBanner(banner) {
        if (!banner) return;
        const bannerCacheFile = path.join(__dirname, 'miqilin_banner.json');
        let data = {};
        if (fs.existsSync(bannerCacheFile)) {
            try { data = JSON.parse(fs.readFileSync(bannerCacheFile, 'utf8')); } catch(e){}
        }
        if (data["current_banner"] && data["current_banner"] !== banner) {
            data["last_banner"] = data["current_banner"];
            data["current_banner"] = banner;
        } else if (!data["current_banner"]) {
            data["current_banner"] = banner;
            data["last_banner"] = "";
        }
        fs.writeFileSync(bannerCacheFile, JSON.stringify(data));
        this.lastBanner = data["last_banner"];
    }

    async run() {
        //随机延迟5-30s 模拟人工操作
        await $.wait(Math.floor(Math.random() * 20 + 5) * 1000);
        // token 缓存：有效期内复用，避免每次运行都重新取 code（规避微信限流）
        const cached = getCachedToken('michelin', this.wcsid);
        if (cached) {
            this.token = cached.token;
            $.log(`🌸账号[${this.index}] 命中token缓存，跳过取code`)
        } else {
            let { data: codeRes } = await wechat.getCode(this.wcsid)
            if (codeRes.status) {
                await this.getUserToken(codeRes.data.code)
            }
            if (this.token) {
                saveCachedToken('michelin', this.wcsid, this.token);
            }
        }
        if (!this.token) {
            $.log(`账号[${this.index}] 获取用户Token失败❌`)
            return
        }
        this.token = 'Bearer ' + this.token
        this.loadQuestionBanner()

        await this.getUserInfo()
        $.log(`执行前积分：${this.points}`)

        await this.doPaper()
        await this.doLuckDraw()
        await this.doFindBib()
        await this.doShare()
        
        await this.getUserInfo()
        $.log(`执行后积分：${this.points}`)

        await this.getOrders()
        await this.getGoods()
    }
    
    async doShare() {
        while (true) {
            await this.share();
            await $.wait(1000);
            let shareCount = await this.sharePoints();
            if (shareCount === 0) {
                break;
            }
            await $.wait(2000);
        }
    }

    async share() {
        const options = {
            method: 'POST',
            url: `https://ulp.michelin.com.cn/op/points/share/have`,
            headers: {
                "Host": "ulp.michelin.com.cn",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.31(0x18001f37) NetType/WIFI Language/zh_CN",
                "Authorization": this.token,
            },
            data: { "type": "ARTICLE", "code": "COM-MHT-93" }
        };
        try {
            let { data: result } = await axios.request(options);
            $.log(`转发:${result?.code != 200 ? "转发失败" + (result?.message||'') : "转发成功!"}`)
        } catch (e) {
            $.log(`转发异常`)
        }
    }

    async sharePoints() {
        const options = {
            method: 'GET',
            url: `https://ulp.michelin.com.cn/membership/member/points/toast`,
            headers: {
                "Host": "ulp.michelin.com.cn",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.31(0x18001f37) NetType/WIFI Language/zh_CN",
                "Authorization": this.token,
            }
        };
        try {
            let { data: rs } = await axios.request(options);
            if (rs.code === 200 && rs.data) {
                for (let item of rs.data) {
                    $.log(`${item.name},获得${item.points}积分`);
                }
                return rs.data.length || 0;
            }
        } catch(e) {}
        return 0;
    }

    async doFindBib() {
        while (true) {
            if (this.findBibNum > 10) break;
            if (await this.findBib()) {
                await $.wait(1000);
            } else {
                break;
            }
        }
    }

    async findBib() {
        const latitude = 23.70556;
        const longitude = 102.49621;
        const options = {
            method: 'GET',
            url: `https://ulp.michelin.com.cn/campaign/findbib/luckydraw/BIB_2022?latitude=${latitude}&longitude=${longitude}`,
            headers: {
                "Host": "ulp.michelin.com.cn",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.31(0x18001f37) NetType/WIFI Language/zh_CN",
                "Authorization": this.token,
            }
        };
        try {
            let { data: rs } = await axios.request(options);
            if (rs.code === 200) {
                if (rs.data.prizeType === "POINTS") {
                    $.log(`[寻找米其林先生]积分:${rs.data.benefit.name}`);
                    this.findBibNum = 0;
                } else if (rs.data.prizeType === "KNWL_CARD") {
                    $.log(`[寻找米其林先生]知识卡:${rs.data.benefit.name}`);
                    this.findBibNum += 1;
                } else if (rs.data.prizeType === "BIB_CARD") {
                    $.log(`[寻找米其林先生]卡片:${rs.data.benefit.name}`);
                    this.findBibNum = 0;
                } else if (rs.data.prizeType === "EC_COUPON") {
                    $.log(`[寻找米其林先生]优惠券:${rs.data.benefit.name}`);
                    this.findBibNum = 0;
                } else {
                    let prizeType = rs.data.prizeType;
                    $.log(`[寻找米其林先生]${prizeType}:${rs.data.benefit.name}`);
                    this.findBibNum = 0;
                }
                return true;
            } else {
                $.log(`寻找米其林先生结束：${rs.message}`);
                return false;
            }
        } catch(e) {
            $.log(`寻找米其林先生请求失败`);
            return false;
        }
    }

    async qualify(lastBanner) {
        const PAPERID = "7391689672818298880";
        const options = {
            method: 'GET',
            url: `https://ulp.michelin.com.cn/campaign/paper/lukcydraw/qualify/${lastBanner}?ulpUserPaperId=${PAPERID}&paperCode=${lastBanner}`,
            headers: {
                "Host": "ulp.michelin.com.cn",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.65(0x18004130) NetType/WIFI Language/zh_CN",
                "Authorization": this.token,
            }
        };
        try {
            await axios.request(options);
        } catch(e) {}
    }

    async stage() {
        if (!this.lastBanner) {
            return { banner: "", status: false };
        }
        const options = {
            method: 'GET',
            url: `https://ulp.michelin.com.cn/campaign/stage/${this.lastBanner}`,
            headers: {
                "Host": "ulp.michelin.com.cn",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.31(0x18001f37) NetType/WIFI Language/zh_CN",
                "Authorization": this.token,
            }
        };
        try {
            let { data: rs } = await axios.request(options);
            if (rs.code === 200) {
                if (rs.data.campaign && rs.data.campaign.status === "ONGOING" && rs.data.prizeEarned === false && parseInt(rs.data.remainCount) > 0) {
                    return { banner: this.lastBanner, status: true };
                }
            }
            return { banner: this.lastBanner, status: false };
        } catch(e) {
            return { banner: this.lastBanner, status: false };
        }
    }

    async luckDraw(banner) {
        const options = {
            method: 'GET',
            url: `https://ulp.michelin.com.cn/campaign/stage/luckydraw/${banner}`,
            headers: {
                "Host": "ulp.michelin.com.cn",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.31(0x18001f37) NetType/WIFI Language/zh_CN",
                "Authorization": this.token,
            }
        };
        try {
            let { data: rs } = await axios.request(options);
            if (rs.code === 200) {
                $.log(`上期问答挑战抽奖获得：${rs.data.name}`);
            } else {
                $.log(`上期问答挑战抽奖结束/失败`);
            }
        } catch(e) {}
    }

    async doLuckDraw() {
        if (!this.lastBanner) {
            $.log("未找到上期问答挑战活动banner，跳过抽奖");
            return;
        }
        await this.qualify(this.lastBanner);
        let { banner, status } = await this.stage();
        if (status) {
            $.log("开始上期问答挑战抽奖");
            await this.luckDraw(banner);
        }
    }

    async getOrders() {
        const options = {
            method: 'GET',
            url: `https://ulp.michelin.com.cn/op/orders`,
            headers: {
                "Host": "ulp.michelin.com.cn",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781 NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/50249",
                "Authorization": this.token,
            }
        };
        try {
            let { data: rs } = await axios.request(options);
            if (rs.code === 200 && rs.data && rs.data.length > 0) {
                const orderStatus = {
                    "TO_BE_SEND": "待发货",
                    "TO_BE_RECEIVED": "待收货"
                };
                let orderIndex = 1;
                let found = false;
                for (let order of rs.data) {
                    if (orderStatus[order.status]) {
                        found = true;
                        $.log(`订单【${orderIndex}】`);
                        $.log(`下单时间：${order.orderTime}`);
                        $.log(`订单状态：${orderStatus[order.status]}`);
                        for (let orderGoods of order.items) {
                            $.log(`商品名：${orderGoods.name}`);
                        }
                        orderIndex++;
                    }
                }
                if (!found) $.log('未查询到待发货或待收货订单');
            } else {
                $.log('未查询到订单');
            }
        } catch(e) {
            $.log(`查询订单失败`);
        }
    }

    async getGoods() {
        const options = {
            method: 'POST',
            url: `https://ulp.michelin.com.cn/op/points/product/search`,
            headers: {
                "Host": "ulp.michelin.com.cn",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781 NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/50249",
                "Authorization": this.token,
            },
            data: {
                "premium": "N",
                "category": null,
                "endPrice": null,
                "page": 1,
                "pageSize": 50,
                "startPrice": null,
                "type": "GOODS"
            }
        };
        try {
            let { data: rs } = await axios.request(options);
            if (rs.code === 200 && rs.data && rs.data.records) {
                global.goodsList = global.goodsList || [];
                if (global.goodsList.length === 0) {
                    for (let goods of rs.data.records) {
                        if (goods.status === "AVAILABLE") {
                            global.goodsList.push({ name: goods.name, price: goods.price });
                        }
                    }
                }
            }
        } catch(e) { }
    }

    async getUserToken(code) {
        let options = {
            method: 'GET',
            url: `https://ulp.michelin.com.cn/bff/wechat/login/${code}`,
            headers: {
                "Host": "ulp.michelin.com.cn",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.31(0x18001f37) NetType/WIFI Language/zh_CN",
                "Referer": "https://servicewechat.com/wx14413dafd16b9540/130/page-frame.html"
            }

        }
        let {
            data: result
        } = await axios.request(options);

        this.token = result?.data?.token?.access_token;
        $.log(`🌸账号[${this.index}] 获取用户Token成功:${this.token}`)

    }

    async getUserInfo() {
        try {
            let { data: result } = await axios.request({
                method: 'GET',
                url: `https://ulp.michelin.com.cn/bff/profile`,
                headers: {
                    "Host": "ulp.michelin.com.cn",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781 NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/50249",
                    "Authorization": this.token,
                }
            });


            if (result?.data?.points) {
                this.points = result.data.points;
            }
        } catch (e) {
            this.ckStatus = false;
        }
    }
    async doPaper() {
        //获取问卷
        await this.getPaper();
        //是否已完成问卷
        if (this.paperStatus) {
            //获取本期问卷题目
            await this.getOpenTpaper(this.npsPaperCode);
            let index = 1;
            for (let question of this.questionList) {
                $.log(`问题${index}:${question?.questionChoise?.stemHtml}\n`);
                let options = question?.questionChoise.options;
                for (let option of options) {
                    $.log(`- ${option.optionHtml}`);
                }
                let theQuestion = question.questionChoise.npsQuestionPk;
                //查找对应题目答案
                let detail = this.stdAnswers.find(answer => theQuestion == answer.npsQuestionChoisePk) || {};
                let answer = options.find(o => o.npsQuestionChoiseOptionPk == detail.npsQuestionChoiseOptionPk);
                if (!answer) answer = options[0]; // 如果没有找到匹配的答案，默认选择第一个选项
                //提交答案
                let answerRes = await this.answer(theQuestion, answer?.npsQuestionChoiseOptionPk);
                $.log(`\n答案: ${answer.optionHtml} => ${answerRes}`);
            }
            //提交问卷
            await this.paperScore(this.paperCode);
        } else {
            $.log(`答题任务:本周奖励领取已达到上限，跳过执行`);
        }
    }

    //获取本期答卷
    async getPaper() {

        const options = {
            method: 'POST',
            url: `https://ulp.michelin.com.cn/campaign/paper/user`,
            headers: {
                "Host": "ulp.michelin.com.cn",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781 NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/50249",
                "Authorization": this.token,
            },
            data: {}
        };

        let { data: result } = await axios.request(options);
        if (result?.code == 200) {
            $.log(`帐号[${this.index}]本次调查问卷为${result?.data?.npsPaperCode}，总共${result?.data?.questionNum}道题目,状态为${result?.data?.status}`);
            //如果已经答题，则跳过执行答题任务
            if (result?.data?.status == 'DONE') this.paperStatus = false;
            else this.paperStatus = true;
            //获取本期问卷期数
            this.npsPaperCode = result?.data?.npsPaperCode;
            //获取本期问卷验证编号
            this.paperCode = result?.data?.paperCode;
            this.saveQuestionBanner(this.paperCode);
        } else {
            this.ckStatus = false;
        }

    }
    //获取问卷题目
    async getOpenTpaper(npsPaperCode) {

        let options = {
            method: 'GET',
            url: `https://ulp.michelin.com.cn/npspaper/nps-admin/open/api/cp/public/get_open_tpaper/${npsPaperCode}`,
            headers: {
                "Host": "ulp.michelin.com.cn",
                "User-Agent": "",
                "Authorization": this.token,
            }
        }

        //post方法
        let result = await axios.request(options);
        if (result?.data?.success || result?.data?.code == 200 || (result?.data && result?.data?.stdAnswers)) {
            let dat = result.data.data ? result.data.data : result.data;
            //答案
            this.stdAnswers = dat?.stdAnswers || [];
            //题目
            this.questionList = dat?.questionList || [];
        } else {
            $.log(`🔴帐号[${this.index}]获取问卷列表失败！${result?.data?.message || ''}`)
        }

    }

    async answer(question, answer) {
        try {
            const options = {
                url: `https://ulp.michelin.com.cn/campaign/paper/user/answer`,
                method: 'POST',
                headers: {
                    "Host": "ulp.michelin.com.cn",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781 NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/50249",
                    "Authorization": this.token,
                },
                data: { "answerOptionId": [`${answer}`], "paperCode": `${this.paperCode}`, "questionId": `${question}` }
            };
            //post方法
            let { data: result } = await axios.request(options);
            return result?.code == 200 ? "回答成功！" : `回答失败！${result?.message}`
        } catch (e) {
            console.log(`❌回答问题失败！原因为:${e}`);
        }
    }

    async paperScore(paperCode) {
        try {
            const options = {
                url: `https://ulp.michelin.com.cn/campaign/paper/score/${paperCode}`,
                method: 'POST',
                headers: {
                    "Host": "ulp.michelin.com.cn",
                    "Authorization": this.token,
                },
                data: {}
            };
            //post方法
            let { data: res } = await axios.request(options);
            $.log(`提交问卷:本期问卷正确率为${res?.data?.score}%,排名${res?.data?.rank}`);
        } catch (e) {
            console.log(`❌提交问卷失败！原因为:${e}`);
        }
    }

}

!(async () => {
    await getNotice()
    await $.checkEnv(ckName);
    if ($.userList && $.userList.length) {
        for (let user of $.userList) {
            await new Task(user).run();
        }
        
        if (global.goodsList && global.goodsList.length > 0) {
            $.log(`\n----------- 🎊 可兑换商品 🎊 -----------`);
            for (let goods of global.goodsList) {
                $.log(`[${goods.price}积分] ${goods.name}`);
            }
        }
    } else {

        $.log(`${ckName}未配置微信SERVER配置 搭建可看仓库目录下的readme.md❌`)
        return
    }

})()
    .catch((e) => console.log(e))
    .finally(() => $.done());

async function getNotice() {
    try {
        let options = {
            url: `https://ghproxy.net/https://raw.githubusercontent.com/smallfawn/Note/refs/heads/main/Notice.json`,
            headers: {
                "User-Agent": defaultUserAgent,
            },
            timeout: 3000
        }
        let {
            data: res
        } = await axios.request(options);
        $.log(res)
        return res
    } catch (e) { }

}