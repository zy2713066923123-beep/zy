// cron "44 12,17 * * *"
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname);
const files = fs.readdirSync(dir);

let modifiedCount = 0;

for (const file of files) {
    if (!file.endsWith('.js')) continue;
    if (['sendNotify.js', 'getCode.js', 'add_notify_script.js', 'unify_wxcode.js'].includes(file)) continue;

    const filePath = path.join(dir, file);
    let content = fs.readFileSync(filePath, 'utf8');

    let modified = false;

    // Enhance log capturing
    if (content.includes('this.userIdx = 1; this.logs = []; }') && !content.includes('originalLog')) {
        content = content.replace(/this\.userIdx = 1; this\.logs = \[\]; \}/g, 'this.userIdx = 1; this.logs = []; const originalLog = console.log; console.log = (...args) => { this.logs.push(args.join(" ")); originalLog.apply(console, args); }; }');
        modified = true;
    }

    if (modified) {
        fs.writeFileSync(filePath, content, 'utf8');
        modifiedCount++;
        console.log(`Modified ${file}`);
    }
}

console.log(`Successfully modified ${modifiedCount} files.`);
