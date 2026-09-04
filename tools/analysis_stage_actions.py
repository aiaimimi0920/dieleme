from __future__ import annotations

from typing import Any


def recommend_analysis_stage_actions(
    stage_snapshot: dict[str, Any] | None,
    *,
    gap_report: dict[str, Any] | None = None,
    action_effectiveness: dict[str, Any] | None = None,
    manual_review_receipt_summary: dict[str, Any] | None = None,
    fetch_archives: bool = False,
    prepare_replay: bool = False,
) -> dict[str, Any]:
    blockers = dict((stage_snapshot or {}).get("analysis_blockers", {}) or {})
    gap_report = gap_report or {}
    action_effectiveness = action_effectiveness or {}
    manual_review_receipt_summary = manual_review_receipt_summary or {}
    missing_field_counts = dict(gap_report.get("missing_field_counts", {}) or {})
    detail_stage_blockers = int(blockers.get("detail_stage", 0) or 0)
    price_anchor_blockers = int(blockers.get("price_anchor", 0) or 0)
    location_precision_blockers = int(blockers.get("location_precision", 0) or 0)
    business_area_blockers = int(blockers.get("business_area", 0) or 0)
    location_blockers = location_precision_blockers + business_area_blockers
    detail_archive_present_count = int(gap_report.get("detail_archive_present_count", 0) or 0)
    recoverability_counts = dict(gap_report.get("recoverability_counts", {}) or {})
    has_recoverability = bool(recoverability_counts)
    coordinate_missing = int(missing_field_counts.get("latitude", 0) or 0) + int(missing_field_counts.get("longitude", 0) or 0)
    matched_ready_signals = set(str(item) for item in (manual_review_receipt_summary.get("matched_ready_signals") or []))
    receipt_status = str(manual_review_receipt_summary.get("top_receipt_status") or "")
    receipt_location_ready = receipt_status in {"ready_for_reentry", "reentered_auto_pipeline"} and "location_artifacts_complete" in matched_ready_signals
    receipt_detail_ready = receipt_status in {"ready_for_reentry", "reentered_auto_pipeline"} and "detail_artifacts_complete" in matched_ready_signals
    receipt_risk_ready = receipt_status in {"ready_for_reentry", "reentered_auto_pipeline"} and "risk_facts_complete" in matched_ready_signals
    receipt_price_ready = receipt_status in {"ready_for_reentry", "reentered_auto_pipeline"} and "price_anchor_complete" in matched_ready_signals
    receipt_area_ready = receipt_status in {"ready_for_reentry", "reentered_auto_pipeline"} and "area_facts_complete" in matched_ready_signals
    receipt_status_ready = receipt_status in {"ready_for_reentry", "reentered_auto_pipeline"} and "status_reconciled" in matched_ready_signals
    future_fixable_count = int(recoverability_counts.get("future_fixable", 0) or 0)
    historical_unrecoverable_count = int(recoverability_counts.get("historical_unrecoverable", 0) or 0)
    archive_backfill_candidate_count = int(recoverability_counts.get("archive_backfill_candidate", 0) or 0)
    replay_candidate_count = int(recoverability_counts.get("replay_candidate", 0) or 0)
    coordinate_infer_candidate_count = int(recoverability_counts.get("coordinate_infer_candidate", 0) or 0)
    risk_missing = sum(
        int(missing_field_counts.get(key, 0) or 0)
        for key in ("is_occupied", "has_long_lease", "clear_delivery", "tax_burden", "is_fractional_share")
    )
    archived_effect = dict(action_effectiveness.get("archived_detail_backfill", {}) or {})
    fetch_effect = dict(action_effectiveness.get("detail_archive_fetch", {}) or {})
    replay_effect = dict(action_effectiveness.get("detail_replay_preparation", {}) or {})
    coordinate_effect = dict(action_effectiveness.get("recent_coordinate_backfill", {}) or {})
    archived_low_yield = (
        int(archived_effect.get("executed_rounds", 0) or 0) >= 2
        and int(archived_effect.get("productive_rounds", 0) or 0) <= 0
    )
    fetch_low_yield = (
        int(fetch_effect.get("executed_rounds", 0) or 0) >= 2
        and int(fetch_effect.get("productive_rounds", 0) or 0) <= 0
    )
    replay_low_yield = (
        int(replay_effect.get("executed_rounds", 0) or 0) >= 2
        and int(replay_effect.get("productive_rounds", 0) or 0) <= 0
    )
    coordinate_low_yield = (
        int(coordinate_effect.get("executed_rounds", 0) or 0) >= 2
        and int(coordinate_effect.get("productive_rounds", 0) or 0) <= 0
    )

    planned_fetch_archives = bool(fetch_archives or detail_stage_blockers > 0 or price_anchor_blockers > 0)
    planned_prepare_replay = bool(prepare_replay or detail_stage_blockers > 0)
    coordinate_focus = location_blockers > 0 or coordinate_missing > 0
    suggest_infer_location = location_blockers > 0
    run_archived_backfill = bool(detail_archive_present_count > 0 and (coordinate_missing > 0 or risk_missing > 0 or detail_stage_blockers > 0 or price_anchor_blockers > 0))
    run_coordinate_backfill = coordinate_focus and not coordinate_low_yield
    suggest_extract_risk = risk_missing > 0
    suggest_analysis_ready_recheck = False
    suggest_stage_state_reconcile = False
    deprioritized_actions: list[str] = []
    deprioritized_reason_map: dict[str, str] = {}
    feedback_hints: list[str] = []
    fallback_routes: dict[str, str] = {}
    manual_review_candidate = False
    if archived_low_yield:
        run_archived_backfill = False
        deprioritized_actions.append("archived_detail_backfill")
        deprioritized_reason_map["archived_detail_backfill"] = "archived_detail_backfill_low_yield"
        feedback_hints.append("archived_detail_backfill_low_yield")
        if suggest_extract_risk:
            fallback_routes["archived_detail_backfill"] = "extract_risk"
    if fetch_low_yield and not fetch_archives:
        planned_fetch_archives = False
        deprioritized_actions.append("fetch_archives")
        deprioritized_reason_map["fetch_archives"] = "detail_archive_fetch_low_yield"
        feedback_hints.append("detail_archive_fetch_low_yield")
        if detail_stage_blockers > 0:
            fallback_routes["fetch_archives"] = "prepare_replay"
    if replay_low_yield and not prepare_replay:
        planned_prepare_replay = False
        deprioritized_actions.append("prepare_replay")
        deprioritized_reason_map["prepare_replay"] = "detail_replay_preparation_low_yield"
        feedback_hints.append("detail_replay_preparation_low_yield")
        fallback_routes["prepare_replay"] = "manual_review"
        manual_review_candidate = True
    if coordinate_low_yield:
        deprioritized_actions.append("coordinate_backfill")
        deprioritized_reason_map["coordinate_backfill"] = "coordinate_backfill_low_yield"
        feedback_hints.append("coordinate_backfill_low_yield")
        suggest_infer_location = True
        fallback_routes["coordinate_backfill"] = "infer_location"

    if receipt_detail_ready:
        planned_prepare_replay = True
        if "manual_receipt_detail_ready" not in feedback_hints:
            feedback_hints.append("manual_receipt_detail_ready")
    if receipt_location_ready:
        coordinate_focus = True
        run_coordinate_backfill = True
        suggest_infer_location = True
        if "manual_receipt_location_ready" not in feedback_hints:
            feedback_hints.append("manual_receipt_location_ready")
    if receipt_risk_ready:
        suggest_extract_risk = True
        if "manual_receipt_risk_ready" not in feedback_hints:
            feedback_hints.append("manual_receipt_risk_ready")
    if receipt_price_ready:
        suggest_analysis_ready_recheck = True
        if "manual_receipt_price_ready" not in feedback_hints:
            feedback_hints.append("manual_receipt_price_ready")
    if receipt_area_ready:
        suggest_analysis_ready_recheck = True
        if "manual_receipt_area_ready" not in feedback_hints:
            feedback_hints.append("manual_receipt_area_ready")
    if receipt_status_ready:
        suggest_stage_state_reconcile = True
        if "manual_receipt_status_ready" not in feedback_hints:
            feedback_hints.append("manual_receipt_status_ready")

    if has_recoverability and run_archived_backfill and archive_backfill_candidate_count <= 0:
        run_archived_backfill = False
        deprioritized_actions.append("archived_detail_backfill")
        deprioritized_reason_map["archived_detail_backfill"] = "no_archive_backfill_candidate"
        feedback_hints.append("no_archive_backfill_candidate")

    if has_recoverability and planned_prepare_replay and replay_candidate_count <= 0 and historical_unrecoverable_count > 0 and not prepare_replay and not receipt_detail_ready:
        planned_prepare_replay = False
        deprioritized_actions.append("prepare_replay")
        deprioritized_reason_map["prepare_replay"] = "no_replay_candidate"
        feedback_hints.append("no_replay_candidate")

    if has_recoverability and planned_fetch_archives and replay_candidate_count <= 0 and detail_archive_present_count <= 0 and historical_unrecoverable_count > 0 and not fetch_archives:
        planned_fetch_archives = False
        deprioritized_actions.append("fetch_archives")
        deprioritized_reason_map["fetch_archives"] = "no_recoverable_detail_source"
        feedback_hints.append("no_recoverable_detail_source")

    if has_recoverability and run_coordinate_backfill and coordinate_infer_candidate_count <= 0 and coordinate_missing > 0 and not receipt_location_ready:
        run_coordinate_backfill = False
        deprioritized_actions.append("coordinate_backfill")
        deprioritized_reason_map["coordinate_backfill"] = "no_coordinate_candidate"
        feedback_hints.append("no_coordinate_candidate")

    if has_recoverability and suggest_infer_location and coordinate_infer_candidate_count <= 0 and coordinate_missing > 0 and not receipt_location_ready:
        suggest_infer_location = False

    if has_recoverability and suggest_extract_risk and archive_backfill_candidate_count <= 0 and risk_missing > 0:
        suggest_extract_risk = False

    if has_recoverability and historical_unrecoverable_count > 0 and future_fixable_count <= 0:
        manual_review_candidate = True
        if "historical_unrecoverable_gap" not in feedback_hints:
            feedback_hints.append("historical_unrecoverable_gap")

    reasons: list[str] = []
    if detail_stage_blockers > 0:
        reasons.append("detail_stage")
    if price_anchor_blockers > 0:
        reasons.append("price_anchor")
    if location_precision_blockers > 0:
        reasons.append("location_precision")
    if business_area_blockers > 0:
        reasons.append("business_area")
    if coordinate_missing > 0:
        reasons.append("missing_coordinates")
    if risk_missing > 0:
        reasons.append("risk_gap")
    if detail_archive_present_count > 0:
        reasons.append("detail_archive_present")
    reasons.extend(feedback_hints)

    priority_actions: list[str] = []
    if planned_fetch_archives:
        priority_actions.append("fetch_archives")
    if run_archived_backfill:
        priority_actions.append("archived_detail_backfill")
    if planned_prepare_replay:
        priority_actions.append("prepare_replay")
    if run_coordinate_backfill:
        priority_actions.append("coordinate_backfill")
    if suggest_infer_location:
        priority_actions.append("infer_location")
    if suggest_extract_risk:
        priority_actions.append("extract_risk")
    if suggest_analysis_ready_recheck:
        priority_actions.append("analysis_ready_recheck")
    if suggest_stage_state_reconcile:
        priority_actions.append("stage_state_reconcile")

    next_best_alternative_actions: list[str] = []
    if manual_review_candidate:
        next_best_alternative_actions.append("manual_review")
    for target_action in fallback_routes.values():
        if target_action not in next_best_alternative_actions:
            next_best_alternative_actions.append(target_action)
    for action in priority_actions:
        if action not in next_best_alternative_actions:
            next_best_alternative_actions.append(action)
    deprioritized_actions = list(dict.fromkeys(deprioritized_actions))
    feedback_hints = list(dict.fromkeys(feedback_hints))

    operator_summary = {
        "primary_action": priority_actions[0] if priority_actions else None,
        "next_best_alternative_actions": next_best_alternative_actions,
        "top_alternative_actions": next_best_alternative_actions[:3],
        "top_alternative_action": next_best_alternative_actions[0] if next_best_alternative_actions else None,
        "deprioritized_actions": deprioritized_actions,
        "feedback_hints": feedback_hints,
        "manual_review_candidate": manual_review_candidate,
        "manual_review_candidates": ["manual_review"] if manual_review_candidate else [],
    }

    return {
        "analysis_blockers": blockers,
        "missing_field_counts": missing_field_counts,
        "recoverability_counts": recoverability_counts,
        "fetch_archives": planned_fetch_archives,
        "prepare_replay": planned_prepare_replay,
        "coordinate_focus": coordinate_focus,
        "run_archived_backfill": run_archived_backfill,
        "run_coordinate_backfill": run_coordinate_backfill,
        "suggest_infer_location": suggest_infer_location,
        "suggest_extract_risk": suggest_extract_risk,
        "suggest_analysis_ready_recheck": suggest_analysis_ready_recheck,
        "suggest_stage_state_reconcile": suggest_stage_state_reconcile,
        "priority_actions": priority_actions,
        "next_best_alternative_actions": next_best_alternative_actions,
        "deprioritized_actions": deprioritized_actions,
        "deprioritized_reason_map": deprioritized_reason_map,
        "feedback_hints": feedback_hints,
        "fallback_routes": fallback_routes,
        "manual_review_candidate": manual_review_candidate,
        "operator_summary": operator_summary,
        "reasons": reasons,
    }


__all__ = ['recommend_analysis_stage_actions']
