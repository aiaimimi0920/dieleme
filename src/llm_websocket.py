from __future__ import annotations

import _thread as thread
import base64
from datetime import datetime
from time import mktime
from urllib.parse import urlparse
from wsgiref.handlers import format_date_time
import hashlib
import hmac
import json
import ssl
import time

import websocket

from src.llm_config import APP_ID, MODEL_ID
from src.llm_metrics import record_api_metrics
from src.llm_model_selector import AUTH_INVALID_ERROR_CODES, model_selector


class Ws_Param(object):
    def __init__(self, APPID, APIKey, APISecret, Spark_url):
        self.APPID = APPID
        self.APIKey = APIKey
        self.APISecret = APISecret
        self.host = urlparse(Spark_url).netloc
        self.path = urlparse(Spark_url).path
        self.Spark_url = Spark_url

    def create_url(self):
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        signature_origin = "host: " + self.host + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + self.path + " HTTP/1.1"

        signature_sha = hmac.new(self.APISecret.encode('utf-8'), signature_origin.encode('utf-8'),
                                 digestmod=hashlib.sha256).digest()

        signature_sha_base64 = base64.b64encode(signature_sha).decode(encoding='utf-8')

        authorization_origin = f'api_key="{self.APIKey}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha_base64}"'

        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')

        v = {
            "authorization": authorization,
            "date": date,
            "host": self.host
        }

        from urllib.parse import urlencode
        url = self.Spark_url + '?' + urlencode(v)
        return url


class AIService:
    def __init__(self, model_config=None):
        self.final_result = ""
        self.error_code = 0
        self.error_msg = ""
        # Use provided config or get from pool
        self.model_config = model_config

    def on_error(self, ws, error):
        print(f"### WS Error ({self.model_config['name'] if self.model_config else 'default'}): {error} ###")

    def on_close(self, ws, one, two):
        # print("### WS Closed ###")
        pass

    def on_open(self, ws):
        thread.start_new_thread(self.run, (ws,))

    def run(self, ws, *args):
        config = self.model_config or {}
        app_id = config.get("app_id", APP_ID)
        model_id = config.get("model_id", MODEL_ID)
        data = json.dumps(self.gen_params(appid=app_id, domain=model_id))
        # print(f"Sending payload...")
        ws.send(data)

    def on_message(self, ws, message):
        data = json.loads(message)
        code = data['header']['code']
        if code != 0:
            self.error_code = code
            self.error_msg = data['header']['message']
            model_name = self.model_config['name'] if self.model_config else 'default'
            print(f"AI Error ({model_name}) Code: {code}")
            print(f"AI Error Message: {self.error_msg}")
            ws.close()
        else:
            choices = data["payload"]["choices"]
            status = data["header"]["status"]
            content = choices["text"][0]["content"]
            self.final_result += content
            if status == 2:
                ws.close()

    def gen_params(self, appid, domain):
        data = {
            "header": {
                "app_id": appid,
                "uid": "1234"
            },
            "parameter": {
                "chat": {
                    "domain": domain,
                    "temperature": 0.5,
                    "max_tokens": 4096
                }
            },
            "payload": {
                "message": {
                    "text": [
                        {"role": "user", "content": self.prompt}
                    ]
                }
            }
        }
        return data

    def get_response(self, prompt, task_type=None):
        """
        Get AI response with concurrency control.
        - task_type='community_search': Routes to GLM-4.7-Base only
        - task_type=None: Uses first available model (not round-robin)
        """
        self.prompt = prompt
        self.final_result = ""
        self.error_code = 0
        self.error_msg = ""
        from_queue = False  # Track how we acquired the slot
        started_at = time.time()

        # Determine model and acquire slot
        # Determine model and acquire slot
        if task_type == 'community_search':
            # Specific routing: community name tasks only go to GLM-4.7-Base
            # Use get_next to find a suitable base model
            config = model_selector.get_next('community_search')
            model_name = config['name']
            print(f"DEBUG: [community_search] Waiting for slot on '{model_name}'...")
            model_selector.acquire(model_name)
            from_queue = False
        elif self.model_config:
            # Explicitly provided model config
            config = self.model_config
            model_name = config['name']
            print(f"DEBUG: [explicit] Waiting for slot on '{model_name}'...")
            model_selector.acquire(model_name)
            from_queue = False
        else:
            # Instant slot from queue
            print(f"DEBUG: Getting slot from queue...")
            config, _ = model_selector.acquire_any()
            model_name = config['name']
            from_queue = True

        print(f"DEBUG: Using model '{model_name}' (ID: {config['model_id']})")
        self.model_config = config

        try:
            wsParam = Ws_Param(
                config["app_id"],
                config["api_key"],
                config["api_secret"],
                config["ws_url"]
            )
            wsUrl = wsParam.create_url()

            ws = websocket.WebSocketApp(wsUrl,
                                        on_message=self.on_message,
                                        on_error=self.on_error,
                                        on_close=self.on_close,
                                        on_open=self.on_open)
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}, ping_interval=130, ping_timeout=120)

            # Record statistics
            if self.error_code != 0:
                # Check if it's a concurrency/rate limit error (common codes: 10013, 10014, 10163, 10110, 11202)
                is_concurrency_err = self.error_code in [10013, 10014, 10163, 10110, 11202]
                model_selector.record_error(model_name, is_concurrency_error=is_concurrency_err)
                if self.error_code in AUTH_INVALID_ERROR_CODES:
                    model_selector.disable_model(
                        model_name,
                        f"error_code={self.error_code}, error_msg={self.error_msg or 'AppIdNoAuthError'}",
                    )
                if is_concurrency_err:
                    print(f"[STATS] Concurrency error on '{model_name}' (code: {self.error_code})")
                    # INSTANT limit reduction: Immediately reduce limit by 1 when concurrency error detected
                    current_limit = model_selector.limits.get(model_name, 10)
                    if current_limit > 3:  # Don't go below 3
                        new_limit = current_limit - 1
                        model_selector.update_limit(model_name, new_limit)
                        print(f"[INSTANT-TUNE] Reduced '{model_name}' limit: {current_limit} → {new_limit}")
            elif self.final_result:
                model_selector.record_success(model_name)
        finally:
            # Release slot back to queue or semaphore
            model_selector.release(model_name, model_config=config, from_queue=from_queue)
            print(f"DEBUG: Released slot on '{model_name}' (queue={from_queue})")

            elapsed_ms = (time.time() - started_at) * 1000
            record_api_metrics(success=bool(self.error_code == 0 and self.final_result), response_time_ms=elapsed_ms)

        return self.final_result


__all__ = ['Ws_Param', 'AIService']
