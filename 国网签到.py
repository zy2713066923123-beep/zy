# # 当前脚本来自于 http://script.nnioj.com/ 脚本库下载！
# # 当前脚本来自于 http://script.nnioj.com/ 脚本库下载！
# # 当前脚本来自于 http://script.nnioj.com/ 脚本库下载！
# # 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
# # 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
# # 您在使用脚本库下载的脚本时自行检查判断风险。
# # 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。

# -*- coding: utf-8 -*-
"""
网上国网签到脚本 (青龙面板) v1.0

作者：21886
时间：2026-07-28

【免责声明】
    本脚本仅供学习和研究使用，禁止用于商业用途
    使用本脚本产生的一切后果由使用者自行承担
    作者不对因使用本脚本而导致的任何损失或账号封禁负责
    请遵守相关法律法规，合理使用

【脚本说明】
    自动完成网上国网APP每日签到，支持查询/签到/补签

【环境变量】
    WG_TOKEN    - 必填，令牌(抓包获取，见下方说明)
    WG_USERID   - 必填，用户ID(抓包获取，见下方说明)
    WG_MODE     - 可选，默认 all
                  all    = 查询+签到+查询(完整流程)
                  sign   = 仅签到
                  query  = 仅查询签到信息
                  resign = 仅补签

【抓包方法】
    1. 手机安装抓包工具(Reqable/Charles/Fiddler等)
    2. 打开网上国网APP，随便浏览一下(不需要进签到页面)
    3. 在抓包记录中找到任意发往 csc-service.sgcc.com.cn 的请求
    4. 从请求头中复制以下两个值：
       - t        → 填入 WG_TOKEN
       - UserId   → 填入 WG_USERID
    5. 在青龙面板添加以上环境变量，运行脚本即可

【令牌时效】
    令牌有效期较短(约数小时)，过期后脚本会提示"令牌已过期"
    需要重新抓包获取新的令牌
    建议每天签到前抓一次包

【关于脚本内的skey/data】
    脚本中SKEYS字典里的skey和data是通用的加密参数，不是账号绑定的
    所有用户共享同一套，无需自行抓包提取
    如国网更新加密体系导致失效，需重新逆向提取

【当前限制】
    1. 令牌无法自动刷新，每天需手动抓包一次
    2. 兑换功能已关闭(业务参数会变化，固定值无法通用)
    3. 多账号支持：配置多个WG_TOKEN(换行分隔)，对应相同数量WG_USERID

【依赖】
    pip install gmssl requests
"""
import os, sys, time, json, requests
try:
    from gmssl import sm2, sm3, sm4 as gm4
except ImportError:
    os.system(f"{sys.executable} -m pip install gmssl -q")
    from gmssl import sm2, sm3, sm4 as gm4
import urllib3
urllib3.disable_warnings()

BASE_URL = "https://csc-service.sgcc.com.cn:28630"
MODE = os.environ.get("WG_MODE", "all")
INTERVAL = 2
TIMEOUT = 15

# SM2私钥 - 从APP的libnacontroller.so中提取，用于解密服务器响应
SM2_PUBKEY = "0409C10D38CF7B4E28097EAAA519E3157C9B4E72194CD13BD11932CE40ED5624AFEFF27F78893E4C4FC2029DA147AB6CEAE0CDC8E3A547EFCDC5AB91757FE1CA60"
SM2_PRIVKEY = "50C4AF48DF75808050729977AA6BC127DC21A404755C660B94222F9D50FA4A75"

# skey+data从抓包数据中提取，可跨账号复用
# 只需更新 timestamp 和 sign 即可发送请求
# sign = SM3(skey + data + timestamp)
SKEYS = {
    "query_sign":   {"api": "/osg-omgmt1042/member/c1/q104051",
                     "skey": "0426710b7ea19a1aed28451ae6c707adfcccc0c88873bb1d1e99aa8e1d649aa5d04cff486e45658dfe315797293bbcbc9c3af984174ea3845495fdca97af287d42751d88c8bac339fc83a5fa200d502a79d1808cc9b22514f3d2b7f1a3f36397b1c2ed572b03b42a84489d915562a867696db358a03db6bc90ad0a798b385bf3da",
                      "data": "91E0D8E458CB8A0D5994034BDCA3B4F5D8AD8C68B49854718FD6637927CEB417"},
    "query_detail": {"api": "/osg-omgmt1042/member/c1/q022607",
                     "skey": "04809a31789533cdb4b2884dd68baca625ba2216985566bdf3f0a107dbd1c3ac9c7a29f2e4f994d9ccf4eecd4d0bc2aa3781faf14e24051b03ded62822bc0b0ee7a3f4536d716d3cbbc1d0ca5fa1dcbb59c7751f2ec8b57a7791ed71e7699e9010ff12ceeb11f0db89786d0824157027e0a94f6c8e4951e4b5e0c9d74afca5f861",
                      "data": "5F1005470B2ADD0C1AC712311CD1CEE4CF036E2FA6BB0239B45E912B393ECD39DF82DB04AD39736708C5F1D874870BE731C335B5E9125537203B8AE7E3F3DABBE540311FFDD91E3885B72C2301BEB31E5BD8855F90BEABC491DFE81300018F283B49DD10B5CCFF24131674D6F8742963FD710E7A8C69C31112A35360828EDFDBEBB101DFE495E1008A18766AF087D38CBBF895EB67A651727A681CDA999133D1BCCA0194E17676084423C6DB1315481704EDE22BF66A7FD17D4C5679034690187854BBF2223B2F17F000768A1C7DF217"},
    "query_record":  {"api": "/osg-omgmt1042/member/c1/q048740",
                      "skey": "04db50d17d436cfb8aa96f40afdb2db2b9165915b64cfb304d78ab23faf128ca2095dd39db003646eb540f496d6c18e55b0c0a202fc9907aae216412c3d87566ecf93f4a3ccf2f5420bed38348a0b21b685e232c24fdb1f7075f1a40d0e3f2028c17b7761fa53d7a523403fabb07aadcc25b1c7bf50e00bba217aa88deba8b42dd",
                      "data": "00C227FC6AB44280D1D8F3FA22C15DE13CCC99CDA3A987C60F920FAB345469AE64D2FD40E840731B4441E3347AFC2F7D55B8F1F6223199E2FA10D083236E9BD054AE98E5ED27FA69F27486C139056868"},
    "query_history": {"api": "/osg-omgmt1042/member/c1/q034992",
                      "skey": "04c6b8592f326802c3883755728e4d503abe32bb65274539ff2bb339636c57681dc5bede00432a1834ff2fe84bc27673ab7844630093a5663cb966c50dea8553a7d108d4f3f023480c7438146b2d43123b732d1330486efa77c540a5818deb750c7171569b1057e07eaff4f350a4b0d9a606031913442fca97f8de8f8650901e59",
                      "data": "A17F3C75BE291563A9404436CCE99B8B9A8E5D47F03EB232B4FA0014E0DF12268FA0BB1ED4C63B2920BE1062DB689A6C276F09906ADA9A4C489F9436E8349E629C3D3058FD71D183CF12D543659E90BF7AA4407885027EF8F67D894F3DC943ABBEE68A7568BDEACBAB0F9DF8E065A4F1EB58EF78D2C403126EEFBBCBD2AB26DA"},
    "query_points":  {"api": "/osg-omgmt1042/member/c1/q034990",
                      "skey": "04a3983f92286aa858da4b4a8481902e23524b47bcfacbc07db15258b3193f651708efd6e6652bcd3227f1f5bbb35240ebce1fffffe3ee51ca042e1f23ae11bcea08b34428344d002453790c6415de5e8e37bae096dd8ee1276d841f27f112d0fcbda40e561e48c8f52c440a34c7d3e63acfa1342b77a89fd4ff1a7a425c470ca5",
                      "data": "DB95BBA3019AE0EF248D15AAAFB542DF9180D758DF418E67BD3B68CDAA270193E42E7E09675131AB41B48308AE1AAE756091F50709498E6F3FA86C5B5566F0807403097FEC0A73EE7260E5DAD4DAE7CA"},
    "sign":     {"api": "/osg-omgmt1042/member/m1/0584615",
                 "skey": "0400db06d82e8f4ead991f1cd85cd333d938ad7e5edf42f4db8e169adff58d26574beff73266481b9b59202b14fa13b87065ed0e3a5b5d820cf4e8168a17e3f1b8b5b235097e4414dee1629d5a28b0203552041d0c6fd4b91fffbeb33f27a5dc8dbd08df87ee1a264ba7befab32c15f065c10c1af245594fb0aff79d7b69ca6738",
                  "data": "C68F73A7A7702E4D784EAD70A7AA8AE1B775FF3DC79A63EDC3CE08EBC1AE51A566A74FA379F87F5084C8D0D77E27FF7CE8B42AE360CCC3EF9F3DEBAC0D7453C86E39A763930F138F61A7FED8AAC29FA8C9C22FA4114A49AC8A4A288FB8B74596"},
    "resign":   {"api": "/osg-omgmt1042/member/m1/0103514",
                 "skey": "04c7c381e4a5223d32b5ac048e3ead286178db349dea351d1c24486ffe03c8e8fb2aea413b53d8189ba225737b05f0fd12e4f87f6d4eb07a8b5fc6d56aa1525f512d72856c84e368d8d196d6a27ea202878ce5c62da48911d0b6a1e120169f74f5a70beaf644bf12dac75e08c6be5a1255df2cfc0c1ef4d6615851cf151fa5ad3b",
                  "data": "69CBE9F400071A7F84DCBF7E26DF619FD45A3652A7F21A4A509B5FFDF364B40FB64E91A579517F7F9541AF639429EB853F422AAD5975A35AB190FBF2B99BF1FD344A902194ED78A9A34F81FEC79F12D63FA434AF9A7C043ABC1C74E6C3DD4EFF"},
}

LABELS = {
    "query_sign": "成长金余额",
    "query_detail": "签到明细",
    "query_record": "补签记录",
    "query_history": "活动信息",
    "query_points": "积分余额",
}


class Crypto:
    """响应解密: SM2解密respKey得到SM4密钥, 再用SM4解密encryptData"""
    def __init__(self):
        self.sm2_dec = sm2.CryptSM2(public_key=SM2_PUBKEY, private_key=SM2_PRIVKEY, mode=1)
        self.sm4 = gm4.CryptSM4()

    def decrypt(self, text):
        try:
            r = json.loads(text)
            enc, rk = r.get("encryptData", ""), r.get("respKey", "")
            if not enc or not rk:
                return r
            ct = rk[2:] if rk.startswith("04") else rk
            key = self.sm2_dec.decrypt(bytes.fromhex(ct))
            self.sm4.set_key(key[:16], gm4.SM4_DECRYPT)
            dec = self.sm4.crypt_ecb(bytes.fromhex(enc))
            return json.loads(dec.rstrip(b'\x00').decode('utf-8'))
        except Exception as e:
            return {"error": str(e), "raw": text[:200]}


def send(api_info, token, userid):
    """构造加密请求: sign = SM3(skey + data + timestamp)"""
    ts = str(int(time.time() * 1000))
    sign = sm3.sm3_hash(list((api_info["skey"] + api_info["data"] + ts).encode("utf-8")))
    body = json.dumps({
        "data": api_info["data"], "skey": api_info["skey"],
        "sign": sign, "timestamp": ts,
        "Authorization": "", "noSecret": ""
    }, separators=(",", ":"), ensure_ascii=False)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "okhttp/3.14.9",
        "security": "android", "appcode": "WSGW-SG1001-APP",
        "datacenter": "99", "AccessMethod": "App",
        "t": token, "version": "3.2.3",
        "wsgwType": "android", "OS": "android", "IP": "127.0.0.1",
        "UserId": userid,
    }
    return requests.post(BASE_URL + api_info["api"], data=body, headers=headers, verify=False, timeout=TIMEOUT)


def push(title, content):
    """统一通知：桥接青龙内置 notify（通过 SendNotify 桥接模块），
    调用方无需关心具体通道，青龙配置的通知环境变量均生效。"""
    try:
        from SendNotify import send as _send
        _send(title, content)
    except Exception as exc:
        print(f"  ⚠️ 通知推送异常: {exc}")


def fmt_val(data):
    """格式化返回数据"""
    if data is None:
        return "无"
    if isinstance(data, (int, str)):
        return str(data)
    if isinstance(data, dict):
        msg = data.get("rtnMessage", "")
        val = data.get("rtnData")
        if val is not None:
            return f"{msg}（{val}）" if val else msg
        return msg or json.dumps(data, ensure_ascii=False)[:120]
    if isinstance(data, list):
        return f"共{len(data)}条记录"
    return str(data)[:120]


def main():
    token = os.environ.get("WG_TOKEN", "")
    userid = os.environ.get("WG_USERID", "")
    if not token:
        print("❌ 未配置 WG_TOKEN")
        print("   抓包网上国网APP，从请求头 t 获取值")
        sys.exit(1)

    crypto = Crypto()
    expired = False
    push_msgs = []

    def call(name):
        nonlocal expired
        if expired:
            return None
        info = SKEYS[name]
        resp = send(info, token, userid)
        result = crypto.decrypt(resp.text)
        if not isinstance(result, dict):
            print(f"  ❌ 响应异常: {str(result)[:100]}")
            return None

        code = str(result.get("code", result.get("Code", "")))
        msg = result.get("message", result.get("Message", ""))
        data = result.get("data", result.get("Data"))

        if code == "101007":
            print("  ⚠️ 令牌已过期，请重新抓包")
            expired = True
            return None

        if name.startswith("query_"):
            label = LABELS.get(name, name)
            print(f"  {label}：{fmt_val(data)}")
        elif name == "sign":
            rmsg = msg
            if isinstance(data, dict):
                rmsg = data.get("rtnMessage", msg)
            print(f"  签到结果：{rmsg}")
            push_msgs.append(f"签到：{rmsg}")
        elif name == "resign":
            rmsg = msg
            if isinstance(data, dict):
                rmsg = data.get("rtnMessage", msg)
            print(f"  补签结果：{rmsg}")
            push_msgs.append(f"补签：{rmsg}")

        return result

    print()
    print("  ╭──────────────────────────╮")
    print("  │   网上国网签到 · v1.0    │")
    print(f"  │   模式：{MODE:<4}  令牌：{token[:10]}... │")
    print("  ╰──────────────────────────╯")
    print()

    if MODE == "query":
        print("  📋 签到信息查询")
        print("  ─────────────────────────")
        for name in ["query_sign", "query_detail", "query_record", "query_history", "query_points"]:
            r = call(name)
            if r is None:
                break
            time.sleep(INTERVAL)

    elif MODE == "sign":
        print("  ✍️ 执行签到")
        print("  ─────────────────────────")
        call("sign")

    elif MODE == "resign":
        print("  📝 执行补签")
        print("  ─────────────────────────")
        call("resign")

    elif MODE == "exchange":
        print("  🎁 执行兑换")
        print("  ─────────────────────────")
        print("  ⚠️ 兑换功能已关闭")

    elif MODE == "all":
        print("  📊 第一步：查询签到状态")
        print("  ─────────────────────────")
        r = call("query_sign")
        if r is None:
            push("国网签到", "⚠️ 令牌过期，请重新抓包")
            print("\n  ❌ 已终止")
            return
        time.sleep(INTERVAL)

        print("\n  ✍️ 第二步：执行签到")
        print("  ─────────────────────────")
        r = call("sign")
        if r is None:
            print("\n  ❌ 已终止")
            return
        time.sleep(INTERVAL)

        print("\n  📊 第三步：查询签到结果")
        print("  ─────────────────────────")
        call("query_sign")

        if push_msgs:
            push("国网签到", "\n".join(push_msgs))
    else:
        print(f"  ❌ 未知模式：{MODE}")
        sys.exit(1)

    print("\n  ─────────────────────────")
    print("  ✅ 执行完毕")
    print()

    # 统一兜底推送：任意模式产生的签到/补签结果都汇总发送
    if push_msgs:
        push("网上国网签到", "\n".join(push_msgs))


if __name__ == "__main__":
    main()