from __future__ import annotations

from typing import Any

from tools.analysis_stage_policy import (
    _auto_retry_policy_for_handoff_mode,
    _handoff_lifecycle_state_for_mode,
    _manual_review_queue_metadata,
    _receipt_validation_guidance,
)


def summarize_action_effectiveness_snapshot(action_effectiveness: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = dict(action_effectiveness or {})
    low_yield_rows: list[tuple[str, int, int]] = []
    productive_rows: list[tuple[str, int]] = []
    for action_name, stats in snapshot.items():
        executed_rounds = int((stats or {}).get("executed_rounds", 0) or 0)
        productive_rounds = int((stats or {}).get("productive_rounds", 0) or 0)
        if executed_rounds > 0 and productive_rounds <= 0:
            low_yield_rows.append((action_name, executed_rounds, productive_rounds))
        if productive_rounds > 0:
            productive_rows.append((action_name, productive_rounds))
    low_yield_rows.sort(key=lambda item: (-item[1], item[0]))
    productive_rows.sort(key=lambda item: (-item[1], item[0]))
    low_yield_actions = [name for name, _, _ in low_yield_rows]
    productive_actions = [name for name, _ in productive_rows]
    return {
        "action_count": len(snapshot),
        "low_yield_actions": low_yield_actions,
        "productive_actions": productive_actions,
        "top_low_yield_action": low_yield_actions[0] if low_yield_actions else None,
        "top_productive_action": productive_actions[0] if productive_actions else None,
        "top_low_yield_actions": low_yield_actions[:3],
        "top_productive_actions": productive_actions[:3],
        "snapshot": snapshot,
    }


def summarize_operator_action_surface(
    recommended_actions: dict[str, Any] | None,
    action_effectiveness_summary: dict[str, Any] | None = None,
    recoverability_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recommended_actions = recommended_actions or {}
    action_effectiveness_summary = action_effectiveness_summary or {}
    recoverability_summary = recoverability_summary or {}
    operator_summary = dict(recommended_actions.get("operator_summary", {}) or {})
    feedback_hints = list(operator_summary.get("feedback_hints") or [])
    top_manual_review_reason = None
    for hint in feedback_hints:
        if "manual_review" in hint or "historical_unrecoverable" in hint:
            top_manual_review_reason = hint
            break
    if top_manual_review_reason is None and recoverability_summary.get("top_manual_review_reason"):
        top_manual_review_reason = recoverability_summary.get("top_manual_review_reason")
    manual_review_candidates = list(
        operator_summary.get("manual_review_candidates")
        or (["manual_review"] if operator_summary.get("manual_review_candidate") else [])
    )
    return {
        "primary_action": operator_summary.get("primary_action"),
        "top_alternative_actions": list(operator_summary.get("top_alternative_actions") or operator_summary.get("next_best_alternative_actions") or [])[:3],
        "deprioritized_actions": list(operator_summary.get("deprioritized_actions") or []),
        "feedback_hints": feedback_hints,
        "manual_review_candidates": manual_review_candidates,
        "manual_review_required": bool(manual_review_candidates or top_manual_review_reason),
        "top_low_yield_actions": list(action_effectiveness_summary.get("top_low_yield_actions") or []),
        "top_productive_actions": list(action_effectiveness_summary.get("top_productive_actions") or []),
        "recoverability_summary": recoverability_summary,
        "top_manual_review_reason": top_manual_review_reason,
    }


def summarize_operator_overview(
    operator_action_summary: dict[str, Any] | None,
    scheduler_feedback_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    operator_action_summary = operator_action_summary or {}
    scheduler_feedback_summary = scheduler_feedback_summary or {}
    recoverability_summary = dict(operator_action_summary.get("recoverability_summary", {}) or {})
    manual_review_backlog_summary = dict(operator_action_summary.get("manual_review_backlog_summary", {}) or {})
    manual_review_receipt_summary = dict(operator_action_summary.get("manual_review_receipt_summary", {}) or {})
    manual_review_reentry_application_summary = dict(operator_action_summary.get("manual_review_reentry_application_summary", {}) or {})
    top_human_actions = list(manual_review_backlog_summary.get("top_human_actions") or [])
    top_human_action_instructions = list(manual_review_backlog_summary.get("top_human_action_instructions") or [])
    top_human_reentry_paths = list(manual_review_backlog_summary.get("top_human_reentry_paths") or [])
    manual_review_required = bool(operator_action_summary.get("manual_review_required"))
    future_fixable = int(recoverability_summary.get("future_fixable", 0) or 0)
    receipt_status = str(manual_review_receipt_summary.get("top_receipt_status") or "")
    top_invalid_receipt_reason = manual_review_receipt_summary.get("top_invalid_receipt_reason")
    top_receipt_fix_actions = list(manual_review_receipt_summary.get("top_receipt_fix_actions") or [])
    receipt_validation_repair_hints = list(manual_review_receipt_summary.get("receipt_validation_repair_hints") or [])
    if not top_receipt_fix_actions and top_invalid_receipt_reason:
        top_receipt_fix_actions, receipt_validation_repair_hints = _receipt_validation_guidance(str(top_invalid_receipt_reason))
    elif not top_receipt_fix_actions:
        top_receipt_fix_actions = list(scheduler_feedback_summary.get("top_receipt_fix_actions") or [])
        receipt_validation_repair_hints = list(scheduler_feedback_summary.get("receipt_validation_repair_hints") or [])
    if receipt_status == "reentered_auto_pipeline":
        handoff_mode = "auto_continue"
        handoff_lifecycle_state = "reentered_auto_pipeline"
    elif manual_review_reentry_application_summary.get("reentry_confirmed"):
        handoff_mode = "auto_continue"
        handoff_lifecycle_state = "reentry_confirmed"
    elif manual_review_reentry_application_summary.get("reentry_applied"):
        handoff_mode = "auto_continue"
        handoff_lifecycle_state = "reentry_applied"
    elif receipt_status == "ready_for_reentry":
        handoff_mode = "auto_continue"
        handoff_lifecycle_state = "receipt_ready_for_reentry"
    elif receipt_status == "receipt_incomplete":
        handoff_mode = "manual_required_retryable" if future_fixable > 0 else "manual_required_hard_stop"
        handoff_lifecycle_state = "awaiting_valid_receipt"
    elif manual_review_required:
        handoff_mode = "manual_required_retryable" if future_fixable > 0 else "manual_required_hard_stop"
        handoff_lifecycle_state = _handoff_lifecycle_state_for_mode(handoff_mode)
    elif operator_action_summary.get("primary_action") or recoverability_summary.get("top_recoverable_actions"):
        handoff_mode = "auto_continue"
        handoff_lifecycle_state = _handoff_lifecycle_state_for_mode(handoff_mode)
    else:
        handoff_mode = "observe_only"
        handoff_lifecycle_state = _handoff_lifecycle_state_for_mode(handoff_mode)
    auto_retry_policy = _auto_retry_policy_for_handoff_mode(handoff_mode)
    top_queue_action = top_human_actions[0] if top_human_actions else None
    top_queue = None
    if top_queue_action:
        top_queue = dict((manual_review_backlog_summary.get("human_action_queues") or {}).get(top_queue_action, {}) or {})
        queue_defaults = _manual_review_queue_metadata(top_queue_action)
        queue_defaults["instruction"] = (
            top_human_action_instructions[0]
            if top_human_action_instructions
            else queue_defaults["instruction"]
        )
        queue_defaults["expected_reentry_path"] = (
            top_human_reentry_paths[0]
            if top_human_reentry_paths
            else queue_defaults["expected_reentry_path"]
        )
        for key, value in queue_defaults.items():
            top_queue.setdefault(key, value)
        top_queue.setdefault("count", int((manual_review_backlog_summary.get("reason_buckets") or {}).get(top_queue_action, 0) or 0))
        sample_summaries = list(top_queue.get("sample_summaries") or [])
        if not sample_summaries:
            backlog_sample_summaries = list(manual_review_backlog_summary.get("sample_summaries") or [])
            if backlog_sample_summaries:
                sample_summaries = backlog_sample_summaries
            else:
                sample_item_ids = list(manual_review_backlog_summary.get("sample_item_ids") or [])
                sample_titles = list(manual_review_backlog_summary.get("sample_titles") or [])
                sample_summaries = [
                    {"item_id": item_id, "title": sample_titles[index] if index < len(sample_titles) else None}
                    for index, item_id in enumerate(sample_item_ids)
                ]
        top_queue.setdefault(
            "sample_summaries",
            sample_summaries,
        )
        top_queue = {"action": top_queue_action, **top_queue}
    pending_ready_signals = []
    if top_queue_action:
        ready_signal = (top_queue or {}).get("reentry_ready_signal")
        if ready_signal:
            pending_ready_signals.append(str(ready_signal))
    matched_ready_signals = list(manual_review_receipt_summary.get("matched_ready_signals") or [])
    top_matched_ready_signal = manual_review_receipt_summary.get("top_matched_ready_signal")
    applied_ready_signals = list(manual_review_reentry_application_summary.get("applied_ready_signals") or [])
    top_applied_ready_signal = manual_review_reentry_application_summary.get("top_applied_ready_signal")
    top_applied_action = manual_review_reentry_application_summary.get("top_applied_action")
    confirmed_ready_signals = list(manual_review_reentry_application_summary.get("confirmed_ready_signals") or [])
    top_confirmed_ready_signal = manual_review_reentry_application_summary.get("top_confirmed_ready_signal")
    handoff_waiting_for_human_receipt = (
        handoff_lifecycle_state.startswith("awaiting_human_receipt")
        or handoff_lifecycle_state == "awaiting_valid_receipt"
    )
    scheduler_pause_recommended = handoff_waiting_for_human_receipt or bool(auto_retry_policy.get("should_pause_scheduler"))
    resume_on_ready_signal = top_applied_ready_signal or top_matched_ready_signal or (pending_ready_signals[0] if pending_ready_signals else scheduler_feedback_summary.get("top_pending_ready_signal"))
    resume_action = (top_queue or {}).get("expected_reentry_path") if top_queue else None
    should_resume_automation = handoff_lifecycle_state in {
        "receipt_ready_for_reentry",
        "reentry_applied",
        "reentry_confirmed",
        "reentered_auto_pipeline",
        "auto_pipeline_active",
    }
    return {
        "primary_action": operator_action_summary.get("primary_action"),
        "handoff_mode": handoff_mode,
        "handoff_lifecycle_state": handoff_lifecycle_state,
        "auto_retry_policy": auto_retry_policy,
        "handoff_waiting_for_human_receipt": handoff_waiting_for_human_receipt,
        "scheduler_pause_recommended": scheduler_pause_recommended,
        "resume_on_ready_signal": resume_on_ready_signal,
        "resume_action": resume_action,
        "should_resume_automation": should_resume_automation,
        "matched_ready_signals": matched_ready_signals,
        "top_matched_ready_signal": top_matched_ready_signal,
        "reentry_applied": bool(manual_review_reentry_application_summary.get("reentry_applied")),
        "applied_ready_signals": applied_ready_signals,
        "top_applied_ready_signal": top_applied_ready_signal,
        "top_applied_action": top_applied_action,
        "reentry_confirmed": bool(manual_review_reentry_application_summary.get("reentry_confirmed")),
        "confirmed_ready_signals": confirmed_ready_signals,
        "top_confirmed_ready_signal": top_confirmed_ready_signal,
        "invalid_receipt_count": int(manual_review_receipt_summary.get("invalid_receipt_count", 0) or 0),
        "top_invalid_receipt_reason": top_invalid_receipt_reason,
        "top_receipt_fix_actions": top_receipt_fix_actions,
        "receipt_validation_repair_hints": receipt_validation_repair_hints,
        "manual_review_required": manual_review_required,
        "top_manual_review_reason": operator_action_summary.get("top_manual_review_reason"),
        "manual_review_candidate_rounds": int(scheduler_feedback_summary.get("manual_review_candidate_rounds", 0) or 0),
        "handoff_mode_counts": dict(scheduler_feedback_summary.get("handoff_mode_counts", {}) or {}),
        "top_handoff_mode": scheduler_feedback_summary.get("top_handoff_mode"),
        "handoff_lifecycle_counts": dict(scheduler_feedback_summary.get("handoff_lifecycle_counts", {}) or {}),
        "top_handoff_lifecycle_state": scheduler_feedback_summary.get("top_handoff_lifecycle_state"),
        "pending_ready_signal_counts": dict(scheduler_feedback_summary.get("pending_ready_signal_counts", {}) or {}),
        "top_pending_ready_signal": top_matched_ready_signal or (pending_ready_signals[0] if pending_ready_signals else scheduler_feedback_summary.get("top_pending_ready_signal")),
        "pending_ready_signals": pending_ready_signals,
        "top_fallback_routes": list(scheduler_feedback_summary.get("top_fallback_routes") or []),
        "top_recoverable_actions": list(recoverability_summary.get("top_recoverable_actions") or []),
        "top_human_actions": top_human_actions,
        "top_human_action_instructions": top_human_action_instructions,
        "top_human_reentry_paths": top_human_reentry_paths,
        "top_human_action_queue": top_queue,
        "manual_review_sample_item_ids": list(manual_review_backlog_summary.get("sample_item_ids") or []),
        "future_fixable": future_fixable,
        "historical_unrecoverable": int(recoverability_summary.get("historical_unrecoverable", 0) or 0),
        "top_low_yield_actions": list(operator_action_summary.get("top_low_yield_actions") or []),
        "top_alternative_actions": list(operator_action_summary.get("top_alternative_actions") or []),
    }


def summarize_action_feedback(
    recommended_actions: dict[str, Any] | None,
    report_sections: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    recommended_actions = recommended_actions or {}
    report_sections = report_sections or {}
    action_specs = {
        "detail_archive_fetch": {
            "recommended_flag": "fetch_archives",
            "productive_key": "fetched_count",
        },
        "archived_detail_backfill": {
            "recommended_flag": "run_archived_backfill",
            "productive_key": "updated_records",
        },
        "recent_coordinate_backfill": {
            "recommended_flag": "run_coordinate_backfill",
            "productive_key": "updated_count",
        },
        "detail_replay_preparation": {
            "recommended_flag": "prepare_replay",
            "productive_key": "prepared_count",
        },
        "analysis_ready_recheck": {
            "recommended_flag": "suggest_analysis_ready_recheck",
            "productive_key": "updated_count",
        },
        "stage_state_reconcile": {
            "recommended_flag": "suggest_stage_state_reconcile",
            "productive_key": "updated_count",
        },
    }

    output: dict[str, dict[str, Any]] = {}
    for action_name, spec in action_specs.items():
        section = dict(report_sections.get(action_name, {}) or {})
        productive_key = spec["productive_key"]
        skipped = bool(section.get("skipped"))
        executed = bool(section) and not skipped
        productive_count = int(section.get(productive_key, 0) or 0)
        output[action_name] = {
            "recommended": bool(recommended_actions.get(spec["recommended_flag"])),
            "executed": executed,
            "produced_work": productive_count > 0,
            "productive_count": productive_count,
            "metrics": section,
        }
    return output


__all__ = ['summarize_action_effectiveness_snapshot', 'summarize_operator_action_surface', 'summarize_operator_overview', 'summarize_action_feedback']
