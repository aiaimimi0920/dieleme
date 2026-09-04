from __future__ import annotations
from tools.hybrid_seed_context import *  # noqa: F401,F403
from tools.hybrid_seed_normalization import *  # noqa: F401,F403
from tools.hybrid_seed_status import *  # noqa: F401,F403
from tools.hybrid_seed_mode import *  # noqa: F401,F403


def run_loop(
    *,
    api_base: str,
    session_id: str,
    cdp_endpoint: str,
    submit: bool,
    mode: str = DEFAULT_MODE,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    open_browser_fallback: bool = False,
    max_runs: int | None = None,
    idle_sleep_seconds: float = 10.0,
    success_sleep_seconds: float = 2.0,
    fallback_sleep_seconds: float = 15.0,
    stop_on_fallback: bool = False,
    stop_on_operator_escalation: bool = False,
    max_consecutive_fallbacks: int | None = None,
    respect_operator_guidance: bool = False,
    load_operator_status_bundle_fn: Callable[..., dict[str, dict[str, Any]]] | None = None,
    load_guidance_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_strategy_guidance,
    load_recovery_policy_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_recovery_policy,
    load_lifecycle_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_lifecycle_state_summary,
    load_intervention_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_intervention_policy_summary,
    load_stability_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_intervention_stability_summary,
    load_final_guidance_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_final_guidance_summary,
    load_digest_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_digest_summary,
    load_digest_stability_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_digest_stability_summary,
    load_escalation_event_trend_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_escalation_event_trend_summary,
    load_escalation_event_stability_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_escalation_event_stability_summary,
    run_once_fn: Callable[..., dict[str, Any]] = run_once,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    iterations = 0
    normalized_requested_mode = str(_coerce_optional_text(mode) or DEFAULT_MODE).strip().lower()
    counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    effective_mode_counts: dict[str, int] = {}
    guidance_status_counts: dict[str, int] = {}
    guidance_applied_count = 0
    results: list[dict[str, Any]] = []
    consecutive_fallbacks = 0
    termination_reason = "max_runs_reached" if max_runs is not None else "stopped"
    should_load_operator_status = bool(respect_operator_guidance or stop_on_operator_escalation)
    if not should_load_operator_status:
        effective_load_operator_status_bundle_fn = None
    elif load_operator_status_bundle_fn is None:
        using_default_status_loaders = (
            load_guidance_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_guidance_fn"]
            and load_recovery_policy_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_recovery_policy_fn"]
            and load_lifecycle_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_lifecycle_summary_fn"]
            and load_intervention_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_intervention_summary_fn"]
            and load_stability_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_stability_summary_fn"]
            and load_final_guidance_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_final_guidance_summary_fn"]
            and load_digest_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_digest_summary_fn"]
            and load_digest_stability_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_digest_stability_summary_fn"]
            and load_escalation_event_trend_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_escalation_event_trend_summary_fn"]
            and load_escalation_event_stability_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_escalation_event_stability_summary_fn"]
        )
        effective_load_operator_status_bundle_fn = (
            load_hybrid_collection_operator_status_bundle if using_default_status_loaders else None
        )
    else:
        effective_load_operator_status_bundle_fn = load_operator_status_bundle_fn

    while max_runs is None or iterations < max_runs:
        guidance_payload: dict[str, Any] = {}
        recovery_policy_payload: dict[str, Any] = {}
        lifecycle_summary: dict[str, Any] = {}
        intervention_summary: dict[str, Any] = {}
        stability_summary: dict[str, Any] = {}
        final_guidance_summary: dict[str, Any] = {}
        digest_summary: dict[str, Any] = {}
        digest_stability_summary: dict[str, Any] = {}
        escalation_event_trend_summary: dict[str, Any] = {}
        escalation_event_stability_summary: dict[str, Any] = {}
        escalation_source = None
        with hybrid_collection_status_snapshot_scope():
            operator_status_bundle: dict[str, dict[str, Any]] = {}
            if effective_load_operator_status_bundle_fn is not None:
                try:
                    operator_status_bundle = effective_load_operator_status_bundle_fn(api_base)
                except requests.exceptions.RequestException:
                    operator_status_bundle = {}
            operator_status_bundle = _coerce_optional_mapping(operator_status_bundle)
            if respect_operator_guidance:
                if operator_status_bundle:
                    guidance_payload = _coerce_optional_mapping(operator_status_bundle.get("guidance"))
                    recovery_policy_payload = _coerce_optional_mapping(operator_status_bundle.get("recovery_policy"))
                else:
                    try:
                        guidance_payload = load_guidance_fn(api_base)
                    except requests.exceptions.RequestException:
                        guidance_payload = {}
                    try:
                        recovery_policy_payload = load_recovery_policy_fn(api_base)
                    except requests.exceptions.RequestException:
                        recovery_policy_payload = {}
            guidance_resolution = resolve_effective_mode(
                requested_mode=mode,
                guidance=guidance_payload,
                recovery_policy=recovery_policy_payload,
                respect_operator_guidance=respect_operator_guidance,
            )
            resolution_effective_mode = _coerce_optional_text(
                guidance_resolution.get("effective_mode")
            )
            effective_mode = _first_optional_text(
                resolution_effective_mode,
                guidance_resolution.get("requested_mode"),
                normalized_requested_mode,
            ) or DEFAULT_MODE
            effective_mode_for_result = resolution_effective_mode
            result = run_once_fn(
                api_base=api_base,
                session_id=session_id,
                cdp_endpoint=cdp_endpoint,
                submit=submit,
                mode=effective_mode,
                profile_dir=profile_dir,
                open_browser_fallback=open_browser_fallback,
            )
            result = _coerce_optional_mapping(result)
            if "task" in result:
                result["task"] = _normalize_task_payload(result.get("task"))
            if "collection_result" in result:
                result["collection_result"] = _normalize_collection_result_payload(
                    result.get("collection_result")
                )
            result["decision"] = _coerce_optional_text(result.get("decision"))
            result["reason"] = _coerce_optional_text(result.get("reason"))
            if "error" in result:
                result["error"] = _coerce_optional_text(result.get("error"))
            if "task_message" in result:
                result["task_message"] = _coerce_optional_text(result.get("task_message"))
            if "message" in result:
                result["message"] = _coerce_optional_text(result.get("message"))
            result["browser_fallback_opened"] = (
                _coerce_optional_bool(result.get("browser_fallback_opened")) is True
            )
            result["fallback_url"] = _coerce_optional_text(result.get("fallback_url"))
            requested_mode_for_result = (
                _coerce_optional_text(guidance_resolution.get("requested_mode"))
                or normalized_requested_mode
            )
            result["requested_mode"] = requested_mode_for_result
            result["effective_mode"] = effective_mode_for_result
            effective_mode_source = _coerce_optional_text(
                guidance_resolution.get("effective_mode_source")
            )
            result["effective_mode_source"] = effective_mode_source
            result["guidance_applied"] = (
                _coerce_optional_bool(guidance_resolution.get("guidance_applied")) is True
            )
            guidance_status = _coerce_optional_text(guidance_resolution.get("guidance_status"))
            result["guidance_status"] = guidance_status
            guidance_recommended_mode = _coerce_optional_mapping(
                guidance_resolution.get("guidance")
            ).get("recommended_mode")
            guidance_recommended_mode = _coerce_optional_text(guidance_recommended_mode)
            result["guidance_recommended_mode"] = guidance_recommended_mode
            top_guidance_reason = _coerce_optional_mapping(
                guidance_resolution.get("guidance")
            ).get("top_guidance_reason")
            top_guidance_reason = _coerce_optional_text(top_guidance_reason)
            top_policy_reason = _coerce_optional_mapping(
                guidance_resolution.get("recovery_policy")
            ).get("top_policy_reason")
            top_policy_reason = _coerce_optional_text(top_policy_reason)
            if effective_mode_source == "recovery_policy":
                top_guidance_reason = top_policy_reason or top_guidance_reason
            result["top_guidance_reason"] = top_guidance_reason
            result["top_policy_reason"] = top_policy_reason
            recovery_policy_status = _coerce_optional_text(
                guidance_resolution.get("recovery_policy_status")
            )
            result["recovery_policy_status"] = recovery_policy_status
            recovery_policy_priority = _coerce_optional_text(
                guidance_resolution.get("recovery_policy_priority")
            )
            result["recovery_policy_priority"] = recovery_policy_priority
            result["recovery_policy_mode_pin_active"] = _coerce_optional_bool(
                guidance_resolution.get("recovery_policy_mode_pin_active")
            )
            recovery_policy_effective_recommended_mode = _coerce_optional_mapping(
                guidance_resolution.get("recovery_policy")
            ).get("effective_recommended_mode")
            recovery_policy_effective_recommended_mode = _coerce_optional_text(
                recovery_policy_effective_recommended_mode
            )
            result["recovery_policy_effective_recommended_mode"] = (
                recovery_policy_effective_recommended_mode
            )
            if stop_on_operator_escalation:
                if operator_status_bundle:
                    lifecycle_summary = _coerce_optional_mapping(operator_status_bundle.get("lifecycle_summary"))
                    intervention_summary = _coerce_optional_mapping(operator_status_bundle.get("intervention_summary"))
                    stability_summary = _coerce_optional_mapping(operator_status_bundle.get("intervention_stability_summary"))
                    final_guidance_summary = _coerce_optional_mapping(operator_status_bundle.get("final_guidance_summary"))
                    digest_summary = _coerce_optional_mapping(operator_status_bundle.get("digest_summary"))
                    digest_stability_summary = _coerce_optional_mapping(operator_status_bundle.get("digest_stability_summary"))
                    escalation_event_trend_summary = _coerce_optional_mapping(operator_status_bundle.get("escalation_event_trend_summary"))
                    escalation_event_stability_summary = _coerce_optional_mapping(operator_status_bundle.get("escalation_event_stability_summary"))
                else:
                    try:
                        lifecycle_summary = load_lifecycle_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        lifecycle_summary = {}
                    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
                    try:
                        intervention_summary = load_intervention_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        intervention_summary = {}
                    intervention_summary = _coerce_optional_mapping(intervention_summary)
                    try:
                        stability_summary = load_stability_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        stability_summary = {}
                    stability_summary = _coerce_optional_mapping(stability_summary)
                    try:
                        final_guidance_summary = load_final_guidance_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        final_guidance_summary = {}
                    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
                    try:
                        digest_summary = load_digest_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        digest_summary = {}
                    digest_summary = _coerce_optional_mapping(digest_summary)
                    try:
                        digest_stability_summary = load_digest_stability_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        digest_stability_summary = {}
                    digest_stability_summary = _coerce_optional_mapping(digest_stability_summary)
                    try:
                        escalation_event_trend_summary = load_escalation_event_trend_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        escalation_event_trend_summary = {}
                    escalation_event_trend_summary = _coerce_optional_mapping(escalation_event_trend_summary)
                    try:
                        escalation_event_stability_summary = load_escalation_event_stability_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        escalation_event_stability_summary = {}
                    escalation_event_stability_summary = _coerce_optional_mapping(escalation_event_stability_summary)
        iterations += 1
        results.append(result)
        decision = result.get("decision")
        if decision not in {None, "", "unknown"}:
            decision_key = str(decision)
            counts[decision_key] = counts.get(decision_key, 0) + 1
        if effective_mode_for_result:
            effective_mode_counts[effective_mode_for_result] = (
                effective_mode_counts.get(effective_mode_for_result, 0) + 1
            )
        guidance_status = result.get("guidance_status")
        if guidance_status:
            guidance_key = str(guidance_status)
            guidance_status_counts[guidance_key] = guidance_status_counts.get(guidance_key, 0) + 1
        if _coerce_optional_bool(result.get("guidance_applied")) is True:
            guidance_applied_count += 1
        reason = result.get("reason")
        if reason in {"", "unknown"}:
            reason = None
        if reason:
            reason_key = str(reason)
            reason_counts[reason_key] = reason_counts.get(reason_key, 0) + 1
        if stop_on_operator_escalation:
            source_last_changed_at = _coerce_optional_text(
                escalation_event_trend_summary.get("last_source_change_at")
            )
            current_source = _coerce_optional_text(
                escalation_event_trend_summary.get("current_operator_escalation_source")
            )
            source_stability_status = _coerce_optional_text(
                escalation_event_stability_summary.get("stability_status")
            )
            source_stability_explanation = _coerce_optional_text(
                escalation_event_stability_summary.get("operator_readable_explanation")
            )
            digest_stability_explanation = _coerce_optional_text(
                digest_stability_summary.get("operator_readable_explanation")
            )
            final_guidance_label = _coerce_optional_text(
                final_guidance_summary.get("guidance_label")
            )
            final_guidance_priority = _coerce_optional_text(
                final_guidance_summary.get("guidance_priority")
            )
            final_guidance_message = _coerce_optional_text(
                final_guidance_summary.get("guidance_message")
            )
            digest_status = _coerce_optional_text(digest_summary.get("digest_status"))
            digest_stability_status = _coerce_optional_text(
                digest_stability_summary.get("stability_status")
            )
            digest_message = _coerce_optional_text(digest_summary.get("operator_digest_message"))
            digest_priority = _coerce_optional_text(digest_summary.get("digest_priority"))
            digest_stability_severity = _coerce_optional_text(
                digest_stability_summary.get("stability_severity")
            )
            previous_source = _coerce_optional_text(
                escalation_event_trend_summary.get("previous_distinct_operator_escalation_source")
            )
            source_stability_severity = _coerce_optional_text(
                escalation_event_stability_summary.get("stability_severity")
            )
            result["operator_digest_stability_status"] = digest_stability_status
            result["operator_digest_stability_severity"] = digest_stability_severity
            result["operator_digest_stability_explanation"] = digest_stability_explanation
            result["operator_escalation_current_source"] = current_source
            result["operator_escalation_previous_source"] = previous_source
            operator_escalation_source_change_count = _coerce_optional_int(
                escalation_event_trend_summary.get("recent_source_change_count")
            )
            if operator_escalation_source_change_count is not None and operator_escalation_source_change_count < 0:
                operator_escalation_source_change_count = 0
            result["operator_escalation_source_change_count"] = operator_escalation_source_change_count
            result["operator_escalation_source_last_changed_at"] = source_last_changed_at
            result["operator_escalation_source_stability_status"] = source_stability_status
            result["operator_escalation_source_stability_severity"] = source_stability_severity
            result["operator_escalation_source_stability_explanation"] = source_stability_explanation
            escalation_source = operator_escalation_source(
                result,
                lifecycle_summary=lifecycle_summary,
                intervention_summary=intervention_summary,
                stability_summary=stability_summary,
                include_flapping=True,
            )
            if escalation_source is not None:
                result["operator_escalation_source"] = escalation_source
                result["operator_action_hint"] = operator_action_hint(
                    result,
                    lifecycle_summary=lifecycle_summary,
                    intervention_summary=intervention_summary,
                    stability_summary=stability_summary,
                    include_flapping=True,
                )
                result["operator_final_guidance_label"] = final_guidance_label
                result["operator_final_guidance_priority"] = final_guidance_priority
                result["operator_final_guidance_message"] = final_guidance_message
                result["operator_digest_status"] = digest_status
                result["operator_digest_priority"] = digest_priority
                result["operator_digest_message"] = digest_message
                audit_message = operator_escalation_audit_message(
                    result,
                    lifecycle_summary=lifecycle_summary,
                    intervention_summary=intervention_summary,
                    stability_summary=stability_summary,
                    final_guidance_summary=final_guidance_summary,
                    digest_summary=digest_summary,
                    digest_stability_summary=digest_stability_summary,
                    include_flapping=True,
                )
                audit_message = _coerce_optional_text(audit_message)
                if audit_message is not None:
                    result["operator_escalation_audit_message"] = audit_message
                else:
                    result.pop("operator_escalation_audit_message", None)
            elif _coerce_optional_text(result.get("operator_escalation_source")) is None:
                result.pop("operator_escalation_source", None)
        if stop_on_fallback and decision == "browser_fallback_required":
            termination_reason = "stop_on_fallback"
            break
        if stop_on_operator_escalation and operator_escalation_exit_code(
            result,
            lifecycle_summary=lifecycle_summary,
            intervention_summary=intervention_summary,
            stability_summary=stability_summary,
            include_flapping=True,
            configured_exit_code=1,
        ) is not None:
            termination_reason = "operator_escalation"
            break
        if decision == "browser_fallback_required":
            consecutive_fallbacks += 1
            if max_consecutive_fallbacks is not None and consecutive_fallbacks >= max_consecutive_fallbacks:
                termination_reason = "fallback_escalation_threshold_reached"
                break
        else:
            consecutive_fallbacks = 0
        if max_runs is not None and iterations >= max_runs:
            termination_reason = "max_runs_reached"
            break

        if decision == "browserless_success":
            sleep_fn(success_sleep_seconds)
        elif decision == "browser_fallback_required":
            sleep_fn(fallback_sleep_seconds)
        else:
            sleep_fn(idle_sleep_seconds)

    last_operator_result = (
        _coerce_optional_mapping(results[-1])
        if results and termination_reason == "operator_escalation"
        else {}
    )
    return {
        "mode": "loop",
        "iterations": iterations,
        "counts": counts,
        "reason_counts": reason_counts,
        "effective_mode_counts": effective_mode_counts,
        "guidance_status_counts": guidance_status_counts,
        "guidance_applied_count": guidance_applied_count,
        "termination_reason": termination_reason,
        "operator_escalation_source": last_operator_result.get("operator_escalation_source"),
        "operator_escalation_audit_message": last_operator_result.get("operator_escalation_audit_message"),
        "operator_final_guidance_label": last_operator_result.get("operator_final_guidance_label"),
        "operator_final_guidance_priority": last_operator_result.get("operator_final_guidance_priority"),
        "operator_final_guidance_message": last_operator_result.get("operator_final_guidance_message"),
        "operator_digest_status": last_operator_result.get("operator_digest_status"),
        "operator_digest_priority": last_operator_result.get("operator_digest_priority"),
        "operator_digest_message": last_operator_result.get("operator_digest_message"),
        "operator_digest_stability_status": last_operator_result.get("operator_digest_stability_status"),
        "operator_digest_stability_severity": last_operator_result.get("operator_digest_stability_severity"),
        "operator_digest_stability_explanation": last_operator_result.get("operator_digest_stability_explanation"),
        "operator_escalation_current_source": last_operator_result.get("operator_escalation_current_source"),
        "operator_escalation_previous_source": last_operator_result.get("operator_escalation_previous_source"),
        "operator_escalation_source_change_count": last_operator_result.get("operator_escalation_source_change_count", 0),
        "operator_escalation_source_last_changed_at": last_operator_result.get("operator_escalation_source_last_changed_at"),
        "operator_escalation_source_stability_status": last_operator_result.get("operator_escalation_source_stability_status"),
        "operator_escalation_source_stability_severity": last_operator_result.get("operator_escalation_source_stability_severity"),
        "operator_escalation_source_stability_explanation": last_operator_result.get("operator_escalation_source_stability_explanation"),
        "results": results,
    }

__all__ = ('run_loop',)
