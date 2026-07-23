// name: Bing - 工具类
/**
 * Utils - 常量、日志、工具函数和 HotWordsManager
 */

const crypto = require('crypto')
const axios = require('axios')
const path = require('path')
const fs = require('fs-extra')

// ===========================
// 常量定义
// ===========================

// URL 常量
const BING_DOMAIN = "bing.com"
const REWARDS_DOMAIN = "rewards.bing.com"
const BING_URL = "https://www.bing.com"
const REWARDS_BASE_URL = "https://rewards.bing.com"
const REWARDS_URL = `${REWARDS_BASE_URL}/dashboard`
const REWARDS_EARN_URL = `${REWARDS_BASE_URL}/earn`
const REWARDS_POINTS_URL = `${REWARDS_BASE_URL}/pointsbreakdown`

const LIVE_DOMAIN = "account.live.com"
const LIVE_URL = "https://account.live.com/"

// OAuth 配置
const OAUTH_CLIENT_ID = "0000000040170455"
const OAUTH_REDIRECT_URI = "https://login.live.com/oauth20_desktop.srf"
const OAUTH_SCOPE = "service::prod.rewardsplatform.microsoft.com::MBI_SSL"
const OAUTH_AUTHORIZE_URL = `https://login.live.com/oauth20_authorize.srf?client_id=${OAUTH_CLIENT_ID}&scope=${OAUTH_SCOPE}&response_type=code&redirect_uri=${OAUTH_REDIRECT_URI}`
const OAUTH_TOKEN_URL = "https://login.live.com/oauth20_token.srf"

// 账号文件路径
const ACCOUNTS_FILE = path.join(__dirname, "accounts.json")

// 日志标签
const LogTag = {
    SYSTEM: "[System]",
    COOKIE: "[Cookie]",
    LOGIN: "[Login]",
    ACCOUNT: "[Account]",
    POINTS: "[Points]",
    SEARCH: "[Search]",
    ACTIVITY: "[Activity]",
    READ: "[Read]",
}

// 日志缩进
const LogIndent = {
    ITEM: "   ├── ",
    END: "   └── ",
}

// 站点类型
const SiteType = {
    BING: "bing",
    REWARDS: "rewards",
    LIVE: "live"
}

// 站点配置
const SITE_CONFIG = {
    [SiteType.BING]: { name: BING_DOMAIN, homeUrl: BING_URL },
    [SiteType.REWARDS]: { name: REWARDS_DOMAIN, homeUrl: REWARDS_URL },
    [SiteType.LIVE]: { name: LIVE_DOMAIN, homeUrl: LIVE_URL },
}

// ===========================
// 工具函数
// ===========================

/**
 * 邮箱打码：显示前3位和@后的域名，中间用***代替
 */
function emailMask(email) {
    if (!email || !email.includes('@')) return email
    const [local, domain] = email.split('@', 2)
    if (local.length <= 3) return `${local}***@${domain}`
    return `${local.slice(0, 3)}***${local.slice(-2)}@${domain}`
}

/**
 * 从邮箱中提取用户名
 */
function emailName(email) {
    if (!email || !email.includes('@')) return email
    return email.split('@')[0]
}

/**
 * 获取用户数据目录：优先使用 node_modules 下的新目录，兼容已存在的旧目录。
 */
function getUserDataDir(username) {
    const dirName = `user_data_${emailName(username)}`
    const nodeModulesDir = path.join(__dirname, 'node_modules', dirName)
    const legacyDir = path.join(__dirname, dirName)

    if (fs.existsSync(nodeModulesDir)) return nodeModulesDir
    if (fs.existsSync(legacyDir)) {
        console.log(`${LogTag.SYSTEM} 检测到旧用户数据目录 ${dirName}，本次继续兼容使用。`)
        console.log(`${LogIndent.ITEM}建议空闲时移动到 node_modules/${dirName}，可减少青龙面板扫描压力，提升目录加载速度。`)
        return legacyDir
    }
    return nodeModulesDir
}

/**
 * 异步睡眠函数
 */
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms))
}

/**
 * 生成范围内的随机数
 */
function rand(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min
}

/**
 * 生成范围内的随机浮点数
 */
function randFloat(min, max) {
    return Math.random() * (max - min) + min
}

/**
 * 从文本中提取数字
 */
function extractInt(pattern, text, defaultValue = 0) {
    const match = text.match(pattern)
    if (match) {
        const num = parseInt(match[1] || match[0], 10)
        return isNaN(num) ? defaultValue : num
    }
    return defaultValue
}

/**
 * 重试装饰器
 */
function retryDecorator(fn, retries = 3) {
    return async function (...args) {
        for (let attempt = 1; attempt <= retries; attempt++) {
            try {
                return await fn.apply(this, args)
            } catch (e) {
                if (attempt === retries) {
                    console.error(`${LogTag.SYSTEM} 函数 [${fn.name || 'anonymous'}] 最终失败:`, e.message)
                    throw e
                }
                console.warn(`${LogTag.SYSTEM} 函数 [${fn.name || 'anonymous'}] 第 ${attempt}/${retries} 次尝试失败:`, e.message)
                await sleep(2000)
            }
        }
    }
}

/**
 * 生成随机字符串
 */
function randomString(length = 32) {
    return crypto.randomBytes(Math.ceil(length / 2)).toString('hex').slice(0, length)
}

/**
 * URL 编码
 */
function encodeQuery(str) {
    return encodeURIComponent(str)
}

/**
 * 解析 URL 查询参数
 */
function parseQueryString(url) {
    const params = {}
    try {
        const queryString = url.split('?')[1]
        if (queryString) {
            const pairs = queryString.split('&')
            for (const pair of pairs) {
                const [key, value] = pair.split('=')
                if (key) {
                    params[decodeURIComponent(key)] = value ? decodeURIComponent(value) : ''
                }
            }
        }
    } catch (e) {
        console.error('解析查询参数失败:', e)
    }
    return params
}

/**
 * 获取当前日期数字（格式：YYYYMMDD）
 */
function getDateNumber() {
    const now = new Date()
    const year = now.getFullYear()
    const month = String(now.getMonth() + 1).padStart(2, '0')
    const day = String(now.getDate()).padStart(2, '0')
    return parseInt(`${year}${month}${day}`, 10)
}

/**
 * 格式化时间
 */
function formatTime(date = new Date()) {
    return date.toTimeString().split(' ')[0]
}

// ===========================
// HotWordsManager 类
// ===========================

/**
 * 热搜词管理类
 */
class HotWordsManager {
    /**
     * 构造函数
     */
    constructor() {
        this.hotWords = []
        this.fetched = false
    }

    /**
     * 从 API 获取热搜词
     * @param {number} maxCount - 最大获取数量
     * @returns {Promise<Array>} 热搜词数组
     */
    async _fetchHotWords(maxCount = 40) {
        const apis = [
            { baseUrl: 'https://v2.xxapi.cn/api/', sources: ['weibohot', 'douyinhot', 'baiduhot'] },
            { baseUrl: 'https://api.gmya.net/api/', sources: ['weibohot', 'douyinhot', 'baiduhot', 'toutiaohot'] },
            { baseUrl: 'https://cnxiaobai.com/DailyHotApi/', sources: ['weibo', 'douyin', 'baidu'] },
        ]

        // 随机打乱 API 顺序
        apis.sort(() => Math.random() - 0.5)

        for (const api of apis) {
            for (const source of api.sources) {
                try {
                    const response = await axios.get(api.baseUrl + source, { timeout: 10000 })
                    if (response.status === 200 && response.data?.data) {
                        const titles = response.data.data
                            .filter(item => item.title)
                            .map(item => item.title)
                        if (titles.length > 0) {
                            console.log(`${LogIndent.ITEM}获取热搜词 ${titles.length} 条`)
                            titles.sort(() => Math.random() - 0.5)
                            return titles.slice(0, maxCount)
                        }
                    }
                } catch (e) { continue }
            }
        }

        console.log(`${LogIndent.ITEM}获取热搜词接口异常`)
        return ['微软必应积分', '今天天气', '科技新闻', '人工智能', '热门话题']
    }

    /**
     * 确保热搜词已加载
     */
    async ensureLoaded() {
        if (!this.fetched) {
            this.hotWords = await this._fetchHotWords()
            this.fetched = true
        }
    }

    /**
     * 获取随机热词
     * @returns {Promise<string>} 随机热词
     */
    async getRandomWord() {
        await this.ensureLoaded()
        return this.hotWords.length > 0 ? this.hotWords.pop() : '微软必应'
    }
}

// 导出所有内容
module.exports = {
    // 常量
    BING_DOMAIN,
    REWARDS_DOMAIN,
    BING_URL,
    REWARDS_BASE_URL,
    REWARDS_URL,
    REWARDS_EARN_URL,
    REWARDS_POINTS_URL,
    LIVE_DOMAIN,
    LIVE_URL,
    OAUTH_CLIENT_ID,
    OAUTH_REDIRECT_URI,
    OAUTH_SCOPE,
    OAUTH_AUTHORIZE_URL,
    OAUTH_TOKEN_URL,
    ACCOUNTS_FILE,
    LogTag,
    LogIndent,
    SiteType,
    SITE_CONFIG,
    // 工具函数
    emailMask,
    emailName,
    getUserDataDir,
    sleep,
    rand,
    randFloat,
    extractInt,
    retryDecorator,
    randomString,
    encodeQuery,
    parseQueryString,
    getDateNumber,
    formatTime,
    // 类
    HotWordsManager
}
