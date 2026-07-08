// cron "14 12,16 * * *"
const fs = require('fs');

const files = fs.readdirSync('.').filter(f => f.endsWith('.js') && !['getCode.js', 'sendNotify.js', 'refactor.js', 'check_deps.js', 'fix_errors.js', 'fix_hash.js', 'fix_slash_n.js', 'fix_all_try_catch.js', 'fix_simple.js', 'fix_account_hash.js'].includes(f));

files.forEach(f => {
    let content = fs.readFileSync(f, 'utf-8');
    let modified = false;

    // We want to replace:
    // this.openid = String(openid || "").trim();
    // this.account = String(account || "").trim();
    // with:
    // this.openid = String(openid || "").split('#')[0].trim();
    // this.account = String(account || "").split('#')[0].trim();

    const regex1 = /this\.openid\s*=\s*String\((.*?)\)\.trim\(\);/g;
    if (regex1.test(content)) {
        content = content.replace(regex1, (match, p1) => {
            return `this.openid = String(${p1}).split('#')[0].trim();`;
        });
        modified = true;
    }

    const regex2 = /this\.account\s*=\s*String\((.*?)\)\.trim\(\);/g;
    if (regex2.test(content)) {
        content = content.replace(regex2, (match, p1) => {
            return `this.account = String(${p1}).split('#')[0].trim();`;
        });
        modified = true;
    }

    // Some scripts might use `this.wcsid = String(wcsid || "").trim();`
    const regex3 = /this\.wcsid\s*=\s*String\((.*?)\)\.trim\(\);/g;
    if (regex3.test(content)) {
        content = content.replace(regex3, (match, p1) => {
            return `this.wcsid = String(${p1}).split('#')[0].trim();`;
        });
        modified = true;
    }

    // What about native `getWxCode`? If they use `this.raw`, it's safer to just split there too, but stripping at the property assignment is best.

    // Let's also check if they assign it inside `$.userList` parsing!
    // In `Env.checkEnv`:
    // const val = process.env.WX_ID || process.env[ckName];
    // if (val) this.userList = val.split(/[\n&]+/).map(v => v.trim()).filter(Boolean);
    // If I replace `.map(v => v.trim())` with `.map(v => v.split('#')[0].trim())` inside `checkEnv`!
    // This is EVEN BETTER! Because it applies to EVERYTHING that uses Env!
    
    const envRegex = /this\.userList\s*=\s*val\.split\(\/[\\n&]\+\/\)\.map\(v\s*=>\s*v\.trim\(\)\)\.filter\(Boolean\);/g;
    if (envRegex.test(content)) {
        content = content.replace(envRegex, "this.userList = val.split(/[\\n&]+/).map(v => String(v).split('#')[0].trim()).filter(Boolean);");
        modified = true;
    } else if (content.includes("val.split(/[\\n&]+/).map(v => v.trim()).filter(Boolean);")) {
        content = content.replace("val.split(/[\\n&]+/).map(v => v.trim()).filter(Boolean);", "val.split(/[\\n&]+/).map(v => String(v).split('#')[0].trim()).filter(Boolean);");
        modified = true;
    }

    if (modified) {
        fs.writeFileSync(f, content, 'utf-8');
        console.log('Fixed ' + f);
    }
});

console.log('Finished fixing hash issue.');
