from __future__ import annotations
from tools.hybrid_seed_context import *  # noqa: F401,F403
from tools.hybrid_seed_normalization import *  # noqa: F401,F403
from tools.hybrid_seed_status import *  # noqa: F401,F403
from tools.hybrid_seed_mode import *  # noqa: F401,F403
from tools.hybrid_seed_loop import *  # noqa: F401,F403


def build_runtime_summary(
    *,
    result: dict[str, Any],
    requested_mode: str,
    effective_mode: str,
    submit: bool,
    api_base: str,
    cdp_endpoint: str,
    session_id: str,
    guidance_resolution: dict[str, Any] | None = None,
    lifecycle_summary: dict[str, Any] | None = None,
    intervention_summary: dict[str, Any] | None = None,
    intervention_stability_summary: dict[str, Any] | None = None,
    final_guidance_summary: dict[str, Any] | None = None,
    operator_digest_summary: dict[str, Any] | None = None,
    operator_digest_stability_summary: dict[str, Any] | None = None,
    operator_escalation_event_trend_summary: dict[str, Any] | None = None,
    operator_escalation_event_stability_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = _coerce_optional_mapping(result)
    guidance_resolution = _coerce_optional_mapping(guidance_resolution)
    guidance_details = _coerce_optional_mapping(guidance_resolution.get("guidance"))
    recovery_policy_details = _coerce_optional_mapping(guidance_resolution.get("recovery_policy"))
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    intervention_summary = _coerce_optional_mapping(intervention_summary)
    intervention_stability_summary = _coerce_optional_mapping(intervention_stability_summary)
    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
    operator_digest_summary = _coerce_optional_mapping(operator_digest_summary)
    operator_digest_stability_summary = _coerce_optional_mapping(operator_digest_stability_summary)
    operator_escalation_event_trend_summary = _coerce_optional_mapping(operator_escalation_event_trend_summary)
    operator_escalation_event_stability_summary = _coerce_optional_mapping(operator_escalation_event_stability_summary)
    loop_mode = result.get("mode") == "loop"
    normalized_requested_mode = str(
        _coerce_optional_text(requested_mode) or DEFAULT_MODE
    ).strip().lower()
    normalized_effective_mode = None
    effective_mode_text = _coerce_optional_text(effective_mode)
    if effective_mode_text is not None:
        normalized_effective_mode = effective_mode_text.strip().lower()
    if loop_mode:
        results = list(result.get("results") or [])
        last_result = _coerce_optional_mapping(results[-1]) if results else {}
        decision_counts: dict[str, int] = {}
        for key, value in _coerce_optional_mapping(result.get("counts")).items():
            parsed_value = _coerce_optional_int(value)
            key_text = _coerce_optional_text(key)
            if key_text is None or parsed_value is None or parsed_value < 0:
                continue
            decision_counts[key_text] = parsed_value
        reason_counts = _coerce_optional_mapping(result.get("reason_counts"))
        effective_mode_counts: dict[str, int] = {}
        for key, value in _coerce_optional_mapping(result.get("effective_mode_counts")).items():
            parsed_value = _coerce_optional_int(value)
            key_text = _coerce_optional_text(key)
            if key_text is None or parsed_value is None or parsed_value < 0:
                continue
            effective_mode_counts[key_text] = parsed_value
        guidance_status_counts: dict[str, int] = {}
        for key, value in _coerce_optional_mapping(result.get("guidance_status_counts")).items():
            parsed_value = _coerce_optional_int(value)
            key_text = _coerce_optional_text(key)
            if key_text is None or parsed_value is None or parsed_value < 0:
                continue
            guidance_status_counts[key_text] = parsed_value
        guidance_applied_count = _coerce_optional_int(result.get("guidance_applied_count"))
        if guidance_applied_count is None or guidance_applied_count < 0:
            guidance_applied_count = 0
        iterations = _coerce_optional_int(result.get("iterations"))
        if iterations is None or iterations < 0:
            iterations = len(results)
        termination_reason = _coerce_optional_text(result.get("termination_reason"))
    else:
        last_result = dict(result or {})
        decision = _coerce_optional_text(last_result.get("decision"))
        decision_counts = {str(decision): 1} if decision else {}
        reason = _coerce_optional_text(last_result.get("reason"))
        reason_counts = {str(reason): 1} if reason else {}
        effective_mode_counts = {normalized_effective_mode: 1} if normalized_effective_mode else {}
        guidance_status = _coerce_optional_text(guidance_resolution.get("guidance_status"))
        guidance_status_counts = {str(guidance_status): 1} if guidance_status else {}
        guidance_applied_count = int(
            _coerce_optional_bool(guidance_resolution.get("guidance_applied")) is True
        )
        iterations = 1
        termination_reason = "single_run"

    collection_result = _normalize_collection_result_payload(last_result.get("collection_result"))
    last_probe_summary = _normalize_probe_summary_payload(collection_result.get("probe_summary"))
    last_submit_result = _normalize_submit_result_payload(collection_result.get("submit_result"))
    fallback_reason_counts: dict[str, int] = {}
    for key, value in reason_counts.items():
        parsed_value = _coerce_optional_int(value)
        key_text = _coerce_optional_text(key)
        if key_text is None or parsed_value is None or parsed_value <= 0:
            continue
        fallback_reason_counts[key_text] = parsed_value
    top_fallback_reason = (
        sorted(fallback_reason_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if fallback_reason_counts
        else None
    )
    last_decision = _coerce_optional_text(last_result.get("decision"))
    last_reason = _coerce_optional_text(last_result.get("reason"))
    last_effective_mode = _first_optional_text(
        last_result.get("effective_mode"),
        normalized_effective_mode,
    )
    last_guidance_status = _first_optional_text(
        last_result.get("guidance_status"),
        guidance_resolution.get("guidance_status"),
    )
    last_guidance_recommended_mode = _first_optional_text(
        last_result.get("guidance_recommended_mode"),
        guidance_details.get("recommended_mode"),
    )
    last_recovery_policy_status = _first_optional_text(
        last_result.get("recovery_policy_status"),
        guidance_resolution.get("recovery_policy_status"),
    )
    last_recovery_policy_priority = _first_optional_text(
        last_result.get("recovery_policy_priority"),
        guidance_resolution.get("recovery_policy_priority"),
    )
    last_recovery_policy_effective_recommended_mode = _first_optional_text(
        last_result.get("recovery_policy_effective_recommended_mode"),
        recovery_policy_details.get("effective_recommended_mode"),
    )
    top_policy_reason = _first_optional_text(
        last_result.get("top_policy_reason"),
        recovery_policy_details.get("top_policy_reason"),
    )
    top_guidance_reason = _first_optional_text(
        last_result.get("top_guidance_reason"),
        guidance_details.get("top_guidance_reason"),
    )
    operator_escalation_audit_message = _first_optional_text(
        last_result.get("operator_escalation_audit_message"),
        result.get("operator_escalation_audit_message"),
    )
    operator_escalation_source_value = _first_optional_text(
        last_result.get("operator_escalation_source"),
        result.get("operator_escalation_source"),
    )
    operator_action_hint_value = _first_optional_text(
        last_result.get("operator_action_hint"),
        result.get("operator_action_hint"),
        operator_action_hint(last_result or result, lifecycle_summary=lifecycle_summary),
    )
    operator_final_guidance_message = _coerce_optional_text(final_guidance_summary.get("guidance_message"))
    operator_final_guidance_priority = _coerce_optional_text(final_guidance_summary.get("guidance_priority"))
    lifecycle_state = _coerce_optional_text(lifecycle_summary.get("lifecycle_state"))
    lifecycle_reason = _coerce_optional_text(lifecycle_summary.get("lifecycle_reason"))
    lifecycle_follow_up = _coerce_optional_text(lifecycle_summary.get("recommended_follow_up"))
    lifecycle_suggested_mode = _coerce_optional_text(lifecycle_summary.get("suggested_mode"))
    lifecycle_priority_hint = _coerce_optional_text(lifecycle_summary.get("priority_hint"))
    lifecycle_active_unresolved_priority = _coerce_optional_text(
        lifecycle_summary.get("active_unresolved_priority")
    )
    lifecycle_active_high_priority_unresolved_count = _coerce_optional_int(
        lifecycle_summary.get("active_high_priority_unresolved_count")
    )
    if lifecycle_active_high_priority_unresolved_count is not None and lifecycle_active_high_priority_unresolved_count < 0:
        lifecycle_active_high_priority_unresolved_count = 0
    intervention_status = _coerce_optional_text(intervention_summary.get("intervention_status"))
    intervention_priority = _coerce_optional_text(intervention_summary.get("intervention_priority"))
    intervention_reason = _coerce_optional_text(intervention_summary.get("intervention_reason"))
    intervention_action_hint = _coerce_optional_text(
        intervention_summary.get("preferred_operator_action_hint")
    )
    intervention_suggested_mode = _coerce_optional_text(intervention_summary.get("suggested_mode"))
    intervention_stability_status = _coerce_optional_text(
        intervention_stability_summary.get("stability_status")
    )
    intervention_stability_severity = _coerce_optional_text(
        intervention_stability_summary.get("stability_severity")
    )
    intervention_stability_explanation = _coerce_optional_text(
        intervention_stability_summary.get("operator_readable_explanation")
    )
    intervention_stability_action_hint = _coerce_optional_text(
        intervention_stability_summary.get("stability_action_hint")
    )
    operator_final_guidance_label = _coerce_optional_text(final_guidance_summary.get("guidance_label"))
    operator_digest_status = _coerce_optional_text(operator_digest_summary.get("digest_status"))
    operator_digest_priority = _coerce_optional_text(operator_digest_summary.get("digest_priority"))
    operator_digest_message = _coerce_optional_text(operator_digest_summary.get("operator_digest_message"))
    operator_digest_stability_status = _coerce_optional_text(
        operator_digest_stability_summary.get("stability_status")
    )
    operator_digest_stability_severity = _coerce_optional_text(
        operator_digest_stability_summary.get("stability_severity")
    )
    operator_digest_stability_explanation = _coerce_optional_text(
        operator_digest_stability_summary.get("operator_readable_explanation")
    )
    operator_escalation_source_last_changed_at = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("last_source_change_at")
    )
    operator_escalation_current_source = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("current_operator_escalation_source")
    )
    operator_escalation_previous_source = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("previous_distinct_operator_escalation_source")
    )
    operator_escalation_source_stability_status = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("stability_status")
    )
    operator_escalation_source_stability_severity = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("stability_severity")
    )
    operator_escalation_source_stability_explanation = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("operator_readable_explanation")
    )
    operator_escalation_source_change_count = _coerce_optional_int(
        operator_escalation_event_trend_summary.get("recent_source_change_count")
    )
    if operator_escalation_source_change_count is not None and operator_escalation_source_change_count < 0:
        operator_escalation_source_change_count = 0
    requested_mode_value = _first_optional_text(
        last_result.get("requested_mode"),
        normalized_requested_mode,
    ) or normalized_requested_mode
    effective_mode_value = last_effective_mode
    last_fallback_url = _coerce_optional_text(last_result.get("fallback_url"))
    effective_mode_source = _first_optional_text(
        last_result.get("effective_mode_source"),
        guidance_resolution.get("effective_mode_source"),
    )
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "runner_mode": effective_mode_value,
        "requested_mode": str(requested_mode_value or DEFAULT_MODE).strip().lower(),
        "effective_mode": effective_mode_value,
        "effective_mode_source": effective_mode_source,
        "guidance_applied": (
            _coerce_optional_bool(
                last_result.get("guidance_applied", guidance_resolution.get("guidance_applied"))
            )
            is True
        ),
        "guidance_status": last_guidance_status,
        "guidance_recommended_mode": last_guidance_recommended_mode,
        "recovery_policy_status": last_recovery_policy_status,
        "recovery_policy_priority": last_recovery_policy_priority,
        "recovery_policy_mode_pin_active": _coerce_optional_bool(
            last_result.get("recovery_policy_mode_pin_active", guidance_resolution.get("recovery_policy_mode_pin_active"))
        ),
        "recovery_policy_effective_recommended_mode": last_recovery_policy_effective_recommended_mode,
        "top_policy_reason": top_policy_reason,
        "top_guidance_reason": top_guidance_reason,
        "effective_mode_counts": effective_mode_counts,
        "guidance_status_counts": guidance_status_counts,
        "guidance_applied_count": guidance_applied_count,
        "last_effective_mode": last_effective_mode,
        "loop_mode": loop_mode,
        "submit_enabled": bool(submit),
        "session_id": session_id,
        "api_base": api_base,
        "cdp_endpoint": cdp_endpoint,
        "iterations": iterations,
        "decision_counts": decision_counts,
        "reason_counts": fallback_reason_counts,
        "top_fallback_reason": top_fallback_reason,
        "termination_reason": termination_reason,
        "operator_escalation_source": operator_escalation_source_value,
        "operator_escalation_audit_message": operator_escalation_audit_message,
        "operator_action_hint": operator_action_hint_value,
        "lifecycle_state": lifecycle_state,
        "lifecycle_reason": lifecycle_reason,
        "lifecycle_follow_up": lifecycle_follow_up,
        "lifecycle_suggested_mode": lifecycle_suggested_mode,
        "lifecycle_priority_hint": lifecycle_priority_hint,
        "lifecycle_active_unresolved_priority": lifecycle_active_unresolved_priority,
        "lifecycle_active_high_priority_unresolved_count": lifecycle_active_high_priority_unresolved_count,
        "intervention_status": intervention_status,
        "intervention_required": _coerce_optional_bool(intervention_summary.get("intervention_required")),
        "intervention_priority": intervention_priority,
        "intervention_reason": intervention_reason,
        "intervention_action_hint": intervention_action_hint,
        "intervention_suggested_mode": intervention_suggested_mode,
        "intervention_stability_status": intervention_stability_status,
        "intervention_stability_severity": intervention_stability_severity,
        "intervention_stability_explanation": intervention_stability_explanation,
        "intervention_stability_action_hint": intervention_stability_action_hint,
        "operator_final_guidance_label": operator_final_guidance_label,
        "operator_final_guidance_priority": operator_final_guidance_priority,
        "operator_final_guidance_message": operator_final_guidance_message,
        "operator_digest_status": operator_digest_status,
        "operator_digest_priority": operator_digest_priority,
        "operator_digest_message": operator_digest_message,
        "operator_digest_stability_status": operator_digest_stability_status,
        "operator_digest_stability_severity": operator_digest_stability_severity,
        "operator_digest_stability_explanation": operator_digest_stability_explanation,
        "operator_escalation_current_source": operator_escalation_current_source,
        "operator_escalation_previous_source": operator_escalation_previous_source,
        "operator_escalation_source_change_count": operator_escalation_source_change_count,
        "operator_escalation_source_last_changed_at": operator_escalation_source_last_changed_at,
        "operator_escalation_source_stability_status": operator_escalation_source_stability_status,
        "operator_escalation_source_stability_severity": operator_escalation_source_stability_severity,
        "operator_escalation_source_stability_explanation": operator_escalation_source_stability_explanation,
        "last_decision": last_decision,
        "last_reason": last_reason,
        "last_task": _normalize_task_payload(last_result.get("task")),
        "last_fallback_url": last_fallback_url,
        "last_browser_fallback_opened": (
            _coerce_optional_bool(last_result.get("browser_fallback_opened")) is True
        ),
        "last_probe_summary": last_probe_summary,
        "last_submit_result": last_submit_result,
    }

def persist_runtime_summary(summary: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def append_runtime_history(summary: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False))
        handle.write("\n")

def append_mode_switch_events(result: dict[str, Any], output_path: Path, *, session_id: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = _coerce_optional_mapping(result)
    loop_mode = result.get("mode") == "loop"
    results = list(result.get("results") or []) if loop_mode else [result]
    events: list[dict[str, Any]] = []
    for item in results:
        if _coerce_optional_bool(item.get("guidance_applied")) is not True:
            continue
        requested_mode = _coerce_optional_text(item.get("requested_mode"))
        effective_mode = _coerce_optional_text(item.get("effective_mode"))
        effective_mode_source = _coerce_optional_text(item.get("effective_mode_source"))
        guidance_status = _coerce_optional_text(item.get("guidance_status"))
        recovery_policy_status = _coerce_optional_text(item.get("recovery_policy_status"))
        top_guidance_reason = _first_optional_text(
            item.get("top_guidance_reason"),
            item.get("reason"),
            item.get("guidance_status"),
        )
        task_payload = _normalize_task_payload(item.get("task"))
        events.append(
            {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "session_id": session_id,
                "requested_mode": requested_mode,
                "effective_mode": effective_mode,
                "effective_mode_source": effective_mode_source,
                "guidance_status": guidance_status,
                "recovery_policy_status": recovery_policy_status,
                "top_guidance_reason": top_guidance_reason,
                "task_url": task_payload.get("url"),
                "task_page": task_payload.get("page"),
            }
        )
    if not events:
        return
    with output_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")

__all__ = ('build_runtime_summary', 'persist_runtime_summary', 'append_runtime_history', 'append_mode_switch_events')
