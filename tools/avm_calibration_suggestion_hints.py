"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_calibration_suggestion_context import *


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


__all__ = (
    "_build_top_target_hint",
    "_build_bundle_commands",
)
