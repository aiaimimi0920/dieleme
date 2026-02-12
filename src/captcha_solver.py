import requests
import websocket
import json
import time
import random
import threading
import math

class CaptchaSolver:
    def __init__(self, port=9222):
        self.port = port
        self.ws_url = None
        self.ws = None
        self.message_id = 1
        self.lock = threading.Lock()

    def _get_json(self, endpoint):
        try:
            resp = requests.get(f"http://localhost:{self.port}/json/{endpoint}", timeout=2)
            return resp.json()
        except:
            return None

    def _send_cdp(self, method, params=None):
        if not self.ws: return None
        
        msg = {
            "id": self.message_id,
            "method": method,
            "params": params or {}
        }
        
        try:
            self.ws.send(json.dumps(msg))
            self.message_id += 1
            
            # Simple synchronous wait
            if "DOM" in method or "Runtime" in method or "Input" in method:
                start_time = time.time()
                while time.time() - start_time < 5: # 5s timeout per command
                    try:
                        res = self.ws.recv()
                        res_json = json.loads(res)
                        if res_json.get("id") == msg["id"]:
                            if "error" in res_json:
                                print(f"[SOLVER] CDP Error ({method}): {res_json['error']}")
                                return None
                            return res_json.get("result")
                    except websocket.WebSocketTimeoutException:
                        print(f"[SOLVER] Timeout waiting for {method}")
                        return None
                    except Exception as e:
                        print(f"[SOLVER] Error recv: {e}")
                        return None
        except Exception as e:
            print(f"[SOLVER] CDP Send Error: {e}")
            return None
        
        return None

    def connect_tab(self):
        """Connect to the first tab that looks like Taobao/Tmall/Auction."""
        tabs = self._get_json("list")
        if not tabs: 
            print("[SOLVER] No Chrome/Edge debug sessions found on port 9222.")
            return False
        
        target_ws = None
        target_title = ""
        
        # Priority: "验证" > "司法" > "淘宝"
        priority_keywords = ["验证", "司法", "淘宝", "tmall"]
        
        for kw in priority_keywords:
            for tab in tabs:
                url = tab.get("url", "")
                title = tab.get("title", "")
                if kw in title or kw in url:
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = title
                    break
            if target_ws: break
        
        if not target_ws:
             print("[SOLVER] No relevant tab found amongst open tabs.")
             return False

        try:
            print(f"[SOLVER] Connecting to tab: {target_title}")
            self.ws = websocket.create_connection(target_ws)
            self.ws.settimeout(5)
            # Enable domains
            self._send_cdp("DOM.enable")
            self._send_cdp("Runtime.enable")
            return True
        except Exception as e:
            print(f"[SOLVER] WS Connection failed: {e}")
            return False

    def solve(self):
        with self.lock:
            if not self.connect_tab():
                return False

            print("[SOLVER] Connected to browser. Searching for slider...")
            
            try:
                # 1. Find Element and Get Coordinates via JS (Bypass flaky DOM.getBoxModel)
                js_script = """
                (function() {
                    function getAbsolutePosition(el) {
                        let x = 0, y = 0;
                        let width = el.offsetWidth;
                        let height = el.offsetHeight;
                        
                        // Traverse up the offset chain
                        let current = el;
                        while(current) {
                            x += current.offsetLeft;
                            y += current.offsetTop;
                            current = current.offsetParent;
                        }

                        // Traverse up the frame chain (if inside iframe)
                        // Note: This only works if we are running in the context that has access.
                        // Since we use Runtime.evaluate in the top frame, we need to manually add iframe offsets if we found it in an iframe.
                        return { x: x, y: y, width: width, height: height };
                    }

                    function findSlider() {
                        // 1. Try selector in main document
                        let el = document.querySelector('#nc_1_n1z');
                        if (el) {
                            let rect = el.getBoundingClientRect();
                            return {
                                found: true,
                                x: rect.left + window.scrollX,
                                y: rect.top + window.scrollY,
                                width: rect.width,
                                height: rect.height,
                                context: 'main'
                            };
                        }
                        
                        // 2. Try selector in iframes
                        let frames = document.getElementsByTagName('iframe');
                        for (let i = 0; i < frames.length; i++) {
                            try {
                                let iframe = frames[i];
                                let doc = iframe.contentDocument;
                                if (doc) {
                                    el = doc.querySelector('#nc_1_n1z');
                                    if (el) {
                                        let rect = el.getBoundingClientRect();
                                        let frameRect = iframe.getBoundingClientRect();
                                        return {
                                            found: true,
                                            x: rect.left + frameRect.left + window.scrollX,
                                            y: rect.top + frameRect.top + window.scrollY,
                                            width: rect.width,
                                            height: rect.height,
                                            context: 'iframe'
                                        };
                                    }
                                }
                            } catch(e) {}
                        }
                        return null;
                    }
                    return findSlider();
                })()
                """
                
                slider_info = None
                
                # Retry loop (Wait for element to appear)
                for attempt in range(20):
                    ret = self._send_cdp("Runtime.evaluate", {
                        "expression": js_script,
                        "returnByValue": True  # KEY: Get the value directly!
                    })
                    
                    if ret and "result" in ret and ret["result"].get("value"):
                        slider_info = ret["result"]["value"]
                        # Double check we got valid coords
                        if slider_info.get("found"):
                             break
                    
                    print(f"[SOLVER] Slider not found... Retrying... (Attempt {attempt+1}/20)")
                    time.sleep(1)
                
                if not slider_info:
                    print("[SOLVER] Slider (#nc_1_n1z) not found after retries.")
                    self.ws.close()
                    return False

                start_x = slider_info["x"] + (slider_info["width"] / 2)
                start_y = slider_info["y"] + (slider_info["height"] / 2)
                
                # Sanity check: if 0,0 something is wrong
                if start_x < 10 or start_y < 10:
                     print(f"[SOLVER] Invalid coordinates: ({start_x}, {start_y})")
                     self.ws.close()
                     return False

                print(f"[SOLVER] Slider found at ({start_x}, {start_y}) [Context: {slider_info.get('context')}]. Executing drag...")

                
                # 4. Input Emulation
                self._send_cdp("Input.dispatchMouseEvent", {
                    "type": "mousePressed", "x": start_x, "y": start_y, "button": "left", "clickCount": 1
                })
                time.sleep(0.5)
                
                # 5. Advanced Human-like Drag Loop
                distance = 380 + random.randint(-5, 10) # Target slightly past end just in case
                duration = random.uniform(0.8, 1.3) # Random total time
                start_time = time.time()
                
                track_frequency = random.uniform(0.01, 0.02) # Mouse event frequency
                
                current_x = start_x
                current_y = start_y
                
                while True:
                    now = time.time()
                    elapsed = now - start_time
                    if elapsed > duration:
                        break
                        
                    progress = elapsed / duration
                    
                    # Easing: EaseOutQuart (starts fast, slows down gradually)
                    eased_progress = 1 - pow(1 - progress, 4)
                    
                    target_x = start_x + (distance * eased_progress)
                    
                    # Human behavior: Y-axis usually dips or arcs slightly
                    # Using a sine wave for arc + random noise
                    y_arc = 10 * math.sin(progress * math.pi) # Up to 10px deviation
                    
                    # Random jitter (tremble)
                    x_jitter = random.uniform(-3, 3)
                    y_jitter = random.uniform(-3, 3)
                    
                    move_x = target_x + x_jitter
                    move_y = start_y + y_arc + y_jitter
                    
                    # Ensure we don't go backwards too much (monotonic check roughly)
                    if move_x < current_x - 5: move_x = current_x # Clamp retrace
                    
                    self._send_cdp("Input.dispatchMouseEvent", {
                        "type": "mouseMoved", "x": move_x, "y": move_y, "button": "left"
                    })
                    
                    current_x = move_x
                    current_y = move_y
                    
                    time.sleep(track_frequency)
                
                # Final adjustment to ensure we are at the end
                end_steps = 10
                final_x = start_x + distance
                for i in range(end_steps):
                     # Linearly move to final exact spot to ensure completion
                     lx = current_x + ((final_x - current_x) * ((i+1)/end_steps))
                     ly = start_y # Return to center Y
                     self._send_cdp("Input.dispatchMouseEvent", {
                        "type": "mouseMoved", "x": lx, "y": ly, "button": "left"
                    })
                     time.sleep(0.02)
                     current_x = lx
                
                # Hold
                time.sleep(0.5)
                
                # Mouse Up
                self._send_cdp("Input.dispatchMouseEvent", {
                    "type": "mouseReleased", "x": current_x, "y": start_y, "button": "left", "clickCount": 1
                })
                
                print("[SOLVER] Drag complete.")
                time.sleep(1)
                
                self.ws.close()
                return True

            except Exception as e:
                print(f"[SOLVER] Error during steps: {e}")
                if self.ws: 
                    try: self.ws.close()
                    except: pass
                return False

if __name__ == "__main__":
    s = CaptchaSolver()
    if s.solve():
        print("Done.")
    else:
        print("Failed.")
