import requests
import websocket
import json
import time
import random
import threading
import math
import os
import re
import subprocess
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(_sys.stderr, "reconfigure"):
    try:
        _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.parse import quote

# Reconfigure stdout/stderr for safe encoding on Windows (GBK) consoles
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(_sys.stderr, "reconfigure"):
    try:
        _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_CDP_PAGE_TARGET_LIMIT = 12
LOCAL_MOCK_VERIFY_MODES = {"strict_success_text", "teardown_only", "explicit_fail", "near_miss", "retry_then_success"}


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
        self.current_target_url = None
        self._target_activation_verified = False
        self._opened_target_ids = set()
        self.last_failure_reason = None
        self._last_mock_terminal_state = None
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
        target_url = str(tab.get("url") or "").strip()
        if target_id:
            if target_id != self.target_id:
                self._target_activation_verified = False
            self.target_id = target_id
        if target_ws_url:
            self.target_ws_url = target_ws_url
        if target_url:
            self.current_target_url = target_url

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
        self.current_target_url = None

    @staticmethod
    def _is_login_url(value):
        target_url = str(value or "").strip().lower()
        if not target_url:
            return False
        return (
            "login.taobao.com" in target_url
            or "login.tmall.com" in target_url
            or "third-party-cookie" in target_url
            or "/passport/" in target_url
            or "/login_jump" in target_url
            or "/_____tmd_____/page/login" in target_url
        )

    @classmethod
    def _is_manual_challenge_url(cls, value):
        target_url = str(value or "").strip().lower()
        if not target_url:
            return False
        return (
            "/_____tmd_____/punish" in target_url
            or "x5secdata=" in target_url
            or "x5step=" in target_url
            or cls._is_login_url(target_url)
        )

    @classmethod
    def _is_challenge_tab(cls, tab):
        if not isinstance(tab, dict):
            return False
        tab_url = str(tab.get("url") or "").strip()
        if cls._is_manual_challenge_url(tab_url):
            return True
        title = re.sub(r"\s+", " ", str(tab.get("title") or "")).strip().lower()
        return title in {
            "captcha verification",
            "验证码拦截",
            "安全验证",
        }

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
            "closing stale page targets before retrying current task."
        )
        keepalive_target_id = self._open_keepalive_tab()
        preserve_target_id = keepalive_target_id or str(page_targets[0].get("id") or "").strip()
        self._reset_current_target()
        closed = 0
        for tab in page_targets:
            target_id = tab.get("id")
            if str(target_id or "").strip() == preserve_target_id:
                continue
            if self._close_cdp_target(target_id):
                closed += 1
                self._opened_target_ids.discard(str(target_id or ""))
        self.target_id = None
        self.target_ws_url = None
        summary = {"triggered": True, "page_count": page_count, "closed": closed}
        if keepalive_target_id:
            summary["keepalive_target_id"] = keepalive_target_id
        elif preserve_target_id:
            summary["preserved_target_id"] = preserve_target_id
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
            self.current_target_url = None
        return closed

    def _prune_duplicate_challenge_tabs(self, tabs):
        """Keep only the active punish target before a solve attempt.

        Each collection scope owns one active challenge at a time. Failed
        requests and cooldown recovery can leave punish pages for older item
        routes in the shared browser profile; those pages may compete for the
        same challenge/session state. Preserve one page for the requested scope
        and close only duplicate pages in that scope. Login, normal auction
        pages, and the other collection scope remain untouched.
        """
        if not isinstance(tabs, list):
            return {"closed": 0, "kept": None}
        requested_route = self._solver_target_route(self.target_url)
        requested_scope = self._solver_target_scope(self.target_url)
        if not requested_route and not requested_scope:
            return {"closed": 0, "kept": None}
        challenge_tabs = []
        candidates = []
        for tab in tabs:
            if not isinstance(tab, dict) or tab.get("type") != "page":
                continue
            tab_url = str(tab.get("url") or "").strip()
            if not self._is_challenge_tab(tab):
                continue
            if self._is_login_url(tab_url):
                continue
            target_id = str(tab.get("id") or "").strip()
            if not target_id or not tab.get("webSocketDebuggerUrl"):
                continue
            candidate_scope = self._solver_target_scope(tab_url)
            if requested_scope:
                if candidate_scope != requested_scope:
                    continue
            elif self._solver_target_route(tab_url) != requested_route:
                continue
            challenge_tabs.append(tab)
            candidates.append(tab)
        preserve_id = str(self.target_id or "").strip()
        if not any(str(tab.get("id") or "").strip() == preserve_id for tab in candidates):
            preserve_id = str(candidates[0].get("id") or "").strip() if candidates else ""
        closed = 0
        for tab in challenge_tabs:
            target_id = str(tab.get("id") or "").strip()
            if target_id == preserve_id:
                continue
            if self._close_cdp_target(target_id):
                closed += 1
                self._opened_target_ids.discard(target_id)
        if closed:
            print(
                f"[SOLVER] Compacted stale challenge targets for "
                f"{requested_scope or 'route ' + requested_route}: "
                f"kept={preserve_id} closed={closed}"
            )
        return {"closed": closed, "kept": preserve_id or None}

    def _normalize_target_url(self, value):
        if not value:
            return ""
        target_url = str(value).strip()
        if not target_url:
            return ""
        try:
            parsed = urlsplit(target_url)
        except ValueError:
            return target_url
        scheme = (parsed.scheme or "").lower()
        netloc = parsed.netloc
        if scheme in {"http", "https", "ws", "wss", "file"}:
            host = (parsed.hostname or "").lower()
            username = parsed.username or ""
            password = parsed.password or ""
            userinfo = username
            if password:
                userinfo = f"{userinfo}:{password}" if userinfo else f":{password}"
            if userinfo:
                userinfo = f"{userinfo}@"
            port = parsed.port
            default_port = 80 if scheme in {"http", "ws"} else 443
            normalized_netloc = f"{userinfo}{host}"
            if port and scheme != "file" and port != default_port:
                normalized_netloc = f"{normalized_netloc}:{port}"
            if scheme == "file" and parsed.netloc:
                normalized_netloc = parsed.netloc.lower()
            netloc = normalized_netloc
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        normalized_query = urlencode(sorted(query_pairs), doseq=True)
        path = parsed.path
        if scheme in {"http", "https", "ws", "wss"}:
            path = re.sub(r"/{2,}", "/", path)
        return urlunsplit((scheme, netloc, path, normalized_query, ""))

    def _solver_target_route(self, value):
        normalized = self._normalize_target_url(value)
        if not normalized:
            return ""
        try:
            parsed = urlsplit(normalized)
        except ValueError:
            return normalized
        path = parsed.path.replace("//", "/")
        if "/_____tmd_____/" in path:
            path = path.split("/_____tmd_____/", 1)[0]
        query_pairs = []
        is_taobao_list_route = bool(
            (parsed.hostname or "").lower() == "sf.taobao.com"
            and re.fullmatch(r"/list/[^/]+\.htm", path)
        )
        if not is_taobao_list_route:
            for key, item in parse_qsl(parsed.query, keep_blank_values=True):
                if key in {"__captcha_solver_bg", "track_id", "x5step", "x5secdata"}:
                    continue
                query_pairs.append((key, item))
        query = urlencode(sorted(query_pairs), doseq=True)
        return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))

    def _solver_target_scope(self, value):
        """Classify auction URLs into the independent list/detail challenge scopes."""
        normalized = self._normalize_target_url(value)
        if not normalized:
            return ""
        try:
            parsed = urlsplit(normalized)
        except ValueError:
            return ""
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "/").replace("//", "/").lower()
        if host == "sf-item.taobao.com" or "/sf_item/" in path:
            return "detail"
        if host == "sf.taobao.com" and "/list/" in path:
            return "seed"
        if "/punish" in path and "/list/" in path:
            return "seed"
        return ""

    def _manual_challenge_matches_requested_target(self, value):
        if self._is_login_url(value):
            return True
        requested_route = self._solver_target_route(self.target_url)
        requested_scope = self._solver_target_scope(self.target_url)
        if not requested_route:
            return True
        challenge_route = self._solver_target_route(value)
        if not challenge_route:
            return False
        challenge_scope = self._solver_target_scope(value)
        if requested_scope and challenge_scope:
            return requested_scope == challenge_scope
        return challenge_route == requested_route

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
                    f"{self.cdp_endpoint}/json/new?{quote(target_url, safe='/:%-._~')}",
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
            self.ws = websocket.create_connection(target_ws, suppress_origin=True, timeout=5)
            self.ws.settimeout(5)
            # Enable domains
            dom_ready = self._send_cdp("DOM.enable")
            runtime_ready = self._send_cdp("Runtime.enable")
            page_ready = self._send_cdp("Page.enable")
            if dom_ready is None or runtime_ready is None or page_ready is None:
                raise RuntimeError("CDP bootstrap failed for target websocket")

            # CDP Stealth Injection: Hide automation fingerprints
            stealth_js = """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined, configurable: true});
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
            disable_stealth = os.getenv("FAPAI_SOLVER_DISABLE_STEALTH", "0").strip().lower() in {
                "1", "true", "yes", "on"
            }
            if not disable_stealth:
                self._send_cdp("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js})
                # The challenge page is already loaded; also patch the current document.
                self._send_cdp("Runtime.evaluate", {"expression": stealth_js, "returnByValue": True})

            return True
        except Exception as e:
            if self.ws:
                try:
                    self.ws.close()
                except Exception:
                    pass
            self.ws = None
            if self._is_manual_challenge_url(self.current_target_url):
                self.last_failure_reason = "manual_required"
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
            start_time = time.time()
            timeout_seconds = 12 if "captureScreenshot" in method else 5
            while time.time() - start_time < timeout_seconds:
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

        if self.target_ws_url:
            pruning = self._prune_duplicate_challenge_tabs(tabs)
            if pruning.get("closed"):
                refreshed_tabs = self._get_json("list")
                if isinstance(refreshed_tabs, list):
                    tabs = refreshed_tabs
            print("[SOLVER] Reusing cached target websocket.")
            if self._connect_to_target(self.target_ws_url, "cached solver target"):
                return True
            print("[SOLVER] Cached target websocket failed; falling back to CDP discovery.")

        compaction = self._compact_cdp_pages_if_needed(
            tabs,
            reserve_for_new_page=bool(self._normalize_target_url(self.target_url)),
        )
        if compaction.get("triggered"):
            tabs = self._get_json("list")
            if tabs is None:
                tabs = []

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
            print(f"[SOLVER] [NEW] Opened requested solver target: {normalized_target_url}")
            return self._connect_to_target(target_ws, target_title)

        pruning = self._prune_duplicate_challenge_tabs(tabs)
        kept_challenge_target_id = str(pruning.get("kept") or "").strip()
        if pruning.get("closed") or self.target_id:
            refreshed_tabs = self._get_json("list")
            if isinstance(refreshed_tabs, list):
                tabs = refreshed_tabs

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
                    print(f"[SOLVER] [TARGET] Found requested solver target: {url}")
                    break
            if not target_ws and kept_challenge_target_id:
                for tab in tabs:
                    if str(tab.get("id") or "").strip() != kept_challenge_target_id:
                        continue
                    self._remember_target_tab(tab)
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    print("[SOLVER] Reusing the unique challenge target for this collection scope.")
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
                for tab in tabs:
                    if (
                        self._is_manual_challenge_url(tab.get("url"))
                        and self._manual_challenge_matches_requested_target(tab.get("url"))
                    ):
                        self._remember_target_tab(tab)
                        target_ws = tab.get("webSocketDebuggerUrl")
                        target_title = tab.get("title", "")
                        print("[SOLVER] Reusing existing manual challenge target.")
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
                    print(f"[SOLVER] [NEW] Opened requested solver target: {normalized_target_url}")

        # Priority 1: 100% targeted background worker currently solving
        if not target_ws:
            requested_scope = self._solver_target_scope(self.target_url)
            for tab in tabs:
                url = tab.get("url", "")
                if "__captcha_solver_bg=1" in url:
                    if requested_scope and self._solver_target_scope(url) != requested_scope:
                        continue
                    self._remember_target_tab(tab)
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    print(f"[SOLVER] [STAR] Found dedicated worker (solving): {url}")
                    break

        # Priority 2: 100% targeted background worker in standby mode (useful if it's stuck or just transitioned)
        if not target_ws:
            for tab in tabs:
                url = tab.get("url", "")
                if "__captcha_worker_master=1" in url:
                    self._remember_target_tab(tab)
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    print(f"[SOLVER] [HOURGLASS] Found dedicated worker (standby): {url}")
                    break

        # Priority 2.5: sec.taobao.com / login.taobao.com pages (common captcha redirect destination)
        if not target_ws:
            for tab in tabs:
                url = tab.get("url", "")
                if "sec.taobao.com" in url or "login.taobao.com" in url:
                    self._remember_target_tab(tab)
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    print(f"[SOLVER] [LOCK] Found sec/login page (likely captcha redirect): {url}")
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
             print("[SOLVER] [X] No relevant debug tag found.")
             # Let's see what tabs are open just for debugging
             print("[SOLVER] Currently open tabs:")
             for t in tabs[:5]:
                 print(f"  - {t.get('title')[:30]} | {t.get('url')[:50]}")
             return False

        return self._connect_to_target(target_ws, target_title)

    def _activate_target_tab(self):
        """Activate the exact CDP target before any physical mouse operation."""
        self._target_activation_verified = False
        target_id = str(self.target_id or "").strip()
        if not target_id:
            return False
        last_error = None
        for timeout in (2, 4, 6):
            try:
                response = requests.get(
                    f"{self.cdp_endpoint}/json/activate/{quote(target_id, safe='')}",
                    timeout=timeout,
                )
                if response.status_code < 400:
                    self._target_activation_verified = True
                    return True
                last_error = RuntimeError(f"CDP target activation returned HTTP {response.status_code}")
            except Exception as error:
                last_error = error
        if last_error is not None:
            print(f"[SOLVER] Failed to activate target tab {target_id}: {last_error}")
        return False

    def _bring_to_front(self):
        """Bring the exact captcha tab forward so OS mouse input hits that tab."""
        activated = self._activate_target_tab()
        if activated:
            time.sleep(0.15)
            return True
        try:
            brought_to_front = self._send_cdp("Page.bringToFront") is not None
            # Best-effort focus; some Chromium builds still need explicit window focus.
            focused = self._send_cdp("Runtime.evaluate", {
                "expression": "try { window.focus(); document.body && document.body.focus && document.body.focus(); } catch(e) {}",
                "returnByValue": True
            }) is not None
            time.sleep(0.15)
            return bool(brought_to_front or focused)
        except Exception as e:
            print(f"[SOLVER] bringToFront failed: {e}")
            return False

    def _find_slider_once(self):
        """Run one slider lookup pass and return slider info dict or None."""
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
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": js_script,
            "returnByValue": True
        })

        if ret and "result" in ret and ret["result"].get("value"):
            slider_info = ret["result"]["value"]
            if slider_info.get("found"):
                return slider_info
        return None

    def _find_slider(self, max_retries=15, retry_delay=1):
        """Find slider element using multiple selectors. Returns slider info dict or None."""

        attempts = max(int(max_retries or 0), 1)
        for attempt in range(attempts):
            if self._stop_if_cancelled():
                return None
            slider_info = self._find_slider_once()
            if slider_info:
                return slider_info

            print(f"[SOLVER] Slider not found... Retrying... (Attempt {attempt+1}/{attempts})")
            if attempt + 1 < attempts and retry_delay:
                time.sleep(retry_delay)

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

    def _get_track_rect(self):
        """Return the live track rectangle so drag distance follows the current handle position."""
        track_selectors_js = json.dumps(self.TRACK_SELECTORS)
        js_script = f"""
        (function() {{
            var selectors = {track_selectors_js};
            function find(doc) {{
                for (var i = 0; i < selectors.length; i++) {{
                    var el = doc.querySelector(selectors[i]);
                    if (!el) continue;
                    var rect = el.getBoundingClientRect();
                    if (rect.width > 50 && rect.height > 5) {{
                        var handle = doc.querySelector('#nc_1_n1z, #nc_2_n1z, [id^="nc_"][id$="_n1z"], .btn_slide, .nc-slider-btn');
                        return {{
                            left: rect.left,
                            top: rect.top,
                            width: rect.width,
                            height: rect.height,
                            offsetWidth: el.offsetWidth,
                            handleOffsetLeft: handle ? handle.offsetLeft : null,
                            handleOffsetWidth: handle ? handle.offsetWidth : null
                        }};
                    }}
                }}
                return null;
            }}
            var result = find(document);
            if (result) return result;
            var frames = document.getElementsByTagName('iframe');
            for (var i = 0; i < frames.length; i++) {{
                try {{
                    var doc = frames[i].contentDocument;
                    if (doc) {{ result = find(doc); if (result) return result; }}
                }} catch (e) {{}}
            }}
            return null;
        }})()
        """
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": js_script,
            "returnByValue": True,
        })
        if ret and "result" in ret and ret["result"].get("value"):
            value = ret["result"]["value"]
            if isinstance(value, dict) and float(value.get("width") or 0) > 50:
                return value
        return None

    def _verify_success(self):
        """Check if captcha was solved."""
        local_mock_mode = self._local_mock_verification_mode()
        self._last_mock_terminal_state = None
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
            var mockState = window.__mockSliderState || null;
            var mockStatusNode = document.getElementById('mock-slider-status');
            var mockTrack = document.getElementById('mock-slider-track');
            var mockHandle = document.getElementById('mock-slider-handle');
            var mockStatusText = mockStatusNode && mockStatusNode.innerText ? String(mockStatusNode.innerText) : '';
            var mockChallengeVisible = !!(
                (mockTrack && mockTrack.offsetParent !== null) ||
                (mockHandle && mockHandle.offsetParent !== null)
            );
            return {
                success: result.hasSuccess && !result.sliderVisible && !result.challengeVisible,
                successDetected: result.hasSuccess,
                sliderGone: !result.sliderVisible,
                challengeGone: !result.challengeVisible,
                hasError: result.hasError,
                noError: !result.hasError,
                mockStateSuccess: !!(mockState && mockState.success),
                mockStateFailure: !!(mockState && mockState.failure),
                mockResolution: mockState && mockState.resolution ? String(mockState.resolution) : '',
                mockStatusText: mockStatusText,
                mockVerifyMode: mockState && mockState.config && mockState.config.verifyMode ? String(mockState.config.verifyMode) : '',
                mockChallengeVisible: mockChallengeVisible
            };
        })()
        """

        ret = self._send_cdp("Runtime.evaluate", {
            "expression": js_check,
            "returnByValue": True
        })

        if ret and "result" in ret and ret["result"].get("value"):
            result = ret["result"]["value"]
            log_parts = [
                "[SOLVER] Verification: "
                f"success={result.get('success')}",
                f"sliderGone={result.get('sliderGone')}",
                f"challengeGone={result.get('challengeGone')}",
                f"hasError={result.get('hasError')}",
            ]
            if local_mock_mode:
                log_parts.extend([
                    f"mockSuccess={result.get('mockStateSuccess')}",
                    f"mockFailure={result.get('mockStateFailure')}",
                    f"mockMode={result.get('mockVerifyMode') or local_mock_mode}",
                ])
            print(", ".join(log_parts))
            success = bool(result.get("success"))
            if "success" not in result:
                success = bool(result.get("successDetected"))
            slider_gone = bool(result.get("sliderGone", True))
            challenge_gone = bool(result.get("challengeGone", True))
            no_error = bool(result.get("noError", not result.get("hasError")))
            challenge_disappeared = result.get("sliderGone") is True and result.get("challengeGone") is True
            if local_mock_mode:
                mock_state_success = bool(result.get("mockStateSuccess"))
                mock_state_failure = bool(result.get("mockStateFailure"))
                mock_challenge_visible = bool(result.get("mockChallengeVisible"))
                mock_status_text = str(result.get("mockStatusText") or "")
                mock_status_lower = mock_status_text.lower()
                mock_has_success_text = any(
                    keyword in mock_status_text for keyword in ("验证通过", "通过验证", "验证成功", "验证已通过")
                ) or ("success" in mock_status_lower)
                mock_has_error_text = any(
                    keyword in mock_status_text for keyword in ("失败", "错误", "再试")
                ) or ("error" in mock_status_lower) or ("fail" in mock_status_lower)
                if mock_state_failure or mock_has_error_text or not no_error:
                    if local_mock_mode == "explicit_fail":
                        self._last_mock_terminal_state = "manual_required"
                    elif mock_state_failure:
                        self._last_mock_terminal_state = "terminal_failure"
                    return False
                if local_mock_mode == "teardown_only":
                    return bool(mock_state_success and not mock_challenge_visible)
                return bool(mock_state_success and mock_has_success_text)
            return bool(no_error and slider_gone and challenge_gone and (success or challenge_disappeared))

        return False

    def _wait_for_verification_success(self, max_checks=6):
        """Poll verification briefly because challenge UI teardown can lag behind the drag."""
        checks = max(int(max_checks or 0), 1)
        local_mock_target = self._is_local_mock_slider_target()
        local_mock_mode = self._local_mock_verification_mode()
        self._last_mock_terminal_state = None
        if local_mock_target:
            checks = max(checks, 10)
        for check_index in range(checks):
            if self._stop_if_cancelled():
                return False
            if self._verify_success():
                return True
            if not local_mock_target:
                challenge_summary = self._page_challenge_summary()
                if challenge_summary.get("authenticatedPage"):
                    print("[SOLVER] Auction page became accessible after drag; treating as solved.")
                    return True
            terminal_state = self._last_mock_terminal_state
            if terminal_state == "manual_required":
                self.last_failure_reason = "manual_required"
                return False
            if terminal_state == "terminal_failure":
                return False
            if local_mock_target and local_mock_mode == "explicit_fail":
                challenge_summary = self._page_challenge_summary()
                if challenge_summary.get("explicitFailure"):
                    self.last_failure_reason = "manual_required"
                    return False
            if check_index < checks - 1:
                if local_mock_target:
                    time.sleep(0.15)
                else:
                    time.sleep(random.uniform(0.6, 1.1))
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

    def _dispatch_mouse(self, event_type, x, y, *, buttons=0, click_count=0):
        """Send a CDP mouse event. Drag moves MUST keep buttons=1 or NC ignores the path."""
        params = {
            "type": event_type,
            "x": x,
            "y": y,
            "pointerType": "mouse",
            "modifiers": 0,
            "buttons": int(buttons),
        }
        if event_type in {"mousePressed", "mouseReleased"}:
            params["button"] = "left"
            params["clickCount"] = click_count or 1
        elif event_type == "mouseMoved" and buttons:
            params["button"] = "left"
        result = self._send_cdp("Input.dispatchMouseEvent", params)
        if result is not None:
            return True
        print("[SOLVER] CDP mouse input is unavailable; manual verification required.")
        self.last_failure_reason = "manual_required"
        return False

    def _do_drag(self, start_x, start_y, distance):
        """Slow human-like drag. NC rejects paths that are too fast or missing button state."""
        target_x = start_x + distance
        target_y = start_y + random.uniform(-3, 3)

        # 1. Pre-approach: Move near slider (no button)
        pre_x = start_x - random.uniform(18, 36)
        pre_y = start_y + random.uniform(-10, 10)
        if not self._dispatch_mouse("mouseMoved", pre_x, pre_y, buttons=0):
            return None
        time.sleep(random.uniform(0.55, 1.05))

        # 2. Approach slider
        if not self._dispatch_mouse("mouseMoved", start_x, start_y, buttons=0):
            return None
        time.sleep(random.uniform(0.35, 0.75))

        # 3. Mouse down with hesitation
        if not self._dispatch_mouse(
            "mousePressed", start_x, start_y, buttons=1, click_count=1
        ):
            return None
        time.sleep(random.uniform(0.18, 0.38))

        # 4. Generate bezier path
        path = self._generate_bezier_path(start_x, start_y, target_x, target_y)

        # 5. Execute drag with a 2.4–4.2s human velocity curve
        n = max(len(path), 1)
        for i, (px, py, _t) in enumerate(path):
            progress = i / n
            if progress < 0.12:
                delay = random.uniform(0.035, 0.060)
            elif progress < 0.35:
                delay = random.uniform(0.022, 0.038)
            elif progress < 0.72:
                delay = random.uniform(0.018, 0.032)
            elif progress < 0.88:
                delay = random.uniform(0.028, 0.048)
            else:
                delay = random.uniform(0.040, 0.070)
            if random.random() < 0.14:
                delay += random.uniform(0.04, 0.10)
            time.sleep(delay)
            if not self._dispatch_mouse(
                "mouseMoved",
                px + random.gauss(0, 0.7),
                py + random.gauss(0, 1.1),
                buttons=1,
            ):
                return None

        # 6. Small overshoot + settle (keep the button down)
        time.sleep(random.uniform(0.08, 0.16))
        overshoot = random.uniform(0, 3)
        if not self._dispatch_mouse(
            "mouseMoved", target_x + overshoot, target_y, buttons=1
        ):
            return None
        time.sleep(random.uniform(0.06, 0.12))
        for _ in range(random.randint(2, 4)):
            target_x -= random.uniform(0.6, 2.2)
            target_y += random.uniform(-0.8, 0.8)
            if not self._dispatch_mouse("mouseMoved", target_x, target_y, buttons=1):
                return None
            time.sleep(random.uniform(0.025, 0.050))
        if not self._dispatch_mouse("mouseMoved", start_x + distance, target_y, buttons=1):
            return None

        # 7. Hold before release (important!)
        time.sleep(random.uniform(0.9, 2.2))

        # 8. Release
        if not self._dispatch_mouse(
            "mouseReleased", start_x + distance, target_y, buttons=0, click_count=1
        ):
            return None
        time.sleep(random.uniform(0.4, 0.7))

        return start_x + distance

    def _os_mouse_enabled(self):
        if self._is_local_mock_slider_target():
            return False
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return False
        raw = os.getenv("FAPAI_SOLVER_OS_MOUSE")
        if raw is not None:
            return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
        return os.name == "nt"

    def _window_metrics(self):
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": """({
                screenX: window.screenX, screenY: window.screenY,
                outerWidth: window.outerWidth, outerHeight: window.outerHeight,
                innerWidth: window.innerWidth, innerHeight: window.innerHeight,
                dpr: window.devicePixelRatio || 1,
                title: document.title || ''
            })""",
            "returnByValue": True,
        })
        if ret and "result" in ret and ret["result"].get("value"):
            return ret["result"]["value"]
        return {}

    def _enable_process_dpi_awareness(self):
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    def _force_foreground_hwnd(self, hwnd):
        if not hwnd:
            return False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            target_hwnd = int(hwnd)
            user32.ShowWindowAsync(target_hwnd, 9)  # SW_RESTORE
            foreground = user32.GetForegroundWindow()
            current_thread = kernel32.GetCurrentThreadId()
            pid = ctypes.c_ulong(0)
            foreground_thread = user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid))
            target_pid = ctypes.c_ulong(0)
            target_thread = user32.GetWindowThreadProcessId(target_hwnd, ctypes.byref(target_pid))
            if foreground_thread and foreground_thread != current_thread:
                user32.AttachThreadInput(current_thread, foreground_thread, True)
            if target_thread and target_thread != current_thread:
                user32.AttachThreadInput(current_thread, target_thread, True)
            try:
                user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass
            user32.keybd_event(0x12, 0, 0, 0)  # ALT down, allows SetForegroundWindow
            user32.BringWindowToTop(target_hwnd)
            user32.SetForegroundWindow(target_hwnd)
            try:
                user32.SwitchToThisWindow(target_hwnd, True)
            except Exception:
                pass
            user32.keybd_event(0x12, 0, 2, 0)  # ALT up
            if foreground_thread and foreground_thread != current_thread:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
            if target_thread and target_thread != current_thread:
                user32.AttachThreadInput(current_thread, target_thread, False)
            time.sleep(0.12)
            focused = int(user32.GetForegroundWindow()) == target_hwnd
            if not focused:
                for _ in range(3):
                    user32.SetForegroundWindow(target_hwnd)
                    time.sleep(0.08)
                    if int(user32.GetForegroundWindow()) == target_hwnd:
                        focused = True
                        break
            return focused
        except Exception as error:
            print(f"[SOLVER] SetForegroundWindow failed: {error}")
            return False

    def _iter_top_level_windows(self):
        if os.name != "nt":
            return []
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return []
        user32 = ctypes.windll.user32
        handles = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value or ""
            class_buff = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buff, 256)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            handles.append({
                "hwnd": int(hwnd),
                "title": title,
                "class_name": class_buff.value or "",
                "left": int(rect.left),
                "top": int(rect.top),
                "right": int(rect.right),
                "bottom": int(rect.bottom),
            })
            return True

        proc = WNDENUMPROC(callback)
        user32.EnumWindows(proc, 0)
        return handles

    def _browser_window_bounds(self):
        params = {}
        if self.target_id:
            params["targetId"] = self.target_id
        result = self._send_cdp("Browser.getWindowForTarget", params)
        if not isinstance(result, dict):
            return None
        bounds = result.get("bounds")
        if not isinstance(bounds, dict):
            return None
        return {
            "left": float(bounds.get("left") or 0),
            "top": float(bounds.get("top") or 0),
            "width": float(bounds.get("width") or 0),
            "height": float(bounds.get("height") or 0),
            "window_state": str(bounds.get("windowState") or ""),
        }

    def _edge_hwnd(self):
        windows = self._iter_top_level_windows()
        if not windows:
            return None
        metrics = self._window_metrics()
        tab_title = str(metrics.get("title") or "").strip()
        bounds = self._browser_window_bounds()
        chrome_windows = [
            item for item in windows
            if "Chrome_WidgetWin_1" in str(item.get("class_name") or "")
            and (item.get("right") or 0) - (item.get("left") or 0) > 200
            and (item.get("bottom") or 0) - (item.get("top") or 0) > 200
        ]
        candidates = chrome_windows or windows

        def score(item):
            title = str(item.get("title") or "")
            value = 0
            if tab_title and tab_title in title:
                value += 50
            lowered = title.lower()
            if "edge" in lowered or "microsoft edge" in lowered:
                value += 10
            if any(token in title for token in ("验证", "淘宝", "拍卖", "司法")):
                value += 8
            if bounds:
                delta = abs(float(item.get("left") or 0) - bounds["left"]) + abs(
                    float(item.get("top") or 0) - bounds["top"]
                )
                value += max(0, 20 - delta / 20.0)
            return value

        ranked = sorted(candidates, key=score, reverse=True)
        if not ranked:
            return None
        best = ranked[0]
        if score(best) <= 0 and not chrome_windows:
            return None
        return best.get("hwnd")

    def _find_child_windows_by_class(self, parent_hwnd, class_name):
        if os.name != "nt" or not parent_hwnd:
            return []
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return []
        user32 = ctypes.windll.user32
        matches = []

        def walk(current):
            child = user32.FindWindowExW(int(current), 0, None, None)
            while child:
                class_buff = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(child, class_buff, 256)
                if (class_buff.value or "") == class_name:
                    rect = wintypes.RECT()
                    user32.GetClientRect(child, ctypes.byref(rect))
                    width = int(rect.right - rect.left)
                    height = int(rect.bottom - rect.top)
                    if width > 200 and height > 200:
                        matches.append({"hwnd": int(child), "width": width, "height": height})
                walk(child)
                child = user32.FindWindowExW(int(current), child, None, None)

        walk(parent_hwnd)
        matches.sort(key=lambda item: item["width"] * item["height"], reverse=True)
        return matches

    def _win32_client_origin(self):
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return None
        top_hwnd = self._edge_hwnd()
        if not top_hwnd:
            return None
        render_windows = self._find_child_windows_by_class(top_hwnd, "Chrome_RenderWidgetHostHWND")
        hwnd = int(render_windows[0]["hwnd"]) if render_windows else int(top_hwnd)
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        point = wintypes.POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
            return None
        width = float(rect.right - rect.left)
        height = float(rect.bottom - rect.top)
        if width < 50 or height < 50:
            return None
        return {
            "hwnd": int(top_hwnd),
            "render_hwnd": hwnd,
            "left": float(point.x),
            "top": float(point.y),
            "width": width,
            "height": height,
            "uses_render_widget": bool(render_windows),
        }

    def _focus_linux_window(self):
        """Focus the visible Chromium window that owns the active CDP tab."""
        if not str(os.environ.get("DISPLAY") or "").strip():
            print("[SOLVER] DISPLAY is not set; cannot focus the Linux browser window.")
            return False
        self._bring_to_front()
        window_ids = []
        for window_class in ("chromium", "google-chrome", "microsoft-edge"):
            try:
                result = subprocess.run(
                    ["xdotool", "search", "--onlyvisible", "--class", window_class],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
            except (FileNotFoundError, subprocess.SubprocessError) as error:
                print(f"[SOLVER] Linux window search failed: {error}")
                return False
            for raw_window_id in result.stdout.splitlines():
                window_id = raw_window_id.strip()
                if window_id.isdigit() and window_id not in window_ids:
                    window_ids.append(window_id)
        for window_id in reversed(window_ids):
            try:
                activated = subprocess.run(
                    ["xdotool", "windowactivate", "--sync", window_id],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
            except subprocess.SubprocessError:
                continue
            if activated.returncode == 0:
                print(f"[SOLVER] Linux browser window focused id={window_id}")
                return True
        print("[SOLVER] No focusable Linux Chromium window was found.")
        return False

    def _focus_os_window(self):
        if os.name != "nt":
            return self._focus_linux_window()
        self._bring_to_front()
        hwnd = None
        client = self._win32_client_origin()
        if client:
            hwnd = client.get("hwnd")
        if not hwnd:
            hwnd = self._edge_hwnd()
        focused = self._force_foreground_hwnd(hwnd) if hwnd else False
        print(f"[SOLVER] OS window focus hwnd={hwnd} focused={focused}")
        return focused

    def _css_to_cdp_window_screen(self, start_x, start_y, distance):
        """Map CSS coordinates to physical screen via CDP Browser.getWindowForTarget + dpr.
        Avoids OS window enumeration unreliability (wrong hwnd selection)."""
        metrics = self._window_metrics()
        bounds = self._browser_window_bounds()
        if not bounds or not isinstance(bounds, dict):
            return None
        inner_w = max(float(metrics.get("innerWidth") or 0), 1.0)
        inner_h = max(float(metrics.get("innerHeight") or 0), 1.0)
        dpr = float(metrics.get("dpr") or 1) or 1.0
        outer_w = float(metrics.get("outerWidth") or 0)
        outer_h = float(metrics.get("outerHeight") or 0)
        if outer_w <= 0 or outer_h <= 0:
            return None
        chrome_left = max(0.0, (outer_w - inner_w) / 2.0)
        chrome_top = max(0.0, outer_h - inner_h)
        return {
            "x": (float(bounds.get("left") or 0) + chrome_left + float(start_x)) * dpr,
            "y": (float(bounds.get("top") or 0) + chrome_top + float(start_y)) * dpr,
            "distance": float(distance) * dpr,
            "source": "cdp_window_bounds",
        }

    def _css_to_client_screen(self, start_x, start_y, distance):
        metrics = self._window_metrics()
        inner_w = max(float(metrics.get("innerWidth") or 0), 1.0)
        inner_h = max(float(metrics.get("innerHeight") or 0), 1.0)
        dpr = float(metrics.get("dpr") or 1) or 1.0
        client = self._win32_client_origin()
        if client:
            scale_x = client["width"] / inner_w
            if client.get("uses_render_widget"):
                toolbar_phys = 0.0
            else:
                page_phys_h = inner_h * scale_x
                toolbar_phys = max(0.0, client["height"] - page_phys_h)
            return {
                "x": client["left"] + float(start_x) * scale_x,
                "y": client["top"] + toolbar_phys + float(start_y) * scale_x,
                "distance": float(distance) * scale_x,
                "source": "win32_render" if client.get("uses_render_widget") else "win32_client",
                "uses_render_widget": bool(client.get("uses_render_widget")),
                "region": (
                    int(client["left"]),
                    int(client["top"]),
                    int(client["width"]),
                    int(client["height"]),
                ),
            }
        inner_h_css = float(metrics.get("innerHeight") or 0)
        outer_h = float(metrics.get("outerHeight") or 0)
        inner_w_css = float(metrics.get("innerWidth") or 0)
        outer_w = float(metrics.get("outerWidth") or 0)
        chrome_top = max(0.0, outer_h - (inner_h_css / dpr if dpr else inner_h_css))
        border = max(0.0, (outer_w - (inner_w_css / dpr if dpr else inner_w_css)) / 2)
        return {
            "x": (float(metrics.get("screenX") or 0) + border + float(start_x)) * dpr,
            "y": (float(metrics.get("screenY") or 0) + chrome_top + float(start_y)) * dpr,
            "distance": float(distance) * dpr,
            "source": "dpr_fallback",
            "region": None,
        }

    def _located_point_from_screenshot(self, located, start_x, start_y, distance):
        clip_w = max(float(located.get("clip_w") or located.get("width") or 1), 1.0)
        clip_h = max(float(located.get("clip_h") or located.get("height") or 1), 1.0)
        scale_x = located["width"] / clip_w
        scale_y = located["height"] / clip_h
        clip_x = float(located.get("clip_x") or 0)
        clip_y = float(located.get("clip_y") or 0)
        return {
            "x": located["left"] + (float(start_x) - clip_x) * scale_x,
            "y": located["top"] + (float(start_y) - clip_y) * scale_y,
            "distance": float(distance) * scale_x,
            "source": "screenshot_handle" if located.get("clipped") else "screenshot_viewport",
        }

    def _clamp_search_region(self, search_region, screen_size):
        if not search_region or len(search_region) != 4:
            return None
        try:
            left, top, width, height = (int(search_region[0]), int(search_region[1]), int(search_region[2]), int(search_region[3]))
            screen_width, screen_height = (int(screen_size[0]), int(screen_size[1]))
        except (TypeError, ValueError, IndexError):
            return None
        if width <= 0 or height <= 0 or screen_width <= 0 or screen_height <= 0:
            return None
        right = min(left + width, screen_width)
        bottom = min(top + height, screen_height)
        left = max(left, 0)
        top = max(top, 0)
        if right <= left or bottom <= top:
            return None
        return (left, top, right - left, bottom - top)

    def _slider_search_region(self, expected, distance, slider_info=None):
        """Bound template matching around the expected live slider position."""
        if not isinstance(expected, dict):
            return None
        try:
            start_x = float(expected["x"])
            start_y = float(expected["y"])
            mapped_distance = abs(float(expected.get("distance", distance) or 0))
            handle_width = float((slider_info or {}).get("width") or 42)
            handle_height = float((slider_info or {}).get("height") or 34)
        except (KeyError, TypeError, ValueError):
            return expected.get("region")
        horizontal_margin = 96.0
        vertical_margin = 80.0
        return (
            int(start_x - horizontal_margin),
            int(start_y - vertical_margin),
            int(max(mapped_distance + handle_width + horizontal_margin * 2, 240.0)),
            int(max(handle_height + vertical_margin * 2, 160.0)),
        )

    def _viewport_origin_on_screen(self, slider_info=None, search_region=None, drag_distance=0):
        """Locate the page viewport (or slider/track) on the physical screen via screenshot."""
        try:
            import base64
            import io
            import tempfile
            from pathlib import Path
            import pyautogui
            from PIL import Image
        except ImportError:
            return None

        clip = None
        if isinstance(slider_info, dict):
            track_w = float(slider_info.get("track_width") or 0)
            if track_w <= 0:
                track_w = float(slider_info.get("width") or 0) + float(drag_distance or 0) + 8
            clip = {
                "x": max(0, float(slider_info.get("x") or 0) - 2),
                "y": max(0, float(slider_info.get("y") or 0) - 4),
                "width": max(float(slider_info.get("width") or 0) + 4, track_w + 4),
                "height": max(float(slider_info.get("height") or 0) + 8, 36),
                "scale": 1,
            }
        params = {"format": "png", "fromSurface": True}
        if clip:
            params["clip"] = clip
        shot = self._send_cdp("Page.captureScreenshot", params)
        data = shot.get("data") if isinstance(shot, dict) else None
        if not data:
            return None
        raw = base64.b64decode(data)
        try:
            shot_w, shot_h = Image.open(io.BytesIO(raw)).size
        except Exception:
            shot_w = shot_h = 0
        tmp = Path(tempfile.gettempdir()) / ("fapai_nc_track.png" if clip else "fapai_nc_viewport.png")
        tmp.write_bytes(raw)
        locate_kwargs = {}
        clamped_region = self._clamp_search_region(search_region, pyautogui.size())
        if clamped_region:
            locate_kwargs["region"] = clamped_region
        box = None
        try:
            box = pyautogui.locateOnScreen(str(tmp), confidence=0.82, **locate_kwargs)
        except Exception:
            try:
                box = pyautogui.locateOnScreen(str(tmp), **locate_kwargs)
            except Exception as error:
                print(f"[SOLVER] Screenshot locate failed: {error}")
                return None
        if box is None:
            return None
        return {
            "left": float(box.left),
            "top": float(box.top),
            "width": float(box.width),
            "height": float(box.height),
            "shot_w": float(shot_w or box.width),
            "shot_h": float(shot_h or box.height),
            "clipped": bool(clip),
            "clip_x": float(clip["x"]) if clip else 0.0,
            "clip_y": float(clip["y"]) if clip else 0.0,
            "clip_w": float(clip["width"]) if clip else float(shot_w or box.width),
            "clip_h": float(clip["height"]) if clip else float(shot_h or box.height),
        }

    def _map_css_to_screen(
        self,
        start_x,
        start_y,
        distance,
        slider_info=None,
        *,
        allow_zero_distance=False,
    ):
        """Map CSS viewport coordinates to physical screen pixels for OS mouse input."""
        expected = self._css_to_client_screen(start_x, start_y, distance)
        cdp_expected = self._css_to_cdp_window_screen(start_x, start_y, distance)
        if expected and cdp_expected:
            dx = abs(float(expected["x"]) - float(cdp_expected["x"]))
            dy = abs(float(expected["y"]) - float(cdp_expected["y"]))
            # win32 enumeration can pick the wrong top-level window when multiple Edge
            # windows exist on different monitors. CDP window bounds are authoritative.
            if dx > 200.0 or dy > 200.0:
                print(
                    f"[SOLVER] Screen map win32=({expected['x']:.0f},{expected['y']:.0f}) "
                    f"cdp=({cdp_expected['x']:.0f},{cdp_expected['y']:.0f}) "
                    f"delta=({dx:.0f},{dy:.0f}); using CDP window bounds"
                )
                expected = cdp_expected
            else:
                expected.setdefault("uses_render_widget", False)
        elif not expected and cdp_expected:
            expected = cdp_expected
        activation_verified = bool(
            self._target_activation_verified
            and expected
            and expected.get("source") in {"win32_render", "cdp_window_bounds", "dpr_fallback"}
        )
        screenshot_search_region = self._slider_search_region(
            expected,
            distance,
            slider_info=slider_info,
        )
        if activation_verified:
            # Activation proves the tab identity, not that the render widget is
            # still at the same physical origin. Take a screenshot-backed sample
            # while the exact target is foregrounded and use it when it disagrees.
            located = self._viewport_origin_on_screen(
                slider_info,
                search_region=screenshot_search_region,
                drag_distance=distance,
            )
            if located is None:
                print(
                    "[SOLVER] Exact CDP target activation verified; "
                    f"screenshot mapping unavailable, falling back to {expected.get('source')}."
                )
        else:
            located = self._viewport_origin_on_screen(
                slider_info,
                search_region=screenshot_search_region,
                drag_distance=distance,
            )
        screenshot_point = None
        delta = None
        if located:
            screenshot_point = self._located_point_from_screenshot(
                located, start_x, start_y, distance
            )
        chosen = expected
        if screenshot_point and expected:
            delta = (
                (screenshot_point["x"] - expected["x"]) ** 2
                + (screenshot_point["y"] - expected["y"]) ** 2
            ) ** 0.5
        screenshot_delta_limit = max(64.0, abs(float(distance or 0)) * 0.35)
        if screenshot_point and not expected:
            chosen = screenshot_point
        elif (
            screenshot_point
            and not expected.get("uses_render_widget")
            and delta is not None
            and delta <= screenshot_delta_limit
        ):
            chosen = screenshot_point
        elif (
            screenshot_point
            and expected.get("uses_render_widget")
            and delta is not None
            and delta <= max(48.0, abs(float(distance or 0)) * 0.15)
        ):
            chosen = expected
        elif screenshot_point and delta is not None and delta > screenshot_delta_limit:
            print(
                f"[SOLVER] Rejecting screenshot map with implausible {delta:.0f}px drift; "
                f"using {expected.get('source')}."
            )
        if screenshot_point and expected:
            print(
                f"[SOLVER] Screen map expected=({expected['x']:.0f},{expected['y']:.0f}) "
                f"screenshot=({screenshot_point['x']:.0f},{screenshot_point['y']:.0f}) "
                f"delta={delta:.0f}px source={chosen.get('source')} "
                f"render={bool(expected.get('uses_render_widget'))}"
            )
        if not chosen:
            self.last_failure_reason = "screen_mapping_unavailable"
            print("[SOLVER] Screen mapping unavailable; skipping OS drag.")
            return None
        try:
            mapped_values = (float(chosen["x"]), float(chosen["y"]), float(chosen["distance"]))
        except (KeyError, TypeError, ValueError):
            self.last_failure_reason = "screen_mapping_invalid"
            print("[SOLVER] Screen mapping is invalid; skipping OS drag.")
            return None
        invalid_distance = mapped_values[2] < 0 if allow_zero_distance else mapped_values[2] <= 0
        if not all(math.isfinite(value) for value in mapped_values) or invalid_distance:
            self.last_failure_reason = "screen_mapping_invalid"
            print("[SOLVER] Screen mapping contains non-finite coordinates; skipping OS drag.")
            return None
        return {
            "x": mapped_values[0],
            "y": mapped_values[1],
            "distance": mapped_values[2],
            "source": chosen.get("source") or (expected.get("source") if expected else None),
            "located": bool(located or activation_verified),
            "clipped": bool(located and located.get("clipped")),
            "activation_verified": activation_verified,
        }

    def _os_drag_profiles(self):
        # Keep the complete drag inside NC's tracking window while avoiding an
        # unrealistically fast, exact-endpoint release.
        return (
            {
                "name": "overshoot_release",
                "pre_pause": (0.3, 0.65),
                "press_hold": (0.1, 0.2),
                "total_time": (1.4, 2.1),
                "steps": (40, 56),
                "tremor_x": 0.45,
                "tremor_y": 0.8,
                "micro_pause_prob": 0.08,
                "micro_pause": (0.02, 0.06),
                "overshoot": (6.0, 10.0),
                "release_overshoot": (2.0, 4.0),
                "settle_steps": (2, 4),
                "hold_before_release": (0.12, 0.25),
                "release_mode": "overshoot_release",
                "warmup_px": (2.0, 5.0),
                "warmup_steps": (2, 3),
                "approach_duration": (0.2, 0.4),
                "start_duration": (0.18, 0.35),
            },
            {
                "name": "legacy_exact_release",
                "pre_pause": (0.35, 0.7),
                "press_hold": (0.12, 0.24),
                "total_time": (1.8, 2.6),
                "steps": (48, 68),
                "tremor_x": 0.5,
                "tremor_y": 0.9,
                "micro_pause_prob": 0.08,
                "micro_pause": (0.02, 0.06),
                "overshoot": (4.0, 8.0),
                "release_overshoot": (0.0, 0.0),
                "settle_steps": (3, 5),
                "hold_before_release": (0.15, 0.3),
                "release_mode": "exact_release",
                "warmup_px": (2.0, 5.0),
                "warmup_steps": (2, 3),
                "approach_duration": (0.25, 0.5),
                "start_duration": (0.2, 0.4),
            },
            {
                "name": "dense_slow_tail",
                "pre_pause": (0.4, 0.8),
                "press_hold": (0.14, 0.28),
                "total_time": (2.4, 3.4),
                "steps": (72, 96),
                "tremor_x": 0.6,
                "tremor_y": 1.1,
                "micro_pause_prob": 0.1,
                "micro_pause": (0.025, 0.07),
                "overshoot": (5.0, 9.0),
                "release_overshoot": (1.0, 3.0),
                "settle_steps": (4, 6),
                "hold_before_release": (0.18, 0.35),
                "release_mode": "overshoot_release",
                "warmup_px": (2.0, 6.0),
                "warmup_steps": (2, 4),
                "approach_duration": (0.3, 0.6),
                "start_duration": (0.25, 0.5),
            },
        )

    def _os_drag_profile(self, variant_index=0):
        profiles = self._os_drag_profiles()
        if not profiles:
            raise RuntimeError("OS drag profiles are unavailable")
        normalized_index = int(variant_index or 0) % len(profiles)
        return dict(profiles[normalized_index])

    def _os_drag_track(self, distance, profile):
        steps = max(int(random.uniform(*profile["steps"])), 1)
        total = random.uniform(*profile["total_time"])
        fracs = []
        dwells = []
        phase = random.uniform(1.5, 2.5) * math.pi
        previous = 0.0
        for index in range(1, steps + 1):
            ratio = index / steps
            eased = ratio * ratio * (3.0 - 2.0 * ratio)
            if index < steps:
                eased += math.sin(ratio * phase) * 0.002
                eased += random.gauss(0.0, 0.0008)
                eased = max(previous + 0.0005, min(eased, 0.998))
            else:
                eased = 1.0
            fracs.append(eased)
            previous = eased
            step_dwell = (total / steps) * random.uniform(0.75, 1.25)
            dwells.append(max(0.006, min(step_dwell, 0.06)))
        return fracs, dwells

    def _os_drag_release_plan(self, sx, phys_distance, profile):
        release_mode = str(profile.get("release_mode") or "overshoot_release").strip().lower()
        if release_mode == "exact_release":
            peak_overshoot = max(random.uniform(*profile["overshoot"]), 0.0)
            peak_x = sx + phys_distance + peak_overshoot
            release_x = sx + phys_distance
            settle_steps = max(int(random.uniform(*profile["settle_steps"])), 1)
            settle_xs = []
            for step in range(settle_steps):
                ratio = (step + 1) / settle_steps
                settle_xs.append(peak_x + (release_x - peak_x) * ratio)
            return peak_x, settle_xs, release_x

        release_overshoot = random.uniform(*profile["release_overshoot"])
        peak_overshoot = max(random.uniform(*profile["overshoot"]), release_overshoot)
        peak_x = sx + phys_distance + peak_overshoot
        release_x = sx + phys_distance + release_overshoot
        settle_steps = max(int(random.uniform(*profile["settle_steps"])), 1)
        settle_xs = []
        for step in range(settle_steps):
            ratio = (step + 1) / settle_steps
            settle_xs.append(peak_x + (release_x - peak_x) * ratio)
        return peak_x, settle_xs, release_x

    def _os_drag_warmup_points(self, sx, sy, profile):
        warmup_steps = max(int(random.uniform(*profile.get("warmup_steps", (0, 0)))), 0)
        if warmup_steps <= 0:
            return []
        warmup_px = random.uniform(*profile.get("warmup_px", (0.0, 0.0)))
        points = []
        for step in range(1, warmup_steps + 1):
            ratio = step / warmup_steps
            points.append((
                sx + warmup_px * ratio,
                sy + random.gauss(0, min(profile["tremor_y"], 0.8)),
            ))
        return points

    def _native_os_input_enabled(self):
        # PyAutoGUI is the production-proven input path for Aliyun NC. Keep the
        # lower-level Win32 injector as an explicit fallback instead of silently
        # changing the mouse event stream on every Windows deployment.
        backend = str(os.getenv("FAPAI_SOLVER_OS_INPUT_BACKEND", "pyautogui")).strip().lower()
        return os.name == "nt" and backend in {"native", "win32"}

    def _get_os_cursor_position(self, pyautogui):
        if not self._native_os_input_enabled():
            return pyautogui.position()
        import ctypes
        from ctypes import wintypes

        point = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            raise OSError("GetCursorPos failed")
        return float(point.x), float(point.y)

    def _set_os_cursor_position(self, pyautogui, x, y):
        if not self._native_os_input_enabled():
            pyautogui.moveTo(x, y, duration=0)
            return
        import ctypes

        user32 = ctypes.windll.user32
        if user32.SetCursorPos(int(round(x)), int(round(y))):
            return

        # SetCursorPos can be denied for a scheduled process even in the same
        # interactive session. Inject an absolute move on the virtual desktop.
        virtual_left = int(user32.GetSystemMetrics(76))
        virtual_top = int(user32.GetSystemMetrics(77))
        virtual_width = max(int(user32.GetSystemMetrics(78)), 1)
        virtual_height = max(int(user32.GetSystemMetrics(79)), 1)
        absolute_x = int(round((float(x) - virtual_left) * 65535 / max(virtual_width - 1, 1)))
        absolute_y = int(round((float(y) - virtual_top) * 65535 / max(virtual_height - 1, 1)))
        absolute_x = min(max(absolute_x, 0), 65535)
        absolute_y = min(max(absolute_y, 0), 65535)
        user32.mouse_event(0x0001 | 0x4000 | 0x8000, absolute_x, absolute_y, 0, 0)

    def _set_os_left_button(self, pyautogui, *, down):
        if not self._native_os_input_enabled():
            (pyautogui.mouseDown if down else pyautogui.mouseUp)()
            return
        import ctypes

        flag = 0x0002 if down else 0x0004
        ctypes.windll.user32.mouse_event(flag, 0, 0, 0, 0)

    def _move_os_cursor_bounded(self, pyautogui, target_x, target_y, duration):
        """Move in a small fixed number of steps so Windows timer granularity cannot amplify duration."""
        duration = max(float(duration or 0), 0.0)
        try:
            start_x, start_y = self._get_os_cursor_position(pyautogui)
        except Exception:
            self._set_os_cursor_position(pyautogui, target_x, target_y)
            if duration:
                time.sleep(duration)
            return
        steps = max(3, min(12, int(math.ceil(duration * 30))))
        dwell = duration / steps if steps else 0.0
        for step in range(1, steps + 1):
            ratio = step / steps
            eased = ratio * ratio * (3.0 - 2.0 * ratio)
            x = float(start_x) + (float(target_x) - float(start_x)) * eased
            y = float(start_y) + (float(target_y) - float(start_y)) * eased
            self._set_os_cursor_position(pyautogui, x, y)
            if dwell:
                time.sleep(dwell)

    def _move_os_cursor_timed(self, pyautogui, target_x, target_y, duration):
        """Keep PyAutoGUI's proven timing; bound only the opt-in native backend."""
        if not self._native_os_input_enabled():
            pyautogui.moveTo(target_x, target_y, duration=max(float(duration or 0), 0.0))
            return
        self._move_os_cursor_bounded(pyautogui, target_x, target_y, duration)

    def _do_drag_os(self, start_x, start_y, distance, slider_info=None, profile_variant_index=0):
        """OS-level mouse drag. CDP Input events are rejected by Aliyun NC (error:TJiA4d/Vx6urd)."""
        try:
            import pyautogui
        except ImportError:
            print("[SOLVER] pyautogui not installed; skipping OS mouse drag.")
            return None
        self._enable_process_dpi_awareness()
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0
        try:
            focused = self._focus_os_window()
        except Exception as error:
            self.last_failure_reason = "window_focus_failed"
            print(f"[SOLVER] OS window focus failed: {error}")
            return None
        if not focused:
            self.last_failure_reason = "window_focus_failed"
            print("[SOLVER] OS window focus failed; skipping OS mouse drag.")
            return None
        time.sleep(0.45)
        mapped = None
        mapping_attempts = 3 if isinstance(slider_info, dict) else 1
        for mapping_attempt in range(1, mapping_attempts + 1):
            try:
                mapped = self._map_css_to_screen(start_x, start_y, distance, slider_info=slider_info)
            except Exception as error:
                self.last_failure_reason = "screen_mapping_exception"
                print(f"[SOLVER] Screen mapping failed: {error}")
                return None
            if mapped and (not isinstance(slider_info, dict) or mapped.get("located")):
                break
            if mapping_attempt < mapping_attempts:
                print(
                    f"[SOLVER] Waiting for verified slider screen mapping "
                    f"({mapping_attempt}/{mapping_attempts})..."
                )
                time.sleep(0.3)
        if not mapped:
            if not self.last_failure_reason:
                self.last_failure_reason = "screen_mapping_unavailable"
            return None
        if isinstance(slider_info, dict) and not mapped.get("located"):
            self.last_failure_reason = "screen_mapping_unverified"
            print("[SOLVER] Slider screenshot mapping could not be verified; skipping OS drag.")
            return None
        sx = mapped["x"]
        sy = mapped["y"]
        phys_distance = mapped["distance"]
        profile = self._os_drag_profile(profile_variant_index)
        print(
            f"[SOLVER] OS mouse drag from ({sx:.0f},{sy:.0f}) +{phys_distance:.0f}px "
            f"source={mapped.get('source')} located={mapped.get('located')} "
            f"clipped={mapped.get('clipped')} profile={profile.get('name')} "
            f"input={'win32' if self._native_os_input_enabled() else 'pyautogui'}"
        )
        mouse_is_down = False
        drag_completed = False
        try:
            # 1. 移动到滑块起点附近的随机位置（更像人眼/鼠标先找位置）
            self._move_os_cursor_timed(
                pyautogui,
                sx - random.uniform(18, 36),
                sy + random.uniform(-10, 10),
                random.uniform(*profile.get("approach_duration", (0.25, 0.5))),
            )
            time.sleep(random.uniform(*profile["pre_pause"]))
            self._move_os_cursor_timed(
                pyautogui,
                sx,
                sy,
                random.uniform(*profile.get("start_duration", (0.25, 0.6))),
            )
            time.sleep(random.uniform(*profile["press_hold"]))
            self._set_os_left_button(pyautogui, down=True)
            mouse_is_down = True
            time.sleep(random.uniform(*profile["press_hold"]))
            for warmup_x, warmup_y in self._os_drag_warmup_points(sx, sy, profile):
                if self._stop_if_cancelled():
                    self.last_failure_reason = "cancelled"
                    return None
                self._set_os_cursor_position(pyautogui, warmup_x, warmup_y)
                time.sleep(random.uniform(0.04, 0.09))
            fracs, dwells = self._os_drag_track(phys_distance, profile)
            prev_x = sx
            target_x = sx + phys_distance
            for eased, dwell in zip(fracs, dwells):
                if self._stop_if_cancelled():
                    self.last_failure_reason = "cancelled"
                    return None
                x = sx + phys_distance * eased
                # 极小幅度回拉（0.5-1.5px），避免严格单调递增
                if random.random() < 0.04:
                    x -= random.uniform(0.5, 1.5)
                x += random.gauss(0, profile["tremor_x"])
                if profile.get("monotonic_x"):
                    # Preserve the monotonic profile after random perturbations.
                    # The final sample remains exactly on the target endpoint.
                    minimum_x = min(prev_x + 0.01, target_x)
                    x = max(minimum_x, min(x, target_x))
                # Y 轴：主体使用 tremor 抖动，末尾 20% 加大 Y 漂移模拟"快到终点时手抖"
                y = sy + random.gauss(0, profile["tremor_y"])
                if eased > 0.8 and random.random() < 0.25:
                    y += random.uniform(-1.5, 1.5)
                self._set_os_cursor_position(pyautogui, x, y)
                prev_x = x
                time.sleep(dwell)
                if random.random() < profile["micro_pause_prob"]:
                    time.sleep(random.uniform(*profile["micro_pause"]))
            peak_x, settle_xs, release_x = self._os_drag_release_plan(sx, phys_distance, profile)
            self._set_os_cursor_position(pyautogui, peak_x, sy)
            time.sleep(random.uniform(0.06, 0.16))
            for settle_x in settle_xs:
                self._set_os_cursor_position(pyautogui, settle_x, sy + random.gauss(0, 1.2))
                time.sleep(random.uniform(0.03, 0.07))
            # 释放前最后一次下压/微调
            self._move_os_cursor_timed(
                pyautogui,
                release_x,
                sy + random.gauss(0, 0.8),
                random.uniform(0.05, 0.15),
            )
            time.sleep(random.uniform(*profile["hold_before_release"]))
            self._set_os_left_button(pyautogui, down=False)
            mouse_is_down = False
            time.sleep(random.uniform(0.4, 0.7))
            drag_completed = True
        except Exception as error:
            self.last_failure_reason = "mouse_drag_exception"
            print(f"[SOLVER] OS mouse drag failed: {error}")
        finally:
            if mouse_is_down:
                try:
                    self._set_os_left_button(pyautogui, down=False)
                    print("[SOLVER] Released OS mouse button after interrupted drag.")
                except Exception as release_error:
                    print(f"[SOLVER] OS mouse release failed: {release_error}")
        if not drag_completed:
            return None
        return start_x + distance

    def _do_drag_local_mock(self, start_x, start_y, distance):
        """Deterministic drag path for the local mock slider harness."""
        target_x = start_x + distance
        target_y = start_y

        def dispatch_mouse_event(params):
            result = self._send_cdp("Input.dispatchMouseEvent", params)
            if result is not None:
                return True
            print("[SOLVER] CDP mouse input is unavailable; manual verification required.")
            self.last_failure_reason = "manual_required"
            return False

        steps = max(24, min(48, int(abs(distance) / 8)))
        if not dispatch_mouse_event({
            "type": "mouseMoved",
            "x": start_x,
            "y": start_y,
            "button": "left",
        }):
            return None
        time.sleep(0.02)
        if not dispatch_mouse_event({
            "type": "mousePressed",
            "x": start_x,
            "y": start_y,
            "button": "left",
            "clickCount": 1,
        }):
            return None
        time.sleep(0.02)
        for index in range(1, steps + 1):
            if self._stop_if_cancelled():
                return None
            ratio = index / steps
            eased = ratio * ratio * (3 - 2 * ratio)
            x = start_x + (distance * eased)
            y = target_y + math.sin(ratio * math.pi) * 0.3
            if not dispatch_mouse_event({
                "type": "mouseMoved",
                "x": x,
                "y": y,
                "button": "left",
            }):
                return None
            time.sleep(0.008)
        time.sleep(0.02)
        if not dispatch_mouse_event({
            "type": "mouseReleased",
            "x": target_x,
            "y": target_y,
            "button": "left",
            "clickCount": 1,
        }):
            return None
        time.sleep(0.1)
        return target_x

    def _nc_widget_rect(self):
        js_script = """
        (function() {
            var el = document.querySelector('.nc_scale, #nc_1_n1t, #nc_2_n1t, .nc-container, .nc_wrapper');
            if (!el || el.offsetParent === null) return null;
            var r = el.getBoundingClientRect();
            if (r.width < 8 || r.height < 8) return null;
            return {x: r.left, y: r.top, width: r.width, height: r.height};
        })()
        """
        ret = self._send_cdp("Runtime.evaluate", {"expression": js_script, "returnByValue": True})
        if ret and "result" in ret and isinstance(ret["result"].get("value"), dict):
            return ret["result"]["value"]
        return None

    def _nc_retry_targets(self):
        js_script = """
        (function() {
            function visibleRect(el, frameOffsetX, frameOffsetY) {
                if (!el || el.offsetParent === null) return null;
                var rect = el.getBoundingClientRect();
                if (rect.width < 8 || rect.height < 8) return null;
                return {
                    x: rect.left + frameOffsetX,
                    y: rect.top + frameOffsetY,
                    width: rect.width,
                    height: rect.height
                };
            }

            function scan(doc, frameOffsetX, frameOffsetY) {
                var result = {
                    widget: null,
                    retryText: null,
                    slider: null
                };
                var widget = doc.querySelector('.nc_scale, #nc_1_n1t, #nc_2_n1t, .nc-container, .nc_wrapper');
                result.widget = visibleRect(widget, frameOffsetX, frameOffsetY);
                var slider = doc.querySelector('#nc_1_n1z, #nc_2_n1z, [id^="nc_"][id$="_n1z"], .btn_slide, .nc-slider-btn');
                result.slider = visibleRect(slider, frameOffsetX, frameOffsetY);
                var errorWidget = doc.querySelector('.errloading, [id*="_refresh1"], [id*="refresh1"]');
                result.retryText = visibleRect(errorWidget, frameOffsetX, frameOffsetY);

                var allNodes = doc.querySelectorAll('div, span, p, button, a');
                for (var i = 0; i < allNodes.length; i++) {
                    var node = allNodes[i];
                    if (!node || node.offsetParent === null) continue;
                    var text = (node.innerText || node.textContent || '').trim();
                    if (!text) continue;
                    if (
                        text.indexOf('点击框体重试') !== -1 ||
                        text.indexOf('验证失败') !== -1 ||
                        text.indexOf('拖动未达标') !== -1 ||
                        text.toLowerCase().indexOf("oops... something's wrong") !== -1 ||
                        text.toLowerCase().indexOf('please refresh page and try again') !== -1
                    ) {
                        result.retryText = visibleRect(node, frameOffsetX, frameOffsetY);
                        if (result.retryText) break;
                    }
                }
                return result;
            }

            var summary = scan(document, 0, 0);
            var frames = document.getElementsByTagName('iframe');
            for (var i = 0; i < frames.length; i++) {
                try {
                    if (frames[i].offsetParent === null) continue;
                    var doc = frames[i].contentDocument;
                    if (!doc) continue;
                    var frameRect = frames[i].getBoundingClientRect();
                    var frameSummary = scan(doc, frameRect.left, frameRect.top);
                    if (!summary.widget && frameSummary.widget) summary.widget = frameSummary.widget;
                    if (!summary.retryText && frameSummary.retryText) summary.retryText = frameSummary.retryText;
                    if (!summary.slider && frameSummary.slider) summary.slider = frameSummary.slider;
                } catch (e) {}
            }
            return summary;
        })()
        """
        ret = self._send_cdp("Runtime.evaluate", {"expression": js_script, "returnByValue": True})
        if ret and "result" in ret and isinstance(ret["result"].get("value"), dict):
            return ret["result"]["value"]
        return {}

    def _nc_retry_click_candidates(self, targets):
        candidates = []
        seen = set()

        def add_point(label, rect, x_ratio, y_ratio=0.5):
            if not isinstance(rect, dict):
                return
            width = float(rect.get("width") or 0)
            height = float(rect.get("height") or 0)
            if width < 8 or height < 8:
                return
            x = float(rect.get("x") or 0) + width * x_ratio
            y = float(rect.get("y") or 0) + height * y_ratio
            key = (round(x, 1), round(y, 1))
            if key in seen:
                return
            seen.add(key)
            candidates.append({
                "label": label,
                "x": x,
                "y": y,
                "rect": rect,
            })

        retry_text = targets.get("retryText") if isinstance(targets, dict) else None
        widget = targets.get("widget") if isinstance(targets, dict) else None

        for ratio in (0.5, 0.35, 0.65):
            add_point("widget_centerline", widget, ratio)
        for y_ratio in (0.35, 0.65):
            add_point("widget_vertical", widget, 0.5, y_ratio)
        for ratio in (0.5, 0.35, 0.65):
            add_point("retry_text", retry_text, ratio)
        return candidates

    def _nc_retry_outcome(self, timeout_seconds=8.0):
        deadline = time.time() + max(float(timeout_seconds or 0), 0.5)
        while time.time() < deadline:
            if self._stop_if_cancelled():
                return {"cancelled": True}
            summary = self._refresh_challenge_summary({})
            if summary.get("authenticatedPage"):
                return {"authenticated": True, "summary": summary}
            if summary.get("explicitFailure"):
                time.sleep(0.35)
                continue
            slider = self._find_slider(max_retries=1, retry_delay=0)
            if slider:
                return {"slider": slider, "summary": summary}
            time.sleep(0.35)
        return {"authenticated": False}

    def _click_css_point(self, css_x, css_y, *, slider_info=None):
        if self._os_mouse_enabled():
            try:
                import pyautogui
            except ImportError:
                pyautogui = None
            if pyautogui is not None:
                self._enable_process_dpi_awareness()
                pyautogui.FAILSAFE = False
                pyautogui.PAUSE = 0
                self._focus_os_window()
                mapped = self._map_css_to_screen(
                    css_x,
                    css_y,
                    0,
                    slider_info=slider_info,
                    allow_zero_distance=True,
                )
                if mapped:
                    print(f"[SOLVER] OS click at ({mapped['x']:.0f},{mapped['y']:.0f}) source={mapped.get('source')}")
                    self._move_os_cursor_bounded(
                        pyautogui,
                        mapped["x"],
                        mapped["y"],
                        random.uniform(0.12, 0.25),
                    )
                    time.sleep(random.uniform(0.08, 0.18))
                    self._set_os_left_button(pyautogui, down=True)
                    time.sleep(random.uniform(0.04, 0.1))
                    self._set_os_left_button(pyautogui, down=False)
                    return True
                print("[SOLVER] OS click mapping unavailable; falling back to CDP click.")
        pressed = self._dispatch_mouse("mousePressed", css_x, css_y, buttons=1, click_count=1)
        released = self._dispatch_mouse("mouseReleased", css_x, css_y, buttons=0, click_count=1)
        return bool(pressed and released)

    def _reset_failed_nc_challenge(self):
        """Click '点击框体重试' so NC rebuilds a fresh slider instead of locking collection."""
        targets = self._nc_retry_targets()
        widget = targets.get("widget") if isinstance(targets, dict) else None
        if not widget:
            widget = self._nc_widget_rect()
            if isinstance(targets, dict) and widget:
                targets["widget"] = widget
        if not widget:
            print("[SOLVER] NC retry widget not found.")
            return False
        candidates = self._nc_retry_click_candidates(targets)
        if not candidates:
            candidates = [{
                "label": "widget_fallback",
                "x": widget["x"] + widget["width"] / 2,
                "y": widget["y"] + widget["height"] / 2,
                "rect": widget,
            }]
        for index, candidate in enumerate(candidates, 1):
            click_x = candidate["x"]
            click_y = candidate["y"]
            print(
                f"[SOLVER] Clicking NC retry target {index}/{len(candidates)} "
                f"({candidate['label']}) at ({click_x:.0f},{click_y:.0f})"
            )
            if not self._click_css_point(click_x, click_y, slider_info=candidate.get("rect") or widget):
                continue
            time.sleep(random.uniform(0.6, 1.0))
            outcome = self._nc_retry_outcome(timeout_seconds=3.0)
            if outcome.get("authenticated"):
                print("[SOLVER] NC retry click recovered an authenticated page.")
                self.last_failure_reason = None
                return True
            if outcome.get("slider"):
                print("[SOLVER] NC slider restored after retry click.")
                return True
        print("[SOLVER] NC retry click did not restore a slider.")
        return False

    def _nc_retry_replay_limit(self):
        raw = os.getenv("FAPAI_SOLVER_NC_RETRY_REPLAYS", "2")
        try:
            return max(int(str(raw or "").strip() or "0"), 0)
        except ValueError:
            return 2

    def _destination_list_url(self):
        href = ""
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": "location.href",
            "returnByValue": True,
        })
        if ret and "result" in ret and ret["result"].get("value"):
            href = str(ret["result"]["value"])
        if not href:
            href = str(self.current_target_url or self.target_url or "")
        if "/_____tmd_____/" in href:
            dest = href.split("/_____tmd_____/", 1)[0]
            dest = dest.replace("://sf.taobao.com//", "://sf.taobao.com/")
            if dest.startswith("http"):
                return dest
        if "sf.taobao.com/list/" in href:
            return href.split("#", 1)[0]
        return "https://sf.taobao.com/list/50025969__2.htm"

    def _recover_authenticated_list_page(self):
        dest = self._destination_list_url()
        if not dest:
            return False
        print(f"[SOLVER] Probing whether the auction list is already authenticated: {dest}")
        navigated = self._send_cdp("Page.navigate", {"url": dest})
        if navigated is None:
            return False
        time.sleep(3.2)
        summary = self._page_challenge_summary()
        if summary.get("authenticatedPage"):
            self.last_failure_reason = None
            return True
        return False

    def _login_wait_seconds(self):
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return 0
        raw = os.getenv("FAPAI_SOLVER_LOGIN_WAIT_SECONDS", "120")
        try:
            return max(int(str(raw or "").strip() or "0"), 0)
        except ValueError:
            return 120

    def _looks_like_login_ui(self, summary):
        if not isinstance(summary, dict):
            return False
        href = str(summary.get("href") or "").lower()
        title = str(summary.get("title") or "")
        return bool(
            summary.get("loginRequired")
            or "login.taobao.com" in href
            or "login_jump" in href
            or "/passport/" in href
            or title.strip() == "登录"
        )

    def _poll_until_authenticated(self):
        wait_seconds = self._login_wait_seconds()
        if wait_seconds <= 0:
            return False
        print(f"[SOLVER] Waiting up to {wait_seconds}s for login/list recovery; keep the Edge window in front.")
        try:
            self._focus_os_window()
        except Exception:
            self._bring_to_front()
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self._stop_if_cancelled():
                return False
            summary = self._page_challenge_summary()
            if summary.get("authenticatedPage"):
                print("[SOLVER] Page became authenticated while waiting for login.")
                self.last_failure_reason = None
                return True
            if summary.get("hasSlider"):
                print("[SOLVER] Slider returned while waiting for login; handing off to drag solver.")
                return False
            if not self._looks_like_login_ui(summary):
                if self._recover_authenticated_list_page():
                    return True
            time.sleep(5)
        return False

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
                var href = (doc.location && doc.location.href) ? String(doc.location.href) : '';
                var readyState = doc.readyState || '';
                var slider = doc.querySelector('#nc_1_n1z, #nc_2_n1z, [id^="nc_"][id$="_n1z"], #nc_1_n1t, #nc_2_n1t, [id^="nc_"][id$="_n1t"], .btn_slide, .nc_iconfont.btn_slide, .nc-slider-btn, .slider-btn');
                var hasSlider = !!(slider && slider.offsetParent !== null);
                var lowerHref = href.toLowerCase();
                var combined = (className + '\\n' + bodyText + '\\n' + title + '\\n' + href).toLowerCase();
                var listRoute = lowerHref.indexOf('sf.taobao.com/list/') !== -1;
                var detailRoute = lowerHref.indexOf('sf-item.taobao.com/sf_item/') !== -1;
                var challengeRedirect = lowerHref.indexOf('/_____tmd_____/') !== -1 || lowerHref.indexOf('/login_jump') !== -1;
                var auctionItemCount = 0;
                try {
                    auctionItemCount = doc.querySelectorAll('a[href*="sf_item/"], [data-itemid], [data-auction-id]').length;
                } catch (e) {}
                var validAuctionPayload = (listRoute && auctionItemCount >= 3) || (detailRoute && bodyText.trim().length > 80);
                var supportedAuctionPage = (listRoute || detailRoute) && !challengeRedirect;
                var hardBlock = combined.indexOf('baxia') !== -1 || combined.indexOf('punish') !== -1 || combined.indexOf('denyfromx5') !== -1 || challengeRedirect;
                var errorMatch = combined.match(/error\\s*:\\s*[a-z0-9/_-]{1,64}/i);
                var errorWidget = doc.querySelector('.errloading, [id*="_refresh1"], [id*="refresh1"]');
                var explicitFailure = combined.indexOf('验证失败') !== -1 ||
                    combined.indexOf('点击框体重试') !== -1 ||
                    combined.indexOf("oops... something's wrong") !== -1 ||
                    combined.indexOf('please refresh page and try again') !== -1 ||
                    !!(errorWidget && errorWidget.offsetParent !== null) ||
                    !!errorMatch;
                var challengeMarker = combined.indexOf('验证码拦截') !== -1 || combined.indexOf('请按住滑块') !== -1 || combined.indexOf('安全验证') !== -1;
                var loginUrl = lowerHref.indexOf('login.taobao.com') !== -1 || lowerHref.indexOf('login.tmall.com') !== -1 || lowerHref.indexOf('third-party-cookie') !== -1 || lowerHref.indexOf('/passport/') !== -1 || lowerHref.indexOf('/login') !== -1;
                var loginText = title.trim().toLowerCase() === '登录' || combined.indexOf('请登录') !== -1 || combined.indexOf('请先登录') !== -1;
                var loginRequired = !validAuctionPayload && (!supportedAuctionPage || challengeRedirect) && (loginUrl || loginText);
                // A valid auction payload wins over generic hidden challenge copy from an iframe.
                var challengePresent = hasSlider || explicitFailure || ((hardBlock || challengeMarker) && !validAuctionPayload);
                var authenticatedPage = validAuctionPayload && readyState !== 'loading' && bodyText.trim().length > 80 && !hasSlider && !explicitFailure;
                return {
                    hardBlock: hardBlock,
                    explicitFailure: explicitFailure,
                    hasSlider: hasSlider,
                    auctionItemCount: auctionItemCount,
                    validAuctionPayload: validAuctionPayload,
                    loginRequired: loginRequired,
                    challengeMarker: challengeMarker,
                    challengePresent: challengePresent,
                    authenticatedPage: authenticatedPage,
                    href: href,
                    readyState: readyState,
                    title: title,
                    className: className,
                    errorCode: errorMatch ? errorMatch[0].replace(/\\s+/g, '').toLowerCase() : '',
                    bodyText: bodyText.slice(0, 1000)
                };
            }
            var summary = scan(document);
            var frames = document.getElementsByTagName('iframe');
            for (var i = 0; i < frames.length; i++) {
                try {
                    if (frames[i].offsetParent === null) continue;
                    var doc = frames[i].contentDocument;
                    if (!doc) continue;
                    var frameSummary = scan(doc);
                    summary.hardBlock = summary.hardBlock || frameSummary.hardBlock;
                    summary.explicitFailure = summary.explicitFailure || frameSummary.explicitFailure;
                    summary.hasSlider = summary.hasSlider || frameSummary.hasSlider;
                    summary.challengeMarker = summary.challengeMarker || frameSummary.challengeMarker;
                    summary.loginRequired = summary.loginRequired || frameSummary.loginRequired;
                    summary.auctionItemCount = Math.max(summary.auctionItemCount || 0, frameSummary.auctionItemCount || 0);
                    if (!summary.title && frameSummary.title) summary.title = frameSummary.title;
                    if (!summary.className && frameSummary.className) summary.className = frameSummary.className;
                    if (!summary.errorCode && frameSummary.errorCode) summary.errorCode = frameSummary.errorCode;
                    if (!summary.bodyText && frameSummary.bodyText) summary.bodyText = frameSummary.bodyText;
                } catch (e) {}
            }
            summary.validAuctionPayload = !!summary.validAuctionPayload;
            summary.challengePresent = !!(
                summary.hasSlider ||
                summary.explicitFailure ||
                ((summary.hardBlock || summary.challengeMarker) && !summary.validAuctionPayload)
            );
            summary.authenticatedPage = summary.validAuctionPayload && !summary.challengePresent;
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
            "validAuctionPayload": False,
            "loginRequired": False,
            "challengeMarker": False,
            "challengePresent": False,
            "authenticatedPage": False,
            "href": "",
            "readyState": "",
            "title": "",
            "className": "",
            "errorCode": "",
            "bodyText": "",
        }

    def _close_solver_ws(self):
        if not self.ws:
            return
        try:
            self.ws.close()
        except Exception:
            pass
        self.ws = None

    def _refresh_challenge_summary(self, fallback):
        try:
            refreshed = self._page_challenge_summary()
        except Exception as error:
            print(f"[SOLVER] Challenge summary refresh failed: {error}")
            return fallback if isinstance(fallback, dict) else {}
        return refreshed or fallback or {}

    def _challenge_failure_diagnostic(self, summary):
        """Return bounded, query-free NC failure context for runtime logs."""
        payload = summary if isinstance(summary, dict) else {}
        title = re.sub(r"\s+", " ", str(payload.get("title") or "")).strip()[:100]
        class_name = re.sub(r"\s+", " ", str(payload.get("className") or "")).strip()[:120]
        error_code = re.sub(r"[^a-zA-Z0-9_:/-]", "", str(payload.get("errorCode") or ""))[:80]
        href = str(payload.get("href") or "").strip()
        try:
            parsed = urlsplit(href)
            safe_href = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))[:220]
        except ValueError:
            safe_href = ""
        return (
            f"code={error_code or 'none'} title={title or 'none'} "
            f"class={class_name or 'none'} path={safe_href or 'none'}"
        )

    def _preflight_already_authenticated(self):
        print("[SOLVER] Auction page is already accessible; no captcha solve is required.")
        self.last_failure_reason = None
        self._close_solver_ws()
        return {
            "connected": False,
            "manual_required": False,
            "has_slider": False,
            "already_authenticated": True,
        }

    def _preflight_manual_required(self):
        self.last_failure_reason = "manual_required"
        self._close_solver_ws()
        return {
            "connected": False,
            "manual_required": True,
            "has_slider": False,
            "already_authenticated": False,
        }

    def _preflight_current_challenge(self):
        """Inspect the current CDP tab before slower solver fallbacks."""
        if not self.connect_tab():
            return {
                "connected": False,
                "manual_required": self.last_failure_reason == "manual_required",
                "has_slider": False,
                "already_authenticated": False,
            }

        try:
            challenge_summary = self._page_challenge_summary()
        except Exception as error:
            print(f"[SOLVER] Challenge preflight failed: {error}")
            challenge_summary = {}

        has_slider = bool(challenge_summary.get("hasSlider"))
        if challenge_summary.get("authenticatedPage"):
            return self._preflight_already_authenticated()
        if challenge_summary.get("loginRequired") and not has_slider:
            print("[SOLVER] Login page detected; waiting for QR/manual login to complete.")
            if self._poll_until_authenticated():
                return self._preflight_already_authenticated()
            challenge_summary = self._refresh_challenge_summary(challenge_summary)
            has_slider = bool(challenge_summary.get("hasSlider"))
            if challenge_summary.get("authenticatedPage"):
                return self._preflight_already_authenticated()
            if has_slider:
                print("[SOLVER] Slider appeared after login wait; continuing with drag solver.")
            else:
                print("[SOLVER] Login page detected; manual login is required.")
                return self._preflight_manual_required()
        if challenge_summary.get("hardBlock") and not has_slider:
            # A failed NC widget is actionable immediately. Waiting for the full
            # login-recovery window first only delays the retry by two minutes.
            if challenge_summary.get("explicitFailure"):
                print("[SOLVER] Failed NC widget detected; trying retry-click immediately.")
                if self._reset_failed_nc_challenge():
                    challenge_summary = self._refresh_challenge_summary(challenge_summary)
                    has_slider = bool(challenge_summary.get("hasSlider"))
                    if challenge_summary.get("authenticatedPage"):
                        return self._preflight_already_authenticated()
                    if has_slider:
                        print("[SOLVER] Slider restored after immediate NC retry-click.")

            if not has_slider:
                print("[SOLVER] [X] Unsupported hard block detected; waiting to see if the session recovers.")
                if self._poll_until_authenticated():
                    return self._preflight_already_authenticated()
                challenge_summary = self._refresh_challenge_summary(challenge_summary)
                has_slider = bool(challenge_summary.get("hasSlider"))
                if challenge_summary.get("authenticatedPage"):
                    return self._preflight_already_authenticated()
                if has_slider:
                    print("[SOLVER] Slider appeared after hard-block wait; continuing with drag solver.")

            if not has_slider:
                print("[SOLVER] Hard block without slider; trying NC retry-click to restore slider.")
                if self._reset_failed_nc_challenge():
                    challenge_summary = self._refresh_challenge_summary(challenge_summary)
                    has_slider = bool(challenge_summary.get("hasSlider"))
                    if challenge_summary.get("authenticatedPage"):
                        return self._preflight_already_authenticated()
                    if has_slider:
                        print("[SOLVER] Slider restored after NC retry-click; continuing with drag solver.")

            if not has_slider:
                print("[SOLVER] [X] Unsupported hard block detected; manual verification required.")
                return self._preflight_manual_required()

        if not has_slider and self.ws:
            try:
                self.ws.close()
            except:
                pass
            self.ws = None
        return {
            "connected": has_slider,
            "manual_required": False,
            "has_slider": has_slider,
            "already_authenticated": False,
        }

    def _headed_playwright_enabled(self):
        raw = os.getenv("FAPAI_SOLVER_ENABLE_HEADED_PLAYWRIGHT")
        if raw is not None:
            return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))

    def _is_local_mock_slider_target(self):
        target_url = self._normalize_target_url(self.target_url)
        if not target_url:
            return False
        lowered = target_url.lower()
        if "mock_slider.html" in lowered or "test_slider_simple.html" in lowered:
            return True
        try:
            parsed = urlsplit(target_url)
        except ValueError:
            return False
        if parsed.scheme != "file":
            return False
        filename = Path(parsed.path or "").name.lower()
        return filename in {"mock_slider.html", "test_slider_simple.html"}

    def _local_mock_verification_mode(self):
        if not self._is_local_mock_slider_target():
            return None
        target_url = self._normalize_target_url(self.target_url)
        if not target_url:
            return "strict_success_text"
        try:
            parsed = urlsplit(target_url)
        except ValueError:
            return "strict_success_text"
        raw_mode = parse_qs(parsed.query or "").get("verifyMode", ["strict_success_text"])[0]
        mode = str(raw_mode or "").strip().lower()
        if mode in LOCAL_MOCK_VERIFY_MODES:
            return mode
        return "strict_success_text"

    def solve(
        self,
        max_attempts=50,
        nc_retry_replay_limit=None,
        slider_find_max_retries=None,
        drag_profile_offset=0,
    ):
        """Main solve method - tries all methods in priority order."""
        with self.lock:
            self.last_failure_reason = None

            def finish(result):
                if not result and self.last_failure_reason == "manual_required":
                    if self.ws:
                        try:
                            self.ws.close()
                        except Exception:
                            pass
                        self.ws = None
                    self._opened_target_ids.clear()
                    return result
                self._close_owned_target_tabs()
                return result

            connected_for_first_attempt = False
            if self._stop_if_cancelled():
                return finish(False)

            preflight = self._preflight_current_challenge()
            local_mock_target = self._is_local_mock_slider_target()
            if preflight.get("manual_required"):
                self.last_failure_reason = "manual_required"
                return finish(False)
            if preflight.get("already_authenticated"):
                return finish(True)
            if preflight.get("connected") and preflight.get("has_slider"):
                connected_for_first_attempt = True
                print("[SOLVER] Active slider challenge detected; using CDP method first.")
            else:
                if not local_mock_target and self._headed_playwright_enabled():
                    # Try ddddocr AI FIRST
                    try:
                        print("[SOLVER] [AI] Attempting ddddocr AI识别...")
                        if self._solve_with_ddddocr():
                            return finish(True)
                    except Exception as e:
                        print(f"[SOLVER] ddddocr error: {e}")

                    # Try Playwright Stealth
                    try:
                        print("[SOLVER] [STAR] Attempting Playwright Stealth...")
                        if self._solve_with_playwright_stealth():
                            return finish(True)
                    except Exception as e:
                        print(f"[SOLVER] Playwright Stealth error: {e}")
                else:
                    if local_mock_target:
                        print("[SOLVER] Local mock target detected; skipping headed solver fallbacks.")
                    else:
                        print("[SOLVER] Skipping headed Playwright solvers because no DISPLAY/WAYLAND_DISPLAY is available.")

                if local_mock_target:
                    print("[SOLVER] Local mock target detected; using CDP solve path directly.")
                else:
                    # Userscript DOM events are isTrusted=false and burn the NC challenge.
                    print("[SOLVER] Skipping userscript fallback on live targets; using CDP drag.")

            # CDP mouse drag (buttons bitmask + slow human path)
            print("[SOLVER] Using CDP method...")
            attempt = 0
            nc_retry_replays = 0
            if nc_retry_replay_limit is None:
                nc_retry_replay_limit = self._nc_retry_replay_limit()
            else:
                nc_retry_replay_limit = max(0, int(nc_retry_replay_limit))
            try:
                drag_profile_offset = int(drag_profile_offset or 0) % max(len(self._os_drag_profiles()), 1)
            except (TypeError, ValueError):
                drag_profile_offset = 0

            while attempt < max_attempts:
                attempt += 1
                if self._stop_if_cancelled():
                    return finish(False)
                print(f"\n[SOLVER] === Attempt {attempt}/{max_attempts} ===")

                # 每一轮都重新连接目标页签，避免 ws 失效后卡死
                if connected_for_first_attempt:
                    connected_for_first_attempt = False
                elif not self.connect_tab():
                    if self.last_failure_reason == "manual_required":
                        return finish(False)
                    print("[SOLVER] [X] connect_tab 失败，5秒后重试...")
                    time.sleep(5)
                    continue

                print("[SOLVER] Connected to browser. Starting solve loop...")
                self._bring_to_front()

                try:
                    # Step 1: Find Slider
                    if slider_find_max_retries is None:
                        slider_info = self._find_slider()
                    else:
                        slider_info = self._find_slider(
                            max_retries=max(1, int(slider_find_max_retries)),
                            retry_delay=0,
                        )
                    if not slider_info:
                        challenge_summary = self._page_challenge_summary()
                        if challenge_summary.get("authenticatedPage"):
                            print("[SOLVER] Auction page became accessible; captcha is already resolved.")
                            self.last_failure_reason = None
                            if self.ws:
                                try:
                                    self.ws.close()
                                except Exception:
                                    pass
                                self.ws = None
                            return finish(True)
                        if challenge_summary.get("hardBlock") and not challenge_summary.get("hasSlider"):
                            print("[SOLVER] Hard block without slider; trying NC retry-click to restore slider.")
                            restored = self._reset_failed_nc_challenge()
                            if restored:
                                print("[SOLVER] NC slider restored after retry-click; continuing loop...")
                                if self.ws:
                                    try:
                                        self.ws.close()
                                    except:
                                        pass
                                    self.ws = None
                                continue
                            print("[SOLVER] [X] Unsupported hard block detected; manual verification required.")
                            self.last_failure_reason = "manual_required"
                            if self.ws:
                                try:
                                    self.ws.close()
                                except:
                                    pass
                            return finish(False)
                        if challenge_summary.get("loginRequired"):
                            print("[SOLVER] Login page detected; manual login is required.")
                            self.last_failure_reason = "manual_required"
                            if self.ws:
                                try:
                                    self.ws.close()
                                except Exception:
                                    pass
                                self.ws = None
                            return finish(False)
                        print("[SOLVER] Slider not found after retries. Reload + continue...")
                        self._reload_page()
                        time.sleep(0.2 if local_mock_target else random.uniform(1, 2))
                        self._close_solver_ws()
                        continue

                    start_x = slider_info["x"] + (slider_info["width"] / 2)
                    start_y = slider_info["y"] + (slider_info["height"] / 2)

                    # Sanity check
                    if start_x < 10 or start_y < 10:
                        print(f"[SOLVER] Invalid coordinates: ({start_x}, {start_y}) -> reload + continue")
                        self._reload_page()
                        time.sleep(0.2 if local_mock_target else random.uniform(1, 2))
                        if self.ws:
                            try:
                                self.ws.close()
                            except:
                                pass
                        continue

                    # Human hesitation before action (NC needs time to bind listeners)
                    time.sleep(0.05 if local_mock_target else random.uniform(1.5, 2.4))

                    print(f"[SOLVER] Slider found at ({start_x:.0f}, {start_y:.0f}) "
                          f"[Selector: {slider_info.get('selector')}, Context: {slider_info.get('context')}]")

                    # Step 2: Get Track Width (dynamic)
                    track_width = self._get_track_width()
                    slider_info["track_width"] = track_width
                    track_rect = self._get_track_rect()

                    # Calculate actual drag distance
                    # NC captcha needs slider to reach nearly the end (95-100%)
                    if local_mock_target:
                        distance = max(1, track_width - slider_info["width"] - 8)
                    else:
                        # The challenge can leave the handle part-way across the
                        # track after a rejected attempt. Calculate the remaining
                        # distance from the live rectangles instead of assuming the
                        # handle is always at the left edge.
                        remaining = None
                        if isinstance(track_rect, dict):
                            track_right = float(track_rect.get("left") or 0) + float(track_rect.get("width") or 0)
                            slider_right = float(slider_info.get("x") or 0) + float(slider_info.get("width") or 0)
                            candidate = track_right - slider_right
                            if 0 < candidate <= track_width + slider_info["width"]:
                                remaining = candidate
                            track_offset_width = float(track_rect.get("offsetWidth") or track_width)
                            handle_offset_width = float(track_rect.get("handleOffsetWidth") or slider_info["width"])
                            current_handle_left = track_rect.get("handleOffsetLeft")
                            if current_handle_left is not None:
                                target_handle_left = track_offset_width - handle_offset_width
                                offset_remaining = target_handle_left - float(current_handle_left)
                                if 0 <= offset_remaining <= track_width + slider_info["width"]:
                                    # NC uses offsetWidth/offsetLeft internally;
                                    # those include the exact 2px border correction
                                    # that getBoundingClientRect() hides.
                                    remaining = offset_remaining
                        if remaining is None:
                            remaining = track_width - slider_info["width"] + 2
                        distance = max(1, min(remaining, 1000))
                    print(
                        f"[SOLVER] Drag distance: {distance:.0f}px "
                        f"(track: {track_width:.0f}px, slider: {slider_info['width']:.0f}px)"
                    )

                    # Step 3: Execute drag
                    self._bring_to_front()
                    time.sleep(0.05 if local_mock_target else random.uniform(0.2, 0.5))
                    if local_mock_target:
                        drag_result = self._do_drag_local_mock(start_x, start_y, distance)
                    elif self._os_mouse_enabled():
                        print("[SOLVER] Using OS-level mouse drag for live NC challenge.")
                        drag_profile_variant = (
                            drag_profile_offset
                            + min(nc_retry_replays, len(self._os_drag_profiles()) - 1)
                        ) % len(self._os_drag_profiles())
                        drag_result = self._do_drag_os(
                            start_x,
                            start_y,
                            distance,
                            slider_info=slider_info,
                            profile_variant_index=drag_profile_variant,
                        )
                        if drag_result is None:
                            print("[SOLVER] OS mouse unavailable; falling back to CDP drag.")
                            drag_result = self._do_drag(start_x, start_y, distance)
                    else:
                        drag_result = self._do_drag(start_x, start_y, distance)
                    if drag_result is None:
                        if self.last_failure_reason in {"manual_required", "cancelled"}:
                            if self.ws:
                                try:
                                    self.ws.close()
                                except Exception:
                                    pass
                                self.ws = None
                            return finish(False)
                        print("[SOLVER] Drag did not complete. Reload + continue...")
                        self._reload_page()
                        self._bring_to_front()
                        time.sleep(0.2 if local_mock_target else random.uniform(1, 2))
                        if self.ws:
                            try:
                                self.ws.close()
                            except Exception:
                                pass
                            self.ws = None
                        continue
                    if self.last_failure_reason == "manual_required":
                        if self.ws:
                            try:
                                self.ws.close()
                            except Exception:
                                pass
                            self.ws = None
                        return finish(False)
                    print("[SOLVER] Drag complete. Verifying...")

                    # Step 4: Verify Success
                    time.sleep(0.15 if local_mock_target else random.uniform(1.8, 2.4))

                    if self._wait_for_verification_success():
                        print("\033[92m[SOLVER] [OK] Verified: Captcha solved!\033[0m")
                        self.last_failure_reason = None

                        # Phase 3.1: We DO NOT close the page anymore.
                        # The userscript handles redirecting it back to standby.
                        print("[SOLVER] Leaving worker tab alive for userscript redirect.")

                        self._close_solver_ws()
                        return finish(True)

                    if self.last_failure_reason == "manual_required":
                        return finish(False)

                    print("\033[93m[SOLVER] [X] Verification failed. Reload + unlimited retry...\033[0m")
                    challenge_summary = self._page_challenge_summary()
                    print(
                        "[SOLVER] Challenge diagnostic: "
                        f"{self._challenge_failure_diagnostic(challenge_summary)}"
                    )
                    if challenge_summary.get("authenticatedPage"):
                        print("\033[92m[SOLVER] [OK] Auction page is accessible after drag; treating as solved.\033[0m")
                        self.last_failure_reason = None
                        self._close_solver_ws()
                        return finish(True)
                    if (
                        not local_mock_target
                        and challenge_summary.get("hasSlider")
                        and not challenge_summary.get("explicitFailure")
                        and nc_retry_replays < nc_retry_replay_limit
                    ):
                        # Preserve the live handle position. The next pass uses
                        # the current rectangles to drag only the residual
                        # distance, matching the path that has solved real NC
                        # challenges. Explicit failures are reset below.
                        nc_retry_replays += 1
                        print(
                            "[SOLVER] Slider is still present without an explicit failure; "
                            f"keeping its live position and switching to the next drag profile "
                            "without spending a main attempt "
                            f"({nc_retry_replays}/{nc_retry_replay_limit})."
                        )
                        self._close_solver_ws()
                        attempt = max(attempt - 1, 0)
                        time.sleep(random.uniform(0.4, 0.9))
                        continue
                    if challenge_summary.get("explicitFailure"):
                        if nc_retry_replays < nc_retry_replay_limit:
                            if self._reset_failed_nc_challenge():
                                nc_retry_replays += 1
                                print(
                                    "[SOLVER] Challenge asked to retry; "
                                    f"replaying drag without spending a main attempt "
                                    f"({nc_retry_replays}/{nc_retry_replay_limit})."
                                )
                                self._close_solver_ws()
                                attempt = max(attempt - 1, 0)
                                continue
                        print("[SOLVER] [X] Official challenge explicitly rejected the automated drag; manual verification required.")
                        self.last_failure_reason = "manual_required"
                        self._close_solver_ws()
                        return finish(False)
                    self._reload_page()
                    self._bring_to_front()
                    time.sleep(0.2 if local_mock_target else random.uniform(1, 2))

                except Exception as e:
                    print(f"[SOLVER] Error during steps: {e}")
                    import traceback
                    traceback.print_exc()
                    self._close_solver_ws()
                    print("[SOLVER] Exception branch, 3秒后继续重试...")
                    time.sleep(3)
                    continue

            print(f"[SOLVER] [X] Max attempts ({max_attempts}) reached without success")
            recovered_authenticated_page = bool(
                not local_mock_target and self._recover_authenticated_list_page()
            )
            self._close_solver_ws()
            if recovered_authenticated_page:
                print("\033[92m[SOLVER] [OK] List page is authenticated after challenge attempts; clearing auth lock path.\033[0m")
                return finish(True)
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
            print("[SOLVER] [OK] Userscript method succeeded!")

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
                    print("[SOLVER] [OK] Playwright Stealth succeeded!")
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
                    print("[SOLVER] [OK] ddddocr AI识别成功!")
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
                    print("[SOLVER] [OK] OpenCV边缘检测成功!")
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
