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

// 导入模块
const VERSION = "v260715.001"
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
        await sleep(rand(2000, 4000))
        const inviteBtn = await browser.page.$('#start-earning-rewards-link')
        if (inviteBtn) {
            await inviteBtn.click()
            await sleep(rand(2000, 4000))
        }

        // 获取积分信息 (检查 /earn 是否可用)
        let result = await pointsMgr.getRewardsPoints(false)
        if (result === null) {
            console.log(`${LogTag.ACTIVITY} 账号${idx} 不支持积分页面任务，跳过`)
            return { index: idx, username, result: null, token: null }
        }
        if (!result) result = {}

        // 获取/刷新 token
        let savedToken = await AccountStorage.getToken(username)
        if (!savedToken) {
            const tokenResult = await tokenMgr.getRefreshToken()
            if (tokenResult?.refresh_token) {
                savedToken = tokenResult.refresh_token
                await AccountStorage.saveToken(username, savedToken)
            }
        }

        // 中间任务列表
        const tasks = [
            { name: '积分页面任务', fn: async () => {
                const pointsPageMgr = new PointsPageManager(browser)
                await pointsPageMgr.completePointsTasks(idx)
                result.punch_stats = pointsPageMgr.stats.punch
                result.activity_stats = pointsPageMgr.stats.activity
                result.daily_stats = pointsPageMgr.stats.daily
                result.claimed_points = pointsPageMgr.stats.claimedPoints
            }},
            { name: '搜索任务', fn: async () => {
                const searchDone = await searchMgr.completeSearchTasks(idx)
                result.search_done = searchDone
            }},
            { name: 'APP任务', fn: async () => {
                const appMgr = new AppTaskManager(savedToken, idx, browser, tokenMgr)
                const appResult = await appMgr.runAllTasks()
                result.app_sign_in = appResult.app_sign_in
                result.read_progress = appResult.read_progress
                // 如果 OAuth 刷新出了新的 refresh_token，持久化保存
                if (appMgr.refreshToken && appMgr.refreshToken !== savedToken) {
                    savedToken = appMgr.refreshToken
                    await AccountStorage.saveToken(username, savedToken)
                }
            }},
        ]

        // 打乱执行顺序
        for (let i = tasks.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [tasks[i], tasks[j]] = [tasks[j], tasks[i]]
        }
        console.log(`${LogTag.ACTIVITY} 账号${idx} 任务顺序: ${tasks.map(t => t.name).join(' → ')}`)

        for (const task of tasks) {
            console.log(`${LogTag.ACTIVITY} 账号${idx} 执行: ${task.name}`)
            await task.fn()
        }

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
        await sleep(2000)
        process.exit(10)
    }

    // 获取账号列表
    const accounts = await AccountStorage.getAccounts()
    if (!accounts.length) {
        console.log(`${LogTag.SYSTEM} 未检测到账号配置`)
        return
    }

    console.log(`${LogTag.SYSTEM} 启动 Bing Rewards (版本: ${VERSION})`)
    console.log(`${LogTag.SYSTEM} 检测到 ${accounts.length} 个账号`)

    // 清理 debug 目录
    const debugDir = path.join(__dirname, 'debug')
    if (fs.existsSync(debugDir)) {
        fs.rmSync(debugDir, { recursive: true, force: true })
    }

    const hotWordsMgr = new HotWordsManager()
    const browserResults = []

    // 执行所有账号任务
    for (const acc of accounts) {
        const item = await processAccount(acc, hotWordsMgr)
        browserResults.push(item)
        if (acc !== accounts[accounts.length - 1]) {
            await sleep(rand(5000, 9000))
        }
    }

    // 打印总结
    printSummary(browserResults)
}

// 启动主程序
main().catch(err => {
    console.error(`${LogTag.SYSTEM} 程序异常退出:`, err)
    process.exitCode = 1
})
