/**
 * Browser - 浏览器管理器
 */

const { chromium } = require('playwright')
const path = require('path')
const fs = require('fs-extra')
const { execSync } = require('child_process')

// 浏览器可执行文件路径列表
const browserPaths = [
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/CentBrowser/chrome.exe",
    "D:/Program Files (x86)/CentBrowser/chrome.exe",
    "D:/Application/CentBrowser/chrome.exe",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome"
]

// 缓存查找到的浏览器路径，避免每次 init 都扫描文件系统
let _cachedBrowserPath = null

// 用户代理
const userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"

/**
 * 查找可用的浏览器可执行文件路径（带缓存）
 * @returns {string|null} - 返回第一个存在的浏览器路径，如果都不存在则返回 null
 */
function findBrowserPath() {
    if (_cachedBrowserPath) return _cachedBrowserPath
    for (const browserPath of browserPaths) {
        if (fs.existsSync(browserPath)) {
            _cachedBrowserPath = browserPath
            return _cachedBrowserPath
        }
    }
    return null
}

/**
 * 清理残留的浏览器进程
 */
function killResidual() {
    try {
        if (process.platform === 'win32') {
            execSync('taskkill /f /im chrome.exe 2>nul & taskkill /f /im chromium.exe 2>nul & taskkill /f /im centbrowser.exe 2>nul', { stdio: 'ignore' })
        } else {
            execSync('pkill -f "chrome|chromium|chromium-browser" 2>/dev/null; pkill -f "Xvfb" 2>/dev/null; pkill -f "x11vnc" 2>/dev/null', { stdio: 'ignore' })
        }
    } catch (_) { }
}

// 从 utils 导入常量、工具函数
const {
    getUserDataDir,
    LogTag
} = require('./utils')

/**
 * 浏览器管理器类
 */
class BrowserManager {
    /**
     * 构造函数
     * @param {string} username - 用户名（用于用户数据目录）
     * @param {string} proxy - SOCKS5 代理地址，如 socks5://127.0.0.1:1080
     */
    constructor(username = "", proxy = "") {
        this.username = username
        this.proxy = proxy
        this.browser = null
        this.context = null
        this.page = null
    }

    /**
     * 初始化浏览器
     */
    async init() {
        // 清理残留进程
        killResidual()

        // 创建用户数据目录
        const userDir = getUserDataDir(this.username)
        await fs.ensureDir(userDir)

        // 查找浏览器可执行文件路径
        const executablePath = findBrowserPath()
        if (!executablePath) {
            throw new Error('未找到可用的浏览器可执行文件，请安装 chromium、chromium-browser 或 google-chrome')
        }
        console.log(`${LogTag.SYSTEM} 使用浏览器路径: ${executablePath}`)

        // 启动持久化浏览器上下文
        // 在 Windows 上使用有头模式，在其他系统上如果没有 DISPLAY 则使用无头模式
        const headless = process.platform === 'win32' ? false : !process.env.DISPLAY
        this.context = await chromium.launchPersistentContext(userDir, {
            headless: headless,
            executablePath: executablePath,
            viewport: { width: 1920, height: 1080 },
            locale: 'zh-CN',
            extraHTTPHeaders: {
                'Accept-Language': 'zh-CN,zh;q=0.9'
            },
            args: [
                '--no-sandbox',
                '--disable-gpu',
                '--disable-dev-shm-usage',
                '--lang=zh-CN',
                '--accept-lang=zh-CN,zh;q=0.9',
                // '--lang=en-US',
                // '--accept-lang=en-US,en;q=0.9',
                '--window-size=1920,1080',
                '--mute-audio',
                '--disable-password-manager-reauthentication',
                '--autoplay-policy=no-user-gesture-required',
                // 禁用 passkey / 安全密钥相关能力，尽量让微软登录回落到密码路径
                '--disable-features=WebAuthentication,WebAuthn,WebAuthnConditionalUI,WebAuthnEnclaveAuthenticator,WebAuthnCable',
                // 添加 User-Agent 以避免被识别为机器人
                '--user-agent=' + userAgent,
                // 消除截图中的“崩溃恢复”弹窗和自动化提示栏
                '--disable-infobars',
                '--disable-session-crashed-bubble',
                '--hide-crash-restore-bubble',
                // SOCKS5 代理
                ...(this.proxy ? ['--proxy-server=' + this.proxy] : [])
            ],
            userAgent: userAgent
        })

        // 获取或创建页面
        this.page = this.context.pages()[0] || await this.context.newPage()

        // 路由拦截：过滤图片、字体、音频、视频以及微软 Clarity 行为追踪器
        await this.page.route('**/*', (route) => {
            const url = route.request().url()
            if (
                route.request().resourceType() === 'image' ||
                route.request().resourceType() === 'font' ||
                route.request().resourceType() === 'media' ||
                url.includes('clarity.ms')
            ) {
                route.abort()
            } else {
                route.continue()
            }
        })

        // 设置全局默认超时
        this.context.setDefaultTimeout(15000)
        this.context.setDefaultNavigationTimeout(45000)
        this.page.setDefaultTimeout(15000)
        this.page.setDefaultNavigationTimeout(45000)

        // 输出代理信息
        if (this.proxy) {
            console.log(`[Browser] 使用代理: ${this.proxy}`)
        }

        // 屏蔽 WebAuthn / Credentials API，防止进入 FIDO 流
        await this.context.addInitScript(() => {
            try {
                const navProto = Object.getPrototypeOf(navigator)
                if (navProto && Object.prototype.hasOwnProperty.call(navProto, 'credentials')) {
                    Object.defineProperty(navProto, 'credentials', {
                        configurable: true,
                        get() {
                            return {
                                get: async () => { throw new Error('credentials.get disabled'); },
                                create: async () => { throw new Error('credentials.create disabled'); },
                                preventSilentAccess: async () => { },
                                store: async () => null,
                            }
                        },
                    })
                }

                if (typeof window.PublicKeyCredential !== 'undefined') {
                    Object.defineProperty(window, 'PublicKeyCredential', {
                        configurable: true,
                        value: undefined,
                    })
                }
            } catch (_) { }
        })

        console.log(`${LogTag.SYSTEM} 浏览器启动成功`)
    }

    /**
     * 保存页面截图
     * @param {string} name - 截图名称
     */
    async screenshot(name) {
        const safeName = String(name).replace(/[^a-zA-Z0-9_-]/g, '_')
        const file = `./debug/${safeName}_${Date.now()}.png`
        await fs.ensureDir(path.join(__dirname, 'debug'))
        await this.page.screenshot({ path: file })
        console.log(`${LogTag.SYSTEM} 截图: ${file}`)
    }

    /**
     * 保存页面 HTML
     * @param {string} name - 文件名称
     */
    async saveHTML(name) {
        const html = await this.page.content()
        const safeName = String(name).replace(/[^a-zA-Z0-9_-]/g, '_')
        const file = `./debug/${safeName}_${Date.now()}.html`
        await fs.ensureDir(path.join(__dirname, 'debug'))
        await fs.writeFile(file, html)
    }

    /**
     * 获取当前页面
     * @returns {import('playwright').Page|null}
     */
    getPage() {
        return this.page
    }

    /**
     * 获取浏览器上下文
     * @returns {import('playwright').BrowserContext|null}
     */
    getContext() {
        return this.context
    }

    /**
     * 导航到指定URL
     * @param {string} url
     */
    async goto(url) {
        if (this.page) {
            await this.page.goto(url, { waitUntil: 'domcontentloaded' })
        }
    }

    /**
     * 执行JavaScript
     * @param {string} script
     * @returns {Promise<any>}
     */
    async evaluate(script) {
        if (this.page) {
            return await this.page.evaluate(script)
        }
        return null
    }

    /**
     * 获取页面URL
     * @returns {string}
     */
    getUrl() {
        return this.page ? this.page.url() : ''
    }

    /**
     * 获取页面标题
     * @returns {Promise<string>}
     */
    async getTitle() {
        if (!this.page) return ''
        try {
            return await this.page.title()
        } catch (err) {
            // 页面导航时执行上下文可能被销毁
            return 'Loading...'
        }
    }

    /**
     * 清理浏览器资源
     */
    async cleanup() {
        if (!this.context) return
        await this.context.close()
        console.log(`${LogTag.SYSTEM} 浏览器关闭`)
    }
}

// 导出函数
module.exports = BrowserManager
module.exports.BrowserManager = BrowserManager
module.exports.findBrowserPath = findBrowserPath
module.exports._resetBrowserPathCache = () => { _cachedBrowserPath = null }
