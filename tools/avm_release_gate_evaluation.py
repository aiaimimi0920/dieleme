"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_release_gate_context import *


def build_eval_gate(metrics: dict[str, Any], thresholds: GateThresholds) -> dict[str, Any]:
    if not metrics:
        return {"pass": False, "reason": "missing_metrics"}

    valuation_mode_counts = metrics.get("valuation_mode_counts", {}) or {}
    risk_validation_counts = metrics.get("risk_validation_counts", {}) or {}
    temporal_reference_mode_counts = metrics.get("temporal_reference_mode_counts", {}) or {}
    historical_temporal_reference_mode_counts = metrics.get("historical_temporal_reference_mode_counts", {}) or {}
    strategy_metrics = metrics.get("strategy_metrics", []) or []
    coordinate_strategy_metrics = metrics.get("coordinate_strategy_metrics", []) or []
    risk_validation_metrics = metrics.get("risk_validation_metrics", []) or []
    valuation_mode_metrics = metrics.get("valuation_mode_metrics", []) or []
    risk_flag_metrics = metrics.get("risk_flag_metrics", []) or []
    calibration_targets = normalize_calibration_targets_payload(suggest_calibration_targets(metrics))

    historical_strict_count = int(valuation_mode_counts.get("historical_strict") or 0)
    current_market_count = int(valuation_mode_counts.get("current_market") or 0)
    historical_ratio = 1.0 if historical_strict_count > 0 else 0.0
    historical_strict_primary = historical_strict_count > 0 and historical_strict_count >= current_market_count

    risk_validation_total = max(sum(int(v) for v in risk_validation_counts.values()), 0)
    risk_invalid_count = int(risk_validation_counts.get("invalid") or 0)
    risk_invalid_ratio = 0.0 if risk_validation_total <= 0 else risk_invalid_count / risk_validation_total
    risk_validation_invalid_pass = risk_invalid_ratio <= thresholds.max_risk_invalid_ratio

    historical_current_time_count = int(historical_temporal_reference_mode_counts.get("current_time") or 0)
    historical_current_time_ratio = 0.0 if historical_strict_count <= 0 else historical_current_time_count / historical_strict_count
    historical_temporal_reference_pass = historical_current_time_ratio <= thresholds.max_historical_current_time_ratio

    top_strategy_group = None
    if strategy_metrics:
        top_strategy_group = max(strategy_metrics, key=lambda row: float(row.get("mape_pct") or 0.0)).get("group")
    top_coordinate_strategy_group = None
    if coordinate_strategy_metrics:
        top_coordinate_strategy_group = max(coordinate_strategy_metrics, key=lambda row: float(row.get("mape_pct") or 0.0)).get("group")
    top_risk_validation_group = None
    if risk_validation_metrics:
        top_risk_validation_group = max(risk_validation_metrics, key=lambda row: float(row.get("mape_pct") or 0.0)).get("group")

    valuation_mode_mape_gap_pct = 0.0
    valuation_mode_gap_warning = False
    valuation_mode_metric_map = {
        str(row.get("group")): row
        for row in valuation_mode_metrics
        if isinstance(row, dict)
    }
    historical_metric = valuation_mode_metric_map.get("historical_strict")
    current_metric = valuation_mode_metric_map.get("current_market")
    if historical_metric and current_metric:
        valuation_mode_mape_gap_pct = round(
            abs(float(current_metric.get("mape_pct") or 0.0) - float(historical_metric.get("mape_pct") or 0.0)),
            4,
        )
        valuation_mode_gap_warning = valuation_mode_mape_gap_pct > thresholds.max_mape_pct / 2

    strategy_watchlist = [
        str(row.get("group"))
        for row in strategy_metrics
        if int(row.get("sample_count") or 0) >= 3
        and (
            float(row.get("mape_pct") or 0.0) > thresholds.max_mape_pct
            or float(row.get("p90_ape_pct") or 0.0) > thresholds.max_p90_ape_pct
        )
    ]
    coordinate_strategy_watchlist = [
        str(row.get("group"))
        for row in coordinate_strategy_metrics
        if int(row.get("sample_count") or 0) >= 1
        and (
            float(row.get("mape_pct") or 0.0) > thresholds.max_mape_pct
            or float(row.get("p90_ape_pct") or 0.0) > thresholds.max_p90_ape_pct
        )
    ]
    risk_validation_watchlist = [
        str(row.get("group"))
        for row in risk_validation_metrics
        if int(row.get("sample_count") or 0) >= 1
        and (
            float(row.get("mape_pct") or 0.0) > thresholds.max_mape_pct
            or float(row.get("p90_ape_pct") or 0.0) > thresholds.max_p90_ape_pct
        )
    ]

    return {
        "mape_pct": metrics.get("mape_pct"),
        "p50_ape_pct": metrics.get("p50_ape_pct"),
        "p90_ape_pct": metrics.get("p90_ape_pct"),
        "max_abs_partition_bias_pct": metrics.get("max_abs_partition_bias_pct"),
        "valuation_mode_counts": valuation_mode_counts,
        "valuation_mode_metrics": valuation_mode_metrics,
        "temporal_reference_mode_counts": temporal_reference_mode_counts,
        "historical_temporal_reference_mode_counts": historical_temporal_reference_mode_counts,
        "risk_validation_counts": risk_validation_counts,
        "future_dated_comparable_exclusion_total": metrics.get("future_dated_comparable_exclusion_total", 0),
        "strategy_metrics": strategy_metrics,
        "coordinate_strategy_metrics": coordinate_strategy_metrics,
        "risk_validation_metrics": risk_validation_metrics,
        "risk_flag_metrics": risk_flag_metrics,
        "calibration_targets": calibration_targets,
        "top_strategy_group": top_strategy_group,
        "top_coordinate_strategy_group": top_coordinate_strategy_group,
        "top_risk_validation_group": top_risk_validation_group,
        "valuation_mode_mape_gap_pct": valuation_mode_mape_gap_pct,
        "valuation_mode_gap_warning": valuation_mode_gap_warning,
        "strategy_watchlist": strategy_watchlist,
        "coordinate_strategy_watchlist": coordinate_strategy_watchlist,
        "risk_validation_watchlist": risk_validation_watchlist,
        "historical_strict_ratio": round(historical_ratio, 4),
        "historical_strict_primary": historical_strict_primary,
        "historical_current_time_ratio": round(historical_current_time_ratio, 4),
        "historical_temporal_reference_pass": historical_temporal_reference_pass,
        "risk_validation_invalid_ratio": round(risk_invalid_ratio, 4),
        "risk_validation_invalid_pass": risk_validation_invalid_pass,
        "pass": (
            float(metrics.get("mape_pct") or 9999) <= thresholds.max_mape_pct
            and float(metrics.get("p50_ape_pct") or 9999) <= thresholds.max_p50_ape_pct
            and float(metrics.get("p90_ape_pct") or 9999) <= thresholds.max_p90_ape_pct
            and float(metrics.get("max_abs_partition_bias_pct") or 9999) <= thresholds.max_abs_partition_bias_pct
            and historical_strict_primary
            and historical_temporal_reference_pass
            and risk_validation_invalid_pass
        ),
    }



__all__ = (
    "build_eval_gate",
)
