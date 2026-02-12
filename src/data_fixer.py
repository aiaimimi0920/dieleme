# -*- coding: utf-8 -*-
"""
批量面积修复工具
- HTTP 服务器接收油猴脚本发送的数据
- 滚动列表显示待审批条目
- 支持批量批准和单独批准
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import json
import os
import subprocess
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
import glob
import random
from datetime import datetime

DATAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'datas')
HTTP_PORT = 5001
AI_REQUEST_INTERVAL = 5  # seconds between AI requests

# Import AI helper for area verification
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Data Schema (Must match detail_helper.user.js)
FIELDS_SCHEMA = [
    {'key': 'id', 'label': 'ID', 'type': 'number', 'readonly': True},
    {'key': '市场评估价', 'label': '市场评估价', 'type': 'number'},
    {'key': '起拍价格', 'label': '起拍价格', 'type': 'number'},
    {'key': '成交价格', 'label': '成交价格', 'type': 'number'},
    {'key': '交易时间', 'label': '交易时间', 'type': 'text'},
    {'key': '原始网站', 'label': '原始网站', 'type': 'text', 'readonly': True},
    {'key': '是否成交', 'label': '是否成交', 'type': 'checkbox'},
    {'key': '竞拍人数', 'label': '竞拍人数', 'type': 'number'},
    {'key': '出价人数', 'label': '出价人数', 'type': 'number'},
    {'key': '地点', 'label': '地点', 'type': 'text'},
    {'key': '所属小区', 'label': '所属小区', 'type': 'text'},
    {'key': '省份', 'label': '省份', 'type': 'text'},
    {'key': '城市', 'label': '城市', 'type': 'text'},
    {'key': '区', 'label': '区', 'type': 'text'},
    {'key': '最靠近商圈', 'label': '最靠近商圈', 'type': 'text'},
    {'key': '建筑面积', 'label': '建筑面积', 'type': 'number', 'step': 0.01},
    {'key': '单价', 'label': '单价', 'type': 'number', 'readonly': True},
    {'key': 'status', 'label': '状态', 'type': 'text', 'readonly': True, 'width': 8},
    {'key': 'detail_captured', 'label': '已抓取', 'type': 'checkbox', 'readonly': True},
    {'key': 'is_processed', 'label': 'AI完毕', 'type': 'checkbox', 'readonly': True},
]

# Fields that can be inferred from "地点" (address) alone, without opening a web page
INFERABLE_FIELDS = {'所属小区', '最靠近商圈', '省份', '城市', '区'}

# Use simplified standalone AI call to avoid sharing concurrency with data_receiver
AI_AVAILABLE = False
try:
    from llm_helper import Ws_Param, MODEL_POOL, AIService
    import websocket
    import ssl
    
    def simple_ai_call(prompt, pool_idx=None, max_retries=3):
        """Standalone AI call with retry. 
        Uses random model selection to leverage high concurrency capacity."""
        import time as _time
        if not MODEL_POOL:
            return "Error: No AI models configured"
            
        # Randomly select a model to distribute load
        # If pool_idx is specifically provided (e.g. for debug), use it, otherwise random
        if pool_idx is not None and 0 <= pool_idx < len(MODEL_POOL):
            config = MODEL_POOL[pool_idx]
            idx = pool_idx
        else:
            idx = random.randint(0, len(MODEL_POOL) - 1)
            config = MODEL_POOL[idx]
            
        print(f"[AI] Using {config['name']} (pool {idx})")
        
        for attempt in range(max_retries):
            try:
                service = AIService(config)
                service.prompt = prompt
                service.final_result = ""
                
                wsParam = Ws_Param(config["app_id"], config["api_key"], config["api_secret"], config["ws_url"])
                wsUrl = wsParam.create_url()
                
                ws = websocket.WebSocketApp(wsUrl,
                                            on_message=service.on_message,
                                            on_error=service.on_error,
                                            on_close=service.on_close,
                                            on_open=service.on_open)
                ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}, ping_interval=130, ping_timeout=120)
                
                result = service.final_result
                
                # Check for API error in result
                if 'ConcurrencyOverFlow' in result or 'Error' in result[:20]:
                    wait = 10 * (2 ** attempt)  # 10s, 20s, 40s
                    print(f"[AI_RETRY] API限流，{wait}s后重试 (attempt {attempt+1}/{max_retries})")
                    _time.sleep(wait)
                    continue
                
                # Cleanup markdown if present
                if "```json" in result:
                    result = result.split("```json")[1].split("```")[0].strip()
                elif "```" in result:
                    result = result.split("```")[1].split("```")[0].strip()
                return result
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 10 * (2 ** attempt)
                    print(f"[AI_RETRY] 异常: {e}，{wait}s后重试")
                    _time.sleep(wait)
                else:
                    print(f"[AI_FAIL] 重试{max_retries}次后仍失败: {e}")
                    return ""
    
    AI_AVAILABLE = True
    print("[AI] Standalone AI call initialized (independent from data_receiver)")
except ImportError as e:
    print(f"[WARNING] AI verification disabled: {e}")

# Lightweight Tooltip for tkinter
class ToolTip:
    def __init__(self, widget, text='', wrap_length=400):
        self.widget = widget
        self.text = text
        self.wrap_length = wrap_length
        self.tip_window = None
        widget.bind('<Enter>', self._show)
        widget.bind('<Leave>', self._hide)

    def _show(self, event=None):
        if self.tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        # Keep within screen bounds
        screen_w = tw.winfo_screenwidth()
        screen_h = tw.winfo_screenheight()
        tw.wm_geometry(f'+{min(x, screen_w - self.wrap_length - 40)}+{min(y, screen_h - 300)}')
        label = tk.Label(tw, text=self.text, justify='left',
                         background='#ffffcc', foreground='#333',
                         relief='solid', borderwidth=1,
                         wraplength=self.wrap_length,
                         font=('Microsoft YaHei', 9),
                         padx=8, pady=6)
        label.pack()

    def _hide(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

    def update_text(self, text):
        self.text = text

class AreaFixerHandler(BaseHTTPRequestHandler):
    gui = None
    
    def log_message(self, format, *args):
        pass
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def do_POST(self):
        if self.path == '/api/area_result':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(body)
                if AreaFixerHandler.gui:
                    AreaFixerHandler.gui.add_item(data)
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok'}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(str(e).encode())
        elif self.path == '/api/approve_area':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(body)
                if AreaFixerHandler.gui:
                    # Run in main thread
                    AreaFixerHandler.gui.root.after(0, lambda: AreaFixerHandler.gui.approve_external(data))
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok'}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(str(e).encode())
        elif self.path == '/api/infer_location':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(body)
                address = data.get('address', '')
                title = data.get('title', '')
                
                result = {'所属小区': '', '最靠近商圈': ''}
                
                if address and AI_AVAILABLE and AreaFixerHandler.gui:
                    inferred = AreaFixerHandler.gui._infer_location_ai(address, title)
                    if inferred:
                        result.update(inferred)
                
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_GET(self):
        if self.path == '/api/next_task':
            if AreaFixerHandler.gui:
                task = AreaFixerHandler.gui.get_next_task()
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(task).encode())
            else:
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'url': None}).encode())
        else:
            self.send_response(404)
            self.end_headers()


class DataFixerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("批量数据修复工具 (面积 & 小区)")
        self.root.geometry("1150x600")
        
        self.pending_items = []
        self.display_items = []
        self.task_queue = []
        self.is_scraping = False
        self.all_selected = False
        
        self.row_widgets = []
        self.next_row_id = 0
        
        # AI verification queue
        self.ai_verify_queue = []
        self.ai_verify_running = False
        self.ai_approved_count = 0
        self.ai_rejected_count = 0
        if AI_AVAILABLE:
            threading.Thread(target=self.ai_verify_worker, daemon=True).start()
        
        self.setup_ui()
        self.scan_missing_data()
        self.start_http_server()
        
        self.root.after(500, self.check_pending_items)

    def setup_ui(self):
        # Header
        header = ttk.Frame(self.root)
        header.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(header, text="批量数据修复工具 (面积 & 小区)", font=('Arial', 14, 'bold')).pack(side='left')
        self.status_label = ttk.Label(header, text="待处理: 0 | 队列: 0")
        self.status_label.pack(side='right')
        
        # Control buttons
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill='x', padx=10, pady=5)
        
        self.start_btn = ttk.Button(control_frame, text="▶ 开始自动抓取", command=self.start_scraping)
        self.start_btn.pack(side='left', padx=5)
        
        self.pause_btn = ttk.Button(control_frame, text="⏸ 暂停抓取", command=self.pause_scraping, state='disabled')
        self.pause_btn.pack(side='left', padx=5)
        
        ttk.Button(control_frame, text="🔄 重新扫描", command=self.scan_missing_data).pack(side='left', padx=5)
        
        self.scraping_status = ttk.Label(control_frame, text="状态: 待命", foreground='gray')
        self.scraping_status.pack(side='right', padx=10)
        
        # AI stats label
        self.ai_stats_label = ttk.Label(control_frame, text="AI通过: 0", foreground='green')
        self.ai_stats_label.pack(side='right', padx=10)
        
        # Main PanedWindow
        main_paned = ttk.PanedWindow(self.root, orient='vertical')
        main_paned.pack(fill='both', expand=True, padx=10, pady=5)
        
        # Top Pane: List Container + Buttons
        top_pane = ttk.Frame(main_paned)
        main_paned.add(top_pane, weight=3)
        
        # Headers moved to scrollable_frame

        
        ttk.Separator(top_pane, orient='horizontal').pack(fill='x', pady=2)
        
        # Canvas for scrolling
        canvas_frame = ttk.Frame(top_pane)
        canvas_frame.pack(fill='both', expand=True)
        
        self.canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient='vertical', command=self.canvas.yview)
        xscrollbar = ttk.Scrollbar(canvas_frame, orient='horizontal', command=self.canvas.xview)
        
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        self.scrollable_frame.bind("<Configure>", 
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor='nw')
        self.canvas.configure(yscrollcommand=scrollbar.set, xscrollcommand=xscrollbar.set)
        
        # Mouse wheel scrolling (Vertical)
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        # Shift+Mouse wheel (Horizontal) - optional
        
        xscrollbar.pack(side='bottom', fill='x')
        self.canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Add Headers inside scrollable_frame
        self.next_row_idx = 1
        self.add_headers()
        
        button_frame = ttk.Frame(top_pane)
        button_frame.pack(fill='x', pady=5)
        
        self.select_all_btn = ttk.Button(button_frame, text="☐ 全选", command=self.toggle_select_all)
        self.select_all_btn.pack(side='right', padx=5)
        
        ttk.Button(button_frame, text="✅ 批量批准选中", command=self.batch_approve).pack(side='right', padx=5)
        ttk.Button(button_frame, text="⏭ 跳过选中", command=self.skip_selected).pack(side='right', padx=5)
        ttk.Button(button_frame, text="🗑 一键清空", command=self.clear_all).pack(side='left', padx=5)

        # Bottom Pane: Log
        log_pane = ttk.LabelFrame(main_paned, text="日志 (可拖动调整大小)")
        main_paned.add(log_pane, weight=1)
        
        self.log_text = tk.Text(log_pane, height=8, state='disabled')
        self.log_text.pack(fill='both', expand=True, padx=5, pady=5)
        
    def add_headers(self):
        # Header row 0
        col = 0
        ttk.Label(self.scrollable_frame, text="✓", width=3).grid(row=0, column=col, sticky='w', padx=1)
        col += 1
        ttk.Label(self.scrollable_frame, text="地址/标题", width=25, anchor='w').grid(row=0, column=col, sticky='w', padx=3)
        col += 1
        
        # Dynamic headers from schema
        for field in FIELDS_SCHEMA:
            if field.get('hidden'): continue
            width = field.get('width', 10)
            ttk.Label(self.scrollable_frame, text=field['label'], width=width, anchor='w').grid(row=0, column=col, sticky='w', padx=3)
            col += 1
            
        ttk.Label(self.scrollable_frame, text="上下文 / 状态", width=30, anchor='w').grid(row=0, column=col, sticky='w', padx=3)
        col += 1
        ttk.Label(self.scrollable_frame, text="操作", width=10).grid(row=0, column=col, sticky='w', padx=3)
        col += 1
        
        ttk.Separator(self.scrollable_frame, orient='horizontal').grid(row=0, column=0, columnspan=col, sticky='ew', pady=2)

    def scan_missing_data(self):
        self.task_queue = []
        
        # Scan root and archive
        root_files = glob.glob(os.path.join(DATAS_DIR, '*.json'))
        archive_files = glob.glob(os.path.join(DATAS_DIR, 'archive', '**', '*.json'), recursive=True)
        all_files = root_files + archive_files
        
        file_count = 0
        for json_file in all_files:
            file_count += 1
            if file_count % 100 == 0:
                print(f"[SCAN] Scanned {file_count}/{len(all_files)} files...")
            
            if "model_config.json" in json_file or "monitor_state.json" in json_file or "sniff_progress.json" in json_file:
                continue

            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                items = data if isinstance(data, list) else [data]
                
                for item in items:
                    # Removed is_processed check to scan ALL historic data
                    
                    # Skip if manually checked
                    if item.get('manual_checked'):
                        continue

                    # Old logic replaced by generic loop below
                    # if area_ok and comm_ok:
                    #     continue
                        
                    # Needs fix
                    url = item.get('原始网站', '')
                    if url and 'taobao.com' in url:
                        item_id = item.get('id', 'unknown')
                        location = item.get('地点', '') or item.get('所属小区', '')
                        if location:
                            title = f"[{item_id}] {location[:25]}"
                        else:
                            title = f"ID:{item_id}"
                        
                        missing_fields = []
                        # Check all fields in schema
                        for field in FIELDS_SCHEMA:
                            key = field['key']
                            # Skip allow-null fields or specialized logic if needed
                            if field.get('readonly'): continue # Skip readonly like id, url, unit price logic handled elsewhere
                            
                            is_missing = False
                            
                            # Inject source file path for offline processing
                            item['json_file'] = json_file

                            val = item.get(key)
                            is_missing = False
                            
                            if field['type'] == 'number':
                                # For numbers, 0 might be valid (e.g. start price 0?), 
                                # but usually for area/price it means missing/invalid in this context.
                                # Exception: '竞拍人数', '出价人数' can be 0.
                                if key in ['竞拍人数', '出价人数']:
                                    if val is None or val == "": is_missing = True
                                elif key in ['单价']: # Auto-calc, ignore
                                    pass
                                else:
                                    if not val or float(val) == 0: is_missing = True
                                    
                            elif field['type'] == 'checkbox':
                                 # boolean false is valid, so check for None
                                 if val is None: is_missing = True
                                 
                            else: # text
                                if not val or val == "null" or val == "":
                                    is_missing = True
                            
                            if is_missing:
                                missing_fields.append(field['label'])

                        # If no missing fields, skip
                        if not missing_fields:
                            continue
                        
                        # --- Smart Routing: AI-inferable vs Scrape-required ---
                        inferable_missing = [f for f in missing_fields if f in INFERABLE_FIELDS]
                        scrape_missing = [f for f in missing_fields if f not in INFERABLE_FIELDS]
                        
                        # If has inferable missing fields AND has address -> queue for AI
                        if inferable_missing and item.get('地点'):
                            self.queue_for_ai_verification(item, row_id=None, priority=False)
                        
                        # Only add to scraper queue if there are fields that REQUIRE web scraping
                        if scrape_missing:
                            self.task_queue.append({
                                'url': url,
                                'title': title[:40],
                                'id': item_id,
                                'json_file': json_file,
                                'missing': missing_fields,
                                'dataset_item': item
                            })
            except:
                pass
        
        ai_queue_count = len(self.ai_verify_queue)
        scrape_count = len(self.task_queue)
        self.log(f"扫描完成：AI推断队列 {ai_queue_count} 条 | 爬虫队列 {scrape_count} 条")
        print(f"[SCAN] Found {len(all_files)} files. AI infer queue: {ai_queue_count}, Scraper queue: {scrape_count}")
        if scrape_count == 0:
            print("[SCAN] WARNING: Scraper queue is empty. Check if data is already complete or paths are correct.")
        self.update_status()

    def log(self, msg):
        def _log():
            try:
                self.log_text.config(state='normal')
                self.log_text.insert('end', f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
                self.log_text.see('end')
                self.log_text.config(state='disabled')
            except:
                pass
        self.root.after(0, _log)
    
    def get_next_task(self):
        if not self.is_scraping:
            return {'url': None, 'paused': True}
        
        while self.task_queue:
            # Random selection instead of sequential
            task = random.choice(self.task_queue)
            
            # Check if task is still needed (e.g. fixed by background AI)
            item = task.get('dataset_item')
            needed = True
            if item:
                needed = False
                for m in task.get('missing', []):
                    if m in INFERABLE_FIELDS:
                        # Check if inferable field is still empty
                        val = item.get(m)
                        if not val or str(val).lower() in ['none', 'null', '']: needed = True
                    else:
                        # Non-inferable field (price, area, etc.): always needs scraping
                        needed = True
            
            if not needed:
                 # self.log(f"[跳过] 已由后台修复: {task.get('title')[:10]}...")
                 self.task_queue.remove(task)
                 self.root.after(0, self.update_status)
                 continue

            self.task_queue.remove(task)
            self.root.after(0, self.update_status)
            return task
        return {'url': None}
    
    def add_item(self, data):
        """Add item from userscript (thread-safe)"""
        # Log received data for debugging
        print(f"[DEBUG] Received: id={data.get('id')}, url={data.get('url')[:50] if data.get('url') else 'N/A'}...")
        
        # Deduplication: check if this URL already exists in display_items
        data_url = data.get('url', '')
        for existing in self.display_items:
            existing_url = existing.get('url', '')
            # Compare URLs by extracting item ID from URL
            if data_url and existing_url and data_url == existing_url:
                print(f"[DEBUG] Skipping duplicate URL")
                return  # Skip duplicate
        
        # Also check pending items
        for pending in self.pending_items:
            if data_url and pending.get('url', '') == data_url:
                print(f"[DEBUG] Skipping duplicate in pending")
                return
        
        # Merge with task_queue info
        data_id = str(data.get('id', ''))
        
        for task in self.task_queue:
            task_id = str(task.get('id', ''))
            task_url = task.get('url', '')
            
            # Match by ID (Preferred) or URL (Fallback)
            is_match = False
            if data_id and task_id and data_id == task_id:
                is_match = True
            elif data_url and task_url and data_url.split('?')[0] == task_url.split('?')[0]: # Ignore params
                is_match = True
                
            if is_match:
                data['json_file'] = task.get('json_file')
                data['title'] = task.get('title') or data.get('title', '')
                # If coming from correct task, we rely on task's file info
                break
        
        
        self.pending_items.append(data)
        # Log keys for debug
        print(f"[DEBUG] Added item keys: {list(data.keys())}")
        print(f"[DEBUG] Added to pending, total pending: {len(self.pending_items)}")
        
        # Auto-advance to next page if in scraping mode
        # DISABLED: Let userscript handle navigation to avoid new tab focus stealing
        # if self.is_scraping and self.task_queue:
        #     self.root.after(2000, self.advance_to_next)
    
    def check_pending_items(self):
        while self.pending_items:
            item = self.pending_items.pop(0)
            self.add_to_display(item)
        
        self.update_status()
        self.root.after(500, self.check_pending_items)
    
    def add_to_display(self, item):
        self.display_items.append(item)
        row_id = self.next_row_id
        self.next_row_id += 1
        self.add_row(item, row_id)
        self.log(f"收到: {item.get('title', '')[:20]}... 面积: {item.get('建筑面积', 'N/A')}")
        
        # Queue for AI verification if area detected
        self.queue_for_ai_verification(item, row_id)

    # ... [get_next_task, add_item, check_pending_items same as before] ...
    # Skipping to add_row update

    def add_row(self, item, row_idx_unused):
        # Use next_row_idx logic
        row_idx = self.next_row_idx
        self.next_row_idx += 1
        
        row_widgets = {}
        row_widgets['idx'] = row_idx # keep calling it idx, but it's grid row
        
        col = 0
        
        # 1. Checkbox
        var = tk.BooleanVar(value=False)
        chk = ttk.Checkbutton(self.scrollable_frame, variable=var)
        chk.grid(row=row_idx, column=col, sticky='w', padx=1)
        row_widgets['start_chk'] = chk
        row_widgets['chk_var'] = var
        col += 1
        
        # 2. Title/Link
        title = item.get('title', '') or '无标题'
        link_btn = ttk.Button(self.scrollable_frame, text=title[:10], width=25,
                             command=lambda: self.open_chrome(item, auto=False)) # Manual open
        link_btn.grid(row=row_idx, column=col, sticky='w', padx=3)
        row_widgets['link_btn'] = link_btn
        col += 1
        
        # 3. Dynamic Fields
        row_widgets['vars'] = {}
        row_widgets['entries'] = {}
        
        for field in FIELDS_SCHEMA:
            if field.get('hidden'): continue
            
            key = field['key']
            val = item.get(key, '')
            if val is None: val = ''
            width = field.get('width', 10)
            
            w_var = tk.StringVar(value=str(val))
            row_widgets['vars'][key] = w_var
            
            if field.get('readonly'):
                state = 'readonly'
            else:
                state = 'normal'
            
            entry = ttk.Entry(self.scrollable_frame, textvariable=w_var, width=width, state=state)
            entry.grid(row=row_idx, column=col, sticky='w', padx=3)
            row_widgets['entries'][key] = entry
            
            col += 1
            
        # 4. Context
        context_text = ""
        full_context = ""
        missing = item.get('missing', [])
        if missing:
            context_text = f"缺: {','.join(missing)}"
            full_context = context_text
        else:
            full_context = item.get('context', '')
            context_text = full_context.replace('\n', ' ')[:30] if full_context else ''
        context_label = ttk.Label(self.scrollable_frame, text=context_text, width=30, anchor='w')
        context_label.grid(row=row_idx, column=col, sticky='w', padx=3)
        row_widgets['context_label'] = context_label
        # Hover tooltip shows full context
        if full_context:
            row_widgets['context_tooltip'] = ToolTip(context_label, full_context, wrap_length=500)
        col += 1
        
        # 5. Operations
        op_frame = ttk.Frame(self.scrollable_frame)
        op_frame.grid(row=row_idx, column=col, sticky='w', padx=3)
        
        approve_btn = ttk.Button(op_frame, text="✓", width=3,
                               command=lambda: self.approve_single(row_idx))
        approve_btn.pack(side='left', padx=1)
        
        infer_btn = ttk.Button(op_frame, text="推断", width=4,
                              command=lambda: self._infer_location_for_row(row_idx))
        infer_btn.pack(side='left', padx=1)
        
        del_btn = ttk.Button(op_frame, text="删", width=3,
                           command=lambda: self.remove_row_by_idx(row_idx))
        del_btn.pack(side='left', padx=1)
        
        row_widgets['op_frame'] = op_frame
        row_widgets['approve_btn'] = approve_btn
        row_widgets['infer_btn'] = infer_btn
        row_widgets['del_btn'] = del_btn
        row_widgets['item'] = item
        
        self.row_widgets.append(row_widgets)
        return row_widgets

    def _infer_location_for_row(self, idx):
        """Handle manual '推断' button click for a row"""
        target_widget = None
        for w in self.row_widgets:
            if w['idx'] == idx:
                target_widget = w
                break
        
        if not target_widget:
            return

        item = target_widget['item']
        address = item.get('地点', '')
        title = item.get('title', '')
        
        if not address:
            self.log(f"无法推断: 缺少地址信息 (ID={item.get('id')})")
            return
            
        def run_infer():
            try:
                # Update button state to indicate working
                if 'infer_btn' in target_widget and target_widget['infer_btn'].winfo_exists():
                    target_widget['infer_btn'].config(state='disabled', text='...')
                
                result = self._infer_location_ai(address, title)
                
                # Callback to update UI in main thread
                def update_ui():
                    if 'infer_btn' in target_widget and target_widget['infer_btn'].winfo_exists():
                        target_widget['infer_btn'].config(state='normal', text='推断')
                        
                    if result:
                        vars_dict = target_widget['vars']
                        updated = []
                        if result.get('所属小区') and '所属小区' in vars_dict:
                            vars_dict['所属小区'].set(result['所属小区'])
                            item['所属小区'] = result['所属小区']
                            updated.append(f"小区={result['所属小区']}")
                            
                        if result.get('最靠近商圈') and '最靠近商圈' in vars_dict:
                            vars_dict['最靠近商圈'].set(result['最靠近商圈'])
                            item['最靠近商圈'] = result['最靠近商圈']
                            updated.append(f"商圈={result['最靠近商圈']}")
                            
                        if updated:
                            self.log(f"推断成功: {' '.join(updated)}")
                        else:
                            self.log("推断完成: 未找到有效信息")
                    else:
                        self.log("推断失败: AI未返回结果")

                self.root.after(0, update_ui)
                
            except Exception as e:
                self.log(f"推断出错: {e}")
                def reset_btn():
                    if 'infer_btn' in target_widget and target_widget['infer_btn'].winfo_exists():
                        target_widget['infer_btn'].config(state='normal', text='推断')
                self.root.after(0, reset_btn)

        import threading
        threading.Thread(target=run_infer, daemon=True).start()
        
    def approve_single(self, idx):
        """Handle manual 'Approve' (check) button click for a row"""
        target_widget = None
        found = False
        for w in self.row_widgets:
            if w['idx'] == idx:
                target_widget = w
                found = True
                break
        
        if not found:
            self.log(f"错误: 找不到行 {idx}")
            return

        item = target_widget['item']
        try:
            # Collect all dynamic fields
            field_vars = target_widget['vars']
            
            for field in FIELDS_SCHEMA:
                if field.get('hidden') or field.get('readonly'): continue
                
                key = field['key']
                if key in field_vars:
                    val = field_vars[key].get().strip()
                    
                    # Type conversion if needed?
                    # For now keep string mostly, except numbers if critical
                    if field.get('key') == '建筑面积':
                         if val and val != '0':
                             try:
                                 item['建筑面积'] = float(val)
                             except:
                                 self.log(f"警告: 建筑面积 {val} 不是有效数字")
                         else:
                             item['建筑面积'] = 0
                    else:
                        item[key] = val
            
            # Define save action
            def do_save():
                # Map back to legacy keys if needed
                if '所属小区' in item:
                     item['community'] = item['所属小区']
                
                # Mark as checked
                item['manual_checked'] = True
                item['is_processed'] = True

                # Save to JSON
                if self.save_record(item):
                    self.log(f"已保存: {item.get('title', '')[:20]}")
                    self.remove_row_by_idx(idx)
                else:
                    self.log(f"保存失败: {item.get('title', '')[:20]}")
                    # Re-enable button if failed
                    if 'approve_btn' in target_widget and target_widget['approve_btn'].winfo_exists():
                        target_widget['approve_btn'].config(state='normal')

            # Check for missing info -> Auto Infer (Gap Filling)
            needs_community = not item.get('所属小区')
            needs_bizarea = not item.get('最靠近商圈')
            needs_area = not item.get('建筑面积') or float(item.get('建筑面积', 0)) == 0
            
            address = item.get('地点')
            
            # Workflow 2: If manual save, check missing -> sub-prompts -> save. No Final Verify.
            if AI_AVAILABLE and ((address and (needs_community or needs_bizarea)) or needs_area):
                self.log(f"保存前自动补全数据...")
                if 'approve_btn' in target_widget and target_widget['approve_btn'].winfo_exists():
                    target_widget['approve_btn'].config(state='disabled')
                
                def run_auto_infer_save():
                    try:
                        updates = []
                        # 1. Location Inference
                        if address and (needs_community or needs_bizarea):
                            # Use pool 1 for interactive
                            pool_idx = 1 if len(MODEL_POOL) > 1 else 0
                            inferred = self._infer_location_ai(address, item.get('title', ''))
                            
                            if inferred:
                                if needs_community and inferred.get('所属小区'):
                                    item['所属小区'] = inferred['所属小区']
                                    updates.append(f"小区={inferred['所属小区']}")
                                if needs_bizarea and inferred.get('最靠近商圈'):
                                    item['最靠近商圈'] = inferred['最靠近商圈']
                                    updates.append(f"商圈={inferred['最靠近商圈']}")
                        
                        # 2. Area Extraction
                        if needs_area:
                             extracted_area = self._infer_area_only_ai(item)
                             if extracted_area and extracted_area > 0:
                                 item['建筑面积'] = extracted_area
                                 updates.append(f"面积={extracted_area}")
                        
                        if updates:
                            self.log(f"补全成功: {' '.join(updates)}")
                            
                    except Exception as e:
                        self.log(f"自动补全失败: {e}")
                    
                    # Always save, even if infer failed
                    self.root.after(0, do_save)
                
                import threading
                threading.Thread(target=run_auto_infer_save, daemon=True).start()
            else:
                do_save()

        except Exception as e:
            self.log(f"处理失败: {e}")
            import traceback
            print(traceback.format_exc())
            return
        
        if self.save_record(item):
            self.log(f"已批准: {item.get('id', 'N/A')}... 面积: {item.get('建筑面积')}, 小区: {item.get('所属小区')}")
            self.remove_row_by_idx(idx)
            # Remove from display_items
            if item in self.display_items:
                self.display_items.remove(item)
            self.update_status()
        else:
            self.log(f"保存失败，请检查日志")

    def batch_approve(self):
        to_approve = []
        for w in self.row_widgets:
            if w['checkbox'].get():
                to_approve.append(w)
        
        if not to_approve:
            self.log("没有选中任何项目")
            return
        
        count = 0
        for w in to_approve:
            if self.approve_single(w['idx']):
                 count += 1
        
        self.log(f"批量批准完成，共 {len(to_approve)} 个")


    def log(self, msg):
        try:
            self.log_text.config(state='normal')
            self.log_text.insert('end', f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
            self.log_text.see('end')
            self.log_text.config(state='disabled')
        except:
            pass

    def approve_external(self, data):
        """Approve item from external source (userscript manual mode)"""
        url = data.get('url')
        # Support full update if id is present
        item_id = data.get('id')
        
        target_item = None
        
        # Helper to check match
        def is_match(item):
            # 1. Match by ID
            if item_id and item.get('id') and str(item.get('id')) == str(item_id):
                return True
            # 2. Match by exact URL
            if item.get('url') == url:
                return True
            # 3. Match by base URL (ignore params)
            if url and item.get('url'):
                base_u1 = url.split('?')[0]
                base_u2 = item.get('url').split('?')[0]
                if base_u1 == base_u2:
                    return True
            return False

        # Check display items first
        for item in self.display_items:
            if is_match(item):
                target_item = item
                break
        
        # Check pending items
        if not target_item:
            for item in self.pending_items:
                if is_match(item):
                    target_item = item
                    break
        
        # Check task queue
        if not target_item:
            for item in self.task_queue:
                if is_match(item):
                    # Load full item data from JSON
                    try:
                        with open(item['json_file'], 'r', encoding='utf-8') as f:
                            full_data = json.load(f)
                            if isinstance(full_data, list):
                                for i in full_data:
                                    if str(i.get('id')) == str(item['id']):
                                        target_item = i
                                        target_item['json_file'] = item['json_file']
                                        break
                            else:
                                target_item = full_data
                                target_item['json_file'] = item['json_file']
                    except:
                        pass
                    break
        
        # Keep finding if not found in memory - construct a minimal item to search in files
        if not target_item and item_id:
             target_item = {'id': item_id, 'url': url}

        if target_item:
            try:
                # Auto-fix missing 所属小区/最靠近商圈 via AI before saving
                address = data.get('地点', '')
                needs_community = not data.get('所属小区') or data.get('所属小区', '').strip() == ''
                needs_bizarea = not data.get('最靠近商圈') or data.get('最靠近商圈', '').strip() == ''
                
                if address and (needs_community or needs_bizarea) and AI_AVAILABLE:
                    self.log(f"位置推断中: {address[:30]}...")
                    try:
                        inferred = self._infer_location_ai(address, data.get('title', ''))
                        if inferred:
                            if needs_community and inferred.get('所属小区'):
                                data['所属小区'] = inferred['所属小区']
                                self.log(f"AI推断小区: {inferred['所属小区']}")
                            if needs_bizarea and inferred.get('最靠近商圈'):
                                data['最靠近商圈'] = inferred['最靠近商圈']
                                self.log(f"AI推断商圈: {inferred['最靠近商圈']}")
                    except Exception as e:
                        self.log(f"位置推断失败，直接保存: {e}")
                
                # Use new save_record method with full data
                if self.save_record(target_item, new_data=data):
                    title = data.get('title', target_item.get('title', 'Unknown'))
                    area = data.get('建筑面积', 0)
                    self.log(f"外部全量更新: {title[:20]}... 面积: {area}")
                    
                    # Remove from display if it's there
                    for i, row_data in enumerate(self.row_widgets):
                        if is_match(row_data['item']):
                            self.remove_row_by_idx(row_data['idx'])
                            break
                    
                    # Also remove from task_queue if present
                    for i, task in enumerate(self.task_queue):
                        if is_match(task):
                            self.task_queue.pop(i)
                            break
                    return True
            except Exception as e:
                self.log(f"外部批准失败: {e}")
                return False
        
        self.log(f"外部批准失败: 未找到对应任务或文件 URL={url}")
        return False

    
    def _infer_full_info_ai(self, item):
        """Stage 1: Main Prompt to get ALL info (Community, BizArea, Area, etc.)"""
        address = item.get('地点', '')
        title = item.get('title', '')
        context = item.get('context', '')
        
        if not AI_AVAILABLE or (not address and not title):
            return None
            
        prompt = f"""任务：全面分析以下房产拍卖信息，提取或推断关键属性。

输入信息：
标题：{title}
地址：{address}
上下文内容：
{context[:2000]}

请仔细分析以上信息，返回以下字段的JSON数据：
1. "所属小区"：标准小区名称（参考贝壳网数据库）。
2. "最靠近商圈"：该地址所属的商圈名称。
3. "建筑面积"：数字（平方米），无需单位。
4. "户型"：如“三室两厅”。
5. "房屋用途"：如“住宅”、“商业”、“办公”等。
6. "省份"：行政省份（如广东省）。
7. "城市"：行政城市（如广州市）。
8. "区"：行政区（如天河区）。
9. "市场评估价"：数字（元）。
10. "起拍价格"：数字（元）。
11. "成交价格"：数字（元），如未成交则为0或null。
12. "交易时间"：格式 YYYY/MM/DD HH:mm:ss。
13. "竞拍人数"：数字（报名人数）。
14. "出价人数"：数字（实际出价人数）。
15. "是否成交"：布尔值（true/false）。

返回JSON格式示例：
{{
    "所属小区": "xxx", 
    "最靠近商圈": "xxx",
    "建筑面积": 0.0,
    "户型": "xxx",
    "房屋用途": "xxx",
    "省份": "xxx",
    "城市": "xxx",
    "区": "xxx",
    "市场评估价": 1000000,
    "区": "xxx",
    "市场评估价": 1000000,
    "起拍价格": 800000,
    "成交价格": 1200000,
    "交易时间": "2023/01/01 10:00:00",
    "竞拍人数": 5,
    "出价人数": 3,
    "是否成交": true
}}
注意：
- 如果不确定某个字段，请返回 null，不要猜测。
- 建筑面积：如果是部分产权（如1/2份额、50%份额），请务必按份额比例计算实际可交易面积（例如100平米的1/2份额应填50）。如果是全套拍卖，则填全套产权证面积。
- 价格请转换为纯数字（元），不要带“万”等单位。"""

        # Use pool 1 (Inference Pool)
        pool_idx = 1 if len(MODEL_POOL) > 1 else 0
        self.log(f"执行全量推断 (Stage 1)...")
        
        try:
            ai_result = simple_ai_call(prompt, pool_idx=pool_idx)
            # Use DOTALL to match newlines and match greedily to handle nested braces
            json_match = re.search(r'\{.*\}', ai_result, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                except json.JSONDecodeError:
                    self.log(f"解析JSON失败: {ai_result[:50]}...")
                    parsed = {}

                
                # Filter valid results
                result = {}
                # Location
                if parsed.get('所属小区'): result['所属小区'] = parsed['所属小区']
                if parsed.get('最靠近商圈'): result['最靠近商圈'] = parsed['最靠近商圈']
                if parsed.get('省份'): result['省份'] = parsed['省份']
                if parsed.get('城市'): result['城市'] = parsed['城市']
                if parsed.get('区'): result['区'] = parsed['区']
                
                # Property Details
                if parsed.get('户型'): result['户型'] = parsed['户型']
                if parsed.get('房屋用途'): result['房屋用途'] = parsed['房屋用途']
                
                # Numeric & Dates (Robust parsing)
                def parse_num(key):
                    val = parsed.get(key)
                    if val is not None:
                        try:
                            return float(str(val).replace(',', '').replace('元', ''))
                        except:
                            pass
                    return None

                if parsed.get('建筑面积'):
                     area = parse_num('建筑面积')
                     if area and area > 0: result['建筑面积'] = area
                
                if parsed.get('市场评估价'): result['市场评估价'] = parse_num('市场评估价')
                if parsed.get('起拍价格'): result['起拍价格'] = parse_num('起拍价格')
                if parsed.get('成交价格'): result['成交价格'] = parse_num('成交价格')
                
                if parsed.get('竞拍人数') is not None: result['竞拍人数'] = int(parse_num('竞拍人数') or 0)
                if parsed.get('出价人数') is not None: result['出价人数'] = int(parse_num('出价人数') or 0)
                
                if parsed.get('交易时间'): result['交易时间'] = parsed['交易时间']
                if parsed.get('是否成交') is not None: result['是否成交'] = parsed['是否成交']

                return result
        except Exception as e:
            self.log(f"全量推断失败: {e}")
            
        return None

    def _infer_location_ai(self, address, title=''):
        """Use AI to infer 所属小区 and 最靠近商圈 from address."""
        if not AI_AVAILABLE or not address:
            return None
        
        prompt = f"""任务：根据以下房产地址，推断所属小区名称和最靠近的商圈。

地址：{address}
标题：{title}

要求：
1. 所属小区：请参考贝壳网小区大全数据库，返回该地址对应的标准小区名称。
2. 最靠近商圈：返回该地址最靠近的商圈名称（如：望京、国贸、五道口等）。

返回JSON格式：{{"所属小区": "xxx", "最靠近商圈": "xxx"}}"""
        
        # Use pool index 1 for inference if available to avoid blocking main worker
        pool_idx = 1 if len(MODEL_POOL) > 1 else 0
        self.log(f"AI推断中 (Pool-{pool_idx})...")
        
        ai_result = simple_ai_call(prompt, pool_idx=pool_idx)
        json_match = re.search(r'\{.*\}', ai_result, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
            except:
                parsed = {}

            result = {}
            if parsed.get('所属小区'):
                result['所属小区'] = parsed['所属小区']
            if parsed.get('最靠近商圈'):
                result['最靠近商圈'] = parsed['最靠近商圈']
            return result if result else None
        return None

    def _infer_area_only_ai(self, item):
        """Stage 2 Helper: Extract ONLY area from context."""
        title = item.get('title', '')
        context = item.get('context', '')
        
        prompt = f"""任务：从以下房产拍卖信息中提取“建筑面积”。

标题：{title}
上下文：
{context[:1500]}

要求：
1. 返回纯数字（平方米），无需单位。
2. 如果是部分产权（如1/2份额），请计算实际可交易面积。
3. 如果无法找到，返回 null。

返回JSON：{{"建筑面积": 123.45}}"""

        try:
             # Use pool 0 (Verification Pool - Default)
             res = simple_ai_call(prompt)
             # Use DOTALL for robustness
             match = re.search(r'\{.*\}', res, re.DOTALL)
             if match:
                 try:
                    parsed = json.loads(match.group())
                 except:
                    parsed = {}
                 val = parsed.get('建筑面积')
                 if val and float(val) > 0:
                     return float(val)
        except:
             pass
        return None

    def _verify_final_ai(self, item, context=None):
        """Stage 3: Final Holistic Verification."""
        # Clean context for prompt
        if context is None:
            context = item.get('context', '')
        context = context[:2000]
        
        # Construct data summary
        data_summary = {
            "标题": item.get('title'),
            "小区": item.get('所属小区'),
            "面积": item.get('建筑面积'),
            "起拍价": item.get('起拍价格'),
            "评估价": item.get('市场评估价'),
            "成交价": item.get('成交价格')
        }
        
        prompt = f"""任务：终审房产拍卖数据准确性。

目标数据：
{json.dumps(data_summary, ensure_ascii=False, indent=2)}

对应网页文本（节选）：
{context}

请核对“目标数据”是否与“网页文本”一致。
特别是：
1. 小区名称是否准确？(如果文本只有地址，请判断小区名是否合理)
2. 建筑面积是否准确？(注意区分产权面积和通过份额计算的面积)
3. 价格是否匹配？

返回JSON格式：
{{
    "approved": true/false,   // 如果数据基本准确（或无法证伪），返回 true
    "reason": "通过原因或拒绝原因",
    "corrections": {{}}       // 如果有明显错误，请在此修正，例如 {{"建筑面积": 100.0}}
}}"""

        try:
             res = simple_ai_call(prompt)
             match = re.search(r'\{.*\}', res, re.DOTALL)
             if match:
                 return json.loads(match.group())
        except Exception as e:
             self.log(f"终审失败: {e}")
        return None

    def get_item_by_id(self, item_id):
        """Find item by ID in memory or files"""
        item_id = str(item_id)
        
        # 1. Check Display Items
        for row in self.row_widgets:
            if str(row['item'].get('id')) == item_id:
                return row['item']
        
        # 2. Check Pending Items
        for item in self.pending_items:
            if str(item.get('id')) == item_id:
                return item
        
        # 3. Check Task Queue
        for item in self.task_queue:
            if str(item.get('id')) == item_id:
                # Load full if only partial
                if 'json_file' in item:
                     try:
                        with open(item['json_file'], 'r', encoding='utf-8') as f:
                            full_data = json.load(f)
                            if isinstance(full_data, list):
                                for i in full_data:
                                    if str(i.get('id')) == item_id:
                                        i['json_file'] = item['json_file']
                                        return i
                            else:
                                full_data['json_file'] = item['json_file']
                                return full_data
                     except:
                         pass
                return item
        
        # 4. Scan files (Slow, but necessary for random access)
        # Optimization: maybe rely only on queue? 
        # But user wants "Local Data" priority, implying if it exists anywhere, show it.
        # Let's limit scan to recent/priority if possible, or just scan all since dataset isn't huge yet?
        # Given "glob.glob" usage in save_record, we can replicate it.
        root_files = glob.glob(os.path.join(DATAS_DIR, '*.json'))
        archive_files = glob.glob(os.path.join(DATAS_DIR, 'archive', '**', '*.json'), recursive=True)
        
        for j_file in root_files + archive_files:
            try:
                with open(j_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    items = data if isinstance(data, list) else [data]
                    for i in items:
                        if str(i.get('id')) == item_id:
                            i['json_file'] = j_file
                            return i
            except:
                pass
        
        return None

    
    def open_chrome(self, item, auto=False):
        url = item.get('url', '')
        if not url:
            # Try to reconstruct from ID if missing
            item_id = item.get('id')
            if item_id:
                url = f"https://sf.taobao.com/Item.htm?id={item_id}"
            else:
                self.log("无法打开链接：没有URL或ID")
                return

        # Prepare URL with port and mode
        # Always inject port so helper knows where to submit
        port_param = f"uni_port={HTTP_PORT}"
        
        separator = '&' if '?' in url else '?'
        if port_param not in url:
            url += f"{separator}{port_param}"
            
        if auto:
            # Add auto_fix
            separator = '&' if '?' in url else '?'
            if 'auto_fix=1' not in url:
                url += f"{separator}auto_fix=1"
        else:
            # Manual open: strip auto_fix param if present (cleanup contaminated data)
            url = url.replace('auto_fix=1', '').replace('?&', '?').replace('&&', '&')
            if url.endswith('?') or url.endswith('&'):
                url = url[:-1]
                
        import subprocess
        try:
            # Open default browser
            # If auto, don't steal focus (SW_SHOWMINNOACTIVE)
            # If manual, allow focus
            si = subprocess.STARTUPINFO()
            if auto:
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 7  # SW_SHOWMINNOACTIVE
            
            # Use shell=True with start command to open in default browser
            # Quote the URL to handle ampersands correctly
            cmd = f'start "" "{url}"'
            subprocess.Popen(cmd, shell=True, startupinfo=si)
            self.log(f"已打开: {url[:60]}...")
        except Exception as e:
            self.log(f"打开浏览器失败: {e}")

    def pause_scraping(self):
        self.is_scraping = False
        self.start_btn.config(state='normal')
        self.pause_btn.config(state='disabled')
        self.scraping_status.config(text="状态: 已暂停", foreground='orange')
        self.log("抓取已暂停")
    
    def toggle_select_all(self):
        """Toggle select all / deselect all"""
        self.all_selected = not self.all_selected
        for row_data in self.row_widgets:
            row_data['checkbox'].set(self.all_selected)
        
        if self.all_selected:
            self.select_all_btn.config(text="☑ 取消全选")
        else:
            self.select_all_btn.config(text="☐ 全选")
            
    def skip_selected(self):
        to_remove = []
        for row_data in self.row_widgets:
            if row_data['checkbox'].get():
                to_remove.append(row_data['idx'])
        
        for idx in to_remove:
            self.remove_row_by_idx(idx)
        
        self.log(f"已跳过 {len(to_remove)} 条记录")
        self.all_selected = False
        self.select_all_btn.config(text="☐ 全选")

    def ai_verify_worker(self):
        """Background worker thread for AI verification with New Workflow Logic (W1/W3)."""
        import time
        import re
        
        # No delay between calls - rely on retry mechanism for failures
        OFFLINE_DELAY = 0
        ONLINE_DELAY  = 0
        
        while True:
            if not self.ai_verify_queue:
                time.sleep(2)
                continue
            
            # Get next item to verify
            verify_item = self.ai_verify_queue.pop(0)
            item = verify_item['item']
            row_id = verify_item['row_id']
            retry_count = verify_item.get('retry_count', 0)
            is_offline = (row_id is None)
            
            try:
                context = item.get('context')
                missing = item.get('missing', [])
                
                print(f"[AI_WORKER] {'BG' if is_offline else 'UI'} | {(item.get('title') or '?')[:15]}... Missing={missing}")

                # --- Workflow 3: Historic Data / Partial Context (No Web Text) ---
                if not context:
                    # Can only fix Community/BizArea via Address
                    if item.get('地点'):
                        address = item.get('地点')
                        prompt = f"""任务：根据以下房产拍卖地址，推断该房产所属的小区名称、最靠近的商圈、以及省份/城市/区。

地址：{address}
标题：{item.get('title', '')}

要求：
1. 小区名称：根据地址推断最可能的小区，使用标准小区名称（参考贝壳网数据库）。
2. 最靠近商圈：根据地址所在区域，推断最近的商业圈/商圈名。
3. 省份、城市、区：从地址中提取行政区划。
4. 如果某项无法确定，返回 null。

返回JSON：
{{{{
    "所属小区": "xxx",
    "最靠近商圈": "xxx",
    "省份": "xxx",
    "城市": "xxx",
    "区": "xxx"
}}}}"""
                        try:
                            res = simple_ai_call(prompt)
                            match = re.search(r'\{.*\}', res, re.DOTALL)
                            if match:
                                parsed = json.loads(match.group())
                                # Collect non-null inferred values
                                inferred = {}
                                for k in ['所属小区', '最靠近商圈', '省份', '城市', '区']:
                                    v = parsed.get(k)
                                    if v and str(v).lower() not in ['null', 'none', '']:
                                        inferred[k] = v
                                
                                if inferred:
                                    print(f"[AI_W3] Address Infer: {address} -> {inferred}")
                                    item.update(inferred)
                                    
                                    if row_id is not None:
                                        self.root.after(0, lambda i=item, r=row_id, kv=inferred.copy(): self._partial_update_item(i, r, kv))
                                    else:
                                        # Offline: Verify then save
                                        self.log(f"[离线推断] {address[:20]} -> {list(inferred.keys())}，验证中...")
                                        temp_context = f"地址：{address}\n请判断以下推断是否合理。"
                                        verify_res = self._verify_final_ai(item, context=temp_context)
                                        
                                        if verify_res and verify_res.get('approved'):
                                            corrections = verify_res.get('corrections', {})
                                            if corrections:
                                                item.update(corrections)
                                                inferred.update(corrections)
                                            self.save_record(item, new_data=inferred)
                                            self.log(f"[离线修复] ✓ 已保存 (ID:{item.get('id')})")
                                        else:
                                            reason = verify_res.get('reason') if verify_res else 'N/A'
                                            self.log(f"[离线修复] ✗ 验证拒绝: {reason}")
                        except Exception as e:
                            print(f"[AI_W3_ERROR] {e}")
                    
                    # Fields like area/price can't be inferred without context
                    # Rate limit for offline tasks
                    time.sleep(OFFLINE_DELAY if is_offline else ONLINE_DELAY)
                    continue

                # --- Workflow 1: Auto-Scraped Data (Has Context) ---
                
                # Step 1: Full Inference (if not done)
                if not item.get('stage1_done'):
                    try:
                        full_res = self._infer_full_info_ai(item)
                        if full_res:
                            item.update(full_res)
                            # Update GUI immediately with what we found
                            self.root.after(0, lambda i=item, r=row_id, kv=full_res: self._partial_update_item(i, r, kv))
                        item['stage1_done'] = True
                    except Exception as e:
                        print(f"[AI_W1_STEP1_ERROR] {e}")

                # Step 2: Gap Filling (Completing Data)
                # Re-evaluate missing
                if not item.get('所属小区'): missing.append('所属小区')
                if not item.get('建筑面积') or float(item.get('建筑面积', 0)) == 0: missing.append('建筑面积')
                
                updates_step2 = {}
                
                # 2.1 Location Fields Extraction (小区 + 商圈 + 省/市/区)
                has_missing_location = any(
                    not item.get(f) or str(item.get(f, '')).strip().lower() in ['none', 'null', '']
                    for f in ['所属小区', '最靠近商圈', '省份', '城市', '区']
                )
                if has_missing_location:
                    address = item.get('地点')
                    if address:
                        print(f"[AI_W1_STEP2] Inferring location fields from: {address[:30]}")
                        prompt = f"""任务：根据以下房产拍卖地址，推断该房产所属的小区名称、最靠近的商圈、以及省份/城市/区。

地址：{address}
标题：{item.get('title', '')}

要求：
1. 小区名称：如果地址中包含小区名，直接提取；否则根据地址推断最可能的小区。
2. 最靠近商圈：根据地址所在区域，推断最近的商业圈/商圈名。
3. 省份、城市、区：从地址中提取行政区划。
4. 如果某项无法确定，返回 null。

返回JSON：
{{{{
    "所属小区": "xxx",
    "最靠近商圈": "xxx",
    "省份": "xxx",
    "城市": "xxx",
    "区": "xxx"
}}}}"""
                        try:
                            res = simple_ai_call(prompt)
                            match = re.search(r'\{.*\}', res, re.DOTALL)
                            if match:
                                parsed = json.loads(match.group())
                                for k in ['所属小区', '最靠近商圈', '省份', '城市', '区']:
                                    v = parsed.get(k)
                                    if v and str(v).lower() not in ['null', 'none', '']:
                                        # Only fill if currently empty
                                        cur = item.get(k)
                                        if not cur or str(cur).strip().lower() in ['none', 'null', '']:
                                            item[k] = v
                                            updates_step2[k] = v
                        except Exception as e:
                            print(f"[AI_W1_STEP2_LOC_ERROR] {e}")

                # 2.2 Area Extraction
                area = item.get('建筑面积')
                if not area or float(area) == 0:
                     extracted_area = self._infer_area_only_ai(item)
                     if extracted_area and extracted_area > 0:
                         item['建筑面积'] = extracted_area
                         updates_step2['建筑面积'] = extracted_area
                
                # Update GUI with Step 2 results
                if updates_step2:
                     print(f"[AI_W1_STEP2] Fill gaps: {updates_step2}")
                     self.root.after(0, lambda i=item, r=row_id, kv=updates_step2: self._partial_update_item(i, r, kv))

                # Step 3: Final Verification
                # Only if we have enough data to verify?
                # Or always verify?
                # User says: "Ask AI if this data is correct. If yes, Use it."
                
                verify_res = self._verify_final_ai(item)
                
                if verify_res and verify_res.get('approved'):
                    print(f"[AI_W1_STEP3] APPROVED. Reason: {verify_res.get('reason')}")
                    # Auto Approve (Remove Row)
                    # We might have corrections in verify_res?
                    corrections = verify_res.get('corrections', {})
                    if corrections:
                        item.update(corrections)
                    
                    self.ai_approved_count += 1
                    self.root.after(0, lambda i=item, r=row_id, kv=corrections: self._auto_approve_item_update(i, r, kv))
                
                else:
                    reason = verify_res.get('reason') if verify_res else "No Response"
                    print(f"[AI_W1_STEP3] REJECTED/UNCERTAIN. Reason: {reason}")
                    # We already did Partial Updates in Step 1 & 2.
                    # So the data is saved in file (if _partial_update saves).
                    # Row remains in GUI for manual review.
                    pass

            except Exception as e:
                error_msg = str(e)
                if 'Concurrency' in error_msg or 'concurrency' in error_msg.lower():
                    print(f"[AI_RETRY] 服务端并发限制，重新入队...")
                    self.ai_verify_queue.append({
                        'item': item,
                        'row_id': row_id,
                        'retry_count': retry_count + 1
                    })
                    time.sleep(30)  # Wait 30s on concurrency error
                else:
                    print(f"[AI_WORKER_ERROR] {e}")
            
            # Update AI stats & rate limit
            self.root.after(0, self._update_ai_stats)
            time.sleep(OFFLINE_DELAY if is_offline else ONLINE_DELAY)

    def _update_ai_stats(self):
        """Update AI stats label in GUI."""
        self.ai_stats_label.config(text=f"AI通过: {self.ai_approved_count} | 待定: {self.ai_rejected_count}")


    def queue_for_ai_verification(self, item, row_id=None, priority=True):
        """Add item to AI verification queue. Auto-detects missing fields."""
        if not AI_AVAILABLE:
            return
        
        # Auto-detect missing fields from actual values
        missing = []
        for field_key in INFERABLE_FIELDS:
            val = item.get(field_key)
            if not val or str(val).strip().lower() in ['none', 'null', '']:
                missing.append(field_key)
        
        # Check area
        area = 0
        try:
            area = float(item.get('建筑面积', 0) or 0)
        except:
            pass
        if area == 0:
            missing.append('建筑面积')
        
        # Check if area needs verification (has area but not yet verified)
        needs_area_verify = (area > 0 and not item.get('is_verified'))
        
        if not missing and not needs_area_verify:
            return  # Nothing to do
        
        # Set missing on item so worker knows what to fix
        item['missing'] = missing
        
        queue_entry = {
            'item': item,
            'row_id': row_id,
            'retry_count': 0
        }
        
        if priority:
            self.ai_verify_queue.insert(0, queue_entry)
            label = 'HighPriority'
        else:
            self.ai_verify_queue.append(queue_entry)
            label = 'LowPriority'
        
        print(f"[AI_QUEUE] Adding {label}: {(item.get('title') or '?')[:30]}... Missing: {missing}")


    def sort_by_area(self):
        """Sort displayed items by whether they have a valid area (items with area first)."""
        if not self.row_widgets:
            self.log("没有可排序的条目")
            return
        
        # Clear current display
        for row_data in self.row_widgets:
            row_data['frame'].destroy()
        
        # Sort: items with valid area first, then by area value descending
        def sort_key(row_data):
            area = row_data['item'].get('建筑面积')
            if area and float(area) > 0:
                return (0, -float(area))  # Has area, sort by area desc
            return (1, 0)  # No area, put at end
        
        sorted_rows = sorted(self.row_widgets, key=sort_key)
        
        # Rebuild display with sorted order
        self.row_widgets = []
        for row_data in sorted_rows:
            self.add_row(row_data['item'], row_data['idx'])
        
        self.log(f"已按面积排序 (有效面积优先)")

    def setup_routes(self, server):
        @server.app.route('/api/next_task', methods=['GET'])
        def get_next_task():
            return jsonify(self.get_next_task())

        @server.app.route('/api/get_item', methods=['GET'])
        def get_item():
            item_id = request.args.get('id')
            if not item_id:
                return jsonify({'error': 'No ID provided'}), 400
            
            item = self.get_item_by_id(item_id)
            if item:
                return jsonify(item)
            else:
                return jsonify({'error': 'Item not found'}), 404
            
        @server.app.route('/api/area_result', methods=['POST'])
        def receive_area():
            data = request.json
            self.root.after(0, lambda: self.add_item(data))
            return jsonify({'status': 'ok'})
            
        @server.app.route('/api/approve_area', methods=['POST'])
        def approve_area():
            data = request.json
            self.root.after(0, lambda: self.approve_external(data))
            return jsonify({'status': 'ok'})
    
    def skip_single(self, idx):
        """Skip single item"""
        self.remove_row_by_idx(idx)
        self.log("已跳过一条记录")
    
    def delete_single(self, idx):
        """Delete single item from display (doesn't affect JSON)"""
        self.remove_row_by_idx(idx)
        self.log("已删除一条记录（仅从显示中移除，不影响原数据）")
    
    def clear_all(self):
        """Clear all displayed items (doesn't affect JSON)"""
        count = len(self.row_widgets)
        # Destroy all row frames
        self.next_row_idx = 1
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.row_widgets = []
        self.add_headers()
        self.display_items.clear()
        self.pending_items.clear()
        self.update_status()
        self.log(f"已清空 {count} 条记录（仅从显示中移除，不影响原数据）")
    
    def remove_row_by_idx(self, idx):
        """Remove a row from display"""
        for i, row_data in enumerate(self.row_widgets):
            if row_data['idx'] == idx:
                # Destroy known widgets
                if 'start_chk' in row_data: row_data['start_chk'].destroy()
                if 'link_btn' in row_data: row_data['link_btn'].destroy()
                if 'context_label' in row_data: row_data['context_label'].destroy()
                if 'approve_btn' in row_data: row_data['approve_btn'].destroy()
                if 'del_btn' in row_data: row_data['del_btn'].destroy()
                if 'op_frame' in row_data: row_data['op_frame'].destroy()
                
                if 'entries' in row_data:
                    for entry in row_data['entries'].values():
                        entry.destroy()
                
                self.row_widgets.pop(i)
                # Also remove from display_items
                if 'item' in row_data:
                    item_to_remove = row_data['item']
                    for j, item in enumerate(self.display_items):
                        if id(item) == id(item_to_remove):
                            self.display_items.pop(j)
                            break
                break
        self.update_status()
    
    def update_status(self):
        remaining = len(self.task_queue)
        self.status_label.config(text=f"显示: {len(self.row_widgets)} | 队列剩余: {remaining}")
    
    def start_scraping(self):
        if not self.task_queue:
            messagebox.showinfo("提示", "没有待处理的任务")
            return
        
        self.is_scraping = True
        self.start_btn.config(state='disabled')
        self.pause_btn.config(state='normal')
        self.scraping_status.config(text="状态: 抓取中...", foreground='green')
        
        if self.task_queue:
            task = random.choice(self.task_queue)
            self.task_queue.remove(task)
            self.open_chrome(task, auto=True)
            self.log(f"开始自动抓取")
        
        self.update_status()

    def advance_to_next(self):
        """Auto-advance to next task in queue."""
        if not self.is_scraping:
            return
        if not self.task_queue:
            self.log("任务队列已空，自动抓取完成")
            self.pause_scraping()
            return
        
        task = random.choice(self.task_queue)
        self.task_queue.remove(task)
        self.open_chrome(task, auto=True)
        self.log(f"自动前进: 剩余 {len(self.task_queue)} 个任务")
        self.update_status()
    
    def pause_scraping(self):
        self.is_scraping = False
        self.start_btn.config(state='normal')
        self.pause_btn.config(state='disabled')
        self.scraping_status.config(text="状态: 已暂停", foreground='orange')
        self.log("抓取已暂停")
    
    def toggle_select_all(self):
        """Toggle select all / deselect all"""
        self.all_selected = not self.all_selected
        for row_data in self.row_widgets:
            row_data['checkbox'].set(self.all_selected)
        
        if self.all_selected:
            self.select_all_btn.config(text="☑ 取消全选")
        else:
            self.select_all_btn.config(text="☐ 全选")
    
    def batch_approve(self):
        approved = 0
        to_remove = []
        
        for row_data in self.row_widgets:
            if row_data['checkbox'].get():
                item = row_data['item']
                try:
                    area = float(row_data['area_var'].get())
                    item['建筑面积'] = area
                    if self.save_area(item):
                        approved += 1
                        to_remove.append(row_data['idx'])
                except:
                    pass
        
        for idx in to_remove:
            self.remove_row(idx)
        
        self.log(f"已批准 {approved} 条记录")
        self.all_selected = False
        self.select_all_btn.config(text="☐ 全选")
    
    def skip_selected(self):
        to_remove = []
        for row_data in self.row_widgets:
            if row_data['checkbox'].get():
                to_remove.append(row_data['idx'])
        
        for idx in to_remove:
            self.remove_row(idx)
        
        self.log(f"已跳过 {len(to_remove)} 条记录")
        self.all_selected = False
        self.select_all_btn.config(text="☐ 全选")
    
    def _partial_update_item(self, item, row_id, updates_dict):
        """Update item and GUI without removing row (for Stage 1)."""
        # Find the row by row_id
        for row_data in self.row_widgets:
            if row_data['idx'] == row_id:
                # Update UI vars dynamically
                if 'vars' in row_data:
                    for k, v in updates_dict.items():
                        if k in row_data['vars']:
                            try:
                                row_data['vars'][k].set(str(v))
                            except:
                                pass

                # Update item data
                for k, v in updates_dict.items():
                    item[k] = v
                
                # Save to JSON
                if self.save_record(item, new_data=updates_dict):
                    title = item.get('title', '')[:20]
                    self.log(f"[AI-Stage1] 已更新: {title}... {updates_dict}")
                else:
                    self.log(f"[AI-Stage1] 保存失败: {item.get('title', '')[:20]}...")
                break

    def _auto_approve_item_update(self, item, row_id, updates_dict):
        """Auto approve an item after AI verification with key-value updates."""
        # Find the row by row_id
        for row_data in self.row_widgets:
            if row_data['idx'] == row_id:
                # Update UI vars dynamically
                if 'vars' in row_data:
                    for k, v in updates_dict.items():
                        if k in row_data['vars']:
                             try:
                                 row_data['vars'][k].set(str(v))
                             except:
                                 pass

                # Update item data
                for k, v in updates_dict.items():
                    item[k] = v
                
                # Save to JSON
                if self.save_record(item, new_data=updates_dict):
                    title = item.get('title', '')[:20]
                    self.log(f"[AI自动] 已修复: {title}... {updates_dict}")
                    # Use remove_row (aliased to remove_row_by_idx usually, or check definition)
                    # If remove_row takes widget, we need to be careful.
                    # Assuming remove_row_by_idx is safer if available? 
                    # But existing code used remove_row(row_id). logic likely: delete row_id.
                    if hasattr(self, 'remove_row_by_idx'):
                        self.remove_row_by_idx(row_id)
                    else:
                        self.remove_row(row_id)
                else:
                    self.log(f"[AI自动] 保存失败: {item.get('title', '')[:20]}...")
                break

    
    # Legacy shim
    def _auto_approve_item(self, item, row_id, area):
        self._auto_approve_item_update(item, row_id, {'建筑面积': area})


    def _update_ai_stats(self):
        """Update AI stats label in GUI."""
        self.ai_stats_label.config(text=f"AI通过: {self.ai_approved_count} | 待定: {self.ai_rejected_count}")
    
    def save_record(self, item, new_data=None):
        """
        Save/Update record in JSON file.
        If new_data is provided, it updates fields in the record.
        """
        try:
            json_file = item.get('json_file')
            item_id = item.get('id')
            item_url = item.get('url', '')
            
            # Extract item ID from URL as fallback
            url_extracted_id = None
            if item_url:
                import re
                match = re.search(r'[?&]id=(\d+)', item_url)
                if match:
                    url_extracted_id = match.group(1)
                else:
                    match = re.search(r'sf_item/(\d+)', item_url)
                    if match:
                        url_extracted_id = match.group(1)
            
            # Use extracted ID if item_id is missing
            if not item_id and url_extracted_id:
                item_id = url_extracted_id
                # print(f"[DEBUG] Extracted ID from URL: {item_id}")
            
            if not json_file:
                # Try to find json_file by scanning datas dir
                # self.log(f"正在查找数据源文件...")
                found = False
                
                root_files = glob.glob(os.path.join(DATAS_DIR, '*.json'))
                archive_files = glob.glob(os.path.join(DATAS_DIR, 'archive', '**', '*.json'), recursive=True)
                
                for j_file in root_files + archive_files:
                    try:
                        with open(j_file, 'r', encoding='utf-8') as f:
                            temp_data = json.load(f)
                            temp_items = temp_data if isinstance(temp_data, list) else [temp_data]
                            for r in temp_items:
                                # Strict ID match only
                                if item_id and str(r.get('id')) == str(item_id):
                                    json_file = j_file
                                    item['json_file'] = j_file
                                    found = True
                                    # print(f"[DEBUG] Found file by ID: {j_file}")
                                    break
                    except Exception:
                        pass
                    
                    if found:
                        break

            if not json_file:
                self.log(f"保存失败: 未找到对应的数据文件 (ID={item_id})")
                return False
            
            if not item_id:
                self.log(f"保存失败: 缺少有效的 item_id")
                return False
            
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            items = data if isinstance(data, list) else [data]
            updated = False
            
            for record in items:
                record_id = str(record.get('id', ''))
                target_id = str(item_id)
                
                # STRICT ID MATCH ONLY
                if record_id and target_id and record_id == target_id:
                    # Update fields if new_data is provided
                    if new_data:
                        # Clean URL to prevent auto_fix pollution
                        if new_data.get('url'):
                             new_data['url'] = new_data['url'].replace('?auto_fix=1', '').replace('&auto_fix=1', '')

                        # Update all fields from new_data
                        for k, v in new_data.items():
                            if k not in ['id', 'json_file']: # Don't overwrite metadata unless necessary
                                record[k] = v
                        
                        # Special handling for automatic fields
                        record['is_processed'] = True
                        record['manual_checked'] = True 
                        
                        # Auto calculate unit price
                        area = record.get('建筑面积')
                        if area:
                            try:
                                area_float = float(area)
                                if area_float > 0:
                                    deal_price = record.get('成交价格')
                                    start_price = record.get('起拍价格')
                                    price = deal_price if deal_price else start_price
                                    
                                    if price:
                                        record['单价'] = round(float(price) / area_float, 2)
                                else:
                                    record['单价'] = 0
                            except:
                                pass
                    
                    # Fallback: update 建筑面积 directly from item
                    elif '建筑面积' in item: 
                         area_float = float(item['建筑面积'])
                         record['建筑面积'] = area_float
                         if area_float == 0:
                             record['manual_checked'] = True
                             record['单价'] = 0
                         else:
                             deal_price = record.get('成交价格') or record.get('起拍价格')
                             if deal_price:
                                 record['单价'] = round(deal_price / area_float, 2)
                    
                    updated = True
                    break
            
            if updated:
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return True
            else:
                self.log(f"保存失败: 未找到匹配的记录 (ID={item_id})")
            
        except Exception as e:
            self.log(f"保存失败: {e}")
            import traceback
            print(traceback.format_exc())
        
        return False
        
    # Alias for backward compatibility
    save_area = save_record
    open_url = open_chrome
    
    def start_http_server(self):
        AreaFixerHandler.gui = self
        
        def run_server():
            server = HTTPServer(('127.0.0.1', HTTP_PORT), AreaFixerHandler)
            self.log(f"HTTP 服务器启动于 localhost:{HTTP_PORT}")
            server.serve_forever()
        
        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()


def main():
    root = tk.Tk()
    app = DataFixerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
