/**
 * Account - 账号管理器（包含 AccountStorage、AuthManager、TokenManager）
 */

const fs = require('fs-extra')
const path = require('path')
const axios = require('axios')
const { authenticator } = require('otplib')

// 从 utils 导入需要的常量和工具函数
const {
    ACCOUNTS_FILE, LogTag, LogIndent,
    SiteType, SITE_CONFIG, BING_DOMAIN, REWARDS_DOMAIN, LIVE_DOMAIN,
    OAUTH_AUTHORIZE_URL, OAUTH_CLIENT_ID, OAUTH_REDIRECT_URI, OAUTH_SCOPE, OAUTH_TOKEN_URL,
    sleep, randFloat, emailMask, parseQueryString, getUserDataDir
} = require('./utils')

// ===========================
// AccountStorage 类
// ===========================

/**
 * 账号存储管理类
 */
class AccountStorage {
    /**
     * 获取账号列表
     * @returns {Promise<Array>} 账号列表
     */
    static async getAccounts() {
        if (!fs.existsSync(ACCOUNTS_FILE)) {
            console.error(`${LogTag.ACCOUNT} 未找到账号文件: ${ACCOUNTS_FILE}`)
            return []
        }

        try {
            const data = await fs.readJson(ACCOUNTS_FILE)
            if (!Array.isArray(data)) {
                console.error(`${LogTag.ACCOUNT} 账号文件格式错误: 应为数组`)
                return []
            }

            const accounts = data.filter((acc, index) => {
                return acc.username && acc.password
            }).map((acc, index) => ({
                index: index + 1,
                username: acc.username,
                password: acc.password,
                otpauth: acc.otpauth || '',
                proxy: acc.proxy || ''
            }))

            return accounts
        } catch (e) {
            console.error(`${LogTag.ACCOUNT} 读取读取账号文件异常:`, e.message)
            return []
        }
    }

    /**
     * 获取用户token文件路径
     * @param {string} username - 用户名
     * @returns {string} token文件路径
     */
    static _getTokenPath(username) {
        const userDir = getUserDataDir(username)
        return path.join(userDir, 'app_token.txt')
    }

    /**
     * 获取账号的Token
     * @param {string} username - 用户名
     * @returns {Promise<string|null>} Token字符串或null
     */
    static async getToken(username) {
        const tokenPath = AccountStorage._getTokenPath(username)

        if (!fs.existsSync(tokenPath)) {
            return null
        }

        try {
            const token = await fs.readFile(tokenPath, 'utf-8')
            return token.trim()
        } catch (e) {
            console.error(`${LogTag.LOGIN} 读取Token失败:`, e.message)
            return null
        }
    }

    /**
     * 保存账号Token
     * @param {string} username - 用户名
     * @param {string} token - Token字符串
     * @returns {Promise<boolean>} 是否保存成功
     */
    static async saveToken(username, token) {
        const tokenPath = AccountStorage._getTokenPath(username)

        try {
            // 确保目录存在
            await fs.ensureDir(path.dirname(tokenPath))
            await fs.writeFile(tokenPath, token, 'utf-8')
            console.log(`${LogTag.LOGIN} Token 已保存`)
            return true
        } catch (e) {
            console.error(`${LogTag.LOGIN} 保存Token异常:`, e.message)
            return false
        }
    }
}

// ===========================
// TokenManager 类
// ===========================

/**
 * Token 获取管理类
 */
class TokenManager {
    /**
     * 构造函数
     * @param {Object} browserMgr - 浏览器管理器实例
     */
    constructor(browserMgr) {
        this.browserMgr = browserMgr
        this.page = browserMgr.page
    }

    /**
     * 获取 OAuth refresh_token
     * @returns {Promise<Object|null>} 包含 refresh_token 和 access_token 的对象，失败返回 null
     */
    async getRefreshToken() {
        console.log(`${LogTag.LOGIN} 获取刷新令牌...`)

        try {
            let authCode = null

            // 尝试使用网络监听方式
            try {
                const responsePromise = this.page.waitForResponse(
                    response => response.url().includes('oauth20_desktop.srf') && response.url().includes('code='),
                    { timeout: 15000 }
                )

                await this.page.goto(OAUTH_AUTHORIZE_URL)
                await sleep(3000)

                const response = await responsePromise
                const url = response.url()

                if (url && url.includes('code=')) {
                    const params = parseQueryString(url)
                    if (params.code) {
                        authCode = params.code
                    }
                }
            } catch (e) {
                console.log(`${LogIndent.ITEM}[Token] 网络监听异常: ${e.message}`)
            }

            // 如果网络监听失败，尝试历史记录方式
            if (!authCode) {
                try {
                    const entries = await this.page.evaluate(() => {
                        const navEntries = performance.getEntriesByType('navigation')
                        const resEntries = performance.getEntriesByType('resource')
                        const all = [...navEntries, ...resEntries]
                        return all
                            .filter(e => e.name && e.name.includes('code=') && e.name.includes('oauth20_desktop.srf'))
                            .map(e => e.name)
                    })

                    if (entries && entries.length > 0) {
                        const params = parseQueryString(entries[0])
                        if (params.code) {
                            authCode = params.code
                        }
                    }
                } catch (e) { }
            }

            if (!authCode) {
                console.log(`${LogTag.LOGIN} 未能获取授权码`)
                await this.browserMgr.screenshot('token_auth_code_fail')
                await this.browserMgr.saveHTML('token_auth_code_fail')
                return null
            }

            // 换取 token
            const tokenData = {
                client_id: OAUTH_CLIENT_ID,
                code: authCode,
                grant_type: 'authorization_code',
                redirect_uri: OAUTH_REDIRECT_URI,
                scope: OAUTH_SCOPE
            }

            const response = await axios.post(OAUTH_TOKEN_URL, new URLSearchParams(tokenData).toString(), {
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                timeout: 15000
            })

            if (response.status === 200) {
                const result = response.data
                if (result.refresh_token) {
                    console.log(`${LogTag.LOGIN} 刷新令牌获取成功!`)
                    return {
                        refresh_token: result.refresh_token,
                        access_token: result.access_token
                    }
                }
            }

            return null
        } catch (e) {
            console.log(`${LogTag.LOGIN} 获取刷新令牌异常: ${e.message}`)
            await this.browserMgr.screenshot('token_refresh_exception')
            await this.browserMgr.saveHTML('token_refresh_exception')
            return null
        }
    }

}

// ===========================
// AuthManager 类
// ===========================

/**
 * 统一认证管理器
 * 流程：访问网站 -> 检查状态 -> 未登录则登录 -> 再检查
 */
class AuthManager {
    /**
     * 构造函数
     * @param {Object} page - Playwright页面对象
     * @param {Object} browserMgr - 浏览器管理器实例
     */
    constructor(page, browserMgr) {
        this.page = page
        this.browserMgr = browserMgr
        this.loginStatus = {
            [SiteType.BING]: false,
            [SiteType.REWARDS]: false,
            [SiteType.LIVE]: false
        }
    }

    /**
     * 确保所有站点都已登录
     * @param {string} username - 用户名
     * @param {string} password - 密码
     * @param {string} otpauth - 两步验证密钥（可选）
     * @returns {Promise<boolean>} 是否全部登录成功
     */
    async ensureAllLoggedIn(username, password, otpauth) {
        console.log(`${LogTag.LOGIN} 开始登录流程...`)
        console.log(`${LogIndent.ITEM}邮箱: ${emailMask(username)}`)

        // 只检查 BING 和 REWARDS 站点，不检查 LIVE
        const sites = [SiteType.BING, SiteType.REWARDS]

        for (const site of sites) {
            const success = await this.ensureSiteLoggedIn(site, username, password, otpauth)
            if (!success) {
                console.log(`${LogIndent.END}登录流程失败`)
                await this.browserMgr.screenshot(`login_flow_fail_${site}`)
                await this.browserMgr.saveHTML(`login_flow_fail_${site}`)
                return false
            }
        }

        console.log(`${LogIndent.END}所有站点登录完成`)
        return true
    }

    /**
     * 确保指定站点已登录
     * @param {string} site - 站点类型
     * @param {string} username - 用户名
     * @param {string} password - 密码
     * @param {string} otpauth - 两步验证密钥
     * @returns {Promise<boolean>} 是否登录成功
     */
    async ensureSiteLoggedIn(site, username, password, otpauth) {
        const config = SITE_CONFIG[site]
        console.log(`${LogIndent.ITEM}访问 ${config.name}...`)

        // 1. 访问网站
        try {
            await this.page.goto(config.homeUrl, { waitUntil: 'domcontentloaded', timeout: 45000 })
        } catch (e) {
            console.log(`${LogIndent.ITEM}页面加载超时，继续检查...`)
        }

        // 等待页面稳定
        await sleep(randFloat(2000, 3000))

        // 额外等待重定向完成（特别是 account.live.com）
        try {
            await this.page.waitForLoadState('domcontentloaded', { timeout: 5000 })
        } catch (e) { }

        // 2. 检查登录状态
        if (await this._isLoggedIn(site)) {
            console.log(`${LogIndent.ITEM}${config.name} 已登录`)
            this.loginStatus[site] = true
            return true
        }

        console.log(`${LogIndent.ITEM}${LogTag.LOGIN} ${config.name} 未登录，开始登录...`)

        // 3. 跳转到登录页面
        if (!(await this._gotoLoginPage(site))) {
            console.log(`${LogIndent.ITEM}无法跳转到登录页面`)
            return false
        }

        // 4. 执行登录
        if (!(await this._doLogin(username, password, otpauth))) {
            console.log(`${LogIndent.ITEM}${config.name} 登录失败`)
            return false
        }

        // 5. 登录完成，再次检查
        console.log(`${LogIndent.ITEM}${LogTag.LOGIN} 登录完成，再次检查 ${config.name}...`)
        await this.page.goto(config.homeUrl, { waitUntil: 'domcontentloaded', timeout: 45000 })
        if (await this._isLoggedIn(site)) {
            console.log(`${LogIndent.ITEM}${config.name} 已登录`)
            this.loginStatus[site] = true
            return true
        } else {
            console.log(`${LogIndent.ITEM}${config.name} 登录后检查失败`)
            await this.browserMgr.screenshot(`login_verify_fail_${site}`)
            await this.browserMgr.saveHTML(`login_verify_fail_${site}`)
            this.loginStatus[site] = false
            return false
        }
    }

    /**
     * 检查当前页面是否已登录
     * @param {string} site - 站点类型
     * @returns {Promise<boolean>} 是否已登录
     */
    async _isLoggedIn(site) {
        const currentUrl = this.page.url()
        let pageContent = ''

        // 尝试获取页面内容，如果页面在导航中则使用空字符串
        try {
            pageContent = await this.page.content()
        } catch (e) {
            // 页面正在导航，无法获取内容
            console.log(`${LogIndent.ITEM}页面正在导航中，跳过内容检查`)
        }

        // 如果在登录页面，说明未登录
        if (currentUrl.includes('login.live.com') || currentUrl.includes('login.microsoftonline.com')) {
            return false
        }
        if (currentUrl.toLowerCase().includes('signin')) {
            return false
        }

        switch (site) {
            case SiteType.BING:
                // 检查用户名元素
                try {
                    const userNameEle = await this.page.$('#id_n')
                    if (userNameEle) {
                        const text = await userNameEle.textContent()
                        if (text && text.trim()) return true
                    }
                    // 检查登录按钮
                    const loginBtn = await this.page.$('#id_l')
                    if (loginBtn) return false
                } catch (e) { }
                return false

            case SiteType.REWARDS:
                if (pageContent.includes('"balance"') || pageContent.includes('availablePoints')) {
                    return true
                }
                return currentUrl.includes(REWARDS_DOMAIN)

            case SiteType.LIVE:
                // 对于 LIVE 站点，如果不在登录页面，基本可以认为已登录
                // 因为访问 account.live.com 会自动重定向到已登录状态
                if (currentUrl.includes('account.live.com') || currentUrl.includes('account.microsoft.com')) {
                    return true
                }
                // 如果在 rewards 域名且不在登录页面，也可以认为已登录
                if (currentUrl.includes(REWARDS_DOMAIN)) {
                    return true
                }
                // 检查页面内容中的用户信息
                if (pageContent.includes('"displayName":"') || pageContent.includes('"userDisplayName":"')) {
                    return true
                }
                return false
        }

        return false
    }

    /**
     * 跳转到登录页面
     * @param {string} site - 站点类型
     * @returns {Promise<boolean>} 是否成功跳转
     */
    async _gotoLoginPage(site) {
        const currentUrl = this.page.url()

        if (currentUrl.includes('login.live.com') || currentUrl.includes('login.microsoftonline.com')) {
            return true
        }
        if (site === SiteType.LIVE && (currentUrl.includes('account.live.com') || currentUrl.includes('account.microsoft.com'))) {
            return true
        }

        if (site === SiteType.BING) {
            const loginBtn = await this.page.$('#id_l')
            if (loginBtn) {
                console.log(`${LogIndent.ITEM}${LogTag.LOGIN} 点击登录按钮...`)
                await loginBtn.click()
                await sleep(randFloat(5000, 8000))
                if (await this._waitForLoginPage(5)) {
                    return true
                }
            }

            console.log(`${LogIndent.ITEM}${LogTag.LOGIN} 直接访问 Bing 登录入口...`)
            await this.page.goto('https://www.bing.com/fd/auth/signin/v2?action=interactive&return_url=/', {
                waitUntil: 'domcontentloaded',
                timeout: 45000
            }).catch(() => { })
        }

        return await this._waitForLoginPage(15)
    }

    /**
     * 等待登录页面加载
     * @param {number} timeout - 超时时间（秒）
     * @returns {Promise<boolean>} 是否成功加载
     */
    async _waitForLoginPage(timeout = 15) {
        for (let i = 0; i < timeout; i++) {
            const currentUrl = this.page.url()
            if (currentUrl.includes('login.live.com') || currentUrl.includes('login.microsoftonline.com')) {
                return true
            }
            if (currentUrl.includes('account.live.com') || currentUrl.includes('account.microsoft.com')) {
                return true
            }

            try {
                const emailInput = await this.page.$('#usernameEntry')
                const altEmailInput = await this.page.$('#i0116')
                if (emailInput || altEmailInput) {
                    return true
                }
            } catch (e) {
                if (!String(e.message || '').includes('Execution context was destroyed')) {
                    throw e
                }
            }

            await sleep(1000)
        }
        return false
    }

    /**
     * 执行登录流程
     * @param {string} username - 用户名
     * @param {string} password - 實碼
     * @param {string} otpauth - 两步验证密钥
     * @returns {Promise<boolean>} 是否登录成功
     */
    async _doLogin(username, password, otpauth) {
        await sleep(2000)

        // 等待 React SPA 渲染登录表单
        console.log(`${LogIndent.ITEM}${LogTag.LOGIN} 等待登录表单渲染...`)
        try {
            await this.page.waitForSelector('#usernameEntry, #i0116, #i0118, #passwordEntry', { timeout: 15000 })
            await sleep(1000)
        } catch (e) {
            console.log(`${LogIndent.ITEM}${LogTag.LOGIN} 等待登录表单渲染超时，继续尝试...`)
        }

        let lastPageType = null
        let repeatCount = 0

        for (let i = 0; i < 15; i++) {
            const pageType = await this._detectPageType()
            console.log(`${LogIndent.ITEM}当前页面: ${pageType}`)

            // 检测重复页面
            if (pageType === lastPageType) {
                repeatCount++
                if (repeatCount >= 2) {
                    console.log(`${LogIndent.ITEM}页面类型重复出现 ${repeatCount} 次，终止登录`)
                    await this.browserMgr.screenshot(`login_repeat_${pageType}`)
                    await this.browserMgr.saveHTML(`login_repeat_${pageType}`)
                    return false
                }
            } else {
                repeatCount = 0
                lastPageType = pageType
            }

            switch (pageType) {
                case 'success':
                    return true
                case 'error':
                    await this.browserMgr.screenshot('login_error_page')
                    await this.browserMgr.saveHTML('login_error_page')
                    return false
                case 'email':
                    if (!(await this._inputEmail(username))) return false
                    break
                case 'select_method':
                    await this._selectPasswordLogin()
                    break
                case 'password':
                    if (!(await this._inputPassword(password))) return false
                    break
                case '2fa':
                    if (!(await this._handle2FA(otpauth))) return false
                    break
                case 'stay_signed_in':
                    await this._clickStaySignedIn()
                    break
                case 'msa_upsell':
                    await this._handleMsaUpsell()
                    break
                case 'send_code_page':
                    await this._clickUsePassword()
                    break
                default:
                    await sleep(2000)
            }
            await sleep(2000)
        }
        return false
    }

    /**
     * 检测当前页面类型
     * @returns {Promise<string>} 页面类型
     */
    async _detectPageType() {
        const currentUrl = this.page.url()
        let pageContent = ''

        // 尝试获取页面内容
        try {
            pageContent = await this.page.content()
        } catch (e) {
            // 页面正在导航，使用空字符串
        }

        // 检查URL判断是否在登录页面
        const urlLower = currentUrl.toLowerCase()
        const isLoginPage = urlLower.includes('login.') || urlLower.includes('/login') || urlLower.includes('signin')

        if (!isLoginPage) {
            if (currentUrl.includes(BING_DOMAIN) || currentUrl.includes('account.live.com') || currentUrl.includes('account.microsoft.com')) {
                return 'success'
            }
        }

        // 检测错误页面
        const errorPatterns = [
            '已被锁定', '密码不正确', 'help us protect your account',
            'your account has been locked', "account doesn't exist",
            "that microsoft account doesn't exist", '账户不存在', '找不到 microsoft 帐户',
            '找不到 microsoft 账户', '请尝试重新输入你的详细信息', 'sign-in was blocked'
        ]
        const pageContentLower = pageContent.toLowerCase()
        for (const pattern of errorPatterns) {
            if (pageContentLower.includes(pattern.toLowerCase())) {
                return 'error'
            }
        }

        // 检测邮箱输入框
        const emailInput = await this.page.$('#usernameEntry')
        const altEmailInput = await this.page.$('#i0116')
        if (emailInput || altEmailInput) {
            return 'email'
        }

        // 检测密码输入框
        const passwordInput = await this._findPasswordInput()
        if (passwordInput) {
            return 'password'
        }

        // 检测2FA输入框
        const otpInput = await this.page.$('#idTxtBx_SAOTCC_OTC')
        const altOtpInput = await this.page.$('#otc-confirmation-input')
        if (otpInput || altOtpInput) {
            return '2fa'
        }

        // 检测发送验证码页面
        const sendCodePatterns = [
            'get a code to sign in', '获取代码以登录', '获取用于登录的代码',
            '发送验证码', 'send code', 'use your password', '使用密码'
        ]
        for (const pattern of sendCodePatterns) {
            if (pageContentLower.includes(pattern)) {
                return 'send_code_page'
            }
        }

        // 检测保持登录页面
        const stayBtn = await this.page.$('#idSIButton9')
        const acceptBtn = await this.page.$('#acceptButton')
        const primaryBtn = await this.page.$('[data-testid="primaryButton"]')
        if (stayBtn || acceptBtn || primaryBtn) {
            const titleEl = await this.page.$('#title')
            const altTitleEl = await this.page.$('[data-testid="title"]')
            const titleText = titleEl ? await titleEl.textContent() : ''
            const altTitleText = altTitleEl ? await altTitleEl.textContent() : ''
            const combinedText = (titleText + altTitleText).toLowerCase()
            if (combinedText.includes('stay signed in') || combinedText.includes('保持')) {
                return 'stay_signed_in'
            }
        }

        // 检测其他登录方式
        const otherMethodsPatterns = [
            'other ways to sign in', 'sign in another way', 'other sign-in options',
            '其他登录方式', '其他登录方法'
        ]
        for (const pattern of otherMethodsPatterns) {
            if (pageContentLower.includes(pattern)) {
                return 'select_method'
            }
        }

        // 检测msa_upsell页面
        const msaUpsell = await this.page.$('#msa_upsell')
        const positiveCta = await this.page.$('#positive_cta')
        const postponeCta = await this.page.$('#postpone_cta')
        if (msaUpsell || positiveCta || postponeCta) {
            return 'msa_upsell'
        }

        return 'unknown'
    }

    /**
     * 输入邮箱
     * @param {string} email - 邮箱地址
     * @returns {Promise<boolean>} 是否成功
     */
    async _inputEmail(email) {
        console.log(`${LogIndent.ITEM}${LogTag.LOGIN} 输入邮箱...`)

        let input = await this.page.$('#usernameEntry')
        if (!input) input = await this.page.$('#i0116')

        if (!input) {
            console.log(`${LogIndent.ITEM}未找到邮箱输入框`)
            await this.browserMgr.screenshot('login_email_input_not_found')
            await this.browserMgr.saveHTML('login_email_input_not_found')
            return false
        }

        await input.fill('')
        await sleep(500)
        await input.fill(email)
        await sleep(1000)

        return await this._clickNext()
    }

    /**
     * 输入密码
     * @param {string} password - 密码
     * @returns {Promise<boolean>} 是否成功
     */
    async _inputPassword(password) {
        console.log(`${LogIndent.ITEM}${LogTag.LOGIN} 输入密码...`)

        const input = await this._findPasswordInput()
        if (!input) {
            console.log(`${LogIndent.ITEM}未找到密码输入框`)
            await this.browserMgr.screenshot('login_password_input_not_found')
            await this.browserMgr.saveHTML('login_password_input_not_found')
            return false
        }

        await input.fill('')
        await sleep(500)
        await input.fill(password)
        await sleep(1000)

        return await this._clickNext()
    }

    /**
     * 查找密码输入框
     * @returns {Promise<Object|null>} 密码输入框元素
     */
    async _findPasswordInput() {
        const selectors = ['#i0118', '#passwordEntry', 'input[name="passwd"]', 'input[type="password"]']
        for (const sel of selectors) {
            const el = await this.page.$(sel)
            if (el) return el
        }
        return null
    }

    /**
     * 选择密码登录
     */
    async _selectPasswordLogin() {
        console.log(`${LogIndent.ITEM}${LogTag.LOGIN} 选择密码登录...`)

        try {
            // 点击 "Other ways to sign in" 按钮
            await this.page.evaluate(() => {
                const els = document.querySelectorAll('span[role="button"], a, button, div[role="button"]')
                for (const el of els) {
                    const t = (el.textContent || '').toLowerCase()
                    if (t.includes('other ways') || t.includes('other sign-in options') || t.includes('其他登录')) {
                        el.click()
                        break
                    }
                }
            })
            await sleep(2000)

            // 点击 "使用密码登录" 选项
            await this.page.evaluate(() => {
                const els = document.querySelectorAll('[data-testid="credential-picker-password"], [data-testid="tile"], button, a, div[role="button"]')
                for (const el of els) {
                    const t = (el.textContent || '').toLowerCase()
                    if (t.includes('use a password') || t.includes('use your password') || t.includes('password') || t.includes('使用密码')) {
                        el.click()
                        break
                    }
                }
            })
            await sleep(1000)
        } catch (e) { }
    }

    /**
     * 处理两步验证
     * @param {string} otpauth - 两步验证密钥
     * @returns {Promise<boolean>} 是否成功
     */
    async _handle2FA(otpauth) {
        console.log(`${LogIndent.ITEM}${LogTag.LOGIN} 处理两步验证...`)

        if (!otpauth) {
            console.log(`${LogIndent.ITEM}未配置 otpauth`)
            await this.browserMgr.screenshot('login_2fa_no_otpauth')
            await this.browserMgr.saveHTML('login_2fa_no_otpauth')
            return false
        }

        try {
            // 解析 otpauth URL 并生成 TOTP 码
            const code = await this._generateTOTP(otpauth)
            console.log(`${LogIndent.ITEM}验证码: ${code}`)

            // 等待页面稳定
            await sleep(2000)

            // 多种2FA输入框选择器（按优先级排序）
            const selectors = [
                '#idTxtBx_SAOTCC_OTC',
                '#otc-confirmation-input',
                'input[id*="otc"]',
                'input[id*="Otc"]',
                'input[id*="floatingLabelInput"]',
                'input[maxlength="6"][type="text"]',
                'input[maxlength="7"][type="text"]',
                '.fui-Input__input[type="text"]'
            ]

            // 使用 waitForSelector 等待任一选择器出现
            let inputLocator = null
            for (const selector of selectors) {
                try {
                    const locator = this.page.locator(selector)
                    const isVisible = await locator.isVisible({ timeout: 2000 }).catch(() => false)
                    if (isVisible) {
                        inputLocator = locator
                        console.log(`${LogIndent.ITEM}找到输入框: ${selector}`)
                        break
                    }
                } catch (e) { continue; }
            }

            if (!inputLocator) {
                // 尝试等待输入框出现
                console.log(`${LogIndent.ITEM}等待2FA输入框...`)
                for (const selector of selectors) {
                    try {
                        inputLocator = this.page.locator(selector)
                        await inputLocator.waitFor({ state: 'visible', timeout: 10000 })
                        console.log(`${LogIndent.ITEM}找到输入框: ${selector}`)
                        break
                    } catch (e) {
                        inputLocator = null
                        continue
                    }
                }
            }

            if (!inputLocator) {
                console.log(`${LogIndent.ITEM}未找到2FA输入框，保存调试信息`)
                await this.browserMgr.screenshot('login_2fa_input_not_found')
                await this.browserMgr.saveHTML('login_2fa_input_not_found')
                return false
            }

            // 确保元素可见并可交互
            await inputLocator.scrollIntoViewIfNeeded()
            await sleep(500)

            // 点击输入框获取焦点
            await inputLocator.click()
            await sleep(300)

            // 清空并输入验证码
            await inputLocator.fill('')
            await sleep(200)
            await inputLocator.fill(code)
            console.log(`${LogIndent.ITEM}验证码已输入: ${code}`)
            await sleep(1000)

            // 点击下一步/验证按钮
            const clicked = await this._clickNext()
            if (!clicked) {
                // 尝试按回车键提交
                await inputLocator.press('Enter')
                console.log(`${LogIndent.ITEM}按回车提交验证码`)
            }

            await sleep(2000)
            return true
        } catch (e) {
            console.log(`${LogIndent.ITEM}2FA异常: ${e.message}`)
            await this.browserMgr.screenshot('login_2fa_exception')
            await this.browserMgr.saveHTML('login_2fa_exception')
        }
        return false
    }

    /**
     * 生成 TOTP 验证码
     * @param {string} otpauth - 两步验证密钥（otpauth:// URL 或 secret）
     * @returns {Promise<string>} 验证码
     */
    async _generateTOTP(otpauth) {
        // 配置 TOTP 参数
        authenticator.options = {
            digits: 6,        // 6位数字
            step: 30,         // 30秒更新一次
            encoding: 'hex',  // 使用 hex 编码
            algorithm: 'sha1'
        }

        // 如果是完整的 otpauth:// URL，需要提取 secret
        let secret = otpauth
        if (otpauth.startsWith('otpauth://')) {
            const url = new URL(otpauth)
            secret = url.searchParams.get('secret')

            if (!secret) {
                throw new Error('无法从 otpauth URL 中提取 secret')
            }

            console.log(`${LogIndent.ITEM}提取 secret: ${secret.substring(0, 4)}...`)

            // 检查 URL 中的参数覆盖默认配置
            const digits = url.searchParams.get('digits')
            if (digits) authenticator.options.digits = parseInt(digits)

            const period = url.searchParams.get('period')
            if (period) authenticator.options.step = parseInt(period)
        }

        // 生成验证码
        const code = authenticator.generate(secret)
        console.log(`${LogIndent.ITEM}生成验证码: ${code}`)

        return code
    }

    /**
     * 点击保持登录
     */
    async _clickStaySignedIn() {
        console.log(`${LogIndent.ITEM}${LogTag.LOGIN} 点击保持登录...`)

        let btn = await this.page.$('#idSIButton9')
        if (!btn) btn = await this.page.$('[data-testid="primaryButton"]')

        if (btn) {
            await btn.click()
            await sleep(2000)
        }
    }

    /**
     * 处理 msa_upsell 确认页面
     */
    async _handleMsaUpsell() {
        console.log(`${LogIndent.ITEM}${LogTag.LOGIN} 处理登录确认页面...`)

        let btn = await this.page.$('#postpone_cta')
        if (!btn) btn = await this.page.$('#positive_cta')

        if (btn) {
            await btn.click()
            await sleep(2000)
        }
    }

    /**
     * 点击使用密码
     */
    async _clickUsePassword() {
        console.log(`${LogIndent.ITEM}${LogTag.LOGIN} 点击'使用密码登录'...`)

        // 尝试各种选择器
        const selectors = [
            'text=Use your password',
            'text=使用密码',
            'xpath://*[contains(@role,"button") and contains(., "使用密码")]',
            'xpath://a[contains(., "Use your password") or contains(., "使用密码")]'
        ]

        for (const sel of selectors) {
            try {
                const el = await this.page.$(sel)
                if (el) {
                    await el.click()
                    await sleep(2000)
                    return
                }
            } catch (e) { }
        }

        // 如果找不到，尝试其他登录方式
        await this._selectPasswordLogin()
    }

    /**
     * 点击下一步按钮
     * @returns {Promise<boolean>} 是否成功
     */
    async _clickNext() {
        let btn = await this.page.$('button[data-testid="primaryButton"]')
        if (btn) {
            await btn.click()
            return true
        }

        btn = await this.page.$('#idSIButton9')
        if (btn) {
            await btn.click()
            return true
        }

        const texts = ['下一步', '登录', 'Next', 'Sign in', '验证']
        for (const text of texts) {
            btn = await this.page.$(`button:has-text("${text}")`)
            if (btn) {
                await btn.click()
                return true
            }
        }

        return false
    }

}

// 导出所有类
module.exports = {
    AccountStorage,
    TokenManager,
    AuthManager
}
