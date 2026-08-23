import _thread as thread
import random
import base64
import datetime
import hashlib
import hmac
import json
from html import unescape
from urllib.parse import urlparse
import ssl
from datetime import datetime
from time import mktime
from wsgiref.handlers import format_date_time
import websocket  # pip install websocket-client
import re
import requests
import time

# ==================== MODEL POOL CONFIGURATION ====================
# Credentials are loaded from secrets.json (not committed to git).
# Copy secrets.example.json to secrets.json and fill in your API keys.

import os as _os
import json as _json

_SECRETS_FILE = _os.path.join(_os.path.dirname(__file__), "..", "secrets.json")

def _has_openai_compatible_env():
    base_url = (
        _os.environ.get("OPENAI_BASE_URL")
        or _os.environ.get("OPENAI_API_BASE")
        or _os.environ.get("OPENAI_COMPATIBLE_BASE_URL")
    )
    return bool(base_url and _os.environ.get("OPENAI_API_KEY"))


def _load_secrets():
    """Load API credentials from secrets.json."""
    if not _os.path.exists(_SECRETS_FILE):
        if not _has_openai_compatible_env():
            print(f"[ERROR] secrets.json not found at {_SECRETS_FILE}")
            print("[ERROR] Please copy secrets.example.json to secrets.json and fill in your API keys.")
        return None
    with open(_SECRETS_FILE, 'r', encoding='utf-8') as f:
        return _json.load(f)

_secrets = _load_secrets()

def _build_model_pool(secrets):
    """Build MODEL_POOL from secrets.json configuration."""
    if not secrets:
        return []
    ws_url = secrets.get("ws_url", "")
    common_models = secrets.get("models", [])
    
    # Check for new multi-account structure
    accounts = secrets.get("accounts")
    if not accounts:
        # Backward compatibility: Treat top-level as one account
        accounts = [{
            "app_id": secrets.get("app_id", ""),
            "api_key": secrets.get("api_key", ""),
            "api_secret": secrets.get("api_secret", "")
        }]

    pool = []
    for idx, acc in enumerate(accounts):
        acc_name = acc.get("name", f"Acc{idx+1}")
        acc_app_id = acc.get("app_id")
        acc_api_key = acc.get("api_key")
        acc_api_secret = acc.get("api_secret")
        # Allow account to override ws_url or models if needed
        acc_ws_url = acc.get("ws_url", ws_url)
        acc_models = acc.get("models", common_models)
        
        for m in acc_models:
            # Create a unique name for each account's model instance
            # e.g., "GLM-4.7-Base" becomes "GLM-4.7-Base-Acc1"
            # This allows ModelSelector to track limits independently
            unique_name = f"{m['name']}-{acc_name}"
            pool.append({
                "name": unique_name,
                "base_name": m["name"], # Original name for grouping
                "app_id": acc_app_id,
                "api_key": acc_api_key,
                "api_secret": acc_api_secret,
                "ws_url": acc_ws_url,
                "model_id": m["model_id"],
                "max_concurrent": m.get("max_concurrent", 5)
            })
    return pool

MODEL_POOL = _build_model_pool(_secrets)

import threading
import time
import json
import os

PREDICTION_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "datas", "avm", "logs")
PREDICTION_LOG_LOCK = threading.Lock()
API_METRICS_LOCK = threading.Lock()
API_METRICS = {
    "total": 0,
    "success": 0,
    "total_response_time_ms": 0.0,
}

def _daily_prediction_log_path(now=None):
    """Build daily log path: datas/avm/logs/YYYY-MM-DD.log."""
    dt = now or datetime.now()
    filename = f"{dt.strftime('%Y-%m-%d')}.log"
    return os.path.join(PREDICTION_LOG_DIR, filename)

def log_prediction_event(task_type, duration_ms, recall_count=None, final_confidence=None, success=True, failure_reason=None, item_id=None):
    """Append one JSON-line prediction record into daily AVM log."""
    record = {
        "timestamp": datetime.now().isoformat(),
        "task_type": task_type,
        "item_id": str(item_id) if item_id is not None else None,
        "duration_ms": round(float(duration_ms), 2) if duration_ms is not None else None,
        "recall_count": recall_count,
        "final_confidence": final_confidence,
        "success": bool(success),
        "failure_reason": failure_reason,
    }

    try:
        os.makedirs(PREDICTION_LOG_DIR, exist_ok=True)
        log_path = _daily_prediction_log_path()
        with PREDICTION_LOG_LOCK:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[LOG] Failed to write prediction log: {e}")

def record_api_metrics(success, response_time_ms):
    """Accumulate API success stats and response-time stats."""
    with API_METRICS_LOCK:
        API_METRICS["total"] += 1
        if success:
            API_METRICS["success"] += 1
        API_METRICS["total_response_time_ms"] += max(float(response_time_ms or 0.0), 0.0)

def get_api_metrics():
    """Expose API success rate and average response time."""
    with API_METRICS_LOCK:
        total = API_METRICS["total"]
        success = API_METRICS["success"]
        total_ms = API_METRICS["total_response_time_ms"]

    success_rate = (success / total * 100.0) if total else 0.0
    avg_ms = (total_ms / total) if total else 0.0
    return {
        "total_calls": total,
        "success_calls": success,
        "success_rate": round(success_rate, 2),
        "avg_response_time_ms": round(avg_ms, 2),
    }

# Configuration file for dynamic tuning
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "datas", "model_config.json")

def load_model_config():
    """Load model concurrency config from file if exists, else use defaults from MODEL_POOL."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                # Merge saved config into MODEL_POOL
                for model in MODEL_POOL:
                    name = model["name"]
                    base = model.get("base_name", name)
                    
                    # Try exact match first, then base name match
                    if name in saved:
                         model["max_concurrent"] = saved[name].get("max_concurrent", model.get("max_concurrent", 5))
                    elif base in saved:
                         model["max_concurrent"] = saved[base].get("max_concurrent", model.get("max_concurrent", 5))
                print(f"[CONFIG] Loaded model config from {CONFIG_FILE}")
        except Exception as e:
            print(f"[CONFIG] Error loading config: {e}, using defaults")
    return MODEL_POOL

# Apply saved config on module load
load_model_config()


import queue


AUTH_INVALID_ERROR_CODES = {11200}


class LLMBackendUnavailableError(RuntimeError):
    """Raised when no configured LLM backend is currently usable."""


class ModelSelector:
    """
    Counter-based model selector with RUNTIME-ADJUSTABLE concurrency limits.
    - Uses counters + Condition variables instead of pre-allocated queues
    - Limits can be changed at runtime without restart
    - Supports task-type based routing and statistics tracking
    """
    def __init__(self, pool):
        self.pool = pool
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        
        # Per-model active counts and limits (can be changed at runtime)
        self.active_counts = {m["name"]: 0 for m in pool}
        self.limits = {m["name"]: m.get("max_concurrent", 5) for m in pool}
        
        # Statistics tracking
        self.stats = {m["name"]: {"success": 0, "error": 0, "concurrency_error": 0, "active": 0} for m in pool}
        self.stats_lock = threading.Lock()
        self.disabled_models = {}
        
        # Track base models for community search
        self.base_models = [m for m in pool if "Base" in m.get("base_name", m["name"])]
        
        total = sum(self.limits.values())
        print(f"[ModelSelector] Counter-based init: {len(pool)} models, Total concurrency: {total}")

    def get_next(self, task_type=None):
        """
        Get next model config.
        - task_type='community_search': Returns one of the GLM-4.7-Base models (round-robin or random)
        - task_type=None: Returns None to signal use of acquire_any()
        """
        if task_type == 'community_search':
            # Random choice from available base models
            available = []
            for m in self.base_models:
                name = m["name"]
                if self.active_counts.get(name, 0) < self.limits.get(name, 0):
                    available.append(m)
            
            if available:
                return random.choice(available)
            
            # If all full, just return a random one and let it block to distribute wait time
            return random.choice(self.base_models) if self.base_models else self.pool[0]
        return None
    
    def _find_available_model(self):
        """Find any model with available capacity. Must hold lock."""
        # Random heuristic: find all available and pick one
        # This ensures load is distributed across accounts
        available = []
        for model in self.pool:
            name = model["name"]
            if name in self.disabled_models:
                continue
            if self.active_counts.get(name, 0) < self.limits.get(name, 0):
                available.append(model)
        
        if available:
            return random.choice(available)
        return None

    def acquire_any(self):
        """
        Get any available model slot.
        INSTANT if slots available, blocks only if ALL slots are busy.
        Returns (model_config, acquired).
        """
        with self.condition:
            # Wait until a slot is available
            while True:
                enabled_model_names = [m["name"] for m in self.pool if m["name"] not in self.disabled_models]
                if not enabled_model_names:
                    raise LLMBackendUnavailableError("All configured models are disabled or unavailable")
                model = self._find_available_model()
                if model:
                    name = model["name"]
                    self.active_counts[name] = self.active_counts.get(name, 0) + 1
                    with self.stats_lock:
                        self.stats[name]["active"] = self.active_counts[name]
                    return model, True
                # No slots available, wait for a release
                self.condition.wait()
    
    def acquire(self, model_name):
        """Acquire a connection slot for a SPECIFIC model. Blocks if at limit."""
        with self.condition:
            if model_name in self.disabled_models:
                raise LLMBackendUnavailableError(
                    f"Model '{model_name}' is disabled: {self.disabled_models.get(model_name) or 'unavailable'}"
                )
            while self.active_counts.get(model_name, 0) >= self.limits.get(model_name, 5):
                self.condition.wait()
            
            self.active_counts[model_name] = self.active_counts.get(model_name, 0) + 1
            with self.stats_lock:
                self.stats[model_name]["active"] = self.active_counts[model_name]
            return True

    def disable_model(self, model_name, reason):
        """Disable a model for the current process when auth/config is invalid."""
        with self.condition:
            if model_name in self.disabled_models:
                return
            self.disabled_models[model_name] = str(reason or "unavailable")
            print(f"[MODEL-DISABLE] Disabled '{model_name}': {self.disabled_models[model_name]}")
            self.condition.notify_all()
    
    def release(self, model_name, model_config=None, from_queue=False):
        """
        Release a connection slot for the model.
        Notifies waiting threads that a slot is available.
        """
        with self.condition:
            if model_name in self.active_counts:
                self.active_counts[model_name] = max(0, self.active_counts[model_name] - 1)
                with self.stats_lock:
                    self.stats[model_name]["active"] = self.active_counts[model_name]
            # Notify all waiters that a slot may be available
            self.condition.notify_all()
    
    def record_success(self, model_name):
        """Record a successful API call."""
        with self.stats_lock:
            if model_name in self.stats:
                self.stats[model_name]["success"] += 1
    
    def record_error(self, model_name, is_concurrency_error=False):
        """Record an error. is_concurrency_error=True for rate limit/concurrency errors."""
        with self.stats_lock:
            if model_name in self.stats:
                self.stats[model_name]["error"] += 1
                if is_concurrency_error:
                    self.stats[model_name]["concurrency_error"] += 1
    
    def get_stats(self):
        """Get current statistics for all models."""
        with self.stats_lock:
            result = {}
            for model in self.pool:
                name = model["name"]
                s = self.stats[name]
                total = s["success"] + s["error"]
                error_rate = (s["error"] / total * 100) if total > 0 else 0
                result[name] = {
                    "max_concurrent": self.limits.get(name, 5),
                    "active": s["active"],
                    "success": s["success"],
                    "error": s["error"],
                    "concurrency_error": s["concurrency_error"],
                    "error_rate": f"{error_rate:.1f}%"
                }
            return result
    
    def save_config(self):
        """Save current config to file for persistence."""
        config = {}
        for model in self.pool:
            name = model["name"]
            config[name] = {"max_concurrent": self.limits.get(name, 5)}
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            print(f"[CONFIG] Saved to {CONFIG_FILE}")
        except Exception as e:
            print(f"[CONFIG] Save error: {e}")
    
    def update_limit(self, model_name, new_limit):
        """
        Update concurrency limit for a model AT RUNTIME.
        Takes effect immediately without restart!
        """
        with self.condition:
            if model_name in self.limits:
                old_limit = self.limits[model_name]
                self.limits[model_name] = new_limit
                # Also update MODEL_POOL for consistency
                for model in self.pool:
                    if model["name"] == model_name:
                        model["max_concurrent"] = new_limit
                        break
                print(f"[CONFIG] Runtime update: {model_name} {old_limit} -> {new_limit}")
                # If limit increased, wake up waiters
                if new_limit > old_limit:
                    self.condition.notify_all()
                self.save_config()
                return True
        return False
    
    def get_total_capacity(self):
        """Get total concurrency capacity across all models."""
        return sum(self.limits.values())



# Global selector instance
model_selector = ModelSelector(MODEL_POOL)

def get_model_for_task(task_type=None):
    """
    Get appropriate model config for a specific task type.
    - 'community_search': Returns GLM-4.7-Base only
    - None: Returns next model in round-robin
    """
    return model_selector.get_next(task_type)

# Legacy compatibility - default to first model
_LEGACY_DEFAULT_MODEL = MODEL_POOL[0] if MODEL_POOL else {}
APP_ID = _LEGACY_DEFAULT_MODEL.get("app_id", "")
API_KEY = _LEGACY_DEFAULT_MODEL.get("api_key", "")
API_SECRET = _LEGACY_DEFAULT_MODEL.get("api_secret", "")
WS_URL = _LEGACY_DEFAULT_MODEL.get("ws_url", "")
MODEL_ID = _LEGACY_DEFAULT_MODEL.get("model_id", "")


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

from bs4 import BeautifulSoup

def filter_content(html_content):
    """
    Filter HTML content using BeautifulSoup to preserve structure (divs, tables)
    but remove scripts, styles, and other noise.
    """
    try:
        # Use lxml if available, else html.parser
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove unwanted tags completely
        for tag in soup(['script', 'style', 'img', 'svg', 'video', 'iframe', 'noscript', 'meta', 'link']):
            tag.decompose()
            
        # Remove strict structure tags but keep content (unwrap)
        for tname in ['div', 'a', 'span', 'li', 'p']:
            for tag in soup.find_all(tname):
                tag.unwrap()

        # Remove all attributes from remaining tags to reduce noise/tokens
        for tag in soup.find_all(True):
            tag.attrs = {}
            
        # Convert to string and normalize whitespace: remove newlines, collapse spaces
        text = str(soup)
        text = re.sub(r'[\r\n]+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
        
    except Exception as e:
        print(f"Error in filter_content: {e}")
        # Fallback to simple filtering if bs4 fails
        # Using string replacement for basic cleanup
        text = html_content
        for tag in ['<div>', '</div>', '<p>', '</p>', '<span>', '</span>', '<a>', '</a>', '<li>', '</li>']:
             text = text.replace(tag, ' ')
        
        # Remove newlines and collapse spaces
        text = re.sub(r'[\r\n]+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


AREA_EVIDENCE_PATTERNS = [
    re.compile(
        r"(?:房屋建筑面积|不动产建筑面积|产权建筑面积|证载建筑面积|建筑面积)"
        r"\s*(?:为|约|是|：|:|=)?\s*([1-9]\d{0,3}(?:\.\d{1,4})?)\s*(?:㎡|平方米|平米|m²|m2)",
        re.IGNORECASE,
    ),
    re.compile(
        r"([1-9]\d{0,3}(?:\.\d{1,4})?)\s*(?:㎡|平方米|平米|m²|m2)"
        r"\s*(?:的)?(?:房屋建筑面积|不动产建筑面积|产权建筑面积|证载建筑面积|建筑面积)",
        re.IGNORECASE,
    ),
]

GENERIC_AREA_EVIDENCE_PATTERNS = [
    re.compile(
        r"面积\s*(?:为|约|是|：|:|=)?\s*([1-9]\d{0,3}(?:\.\d{1,4})?)\s*(?:㎡|平方米|平米|m²|m2)",
        re.IGNORECASE,
    ),
    re.compile(
        r"([1-9]\d{0,3}(?:\.\d{1,4})?)\s*(?:㎡|平方米|平米|m²|m2)\s*(?:的)?面积",
        re.IGNORECASE,
    ),
]

NON_BUILDING_AREA_PREFIXES = ("宗地", "土地", "占地", "用地")


def _parse_area_number(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = re.search(r"[1-9]\d{0,3}(?:\.\d{1,4})?", str(value).replace(",", ""))
        if not match:
            return None
        number = float(match.group(0))
    if number <= 0 or number > 5000:
        return None
    return round(number, 4)


def extract_area_from_text(text):
    """Extract a plausible building area from Chinese auction detail text."""
    if not text:
        return None
    normalized = re.sub(r"\s+", "", str(text))
    for pattern in AREA_EVIDENCE_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return _parse_area_number(match.group(1))
    for pattern in GENERIC_AREA_EVIDENCE_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        prefix = normalized[max(0, match.start() - 4) : match.start()]
        if any(prefix.endswith(term) for term in NON_BUILDING_AREA_PREFIXES):
            continue
        return _parse_area_number(match.group(1))
    return None


def _parse_description_data_link(soup):
    node = soup.find(id="description-data")
    if not node:
        return None
    raw = node.get_text(strip=True)
    if not raw:
        return None
    try:
        payload = json.loads(unescape(raw))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    link = payload.get("link")
    if not link:
        return None
    link = str(link).strip()
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("http://") or link.startswith("https://"):
        return link
    return None


def fetch_description_data_text(html_content, *, timeout=20):
    """Fetch Taobao/Tmall async description HTML referenced by #description-data."""
    if not html_content:
        return None
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        link = _parse_description_data_link(soup)
        if not link:
            return None
        session = requests.Session()
        session.trust_env = False
        session.proxies = {"http": None, "https": None}
        response = session.get(
            link,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://sf.taobao.com/",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        raw_bytes = getattr(response, "content", None)
        if isinstance(raw_bytes, (bytes, bytearray)):
            desc_html = _decode_response_bytes(raw_bytes)
        else:
            desc_html = str(getattr(response, "text", ""))
        desc_soup = BeautifulSoup(desc_html, "html.parser")
        return desc_soup.get_text("\n", strip=True) or desc_html
    except Exception as exc:
        print(f"[AREA_FALLBACK_WARN] description-data fetch failed: {exc}")
        return None


def _decode_response_bytes(raw_bytes):
    candidates = []
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            text = raw_bytes.decode(encoding)
            candidates.append(text)
        except UnicodeDecodeError:
            continue
    if not candidates:
        return raw_bytes.decode("utf-8", errors="replace")
    return min(candidates, key=lambda text: text.count("\ufffd"))


def _parse_plain_number(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("¥", "").replace("元", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def _parse_share_ratio(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        ratio = float(value)
    else:
        text = str(value).strip().replace("％", "%")
        fraction_match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", text)
        if fraction_match:
            numerator = float(fraction_match.group(1))
            denominator = float(fraction_match.group(2))
            if denominator == 0:
                return None
            ratio = numerator / denominator
        elif "二分之一" in text or "1/2" in text:
            ratio = 0.5
        else:
            ratio = _parse_plain_number(text)
            if ratio is not None and "%" in text:
                ratio = ratio / 100.0
    if ratio is None or ratio <= 0 or ratio > 1:
        return None
    return ratio


def _backfill_area_and_unit_price(data, area_fallback):
    if not isinstance(data, dict):
        return data
    area = _parse_area_number(data.get("建筑面积"))
    gross_area = _parse_area_number(data.get("产权建筑面积"))
    share_ratio = _parse_share_ratio(data.get("产权份额比例"))
    if area is None:
        fallback_area = _parse_area_number(area_fallback)
        if fallback_area is not None:
            if gross_area is None:
                gross_area = fallback_area
                data["产权建筑面积"] = gross_area
            area = round(gross_area * share_ratio, 2) if share_ratio and share_ratio < 1 else gross_area
            data["建筑面积"] = area
    if area is None:
        return data

    unit_price = _parse_plain_number(data.get("单价"))
    transaction_price = _parse_plain_number(data.get("成交价格"))
    if transaction_price and transaction_price > 0 and (unit_price is None or unit_price <= 0):
        data["单价"] = round(transaction_price / area, 2)
    return data


COORDINATE_PATTERNS = [
    re.compile(
        r'(?is)(?:longitude|lng)\s*["\']?\s*[:=]\s*["\']?([1-9]\d{1,2}\.\d+)[,"\']?.{0,80}?(?:latitude|lat)\s*["\']?\s*[:=]\s*["\']?(-?\d{1,2}\.\d+)',
    ),
    re.compile(
        r'(?is)(?:latitude|lat)\s*["\']?\s*[:=]\s*["\']?(-?\d{1,2}\.\d+)[,"\']?.{0,80}?(?:longitude|lng)\s*["\']?\s*[:=]\s*["\']?([1-9]\d{1,2}\.\d+)',
    ),
    re.compile(
        r'(?is)(?:center|point|lnglat|lonlat)[^0-9-]{0,20}\[\s*([1-9]\d{1,2}\.\d+)\s*,\s*(-?\d{1,2}\.\d+)\s*\]',
    ),
    re.compile(
        r'(?is)(?:longitude|lng)=([1-9]\d{1,2}\.\d+).*?(?:latitude|lat)=(-?\d{1,2}\.\d+)',
    ),
    re.compile(
        r'(?is)(?:center|point|lnglat|lonlat)\s*[:=]\s*["\']([1-9]\d{1,2}\.\d+)\s*,\s*(-?\d{1,2}\.\d+)["\']',
    ),
    re.compile(
        r'(?is)(?:AMap\.LngLat|LngLat)\s*\(\s*([1-9]\d{1,2}\.\d+)\s*,\s*(-?\d{1,2}\.\d+)\s*\)',
    ),
]


def _is_valid_china_coordinate(latitude, longitude):
    return 3.0 <= latitude <= 54.5 and 73.0 <= longitude <= 136.0


def extract_property_coordinates(html_content):
    """Best-effort coordinate extraction from raw page HTML/scripts."""
    if not html_content:
        return None

    text = str(html_content)

    for pattern in COORDINATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        first = float(match.group(1))
        second = float(match.group(2))
        if pattern is COORDINATE_PATTERNS[1]:
            latitude, longitude = first, second
        else:
            longitude, latitude = first, second

        if _is_valid_china_coordinate(latitude, longitude):
            return {
                "latitude": round(latitude, 6),
                "longitude": round(longitude, 6),
                "coordinate_evidence": match.group(0)[:200],
            }

    return None


AVM_RISK_SYSTEM_PROMPT = (
    "你是一个专业的真实房地产估价师与法拍房风控专家。你的任务是从法院复杂的拍卖公告、须知"
    "以及页面详情中，像侦探一样精准提取出房屋的核心属性与潜在风险（雷区）。你必须保持绝对"
    "的客观，如果文中没有提及某项信息，请将其对应的值设置为 null。"
)

AVM_RISK_PROMPT_RULES = [
    (
        "community_name",
        "请从地址/公告中提取后续可复用、可归并的稳定位置索引名，优先是小区、楼盘或院落名称；"
        "不要求官方名称，但同一小区或同一片房源应尽量输出同一个名字。"
        "不要包含城市、区县、道路门牌号、楼号、单元号、房号；"
        "如果只能定位到商圈、镇街或片区且没有稳定小区名，可输出该片区名；无法稳定判断则返回 null。",
    ),
    ("build_year", "房屋建成年份，提取纯数字（如 2010）。如果没写，请尝试根据周边楼盘或证号年份推测，无法确定则返回 null。"),
    ("total_floors", "这栋楼一共有多少层。"),
    ("floor_level", "该房产所在的楼层，请归一化为 [\"低区\", \"中区\", \"高区\", \"顶层\", \"底层\", \"独栋\"]。"),
    ("has_elevator", "是否带电梯。true/false。"),
    ("orientation", "房屋的主要朝向。归一化为 [\"南\", \"南北\", \"东\", \"西\", \"北\", \"未知\"]。"),
    ("land_right_type", "土地权利性质。如果写了“出让”返回\"出让\"，如果写了“划拨”返回\"划拨\"，否则返回\"未知\"。注意，划拨极其危险需要补交土地出让金。"),
    ("is_occupied", "房屋目前是否有人居住、占用、或者未腾空状态？如果是，返回 true，否则 false。"),
    ("has_long_lease", "公告中是否提到“带租约”、“设立了租赁权”等？如果是，返回 true。"),
    ("clear_delivery", "法院是否明确表示“负责清场”、“按现状交付且已腾空”？如果是返回 true。如果写着“买受人自行腾退”、“自行解决”、“法院不负责交付”，则务必返回 false！"),
    ("tax_burden", "历史欠费和交易税费是由谁承担？归一化为 [\"买受人承担全部\", \"各自承担\", \"未知\"]。当写明“标的物转让登记手续所涉及的一切税费及明确或不明确的欠费均由买受人承担”时为买受人承担全部。"),
    ("is_haunted", "公告是否提到“发生过非正常死亡”、“涉嫌刑事案”等凶宅特征？如果是，返回 true。"),
    ("housing_type", "这套房子的用途是什么？归一化为 [\"住宅\", \"别墅\", \"商业\", \"办公\", \"工业\", \"车位\", \"其他\"]。"),
    ("has_keys", "法院是否持有钥匙？是否能正常安排看样？如果是返回 true，如果写明“无钥匙”返回 false。"),
    ("property_fee_owed", "公告中是否提及存在（或可能存在）物业费、水费、电费欠缴？提到了就返回 true。"),
    ("special_school_tag", "公告中是否把“带学位”、“学区房”、“对口XX小学”作为卖点提及？如果是返回 true。"),
    ("evaluation_price", "法院给出的“评估价”或“市场价”是多少元？请输出元为单位的纯数字（例如原文是230万元，则输出 2300000）。如无则返回 null。"),
    ("layout", "房屋的户型结构。提取如“3室2厅1厨2卫”这样的格式。找不到则返回 null。"),
    ("is_restricted_purchase", "公告中是否明确标明该房产“受当地限购政策限制”或“需具备购房资格”？如果是真正的限购，返回 true；如果不限购或没提，返回 false。"),
    ("includes_parking", "此次拍卖的标的物，是否附带了真实的地下车位/车库一起拍卖？（注意：不是指小区内有公共停车位，而是这个拍品本身包含了车位产权或使用权）。如果是，返回 true，寻找不到直接证据返回 false。"),
    ("is_fractional_share", "拍卖的标的物是否为“部分产权”（例如：某某房屋 50% 的份额、二分之一产权）？如果是部分产权，请务必返回 true，否则返回 false。"),
    ("tax_is_company_owned", "标的物的原所有人（即被执行人）是否为一家“公司”、“企业法人”或者挂在企业名下？如果是，返回 true（意味着买受人需承担极高的土地增值税），如果是个人则返回 false。"),
    ("has_lease_before_mortgage", "公告中是否有明确表述如：“该租赁关系设立于抵押权之后”、“不能对抗抵押权”、“法院负责带租清场”？如果是这种其实可以强制赶走租客的“假长租”，必须精准识别并返回 true；如果是普通无法清场的租约，或没有租约，均返回 false。"),
]

AVM_RISK_PROMPT_OUTPUT_RULE = (
    "请务必仅返回一段合法的 JSON 对象，不要包含任何额外的多余说明文字或 Markdown 标记。"
    "JSON 的 key 必须与上述英文名完全一致。"
    "请额外输出 extraction_confidence(0~1)、evidence_span(字符串或字符串数组)、"
    "evidence_source(公告/须知/评估报告/页面主文)、extraction_version。"
)


def build_avm_risk_prompt(page_text_content):
    """Build AVM risk extraction prompt from independent rule constants."""
    rules_text = "\n".join(
        f"{idx}. `{field}`：{instruction}"
        for idx, (field, instruction) in enumerate(AVM_RISK_PROMPT_RULES, start=1)
    )
    return f"""
# 系统 Prompt
{AVM_RISK_SYSTEM_PROMPT}

# 用户 Prompt
请仔细阅读以下法拍房网页的文本内容，帮我提取以下结构化字段。

提取规则：
{rules_text}

{AVM_RISK_PROMPT_OUTPUT_RULE}

以下是目标网页的文本内容：
```
{page_text_content}
```
""".strip()


def _extract_avm_risk_features_raw(text, item_id=None):
    """Extract AVM risk features using the 23-rule structured prompt."""
    page_text_content = (text or "").strip()
    if not page_text_content:
        return "{}"

    truncated_text = page_text_content[:120000]
    prompt = build_avm_risk_prompt(truncated_text)
    print(
        f"DEBUG: Extracting AVM risk features (item_id={item_id}, text_len={len(page_text_content)}, "
        f"prompt_len={len(prompt)})."
    )
    return chat_with_glm(prompt)

def extract_auction_data(html_content, item_id=None):
    """
    Extract structured auction data from HTML/Text content using AI.
    Applies filtering first.
    """
    # 0. Pre-Extraction of Critical Data (Area, Address)
    print("DEBUG: Pre-extracting critical data...")
    critical_text = ""
    trusted_url = None
    trusted_title = None
    coordinate_payload = extract_property_coordinates(html_content)
    area_fallback = None
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 0.4 Extract Metadata (fapaifang-meta) - Trusted Source
        meta_div = soup.find(id="fapaifang-meta")
        if meta_div:
            url_meta = meta_div.find("meta", attrs={"name": "original_url"})
            if url_meta and url_meta.get("content"):
                trusted_url = url_meta["content"]
                critical_text += f"【已知元数据】\n原始链接: {trusted_url}\n\n"
            lat_meta = meta_div.find("meta", attrs={"name": "latitude"})
            lon_meta = meta_div.find("meta", attrs={"name": "longitude"})
            if lat_meta and lon_meta:
                try:
                    lat = float(lat_meta.get("content"))
                    lon = float(lon_meta.get("content"))
                    if _is_valid_china_coordinate(lat, lon):
                        coordinate_payload = {
                            "latitude": round(lat, 6),
                            "longitude": round(lon, 6),
                            "coordinate_evidence": "meta:fapaifang-meta",
                        }
                except (TypeError, ValueError):
                    pass

        if soup.title and soup.title.string:
            trusted_title = soup.title.string.strip()
            if trusted_title:
                critical_text += f"【已知标题】\n{trusted_title}\n\n"
        
        # 0.1 Extract Address (item-address class)
        # Note: Address is often split into multiple divs inside .item-address
        addr_div = soup.find(class_="item-address")
        if addr_div:
            # Join text with space to ensure "上海 上海市 黄浦区" + " 巨鹿路..."
            addr_text = addr_div.get_text(" ", strip=True) 
            critical_text += f"【重要地点信息】\n{addr_text}\n\n"
            
        # 0.2 Extract Subject Description (J_desc id) - Provides Area
        # This contains the table with "建筑面积：105.08平方米"
        desc_div = soup.find(id="J_desc")
        if desc_div:
            # Get text but try to preserve some structure with newlines
            desc_text = desc_div.get_text("\n", strip=True)
            # Limit length of description just in case it's massive
            critical_text += f"【重要标的物描述】\n{desc_text[:20000]}\n\n"

        # 0.3 Extract Notice Detail (J_NoticeDetail id) - Provides Critical Area Info
        # As per user request, this div contains the "建筑面积" text reliably.
        notice_div = soup.find(id="J_NoticeDetail")
        if notice_div:
            # Extract text as single line, truncate at "竞买人条件"
            text_val = notice_div.get_text(separator="", strip=True)
            if "竞买人条件" in text_val:
                text_val = text_val.split("竞买人条件")[0]
            clean_notice = re.sub(r'\s+', '', text_val)
            critical_text += f"【重要竞买公告（含建筑面积）】\n{clean_notice}\n\n"
        else:
            print("DEBUG: J_NoticeDetail not found, skipping this part.")

        desc_async_text = fetch_description_data_text(html_content)
        if desc_async_text:
            area_fallback = extract_area_from_text(desc_async_text)
            critical_text += f"【异步标的物描述（含可能面积）】\n{desc_async_text[:20000]}\n\n"
            
    except Exception as e:
        print(f"Warning: Pre-extraction failed: {e}")

    if coordinate_payload:
        critical_text += (
            "【已知坐标信息】\n"
            f"纬度: {coordinate_payload['latitude']}\n"
            f"经度: {coordinate_payload['longitude']}\n\n"
        )

    # 1. Filter Content
    print(f"DEBUG: Filtering content (len={len(html_content)})...")
    filtered_text = filter_content(html_content)
    print(f"DEBUG: Filtered content (len={len(filtered_text)}). Preparing prompt...")
    
    # Limit length to avoid context overflow, though filtered text should be smaller
    truncated_text = filtered_text[:100000] 

    # 2. Construct Prompt (Strict User Rules)
    prompt = f"""
# Role
你是一个专业的房产拍卖数据清洗专家。

# Task
我将提供一条原始的房产数据。你需要根据以下规则，对其进行清洗、提取、计算和标准化，最终输出一个符合指定结构的 JSON 对象。

# Rules

## 1. 数据清洗与类型转换
- **数值清洗**：所有价格、面积、ID、人数等字段，必须去除人民币符号（¥）、逗号（,）和引号。输出应为纯数字（Number 类型）。
- **布尔值转换**：`是否成交` 字段，如果原始数据 `status` 为 "done" 或类似成交状态，输出布尔值 `true`，否则输出 `false`。
- **面积清洗**：`建筑面积` 字段需去除“平方米”、“㎡”等单位，仅保留数字（保留两位小数）。注意：此处的建筑面积为房产证上的建筑面积，非套内建筑面积。

## 2. 字段映射与提取
请从原始数据中提取并映射到以下字段（注意：不要输出原始字段名，只输出新字段名）：
- `id` -> `唯一id`
- `market_price` -> `市场评估价`
- `initialPrice` -> `起拍价格`
- `deposit` 或文本中的 **保证金** -> `保证金`
- `deal_price`、`currentPrice` 或文本中的 **`拍下价`** -> `成交价格` (注意：不要输出 `成交价` 字段，仅保留 `成交价格`)
- `startTime` 或文本中的 **开拍时间** -> `开拍时间`
- `auction_date` -> `交易时间`
- `url` -> `原始网站`
- `title` -> `标题`
- `status` -> `是否成交`
- `applyCount` -> `竞拍人数`
- `bidCount` -> `出价次数`
- `bidUserNumber` 或明确描述“共有X人出价” -> `出价人数`
- `watchCount` / `pv` / 文本中的围观数 -> `围观人数`
- `remindCount` / 文本中的提醒数 -> `提醒人数`
- `viewCount` / 文本中的浏览数 -> `浏览次数`
- `item_address` -> `地点`

## 3. 智能信息补充
- **地点/完整地址**：必须优先输出真实地址文本。如果页面没有明确地址，不要为了凑字段把 `title` 原样抄进 `地点`；此时 `地点` 和 `完整地址` 可以为 null。
- **所属小区/稳定位置索引名**：必须基于 `item_address`、`地点`、`完整地址` 或 `title` 中的地址信息，输出用于后续归并、索引同片房源的稳定位置索引名。不要求它是官方名称，但同一小区或同一片房源应尽量输出同一个名字；优先输出小区、楼盘或院落名称，也可以在无法稳定识别小区时输出商圈、镇街或片区名。不要输出城市、区县、道路门牌号、楼号、单元号、房号。如果确实无法形成稳定索引名，填入 null。
- **地理位置解析**：根据 `地点`、`完整地址` 或 `title`，解析并填充 `省份`、`城市`、`区`。
- **最靠近商圈**：根据地址信息，推断该房产最靠近的知名商圈或板块名称。

## 4. 数据计算
- **单价计算**：公式为 `单价 = 成交价格 / 建筑面积`。结果保留两位小数。（注意：成交价格即为上面提取的拍下价）
- **缺失面积处理**：如果 `building_area` 为空，请优先从【重要标的物描述】或【重要竞买公告（含建筑面积）】中寻找数字线索。如果确实无法获取，请将 `建筑面积` 设为 null，`单价` 设为 0。
- **产权份额处理**：如果拍卖标的涉及部分产权（如"1/2产权"、"二分之一所有权"、"50%份额"、"1/12产权份额"等），请同时输出：
  - `产权建筑面积` = 原始产权建筑面积
  - `产权份额比例` = 0~1 浮点值
  - `建筑面积` = 最终有效可交易面积（例如 120 平米的 1/2 产权，则输出 60）
- **法务上下文**：如果页面中出现执行法院、案号，请尽量提取到 `法院名称` 和 `案号`。

## 5. 输出格式要求
- 仅输出最终的 JSON 对象，不要包含任何解释性文字、Markdown 代码块标记（如 ```json）或其他多余内容。
- 字段顺序必须严格遵循下方的“输出模板”顺序。

# Output Template
请严格按照以下 JSON 结构和顺序输出数据：

{{
    "id": [Number],
    "市场评估价": [Number],
    "起拍价格": [Number],
    "成交价格": [Number],
    "保证金": [Number],
    "开拍时间": [String],
    "交易时间": [String],
    "原始网站": [String],
    "标题": [String],
    "是否成交": [Boolean],
    "竞拍人数": [Number],
    "出价次数": [Number],
    "出价人数": [Number],
    "围观人数": [Number],
    "提醒人数": [Number],
    "浏览次数": [Number],
    "地点": [String],
    "完整地址": [String],
    "所属小区": [String],
    "省份": [String],
    "城市": [String],
    "区": [String],
    "最靠近商圈": [String],
    "建筑面积": [Number],
    "产权建筑面积": [Number],
    "产权份额比例": [Number],
    "法院名称": [String],
    "案号": [String],
    "单价": [Number],
    "is_processed": true
}}

# Input Data
{critical_text}
---
{truncated_text}
    """
    
    # Debug: Save prompt for inspection
    # Debug: Save prompt for inspection (DISABLED by user request)
    # try:
    #     filename = f"item_{item_id}_ai_prompt.txt" if item_id else "test_output.txt"
    #     with open(filename, "w", encoding="utf-8") as f:
    #         f.write(prompt)
    # except: pass

    ai_response = chat_with_glm(prompt)

    try:
        data = json.loads(ai_response)
        if trusted_url:
            print(f"DEBUG: Overwriting AI URL with trusted metadata: {trusted_url}")
            data["原始网站"] = trusted_url
        if trusted_title and not data.get("标题"):
            data["标题"] = trusted_title
        if trusted_title and not data.get("title"):
            data["title"] = trusted_title
            data.setdefault("source_title", trusted_title)
        elif data.get("标题") and not data.get("title"):
            data["title"] = data.get("标题")
            data.setdefault("source_title", data.get("标题"))
        if data.get("完整地址") and not data.get("地点"):
            data["地点"] = data.get("完整地址")
        if data.get("地点") and not data.get("完整地址"):
            data["完整地址"] = data.get("地点")
        _backfill_area_and_unit_price(data, area_fallback)
        if coordinate_payload:
            data.setdefault("纬度", coordinate_payload["latitude"])
            data.setdefault("经度", coordinate_payload["longitude"])
            data.setdefault("latitude", coordinate_payload["latitude"])
            data.setdefault("longitude", coordinate_payload["longitude"])
            data.setdefault("coordinate_source", coordinate_payload.get("coordinate_evidence", "html"))
        return json.dumps(data, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Warning: Failed to normalize extracted JSON: {e}. Returning original response.")
        return ai_response


AVM_RISK_BOOLEAN_FIELDS = {
    "has_elevator",
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "is_haunted",
    "has_keys",
    "property_fee_owed",
    "special_school_tag",
    "is_restricted_purchase",
    "includes_parking",
    "is_fractional_share",
    "tax_is_company_owned",
    "has_lease_before_mortgage",
}

AVM_RISK_NUMERIC_FIELDS = {
    "build_year",
    "total_floors",
    "evaluation_price",
}

AVM_RISK_ENUM_FIELDS = {
    "floor_level": {"低区", "中区", "高区", "顶层", "底层", "独栋"},
    "orientation": {"南", "南北", "东", "西", "北", "未知"},
    "land_right_type": {"出让", "划拨", "未知"},
    "tax_burden": {"买受人承担全部", "各自承担", "未知"},
    "housing_type": {"住宅", "别墅", "商业", "办公", "工业", "车位", "其他"},
}

AVM_RISK_KEYS = [
    "community_name",
    "build_year",
    "total_floors",
    "floor_level",
    "has_elevator",
    "orientation",
    "land_right_type",
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "tax_burden",
    "is_haunted",
    "housing_type",
    "has_keys",
    "property_fee_owed",
    "special_school_tag",
    "evaluation_price",
    "layout",
    "is_restricted_purchase",
    "includes_parking",
    "is_fractional_share",
    "tax_is_company_owned",
    "has_lease_before_mortgage",
]

AVM_RISK_AUDIT_KEYS = [
    "extraction_confidence",
    "evidence_span",
    "evidence_source",
    "extraction_version",
]


def validate_avm_risk_features_schema(features, item_id=None):
    """
    Hand-written schema validation for AVM risk extraction.
    Returns (passed, errors).
    """
    errors = []
    item_label = item_id if item_id is not None else "unknown"

    if not isinstance(features, dict):
        return False, [f"item={item_label}: payload is not a dict"]

    for key in AVM_RISK_KEYS:
        if key not in features:
            errors.append(f"item={item_label}: missing key '{key}'")

    for key in AVM_RISK_BOOLEAN_FIELDS:
        value = features.get(key)
        if value is not None and not isinstance(value, bool):
            errors.append(f"item={item_label}: '{key}' expects bool/null, got {type(value).__name__}")

    for key in AVM_RISK_NUMERIC_FIELDS:
        value = features.get(key)
        if value is not None and not isinstance(value, (int, float)):
            errors.append(f"item={item_label}: '{key}' expects number/null, got {type(value).__name__}")

    extraction_confidence = features.get("extraction_confidence")
    if extraction_confidence is not None:
        if not isinstance(extraction_confidence, (int, float)):
            errors.append(f"item={item_label}: 'extraction_confidence' expects number/null, got {type(extraction_confidence).__name__}")
        elif extraction_confidence < 0 or extraction_confidence > 1:
            errors.append(f"item={item_label}: 'extraction_confidence' out of range {extraction_confidence}")

    for key, allowed in AVM_RISK_ENUM_FIELDS.items():
        value = features.get(key)
        if value is not None and value not in allowed:
            errors.append(f"item={item_label}: '{key}' enum invalid value '{value}'")

    evidence_span = features.get("evidence_span")
    if evidence_span is not None and not isinstance(evidence_span, (str, list)):
        errors.append(f"item={item_label}: 'evidence_span' expects str/list/null, got {type(evidence_span).__name__}")

    if "evidence_source" in features:
        source = features.get("evidence_source")
        allowed_sources = {"公告", "须知", "评估报告", "页面主文"}
        if source is not None and not isinstance(source, str):
            errors.append(f"item={item_label}: 'evidence_source' expects str/null, got {type(source).__name__}")
        elif source is not None and source not in allowed_sources:
            errors.append(f"item={item_label}: 'evidence_source' invalid value '{source}'")

    extraction_version = features.get("extraction_version")
    if extraction_version is not None and not isinstance(extraction_version, str):
        errors.append(f"item={item_label}: 'extraction_version' expects str/null, got {type(extraction_version).__name__}")

    passed = len(errors) == 0
    if passed:
        print(f"[AVM-RISK][SCHEMA PASS] item={item_label}")
    else:
        print(f"[AVM-RISK][SCHEMA FAILED] item={item_label}; errors={errors}")

    return passed, errors


def sanitize_avm_risk_features(features, item_id=None):
    """按字段降级清洗抽取结果，返回 (sanitized, dropped_fields)。

    与 `validate_avm_risk_features_schema` 的整条否决不同，这里把不合规的
    单个字段置为 None 并记录，其余字段原样保留。整条否决在线上造成过
    228,959 条记录风险字段全空：`orientation` 返回“东南”这类枚举外的真实值
    会把同一条里已正确抽出的 is_occupied / clear_delivery / build_year 一起
    丢掉。结构性错误（非 dict）无法字段级降级，仍整体拒绝。
    """
    item_label = item_id if item_id is not None else "unknown"

    if not isinstance(features, dict):
        print(f"[AVM-RISK][SANITIZE REJECT] item={item_label}: payload is not a dict")
        return None, []

    sanitized = dict(features)
    dropped = []

    def _drop(key, reason):
        sanitized[key] = None
        dropped.append(key)
        print(f"[AVM-RISK][FIELD DROPPED] item={item_label}: {key} ({reason})")

    for key in AVM_RISK_BOOLEAN_FIELDS:
        value = sanitized.get(key)
        if value is not None and not isinstance(value, bool):
            _drop(key, f"expects bool/null, got {type(value).__name__}")

    for key in AVM_RISK_NUMERIC_FIELDS:
        value = sanitized.get(key)
        # bool 是 int 的子类，这里要排除，否则 True 会被当成数字放过
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            _drop(key, f"expects number/null, got {type(value).__name__}")

    for key, allowed in AVM_RISK_ENUM_FIELDS.items():
        value = sanitized.get(key)
        if value is not None and value not in allowed:
            _drop(key, f"enum invalid value {value!r}")

    confidence = sanitized.get("extraction_confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            _drop("extraction_confidence", f"expects number/null, got {type(confidence).__name__}")
        elif confidence < 0 or confidence > 1:
            _drop("extraction_confidence", f"out of range {confidence}")

    evidence_span = sanitized.get("evidence_span")
    if evidence_span is not None and not isinstance(evidence_span, (str, list)):
        _drop("evidence_span", f"expects str/list/null, got {type(evidence_span).__name__}")

    if dropped:
        print(f"[AVM-RISK][SANITIZED] item={item_label}: dropped={dropped}")
    else:
        print(f"[AVM-RISK][SANITIZE CLEAN] item={item_label}")

    return sanitized, dropped


def _normalize_evidence_source(value):
    allowed_sources = {"公告", "须知", "评估报告", "页面主文"}
    if isinstance(value, str):
        normalized = value.strip()
        return normalized if normalized in allowed_sources else "页面主文"
    if isinstance(value, list):
        for item in value:
            normalized = str(item).strip()
            if normalized in allowed_sources:
                return normalized
        return "页面主文"
    if value is None:
        return "页面主文"
    return "页面主文"


def extract_avm_risk_features(page_text, item_id=None):
    """
    Independent AVM risk feature extraction aligned with the frozen collection contract
    and the in-code AVM risk prompt rules.
    """
    item_label = item_id if item_id is not None else "unknown"
    if not page_text or not str(page_text).strip():
        print(f"[AVM-RISK] Empty page text for item={item_label}")
        return None

    prompt = build_avm_risk_prompt(str(page_text)[:100000])

    try:
        raw = chat_with_glm(prompt)
        features = json.loads(raw)
    except Exception as e:
        print(f"[AVM-RISK] LLM parse error item={item_label}: {e}")
        return None

    if not isinstance(features, dict):
        print(f"[AVM-RISK] Non-dict response item={item_label}: {type(features).__name__}")
        return None

    for key in AVM_RISK_KEYS:
        if key not in features:
            features[key] = None

    for key in AVM_RISK_AUDIT_KEYS:
        features.setdefault(key, None)

    features["extraction_version"] = features.get("extraction_version") or "avm_risk_v2"
    features["evidence_source"] = _normalize_evidence_source(features.get("evidence_source"))
    if features.get("extraction_confidence") is None:
        features["extraction_confidence"] = 0.5
    if features.get("evidence_span") is None:
        features["evidence_span"] = ""

    # 保留一次整条校验，纯粹为了把问题字段打进日志便于观测
    validate_avm_risk_features_schema(features, item_id=item_id)

    # 落库走字段级降级：坏字段置 None，好字段保留。整条否决会让单个枚举外的
    # 真实值（如 orientation="东南"）带走同一条里所有正确抽取的风险字段。
    sanitized, _dropped = sanitize_avm_risk_features(features, item_id=item_id)
    return sanitized

def _strip_json_markdown(result):
    if "```json" in result:
        return result.split("```json")[1].split("```")[0].strip()
    if "```" in result:
        return result.split("```")[1].split("```")[0].strip()
    return result


def _get_openai_compatible_config():
    base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or os.environ.get("OPENAI_COMPATIBLE_BASE_URL")
    )
    api_key = os.environ.get("OPENAI_API_KEY")
    if not base_url or not api_key:
        return None
    primary_model = os.environ.get("OPENAI_MODEL") or os.environ.get("OPENAI_COMPATIBLE_MODEL") or "gpt-5.5"
    candidate_text = os.environ.get("OPENAI_MODEL_CANDIDATES") or ""
    models = []
    for candidate in [primary_model, *re.split(r"[;,]", candidate_text)]:
        normalized = str(candidate or "").strip()
        if normalized and normalized not in models:
            models.append(normalized)
    config = {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "model": models[0],
        "models": models,
        "timeout": float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "180")),
        "max_retries": int(os.environ.get("OPENAI_MAX_RETRIES", "3")),
    }
    reasoning_effort = str(os.environ.get("OPENAI_REASONING_EFFORT") or "").strip().lower()
    if reasoning_effort:
        allowed_reasoning_efforts = {"none", "minimal", "low", "medium", "high", "xhigh"}
        if reasoning_effort not in allowed_reasoning_efforts:
            raise ValueError(
                "OPENAI_REASONING_EFFORT must be one of: "
                + ", ".join(sorted(allowed_reasoning_efforts))
            )
        config["reasoning_effort"] = reasoning_effort
    return config


def _first_nonempty_env(*names):
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _is_local_openai_compatible_url(base_url):
    host = (urlparse(str(base_url)).hostname or "").strip().lower()
    return host in {
        "localhost",
        "127.0.0.1",
        "::1",
        "host.docker.internal",
        "gateway.docker.internal",
        "host.containers.internal",
        "192.168.65.254",
    }


def _get_openai_compatible_proxies(base_url=None):
    fallback_proxy = _first_nonempty_env("OPENAI_PROXY", "FAPAI_LLM_PROXY")
    explicit_http_proxy = _first_nonempty_env("OPENAI_HTTP_PROXY", "FAPAI_LLM_HTTP_PROXY")
    explicit_https_proxy = _first_nonempty_env("OPENAI_HTTPS_PROXY", "FAPAI_LLM_HTTPS_PROXY")
    if base_url and _is_local_openai_compatible_url(base_url) and not (
        fallback_proxy or explicit_http_proxy or explicit_https_proxy
    ):
        return {}

    http_proxy = explicit_http_proxy or _first_nonempty_env("FAPAI_HTTP_PROXY") or fallback_proxy
    https_proxy = explicit_https_proxy or _first_nonempty_env("FAPAI_HTTPS_PROXY") or fallback_proxy or http_proxy
    proxies = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies


def _chat_with_openai_compatible(content, config):
    url = f"{config['base_url']}/chat/completions"
    session = requests.Session()
    session.trust_env = False
    proxies = _get_openai_compatible_proxies(config["base_url"])
    if proxies:
        session.proxies = proxies
    max_retries = max(int(config.get("max_retries", 3)), 1)
    models = list(config.get("models") or [config["model"]])
    response = None
    for attempt in range(1, max_retries + 1):
        for model in models:
            request_payload = {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0,
            }
            if config.get("reasoning_effort"):
                request_payload["reasoning_effort"] = config["reasoning_effort"]
            response = session.post(
                url,
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=config["timeout"],
            )
            status_code = getattr(response, "status_code", None)
            if status_code is not None and status_code < 400:
                config["last_successful_model"] = model
                break
            if status_code in (400, 401):
                response.raise_for_status()
            if status_code not in (403, 429, 500, 502, 503, 504, 524):
                response.raise_for_status()
        if response is not None and getattr(response, "status_code", None) is not None and response.status_code < 400:
            break
        if attempt >= max_retries:
            break
        wait_seconds = min(2 ** (attempt - 1), 8)
        print(
            "DEBUG: OpenAI-compatible candidate models unavailable; "
            f"retry {attempt}/{max_retries} after {wait_seconds}s"
        )
        time.sleep(wait_seconds)
    if response is None:
        raise LLMBackendUnavailableError("LLM backend unavailable: no OpenAI-compatible model candidates")
    response.raise_for_status()
    raw_bytes = getattr(response, "content", None)
    if isinstance(raw_bytes, (bytes, bytearray)):
        raw_payload = raw_bytes.decode("utf-8")
    else:
        raw_payload = str(getattr(response, "text", ""))
    payload = json.loads(raw_payload)
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise ValueError("OpenAI-compatible response missing choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    result = message.get("content") if isinstance(message, dict) else None
    if not result:
        raise ValueError("OpenAI-compatible response missing message content")
    return result


def preflight_openai_compatible_backend(timeout=15.0, *, check_chat=False):
    config = _get_openai_compatible_config()
    if not config:
        return {"enabled": False}
    url = f"{config['base_url']}/models"
    session = requests.Session()
    session.trust_env = False
    proxies = _get_openai_compatible_proxies(config["base_url"])
    if proxies:
        session.proxies = proxies
    try:
        response = session.get(
            url,
            headers={"Authorization": f"Bearer {config['api_key']}"},
            timeout=float(timeout),
        )
    except requests.RequestException as exc:
        return {
            "enabled": True,
            "url": url,
            "status_code": 0,
            "error_type": type(exc).__name__,
        }
    result = {
        "enabled": True,
        "url": url,
        "status_code": getattr(response, "status_code", None),
    }
    if check_chat:
        chat_url = f"{config['base_url']}/chat/completions"
        models = list(config.get("models") or [config["model"]])
        chat_response = None
        chat_model = None
        for model in models:
            try:
                request_payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": '这是法拍房分析服务连通性检查。请仅返回 JSON：{"ok":true}',
                        }
                    ],
                    "temperature": 0,
                    "max_tokens": 32,
                }
                if config.get("reasoning_effort"):
                    request_payload["reasoning_effort"] = config["reasoning_effort"]
                chat_response = session.post(
                    chat_url,
                    headers={
                        "Authorization": f"Bearer {config['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                    timeout=float(timeout),
                )
            except requests.RequestException as exc:
                chat_response = None
                result.setdefault("probe_errors", []).append(
                    {"model_name": model, "error_type": type(exc).__name__}
                )
                continue
            status_code = getattr(chat_response, "status_code", None)
            if status_code is not None and status_code < 400:
                chat_model = model
                break
            if status_code in (400, 401):
                break
        result.update(
            {
                "chat_url": chat_url,
                "chat_status_code": getattr(chat_response, "status_code", None),
            }
        )
        if len(models) > 1:
            result["chat_model_name"] = chat_model
    return result


def preflight_llm_backend(timeout=15.0, *, check_chat=False):
    config = _get_openai_compatible_config()
    if config:
        result = preflight_openai_compatible_backend(timeout=timeout, check_chat=check_chat)
        result.setdefault("backend", "openai_compatible")
        return result
    if not MODEL_POOL:
        return {"enabled": False}

    result = {
        "enabled": True,
        "backend": "glm_websocket_pool",
        "model_pool_size": len(MODEL_POOL),
    }
    if not check_chat:
        return result

    disabled_models = dict(getattr(model_selector, "disabled_models", {}) or {})
    enabled_models = [model for model in MODEL_POOL if str(model.get("name") or "") not in disabled_models]
    if not enabled_models:
        result.update(
            {
                "chat_status_code": 401 if disabled_models else 503,
                "error": "all_models_appid_no_auth" if disabled_models else "all_models_unavailable",
                "probe_errors": [
                    {
                        "model_name": model_name,
                        "error": reason,
                    }
                    for model_name, reason in list(disabled_models.items())[:5]
                ],
            }
        )
        return result

    prompt = '请只返回JSON: {"ok":true}'
    probe_errors = []
    probe_success = None
    auth_error_only = True

    for model in enabled_models:
        model_name = str(model.get("name") or "")
        try:
            service = AIService(model_config=model)
            response = service.get_response(prompt)
            if str(response or "").strip():
                probe_success = model_name
                break
            error_code = int(service.error_code or 0)
            error_msg = str(service.error_msg or "empty_response")
            probe_errors.append(
                {
                    "model_name": model_name,
                    "error_code": error_code,
                    "error": error_msg,
                }
            )
            if error_code not in AUTH_INVALID_ERROR_CODES or "AppIdNoAuthError" not in error_msg:
                auth_error_only = False
        except LLMBackendUnavailableError as exc:
            message = str(exc)
            probe_errors.append(
                {
                    "model_name": model_name,
                    "error": message,
                }
            )
            if "disabled" not in message.lower():
                auth_error_only = False
        except Exception as exc:
            probe_errors.append(
                {
                    "model_name": model_name,
                    "error": repr(exc),
                }
            )
            auth_error_only = False

    if probe_success:
        result.update(
            {
                "chat_status_code": 200,
                "chat_model_name": probe_success,
            }
        )
        return result

    result.update(
        {
            "chat_status_code": 401 if probe_errors and auth_error_only else 503,
            "error": "all_models_appid_no_auth" if probe_errors and auth_error_only else "all_models_unavailable",
            "probe_errors": probe_errors[:5],
        }
    )
    return result


def chat_with_glm(content):
    """
    Send content to the configured LLM backend and return response.
    """
    openai_config = _get_openai_compatible_config()
    if openai_config:
        print(f"DEBUG: Sending request to OpenAI-compatible backend (model={openai_config['model']})...")
        result = _chat_with_openai_compatible(content, openai_config)
        print(f"DEBUG: OpenAI-compatible response received (len={len(result)}).")
        stripped = _strip_json_markdown(result)
        if not str(stripped or "").strip():
            raise LLMBackendUnavailableError("LLM backend unavailable: OpenAI-compatible backend returned empty response")
        return stripped

    service = AIService()
    print("DEBUG: Sending request to GLM-4.7...")
    result = service.get_response(content)
    print(f"DEBUG: GLM-4.7 response received (len={len(result)}).")

    if service.error_code in AUTH_INVALID_ERROR_CODES:
        raise LLMBackendUnavailableError(
            f"LLM backend unavailable: error_code={service.error_code}, error_msg={service.error_msg or 'AppIdNoAuthError'}"
        )
    stripped = _strip_json_markdown(result)
    if not str(stripped or "").strip():
        raise LLMBackendUnavailableError("LLM backend unavailable: empty response from AI backend")
    return stripped

if __name__ == "__main__":
    # Test
    print("Testing GLM-4.7 (WebSocket)...")
    res = chat_with_glm("你好，请做一个简单的自我介绍，并返回JSON格式: {\"name\": \"AI\", \"role\": \"Assistant\"}")
    print(f"Response: {res}")
