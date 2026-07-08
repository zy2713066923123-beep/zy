#!/usr/bin/python3
# cron "51 11,18 * * *"
# -- coding: utf-8 --

# 变量名：yd   
# 格式：手机号@手机号


import json
import os
import random
import threading
from base64 import b64encode
from binascii import b2a_hex
from datetime import datetime
from hashlib import md5 as md5Encode
from sys import exit
from time import sleep, time

import requests
import urllib3
from Crypto.Cipher import AES, DES, DES3

# 禁用安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 全局消息变量
msg = ""


class Crypt:
    def __init__(self, crypt_type: str, key, iv=None, mode="ECB"):
        if crypt_type.upper() not in ["AES", "DES", "DES3"]:
            raise Exception("加密类型错误, 请重新选择 AES/DES/DES3")
        self.crypt_type = AES if crypt_type.upper() == "AES" else DES if crypt_type.upper() == "DES" else DES3
        self.block_size = self.crypt_type.block_size
        if self.crypt_type == DES:
            self.key_size = self.crypt_type.key_size
        elif self.crypt_type == DES3:
            self.key_size = self.crypt_type.key_size[1]
        else:
            if len(key) <= 16:
                self.key_size = self.crypt_type.key_size[0]
            elif len(key) > 24:
                self.key_size = self.crypt_type.key_size[2]
            else:
                self.key_size = self.crypt_type.key_size[1]
                print("当前aes密钥的长度只填充到24 若需要32 请手动用 chr(0) 填充")
        if len(key) > self.key_size:
            key = key[:self.key_size]
        else:
            if len(key) % self.key_size != 0:
                key = key + (self.key_size - len(key) % self.key_size) * chr(0)
        self.key = key.encode("utf-8")
        if mode == "ECB":
            self.mode = self.crypt_type.MODE_ECB
        elif mode == "CBC":
            self.mode = self.crypt_type.MODE_CBC
        else:
            raise Exception("您选择的加密模式错误")
        if iv is None:
            self.cipher = self.crypt_type.new(self.key, self.mode)
        else:
            if isinstance(iv, str):
                iv = iv[:self.block_size]
                self.cipher = self.crypt_type.new(self.key, self.mode, iv.encode("utf-8"))
            elif isinstance(iv, bytes):
                iv = iv[:self.block_size]
                self.cipher = self.crypt_type.new(self.key, self.mode, iv)
            else:
                raise Exception("偏移量不为字符串")

    def encrypt(self, data, padding="pkcs7", b64=False):
        pkcs7_padding = lambda s: s + (self.block_size - len(s.encode()) % self.block_size) * chr(
            self.block_size - len(s.encode()) % self.block_size)
        zero_padding = lambda s: s + (self.block_size - len(s) % self.block_size) * chr(0)
        pad = pkcs7_padding if padding == "pkcs7" else zero_padding
        data = self.cipher.encrypt(pad(data).encode("utf8"))
        encrypt_data = b64encode(data) if b64 else b2a_hex(data)  # 输出hex或者base64
        return encrypt_data.decode('utf8')


class China_Unicom:
    def __init__(self, phone_num, t):
        self.index = t + 1
        self.phone_num = phone_num
        self.catid = None
        self.cardid = None
        self.userinfo = None
        self.cntindex = None
        self.chapterid = None
        self.chapterallindex = None
        self.date = datetime.today().__format__("%Y%m%d%H%M%S")
        self.mobile = self.phone_num[:3] + "*" * 4 + self.phone_num[7:]
        self.ua = "Mozilla/5.0 (Linux; Android 13; LE2100 Build/TP1A.220905.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/103.0.5060.129 Mobile Safari/537.36; unicom{version:android@11.0300,desmobile:" + self.phone_num + "};devicetype{deviceBrand:OnePlus,deviceModel:LE2100};{yw_code:}"
        self.headers = {
            "Host": "10010.woread.com.cn",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Content-Type": "application/json;charset=utf-8",
            "Origin": "https://10010.woread.com.cn",
            "User-Agent": self.ua,
            "Connection": "keep-alive",
            "Referer": "https://10010.woread.com.cn/ng_woread/"}

    def log(self, cont):
        global msg
        print(cont, flush=True)
        msg += f"{cont}\n"

    def md5(self, str):
        m = md5Encode(str.encode(encoding='utf-8'))
        return m.hexdigest()

    def req(self, url, crypt_text):
        body = {"sign": b64encode(
            Crypt(crypt_type="AES", key="woreadst^&*12345", iv="16-Bytes--String", mode="CBC").encrypt(
                crypt_text).encode()).decode()}
        self.headers["Content-Length"] = str(
            len(json.dumps(body).replace(" ", "")))
        try:
            res = requests.post(url, headers=self.headers, json=body).json()
            return res
        except Exception as e:
            print(f"请求失败:{e}", flush=True)

    # 登录
    def referer_login(self):
        timestamp = round(time() * 1000)
        url = f"https://10010.woread.com.cn/ng_woread_service/rest/app/auth/10000002/{timestamp}/{self.md5(f'100000027k1HcDL8RKvc{timestamp}')}"
        crypt_text = f'{{"timestamp":"{self.date}"}}'
        body = {
            "sign": b64encode(Crypt(crypt_type="AES", key="woreadst^&*12345").encrypt(crypt_text).encode()).decode()}
        self.headers["Content-Length"] = str(len(str(body)) - 1)
        data = requests.post(url, headers=self.headers, json=body).json()
        print(data)
        if data["code"] == "0000":
            self.headers["accesstoken"] = data["data"]["accesstoken"]
            self.get_userinfo()
        else:
            self.log(f"设备登录失败,日志为{data}")
            exit(0)
        sleep(random.uniform(4, 8))

    # 查询登录结果
    def get_userinfo(self):
        url = "https://10010.woread.com.cn/ng_woread_service/rest/account/login"
        phone = b64encode(Crypt(crypt_type="AES", key="woreadst^&*12345", iv="16-Bytes--String", mode="CBC").encrypt(
            self.phone_num).encode()).decode('utf-8')
        crypt_text = f'{{"phone":"{phone}","timestamp":"{self.date}"}}'
        data = self.req(url, crypt_text)
        if data.get("code") == "0000":
            self.userinfo = data.get("data")
            self.log(f"账号[{self.index}][{self.mobile}]登录成功")
        else:
            self.log(f"手机号登录失败, 日志为{data}")
            exit(0)

    # 阅读
    def read_novel(self, b):
        self.log(f"账号[{self.index}][{self.mobile}]开始阅读小说...")
        self.get_cntindex()
        self.get_chapterallindex()
        for i in range(b):
            url = f"https://10010.woread.com.cn/ng_woread_service/rest/cnt/wordsDetail?catid={self.catid}&cardid={self.cardid}&cntindex={self.cntindex}&chapterallindex={self.chapterallindex}&chapterseno=1"
            crypt_text = f'{{"chapterAllIndex":{self.chapterallindex},"cntIndex":{self.cntindex},"cntTypeFlag":"1","timestamp":"{self.date}","token":"{self.userinfo["token"]}","userId":"{self.userinfo["userid"]}","userIndex":{self.userinfo["userindex"]},"userAccount":"{self.userinfo["phone"]}","verifyCode":"{self.userinfo["verifycode"]}"}}'
            self.req(url, crypt_text)
            self.addReadTime()
            self.log(f"账号[{self.index}][{self.mobile}]阅读进度 {i+1}/{b}，等待120秒...")
            sleep(120)
        self.log(f"账号[{self.index}][{self.mobile}]阅读完成")

    # 上报阅读时间
    def addReadTime(self):
        url = "https://10010.woread.com.cn/ng_woread_service/rest/history/addReadTime"
        crypt_text = f'{{"readTime":"2","cntIndex":"{self.cntindex}","cntType":"1","catid":"0","pageIndex":"","cardid":"{self.cardid}","cntindex":"{self.cntindex}","cnttype":"1","chapterallindex":"{self.chapterallindex}","chapterseno":"1","channelid":"","chapterid":"{self.chapterid}","readtype":1,"isend":"0","timestamp":"{self.date}","token":"{self.userinfo["token"]}","userId":"{self.userinfo["userid"]}","userIndex":{self.userinfo["userindex"]},"userAccount":"{self.userinfo["phone"]}","verifyCode":"{self.userinfo["verifycode"]}"}}'
        self.req(url, crypt_text)

    # 获取参数
    def get_cntindex(self):
        url = "https://10010.woread.com.cn/ng_woread_service/rest/basics/recommposdetail/14856"
        self.headers.pop("Content-Length", "no")
        try:
            data = requests.get(url, headers=self.headers).json()
            self.catid = data["data"]['booklist']['message'][0]['catindex']
            self.cardid = data['data']['bindinfo'][0]['recommposiindex']
            self.cntindex = data["data"]['booklist']['message'][0]['cntindex']
            self.log(f"账号[{self.index}][{self.mobile}]获取阅读参数成功")
        except Exception as e:
            self.log(f"账号[{self.index}][{self.mobile}]获取阅读参数失败: {e}")
            raise

    # 获取参数
    def get_chapterallindex(self):
        url = f"https://10010.woread.com.cn/ng_woread_service/rest/cnt/chalist"
        crypt_text = f'{{"curPage":1,"limit":30,"index":"{self.cntindex}","sort":0,"finishFlag":1,"timestamp":"{self.date}","token":"{self.userinfo["token"]}","userId":"{self.userinfo["userid"]}","userIndex":{self.userinfo["userindex"]},"userAccount":"{self.userinfo["phone"]}","verifyCode":"{self.userinfo["verifycode"]}"}}'
        data = self.req(url, crypt_text)
        self.chapterallindex = data["list"][0]["charptercontent"][0]['chapterallindex']
        self.chapterid = data["list"][0]["charptercontent"][0]['chapterid']

    # 抽奖
    def cj(self):
        url = "https://10010.woread.com.cn/ng_woread_service/rest/basics/doDraw"
        crypt_text = f'{{"activeindex": "8051", "timestamp": "{self.date}", "token": "{self.userinfo["token"]}","userId": "{self.userinfo["userid"]}", "userIndex": {self.userinfo["userindex"]}, "userAccount": "{self.userinfo["phone"]}", "verifyCode": "{self.userinfo["verifycode"]}"}}'
        data = self.req(url, crypt_text)
        if data["code"] == '0000':
            self.log(f"账号[{self.index}][{self.mobile}]抽奖获得：{data['data']['prizedesc']}")
        sleep(random.uniform(4, 8))

    # 查询红包
    def query_red(self):
        url = "https://10010.woread.com.cn/ng_woread_service/rest/phone/vouchers/queryTicketAccount"
        crypt_text = f'{{"timestamp":"{self.date}","token":"{self.userinfo["token"]}","userId":"{self.userinfo["userid"]}","userIndex":{self.userinfo["userindex"]},"userAccount":"{self.userinfo["phone"]}","verifyCode":"{self.userinfo["verifycode"]}"}}'
        data = self.req(url, crypt_text)
        if data["code"] == "0000":
            can_use_red = data["data"]["usableNum"] / 100
            self.log(f"账号[{self.index}][{self.mobile}]阅光宝盒话费红包余额：{can_use_red}元")
            sleep(random.uniform(4, 8))

    def main(self):
        self.referer_login()
        self.read_novel(1)
        self.cj()
        self.query_red()


def start(phone, t):
    China_Unicom(phone, t).main()


if __name__ == "__main__":
    l = []
    us = os.environ.get("yd", "").split('@')
    for t, user in enumerate(us):
        phone = user
        p = threading.Thread(target=start, args=(phone, t))
        l.append(p)
        p.start()
    for i in l:
        sleep(3)
        i.join()
