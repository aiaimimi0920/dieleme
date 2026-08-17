from __future__ import annotations
import datetime, json, os, sys, time, traceback
from pathlib import Path
from typing import Any
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path: sys.path.insert(0, str(REPO_ROOT))
from src.captcha_solver import CaptchaSolver
from tools.internal_api_http import fetch_json, post_json
DEFAULT_API_BASE_URL = os.environ.get("FAPAI_API_BASE_URL", "http://192.168.15.200:8001/api")
DEFAULT_CDP_ENDPOINT = os.environ.get("FAPAI_CDP_ENDPOINT", "http://127.0.0.1:9223")
DEFAULT_POLL_SECONDS = int(os.environ.get("FAPAI_LOCAL_SOLVER_POLL_SECONDS", "10"))
DEFAULT_MAX_ATTEMPTS = int(os.environ.get("FAPAI_LOCAL_SOLVER_MAX_ATTEMPTS", "50"))
def _status_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/status"

def _auth_complete_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/collection/auth/complete"

def log_event(event):
    event["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
    line = json.dumps(event, ensure_ascii=False)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("utf-8", errors="replace").decode("utf-8", errors="replace"), flush=True)

def read_solver_status(api_base):
    try:
        payload = fetch_json(_status_url(api_base), timeout=10)
        if not isinstance(payload, dict): return {"error": "non_dict_status_response"}
        solver = payload.get("captcha_solver")
        return dict(solver) if isinstance(solver, dict) else {}
    except Exception as exc: return {"error": repr(exc)}

def check_cdp_healthy(cdp_endpoint):
    endpoint = cdp_endpoint.rstrip("/")
    for p in ("/json/list", "/json/version"):
        try:
            resp = fetch_json(f"{endpoint}{p}", timeout=5)
            if resp is not None: return True
        except Exception: continue
    return False
def cdp_endpoint_matches_local(reported_cdp, local_cdp):
    if not reported_cdp or not local_cdp: return False
    reported = reported_cdp.lower().strip().rstrip("/")
    local = local_cdp.lower().strip().rstrip("/")
    if reported == local: return True
    for loopback in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        if loopback in reported and loopback in local: return True
        if loopback in reported and "host.docker.internal" in local: return True
        if loopback in reported and "192.168.65.254" in local: return True
    return False

def node_owns_last_request(solver_status, local_cdp_endpoint, expected_node_id=None):
    last_request = solver_status.get("last_request")
    if not isinstance(last_request, dict): return False
    node_id = str(last_request.get("node_id") or "").strip().lower()
    if expected_node_id:
        if node_id == expected_node_id.strip().lower(): return True
    reported_cdp = str(last_request.get("cdp_endpoint") or "").strip()
    if reported_cdp and cdp_endpoint_matches_local(reported_cdp, local_cdp_endpoint): return True
    return False

def notify_auth_complete(api_base, source="pc2_local_solver", refresh_cookie_snapshot=True):
    url = _auth_complete_url(api_base)
    try:
        payload = post_json(url, {"source": source, "refresh_cookie_snapshot": refresh_cookie_snapshot}, timeout=15)
        return dict(payload) if isinstance(payload, dict) else {"ok": False, "raw": payload}
    except Exception as exc: return {"ok": False, "error": repr(exc)}

# --- Fallback escalation: push to PC1 manual auth after repeated failures ---
FALLBACK_STATE_PATH = REPO_ROOT / ".codex-temp" / "bridge-control" / "solver-fallback-state.json"
FALLBACK_FAIL_THRESHOLD = int(os.environ.get("FAPAI_SOLVER_FALLBACK_FAIL_THRESHOLD", "10"))
FALLBACK_STALL_SECONDS = int(os.environ.get("FAPAI_SOLVER_FALLBACK_STALL_SECONDS", "600"))


def manual_fallback_enabled():
    """Keep automatic solving primary unless manual escalation is explicitly enabled."""
    value = os.environ.get("FAPAI_SOLVER_MANUAL_FALLBACK_ENABLED", "0")
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _manual_fallback_latch_active(fallback_state, manual_required):
    return bool(
        manual_fallback_enabled()
        and manual_required
        and fallback_state.get("manual_pushed")
    )

def _report_manual_captcha(api_base_url, cdp_endpoint, target_url):
    url = api_base_url.rstrip("/") + "/report_manual_captcha"
    payload = {
        "url": target_url or "",
        "cdp_endpoint": cdp_endpoint,
        "node_id": os.environ.get("FAPAI_NODE_ID", "").strip() or None,
        "manual_only": True,
        "timestamp": int(time.time() * 1000),
    }
    try:
        loaded = post_json(url, payload, timeout=10)
        return dict(loaded) if isinstance(loaded, dict) else {"raw": loaded}
    except Exception as exc:
        return {"error": repr(exc)}

def _load_fallback_state():
    try:
        if FALLBACK_STATE_PATH.exists():
            raw = FALLBACK_STATE_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            return {
                "consecutive_failures": int(data.get("consecutive_failures", 0) or 0),
                "window_started_at": float(data.get("window_started_at") or 0) or None,
                "last_success_at": float(data.get("last_success_at") or 0) or None,
                "manual_pushed": bool(data.get("manual_pushed", False)),
            }
    except Exception:
        pass
    return {"consecutive_failures": 0, "window_started_at": None, "last_success_at": None, "manual_pushed": False}

def _save_fallback_state(state):
    try:
        FALLBACK_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FALLBACK_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        log_event({"kind": "fallback_state_save_error", "error": repr(exc)})

def _reset_fallback_state():
    state = {"consecutive_failures": 0, "window_started_at": None, "last_success_at": None, "manual_pushed": False}
    _save_fallback_state(state)
    return state

def get_cdp_page_url(cdp_endpoint):
    """Get the URL of the first page tab from CDP."""
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        if not isinstance(tabs, list):
            return None
        for tab in tabs:
            if tab.get("type") == "page":
                url = str(tab.get("url") or "").strip()
                if url:
                    return url
        if tabs:
            url = str(tabs[0].get("url") or "").strip()
            if url:
                return url
        return None
    except Exception:
        return None

def check_cdp_browser_for_challenge_page(cdp_endpoint):
    """Check if the CDP browser has a punish/challenge page URL even without a visible slider.
    Returns True if a punish page is detected."""
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        if not isinstance(tabs, list) or not tabs:
            return False
        for tab in tabs:
            url = str(tab.get("url") or "").lower()
            if "/_____tmd_____/punish" in url or "x5secdata" in url:
                return True
            if "sec.taobao.com" in url and "punish" in url:
                return True
        return False
    except Exception:
        return False

def check_cdp_browser_for_slider(cdp_endpoint):
    """Lightweight CDP check: probe browser tabs for a visible NC slider.
    Returns the slider_info dict if found, or None."""
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        if not isinstance(tabs, list) or not tabs:
            return None
        # Prefer captcha / sec / login pages
        target = None
        for tab in tabs:
            url = str(tab.get("url") or "").lower()
            if "/_____tmd_____/" in url or "sec.taobao.com" in url or "login.taobao.com" in url:
                target = tab
                break
        if not target:
            for tab in tabs:
                if tab.get("type") == "page":
                    target = tab
                    break
        if not target:
            target = tabs[0]
        ws_url = str(target.get("webSocketDebuggerUrl") or "")
        if not ws_url:
            return None
        import websocket
        ws = websocket.create_connection(ws_url, suppress_origin=True, timeout=5)
        ws.settimeout(5)
        _send_id = [0]
        def _send(method, params=None):
            _send_id[0] += 1
            mid = _send_id[0]
            msg = {"id": mid, "method": method, "params": params or {}}
            ws.send(json.dumps(msg))
            while True:
                resp = json.loads(ws.recv())
                if resp.get("id") == mid:
                    return resp.get("result")
        _send("Runtime.enable")
        js = r"""
        (function() {
            var selectors = ['#nc_1_n1z', '#nc_2_n1z', '[id^="nc_"][id$="_n1z"]', '.btn_slide', '.nc_iconfont.btn_slide', '#nc_1_n1t', '#nc_2_n1t', '.nc-slider-btn'];
            for (var i = 0; i < selectors.length; i++) {
                var el = document.querySelector(selectors[i]);
                if (el && el.offsetParent !== null) {
                    var r = el.getBoundingClientRect();
                    if (r.width > 5 && r.height > 5) return {found:true, x:r.left, y:r.top, width:r.width, height:r.height, selector:selectors[i]};
                }
            }
            return {found:false};
        })()
        """
        ret = _send("Runtime.evaluate", {"expression": js, "returnByValue": True})
        ws.close()
        if ret and isinstance(ret.get("result"), dict) and ret["result"].get("value", {}).get("found"):
            return ret["result"]["value"]
        return None
    except Exception:
        return None


def run_solver_local(cdp_endpoint, target_url, max_attempts=50):
    log_event({"kind": "local_solver_start", "cdp_endpoint": cdp_endpoint, "target_url": target_url, "max_attempts": max_attempts})
    try:
        solver = CaptchaSolver(cdp_endpoint=cdp_endpoint, target_url=target_url)
        success = solver.solve(max_attempts=max_attempts)
        log_event({"kind": "local_solver_end", "success": success, "failure_reason": solver.last_failure_reason})
        return bool(success)
    except Exception as exc:
        log_event({"kind": "local_solver_error", "error": repr(exc), "traceback": traceback.format_exc()})
        return False

def local_solver_loop(api_base_url=None, cdp_endpoint=None, poll_seconds=None, max_attempts=None, expected_node_id=None):
    if api_base_url is None: api_base_url = DEFAULT_API_BASE_URL
    if cdp_endpoint is None: cdp_endpoint = DEFAULT_CDP_ENDPOINT
    if poll_seconds is None: poll_seconds = DEFAULT_POLL_SECONDS
    if max_attempts is None: max_attempts = DEFAULT_MAX_ATTEMPTS
    log_event({"kind": "local_solver_boot", "api_base_url": api_base_url, "cdp_endpoint": cdp_endpoint, "poll_seconds": poll_seconds, "max_attempts": max_attempts, "expected_node_id": expected_node_id})
    while not check_cdp_healthy(cdp_endpoint):
        log_event({"kind": "waiting_for_cdp", "cdp_endpoint": cdp_endpoint})
        time.sleep(5)
    while True:
        try:
            solver_status = read_solver_status(api_base_url)
            if "error" in solver_status:
                log_event({"kind": "status_error", "error": solver_status["error"]})
                time.sleep(poll_seconds); continue
            paused = bool(solver_status.get("paused"))
            running = bool(solver_status.get("running"))
            manual_required = bool(solver_status.get("manual_required"))
            # Manual escalation is opt-in. A stale fallback latch must never disable
            # the automatic solver after an operator turns manual fallback off.
            fallback_state = _load_fallback_state()
            if fallback_state.get("manual_pushed"):
                if not manual_required:
                    # PC1 manual auth completed/cleared; reset fallback state
                    log_event({"kind": "fallback_manual_resolved"})
                    _reset_fallback_state()
                elif _manual_fallback_latch_active(fallback_state, manual_required):
                    log_event({"kind": "fallback_waiting_manual_auth", "manual_required": manual_required})
                    time.sleep(poll_seconds); continue
                else:
                    log_event({"kind": "fallback_manual_latch_bypassed", "manual_required": manual_required})
                    _reset_fallback_state()
            # Primary trigger: API says paused + not running (standard flow)
            api_trigger = paused and not running
            # Secondary trigger: probe CDP for slider whenever manual_required is set.
            # The Docker solver keeps resetting the API state via manual_retry, so we check CDP directly.
            cdp_trigger = False
            if manual_required:
                slider_found = check_cdp_browser_for_slider(cdp_endpoint)
                if slider_found:
                    log_event({"kind": "cdp_probe_slider_found", "slider": slider_found})
                    cdp_trigger = True
                else:
                    log_event({"kind": "cdp_probe_no_slider", "running": running, "paused": paused})
            # Periodic CDP probe even when API says not paused, to catch slider after Docker resets state
            _cdp_probe_counter = getattr(local_solver_loop, "_probe_counter", 0) + 1
            local_solver_loop._probe_counter = _cdp_probe_counter
            # Probe every ~30 seconds. The previous calculation multiplied the
            # poll duration by three and then treated that value as an iteration
            # count, turning a 30-second probe into a 5-minute probe at the
            # default 10-second polling interval.
            _probe_interval = max(1, int(30 / max(1, poll_seconds)))
            if not api_trigger and not cdp_trigger and not manual_required and _cdp_probe_counter >= _probe_interval:
                _cdp_probe_counter = 0
                periodic_found = check_cdp_browser_for_slider(cdp_endpoint)
                if periodic_found:
                    log_event({"kind": "cdp_periodic_probe_slider_found", "slider": periodic_found})
                    cdp_trigger = True
                elif check_cdp_browser_for_challenge_page(cdp_endpoint):
                    log_event({"kind": "cdp_periodic_probe_challenge_page", "cdp_endpoint": cdp_endpoint})
                    cdp_trigger = True
            if not api_trigger and not cdp_trigger:
                time.sleep(poll_seconds); continue
            if not node_owns_last_request(solver_status, cdp_endpoint, expected_node_id):
                time.sleep(poll_seconds); continue
            last_request = solver_status.get("last_request")
            target_url = ""
            if isinstance(last_request, dict):
                target_url = str(last_request.get("target_url") or last_request.get("url") or "").strip()
            if not target_url:
                log_event({"kind": "skip_no_target_url", "solver_status": solver_status})
                time.sleep(poll_seconds); continue
            if not check_cdp_healthy(cdp_endpoint):
                log_event({"kind": "cdp_unhealthy_before_solve", "cdp_endpoint": cdp_endpoint})
                time.sleep(poll_seconds); continue
            success = run_solver_local(cdp_endpoint, target_url, max_attempts=max_attempts)
            if success:
                log_event({"kind": "local_solver_success"})
                auth_result = notify_auth_complete(api_base_url, source="pc2_local_solver")
                log_event({"kind": "auth_complete_result", "result": auth_result})
                _reset_fallback_state()
            else:
                log_event({"kind": "local_solver_failure"})
                state = _load_fallback_state()
                state["consecutive_failures"] = int(state.get("consecutive_failures", 0) or 0) + 1
                now = time.time()
                if not state.get("window_started_at"):
                    state["window_started_at"] = now
                # A successful solve anywhere after a previous failure resets the window.
                last_success_at = float(state.get("last_success_at") or 0) or None
                window_started_at = float(state.get("window_started_at") or 0) or now
                stalled_seconds = now - window_started_at if last_success_at is None else now - max(last_success_at, window_started_at)
                threshold_reached = int(state["consecutive_failures"]) >= FALLBACK_FAIL_THRESHOLD
                stalled = stalled_seconds >= FALLBACK_STALL_SECONDS
                should_push = bool(
                    manual_fallback_enabled()
                    and threshold_reached
                    and stalled
                    and not state.get("manual_pushed")
                )
                state["stalled_seconds"] = round(stalled_seconds, 1)
                state["threshold_reached"] = threshold_reached
                state["stalled"] = stalled
                _save_fallback_state(state)
                log_event({
                    "kind": "pc1_manual_escalation_check",
                    "consecutive_failures": state["consecutive_failures"],
                    "stalled_seconds": round(stalled_seconds, 1),
                    "threshold": FALLBACK_FAIL_THRESHOLD,
                    "stalled_threshold_seconds": FALLBACK_STALL_SECONDS,
                    "should_push": should_push,
                    "manual_pushed": state.get("manual_pushed", False),
                })
                if should_push:
                    manual_result = _report_manual_captcha(api_base_url, cdp_endpoint, target_url)
                    state["manual_pushed"] = True
                    state["manual_pushed_at_epoch"] = time.time()
                    state["manual_result"] = manual_result
                    _save_fallback_state(state)
                    log_event({"kind": "pc1_manual_auth_pushed", "result": manual_result})
        except Exception as exc:
            log_event({"kind": "loop_error", "error": repr(exc), "traceback": traceback.format_exc()})
        time.sleep(poll_seconds)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PC2 local captcha solver daemon")
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--cdp-endpoint", default=DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--node-id", default=None)
    args = parser.parse_args()
    local_solver_loop(
        api_base_url=str(args.api_base_url),
        cdp_endpoint=str(args.cdp_endpoint),
        poll_seconds=int(args.poll_seconds),
        max_attempts=int(args.max_attempts),
        expected_node_id=str(args.node_id).strip() if args.node_id else None,
    )
