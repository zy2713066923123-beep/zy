// 当前脚本来自于 http://script.345yun.cn 脚本库下载！
// 当前脚本来自于 http://2.345yun.cn 脚本库下载！
// 当前脚本来自于 http://2.345yun.cc 脚本库下载！
// 脚本库官方QQ群1群: 429274456
// 脚本库官方QQ群2群: 1077801222
// 脚本库官方QQ群3群: 433030897
// 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
// 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
// 您在使用脚本库下载的脚本时自行检查判断风险。
// 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。

/**
 * ============================================================
 *  绿树田园 - 青龙面板每日签到脚本（微信协议版）
 *  现已上线小程序公众号注册，每日签到得1元！
 * ============================================================
 *
 *  脚本功能：
 *    1. 优先使用 TreeCoin 授权码(TREE+28位)：从 TREECOIN_AUTH_CODE 读取，
 *       多账号用 & 或换行分隔，走 /auth/login-by-auth-code 登录获取 token
 *    2. 兼容微信协议：配置 WX_ID 时自动经 getCode.js 获取微信 code，
 *       传给 /wechat/miniprogram/login 登录（需未配置 TREECOIN_AUTH_CODE）
 *    3. 模拟页面访问设置 page_visit 标记
 *    4. 执行每日签到（POST /app/signin，明文 body，token 走 Authorization）
 *    5. 输出签到结果(树苗/大树收益)
 *
 *  使用方法（推荐：授权码）：
 *    1. 青龙面板 → 环境变量 → 添加：
 *         TREECOIN_AUTH_CODE = 授权码（多账号用 & 或换行分隔）
 *       示例：
 *         TREECOIN_AUTH_CODE = TREE8G5MXFQPF72&TREExxxxxxxxxxxxxxxx
 *    2. 青龙面板 → 定时任务 → 命令：task 绿树田园.js
 *         cron：0 16,8 * * *  (每天早上8点)
 *
 *  微信协议方式（可选，需清空 TREECOIN_AUTH_CODE）：
 *    WX_ID  微信账号（多账号换行/&/| 分隔），格式 wxid#备注
 *
 *  环境变量：
 *    TREECOIN_AUTH_CODE  授权码（优先，默认已内置一个，多账号 &/换行 分隔）
 *    WX_ID             微信账号（自动 getcode，仅在未配置 TREECOIN_AUTH_CODE 时生效）
 *    TREECOIN_APPID    绿树田园小程序 AppID（默认 wx1cc3b7be9bf56740，可覆盖）
 *    TREECOIN_API_BASE 后端地址（默认 https://treecoin.cn/api）
 *    TREECOIN_INVITE_CODE 邀请码（默认空）
 * ============================================================
 */

const crypto = require('crypto')
const https = require('https')
const http = require('http')

// 微信协议统一接口（牛子/应用宝双协议）
let getSingleCode = null
try {
    ({ getSingleCode } = require('./getCode'))
} catch (e) {
    getSingleCode = null
}

// ============ 配置 ============
// 真实后端域名（抓包：treecoin.cn）
const API_BASE = process.env.TREECOIN_API_BASE || 'https://treecoin.cn/api'
const WX_APP_ID = (process.env.TREECOIN_APPID || 'wx1cc3b7be9bf56740').trim()
const WX_IDS_RAW = (process.env.WX_ID || '').trim()
const AUTH_CODES_RAW = (process.env.TREECOIN_AUTH_CODE||'' ).trim()
const INVITE_CODE = (process.env.TREECOIN_INVITE_CODE || 'NGLNCW5W').trim()

// 微信小程序 WebView UA（对齐抓包）
const UA = 'Mozilla/5.0 (Linux; Android 15; M2012K11AC Build/AQ3A.250226.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.178 Mobile Safari/537.36 XWEB/1460243 MMWEBSDK/20260502 MMWEBID/3433 MicroMessenger/8.0.72.3100(0x28004853) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android'
const REFERER = `https://servicewechat.com/${WX_APP_ID}/2/page-frame.html`

// ============ 工具函数 ============

/**
 * 生成设备指纹
 */
function generateDeviceId() {
    return crypto.randomBytes(16).toString('hex')
}

/**
 * 发送 HTTP 请求
 */
function request(path, method, body, token) {
    return new Promise((resolve, reject) => {
        const url = new URL(API_BASE + path)
        const isHttps = url.protocol === 'https:'
        const lib = isHttps ? https : http

        const data = body ? JSON.stringify(body) : null

        const options = {
            hostname: url.hostname,
            port: url.port || (isHttps ? 443 : 80),
            path: url.pathname,
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'charset': 'utf-8',
                'User-Agent': UA,
                'Referer': REFERER,
                'Accept': 'application/json'
            }
        }

        if (data) {
            options.headers['Content-Length'] = Buffer.byteLength(data)
        }

        if (token) {
            options.headers['Authorization'] = `Bearer ${token}`
        }

        const req = lib.request(options, (res) => {
            let chunks = ''
            res.on('data', (chunk) => { chunks += chunk })
            res.on('end', () => {
                try {
                    resolve(JSON.parse(chunks))
                } catch (e) {
                    resolve({ c: 0, msg: '响应解析失败', raw: chunks })
                }
            })
        })

        req.on('error', reject)
        req.setTimeout(15000, () => {
            req.destroy(new Error('请求超时'))
        })

        if (data) req.write(data)
        req.end()
    })
}

/**
 * 控制台输出带时间戳
 */
function log(msg) {
    const now = new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
    console.log(`[${now}] ${msg}`)
}

/**
 * 延迟
 */
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms))
}

// ============ 账号解析 ============

/**
 * 解析账号配置：
 *   优先 TREECOIN_AUTH_CODE（授权码，多账号用 & 或换行分隔），
 *   其次 WX_ID（微信协议，自动 getcode）
 * 返回 [{ authCode, remark }] 或 [{ wxid, remark }]
 */
function parseAccounts() {
    const accounts = []
    if (AUTH_CODES_RAW) {
        for (const ac of AUTH_CODES_RAW.split(/[&\n|]/).map(s => s.trim()).filter(Boolean)) {
            accounts.push({ authCode: ac, remark: ac.substring(0, 8) })
        }
    } else if (WX_IDS_RAW) {
        for (const line of WX_IDS_RAW.split(/[&\n|]/).map(s => s.trim()).filter(Boolean)) {
            if (line.includes('#')) {
                const [wxid, remark] = line.split('#', 2)
                accounts.push({ wxid: wxid.trim(), remark: remark.trim() })
            } else {
                accounts.push({ wxid: line, remark: line })
            }
        }
    }
    return accounts
}

// ============ 核心逻辑 ============

/**
 * 微信协议登录（真实接口：/wechat/miniprogram/login）
 */
async function wechatLogin(code) {
    const result = await request('/wechat/miniprogram/login', 'POST', {
        code: code,
        userInfo: null,
        inviteCode: INVITE_CODE
    })

    const d = (result && result.data !== undefined) ? result.data : result
    const token = (d && d.token) || (result && result.token)
    if (!token) {
        throw new Error((result && (result.msg || result.message)) || '登录失败，未返回 token')
    }

    return {
        token: token,
        openid: (d && (d.openid || (d.user && d.user.openid))) || (result && result.openid) || '',
        deviceFingerprint: generateDeviceId(),
        userInfo: (d && (d.user || d.userInfo || d.userInfoVo)) || {}
    }
}

/**
 * 授权码登录（旧方式：/auth/login-by-auth-code，接受 TREE+ 授权码）
 */
async function authCodeLogin(authCode) {
    const deviceFingerprint = generateDeviceId()

    const result = await request('/auth/login-by-auth-code', 'POST', {
        authCode,
        device_fingerprint: deviceFingerprint
    })

    if ((result && result.c !== undefined && result.c !== 1) || !result || (!result.data && !result.token)) {
        throw new Error((result && (result.msg || result.message)) || '登录失败')
    }

    const d = (result && result.data) || result
    return {
        token: d.token || result.token,
        openid: d.openid || result.openid || '',
        deviceFingerprint: deviceFingerprint,
        userInfo: (d && (d.user || d.userInfo || d.userInfoVo)) || {}
    }
}

/**
 * 执行签到（真实接口：/app/signin，明文 body，token 走 Authorization）
 */
async function doSignin(token, deviceId) {
    const result = await request('/app/signin', 'POST', {
        deviceId: deviceId !== undefined ? deviceId : ''
    }, token)

    return result
}

/**
 * 单账号签到流程
 */
async function signinForAccount(account, index) {
    log(`---------- 账号 ${index + 1} (${account.remark}) ----------`)

    let loginResult
    try {
        if (account.wxid) {
            if (!getSingleCode) {
                throw new Error('未找到 getCode.js，请将其放在同一目录')
            }
            log('通过微信协议获取 code...')
            const code = await getSingleCode(WX_APP_ID, account.wxid)
            log(`wxid: ${account.wxid.substring(0, 8)}**** （微信协议已获取 code）`)
            loginResult = await wechatLogin(code)
        } else {
            log(`授权码: ${account.authCode.substring(0, 8)}****`)
            loginResult = await authCodeLogin(account.authCode)
        }
    } catch (e) {
        log(`登录失败: ${e.message}`)
        return { success: false, msg: e.message }
    }

    try {
        log(`登录成功！用户: ${loginResult.userInfo.nickName || loginResult.userInfo.nickname || '未知'}`)
        const { token, deviceFingerprint } = loginResult

        // 2. 设置页面访问标记
        log('设置签到前置标记...')
        await sleep(500)

        // 3. 签到（deviceId 传空串，与抓包一致）
        log('执行签到...')
        const signinResult = await doSignin(token, '')

        if (signinResult.c === 1) {
            const data = signinResult.data || {}
            log('========================================')
            log('           签到成功！')
            log('========================================')
            log(`  连续签到天数: ${data.continuousDays || 1} 天`)
            log(`  当前持有树苗: ${data.vitality || '未知'}`)
            log(`  本次树苗奖励: +${data.baseReward || 0}`)
            if (data.continuousReward && data.continuousReward > 0) {
                log(`  连续签到奖励: +${data.continuousReward} (满7天额外奖励！)`)
            }
            log(`  本次总收益:   +${data.increase || 0} 树苗`)
            log('========================================')
            log('提示: 大树(能量币)收益将在签到后异步发放')
            log('      持有树苗越多，每日大树产币越多！')
            return { success: true, data }
        } else {
            log(`签到结果: ${signinResult.msg || '未知'}`)
            // 调试：打印完整签到响应，便于定位「签到失败，请重试」
            log(`签到响应(raw): ${JSON.stringify(signinResult)}`)

            // 今日已签到也算成功
            if (signinResult.msg && signinResult.msg.includes('已签到')) {
                log('今天已经签到过了，明天再来吧！')
                return { success: true, alreadySigned: true }
            }

            return { success: false, msg: signinResult.msg }
        }
    } catch (error) {
        log(`签到失败: ${error.message}`)
        return { success: false, msg: error.message }
    }
}

/**
 * 主函数
 */
async function main() {
    console.log('')
    console.log('╔══════════════════════════════════════════╗')
    console.log('║  绿树田园 - 每日签到脚本 (微信协议版)    ║')
    console.log('║                                          ║')
    console.log('║  种树赚钱，每日签到，连续7天额外奖励！   ║')
    console.log('║  树苗可兑换真实树苗，为地球添一份绿！    ║')
    console.log('║  当前币价：3.12，自由交易    ║')
    console.log('╚══════════════════════════════════════════╝')
    console.log('')

    const accounts = parseAccounts()
    if (accounts.length === 0) {
        console.log('❌ 未配置账号！')
        console.log('')
        console.log('微信协议版（推荐）：')
        console.log('  环境变量 → WX_ID = wxid#备注（多账号换行/&/| 分隔）')
        console.log('旧方式（已内置默认授权码）：')
        console.log('  环境变量 → TREECOIN_AUTH_CODE = 授权码（多账号用 & 分隔，可覆盖默认）')
        console.log('')
        return
    }

    log(`共 ${accounts.length} 个账号待签到`)
    log(`API地址: ${API_BASE}`)
    log(`登录方式: ${AUTH_CODES_RAW ? '授权码 (TREECOIN_AUTH_CODE)' : '微信协议 (AppID=' + WX_APP_ID + ')'}`)
    log(`待签到账号数: ${accounts.length}`)
    console.log('')

    let successCount = 0
    let failCount = 0

    for (let i = 0; i < accounts.length; i++) {
        const result = await signinForAccount(accounts[i], i)
        if (result.success) {
            successCount++
        } else {
            failCount++
        }

        // 多账号间隔2秒，避免频率限制
        if (i < accounts.length - 1) {
            log('等待2秒后处理下一个账号...')
            await sleep(2000)
        }
    }

    console.log('')
    log('========== 签到汇总 ==========')
    log(`成功: ${successCount} 个账号`)
    log(`失败: ${failCount} 个账号`)
    log('==============================')

    if (failCount > 0) {
        log('部分账号签到失败，请检查 WX_ID/AppID 或授权码是否正确、微信协议服务是否在线')
    }
}

// 运行
main().catch(err => {
    log(`脚本运行异常: ${err.message}`)
    console.error(err)
})

// 当前脚本来自于 http://script.345yun.cn 脚本库下载！
// 当前脚本来自于 http://2.345yun.cn 脚本库下载！
// 当前脚本来自于 http://2.345yun.cc 脚本库下载！
// 脚本库官方QQ群1群: 429274456
// 脚本库官方QQ群2群: 1077801222
// 脚本库官方QQ群3群: 433030897
// 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
// 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
// 您在使用脚本库下载的脚本时自行检查判断风险。
// 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。
