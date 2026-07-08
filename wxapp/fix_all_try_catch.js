// cron "13 12,23 * * *"
const fs = require('fs');

const files = fs.readdirSync('.').filter(f => f.endsWith('.js') && !['getCode.js', 'sendNotify.js', 'refactor.js', 'check_deps.js', 'fix_errors.js', 'fix_hash.js', 'fix_slash_n.js', 'fix_all_try_catch.js'].includes(f));

files.forEach(f => {
    let content = fs.readFileSync(f, 'utf-8');
    let modified = false;

    const methodNames = ['loginByWxCode', 'login'];

    for (const methodName of methodNames) {
        // Regex to find "async loginByWxCode() {" or similar
        const regex = new RegExp('async\\\\s+' + methodName + '\\\\s*\\\\([^)]*\\\\)\\\\s*\\\\{');
        const match = content.match(regex);
        if (match) {
            const startIdx = match.index;
            const openBraceIdx = startIdx + match[0].length - 1;

            let braceCount = 1;
            let endIdx = -1;
            for (let i = openBraceIdx + 1; i < content.length; i++) {
                if (content[i] === '{') braceCount++;
                if (content[i] === '}') braceCount--;
                if (braceCount === 0) {
                    endIdx = i;
                    break;
                }
            }

            if (endIdx !== -1) {
                const body = content.substring(openBraceIdx + 1, endIdx);
                // Check if the body already seems to be wrapped in try-catch
                if (!body.trim().startsWith('try')) {
                    // Wrap the body in try..catch
                    const newBody = '\\n        try { ' + body + ' \\n        } catch(e) { $.log(`账号[${this.index}] 登录失败: ${e.message || e}`); }\\n    ';
                    content = content.substring(0, openBraceIdx + 1) + newBody + content.substring(endIdx);
                    modified = true;
                }
            }
        }
    }

    if (modified) {
        fs.writeFileSync(f, content, 'utf-8');
        console.log('Fixed ' + f);
    }
});

console.log('Finished wrapping login methods in try-catch.');
