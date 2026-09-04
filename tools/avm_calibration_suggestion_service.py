"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_calibration_suggestion_context import *


def suggest_calibration_targets(
    metrics: dict[str, Any],
    *,
    min_sample_count: int = 3,
    bias_threshold_pct: float = 5.0,
    mape_threshold_pct: float = 12.0,
) -> dict[str, Any]:
    active_weighting = get_effective_weighting()
    current_risk_discount_factor = get_effective_risk_discount_factor(0.9)
    qualifying_risk_rows: list[dict[str, Any]] = []
    risk_factor_targets: list[dict[str, Any]] = []
    effective_risk_factor_map = get_effective_risk_factor_map()
    for row in metrics.get("risk_flag_metrics", []) or []:
        sample_count = int(row.get("sample_count") or 0)
        mean_bias_pct = float(row.get("mean_bias_pct") or 0.0)
        mape_pct = float(row.get("mape_pct") or 0.0)
        if sample_count < min_sample_count:
            continue
        if abs(mean_bias_pct) < bias_threshold_pct and mape_pct < mape_threshold_pct:
            continue
        qualifying_risk_rows.append(row)
        name = str(row.get("group") or "")
        current_factor = effective_risk_factor_map.get(name)
        suggested_action = _risk_flag_action(name, mean_bias_pct)
        suggested_factor_step_pct = _suggest_factor_step_pct(mean_bias_pct)
        risk_factor_targets.append(
            {
                "target_type": "risk_flag",
                "name": name,
                "sample_count": sample_count,
                "mape_pct": mape_pct,
                "mean_bias_pct": mean_bias_pct,
                "current_factor": current_factor,
                "suggested_action": suggested_action,
                "suggested_factor_step_pct": suggested_factor_step_pct,
                "suggested_next_factor": _suggest_next_factor(current_factor, suggested_action, suggested_factor_step_pct),
            }
        )

    global_risk_targets: list[dict[str, Any]] = []
    if len(qualifying_risk_rows) >= 2:
        signs = {1 if float(row.get("mean_bias_pct") or 0.0) > 0 else -1 for row in qualifying_risk_rows}
        if len(signs) == 1:
            avg_bias_pct = sum(float(row.get("mean_bias_pct") or 0.0) for row in qualifying_risk_rows) / len(qualifying_risk_rows)
            suggested_action = _global_risk_discount_action(avg_bias_pct)
            step_pct = _suggest_factor_step_pct(avg_bias_pct)
            global_risk_targets.append(
                {
                    "target_type": "global_risk",
                    "name": "risk_discount_factor",
                    "sample_count": sum(int(row.get("sample_count") or 0) for row in qualifying_risk_rows),
                    "mean_bias_pct": round(avg_bias_pct, 4),
                    "supporting_risk_flags": [str(row.get("group") or "") for row in qualifying_risk_rows],
                    "current_value": current_risk_discount_factor,
                    "suggested_action": suggested_action,
                    "suggested_factor_step_pct": step_pct,
                    "suggested_next_value": _suggest_next_risk_discount_factor(current_risk_discount_factor, suggested_action, step_pct),
                }
            )

    strategy_targets: list[dict[str, Any]] = []
    for row in metrics.get("strategy_metrics", []) or []:
        sample_count = int(row.get("sample_count") or 0)
        mape_pct = float(row.get("mape_pct") or 0.0)
        p90_ape_pct = float(row.get("p90_ape_pct") or 0.0)
        if sample_count < min_sample_count:
            continue
        if mape_pct < mape_threshold_pct and p90_ape_pct < max(mape_threshold_pct * 2, 25.0):
            continue
        name = str(row.get("group") or "")
        strategy_targets.append(
            {
                "target_type": "strategy",
                "name": name,
                "sample_count": sample_count,
                "mape_pct": mape_pct,
                "p90_ape_pct": p90_ape_pct,
                "suggested_action": _strategy_action(name),
            }
        )

    valuation_mode_metric_map = {
        str(row.get("group") or ""): row
        for row in metrics.get("valuation_mode_metrics", []) or []
        if isinstance(row, dict)
    }
    temporal_targets: list[dict[str, Any]] = []
    historical_metric = valuation_mode_metric_map.get("historical_strict")
    current_metric = valuation_mode_metric_map.get("current_market")
    if historical_metric is not None:
        sample_count = int(historical_metric.get("sample_count") or 0)
        historical_mape_pct = float(historical_metric.get("mape_pct") or 0.0)
        historical_mean_bias_pct = float(historical_metric.get("mean_bias_pct") or 0.0)
        current_market_mape_pct = float(current_metric.get("mape_pct") or 0.0) if current_metric is not None else 0.0
        valuation_mode_gap_pct = abs(current_market_mape_pct - historical_mape_pct) if current_metric is not None else 0.0
        if sample_count >= min_sample_count and (
            abs(historical_mean_bias_pct) >= bias_threshold_pct
            or historical_mape_pct >= mape_threshold_pct
            or valuation_mode_gap_pct >= mape_threshold_pct / 2
        ):
            current_time_decay = float(active_weighting.get("time_decay", 1.0))
            suggested_action = _temporal_action(historical_mean_bias_pct)
            suggested_factor_step_pct = _suggest_factor_step_pct(max(abs(historical_mean_bias_pct), valuation_mode_gap_pct))
            temporal_targets.append(
                {
                    "target_type": "temporal",
                    "name": "time_decay",
                    "sample_count": sample_count,
                    "historical_mape_pct": historical_mape_pct,
                    "historical_mean_bias_pct": historical_mean_bias_pct,
                    "current_market_mape_pct": current_market_mape_pct if current_metric is not None else None,
                    "valuation_mode_gap_pct": round(valuation_mode_gap_pct, 4),
                    "current_value": current_time_decay,
                    "suggested_action": suggested_action,
                    "suggested_factor_step_pct": suggested_factor_step_pct,
                    "suggested_next_value": _suggest_next_time_decay(current_time_decay, suggested_action, suggested_factor_step_pct),
                }
            )

    risk_factor_targets.sort(key=lambda row: (-abs(float(row.get("mean_bias_pct") or 0.0)), -float(row.get("mape_pct") or 0.0), row.get("name") or ""))
    strategy_targets.sort(key=lambda row: (-float(row.get("mape_pct") or 0.0), -float(row.get("p90_ape_pct") or 0.0), row.get("name") or ""))

    top_calibration_target = (
        global_risk_targets[0]
        if global_risk_targets
        else (risk_factor_targets[0] if risk_factor_targets else (temporal_targets[0] if temporal_targets else (strategy_targets[0] if strategy_targets else None)))
    )
    config_patch = {
        "weighting": {
            "time_decay": temporal_targets[0]["suggested_next_value"]
        } if temporal_targets and temporal_targets[0].get("suggested_next_value") is not None else {},
        "risk_discount_factor": global_risk_targets[0]["suggested_next_value"]
        if global_risk_targets and global_risk_targets[0].get("suggested_next_value") is not None
        else None,
        "risk_factor_overrides": {
            str(item["name"]): item["suggested_next_factor"]
            for item in risk_factor_targets
            if item.get("suggested_next_factor") is not None
        }
    }
    if config_patch.get("risk_discount_factor") is None:
        config_patch.pop("risk_discount_factor", None)
    guidance = _build_guidance(
        metrics,
        global_risk_targets=global_risk_targets,
        risk_factor_targets=risk_factor_targets,
        temporal_targets=temporal_targets,
        strategy_targets=strategy_targets,
        min_sample_count=min_sample_count,
        mape_threshold_pct=mape_threshold_pct,
    )
    top_calibration_target_hint = _build_top_target_hint(top_calibration_target, guidance)
    top_calibration_target_hint = _build_bundle_commands(
        top_calibration_target,
        top_calibration_target_hint,
        global_risk_targets=global_risk_targets,
        temporal_targets=temporal_targets,
        risk_factor_targets=risk_factor_targets,
    )
    return normalize_calibration_targets_payload({
        "has_recommendations": bool(global_risk_targets or risk_factor_targets or temporal_targets or strategy_targets),
        "global_risk_targets": global_risk_targets,
        "risk_factor_targets": risk_factor_targets,
        "temporal_targets": temporal_targets,
        "strategy_targets": strategy_targets,
        "top_calibration_target": top_calibration_target,
        "top_calibration_target_hint": top_calibration_target_hint,
        "guidance": guidance,
        "config_patch": config_patch,
    })


__all__ = (
    "suggest_calibration_targets",
)
