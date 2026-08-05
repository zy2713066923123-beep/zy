/**
 * Bing Rewards
 *
 * 功能：自动完成 Bing 搜索任务、积分任务、APP签到等
 * Cron：5 5 12,13 * * *
 * Linux 依赖：chromium、chromium-chromedriver、xvfb
 * Node 依赖：fs-extra、playwright
 * by zgcwkj
 */

const fs = require('fs')
const path = require('path')
const { spawnSync } = require('child_process')

// 导入模块
const VERSION = "v260430.001"
const BrowserManager = require('./browser')
const { AccountStorage, AuthManager, TokenManager } = require('./account')
const { PointsManager, PointsPageManager } = require('./points')
const SearchManager = require('./search')
const AppTaskManager = require('./appTask')
const { 
    HotWordsManager, LogTag, LogIndent,
    emailMask, sleep, rand 
} = require('./utils')
const { checkForUpdates } = require('./updater')


/**
 * 青龙推送通知
 * 优先使用 Node 版 sendNotify.js；如果不存在，则回退调用青龙 notify.py
 * @param {string} title - 推送标题
 * @param {string} content - 推送内容
 * @returns {Promise<boolean>} 是否推送成功
 */
async function sendNotify(title, content) {
    if (!content) content = ''

    // 1. 优先兼容青龙常见的 sendNotify.js
    const jsNotifyPaths = [
        path.join(__dirname, 'sendNotify.js'),
        path.join(__dirname, 'utils', 'sendNotify.js'),
        '/ql/data/scripts/sendNotify.js'
    ]

    for (const notifyPath of jsNotifyPaths) {
        try {
            if (!fs.existsSync(notifyPath)) continue

            const notifyModule = require(notifyPath)
            const notifyFn = notifyModule.sendNotify || notifyModule.send || notifyModule

            if (typeof notifyFn === 'function') {
                await notifyFn(title, content)
                console.log(`${LogTag.SYSTEM} 推送完成: ${notifyPath}`)
                return true
            }
        } catch (err) {
            console.log(`${LogTag.SYSTEM} JS推送失败(${notifyPath}): ${err.message}`)
        }
    }

    // 2. 回退兼容青龙 Python 版 notify.py
    const pyNotifyPaths = [
        path.join(__dirname, 'notify.py'),
        '/ql/data/scripts/notify.py'
    ]
    const notifyPy = pyNotifyPaths.find(p => fs.existsSync(p))

    if (!notifyPy) {
        console.log(`${LogTag.SYSTEM} 未找到 sendNotify.js 或 notify.py，跳过推送`)
        return false
    }

    const pyCode = [
        'import os, sys',
        `sys.path.insert(0, ${JSON.stringify(path.dirname(notifyPy))})`,
        'from notify import send',
        'send(os.environ.get("NOTIFY_TITLE", ""), os.environ.get("NOTIFY_CONTENT", ""))'
    ].join('\n')

    for (const pyCmd of ['python3', 'python']) {
        try {
            const ret = spawnSync(pyCmd, ['-c', pyCode], {
                encoding: 'utf8',
                timeout: 30000,
                env: {
                    ...process.env,
                    NOTIFY_TITLE: title,
                    NOTIFY_CONTENT: content
                }
            })

            if (ret.error) {
                continue
            }

            if (ret.status === 0) {
                console.log(`${LogTag.SYSTEM} 推送完成: ${notifyPy}`)
                return true
            }

            const errText = (ret.stderr || ret.stdout || '').trim()
            console.log(`${LogTag.SYSTEM} Python推送失败(${pyCmd}): ${errText || '未知错误'}`)
        } catch (err) {
            console.log(`${LogTag.SYSTEM} Python推送异常(${pyCmd}): ${err.message}`)
        }
    }

    console.log(`${LogTag.SYSTEM} 推送失败，已跳过`)
    return false
}

function numberOrZero(value) {
    const n = Number(value)
    return Number.isFinite(n) ? n : 0
}

/**
 * 构建推送汇总内容
 * @param {Array} items - 处理结果数组
 * @returns {string} 推送内容
 */
function buildNotifyContent(items) {
    const total = items.length
    const successCount = items.filter(r => r.result).length
    const failCount = total - successCount
    const totalToday = items.reduce((sum, r) => sum + numberOrZero(r.result?.today_points), 0)
    const totalClaimed = items.reduce((sum, r) => sum + numberOrZero(r.result?.claimed_points), 0)
    const totalRead = items.reduce((sum, r) => sum + numberOrZero(r.result?.read_progress), 0)

    const lines = [
        `🎉 Bing Rewards ${VERSION}`,
        `⏰ 执行时间: ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
        `📱 账号总数: ${total}`,
        `✅ 成功: ${successCount}  ❌ 失败: ${failCount}`,
        `💰 今日积分合计: +${totalToday}`,
        `🎁 积分领取合计: +${totalClaimed}`,
        `📖 APP阅读合计: +${totalRead}分`,
        '',
        '📊 账号明细:'
    ]

    for (const r of items) {
        const accountName = `账号${r.index} (${emailMask(r.username)})`
        if (!r.result) {
            lines.push(`\n${accountName}`)
            lines.push('   ❌ 未登录或流程中断')
            continue
        }

        const res = r.result
        const pts = res.points ?? '?'
        const today = res.today_points ?? 0
        const search = res.search || {}
        const readPts = res.read_progress ?? 0
        const daily = res.daily_stats || {}
        const activity = res.activity_stats || {}
        const punch = res.punch_stats || {}
        const claimed = res.claimed_points || 0
        const claimStr = claimed > 0 ? `+${claimed}分` : '无'
        const appSign = res.app_sign_in ?? -1
        const appStr = appSign === 0 ? '今日已签到' : (appSign > 0 ? `+${appSign}分` : '失败')

        lines.push(`\n${accountName}`)
        lines.push(`   ├── 总积分: ${pts}`)
        lines.push(`   ├── 今日积分: +${today}`)
        lines.push(`   ├── 积分领取: ${claimStr}`)
        lines.push(`   ├── 搜索进度: ${search.progress ?? '?'}/${search.max ?? '?'} (剩余${search.remaining ?? '?'}次)`)
        lines.push(`   ├── 每日活动: ${daily.done ?? 0}/${daily.total ?? 0}`)
        lines.push(`   ├── 活动任务: ${activity.done ?? 0}/${activity.total ?? 0}`)
        lines.push(`   ├── 打卡任务: ${punch.done ?? 0}/${punch.total ?? 0}`)
        lines.push(`   ├── APP签到: ${appStr}`)
        lines.push(`   └── APP阅读: +${readPts}分`)
    }

    return lines.join('\n')
}

/**
 * 处理单个账号的完整流程
 * @param {Object} account - 账号信息
 * @param {Object} hotWordsMgr - 热搜词管理器
 * @returns {Promise<Object>} 处理结果
 */
async function processAccount(account, hotWordsMgr) {
    const idx = account.index
    const username = account.username
    const password = account.password
    const otpauth = account.otpauth

    console.log('==================================================')
    console.log(`${LogTag.ACCOUNT} 处理账号 ${idx}: ${emailMask(username)}`)
    console.log('==================================================')

    const browser = new BrowserManager(username, account.proxy)
    await browser.init()

    try {
        const auth = new AuthManager(browser.page, browser)
        const tokenMgr = new TokenManager(browser)
        const pointsMgr = new PointsManager(browser)
        const searchMgr = new SearchManager(browser, pointsMgr, hotWordsMgr)

        // 统一检查登录状态
        const loggedIn = await auth.ensureAllLoggedIn(username, password, otpauth)
        if (!loggedIn) {
            console.log(`${LogTag.LOGIN} 账号${idx} 登录失败`)
            return { index: idx, username, result: null, token: null }
        }

        // 邀请好友链接
        console.log(`${LogTag.ACTIVITY} 账号${idx} 访问邀请好友链接`)
        const rhUrl = 'https://rewards.bing.com/welcome?rh=81BD22C3&ref=rafsrchae'
        await browser.page.goto(rhUrl, { waitUntil: 'domcontentloaded', timeout: 45000 })

        // 获取积分信息
        let result = await pointsMgr.getRewardsPoints(false)
        
        // 如果返回 null，说明 /earn 返回 404，跳过所有任务
        if (result === null) {
            console.log(`${LogTag.ACTIVITY} 账号${idx} 不支持积分页面任务，跳过`)
            return { index: idx, username, result: null, token: null }
        }

        if (!result) result = {}

        const pointsPageMgr = new PointsPageManager(browser)

        // 获取/刷新 token
        let savedToken = await AccountStorage.getToken(username)
        if (!savedToken) {
            const tokenResult = await tokenMgr.getRefreshToken()
            if (tokenResult?.refresh_token) {
                savedToken = tokenResult.refresh_token
                await AccountStorage.saveToken(username, savedToken)
            }
        }

        // 执行积分页面任务
        await pointsPageMgr.completePointsTasks(idx)
        result.punch_stats = pointsPageMgr.stats.punch
        result.activity_stats = pointsPageMgr.stats.activity
        result.daily_stats = pointsPageMgr.stats.daily
        result.claimed_points = pointsPageMgr.stats.claimedPoints

        // 执行搜索任务
        const searchDone = await searchMgr.completeSearchTasks(idx)
        result.search_done = searchDone

        // 获取最终积分
        const finalPoints = await pointsMgr.getRewardsPoints(true)
        if (finalPoints) result = { ...result, ...finalPoints }

        return { index: idx, username, result, token: savedToken }
    } catch (err) {
        console.log(`${LogTag.SYSTEM} 账号${idx} 处理异常:`, err.message)
        return { index: idx, username, result: null, token: null }
    } finally {
        await browser.cleanup()
    }
}

/**
 * 打印任务总结
 * @param {Array} items - 处理结果数组
 */
function printSummary(items) {
    console.log('==================================================')
    console.log(`${LogTag.POINTS} 任务总结`)
    console.log('==================================================')

    for (const r of items) {
        if (!r.result) {
            console.log(`账号${r.index} (${emailMask(r.username)}): 未登录或流程中断`)
            continue
        }

        const res = r.result
        const pts = res.points ?? '?'
        const today = res.today_points ?? 0
        const search = res.search || {}
        const readPts = res.read_progress ?? 0
        const daily = res.daily_stats || {}
        const activity = res.activity_stats || {}
        const punch = res.punch_stats || {}
        const claimed = res.claimed_points || 0
        const claimStr = claimed > 0 ? `+${claimed}分` : '无'
        const appSign = res.app_sign_in ?? -1
        const appStr = appSign === 0 ? '今日已签到' : (appSign > 0 ? `+${appSign}分` : '失败')

        console.log(`账号${r.index} (${emailMask(r.username)})`)
        console.log(`   ├── 总积分: ${pts}`)
        console.log(`   ├── 今日积分: +${today}`)
        console.log(`   ├── 积分领取: ${claimStr}`)
        console.log(`   ├── 搜索进度: ${search.progress ?? '?'}/${search.max ?? '?'} (剩余${search.remaining ?? '?'}次)`)
        console.log(`   ├── 每日活动: ${daily.done ?? 0}/${daily.total ?? 0}`)
        console.log(`   ├── 活动任务: ${activity.done ?? 0}/${activity.total ?? 0}`)
        console.log(`   ├── 打卡任务: ${punch.done ?? 0}/${punch.total ?? 0}`)
        console.log(`   ├── APP签到: ${appStr}`)
        console.log(`   └── APP阅读: +${readPts}分`)
    }
}

async function main() {
    // 检查更新
    const updateResult = await checkForUpdates(VERSION)
    if (updateResult.updated) {
        console.log(`${LogTag.SYSTEM} 更新成功，程序将自动重启...`)
        await sendNotify('Bing Rewards', `🔄 Bing Rewards ${VERSION} 更新成功，程序将自动重启`)
        await sleep(2000)
        process.exit(10)
    }

    // 获取账号列表
    const accounts = await AccountStorage.getAccounts()
    if (!accounts.length) {
        console.log(`${LogTag.SYSTEM} 未检测到账号配置`)
        await sendNotify('Bing Rewards', `❌ 未检测到账号配置，请检查账号配置文件`)
        return
    }

    console.log(`${LogTag.SYSTEM} 启动 Bing Rewards (版本: ${VERSION})`)
    console.log(`${LogTag.SYSTEM} 检测到 ${accounts.length} 个账号`)

    // 清理并创建 debug 目录
    const debugDir = path.join(__dirname, 'debug')
    if (fs.existsSync(debugDir)) {
        fs.rmSync(debugDir, { recursive: true, force: true })
    }
    fs.mkdirSync(debugDir, { recursive: true })

    const hotWordsMgr = new HotWordsManager()
    const browserResults = []

    // 第一阶段：执行浏览器任务
    for (const acc of accounts) {
        const item = await processAccount(acc, hotWordsMgr)
        browserResults.push(item)
        if (acc !== accounts[accounts.length - 1]) {
            await sleep(rand(5000, 9000))
        }
    }

    // 第二阶段：执行 APP 任务
    console.log('==================================================')
    console.log(`${LogTag.READ} 执行 APP 任务`)
    console.log('==================================================')

    for (const item of browserResults) {
        if (!item.result) continue

        const token = item.token
        if (!token) {
            item.result.app_sign_in = -1
            item.result.read_progress = 0
            console.log(`${LogIndent.ITEM}账号${item.index} 无 token，跳过 APP 任务`)
            continue
        }

        const appMgr = new AppTaskManager(token, item.index)
        const appResult = await appMgr.runAllTasks()
        item.result.app_sign_in = appResult.app_sign_in
        item.result.read_progress = appResult.read_progress

        // 保存更新的 token
        if (appMgr.refreshToken && appMgr.refreshToken !== token) {
            await AccountStorage.saveToken(item.username, appMgr.refreshToken)
        }
    }

    // 打印总结
    printSummary(browserResults)

    // 推送总结
    await sendNotify('Bing Rewards', buildNotifyContent(browserResults))
}

// 启动主程序
main().catch(async err => {
    console.error(`${LogTag.SYSTEM} 程序异常退出:`, err)
    try {
        const errorText = err && (err.stack || err.message) ? (err.stack || err.message) : String(err)
        await sendNotify('Bing Rewards', `❌ 程序异常退出

${errorText}`)
    } catch (_) {}
    process.exitCode = 1
})
