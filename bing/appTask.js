// name: Bing - APP任务模块
/**
 * AppTask - APP任务管理器（签到、阅读）
 */

const axios = require('axios')
const {
    LogTag, LogIndent, OAUTH_CLIENT_ID, OAUTH_SCOPE, OAUTH_TOKEN_URL,
    sleep, randFloat, getDateNumber, randomString
} = require('./utils')

/**
 * APP 任务管理类（签到、阅读）
 */
class AppTaskManager {
    static API_BASE = 'https://prod.rewardsplatform.microsoft.com/dapi'

    // APP 程序信息
    static APP_UA = 'Mozilla/5.0 (Linux; Android 16; 2211133C Build/BP2A.250605.031.A3; ) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/137.0.7151.115 Mobile Safari/537.36 BingSapphire/32.6.2110003561'
    static APP_VERSION = '32.6.2110003561'

    /**
     * 构造函数
     * @param {string} refreshToken - OAuth刷新令牌（可为 null）
     * @param {number} accountIndex - 账号索引
     * @param {Object} browser - 浏览器管理器实例
     * @param {Object} tokenMgr - TokenManager 实例（用于浏览器授权流程）
     */
    constructor(refreshToken, accountIndex = 1, browser = null, tokenMgr = null) {
        this.refreshToken = refreshToken
        this.accountIndex = accountIndex
        this.browser = browser
        this.tokenMgr = tokenMgr
        this.accessToken = null
        this.result = {
            app_sign_in: -1,
            read_progress: 0
        }
    }

    /**
     * 获取 access_token
     * @returns {Promise<boolean>} 是否成功获取
     */
    async _getAccessToken() {
        // 已有有效 token，直接返回
        if (this.accessToken) return true

        // 方法1：通过 OAuth refresh_token 获取
        if (this.refreshToken) {
            try {
                const data = {
                    client_id: OAUTH_CLIENT_ID,
                    refresh_token: this.refreshToken,
                    scope: OAUTH_SCOPE,
                    grant_type: 'refresh_token'
                }

                const response = await axios.post(OAUTH_TOKEN_URL, new URLSearchParams(data).toString(), {
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    timeout: 15000
                })

                if (response.status === 200) {
                    const json = response.data
                    if (!json.access_token) {
                        console.log(`${LogIndent.ITEM}OAuth 返回缺少 access_token`)
                    } else {
                        this.accessToken = json.access_token
                        if (json.refresh_token) this.refreshToken = json.refresh_token
                        return true
                    }
                }
            } catch (e) {
                console.log(`${LogIndent.ITEM}通过 refresh_token 获取 access_token 失败: ${e.message}`)
            }
            // OAuth 失败，如果已有 accessToken 则返回成功，否则继续尝试浏览器方式
            if (this.accessToken) return true
        }

        // 方法2：通过浏览器 OAuth 授权码流程获取（复用已登录的浏览器 Session）
        const browserToken = await this._getAccessTokenFromBrowser()
        if (browserToken) {
            this.accessToken = browserToken
            return true
        }

        return false
    }

    /**
     * 委托 TokenManager 通过浏览器 OAuth 授权码流程获取 token
     * @returns {Promise<string|null>} access_token 或 null
     */
    async _getAccessTokenFromBrowser() {
        if (!this.tokenMgr) return null

        console.log(`${LogIndent.ITEM}尝试通过浏览器获取 access_token...`)

        const tokenData = await this.tokenMgr.getRefreshToken()
        if (tokenData) {
            if (tokenData.refresh_token) {
                this.refreshToken = tokenData.refresh_token
                console.log(`${LogIndent.ITEM}浏览器 OAuth 获取 token 成功（已更新 refresh_token）`)
            } else {
                console.log(`${LogIndent.ITEM}浏览器 OAuth 获取 access_token 成功`)
            }
            return tokenData.access_token || null
        }

        return null
    }

    /**
     * 获取请求头
     * @param {boolean} withContentType - 是否包含Content-Type
     * @returns {Object} 请求头对象
     */
    _getHeaders(withContentType = false) {
        const headers = {
            'Authorization': `Bearer ${this.accessToken}`,
            'User-Agent': AppTaskManager.APP_UA,
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip',
            'channel': 'SAAndroid',
            'x-rewards-partnerid': 'startapp',
            'x-rewards-appid': `SAAndroid/${AppTaskManager.APP_VERSION}`,
            'x-rewards-country': 'cn',
            'x-rewards-language': 'zh-hans',
            'x-rewards-flights': 'rwgobig'
        }
        if (withContentType) headers['Content-Type'] = 'application/json'
        return headers
    }

    /**
     * 提取 axios/普通异常中的可读错误文本
     */
    _getErrorText(err) {
        const data = err?.response?.data || err?.data
        const detail = data?.error?.description || data?.error || data
        const detailText = typeof detail === 'string' ? detail : (detail ? JSON.stringify(detail) : '')
        return String(detailText || err?.message || err || '')
    }

    /**
     * 获取阅读任务进度
     * @returns {Promise<Object>} 进度对象 {max, progress}
     */
    async _getReadProgress() {
        try {
            const url = `${AppTaskManager.API_BASE}/me?channel=SAAndroid&options=613`
            const response = await axios.get(url, { headers: this._getHeaders(), timeout: 15000 })

            if (response.status === 200) {
                const promotions = response.data.response?.promotions || []
                for (const p of promotions) {
                    if (p.attributes?.offerid === 'ENUS_readarticle3_30points') {
                        const maxVal = p.attributes.max
                        const progressVal = p.attributes.progress
                        if (maxVal !== undefined && progressVal !== undefined) {
                            return { max: parseInt(maxVal, 10), progress: parseInt(progressVal, 10) }
                        }
                    }
                }
            }
        } catch (e) {
            console.log(`${LogIndent.ITEM}获取阅读进度失败: ${e.message}`)
        }
        return { max: 0, progress: 0 }
    }

    /**
     * APP 签到
     * @returns {Promise<number>} 获得的积分，-1表示失败
     */
    async appSignIn() {
        console.log(`${LogTag.READ} 账号${this.accountIndex} 执行 APP 签到...`)
        try {
            const url = `${AppTaskManager.API_BASE}/me/activities`
            const payload = {
                amount: 1,
                attributes: {
                    offerid: 'Gamification_Sapphire_DailyCheckIn',
                    date: getDateNumber(),
                    signIn: false,
                    timezoneOffset: '08:00:00'
                },
                id: '',
                type: 101,
                country: 'cn',
                risk_context: {},
                channel: 'SAAndroid'
            }

            await sleep(randFloat(2000, 4000))
            const response = await axios.post(url, payload, { headers: this._getHeaders(true), timeout: 15000 })

            if (response.status === 200) {
                const pts = response.data.response?.activity?.p || 0
                if (pts > 0) {
                    console.log(`${LogIndent.ITEM}APP签到成功 +${pts}分`)
                    this.result.app_sign_in = pts
                    return pts
                }
                // HTTP 200 但 p=0：可能今日已完成（服务器已记录），也可能新签到（无积分奖励）
                // 检查 response 中是否有 activity 内容来判断
                const hasActivity = !!response.data.response?.activity
                if (hasActivity) {
                    console.log(`${LogIndent.ITEM}APP签到成功（今日可能已签到）`)
                    this.result.app_sign_in = 0
                    return 0
                }
                console.log(`${LogIndent.ITEM}APP签到结果未知`)
                this.result.app_sign_in = -1
                return -1
            }
            return this._handleSignInError(response)
        } catch (e) {
            return this._handleSignInError(e)
        }
    }

    /**
     * 处理签到错误
     */
    _handleSignInError(err) {
        const errorMsg = this._getErrorText(err).toLowerCase()
        if (errorMsg.includes('already') || errorMsg.includes('duplicate')) {
            console.log(`${LogIndent.ITEM}APP今日已签到`)
            this.result.app_sign_in = 0
            return 0
        }
        console.log(`${LogIndent.ITEM}APP签到失败: ${this._getErrorText(err)}`)
        return -1
    }

    /**
     * 提交单次阅读活动
     * @returns {Promise<boolean>} 是否成功
     */
    async _submitReadActivity() {
        try {
            const url = `${AppTaskManager.API_BASE}/me/activities`
            const payload = {
                amount: 1,
                country: 'cn',
                id: randomString(32),
                type: 101,
                attributes: { offerid: 'ENUS_readarticle3_30points' }
            }
            const response = await axios.post(url, payload, { headers: this._getHeaders(true), timeout: 15000 })
            return response.status === 200
        } catch (e) {
            return this._getErrorText(e).toLowerCase().includes('already')
        }
    }

    /**
     * 执行阅读任务
     * @returns {Promise<number>} 当前阅读进度
     */
    async completeReadTasks() {
        console.log(`${LogTag.READ} 账号${this.accountIndex} 执行 APP 阅读任务...`)

        const progressData = await this._getReadProgress()
        const maxProgress = progressData.max
        let currentProgress = progressData.progress

        if (maxProgress === 0) {
            console.log(`${LogIndent.ITEM}无法获取阅读任务数据`)
            return 0
        }

        console.log(`${LogIndent.ITEM}阅读进度: ${currentProgress}/${maxProgress}`)

        if (currentProgress >= maxProgress) {
            console.log(`${LogIndent.END}阅读任务已完成`)
            this.result.read_progress = currentProgress
            return currentProgress
        }

        const maxAttempts = maxProgress - currentProgress
        for (let i = 0; i < maxAttempts; i++) {
            console.log(`${LogIndent.ITEM}执行第 ${i + 1}/${maxAttempts} 次阅读`)

            if (await this._submitReadActivity()) {
                await sleep(randFloat(5000, 10000))
                const newProgress = (await this._getReadProgress()).progress
                if (newProgress > currentProgress) {
                    currentProgress = newProgress
                    console.log(`${LogIndent.ITEM}阅读进度: ${currentProgress}/${maxProgress}`)
                    if (currentProgress >= maxProgress) {
                        console.log(`${LogIndent.END}阅读任务已完成`)
                        break
                    }
                }
            } else {
                await sleep(randFloat(2000, 5000))
            }
        }

        this.result.read_progress = currentProgress
        return currentProgress
    }

    /**
     * 执行所有 APP 任务（签到 + 阅读）
     * @returns {Promise<Object>} 任务结果对象
     */
    async runAllTasks() {
        const hasToken = await this._getAccessToken()
        if (hasToken) {
            await this.appSignIn()
            await this.completeReadTasks()
        } else {
            console.log(`${LogIndent.ITEM}无法获取 access_token，跳过 APP 签到/阅读`)
        }

        return this.result
    }
}

module.exports = AppTaskManager
