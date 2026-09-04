from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _captcha_solver_runtime_status(now: float | None = None) -> dict[str, Any]:
    current_time = time.time() if now is None else now
    with SOLVER_LOCK:
        active_run = bool(SOLVER_RUNNING)
        queued = SOLVER_PENDING_TOKEN is not None
        started_at = float(SOLVER_START_TIME or 0)
    running = bool(active_run or queued)
    force_unlock_flag_exists = _solver_force_unlock_flag_exists()
    last_request = dict(SOLVER_LAST_REQUEST) if isinstance(SOLVER_LAST_REQUEST, dict) else {}
    if not last_request and force_unlock_flag_exists:
        last_request = _solver_manual_flag_request()
    elapsed_seconds = max(int(current_time - started_at), 0) if active_run and started_at > 0 else 0
    if not last_request and SOLVER_LAST_STATUS == "idle" and not force_unlock_flag_exists:
        scope_statuses = {scope: _solver_scope_runtime_status(scope, now=current_time) for scope in CHALLENGE_SCOPES}
        for status in scope_statuses.values():
            status.update({"challenge_id": None, "paused": False, "manual_required": False, "force_reset_required": False})
    else:
        scope_statuses = {
            scope: _solver_scope_runtime_status(scope, now=current_time)
            for scope in CHALLENGE_SCOPES
        }
    active_scope = _challenge_scope_for_request(last_request)
    if active_scope not in CHALLENGE_SCOPES:
        active_scope = next(
            (
                scope
                for scope, status in scope_statuses.items()
                if status.get("challenge_id")
            ),
            None,
        )
    selected_scope = scope_statuses.get(active_scope or "", {})
    manual_required = bool(
        force_unlock_flag_exists
        or (PAUSED and SOLVER_LAST_STATUS == "manual_required")
        or any(status.get("manual_required") for status in scope_statuses.values())
    )
    scoped_manual_only = bool(selected_scope.get("manual_only")) if selected_scope else False
    manual_only = bool(
        scoped_manual_only
        or (
            active_scope not in CHALLENGE_SCOPES
            and (SOLVER_MANUAL_ONLY or _solver_manual_flag_is_manual_only())
        )
        or _solver_target_requires_manual_only(last_request)
    )
    delegated_to_node = bool(last_request and _solver_request_delegated_to_node(last_request))
    request_node_id = str(last_request.get("node_id") or "").strip().lower()
    request_owner = (request_node_id or "node") if delegated_to_node else ("nas" if last_request else None)
    execution_mode = (
        "manual"
        if manual_only
        else "delegated_node"
        if delegated_to_node
        else "nas_local"
        if last_request
        else "idle"
    )
    manual_retry_next_epoch = _manual_solver_retry_next_epoch(current_time) if manual_required else None
    return {
        "running": running,
        "queued": queued,
        "started_at_epoch": started_at if started_at > 0 else None,
        "elapsed_seconds": elapsed_seconds,
        "last_status": SOLVER_LAST_STATUS,
        "last_failure_reason": SOLVER_LAST_FAILURE_REASON,
        "last_finished_at_epoch": SOLVER_LAST_FINISHED_TIME if SOLVER_LAST_FINISHED_TIME else None,
        "manual_required": manual_required,
        "manual_only": manual_only,
        "execution_mode": execution_mode,
        "request_owner": request_owner,
        "delegated_to_node_solver": delegated_to_node,
        "nas_solver_active": running,
        "node_solver_expected": bool(delegated_to_node and not manual_only),
        "real_taobao_auto_solver_enabled": _real_taobao_auto_solver_enabled(),
        "force_unlock_flag_exists": force_unlock_flag_exists,
        "paused": bool(
            _collection_effectively_paused()
            or any(status.get("paused") for status in scope_statuses.values())
        ),
        "pause_reason": COLLECTION_PAUSE_REASON,
        "last_request": last_request,
        "manual_retry_enabled": _manual_solver_retry_enabled(),
        "manual_retry_interval_seconds": _manual_solver_retry_interval_seconds(),
        "solver_max_runtime_seconds": _solver_max_runtime_seconds(),
        "manual_retry_attempts": int(SOLVER_MANUAL_RETRY_ATTEMPTS or 0),
        "manual_retry_last_epoch": SOLVER_MANUAL_RETRY_LAST_EPOCH or None,
        "manual_retry_next_epoch": manual_retry_next_epoch,
        "challenge_id": SOLVER_CHALLENGE_ID,
        "cookie_snapshot_refresh": _auth_cookie_snapshot_runtime_status(),
        # New consumers use these independent state machines.  The legacy
        # singleton fields above remain for older workers and API clients.
        "scope": active_scope or None,
        "scopes": scope_statuses,
        "collection_scopes": scope_statuses,
        "collection_pause_markers": {
            scope: "paused" if bool(status.get("paused") or status.get("manual_required")) else "collecting"
            for scope, status in scope_statuses.items()
        },
    }

def _solver_challenge_state_path() -> Path:
    state_dir = str(os.getenv("FAPAI_SOLVER_STATE_DIR") or DATA_DIR).strip() or DATA_DIR
    return Path(state_dir) / "solver-challenge-state.json"

def _read_solver_challenge_state() -> dict[str, Any]:
    try:
        payload = json.loads(_solver_challenge_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict) or payload.get("active") is not True:
        return {}
    challenge_id = str(payload.get("challenge_id") or "").strip()
    if not challenge_id:
        return {}
    last_request = payload.get("last_request")
    payload["challenge_id"] = challenge_id
    payload["last_request"] = dict(last_request) if isinstance(last_request, dict) else {}
    return payload

def _solver_challenge_request_key(request_payload: dict[str, Any] | None) -> tuple[str, str, str]:
    payload = request_payload if isinstance(request_payload, dict) else {}
    node_id = str(payload.get("node_id") or "").strip().lower()
    cdp_endpoint = str(payload.get("cdp_endpoint") or "").strip().lower().rstrip("/")
    target_url = _normalize_solver_target_url(
        payload.get("challenge_target_url") or payload.get("target_url") or payload.get("url") or ""
    )
    return node_id, cdp_endpoint, target_url

def _solver_challenge_owner_key(request_payload: dict[str, Any] | None) -> tuple[str, str]:
    node_id, cdp_endpoint, _target_url = _solver_challenge_request_key(request_payload)
    return node_id, cdp_endpoint

def _solver_detail_captured_count() -> int | None:
    if not getattr(DB_REPOSITORY, "enabled", False):
        return None
    try:
        counts = DB_REPOSITORY.seed_queue_counts()
    except Exception:
        return None
    if not isinstance(counts, dict):
        return None
    captured_status_keys = (
        "seed_item_raw_detail_captured",
        # Analysis states are included because each can only be entered after
        # raw detail HTML was captured successfully. Moving between these
        # states therefore keeps the total stable instead of inventing progress.
        "seed_item_analysis_in_progress",
        "seed_item_analysis_failed",
        "seed_item_analysis_blocked",
        "seed_item_detail_completed",
    )
    try:
        return sum(max(int(counts.get(key, 0) or 0), 0) for key in captured_status_keys)
    except (TypeError, ValueError):
        return None

def _nas_auth_recovery_pending_detail_count() -> int:
    if not getattr(DB_REPOSITORY, "enabled", False):
        return 0
    try:
        counts = DB_REPOSITORY.seed_queue_counts()
    except Exception:
        return 0
    if not isinstance(counts, dict):
        return 0
    try:
        return max(int(counts.get("seed_item_pending_detail", 0) or 0), 0) + max(
            int(counts.get("seed_item_in_progress", 0) or 0),
            0,
        )
    except (TypeError, ValueError):
        return 0

def _nas_auth_recovery_signal() -> str | None:
    if COLLECTION_PAUSE_REASON == "operator":
        return None
    solver_status = _captcha_solver_runtime_status()
    if not solver_status.get("paused"):
        return None
    if solver_status.get("manual_required"):
        return "captcha_manual_required"
    scoped_statuses = solver_status.get("scopes") or solver_status.get("collection_scopes")
    detail_status = (
        scoped_statuses.get("detail")
        if isinstance(scoped_statuses, dict)
        else None
    )
    try:
        detail_challenge_age = float((detail_status or {}).get("challenge_age_seconds") or 0)
    except (TypeError, ValueError):
        detail_challenge_age = 0.0
    if (
        isinstance(detail_status, dict)
        and detail_status.get("paused")
        and detail_challenge_age >= NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS
    ):
        return "detail_challenge_stalled"
    if isinstance(scoped_statuses, dict) and any(
        isinstance(status, dict)
        and status.get("paused")
        and status.get("node_solver_blocked")
        and status.get("node_solver_blocked_reason") == "repeated_solver_failures"
        for status in scoped_statuses.values()
    ):
        return "node_solver_retries_exhausted"
    snapshot_status = _auth_cookie_snapshot_runtime_status()
    snapshot_result = snapshot_status.get("result")
    if not isinstance(snapshot_result, dict):
        snapshot_result = {}
    if (
        snapshot_status.get("status") == "failed"
        and snapshot_result.get("reason") == "cookie_snapshot_candidate_unhealthy"
    ):
        return "cookie_snapshot_candidate_unhealthy"
    return None

def _sample_nas_auth_recovery() -> dict[str, Any]:
    return NAS_AUTH_RECOVERY.sample(
        _solver_detail_captured_count(),
        _nas_auth_recovery_pending_detail_count(),
        operator_paused=COLLECTION_PAUSE_REASON == "operator",
        recovery_signal=_nas_auth_recovery_signal(),
        recovery_signal_stall_seconds=NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS,
    )

def _nas_auth_recovery_authorized(headers: Any) -> tuple[bool, str]:
    if not NAS_AUTH_RECOVERY.enabled:
        return False, "auth recovery is disabled"
    try:
        expected = NAS_AUTH_RECOVERY_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        expected = ""
    supplied = str(headers.get("X-Fapai-Recovery-Token") or "").strip()
    if not expected:
        return False, "auth recovery token is not configured"
    if not supplied or not hmac.compare_digest(supplied, expected):
        return False, "auth recovery token is invalid"
    return True, ""

def nas_auth_recovery_watchdog_thread() -> None:
    while True:
        try:
            snapshot = _sample_nas_auth_recovery()
            active = snapshot.get("active")
            if isinstance(active, dict) and active.get("status") == "requested":
                print(
                    "[AUTH-RECOVERY] Collection stalled; PC1 authentication "
                    f"recovery requested ({active.get('recovery_id')}, "
                    f"trigger={active.get('trigger_reason')})."
                )
        except Exception as error:
            print(f"[AUTH-RECOVERY] Watchdog sample failed: {error!r}")
        time.sleep(NAS_AUTH_RECOVERY_POLL_SECONDS)

def _nas_auth_recovery_result(payload: dict[str, Any]) -> dict[str, Any]:
    recovery_id = str(payload.get("recovery_id") or "").strip()
    success = payload.get("success") is True
    reason = str(payload.get("reason") or "").strip()
    if not recovery_id:
        return {"ok": False, "error": "recovery_id is required"}
    if not success:
        return NAS_AUTH_RECOVERY.result(
            recovery_id,
            success=False,
            reason=reason or "pc2_recovery_failed",
        )
    if COLLECTION_PAUSE_REASON == "operator":
        return NAS_AUTH_RECOVERY.result(
            recovery_id,
            success=False,
            reason="operator_pause_active",
        )

    result = NAS_AUTH_RECOVERY.result(recovery_id, success=True, reason=reason)
    if not result.get("ok"):
        return result
    clear_error = _clear_solver_manual_required_pause()
    if clear_error:
        NAS_AUTH_RECOVERY.result(
            recovery_id,
            success=False,
            reason=f"clear_collection_pause_failed:{clear_error}",
        )
        return {"ok": False, "error": clear_error}
    _remember_solver_auth_completion(
        {
            "node_id": "pc2",
            "source": "nas_auth_recovery",
        }
    )
    return {
        **result,
        "paused": _collection_effectively_paused(),
        "captcha_solver": _captcha_solver_runtime_status(),
    }

def _remember_solver_auth_completion(request_payload: dict[str, Any] | None) -> None:
    global SOLVER_LAST_AUTH_COMPLETED_TIME, SOLVER_LAST_AUTH_COMPLETED_REQUEST
    global SOLVER_LAST_AUTH_DETAIL_CAPTURED_COUNT
    request = _build_solver_request(request_payload or {})
    SOLVER_LAST_AUTH_COMPLETED_TIME = time.time()
    SOLVER_LAST_AUTH_COMPLETED_REQUEST = dict(request)
    SOLVER_LAST_AUTH_DETAIL_CAPTURED_COUNT = _solver_detail_captured_count()

def _solver_request_matches_auth_source(
    completed_request: dict[str, Any],
    incoming_request: dict[str, Any],
) -> bool:
    completed_node, completed_cdp, completed_target = _solver_challenge_request_key(
        completed_request
    )
    incoming_node, incoming_cdp, incoming_target = _solver_challenge_request_key(
        incoming_request
    )
    if completed_node and incoming_node:
        return completed_node == incoming_node
    if completed_cdp and incoming_cdp:
        return completed_cdp == incoming_cdp
    return bool(
        completed_target
        and incoming_target
        and completed_target == incoming_target
    )

def _remember_solver_force_reset_recovery(
    scope: str,
    request_payload: dict[str, Any] | None,
    *,
    now: float | None = None,
) -> None:
    """Remember a scoped reset so its just-closed page cannot immediately re-lock collection."""
    normalized_scope = _normalize_challenge_scope(scope)
    request = _build_solver_request(request_payload or {})
    if normalized_scope not in CHALLENGE_SCOPES or not request:
        return
    with SOLVER_SCOPE_LOCK:
        SOLVER_SCOPE_FORCE_RESET_RECOVERIES[normalized_scope] = {
            "completed_at_epoch": time.time() if now is None else float(now),
            "request": dict(request),
        }

def _solver_force_reset_report_suppression(
    request_payload: dict[str, Any] | None,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Ignore same-scope reports briefly after a forced recovery attempt."""
    incoming = _build_solver_request(request_payload or {})
    scope = _challenge_scope_for_request(incoming)
    if scope not in CHALLENGE_SCOPES or SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS <= 0:
        return None
    with SOLVER_SCOPE_LOCK:
        recovery = dict(SOLVER_SCOPE_FORCE_RESET_RECOVERIES.get(scope) or {})
    completed_at = float(recovery.get("completed_at_epoch") or 0)
    completed_request = _build_solver_request(recovery.get("request") or {})
    if completed_at <= 0 or not completed_request or not incoming:
        return None
    current_time = time.time() if now is None else float(now)
    age = current_time - completed_at
    if age < 0 or age > SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS:
        return None
    if not _solver_request_matches_auth_source(completed_request, incoming):
        return None
    return {
        "reason": "recent_force_reset",
        "scope": scope,
        "age_seconds": age,
        "grace_seconds": SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS,
    }

def _solver_auth_report_suppression(
    request_payload: dict[str, Any] | None,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    completed_at = float(SOLVER_LAST_AUTH_COMPLETED_TIME or 0)
    if completed_at <= 0:
        return None
    current_time = time.time() if now is None else float(now)
    age = current_time - completed_at
    max_grace_seconds = max(
        SOLVER_AUTH_REPORT_GRACE_SECONDS,
        SOLVER_DETAIL_PROGRESS_GRACE_SECONDS,
    )
    if age < 0 or age > max_grace_seconds:
        return None

    completed = _build_solver_request(SOLVER_LAST_AUTH_COMPLETED_REQUEST)
    incoming = _build_solver_request(request_payload or {})
    if not completed or not incoming:
        return None
    if not _solver_request_matches_auth_source(completed, incoming):
        return None

    if SOLVER_AUTH_REPORT_GRACE_SECONDS > 0 and age <= SOLVER_AUTH_REPORT_GRACE_SECONDS:
        return {
            "reason": "recent_auth_complete",
            "age_seconds": age,
            "grace_seconds": SOLVER_AUTH_REPORT_GRACE_SECONDS,
            "captured_since_auth": 0,
        }

    baseline = SOLVER_LAST_AUTH_DETAIL_CAPTURED_COUNT
    current_count = _solver_detail_captured_count()
    if baseline is None or current_count is None:
        return None
    captured_since_auth = max(current_count - baseline, 0)
    if (
        age > SOLVER_DETAIL_PROGRESS_GRACE_SECONDS
        or captured_since_auth < SOLVER_DETAIL_PROGRESS_GRACE_MIN_ITEMS
    ):
        return None
    return {
        "reason": "recent_detail_progress",
        "age_seconds": age,
        "grace_seconds": SOLVER_DETAIL_PROGRESS_GRACE_SECONDS,
        "captured_since_auth": captured_since_auth,
    }

def _solver_report_is_recent_auth_duplicate(
    request_payload: dict[str, Any] | None,
    *,
    now: float | None = None,
) -> bool:
    """Reject delayed captcha reports from the node that just completed auth.

    Worker captcha reports are fire-and-forget and do not carry the active
    challenge id.  A report already in flight can therefore arrive after the
    solver has cleared the challenge and otherwise create a new pause.  Keep a
    short, same-node grace window so the next worker cycle can observe the
    authenticated cookie instead of reopening the just-cleared challenge. If
    detail capture then advances, extend only that same-node protection to the
    configured progress-backed window.
    """
    return _solver_auth_report_suppression(request_payload, now=now) is not None

__all__ = ["_captcha_solver_runtime_status", "_solver_challenge_state_path", "_read_solver_challenge_state", "_solver_challenge_request_key", "_solver_challenge_owner_key", "_solver_detail_captured_count", "_nas_auth_recovery_pending_detail_count", "_nas_auth_recovery_signal", "_sample_nas_auth_recovery", "_nas_auth_recovery_authorized", "nas_auth_recovery_watchdog_thread", "_nas_auth_recovery_result", "_remember_solver_auth_completion", "_solver_request_matches_auth_source", "_remember_solver_force_reset_recovery", "_solver_force_reset_report_suppression", "_solver_auth_report_suppression", "_solver_report_is_recent_auth_duplicate"]
