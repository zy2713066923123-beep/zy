const fs = require('fs');
const path = require('path');
const dir = 'c:/Users/26645/Desktop/QLScriptPublic-main/wxapp';
const files = fs.readdirSync(dir).filter(f => f.endsWith('.js'));
let modified = 0;

const unifyWxCodeMethod = `            async getWxCode() {
        const wxServerUrl = (process.env.WECHAT_SERVER || "http://192.168.6.222:8011").replace(/\/+$/, "");
        const endpoints = ['/api/v1/wx/app/get/code', '/api/v1/wx/app/get/code/', '/api/v1/wx/get/code'];
        let lastError = null;
        for (const endpoint of endpoints) {
            try {
                const { status, data } = await axios.post(
                    wxServerUrl + endpoint,
                    { appid: MINI_APP_ID, wxid: this.openid || this.account || this.wcsid || this.raw || "" },
                    {
                        headers: { "Content-Type": "application/json", "Accept": "application/json" },
                        timeout: 15000,
                        validateStatus: () => true,
                    }
                );
                const code = data?.code || data?.data?.code || data?.Data?.code || (typeof data?.Data === 'string' ? data.Data : '') || (typeof data?.data === 'string' ? data.data : '') || "";
                if (typeof code === 'string' && code.length > 5) return code;
                lastError = new Error(`无 code：${ JSON.stringify(data)}`);
            } catch (error) {
                lastError = error;
            }
        }
        throw new Error(`获取微信 code 失败：${ lastError ? lastError.message : '未知错误' } `);
    }

        for (const endpoint of endpoints) {
            try {
                const { status, data } = await axios.post(
                    wxServerUrl + endpoint,
                    { appid: MINI_APP_ID, wxid: this.openid || this.account || this.wcsid || this.raw || "" },
                    {
                        headers: { "Content-Type": "application/json", "Accept": "application/json" },
                        timeout: 15000,
                        validateStatus: () => true,
                    }
                );
                const code = data?.code || data?.data?.code || data?.Data?.code || (typeof data?.Data === 'string' ? data.Data : '') || (typeof data?.data === 'string' ? data.data : '') || "";
                if (typeof code === 'string' && code.length > 5) return code;
                lastError = new Error(`无 code：${ JSON.stringify(data) } `);
            } catch (error) {
                lastError = error;
            }
        }
        throw new Error(`获取微信 code 失败：${ lastError ? lastError.message : '未知错误' } `);
    }

                );
                const code = data?.code || data?.data?.code || data?.Data?.code || (typeof data?.Data === 'string' ? data.Data : '') || (typeof data?.data === 'string' ? data.data : '') || "";
                if (typeof code === 'string' && code.length > 5) return code;
                lastError = new Error(\`无 code：\${JSON.stringify(data)}\`);
            } catch (error) {
                lastError = error;
            }
        }
        throw new Error(\`获取微信 code 失败：\${lastError ? lastError.message : '未知错误'}\`);
    }`;

// Since some have async function getWxCode(account)
const unifyWxCodeFunction = `async function getWxCode(account) {
    const wxServerUrl = (process.env.WECHAT_SERVER || "http://192.168.6.222:8011").replace(/\/+$/, "");
    const endpoints = ['/api/v1/wx/app/get/code', '/api/v1/wx/app/get/code/', '/api/v1/wx/get/code'];
    let lastError = null;
    for (const endpoint of endpoints) {
        try {
            const { status, data } = await axios.post(
                wxServerUrl + endpoint,
                { appid: MINI_APP_ID, wxid: account },
                {
                    headers: { "Content-Type": "application/json", "Accept": "application/json" },
                    timeout: 15000,
                    validateStatus: () => true,
                }
            );
            const code = data?.code || data?.data?.code || data?.Data?.code || (typeof data?.Data === 'string' ? data.Data : '') || (typeof data?.data === 'string' ? data.data : '') || "";
            if (typeof code === 'string' && code.length > 5) return code;
            lastError = new Error(`无 code：${ JSON.stringify(data)}`);
        } catch (error) {
            lastError = error;
        }
    }
    throw new Error(`获取微信 code 失败：${ lastError ? lastError.message : '未知错误' } `);
}

    for (const endpoint of endpoints) {
        try {
            const { status, data } = await axios.post(
                wxServerUrl + endpoint,
                { appid: MINI_APP_ID, wxid: account },
                {
                    headers: { "Content-Type": "application/json", "Accept": "application/json" },
                    timeout: 15000,
                    validateStatus: () => true,
                }
            );
            const code = data?.code || data?.data?.code || data?.Data?.code || (typeof data?.Data === 'string' ? data.Data : '') || (typeof data?.data === 'string' ? data.data : '') || "";
            if (typeof code === 'string' && code.length > 5) return code;
            lastError = new Error(`无 code：${ JSON.stringify(data) } `);
        } catch (error) {
            lastError = error;
        }
    }
    throw new Error(`获取微信 code 失败：${ lastError ? lastError.message : '未知错误' } `);
}

            );
            const code = data?.code || data?.data?.code || data?.Data?.code || (typeof data?.Data === 'string' ? data.Data : '') || (typeof data?.data === 'string' ? data.data : '') || "";
            if (typeof code === 'string' && code.length > 5) return code;
            lastError = new Error(\`无 code：\${JSON.stringify(data)}\`);
        } catch (error) {
            lastError = error;
        }
    }
    throw new Error(\`获取微信 code 失败：\${lastError ? lastError.message : '未知错误'}\`);
}`;

files.forEach(f => {
    if (f === 'ljzf.js' || f === 'wcs.js' || f === 'env.js') return;

    const filePath = path.join(dir, f);
    let content = fs.readFileSync(filePath, 'utf8');
    let changed = false;

    // 1. Unify ckName to "WX_ID"
    if (/let\s+ckName\s*=\s*['"][^'"]+['"]/.test(content)) {
        content = content.replace(/let\s+ckName\s*=\s*['"][^'"]+['"]/, 'let ckName = "WX_ID"');
        changed = true;
    } else if (/const\s+ckName\s*=\s*['"][^'"]+['"]/.test(content)) {
        content = content.replace(/const\s+ckName\s*=\s*['"][^'"]+['"]/, 'const ckName = "WX_ID"');
        changed = true;
    }

    // 2. Unify getWxCode
    const classMethodRegex = /async\s+getWxCode\s*\(\)\s*\{[\s\S]*?(?=\n\s+(?:async|get|set|\w+\s*\())/;
    if (classMethodRegex.test(content)) {
        content = content.replace(classMethodRegex, unifyWxCodeMethod + "\\n");
        changed = true;
    }

    const functionRegex = /async\s+function\s+getWxCode\s*\([^)]*\)\s*\{[\s\S]*?(?=\n\s*(?:async|function|class|\w+\s*\())/;
    if (functionRegex.test(content)) {
        content = content.replace(functionRegex, unifyWxCodeFunction + "\\n");
        changed = true;
    }

    if (changed) {
        fs.writeFileSync(filePath, content, 'utf8');
        modified++;
    }
});
console.log('Modified files: ' + modified);
