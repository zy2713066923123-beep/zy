const fs = require('fs');

const files = fs.readdirSync('.').filter(f => f.endsWith('.js') && !['getCode.js', 'sendNotify.js', 'refactor.js', 'check_deps.js', 'fix_errors.js', 'fix_hash.js'].includes(f));

files.forEach(f => {
    let content = fs.readFileSync(f, 'utf-8');
    let modified = false;

    // Fix WeChatServer getCode polyfill
    const oldWeChatServer = "const code = await getSingleCode(this.config.appid, wxid);";
    const newWeChatServer = "const actualWxid = String(wxid).split('#')[0].trim();\\n            const code = await getSingleCode(this.config.appid, actualWxid);";
    
    if (content.includes(oldWeChatServer)) {
        content = content.replace(oldWeChatServer, newWeChatServer);
        modified = true;
    }

    // Fix getWxCode polyfill
    const oldGetWxCode = "const getWxCode = (wxid, appid) => getSingleCode(appid, wxid);";
    const newGetWxCode = "const getWxCode = (wxid, appid) => getSingleCode(appid, String(wxid).split('#')[0].trim());";

    if (content.includes(oldGetWxCode)) {
        content = content.replace(oldGetWxCode, newGetWxCode);
        modified = true;
    }

    if (modified) {
        fs.writeFileSync(f, content, 'utf-8');
    }
});

console.log('Fixed hash parsing.');
