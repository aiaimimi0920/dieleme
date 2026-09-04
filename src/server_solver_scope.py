from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _runtime_env_flag(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}

def _real_taobao_auto_solver_enabled() -> bool:
    """Require an explicit production opt-in for automatic Taobao solving."""
    return _runtime_env_flag("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", False)

def _normalize_challenge_scope(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"list", "seed", "search", "listing"}:
        return "seed"
    if normalized in {"detail", "details", "item"}:
        return "detail"
    return ""

def _challenge_scope_for_request(request_payload: dict[str, Any] | None) -> str:
    payload = request_payload if isinstance(request_payload, dict) else {}
    explicit = _normalize_challenge_scope(payload.get("scope"))
    if explicit:
        return explicit
    target_url = str(
        payload.get("challenge_target_url")
        or payload.get("target_url")
        or payload.get("url")
        or ""
    )
    return _normalize_challenge_scope(_solver_request_scope_from_target_url(target_url))

def _new_solver_scope_state() -> dict[str, Any]:
    return {
        "challenge_id": None,
        "last_request": {},
        "first_seen_epoch": 0.0,
        "pause_started_epoch": 0.0,
        "paused": False,
        "pause_reason": None,
        "manual_required": False,
        "last_status": "idle",
        "last_failure_reason": None,
        "node_solver_blocked": False,
        "node_solver_blocked_at_epoch": 0.0,
        "node_solver_blocked_reason": None,
        "node_solver_blocked_attempts": 0,
        "force_reset_required": False,
    }

def _solver_scope_state_path(scope: str) -> Path:
    normalized_scope = _normalize_challenge_scope(scope) or "unknown"
    return _solver_scope_state_root_path() / f"solver-challenge-state-{normalized_scope}.json"

def _solver_scope_state_root_path() -> Path:
    global SOLVER_SCOPE_STATE_ROOT
    configured_state_dir = str(os.getenv("FAPAI_SOLVER_STATE_DIR") or "").strip()
    if configured_state_dir:
        state_dir = configured_state_dir
    else:
        # Keep scoped receipts beside the legacy receipt.  Besides preserving
        # one durable state root in production, this lets callers/tests that
        # redirect the legacy path atomically redirect both state machines.
        try:
            state_dir = str(Path(_solver_challenge_state_path()).parent)
        except Exception:
            state_dir = DATA_DIR
    state_dir = str(state_dir).strip() or DATA_DIR
    try:
        root = str(Path(state_dir).expanduser().resolve())
    except OSError:
        root = str(Path(state_dir).expanduser())
    with SOLVER_SCOPE_LOCK:
        if SOLVER_SCOPE_STATE_ROOT != root:
            SOLVER_SCOPE_STATE_ROOT = root
            SOLVER_SCOPE_STATES.clear()
            SOLVER_SCOPE_STATES.update({scope: _new_solver_scope_state() for scope in CHALLENGE_SCOPES})
    return Path(root)

def _read_solver_scope_state(scope: str) -> dict[str, Any]:
    normalized_scope = _normalize_challenge_scope(scope)
    if not normalized_scope:
        return _new_solver_scope_state()
    with SOLVER_SCOPE_LOCK:
        state = dict(SOLVER_SCOPE_STATES.get(normalized_scope) or _new_solver_scope_state())
    state_path = _solver_scope_state_path(normalized_scope)
    if state.get("challenge_id") and not state_path.exists():
        # Do not let an in-memory latch from a previous runtime/test leak into
        # a new state directory. Persisted latches are the source of truth for
        # scopes that are not the latest request.
        return _new_solver_scope_state()
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return state
    if not isinstance(payload, dict) or payload.get("active") is not True:
        # An explicit inactive receipt wins over any in-memory state left by a
        # prior test/process.  This also prevents a cleared scope from keeping
        # the aggregate pause latch set after a restart.
        cleared = _new_solver_scope_state()
        with SOLVER_SCOPE_LOCK:
            SOLVER_SCOPE_STATES[normalized_scope] = dict(cleared)
        return cleared
    state.update(
        {
            "challenge_id": str(payload.get("challenge_id") or "").strip() or None,
            "last_request": dict(payload.get("last_request") or {}) if isinstance(payload.get("last_request"), dict) else {},
            "first_seen_epoch": float(payload.get("first_seen_epoch") or payload.get("created_at_epoch") or 0),
            "pause_started_epoch": float(payload.get("pause_started_epoch") or payload.get("created_at_epoch") or 0),
            "paused": bool(payload.get("paused", True)),
            "pause_reason": str(payload.get("pause_reason") or "captcha_solver").strip() or "captcha_solver",
            "manual_required": bool(payload.get("manual_required", False)),
            "manual_only": bool(payload.get("manual_only", False)),
            "last_status": str(payload.get("last_status") or "running"),
            "last_failure_reason": str(payload.get("last_failure_reason") or "").strip() or None,
            "node_solver_blocked": bool(payload.get("node_solver_blocked", False)),
            "node_solver_blocked_at_epoch": float(payload.get("node_solver_blocked_at_epoch") or 0),
            "node_solver_blocked_reason": str(payload.get("node_solver_blocked_reason") or "").strip() or None,
            "node_solver_blocked_attempts": int(payload.get("node_solver_blocked_attempts") or 0),
        }
    )
    return state

def _persist_solver_scope_state(scope: str, state: dict[str, Any]) -> str | None:
    normalized_scope = _normalize_challenge_scope(scope)
    if not normalized_scope:
        return None
    path = _solver_scope_state_path(normalized_scope)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    payload = {
        "active": bool(state.get("challenge_id")),
        "scope": normalized_scope,
        "challenge_id": state.get("challenge_id"),
        "first_seen_epoch": float(state.get("first_seen_epoch") or 0),
        "pause_started_epoch": float(state.get("pause_started_epoch") or 0),
        "updated_at_epoch": time.time(),
        "paused": bool(state.get("paused")),
        "pause_reason": state.get("pause_reason"),
        "manual_required": bool(state.get("manual_required")),
        "manual_only": bool(state.get("manual_only")),
        "last_status": state.get("last_status"),
        "last_failure_reason": state.get("last_failure_reason"),
        "node_solver_blocked": bool(state.get("node_solver_blocked")),
        "node_solver_blocked_at_epoch": float(state.get("node_solver_blocked_at_epoch") or 0),
        "node_solver_blocked_reason": state.get("node_solver_blocked_reason"),
        "node_solver_blocked_attempts": int(state.get("node_solver_blocked_attempts") or 0),
        "last_request": dict(state.get("last_request") or {}),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
        with SOLVER_SCOPE_LOCK:
            SOLVER_SCOPE_STATES[normalized_scope] = dict(state)
    except Exception as error:
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            pass
        return repr(error)
    return None

def _scope_challenge_age(scope: str, now: float | None = None) -> float:
    state = _read_solver_scope_state(scope)
    first_seen = float(state.get("first_seen_epoch") or 0)
    if first_seen <= 0 or not state.get("challenge_id"):
        return 0.0
    return max(0.0, (time.time() if now is None else float(now)) - first_seen)

def _force_reset_solver_scope(
    scope: str | None,
    challenge_id: str | None = None,
) -> dict[str, Any]:
    """Reset one stuck list/detail challenge after the safety timeout."""
    normalized_scope = _normalize_challenge_scope(scope)
    if normalized_scope not in CHALLENGE_SCOPES:
        return {"ok": False, "force_reset": False, "error": "scope must be seed or detail"}
    status = _solver_scope_runtime_status(normalized_scope)
    active_id = str(status.get("challenge_id") or "").strip()
    reported_id = str(challenge_id or "").strip()
    if not active_id:
        return {"ok": True, "force_reset": False, "scope": normalized_scope, "reason": "no_active_challenge"}
    if reported_id and reported_id != active_id:
        return {
            "ok": False,
            "force_reset": False,
            "scope": normalized_scope,
            "challenge_id": active_id,
            "stale_challenge": True,
            "error": "challenge_id does not match the active scoped challenge",
        }
    age = float(status.get("challenge_age_seconds") or 0)
    if age < CHALLENGE_FORCE_RESET_SECONDS:
        return {
            "ok": False,
            "force_reset": False,
            "scope": normalized_scope,
            "challenge_id": active_id,
            "challenge_age_seconds": age,
            "retry_after_seconds": max(0, int(math.ceil(CHALLENGE_FORCE_RESET_SECONDS - age))),
            "error": "challenge has not reached the force-reset safety timeout",
        }
    recovery_request = dict(status.get("last_request") or {})
    clear_error = _clear_solver_challenge_state(normalized_scope)
    if clear_error:
        return {
            "ok": False,
            "force_reset": False,
            "scope": normalized_scope,
            "challenge_id": active_id,
            "error": clear_error,
        }
    _set_collection_pause_state(False, scope=normalized_scope)
    try:
        Path(_solver_scope_manual_flag_path(normalized_scope)).unlink(missing_ok=True)
    except Exception:
        pass
    # The legacy flag is aggregate state.  Once the reset scope is clear, only
    # keep it if another independent scope still requires manual recovery;
    # otherwise it would continue to report a global pause after both scoped
    # collectors have resumed.
    try:
        other_scope_requires_manual = any(
            bool(_read_solver_scope_state(candidate).get("manual_required"))
            for candidate in CHALLENGE_SCOPES
            if candidate != normalized_scope
        )
        if not other_scope_requires_manual:
            Path(_solver_force_unlock_flag_path()).unlink(missing_ok=True)
    except Exception:
        pass
    _remember_solver_force_reset_recovery(normalized_scope, recovery_request)
    return {
        "ok": True,
        "force_reset": True,
        "scope": normalized_scope,
        "previous_challenge_id": active_id,
        "challenge_age_seconds": age,
        "report_grace_seconds": SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS,
        "paused": _collection_effectively_paused(),
        "captcha_solver": _captcha_solver_runtime_status(),
    }

def _solver_force_unlock_flag_path() -> str:
    state_dir = str(os.getenv("FAPAI_SOLVER_STATE_DIR") or DATA_DIR).strip() or DATA_DIR
    return os.path.join(state_dir, "force_unlock.flag")

def _solver_scope_manual_flag_path(scope: str) -> str:
    normalized = _normalize_challenge_scope(scope)
    state_dir = str(os.getenv("FAPAI_SOLVER_STATE_DIR") or DATA_DIR).strip() or DATA_DIR
    return str(Path(state_dir) / f"force_unlock-{normalized}.flag")

def _solver_force_unlock_flag_exists() -> bool:
    try:
        return os.path.exists(_solver_force_unlock_flag_path())
    except Exception:
        return False

def _is_client_disconnect_error(error: BaseException) -> bool:
    return isinstance(error, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)) or getattr(
        error,
        "errno",
        None,
    ) in {32, 104, 10053, 10054}

def _collection_effectively_paused() -> bool:
    if _solver_force_unlock_flag_exists():
        return True
    if not PAUSED:
        return False
    if _solver_transient_pause_active():
        return False
    return True

def _collection_scope_effectively_paused(scope: str) -> bool:
    """Return pause state for one collector without inheriting the other scope."""
    if _solver_force_unlock_flag_exists():
        return True
    normalized = _normalize_challenge_scope(scope)
    if normalized not in CHALLENGE_SCOPES:
        return _collection_effectively_paused()
    scoped = _solver_scope_runtime_status(normalized)
    if scoped.get("paused") or scoped.get("manual_required"):
        return True
    # Operator pause is intentionally global. A solver pause is scoped and
    # must not stop the other collector.
    if PAUSED and COLLECTION_PAUSE_REASON in (None, "operator"):
        return True
    if COLLECTION_PAUSE_REASON in {"manual_required"} and not any(
        _solver_scope_runtime_status(candidate).get("paused")
        for candidate in CHALLENGE_SCOPES
    ):
        return True
    return False

def _set_collection_pause_state(
    paused: bool,
    reason: str | None = None,
    *,
    scope: str | None = None,
) -> None:
    global PAUSED, COLLECTION_PAUSE_REASON
    normalized_scope = _normalize_challenge_scope(scope)
    if normalized_scope:
        with SOLVER_SCOPE_LOCK:
            state = dict(SOLVER_SCOPE_STATES.get(normalized_scope) or _new_solver_scope_state())
            state["paused"] = bool(paused)
            state["pause_reason"] = str(reason or "").strip() or None if paused else None
            if paused and not state.get("pause_started_epoch"):
                state["pause_started_epoch"] = time.time()
            if not paused:
                state["force_reset_required"] = False
        _persist_solver_scope_state(normalized_scope, state)
        if paused:
            PAUSED = True
            if COLLECTION_PAUSE_REASON not in {"operator", "manual_required"}:
                COLLECTION_PAUSE_REASON = str(reason or "captcha_solver").strip() or "captcha_solver"
        elif not any(
            bool(_read_solver_scope_state(candidate).get("paused"))
            for candidate in CHALLENGE_SCOPES
        ) and COLLECTION_PAUSE_REASON in {"captcha_solver", "manual_required"}:
            PAUSED = False
            COLLECTION_PAUSE_REASON = None
        return
    PAUSED = bool(paused)
    if PAUSED:
        COLLECTION_PAUSE_REASON = str(reason or "").strip() or None
    else:
        COLLECTION_PAUSE_REASON = None

def _solver_transient_pause_active() -> bool:
    return bool(
        PAUSED
        and COLLECTION_PAUSE_REASON == "captcha_solver"
        and SOLVER_RUNNING
        and SOLVER_LAST_STATUS == "running"
        and SOLVER_LAST_FAILURE_REASON != "manual_required"
    )

def _solver_scope_runtime_status(scope: str, now: float | None = None) -> dict[str, Any]:
    normalized_scope = _normalize_challenge_scope(scope) or "seed"
    current_time = time.time() if now is None else float(now)
    state = _read_solver_scope_state(normalized_scope)
    challenge_id = str(state.get("challenge_id") or "").strip() or None
    first_seen = float(state.get("first_seen_epoch") or 0)
    age = max(0.0, current_time - first_seen) if challenge_id and first_seen > 0 else 0.0
    force_reset_required = bool(
        challenge_id
        and bool(state.get("paused"))
        and age >= CHALLENGE_FORCE_RESET_SECONDS
    )
    state["force_reset_required"] = force_reset_required
    return {
        "scope": normalized_scope,
        "challenge_id": challenge_id,
        "first_seen_epoch": first_seen or None,
        "pause_started_epoch": float(state.get("pause_started_epoch") or 0) or None,
        "challenge_age_seconds": age,
        "paused": bool(state.get("paused")),
        "pause_reason": state.get("pause_reason"),
        "manual_required": bool(state.get("manual_required")),
        "manual_only": bool(state.get("manual_only")),
        "force_reset_required": force_reset_required,
        "last_status": state.get("last_status") or "idle",
        "last_failure_reason": state.get("last_failure_reason"),
        "node_solver_blocked": bool(state.get("node_solver_blocked")),
        "node_solver_blocked_at_epoch": float(state.get("node_solver_blocked_at_epoch") or 0) or None,
        "node_solver_blocked_reason": state.get("node_solver_blocked_reason"),
        "node_solver_blocked_attempts": int(state.get("node_solver_blocked_attempts") or 0),
        "last_request": dict(state.get("last_request") or {}),
    }

__all__ = ["_runtime_env_flag", "_real_taobao_auto_solver_enabled", "_normalize_challenge_scope", "_challenge_scope_for_request", "_new_solver_scope_state", "_solver_scope_state_path", "_solver_scope_state_root_path", "_read_solver_scope_state", "_persist_solver_scope_state", "_scope_challenge_age", "_force_reset_solver_scope", "_solver_force_unlock_flag_path", "_solver_scope_manual_flag_path", "_solver_force_unlock_flag_exists", "_is_client_disconnect_error", "_collection_effectively_paused", "_collection_scope_effectively_paused", "_set_collection_pause_state", "_solver_transient_pause_active", "_solver_scope_runtime_status"]
