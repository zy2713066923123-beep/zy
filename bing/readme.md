# Bing Rewards - Node.js 版本

自动完成 Bing 搜索任务、积分任务、APP签到等。

## 功能特性

- 🔐 自动登录微软账号（支持两步验证）
- 🔍 自动执行搜索任务获取积分
- 📋 自动完成打卡任务和活动任务
- 📱 APP 签到和阅读任务（通过 API）
- 💰 自动领取待领取积分

## 文件结构

```
├── accounts.json      # 账号配置文件
├── index.js           # 主程序入口
├── utils.js           # 常量、日志、工具函数、热搜词管理
├── browser.js         # 浏览器管理器
├── account.js         # 账号存储、认证管理、Token管理
├── points.js          # 积分获取、积分页面任务
├── search.js          # 搜索任务管理
├── appTask.js         # APP任务（签到、阅读）
└── package.json       # 项目配置
```

## 模块说明

| 文件 | 说明 |
|------|------|
| `utils.js` | 全局常量（URL、OAuth配置）、日志标签、工具函数（sleep、rand等）、HotWordsManager热搜词管理 |
| `browser.js` | BrowserManager 类，负责浏览器启动、截图、保存HTML、清理 |
| `account.js` | AccountStorage（账号读写）、AuthManager（登录认证）、TokenManager（OAuth令牌） |
| `points.js` | PointsManager（积分解析）、PointsPageManager（打卡/活动任务） |
| `search.js` | SearchManager，执行搜索任务 |
| `appTask.js` | AppTaskManager，APP签到和阅读任务（API调用） |

## 安装

```bash
npm install
```

## 配置

在 `accounts.json` 中配置账号：

```json
[
  {
    "username": "your_email@outlook.com",
    "password": "your_password",
    "otpauth": "otpauth://totp/...?secret=..."
  }
]
```

## 运行

```bash
npm start
```

或直接运行：

```bash
node index.js
```

## 依赖

- fs-extra - 文件系统增强
- axios - HTTP 请求
- playwright - 浏览器自动化
- otplib - TOTP 两步验证

## 说明

- 调试截图和 HTML 保存在 `debug` 目录
- 程序会自动管理登录状态，Cookie 保存在 `user_data_用户名` 目录
- Token 缓存在用户数据目录的 `app_token.txt` 文件中
