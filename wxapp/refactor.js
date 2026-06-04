const fs = require('fs');
const path = require('path');

const files = fs.readdirSync('.').filter(f => f.endsWith('.js') && !['getCode.js', 'sendNotify.js', 'refactor.js', 'check_deps.js'].includes(f));

const envPolyfill = `
class Env {
    constructor(name) { this.name = name; this.userList = []; this.userIdx = 1; this.logs = []; const originalLog = console.log; console.log = (...args) => { this.logs.push(args.join(" ")); originalLog.apply(console, args); }; }
    log(...args) { console.log(...args); this.logs.push(args.join(" ")); }
    checkEnv(ckName) {
        const val = process.env.WX_ID || process.env[ckName];
        if (val) this.userList = val.split(/[\\n&]+/).map(v => v.trim()).filter(Boolean);
        else console.log('未找到环境变量 WX_ID');
    }
    done() {}
}
`;

const wcsPolyfill = `
const { getSingleCode } = require('./getCode.js');
class WeChatServer {
    constructor(config) { this.config = config; }
    async getCode(wxid) {
        try {
            const code = await getSingleCode(this.config.appid, wxid);
            return { data: { status: true, code, data: { code } } };
        } catch(e) {
            return { data: {} };
        }
    }
}
`;

files.forEach(f => {
    let content = fs.readFileSync(f, 'utf-8');
    let modified = false;

    // Process env.js
    if (/require\(['"]\.\/env(\.js)?['"]\)/.test(content)) {
        content = content.replace(/(?:const\s*(?:\{\s*Env\s*\}|Env)\s*=\s*)?require\(['"]\.\/env(\.js)?['"]\);?/g, '');
        content = envPolyfill + content;
        modified = true;
    }

    // Process wcs.js
    if (/require\(['"]\.\/wcs(\.js)?['"]\)/.test(content)) {
        content = content.replace(/(?:const\s*WeChatServer\s*=\s*)?require\(['"]\.\/wcs(\.js)?['"]\);?/g, '');
        content = wcsPolyfill + content;
        modified = true;
    }

    // Process unify_wxcode.js
    if (/require\(['"]\.\/unify_wxcode(\.js)?['"]\)/.test(content)) {
        content = content.replace(/const\s*\{\s*getWxCode\s*\}\s*=\s*require\(['"]\.\/unify_wxcode(\.js)?['"]\);?/g, "const { getSingleCode } = require('./getCode.js');\\nconst getWxCode = (wxid, appid) => getSingleCode(appid, wxid);");
        modified = true;
    }

    // Redirect any sendNotify requires (like '../sendNotify' or '/ql/scripts/sendNotify') to './sendNotify.js'
    if (/require\(['"][^'"]*sendNotify[^'"]*['"]\)/.test(content)) {
        content = content.replace(/require\(['"][^'"]*sendNotify[^'"]*['"]\)/g, "require('./sendNotify.js')");
        modified = true;
    }

    // Clean up any remaining local requires that are not getCode.js or sendNotify.js
    content = content.replace(/require\(['"](\.[^'"]+)['"]\)/g, (match, p1) => {
        if (p1.includes('sendNotify') || p1.includes('getCode')) {
            return match;
        }
        console.log(`Removed local dependency: ${match} in ${f}`);
        return '{}';
    });

    // Unify environment variables to WX_ID
    const envVarsToReplace = [
        'WX_ID',
        'wx_auth',
        'G_ljzfhd',
        'zmnlxq',
        'aima',
        'wx_midea',
        'wx_xlxyh',
        'fsdlb'
    ];

    envVarsToReplace.forEach(v => {
        const regex = new RegExp('process\\.env\\.' + v, 'g');
        if (regex.test(content)) {
            content = content.replace(regex, 'process.env.WX_ID');
            modified = true;
        }
    });

    // Unify WECHAT_SERVER (ignoring case)
    if (/process\.env\.wechatServer/i.test(content) || /process\.env\.WECHAT_URL/i.test(content)) {
        content = content.replace(/process\.env\.wechatServer/gi, 'process.env.WECHAT_SERVER');
        content = content.replace(/process\.env\.WECHAT_URL/gi, 'process.env.WECHAT_SERVER');
        modified = true;
    }

    if (modified || content !== fs.readFileSync(f, 'utf-8')) {
        fs.writeFileSync(f, content, 'utf-8');
    }
});

console.log('Refactoring complete.');
