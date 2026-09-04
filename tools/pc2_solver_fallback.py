from __future__ import annotations
from tools.pc2_solver_context import *  # noqa: F401,F403
from tools.pc2_solver_transport import *  # noqa: F401,F403
from tools.pc2_solver_scope import *  # noqa: F401,F403
from tools.pc2_solver_auth import *  # noqa: F401,F403


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
        "node_solver_blocked_reported": False,
        "node_solver_blocked_report_attempts": 0,
        "node_solver_blocked_report_next_retry_at": None,
        "node_solver_blocked_report_last_error": None,
        "collection_resume_pending": False,
        "collection_resume_request_id": None,
        "collection_resume_attempts": 0,
        "collection_resume_next_retry_at": None,
        "collection_resume_last_error": None,
        "challenge_id": None,
        "scope": None,
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
                    "node_solver_blocked_reported": bool(data.get("node_solver_blocked_reported", False)),
                    "node_solver_blocked_report_attempts": int(data.get("node_solver_blocked_report_attempts", 0) or 0),
                    "node_solver_blocked_report_next_retry_at": float(data.get("node_solver_blocked_report_next_retry_at") or 0) or None,
                    "node_solver_blocked_report_last_error": str(data.get("node_solver_blocked_report_last_error") or "").strip() or None,
                    "collection_resume_pending": bool(data.get("collection_resume_pending", False)),
                    "collection_resume_request_id": str(data.get("collection_resume_request_id") or "").strip() or None,
                    "collection_resume_attempts": int(data.get("collection_resume_attempts", 0) or 0),
                    "collection_resume_next_retry_at": float(data.get("collection_resume_next_retry_at") or 0) or None,
                    "collection_resume_last_error": str(data.get("collection_resume_last_error") or "").strip() or None,
                    "challenge_id": str(data.get("challenge_id") or "").strip() or None,
                    "scope": str(data.get("scope") or "").strip() or None,
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

def _sync_challenge_state(state, challenge_id, scope=None):
    challenge_id = str(challenge_id or "").strip()
    if not challenge_id:
        return state, False
    current_id = str(state.get("challenge_id") or "").strip()
    if current_id == challenge_id:
        normalized_scope = str(scope or "").strip() or None
        if normalized_scope and state.get("scope") != normalized_scope:
            state["scope"] = normalized_scope
            _save_fallback_state(state)
        return state, False
    if current_id:
        state = _default_fallback_state()
    state["challenge_id"] = challenge_id
    state["scope"] = str(scope or "").strip() or None
    _save_fallback_state(state)
    return state, bool(current_id)

def _retry_node_solver_blocked_report(
    api_base_url,
    solver_status,
    state,
    expected_node_id=None,
    now=None,
):
    current_time = time.time() if now is None else float(now)
    state_challenge_id = str(state.get("challenge_id") or "").strip()
    status_challenge_id = str(solver_status.get("challenge_id") or "").strip()
    state_scope = str(state.get("scope") or "").strip()
    status_scope = str(solver_status.get("scope") or "").strip()
    if (
        not state_challenge_id
        or state_challenge_id != status_challenge_id
        or (state_scope and status_scope and state_scope != status_scope)
    ):
        return {
            "attempted": False,
            "confirmed": False,
            "reason": "challenge_mismatch",
            "state": state,
        }
    if state.get("solver_cooldown_reason") != "repeated_solver_failures":
        return {"attempted": False, "confirmed": False, "state": state}
    if not state.get("solver_cooldown_until") or state.get("node_solver_blocked_reported"):
        return {
            "attempted": False,
            "confirmed": bool(state.get("node_solver_blocked_reported")),
            "state": state,
        }
    if float(state.get("node_solver_blocked_report_next_retry_at") or 0) > current_time:
        return {"attempted": False, "confirmed": False, "state": state}

    result = notify_solver_blocked(
        api_base_url,
        solver_status,
        state,
        expected_node_id=expected_node_id,
    )
    state["node_solver_blocked_report_attempts"] = int(
        state.get("node_solver_blocked_report_attempts", 0) or 0
    ) + 1
    confirmed = result.get("status") == "node_solver_blocked"
    state["node_solver_blocked_reported"] = confirmed
    if confirmed:
        state["node_solver_blocked_report_next_retry_at"] = None
        state["node_solver_blocked_report_last_error"] = None
    else:
        state["node_solver_blocked_report_next_retry_at"] = current_time + max(
            5.0,
            SLIDER_RETRY_INTERVAL_SECONDS,
        )
        state["node_solver_blocked_report_last_error"] = str(
            result.get("error") or result.get("status") or "report_failed"
        )
    _save_fallback_state(state)
    return {
        "attempted": True,
        "confirmed": confirmed,
        "result": result,
        "state": state,
    }

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
    resume_scope = str(state.get("scope") or "").strip()
    if resume_scope:
        result = notify_collection_resume_after_cooldown(
            api_base_url,
            request_id,
            challenge_id=state.get("challenge_id"),
            scope=resume_scope,
        )
    else:
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

__all__ = ('FALLBACK_STATE_PATH', 'FALLBACK_FAIL_THRESHOLD', 'FALLBACK_STALL_SECONDS', 'SOLVER_COOLDOWN_FAIL_THRESHOLD', 'SOLVER_COOLDOWN_SECONDS', 'SLIDER_RETRY_INTERVAL_SECONDS', '_default_fallback_state', 'manual_fallback_enabled', '_manual_fallback_latch_active', '_report_manual_captcha', '_load_fallback_state', '_save_fallback_state', '_reset_fallback_state', '_sync_challenge_state', '_retry_node_solver_blocked_report', '_solver_cooldown_active', '_begin_solver_cooldown_if_needed', '_slider_retry_due', '_record_slider_attempt_started', '_record_slider_attempt_failure', '_new_collection_resume_request_id', '_mark_collection_resume_pending', '_retry_pending_collection_resume')
