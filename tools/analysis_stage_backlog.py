from __future__ import annotations

from typing import Any

from tools.analysis_stage_policy import (
    MANUAL_REVIEW_ACTION_INSTRUCTIONS,
    MANUAL_REVIEW_REASON_PRIORITY,
    MANUAL_REVIEW_REENTRY_PATHS,
    _manual_review_queue_metadata,
    _receipt_validation_guidance,
)


def summarize_recoverability_snapshot(gap_report: dict[str, Any] | None) -> dict[str, Any]:
    gap_report = gap_report or {}
    counts = dict(gap_report.get("recoverability_counts", {}) or {})
    action_candidates = [
        ("infer_location", int(counts.get("coordinate_infer_candidate", 0) or 0)),
        ("archived_detail_backfill", int(counts.get("archive_backfill_candidate", 0) or 0)),
        ("prepare_replay", int(counts.get("replay_candidate", 0) or 0)),
    ]
    action_candidates = [item for item in action_candidates if item[1] > 0]
    action_candidates.sort(key=lambda item: (-item[1], item[0]))
    future_fixable = int(counts.get("future_fixable", 0) or 0)
    historical_unrecoverable = int(counts.get("historical_unrecoverable", 0) or 0)
    return {
        "future_fixable": future_fixable,
        "historical_unrecoverable": historical_unrecoverable,
        "archive_backfill_candidate": int(counts.get("archive_backfill_candidate", 0) or 0),
        "replay_candidate": int(counts.get("replay_candidate", 0) or 0),
        "coordinate_infer_candidate": int(counts.get("coordinate_infer_candidate", 0) or 0),
        "top_recoverable_actions": [name for name, _count in action_candidates[:3]],
        "top_manual_review_reason": "historical_unrecoverable_gap" if historical_unrecoverable > 0 and future_fixable <= 0 else None,
    }


def summarize_manual_review_backlog(
    gap_report: dict[str, Any] | None,
    *,
    limit: int = 5,
) -> dict[str, Any]:
    gap_report = gap_report or {}
    counts = dict(gap_report.get("recoverability_counts", {}) or {})
    samples = list(gap_report.get("samples") or [])
    backlog_samples = [sample for sample in samples if sample.get("historical_unrecoverable")]
    trimmed = backlog_samples[:limit]
    reason_buckets: dict[str, int] = {}
    reason_priority = {
        "manual_location_review": 0,
        "manual_detail_capture_review": 1,
        "manual_price_anchor_review": 2,
        "manual_risk_review": 3,
        "manual_area_review": 4,
        "manual_status_review": 5,
    }

    def _bump(reason: str) -> None:
        reason_buckets[reason] = int(reason_buckets.get(reason, 0) or 0) + 1

    human_action_queues: dict[str, dict[str, Any]] = {}

    def _queue(reason: str, sample: dict[str, Any]) -> None:
        queue = human_action_queues.setdefault(
            reason,
            {
                "count": 0,
                **_manual_review_queue_metadata(reason),
                "sample_item_ids": [],
                "sample_titles": [],
                "sample_summaries": [],
            },
        )
        queue["count"] = int(queue.get("count", 0) or 0) + 1
        item_id = sample.get("item_id")
        if item_id not in (None, "") and len(queue["sample_item_ids"]) < limit:
            queue["sample_item_ids"].append(str(item_id))
        title = sample.get("title")
        if title not in (None, "") and len(queue["sample_titles"]) < limit:
            queue["sample_titles"].append(str(title))
        if len(queue["sample_summaries"]) < limit:
            queue["sample_summaries"].append(
                {
                    "item_id": sample.get("item_id"),
                    "title": sample.get("title"),
                    "missing_fields": list(sample.get("missing_fields") or []),
                    "analysis_missing_fields": list(sample.get("analysis_missing_fields") or []),
                }
            )

    for sample in backlog_samples:
        analysis_missing = set(str(item) for item in (sample.get("analysis_missing_fields") or []))
        missing_fields = set(str(item) for item in (sample.get("missing_fields") or []))
        location_review_needed = False
        if "detail_stage" in analysis_missing:
            _bump("manual_detail_capture_review")
            _queue("manual_detail_capture_review", sample)
        if "price_anchor" in analysis_missing:
            _bump("manual_price_anchor_review")
            _queue("manual_price_anchor_review", sample)
        if (
            "location_precision" in analysis_missing
            or "city" in analysis_missing
            or "district" in analysis_missing
            or "business_area" in analysis_missing
            or "latitude" in missing_fields
            or "longitude" in missing_fields
        ):
            location_review_needed = True
        if "area_sqm" in analysis_missing:
            _bump("manual_area_review")
            _queue("manual_area_review", sample)
        if "status" in analysis_missing:
            _bump("manual_status_review")
            _queue("manual_status_review", sample)
        if {"is_occupied", "has_long_lease", "clear_delivery", "tax_burden", "is_fractional_share"} & missing_fields:
            _bump("manual_risk_review")
            _queue("manual_risk_review", sample)
        if sample.get("historical_unrecoverable"):
            location_review_needed = True
        if location_review_needed:
            _bump("manual_location_review")
            _queue("manual_location_review", sample)

    sorted_reasons = sorted(
        reason_buckets.items(),
        key=lambda item: (-item[1], MANUAL_REVIEW_REASON_PRIORITY.get(item[0], 99), item[0]),
    )
    return {
        "candidate_count": int(counts.get("historical_unrecoverable", 0) or 0),
        "sample_item_ids": [str(sample.get("item_id") or "") for sample in trimmed if sample.get("item_id") not in (None, "")],
        "sample_titles": [str(sample.get("title") or "") for sample in trimmed if sample.get("title") not in (None, "")],
        "reason_buckets": reason_buckets,
        "top_human_actions": [name for name, _count in sorted_reasons[:3]],
        "top_human_action_instructions": [MANUAL_REVIEW_ACTION_INSTRUCTIONS.get(name, "") for name, _count in sorted_reasons[:3]],
        "top_human_reentry_paths": [MANUAL_REVIEW_REENTRY_PATHS.get(name) for name, _count in sorted_reasons[:3]],
        "human_action_queues": human_action_queues,
        "sample_summaries": [
            {
                "item_id": sample.get("item_id"),
                "title": sample.get("title"),
                "missing_fields": list(sample.get("missing_fields") or []),
                "analysis_missing_fields": list(sample.get("analysis_missing_fields") or []),
            }
            for sample in trimmed
        ],
    }


def summarize_scheduler_feedback_snapshot(total_progress: dict[str, Any] | None) -> dict[str, Any]:
    total_progress = total_progress or {}
    fallback_usage = dict(total_progress.get("fallback_usage", {}) or {})
    handoff_mode_counts = dict(total_progress.get("handoff_mode_counts", {}) or {})
    handoff_lifecycle_counts = dict(total_progress.get("handoff_lifecycle_counts", {}) or {})
    human_action_counts = dict(total_progress.get("human_action_counts", {}) or {})
    retry_policy_counts = dict(total_progress.get("retry_policy_counts", {}) or {})
    pending_ready_signal_counts = dict(total_progress.get("pending_ready_signal_counts", {}) or {})
    matched_ready_signal_counts = dict(total_progress.get("matched_ready_signal_counts", {}) or {})
    invalid_receipt_reason_counts = dict(total_progress.get("invalid_receipt_reason_counts", {}) or {})
    confirmed_ready_signal_counts = dict(total_progress.get("confirmed_ready_signal_counts", {}) or {})
    manual_review_candidate_rounds = int(total_progress.get("manual_review_candidate_rounds", 0) or 0)
    if not handoff_mode_counts and manual_review_candidate_rounds > 0:
        handoff_mode_counts["manual_required_hard_stop"] = manual_review_candidate_rounds
    if not handoff_lifecycle_counts and manual_review_candidate_rounds > 0:
        handoff_lifecycle_counts["awaiting_human_receipt_hard_stop"] = manual_review_candidate_rounds
    flattened_fallbacks: list[tuple[str, int]] = []
    for source_action, targets in fallback_usage.items():
        for target_action, count in dict(targets or {}).items():
            flattened_fallbacks.append((f"{source_action}->{target_action}", int(count or 0)))
    flattened_fallbacks.sort(key=lambda item: (-item[1], item[0]))
    top_handoff_mode = total_progress.get("top_handoff_mode")
    if top_handoff_mode is None and handoff_mode_counts:
        top_handoff_mode = sorted(handoff_mode_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_human_actions = total_progress.get("top_human_actions")
    if top_human_actions is None and human_action_counts:
        top_human_actions = [
            name
            for name, _count in sorted(
                human_action_counts.items(),
                key=lambda item: (-int(item[1] or 0), MANUAL_REVIEW_REASON_PRIORITY.get(item[0], 99), item[0]),
            )[:3]
        ]
    top_retry_policy = total_progress.get("top_retry_policy")
    if top_retry_policy is None and retry_policy_counts:
        top_retry_policy = sorted(retry_policy_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_handoff_lifecycle_state = total_progress.get("top_handoff_lifecycle_state")
    if top_handoff_lifecycle_state is None and handoff_lifecycle_counts:
        top_handoff_lifecycle_state = sorted(handoff_lifecycle_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_pending_ready_signal = total_progress.get("top_pending_ready_signal")
    if top_pending_ready_signal is None and pending_ready_signal_counts:
        top_pending_ready_signal = sorted(pending_ready_signal_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_matched_ready_signal = total_progress.get("top_matched_ready_signal")
    if top_matched_ready_signal is None and matched_ready_signal_counts:
        top_matched_ready_signal = sorted(matched_ready_signal_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_invalid_receipt_reason = total_progress.get("top_invalid_receipt_reason")
    if top_invalid_receipt_reason is None and invalid_receipt_reason_counts:
        top_invalid_receipt_reason = sorted(invalid_receipt_reason_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_receipt_fix_actions, receipt_validation_repair_hints = _receipt_validation_guidance(top_invalid_receipt_reason)
    top_reentry_confirmed_signal = total_progress.get("top_reentry_confirmed_signal")
    if top_reentry_confirmed_signal is None and confirmed_ready_signal_counts:
        top_reentry_confirmed_signal = sorted(confirmed_ready_signal_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return {
        "manual_review_candidate_rounds": manual_review_candidate_rounds,
        "manual_review_reasons": dict(total_progress.get("manual_review_reasons", {}) or {}),
        "top_manual_review_reason": total_progress.get("top_manual_review_reason"),
        "fallback_usage": fallback_usage,
        "top_fallback_routes": [name for name, _count in flattened_fallbacks[:3]],
        "human_action_counts": human_action_counts,
        "top_human_actions": list(top_human_actions or []),
        "retry_policy_counts": retry_policy_counts,
        "top_retry_policy": top_retry_policy,
        "handoff_mode_counts": handoff_mode_counts,
        "top_handoff_mode": top_handoff_mode,
        "handoff_lifecycle_counts": handoff_lifecycle_counts,
        "top_handoff_lifecycle_state": top_handoff_lifecycle_state,
        "pending_ready_signal_counts": pending_ready_signal_counts,
        "top_pending_ready_signal": top_pending_ready_signal,
        "matched_ready_signal_counts": matched_ready_signal_counts,
        "top_matched_ready_signal": top_matched_ready_signal,
        "invalid_receipt_reason_counts": invalid_receipt_reason_counts,
        "top_invalid_receipt_reason": top_invalid_receipt_reason,
        "top_receipt_fix_actions": top_receipt_fix_actions,
        "receipt_validation_repair_hints": receipt_validation_repair_hints,
        "reentry_confirmed_rounds": int(total_progress.get("reentry_confirmed_rounds", 0) or 0),
        "confirmed_ready_signal_counts": confirmed_ready_signal_counts,
        "top_reentry_confirmed_signal": top_reentry_confirmed_signal,
    }


__all__ = ['summarize_recoverability_snapshot', 'summarize_manual_review_backlog', 'summarize_scheduler_feedback_snapshot']
