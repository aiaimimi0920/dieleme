import http.server
import socketserver
import json
import os
import datetime
import glob
import llm_helper
import threading
import time
import re
import re
from urllib.parse import urlparse, parse_qs, unquote
from concurrent.futures import ThreadPoolExecutor

# AVM module placeholder import (not wired into main flow yet)
from avm import service as avm_service  # noqa: F401

# Import Captcha Solver
from captcha_solver import CaptchaSolver
solver = CaptchaSolver(port=9222)

# Import JobManager from jobs directory
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jobs.job_manager import JobManager

PORT = 8001
BATCH_SIZE = 8  # User Configurable Concurrency
DISPATCH_COOLDOWN_SECONDS = 20  # Task redispatch cooldown (aggressive profile)
# Global Thread Pool for AI tasks (Limit 32 to prevent API overload)
executor = ThreadPoolExecutor(max_workers=32)
DATA_DIR = "datas"

# Global state
SEEN_IDS = {}  # id -> {file_path, status, data}
PENDING_TASKS = [] # list of ids
DISPATCHED_TASKS = {} # id -> timestamp
PAUSED = False
SOLVER_LOCK = threading.Lock()
FILE_LOCK = threading.Lock()
DATA_LOCK = threading.Lock() # Protects SEEN_IDS and PENDING_TASKS
CURRENT_PROCESSING = set() # Track running tasks to avoid duplicate submission
SOLVER_RUNNING = False
SOLVER_START_TIME = 0

# --- Watchdog for Service Continuity ---
LAST_REQUEST_TIME = time.time()
WATCHDOG_TIMEOUT = 10 * 60  # 10 minutes in seconds
WATCHDOG_CHECK_INTERVAL = 60  # Check every 60 seconds

def watchdog_thread():
    """Monitor for service continuity. If no requests for 10 minutes, restart Edge with recovery URLs."""
    global LAST_REQUEST_TIME
    import subprocess
    
    while True:
        time.sleep(WATCHDOG_CHECK_INTERVAL)
        
        elapsed = time.time() - LAST_REQUEST_TIME
        if elapsed > WATCHDOG_TIMEOUT:
            print(f"[WATCHDOG] No requests for {int(elapsed)}s. Triggering recovery...")
            
            try:
                # Step 1: Kill all Edge processes
                subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], 
                              capture_output=True, timeout=30)
                print("[WATCHDOG] Killed all Edge processes.")
                
                # Wait for processes to fully terminate
                time.sleep(5)
                
                # Step 2: Open 3 independent Edge windows with Remote Debugging
                # Window 1: Sniff Tab #1
                subprocess.Popen(['start', 'msedge', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window', 
                                 'https://sf.taobao.com/list/50025969.htm?auto_recovery=1'], 
                                shell=True)
                time.sleep(2)
                
                # Window 2: Sniff Tab #2
                subprocess.Popen(['start', 'msedge', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window', 
                                 'https://sf.taobao.com/list/50025969.htm?auto_recovery=2'], 
                                shell=True)
                time.sleep(2)
                
                # Window 3: Worker Tab
                subprocess.Popen(['start', 'msedge', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window', 
                                 'https://sf.taobao.com/?auto_worker=1'], 
                                shell=True)
                
                print("[WATCHDOG] Recovery complete. 3 Edge windows opened with Debug Port 9222.")
                
                # Reset timer to avoid immediate re-trigger
                LAST_REQUEST_TIME = time.time()
                
            except Exception as e:
                print(f"[WATCHDOG] Recovery failed: {e}")

# Start watchdog thread
threading.Thread(target=watchdog_thread, daemon=True).start()
print("[WATCHDOG] Service continuity watchdog started (timeout: 10 minutes).")

def check_and_launch_browser():
    """Check if debug port 9222 is open, if not, launch browser."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 9222))
    sock.close()
    
    if result != 0:
        print("[STARTUP] Debug port 9222 not open. Launching Edge...")
        # Reuse watchdog logic to launch
        try:
             # Kill existing first to ensure port availability
             import subprocess
             subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
             time.sleep(2)
             
             # Launch windows
             subprocess.Popen(['start', 'msedge', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window', 'https://sf.taobao.com/list/50025969.htm?auto_recovery=1'], shell=True)
             time.sleep(2)
             subprocess.Popen(['start', 'msedge', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window', 'https://sf.taobao.com/list/50025969.htm?auto_recovery=2'], shell=True)
             time.sleep(2)
             subprocess.Popen(['start', 'msedge', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window', 'https://sf.taobao.com/?auto_worker=1'], shell=True)
             print("[STARTUP] Edge launched with debug port 9222.")
        except Exception as e:
            print(f"[STARTUP] Error launching browser: {e}")

# Check on import/startup
threading.Thread(target=check_and_launch_browser, daemon=True).start()

# --- Initialize JobManager (replaces old LocationManager + SniffTaskManager) ---

JOBS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jobs")

job_manager = JobManager(JOBS_DIR)







def submit_task(file_path):
    """
    Thread-safe task submission helper.
    Ensures we don't submit the same file twice.
    """
    with DATA_LOCK:
        if file_path in CURRENT_PROCESSING:
            return
        CURRENT_PROCESSING.add(file_path)
    
    try:
        # Submit to global executor
        future = executor.submit(process_single_file, file_path)
        # Ensure cleanup
        future.add_done_callback(lambda f: CURRENT_PROCESSING.discard(file_path))
    except Exception as e:
        print(f"Failed to submit task {file_path}: {e}")
        CURRENT_PROCESSING.discard(file_path)



def get_data_path(date_str_or_obj):
    """
    Helper to get the correct archive path: datas/archive/YYYY/YYYY-MM-DD.json
    """
    if isinstance(date_str_or_obj, str):
        try:
            dt = datetime.datetime.strptime(date_str_or_obj[:10], "%Y-%m-%d")
        except:
            dt = datetime.datetime.now()
    elif isinstance(date_str_or_obj, datetime.date) or isinstance(date_str_or_obj, datetime.datetime):
        dt = date_str_or_obj
    else:
        dt = datetime.datetime.now()
        
    year = dt.strftime("%Y")
    filename = f"{dt.strftime('%Y-%m-%d')}.json"
    
    archive_dir = os.path.join(DATA_DIR, "archive", year)
    if not os.path.exists(archive_dir):
        os.makedirs(archive_dir)
        
    return os.path.join(archive_dir, filename)


def load_data():
    """Load all json files from datas/ directory (and archives) into memory index"""
    global SEEN_IDS, PENDING_TASKS
    SEEN_IDS = {}
    PENDING_TASKS = []
    
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
    print("Loading data...")
    
    # 1. Scan root JSONs (priority config, current files)
    try:
        root_files = glob.glob(os.path.join(DATA_DIR, '*.json'))
    except:
        root_files = []

    # 2. Scan Archive JSONs (Recursive)
    try:
        archive_pattern = os.path.join(DATA_DIR, 'archive', '**', '*.json')
        archive_files = glob.glob(archive_pattern, recursive=True)
    except:
        archive_files = []
        
    files = root_files + archive_files

    # Skip non-data json files (config files, progress files, etc.)
    skip_files = [
        "all_locations.json", "sniff_queue", "sniff_status", "sniff_history", "sniff_done",
        "manual_priority_locations.json", "sniff_progress.json", "collected_locations.json",
        "model_config.json", "tuning_history.json", "seen_ids.json"
    ]
    # Filter by basename to be safe with paths
    files = [f for f in files if not any(skip in os.path.basename(f) for skip in skip_files)]
    
    print(f"Loading data from {len(files)} files...")
    
    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                
            items = []
            if isinstance(content, list):
                items = content
            elif isinstance(content, dict):
                items = [content]

            for item in items:
                item_id = str(item.get("id"))
                if not item_id:
                    continue
                    
                with DATA_LOCK:
                    SEEN_IDS[item_id] = {
                        "file_path": file_path,
                        "data": item
                    }
                    
                    is_done = item.get("status") in ["done", "成交", "failure", "failed_timeout"] or item.get("是否成交") is True
                    is_processed = item.get("is_processed", False)
                    
                    # QUEUE LOGIC: If it's a valid item (done/failed) AND not processed, queue it.
                    if is_done and not is_processed:
                        PENDING_TASKS.append(item_id)
        except Exception as e:
            # print(f"Error loading {file_path}: {e}")
            pass
            
    print(f"Loaded {len(SEEN_IDS)} items. {len(PENDING_TASKS)} pending detail tasks.")

# Initial load
def cleanup_orphaned_files():
    """Rename *.processing and *.processing.failed files back to original"""
    failed_orphans = glob.glob(os.path.join(DATA_DIR, "*.processing.failed"))
    for p in failed_orphans:
        original_base = p.replace(".processing.failed", "")
        try:
             os.rename(p, original_base)
             with open(original_base + ".failed", "w") as f: f.write("recovered")
        except Exception as e:
             print(f"Failed to reset {p}: {e}")

    
    # Optimized: Skip aggressive .failed file cleanup on every startup
    # failed_items = glob.glob(os.path.join(DATA_DIR, "item-*.html.failed")) + glob.glob(os.path.join(DATA_DIR, "item-*.txt.failed"))
    # if failed_items:
    #     print(f"Found {len(failed_items)} failed marker files (item-*.failed). Cleaning up...")
    #     for p in failed_items:
    #         try:
    #             os.remove(p)
    #         except Exception as e:
    #             print(f"Failed to remove {p}: {e}")

    orphans = glob.glob(os.path.join(DATA_DIR, "*.processing"))
    if orphans:
        print(f"Found {len(orphans)} orphaned processing files. Resetting...")
        for p in orphans:
            original = p.replace(".processing", "")
            try:
                os.rename(p, original)
            except Exception as e:
                print(f"Failed to reset {p}: {e}")

cleanup_orphaned_files()
load_data()

def update_file_global(file_path, item_id, new_data):
    try:
        with FILE_LOCK:
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    all_data = json.load(f)
                
                updated = False
                for i, item in enumerate(all_data):
                    if str(item.get("id")) == item_id:
                        all_data[i] = new_data
                        updated = True
                        break
                
                if updated:
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(all_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"File write error (global): {e}")

def process_single_file(file_path):
    filename = os.path.basename(file_path)
    match = re.search(r"item-(\d+)", filename)
    if not match:
        print(f"Skipping {filename}: No ID found")
        try: os.remove(file_path) 
        except: pass
        return

    item_id = match.group(1)
    
    # Use dedicated failed directory
    failed_dir = os.path.join(DATA_DIR, 'failed')
    if not os.path.exists(failed_dir):
        os.makedirs(failed_dir)
    failed_marker_path = os.path.join(failed_dir, f"item-{item_id}.html.failed")
    
    try:
        failed_once = os.path.exists(failed_marker_path)
        
        if not os.path.exists(file_path):
            print(f"File {filename} disappeared (race condition), skipping.")
            try: CURRENT_PROCESSING.remove(file_path)
            except: pass
            return

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.strip():
            print(f"Empty content for {item_id}, deleting.")
            try: os.remove(file_path)
            except: pass
            if failed_once: 
                try: os.remove(failed_marker_path)
                except: pass
            return

        # 1. AI Extraction
        print(f"Processing {item_id}...")
        json_str = llm_helper.extract_auction_data(content, item_id=item_id)
        
        if json_str:
            print(f"\033[92m[AI SUCCESS] {item_id}: {json_str[:200]}...\033[0m")
        
        if not json_str:
            raise ValueError("Empty response from AI")
        
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        new_data = json.loads(json_str)
        
        if not isinstance(new_data, dict):
                raise ValueError("AI did not return a dictionary")

        found_id = new_data.get("id") or new_data.get("ID") or new_data.get("唯一id")
        if not found_id:
            raise ValueError("AI response missing 'id'/'ID'/'唯一id' field")
        
        if "id" not in new_data:
            new_data["id"] = found_id

        # Determine target path
        original_record = SEEN_IDS.get(str(item_id))
        target_json_path = None
        if original_record:
            target_json_path = original_record["file_path"]
        else:
            date_str = new_data.get("auction_date", "")
            if date_str:
                try:
                    target_json_path = get_data_path(date_str)
                except:
                   target_json_path = get_data_path(datetime.datetime.now())
            else:
                target_json_path = get_data_path(datetime.datetime.now())

        # 3. Success Check: Only keep 'done' items
        # 3. Success Check: Only keep 'done' items
        status = str(new_data.get("status", "")).lower()
        is_sold = new_data.get("是否成交")
        is_done = (status in ["done", "成交", "ended", "finished", "结束"]) or (is_sold is True) or (str(new_data.get("outcome", "")).lower() in ["成交", "success", "successful"])
        
        if not is_done:
            print(f"\033[93mAI identified item {item_id} as NOT DONE. REMOVING from database.\033[0m")
            remove_item_from_json(target_json_path, str(item_id))
            with DATA_LOCK:
                if str(item_id) in SEEN_IDS:
                    del SEEN_IDS[str(item_id)]
                if str(item_id) in PENDING_TASKS:
                    PENDING_TASKS.remove(str(item_id))
        else:
            # --- NEW: Area Retry Logic ---
            # Check if 建设面积/建筑面积 is empty (0, None, null, or missing)
            area_value = new_data.get("建筑面积") or new_data.get("建设面积")
            area_is_empty = area_value is None or area_value == 0 or area_value == "0" or area_value == ""
            
            # Use dedicated retry directory
            retry_dir = os.path.join(DATA_DIR, 'retry')
            if not os.path.exists(retry_dir): os.makedirs(retry_dir)
            retry_marker_path = os.path.join(retry_dir, f"item-{item_id}.html.retry")
            
            is_retry_attempt = os.path.exists(retry_marker_path)
            
            if area_is_empty and not is_retry_attempt:
                # First attempt with empty area: Requeue for retry
                print(f"\033[93m[AREA RETRY] {item_id}: 建筑面积为空, 将重新入队重试一次...\033[0m")
                # Create retry marker
                try:
                    with open(retry_marker_path, "w") as f:
                        f.write(f"Retry scheduled at {datetime.datetime.now().isoformat()}")
                except: pass
                # Re-add to PENDING_TASKS for re-dispatch
                with DATA_LOCK:
                    if str(item_id) not in PENDING_TASKS:
                        PENDING_TASKS.append(str(item_id))
                # DELETE the HTML file so frontend will re-fetch the page
                try: 
                    os.remove(file_path)
                    # Also remove from html dir if exists there (duplicate case)
                    html_name = f"item-{item_id}.html"
                    html_path = os.path.join(DATA_DIR, 'html', html_name)
                    if os.path.exists(html_path):
                        os.remove(html_path)
                except: pass
                return
            
            if area_is_empty and is_retry_attempt:
                print(f"\033[93m[AREA RETRY] {item_id}: 第二次仍为空, 按原逻辑继续处理...\033[0m")
                # Clean up retry marker
                try: os.remove(retry_marker_path)
                except: pass
            
            # 4. Success: Update Data
            new_data["detail_captured"] = True
            new_data["is_processed"] = True
            new_data["id"] = int(item_id) if item_id.isdigit() else item_id
            
            update_item_in_json(target_json_path, str(item_id), new_data)
            
            # Sync memory
            with DATA_LOCK:
                SEEN_IDS[str(item_id)] = {
                    "file_path": target_json_path,
                    "data": new_data
                }
                if str(item_id) in PENDING_TASKS:
                    PENDING_TASKS.remove(str(item_id))

            # Quality Check for Color Coding
            q_color = "\033[92m" # Green by default
            
            # Critical Missing (Red)
            if not new_data.get("id"):
                q_color = "\033[91m"
            
            # Important Missing (Yellow)
            elif (not new_data.get("建筑面积") or 
                  not new_data.get("所属小区") or 
                  not new_data.get("单价")):
                q_color = "\033[93m"
            
            print(f"{q_color}Success {item_id}: Saved to {target_json_path} (Area: {new_data.get('建筑面积')}, Comm: {new_data.get('所属小区')}, Price: {new_data.get('单价')})\033[0m")
        
        try: os.remove(file_path)
        except: pass
        
        # Also clean up processing marker which might be in new or old location
        try: 
            if failed_once: os.remove(failed_marker_path)
        except: pass
        
        # Clean up processing markers
        html_name = f"item-{item_id}.html"
        p_new = os.path.join(DATA_DIR, 'html', html_name + ".processing")
        p_old = os.path.join(DATA_DIR, html_name + ".processing")
        
        try:
            if os.path.exists(p_new): os.remove(p_new)
            if os.path.exists(p_old): os.remove(p_old)
        except: pass

    except Exception as e:
        print(f"\033[91mError processing {item_id}: {e}\033[0m") 
        failed_once = os.path.exists(failed_marker_path)
        
        if failed_once:
            print(f"Second failure for {item_id}. Deleting file to avoid deadlock.")
            try: os.remove(file_path)
            except: pass
            try: os.remove(failed_marker_path)
            except: pass
        else:
            print(f"First failure for {item_id}. Marking as failed.")
            try:
                with open(failed_marker_path, "w") as f:
                    f.write(str(e))
            except: pass
            
    finally:
        try: CURRENT_PROCESSING.remove(file_path)
        except: pass

def update_item_in_json(file_path, item_id, new_data):
    """Helper to update a specific item in a JSON file, or append if new."""
    with FILE_LOCK:
        data_list = []
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data_list = json.load(f)
            except:
                data_list = []
        
        updated = False
        for i, item in enumerate(data_list):
            if str(item.get("id")) == item_id:
                data_list[i] = new_data
                updated = True
                break
        
        if not updated:
            data_list.append(new_data)
            
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data_list, f, ensure_ascii=False, indent=4)

def remove_item_from_json(file_path, item_id):
    """Helper to remove a specific item from a JSON file."""
    if not file_path or not os.path.exists(file_path):
        return
    with FILE_LOCK:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data_list = json.load(f)
            
            new_list = [item for item in data_list if str(item.get("id")) != item_id]
            
            if len(new_list) < len(data_list):
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(new_list, f, ensure_ascii=False, indent=4)
                print(f"Removed item {item_id} from {file_path}")
        except Exception as e:
            print(f"Error removing item {item_id}: {e}")

def background_file_processor():
    """
    Periodically checks for item-*.txt AND item-*.html files and processes them.
    Uses global `executor` to limit total concurrency.
    """
    print("Background AI Processor Started (using global executor).")
    
    while True:
        try:
            txt_files = glob.glob(os.path.join(DATA_DIR, "item-*.txt"))
            
            # Scan new html directory + root (legacy)
            html_files = glob.glob(os.path.join(DATA_DIR, 'html', 'item-*.html'))
            html_files += glob.glob(os.path.join(DATA_DIR, "item-*.html"))
            
            files = txt_files + html_files
            
            # Simple check to avoid scan overhead if nothing is there
            if not files:
                time.sleep(1)
                continue

            # Submit tasks
            submitted_count = 0
            for f_path in files:
                # Fast check before lock
                if f_path in CURRENT_PROCESSING:
                    continue
                    
                submit_task(f_path)
                submitted_count += 1
            
            if submitted_count > 0:
                print(f"Background scanner submitted {submitted_count} new tasks.")
                
            time.sleep(1) # Check every second
                
        except Exception as outer_e:
            print(f"Background Loop Error: {outer_e}")
            time.sleep(5)


# ==================== AUTO-TUNER BACKGROUND THREAD ====================
def auto_tuner_thread():
    """
    Background thread for automatic concurrency tuning.
    Runs every 5 minutes, analyzes error rates, and adjusts ModelSelector limits.
    """
    from llm_helper import model_selector, MODEL_POOL
    
    TUNING_INTERVAL = 5 * 60  # 5 minutes
    MIN_REQUESTS = 20
    ERROR_RATE_LOW = 1.0   # Below this: increase
    ERROR_RATE_HIGH = 5.0  # Above this: decrease
    MAX_LIMIT = 20
    MIN_LIMIT = 3
    STEP_SIZE = 2
    STABLE_ROUNDS = 2
    
    stable_count = {m["name"]: 0 for m in MODEL_POOL}
    is_stable = False
    
    print("[AUTO-TUNER] Started (5-minute intervals)")
    
    while True:
        time.sleep(TUNING_INTERVAL)
        
        if is_stable:
            # Already stable, just monitor
            continue
        
        try:
            stats = model_selector.get_stats()
            all_stable = True
            
            print(f"\n[AUTO-TUNER] Analysis @ {time.strftime('%H:%M:%S')}")
            
            for name, s in stats.items():
                current_limit = model_selector.limits.get(name, 5)
                total = s["success"] + s["error"]
                
                if total < MIN_REQUESTS:
                    print(f"  [{name}] Requests {total} < {MIN_REQUESTS}, skipping")
                    continue
                
                error_rate = (s["concurrency_error"] / total * 100) if total > 0 else 0
                
                if error_rate < ERROR_RATE_LOW and current_limit < MAX_LIMIT:
                    new_limit = min(current_limit + STEP_SIZE, MAX_LIMIT)
                    print(f"  [{name}] Error {error_rate:.1f}% < {ERROR_RATE_LOW}% → {current_limit} → {new_limit}")
                    model_selector.update_limit(name, new_limit)
                    stable_count[name] = 0
                    all_stable = False
                elif error_rate > ERROR_RATE_HIGH and current_limit > MIN_LIMIT:
                    new_limit = max(current_limit - STEP_SIZE, MIN_LIMIT)
                    print(f"  [{name}] Error {error_rate:.1f}% > {ERROR_RATE_HIGH}% → {current_limit} → {new_limit}")
                    model_selector.update_limit(name, new_limit)
                    stable_count[name] = 0
                    all_stable = False
                else:
                    print(f"  [{name}] Error {error_rate:.1f}% OK, keeping {current_limit}")
                    stable_count[name] += 1
            
            # Reset stats for next round
            with model_selector.stats_lock:
                for name in model_selector.stats:
                    model_selector.stats[name] = {"success": 0, "error": 0, "concurrency_error": 0, "active": model_selector.stats[name]["active"]}
            
            # Check stability
            if min(stable_count.values()) >= STABLE_ROUNDS:
                is_stable = True
                print(f"[AUTO-TUNER] ✅ Stable! Final config: {model_selector.limits}")
                
        except Exception as e:
            print(f"[AUTO-TUNER] Error: {e}")

class DataHandler(http.server.SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
        LAST_REQUEST_TIME = time.time()  # Update watchdog timer
        
        if self.path == '/api/status':
            with DATA_LOCK:
                total_ids = len(SEEN_IDS)
                # Captured IDs = (Has raw file in DATA_DIR) UNION (Already finalized in memory/JSON)
                captured_ids = set()
                
                # 1. Add IDs currently in final storage
                for tid, entry in SEEN_IDS.items():
                    if entry.get("data", {}).get("is_processed"):
                        captured_ids.add(tid)
                
                ai_finalized_count = len(captured_ids)

                # 2. Add IDs currently in raw file form
                for f in os.listdir(DATA_DIR):
                    if f.startswith("item-") and (f.endswith(".txt") or f.endswith(".html")):
                        m = re.search(r"item-(\d+)", f)
                        if m: captured_ids.add(m.group(1))
                
                captured_count = len(captured_ids)

                # Next Batch Preview (IDs that are known but NOT yet finalized by AI)
                next_batch = []
                now = datetime.datetime.now()
                # Sort PENDING_TASKS to show something consistent or just first 10
                for tid in PENDING_TASKS[:100]: # Check first 100 for dispatchable ones
                    if len(next_batch) >= 10: break
                    last_time = DISPATCHED_TASKS.get(tid)
                    if not last_time or (now - last_time).total_seconds() >= DISPATCH_COOLDOWN_SECONDS:
                        next_batch.append(tid)

            # Task Queue Status (Sniffing)
            status_info = job_manager.get_status()

            self.send_json({
                "paused": PAUSED,
                "total_ids": total_ids,
                "captured_count": captured_count,
                "ai_finalized_count": ai_finalized_count,
                "sniff_queue_count": status_info.get("pending_locations", 0),
                "sniff_done_count": status_info.get("done_locations", 0),
                "next_batch_preview": next_batch
            })

        # --- Single Task Dispatch for Detail Helper (Auto Fix) ---
        elif self.path == '/api/next_task':
            now = datetime.datetime.now()
            next_task = None
            
            # Find first valid pending task
            with DATA_LOCK:
                # Cleanup PENDING_TASKS first (remove processed)
                PENDING_TASKS[:] = [tid for tid in PENDING_TASKS 
                                  if tid in SEEN_IDS and not SEEN_IDS[tid].get("data", {}).get("is_processed")]
                
                check_candidates = list(PENDING_TASKS) # Copy to avoid mutation issues during iteration
                
                for tid in check_candidates:
                    # Check dispatch throttle
                    last_time = DISPATCHED_TASKS.get(tid)
                    if last_time and (now - last_time).total_seconds() < DISPATCH_COOLDOWN_SECONDS:
                        continue
                        
                    if tid in SEEN_IDS:
                        item = SEEN_IDS[tid]["data"]
                        next_task = {"url": item.get("url")}
                        DISPATCHED_TASKS[tid] = now
                        break
            
            if next_task:
                self.send_json(next_task)
            else:
                self.send_json({}) # Empty object means no task

        # --- Get Item Data (for Detail Helper) ---
        elif self.path.startswith('/api/get_item'):
            query = urlparse(self.path).query
            params = parse_qs(query)
            item_id = params.get('id', [''])[0]
            
            if item_id and item_id in SEEN_IDS:
                self.send_json(SEEN_IDS[item_id]["data"])
            else:
                self.send_json({})

        # --- Sniffing API (legacy endpoint removed, use /api/get_or_create_sniff_task) ---
        
        elif self.path.startswith('/api/get_or_create_sniff_task'):
            # Smart task assignment using JobManager: resume in_progress or generate from priority
            parsed_url = urlparse(self.path)
            params = parse_qs(parsed_url.query)
            session_id = params.get('session_id', ['default'])[0]
            
            if PAUSED:
                self.send_json({"task": None, "message": "Paused (Captcha)"})
                return
            
            # Use new JobManager for smart task assignment
            task = job_manager.get_next_job(session_id)
            if task:
                self.send_json({
                    "task": task,
                    "location": {"code": task.get("location_code"), "name": task.get("location_code")},
                    "is_resume": task.get("is_resume", False),
                    "message": task.get("desc", "Task assigned")
                })
            else:
                self.send_json({
                    "task": None,
                    "message": "所有嗅探任务已完成"
                })
        
        elif self.path == '/api/get_tasks':
            if PAUSED:
                self.send_json({"tasks": []})
                return

            # Dynamic Batch Size (increased to saturate 10 tabs or high concurrency)
            batch_size = 300 
            tasks = []
            now = datetime.datetime.now()
            
            # Use a copy to iterate safely
            # CLEANUP: Remove finished tasks from PENDING list
            active_pending = []
            
            for tid in list(PENDING_TASKS): 
                if tid in SEEN_IDS:
                    item = SEEN_IDS[tid].get("data")
                    # If marked processed (saved), it's DONE. Remove from pending.
                    if item and item.get("is_processed"):
                         continue
                
                active_pending.append(tid)

            # Update global pending list with cleaned version
            PENDING_TASKS[:] = active_pending 
            
            pending_count = len(PENDING_TASKS)
            total_count = len(SEEN_IDS)
            done_count = total_count - pending_count
            
            print(f"[DEBUG] /get_tasks: PENDING={pending_count}, TOTAL={total_count}, DONE={done_count}")

            candidates = []
            skipped_cooldown = 0
            for tid in PENDING_TASKS:
                last_time = DISPATCHED_TASKS.get(tid)
                if last_time:
                    # Retry after configured cooldown silence window
                    if (now - last_time).total_seconds() < DISPATCH_COOLDOWN_SECONDS:
                        skipped_cooldown += 1
                        continue
                candidates.append(tid)
            
            print(f"[DEBUG] Candidates after cooldown filter: {len(candidates)} (Skipped {skipped_cooldown} due to cooldown)")

            for item_id in candidates[:batch_size]:
                if item_id in SEEN_IDS:
                    item = SEEN_IDS[item_id]["data"]
                    # Double check process status
                    if item.get("is_processed"):
                        continue
                        
                    tasks.append({
                        "id": item_id,
                        "url": item.get("url")
                    })
                    DISPATCHED_TASKS[item_id] = now
            
            self.send_json({
                "tasks": tasks,
                "total": total_count,
                "done": done_count
            })
            if len(tasks) > 0:
                print(f"Dispatched {len(tasks)} tasks (Batch Limit: {batch_size}). Pending: {pending_count}")
            else:
                print(f"[DEBUG] Returned 0 tasks. Candidates={len(candidates)}")
            
        elif self.path == '/api/resume':
            PAUSED = False
            # Clear emergency flag if it exists
            flag_path = os.path.join(DATA_DIR, 'force_unlock.flag')
            if os.path.exists(flag_path):
                try: os.remove(flag_path)
                except: pass
            print("System RESUMED (via API).")
            self.send_json({"status": "resumed"})
            
        else:
            self.send_response(404)
            self.end_headers()
            
    def do_POST(self):
        global PAUSED, LAST_REQUEST_TIME
        LAST_REQUEST_TIME = time.time()  # Update watchdog timer
        
        # --- Sniffing API (POST to add next pages) ---
        if self.path == '/api/report_sniff_status':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                url = data.get("url")
                has_next = data.get("has_next", True)
                is_empty = data.get("is_empty", False)
                page_num = data.get("page_num", 1)
                total_pages = data.get("total_pages")
                zero_bid_detected = data.get("zero_bid_detected", False)
                
                log_msg = f"[SNIFF REPORT] Page {page_num} | Next: {has_next} | Empty: {is_empty} | TotalPages: {total_pages}"
                if zero_bid_detected:
                    log_msg += " | [ZERO-BID EARLY TERMINATION]"
                print(log_msg + f" | URL: {url}")
                
                if url:
                    job_manager.update_progress(url, page_num, has_next=has_next, max_page=int(total_pages) if total_pages else None, zero_bid_detected=zero_bid_detected)
                    self.send_json({"status": "ok"})
                else:
                    self.send_error(400, "Missing URL")
            except Exception as e:
                 print(f"Error in report_sniff_status: {e}")
                 self.send_error(500)



        elif self.path == '/api/save_locations':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                new_locations = data.get("locations", [])
                
                loc_file = os.path.join(DATA_DIR, "collected_locations.json")
                existing_locs = {}
                
                if os.path.exists(loc_file):
                    try:
                        with open(loc_file, "r", encoding="utf-8") as f:
                            existing_locs = {item['code']: item['name'] for item in json.load(f)}
                    except: pass
                
                updated = False
                for loc in new_locations:
                    code = str(loc.get('code'))
                    name = loc.get('name')
                    if code and name:
                        if code not in existing_locs:
                            existing_locs[code] = name
                            updated = True
                
                if updated:
                    # Convert back to list
                    final_list = [{"code": k, "name": v} for k, v in existing_locs.items()]
                    with open(loc_file, "w", encoding="utf-8") as f:
                        json.dump(final_list, f, ensure_ascii=False, indent=2)
                    print(f"Saved {len(new_locations)} locations. Total unique: {len(final_list)}")
                
                self.send_json({"status": "ok", "count": len(new_locations)})
            except Exception as e:
                print(f"Error saving locations: {e}")
                self.send_error(500)

        elif self.path == '/api/area_result':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                item_id = str(data.get("id"))
                
                if item_id and item_id in SEEN_IDS:
                    # Update in-memory data
                    with DATA_LOCK:
                        item_entry = SEEN_IDS[item_id]
                        current_data = item_entry["data"]
                        # Merge new fields
                        current_data.update(data)
                        current_data["is_processed"] = True # Mark as processed
                        
                        # Remove from pending tasks
                        if item_id in PENDING_TASKS:
                            PENDING_TASKS.remove(item_id)
                            
                    # Save to file
                    file_path = item_entry["file_path"]
                    self.update_file(file_path, item_id, current_data)
                    
                    print(f"[AREA RESULT] Updated {item_id} | Area: {data.get('建筑面积', 0)}")
                    self.send_json({"status": "ok"})
                else:
                    print(f"[AREA RESULT] Item {item_id} not found in index")
                    self.send_error(404, "Item not found")
            except Exception as e:
                print(f"Error processing area result: {e}")
                self.send_error(500)

        elif self.path == '/api/infer_location':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                address = data.get("address", "")
                title = data.get("title", "")
                
                print(f"[Infer Location] Request for: {address} | {title}")
                
                prompt = f"""
# Task
根据提供的房产地址和标题，推断该房产的详细位置信息。
请基于贝壳/链家等房产数据库的标准名称。

# Input
地址: {address}
标题: {title}

# Output JSON
{{
    "所属小区": "小区名称",
    "最靠近商圈": "商圈名称",
    "省份": "省",
    "城市": "市",
    "区": "区"
}}
如果某个字段无法推断，请填 null. 仅返回 JSON对象，不要包含 ```json 标记。
"""
                try:
                    # Invoke LLM (GLM-4.7)
                    resp = llm_helper.chat_with_glm(prompt)
                    
                    # Clean response
                    if "```json" in resp:
                        resp = resp.split("```json")[1].split("```")[0]
                    elif "```" in resp:
                        resp = resp.split("```")[1].split("```")[0]
                    
                    result = json.loads(resp.strip())
                    self.send_json(result)
                except Exception as e:
                    print(f"Error calling LLM: {e}")
                    self.send_json({})
                    
            except Exception as e:
                print(f"Error in infer_location: {e}")
                self.send_error(500)

        elif self.path == '/api/approve_area':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                item_id = str(data.get("id"))
                
                if item_id and item_id in SEEN_IDS:
                    with DATA_LOCK:
                        item_entry = SEEN_IDS[item_id]
                        current_data = item_entry["data"]
                        current_data.update(data)
                        current_data["is_processed"] = True
                        current_data["status"] = "done" # Mark done manually
                        
                        if item_id in PENDING_TASKS:
                            PENDING_TASKS.remove(item_id)
                            
                    # Save to file
                    file_path = item_entry["file_path"]
                    self.update_file(file_path, item_id, current_data)
                    
                    print(f"[APPROVE AREA] Manually Approved {item_id} | Area: {data.get('建筑面积', 0)}")
                    self.send_json({"status": "ok"})
                else:
                    # Treat as new override if ID provided but not found? 
                    # For now just error or create new entry if we want to support manual add
                    print(f"[APPROVE AREA] Item {item_id} not found in index")
                    self.send_error(404, "Item not found")
            except Exception as e:
                print(f"Error processing area approval: {e}")
                self.send_error(500)

        elif self.path == '/api/save':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                items = data.get("items", [])
                
                new_count = 0
                items_by_date = {}
                
                for item in items:
                    item_id = str(item.get("id"))
                    status = str(item.get("status", "")).lower()
                    is_sold = item.get("是否成交")
                    
                    # --- FILTER: Only allow 'done' status ---
                    is_done = (status in ["done", "成交"]) or (is_sold is True) or (str(item.get("outcome", "")).lower() == "成交")
                    
                    if not is_done:
                        # print(f"Skipping save for {item_id}: Not done")
                        continue
                    

                    if item_id in SEEN_IDS:
                        print(f"[SNIFF ITEM] [EXISTING] Scanned: {item.get('title', 'Unknown')} | ID: {item_id}")
                        # Update existing item data if needed, but for now we just log
                        # Note: We continue to process it to update status/details if changed
                    else:
                        print(f"[SNIFF ITEM] [NEW] Found: {item.get('title', 'Unknown')} | Status: {status} | URL: {item.get('url')}")

                    if item_id not in SEEN_IDS:
                        a_date = item.get("auction_date", "").split(" ")[0] or "unknown"
                        if a_date not in items_by_date: items_by_date[a_date] = []
                        
                        # Store ID, URL, and End Timestamp for external processor
                        minimal_item = {
                            "id": item_id, 
                            "url": item.get("url"),
                            "end": item.get("end"),
                            "status": "done",      # Explicitly set for Worker queuing
                            "is_processed": False  # Explicitly set for Worker queuing
                        }
                        items_by_date[a_date].append(minimal_item)
                        
                        file_path = get_data_path(a_date)
                        with DATA_LOCK:
                            SEEN_IDS[item_id] = {
                                "file_path": file_path,
                                "data": minimal_item,
                                "status": item.get("status")
                            }
                            # --- RESTORED: Queue for Processing ---
                            if not item.get("is_processed"):
                                if item_id not in PENDING_TASKS:
                                    PENDING_TASKS.append(item_id)
                        
                        new_count += 1
                
                for date_str, date_items in items_by_date.items():
                    file_path = get_data_path(date_str)
                    current_file_data = []
                    if os.path.exists(file_path):
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                current_file_data = json.load(f)
                        except: pass
                    current_file_data.extend(date_items)
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(current_file_data, f, ensure_ascii=False, indent=4)
                        
                self.send_json({"status": "ok", "new": new_count})
                
            except Exception as e:
                print(f"Error processing save: {e}")
                self.send_error(500, str(e))

        elif self.path == '/api/report_captcha':
            print("CAPTCHA REPORTED! Triggering Solver...")
            
            # Using ThreadPool to avoid blocking the server main loop
            executor.submit(self.run_solver)
            
            self.send_json({"status": "solving"})



        elif self.path == '/api/log':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                msg = data.get("msg", "")
                is_error = data.get("isError", False)
                prefix = "[Client Error]" if is_error else "[Client Log]"
                print(f"{prefix} {msg}")
                self.send_json({"status": "ok"})
            except:
                self.send_error(400)
        
        elif self.path.startswith('/api/upload'):
            try:
                query = urlparse(self.path).query
                params = parse_qs(query)
                item_id = params.get('id', [''])[0]
                filename = params.get('name', [''])[0]
                
                if not item_id or not filename:
                    self.send_error(400, "Missing id or name")
                    return
                
                filename = unquote(filename)
                filename = filename.replace("\\", "")
                
                save_dir = os.path.join(DATA_DIR, "downloads", item_id)
                os.makedirs(save_dir, exist_ok=True)
                
                file_path = os.path.join(save_dir, filename)
                
                content_length = int(self.headers['Content-Length'])
                file_data = self.rfile.read(content_length)
                
                with open(file_path, "wb") as f:
                    f.write(file_data)
                
                print(f"Saved file: {filename} ({content_length} bytes)")
                self.send_json({"status": "saved"})
                
            except Exception as e:
                print(f"Upload failed: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))

        elif self.path == '/api/update_item':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                item_id = str(data.get("id"))
                
                if item_id in SEEN_IDS:
                    entry = SEEN_IDS[item_id]
                    if data.get("status") == "failed_timeout":
                         print(f"Item {item_id} TIMED OUT.")
                         if item_id in PENDING_TASKS: PENDING_TASKS.remove(item_id)
                    else:
                        entry["data"].update(data)
                        if item_id in PENDING_TASKS: PENDING_TASKS.remove(item_id)
                        update_file_global(entry["file_path"], item_id, entry["data"])
                    self.send_json({"status": "updated"})
                else:
                    self.send_json({"status": "id_not_found"})
            except Exception as e:
                self.send_error(500, str(e))

        elif self.path == '/api/get_next_task':
            target_id = None
            target_url = None
            now = datetime.datetime.now()
            
            for item_id, entry in SEEN_IDS.items():
                data = entry.get("data", {})
                
                if not data.get("is_processed") and data.get("url"):
                    # Check HTML paths (Unified structure)
                    html_name = f"item-{item_id}.html"
                    
                    # 1. Check New Location
                    html_path = os.path.join(DATA_DIR, 'html', html_name)
                    
                    # 2. Check Retry Location
                    retry_path = os.path.join(DATA_DIR, 'retry', html_name + '.retry')
                    
                    # 3. Check Legacy Root (fallback)
                    legacy_html = os.path.join(DATA_DIR, html_name)
                    
                    # Txt file logic mostly deprecated but check for legacy
                    txt_path = os.path.join(DATA_DIR, f"item-{item_id}.txt")
                    
                    p_html = html_path + ".processing"
                    p_legacy = legacy_html + ".processing"
                    
                    exists = (
                        os.path.exists(html_path) or 
                        os.path.exists(retry_path) or
                        os.path.exists(legacy_html) or
                        os.path.exists(txt_path) or
                        os.path.exists(p_html) or
                        os.path.exists(p_legacy)
                    )
                    
                    if exists:
                        continue
                        
                    last_time = DISPATCHED_TASKS.get(item_id)
                    if last_time and (now - last_time).total_seconds() < DISPATCH_COOLDOWN_SECONDS:
                        continue
                        
                    target_id = item_id
                    target_url = data.get("url")
                    break
            
            if target_id:
                print(f"Dispatching reprocessing task for {target_id}...")
                DISPATCHED_TASKS[target_id] = now
                self.send_json({
                    "task_type": "visit",
                    "id": target_id,
                    "url": target_url
                })
            else:
                self.send_json({"task_type": "none"})

        elif self.path == '/api/analyze_html':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                item_id = str(data.get("id"))
                html_content = data.get("html", "")
                status = data.get("status")  # NEW: Handle merged status update
                
                if item_id in SEEN_IDS:
                    # Save to html subdirectory
                    html_dir = os.path.join(DATA_DIR, 'html')
                    if not os.path.exists(html_dir): os.makedirs(html_dir)
                    html_path = os.path.join(html_dir, f"item-{item_id}.html")
                    
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(html_content)
                    print(f"Saved HTML to {html_path}. Queued for Background AI.")
                    
                    # Handle merged status update (replaces separate /update_item call)
                    if status:
                        entry = SEEN_IDS[item_id]
                        if status == "failed_timeout":
                            print(f"Item {item_id} TIMED OUT.")
                            if item_id in PENDING_TASKS: PENDING_TASKS.remove(item_id)
                        else:
                            entry["data"]["status"] = status
                            if item_id in PENDING_TASKS: PENDING_TASKS.remove(item_id)
                    
                    # --- RESTORED AI LOGIC ---
                    submit_task(html_path)
                    
                    self.send_json({"status": "queued"})
                else:
                    self.send_json({"status": "id_not_found"})
                    
            except Exception as e:
                print(f"Error saving HTML content: {e}")
                self.send_error(500, str(e))
                
        else:
            self.send_response(404)
            self.end_headers()

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def update_file(self, file_path, item_id, new_data):
        update_file_global(file_path, item_id, new_data)
        
    def run_solver(self):
        """Run the captcha solver in background with server-level retry."""
        global PAUSED
        global SOLVER_RUNNING, SOLVER_START_TIME
        
        # Initialize if not present (hack for hot-reload or first run)
        if 'SOLVER_RUNNING' not in globals():
            SOLVER_RUNNING = False
            SOLVER_START_TIME = 0

        # Check existing lock state
        if SOLVER_RUNNING:
            elapsed = time.time() - SOLVER_START_TIME
            if elapsed < 120:  # Extended timeout for retries
                print(f"\033[93m[SOLVER] Solver already running for {int(elapsed)}s. Skipping.\033[0m")
                return
            else:
                print(f"\033[91m[SOLVER] Solver hung for {int(elapsed)}s. FORCE BREAKING LOCK.\033[0m")
        
        SERVER_MAX_ATTEMPTS = 2  # Server-level retries (solver has its own internal retries)
        
        try:
            SOLVER_RUNNING = True
            SOLVER_START_TIME = time.time()
            PAUSED = True
            print("\033[93m[SOLVER] Starting solver...\033[0m")
            
            success = False
            for server_attempt in range(SERVER_MAX_ATTEMPTS):
                if server_attempt > 0:
                    print(f"\033[93m[SOLVER] Server retry {server_attempt + 1}/{SERVER_MAX_ATTEMPTS} after delay...\033[0m")
                    time.sleep(3)
                
                success = solver.solve()
                if success:
                    break
            
            if success:
                print("\033[92m[SOLVER] ✅ Captcha Solved! Resuming system...\033[0m")
                PAUSED = False
            else:
                print("\033[91m[SOLVER] ❌ All solve attempts failed. System remains PAUSED.\033[0m")
                print("\033[91m[SOLVER] Manual intervention required. Please solve in Edge, then click 'Resume' or delete 'force_unlock.flag'.\033[0m")
                
                # Create a lock flag file for easy manual resuming via file system if API is stuck
                flag_path = os.path.join(DATA_DIR, 'force_unlock.flag')
                try:
                    with open(flag_path, 'w') as f:
                        f.write("Delete this file to force resume the queue after manual solving")
                except: pass
                
                # Wait for user to either hit API resume or delete the file
                while PAUSED:
                    if not os.path.exists(flag_path):
                        print("\033[92m[SOLVER] 🟢 Force unlock flag removed! Auto-resuming system...\033[0m")
                        PAUSED = False
                        break
                    time.sleep(2)
                
        except Exception as e:
            print(f"[SOLVER] Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            SOLVER_RUNNING = False
            elapsed = time.time() - SOLVER_START_TIME
            print(f"[SOLVER] Finished. Total time: {elapsed:.1f}s")

    def log_message(self, format, *args):
        return

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    print(f"Starting Data Receiver on port {PORT}...")
    print(f"Serving Pending Tasks from: {os.path.abspath(DATA_DIR)}")
    
    # Start the background AI processor
    import threading
    threading.Thread(target=background_file_processor, daemon=True).start()
    
    # Start the auto-tuner (adjusts concurrency limits every 5 minutes)
    threading.Thread(target=auto_tuner_thread, daemon=True).start()
    
    try:
        with ReusableTCPServer(("", PORT), DataHandler) as httpd:
            print("Server running. Press Ctrl+C to stop.")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nServer stopped by user.")
            except Exception as e:
                print(f"\nServer crashed: {e}")
                import traceback
                traceback.print_exc()
    except OSError as e:
        print(f"Error binding to port {PORT}: {e}")
