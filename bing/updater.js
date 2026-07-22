/**
 * Updater - 自动更新管理器
 * 从云端检查版本并下载更新
 */

const axios = require('axios')
const fs = require('fs-extra')
const path = require('path')
const { LogTag, LogIndent, sleep, randFloat } = (() => {
    try {
        return require('./utils')
    } catch (_) {
        // 允许独立运行 updater.js（utils.js 不存在时降级）
        return {
            LogTag: { SYSTEM: '[System]' },
            LogIndent: { ITEM: '   ├── ', END: '   └── ' },
            sleep: (ms) => new Promise(r => setTimeout(r, ms)),
            randFloat: (a, b) => Math.random() * (b - a) + a,
        }
    }
})()

// 云端更新服务器地址（可配置）
const UPDATE_SERVER_URL = 'https://www.zgcwkj.cn/scriptBing'

/**
 * 更新管理器类
 */
class UpdaterManager {
    /**
     * 构造函数
     * @param {string} currentVersion - 当前程序版本号（从 index.js 传入）
     */
    constructor(currentVersion) {
        this.currentVersion = currentVersion || 'v0.0.0'
    }

    /**
     * 解析版本号进行比较
     * @param {string} v1 - 版本1
     * @param {string} v2 - 版本2
     * @returns {number} -1: v1 < v2, 0: v1 = v2, 1: v1 > v2
     */
    compareVersions(v1, v2) {
        // 移除 'v' 前缀
        const cleanV1 = v1.replace(/^v/, '')
        const cleanV2 = v2.replace(/^v/, '')

        const parts1 = cleanV1.split('.').map(p => parseInt(p, 10) || 0)
        const parts2 = cleanV2.split('.').map(p => parseInt(p, 10) || 0)

        const maxLen = Math.max(parts1.length, parts2.length)

        for (let i = 0; i < maxLen; i++) {
            const p1 = parts1[i] || 0
            const p2 = parts2[i] || 0
            if (p1 < p2) return -1
            if (p1 > p2) return 1
        }

        return 0
    }

    /**
     * 从云端获取更新信息
     * @returns {Promise<Object|null>} 更新信息 {version, files} 或 null
     */
    async fetchUpdateInfo() {
        try {
            console.log(`${LogIndent.ITEM}检查更新: ${UPDATE_SERVER_URL}`)

            const response = await axios.get(UPDATE_SERVER_URL, {
                timeout: 15000
            })

            const lines = response.data.trim().split('\n').filter(line => line.trim())
            if (lines.length < 2) {
                console.log(`${LogIndent.ITEM}更新文件格式错误`)
                return null
            }

            const version = lines[0].trim()
            const files = lines.slice(1).map(line => line.trim()).filter(line => line)

            console.log(`${LogIndent.ITEM}本地版本: ${this.currentVersion}`)
            console.log(`${LogIndent.ITEM}云端版本: ${version}`)

            // 比较版本：使用传入的当前版本号
            if (this.compareVersions(version, this.currentVersion) <= 0) {
                console.log(`${LogIndent.END}已是最新版本`)
                return null
            }

            console.log(`${LogIndent.ITEM}发现新版本: ${this.currentVersion} → ${version}`)

            return { version, files }
        } catch (e) {
            console.log(`${LogIndent.END}检查更新失败: ${e.message}`)
            return null
        }
    }

    /**
     * 下载单个文件
     * @param {string} fileUrl - 文件URL
     * @param {string} savePath - 保存路径
     * @returns {Promise<boolean>} 是否成功
     */
    async downloadFile(fileUrl, savePath) {
        try {
            // 确保目录存在
            await fs.ensureDir(path.dirname(savePath))

            const response = await axios.get(fileUrl, {
                responseType: 'arraybuffer',
                timeout: 30000
            })

            await fs.writeFile(savePath, response.data)
            return true
        } catch (e) {
            console.log(`${LogIndent.ITEM}下载失败 ${fileUrl}: ${e.message}`)
            return false
        }
    }

    /**
     * 执行更新
     * @param {Object} updateInfo - 更新信息
     * @returns {Promise<boolean>} 是否成功
     */
    async performUpdate(updateInfo) {
        const { version, files } = updateInfo
        const successFiles = []
        const failedFiles = []

        console.log(`${LogIndent.ITEM}开始更新 ${files.length} 个文件...`)

        for (let i = 0; i < files.length; i++) {
            if (files[i] == '') continue
            const fileUrl = files[i]
            const urlPathname = new URL(fileUrl).pathname
            const filePath = path.basename(urlPathname)
            const savePath = path.join(__dirname, filePath)

            console.log(`${LogIndent.ITEM} [${i + 1}/${files.length}] 下载: ${filePath}`)

            const success = await this.downloadFile(fileUrl, savePath)
            if (success) {
                successFiles.push(filePath)
            } else {
                failedFiles.push(filePath)
            }

            // 随机延迟，避免被限流
            await sleep(randFloat(500, 1500))
        }

        // 更新版本文件
        if (successFiles.length > 0 && failedFiles.length === 0) {
            console.log(`${LogIndent.ITEM}更新完成: ${version}`)
            return true
        } else if (successFiles.length > 0) {
            console.log(`${LogIndent.ITEM}部分更新成功: ${successFiles.length}/${files.length}`)
            console.log(`${LogIndent.ITEM}失败的文件: ${failedFiles.join(', ')}`)
            // 只有全部成功才更新版本号
            return false
        }

        return false
    }

    /**
     * 检查并执行更新
     * @returns {Promise<Object>} 更新结果 {updated, version, files}
     */
    async checkAndUpdate() {
        console.log(`${LogTag.SYSTEM} 检查更新...`)

        const updateInfo = await this.fetchUpdateInfo()
        if (!updateInfo) {
            return { updated: false, version: this.currentVersion }
        }

        const success = await this.performUpdate(updateInfo)

        if (success) {
            console.log(`${LogIndent.ITEM}更新成功，准备重启...`)
            console.log(`${LogIndent.END}可能需要手动重启...`)
            // 延迟重启，确保文件写入完成
            await sleep(2000)

            // 使用 process.exit 让外部脚本处理重启
            process.exit(10)
        }

        return {
            updated: success,
            version: updateInfo.version,
            files: updateInfo.files
        }
    }
}

/**
 * 主函数 - 在项目启动前调用
 * @param {string} version - 版本号
 * @returns {Promise<Object>} 更新结果
 */
async function checkForUpdates(version) {
    // 跳过更新标识
    const skipFile = 'updater.skip'
    if (fs.existsSync(skipFile)) {
        return { updated: false }
    }
    // 更新管理器
    const updater = new UpdaterManager(version)
    return await updater.checkAndUpdate()
}

/**
 * 命令行入口
 * wget UPDATE_SERVER_URL/updater.js
 * npm install axios
 * npm install fs-extra
 * node updater.js
 */
async function main() {
    console.log('[Updater] 通过云端获取脚本...')

    // 直接使用固定版本号进行更新
    const result = await checkForUpdates('v200101.001')

    if (result.updated) {
        console.log('[Updater] 获取成功')
    } else {
        console.log('[Updater] 已是最新版本，无需更新')
    }
}

/**
 * 判断是否直接运行
 */
if (require.main === module) {
    main().catch(err => {
        console.error('[Updater] 异常:', err)
        process.exit(1)
    })
}

module.exports = { UpdaterManager, checkForUpdates }
