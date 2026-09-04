from __future__ import annotations
from tools.hybrid_seed_context import *  # noqa: F401,F403
from tools.hybrid_seed_normalization import *  # noqa: F401,F403
from tools.hybrid_seed_status import *  # noqa: F401,F403
from tools.hybrid_seed_mode import *  # noqa: F401,F403
from tools.hybrid_seed_loop import *  # noqa: F401,F403
from tools.hybrid_seed_runtime import *  # noqa: F401,F403
from tools.hybrid_seed_policy_state import *  # noqa: F401,F403


def operator_escalation_source(
    result: dict[str, Any],
    *,
    lifecycle_summary: dict[str, Any] | None = None,
    intervention_summary: dict[str, Any] | None = None,
    stability_summary: dict[str, Any] | None = None,
    include_flapping: bool = False,
) -> str | None:
    policy_status = _coerce_optional_text(result.get("recovery_policy_status")) or ""
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    intervention_summary = _coerce_optional_mapping(intervention_summary)
    stability_summary = _coerce_optional_mapping(stability_summary)
    priority_hint = _coerce_optional_text(lifecycle_summary.get("priority_hint")) or ""
    intervention_required = _coerce_optional_bool(intervention_summary.get("intervention_required"))
    intervention_reason = _coerce_optional_text(intervention_summary.get("intervention_reason")) or ""
    stability_status = _coerce_optional_text(stability_summary.get("stability_status")) or ""
    if policy_status == "escalate_repeated_repin":
        return "recovery_policy"
    if (
        priority_hint == "high_priority_backlog_present"
        or intervention_reason == "high_priority_unresolved_escalation_backlog"
    ):
        return "lifecycle_high_priority_backlog"
    if stability_status in {"escalating", "persistent_intervention_required"}:
        return "intervention_stability"
    if stability_status == "flapping":
        if include_flapping:
            return "intervention_stability_flapping"
        return None
    if intervention_required is True:
        return "intervention_policy"
    return None

def operator_action_hint(
    result: dict[str, Any],
    *,
    lifecycle_summary: dict[str, Any] | None = None,
    intervention_summary: dict[str, Any] | None = None,
    stability_summary: dict[str, Any] | None = None,
    include_flapping: bool = False,
) -> str | None:
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    intervention_summary = _coerce_optional_mapping(intervention_summary)
    source = operator_escalation_source(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=stability_summary,
        include_flapping=include_flapping,
    )
    suggested_mode = _first_optional_text(
        intervention_summary.get("suggested_mode"),
        lifecycle_summary.get("suggested_mode"),
        result.get("recovery_policy_effective_recommended_mode"),
        result.get("effective_mode"),
    )
    suggested_mode_suffix = (
        f"; suggested mode={suggested_mode}"
        if suggested_mode is not None
        else ""
    )
    preferred_intervention_action_hint = _coerce_optional_text(
        intervention_summary.get("preferred_operator_action_hint")
    )
    if preferred_intervention_action_hint is not None:
        return preferred_intervention_action_hint
    if source == "lifecycle_high_priority_backlog":
        return f"inspect unresolved high-priority backlog{suggested_mode_suffix}"
    if source == "recovery_policy":
        return f"follow recovery policy escalation guidance{suggested_mode_suffix}"
    if source == "intervention_policy":
        return f"prefer browser and investigate escalation{suggested_mode_suffix}"
    if source == "intervention_stability":
        return f"prefer browser and investigate escalation{suggested_mode_suffix}"
    if source == "intervention_stability_flapping":
        return f"monitor until stable{suggested_mode_suffix}"
    return None

def operator_escalation_audit_message(
    result: dict[str, Any],
    *,
    lifecycle_summary: dict[str, Any] | None = None,
    intervention_summary: dict[str, Any] | None = None,
    stability_summary: dict[str, Any] | None = None,
    final_guidance_summary: dict[str, Any] | None = None,
    digest_summary: dict[str, Any] | None = None,
    digest_stability_summary: dict[str, Any] | None = None,
    include_flapping: bool = False,
) -> str | None:
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    intervention_summary = _coerce_optional_mapping(intervention_summary)
    stability_summary = _coerce_optional_mapping(stability_summary)
    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
    digest_summary = _coerce_optional_mapping(digest_summary)
    digest_stability_summary = _coerce_optional_mapping(digest_stability_summary)
    source = operator_escalation_source(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=stability_summary,
        include_flapping=include_flapping,
    )
    if source is None:
        return None
    guidance_message = _first_optional_text(
        result.get("operator_final_guidance_message"),
        final_guidance_summary.get("guidance_message"),
        digest_summary.get("operator_digest_message"),
    )
    digest_status = _first_optional_text(
        result.get("operator_digest_status"),
        digest_summary.get("digest_status"),
    )
    digest_stability = _first_optional_text(
        result.get("operator_digest_stability_status"),
        digest_stability_summary.get("stability_status"),
    )
    detail_parts = [f"source={source}"]
    if digest_status is not None:
        detail_parts.append(f"digest={digest_status}")
    if digest_stability is not None:
        detail_parts.append(f"digest_stability={digest_stability}")
    return f"{guidance_message or 'Operator escalation'} [{', '.join(detail_parts)}]"

def emit_operator_console_summary(
    result: dict[str, Any],
    *,
    lifecycle_summary: dict[str, Any] | None = None,
    intervention_summary: dict[str, Any] | None = None,
    stability_summary: dict[str, Any] | None = None,
    final_guidance_summary: dict[str, Any] | None = None,
    digest_summary: dict[str, Any] | None = None,
    digest_stability_summary: dict[str, Any] | None = None,
    stream=None,
) -> None:
    stream = stream or sys.stderr
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    intervention_summary = _coerce_optional_mapping(intervention_summary)
    stability_summary = _coerce_optional_mapping(stability_summary)
    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
    digest_summary = _coerce_optional_mapping(digest_summary)
    digest_stability_summary = _coerce_optional_mapping(digest_stability_summary)
    source = operator_escalation_source(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=stability_summary,
    )
    if source is not None:
        audit_message = _coerce_optional_text(result.get("operator_escalation_audit_message"))
        has_audit_message = audit_message is not None
        if has_audit_message:
            print(
                f"[OPERATOR] Operator escalation audit: {audit_message}",
                file=stream,
            )
        policy_status = _coerce_optional_text(result.get("recovery_policy_status"))
        priority = _first_optional_text(
            result.get("recovery_policy_priority"),
            intervention_summary.get("intervention_priority"),
        )
        mode = _first_optional_text(
            result.get("recovery_policy_effective_recommended_mode"),
            intervention_summary.get("suggested_mode"),
            lifecycle_summary.get("suggested_mode"),
            result.get("effective_mode"),
        )
        reason = _first_optional_text(
            result.get("top_policy_reason"),
            intervention_summary.get("intervention_reason"),
            lifecycle_summary.get("priority_hint"),
        )
        guidance_label = _first_optional_text(
            result.get("operator_final_guidance_label"),
            final_guidance_summary.get("guidance_label"),
        )
        digest_status = _first_optional_text(
            result.get("operator_digest_status"),
            digest_summary.get("digest_status"),
        )
        digest_stability_status = _first_optional_text(
            result.get("operator_digest_stability_status"),
            digest_stability_summary.get("stability_status"),
        )
        task_payload = _normalize_task_payload(result.get("task"))
        page = task_payload.get("page")
        intervention_status_label = _coerce_optional_text(intervention_summary.get("intervention_status"))
        stability_status_label = _coerce_optional_text(stability_summary.get("stability_status"))
        lifecycle_state_label = _coerce_optional_text(lifecycle_summary.get("lifecycle_state"))
        status_label = (
            policy_status
            or intervention_status_label
            or stability_status_label
            or lifecycle_state_label
            or "operator_escalation"
        )
        if has_audit_message:
            parts = []
            if mode is not None:
                parts.append(f"mode={mode}")
            if priority is not None:
                parts.append(f"priority={priority}")
            if reason is not None:
                parts.append(f"reason={reason}")
            if page not in {None, "", "unknown"}:
                parts.append(f"page={page}")
            if parts:
                message = (
                    f"[OPERATOR] Operator escalation: {status_label} "
                    f"({', '.join(parts)})"
                )
            else:
                message = f"[OPERATOR] Operator escalation: {status_label}"
        else:
            parts = [
                f"source={source}",
            ]
            if mode is not None:
                parts.append(f"mode={mode}")
            if priority is not None:
                parts.append(f"priority={priority}")
            if reason is not None:
                parts.append(f"reason={reason}")
            if guidance_label is not None:
                parts.append(f"guidance={guidance_label}")
            if digest_status is not None:
                parts.append(f"digest_status={digest_status}")
            if digest_stability_status is not None:
                parts.append(f"digest_stability={digest_stability_status}")
            if page not in {None, "", "unknown"}:
                parts.append(f"page={page}")
            message = (
                f"[OPERATOR] Operator escalation: {status_label} "
                f"({', '.join(parts)})"
            )
        print(message, file=stream)

def emit_operator_recovery_console_summary(events: list[dict[str, Any]], *, stream=None) -> None:
    stream = stream or sys.stderr
    for event in events:
        if _coerce_optional_text(event.get("transition_kind")) != "escalation_cleared":
            continue
        from_status = _coerce_optional_text(event.get("from_policy_status"))
        to_status = _coerce_optional_text(event.get("to_policy_status"))
        mode = _coerce_optional_text(event.get("effective_mode"))
        page = _coerce_optional_int(event.get("task_page"))
        if page is not None and page < 0:
            page = None
        parts = []
        if from_status is not None:
            parts.append(f"from={from_status}")
        if to_status is not None:
            parts.append(f"to={to_status}")
        if mode is not None:
            parts.append(f"mode={mode}")
        if page not in {None, "", "unknown"}:
            parts.append(f"page={page}")
        if parts:
            message = f"[OPERATOR] Operator recovery: escalation_cleared ({', '.join(parts)})"
        else:
            message = "[OPERATOR] Operator recovery: escalation_cleared"
        print(message, file=stream)

def emit_operator_lifecycle_console_summary(summary: dict[str, Any], *, stream=None) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    if not summary and not summary.get("lifecycle_state"):
        return
    lifecycle_state = _coerce_optional_text(summary.get("lifecycle_state"))
    if lifecycle_state in {None, "steady"}:
        return
    reason = _coerce_optional_text(summary.get("lifecycle_reason"))
    follow_up = _coerce_optional_text(summary.get("recommended_follow_up"))
    suggested_mode = _coerce_optional_text(summary.get("suggested_mode"))
    priority_hint = _coerce_optional_text(summary.get("priority_hint"))
    active_unresolved_priority = _coerce_optional_text(summary.get("active_unresolved_priority"))
    active_high_priority_unresolved_count = _coerce_optional_int(
        summary.get("active_high_priority_unresolved_count")
    )
    if active_high_priority_unresolved_count is not None and active_high_priority_unresolved_count < 0:
        active_high_priority_unresolved_count = None
    parts = []
    if reason is not None:
        parts.append(f"reason={reason}")
    if follow_up is not None:
        parts.append(f"follow_up={follow_up}")
    if suggested_mode is not None:
        parts.append(f"suggested_mode={suggested_mode}")
    if priority_hint is not None:
        parts.append(f"priority_hint={priority_hint}")
    if active_unresolved_priority is not None:
        parts.append(f"active_unresolved_priority={active_unresolved_priority}")
    if active_high_priority_unresolved_count is not None:
        parts.append(f"active_high_priority_unresolved_count={active_high_priority_unresolved_count}")
    detail_suffix = f" ({', '.join(parts)})" if parts else ""
    message = f"[OPERATOR] Lifecycle state: {lifecycle_state}{detail_suffix}"
    print(message, file=stream)

def emit_operator_intervention_console_summary(
    summary: dict[str, Any],
    *,
    stream=None,
    suppress_reason: bool = False,
    suppress_priority: bool = False,
    suppress_suggested_mode: bool = False,
) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    intervention_status = _coerce_optional_text(summary.get("intervention_status"))
    if intervention_status in {None, "ready"}:
        return
    intervention_required = _coerce_optional_bool(summary.get("intervention_required"))
    priority = _coerce_optional_text(summary.get("intervention_priority"))
    reason = _coerce_optional_text(summary.get("intervention_reason"))
    action_hint = _coerce_optional_text(summary.get("preferred_operator_action_hint"))
    suggested_mode = _coerce_optional_text(summary.get("suggested_mode"))
    effective_suppress_action_hint = action_hint is None
    effective_suppress_suggested_mode = suppress_suggested_mode or (
        suggested_mode is None
        or (
            action_hint is not None
            and f"suggested mode={suggested_mode}" in action_hint
        )
    )
    parts = []
    if intervention_required is not None:
        parts.append(f"required={intervention_required}")
    if not suppress_priority and priority is not None:
        parts.append(f"priority={priority}")
    if not suppress_reason and reason is not None:
        parts.append(f"reason={reason}")
    if not effective_suppress_action_hint:
        parts.append(f"action_hint={action_hint}")
    if not effective_suppress_suggested_mode:
        parts.append(f"suggested_mode={suggested_mode}")
    detail_suffix = f" ({', '.join(parts)})" if parts else ""
    message = f"[OPERATOR] Intervention status: {intervention_status}{detail_suffix}"
    print(message, file=stream)

__all__ = ('operator_escalation_source', 'operator_action_hint', 'operator_escalation_audit_message', 'emit_operator_console_summary', 'emit_operator_recovery_console_summary', 'emit_operator_lifecycle_console_summary', 'emit_operator_intervention_console_summary')
