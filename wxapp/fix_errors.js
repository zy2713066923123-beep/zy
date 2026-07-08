// cron "40 9,17 * * *"
const fs = require('fs');

const files = fs.readdirSync('.').filter(f => f.endsWith('.js') && !['getCode.js', 'sendNotify.js', 'refactor.js', 'check_deps.js', 'fix_errors.js'].includes(f));

files.forEach(f => {
    let content = fs.readFileSync(f, 'utf-8');
    let modified = false;

    // Replace the misleading error message
    if (content.includes('缺少 WX_ID')) {
        content = content.replace(/缺少 WX_ID/g, '缺少 WX_ID');
        modified = true;
    }

    // Remove the redundant if (!process.env.WX_ID) throw new Error(...) check before wechat.getCode()
    // It usually looks like: if (!process.env.WX_ID) throw new Error("缺少 WX_ID，无法从 wx_server 获取 code");
    const regex = /if\s*\(\!process\.env\.WX_ID\)\s*throw\s*new\s*Error\(['"]缺少 WX_ID.*?['"]\);?\n?/g;
    if (regex.test(content)) {
        content = content.replace(regex, '');
        modified = true;
    }

    if (modified) {
        fs.writeFileSync(f, content, 'utf-8');
    }
});

console.log('Fixed error messages and redundant checks.');
