import _thread as thread
import random
import base64
import datetime
import hashlib
import hmac
import json
from urllib.parse import urlparse
import ssl
from datetime import datetime
from time import mktime
from wsgiref.handlers import format_date_time
import websocket  # pip install websocket-client
import re

# ==================== MODEL POOL CONFIGURATION ====================
# Credentials are loaded from secrets.json (not committed to git).
# Copy secrets.example.json to secrets.json and fill in your API keys.

import os as _os
import json as _json

_SECRETS_FILE = _os.path.join(_os.path.dirname(__file__), "..", "secrets.json")

def _load_secrets():
    """Load API credentials from secrets.json."""
    if not _os.path.exists(_SECRETS_FILE):
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
            while self.active_counts.get(model_name, 0) >= self.limits.get(model_name, 5):
                self.condition.wait()
            
            self.active_counts[model_name] = self.active_counts.get(model_name, 0) + 1
            with self.stats_lock:
                self.stats[model_name]["active"] = self.active_counts[model_name]
            return True
    
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
APP_ID = MODEL_POOL[0]["app_id"]
API_KEY = MODEL_POOL[0]["api_key"]
API_SECRET = MODEL_POOL[0]["api_secret"]
WS_URL = MODEL_POOL[0]["ws_url"]
MODEL_ID = MODEL_POOL[0]["model_id"]


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
        from_queue = False  # Track how we acquired the slot
        
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

def extract_auction_data(html_content, item_id=None):
    """
    Extract structured auction data from HTML/Text content using AI.
    Applies filtering first.
    """
    # 0. Pre-Extraction of Critical Data (Area, Address)
    print("DEBUG: Pre-extracting critical data...")
    critical_text = ""
    trusted_url = None
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 0.4 Extract Metadata (fapaifang-meta) - Trusted Source
        meta_div = soup.find(id="fapaifang-meta")
        if meta_div:
            url_meta = meta_div.find("meta", attrs={"name": "original_url"})
            if url_meta and url_meta.get("content"):
                trusted_url = url_meta["content"]
                critical_text += f"【已知元数据】\n原始链接: {trusted_url}\n\n"
        
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
            
    except Exception as e:
        print(f"Warning: Pre-extraction failed: {e}")

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
- `deal_price`、`currentPrice` 或文本中的 **`拍下价`** -> `成交价格` (注意：不要输出 `成交价` 字段，仅保留 `成交价格`)
- `auction_date` -> `交易时间`
- `url` -> `原始网站`
- `status` -> `是否成交`
- `applyCount` -> `竞拍人数`
- `bidCount` -> `出价人数`
- `item_address` -> `地点`

## 3. 智能信息补充
- **所属小区**：必须基于 `item_address` 或 `title` 中的地址信息，推理该房产所在的具体小区名称（请使用贝壳楼盘字典数据库中的标准名称）。例如“天寿路25号”应识别为对应的小区名。如果确实无法识别，填入 null。
- **地理位置解析**：根据 `地点` 或 `title`，解析并填充 `省份`、`城市`、`区`。
- **最靠近商圈**：根据地址信息，推断该房产最靠近的知名商圈或板块名称。

## 4. 数据计算
- **单价计算**：公式为 `单价 = 成交价格 / 建筑面积`。结果保留两位小数。（注意：成交价格即为上面提取的拍下价）
- **缺失面积处理**：如果 `building_area` 为空，请优先从【重要标的物描述】或【重要竞买公告（含建筑面积）】中寻找数字线索。如果确实无法获取，请将 `建筑面积` 设为 null，`单价` 设为 0。
- **产权份额处理**：如果拍卖标的涉及部分产权（如"1/2产权"、"二分之一所有权"、"50%份额"、"1/12产权份额"等），则必须按份额比例缩小建筑面积。例如：房产证上建筑面积为120平方米，拍卖的是1/2产权，则输出的 `建筑面积` 应为60平方米。请仔细阅读标题和公告内容，识别产权份额信息。

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
    "交易时间": [String],
    "原始网站": [String],
    "是否成交": [Boolean],
    "竞拍人数": [Number],
    "出价人数": [Number],
    "地点": [String],
    "所属小区": [String],
    "省份": [String],
    "城市": [String],
    "区": [String],
    "最靠近商圈": [String],
    "建筑面积": [Number],
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
    
    # Post-process: Force overwrite URL if trusted one exists
    if trusted_url:
        try:
            print(f"DEBUG: Overwriting AI URL with trusted metadata: {trusted_url}")
            data = json.loads(ai_response)
            data["原始网站"] = trusted_url
            return json.dumps(data, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Warning: Failed to overwrite URL in JSON: {e}. Returning original response.")
            return ai_response
            
    return ai_response

def chat_with_glm(content):
    """
    Send content to GLM-4.7 (MaaS via WebSocket) and return response.
    """
    service = AIService()
    print("DEBUG: Sending request to GLM-4.7...")
    result = service.get_response(content)
    print(f"DEBUG: GLM-4.7 response received (len={len(result)}).")
    
    # Cleanup markdown if present
    if "```json" in result:
        result = result.split("```json")[1].split("```")[0].strip()
    elif "```" in result:
        result = result.split("```")[1].split("```")[0].strip()
        
    return result

if __name__ == "__main__":
    # Test
    print("Testing GLM-4.7 (WebSocket)...")
    res = chat_with_glm("你好，请做一个简单的自我介绍，并返回JSON格式: {\"name\": \"AI\", \"role\": \"Assistant\"}")
    print(f"Response: {res}")
