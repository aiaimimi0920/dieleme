from __future__ import annotations
from tools.hybrid_seed_context import *  # noqa: F401,F403
from tools.hybrid_seed_normalization import *  # noqa: F401,F403
from tools.hybrid_seed_status import *  # noqa: F401,F403
from tools.hybrid_seed_mode import *  # noqa: F401,F403
from tools.hybrid_seed_loop import *  # noqa: F401,F403
from tools.hybrid_seed_runtime import *  # noqa: F401,F403


def _normalize_recovery_policy_snapshot(policy: dict[str, Any] | None) -> dict[str, Any]:
    policy = _coerce_optional_mapping(policy)
    policy_status = _coerce_optional_text(policy.get("policy_status"))
    effective_recommended_mode = _coerce_optional_text(policy.get("effective_recommended_mode"))
    top_policy_reason = _coerce_optional_text(policy.get("top_policy_reason"))
    return {
        "policy_status": policy_status,
        "effective_recommended_mode": effective_recommended_mode,
        "mode_pin_active": _coerce_optional_bool(policy.get("mode_pin_active")),
        "top_policy_reason": top_policy_reason,
    }

def _load_recovery_policy_state(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}

def persist_recovery_policy_state(policy: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_normalize_recovery_policy_snapshot(policy), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def append_recovery_policy_transition_events(
    result: dict[str, Any],
    state_path: Path,
    events_path: Path,
    *,
    session_id: str,
) -> None:
    previous_state = _normalize_recovery_policy_snapshot(_load_recovery_policy_state(state_path))
    result = _coerce_optional_mapping(result)
    loop_mode = result.get("mode") == "loop"
    results = list(result.get("results") or []) if loop_mode else [result]
    current_state = previous_state
    events: list[dict[str, Any]] = []
    current_state_has_signal = any(value is not None for value in current_state.values())

    for item in results:
        next_state = _normalize_recovery_policy_snapshot(
            {
                "policy_status": item.get("recovery_policy_status"),
                "effective_recommended_mode": item.get("recovery_policy_effective_recommended_mode"),
                "mode_pin_active": item.get("recovery_policy_mode_pin_active"),
                "top_policy_reason": item.get("top_policy_reason"),
            }
        )
        if (
            not any(
                (
                    next_state.get("policy_status"),
                    next_state.get("effective_recommended_mode"),
                    next_state.get("top_policy_reason"),
                )
            )
            and next_state.get("mode_pin_active") is None
        ):
            continue
        if current_state_has_signal and next_state != current_state:
            requested_mode = _coerce_optional_text(item.get("requested_mode"))
            effective_mode = _coerce_optional_text(item.get("effective_mode"))
            task_payload = _normalize_task_payload(item.get("task"))
            if current_state.get("mode_pin_active") and not next_state.get("mode_pin_active"):
                transition_kind = "pin_released"
            elif not current_state.get("mode_pin_active") and next_state.get("mode_pin_active"):
                transition_kind = "pin_activated"
            elif current_state.get("policy_status") != next_state.get("policy_status"):
                transition_kind = "policy_status_changed"
            elif current_state.get("effective_recommended_mode") != next_state.get("effective_recommended_mode"):
                transition_kind = "recommended_mode_changed"
            else:
                transition_kind = "policy_updated"
            events.append(
                {
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "session_id": session_id,
                    "transition_kind": transition_kind,
                    "from_policy_status": current_state.get("policy_status"),
                    "to_policy_status": next_state.get("policy_status"),
                    "from_mode_pin_active": current_state.get("mode_pin_active"),
                    "to_mode_pin_active": next_state.get("mode_pin_active"),
                    "from_effective_recommended_mode": current_state.get("effective_recommended_mode"),
                    "to_effective_recommended_mode": next_state.get("effective_recommended_mode"),
                    "from_top_policy_reason": current_state.get("top_policy_reason"),
                    "to_top_policy_reason": next_state.get("top_policy_reason"),
                    "requested_mode": requested_mode,
                    "effective_mode": effective_mode,
                    "task_url": task_payload.get("url"),
                    "task_page": task_payload.get("page"),
                }
            )
        current_state = next_state
        current_state_has_signal = any(value is not None for value in current_state.values())

    persist_recovery_policy_state(current_state, state_path)
    if not events:
        return
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")

def append_operator_escalation_events(
    result: dict[str, Any],
    output_path: Path,
    *,
    session_id: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = _coerce_optional_mapping(result)
    loop_mode = result.get("mode") == "loop"
    results = list(result.get("results") or []) if loop_mode else [result]
    events: list[dict[str, Any]] = []

    for item in results:
        source = _coerce_optional_text(item.get("operator_escalation_source")) or ""
        requested_mode = _coerce_optional_text(item.get("requested_mode"))
        policy_status = _coerce_optional_text(item.get("recovery_policy_status"))
        policy_priority = _first_optional_text(
            item.get("recovery_policy_priority"),
            item.get("intervention_priority"),
        )
        top_policy_reason = _first_optional_text(
            item.get("top_policy_reason"),
            item.get("intervention_reason"),
        )
        operator_escalation_audit_message = _coerce_optional_text(
            item.get("operator_escalation_audit_message")
        )
        effective_mode = _coerce_optional_text(item.get("effective_mode"))
        effective_mode_source = _coerce_optional_text(item.get("effective_mode_source"))
        task_payload = _normalize_task_payload(item.get("task"))
        if policy_status == "escalate_repeated_repin":
            escalation_kind = "repeated_repin_cycle"
            if not source:
                source = "recovery_policy"
        elif source in {
            "lifecycle_high_priority_backlog",
            "intervention_policy",
            "intervention_stability",
            "intervention_stability_flapping",
        }:
            escalation_kind = source
        else:
            continue
        events.append(
            {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "session_id": session_id,
                "escalation_kind": escalation_kind,
                "operator_escalation_source": source or None,
                "policy_status": policy_status,
                "policy_priority": policy_priority,
                "top_policy_reason": top_policy_reason,
                "requested_mode": requested_mode,
                "effective_mode": effective_mode,
                "effective_mode_source": effective_mode_source,
                "task_url": task_payload.get("url"),
                "task_page": task_payload.get("page"),
                "operator_escalation_audit_message": operator_escalation_audit_message,
            }
        )
    if not events:
        return
    with output_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")

def _normalize_operator_escalation_snapshot(result: dict[str, Any] | None) -> dict[str, Any]:
    result = _coerce_optional_mapping(result)
    policy_status = _first_optional_text(
        result.get("recovery_policy_status"),
        result.get("policy_status"),
    )
    policy_priority = _first_optional_text(
        result.get("recovery_policy_priority"),
        result.get("policy_priority"),
    )
    top_policy_reason = _coerce_optional_text(result.get("top_policy_reason"))
    explicit_escalation_kind = _coerce_optional_text(result.get("escalation_kind")) or ""
    operator_escalation_source = _coerce_optional_text(result.get("operator_escalation_source")) or ""
    source_driven_escalation_kinds = {
        "lifecycle_high_priority_backlog",
        "intervention_policy",
        "intervention_stability",
        "intervention_stability_flapping",
    }
    if policy_status == "escalate_repeated_repin":
        escalation_kind = "repeated_repin_cycle"
    elif operator_escalation_source in source_driven_escalation_kinds:
        escalation_kind = operator_escalation_source
    elif explicit_escalation_kind in {"repeated_repin_cycle", *source_driven_escalation_kinds}:
        escalation_kind = explicit_escalation_kind
    else:
        escalation_kind = None
    return {
        "escalation_kind": escalation_kind,
        "policy_status": policy_status,
        "policy_priority": policy_priority,
        "top_policy_reason": top_policy_reason,
    }

def _load_operator_escalation_state(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}

def persist_operator_escalation_state(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_normalize_operator_escalation_snapshot(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def append_operator_escalation_recovery_events(
    result: dict[str, Any],
    state_path: Path,
    recovery_events_path: Path,
    *,
    session_id: str,
) -> None:
    previous_state = _normalize_operator_escalation_snapshot(_load_operator_escalation_state(state_path))
    result = _coerce_optional_mapping(result)
    loop_mode = result.get("mode") == "loop"
    results = list(result.get("results") or []) if loop_mode else [result]
    current_state = previous_state
    events: list[dict[str, Any]] = []

    for item in results:
        next_state = _normalize_operator_escalation_snapshot(item)
        previous_active = bool(current_state.get("escalation_kind"))
        next_active = bool(next_state.get("escalation_kind"))
        effective_mode = _coerce_optional_text(item.get("effective_mode"))
        task_payload = _normalize_task_payload(item.get("task"))
        if previous_active and not next_active:
            events.append(
                {
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "session_id": session_id,
                    "transition_kind": "escalation_cleared",
                    "from_escalation_kind": current_state.get("escalation_kind"),
                    "from_policy_status": current_state.get("policy_status"),
                    "to_policy_status": next_state.get("policy_status"),
                    "effective_mode": effective_mode,
                    "task_url": task_payload.get("url"),
                    "task_page": task_payload.get("page"),
                }
            )
        current_state = next_state

    persist_operator_escalation_state(current_state, state_path)
    if not events:
        return []
    recovery_events_path.parent.mkdir(parents=True, exist_ok=True)
    with recovery_events_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")
    return events

def _normalize_operator_intervention_snapshot(summary: dict[str, Any] | None) -> dict[str, Any]:
    summary = _coerce_optional_mapping(summary)
    intervention_status = _coerce_optional_text(summary.get("intervention_status"))
    intervention_required = _coerce_optional_bool(summary.get("intervention_required"))
    intervention_priority = _coerce_optional_text(summary.get("intervention_priority"))
    intervention_reason = _coerce_optional_text(summary.get("intervention_reason"))
    preferred_operator_action_hint = _coerce_optional_text(
        summary.get("preferred_operator_action_hint")
    )
    suggested_mode = _coerce_optional_text(summary.get("suggested_mode"))
    return {
        "intervention_status": intervention_status,
        "intervention_required": intervention_required,
        "intervention_priority": intervention_priority,
        "intervention_reason": intervention_reason,
        "preferred_operator_action_hint": preferred_operator_action_hint,
        "suggested_mode": suggested_mode,
    }

def _load_operator_intervention_state(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}

def persist_operator_intervention_state(summary: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_normalize_operator_intervention_snapshot(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def append_operator_intervention_transition_events(
    result: dict[str, Any],
    intervention_summary: dict[str, Any],
    final_guidance_summary: dict[str, Any],
    state_path: Path,
    events_path: Path,
    *,
    session_id: str,
) -> None:
    previous_state = _normalize_operator_intervention_snapshot(_load_operator_intervention_state(state_path))
    next_state = _normalize_operator_intervention_snapshot(intervention_summary)
    result = _coerce_optional_mapping(result)
    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
    if (
        not any(
            (
                next_state.get("intervention_status"),
                next_state.get("intervention_priority"),
                next_state.get("intervention_reason"),
                next_state.get("preferred_operator_action_hint"),
                next_state.get("suggested_mode"),
            )
        )
        and next_state.get("intervention_required") is None
    ):
        return

    loop_mode = result.get("mode") == "loop"
    loop_results = list(result.get("results") or []) if loop_mode else []
    last_result = (
        _coerce_optional_mapping(loop_results[-1]) if loop_results else result
    )
    previous_state_has_signal = any(value is not None for value in previous_state.values())
    if previous_state == next_state:
        persist_operator_intervention_state(next_state, state_path)
        return
    if not previous_state_has_signal:
        persist_operator_intervention_state(next_state, state_path)
        return

    if not previous_state.get("intervention_status") and next_state.get("intervention_status"):
        transition_kind = "status_initialized"
    elif previous_state.get("intervention_status") != next_state.get("intervention_status"):
        transition_kind = "status_changed"
    elif bool(previous_state.get("intervention_required")) != bool(next_state.get("intervention_required")):
        transition_kind = "required_flag_changed"
    elif previous_state.get("intervention_priority") != next_state.get("intervention_priority"):
        transition_kind = "priority_changed"
    else:
        transition_kind = "reason_changed"

    final_guidance_priority = _coerce_optional_text(final_guidance_summary.get("guidance_priority"))
    final_guidance_label = _coerce_optional_text(final_guidance_summary.get("guidance_label"))
    final_guidance_message = _coerce_optional_text(final_guidance_summary.get("guidance_message"))
    effective_mode = _coerce_optional_text(last_result.get("effective_mode"))
    task_payload = _normalize_task_payload(last_result.get("task"))

    event = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session_id": session_id,
        "transition_kind": transition_kind,
        "from_intervention_status": previous_state.get("intervention_status"),
        "to_intervention_status": next_state.get("intervention_status"),
        "from_intervention_required": bool(previous_state.get("intervention_required")),
        "to_intervention_required": bool(next_state.get("intervention_required")),
        "from_intervention_priority": previous_state.get("intervention_priority"),
        "to_intervention_priority": next_state.get("intervention_priority"),
        "from_intervention_reason": previous_state.get("intervention_reason"),
        "to_intervention_reason": next_state.get("intervention_reason"),
        "to_action_hint": next_state.get("preferred_operator_action_hint"),
        "to_suggested_mode": next_state.get("suggested_mode"),
        "to_final_guidance_label": final_guidance_label,
        "to_final_guidance_priority": final_guidance_priority,
        "to_final_guidance_message": final_guidance_message,
        "effective_mode": effective_mode,
        "task_url": task_payload.get("url"),
        "task_page": task_payload.get("page"),
    }
    persist_operator_intervention_state(next_state, state_path)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False))
        handle.write("\n")

__all__ = ('_normalize_recovery_policy_snapshot', '_load_recovery_policy_state', 'persist_recovery_policy_state', 'append_recovery_policy_transition_events', 'append_operator_escalation_events', '_normalize_operator_escalation_snapshot', '_load_operator_escalation_state', 'persist_operator_escalation_state', 'append_operator_escalation_recovery_events', '_normalize_operator_intervention_snapshot', '_load_operator_intervention_state', 'persist_operator_intervention_state', 'append_operator_intervention_transition_events')
