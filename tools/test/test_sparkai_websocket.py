"""
讯飞 MaaS WebSocket API 连接测试脚本
验证 WebSocket 方式调用讯飞大模型是否正常工作。
密钥从项目根目录的 secrets.json 加载。

原文件名: test_ws.py -> test_sparkai_websocket.py
"""
import _thread as thread
import base64
import datetime
import hashlib
import hmac
import json
import os
from urllib.parse import urlparse, urlencode
import ssl
from datetime import datetime
from time import mktime
from wsgiref.handlers import format_date_time

import websocket  # NOTE: pip install websocket-client

# ---- Load credentials from secrets.json ----
SECRETS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "secrets.json")

def load_secrets():
    if not os.path.exists(SECRETS_FILE):
        print(f"[ERROR] secrets.json not found: {SECRETS_FILE}")
        print("[ERROR] Copy secrets.example.json to secrets.json and fill in your keys.")
        exit(1)
    with open(SECRETS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

secrets = load_secrets()
APP_ID = secrets["app_id"]
API_KEY = secrets["api_key"]
API_SECRET = secrets["api_secret"]
MODEL_ID = secrets["models"][0]["model_id"]
WS_URL = secrets.get("ws_url", "wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat")


class WsParam(object):
    def __init__(self, app_id, api_key, api_secret, spark_url):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.host = urlparse(spark_url).netloc
        self.path = urlparse(spark_url).path
        self.spark_url = spark_url

    def create_url(self):
        # Generate timestamp in RFC1123 format
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # Signature Origin (WebSocket connection uses GET)
        signature_origin = "host: " + self.host + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + self.path + " HTTP/1.1"

        # HMAC-SHA256
        signature_sha = hmac.new(self.api_secret.encode('utf-8'), signature_origin.encode('utf-8'),
                                 digestmod=hashlib.sha256).digest()

        signature_sha_base64 = base64.b64encode(signature_sha).decode(encoding='utf-8')

        authorization_origin = f'api_key="{self.api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha_base64}"'

        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')

        # Combine parameters
        v = {
            "authorization": authorization,
            "date": date,
            "host": self.host
        }
        
        # Build URL
        url = self.spark_url + '?' + urlencode(v)
        return url

def on_error(ws, error):
    print("### Error:", error)

def on_close(ws, one, two):
    print("### Closed ###")

def on_open(ws):
    thread.start_new_thread(run, (ws,))

def run(ws, *args):
    data = json.dumps(gen_params(appid=APP_ID, domain=MODEL_ID))
    print(f"Sending payload: {data}")
    ws.send(data)

def on_message(ws, message):
    print("### Message:", message)
    data = json.loads(message)
    code = data['header']['code']
    if code != 0:
        print(f"Error Code: {code}")
        print(f"Error Message: {data['header']['message']}")
        ws.close()
    else:
        choices = data["payload"]["choices"]
        status = data["header"]["status"]
        content = choices["text"][0]["content"]
        print(content, end="")
        if status == 2:
            print("\nAnalysis Finished.")
            ws.close()

def gen_params(appid, domain):
    """Construct the request JSON."""
    data = {
        "header": {
            "app_id": appid,
            "uid": "1234"
        },
        "parameter": {
            "chat": {
                "domain": domain, 
                "temperature": 0.5,
                "max_tokens": 2048
            }
        },
        "payload": {
            "message": {
                "text": [
                    {"role": "user", "content": "你好"}
                ]
            }
        }
    }
    return data

if __name__ == "__main__":
    wsParam = WsParam(APP_ID, API_KEY, API_SECRET, WS_URL)
    wsUrl = wsParam.create_url()
    print(f"Connecting to: {wsUrl}")
    
    ws = websocket.WebSocketApp(wsUrl, on_message=on_message, on_error=on_error, on_close=on_close, on_open=on_open)
    ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
