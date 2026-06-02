
const { getSingleCode } = require('./getCode.js');
class WeChatServer {
    constructor(config) { this.config = config; }
    async getCode(wxid) {
        try {
            const actualWxid = String(wxid).split('#')[0].trim();
            const code = await getSingleCode(this.config.appid, actualWxid);
            return { data: { code, data: { code } } };
        } catch (e) {
            return { data: {} };
        }
    }
}

class Env {
    constructor(name) { this.name = name; this.userList = []; this.userIdx = 1; this.logs = []; const originalLog = console.log; console.log = (...args) => { this.logs.push(args.join(" ")); originalLog.apply(console, args); }; }
    log(...args) { console.log(...args); this.logs.push(args.join(" ")); }
    checkEnv(ckName) {
        const val = process.env.WX_ID || process.env[ckName];
        if (val) this.userList = val.split(/[\n&]+/).map(v => String(v).split('#')[0].trim()).filter(Boolean);
        else console.log('未找到环境变量 WX_ID');
    }
    wait(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
    uuid() { return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) { var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8); return v.toString(16); }); }
    time(fmt) { let date = new Date(); let o = { "M+": date.getMonth() + 1, "d+": date.getDate() }; if (/(y+)/.test(fmt)) fmt = fmt.replace(RegExp.$1, (date.getFullYear() + "").substr(4 - RegExp.$1.length)); for (let k in o) if (new RegExp("(" + k + ")").test(fmt)) fmt = fmt.replace(RegExp.$1, (RegExp.$1.length === 1) ? (o[k]) : (("00" + o[k]).substr(("" + o[k]).length))); return fmt; }
    async done() { try { const notify = require('./sendNotify'); await notify.sendNotify(this.name, this.logs.join('\n')); } catch(e) { console.log('通知发送失败', e); } }
}


/*
------------------------------------------
@Author: sm
@Date: 2024.06.07 19:15
@Description:  
cron: 30 9 * * 1
------------------------------------------
#Notice:   
谷雨 微信小程序 签到得积分 
变量名称：guyu 名字 授权中心 里面的openid 多个账号用&分割
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
  WECHAT_SERVER  微信协议服务地址，默认 http://192.168.6.222:8011
  WX_ID         微信账号，多账号支持换行、& 分隔，必须配置

WX_ID 格式：
  wxid#备注  多个换行
*/


const $ = new Env("谷雨小程序");

let ckName = `guyu`;
const strSplitor = "#";
const axios = require("axios");
const defaultUserAgent = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.31(0x18001e31) NetType/WIFI Language/zh_CN miniProgram"
let wechat = new WeChatServer({
    url: process.env.WECHAT_SERVER || "http://192.168.6.222:8011",
    appid: 'wxda948f3be0afc375',
    WX_ID: process.env.WX_ID || "",

}
);

class Task {
    constructor(env) {
        this.index = $.userIdx++
        this.user = env.split(strSplitor);
        this.token = null
        this.wcsid = this.user[0]
        this.isSign = false
    }

    async run() {
        //随机延迟5-30s 模拟人工操作
        await $.wait(Math.floor(Math.random() * 20 + 5) * 1000);
        let { data: codeRes } = await wechat.getCode(this.wcsid)
        if (codeRes.status) {
            await this.getUserToken(codeRes.data.code)
        }
        if (!this.token) {
            $.log(`账号[${this.index}] 获取用户Token失败❌`)
            return
        }
        await this.signIn()
        await this.getUserPoints()
    }
    async getUserToken(code) {
        let data = JSON.stringify({
            "code": "" + code,
            "appid": "wxda948f3be0afc375",
            "shopId": null,
            "envVersion": "release",
            "isEnterpriseWx": false,
            "scene": 1168,
            "referrerInfo": {
                "appId": "wxda948f3be0afc375"
            }
        });

        let options = {
            method: 'POST',
            url: 'https://mall-mobile-v6.vecrp.com/mobile/wxAppLogin',
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781 NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/50249',
                'Content-Type': 'application/json;charset=UTF-8',
                'xweb_xhr': '1',
                'appid': 'wxda948f3be0afc375',
                'token': '',
                'Sec-Fetch-Site': 'cross-site',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Referer': 'https://servicewechat.com/wxda948f3be0afc375/65/page-frame.html',
                'Accept-Language': 'zh-CN,zh;q=0.9'
            },
            data: data
        };

        let {
            data: result
        } = await axios.request(options);
        console.log(result);

        if (result?.success) {
            this.token = result.result.mobileToken
            $.log(`🌸账号[${this.index}] 获取用户Token成功:${this.token}`)
        } else {
            $.log(`🌸账号[${this.index}] 获取用户Token-失败:${result.message}❌`)
        }
    }
    sha1(str) {
        return require("crypto").createHash("sha1").update(str).digest("hex");
    }
    request(options) {

        var sign,
            n = void 0
            , d = {},
            l = "R6WbJ830wNsEdjH9GumwKYiYxHz0K9QD",
            n = (new Date).getTime(),
            d = "post" === options.method || "POST" === options.method ? {
                body: JSON.stringify(options.data),
                secretKey: l,
                ts: n
            } : Object.assign({}, options.params, {
                secretKey: l,
                ts: n
            }),
            sign = this.sha1(function (e) {
                var t, a = [];
                for (t in e) {
                    var r = t + e[t];
                    a.push(r)
                }
                a.sort();
                var u = "";
                return a.map((function (e) {
                    "" === u ? u = e : u += e
                }
                )),
                    u
            }(d))
        let baseHeaders = {
            host: "mall-mobile-v6.vecrp.com",
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9",
            "appid": "wxda948f3be0afc375",
            "content-type": "application/json;charset=UTF-8",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254173b) XWEB/19027",
            "sign": "" + sign,
            "starttime": "" + n,
            "token": "" + this.token,
            "ts": "" + n,
            "x-tracedid": "" + $.uuid(),
            "xweb_xhr": "1",
            "Referer": "https://servicewechat.com/wxda948f3be0afc375/65/page-frame.html",
        }
        options.headers = Object.assign(options.headers, baseHeaders)

        return axios.request(options)
    }
    async signIn() {
        let options = {
            method: 'POST',
            url: `https://mall-mobile-v6.vecrp.com/mobile/activity/sign/sign`,

            headers: {},
            data: {
                activityId: 'cdd30467-abb8-4944-8941-2879aa950a86',
                shopId: '100186753',
                signDate: $.time(`yyyy-M-dd`),
            }

        };
        let {
            data: result
        } = await this.request(options);
        if (result?.success) {
            //打印签到结果
            $.log(`🌸账号[${this.index}]` + `签到成功`);
        } else {
            $.log(`🌸账号[${this.index}] 签到-失败:${result.msg}❌`)
        }




    }
    async getUserPoints() {
        let options = {
            method: 'GET',
            url: `https://mall-mobile-v6.vecrp.com/mobile/customer/getMyAllPoint`,
            params: {
                shopId: '100186753'
            },
            headers: {},

        }
        let {
            data: result
        } = await this.request(options);
        if (result?.success) {
            $.log(`账号[${this.index}]` + `积分:${result.result[0].score}`);
        } else {
            $.log(`账号[${this.index}] 获取积分-失败:${result.msg}❌`)
        }
    }








}

!(async () => {
    await getNotice()
    $.checkEnv(ckName);
    if (process.env['WX_ID'] || $.userList.length > 0) {
        for (let user of $.userList) {
            await new Task(user).run();
        }
    } else {
        $.log(`${ckName}未配置WX_ID配置❌`)
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
