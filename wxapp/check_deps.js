const fs = require('fs');
const files = fs.readdirSync('.').filter(f => f.endsWith('.js') && f !== 'check_deps.js');
const deps = new Set();
const vars = new Set();
files.forEach(f => {
    const content = fs.readFileSync(f, 'utf-8');
    const requireRegex = /require\(['"]([^'"]+)['"]\)/g;
    let match;
    while ((match = requireRegex.exec(content)) !== null) {
        if (match[1].startsWith('.') || match[1].startsWith('/')) {
            deps.add(match[1]);
        }
    }
    const envRegex = /process\.env\.([a-zA-Z0-9_]+)/g;
    while ((match = envRegex.exec(content)) !== null) {
        vars.add(match[1]);
    }
});
console.log('Local Dependencies:', Array.from(deps));
console.log('Env Vars:', Array.from(vars));
