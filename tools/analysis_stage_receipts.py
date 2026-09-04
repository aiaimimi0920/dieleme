from __future__ import annotations

import json
from typing import Any

from tools.analysis_stage_policy import (
    MANUAL_REENTRY_READY_SIGNALS,
    _manual_review_queue_metadata,
    _receipt_validation_guidance,
)


def summarize_manual_review_receipt_snapshot(
    receipt_snapshot: dict[str, Any] | None,
    manual_review_backlog_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    receipt_snapshot = receipt_snapshot or {}
    manual_review_backlog_summary = manual_review_backlog_summary or {}
    receipts = list(receipt_snapshot.get("receipts") or [])
    top_human_actions = list(manual_review_backlog_summary.get("top_human_actions") or [])
    action_queues = dict(manual_review_backlog_summary.get("human_action_queues") or {})
    queue_open = bool(action_queues or top_human_actions)
    known_manual_actions = set(MANUAL_REENTRY_READY_SIGNALS)
    expected_ready_signals: set[str] = set()
    for action_name in top_human_actions:
        queue = dict(action_queues.get(action_name, {}) or _manual_review_queue_metadata(action_name))
        ready_signal = queue.get("reentry_ready_signal")
        if ready_signal:
            expected_ready_signals.add(str(ready_signal))

    matched_ready_signals: list[str] = []
    valid_receipt_count = 0
    top_receipt_status = None
    status_priority = {"reentered_auto_pipeline": 2, "ready_for_reentry": 1}
    best_status_rank = -1
    invalid_receipt_reasons: dict[str, int] = {}
    seen_ready_signals: set[str] = set()
    seen_action_payloads: set[tuple[str, str]] = set()
    for receipt in receipts:
        action_name = str(receipt.get("action") or "")
        action_recognized = action_name in known_manual_actions
        action_waiting = not top_human_actions or action_name in action_queues or action_name in top_human_actions
        action_known = action_recognized and action_waiting
        queue = dict(action_queues.get(action_name, {}) or _manual_review_queue_metadata(action_name))
        ready_signal = str(receipt.get("ready_signal") or "")
        status = str(receipt.get("status") or "")
        raw_payload = receipt.get("payload")
        payload_is_mapping = isinstance(raw_payload, dict)
        payload = dict(raw_payload or {}) if payload_is_mapping else {}
        payload_fingerprint = json.dumps(payload, ensure_ascii=False, sort_keys=True) if payload_is_mapping else ""
        required_fields = list(((queue.get("handoff_completion_payload") or {}).get("required_fields") or []))
        missing_required_fields = [
            field
            for field in required_fields
            if payload.get(field) in (None, "", [])
        ]
        ready_signal_expected = ready_signal and (not expected_ready_signals or ready_signal in expected_ready_signals)
        status_supported = status in {"ready_for_reentry", "reentered_auto_pipeline"}
        if not queue_open:
            closed_queue_reason = (
                "stale_receipt_for_recovered_item"
                if status == "reentered_auto_pipeline"
                else "late_receipt_for_closed_queue"
            )
            invalid_receipt_reasons[closed_queue_reason] = int(invalid_receipt_reasons.get(closed_queue_reason, 0) or 0) + 1
        elif action_recognized and not action_waiting:
            invalid_receipt_reasons["receipt_action_not_waiting"] = int(invalid_receipt_reasons.get("receipt_action_not_waiting", 0) or 0) + 1
        elif payload_is_mapping and (action_name, payload_fingerprint) in seen_action_payloads:
            invalid_receipt_reasons["duplicate_payload_for_same_action"] = int(invalid_receipt_reasons.get("duplicate_payload_for_same_action", 0) or 0) + 1
        elif ready_signal and ready_signal in seen_ready_signals:
            invalid_receipt_reasons["duplicate_ready_signal"] = int(invalid_receipt_reasons.get("duplicate_ready_signal", 0) or 0) + 1
        elif action_known and payload_is_mapping and status_supported and ready_signal_expected and not missing_required_fields:
            if ready_signal not in matched_ready_signals:
                matched_ready_signals.append(ready_signal)
            if ready_signal:
                seen_ready_signals.add(ready_signal)
            seen_action_payloads.add((action_name, payload_fingerprint))
            valid_receipt_count += 1
            rank = status_priority.get(status, 0)
            if rank > best_status_rank:
                best_status_rank = rank
                top_receipt_status = status or None
        elif not action_recognized:
            invalid_receipt_reasons["unknown_action"] = int(invalid_receipt_reasons.get("unknown_action", 0) or 0) + 1
        elif not payload_is_mapping:
            invalid_receipt_reasons["malformed_payload"] = int(invalid_receipt_reasons.get("malformed_payload", 0) or 0) + 1
        elif not status_supported:
            invalid_receipt_reasons["unsupported_receipt_status"] = int(invalid_receipt_reasons.get("unsupported_receipt_status", 0) or 0) + 1
        elif not ready_signal_expected:
            invalid_receipt_reasons["ready_signal_mismatch"] = int(invalid_receipt_reasons.get("ready_signal_mismatch", 0) or 0) + 1
        elif missing_required_fields:
            invalid_receipt_reasons["missing_required_fields"] = int(invalid_receipt_reasons.get("missing_required_fields", 0) or 0) + 1

    if top_receipt_status is None and invalid_receipt_reasons:
        top_receipt_status = "receipt_incomplete"
    top_invalid_receipt_reason = (
        sorted(invalid_receipt_reasons.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if invalid_receipt_reasons
        else None
    )
    top_receipt_fix_actions, receipt_validation_repair_hints = _receipt_validation_guidance(top_invalid_receipt_reason)

    return {
        "receipt_count": len(receipts),
        "valid_receipt_count": valid_receipt_count,
        "matched_ready_signals": matched_ready_signals,
        "top_matched_ready_signal": matched_ready_signals[0] if matched_ready_signals else None,
        "top_receipt_status": top_receipt_status,
        "invalid_receipt_count": sum(invalid_receipt_reasons.values()),
        "invalid_receipt_reasons": invalid_receipt_reasons,
        "top_invalid_receipt_reason": top_invalid_receipt_reason,
        "top_receipt_fix_actions": top_receipt_fix_actions,
        "receipt_validation_repair_hints": receipt_validation_repair_hints,
    }


def summarize_manual_review_reentry_application_summary(
    manual_review_receipt_summary: dict[str, Any] | None,
    action_feedback: dict[str, Any] | None,
    before_gap_report: dict[str, Any] | None,
    after_gap_report: dict[str, Any] | None,
    before_stage: dict[str, Any] | None,
    after_stage: dict[str, Any] | None,
) -> dict[str, Any]:
    manual_review_receipt_summary = manual_review_receipt_summary or {}
    action_feedback = action_feedback or {}
    before_gap_report = before_gap_report or {}
    after_gap_report = after_gap_report or {}
    before_stage = before_stage or {}
    after_stage = after_stage or {}

    ready_status = str(manual_review_receipt_summary.get("top_receipt_status") or "")
    matched_ready_signals = list(manual_review_receipt_summary.get("matched_ready_signals") or [])
    if ready_status != "ready_for_reentry" or not matched_ready_signals:
        return {
            "reentry_applied": False,
            "reentry_confirmed": False,
            "applied_ready_signals": [],
            "top_applied_ready_signal": None,
            "applied_actions": [],
            "top_applied_action": None,
            "confirmed_ready_signals": [],
            "top_confirmed_ready_signal": None,
            "missing_reduction_total": 0,
            "analysis_blocker_reduction_total": 0,
            "detail_enriched_delta": 0,
            "analysis_ready_delta": 0,
        }

    productive_actions = [
        action_name
        for action_name, feedback in action_feedback.items()
        if dict(feedback or {}).get("produced_work")
    ]
    before_missing = dict((before_gap_report.get("missing_field_counts") or {}) or {})
    after_missing = dict((after_gap_report.get("missing_field_counts") or {}) or {})
    missing_reduction_total = sum(
        max(0, int(before_missing.get(key, 0) or 0) - int(after_missing.get(key, 0) or 0))
        for key in set(before_missing) | set(after_missing)
    )
    before_blockers = dict((before_stage.get("analysis_blockers") or {}) or {})
    after_blockers = dict((after_stage.get("analysis_blockers") or {}) or {})
    blocker_reduction_total = sum(
        max(0, int(before_blockers.get(key, 0) or 0) - int(after_blockers.get(key, 0) or 0))
        for key in set(before_blockers) | set(after_blockers)
    )
    detail_enriched_delta = max(0, int(after_stage.get("detail_enriched", 0) or 0) - int(before_stage.get("detail_enriched", 0) or 0))
    analysis_ready_delta = max(0, int(after_stage.get("analysis_ready", 0) or 0) - int(before_stage.get("analysis_ready", 0) or 0))
    reentry_applied = bool(
        productive_actions
        or missing_reduction_total > 0
        or blocker_reduction_total > 0
        or detail_enriched_delta > 0
        or analysis_ready_delta > 0
    )
    reentry_confirmed = bool(
        missing_reduction_total > 0
        or blocker_reduction_total > 0
        or detail_enriched_delta > 0
        or analysis_ready_delta > 0
    )

    return {
        "reentry_applied": reentry_applied,
        "reentry_confirmed": reentry_confirmed,
        "applied_ready_signals": matched_ready_signals if reentry_applied else [],
        "top_applied_ready_signal": matched_ready_signals[0] if reentry_applied and matched_ready_signals else None,
        "applied_actions": productive_actions if reentry_applied else [],
        "top_applied_action": productive_actions[0] if reentry_applied and productive_actions else None,
        "confirmed_ready_signals": matched_ready_signals if reentry_confirmed else [],
        "top_confirmed_ready_signal": matched_ready_signals[0] if reentry_confirmed and matched_ready_signals else None,
        "missing_reduction_total": missing_reduction_total,
        "analysis_blocker_reduction_total": blocker_reduction_total,
        "detail_enriched_delta": detail_enriched_delta,
        "analysis_ready_delta": analysis_ready_delta,
    }


__all__ = ['summarize_manual_review_receipt_snapshot', 'summarize_manual_review_reentry_application_summary']
