/**
 * 远程浏览器
 *
 * 功能：远程浏览器（Chromium + Xvfb + x11vnc + noVNC）
 * 用法： node novnc.js [url] [选项]
 * 选项：
 *   --proxy, -p <addr>           SOCKS5 代理，如 socks5://127.0.0.1:1080
 *   --username, -u <name>        用户名（用于自动生成用户数据目录名）
 *   --port, -P <port>            HTTP 服务端口，默认 7856
 * Linux 依赖：chromium、chromium-chromedriver、xvfb、x11vnc
 * Node 依赖：playwright
 * by zgcwkj
 */

const http = require('http');
const net = require('net');
const crypto = require('crypto');
const { spawn } = require('child_process');
const BrowserManager = require('./browser');
const { findBrowserPath } = require('./browser');

// 解析命令行参数
function parseArgs() {
    const args = process.argv.slice(2);
    const cfg = {
        url: 'https://www.bing.com',
        proxy: '',
        username: 'test',
        httpPort: 7856,
    };

    let i = 0;
    while (i < args.length) {
        const a = args[i];
        if (a === '--username' || a === '-u') {
            cfg.username = args[++i] || '';
        } else if (a === '--proxy' || a === '-p') {
            cfg.proxy = args[++i] || '';
        } else if (a === '--port' || a === '-P') {
            cfg.httpPort = parseInt(args[++i]) || 7856;
        } else if (!a.startsWith('-')) {
            cfg.url = a;
        }
        i++;
    }
    return cfg;
}

const CLI = parseArgs();

// 配置
const CFG = {
    httpPort: CLI.httpPort,
    vncPort: 5900,
    display: ':99',
    screenW: 1920,
    screenH: 1080,
    url: CLI.url,
};

// 工具函数
const log = (msg) => console.log(`[novnc] ${msg}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function run(name, args) {
    return new Promise((resolve, reject) => {
        const proc = spawn(name, args, { stdio: 'inherit' });
        proc.on('error', reject);
        // 进程启动后返回
        proc.once('spawn', () => resolve(proc));
    });
}

// Xvfb 虚拟显示
async function startXvfb() {
    log(`正在启动 Xvfb ${CFG.display} (${CFG.screenW}x${CFG.screenH})...`);
    try {
        await run('Xvfb', [
            CFG.display,
            '-screen', '0',
            `${CFG.screenW}x${CFG.screenH}x24`,
            '-ac',
            '+extension', 'RANDR',
        ]);
    } catch (e) {
        if (e.code === 'ENOENT') {
            log('错误: 未找到 Xvfb。安装: sudo apt install xvfb');
            process.exit(1);
        }
        throw e;
    }
}

// x11vnc VNC 服务
async function startX11vnc() {
    log(`正在启动 x11vnc，端口 ${CFG.vncPort}...`);
    try {
        await run('x11vnc', [
            '-display', CFG.display,
            '-rfbport', String(CFG.vncPort),
            '-forever',
            '-shared',
            '-nopw',
            '-quiet',
            '-xkb',
            '-noxdamage',
            '-noxfixes',
            '-rfbversion', '3.8',
        ]);
    } catch (e) {
        if (e.code === 'ENOENT') {
            log('错误: 未找到 x11vnc。安装: sudo apt install x11vnc');
            process.exit(1);
        }
        throw e;
    }
}

// 浏览器
async function launchBrowser() {
    log(`正在启动 Chromium → ${CFG.url}`);

    // 检查是否有可用的浏览器
    const execPath = findBrowserPath();
    if (!execPath) {
        log('错误: 未找到浏览器可执行文件');
        process.exit(1);
    }

    // 设置 DISPLAY 让 BrowserManager 使用有头模式
    process.env.DISPLAY = CFG.display;

    const browser = new BrowserManager(CLI.username, CLI.proxy);
    await browser.init();

    // 导航到目标 URL
    await browser.goto(CFG.url);

    log(`浏览器已就绪`);
    return browser;
}

// WebSocket ↔ TCP 代理
const WS_MAGIC = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

function proxyWebSocket(req, socket) {
    // WebSocket 握手
    const key = req.headers['sec-websocket-key'];
    if (!key) return socket.destroy();

    const hash = crypto.createHash('sha1').update(key + WS_MAGIC).digest('base64');
    socket.write(
        'HTTP/1.1 101 Switching Protocols\r\n' +
        'Upgrade: websocket\r\n' +
        'Connection: Upgrade\r\n' +
        `Sec-WebSocket-Accept: ${hash}\r\n\r\n`
    );

    // 连接 VNC
    const vnc = net.connect(CFG.vncPort, '127.0.0.1');
    let buf = Buffer.alloc(0);

    socket.on('data', (chunk) => {
        buf = Buffer.concat([buf, chunk]);
        while (tryParse()) { /* empty */ }
    });

    function tryParse() {
        if (buf.length < 2) return false;

        const b0 = buf[0];
        const b1 = buf[1];
        const opcode = b0 & 0x0f;
        const masked = (b1 & 0x80) !== 0;
        let plen = b1 & 0x7f;
        let headLen = 2;

        if (plen === 126) {
            if (buf.length < 4) return false;
            plen = buf.readUInt16BE(2);
            headLen = 4;
        } else if (plen === 127) {
            if (buf.length < 10) return false;
            plen = Number(buf.readBigUInt64BE(2));
            headLen = 10;
        }

        // 掩码密钥 (客户端 → 服务端帧按 RFC 6455 必须掩码)
        let mask = null;
        if (masked) {
            if (buf.length < headLen + 4) return false;
            mask = buf.slice(headLen, headLen + 4);
            headLen += 4;
        }

        if (buf.length < headLen + plen) return false;

        // 提取 & 解掩码
        let payload = buf.slice(headLen, headLen + plen);
        if (masked) {
            for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
        }

        buf = buf.slice(headLen + plen);

        switch (opcode) {
            case 0x1: // 文本帧
            case 0x2: // 二进制帧
                if (vnc.writable) vnc.write(payload);
                break;
            case 0x8: // 关闭帧
                sendFrame(socket, 0x8, Buffer.alloc(0));
                cleanup();
                return false;
            case 0x9: // ping 帧
                sendFrame(socket, 0xA, payload);
                break;
            // 0xA = pong 帧 — 忽略
        }

        return buf.length >= 2;
    }

    vnc.on('data', (data) => sendFrame(socket, 0x2, data));

    vnc.on('close', () => cleanup());
    socket.on('close', () => cleanup());
    socket.on('error', () => cleanup());
    vnc.on('error', () => cleanup());

    let closed = false;
    function cleanup() {
        if (closed) return;
        closed = true;
        try { vnc.destroy(); } catch (_) { }
        try { socket.destroy(); } catch (_) { }
    }
}

function sendFrame(socket, opcode, payload) {
    const len = payload.length;
    let head;
    if (len < 126) {
        head = Buffer.allocUnsafe(2);
        head[0] = 0x80 | opcode;
        head[1] = len;
    } else if (len < 65536) {
        head = Buffer.allocUnsafe(4);
        head[0] = 0x80 | opcode;
        head[1] = 126;
        head.writeUInt16BE(len, 2);
    } else {
        head = Buffer.allocUnsafe(10);
        head[0] = 0x80 | opcode;
        head[1] = 127;
        head.writeBigUInt64BE(BigInt(len), 2);
    }
    socket.write(Buffer.concat([head, payload]));
}

// HTML 页面 (noVNC 从 CDN 加载)
const HTML = `<!DOCTYPE html>

<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>远程浏览器</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  html,body{width:100%;height:100%;overflow:hidden;background:#111}
  #screen{width:100%;height:100%}
  #status{color:#888;font:14px monospace;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);pointer-events:none;z-index:9}
</style>
</head>
<body>
<div id="screen"><div id="status">正在连接...</div></div>
<script type="module">
import RFB from 'https://esm.sh/@novnc/novnc@1.5.0/lib/rfb.js';

const s = document.getElementById('status');
const screen = document.getElementById('screen');

// 检查 URL 参数，自动适应屏幕
const params = new URLSearchParams(location.search);
const autoFit = params.get('fit') !== 'false';

const rfb = new RFB(screen, 'ws://' + location.host, {
    credentials: { password: '' },
    localCursor: true,
});

// 自适应缩放模式：VNC 内容自动缩放到容器宽度
if (autoFit) {
    rfb.quality = 5;
    rfb.compression = 2;
    rfb.scaleViewport = true;

    function fitToWindow() {
        const containerW = screen.clientWidth;
        const containerH = screen.clientHeight;
        rfb.requestDesktopSize(containerW, containerH);
    }

    // 等待连接后立即适配
    rfb.addEventListener('connect', () => {
        s.textContent = '';
        setTimeout(fitToWindow, 100);
    });

    // 窗口大小变化时重新适配
    window.addEventListener('resize', fitToWindow);
}

rfb.viewOnly = false;

rfb.addEventListener('disconnect', (e) => {
    s.textContent = e.detail.clean ? '已断开连接.' : '连接断开，正在重连...';
});
</script>
</body>
</html>`;

// HTTP 服务
function startServer() {
    const server = http.createServer((req, res) => {
        if (req.url === '/' || req.url === '/index.html') {
            res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
            res.end(HTML);
        } else if (req.url === '/health') {
            res.writeHead(200, { 'Content-Type': 'text/plain' });
            res.end('ok');
        } else {
            res.writeHead(404);
            res.end('Not Found');
        }
    });

    server.on('upgrade', (req, socket) => proxyWebSocket(req, socket));

    server.listen(CFG.httpPort, () => {
        log(`──────────────────────────────────────────`);
        log(`打开: http://localhost:${CFG.httpPort}`);
        log(`远程浏览器已就绪.`);
        log(`──────────────────────────────────────────`);
    });

    return server;
}

// 主流程
async function main() {
    log('正在启动远程浏览器...');

    await startXvfb();
    await sleep(500);

    await startX11vnc();
    await sleep(1500);

    const browser = await launchBrowser();
    startServer();

    let closing = false;
    const shutdown = async () => {
        if (closing) return;
        closing = true;
        log('正在关闭...');
        await browser.cleanup().catch(() => { });
        process.exit(0);
    };
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);
}

main().catch((err) => { console.error(err); process.exit(1); });
