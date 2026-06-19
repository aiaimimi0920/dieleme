import requests
import websocket
import json
import time
import random
import threading
import math
import os
from urllib.parse import urlsplit, urlunsplit
from urllib.parse import quote

DEFAULT_CDP_PAGE_TARGET_LIMIT = 12


class CaptchaSolver:
    # Multiple selectors for different captcha variants
    SLIDER_SELECTORS = [
        '#nc_1_n1z', '#nc_2_n1z', '[id^="nc_"][id$="_n1z"]',
        '#nc_1_n1t', '#nc_2_n1t', '[id^="nc_"][id$="_n1t"]',  # NC captcha uses _n1t for button
        '.btn_slide', '.nc_iconfont.btn_slide', '.nc_scale .btn_slide', '.nc_wrapper .btn_slide',
        '.nc-slider-btn', '.slider-btn', '.nc-lang-cnt .btn_ok', '.btn_ok',
        '.icon-slide-arrow', '.nc-iconfont.icon-slide-arrow',  # NC specific
        '#mock-slider-handle'  # For testing with mock page
    ]
    TRACK_SELECTORS = [
        '#nc_1_n1t', '#nc_2_n1t', '[id^="nc_"][id$="_n1t"]',
        '.nc_scale', '.nc-lang-cnt', '.scale_text', '.slidetounlock', '.nc_wrapper',
        '.nc_scale_text', '[id^="nc_"][id*="scale_text"]',
        '.slider', '.nc-container .slider',  # NC track
        '#mock-slider-track'  # For testing with mock page
    ]

    def __init__(self, port=9222, target_url=None, cdp_endpoint=None, cancel_checker=None):
        configured_endpoint = (cdp_endpoint or os.getenv("FAPAI_CDP_ENDPOINT") or "").strip()
        if configured_endpoint:
            self.cdp_endpoint = configured_endpoint.rstrip("/")
            parsed = urlsplit(self.cdp_endpoint)
            self.port = parsed.port or port
        else:
            self.port = port
            self.cdp_endpoint = f"http://localhost:{self.port}"
        self.target_url = target_url
        self.ws_url = None
        self.ws = None
        self.message_id = 1
        self.lock = threading.Lock()
        self.target_id = None
        self.target_ws_url = None
        self._opened_target_ids = set()
        self.last_failure_reason = None
        self.cancel_checker = cancel_checker

    def _cancel_requested(self):
        checker = getattr(self, "cancel_checker", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception as error:
            print(f"[SOLVER] Cancel checker failed: {error}")
            return False

    def _stop_if_cancelled(self):
        if not self._cancel_requested():
            return False
        print("[SOLVER] Stop requested after manual resume/auth completion; exiting solver loop.")
        self.last_failure_reason = "cancelled"
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
        return True

    def _remember_target_tab(self, tab):
        if not isinstance(tab, dict):
            return
        target_id = str(tab.get("id") or "").strip()
        target_ws_url = str(tab.get("webSocketDebuggerUrl") or "").strip()
        if target_id:
            self.target_id = target_id
        if target_ws_url:
            self.target_ws_url = target_ws_url

    def _get_json(self, endpoint):
        last_error = None
        for timeout in (2, 4, 6):
            try:
                resp = requests.get(f"{self.cdp_endpoint}/json/{endpoint}", timeout=timeout)
                return resp.json()
            except Exception as error:
                last_error = error
        if last_error is not None:
            print(f"[SOLVER] Failed to fetch /json/{endpoint}: {last_error}")
        return None

    def _page_target_limit(self):
        raw_limit = os.getenv("FAPAI_CDP_MAX_PAGE_TARGETS", str(DEFAULT_CDP_PAGE_TARGET_LIMIT)).strip()
        try:
            limit = int(raw_limit)
        except ValueError:
            return DEFAULT_CDP_PAGE_TARGET_LIMIT
        if limit <= 0:
            return DEFAULT_CDP_PAGE_TARGET_LIMIT
        return limit

    def _reset_current_target(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.ws = None
        self.target_id = None
        self.target_ws_url = None

    def _close_cdp_target(self, target_id):
        target_id = str(target_id or "").strip()
        if not target_id:
            return False
        try:
            requests.get(
                f"{self.cdp_endpoint}/json/close/{quote(target_id, safe='')}",
                timeout=5,
            )
            return True
        except Exception as error:
            print(f"[SOLVER] Failed to close CDP target {target_id}: {error}")
            return False

    def _open_keepalive_tab(self):
        try:
            response = requests.put(f"{self.cdp_endpoint}/json/new?about:blank", timeout=5)
            payload = response.json()
            if isinstance(payload, dict):
                return str(payload.get("id") or "").strip() or None
        except Exception as error:
            print(f"[SOLVER] Failed to open keepalive tab before page compaction: {error}")
        return None

    def _compact_cdp_pages_if_needed(self, tabs=None, reserve_for_new_page=False):
        if tabs is None:
            tabs = self._get_json("list")
        if not isinstance(tabs, list):
            return {"triggered": False, "page_count": 0, "closed": 0}

        page_targets = [
            tab
            for tab in tabs
            if isinstance(tab, dict) and str(tab.get("type") or "") == "page"
        ]
        page_count = len(page_targets)
        target_limit = self._page_target_limit()
        trigger_count = max(target_limit - 1, 1) if reserve_for_new_page else target_limit
        if page_count < trigger_count:
            return {"triggered": False, "page_count": page_count, "closed": 0}

        print(
            f"[SOLVER] CDP page target count reached {page_count}; "
            "closing all page targets before retrying current task."
        )
        keepalive_target_id = self._open_keepalive_tab() if reserve_for_new_page else None
        self._reset_current_target()
        closed = 0
        for tab in page_targets:
            target_id = tab.get("id")
            if self._close_cdp_target(target_id):
                closed += 1
                self._opened_target_ids.discard(str(target_id or ""))
        self.target_id = None
        self.target_ws_url = None
        summary = {"triggered": True, "page_count": page_count, "closed": closed}
        if keepalive_target_id:
            summary["keepalive_target_id"] = keepalive_target_id
        return summary

    def _close_owned_target_tabs(self):
        owned_target_ids = [target_id for target_id in self._opened_target_ids if target_id]
        if not owned_target_ids:
            return 0
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

        closed = 0
        current_target_id = self.target_id
        for target_id in owned_target_ids:
            if self._close_cdp_target(target_id):
                closed += 1
            self._opened_target_ids.discard(target_id)
        if current_target_id in owned_target_ids:
            self.target_id = None
            self.target_ws_url = None
        return closed

    def _normalize_target_url(self, value):
        if not value:
            return ""
        return str(value).strip()

    def _rewrite_ws_url(self, ws_url):
        if not ws_url:
            return ws_url
        try:
            parsed_ws = urlsplit(ws_url)
            parsed_cdp = urlsplit(self.cdp_endpoint)
        except ValueError:
            return ws_url

        if parsed_ws.hostname not in {"127.0.0.1", "localhost"}:
            return ws_url

        target_netloc = parsed_cdp.netloc
        if not target_netloc:
            return ws_url
        return urlunsplit((parsed_ws.scheme, target_netloc, parsed_ws.path, parsed_ws.query, parsed_ws.fragment))

    def _open_target_tab(self):
        target_url = self._normalize_target_url(self.target_url)
        if not target_url:
            return None
        last_error = None
        for timeout in (5, 8, 12):
            try:
                response = requests.put(
                    f"{self.cdp_endpoint}/json/new?{quote(target_url, safe='/:%?=&_-')}",
                    timeout=timeout,
                )
                payload = response.json()
                if isinstance(payload, dict):
                    self._remember_target_tab(payload)
                    target_id = str(payload.get("id") or "").strip()
                    if target_id:
                        self._opened_target_ids.add(target_id)
                    return payload
            except Exception as error:
                last_error = error
        if last_error is not None:
            print(f"[SOLVER] Failed to open target tab: {last_error}")
        return None

    def _connect_to_target(self, target_ws, target_title):
        try:
            if self.ws:
                try:
                    self.ws.close()
                except Exception:
                    pass
            target_ws = self._rewrite_ws_url(target_ws)
            if target_ws:
                self.target_ws_url = target_ws
            print(f"[SOLVER] Connecting to tab: {target_title}")
            self.ws = websocket.create_connection(target_ws, suppress_origin=True)
            self.ws.settimeout(5)
            # Enable domains
            self._send_cdp("DOM.enable")
            self._send_cdp("Runtime.enable")
            self._send_cdp("Page.enable")

            # CDP Stealth Injection: Hide automation fingerprints
            self._send_cdp("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = window.chrome || {runtime: {}};
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                    Promise.resolve({state: Notification.permission}) :
                    originalQuery(parameters)
                );
                """
            })

            return True
        except Exception as e:
            self.ws = None
            print(f"[SOLVER] WS Connection failed: {e}")
            return False

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

            if method.startswith("Input.dispatchMouseEvent"):
                return None

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
        if tabs is None:
            if self.target_ws_url:
                print("[SOLVER] CDP target list unavailable; reusing cached target websocket.")
                if self._connect_to_target(self.target_ws_url, "cached solver target"):
                    return True
                print("[SOLVER] Cached target websocket failed; CDP target list is unavailable.")
            print(f"[SOLVER] CDP target list unavailable on {self.cdp_endpoint}.")
            return False

        compaction = self._compact_cdp_pages_if_needed(
            tabs,
            reserve_for_new_page=bool(self._normalize_target_url(self.target_url)),
        )
        if compaction.get("triggered"):
            tabs = self._get_json("list")
            if tabs is None:
                tabs = []

        if self.target_ws_url:
            print("[SOLVER] Reusing cached target websocket.")
            if self._connect_to_target(self.target_ws_url, "cached solver target"):
                return True
            print("[SOLVER] Cached target websocket failed; falling back to CDP discovery.")

        if not tabs:
            normalized_target_url = self._normalize_target_url(self.target_url)
            if not normalized_target_url:
                print(f"[SOLVER] No Chrome/Edge debug sessions found on port {self.port}.")
                return False
            opened_target = self._open_target_tab()
            if not isinstance(opened_target, dict):
                print(f"[SOLVER] No Chrome/Edge debug sessions found on port {self.port}.")
                return False
            target_ws = opened_target.get("webSocketDebuggerUrl")
            target_title = str(opened_target.get("title") or "")
            print(f"[SOLVER] 🆕 Opened requested solver target: {normalized_target_url}")
            return self._connect_to_target(target_ws, target_title)

        target_ws = None
        target_title = ""
        normalized_target_url = self._normalize_target_url(self.target_url)

        # Priority 0: exact requested target URL
        if normalized_target_url:
            for tab in tabs:
                url = self._normalize_target_url(tab.get("url", ""))
                if url == normalized_target_url:
                    self._remember_target_tab(tab)
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    print(f"[SOLVER] 🎯 Found requested solver target: {url}")
                    break
            if not target_ws and self.target_id:
                for tab in tabs:
                    if str(tab.get("id") or "") == self.target_id:
                        self._remember_target_tab(tab)
                        target_ws = tab.get("webSocketDebuggerUrl")
                        target_title = tab.get("title", "")
                        print(f"[SOLVER] ♻ Recovered cached solver target by id: {self.target_id}")
                        break
            if not target_ws:
                if self.target_id:
                    print(f"[SOLVER] Cached solver target {self.target_id} no longer present; reopening requested target.")
                    self.target_id = None
                    self.target_ws_url = None
                compaction = self._compact_cdp_pages_if_needed(tabs, reserve_for_new_page=True)
                if compaction.get("triggered"):
                    tabs = self._get_json("list") or []
                opened_target = self._open_target_tab()
                if isinstance(opened_target, dict):
                    target_ws = opened_target.get("webSocketDebuggerUrl")
                    target_title = str(opened_target.get("title") or "")
                    print(f"[SOLVER] 🆕 Opened requested solver target: {normalized_target_url}")

        # Priority 1: 100% targeted background worker currently solving
        if not target_ws:
            for tab in tabs:
                url = tab.get("url", "")
                if "__captcha_solver_bg=1" in url:
                    self._remember_target_tab(tab)
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    print(f"[SOLVER] ✨ Found dedicated worker (solving): {url}")
                    break

        # Priority 2: 100% targeted background worker in standby mode (useful if it's stuck or just transitioned)
        if not target_ws:
            for tab in tabs:
                url = tab.get("url", "")
                if "__captcha_worker_master=1" in url:
                    self._remember_target_tab(tab)
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    print(f"[SOLVER] ⏳ Found dedicated worker (standby): {url}")
                    break

        # Priority 2.5: sec.taobao.com / login.taobao.com pages (common captcha redirect destination)
        if not target_ws:
            for tab in tabs:
                url = tab.get("url", "")
                if "sec.taobao.com" in url or "login.taobao.com" in url:
                    self._remember_target_tab(tab)
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
                        self._remember_target_tab(tab)
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

        return self._connect_to_target(target_ws, target_title)

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
            if self._stop_if_cancelled():
                return None
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
        """Check if captcha was solved."""
        js_check = """
        (function() {
            var successKeywords = ['验证通过', '通过验证', '验证成功', '验证已通过', 'success'];
            var errorKeywords = ['失败', '错误', '再试', 'error', 'fail'];

            function scanDoc(doc) {
                var text = (doc.body && doc.body.innerText) ? doc.body.innerText : '';
                var hasSuccess = false;
                var hasError = false;

                for (var i = 0; i < successKeywords.length; i++) {
                    if (text.toLowerCase().indexOf(successKeywords[i].toLowerCase()) !== -1) {
                        hasSuccess = true;
                        break;
                    }
                }

                for (var j = 0; j < errorKeywords.length; j++) {
                    if (text.indexOf(errorKeywords[j]) !== -1) {
                        hasError = true;
                        break;
                    }
                }

                // Check for NC success class
                var container = doc.querySelector('.nc-container');
                if (container && container.className) {
                    if (container.className.indexOf('nc-success') !== -1) {
                        hasSuccess = true;
                    }
                }

                // Check if slider is still visible
                var slider = doc.querySelector('#nc_1_n1t, .icon-slide-arrow, #nc_1_n1z');
                var sliderVisible = !!(slider && slider.offsetParent !== null);
                var challenge = doc.querySelector('.nc-container, #nocaptcha, .nc_wrapper, .nc_scale');
                var challengeVisible = !!(challenge && challenge.offsetParent !== null);

                return {
                    hasSuccess: hasSuccess,
                    hasError: hasError,
                    sliderVisible: sliderVisible,
                    challengeVisible: challengeVisible
                };
            }

            var result = scanDoc(document);
            return {
                success: result.hasSuccess && !result.sliderVisible && !result.challengeVisible,
                successDetected: result.hasSuccess,
                sliderGone: !result.sliderVisible,
                challengeGone: !result.challengeVisible,
                hasError: result.hasError,
                noError: !result.hasError
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
                f"success={result.get('success')}, "
                f"sliderGone={result.get('sliderGone')}, "
                f"challengeGone={result.get('challengeGone')}, "
                f"hasError={result.get('hasError')}"
            )
            success = bool(result.get("success"))
            if "success" not in result:
                success = bool(result.get("successDetected"))
            slider_gone = bool(result.get("sliderGone", True))
            challenge_gone = bool(result.get("challengeGone", True))
            no_error = bool(result.get("noError", not result.get("hasError")))
            challenge_disappeared = result.get("sliderGone") is True and result.get("challengeGone") is True
            return bool(no_error and slider_gone and challenge_gone and (success or challenge_disappeared))

        return False

    def _generate_bezier_path(self, start_x, start_y, target_x, target_y):
        """Generate a realistic human-like mouse path using a Cubic Bezier curve."""
        distance = ((target_x - start_x)**2 + (target_y - start_y)**2)**0.5
        p0 = (start_x, start_y)
        p3 = (target_x, target_y)

        # More subtle bow - humans don't always bow much
        bow = random.choice([1, -1]) * random.uniform(2, 12)

        # More varied control points
        p1_x = start_x + (target_x - start_x) * random.uniform(0.15, 0.45)
        p1_y = start_y + bow + random.uniform(-8, 8)

        p2_x = start_x + (target_x - start_x) * random.uniform(0.55, 0.85)
        p2_y = target_y + bow/3 + random.uniform(-8, 8)

        # More varied point density
        num_points = int(distance / random.uniform(2, 6))
        num_points = max(15, min(num_points, 80))

        path = []
        for i in range(num_points + 1):
            t = i / num_points

            # Bezier formula
            x = (1-t)**3 * p0[0] + 3 * (1-t)**2 * t * p1_x + 3 * (1-t) * t**2 * p2_x + t**3 * p3[0]
            y = (1-t)**3 * p0[1] + 3 * (1-t)**2 * t * p1_y + 3 * (1-t) * t**2 * p2_y + t**3 * p3[1]

            # More realistic jitter - humans shake more
            x += random.uniform(-2, 2)
            y += random.uniform(-2.5, 2.5)

            # Custom easing - slow start, fast middle, very slow end
            ease_t = t * t * (3 - 2 * t)

            path.append((x, y, ease_t))

        return path

    def _do_drag(self, start_x, start_y, distance):
        """Enhanced drag with maximum human-like behavior."""
        target_x = start_x + distance
        target_y = start_y + random.uniform(-5, 5)

        # 1. Pre-approach: Move near slider
        pre_x = start_x - random.uniform(20, 40)
        pre_y = start_y + random.uniform(-15, 15)
        self._send_cdp("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": pre_x, "y": pre_y
        })
        time.sleep(random.uniform(0.5, 0.9))

        # 2. Approach slider
        self._send_cdp("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": start_x, "y": start_y
        })
        time.sleep(random.uniform(0.3, 0.6))

        # 3. Mouse down with hesitation
        self._send_cdp("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": start_x, "y": start_y,
            "button": "left", "clickCount": 1
        })
        time.sleep(random.uniform(0.25, 0.45))

        # 4. Generate bezier path
        path = self._generate_bezier_path(start_x, start_y, target_x, target_y)

        # 5. Execute drag with ultra-realistic timing
        for i, (px, py, t) in enumerate(path):
            progress = i / len(path)

            # Variable speed based on progress
            if progress < 0.15:  # Initial acceleration
                delay = random.uniform(0.025, 0.045)
            elif progress < 0.3:  # Speed up
                delay = random.uniform(0.015, 0.025)
            elif progress < 0.7:  # Maintain speed
                delay = random.uniform(0.010, 0.018)
            elif progress < 0.85:  # Deceleration
                delay = random.uniform(0.018, 0.030)
            else:  # Final slow
                delay = random.uniform(0.030, 0.050)

            # Random micro-pauses (more frequent)
            if random.random() < 0.20:
                delay += random.uniform(0.03, 0.08)

            time.sleep(delay)

            # Add more jitter
            jitter_x = random.uniform(-1.5, 1.5)
            jitter_y = random.uniform(-2, 2)

            self._send_cdp("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": px + jitter_x,
                "y": py + jitter_y,
                "button": "left"
            })

        # 6. Overshoot + correction
        time.sleep(random.uniform(0.12, 0.25))
        overshoot = random.uniform(4, 12)
        self._send_cdp("Input.dispatchMouseEvent", {
            "type": "mouseMoved",
            "x": target_x + overshoot,
            "y": target_y,
            "button": "left"
        })

        time.sleep(random.uniform(0.08, 0.15))

        # Multiple small corrections
        for _ in range(random.randint(2, 4)):
            target_x -= random.uniform(1, 3)
            target_y += random.uniform(-1, 1)
            self._send_cdp("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": target_x,
                "y": target_y,
                "button": "left"
            })
            time.sleep(random.uniform(0.020, 0.040))

        # 7. Hold before release (important!)
        time.sleep(random.uniform(0.9, 2.2))

        # 8. Release
        self._send_cdp("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": target_x, "y": target_y,
            "button": "left", "clickCount": 1
        })
        time.sleep(random.uniform(0.4, 0.7))

        return target_x

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

    def _page_challenge_summary(self):
        js_script = """
        (function() {
            function scan(doc) {
                var body = doc.body || document.body || null;
                var className = body && body.className ? String(body.className) : '';
                var bodyText = body && body.innerText ? String(body.innerText) : '';
                var title = doc.title || '';
                var slider = doc.querySelector('#nc_1_n1z, #nc_2_n1z, [id^="nc_"][id$="_n1z"], .btn_slide, .nc-slider-btn, .slider-btn');
                var hasSlider = !!(slider && slider.offsetParent !== null);
                var combined = (className + '\\n' + bodyText + '\\n' + title).toLowerCase();
                var hardBlock = combined.indexOf('baxia') !== -1 || combined.indexOf('punish') !== -1 || combined.indexOf('denyfromx5') !== -1;
                var explicitFailure = combined.indexOf('验证失败') !== -1 || combined.indexOf('点击框体重试') !== -1 || combined.indexOf('error:kzcfr9') !== -1;
                return {
                    hardBlock: hardBlock,
                    explicitFailure: explicitFailure,
                    hasSlider: hasSlider,
                    title: title,
                    className: className,
                    bodyText: bodyText.slice(0, 1000)
                };
            }
            var summary = scan(document);
            var frames = document.getElementsByTagName('iframe');
            for (var i = 0; i < frames.length; i++) {
                try {
                    var doc = frames[i].contentDocument;
                    if (!doc) continue;
                    var frameSummary = scan(doc);
                    summary.hardBlock = summary.hardBlock || frameSummary.hardBlock;
                    summary.explicitFailure = summary.explicitFailure || frameSummary.explicitFailure;
                    summary.hasSlider = summary.hasSlider || frameSummary.hasSlider;
                    if (!summary.title && frameSummary.title) summary.title = frameSummary.title;
                    if (!summary.className && frameSummary.className) summary.className = frameSummary.className;
                    if (!summary.bodyText && frameSummary.bodyText) summary.bodyText = frameSummary.bodyText;
                } catch (e) {}
            }
            return summary;
        })()
        """
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": js_script,
            "returnByValue": True
        })
        if ret and "result" in ret and ret["result"].get("value"):
            return ret["result"]["value"]
        return {
            "hardBlock": False,
            "explicitFailure": False,
            "hasSlider": False,
            "title": "",
            "className": "",
            "bodyText": "",
        }

    def _preflight_current_challenge(self):
        """Inspect the current CDP tab before slower solver fallbacks."""
        if not self.connect_tab():
            return {"connected": False, "manual_required": False, "has_slider": False}

        try:
            challenge_summary = self._page_challenge_summary()
        except Exception as error:
            print(f"[SOLVER] Challenge preflight failed: {error}")
            challenge_summary = {}

        has_slider = bool(challenge_summary.get("hasSlider"))
        if challenge_summary.get("hardBlock") and not has_slider:
            print("[SOLVER] ❌ Unsupported hard block detected; manual verification required.")
            self.last_failure_reason = "manual_required"
            if self.ws:
                try:
                    self.ws.close()
                except:
                    pass
            return {"connected": False, "manual_required": True, "has_slider": False}

        if not has_slider and self.ws:
            try:
                self.ws.close()
            except:
                pass
        return {"connected": has_slider, "manual_required": False, "has_slider": has_slider}

    def _headed_playwright_enabled(self):
        raw = os.getenv("FAPAI_SOLVER_ENABLE_HEADED_PLAYWRIGHT")
        if raw is not None:
            return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))

    def solve(self, max_attempts=50):
        """Main solve method - tries all methods in priority order."""
        with self.lock:
            self.last_failure_reason = None

            def finish(result):
                self._close_owned_target_tabs()
                return result

            connected_for_first_attempt = False
            if self._stop_if_cancelled():
                return finish(False)

            preflight = self._preflight_current_challenge()
            if preflight.get("manual_required"):
                return finish(False)
            if preflight.get("connected") and preflight.get("has_slider"):
                connected_for_first_attempt = True
                print("[SOLVER] Active slider challenge detected; using CDP method first.")
            else:
                if self._headed_playwright_enabled():
                    # Try ddddocr AI FIRST
                    try:
                        print("[SOLVER] 🤖 Attempting ddddocr AI识别...")
                        if self._solve_with_ddddocr():
                            return finish(True)
                    except Exception as e:
                        print(f"[SOLVER] ddddocr error: {e}")

                    # Try Playwright Stealth
                    try:
                        print("[SOLVER] ⭐ Attempting Playwright Stealth...")
                        if self._solve_with_playwright_stealth():
                            return finish(True)
                    except Exception as e:
                        print(f"[SOLVER] Playwright Stealth error: {e}")
                else:
                    print("[SOLVER] Skipping headed Playwright solvers because no DISPLAY/WAYLAND_DISPLAY is available.")

                # Try userscript method
                print("[SOLVER] Playwright failed, trying userscript method...")
                if self._solve_with_userscript():
                    return finish(True)

            # Fallback to CDP method
            print("[SOLVER] Userscript failed, trying CDP method...")
            attempt = 0

            while attempt < max_attempts:
                attempt += 1
                if self._stop_if_cancelled():
                    return finish(False)
                print(f"\n[SOLVER] === Attempt {attempt}/{max_attempts} ===")

                # 每一轮都重新连接目标页签，避免 ws 失效后卡死
                if connected_for_first_attempt:
                    connected_for_first_attempt = False
                elif not self.connect_tab():
                    print("[SOLVER] ❌ connect_tab 失败，5秒后重试...")
                    time.sleep(5)
                    continue

                print("[SOLVER] Connected to browser. Starting solve loop...")
                self._bring_to_front()

                try:
                    # Step 1: Find Slider
                    slider_info = self._find_slider()
                    if not slider_info:
                        challenge_summary = self._page_challenge_summary()
                        if challenge_summary.get("hardBlock") and not challenge_summary.get("hasSlider"):
                            print("[SOLVER] ❌ Unsupported hard block detected; manual verification required.")
                            self.last_failure_reason = "manual_required"
                            if self.ws:
                                try:
                                    self.ws.close()
                                except:
                                    pass
                            return finish(False)
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

                    # Human hesitation before action
                    time.sleep(random.uniform(0.4, 0.9))

                    print(f"[SOLVER] Slider found at ({start_x:.0f}, {start_y:.0f}) "
                          f"[Selector: {slider_info.get('selector')}, Context: {slider_info.get('context')}]")

                    # Step 2: Get Track Width (dynamic)
                    track_width = self._get_track_width()

                    # Calculate actual drag distance
                    # NC captcha needs slider to reach nearly the end (95-100%)
                    usable_track = track_width - slider_info["width"] - 4
                    distance = usable_track
                    distance = distance + random.uniform(-3, 2)

                    distance = max(100, min(distance, 1000))
                    print(f"[SOLVER] Drag distance: {distance:.0f}px (track: {track_width:.0f}px, slider: {slider_info['width']:.0f}px)")

                    # Step 3: Execute Bezier Drag
                    self._bring_to_front()
                    time.sleep(random.uniform(0.2, 0.5))
                    self._do_drag(start_x, start_y, distance)
                    print("[SOLVER] Drag complete. Verifying...")

                    # Step 4: Verify Success
                    time.sleep(random.uniform(2.5, 3.5))

                    if self._verify_success():
                        print("\033[92m[SOLVER] ✅ Verified: Captcha solved!\033[0m")
                        self.last_failure_reason = None

                        # Phase 3.1: We DO NOT close the page anymore.
                        # The userscript handles redirecting it back to standby.
                        print("[SOLVER] Leaving worker tab alive for userscript redirect.")

                        if self.ws:
                            self.ws.close()
                        return finish(True)

                    print("\033[93m[SOLVER] ❌ Verification failed. Reload + unlimited retry...\033[0m")
                    challenge_summary = self._page_challenge_summary()
                    if challenge_summary.get("explicitFailure"):
                        print("[SOLVER] ❌ Official challenge explicitly rejected the automated drag; manual verification required.")
                        self.last_failure_reason = "manual_required"
                        if self.ws:
                            try:
                                self.ws.close()
                            except:
                                pass
                        return finish(False)
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
                    print("[SOLVER] Exception branch, 3秒后继续重试...")
                    time.sleep(3)
                    continue

            print(f"[SOLVER] ❌ Max attempts ({max_attempts}) reached without success")
            self.last_failure_reason = "max_attempts_exceeded"
            return finish(False)

    def _solve_with_playwright(self):
        """Solve using Playwright."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled'])
                context = browser.new_context(viewport={'width': 1920, 'height': 1080})
                context.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined});')
                page = context.new_page()
                page.goto(self.target_url, timeout=30000)
                time.sleep(2)

                slider = page.query_selector('#nc_1_n1z, .btn_slide')
                if not slider:
                    browser.close()
                    return False

                box = slider.bounding_box()
                track = page.query_selector('#nc_1_n1t, .nc_scale')
                distance = track.bounding_box()['width'] - box['width'] - 10 if track else 260

                tracks = []
                current, mid, v = 0, distance * 4/5, 0
                while current < distance:
                    import random
                    a = random.randint(2,4) if current < mid else -random.randint(3,5)
                    s = v * 0.2 + 0.5 * a * 0.04
                    current += s
                    tracks.append(round(s))
                    v += a * 0.2
                tracks.extend([-random.randint(1,2) for _ in range(3)])

                start_x, start_y = box['x'] + box['width']/2, box['y'] + box['height']/2
                page.mouse.move(start_x, start_y)
                time.sleep(0.3)
                page.mouse.down()
                time.sleep(0.2)

                cx = start_x
                for t in tracks:
                    cx += t
                    page.mouse.move(cx, start_y + random.uniform(-1, 1))
                    time.sleep(0.01)

                time.sleep(0.5)
                page.mouse.up()
                time.sleep(3)

                success = '验证通过' in page.content()
                browser.close()
                return success
        except:
            return False

    def _solve_with_userscript(self):
        """Try to solve using injected userscript."""
        if not self.connect_tab():
            return False

        self._bring_to_front()
        time.sleep(1)

        # Check if slider exists
        slider_check = self._find_slider()
        if not slider_check:
            return False

        print("[SOLVER] Injecting userscript...")

        # Read userscript
        import os
        script_path = os.path.join(os.path.dirname(__file__), "..", "userscripts", "nc_captcha_solver.user.js")

        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                userscript = f.read()
                # Remove userscript header
                userscript = '\n'.join([line for line in userscript.split('\n')
                                       if not line.strip().startswith('// @')])
        except:
            print("[SOLVER] Userscript file not found")
            return False

        # Inject script
        self._send_cdp("Runtime.evaluate", {
            "expression": userscript
        })

        time.sleep(0.5)

        # Trigger solve
        trigger_js = "window.solveNCCaptcha ? window.solveNCCaptcha() : false"
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": trigger_js,
            "returnByValue": True
        })

        print("[SOLVER] Userscript triggered, waiting for result...")
        time.sleep(4)

        # Check success
        result = self._verify_success()

        if self.ws:
            try:
                self.ws.close()
            except:
                pass

        if result:
            print("[SOLVER] ✅ Userscript method succeeded!")

        return result

    def _solve_with_playwright_stealth(self):
        """Playwright Stealth - the method that worked before!"""
        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import Stealth
            import random
        except ImportError:
            return False

        print("[SOLVER] Starting Playwright Stealth...")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                page = browser.new_page()

                # Apply stealth - KEY!
                stealth = Stealth()
                stealth.apply_stealth_sync(page)

                page.goto(self.target_url, timeout=60000)
                time.sleep(3)

                slider = page.query_selector('#nc_1_n1z, .btn_slide, .nc-slider-btn')
                if not slider:
                    browser.close()
                    return False

                box = slider.bounding_box()
                track = page.query_selector('#nc_1_n1t, .nc_scale')
                distance = track.bounding_box()['width'] - box['width'] - 10 if track else 260

                print(f"[SOLVER] Playwright Stealth drag: {distance}px")

                tracks = []
                current, mid, v = 0, distance * 4/5, 0
                while current < distance:
                    a = random.randint(2,4) if current < mid else -random.randint(3,5)
                    s = v * 0.2 + 0.5 * a * 0.04
                    current += s
                    tracks.append(round(s))
                    v += a * 0.2
                tracks.extend([-random.randint(1,2) for _ in range(3)])

                start_x, start_y = box['x'] + box['width']/2, box['y'] + box['height']/2
                page.mouse.move(start_x, start_y)
                time.sleep(0.4)
                page.mouse.down()
                time.sleep(0.2)

                cx = start_x
                for t in tracks:
                    cx += t
                    page.mouse.move(cx, start_y + random.uniform(-1.5, 1.5))
                    time.sleep(0.015)

                time.sleep(0.5)
                page.mouse.up()
                time.sleep(3)

                success = '验证通过' in page.content()
                browser.close()

                if success:
                    print("[SOLVER] ✅ Playwright Stealth succeeded!")
                return success
        except Exception as e:
            print(f"[SOLVER] Playwright Stealth error: {e}")
            return False

    def _solve_with_ddddocr(self):
        """AI识别距离"""
        try:
            import ddddocr
            from playwright.sync_api import sync_playwright
            from playwright_stealth import Stealth
        except ImportError:
            return False

        try:
            det = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                page = browser.new_page()
                stealth = Stealth()
                stealth.apply_stealth_sync(page)

                page.goto(self.target_url, timeout=60000)
                time.sleep(3)

                slider = page.query_selector('#nc_1_n1z, .btn_slide')
                if not slider:
                    browser.close()
                    return False

                # 截图识别
                bg = page.query_selector('.nc_bg, canvas')
                slider_img = page.query_selector('.nc_slider')

                if bg and slider_img:
                    bg_bytes = bg.screenshot()
                    slider_bytes = slider_img.screenshot()
                    distance = det.slide_match(slider_bytes, bg_bytes)
                    print(f"[SOLVER] ddddocr识别距离: {distance}px")
                else:
                    track = page.query_selector('#nc_1_n1t')
                    box = slider.bounding_box()
                    distance = track.bounding_box()['width'] - box['width'] - 10 if track else 260

                # 拖动
                import random
                box = slider.bounding_box()
                start_x, start_y = box['x'] + box['width']/2, box['y'] + box['height']/2
                page.mouse.move(start_x, start_y)
                time.sleep(0.3)
                page.mouse.down()
                time.sleep(0.2)

                cx = start_x
                for i in range(int(distance/5)):
                    cx += 5
                    page.mouse.move(cx, start_y + random.uniform(-1, 1))
                    time.sleep(0.015)

                page.mouse.up()
                time.sleep(3)

                success = '验证通过' in page.content()
                browser.close()

                if success:
                    print("[SOLVER] ✅ ddddocr AI识别成功!")
                return success
        except Exception as e:
            print(f"[SOLVER] ddddocr error: {e}")
            return False


    def _solve_with_opencv(self):
        """OpenCV边缘检测找缺口 - 从博客学到的方案"""
        try:
            import cv2
            import numpy as np
            from playwright.sync_api import sync_playwright
            from playwright_stealth import Stealth
        except ImportError:
            return False

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                stealth = Stealth()
                stealth.apply_stealth_sync(page)

                page.goto(self.target_url, timeout=60000)
                time.sleep(3)

                slider = page.query_selector('#nc_1_n1z, .btn_slide')
                if not slider:
                    browser.close()
                    return False

                # 截图并用OpenCV找缺口
                bg_area = page.query_selector('.nc_wrapper')
                if bg_area:
                    bg_bytes = bg_area.screenshot()
                    nparr = np.frombuffer(bg_bytes, np.uint8)
                    bg = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
                    bg = cv2.GaussianBlur(bg, (3,3), 0)
                    edges = cv2.Canny(bg, 100, 200)

                    height, width = edges.shape
                    gap_x = None
                    for x in range(50, width-50):
                        if np.sum(edges[:, x:x+1]) > height * 20:
                            left = np.mean(bg[:, max(0,x-10):x])
                            right = np.mean(bg[:, x:min(width,x+10)])
                            if abs(left-right) > 30:
                                gap_x = x
                                break

                    distance = gap_x - 40 if gap_x else 260
                    print(f"[SOLVER] OpenCV检测距离: {distance}px")
                else:
                    distance = 260

                # 拖动
                import random
                box = slider.bounding_box()
                start_x, start_y = box['x'] + box['width']/2, box['y'] + box['height']/2
                page.mouse.move(start_x, start_y)
                time.sleep(0.4)
                page.mouse.down()
                time.sleep(0.2)

                cx = start_x
                for i in range(int(distance/5)):
                    cx += 5
                    page.mouse.move(cx, start_y + random.uniform(-1,1))
                    time.sleep(0.015)

                page.mouse.up()
                time.sleep(3)

                success = '验证通过' in page.content()
                browser.close()

                if success:
                    print("[SOLVER] ✅ OpenCV边缘检测成功!")
                return success
        except Exception as e:
            print(f"[SOLVER] OpenCV error: {e}")
            return False

if __name__ == "__main__":
    s = CaptchaSolver()
    if s.solve():
        print("Done.")
    else:
        print("Failed.")
