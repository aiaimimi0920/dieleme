"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_pipeline_runner_context import *


def _run_calibration_stage(eval_report_path: str, output_path: str) -> Dict[str, Any]:
    report = json.loads(Path(eval_report_path).read_text(encoding="utf-8"))
    result = normalize_calibration_targets_payload(suggest_calibration_targets(report.get("metrics", {}) or {}))
    gate_eval = build_eval_gate(report.get("metrics", {}) or {}, GateThresholds())
    global_risk_targets = list(result.get("global_risk_targets") or [])
    risk_factor_targets = list(result.get("risk_factor_targets") or [])
    temporal_targets = list(result.get("temporal_targets") or [])
    strategy_targets = list(result.get("strategy_targets") or [])
    has_recommendations = bool(global_risk_targets or risk_factor_targets or temporal_targets or strategy_targets)
    top_target = result.get("top_calibration_target") if isinstance(result.get("top_calibration_target"), dict) else {}
    top_target_hint = result.get("top_calibration_target_hint") if isinstance(result.get("top_calibration_target_hint"), dict) else {}
    recommended_bundle = top_target_hint.get("recommended_bundle") if isinstance(top_target_hint.get("recommended_bundle"), dict) else {}
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if recommended_bundle:
        config_path = Path(output_path).with_name("config.json")
        if config_path.exists() and not _json_file_is_object(config_path):
            with tempfile.TemporaryDirectory() as tmpdir:
                temp_config_path = Path(tmpdir) / "config.json"
                temp_config_path.write_text(json.dumps(DEFAULT_AVM_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
                bundle_preview = apply_avm_calibration_patch(
                    config_path=temp_config_path,
                    calibration_path=Path(output_path),
                    write_back=False,
                    target_types=list(recommended_bundle.get("target_types") or []),
                    target_names=list(recommended_bundle.get("target_names") or []),
                )
        else:
            bundle_preview = apply_avm_calibration_patch(
                config_path=config_path,
                calibration_path=Path(output_path),
                write_back=False,
                target_types=list(recommended_bundle.get("target_types") or []),
                target_names=list(recommended_bundle.get("target_names") or []),
            )
    else:
        bundle_preview = {}
    recommended_bundle_primary_change, recommended_bundle_secondary_changes = _bundle_change_summary(bundle_preview)
    (
        recommended_bundle_preview_command,
        recommended_bundle_write_command,
        recommended_bundle_verify_command,
        recommended_bundle_gate_command,
    ) = _bundle_command_summary(top_target_hint)
    recommended_bundle_risk = summarize_patch_risk(bundle_preview)
    recommended_bundle_next_action = summarize_patch_next_action(recommended_bundle_risk, bundle_preview)
    next_action_command = summarize_patch_next_action_command(
        recommended_bundle_next_action,
        preview_command=recommended_bundle_preview_command,
        write_command=recommended_bundle_write_command,
    )
    follow_up_command = summarize_patch_follow_up_command(
        recommended_bundle_next_action,
        preview_command=recommended_bundle_preview_command,
        write_command=recommended_bundle_write_command,
        verify_command=recommended_bundle_verify_command,
    )
    command_chain = summarize_patch_command_chain(
        next_action_command=str(next_action_command.get("next_action_command") or ""),
        next_action_command_kind=str(next_action_command.get("next_action_command_kind") or "none"),
        follow_up_command=str(follow_up_command.get("follow_up_command") or ""),
        follow_up_command_kind=str(follow_up_command.get("follow_up_command_kind") or "none"),
        verify_command=recommended_bundle_verify_command,
        gate_command=recommended_bundle_gate_command,
    )
    command_chain = resolve_command_chain_artifacts(command_chain, Path(output_path).parent.parent)
    command_chain = apply_command_chain_next_action_policy(
        command_chain,
        next_action=str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
    )
    return {
        "output_path": output_path,
        "summary": {
            "has_recommendations": has_recommendations,
            "global_risk_target_count": len(global_risk_targets),
            "risk_factor_target_count": len(risk_factor_targets),
            "temporal_target_count": len(temporal_targets),
            "strategy_target_count": len(strategy_targets),
            "guidance_status": str((result.get("guidance") or {}).get("status") or "unknown"),
            "coordinate_strategy_watchlist": list(gate_eval.get("coordinate_strategy_watchlist") or []),
            "top_coordinate_strategy_group": gate_eval.get("top_coordinate_strategy_group"),
            "top_target_name": str(top_target.get("name") or ""),
            "top_target_type": str(top_target.get("target_type") or ""),
            "top_target_hint_status": str(top_target_hint.get("status") or "unknown"),
            "top_target_playbook_id": str(top_target_hint.get("playbook_id") or "unknown"),
            "recommended_bundle_id": str(recommended_bundle.get("bundle_id") or ""),
            "recommended_bundle_changed_key_count": int(bundle_preview.get("changed_key_count") or 0),
            "recommended_bundle_primary_change": recommended_bundle_primary_change,
            "recommended_bundle_secondary_changes": recommended_bundle_secondary_changes,
            "recommended_bundle_preview_command": recommended_bundle_preview_command,
            "recommended_bundle_write_command": recommended_bundle_write_command,
            "recommended_bundle_verify_command": recommended_bundle_verify_command,
            "recommended_bundle_gate_command": recommended_bundle_gate_command,
            "recommended_bundle_risk_level": str(recommended_bundle_risk.get("risk_level") or "none"),
            "recommended_bundle_risk_reasons": list(recommended_bundle_risk.get("risk_reasons") or []),
            "recommended_bundle_next_action": str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
            "recommended_bundle_next_action_reasons": list(recommended_bundle_next_action.get("next_action_reasons") or []),
            "recommended_bundle_next_action_command": str(next_action_command.get("next_action_command") or ""),
            "recommended_bundle_next_action_command_kind": str(next_action_command.get("next_action_command_kind") or "none"),
            "recommended_bundle_follow_up_command": str(follow_up_command.get("follow_up_command") or ""),
            "recommended_bundle_follow_up_command_kind": str(follow_up_command.get("follow_up_command_kind") or "none"),
            "recommended_bundle_command_chain": command_chain,
        },
        "report": result,
    }



__all__ = (
    "_run_calibration_stage",
)
