"""收益参考:实物/现金
本项目支持双端签到，答题，盲盒抽奖，幸运抽奖，云宠物。
APP抓包
1.手机各大市场下载白鲸旧衣回收这个APP。
2.下载完手机验证码登录便可,登录后点我的-右上角齿轮-点账户安全改密码。
*提交格式:备注#手机号#密码
微信抓包
1.微信搜索白鲸回收,然后微信授权手机登陆。注:登陆后不需要绑定手机如绑定就会同步APP数据,不绑定手机可以撸实物,绑定可以同步APP撸现金需知晓。
2.打开抓包软件抓https://www.52bjy.com/api/app/user.php此域名下的username和auth的2个参数跟APP的CK参数有区别切勿混淆。
*提交格式:备注#username#auth"""
import requests,json,re,os,sys,time,random,datetime,threading,execjs,hashlib,base64,urllib3,certifi
from urllib.parse import quote
retrycount = 1
environ = "bjhs"
name = "꧁༺ 白鲸༒回收 ༻꧂"
session = requests.session()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#---------------------主代码区块---------------------
def getparm(parm):
    sign = hashlib.md5((parm + Secret).encode('utf-8')).hexdigest()
    return parm + "&sign=" + sign
def run(arg1,arg2,arg3,arg4,arg5):
    global id, messages,Secret
    header = {
        "Host": "www.52bjy.com",
        "Connection": "keep-alive",
        "Content-Length": "",
        "Content-Type": "application/x-www-form-urlencoded",
        "EnvConnection": "test",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; MI 8 Build/QKQ1.190828.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/83.0.4103.101 Mobile Safari/537.36 uni-app Html5Plus/1.0 (Immersed/32.363636)",
    }
    if len(arg1) >11:
        app = 'wx'
        appkey = '1f70a57fdf4061a7'
        Secret = 'eBRaFLkuJ5'  
        apk = f"&appkey={appkey}"
        auth = arg2              
    else:
        app = 'self'
        appkey = "a9827e37ed2becd8"
        Secret = 'mCaP57nCwC'
        apk = ''
        url = 'https://www.52bjy.com/api/app/member.php?'
        data = f"action=login&username={arg1}&password={arg2}&app={app}&sign="
        response = session.post(url=url, headers=header, data=data).json()
        #print(f"☁️{response}")
        if "登录成功" not in response.get("message",""):
            print(f"⭕登陆：账密错误")
            return
        auth = response["data"]["token"]     
    # return
    for retry in range(int(retrycount)):
            ctime = int(time.time())
        # try:

            userinfo_url = f'https://www.52bjy.com/api/app/user.php?' + getparm(f"action=userinfo&appkey={appkey}&auth={auth}&username={arg1}")
            userinfo_response = session.get(url=userinfo_url).json()
            # print(userinfo_response)
            token = userinfo_response['data']['token']            

            #签到
            del header['Content-Length']
            urlsign = f'https://www.52bjy.com/api/app/user.php?action=qiandao&app={app}&auth={auth}&username={arg1}'
            responsesign = session.get(url=urlsign, headers=header).json()
            #print(f"☁️{responsesign}")

            if "签到成功" in responsesign.get("message","") or "已经签到" in responsesign.get("message",""):
                print(f"☁️签到状态：成功")
            urlday = f"https://www.52bjy.com/api/app/user.php?action=getsigninfo&auth={auth}&username={arg1}"
            responseday = session.get(url=urlday, headers=header).json()
            #print(f"☁️{responseday}")
            status = responseday['data']["status"]
            thisturn = responseday['data']["thisturn"]
            print(f"☁️本周连签：{thisturn} 天")
            arg4 = f'https://www.52bjy.com/api/app/user.php?' + getparm(f"action=qiandaobox&app={app}{apk}&auth={auth}&merchant_id=1&username={arg1}")
            if thisturn == 7 and arg4:
                #连签7天抽奖
                responsebox = session.get(url=arg4, headers=header).json()
                #print(f"☁️{responsebox}")
                if responsebox["isSucess"]:
                    if responsebox['data']['type'] == "money":
                        print(f"🌈连签盲盒：{responsebox['data']['data']} 红包")
                    elif responsebox['data']['type'] == "credit":
                        print(f"☁️连签盲盒：+{responsebox['data']['data']} 鲸鱼币")
                    else:
                        print(f"☁️连签盲盒：{responsebox['data']}")
                else:
                    print(f"☁️连签盲盒：{responsebox}")
                if len(arg1) <= 11:
                    responseday = session.get(url=f'https://www.52bjy.com/api/app/user.php?action=getsigninfo&auth={auth}&username={arg1}', headers=header).json()
                    if responseday["data"]["boxdata"]['type'] == "money":
                        money = responseday["data"]["boxdata"]['data']
                        arg5 = f'https://www.52bjy.com/api/app/redpacket.php?' + getparm(f"action=qiandao&appkey={appkey}&money={money}&timestamp={ctime}&username={arg1}&version=2")
                        responseday = session.get(url=arg5, headers=header).json()
                        print(f"⭕连签红包：{responseday['message']}")


            print("☼ ――――  任  务  ―――― ☼")
            #答题
            for i in range(7):
                dt_response = session.get(url=f'https://www.52bjy.com/api/app/question.php?'+ getparm(f"action=list&appkey={appkey}&username={arg1}&version=1"), headers=header).json()
                if dt_response['isSucess']:
                    dt_id = dt_response['data'][0]['id']
                    for index, value in enumerate(dt_response['data'][0]['answer']):
                        if value['isright'] == "1":
                            answer = index
                    print(f"☁️第 {dt_response['data'][0]['index']} 题id: {dt_id}，答案：{answer}")
                    tj_response = session.get(url=f'https://www.52bjy.com/api/app/question.php?'+ getparm(f"action=addcount&answer={answer}&appkey={appkey}&id={dt_id}&merchant_id=1&username={arg1}&version=2"), headers=header).json()
                    if tj_response['isSucess']:
                        print(f'☁️答对: {tj_response["data"]["right"]}，答错: {tj_response["data"]["wrong"]}')
                        time.sleep(random.randint(1, 2))
                    else:
                        print(f"⭕提交答案错误: {tj_response}")
                        break
                else:
                    print(f"☁️答题结束: {dt_response['message']}")
                    break
            # arg3 = f'https://www.52bjy.com/api/app/credit.php?' + getparm(f'action=add&appkey={appkey}&price=10&reason=%E6%AF%8F%E6%97%A5%E7%AD%94%E9%A2%98&timestamp={ctime}&token={token}&type=promotion&username={arg1}&version=4')
            # responsedt = session.get(url=arg3, headers=header).json()
            # #print(f"☁️{responsedt}")
            # dtgetpoint = arg3.split("price=")[1].split("&")[0]
            # if responsedt["isSucess"]:
            #     print(f"☁️答题：+{dtgetpoint} 鲸鱼币")
            # elif "每日答题已获取" in responsedt["message"]:
            #     #print(f"☁️答题：已完成")
            #     print(f"☁️答题：+{dtgetpoint} 鲸鱼币")
            # else:
            #     print(f"☁️{responsedt}")


            print("☼ ――――  信  息  ―――― ☼")  
            #今日获取
            now= datetime.datetime.now()
            urlinfo = f'https://www.52bjy.com/api/app/user.php?action=creditrecord&auth={auth}&month={now.month}&page=1&type=0&username={arg1}&year={now.year}'
            responseinfo = session.get(url=urlinfo, headers=header).json()
            amountall = 0
            for i in responseinfo["data"]:
                amount = int(i["amount"])
                addtime = i["addtime"]
                if datetime.datetime.strptime(i["addtime"], "%Y-%m-%d %H:%M:%S").date() == now.date():
                    amountall = amountall + amount
            print(f"☁️今日获：{amountall} 鲸鱼币")
            #信息
            urlinfo = f'https://www.52bjy.com/api/app/user.php?' + getparm(f"action=userinfo&appkey={appkey}&auth={auth}&username={arg1}")
            responseinfo = session.get(url=urlinfo, headers=header).json()
            print(f"☁️鲸鱼币：{responseinfo['data']['credit']} 鲸鱼币")
            print(f"☁️成长值：{responseinfo['data']['growths']} 成长值")

            print("☼ ――――  宠物  ―――― ☼")  
            for i in range(3):
                responseym = session.get(url=f'https://www.52bjy.com/api/app/promotionanimal.php?' + getparm(f"action=adoptanimalshow&appkey={appkey}&username={arg1}"), headers=header).json()
                if responseym['data'].get("exist_pet") > 0:
                    print(f"☁️宠物等级：{responseym['data']['level']} 级")
                    responseym = session.get(url=f'https://www.52bjy.com/api/app/promotion.php?' + getparm(f"action=tasklist&app={app}&appkey={appkey}&type=adopt&username={arg1}"), headers=header).json()
                    for ymtasks in responseym["data"]:
                        title = ymtasks["title"]
                        is_done = ymtasks["is_done"]
                        ymtype = ymtasks["type"]
                        if is_done == 1:
                            print(f"☁️【{title[:4]}】：已完成")
                            continue
                        if "社区发帖" in title or "邀请新用户" in title or "商城下单" in title :
                            continue
                        for _ in range(4):
                            if len(arg1) >11:
                                responseym = session.get(url=f'https://www.52bjy.com/api/app/user.php?' + getparm(f"action=task&app={app}&appkey={appkey}&auth={auth}&type={ymtype}&username={arg1}"), headers=header).json()
                                #print(responseym)
                                if "社区点赞" in title:
                                    continue
                                if responseym["isSucess"]:
                                    break
                                    time.sleep(2)
                    ywtype = {1:"喂养",2:"喝水",3:"铲屎"}
                    for key, value in ywtype.items():
                        responseym = session.get(url=f'https://www.52bjy.com/api/app/promotionanimal.php?' + getparm(f"action=adoptinteract&appkey={appkey}&type={key}&username={arg1}"), headers=header).json()
                        if responseym["isSucess"]:
                            print(f"☁️{value}：完成")
                        else:
                            print(f'☁️{value}：{responseym["message"]}')
                        time.sleep(1)
                    break
                else:
                    print(f"⭕养猫：请先领养小猫") 
                    responseym = session.get(url=f'https://www.52bjy.com/api/app/promotionanimal.php?' + getparm(f"action=adoptanimal&appkey={appkey}&type=2&username={arg1}"), headers=header).json()
                    if responseym["isSucess"]:
                        print(f"☁️领养：{responseym['message']}")
                    else:
                        print(f"☁️领养：{responseym}")
                        break

            print("☼ ――――  幸  运  ―――― ☼")  
            # if len(arg1) >11:
            #     responsecj = session.get(url=f'https://www.52bjy.com/api/app/user.php?' + getparm(f"action=task&app={app}&appkey={appkey}&auth={appkey}&type=sharefriends&username={arg1}"), headers=header).json()
            # else:
            #     #app端无任务
            #     pass
            for i in range(5):
                responsecj = session.get(url=f'https://www.52bjy.com/api/app/promotionjgg.php?' + getparm(f"action=prize_draw&app={app}&appkey={appkey}&merchant_id=1&username={arg1}"), headers=header).json()
                if responsecj["isSucess"]:
                    coupon_id = responsecj['data']['coupon_id']
                    introduce = responsecj['data']['introduce']
                    responsecjlq = session.get(url=f'https://www.52bjy.com/api/app/promotioncoupon.php?' + getparm(f"action=get&appkey={appkey}&cid={introduce}&did={coupon_id}&type=promotion_coupun&username={arg1}"), headers=header).json()
                    if "成功" in responsecjlq["message"] or "已" in responsecjlq["message"]:
                        print(f"☁️抽奖：{responsecj['data']['title']}")
                        time.sleep(2)
                elif "已用完" in responsecj["message"]:
                    print(f"☁️抽奖：次数用完")
                    break
                else:
                    print(f"☁️{responsecj}")
                    break


            break
        # except Exception as e:
        #     if retry >= int(retrycount)-1:
        #         print(f"⭕模块：{e}")

def main():
    global id, messages
    messages = []
    if os.environ.get(environ):
        ck = os.environ.get(environ)
    else:
        ck = ""
        if ck == "":
            print("⭕请设置变量")
            sys.exit()
    ck_run = ck.split('\n')
    ck_run = [item for item in ck_run if item]
    print(f"{' ' * 7}{name}\n\n")
    print(f"-------- ☁️ 开 始  执 行 ☁️ --------")
    for i, ck_run_n in enumerate(ck_run):
            #if (i + 1) != 11:
            #    continue  
        # try:
            qdbox = ""
            qdhb = ""
            if len(ck_run_n.split('#'))==4:
                mark,acc,paw,ques = ck_run_n.split('#')
            elif len(ck_run_n.split('#'))==5:
                mark,acc,paw,ques,qdbox = ck_run_n.split('#')
            elif len(ck_run_n.split('#'))==6:
                mark,acc,paw,ques,qdbox,qdhb = ck_run_n.split('#')
            elif len(ck_run_n.split('#'))==3:
                ques = ""
                mark,acc,paw = ck_run_n.split('#')
            else:
                print(f"⭕当前账号：ck异常")
            print(f"\n>>>>>  账号 [{i + 1}/{len(ck_run)}]")

            #id = mark[:3] + "*****" + mark[-3:]
            print(f"☁️当前账号：{mark}")
            run(acc,paw,ques,qdbox,qdhb)
            time.sleep(random.randint(1, 2))
        # except Exception as e:
        #     print(e)
    print(f"\n\n-------- ☁️ 执 行  结 束 ☁️ --------\n\n")

if __name__ == '__main__':
    
    main()