from __future__ import annotations
from tools.hybrid_seed_context import *  # noqa: F401,F403
from tools.hybrid_seed_normalization import *  # noqa: F401,F403
from tools.hybrid_seed_status import *  # noqa: F401,F403


def resolve_effective_mode(
    *,
    requested_mode: str,
    guidance: dict[str, Any] | None,
    recovery_policy: dict[str, Any] | None,
    respect_operator_guidance: bool,
) -> dict[str, Any]:
    normalized_requested = str(
        _coerce_optional_text(requested_mode) or DEFAULT_MODE
    ).strip().lower()
    guidance = _coerce_optional_mapping(guidance)
    recovery_policy = _coerce_optional_mapping(recovery_policy)
    guidance_status = _coerce_optional_text(guidance.get("guidance_status"))
    if "guidance_status" in guidance:
        guidance["guidance_status"] = guidance_status
    recommended_mode_value = _coerce_optional_text(guidance.get("recommended_mode"))
    if "recommended_mode" in guidance:
        guidance["recommended_mode"] = recommended_mode_value
    if "top_guidance_reason" in guidance:
        guidance["top_guidance_reason"] = _coerce_optional_text(guidance.get("top_guidance_reason"))
    recommended_mode = str(recommended_mode_value or "").strip().lower()
    recovery_policy_mode_value = _coerce_optional_text(recovery_policy.get("effective_recommended_mode"))
    if "effective_recommended_mode" in recovery_policy:
        recovery_policy["effective_recommended_mode"] = recovery_policy_mode_value
    recovery_policy_mode = str(recovery_policy_mode_value or "").strip().lower()
    recovery_policy_status = _coerce_optional_text(recovery_policy.get("policy_status"))
    if "policy_status" in recovery_policy:
        recovery_policy["policy_status"] = recovery_policy_status
    recovery_policy_priority = _coerce_optional_text(recovery_policy.get("priority"))
    if "priority" in recovery_policy:
        recovery_policy["priority"] = recovery_policy_priority
    recovery_policy_mode_pin_active = _coerce_optional_bool(recovery_policy.get("mode_pin_active"))
    if "mode_pin_active" in recovery_policy:
        recovery_policy["mode_pin_active"] = recovery_policy_mode_pin_active
    if "top_policy_reason" in recovery_policy:
        recovery_policy["top_policy_reason"] = _coerce_optional_text(recovery_policy.get("top_policy_reason"))
    if (
        respect_operator_guidance
        and normalized_requested == "hybrid"
        and recovery_policy_mode_pin_active is True
        and recovery_policy_mode in {"hybrid", "browser"}
    ):
        effective_mode = recovery_policy_mode
        effective_mode_source = "recovery_policy"
    elif (
        respect_operator_guidance
        and normalized_requested == "hybrid"
        and recommended_mode in {"hybrid", "browser"}
    ):
        effective_mode = recommended_mode
        effective_mode_source = "guidance"
    else:
        effective_mode = normalized_requested
        effective_mode_source = "requested_mode"
    return {
        "requested_mode": normalized_requested,
        "effective_mode": effective_mode,
        "effective_mode_source": effective_mode_source,
        "guidance_applied": bool(
            respect_operator_guidance
            and normalized_requested == "hybrid"
            and effective_mode != normalized_requested
        ),
        "recovery_policy_applied": bool(
            respect_operator_guidance
            and normalized_requested == "hybrid"
            and effective_mode_source == "recovery_policy"
            and effective_mode != normalized_requested
        ),
        "guidance_status": guidance_status,
        "recovery_policy_status": recovery_policy_status,
        "recovery_policy_priority": recovery_policy_priority,
        "recovery_policy_mode_pin_active": recovery_policy_mode_pin_active,
        "guidance": guidance,
        "recovery_policy": recovery_policy,
    }

def build_browser_fallback_url(task_url: str) -> str:
    parsed = urlparse(task_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["uni_mode"] = ["SNIFF_WORKER"]
    rebuilt_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=rebuilt_query))

def open_browser_fallback(url: str, profile_dir: Path, remote_debugging_port: int) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            "chrome",
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={remote_debugging_port}",
            "--remote-allow-origins=*",
            "--disable-session-crashed-bubble",
            "--disable-restore-session-state",
            "--new-window",
            url,
        ],
        shell=False,
    )

def run_once(
    *,
    api_base: str,
    session_id: str,
    cdp_endpoint: str,
    submit: bool,
    mode: str = DEFAULT_MODE,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    open_browser_fallback: bool = False,
    claim_task_fn: Callable[..., dict[str, Any]] = claim_next_seed_task,
    export_cookies_fn: Callable[..., list[dict[str, Any]]] = browserless_seed_probe.export_cdp_cookies,
    hybrid_collect_fn: Callable[..., dict[str, Any]] = hybrid_seed_collector.run_hybrid_collection,
    open_browser_fn: Callable[[str, Path, int], None] = open_browser_fallback,
) -> dict[str, Any]:
    try:
        task_payload = claim_task_fn(api_base=api_base, session_id=session_id)
    except requests.exceptions.RequestException as exc:
        return {
            "decision": "api_unavailable",
            "reason": "dispatch_endpoint_unreachable",
            "error": _coerce_optional_text(str(exc)),
        }
    raw_task = task_payload.get("task") if isinstance(task_payload, dict) else None
    task = _normalize_task_payload(raw_task) if raw_task is not None else None
    if not isinstance(task, dict) or task.get("url") is None:
        return {
            "decision": "idle",
            "message": _coerce_optional_text(task_payload.get("message")) if isinstance(task_payload, dict) else "no task",
            "task": task,
        }

    normalized_mode = str(_coerce_optional_text(mode) or DEFAULT_MODE).strip().lower()
    if normalized_mode == "browser":
        fallback_url = build_browser_fallback_url(task["url"])
        result: dict[str, Any] = {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": task,
            "task_message": _coerce_optional_text(task_payload.get("message")) if isinstance(task_payload, dict) else None,
            "fallback_url": fallback_url,
        }
        if open_browser_fallback:
            open_browser_fn(fallback_url, profile_dir, urlparse(cdp_endpoint).port or 9223)
            result["browser_fallback_opened"] = True
        else:
            result["browser_fallback_opened"] = False
        return result

    cookies = export_cookies_fn(cdp_endpoint)
    collection_result = _normalize_collection_result_payload(
        hybrid_collect_fn(
            task["url"],
            cookies=cookies,
            submit=submit,
            api_base=api_base,
        )
    )
    decision = collection_result.get("decision")
    result: dict[str, Any] = {
        "decision": decision,
        "reason": collection_result.get("reason"),
        "task": task,
        "task_message": _coerce_optional_text(task_payload.get("message")) if isinstance(task_payload, dict) else None,
        "collection_result": collection_result,
    }
    if decision == "browser_fallback_required":
        fallback_url = build_browser_fallback_url(task["url"])
        result["fallback_url"] = fallback_url
        if normalized_mode == "hybrid" and open_browser_fallback:
            open_browser_fn(fallback_url, profile_dir, urlparse(cdp_endpoint).port or 9223)
            result["browser_fallback_opened"] = True
        else:
            result["browser_fallback_opened"] = False
    return result

__all__ = ('resolve_effective_mode', 'build_browser_fallback_url', 'open_browser_fallback', 'run_once')
