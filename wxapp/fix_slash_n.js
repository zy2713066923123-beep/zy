const fs = require('fs');

const files = fs.readdirSync('.').filter(f => f.endsWith('.js') && !['getCode.js', 'sendNotify.js', 'refactor.js', 'check_deps.js', 'fix_errors.js', 'fix_hash.js', 'fix_slash_n.js'].includes(f));

files.forEach(f => {
    let content = fs.readFileSync(f, 'utf-8');
    let modified = false;

    // We search for the literal string "\n" (which is \\n in regex)
    const literalN = "trim();\\n            const code";
    const actualN = "trim();\n            const code";
    
    if (content.includes(literalN)) {
        content = content.replace(literalN, actualN);
        modified = true;
    }

    if (modified) {
        fs.writeFileSync(f, content, 'utf-8');
    }
});

console.log('Fixed literal \\n.');
