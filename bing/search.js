// name: Bing - 搜索模块
/**
 * Search - 搜索任务管理器
 */

const {
    LogTag, LogIndent, BING_URL,
    sleep, rand, randFloat
} = require('./utils')

/**
 * 搜索任务管理类
 */
class SearchManager {
    /**
     * 构造函数
     * @param {Object} browserMgr - 浏览器管理器实例
     * @param {Object} pointsMgr - 积分管理器实例
     * @param {Object} hotWordsMgr - 热搜词管理器实例
     */
    constructor(browserMgr, pointsMgr, hotWordsMgr) {
        this.browserMgr = browserMgr
        this.page = browserMgr.page
        this.pointsMgr = pointsMgr
        this.hotWordsMgr = hotWordsMgr
    }

    /**
     * 执行搜索任务
     * @param {number} accountIndex - 账号索引
     * @returns {Promise<number>} 成功搜索次数
     */
    async completeSearchTasks(accountIndex) {
        console.log(`${LogTag.SEARCH} 账号${accountIndex} 准备执行搜索任务...`)

        const pointsData = await this.pointsMgr.getRewardsPoints(true)
        if (!pointsData) return 0

        const remaining = pointsData.search?.remaining || 0
        const progress = pointsData.search?.progress || 0
        const maxPoints = pointsData.search?.max || 0

        console.log(`${LogIndent.ITEM}搜索进度: ${progress}/${maxPoints}，剩余 ${remaining} 次`)

        if (remaining <= 0) {
            console.log(`${LogIndent.END}搜索任务已完成`)
            return 0
        }

        // 确保热搜词已加载
        await this.hotWordsMgr.ensureLoaded()

        try {
            // 访问搜索首页
            await this.page.goto(BING_URL, { waitUntil: 'domcontentloaded', timeout: 45000 })
            await sleep(randFloat(2000, 4000))

            // 刷新页面
            await this.page.reload({ waitUntil: 'domcontentloaded', timeout: 45000 })
            await sleep(randFloat(2000, 4000))

            // 检查是否需要登录
            const loginBtn = await this.page.$('#id_l')
            if (loginBtn) {
                await loginBtn.click()
                await sleep(randFloat(8000, 10000))
            }
        } catch (e) { }

        // 计算本批次搜索次数
        let batchSize
        if (remaining <= 6) {
            batchSize = remaining
        } else {
            const minBatch = Math.floor(remaining * 0.6)
            const maxBatch = Math.floor(remaining * 0.9)
            batchSize = rand(minBatch, maxBatch)
        }

        let totalSuccess = 0
        const checkInterval = 3
        let noChangeCount = 0
        const maxNoChange = 2;  // 连续2次无变化就停止
        let startPoints = await this.pointsMgr.getPointsFromPage()
        let lastPoints = startPoints
        let lastCheckedSuccess = 0

        console.log(`${LogIndent.ITEM}本批次计划搜索 ${batchSize} 次，当前积分: ${startPoints || '未知'}`)

        for (let i = 0; i < batchSize; i++) {
            const searchStr = await this.hotWordsMgr.getRandomWord()

            try {
                // 在输入框输入搜索词
                const success = await this._searchInput(searchStr)
                if (success) {
                    await sleep(randFloat(4000, 7000))
                    totalSuccess++
                }

                const currentPoints = await this.pointsMgr.getPointsFromPage()
                const pointsStr = currentPoints ? `，当前积分: ${currentPoints}` : ''
                console.log(`${LogIndent.ITEM}搜索 ${i + 1}/${batchSize}: ${searchStr}${pointsStr}`)

                // 每3次检查积分变化
                if (totalSuccess > lastCheckedSuccess && totalSuccess % checkInterval === 0) {
                    lastCheckedSuccess = totalSuccess
                    const checkPoints = await this.pointsMgr.getPointsFromPage()
                    if (checkPoints !== null && lastPoints !== null) {
                        const delta = checkPoints - lastPoints
                        if (delta > 0) {
                            console.log(`${LogIndent.ITEM}积分检查: ${lastPoints} → ${checkPoints} (+${delta})`)
                            lastPoints = checkPoints
                            noChangeCount = 0
                        } else if (delta < 0) {
                            // 积分减少的情况，更新最后积分但不增加计数（可能是页面显示延迟）
                            console.log(`${LogIndent.ITEM}积分变化: ${lastPoints} → ${checkPoints} (${delta})`)
                            lastPoints = checkPoints
                        } else {
                            // delta === 0，积分未增加
                            noChangeCount++
                            console.log(`${LogIndent.ITEM}积分未增加: 仍为 ${checkPoints} (连续${noChangeCount}次)`)
                            if (noChangeCount >= maxNoChange) {
                                console.log(`${LogIndent.ITEM}连续${maxNoChange}次积分无变化，停止搜索`)
                                break
                            }
                        }
                    }
                }
            } catch (e) {
                console.log(`${LogIndent.ITEM}搜索失败: ${e.message}`)
                await sleep(2000)
            }
        }

        // 最终积分检查
        const finalPoints = await this.pointsMgr.getPointsFromPage()
        if (finalPoints !== null && startPoints !== null) {
            const totalDelta = finalPoints - startPoints
            console.log(`${LogIndent.ITEM}本批次结果: 搜索 ${totalSuccess} 次，积分 ${startPoints} → ${finalPoints} (+${totalDelta})`)
        }

        console.log(`${LogIndent.END}本批次搜索完成 ${totalSuccess}/${batchSize}`)
        return totalSuccess
    }

    /**
     * 在搜索输入框输入文字并搜索
     * @param {string} keyword - 搜索关键词
     * @returns {Promise<boolean>} 是否成功
     */
    async _searchInput(keyword) {
        try {
            // 查找搜索输入框（多种选择器）
            const selectors = [
                '#sb_form_q',
                'input[name="q"]',
                'input[type="search"]',
                '#qs',
                '.b_searchbox'
            ]

            let searchInput = null
            for (const sel of selectors) {
                searchInput = await this.page.$(sel)
                if (searchInput) break
            }

            if (!searchInput) {
                // 如果找不到输入框，可能是搜索结果页，点击搜索框图标
                const searchIcon = await this.page.$('#sb_form_l')
                if (searchIcon) {
                    await searchIcon.click()
                    await sleep(500)
                    searchInput = await this.page.$('#sb_form_q')
                }
            }

            if (!searchInput) {
                // 最后尝试：重新访问首页
                await this.page.goto(BING_URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
                await sleep(randFloat(2000, 3000))

                for (const sel of selectors) {
                    searchInput = await this.page.$(sel)
                    if (searchInput) break
                }
            }

            if (!searchInput) {
                await this.browserMgr.screenshot('search_noinput')
                await this.browserMgr.saveHTML('search_noinput')
                console.log(`${LogIndent.ITEM}未找到搜索输入框`)
                return false
            }

            // 点击输入框获取焦点
            await searchInput.click()
            await sleep(300)

            // 全选并清空
            await searchInput.fill('')
            await sleep(200)

            // 输入搜索词
            await searchInput.fill(keyword)
            await sleep(500)

            // 按回车搜索
            await searchInput.press('Enter')

            // 等待页面加载
            try {
                await this.page.waitForLoadState('domcontentloaded', { timeout: 10000 })
            } catch (e) { }

            return true
        } catch (e) {
            console.log(`${LogIndent.ITEM}搜索输入失败: ${e.message}`)
            return false
        }
    }
}

module.exports = SearchManager
