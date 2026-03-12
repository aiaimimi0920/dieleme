import requests
import websocket
import json
import time
import random
import threading
import math

class CaptchaSolver:
    # Multiple selectors for different captcha variants
    SLIDER_SELECTORS = [
        '#nc_1_n1z', '#nc_2_n1z', '[id^="nc_"][id$="_n1z"]',
        '.btn_slide', '.nc_iconfont.btn_slide', '.nc_scale .btn_slide', '.nc_wrapper .btn_slide',
        '.nc-slider-btn', '.slider-btn', '.nc-lang-cnt .btn_ok', '.btn_ok'
    ]
    TRACK_SELECTORS = [
        '#nc_1_n1t', '#nc_2_n1t', '[id^="nc_"][id$="_n1t"]',
        '.nc_scale', '.nc-lang-cnt', '.scale_text', '.slidetounlock', '.nc_wrapper',
        '.nc_scale_text', '[id^="nc_"][id*="scale_text"]'
    ]

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
            if "DOM" in method or "Runtime" in method or "Input" in method or "Page" in method:
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
        """Connect to the background worker tab using explicit URL parameters."""
        tabs = self._get_json("list")
        if not tabs: 
            print("[SOLVER] No Chrome/Edge debug sessions found on port 9222.")
            return False
        
        target_ws = None
        target_title = ""
        
        # Priority 1: 100% targeted background worker currently solving
        for tab in tabs:
            url = tab.get("url", "")
            if "__captcha_solver_bg=1" in url:
                target_ws = tab.get("webSocketDebuggerUrl")
                target_title = tab.get("title", "")
                print(f"[SOLVER] ✨ Found dedicated worker (solving): {url}")
                break
                
        # Priority 2: 100% targeted background worker in standby mode (useful if it's stuck or just transitioned)
        if not target_ws:
            for tab in tabs:
                url = tab.get("url", "")
                if "__captcha_worker_master=1" in url:
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    print(f"[SOLVER] ⏳ Found dedicated worker (standby): {url}")
                    break
        
        # Priority 2.5: sec.taobao.com / login.taobao.com pages (common captcha redirect destination)
        if not target_ws:
            for tab in tabs:
                url = tab.get("url", "")
                if "sec.taobao.com" in url or "login.taobao.com" in url:
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    print(f"[SOLVER] 🔐 Found sec/login page (likely captcha redirect): {url}")
                    break
        
        # Priority 3: Fallback to old heuristic
        if not target_ws:
            priority_keywords = ["验证", "RGV587", "司法", "淘宝", "tmall", "taobao"]
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
             print("[SOLVER] ❌ No relevant debug tag found.")
             # Let's see what tabs are open just for debugging
             print("[SOLVER] Currently open tabs:")
             for t in tabs[:5]:
                 print(f"  - {t.get('title')[:30]} | {t.get('url')[:50]}")
             return False

        try:
            print(f"[SOLVER] Connecting to tab: {target_title}")
            self.ws = websocket.create_connection(target_ws)
            self.ws.settimeout(5)
            # Enable domains
            self._send_cdp("DOM.enable")
            self._send_cdp("Runtime.enable")
            self._send_cdp("Page.enable")
            
            # CDP Stealth Injection: Overwrite navigator.webdriver to hide automation fingerprint
            self._send_cdp("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            })
            
            return True
        except Exception as e:
            print(f"[SOLVER] WS Connection failed: {e}")
            return False

    def _bring_to_front(self):
        """Bring captcha page to foreground to ensure mouse events hit the target."""
        try:
            self._send_cdp("Page.bringToFront")
            # Best-effort focus; some Chromium builds still need explicit window focus.
            self._send_cdp("Runtime.evaluate", {
                "expression": "try { window.focus(); document.body && document.body.focus && document.body.focus(); } catch(e) {}",
                "returnByValue": True
            })
            time.sleep(0.15)
            return True
        except Exception as e:
            print(f"[SOLVER] bringToFront failed: {e}")
            return False

    def _find_slider(self):
        """Find slider element using multiple selectors. Returns slider info dict or None."""
        selectors_js = json.dumps(self.SLIDER_SELECTORS)
        
        js_script = f"""
        (function() {{
            var selectors = {selectors_js};
            
            function tryFind(doc, frameOffsetX, frameOffsetY) {{
                for (var i = 0; i < selectors.length; i++) {{
                    var el = doc.querySelector(selectors[i]);
                    if (el && el.offsetParent !== null) {{
                        var rect = el.getBoundingClientRect();
                        if (rect.width > 5 && rect.height > 5) {{
                            return {{
                                found: true,
                                x: rect.left + frameOffsetX,
                                y: rect.top + frameOffsetY,
                                width: rect.width,
                                height: rect.height,
                                selector: selectors[i],
                                context: frameOffsetX === 0 ? 'main' : 'iframe'
                            }};
                        }}
                    }}
                }}
                return null;
            }}
            
            // Try main document
            var result = tryFind(document, 0, 0);
            if (result) return result;
            
            // Try iframes
            var frames = document.getElementsByTagName('iframe');
            for (var i = 0; i < frames.length; i++) {{
                try {{
                    var iframe = frames[i];
                    var doc = iframe.contentDocument;
                    if (doc) {{
                        var frameRect = iframe.getBoundingClientRect();
                        result = tryFind(doc, frameRect.left, frameRect.top);
                        if (result) return result;
                    }}
                }} catch(e) {{}}
            }}
            return null;
        }})()
        """
        
        for attempt in range(15):
            ret = self._send_cdp("Runtime.evaluate", {
                "expression": js_script,
                "returnByValue": True
            })
            
            if ret and "result" in ret and ret["result"].get("value"):
                slider_info = ret["result"]["value"]
                if slider_info.get("found"):
                    return slider_info
            
            print(f"[SOLVER] Slider not found... Retrying... (Attempt {attempt+1}/15)")
            time.sleep(1)
        
        return None

    def _get_track_width(self):
        """Dynamically get the slider track width using multiple selectors."""
        track_selectors_js = json.dumps(self.TRACK_SELECTORS)
        
        js_script = f"""
        (function() {{
            var selectors = {track_selectors_js};
            
            function tryFind(doc) {{
                for (var i = 0; i < selectors.length; i++) {{
                    var el = doc.querySelector(selectors[i]);
                    if (el) {{
                        var rect = el.getBoundingClientRect();
                        if (rect.width > 50) {{
                            return {{ width: rect.width, selector: selectors[i] }};
                        }}
                    }}
                }}
                return null;
            }}
            
            var result = tryFind(document);
            if (result) return result;
            
            var frames = document.getElementsByTagName('iframe');
            for (var i = 0; i < frames.length; i++) {{
                try {{
                    var doc = frames[i].contentDocument;
                    if (doc) {{
                        result = tryFind(doc);
                        if (result) return result;
                    }}
                }} catch(e) {{}}
            }}
            return null;
        }})()
        """
        
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": js_script,
            "returnByValue": True
        })
        
        if ret and "result" in ret and ret["result"].get("value"):
            info = ret["result"]["value"]
            print(f"[SOLVER] Track width: {info['width']}px (selector: {info['selector']})")
            return info["width"]
        
        # Fallback: try to get from viewport if track not found
        print("[SOLVER] ⚠ Could not detect track width, using fallback 340px")
        return 340

    def _verify_success(self):
        """Check if captcha was actually solved after dragging.
        Important: avoid false-positive when challenge still exists but text lacks RGV587.
        """
        js_check = """
        (function() {
            var sliderSelectors = [
                '#nc_1_n1z', '#nc_2_n1z', '[id^="nc_"][id$="_n1z"]',
                '.btn_slide', '.nc_iconfont.btn_slide', '.nc_scale .btn_slide', '.nc_wrapper .btn_slide',
                '.nc-slider-btn', '.slider-btn'
            ];
            var challengeSelectors = [
                '#nocaptcha', '.nc-container', '.nc_wrapper', '.nc_scale',
                '[id^="nc_"][id$="_n1t"]', '[id^="nc_"][id$="_n1z"]'
            ];
            var successKeywords = ['验证通过', '通过验证', '验证成功', '验证已通过'];

            function visible(el) {
                if (!el) return false;
                var rect = el.getBoundingClientRect();
                return el.offsetParent !== null && rect.width > 2 && rect.height > 2;
            }

            function scanDoc(doc) {
                var sliderVisible = false;
                var challengePresent = false;
                var successDetected = false;

                for (var i = 0; i < sliderSelectors.length; i++) {
                    var s = doc.querySelector(sliderSelectors[i]);
                    if (visible(s)) {
                        sliderVisible = true;
                        challengePresent = true;
                        break;
                    }
                }

                for (var j = 0; j < challengeSelectors.length; j++) {
                    var c = doc.querySelector(challengeSelectors[j]);
                    if (visible(c)) {
                        challengePresent = true;
                        break;
                    }
                }

                var text = (doc.body && doc.body.innerText) ? doc.body.innerText : '';
                for (var k = 0; k < successKeywords.length; k++) {
                    if (text.indexOf(successKeywords[k]) !== -1) {
                        successDetected = true;
                        break;
                    }
                }

                var okNode = doc.querySelector('.nc-lang-cnt, #nocaptcha, .nc-container');
                if (okNode) {
                    var cls = okNode.className || '';
                    var t = okNode.innerText || '';
                    if (cls.indexOf('nc-right') !== -1 || cls.indexOf('success') !== -1 || t.indexOf('通过') !== -1) {
                        successDetected = true;
                    }
                }

                var hasError = text.indexOf('RGV587_ERROR') !== -1 || text.indexOf('验证码') !== -1;
                return {
                    sliderVisible: sliderVisible,
                    challengePresent: challengePresent,
                    successDetected: successDetected,
                    hasError: hasError
                };
            }

            var agg = scanDoc(document);
            var frames = document.getElementsByTagName('iframe');
            for (var i = 0; i < frames.length; i++) {
                try {
                    var doc = frames[i].contentDocument;
                    if (!doc) continue;
                    var r = scanDoc(doc);
                    agg.sliderVisible = agg.sliderVisible || r.sliderVisible;
                    agg.challengePresent = agg.challengePresent || r.challengePresent;
                    agg.successDetected = agg.successDetected || r.successDetected;
                    agg.hasError = agg.hasError || r.hasError;
                } catch(e) {}
            }

            return {
                sliderGone: !agg.sliderVisible,
                challengeGone: !agg.challengePresent,
                successDetected: agg.successDetected,
                hasError: agg.hasError,
                noError: !agg.hasError
            };
        })()
        """
        
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": js_check,
            "returnByValue": True
        })
        
        if ret and "result" in ret and ret["result"].get("value"):
            result = ret["result"]["value"]
            print(
                "[SOLVER] Verification: "
                f"sliderGone={result.get('sliderGone')}, "
                f"challengeGone={result.get('challengeGone')}, "
                f"successDetected={result.get('successDetected')}, "
                f"hasError={result.get('hasError')}"
            )

            # 必须更严格：有成功信号，或挑战已消失且无错误
            if result.get("successDetected") and result.get("noError"):
                return True
            if result.get("challengeGone") and result.get("sliderGone") and result.get("noError"):
                return True

        return False

    def _generate_bezier_path(self, start_x, start_y, target_x, target_y):
        """Generate a realistic human-like mouse path using a Cubic Bezier curve."""
        # Calculate distance
        distance = ((target_x - start_x)**2 + (target_y - start_y)**2)**0.5
        
        # We need 4 points for a cubic bezier: P0, P1, P2, P3
        p0 = (start_x, start_y)
        p3 = (target_x, target_y)
        
        # Human drags usually bow slightly upwards or downwards
        bow = random.choice([1, -1]) * random.uniform(5, 20)
        
        # Randomize control points (P1, P2) along the path
        # P1 is usually 20-40% along the X axis, P2 is 60-80%
        p1_x = start_x + (target_x - start_x) * random.uniform(0.2, 0.4)
        p1_y = start_y + bow + random.uniform(-5, 5)
        
        p2_x = start_x + (target_x - start_x) * random.uniform(0.6, 0.8)
        p2_y = target_y + bow/2 + random.uniform(-5, 5) # Usually straightens out towards the end
        
        # Generate points along the curve
        num_points = int(distance / random.uniform(3, 8)) # One point every 3-8 pixels
        num_points = max(10, min(num_points, 100))
        
        path = []
        for i in range(num_points + 1):
            t = i / num_points
            
            # Bezier formula
            x = (1-t)**3 * p0[0] + 3 * (1-t)**2 * t * p1_x + 3 * (1-t) * t**2 * p2_x + t**3 * p3[0]
            y = (1-t)**3 * p0[1] + 3 * (1-t)**2 * t * p1_y + 3 * (1-t) * t**2 * p2_y + t**3 * p3[1]
            
            # Add micro-jitter (tremble)
            x += random.uniform(-1, 1)
            y += random.uniform(-1.5, 1.5)
            
            # Non-linear time distribution (Ease In-Out)
            # Starts slow, fast in middle, extremely slow at end
            ease_t = t * t * (3 - 2 * t)
            
            path.append((x, y, ease_t))
            
        return path

    def _do_drag(self, start_x, start_y, distance):
        """Execute a human-like drag using Bezier curves and overshoot mechanics."""
        
        # Pre-drag: move mouse to slider area first (human behavior)
        hover_x = start_x + random.uniform(-10, 10)
        hover_y = start_y + random.uniform(-10, 10)
        self._send_cdp("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": hover_x, "y": hover_y, "button": "none"
        })
        time.sleep(random.uniform(0.2, 0.6))  # Random pre-click delay (human hesitation)
        
        # Mouse Down
        time.sleep(random.uniform(0.1, 0.3)) # Micro hesitation before click
        self._send_cdp("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": start_x, "y": start_y, "button": "left", "clickCount": 1
        })
        time.sleep(random.uniform(0.1, 0.4)) # Hold down for a moment before moving
        
        # Overshoot mechanic (drag slightly past the goal, then pull back)
        overshoot = random.uniform(2, 6)
        target_x = start_x + distance + overshoot
        target_y = start_y + random.uniform(-3, 3)
        
        # Generate bezier path
        path = self._generate_bezier_path(start_x, start_y, target_x, target_y)
        
        duration = random.uniform(0.7, 1.8) # Total drag time
        
        last_t = 0
        current_x = start_x
        current_y = start_y
        
        for px, py, t in path:
            # Time delta based on ease_t
            dt = (t - last_t) * duration
            
            # Sometimes add micro-pause (stickiness)
            if random.random() < 0.05:
                dt += random.uniform(0.02, 0.08)
                
            if dt > 0:
                time.sleep(dt)
                
            # Prevent going backwards during the main drag (unless intentional overshoot correction)
            if px < current_x - 1 and px < target_x - overshoot:
                px = current_x # Clamp
                
            self._send_cdp("Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": px, "y": py, "button": "left"
            })
            
            current_x = px
            current_y = py
            last_t = t
            
        # Correction phase: Pull back the overshoot
        time.sleep(random.uniform(0.1, 0.3)) # Notice the overshoot
        correction_steps = random.randint(3, 6)
        final_x = start_x + distance
        
        for i in range(correction_steps):
            ratio = (i + 1) / correction_steps
            cx = current_x + (final_x - current_x) * ratio
            cy = current_y + random.uniform(-1, 1)
            self._send_cdp("Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": cx, "y": cy, "button": "left"
            })
            time.sleep(random.uniform(0.02, 0.05))
            
        current_x = final_x
            
        # Hold at end position before releasing
        time.sleep(random.uniform(0.3, 0.8))
        
        # Mouse Up
        self._send_cdp("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": current_x, "y": start_y, "button": "left", "clickCount": 1
        })
        
        return current_x

    def _close_page(self):
        """Close the dedicated solver page."""
        try:
            self._send_cdp("Page.close")
            time.sleep(1)
        except:
            pass
            
    def _reload_page(self):
        """Reload the page via CDP."""
        try:
            self._send_cdp("Page.reload", {"ignoreCache": False})
            time.sleep(3)  # Wait for page to reload
        except:
            pass

    def solve(self):
        """Main solve method with unlimited retry until success."""
        with self.lock:
            attempt = 0

            while True:
                attempt += 1
                print(f"\n[SOLVER] === Attempt {attempt} (unlimited) ===")

                # 每一轮都重新连接目标页签，避免 ws 失效后卡死
                if not self.connect_tab():
                    print("[SOLVER] ❌ connect_tab 失败，5秒后无限重试...")
                    time.sleep(5)
                    continue

                print("[SOLVER] Connected to browser. Starting solve loop...")
                self._bring_to_front()

                try:
                    # Step 1: Find Slider
                    slider_info = self._find_slider()
                    if not slider_info:
                        print("[SOLVER] Slider not found after retries. Reload + continue...")
                        self._reload_page()
                        time.sleep(random.uniform(1, 2))
                        if self.ws:
                            try:
                                self.ws.close()
                            except:
                                pass
                        continue

                    start_x = slider_info["x"] + (slider_info["width"] / 2)
                    start_y = slider_info["y"] + (slider_info["height"] / 2)

                    # Sanity check
                    if start_x < 10 or start_y < 10:
                        print(f"[SOLVER] Invalid coordinates: ({start_x}, {start_y}) -> reload + continue")
                        self._reload_page()
                        time.sleep(random.uniform(1, 2))
                        if self.ws:
                            try:
                                self.ws.close()
                            except:
                                pass
                        continue

                    # Human hesitation before getting track width
                    time.sleep(random.uniform(0.2, 0.5))

                    print(f"[SOLVER] Slider found at ({start_x:.0f}, {start_y:.0f}) "
                          f"[Selector: {slider_info.get('selector')}, Context: {slider_info.get('context')}]")

                    # Step 2: Get Track Width (dynamic)
                    track_width = self._get_track_width()
                    distance = track_width - slider_info["width"]

                    # Clamp distance to reasonable range
                    distance = max(100, min(distance, 500))
                    print(f"[SOLVER] Drag distance (base): {distance:.0f}px (track: {track_width:.0f}px, slider: {slider_info['width']:.0f}px)")

                    # Step 3: Execute Bezier Drag
                    self._bring_to_front()
                    self._do_drag(start_x, start_y, distance)
                    print("[SOLVER] Drag complete. Verifying...")

                    # Step 4: Verify Success
                    time.sleep(3)  # Wait for captcha response animation

                    if self._verify_success():
                        print("\033[92m[SOLVER] ✅ Verified: Captcha solved!\033[0m")

                        # Phase 3.1: We DO NOT close the page anymore.
                        # The userscript handles redirecting it back to standby.
                        print("[SOLVER] Leaving worker tab alive for userscript redirect.")

                        if self.ws:
                            self.ws.close()
                        return True

                    print("\033[93m[SOLVER] ❌ Verification failed. Reload + unlimited retry...\033[0m")
                    self._reload_page()
                    self._bring_to_front()
                    time.sleep(random.uniform(1, 2))
                    if self.ws:
                        try:
                            self.ws.close()
                        except:
                            pass

                except Exception as e:
                    print(f"[SOLVER] Error during steps: {e}")
                    import traceback
                    traceback.print_exc()
                    if self.ws:
                        try:
                            self.ws.close()
                        except:
                            pass
                    print("[SOLVER] Exception branch, 3秒后继续无限重试...")
                    time.sleep(3)
                    continue

if __name__ == "__main__":
    s = CaptchaSolver()
    if s.solve():
        print("Done.")
    else:
        print("Failed.")
