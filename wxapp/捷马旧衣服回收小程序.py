# 当前脚本来自于http://script.345yun.cn脚本库下载！
#小程序：https://img.meituan.net/portalweb/fd97d0e09c72c225cf57aa520e19e413160847.jpg
#环境变量名：JMJY
#变量值：抓小程序的token
#多用户用@分隔开
#by
import requests
import os
import json
from notify import send

# 从环境变量获取多账户，用@分割
JYXE_ACCOUNTS = os.getenv("JMJY", "").split("@")

url = "https://jiema.fzjingzhou.com/api/Person/sign"

headers = {
    'User-Agent': "Mozilla/5.0 (Linux; Android 15; PKG110 Build/UKQ1.231108.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/138.0.7204.180 Mobile Safari/537.36 XWEB/1380215 MMWEBSDK/20250904 MMWEBID/6169 MicroMessenger/8.0.64.2940(0x28004034) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android"
}

# 遍历每个账户进行签到
for index, token in enumerate(JYXE_ACCOUNTS, 1):
    # 跳过空字符串（处理环境变量为空或分割后有空值的情况）
    if not token.strip():
        continue
        
    payload = {
        'token': token.strip()
    }
    
    try:
        response = requests.post(url, data=payload, headers=headers)
        msg = json.loads(response.text)
        
        if "success" in msg.get("msg", ""):
            result = f"👤账户{index}：签到成功✅"
            print(f"{result}\n")
            send("捷马旧衣服回收", f"{result}\n")
        else:
            result = f"👤账户{index}：{msg}ℹ️"
            print(f"{result}\n")
            send("捷马旧衣服回收", f"{result}\n")
    except Exception as e:
        error_msg = f"👤账户{index}：签到失败，错误信息：{str(e)}❌"
        print(f"{error_msg}\n")
        send("捷马旧衣服回收", f"{error_msg}")
# 当前脚本来自于http://script.345yun.cn脚本库下载！