from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _solver_report_predates_auth_completion(
    payload: dict[str, Any] | None,
) -> bool:
    """Identify an in-flight worker report created before auth completed."""
    completed_at = float(SOLVER_LAST_AUTH_COMPLETED_TIME or 0)
    if completed_at <= 0 or not isinstance(payload, dict):
        return False
    raw_timestamp = payload.get("timestamp")
    if isinstance(raw_timestamp, bool):
        return False
    try:
        reported_at = float(raw_timestamp)
    except (TypeError, ValueError):
        return False
    if reported_at > 10_000_000_000:
        reported_at /= 1000.0
    if reported_at <= 0 or reported_at > completed_at:
        return False

    completed = _build_solver_request(SOLVER_LAST_AUTH_COMPLETED_REQUEST)
    incoming = _build_solver_request(payload)
    if not completed or not incoming:
        return False
    return _solver_request_matches_auth_source(completed, incoming)

def _solver_report_stale_challenge_id(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    reported_challenge_id = str(payload.get("challenge_id") or "").strip()
    if not reported_challenge_id:
        return None
    scope = _challenge_scope_for_request(payload)
    if scope in CHALLENGE_SCOPES:
        active_challenge_id = str(
            _solver_scope_runtime_status(scope).get("challenge_id") or ""
        ).strip()
    else:
        active_challenge_id = str(SOLVER_CHALLENGE_ID or "").strip()
    if reported_challenge_id == active_challenge_id:
        return None
    return reported_challenge_id

def _persist_solver_challenge_state(challenge_id: str, last_request: dict[str, Any]) -> str | None:
    path = _solver_challenge_state_path()
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    existing = _read_solver_challenge_state()
    created_at_epoch = time.time()
    if existing.get("challenge_id") == challenge_id:
        created_at_epoch = float(existing.get("created_at_epoch") or 0) or created_at_epoch
    payload = {
        "active": True,
        "challenge_id": challenge_id,
        "created_at_epoch": created_at_epoch,
        "updated_at_epoch": time.time(),
        "pause_reason": "captcha_solver",
        "last_request": dict(last_request),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except Exception as error:
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            pass
        return repr(error)
    return None

def _scope_for_challenge_id(challenge_id: str | None) -> str | None:
    normalized = str(challenge_id or "").strip()
    if not normalized:
        return None
    for scope in CHALLENGE_SCOPES:
        if str(_solver_scope_runtime_status(scope).get("challenge_id") or "").strip() == normalized:
            return scope
    return None

def _clear_solver_challenge_state(scope: str | None = None) -> str | None:
    """Clear one scoped challenge, or all challenge state for legacy callers."""
    global SOLVER_CHALLENGE_ID, SOLVER_LAST_REQUEST
    normalized_scope = _normalize_challenge_scope(scope)
    scopes = (normalized_scope,) if normalized_scope else CHALLENGE_SCOPES
    errors: list[str] = []
    legacy_payload = _read_solver_challenge_state() if normalized_scope else {}
    scoped_challenge_id = (
        str(_read_solver_scope_state(normalized_scope).get("challenge_id") or "")
        if normalized_scope
        else ""
    )
    for candidate in scopes:
        with SOLVER_SCOPE_LOCK:
            SOLVER_SCOPE_STATES[candidate] = _new_solver_scope_state()
        try:
            _solver_scope_state_path(candidate).unlink(missing_ok=True)
        except Exception as error:
            errors.append(f"{candidate}: {error!r}")
    if not normalized_scope:
        path = _solver_challenge_state_path()
        legacy_cleared = True
        try:
            path.unlink(missing_ok=True)
        except Exception as error:
            errors.append(f"legacy: {error!r}")
            legacy_cleared = False
        if legacy_cleared:
            SOLVER_CHALLENGE_ID = None
    elif str(SOLVER_CHALLENGE_ID or "").strip() and _challenge_scope_for_request(SOLVER_LAST_REQUEST) == normalized_scope:
        SOLVER_CHALLENGE_ID = None
        for other_scope in CHALLENGE_SCOPES:
            if other_scope == normalized_scope:
                continue
            other_state = _read_solver_scope_state(other_scope)
            if other_state.get("challenge_id"):
                SOLVER_CHALLENGE_ID = str(other_state.get("challenge_id"))
                SOLVER_LAST_REQUEST = dict(other_state.get("last_request") or {})
                break
    if normalized_scope and scoped_challenge_id and legacy_payload.get("challenge_id") == scoped_challenge_id:
        # A scoped solve may have refreshed the compatibility receipt. Remove
        # it only when it represented this scoped challenge; leave a newer
        # receipt from the other scope untouched.
        try:
            _solver_challenge_state_path().unlink(missing_ok=True)
        except Exception as error:
            errors.append(f"legacy: {error!r}")
    return "; ".join(errors) if errors else None

def _restore_solver_challenge_state() -> bool:
    global SOLVER_CHALLENGE_ID, SOLVER_LAST_REQUEST
    payload = _read_solver_challenge_state()
    if not payload:
        return False
    SOLVER_CHALLENGE_ID = payload["challenge_id"]
    persisted_request = payload.get("last_request")
    if isinstance(persisted_request, dict) and persisted_request:
        SOLVER_LAST_REQUEST = dict(persisted_request)
    _set_collection_pause_state(True, str(payload.get("pause_reason") or "captcha_solver"))
    return True

def _restore_solver_scope_states() -> bool:
    """Restore independent list/detail challenge latches after a process restart."""
    global SOLVER_CHALLENGE_ID, SOLVER_LAST_REQUEST
    restored = False
    for scope in CHALLENGE_SCOPES:
        state = _read_solver_scope_state(scope)
        if not state.get("challenge_id"):
            continue
        with SOLVER_SCOPE_LOCK:
            SOLVER_SCOPE_STATES[scope] = dict(state)
        _set_collection_pause_state(True, str(state.get("pause_reason") or "captcha_solver"), scope=scope)
        if not SOLVER_CHALLENGE_ID:
            SOLVER_CHALLENGE_ID = str(state.get("challenge_id"))
            SOLVER_LAST_REQUEST = dict(state.get("last_request") or {})
        restored = True
    return restored

def _begin_solver_challenge(request_payload: dict[str, Any] | None = None) -> str:
    """Create/reuse the unique challenge latch for the request's collection scope."""
    global SOLVER_CHALLENGE_ID, SOLVER_LAST_REQUEST
    supplied_request = request_payload if isinstance(request_payload, dict) else SOLVER_LAST_REQUEST
    last_request = _build_solver_request(supplied_request or {})
    # Direct legacy callers without a request use the singleton state. New
    # collection workers always pass their request explicitly, enabling scope
    # isolation without breaking old plugins/tests that only know the legacy ID.
    scope = _challenge_scope_for_request(last_request) if isinstance(request_payload, dict) else ""
    if scope in CHALLENGE_SCOPES:
        now = time.time()
        with SOLVER_SCOPE_LOCK:
            state = dict(SOLVER_SCOPE_STATES.get(scope) or _new_solver_scope_state())
        persisted = _read_solver_scope_state(scope)
        if not state.get("challenge_id") and persisted.get("challenge_id"):
            state.update(persisted)
        challenge_id = str(state.get("challenge_id") or "").strip() or f"captcha-{time.time_ns()}"
        first_seen = float(state.get("first_seen_epoch") or 0) or now
        state.update(
            {
                "challenge_id": challenge_id,
                "last_request": dict(last_request),
                "first_seen_epoch": first_seen,
                "pause_started_epoch": float(state.get("pause_started_epoch") or 0) or now,
                "paused": True,
                "pause_reason": "captcha_solver",
                "manual_required": False,
                "manual_only": False,
                "last_status": "running",
                "last_failure_reason": None,
            }
        )
        persist_error = _persist_solver_scope_state(scope, state)
        if persist_error:
            print(f"[SOLVER] Failed to persist {scope} challenge state: {persist_error}")
        # Keep the legacy singleton receipt for older operators/clients. The
        # scoped files above remain authoritative when list and detail overlap.
        legacy_error = _persist_solver_challenge_state(challenge_id, last_request)
        if legacy_error:
            print(f"[SOLVER] Failed to refresh legacy challenge state: {legacy_error}")
        _set_collection_pause_state(True, "captcha_solver", scope=scope)
        SOLVER_CHALLENGE_ID = challenge_id
        SOLVER_LAST_REQUEST = dict(last_request)
        return challenge_id

    # Legacy/unknown request path retained for older API clients and tests.
    last_request = dict(SOLVER_LAST_REQUEST) if isinstance(SOLVER_LAST_REQUEST, dict) else {}
    persisted = _read_solver_challenge_state()
    if SOLVER_CHALLENGE_ID and _collection_effectively_paused():
        if (
            not persisted
            or _solver_challenge_owner_key(persisted.get("last_request"))
            == _solver_challenge_owner_key(last_request)
        ):
            persist_error = _persist_solver_challenge_state(SOLVER_CHALLENGE_ID, last_request)
            if persist_error:
                print(f"[SOLVER] Failed to refresh persisted challenge state: {persist_error}")
            return SOLVER_CHALLENGE_ID
    if (
        persisted
        and _solver_challenge_request_key(persisted.get("last_request"))
        == _solver_challenge_request_key(last_request)
    ):
        SOLVER_CHALLENGE_ID = persisted["challenge_id"]
    else:
        SOLVER_CHALLENGE_ID = f"captcha-{time.time_ns()}"
    persist_error = _persist_solver_challenge_state(SOLVER_CHALLENGE_ID, last_request)
    if persist_error:
        print(f"[SOLVER] Failed to persist challenge state: {persist_error}")
    return SOLVER_CHALLENGE_ID

def _solver_last_request_target_url(solver_status: dict[str, Any] | None = None) -> str:
    payload = solver_status if isinstance(solver_status, dict) else _captcha_solver_runtime_status()
    last_request = payload.get("last_request")
    if not isinstance(last_request, dict):
        return ""
    return str(last_request.get("target_url") or last_request.get("url") or "").strip()

def _solver_request_scope_from_target_url(target_url: str) -> str:
    normalized_target_url = str(target_url or "").strip().lower()
    if not normalized_target_url:
        return "unknown"
    if "sf-item.taobao.com" in normalized_target_url or "/sf_item/" in normalized_target_url:
        return "detail"
    if "sf.taobao.com/list/" in normalized_target_url or "sf.taobao.com//list/" in normalized_target_url:
        return "seed"
    if "/punish" in normalized_target_url and "/list/" in normalized_target_url:
        return "seed"
    return "unknown"

def _solver_last_request_scope(solver_status: dict[str, Any] | None = None) -> str:
    payload = solver_status if isinstance(solver_status, dict) else _captcha_solver_runtime_status()
    last_request = payload.get("last_request")
    if isinstance(last_request, dict):
        scoped = _challenge_scope_for_request(last_request)
        if scoped in CHALLENGE_SCOPES:
            return scoped
    return _solver_request_scope_from_target_url(_solver_last_request_target_url(payload))

def _solver_request_scope(request_payload: dict[str, Any] | None = None) -> str:
    if not isinstance(request_payload, dict):
        return "unknown"
    target_url = request_payload.get("target_url") or request_payload.get("url") or ""
    return _solver_request_scope_from_target_url(str(target_url))

def _seed_stage_has_remaining_work(status_payload: dict[str, Any]) -> bool:
    return any(
        int(status_payload.get(key, 0) or 0) > 0
        for key in (
            "seed_scan_job_pending",
            "seed_scan_job_in_progress",
            "seed_scan_progress_pending",
            "seed_scan_progress_in_progress",
        )
    )

def _collection_runtime_state_label_from_status_payload(status_payload: dict[str, Any]) -> str:
    solver_status = status_payload.get("captcha_solver")
    if not isinstance(solver_status, dict):
        solver_status = {}

    manual_required = bool(solver_status.get("manual_required") or solver_status.get("force_unlock_flag_exists"))
    if manual_required:
        if _solver_last_request_scope(solver_status) == "detail" and _seed_stage_has_remaining_work(status_payload):
            return "运行中"
        return "待认证"

    if bool(status_payload.get("paused")):
        return "暂停中"

    total_items = int(status_payload.get("total_ids", 0) or 0)
    raw_pending = int(status_payload.get("raw_capture_pending_count", 0) or 0)
    detail_failed = int(status_payload.get("detail_failed_count", 0) or 0)
    detail_blocked = int(status_payload.get("detail_blocked_count", 0) or 0)
    analysis_pending = int(status_payload.get("analysis_pending_count", 0) or 0)
    analysis_blocked = int(status_payload.get("analysis_blocked_count", 0) or 0)
    if total_items > 0 and raw_pending == 0 and detail_failed == 0 and detail_blocked == 0 and analysis_pending == 0 and analysis_blocked == 0:
        return "已完成"
    return "运行中"

def _clear_auth_lock_after_solver_success(scope: str | None = None) -> None:
    """After an automated captcha pass, drop the durable auth lock so workers resume."""
    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON, SOLVER_MANUAL_ONLY, SOLVER_MANUAL_RESUME_EPOCH
    normalized_scope = _normalize_challenge_scope(scope)
    if not normalized_scope:
        normalized_scope = _challenge_scope_for_request(SOLVER_LAST_REQUEST)
    completed_request = dict(SOLVER_LAST_REQUEST) if isinstance(SOLVER_LAST_REQUEST, dict) else {}
    challenge_state_error = _clear_solver_challenge_state(normalized_scope or None)
    if challenge_state_error:
        SOLVER_LAST_STATUS = "manual_required"
        SOLVER_LAST_FAILURE_REASON = "manual_required"
        _set_collection_pause_state(True, "manual_required", scope=normalized_scope or None)
        print(f"[SOLVER] Failed to clear persisted challenge state after success: {challenge_state_error}")
        return
    SOLVER_LAST_STATUS = "solved"
    SOLVER_LAST_FAILURE_REASON = None
    SOLVER_MANUAL_ONLY = False
    SOLVER_MANUAL_RESUME_EPOCH = time.time()
    _remember_solver_auth_completion(completed_request)
    if normalized_scope:
        _set_collection_pause_state(False, scope=normalized_scope)
    elif PAUSED and COLLECTION_PAUSE_REASON in {None, "captcha_solver", "manual_required"}:
        _set_collection_pause_state(False)
    flag_path = _solver_force_unlock_flag_path()
    flag_scope = _solver_manual_flag_scope()
    if os.path.exists(flag_path) and (
        not normalized_scope or not flag_scope or flag_scope == normalized_scope
    ):
        try:
            os.remove(flag_path)
            print("[SOLVER] Cleared force_unlock.flag after automated captcha success.")
        except Exception as error:
            print(f"[SOLVER] Failed to remove force_unlock.flag after success: {error}")
    if normalized_scope:
        try:
            Path(_solver_scope_manual_flag_path(normalized_scope)).unlink(missing_ok=True)
        except Exception as error:
            print(f"[SOLVER] Failed to remove scoped manual flag after success: {error}")

def _clear_solver_manual_required_state() -> None:
    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON, SOLVER_MANUAL_ONLY
    if SOLVER_LAST_STATUS == "manual_required":
        SOLVER_LAST_STATUS = "resumed"
    if SOLVER_LAST_FAILURE_REASON == "manual_required":
        SOLVER_LAST_FAILURE_REASON = None
    SOLVER_MANUAL_ONLY = False

def _clear_solver_running_state() -> None:
    global SOLVER_RUNNING, SOLVER_PENDING_TOKEN, SOLVER_START_TIME, SOLVER_LAST_FINISHED_TIME
    with SOLVER_LOCK:
        if SOLVER_RUNNING:
            SOLVER_LAST_FINISHED_TIME = time.time()
        SOLVER_RUNNING = False
        SOLVER_PENDING_TOKEN = None
        SOLVER_START_TIME = 0

def _request_solver_cancel() -> None:
    global SOLVER_CANCEL_EPOCH
    SOLVER_CANCEL_EPOCH = time.time()

def _clear_solver_manual_required_pause(
    *, preserve_running_state: bool = False, scope: str | None = None
) -> str | None:
    global SOLVER_MANUAL_RESUME_EPOCH
    normalized_scope = _normalize_challenge_scope(scope)
    flag_path = _solver_force_unlock_flag_path()
    flag_scope = _solver_manual_flag_scope()
    if os.path.exists(flag_path) and (
        not normalized_scope or not flag_scope or flag_scope == normalized_scope
    ):
        try:
            os.remove(flag_path)
        except Exception as error:
            return str(error)
    if normalized_scope:
        scoped_flag_path = _solver_scope_manual_flag_path(normalized_scope)
        try:
            Path(scoped_flag_path).unlink(missing_ok=True)
        except Exception as error:
            return str(error)
    challenge_state_error = _clear_solver_challenge_state(normalized_scope or None)
    if challenge_state_error:
        return challenge_state_error
    _set_collection_pause_state(False, scope=normalized_scope or None)
    SOLVER_MANUAL_RESUME_EPOCH = time.time()
    if not preserve_running_state:
        _clear_solver_running_state()
    _clear_solver_manual_required_state()
    return None

def _clear_solver_manual_required_pause_compat(scope: str | None = None) -> str | None:
    """Call the scoped cleanup while tolerating legacy test/plugin overrides."""
    try:
        return _clear_solver_manual_required_pause(scope=scope)
    except TypeError as error:
        if "unexpected keyword" not in str(error):
            raise
        return _clear_solver_manual_required_pause()

def _mark_solver_manual_required(
    *, manual_only: bool = False, scope: str | None = None
) -> str | None:
    global SOLVER_PENDING_TOKEN, SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON, SOLVER_MANUAL_REQUIRED_EPOCH
    global SOLVER_MANUAL_ONLY
    with SOLVER_LOCK:
        SOLVER_PENDING_TOKEN = None
        solver_running = bool(SOLVER_RUNNING)
    SOLVER_MANUAL_REQUIRED_EPOCH = time.time()
    SOLVER_LAST_STATUS = "manual_required"
    SOLVER_LAST_FAILURE_REASON = "manual_required"
    SOLVER_MANUAL_ONLY = bool(manual_only)
    if solver_running:
        _request_solver_cancel()
    normalized_scope = _normalize_challenge_scope(scope)
    if normalized_scope:
        with SOLVER_SCOPE_LOCK:
            state = dict(SOLVER_SCOPE_STATES.get(normalized_scope) or _new_solver_scope_state())
            state.update(
                {
                    "paused": True,
                    "pause_reason": "manual_required",
                    "manual_required": True,
                    "manual_only": bool(manual_only),
                    "last_status": "manual_required",
                    "last_failure_reason": "manual_required",
                }
            )
        _persist_solver_scope_state(normalized_scope, state)
    _set_collection_pause_state(True, "manual_required", scope=normalized_scope or None)
    flag_error = _write_solver_manual_required_flag(
        SOLVER_MANUAL_REQUIRED_EPOCH,
        scope=normalized_scope or None,
    )
    if normalized_scope:
        # Retain the legacy flag for old operators while the scoped flag above
        # is authoritative for independent workers.
        legacy_error = _write_solver_manual_required_flag(SOLVER_MANUAL_REQUIRED_EPOCH)
        return flag_error or legacy_error
    return flag_error

__all__ = ["_solver_report_predates_auth_completion", "_solver_report_stale_challenge_id", "_persist_solver_challenge_state", "_scope_for_challenge_id", "_clear_solver_challenge_state", "_restore_solver_challenge_state", "_restore_solver_scope_states", "_begin_solver_challenge", "_solver_last_request_target_url", "_solver_request_scope_from_target_url", "_solver_last_request_scope", "_solver_request_scope", "_seed_stage_has_remaining_work", "_collection_runtime_state_label_from_status_payload", "_clear_auth_lock_after_solver_success", "_clear_solver_manual_required_state", "_clear_solver_running_state", "_request_solver_cancel", "_clear_solver_manual_required_pause", "_clear_solver_manual_required_pause_compat", "_mark_solver_manual_required"]
