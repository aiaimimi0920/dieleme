from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _collection_observer_items_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    stage = str((query.get("stage") or ["links"])[0] or "links").strip().lower()
    if stage not in {"links", "details", "analysis"}:
        stage = "links"
    limit = _collection_query_int(query, "limit", 100, minimum=1, maximum=500)
    offset = _collection_query_int(query, "offset", 0, minimum=0, maximum=1_000_000)
    location_code = str((query.get("location_code") or [""])[0] or "").strip()
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "collection_observer_items"):
        return {
            "stage": stage,
            "limit": limit,
            "offset": offset,
            "location_code": location_code or None,
            "total": 0,
            "items": [],
            "db_mode": DB_REPOSITORY.enabled,
        }
    payload = DB_REPOSITORY.collection_observer_items(
        stage=stage,
        limit=limit,
        offset=offset,
        location_code=location_code or None,
    )
    payload["location_code"] = location_code or payload.get("location_code")
    payload["db_mode"] = DB_REPOSITORY.enabled
    return payload

def _collection_observer_regions_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    stage = str((query.get("stage") or ["links"])[0] or "links").strip().lower()
    if stage not in {"links", "details", "analysis"}:
        stage = "links"
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "collection_observer_regions"):
        return {"ok": True, "stage": stage, "regions": [], "db_mode": DB_REPOSITORY.enabled}
    payload = DB_REPOSITORY.collection_observer_regions(stage=stage)
    payload["db_mode"] = DB_REPOSITORY.enabled
    return payload

def _collection_observer_item_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    item_id = str((query.get("item_id") or [""])[0] or "").strip()
    max_chars = _collection_query_int(query, "max_chars", 100_000, minimum=1, maximum=1_000_000)
    if not item_id:
        return {"found": False, "error": "item_id is required", "item_id": ""}
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "collection_observer_item_detail"):
        return {"found": False, "item_id": item_id, "item": None, "occurrences": [], "artifacts": {}, "db_mode": DB_REPOSITORY.enabled}
    payload = DB_REPOSITORY.collection_observer_item_detail(item_id, max_chars=max_chars)
    payload["db_mode"] = DB_REPOSITORY.enabled
    return payload

def _collection_observer_reanalysis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    item_id = str((payload.get("item_id") or "")).strip()
    reason = str(payload.get("reason") or "operator_requested").strip() or "operator_requested"
    if not item_id:
        return {"ok": False, "error": "item_id is required", "item_id": ""}
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "requeue_seed_detail_analysis"):
        return {"ok": False, "item_id": item_id, "error": "database repository is not available", "db_mode": DB_REPOSITORY.enabled}
    result = DB_REPOSITORY.requeue_seed_detail_analysis(item_id, reason=reason)
    result["db_mode"] = DB_REPOSITORY.enabled
    return result

def _collection_observer_manual_update_payload(payload: dict[str, Any]) -> dict[str, Any]:
    item_id = str((payload.get("item_id") or "")).strip()
    updates = payload.get("updates")
    if not item_id:
        return {"ok": False, "error": "item_id is required", "item_id": ""}
    if not isinstance(updates, dict) or not updates:
        return {"ok": False, "item_id": item_id, "error": "updates must be a non-empty object"}
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "manual_update_flat_item"):
        return {"ok": False, "item_id": item_id, "error": "database repository is not available", "db_mode": DB_REPOSITORY.enabled}
    result = DB_REPOSITORY.manual_update_flat_item(item_id, updates)
    result["db_mode"] = DB_REPOSITORY.enabled
    return result

def _collection_observer_reset_region_links_payload(payload: dict[str, Any]) -> dict[str, Any]:
    location_code = str((payload.get("location_code") or "")).strip()
    if not location_code:
        return {"ok": False, "error": "location_code is required", "location_code": ""}
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "reset_seed_link_region"):
        return {"ok": False, "location_code": location_code, "error": "database repository is not available", "db_mode": DB_REPOSITORY.enabled}
    result = DB_REPOSITORY.reset_seed_link_region(location_code)
    result["db_mode"] = DB_REPOSITORY.enabled
    return result

def _collection_runtime_state_label() -> str:
    try:
        status_payload = _collection_api_lightweight_status_payload()
        runtime_state = str(status_payload.get("runtime_state") or "").strip()
        if runtime_state:
            return runtime_state
    except Exception:
        pass
    if _collection_effectively_paused():
        return "暂停中"
    return "运行中"

def _collection_observer_runtime_control_payload(action: str) -> dict[str, Any]:
    global SOLVER_MANUAL_RESUME_EPOCH
    safe_action = str(action or "").strip().lower()
    if safe_action not in {"pause", "resume"}:
        return {"ok": False, "error": "action must be pause or resume", "action": safe_action}
    if safe_action == "pause":
        _set_collection_pause_state(True, "operator")
    else:
        _set_collection_pause_state(False)
        SOLVER_MANUAL_RESUME_EPOCH = time.time()
        _clear_solver_running_state()
        _clear_solver_manual_required_state()
        flag_path = _solver_force_unlock_flag_path()
        if os.path.exists(flag_path):
            try:
                os.remove(flag_path)
            except Exception as error:
                return {
                    "ok": False,
                    "error": f"failed to clear force unlock flag: {error}",
                    "action": safe_action,
                    "paused": _collection_effectively_paused(),
                    "captcha_solver": _captcha_solver_runtime_status(),
                }
        challenge_state_error = _clear_solver_challenge_state()
        if challenge_state_error:
            return {
                "ok": False,
                "error": f"failed to clear persisted challenge state: {challenge_state_error}",
                "action": safe_action,
                "paused": _collection_effectively_paused(),
                "captcha_solver": _captcha_solver_runtime_status(),
            }
    return {
        "ok": True,
        "action": safe_action,
        "paused": _collection_effectively_paused(),
        "runtime_state": _collection_runtime_state_label(),
        "captcha_solver": _captcha_solver_runtime_status(),
    }

def _normalize_auth_completion_id(value: Any) -> str | None:
    completion_id = str(value or "").strip()
    return completion_id[:160] if completion_id else None

def _auth_completion_confirmation_path() -> Path:
    state_dir = str(os.getenv("FAPAI_SOLVER_STATE_DIR") or DATA_DIR).strip() or DATA_DIR
    return Path(state_dir) / "auth-completion-confirmations.json"

def _read_auth_completion_confirmations() -> dict[str, float]:
    path = _auth_completion_confirmation_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    raw_confirmations = payload.get("confirmations") if isinstance(payload, dict) else None
    if not isinstance(raw_confirmations, dict):
        return {}
    confirmations: dict[str, float] = {}
    for raw_id, raw_epoch in raw_confirmations.items():
        completion_id = _normalize_auth_completion_id(raw_id)
        if not completion_id:
            continue
        try:
            confirmations[completion_id] = float(raw_epoch)
        except (TypeError, ValueError):
            continue
    return confirmations

def _auth_completion_was_confirmed(completion_id: str | None) -> bool:
    if not completion_id:
        return False
    with AUTH_COMPLETION_LOCK:
        AUTH_COMPLETION_CONFIRMATIONS.update(_read_auth_completion_confirmations())
        return completion_id in AUTH_COMPLETION_CONFIRMATIONS

def _remember_auth_completion_confirmation(completion_id: str | None) -> str | None:
    if not completion_id:
        return None
    with AUTH_COMPLETION_LOCK:
        confirmations = _read_auth_completion_confirmations()
        confirmations.update(AUTH_COMPLETION_CONFIRMATIONS)
        confirmations[completion_id] = time.time()
        if len(confirmations) > 256:
            confirmations = dict(sorted(confirmations.items(), key=lambda item: item[1])[-192:])
        path = _auth_completion_confirmation_path()
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps({"confirmations": confirmations}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except Exception as error:
            try:
                temporary.unlink(missing_ok=True)
            except Exception:
                pass
            return repr(error)
        AUTH_COMPLETION_CONFIRMATIONS.clear()
        AUTH_COMPLETION_CONFIRMATIONS.update(confirmations)
    return None

def _auth_state_is_confirmed(
    solver_status: dict[str, Any], scope: str | None = None
) -> bool:
    normalized_scope = _normalize_challenge_scope(scope)
    if normalized_scope:
        scoped = _solver_scope_runtime_status(normalized_scope)
        return bool(
            not scoped.get("paused")
            and not scoped.get("manual_required")
            and not scoped.get("force_reset_required")
        )
    return bool(
        not solver_status.get("paused")
        and not solver_status.get("running")
        and not solver_status.get("manual_required")
        and not solver_status.get("force_unlock_flag_exists")
    )

def _finalize_auth_completion_after_cookie_snapshot(
    completion_id: str | None,
    *,
    expected_challenge_id: str | None,
    completion_request: dict[str, Any] | None,
) -> dict[str, Any]:
    """Clear a manual pause only after a healthy cookie snapshot is durable."""

    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON
    normalized_expected = str(expected_challenge_id or "").strip() or None
    completion_scope = _challenge_scope_for_request(completion_request)
    if completion_scope not in CHALLENGE_SCOPES:
        completion_scope = _scope_for_challenge_id(normalized_expected)
    if (
        completion_scope in CHALLENGE_SCOPES
        and not _solver_scope_runtime_status(completion_scope).get("challenge_id")
        and normalized_expected == str(SOLVER_CHALLENGE_ID or "").strip()
    ):
        completion_scope = None
    with AUTH_COMPLETION_FINALIZE_LOCK:
        normalized_current = (
            str(_solver_scope_runtime_status(completion_scope).get("challenge_id") or "").strip() or None
            if completion_scope in CHALLENGE_SCOPES
            else str(SOLVER_CHALLENGE_ID or "").strip() or None
        )
        if normalized_current != normalized_expected:
            return {
                "auth_state_confirmed": False,
                "stale_challenge": True,
                "expected_challenge_id": normalized_expected,
                "challenge_id": normalized_current,
                "error": "cookie snapshot belongs to an older captcha challenge",
            }

        previously_confirmed = _auth_completion_was_confirmed(completion_id)
        before_status = _captcha_solver_runtime_status()
        if previously_confirmed and _auth_state_is_confirmed(before_status, completion_scope):
            return {
                "auth_state_confirmed": True,
                "idempotent": True,
                "challenge_id": normalized_current,
            }

        clear_error = _clear_solver_manual_required_pause_compat(completion_scope or None)
        cleared_status = _captcha_solver_runtime_status()
        auth_state_confirmed = clear_error is None and _auth_state_is_confirmed(cleared_status, completion_scope)
        receipt_error: str | None = None
        if auth_state_confirmed:
            receipt_error = _remember_auth_completion_confirmation(completion_id)
            auth_state_confirmed = receipt_error is None

        if auth_state_confirmed:
            SOLVER_LAST_STATUS = "manual_auth_completed"
            SOLVER_LAST_FAILURE_REASON = None
            _remember_solver_auth_completion(completion_request)
        else:
            recovery_error: str | None = None
            if clear_error is None:
                if isinstance(completion_request, dict) and completion_request:
                    _refresh_solver_last_request(completion_request)
                _begin_solver_challenge(completion_request)
                recovery_error = _mark_solver_manual_required(
                    manual_only=_solver_target_requires_manual_only(completion_request),
                    scope=completion_scope or None,
                )
            SOLVER_LAST_STATUS = "manual_required"
            SOLVER_LAST_FAILURE_REASON = "manual_required"
            _set_collection_pause_state(True, "manual_required")

        result: dict[str, Any] = {
            "auth_state_confirmed": auth_state_confirmed,
            "idempotent": bool(previously_confirmed and auth_state_confirmed),
            "challenge_id": SOLVER_CHALLENGE_ID,
        }
        if clear_error is not None:
            result["error"] = f"failed to clear force unlock flag: {clear_error}"
        elif receipt_error is not None:
            result["error"] = f"failed to persist auth completion receipt: {receipt_error}"
        elif not auth_state_confirmed:
            result["error"] = "auth state remained paused or manual_required after cleanup"
        if not auth_state_confirmed and recovery_error is not None:
            result["recovery_error"] = recovery_error
        return result

def _node_auth_challenge_matches(payload: dict[str, Any], source: str) -> bool:
    challenge_id = str(payload.get("challenge_id") or "").strip()
    scope = _normalize_challenge_scope(payload.get("scope")) or _scope_for_challenge_id(challenge_id)
    active_id = (
        str(_solver_scope_runtime_status(scope).get("challenge_id") or "").strip()
        if scope in CHALLENGE_SCOPES
        else str(SOLVER_CHALLENGE_ID or "").strip()
    )
    if source != "pc2_local_solver" or not active_id:
        return True
    return bool(challenge_id and challenge_id == active_id)

def _collection_observer_resume_after_cooldown_payload(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resume collection after a node-local cooldown without claiming a solve.

    The request id is recorded in the same durable receipt store as auth
    completions so a NAS timeout or PC2 restart can safely replay the request.
    """
    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON
    payload = payload if isinstance(payload, dict) else {}
    request_id = _normalize_auth_completion_id(payload.get("resume_request_id"))
    source = str(payload.get("source") or "pc2_local_solver")
    resume_scope = _normalize_challenge_scope(payload.get("scope")) or _scope_for_challenge_id(payload.get("challenge_id"))
    if resume_scope not in CHALLENGE_SCOPES:
        reported_resume_id = str(payload.get("challenge_id") or "").strip()
        if reported_resume_id and reported_resume_id == str(SOLVER_CHALLENGE_ID or "").strip():
            resume_scope = None
        else:
            resume_scope = _challenge_scope_for_request(SOLVER_LAST_REQUEST)
    if not request_id:
        return {
            "ok": False,
            "action": "resume_after_cooldown",
            "source": source,
            "resume_request_id": None,
            "auth_state_confirmed": False,
            "paused": bool(_collection_effectively_paused()),
            "captcha_solver": _captcha_solver_runtime_status(),
            "error": "resume_request_id is required",
        }
    if not _node_auth_challenge_matches(payload, source):
        solver_status = _captcha_solver_runtime_status()
        return {
            "ok": False,
            "action": "resume_after_cooldown",
            "source": source,
            "resume_request_id": request_id,
            "auth_state_confirmed": False,
            "stale_challenge": True,
            "challenge_id": SOLVER_CHALLENGE_ID,
            "paused": bool(solver_status.get("paused")),
            "captcha_solver": solver_status,
            "error": "resume request belongs to an older captcha challenge",
        }

    receipt_id = f"resume-after-cooldown:{request_id}"
    previously_confirmed = _auth_completion_was_confirmed(receipt_id)
    before_status = _captcha_solver_runtime_status()
    already_clear = _auth_state_is_confirmed(before_status, resume_scope)
    clear_error: str | None = None
    receipt_error: str | None = None
    if previously_confirmed:
        auth_state_confirmed = already_clear
    else:
        clear_error = _clear_solver_manual_required_pause_compat(resume_scope or None)
        cleared_status = _captcha_solver_runtime_status()
        auth_state_confirmed = clear_error is None and _auth_state_is_confirmed(cleared_status, resume_scope)
        if auth_state_confirmed:
            receipt_error = _remember_auth_completion_confirmation(receipt_id)
            auth_state_confirmed = receipt_error is None

    if auth_state_confirmed:
        SOLVER_LAST_STATUS = "resumed_after_cooldown"
        SOLVER_LAST_FAILURE_REASON = None
        # The scoped clear can remove last_request before the grace baseline is
        # recorded. Keep the reporting node/CDP carried by the resume receipt,
        # then fill any missing target metadata from the retained server state.
        resume_request = _build_solver_request(payload)
        retained_request = SOLVER_LAST_REQUEST
        if resume_scope in CHALLENGE_SCOPES:
            scoped_request = _solver_scope_runtime_status(resume_scope).get("last_request")
            if isinstance(scoped_request, dict) and scoped_request:
                retained_request = scoped_request
        for key, value in _build_solver_request(retained_request).items():
            resume_request.setdefault(key, value)
        _remember_solver_auth_completion(resume_request)
    else:
        SOLVER_LAST_STATUS = "manual_required"
        SOLVER_LAST_FAILURE_REASON = "manual_required"
        _set_collection_pause_state(True, "manual_required", scope=resume_scope or None)
    solver_status = _captcha_solver_runtime_status()
    scoped_result_status = (
        _solver_scope_runtime_status(resume_scope)
        if resume_scope in CHALLENGE_SCOPES
        else solver_status
    )
    result: dict[str, Any] = {
        "ok": auth_state_confirmed,
        "action": "resume_after_cooldown",
        "source": source,
        "resume_request_id": request_id,
        "auth_state_confirmed": auth_state_confirmed,
        "idempotent": bool(previously_confirmed or (already_clear and auth_state_confirmed)),
        "manual_auth_completed": False,
        "paused": bool(solver_status.get("paused")),
        "scope": resume_scope or None,
        "scope_paused": bool(scoped_result_status.get("paused")),
        "scope_manual_required": bool(scoped_result_status.get("manual_required")),
        "scope_force_reset_required": bool(scoped_result_status.get("force_reset_required")),
        "scope_force_unlock_flag_exists": bool(
            resume_scope in CHALLENGE_SCOPES
            and os.path.exists(_solver_scope_manual_flag_path(resume_scope))
        ),
        "runtime_state": _collection_runtime_state_label(),
        "captcha_solver": solver_status,
        "cookie_snapshot": {"status": "skipped", "reason": "resume_after_cooldown"},
    }
    if clear_error is not None:
        result["error"] = f"failed to clear force unlock flag: {clear_error}"
    elif receipt_error is not None:
        result["error"] = f"failed to persist resume receipt: {receipt_error}"
    elif previously_confirmed and not auth_state_confirmed:
        result["error"] = "confirmed resume_request_id is stale for the current auth state"
    elif not auth_state_confirmed:
        result["error"] = "auth state remained paused or manual_required after cleanup"
    return result

__all__ = ["_collection_observer_items_payload", "_collection_observer_regions_payload", "_collection_observer_item_payload", "_collection_observer_reanalysis_payload", "_collection_observer_manual_update_payload", "_collection_observer_reset_region_links_payload", "_collection_runtime_state_label", "_collection_observer_runtime_control_payload", "_normalize_auth_completion_id", "_auth_completion_confirmation_path", "_read_auth_completion_confirmations", "_auth_completion_was_confirmed", "_remember_auth_completion_confirmation", "_auth_state_is_confirmed", "_finalize_auth_completion_after_cookie_snapshot", "_node_auth_challenge_matches", "_collection_observer_resume_after_cooldown_payload"]
