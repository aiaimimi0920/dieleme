from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _trigger_manual_solver_retry_if_due(
    *,
    now: float | None = None,
    submit_solver: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    if not RUNTIME.retry_lock.acquire(blocking=False):
        return {"queued": False, "reason": "retry_pending"}
    try:
        return _run_manual_solver_retry_if_due(now=now, submit_solver=submit_solver)
    finally:
        RUNTIME.retry_lock.release()

def _run_manual_solver_retry_if_due(
    *,
    now: float | None = None,
    submit_solver: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    current_time = time.time() if now is None else now
    with RUNTIME.lock:
        recovery_before = RUNTIME.recovery.snapshot()
        control_before = RUNTIME.control.snapshot()
        execution_before = RUNTIME.solver.snapshot()
    if control_before.reason == "operator":
        return {"queued": False, "reason": "operator_paused"}
    if not _manual_solver_retry_enabled():
        return {"queued": False, "reason": "disabled"}
    if _solver_submission_pending():
        return {"queued": False, "reason": "solver_pending"}
    execution = RUNTIME.solver.snapshot()
    if execution.running:
        elapsed_seconds = max(int(current_time - execution.started_at), 0) if execution.started_at else 0
        max_runtime_seconds = _solver_max_runtime_seconds()
        if elapsed_seconds >= max_runtime_seconds:
            flag_error = _mark_solver_manual_required(
                scope=_challenge_scope_for_request(RUNTIME.recovery.snapshot().last_request) or None
            )
            result: dict[str, Any] = {
                "queued": False,
                "reason": "running_solver_timed_out",
                "elapsed_seconds": elapsed_seconds,
                "max_runtime_seconds": max_runtime_seconds,
            }
            if flag_error:
                result["flag_error"] = flag_error
            return result
        return {
            "queued": False,
            "reason": "solver_running",
            "elapsed_seconds": elapsed_seconds,
            "max_runtime_seconds": max_runtime_seconds,
        }

    solver_status = _captcha_solver_runtime_status(now=current_time)
    if not solver_status.get("manual_required"):
        return {"queued": False, "reason": "not_manual_required"}

    solver_request = _manual_solver_retry_request()
    if not solver_request.get("target_url"):
        return {"queued": False, "reason": "missing_target_url"}
    solver_scope = _challenge_scope_for_request(solver_request)

    # PC2 owns its browser and runs the persistent 20s/10-attempt state
    # machine. The NAS monitor must not clear its manual pause or submit a
    # competing central solver request.
    if _solver_request_delegated_to_node(solver_request):
        return {
            "queued": False,
            "reason": "delegated_to_node_solver",
            "solver_request": solver_request,
        }

    next_retry_epoch = _manual_solver_retry_next_epoch(current_time)
    if next_retry_epoch is not None and current_time < next_retry_epoch:
        return {
            "queued": False,
            "reason": "cooldown_active",
            "next_retry_epoch": next_retry_epoch,
        }

    # CDP 掉线时直接跳过本轮：保留 manual_required，不清 pause、不投 solver。
    # 只吃掉一个 cooldown，这样探测按 retry interval 走而不是每轮轮询都打一次。
    retry_cdp_endpoint = str(solver_request.get("cdp_endpoint") or "").strip().rstrip("/")
    healthy = _probe_solver_cdp_endpoint(retry_cdp_endpoint)
    with RUNTIME.lock:
        if (
            RUNTIME.recovery.snapshot() != recovery_before
            or RUNTIME.control.snapshot() != control_before
            or RUNTIME.solver.snapshot() != execution_before
        ):
            return {"queued": False, "reason": "state_changed"}
        if not healthy:
            RUNTIME.recovery.record_retry(current_time, attempted=False)
            return {
                "queued": False,
                "reason": "cdp_endpoint_unhealthy",
                "cdp_endpoint": retry_cdp_endpoint,
            }
        return _queue_manual_solver_retry(solver_request, solver_scope, current_time, submit_solver)

def _queue_manual_solver_retry(solver_request, solver_scope, current_time, submit_solver):
    clear_error = _clear_solver_manual_required_pause(scope=solver_scope or None)
    if clear_error:
        return {"queued": False, "reason": "clear_manual_required_failed", "error": clear_error}
    if (
        solver_scope in CHALLENGE_SCOPES
        and RUNTIME.control.snapshot().reason in {"captcha_solver", "manual_required"}
        and not any(
            _solver_scope_runtime_status(other).get("paused")
            for other in CHALLENGE_SCOPES
            if other != solver_scope
        )
    ):
        # A retry is a transient hand-off: the worker will establish its own
        # scoped pause when it observes the next challenge.
        _set_collection_pause_state(False)

    with RUNTIME.lock:
        RUNTIME.recovery.record_retry(current_time, attempted=True)
        RUNTIME.solver.record_outcome("manual_retry_queued")

    try:
        submit_result = (submit_solver or _submit_solver_request)(solver_request)
    except Exception as error:
        _mark_solver_manual_required(scope=solver_scope or None)
        return {
            "queued": False,
            "reason": "submit_failed",
            "error": repr(error),
        }
    if submit_solver is None and submit_result is False:
        _mark_solver_manual_required(scope=solver_scope or None)
        return {
            "queued": False,
            "reason": "solver_active",
        }

    return {
        "queued": True,
        "reason": "manual_required_retry_due",
        "attempt": RUNTIME.recovery.snapshot().retry_attempts,
        "solver_request": solver_request,
    }

def _payload_flag(payload: dict[str, Any], key: str, default: bool) -> bool:
    if key not in payload:
        return default
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return default
    return text not in {"0", "false", "no", "off"}

def _payload_force_solver_retry(payload: dict[str, Any]) -> bool:
    return any(
        _payload_flag(payload, key, False)
        for key in ("force_retry", "force_manual_retry", "operator_retry")
    )

def _payload_manual_only(payload: dict[str, Any]) -> bool:
    return _payload_flag(payload, "manual_only", False)

def _manual_only_captcha_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    solver_request = _build_solver_request(payload)
    if solver_request:
        _refresh_solver_last_request(solver_request)
    scope = _challenge_scope_for_request(solver_request)
    _begin_solver_challenge(solver_request)
    flag_error = _mark_solver_manual_required(manual_only=True, scope=scope or None)
    response_payload: dict[str, Any] = {
        "status": "manual_required",
        "captcha_solver": _captcha_solver_runtime_status(),
    }
    if flag_error:
        response_payload["flag_error"] = flag_error
    return response_payload

def _node_solver_blocked_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    solver_request = _build_solver_request(payload)
    if solver_request:
        _refresh_solver_last_request(solver_request)
    scope = _challenge_scope_for_request(solver_request)
    if scope not in CHALLENGE_SCOPES:
        return {
            "status": "invalid_scope",
            "captcha_solver": _captcha_solver_runtime_status(),
        }

    _begin_solver_challenge(solver_request)
    state = _read_solver_scope_state(scope)
    blocked_at = float(state.get("node_solver_blocked_at_epoch") or 0)
    if blocked_at <= 0:
        blocked_at = time.time()
    reason = str(payload.get("node_solver_blocked_reason") or "").strip()
    if reason != "repeated_solver_failures":
        reason = "repeated_solver_failures"
    try:
        attempts = max(int(payload.get("node_solver_blocked_attempts") or 0), 0)
    except (TypeError, ValueError):
        attempts = 0
    state.update(
        {
            "paused": True,
            "pause_reason": "manual_required",
            "manual_required": True,
            "manual_only": True,
            "last_status": "manual_required",
            "last_failure_reason": reason,
            "node_solver_blocked": True,
            "node_solver_blocked_at_epoch": blocked_at,
            "node_solver_blocked_reason": reason,
            "node_solver_blocked_attempts": max(
                attempts,
                int(state.get("node_solver_blocked_attempts") or 0),
            ),
        }
    )
    persist_error = _persist_solver_scope_state(scope, state)
    _set_collection_pause_state(True, "manual_required", scope=scope)
    response: dict[str, Any] = {
        "status": "node_solver_blocked",
        "scope": scope,
        "captcha_solver": _captcha_solver_runtime_status(),
    }
    if persist_error:
        response["state_error"] = persist_error
    return response

def _auth_cookie_snapshot_sample_urls(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("sample_urls")
    if isinstance(raw, list):
        urls = [str(value).strip() for value in raw if str(value or "").strip()]
        if urls:
            return urls

    env_raw = os.getenv("FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS")
    if env_raw:
        urls = [part.strip() for part in re.split(r"[;,]", env_raw) if part.strip()]
        if urls:
            return urls

    return [
        "https://sf.taobao.com/list/50025969__2.htm",
        "https://sf.taobao.com/list/200782003__1.htm",
    ]

def _normalize_auth_cookie_snapshot_node_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]+", text):
        return ""
    return text

def _auth_cookie_snapshot_root_candidates() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def _add(path_value: str | Path | None) -> None:
        if not path_value:
            return
        path = Path(path_value).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        candidates.append(resolved)

    _add(os.getenv("FAPAI_COOKIE_SNAPSHOT_ROOT"))
    _add(os.getenv("FAPAI_SHARED_DATA_ROOT_HOST"))
    _add(REPO_ROOT / "FPFData")

    data_root = Path(DATA_DIR).expanduser()
    try:
        data_root = data_root.resolve()
    except OSError:
        pass
    if data_root.name.lower() == "datas":
        _add(data_root.parent)
    return candidates

def _resolve_auth_cookie_snapshot_path(payload: dict[str, Any]) -> str:
    explicit_path = str(payload.get("cookie_snapshot_path") or "").strip()
    env_path = str(os.getenv("FAPAI_COOKIE_SNAPSHOT") or "").strip()
    if env_path:
        configured = Path(env_path).expanduser().resolve()
        if explicit_path and Path(explicit_path).expanduser().resolve() != configured:
            return ""
        return str(configured)

    node_id = _normalize_auth_cookie_snapshot_node_id(
        payload.get("node_id")
        or os.getenv("FAPAI_NODE_ID")
    )
    if not node_id:
        return ""

    roots = _auth_cookie_snapshot_root_candidates()
    if not roots:
        return ""

    existing_roots = [root for root in roots if root.exists()]
    selected_root = existing_roots[0] if existing_roots else roots[0]
    node_root = (selected_root / "secrets" / "nodes" / node_id).resolve()
    candidate = Path(explicit_path).expanduser().resolve() if explicit_path else node_root / "taobao-cookies.json"
    try:
        node_root.relative_to(selected_root.resolve())
        candidate.relative_to(node_root)
    except ValueError:
        return ""
    return str(candidate)

def _export_auth_cdp_cookies(cdp_endpoint: str) -> list[dict[str, Any]]:
    from tools.browserless_seed_probe import export_cdp_cookies

    return export_cdp_cookies(cdp_endpoint)

def _summarize_auth_cookies(cookies: list[dict[str, Any]]) -> dict[str, Any]:
    from tools.browserless_seed_probe import summarize_cookie_snapshot

    return summarize_cookie_snapshot(cookies)

def _write_auth_cookie_snapshot(cookies: list[dict[str, Any]], snapshot_path: str) -> None:
    from tools.browserless_seed_probe import write_cookie_snapshot

    write_cookie_snapshot(cookies, snapshot_path)

def _probe_auth_cookie_snapshot_health(
    cookies: list[dict[str, Any]],
    sample_urls: list[str],
    *,
    cdp_endpoint: str = "",
) -> dict[str, Any]:
    from tools import browserless_seed_probe, taobao_login_health

    session = browserless_seed_probe.build_session_from_playwright_cookies(cookies)
    user_agent = browserless_seed_probe.resolve_cdp_user_agent(cdp_endpoint)
    sample_results: list[dict[str, Any]] = []
    healthy_samples = 0
    for url in sample_urls:
        try:
            summary = browserless_seed_probe.probe_seed_page(
                url,
                cookies=cookies,
                session=session,
                timeout=15,
                user_agent=user_agent,
            )
            classification = taobao_login_health.classify_taobao_health(
                "",
                final_url=str(summary.get("final_url") or url),
                list_summary=summary,
                payload_present=summary.get("has_script") is True,
            )
            result = {
                "check_url": url,
                "status": classification.get("status"),
                "healthy": bool(classification.get("healthy")),
                "final_url": classification.get("final_url"),
                "http_status": summary.get("status"),
                "has_script": summary.get("has_script"),
                "item_count": summary.get("item_count"),
                "body_has_login": summary.get("body_has_login"),
                "body_has_captcha": summary.get("body_has_captcha"),
                "body_has_punish": summary.get("body_has_punish"),
                "body_has_challenge": summary.get("body_has_challenge"),
            }
        except Exception as error:
            result = {
                "check_url": url,
                "status": "probe_error",
                "healthy": False,
                "error": repr(error),
            }
        if result.get("healthy") is True:
            healthy_samples += 1
        sample_results.append(result)

    return {
        "healthy": healthy_samples > 0,
        "healthy_samples": healthy_samples,
        "sample_count": len(sample_results),
        "sample_results": sample_results,
    }

def _refresh_auth_cookie_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    if not _payload_flag(payload, "refresh_cookie_snapshot", True):
        return {"refreshed": False, "reason": "disabled_by_request"}

    snapshot_path = _resolve_auth_cookie_snapshot_path(payload)
    if not snapshot_path:
        return {"refreshed": False, "reason": "cookie_snapshot_path_not_configured"}

    request_cdp_endpoint = payload.get("cdp_endpoint")
    if not request_cdp_endpoint and isinstance(RUNTIME.recovery.snapshot().last_request, dict):
        request_cdp_endpoint = RUNTIME.recovery.snapshot().last_request.get("cdp_endpoint")
    cdp_endpoint = _normalize_solver_cdp_endpoint(request_cdp_endpoint or os.getenv("FAPAI_CDP_ENDPOINT") or "")
    if not cdp_endpoint:
        return {"refreshed": False, "reason": "cdp_endpoint_not_configured", "path": snapshot_path}
    if not _cdp_endpoint_permitted(cdp_endpoint):
        return {"refreshed": False, "reason": "cdp_endpoint_not_permitted"}

    cookies = _export_auth_cdp_cookies(cdp_endpoint)
    summary = _summarize_auth_cookies(cookies)
    sample_urls = _auth_cookie_snapshot_sample_urls(payload)
    health = _probe_auth_cookie_snapshot_health(
        cookies,
        sample_urls,
        cdp_endpoint=cdp_endpoint,
    )
    cookie_count = int(summary.get("count") or 0)
    if not health.get("healthy"):
        return {
            "refreshed": False,
            "reason": "cookie_snapshot_candidate_unhealthy",
            "path": snapshot_path,
            "cdp_endpoint": cdp_endpoint,
            "cookie_count": cookie_count,
            "health": health,
        }

    _write_auth_cookie_snapshot(cookies, snapshot_path)
    return {
        "refreshed": True,
        "path": snapshot_path,
        "cdp_endpoint": cdp_endpoint,
        "cookie_count": cookie_count,
        "domains": summary.get("domains") or [],
        "shape_fingerprint": summary.get("shape_fingerprint"),
        "value_fingerprint": summary.get("value_fingerprint"),
        "health": health,
    }

def _auth_cookie_snapshot_retry_attempts() -> int:
    raw = os.getenv("FAPAI_AUTH_COOKIE_RETRY_ATTEMPTS", "3")
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 3
    return max(1, min(value, 10))

def _auth_cookie_snapshot_retry_backoff_seconds() -> float:
    raw = os.getenv("FAPAI_AUTH_COOKIE_RETRY_BACKOFF_SECONDS", "2")
    try:
        value = float(str(raw or "").strip())
    except ValueError:
        value = 2.0
    return max(0.0, min(value, 300.0))

def _auth_cookie_snapshot_runtime_status() -> dict[str, Any]:
    return _auth_cookie_snapshot_runtime_state().snapshot()

def _set_auth_cookie_snapshot_state(**updates: Any) -> dict[str, Any]:
    return _auth_cookie_snapshot_runtime_state().update(updates)


def _auth_cookie_snapshot_runtime_state():
    return RUNTIME.cookie_snapshot

__all__ = ["_trigger_manual_solver_retry_if_due", "_run_manual_solver_retry_if_due", "_queue_manual_solver_retry", "_payload_flag", "_payload_force_solver_retry", "_payload_manual_only", "_manual_only_captcha_report_payload", "_node_solver_blocked_report_payload", "_auth_cookie_snapshot_sample_urls", "_normalize_auth_cookie_snapshot_node_id", "_auth_cookie_snapshot_root_candidates", "_resolve_auth_cookie_snapshot_path", "_export_auth_cdp_cookies", "_summarize_auth_cookies", "_write_auth_cookie_snapshot", "_probe_auth_cookie_snapshot_health", "_refresh_auth_cookie_snapshot", "_auth_cookie_snapshot_retry_attempts", "_auth_cookie_snapshot_retry_backoff_seconds", "_auth_cookie_snapshot_runtime_status", "_set_auth_cookie_snapshot_state", "_auth_cookie_snapshot_runtime_state"]
