const fs = require('fs');
const path = require('path');
const dir = 'c:/Users/26645/Desktop/QLScriptPublic-main/wxapp';
const files = fs.readdirSync(dir).filter(f => f.endsWith('.js'));
let modified = 0;

const formatText = `WX_ID  格式：\n  wxid#备注  多个换行`;

files.forEach(f => {
    // Ignore ljzf.js as its format is already custom
    if (f === 'ljzf.js') return;

    const filePath = path.join(dir, f);
    let content = fs.readFileSync(filePath, 'utf8');
    let changed = false;

    // Pattern 1
    const p1 = /WX_ID\s+必填，wx_server 鉴权值/g;
    if (p1.test(content)) {
        content = content.replace(p1, formatText);
        changed = true;
    }

    // Pattern 2
    const p2 = /(WECHAT_SERVER、WX_ID)/g;
    if (p2.test(content) && !content.includes('WX_ID  格式：')) {
        content = content.replace(p2, `$1\n${formatText}`);
        changed = true;
    }

    if (changed) {
        fs.writeFileSync(filePath, content, 'utf8');
        modified++;
    }
});
console.log('Modified files: ' + modified);
