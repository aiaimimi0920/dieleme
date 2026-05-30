#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.avm.engine import get_effective_risk_factor_map
from src.avm_config import get_effective_risk_discount_factor, get_effective_weighting
from tools.apply_avm_calibration_patch import normalize_calibration_targets_payload


def _risk_flag_action(flag: str, mean_bias_pct: float) -> str:
    if mean_bias_pct > 0:
        return "lower_price_contribution"
    return "raise_price_contribution"


def _suggest_factor_step_pct(mean_bias_pct: float) -> float:
    return round(min(max(abs(mean_bias_pct) * 0.5, 2.0), 10.0), 4)


def _suggest_next_factor(current_factor: float | None, suggested_action: str, step_pct: float) -> float | None:
    if current_factor is None:
        return None
    step = step_pct / 100.0
    if suggested_action == "lower_price_contribution":
        return round(current_factor * (1.0 - step), 6)
    return round(current_factor * (1.0 + step), 6)


def _strategy_action(name: str) -> str:
    if name in {"global_fallback", "city_fallback", "district_fallback", "business_area_fallback"}:
        return "improve_candidate_coverage"
    return "review_weighting_and_filters"


def _temporal_action(mean_bias_pct: float) -> str:
    if mean_bias_pct > 0:
        return "strengthen_time_decay"
    return "relax_time_decay"


def _global_risk_discount_action(mean_bias_pct: float) -> str:
    if mean_bias_pct > 0:
        return "strengthen_global_risk_discount"
    return "relax_global_risk_discount"


def _suggest_next_time_decay(current_value: float | None, suggested_action: str, step_pct: float) -> float | None:
    if current_value is None:
        return None
    step = step_pct / 100.0
    if suggested_action == "strengthen_time_decay":
        return round(max(0.05, current_value * (1.0 - step)), 6)
    return round(min(1.0, current_value * (1.0 + step)), 6)


def _suggest_next_risk_discount_factor(current_value: float | None, suggested_action: str, step_pct: float) -> float | None:
    if current_value is None:
        return None
    step = step_pct / 100.0
    if suggested_action == "strengthen_global_risk_discount":
        return round(min(2.0, current_value * (1.0 + step)), 6)
    return round(max(0.05, current_value * (1.0 - step)), 6)


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


def _build_top_target_hint(
    top_target: dict[str, Any] | None,
    guidance: dict[str, Any],
) -> dict[str, Any] | None:
    guidance_status = str(guidance.get("status") or "")
    if not isinstance(top_target, dict):
        if guidance_status == "fix_coordinate_quality":
            return {
                "status": "coordinate_quality_priority",
                "target_type": "coordinate_strategy",
                "target_name": str(guidance.get("top_reason") or ""),
                "playbook_id": "fix-coordinate-quality",
                "runbook_refs": [
                    "docs/AVM_Runbook.md",
                    "tools/run_recent_enrich_maintenance.py",
                    "tools/evaluate_avm.py",
                    "tools/avm_release_gate.py",
                ],
                "recommended_actions": [
                    "review_coordinate_strategy_cohorts",
                    "backfill_missing_coordinates_or_centroids",
                    "rerun_eval_and_release_gate",
                ],
                "suggested_commands": [
                    "python tools/run_recent_enrich_maintenance.py --dry-run",
                    "python tools/evaluate_avm.py",
                    "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
                ],
            }
        if guidance_status == "fix_risk_data_quality":
            return {
                "status": "risk_data_quality_priority",
                "target_type": "risk_validation",
                "target_name": str(guidance.get("top_reason") or ""),
                "playbook_id": "fix-risk-data-quality",
                "runbook_refs": [
                    "docs/AVM_Runbook.md",
                    "tools/audit_recent_avm_gaps.py",
                    "tools/evaluate_avm.py",
                    "tools/avm_release_gate.py",
                ],
                "recommended_actions": [
                    "review_risk_validation_cohorts",
                    "repair_invalid_or_missing_risk_fields",
                    "rerun_eval_and_release_gate",
                ],
                "suggested_commands": [
                    "python tools/audit_recent_avm_gaps.py",
                    "python tools/evaluate_avm.py",
                    "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
                ],
            }
        return None

    target_type = str(top_target.get("target_type") or "")
    target_name = str(top_target.get("name") or "")

    if target_type == "risk_flag":
        return {
            "status": guidance_status or "tune_risk_factors",
            "target_type": target_type,
            "target_name": target_name,
            "playbook_id": "tune-risk-factors",
            "runbook_refs": [
                "docs/AVM_Runbook.md",
                "src/avm_config.py",
                "tools/evaluate_avm.py",
                "tools/avm_release_gate.py",
            ],
            "recommended_actions": [
                f"review_risk_flag_metric_{target_name}",
                f"adjust_risk_factor_override_{target_name}",
                "rerun_eval_and_release_gate",
            ],
            "suggested_commands": [
                f"python tools/apply_avm_calibration_patch.py --target-type risk_flag --target-name {target_name}",
                f"python tools/apply_avm_calibration_patch.py --target-type risk_flag --target-name {target_name} --write",
                "python tools/evaluate_avm.py",
                "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            ],
        }
    if target_type == "global_risk":
        return {
            "status": guidance_status or "tune_global_risk_discount",
            "target_type": target_type,
            "target_name": target_name,
            "playbook_id": "tune-global-risk-discount",
            "runbook_refs": [
                "docs/AVM_Runbook.md",
                "src/avm_config.py",
                "tools/evaluate_avm.py",
                "tools/avm_release_gate.py",
            ],
            "recommended_actions": [
                "review_cross_risk_flag_bias",
                "adjust_global_risk_discount_factor",
                "rerun_eval_and_release_gate",
            ],
            "suggested_commands": [
                f"python tools/apply_avm_calibration_patch.py --target-type global_risk --target-name {target_name}",
                f"python tools/apply_avm_calibration_patch.py --target-type global_risk --target-name {target_name} --write",
                "python tools/evaluate_avm.py",
                "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            ],
        }
    if target_type == "temporal":
        return {
            "status": guidance_status or "tune_temporal_decay",
            "target_type": target_type,
            "target_name": target_name,
            "playbook_id": "tune-temporal-decay",
            "runbook_refs": [
                "docs/AVM_Runbook.md",
                "tools/evaluate_avm.py",
                "tools/avm_release_gate.py",
            ],
            "recommended_actions": [
                "review_valuation_mode_gap_metrics",
                "adjust_weighting_time_decay",
                "rerun_eval_and_release_gate",
            ],
            "suggested_commands": [
                f"python tools/apply_avm_calibration_patch.py --target-type temporal --target-name {target_name}",
                f"python tools/apply_avm_calibration_patch.py --target-type temporal --target-name {target_name} --write",
                "python tools/evaluate_avm.py",
                "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            ],
        }
    if target_type == "strategy":
        return {
            "status": guidance_status or "improve_candidate_coverage",
            "target_type": target_type,
            "target_name": target_name,
            "playbook_id": "improve-candidate-coverage",
            "runbook_refs": [
                "docs/AVM_Runbook.md",
                "tools/run_avm_pipeline.py",
                "tools/evaluate_avm.py",
                "tools/avm_release_gate.py",
            ],
            "recommended_actions": [
                f"review_strategy_cohort_{target_name}",
                "expand_candidate_coverage_or_refine_filters",
                "rerun_eval_and_release_gate",
            ],
            "suggested_commands": [
                "python tools/run_avm_pipeline.py --data-dir datas",
                "python tools/evaluate_avm.py",
                "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            ],
        }
    return {
        "status": guidance_status or "review_target",
        "target_type": target_type,
        "target_name": target_name,
        "playbook_id": "review-target",
        "runbook_refs": ["docs/AVM_Runbook.md"],
        "recommended_actions": list(guidance.get("recommended_actions") or []),
        "suggested_commands": [],
    }


def _build_bundle_commands(
    top_target: dict[str, Any] | None,
    hint: dict[str, Any] | None,
    *,
    global_risk_targets: list[dict[str, Any]],
    temporal_targets: list[dict[str, Any]],
    risk_factor_targets: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(top_target, dict) or not isinstance(hint, dict):
        return hint

    augmented = dict(hint)
    target_type = str(top_target.get("target_type") or "")

    if target_type in {"temporal", "global_risk"} and global_risk_targets and temporal_targets:
        augmented["recommended_bundle"] = {
            "bundle_id": "temporal-global-risk",
            "target_types": ["global_risk", "temporal"],
            "target_names": None,
        }
        augmented["suggested_bundle_commands"] = [
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "python tools/evaluate_avm.py",
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        ]
        return augmented

    if target_type == "risk_flag" and len(risk_factor_targets) >= 2:
        target_names = [str(item.get("name") or "") for item in risk_factor_targets[:2] if str(item.get("name") or "")]
        if len(target_names) >= 2:
            bundle_name_args = " ".join(f"--target-name {name}" for name in target_names)
            augmented["recommended_bundle"] = {
                "bundle_id": "top-two-risk-flags",
                "target_types": ["risk_flag"],
                "target_names": target_names,
            }
            augmented["suggested_bundle_commands"] = [
                f"python tools/apply_avm_calibration_patch.py --target-type risk_flag {bundle_name_args}",
                f"python tools/apply_avm_calibration_patch.py --target-type risk_flag {bundle_name_args} --write",
                "python tools/evaluate_avm.py",
                "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            ]
    return augmented


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Suggest AVM calibration targets from eval report metrics")
    parser.add_argument("--eval-report", type=Path, default=Path("datas/avm/eval_report.json"))
    parser.add_argument("--output", type=Path, default=Path("datas/avm/calibration_targets.json"))
    parser.add_argument("--min-sample-count", type=int, default=3)
    parser.add_argument("--bias-threshold-pct", type=float, default=5.0)
    parser.add_argument("--mape-threshold-pct", type=float, default=12.0)
    args = parser.parse_args()

    payload = json.loads(args.eval_report.read_text(encoding="utf-8"))
    result = suggest_calibration_targets(
        payload.get("metrics", {}) or {},
        min_sample_count=args.min_sample_count,
        bias_threshold_pct=args.bias_threshold_pct,
        mape_threshold_pct=args.mape_threshold_pct,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
