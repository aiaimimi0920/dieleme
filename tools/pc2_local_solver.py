from __future__ import annotations
import datetime, json, os, sys, time, traceback, uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path: sys.path.insert(0, str(REPO_ROOT))
from src.captcha_solver import CaptchaSolver
from tools.internal_api_http import fetch_json, post_json
DEFAULT_API_BASE_URL = os.environ.get("FAPAI_API_BASE_URL", "http://192.168.15.200:8001/api")
DEFAULT_CDP_ENDPOINT = os.environ.get("FAPAI_CDP_ENDPOINT", "http://127.0.0.1:9223")
DEFAULT_POLL_SECONDS = int(os.environ.get("FAPAI_LOCAL_SOLVER_POLL_SECONDS", "5"))
DEFAULT_MAX_ATTEMPTS = 1
DEFAULT_DRAG_PROFILE_VARIANTS = 3
AUTH_COMPLETE_REQUEST_ATTEMPTS = int(os.environ.get("FAPAI_AUTH_COMPLETE_REQUEST_ATTEMPTS", "3"))
AUTH_COMPLETE_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("FAPAI_AUTH_COMPLETE_REQUEST_TIMEOUT_SECONDS", "15"))
AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS = float(os.environ.get("FAPAI_AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS", "1"))
AUTH_COMPLETE_RETRY_BASE_SECONDS = float(os.environ.get("FAPAI_AUTH_COMPLETE_RETRY_BASE_SECONDS", "5"))
AUTH_COMPLETE_RETRY_MAX_SECONDS = float(os.environ.get("FAPAI_AUTH_COMPLETE_RETRY_MAX_SECONDS", "60"))
AUTH_COMPLETE_PENDING_MAX_SECONDS = float(
    os.environ.get("FAPAI_AUTH_COMPLETE_PENDING_MAX_SECONDS", "120")
)
RECENT_HEALTHY_AUTH_MAX_AGE_SECONDS = float(
    os.environ.get("FAPAI_RECENT_HEALTHY_AUTH_MAX_AGE_SECONDS", "3600")
)
POST_AUTH_CDP_PROBE_GRACE_SECONDS = float(
    os.environ.get("FAPAI_POST_AUTH_CDP_PROBE_GRACE_SECONDS", "90")
)

def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() not in {"0", "false", "no", "off"}

def real_taobao_auto_solver_enabled():
    return _env_flag("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", False)

def _status_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/status"

def _auth_complete_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/collection/auth/complete"

def _resume_after_cooldown_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/collection/auth/resume_after_cooldown"

def _manual_captcha_report_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/report_manual_captcha"

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

def solver_status_requires_manual_only(solver_status):
    if not isinstance(solver_status, dict):
        return False
    if solver_status.get("manual_only") is True:
        return True
    last_request = solver_status.get("last_request")
    if not isinstance(last_request, dict):
        return False
    target_url = str(last_request.get("target_url") or last_request.get("url") or "").strip()
    try:
        hostname = str(urlsplit(target_url).hostname or "").strip().lower()
    except ValueError:
        return False
    is_taobao = hostname == "taobao.com" or hostname.endswith(".taobao.com")
    return bool(is_taobao and not real_taobao_auto_solver_enabled())

def manual_challenge_registration_needed(solver_status):
    return bool(
        solver_status_requires_manual_only(solver_status)
        and not (
            solver_status.get("manual_required") is True
            and str(solver_status.get("challenge_id") or "").strip()
        )
    )

def canonical_manual_challenge_target(value):
    target_url = str(value or "").strip()
    try:
        parsed = urlsplit(target_url)
    except ValueError:
        return ""
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname or not (hostname == "taobao.com" or hostname.endswith(".taobao.com")):
        return ""
    path = parsed.path.split("/_____tmd_____/punish", 1)[0]
    while "//" in path:
        path = path.replace("//", "/")
    return urlunsplit((parsed.scheme or "https", parsed.netloc, path or "/", "", ""))

def notify_manual_challenge(api_base, solver_status, expected_node_id=None):
    last_request = solver_status.get("last_request") if isinstance(solver_status, dict) else None
    if not isinstance(last_request, dict):
        return {"ok": False, "error": "missing_last_request"}
    target_url = canonical_manual_challenge_target(
        last_request.get("target_url") or last_request.get("url")
    )
    if not target_url:
        return {"ok": False, "error": "missing_safe_target_url"}
    payload = {
        "target_url": target_url,
        "url": target_url,
        "node_id": str(expected_node_id or last_request.get("node_id") or "").strip(),
        "cdp_endpoint": str(last_request.get("cdp_endpoint") or "").strip(),
        "manual_only": True,
        "timestamp": int(time.time() * 1000),
    }
    try:
        response = post_json(_manual_captcha_report_url(api_base), payload, timeout=10)
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}
    return dict(response) if isinstance(response, dict) else {"ok": False, "error": "non_dict_response"}

def node_solver_execution_block_reason(solver_status, local_cdp_endpoint, expected_node_id=None):
    """Fail closed unless this node is the sole eligible challenge executor."""
    if not isinstance(solver_status, dict) or solver_status.get("error"):
        return "status_unavailable"
    if solver_status_requires_manual_only(solver_status):
        return "manual_only"
    if solver_status.get("running") is True:
        return "nas_solver_running"
    if not node_owns_last_request(solver_status, local_cdp_endpoint, expected_node_id):
        return "request_owned_elsewhere"
    return None

def notify_auth_complete(
    api_base,
    source="pc2_local_solver",
    refresh_cookie_snapshot=True,
    completion_id=None,
    challenge_id=None,
):
    url = _auth_complete_url(api_base)
    request_payload = {
        "source": source,
        "refresh_cookie_snapshot": refresh_cookie_snapshot,
        "completion_id": completion_id,
        "challenge_id": challenge_id,
    }
    attempts = max(1, min(int(AUTH_COMPLETE_REQUEST_ATTEMPTS), 10))
    last_result = {"ok": False, "error": "auth_complete_not_attempted"}
    for attempt in range(1, attempts + 1):
        try:
            payload = post_json(url, request_payload, timeout=max(AUTH_COMPLETE_REQUEST_TIMEOUT_SECONDS, 1.0))
            last_result = dict(payload) if isinstance(payload, dict) else {"ok": False, "raw": payload}
        except Exception as exc:
            last_result = {"ok": False, "error": repr(exc)}
        last_result["request_attempts"] = attempt
        if _auth_complete_response_confirmed(last_result, completion_id):
            return last_result
        if last_result.get("stale_challenge") is True:
            return last_result
        if attempt < attempts and AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS > 0:
            time.sleep(AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS * attempt)
    return last_result


def _auth_complete_response_confirmed(payload, completion_id):
    if not isinstance(payload, dict):
        return False
    if payload.get("ok") is not True or payload.get("auth_state_confirmed") is not True:
        return False
    if str(payload.get("completion_id") or "") != str(completion_id or ""):
        return False
    if payload.get("paused") is not False:
        return False
    solver_status = payload.get("captcha_solver")
    if not isinstance(solver_status, dict):
        return False
    return bool(
        solver_status.get("manual_required") is False
        and solver_status.get("force_unlock_flag_exists") is False
        and solver_status.get("paused") is False
    )


def _recent_healthy_auth_snapshot(solver_status, now=None):
    if not isinstance(solver_status, dict):
        return False
    resolved_statuses = {"manual_auth_completed", "resumed_after_cooldown", "resumed", "solved"}
    if str(solver_status.get("last_status") or "") not in resolved_statuses:
        return False
    if (
        solver_status.get("running") is True
        or solver_status.get("manual_required") is True
        or solver_status.get("force_unlock_flag_exists") is True
    ):
        return False
    snapshot = solver_status.get("cookie_snapshot_refresh")
    if not isinstance(snapshot, dict):
        return False
    result = snapshot.get("result")
    health = result.get("health") if isinstance(result, dict) else None
    if not (
        snapshot.get("status") == "completed"
        and snapshot.get("refreshed") is True
        and isinstance(health, dict)
        and health.get("healthy") is True
    ):
        return False
    try:
        finished_at = float(snapshot.get("last_finished_at_epoch") or 0)
    except (TypeError, ValueError):
        return False
    current_time = time.time() if now is None else float(now)
    age_seconds = current_time - finished_at
    return 0 <= age_seconds <= max(0.0, RECENT_HEALTHY_AUTH_MAX_AGE_SECONDS)


def _post_auth_cdp_probe_grace_active(confirmed_at, now=None):
    try:
        completed_at = float(confirmed_at or 0)
    except (TypeError, ValueError):
        return False
    if completed_at <= 0 or POST_AUTH_CDP_PROBE_GRACE_SECONDS <= 0:
        return False
    current_time = time.time() if now is None else float(now)
    age_seconds = current_time - completed_at
    return 0 <= age_seconds <= POST_AUTH_CDP_PROBE_GRACE_SECONDS


def notify_collection_resume_after_cooldown(api_base, resume_request_id, challenge_id=None):
    request_payload = {
        "source": "pc2_local_solver",
        "resume_request_id": resume_request_id,
        "challenge_id": challenge_id,
    }
    attempts = max(1, min(int(AUTH_COMPLETE_REQUEST_ATTEMPTS), 10))
    last_result = {"ok": False, "error": "resume_after_cooldown_not_attempted"}
    for attempt in range(1, attempts + 1):
        try:
            payload = post_json(
                _resume_after_cooldown_url(api_base),
                request_payload,
                timeout=max(AUTH_COMPLETE_REQUEST_TIMEOUT_SECONDS, 1.0),
            )
            last_result = dict(payload) if isinstance(payload, dict) else {"ok": False, "raw": payload}
        except Exception as exc:
            last_result = {"ok": False, "error": repr(exc)}
        last_result["request_attempts"] = attempt
        if _resume_after_cooldown_response_confirmed(last_result, resume_request_id):
            return last_result
        if last_result.get("stale_challenge") is True:
            return last_result
        if attempt < attempts and AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS > 0:
            time.sleep(AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS * attempt)
    return last_result


def _resume_after_cooldown_response_confirmed(payload, resume_request_id):
    if not isinstance(payload, dict):
        return False
    if payload.get("ok") is not True or payload.get("action") != "resume_after_cooldown":
        return False
    if payload.get("auth_state_confirmed") is not True or payload.get("paused") is not False:
        return False
    if str(payload.get("resume_request_id") or "") != str(resume_request_id or ""):
        return False
    solver_status = payload.get("captcha_solver")
    if not isinstance(solver_status, dict):
        return False
    return bool(
        solver_status.get("manual_required") is False
        and solver_status.get("force_unlock_flag_exists") is False
        and solver_status.get("paused") is False
    )

# --- Fallback escalation: push to PC1 manual auth after repeated failures ---
FALLBACK_STATE_PATH = REPO_ROOT / ".codex-temp" / "bridge-control" / "solver-fallback-state.json"
FALLBACK_FAIL_THRESHOLD = int(os.environ.get("FAPAI_SOLVER_FALLBACK_FAIL_THRESHOLD", "10"))
FALLBACK_STALL_SECONDS = int(os.environ.get("FAPAI_SOLVER_FALLBACK_STALL_SECONDS", "600"))
SOLVER_COOLDOWN_FAIL_THRESHOLD = int(
    os.environ.get("FAPAI_SOLVER_COOLDOWN_FAIL_THRESHOLD", "10")
)
SOLVER_COOLDOWN_SECONDS = float(os.environ.get("FAPAI_SOLVER_COOLDOWN_SECONDS", "180"))
SLIDER_RETRY_INTERVAL_SECONDS = float(os.environ.get("FAPAI_SLIDER_RETRY_INTERVAL_SECONDS", "5"))


def _default_fallback_state():
    return {
        "consecutive_failures": 0,
        "window_started_at": None,
        "last_success_at": None,
        "manual_pushed": False,
        "auth_complete_pending": False,
        "auth_completion_id": None,
        "auth_complete_attempts": 0,
        "auth_complete_next_retry_at": None,
        "auth_complete_last_error": None,
        "auth_complete_target_url": None,
        "slider_attempts": 0,
        "slider_attempt_started_at": None,
        "slider_last_progress_at": None,
        "slider_next_attempt_at": None,
        "solver_cooldown_until": None,
        "solver_cooldown_reason": None,
        "collection_resume_pending": False,
        "collection_resume_request_id": None,
        "collection_resume_attempts": 0,
        "collection_resume_next_retry_at": None,
        "collection_resume_last_error": None,
        "challenge_id": None,
    }


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
    state = _default_fallback_state()
    try:
        if FALLBACK_STATE_PATH.exists():
            raw = FALLBACK_STATE_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            state.update(
                {
                    "consecutive_failures": int(data.get("consecutive_failures", 0) or 0),
                    "window_started_at": float(data.get("window_started_at") or 0) or None,
                    "last_success_at": float(data.get("last_success_at") or 0) or None,
                    "manual_pushed": bool(data.get("manual_pushed", False)),
                    "auth_complete_pending": bool(data.get("auth_complete_pending", False)),
                    "auth_completion_id": str(data.get("auth_completion_id") or "").strip() or None,
                    "auth_complete_attempts": int(data.get("auth_complete_attempts", 0) or 0),
                    "auth_complete_next_retry_at": float(data.get("auth_complete_next_retry_at") or 0) or None,
                    "auth_complete_last_error": str(data.get("auth_complete_last_error") or "").strip() or None,
                    "auth_complete_target_url": str(data.get("auth_complete_target_url") or "").strip() or None,
                    "slider_attempts": int(data.get("slider_attempts", data.get("consecutive_failures", 0)) or 0),
                    "slider_attempt_started_at": float(data.get("slider_attempt_started_at") or 0) or None,
                    "slider_last_progress_at": float(data.get("slider_last_progress_at") or 0) or None,
                    "slider_next_attempt_at": float(data.get("slider_next_attempt_at") or 0) or None,
                    "solver_cooldown_until": float(data.get("solver_cooldown_until") or 0) or None,
                    "solver_cooldown_reason": str(data.get("solver_cooldown_reason") or "").strip() or None,
                    "collection_resume_pending": bool(data.get("collection_resume_pending", False)),
                    "collection_resume_request_id": str(data.get("collection_resume_request_id") or "").strip() or None,
                    "collection_resume_attempts": int(data.get("collection_resume_attempts", 0) or 0),
                    "collection_resume_next_retry_at": float(data.get("collection_resume_next_retry_at") or 0) or None,
                    "collection_resume_last_error": str(data.get("collection_resume_last_error") or "").strip() or None,
                    "challenge_id": str(data.get("challenge_id") or "").strip() or None,
                }
            )
            return state
    except Exception:
        pass
    return state

def _save_fallback_state(state):
    temporary_path = FALLBACK_STATE_PATH.with_name(f"{FALLBACK_STATE_PATH.name}.{os.getpid()}.tmp")
    try:
        FALLBACK_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary_path, FALLBACK_STATE_PATH)
    except Exception as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except Exception:
            pass
        log_event({"kind": "fallback_state_save_error", "error": repr(exc)})

def _reset_fallback_state():
    state = _default_fallback_state()
    _save_fallback_state(state)
    return state


def _sync_challenge_state(state, challenge_id):
    challenge_id = str(challenge_id or "").strip()
    if not challenge_id:
        return state, False
    current_id = str(state.get("challenge_id") or "").strip()
    if current_id == challenge_id:
        return state, False
    if current_id:
        state = _default_fallback_state()
    state["challenge_id"] = challenge_id
    _save_fallback_state(state)
    return state, bool(current_id)


def _solver_cooldown_active(state, now=None):
    """Return whether the persisted solver retry cooldown is still active."""
    if not isinstance(state, dict):
        return False
    current_time = time.time() if now is None else float(now)
    cooldown_until = float(state.get("solver_cooldown_until") or 0)
    return cooldown_until > current_time


def _begin_solver_cooldown_if_needed(state, now=None):
    if not isinstance(state, dict) or state.get("solver_cooldown_until"):
        return False
    failures = int(state.get("slider_attempts", state.get("consecutive_failures", 0)) or 0)
    threshold = max(1, SOLVER_COOLDOWN_FAIL_THRESHOLD)
    cooldown_seconds = max(0.0, SOLVER_COOLDOWN_SECONDS)
    if failures < threshold or cooldown_seconds <= 0:
        return False
    current_time = time.time() if now is None else float(now)
    state["solver_cooldown_until"] = current_time + cooldown_seconds
    state["solver_cooldown_reason"] = "repeated_solver_failures"
    state["slider_next_attempt_at"] = None
    return True


def _slider_retry_due(state, now=None):
    current_time = time.time() if now is None else float(now)
    return float(state.get("slider_next_attempt_at") or 0) <= current_time


def _record_slider_attempt_started(state, now=None):
    current_time = time.time() if now is None else float(now)
    state["slider_attempt_started_at"] = current_time
    state["slider_last_progress_at"] = current_time
    _save_fallback_state(state)
    return state


def _record_slider_attempt_failure(state, now=None):
    current_time = time.time() if now is None else float(now)
    attempts = int(state.get("slider_attempts", 0) or 0) + 1
    state["slider_attempts"] = attempts
    state["consecutive_failures"] = attempts
    state["slider_attempt_started_at"] = None
    state["slider_last_progress_at"] = current_time
    if not state.get("window_started_at"):
        state["window_started_at"] = current_time
    cooldown_started = _begin_solver_cooldown_if_needed(state, now=current_time)
    if not cooldown_started:
        state["slider_next_attempt_at"] = current_time + max(0.0, SLIDER_RETRY_INTERVAL_SECONDS)
    return {
        "attempts": attempts,
        "cooldown_started": cooldown_started,
        "next_attempt_at": state.get("slider_next_attempt_at"),
        "cooldown_until": state.get("solver_cooldown_until"),
    }


def _new_collection_resume_request_id():
    node_id = os.environ.get("FAPAI_NODE_ID", "pc2").strip() or "pc2"
    return f"{node_id}-resume-{int(time.time() * 1000)}-{uuid.uuid4().hex}"


def _mark_collection_resume_pending(state=None, now=None):
    current_time = time.time() if now is None else float(now)
    state = dict(state) if isinstance(state, dict) else _load_fallback_state()
    if not state.get("collection_resume_pending"):
        state.update(
            {
                "collection_resume_pending": True,
                "collection_resume_request_id": _new_collection_resume_request_id(),
                "collection_resume_attempts": 0,
                "collection_resume_next_retry_at": current_time,
                "collection_resume_last_error": None,
            }
        )
    _save_fallback_state(state)
    return state


def _retry_pending_collection_resume(api_base_url, state=None, now=None):
    state = dict(state) if isinstance(state, dict) else _load_fallback_state()
    if not state.get("collection_resume_pending"):
        return {"pending": False, "attempted": False, "confirmed": False, "state": state}
    current_time = time.time() if now is None else float(now)
    next_retry_at = float(state.get("collection_resume_next_retry_at") or 0)
    if next_retry_at > current_time:
        return {
            "pending": True,
            "attempted": False,
            "confirmed": False,
            "next_retry_at": next_retry_at,
            "state": state,
        }

    request_id = str(state.get("collection_resume_request_id") or "").strip()
    result = notify_collection_resume_after_cooldown(
        api_base_url,
        request_id,
        challenge_id=state.get("challenge_id"),
    )
    request_attempts = max(1, int(result.get("request_attempts", 1) or 1))
    total_attempts = int(state.get("collection_resume_attempts", 0) or 0) + request_attempts
    if result.get("stale_challenge") is True:
        reset_state = _reset_fallback_state()
        return {
            "pending": False,
            "attempted": True,
            "confirmed": False,
            "superseded": True,
            "result": result,
            "state": reset_state,
        }
    if _resume_after_cooldown_response_confirmed(result, request_id):
        reset_state = _reset_fallback_state()
        return {
            "pending": False,
            "attempted": True,
            "confirmed": True,
            "result": result,
            "state": reset_state,
        }

    error = str(result.get("error") or "").strip()
    if not error:
        try:
            error = json.dumps(result, ensure_ascii=False, sort_keys=True)
        except Exception:
            error = "NAS did not explicitly confirm collection resume"
    retry_delay = _auth_complete_retry_delay(total_attempts)
    state.update(
        {
            "collection_resume_pending": True,
            "collection_resume_attempts": total_attempts,
            "collection_resume_next_retry_at": current_time + retry_delay,
            "collection_resume_last_error": error[:1000],
        }
    )
    _save_fallback_state(state)
    return {
        "pending": True,
        "attempted": True,
        "confirmed": False,
        "next_retry_at": state["collection_resume_next_retry_at"],
        "result": result,
        "state": state,
    }


def _new_auth_completion_id():
    node_id = os.environ.get("FAPAI_NODE_ID", "pc2").strip() or "pc2"
    return f"{node_id}-{int(time.time() * 1000)}-{uuid.uuid4().hex}"


def _mark_auth_complete_pending(target_url, challenge_id=None):
    state = _load_fallback_state()
    state.update(
        {
            "last_success_at": time.time(),
            "manual_pushed": False,
            "auth_complete_pending": True,
            "auth_completion_id": _new_auth_completion_id(),
            "auth_complete_attempts": 0,
            "auth_complete_next_retry_at": time.time(),
            "auth_complete_last_error": None,
            "auth_complete_target_url": str(target_url or "").strip() or None,
            "collection_resume_pending": False,
            "collection_resume_request_id": None,
            "collection_resume_attempts": 0,
            "collection_resume_next_retry_at": None,
            "collection_resume_last_error": None,
        }
    )
    resolved_challenge_id = str(challenge_id or "").strip()
    if resolved_challenge_id:
        state["challenge_id"] = resolved_challenge_id
    _save_fallback_state(state)
    return state


def _completion_challenge_id(
    solver_status,
    latest_solver_status,
    target_url,
    local_cdp_endpoint,
    expected_node_id=None,
):
    """Accept a rotated challenge id only for the same owned solver request."""
    original_id = str(solver_status.get("challenge_id") or "").strip() or None
    if not isinstance(latest_solver_status, dict) or latest_solver_status.get("error"):
        return original_id
    if solver_status_requires_manual_only(latest_solver_status):
        return original_id
    if not node_owns_last_request(latest_solver_status, local_cdp_endpoint, expected_node_id):
        return original_id
    latest_request = latest_solver_status.get("last_request")
    if not isinstance(latest_request, dict):
        return original_id
    latest_target = str(latest_request.get("target_url") or latest_request.get("url") or "").strip()
    if latest_target != str(target_url or "").strip():
        return original_id
    return str(latest_solver_status.get("challenge_id") or "").strip() or original_id


def _auth_complete_retry_delay(attempts):
    exponent = max(0, min(int(attempts or 0) - 1, 6))
    return min(max(AUTH_COMPLETE_RETRY_BASE_SECONDS, 0.0) * (2 ** exponent), max(AUTH_COMPLETE_RETRY_MAX_SECONDS, 0.0))


def _clear_expired_auth_confirmation(state):
    cleared = dict(state)
    cleared.update(
        {
            "last_success_at": None,
            "auth_complete_pending": False,
            "auth_completion_id": None,
            "auth_complete_attempts": 0,
            "auth_complete_next_retry_at": None,
            "auth_complete_last_error": None,
            "auth_complete_target_url": None,
        }
    )
    _save_fallback_state(cleared)
    return cleared


def _retry_pending_auth_confirmation(api_base_url, state=None, now=None):
    state = dict(state) if isinstance(state, dict) else _load_fallback_state()
    if not state.get("auth_complete_pending"):
        return {"pending": False, "attempted": False, "confirmed": False, "state": state}
    current_time = time.time() if now is None else float(now)
    pending_started_at = float(state.get("last_success_at") or 0)
    pending_age = current_time - pending_started_at if pending_started_at > 0 else 0
    if (
        AUTH_COMPLETE_PENDING_MAX_SECONDS > 0
        and pending_started_at > 0
        and pending_age >= AUTH_COMPLETE_PENDING_MAX_SECONDS
    ):
        latest_solver_status = read_solver_status(api_base_url)
        if (
            isinstance(latest_solver_status, dict)
            and not latest_solver_status.get("error")
            and latest_solver_status.get("manual_required") is True
            and bool(latest_solver_status.get("paused"))
        ):
            cleared_state = _clear_expired_auth_confirmation(state)
            return {
                "pending": False,
                "attempted": False,
                "confirmed": False,
                "superseded": True,
                "reason": "active_challenge_after_auth_confirmation_timeout",
                "pending_age_seconds": pending_age,
                "state": cleared_state,
            }
    next_retry_at = float(state.get("auth_complete_next_retry_at") or 0)
    if next_retry_at > current_time:
        return {
            "pending": True,
            "attempted": False,
            "confirmed": False,
            "next_retry_at": next_retry_at,
            "state": state,
        }

    completion_id = str(state.get("auth_completion_id") or "").strip()
    result = notify_auth_complete(
        api_base_url,
        source="pc2_local_solver",
        completion_id=completion_id,
        challenge_id=state.get("challenge_id"),
    )
    request_attempts = max(1, int(result.get("request_attempts", 1) or 1))
    total_attempts = int(state.get("auth_complete_attempts", 0) or 0) + request_attempts
    if result.get("stale_challenge") is True:
        reset_state = _reset_fallback_state()
        return {
            "pending": False,
            "attempted": True,
            "confirmed": False,
            "superseded": True,
            "result": result,
            "state": reset_state,
        }
    if _auth_complete_response_confirmed(result, completion_id):
        reset_state = _reset_fallback_state()
        return {
            "pending": False,
            "attempted": True,
            "confirmed": True,
            "result": result,
            "state": reset_state,
        }

    error = str(result.get("error") or "").strip()
    if not error:
        try:
            error = json.dumps(result, ensure_ascii=False, sort_keys=True)
        except Exception:
            error = "NAS did not explicitly confirm cleared auth state"
    retry_delay = _auth_complete_retry_delay(total_attempts)
    state.update(
        {
            "auth_complete_pending": True,
            "auth_complete_attempts": total_attempts,
            "auth_complete_next_retry_at": current_time + retry_delay,
            "auth_complete_last_error": error[:1000],
        }
    )
    _save_fallback_state(state)
    return {
        "pending": True,
        "attempted": True,
        "confirmed": False,
        "next_retry_at": state["auth_complete_next_retry_at"],
        "result": result,
        "state": state,
    }

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

def check_cdp_browser_for_challenge_page(cdp_endpoint, target_url=None):
    """Find an existing challenge target using metadata, then fail-closed DOM evidence."""
    solver = None
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        if not isinstance(tabs, list) or not tabs:
            return None
        page_tabs = [
            tab
            for tab in tabs
            if isinstance(tab, dict)
            and tab.get("type") == "page"
            and str(tab.get("webSocketDebuggerUrl") or "").strip()
        ]
        requested_route = None
        if target_url:
            solver = CaptchaSolver(cdp_endpoint=cdp_endpoint, target_url=target_url)
            requested_route = solver._solver_target_route(target_url)
        candidates = []
        for tab in page_tabs:
            url = str(tab.get("url") or "").lower()
            title = str(tab.get("title") or "").strip().lower()
            is_challenge = (
                "/_____tmd_____/punish" in url
                or "x5secdata" in url
                or ("sec.taobao.com" in url and "punish" in url)
                or ("验证码" in title and "拦截" in title)
            )
            if is_challenge:
                candidates.append(tab)
        if requested_route:
            candidates = [
                tab
                for tab in candidates
                if solver._solver_target_route(tab.get("url")) == requested_route
            ]
        if candidates:
            tab = candidates[0]
            return {
                "_target_id": str(tab.get("id") or "").strip(),
                "_target_url": str(tab.get("url") or "").strip(),
                "_target_ws_url": str(tab.get("webSocketDebuggerUrl") or "").strip(),
            }

        if solver is None:
            solver = CaptchaSolver(cdp_endpoint=cdp_endpoint, target_url=target_url)
        dom_candidates = page_tabs
        if requested_route:
            dom_candidates = [
                tab
                for tab in page_tabs
                if solver._solver_target_route(tab.get("url")) == requested_route
            ]
        for tab in dom_candidates:
            try:
                solver._remember_target_tab(tab)
                if not solver._connect_to_target(
                    str(tab.get("webSocketDebuggerUrl") or ""),
                    str(tab.get("title") or ""),
                ):
                    continue
                summary = solver._page_challenge_summary()
                evidence = [
                    key
                    for key in ("challengePresent", "explicitFailure", "hardBlock", "hasSlider")
                    if summary.get(key) is True
                ]
                if evidence:
                    return {
                        "_target_id": str(tab.get("id") or "").strip(),
                        "_target_url": str(tab.get("url") or "").strip(),
                        "_target_ws_url": str(tab.get("webSocketDebuggerUrl") or "").strip(),
                        "_challenge_evidence": evidence,
                    }
            except Exception as error:
                log_event({
                    "kind": "cdp_challenge_probe_target_error",
                    "target_id": str(tab.get("id") or "").strip(),
                    "error_type": type(error).__name__,
                })
                continue
            finally:
                solver._close_solver_ws()
        return None
    except Exception as error:
        log_event({
            "kind": "cdp_challenge_probe_error",
            "error_type": type(error).__name__,
        })
        return None
    finally:
        if solver is not None:
            solver._close_solver_ws()


def solver_request_target_urls(last_request):
    if not isinstance(last_request, dict):
        return []
    targets = []
    for key in ("challenge_target_url", "target_url", "url"):
        target_url = str(last_request.get(key) or "").strip()
        if target_url and target_url not in targets:
            targets.append(target_url)
    return targets


def solver_request_target_url(last_request):
    targets = solver_request_target_urls(last_request)
    return targets[0] if targets else ""


def match_solver_request_target_url(last_request, selected_target_url, cdp_endpoint):
    """Revalidate the probed request route against the latest control-plane state."""
    candidates = solver_request_target_urls(last_request)
    if not candidates:
        return ""
    selected_target_url = str(selected_target_url or "").strip()
    if not selected_target_url:
        return candidates[0]
    if selected_target_url in candidates:
        return selected_target_url
    solver = CaptchaSolver(cdp_endpoint=cdp_endpoint, target_url=selected_target_url)
    selected_route = solver._solver_target_route(selected_target_url)
    if not selected_route:
        return ""
    for candidate in candidates:
        if solver._solver_target_route(candidate) == selected_route:
            return candidate
    return ""


def check_cdp_browser_for_authenticated_target(cdp_endpoint, target_url):
    """Confirm that an existing target page is healthy without opening a new tab."""
    target_url = str(target_url or "").strip()
    if not target_url:
        return None
    solver = CaptchaSolver(cdp_endpoint=cdp_endpoint, target_url=target_url)
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        if not isinstance(tabs, list):
            return None
        normalized_target = solver._normalize_target_url(target_url)
        requested_route = solver._solver_target_route(target_url)
        page_tabs = []
        exact_tabs = []
        route_tabs = []
        for tab in tabs:
            if not isinstance(tab, dict) or tab.get("type") != "page":
                continue
            tab_url = str(tab.get("url") or "").strip()
            if not tab_url or not tab.get("webSocketDebuggerUrl"):
                continue
            page_tabs.append(tab)
            normalized_tab = solver._normalize_target_url(tab_url)
            if normalized_tab == normalized_target:
                exact_tabs.append(tab)
            elif requested_route and solver._solver_target_route(tab_url) == requested_route:
                route_tabs.append(tab)
        scoped_tabs = exact_tabs + route_tabs
        target_scoped = bool(scoped_tabs)
        candidates = scoped_tabs or page_tabs
        if not candidates:
            return None

        healthy_target = None
        for tab in candidates:
            solver._remember_target_tab(tab)
            if not solver._connect_to_target(
                str(tab.get("webSocketDebuggerUrl") or ""),
                str(tab.get("title") or ""),
            ):
                return None
            try:
                summary = solver._page_challenge_summary()
            finally:
                solver._close_solver_ws()
            if (
                summary.get("challengePresent") is True
                or summary.get("loginRequired") is True
                or summary.get("explicitFailure") is True
                or summary.get("hardBlock") is True
            ):
                return None
            if summary.get("authenticatedPage") is True and healthy_target is None:
                healthy_target = {
                    "_target_id": str(tab.get("id") or "").strip(),
                    "_target_url": str(tab.get("url") or "").strip(),
                }
            elif target_scoped and summary.get("authenticatedPage") is not True:
                return None
        return healthy_target
    except Exception:
        return None
    finally:
        solver._close_solver_ws()


def check_cdp_browser_for_slider(cdp_endpoint, target_url=None):
    """Lightweight CDP check: probe browser tabs for a visible NC slider.
    Returns the slider_info dict if found, or None."""
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        if not isinstance(tabs, list) or not tabs:
            return None
        import websocket

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

        challenge_tabs = []
        page_tabs = []
        other_tabs = []
        for tab in tabs:
            if not isinstance(tab, dict) or not tab.get("webSocketDebuggerUrl"):
                continue
            url = str(tab.get("url") or "").lower()
            if "/_____tmd_____/" in url or "sec.taobao.com" in url or "login.taobao.com" in url:
                challenge_tabs.append(tab)
            elif tab.get("type") == "page":
                page_tabs.append(tab)
            elif tab.get("type") == "iframe":
                other_tabs.append(tab)

        requested_route = None
        if target_url:
            solver = CaptchaSolver(cdp_endpoint=cdp_endpoint, target_url=target_url)
            requested_route = solver._solver_target_route(target_url)
            if requested_route:
                challenge_tabs = [
                    tab
                    for tab in challenge_tabs
                    if solver._solver_target_route(tab.get("url")) == requested_route
                ]
        for target in challenge_tabs + page_tabs + other_tabs:
            ws_url = str(target.get("webSocketDebuggerUrl") or "").strip()
            ws = None
            try:
                ws = websocket.create_connection(ws_url, suppress_origin=True, timeout=5)
                ws.settimeout(5)
                send_id = 0

                def _send(method, params=None):
                    nonlocal send_id
                    send_id += 1
                    mid = send_id
                    msg = {"id": mid, "method": method, "params": params or {}}
                    ws.send(json.dumps(msg))
                    while True:
                        resp = json.loads(ws.recv())
                        if resp.get("id") == mid:
                            return resp.get("result")

                _send("Runtime.enable")
                ret = _send("Runtime.evaluate", {"expression": js, "returnByValue": True})
                value = ret.get("result", {}).get("value", {}) if isinstance(ret, dict) else {}
                if isinstance(value, dict) and value.get("found"):
                    slider_info = dict(value)
                    slider_info.update({
                        "_target_id": str(target.get("id") or "").strip(),
                        "_target_url": str(target.get("url") or "").strip(),
                        "_target_ws_url": ws_url,
                    })
                    return slider_info
            except Exception as error:
                log_event({
                    "kind": "cdp_slider_probe_target_error",
                    "target_id": str(target.get("id") or "").strip(),
                    "error_type": type(error).__name__,
                })
                continue
            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass
        return None
    except Exception as error:
        log_event({
            "kind": "cdp_slider_probe_error",
            "error_type": type(error).__name__,
        })
        return None


def run_solver_local(cdp_endpoint, target_url, max_attempts=50, probe_target=None, drag_profile_offset=0):
    log_event({
        "kind": "local_solver_start",
        "cdp_endpoint": cdp_endpoint,
        "target_url": target_url,
        "max_attempts": 1,
        "drag_profile_offset": drag_profile_offset,
    })
    try:
        solver = CaptchaSolver(cdp_endpoint=cdp_endpoint, target_url=target_url)
        if isinstance(probe_target, dict):
            solver._remember_target_tab({
                "id": probe_target.get("_target_id"),
                "url": probe_target.get("_target_url"),
                "webSocketDebuggerUrl": probe_target.get("_target_ws_url"),
            })
        success = solver.solve(
            max_attempts=1,
            nc_retry_replay_limit=2,
            slider_find_max_retries=1,
            drag_profile_offset=drag_profile_offset,
        )
        log_event({"kind": "local_solver_end", "success": success, "failure_reason": solver.last_failure_reason})
        return bool(success)
    except Exception as exc:
        log_event({"kind": "local_solver_error", "error": repr(exc), "traceback": traceback.format_exc()})
        return False


def close_stale_challenge_probe_target(cdp_endpoint, probe_target):
    if not isinstance(probe_target, dict):
        return {"attempted": False, "closed": False, "reason": "missing_probe_target"}
    target_id = str(probe_target.get("_target_id") or "").strip()
    target_url = str(probe_target.get("_target_url") or "").strip()
    challenge_evidence = probe_target.get("_challenge_evidence")
    if not target_id:
        return {"attempted": False, "closed": False, "reason": "missing_target_id"}
    if not challenge_evidence and not CaptchaSolver._is_manual_challenge_url(target_url):
        return {"attempted": False, "closed": False, "reason": "target_not_challenge"}

    solver = CaptchaSolver(cdp_endpoint=cdp_endpoint, target_url=target_url)
    keepalive_target_id = None
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        for tab in tabs if isinstance(tabs, list) else []:
            if (
                isinstance(tab, dict)
                and tab.get("type") == "page"
                and str(tab.get("url") or "").strip().lower() == "about:blank"
                and str(tab.get("id") or "").strip() != target_id
            ):
                keepalive_target_id = str(tab.get("id") or "").strip()
                break
    except Exception:
        keepalive_target_id = None
    keepalive_reused = bool(keepalive_target_id)
    if not keepalive_target_id:
        keepalive_target_id = solver._open_keepalive_tab()
    closed = solver._close_cdp_target(target_id)
    if not closed and keepalive_target_id and not keepalive_reused:
        solver._close_cdp_target(keepalive_target_id)
    return {
        "attempted": True,
        "closed": bool(closed),
        "target_id": target_id,
        "keepalive_opened": bool(keepalive_target_id and not keepalive_reused),
        "keepalive_reused": keepalive_reused,
    }


def resolve_stale_challenge_probe_target_after_resume(cdp_endpoint, probe_target, resume_result):
    """Recover the exact challenge target after a solver restart during cooldown."""
    if isinstance(probe_target, dict):
        return probe_target
    if not isinstance(resume_result, dict):
        return None
    payload = resume_result.get("result")
    if not isinstance(payload, dict):
        return None
    solver_status = payload.get("captcha_solver")
    if not isinstance(solver_status, dict):
        return None
    for target_url in solver_request_target_urls(solver_status.get("last_request")):
        recovered_target = check_cdp_browser_for_challenge_page(
            cdp_endpoint,
            target_url=target_url,
        )
        if recovered_target:
            return recovered_target
    return None


def local_solver_loop(api_base_url=None, cdp_endpoint=None, poll_seconds=None, max_attempts=None, expected_node_id=None):
    if api_base_url is None: api_base_url = DEFAULT_API_BASE_URL
    if cdp_endpoint is None: cdp_endpoint = DEFAULT_CDP_ENDPOINT
    if poll_seconds is None: poll_seconds = DEFAULT_POLL_SECONDS
    if max_attempts is None: max_attempts = DEFAULT_MAX_ATTEMPTS
    log_event({
        "kind": "local_solver_boot",
        "api_base_url": api_base_url,
        "cdp_endpoint": cdp_endpoint,
        "poll_seconds": poll_seconds,
        "max_attempts": max_attempts,
        "expected_node_id": expected_node_id,
        "real_taobao_auto_solver_enabled": real_taobao_auto_solver_enabled(),
        "cooldown_fail_threshold": SOLVER_COOLDOWN_FAIL_THRESHOLD,
        "cooldown_seconds": SOLVER_COOLDOWN_SECONDS,
        "slider_retry_interval_seconds": SLIDER_RETRY_INTERVAL_SECONDS,
    })
    while not check_cdp_healthy(cdp_endpoint):
        log_event({"kind": "waiting_for_cdp", "cdp_endpoint": cdp_endpoint})
        time.sleep(5)
    last_probe_target = None
    last_auth_confirmed_at = 0.0
    while True:
        try:
            pending_confirmation = _retry_pending_auth_confirmation(api_base_url)
            if pending_confirmation.get("confirmed"):
                last_auth_confirmed_at = time.time()
                local_solver_loop._probe_counter = 0
                log_event(
                    {
                        "kind": "auth_complete_confirmed",
                        "result": pending_confirmation.get("result"),
                    }
                )
                # The confirmation mutates NAS pause/challenge state. Always fetch
                # a fresh snapshot before deciding whether another solve is needed.
                time.sleep(0)
                continue
            elif pending_confirmation.get("pending"):
                if pending_confirmation.get("attempted"):
                    log_event(
                        {
                            "kind": "auth_complete_retry_pending",
                            "next_retry_at": pending_confirmation.get("next_retry_at"),
                            "result": pending_confirmation.get("result"),
                        }
                    )
                time.sleep(poll_seconds)
                continue
            pending_resume = _retry_pending_collection_resume(api_base_url)
            if pending_resume.get("confirmed"):
                cleanup_target = resolve_stale_challenge_probe_target_after_resume(
                    cdp_endpoint,
                    last_probe_target,
                    pending_resume,
                )
                cleanup = close_stale_challenge_probe_target(cdp_endpoint, cleanup_target)
                last_probe_target = None
                last_auth_confirmed_at = time.time()
                local_solver_loop._probe_counter = 0
                log_event({
                    "kind": "collection_resume_confirmed",
                    "result": pending_resume.get("result"),
                    "challenge_target_cleanup": cleanup,
                })
                # Re-read NAS status after the explicit confirmation. Do not let
                # the status snapshot from before the resume trigger a solver run.
                time.sleep(0)
                continue
            if pending_resume.get("pending"):
                if pending_resume.get("attempted"):
                    log_event({
                        "kind": "collection_resume_pending",
                        "request_id": pending_resume.get("state", {}).get("collection_resume_request_id"),
                        "next_retry_at": pending_resume.get("next_retry_at"),
                        "result": pending_resume.get("result"),
                    })
                time.sleep(poll_seconds)
                continue
            solver_status = read_solver_status(api_base_url)
            if "error" in solver_status:
                log_event({"kind": "status_error", "error": solver_status["error"]})
                time.sleep(poll_seconds); continue
            paused = bool(solver_status.get("paused"))
            running = bool(solver_status.get("running"))
            manual_required = bool(solver_status.get("manual_required"))
            if (
                solver_status_requires_manual_only(solver_status)
                and not manual_challenge_registration_needed(solver_status)
            ):
                log_event({"kind": "waiting_for_manual_auth", "challenge_id": solver_status.get("challenge_id")})
                time.sleep(poll_seconds)
                continue
            # Manual escalation is opt-in. A stale fallback latch must never disable
            # the automatic solver after an operator turns manual fallback off.
            fallback_state = _load_fallback_state()
            fallback_state, challenge_reset = _sync_challenge_state(
                fallback_state,
                solver_status.get("challenge_id"),
            )
            if challenge_reset:
                last_probe_target = None
                log_event({
                    "kind": "slider_challenge_changed",
                    "challenge_id": fallback_state.get("challenge_id"),
                })
            cooldown_started = _begin_solver_cooldown_if_needed(fallback_state)
            if cooldown_started:
                _save_fallback_state(fallback_state)
                log_event({
                    "kind": "solver_cooldown_started",
                    "until": fallback_state["solver_cooldown_until"],
                    "seconds": max(0.0, SOLVER_COOLDOWN_SECONDS),
                    "consecutive_failures": fallback_state.get("consecutive_failures", 0),
                })
            if _solver_cooldown_active(fallback_state):
                _save_fallback_state(fallback_state)
                log_event({
                    "kind": "solver_cooldown_active",
                    "until": fallback_state.get("solver_cooldown_until"),
                    "reason": fallback_state.get("solver_cooldown_reason"),
                    "consecutive_failures": fallback_state.get("consecutive_failures", 0),
                })
                time.sleep(poll_seconds)
                continue
            cooldown_until = float(fallback_state.get("solver_cooldown_until") or 0)
            if cooldown_until and cooldown_until <= time.time():
                fallback_state = _mark_collection_resume_pending(fallback_state)
                log_event({
                    "kind": "solver_cooldown_elapsed",
                    "resume_request_id": fallback_state.get("collection_resume_request_id"),
                })
                resume_result = _retry_pending_collection_resume(
                    api_base_url,
                    state=fallback_state,
                )
                if resume_result.get("confirmed"):
                    cleanup_target = resolve_stale_challenge_probe_target_after_resume(
                        cdp_endpoint,
                        last_probe_target,
                        resume_result,
                    )
                    cleanup = close_stale_challenge_probe_target(cdp_endpoint, cleanup_target)
                    last_probe_target = None
                    last_auth_confirmed_at = time.time()
                    local_solver_loop._probe_counter = 0
                    log_event({
                        "kind": "collection_resume_confirmed",
                        "result": resume_result.get("result"),
                        "challenge_target_cleanup": cleanup,
                    })
                else:
                    log_event({
                        "kind": "collection_resume_pending",
                        "request_id": fallback_state.get("collection_resume_request_id"),
                        "next_retry_at": resume_result.get("next_retry_at"),
                        "result": resume_result.get("result"),
                    })
                time.sleep(poll_seconds)
                continue
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
            last_request = solver_status.get("last_request")
            requested_target_urls = solver_request_target_urls(last_request)
            requested_target_url = requested_target_urls[0] if requested_target_urls else ""
            # Secondary trigger: probe CDP for slider whenever manual_required is set.
            # The Docker solver keeps resetting the API state via manual_retry, so we check CDP directly.
            cdp_trigger = False
            probe_target = None
            probe_request_target_url = ""
            if manual_required or api_trigger:
                for candidate_target_url in requested_target_urls or [None]:
                    slider_found = check_cdp_browser_for_slider(
                        cdp_endpoint,
                        target_url=candidate_target_url,
                    )
                    if slider_found:
                        log_event({"kind": "cdp_probe_slider_found", "slider": slider_found})
                        cdp_trigger = True
                        probe_target = slider_found
                        probe_request_target_url = str(candidate_target_url or "")
                        last_probe_target = slider_found
                        break
                    requested_route = CaptchaSolver(
                        cdp_endpoint=cdp_endpoint,
                        target_url=candidate_target_url,
                    )._solver_target_route(candidate_target_url)
                    log_event({
                        "kind": "cdp_probe_no_slider",
                        "running": running,
                        "paused": paused,
                        "requested_route": requested_route,
                    })
                    challenge_found = check_cdp_browser_for_challenge_page(
                        cdp_endpoint,
                        target_url=candidate_target_url,
                    )
                    if challenge_found:
                        log_event({
                            "kind": "cdp_probe_challenge_page",
                            "target": challenge_found,
                        })
                        cdp_trigger = True
                        probe_target = challenge_found
                        probe_request_target_url = str(candidate_target_url or "")
                        last_probe_target = challenge_found
                        break
                if not cdp_trigger:
                    last_probe_target = None

            if api_trigger and not cdp_trigger:
                last_request = solver_status.get("last_request")
                target_url = solver_request_target_url(last_request)
                recent_healthy_snapshot = bool(
                    target_url and _recent_healthy_auth_snapshot(solver_status)
                )
                authenticated_target = None
                authenticated_target_url = ""
                if not recent_healthy_snapshot:
                    for candidate_target_url in requested_target_urls:
                        authenticated_target = check_cdp_browser_for_authenticated_target(
                            cdp_endpoint,
                            candidate_target_url,
                        )
                        if authenticated_target:
                            authenticated_target_url = candidate_target_url
                            log_event({
                                "kind": "cdp_authenticated_target_found",
                                "target_id": authenticated_target.get("_target_id"),
                            })
                            break
                confirmation_target_url = target_url if recent_healthy_snapshot else authenticated_target_url
                if confirmation_target_url:
                    pending_state = _mark_auth_complete_pending(
                        confirmation_target_url,
                        challenge_id=solver_status.get("challenge_id"),
                    )
                    confirmation = _retry_pending_auth_confirmation(api_base_url, state=pending_state)
                    log_event({
                        "kind": "stale_pause_auth_complete_result",
                        "result": confirmation,
                    })
                    if confirmation.get("confirmed"):
                        last_auth_confirmed_at = time.time()
                        local_solver_loop._probe_counter = 0
                else:
                    log_event({
                        "kind": "skip_api_pause_without_cdp_challenge",
                        "last_status": solver_status.get("last_status"),
                    })
                time.sleep(poll_seconds)
                continue
            # Periodic CDP probe even when API says not paused, to catch slider after Docker resets state
            _cdp_probe_counter = getattr(local_solver_loop, "_probe_counter", 0) + 1
            local_solver_loop._probe_counter = _cdp_probe_counter
            # Probe every ~30 seconds. The previous calculation multiplied the
            # poll duration by three and then treated that value as an iteration
            # count, turning a 30-second probe into a 5-minute probe at the
            # default 10-second polling interval.
            _probe_interval = max(1, int(30 / max(1, poll_seconds)))
            post_auth_probe_grace = _post_auth_cdp_probe_grace_active(last_auth_confirmed_at)
            if (
                not api_trigger
                and not cdp_trigger
                and not manual_required
                and not post_auth_probe_grace
                and _cdp_probe_counter >= _probe_interval
            ):
                _cdp_probe_counter = 0
                for candidate_target_url in requested_target_urls or [None]:
                    periodic_found = check_cdp_browser_for_slider(
                        cdp_endpoint,
                        target_url=candidate_target_url,
                    )
                    if periodic_found:
                        log_event({"kind": "cdp_periodic_probe_slider_found", "slider": periodic_found})
                        cdp_trigger = True
                        probe_target = periodic_found
                        probe_request_target_url = str(candidate_target_url or "")
                        last_probe_target = periodic_found
                        break
                    challenge_found = check_cdp_browser_for_challenge_page(
                        cdp_endpoint,
                        target_url=candidate_target_url,
                    )
                    if challenge_found:
                        log_event({"kind": "cdp_periodic_probe_challenge_page", "cdp_endpoint": cdp_endpoint})
                        cdp_trigger = True
                        probe_target = challenge_found
                        probe_request_target_url = str(candidate_target_url or "")
                        last_probe_target = challenge_found
                        break
            if not cdp_trigger:
                time.sleep(poll_seconds); continue
            # CDP probing can take several seconds. Re-read the control plane at
            # the execution boundary so a concurrently started NAS solver wins
            # instead of both processes acting on the same browser challenge.
            latest_solver_status = read_solver_status(api_base_url)
            execution_block_reason = node_solver_execution_block_reason(
                latest_solver_status,
                cdp_endpoint,
                expected_node_id,
            )
            if execution_block_reason:
                if execution_block_reason == "manual_only" and manual_challenge_registration_needed(
                    latest_solver_status
                ):
                    manual_report = notify_manual_challenge(
                        api_base_url,
                        latest_solver_status,
                        expected_node_id,
                    )
                    report_solver = manual_report.get("captcha_solver")
                    log_event({
                        "kind": "manual_challenge_reported",
                        "status": manual_report.get("status"),
                        "ok": manual_report.get("ok"),
                        "error": manual_report.get("error"),
                        "challenge_id": report_solver.get("challenge_id") if isinstance(report_solver, dict) else None,
                    })
                log_event({"kind": "local_solver_execution_blocked", "reason": execution_block_reason})
                time.sleep(poll_seconds); continue
            solver_status = latest_solver_status
            last_request = solver_status.get("last_request")
            target_url = match_solver_request_target_url(
                last_request,
                probe_request_target_url,
                cdp_endpoint,
            )
            if not target_url:
                log_event({
                    "kind": "skip_probe_target_superseded",
                    "selected_target_url": probe_request_target_url,
                })
                time.sleep(poll_seconds); continue
            if not check_cdp_healthy(cdp_endpoint):
                log_event({"kind": "cdp_unhealthy_before_solve", "cdp_endpoint": cdp_endpoint})
                time.sleep(poll_seconds); continue
            fallback_state = _load_fallback_state()
            if not _slider_retry_due(fallback_state):
                log_event({
                    "kind": "slider_retry_wait",
                    "next_attempt_at": fallback_state.get("slider_next_attempt_at"),
                    "attempts": fallback_state.get("slider_attempts", 0),
                })
                time.sleep(poll_seconds)
                continue
            scheduled_attempt = int(fallback_state.get("slider_attempts", 0) or 0) + 1
            drag_profile_offset = (scheduled_attempt - 1) % max(DEFAULT_DRAG_PROFILE_VARIANTS, 1)
            log_event({
                "kind": "slider_attempt_started",
                "attempt": scheduled_attempt,
                "max_attempts": max(1, SOLVER_COOLDOWN_FAIL_THRESHOLD),
                "drag_profile_offset": drag_profile_offset,
            })
            _record_slider_attempt_started(fallback_state)
            success = run_solver_local(
                cdp_endpoint,
                target_url,
                max_attempts=max_attempts,
                probe_target=probe_target,
                drag_profile_offset=drag_profile_offset,
            )
            if success:
                log_event({"kind": "local_solver_success"})
                completed_state = _load_fallback_state()
                completed_state["slider_attempt_started_at"] = None
                completed_state["slider_last_progress_at"] = time.time()
                _save_fallback_state(completed_state)
                completion_status = read_solver_status(api_base_url)
                completion_challenge_id = _completion_challenge_id(
                    solver_status,
                    completion_status,
                    target_url,
                    cdp_endpoint,
                    expected_node_id,
                )
                log_event({
                    "kind": "auth_completion_challenge_resolved",
                    "started_challenge_id": solver_status.get("challenge_id"),
                    "completion_challenge_id": completion_challenge_id,
                })
                pending_state = _mark_auth_complete_pending(
                    target_url,
                    challenge_id=completion_challenge_id,
                )
                confirmation = _retry_pending_auth_confirmation(api_base_url, state=pending_state)
                log_event({"kind": "auth_complete_result", "result": confirmation})
                if confirmation.get("confirmed"):
                    last_auth_confirmed_at = time.time()
                    local_solver_loop._probe_counter = 0
            else:
                log_event({"kind": "local_solver_failure"})
                state = _load_fallback_state()
                now = time.time()
                failure = _record_slider_attempt_failure(state, now=now)
                # A successful solve anywhere after a previous failure resets the window.
                last_success_at = float(state.get("last_success_at") or 0) or None
                window_started_at = float(state.get("window_started_at") or 0) or now
                stalled_seconds = now - window_started_at if last_success_at is None else now - max(last_success_at, window_started_at)
                threshold_reached = int(state["slider_attempts"]) >= FALLBACK_FAIL_THRESHOLD
                stalled = stalled_seconds >= FALLBACK_STALL_SECONDS
                cooldown_started = bool(failure.get("cooldown_started"))
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
                    "kind": "slider_attempt_failed",
                    "attempt": state["slider_attempts"],
                    "next_attempt_at": state.get("slider_next_attempt_at"),
                    "cooldown_until": state.get("solver_cooldown_until"),
                })
                log_event({
                    "kind": "pc1_manual_escalation_check",
                    "consecutive_failures": state["consecutive_failures"],
                    "stalled_seconds": round(stalled_seconds, 1),
                    "threshold": FALLBACK_FAIL_THRESHOLD,
                    "stalled_threshold_seconds": FALLBACK_STALL_SECONDS,
                    "should_push": should_push,
                    "manual_pushed": state.get("manual_pushed", False),
                })
                if cooldown_started:
                    log_event({
                        "kind": "solver_cooldown_started",
                        "until": state["solver_cooldown_until"],
                        "seconds": max(0.0, SOLVER_COOLDOWN_SECONDS),
                        "consecutive_failures": state["consecutive_failures"],
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
