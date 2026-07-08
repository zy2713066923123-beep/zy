// cron "40 11,14 * * *"
const fs = require('fs');

const files = fs.readdirSync('.').filter(f => f.endsWith('.js') && !['getCode.js', 'sendNotify.js', 'refactor.js', 'check_deps.js', 'fix_errors.js', 'fix_hash.js', 'fix_slash_n.js', 'fix_all_try_catch.js', 'fix_simple.js'].includes(f));

files.forEach(f => {
    let content = fs.readFileSync(f, 'utf-8');
    let modified = false;

    // We only want to replace instances that are NOT already in our try block.
    // To be safe, we'll replace `await this.loginByWxCode();` if it doesn't already have `try { await this.loginByWxCode(); }`
    
    const targets = [
        'await this.loginByWxCode();',
        'await this.login();'
    ];

    targets.forEach(target => {
        // Find occurrences
        let idx = content.indexOf(target);
        while (idx !== -1) {
            // Check if the 6 characters before it are "try { "
            const before = content.substring(Math.max(0, idx - 10), idx);
            if (!before.includes('try {')) {
                const replacement = "try { " + target + " } catch (e) { $.log(`账号[${this.index}] 登录失败: ${e.message || e}`); }";
                content = content.substring(0, idx) + replacement + content.substring(idx + target.length);
                modified = true;
                idx = content.indexOf(target, idx + replacement.length);
            } else {
                idx = content.indexOf(target, idx + target.length);
            }
        }
    });

    if (modified) {
        fs.writeFileSync(f, content, 'utf-8');
        console.log('Fixed ' + f);
    }
});

console.log('Finished simple wrapper.');
