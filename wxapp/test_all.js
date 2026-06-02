const { execSync } = require('child_process');
const fs = require('fs');

const env = {
  ...process.env,
  WX_ID: 'wxid_0r2hnuueolpg22#156\nwxid_854qthkdugnb21#133\nwxid_uk7qcnzfxipt22#170'
};

const ignored = [
  'getCode.js', 'sendNotify.js', 'refactor.js', 'check_deps.js', 
  'fix_errors.js', 'fix_hash.js', 'fix_slash_n.js', 'fix_all_try_catch.js', 
  'fix_simple.js', 'fix_account_hash.js', 'test_all.js'
];

const files = fs.readdirSync('.').filter(f => f.endsWith('.js') && !ignored.includes(f));

console.log(`Found ${files.length} scripts to execute.\n`);

async function runAll() {
    for (const file of files) {
        console.log(`\n\n>>> 正在执行: ${file} <<<`);
        try {
            execSync(`node ${file}`, { env, stdio: 'inherit' });
        } catch (e) {
            console.error(`\n[!] 执行 ${file} 时遇到错误。`);
        }
    }
    console.log('\n\n>>> 所有脚本执行完毕 <<<');
}

runAll();
