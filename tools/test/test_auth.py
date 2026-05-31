"""
讯飞 MaaS API 认证方式测试脚本
测试 OpenAI 风格和 HMAC 两种认证方式是否可用。
密钥从项目根目录的 secrets.json 加载。
"""
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime
from time import mktime
from urllib.parse import urlparse
from wsgiref.handlers import format_date_time

import requests


SECRETS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "secrets.json")


def load_secrets():
    if not os.path.exists(SECRETS_FILE):
        print(f"[ERROR] secrets.json not found: {SECRETS_FILE}")
        print("[ERROR] Copy secrets.example.json to secrets.json and fill in your keys.")
        raise SystemExit(1)
    with open(SECRETS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def run_openai_style(api_key, api_secret, model_id):
    print("\n--- Testing OpenAI Style ---")
    url = "https://maas-api.cn-huabei-1.xf-yun.com/v1/chat/completions"

    token_variants = [
        ("Full String", f"{api_key}:{api_secret}"),
        ("Secret Only", api_secret),
        ("Key Only", api_key),
    ]

    for name, token in token_variants:
        print(f"Testing Bearer {name}...")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.5,
        }

        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            print(f"Status: {res.status_code}")
            if res.status_code == 200:
                print("SUCCESS!")
                print(res.text)
                return
            print(f"Body: {res.text}")
        except Exception as e:
            print(f"Error: {e}")


def run_v2_hmac(api_key, api_secret, app_id, model_id, use_request_line=False):
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
        api_secret.encode("utf-8"),
        signature_origin.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    signature_sha_base64 = base64.b64encode(signature_sha).decode("utf-8")

    authorization_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="{headers_str}", signature="{signature_sha_base64}"'
    )
    authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Host": host,
        "Date": date,
        "Authorization": authorization,
    }

    payload = {
        "header": {"app_id": app_id, "uid": "123"},
        "parameter": {"chat": {"domain": model_id, "temperature": 0.5}},
        "payload": {"message": {"text": [{"role": "user", "content": "hi"}]}},
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"Status: {res.status_code}")
        print(f"Body: {res.text}")
    except Exception as e:
        print(f"Error: {e}")


def main():
    secrets = load_secrets()
    app_id = secrets["app_id"]
    api_key = secrets["api_key"]
    api_secret = secrets["api_secret"]
    model_id = secrets["models"][0]["model_id"]

    run_openai_style(api_key, api_secret, model_id)
    run_v2_hmac(api_key, api_secret, app_id, model_id, False)
    run_v2_hmac(api_key, api_secret, app_id, model_id, True)


if __name__ == "__main__":
    main()
