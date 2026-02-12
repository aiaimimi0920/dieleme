"""
讯飞 MaaS API 认证方式测试脚本
测试 OpenAI 风格和 HMAC 两种认证方式是否可用。
密钥从项目根目录的 secrets.json 加载。
"""
import requests
import json
import hmac
import hashlib
import base64
import os
from datetime import datetime
from time import mktime
from wsgiref.handlers import format_date_time
from urllib.parse import urlparse

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


def test_openai_style():
    print("\n--- Testing OpenAI Style ---")
    url = "https://maas-api.cn-huabei-1.xf-yun.com/v1/chat/completions"
    
    # Variant 1: Full String
    token_full = f"{API_KEY}:{API_SECRET}"
    # Variant 2: Secret Only
    token_secret = API_SECRET
    # Variant 3: Key Only
    token_key = API_KEY
    
    for name, t in [("Full String", token_full), ("Secret Only", token_secret), ("Key Only", token_key)]:
        print(f"Testing Bearer {name}...")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {t}"
        }
        
        payload = {
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.5
        }
        
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            print(f"Status: {res.status_code}")
            if res.status_code == 200:
                print("SUCCESS!")
                print(res.text)
                return
            else:
               print(f"Body: {res.text}")
        except Exception as e:
            print(f"Error: {e}")

def test_v2_hmac(use_request_line=False):
    print(f"\n--- Testing V2 HMAC (Request Line: {use_request_line}) ---")
    url = "https://maas-api.cn-huabei-1.xf-yun.com/v2"
    
    u = urlparse(url)
    host = u.netloc
    path = u.path
    
    now = datetime.utcnow()
    date = format_date_time(mktime(now.timetuple()))
    
    if use_request_line:
        signature_origin = f"host: {host}\ndate: {date}\nPOST {path} HTTP/1.1"
        headers_str = "host date request-line"
    else:
        signature_origin = f"host: {host}\ndate: {date}"
        headers_str = "host date"
        
    signature_sha = hmac.new(
        API_SECRET.encode('utf-8'),
        signature_origin.encode('utf-8'),
        hashlib.sha256
    ).digest()
    
    signature_sha_base64 = base64.b64encode(signature_sha).decode(encoding='utf-8')
    
    authorization_origin = f'api_key="{API_KEY}", algorithm="hmac-sha256", headers="{headers_str}", signature="{signature_sha_base64}"'
    authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')
    
    headers = {
        "Content-Type": "application/json",
        "Host": host,
        "Date": date,
        "Authorization": authorization
    }
    
    payload = {
        "header": { "app_id": APP_ID, "uid": "123" },
        "parameter": { "chat": { "domain": MODEL_ID, "temperature": 0.5 } },
        "payload": { "message": { "text": [{"role": "user", "content": "hi"}] } }
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"Status: {res.status_code}")
        print(f"Body: {res.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_openai_style()
    test_v2_hmac(False)
    test_v2_hmac(True)
