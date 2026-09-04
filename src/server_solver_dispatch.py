from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _write_solver_manual_required_flag(
    created_at_epoch: float, *, scope: str | None = None
) -> str | None:
    normalized_scope = _normalize_challenge_scope(scope)
    flag_path = (
        _solver_scope_manual_flag_path(normalized_scope)
        if normalized_scope
        else _solver_force_unlock_flag_path()
    )
    try:
        os.makedirs(os.path.dirname(flag_path) or ".", exist_ok=True)
        with open(flag_path, "w", encoding="utf-8") as flag_file:
            json.dump(
                {
                    "manual_required": True,
                    "manual_only": bool(SOLVER_MANUAL_ONLY),
                    "scope": _normalize_challenge_scope(scope) or None,
                    "created_at_epoch": created_at_epoch,
                    "last_request": dict(SOLVER_LAST_REQUEST) if isinstance(SOLVER_LAST_REQUEST, dict) else {},
                    "message": "Delete this file to force resume the queue after manual solving",
                },
                flag_file,
                ensure_ascii=False,
            )
    except Exception as error:
        return repr(error)
    return None

def _solver_manual_flag_scope() -> str | None:
    try:
        with open(_solver_force_unlock_flag_path(), "r", encoding="utf-8") as flag_file:
            payload = json.load(flag_file)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return _normalize_challenge_scope(payload.get("scope")) or None

def _solver_manual_flag_is_manual_only() -> bool:
    try:
        with open(_solver_force_unlock_flag_path(), "r", encoding="utf-8") as flag_file:
            payload = json.load(flag_file)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    value = payload.get("manual_only")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

def _manual_solver_retry_enabled(scope: str | None = None) -> bool:
    normalized_scope = _normalize_challenge_scope(scope)
    if normalized_scope not in CHALLENGE_SCOPES:
        inferred_scope = _challenge_scope_for_request(SOLVER_LAST_REQUEST)
        if inferred_scope in CHALLENGE_SCOPES:
            normalized_scope = inferred_scope
    if normalized_scope in CHALLENGE_SCOPES:
        scoped = _solver_scope_runtime_status(normalized_scope)
        if scoped.get("manual_only"):
            return False
        flag_scope = _solver_manual_flag_scope()
        if flag_scope and flag_scope != normalized_scope:
            return True
        if scoped.get("challenge_id") or scoped.get("manual_required"):
            # The global manual-only bit is retained for legacy clients, but
            # must not disable retry for this independent scope.
            return _runtime_env_flag("FAPAI_SOLVER_MANUAL_RETRY_ENABLED", True)
    if SOLVER_MANUAL_ONLY or _solver_manual_flag_is_manual_only():
        return False
    return _runtime_env_flag("FAPAI_SOLVER_MANUAL_RETRY_ENABLED", True)

def _manual_solver_retry_interval_seconds() -> int:
    raw = os.getenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "180")
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 180
    if value < 0:
        return 180
    return value

def _solver_max_runtime_seconds() -> int:
    raw = os.getenv("FAPAI_SOLVER_MAX_RUNTIME_SECONDS", "180")
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 180
    if value <= 0:
        return 180
    return value

def _solver_worker_quiesce_seconds() -> int:
    raw = os.getenv("FAPAI_SOLVER_WORKER_QUIESCE_SECONDS", "0")
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 0
    return max(0, min(value, 300))

def _solver_cdp_ready_timeout_seconds() -> int:
    raw = os.getenv("FAPAI_SOLVER_CDP_READY_TIMEOUT_SECONDS", "0")
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 0
    return max(0, min(value, 600))

def _wait_for_solver_cdp_ready(solver_request: dict[str, Any] | None) -> bool:
    timeout_seconds = _solver_cdp_ready_timeout_seconds()
    request_payload = solver_request if isinstance(solver_request, dict) else {}
    cdp_endpoint = str(request_payload.get("cdp_endpoint") or "").strip().rstrip("/")
    if timeout_seconds <= 0 or not cdp_endpoint:
        return True

    print(
        f"[SOLVER] Waiting up to {timeout_seconds}s for a stable CDP target list at "
        f"{cdp_endpoint}."
    )
    deadline = time.monotonic() + timeout_seconds
    consecutive_healthy_probes = 0
    while time.monotonic() < deadline:
        try:
            request = Request(f"{cdp_endpoint}/json/list", headers={"Accept": "application/json"})
            with urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            healthy = isinstance(payload, list)
        except Exception:
            healthy = False

        if healthy:
            consecutive_healthy_probes += 1
            if consecutive_healthy_probes >= 2:
                print("[SOLVER] CDP target list is stable; starting solver control.")
                return True
        else:
            consecutive_healthy_probes = 0
        time.sleep(2)

    print(f"[SOLVER] CDP did not become stable within {timeout_seconds}s.")
    return False

def _solver_cdp_probe_timeout_seconds() -> float:
    raw = os.getenv("FAPAI_SOLVER_CDP_PROBE_TIMEOUT_SECONDS", "3")
    try:
        value = float(str(raw or "").strip())
    except ValueError:
        value = 3.0
    return max(0.5, min(value, 30.0))

def _probe_solver_cdp_endpoint(cdp_endpoint: str) -> bool:
    """轻量探测 CDP 是否可达；没有 endpoint 时视为通过。

    manual retry 会先走这里，避免浏览器已经掉线时还不停地清 pause、重投
    solver，最后把 manual_retry_attempts 刷到几千次。
    """
    endpoint = str(cdp_endpoint or "").strip().rstrip("/")
    if not endpoint:
        return True
    try:
        request = Request(f"{endpoint}/json/version", headers={"Accept": "application/json"})
        with urlopen(request, timeout=_solver_cdp_probe_timeout_seconds()) as response:
            json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    return True

def _manual_solver_retry_poll_seconds() -> int:
    raw = os.getenv("FAPAI_SOLVER_MANUAL_RETRY_POLL_SECONDS", "30")
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 30
    return max(value, 1)

def _captcha_solver_background_url(url: str) -> str:
    target_url = str(url or "").strip()
    if not target_url:
        return ""
    if "__captcha_solver_bg=1" in target_url:
        return target_url
    separator = "&" if "?" in target_url else "?"
    return f"{target_url}{separator}__captcha_solver_bg=1"

def _solver_manual_flag_request() -> dict[str, Any]:
    flag_path = _solver_force_unlock_flag_path()
    try:
        with open(flag_path, "r", encoding="utf-8") as flag_file:
            payload = json.load(flag_file)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    last_request = payload.get("last_request")
    return dict(last_request) if isinstance(last_request, dict) else {}

def _default_manual_solver_retry_request() -> dict[str, Any]:
    default_url = _captcha_solver_background_url(_auth_cookie_snapshot_sample_urls({})[0])
    return {"target_url": default_url} if default_url else {}

def _prefer_seed_manual_solver_retry_request() -> bool:
    try:
        status_payload = _collection_api_lightweight_status_payload()
    except Exception:
        return False
    return _solver_last_request_scope() == "detail" and _seed_stage_has_remaining_work(status_payload)

def _seed_priority_manual_solver_retry_request(
    current_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = dict(current_request or {})
    default_request = _build_solver_request(_default_manual_solver_retry_request())
    if default_request.get("target_url"):
        request["target_url"] = default_request["target_url"]
    return request

def _prefer_seed_solver_request_for_payload(
    request_payload: dict[str, Any] | None = None,
    *,
    status_payload: dict[str, Any] | None = None,
) -> bool:
    if _solver_request_scope(request_payload) != "detail":
        return False
    if status_payload is None:
        try:
            status_payload = _collection_api_lightweight_status_payload()
        except Exception:
            return False
    if not isinstance(status_payload, dict):
        return False
    return _seed_stage_has_remaining_work(status_payload)

def _seed_priority_solver_request(
    request_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    solver_request = _build_solver_request(request_payload or {})
    if not solver_request.get("target_url"):
        return solver_request
    if _prefer_seed_solver_request_for_payload(solver_request):
        solver_request["challenge_target_url"] = solver_request["target_url"]
        return _seed_priority_manual_solver_retry_request(solver_request)
    return solver_request

def _manual_solver_retry_request() -> dict[str, Any]:
    solver_request = _build_solver_request(SOLVER_LAST_REQUEST if isinstance(SOLVER_LAST_REQUEST, dict) else {})
    if solver_request.get("target_url"):
        if _prefer_seed_manual_solver_retry_request():
            return _seed_priority_manual_solver_retry_request(solver_request)
        return solver_request
    solver_request = _build_solver_request(_solver_manual_flag_request())
    if solver_request.get("target_url"):
        return solver_request
    return _build_solver_request(_default_manual_solver_retry_request())

def _manual_solver_retry_next_epoch(now: float | None = None) -> float | None:
    retry_scope = _challenge_scope_for_request(SOLVER_LAST_REQUEST)
    if not _manual_solver_retry_enabled(retry_scope or None):
        return None
    interval = _manual_solver_retry_interval_seconds()
    current_time = time.time() if now is None else now
    base_epoch = max(
        float(SOLVER_MANUAL_REQUIRED_EPOCH or 0),
        float(SOLVER_MANUAL_RETRY_LAST_EPOCH or 0),
        float(SOLVER_LAST_FINISHED_TIME or 0),
    )
    if base_epoch <= 0:
        return current_time
    return base_epoch + interval

def _solver_submission_pending() -> bool:
    with SOLVER_LOCK:
        return SOLVER_PENDING_TOKEN is not None

def _reserve_solver_submission() -> object | None:
    global SOLVER_PENDING_TOKEN
    with SOLVER_LOCK:
        if SOLVER_RUNNING or SOLVER_PENDING_TOKEN is not None:
            return None
        token = object()
        SOLVER_PENDING_TOKEN = token
        return token

def _release_solver_submission(token: object | None) -> None:
    global SOLVER_PENDING_TOKEN
    if token is None:
        return
    with SOLVER_LOCK:
        if SOLVER_PENDING_TOKEN is token:
            SOLVER_PENDING_TOKEN = None

def _activate_solver_submission(
    solver_request: dict[str, Any] | None,
    token: object | None,
) -> tuple[bool, str, float]:
    global SOLVER_RUNNING, SOLVER_PENDING_TOKEN, SOLVER_START_TIME
    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON, SOLVER_LAST_REQUEST

    with SOLVER_LOCK:
        if token is not None:
            if SOLVER_PENDING_TOKEN is not token:
                return False, "stale_submission", 0.0
            SOLVER_PENDING_TOKEN = None
        elif SOLVER_PENDING_TOKEN is not None:
            return False, "submission_pending", 0.0

        if SOLVER_RUNNING:
            elapsed = max(time.time() - float(SOLVER_START_TIME or 0), 0.0)
            return False, "solver_running", elapsed

        started_at = time.time()
        SOLVER_RUNNING = True
        SOLVER_START_TIME = started_at
        SOLVER_LAST_STATUS = "running"
        SOLVER_LAST_FAILURE_REASON = None
        SOLVER_LAST_REQUEST = dict(solver_request) if isinstance(solver_request, dict) else {}
        return True, "started", started_at

def _solver_cdp_endpoint_is_remote(cdp_endpoint: str) -> bool:
    """Check if the CDP endpoint belongs to a remote node (not the local machine).

    Returns True when the endpoint hostname is not a loopback address, indicating
    the solver runs on a different host than the CDP browser. In that case the
    local solver cannot use OS-level mouse drag and must defer to the node's
    own solver process.
    """
    endpoint = str(cdp_endpoint or "").strip().rstrip("/")
    if not endpoint:
        return False
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return False
    hostname = str(parsed.hostname or "").lower()
    if not hostname:
        return False
    # Local loopback addresses are on the same machine.
    if hostname in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}:
        return False
    # host.docker.internal resolves to the Docker host — same machine when
    # the solver runs inside a container on the host.
    if hostname in {"host.docker.internal", "192.168.65.254"}:
        return False
    return True

def _solver_request_delegated_to_node(solver_request: dict[str, Any] | None) -> bool:
    request = solver_request if isinstance(solver_request, dict) else {}
    node_id = str(request.get("node_id") or "").strip().lower()
    if node_id == "pc2":
        return True
    return _solver_cdp_endpoint_is_remote(str(request.get("cdp_endpoint") or ""))

def _submit_solver_request(solver_request: dict[str, Any]) -> bool:
    token = _reserve_solver_submission()
    if token is None:
        return False

    handler = object.__new__(DataHandler)
    try:
        executor.submit(handler.run_solver, solver_request, token)
    except Exception:
        _release_solver_submission(token)
        raise
    return True

__all__ = ["_write_solver_manual_required_flag", "_solver_manual_flag_scope", "_solver_manual_flag_is_manual_only", "_manual_solver_retry_enabled", "_manual_solver_retry_interval_seconds", "_solver_max_runtime_seconds", "_solver_worker_quiesce_seconds", "_solver_cdp_ready_timeout_seconds", "_wait_for_solver_cdp_ready", "_solver_cdp_probe_timeout_seconds", "_probe_solver_cdp_endpoint", "_manual_solver_retry_poll_seconds", "_captcha_solver_background_url", "_solver_manual_flag_request", "_default_manual_solver_retry_request", "_prefer_seed_manual_solver_retry_request", "_seed_priority_manual_solver_retry_request", "_prefer_seed_solver_request_for_payload", "_seed_priority_solver_request", "_manual_solver_retry_request", "_manual_solver_retry_next_epoch", "_solver_submission_pending", "_reserve_solver_submission", "_release_solver_submission", "_activate_solver_submission", "_solver_cdp_endpoint_is_remote", "_solver_request_delegated_to_node", "_submit_solver_request"]
