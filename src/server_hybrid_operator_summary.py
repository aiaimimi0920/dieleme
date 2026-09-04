from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _hybrid_collection_operator_final_guidance_summary(
    intervention_policy_summary: dict[str, Any],
    intervention_stability_summary: dict[str, Any],
) -> dict[str, Any]:
    intervention_policy_summary = _coerce_optional_mapping(intervention_policy_summary)
    intervention_stability_summary = _coerce_optional_mapping(intervention_stability_summary)
    available = (
        _coerce_optional_bool(intervention_policy_summary.get("available")) is True
        or _coerce_optional_bool(intervention_stability_summary.get("available")) is True
    )
    if not available:
        return {
            "available": False,
            "guidance_label": None,
            "guidance_priority": None,
            "guidance_message": None,
            "preferred_action_hint": None,
            "suggested_mode": None,
            "intervention_status": None,
            "stability_status": None,
        }

    stability_status = _coerce_optional_text(intervention_stability_summary.get("stability_status")) or ""
    action_hint = _coerce_optional_text(intervention_stability_summary.get("stability_action_hint")) or ""
    intervention_status = _coerce_optional_text(
        intervention_stability_summary.get("current_intervention_status")
    ) or _coerce_optional_text(intervention_policy_summary.get("intervention_status"))
    suggested_mode = _coerce_optional_text(intervention_policy_summary.get("suggested_mode"))
    normalized_action_hint = action_hint.lower()
    if "browser" in normalized_action_hint and stability_status in {"escalating", "persistent_intervention_required"}:
        suggested_mode = "browser"
    elif "hybrid" in normalized_action_hint and not suggested_mode:
        suggested_mode = "hybrid"

    if stability_status == "escalating":
        guidance_label = "Escalating intervention"
        guidance_priority = "high"
    elif stability_status == "persistent_intervention_required":
        guidance_label = "Persistent intervention required"
        guidance_priority = "high"
    elif stability_status == "flapping":
        guidance_label = "Flapping intervention"
        guidance_priority = "warning"
    elif stability_status == "transitioning":
        guidance_label = "Transitioning intervention"
        guidance_priority = "warning"
    elif stability_status == "stable_ready":
        guidance_label = "Stable ready state"
        guidance_priority = "info"
    else:
        guidance_label = "Operator guidance"
        guidance_priority = _coerce_optional_text(
            intervention_policy_summary.get("intervention_priority")
        )

    guidance_message = f"{guidance_label}: {action_hint}." if action_hint else guidance_label
    return {
        "available": True,
        "guidance_label": guidance_label,
        "guidance_priority": guidance_priority,
        "guidance_message": guidance_message,
        "preferred_action_hint": action_hint or None,
        "suggested_mode": suggested_mode,
        "intervention_status": intervention_status,
        "stability_status": stability_status or None,
    }

def _hybrid_collection_operator_digest_summary(
    intervention_policy_summary: dict[str, Any],
    intervention_stability_summary: dict[str, Any],
    final_guidance_summary: dict[str, Any],
    final_guidance_stability_summary: dict[str, Any],
) -> dict[str, Any]:
    intervention_policy_summary = _coerce_optional_mapping(intervention_policy_summary)
    intervention_stability_summary = _coerce_optional_mapping(intervention_stability_summary)
    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
    final_guidance_stability_summary = _coerce_optional_mapping(final_guidance_stability_summary)
    available = any(
        (
            _coerce_optional_bool(intervention_policy_summary.get("available")) is True,
            _coerce_optional_bool(intervention_stability_summary.get("available")) is True,
            _coerce_optional_bool(final_guidance_summary.get("available")) is True,
            _coerce_optional_bool(final_guidance_stability_summary.get("available")) is True,
        )
    )
    if not available:
        return {
            "available": False,
            "digest_status": "unknown",
            "digest_priority": "info",
            "final_guidance_message": None,
            "intervention_status": None,
            "intervention_stability_status": None,
            "final_guidance_stability_status": None,
            "operator_digest_message": None,
        }

    current_guidance_label = _coerce_optional_text(
        final_guidance_stability_summary.get("current_guidance_label")
    ) or _coerce_optional_text(final_guidance_summary.get("guidance_label"))
    current_guidance_priority = _coerce_optional_text(
        final_guidance_stability_summary.get("current_guidance_priority")
    ) or _coerce_optional_text(final_guidance_summary.get("guidance_priority"))
    current_guidance_message = _coerce_optional_text(
        final_guidance_stability_summary.get("current_guidance_message")
    ) or _coerce_optional_text(final_guidance_summary.get("guidance_message"))
    if not current_guidance_priority:
        if current_guidance_label in {"Escalating intervention", "Persistent intervention required"}:
            current_guidance_priority = "high"
        elif current_guidance_label in {"Transitioning intervention", "Flapping intervention"}:
            current_guidance_priority = "warning"
        elif current_guidance_label == "Stable ready state":
            current_guidance_priority = "info"
    intervention_status = _coerce_optional_text(intervention_policy_summary.get("intervention_status"))
    intervention_stability_status = _coerce_optional_text(intervention_stability_summary.get("stability_status"))
    final_guidance_stability_status = _coerce_optional_text(final_guidance_stability_summary.get("stability_status"))
    final_guidance_priority = (
        _coerce_optional_text(current_guidance_priority)
        or _coerce_optional_text(final_guidance_stability_summary.get("stability_severity"))
        or "info"
    )

    guidance_intervention_status = None
    guidance_intervention_stability_status = None
    if current_guidance_label == "Stable ready state":
        guidance_intervention_status = "ready"
        guidance_intervention_stability_status = "stable_ready"
    elif current_guidance_label == "Transitioning intervention":
        guidance_intervention_status = "monitor"
        guidance_intervention_stability_status = "transitioning"
    elif current_guidance_label == "Escalating intervention":
        guidance_intervention_status = "intervention_required"
        guidance_intervention_stability_status = "escalating"
    elif current_guidance_label == "Persistent intervention required":
        guidance_intervention_status = "intervention_required"
        guidance_intervention_stability_status = "persistent_intervention_required"
    elif current_guidance_label == "Flapping intervention":
        guidance_intervention_status = "monitor"
        guidance_intervention_stability_status = "flapping"

    if guidance_intervention_status is not None:
        intervention_status = guidance_intervention_status

    if guidance_intervention_stability_status is not None:
        intervention_stability_status = guidance_intervention_stability_status

    if final_guidance_priority == "high":
        digest_status = "intervention_required"
        digest_priority = "high"
    elif final_guidance_priority == "warning":
        digest_status = "attention_required"
        digest_priority = "warning"
    else:
        digest_status = "ready"
        digest_priority = "info"

    return {
        "available": True,
        "digest_status": digest_status,
        "digest_priority": digest_priority,
        "final_guidance_message": current_guidance_message,
        "intervention_status": intervention_status or current_guidance_label,
        "intervention_stability_status": intervention_stability_status,
        "final_guidance_stability_status": final_guidance_stability_status,
        "operator_digest_message": current_guidance_message,
    }

def _hybrid_collection_recovery_latency_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    escalation_entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_operator_escalation_events.jsonl")
    recovery_entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_operator_escalation_recovery_events.jsonl")
    if not escalation_entries or not recovery_entries:
        return {
            "available": False,
            "last_recovery_at": None,
            "last_recovery_from_policy_status": None,
            "last_recovery_to_policy_status": None,
            "matched_escalation_at": None,
            "matched_escalation_policy_status": None,
            "last_recovery_latency_seconds": None,
            "last_recovery_latency_minutes": None,
        }

    recent_escalations = escalation_entries[-limit:]
    recent_recoveries = recovery_entries[-limit:]
    last_recovery = recent_recoveries[-1]
    recovery_at = _coerce_optional_text(last_recovery.get("generated_at"))
    matched_escalation = None
    matched_escalation_at = None
    for entry in reversed(recent_escalations):
        escalation_at = _coerce_optional_text(entry.get("generated_at"))
        if escalation_at and recovery_at and escalation_at <= recovery_at:
            matched_escalation = entry
            matched_escalation_at = escalation_at
            break
    if matched_escalation is None:
        return {
            "available": False,
            "last_recovery_at": recovery_at,
            "last_recovery_from_policy_status": _coerce_optional_text(last_recovery.get("from_policy_status")),
            "last_recovery_to_policy_status": _coerce_optional_text(last_recovery.get("to_policy_status")),
            "matched_escalation_at": None,
            "matched_escalation_policy_status": None,
            "last_recovery_latency_seconds": None,
            "last_recovery_latency_minutes": None,
        }

    latency_seconds = None
    latency_minutes = None
    try:
        recovery_dt = datetime.datetime.strptime(recovery_at, "%Y-%m-%d %H:%M:%S")
        escalation_dt = datetime.datetime.strptime(matched_escalation_at, "%Y-%m-%d %H:%M:%S")
        latency_seconds = int((recovery_dt - escalation_dt).total_seconds())
        latency_minutes = round(latency_seconds / 60, 2)
        if latency_seconds < 0:
            latency_seconds = None
            latency_minutes = None
    except Exception:
        latency_seconds = None
        latency_minutes = None

    return {
        "available": True,
        "last_recovery_at": recovery_at,
        "last_recovery_from_policy_status": _coerce_optional_text(last_recovery.get("from_policy_status")),
        "last_recovery_to_policy_status": _coerce_optional_text(last_recovery.get("to_policy_status")),
        "matched_escalation_at": matched_escalation_at,
        "matched_escalation_policy_status": _coerce_optional_text(matched_escalation.get("policy_status")),
        "last_recovery_latency_seconds": latency_seconds,
        "last_recovery_latency_minutes": latency_minutes,
    }

def _hybrid_collection_operator_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    guidance_applied_count = _coerce_optional_int(summary.get("guidance_applied_count")) or 0
    if guidance_applied_count < 0:
        guidance_applied_count = 0
    browserless_success_count = _coerce_optional_int(summary.get("browserless_success_count")) or 0
    if browserless_success_count < 0:
        browserless_success_count = 0
    browser_fallback_required_count = _coerce_optional_int(summary.get("browser_fallback_required_count")) or 0
    if browser_fallback_required_count < 0:
        browser_fallback_required_count = 0
    browser_worker_dispatched_count = _coerce_optional_int(summary.get("browser_worker_dispatched_count")) or 0
    if browser_worker_dispatched_count < 0:
        browser_worker_dispatched_count = 0
    last_task_page = _coerce_optional_int(summary.get("last_task_page"))
    if last_task_page is not None and last_task_page < 0:
        last_task_page = None
    return {
        "hybrid_collection_available": _coerce_optional_bool(summary.get("available")) is True,
        "hybrid_collection_runner_mode": _coerce_optional_text(summary.get("runner_mode")),
        "hybrid_collection_requested_mode": _coerce_optional_text(summary.get("requested_mode")),
        "hybrid_collection_effective_mode_source": _coerce_optional_text(summary.get("effective_mode_source")),
        "hybrid_collection_operator_action_hint": _coerce_optional_text(summary.get("operator_action_hint")),
        "hybrid_collection_last_decision": _coerce_optional_text(summary.get("last_decision")),
        "hybrid_collection_last_reason": _coerce_optional_text(summary.get("last_reason")),
        "hybrid_collection_last_effective_mode": _coerce_optional_text(summary.get("last_effective_mode")),
        "hybrid_collection_top_fallback_reason": _coerce_optional_text(summary.get("top_fallback_reason")),
        "hybrid_collection_termination_reason": _coerce_optional_text(summary.get("termination_reason")),
        "hybrid_collection_guidance_applied_count": guidance_applied_count,
        "hybrid_collection_guidance_status": _coerce_optional_text(summary.get("guidance_status")),
        "hybrid_collection_recovery_policy_status": _coerce_optional_text(summary.get("recovery_policy_status")),
        "hybrid_collection_recovery_mode_pin_active": _coerce_optional_bool(
            summary.get("recovery_policy_mode_pin_active")
        )
        is True,
        "hybrid_collection_browserless_success_count": browserless_success_count,
        "hybrid_collection_browser_fallback_required_count": browser_fallback_required_count,
        "hybrid_collection_browser_worker_dispatched_count": browser_worker_dispatched_count,
        "hybrid_collection_last_task_url": _coerce_optional_text(summary.get("last_task_url")),
        "hybrid_collection_last_task_page": last_task_page,
        "hybrid_collection_last_submit_batch_status": _coerce_optional_text(summary.get("last_submit_batch_status")),
        "hybrid_collection_last_submit_progress_status": _coerce_optional_text(
            summary.get("last_submit_progress_status")
        ),
    }

def _hybrid_collection_operator_history_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_runs = _coerce_optional_int(summary.get("recent_runs")) or 0
    if recent_runs < 0:
        recent_runs = 0
    recent_browserless_success_count = _coerce_optional_int(summary.get("recent_browserless_success_count")) or 0
    if recent_browserless_success_count < 0:
        recent_browserless_success_count = 0
    recent_browser_fallback_required_count = (
        _coerce_optional_int(summary.get("recent_browser_fallback_required_count")) or 0
    )
    if recent_browser_fallback_required_count < 0:
        recent_browser_fallback_required_count = 0
    recent_browser_worker_dispatched_count = (
        _coerce_optional_int(summary.get("recent_browser_worker_dispatched_count")) or 0
    )
    if recent_browser_worker_dispatched_count < 0:
        recent_browser_worker_dispatched_count = 0
    recent_browserless_success_rate = _coerce_optional_float(summary.get("recent_browserless_success_rate")) or 0.0
    if recent_browserless_success_rate < 0:
        recent_browserless_success_rate = 0.0
    elif recent_browserless_success_rate > 1:
        recent_browserless_success_rate = 1.0
    return {
        "hybrid_collection_recent_runs": recent_runs,
        "hybrid_collection_recent_browserless_success_count": recent_browserless_success_count,
        "hybrid_collection_recent_browser_fallback_required_count": recent_browser_fallback_required_count,
        "hybrid_collection_recent_browser_worker_dispatched_count": recent_browser_worker_dispatched_count,
        "hybrid_collection_recent_browserless_success_rate": recent_browserless_success_rate,
        "hybrid_collection_recent_top_fallback_reason": _coerce_optional_text(summary.get("recent_top_fallback_reason")),
        "hybrid_collection_recent_top_termination_reason": _coerce_optional_text(
            summary.get("recent_top_termination_reason")
        ),
    }

def _hybrid_collection_operator_action_hint_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    return {
        "hybrid_collection_current_action_hint": _coerce_optional_text(summary.get("current_action_hint")),
        "hybrid_collection_previous_action_hint": _coerce_optional_text(summary.get("previous_distinct_action_hint")),
        "hybrid_collection_action_hint_change_count": recent_change_count,
        "hybrid_collection_action_hint_last_changed_at": _coerce_optional_text(summary.get("last_change_at")),
    }

def _hybrid_collection_operator_final_guidance_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    return {
        "hybrid_collection_current_final_guidance_label": _coerce_optional_text(summary.get("current_guidance_label")),
        "hybrid_collection_current_final_guidance_priority": _coerce_optional_text(
            summary.get("current_guidance_priority")
        ),
        "hybrid_collection_current_final_guidance_message": _coerce_optional_text(
            summary.get("current_guidance_message")
        ),
        "hybrid_collection_previous_final_guidance_message": _coerce_optional_text(
            summary.get("previous_distinct_guidance_message")
        ),
        "hybrid_collection_final_guidance_change_count": recent_change_count,
        "hybrid_collection_final_guidance_last_changed_at": _coerce_optional_text(summary.get("last_change_at")),
    }

def _hybrid_collection_operator_final_guidance_stability_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_final_guidance_stability_status": _coerce_optional_text(summary.get("stability_status")),
        "hybrid_collection_final_guidance_stability_severity": _coerce_optional_text(
            summary.get("stability_severity")
        ),
        "hybrid_collection_final_guidance_stability_explanation": _coerce_optional_text(
            summary.get("operator_readable_explanation")
        ),
    }

def _hybrid_collection_operator_digest_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    return {
        "hybrid_collection_current_digest_status": _coerce_optional_text(summary.get("current_digest_status")),
        "hybrid_collection_current_digest_priority": _coerce_optional_text(summary.get("current_digest_priority")),
        "hybrid_collection_current_digest_message": _coerce_optional_text(summary.get("current_digest_message")),
        "hybrid_collection_previous_digest_message": _coerce_optional_text(
            summary.get("previous_distinct_digest_message")
        ),
        "hybrid_collection_digest_change_count": recent_change_count,
        "hybrid_collection_digest_last_changed_at": _coerce_optional_text(summary.get("last_change_at")),
    }

def _hybrid_collection_operator_digest_stability_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_digest_stability_status": _coerce_optional_text(summary.get("stability_status")),
        "hybrid_collection_digest_stability_severity": _coerce_optional_text(summary.get("stability_severity")),
        "hybrid_collection_digest_stability_explanation": _coerce_optional_text(
            summary.get("operator_readable_explanation")
        ),
    }

def _hybrid_collection_operator_intervention_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    return {
        "hybrid_collection_current_intervention_status": _coerce_optional_text(
            summary.get("current_intervention_status")
        ),
        "hybrid_collection_current_intervention_priority": _coerce_optional_text(
            summary.get("current_intervention_priority")
        ),
        "hybrid_collection_current_intervention_reason": _coerce_optional_text(
            summary.get("current_intervention_reason")
        ),
        "hybrid_collection_previous_intervention_status": _coerce_optional_text(
            summary.get("previous_distinct_intervention_status")
        ),
        "hybrid_collection_intervention_change_count": recent_change_count,
        "hybrid_collection_intervention_last_changed_at": _coerce_optional_text(summary.get("last_change_at")),
    }

def _hybrid_collection_operator_intervention_event_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_event_count = _coerce_optional_int(summary.get("recent_event_count")) or 0
    if recent_event_count < 0:
        recent_event_count = 0
    return {
        "hybrid_collection_recent_intervention_event_count": recent_event_count,
        "hybrid_collection_last_intervention_event_at": _coerce_optional_text(summary.get("last_event_at")),
        "hybrid_collection_last_intervention_transition_kind": _coerce_optional_text(summary.get("last_transition_kind")),
        "hybrid_collection_last_to_intervention_status": _coerce_optional_text(summary.get("last_to_intervention_status")),
        "hybrid_collection_last_to_intervention_priority": _coerce_optional_text(
            summary.get("last_to_intervention_priority")
        ),
        "hybrid_collection_last_to_final_guidance_label": _coerce_optional_text(
            summary.get("last_to_final_guidance_label")
        ),
        "hybrid_collection_last_to_final_guidance_priority": _coerce_optional_text(
            summary.get("last_to_final_guidance_priority")
        ),
        "hybrid_collection_last_to_final_guidance_message": _coerce_optional_text(
            summary.get("last_to_final_guidance_message")
        ),
    }

def _hybrid_collection_operator_intervention_stability_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_intervention_stability_status": _coerce_optional_text(summary.get("stability_status")),
        "hybrid_collection_intervention_stability_severity": _coerce_optional_text(summary.get("stability_severity")),
        "hybrid_collection_intervention_stability_explanation": _coerce_optional_text(
            summary.get("operator_readable_explanation")
        ),
        "hybrid_collection_intervention_stability_action_hint": _coerce_optional_text(
            summary.get("stability_action_hint")
        ),
    }

__all__ = ["_hybrid_collection_operator_final_guidance_summary", "_hybrid_collection_operator_digest_summary", "_hybrid_collection_recovery_latency_summary", "_hybrid_collection_operator_overview_fields", "_hybrid_collection_operator_history_overview_fields", "_hybrid_collection_operator_action_hint_trend_overview_fields", "_hybrid_collection_operator_final_guidance_trend_overview_fields", "_hybrid_collection_operator_final_guidance_stability_overview_fields", "_hybrid_collection_operator_digest_trend_overview_fields", "_hybrid_collection_operator_digest_stability_overview_fields", "_hybrid_collection_operator_intervention_trend_overview_fields", "_hybrid_collection_operator_intervention_event_overview_fields", "_hybrid_collection_operator_intervention_stability_overview_fields"]
