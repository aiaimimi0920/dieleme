"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_calibration_suggestion_context import *


def _build_guidance(
    metrics: dict[str, Any],
    *,
    global_risk_targets: list[dict[str, Any]],
    risk_factor_targets: list[dict[str, Any]],
    temporal_targets: list[dict[str, Any]],
    strategy_targets: list[dict[str, Any]],
    min_sample_count: int,
    mape_threshold_pct: float,
) -> dict[str, Any]:
    risk_validation_metrics = metrics.get("risk_validation_metrics", []) or []
    risk_quality_target = None
    for row in risk_validation_metrics:
        if str(row.get("group") or "") not in {"invalid", "incomplete"}:
            continue
        if int(row.get("sample_count") or 0) < min_sample_count:
            continue
        if float(row.get("mape_pct") or 0.0) < mape_threshold_pct:
            continue
        if risk_quality_target is None or float(row.get("mape_pct") or 0.0) > float(risk_quality_target.get("mape_pct") or 0.0):
            risk_quality_target = row

    coordinate_strategy_metrics = metrics.get("coordinate_strategy_metrics", []) or []
    coordinate_quality_target = None
    for row in coordinate_strategy_metrics:
        group = str(row.get("group") or "")
        if group in {"observed", "unknown"}:
            continue
        if int(row.get("sample_count") or 0) < min_sample_count:
            continue
        if float(row.get("mape_pct") or 0.0) < mape_threshold_pct:
            continue
        if coordinate_quality_target is None or float(row.get("mape_pct") or 0.0) > float(coordinate_quality_target.get("mape_pct") or 0.0):
            coordinate_quality_target = row

    if risk_quality_target is not None:
        group = str(risk_quality_target.get("group") or "invalid")
        return {
            "status": "fix_risk_data_quality",
            "priority": "high",
            "recommended_actions": [
                "review_risk_validation_cohorts",
                f"reduce_{group}_risk_fields",
                "rebuild_eval_report_after_data_fix",
            ],
            "top_reason": group,
        }

    if coordinate_quality_target is not None:
        group = str(coordinate_quality_target.get("group") or "district_centroid")
        return {
            "status": "fix_coordinate_quality",
            "priority": "high",
            "recommended_actions": [
                "review_coordinate_strategy_cohorts",
                f"reduce_{group}_subjects",
                "backfill_missing_coordinates_or_centroids",
            ],
            "top_reason": group,
        }

    if global_risk_targets:
        return {
            "status": "tune_global_risk_discount",
            "priority": "medium",
            "recommended_actions": [
                "apply_global_risk_discount_patch",
                "rerun_eval_and_release_gate",
            ],
            "top_reason": str(global_risk_targets[0].get("name") or "risk_discount_factor"),
        }

    if risk_factor_targets:
        return {
            "status": "tune_risk_factors",
            "priority": "medium",
            "recommended_actions": [
                "apply_risk_factor_overrides_in_config_patch",
                "rerun_eval_and_release_gate",
            ],
            "top_reason": str(risk_factor_targets[0].get("name") or ""),
        }

    if temporal_targets:
        return {
            "status": "tune_temporal_decay",
            "priority": "medium",
            "recommended_actions": [
                "apply_temporal_time_decay_patch",
                "rerun_eval_and_release_gate",
            ],
            "top_reason": str(temporal_targets[0].get("name") or "time_decay"),
        }

    if strategy_targets:
        top = strategy_targets[0]
        action = str(top.get("suggested_action") or "")
        if action == "improve_candidate_coverage":
            return {
                "status": "improve_candidate_coverage",
                "priority": "medium",
                "recommended_actions": [
                    "expand_candidate_coverage",
                    "review_analysis_ready_supply",
                ],
                "top_reason": str(top.get("name") or ""),
            }
        return {
            "status": "review_weighting_and_filters",
            "priority": "medium",
            "recommended_actions": [
                "review_spatial_weighting",
                "review_outlier_filters",
            ],
            "top_reason": str(top.get("name") or ""),
        }

    return {
        "status": "no_action_required",
        "priority": "info",
        "recommended_actions": [],
        "top_reason": "",
    }



__all__ = (
    "_build_guidance",
)
