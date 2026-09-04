from __future__ import annotations
from tools.hybrid_seed_context import *  # noqa: F401,F403
from tools.hybrid_seed_normalization import *  # noqa: F401,F403
from tools.hybrid_seed_status import *  # noqa: F401,F403
from tools.hybrid_seed_mode import *  # noqa: F401,F403
from tools.hybrid_seed_loop import *  # noqa: F401,F403
from tools.hybrid_seed_runtime import *  # noqa: F401,F403
from tools.hybrid_seed_policy_state import *  # noqa: F401,F403
from tools.hybrid_seed_operator_guidance import *  # noqa: F401,F403


def emit_operator_intervention_stability_console_summary(
    summary: dict[str, Any],
    *,
    stream=None,
    suppress_action_hint: bool = False,
    suppress_current: bool = False,
    suppress_status: bool = False,
) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    stability_status = _coerce_optional_text(summary.get("stability_status"))
    if stability_status in {None, "stable_ready"}:
        return
    stability_severity = _coerce_optional_text(summary.get("stability_severity"))
    current_status = _coerce_optional_text(summary.get("current_intervention_status"))
    previous_status = _coerce_optional_text(summary.get("previous_intervention_status"))
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count"))
    if recent_change_count is not None and recent_change_count < 0:
        recent_change_count = None
    explanation = _coerce_optional_text(summary.get("operator_readable_explanation"))
    action_hint = _coerce_optional_text(summary.get("stability_action_hint"))
    effective_suppress_action_hint = suppress_action_hint or action_hint is None
    parts = []
    if not suppress_status:
        parts.append(stability_status)
    if stability_severity is not None:
        parts.append(f"severity={stability_severity}")
    if not suppress_current and current_status is not None:
        parts.append(f"current={current_status}")
    if previous_status is not None:
        parts.append(f"previous={previous_status}")
    if recent_change_count is not None:
        parts.append(f"changes={recent_change_count}")
    if explanation is not None:
        parts.append(f"explanation={explanation}")
    if not effective_suppress_action_hint:
        parts.append(f"action_hint={action_hint}")
    if not parts:
        parts.append(stability_status)
    message = f"[OPERATOR] Intervention stability: {', '.join(parts)}"
    print(message, file=stream)

def emit_operator_final_guidance_console_summary(summary: dict[str, Any], *, stream=None) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    raw_priority = summary.get("guidance_priority")
    priority = _coerce_optional_text(raw_priority)
    priority_key = (priority or "").lower()
    if priority_key == "info" or (priority is None and not raw_priority):
        return
    if priority_key == "unknown":
        priority = None
    guidance_label = _coerce_optional_text(summary.get("guidance_label"))
    label = str(guidance_label or "Operator guidance")
    guidance_message = _coerce_optional_text(summary.get("guidance_message"))
    message = str(guidance_message or label)
    suggested_mode = _coerce_optional_text(summary.get("suggested_mode"))
    parts = []
    if priority is not None:
        parts.append(f"priority={priority}")
    if suggested_mode is not None:
        parts.append(f"suggested_mode={suggested_mode}")
    detail_suffix = f" ({', '.join(parts)})" if parts else ""
    print(f"[OPERATOR] Final guidance: {message}{detail_suffix}", file=stream)

def emit_operator_digest_console_summary(
    summary: dict[str, Any],
    *,
    stream=None,
    suppress_message: bool = False,
    suppress_status: bool = False,
) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    digest_status = _coerce_optional_text(summary.get("digest_status"))
    if digest_status in {None, "ready"}:
        return
    digest_priority = _coerce_optional_text(summary.get("digest_priority"))
    digest_message = _coerce_optional_text(summary.get("operator_digest_message"))
    has_priority = digest_priority is not None
    effective_suppress_message = suppress_message or digest_message is None
    if effective_suppress_message and suppress_status:
        if not has_priority:
            return
        message = f"[OPERATOR] Operator digest: priority={digest_priority}"
    elif effective_suppress_message:
        if has_priority:
            message = f"[OPERATOR] Operator digest: {digest_status} (priority={digest_priority})"
        else:
            message = f"[OPERATOR] Operator digest: {digest_status}"
    elif suppress_status:
        if has_priority:
            message = f"[OPERATOR] Operator digest: {digest_message} (priority={digest_priority})"
        else:
            message = f"[OPERATOR] Operator digest: {digest_message}"
    else:
        parts = [f"status={digest_status}"]
        if has_priority:
            parts.append(f"priority={digest_priority}")
        message = f"[OPERATOR] Operator digest: {digest_message} ({', '.join(parts)})"
    print(message, file=stream)

def emit_operator_digest_stability_console_summary(
    summary: dict[str, Any],
    *,
    stream=None,
    suppress_current: bool = False,
    suppress_status: bool = False,
) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    stability_status = _coerce_optional_text(summary.get("stability_status"))
    if stability_status in {None, "stable_digest"}:
        return
    stability_severity = _coerce_optional_text(summary.get("stability_severity"))
    current_status = _coerce_optional_text(summary.get("current_digest_status"))
    previous_status = _coerce_optional_text(summary.get("previous_digest_status"))
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count"))
    if recent_change_count is not None and recent_change_count < 0:
        recent_change_count = None
    explanation = _coerce_optional_text(summary.get("operator_readable_explanation"))
    effective_suppress_status = suppress_status or explanation is not None
    parts = []
    if not effective_suppress_status:
        parts.append(stability_status)
    if stability_severity is not None:
        parts.append(f"severity={stability_severity}")
    if not suppress_current and current_status is not None:
        parts.append(f"current={current_status}")
    if previous_status is not None:
        parts.append(f"previous={previous_status}")
    if recent_change_count is not None:
        parts.append(f"changes={recent_change_count}")
    if explanation is not None:
        parts.append(f"explanation={explanation}")
    if not parts:
        parts.append(stability_status)
    message = f"[OPERATOR] Operator digest stability: {', '.join(parts)}"
    print(message, file=stream)

def emit_operator_escalation_event_trend_console_summary(summary: dict[str, Any], *, stream=None) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    current_source = _coerce_optional_text(summary.get("current_operator_escalation_source"))
    recent_change_count = _coerce_optional_int(summary.get("recent_source_change_count"))
    if recent_change_count is not None and recent_change_count < 0:
        recent_change_count = None
    previous_source = _coerce_optional_text(summary.get("previous_distinct_operator_escalation_source"))
    last_changed_at = _coerce_optional_text(summary.get("last_source_change_at"))
    if current_source is None or (
        recent_change_count in {None, 0}
        and not previous_source
        and last_changed_at is None
    ):
        return
    parts = []
    if previous_source is not None:
        parts.append(f"previous={previous_source}")
    if recent_change_count is not None:
        parts.append(f"changes={recent_change_count}")
    if last_changed_at is not None:
        parts.append(f"last_changed_at={last_changed_at}")
    detail_suffix = f" ({', '.join(parts)})" if parts else ""
    message = f"[OPERATOR] Operator escalation source trend: current={current_source}{detail_suffix}"
    print(message, file=stream)

def emit_operator_escalation_event_stability_console_summary(
    summary: dict[str, Any],
    *,
    stream=None,
    suppress_source_context: bool = False,
    suppress_status: bool = False,
) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    stability_status = _coerce_optional_text(summary.get("stability_status"))
    if stability_status in {None, "stable_escalation_source"}:
        return
    stability_severity = _coerce_optional_text(summary.get("stability_severity"))
    current_source = _coerce_optional_text(summary.get("current_operator_escalation_source"))
    previous_source = _coerce_optional_text(summary.get("previous_operator_escalation_source"))
    recent_source_change_count = _coerce_optional_int(summary.get("recent_source_change_count"))
    if recent_source_change_count is not None and recent_source_change_count < 0:
        recent_source_change_count = None
    explanation = _coerce_optional_text(summary.get("operator_readable_explanation"))
    parts = []
    if not suppress_status:
        parts.append(stability_status)
    if stability_severity is not None:
        parts.append(f"severity={stability_severity}")
    if not suppress_source_context:
        if current_source is not None:
            parts.append(f"current={current_source}")
        if previous_source is not None:
            parts.append(f"previous={previous_source}")
        if recent_source_change_count is not None:
            parts.append(f"changes={recent_source_change_count}")
    if explanation is not None:
        parts.append(f"explanation={explanation}")
    if not parts:
        return
    message = f"[OPERATOR] Operator escalation source stability: {', '.join(parts)}"
    print(message, file=stream)

def operator_escalation_exit_code(
    result: dict[str, Any],
    *,
    lifecycle_summary: dict[str, Any] | None = None,
    intervention_summary: dict[str, Any] | None = None,
    stability_summary: dict[str, Any] | None = None,
    include_flapping: bool = False,
    configured_exit_code: int,
) -> int | None:
    source = operator_escalation_source(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=stability_summary,
        include_flapping=include_flapping,
    )
    if source is not None:
        return int(configured_exit_code)
    return None

__all__ = ('emit_operator_intervention_stability_console_summary', 'emit_operator_final_guidance_console_summary', 'emit_operator_digest_console_summary', 'emit_operator_digest_stability_console_summary', 'emit_operator_escalation_event_trend_console_summary', 'emit_operator_escalation_event_stability_console_summary', 'operator_escalation_exit_code')
