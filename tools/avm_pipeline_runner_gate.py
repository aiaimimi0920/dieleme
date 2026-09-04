"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_pipeline_runner_context import *


def _run_gate_stage(data_dir: str, eval_report_path: str, output_path: str) -> Dict[str, Any]:
    report = generate_release_gate_report(
        data_root=Path(data_dir),
        eval_report_path=Path(eval_report_path),
        gate_report_path=Path(output_path),
        smoke_sample_size=0,
        reuse_eval_report=True,
    )
    evaluation = report.get("evaluation") if isinstance(report.get("evaluation"), dict) else {}
    calibration_targets_path = Path(data_dir) / "avm" / "calibration_targets.json"
    raw_embedded_calibration_targets = (
        evaluation.get("calibration_targets") if isinstance(evaluation.get("calibration_targets"), dict) else {}
    )
    loaded_calibration_targets: dict[str, Any] = {}
    if calibration_targets_path.exists():
        try:
            raw_loaded_calibration_targets = json.loads(calibration_targets_path.read_text(encoding="utf-8"))
            if isinstance(raw_loaded_calibration_targets, dict):
                loaded_calibration_targets = normalize_calibration_targets_payload(raw_loaded_calibration_targets)
        except json.JSONDecodeError:
            loaded_calibration_targets = {}
    if loaded_calibration_targets:
        def _merge_calibration_targets(preferred: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
            merged = dict(fallback)
            for key, value in preferred.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = _merge_calibration_targets(value, merged[key])
                else:
                    merged[key] = value
            return merged

        calibration_targets = normalize_calibration_targets_payload(
            _merge_calibration_targets(raw_embedded_calibration_targets, loaded_calibration_targets)
            if raw_embedded_calibration_targets
            else loaded_calibration_targets
        )
    else:
        calibration_targets = normalize_calibration_targets_payload(raw_embedded_calibration_targets)
    top_target = calibration_targets.get("top_calibration_target") if isinstance(calibration_targets.get("top_calibration_target"), dict) else {}
    top_target_hint = calibration_targets.get("top_calibration_target_hint") if isinstance(calibration_targets.get("top_calibration_target_hint"), dict) else {}
    guidance = calibration_targets.get("guidance") if isinstance(calibration_targets.get("guidance"), dict) else {}
    global_risk_targets = list(calibration_targets.get("global_risk_targets") or [])
    risk_factor_targets = list(calibration_targets.get("risk_factor_targets") or [])
    temporal_targets = list(calibration_targets.get("temporal_targets") or [])
    strategy_targets = list(calibration_targets.get("strategy_targets") or [])
    recommended_bundle = top_target_hint.get("recommended_bundle") if isinstance(top_target_hint.get("recommended_bundle"), dict) else {}
    config_path = Path(data_dir) / "avm" / "config.json"
    use_temp_config_path = config_path.exists() and not _json_file_is_object(config_path)

    def _build_bundle_preview(config_preview_path: Path, calibration_path: Path) -> dict[str, Any]:
        if not recommended_bundle:
            return {}
        return apply_avm_calibration_patch(
            config_path=config_preview_path,
            calibration_path=calibration_path,
            write_back=False,
            target_types=list(recommended_bundle.get("target_types") or []),
            target_names=list(recommended_bundle.get("target_names") or []),
        )

    use_temp_calibration_path = (
        not calibration_targets_path.exists()
        or calibration_targets != loaded_calibration_targets
    )
    if use_temp_calibration_path or use_temp_config_path:
        with tempfile.TemporaryDirectory() as tmpdir:
            if use_temp_calibration_path:
                temp_calibration_path = Path(tmpdir) / "calibration_targets.json"
                temp_calibration_path.write_text(json.dumps(calibration_targets, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                temp_calibration_path = calibration_targets_path
            if use_temp_config_path:
                temp_config_path = Path(tmpdir) / "config.json"
                temp_config_path.write_text(json.dumps(DEFAULT_AVM_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                temp_config_path = config_path
            bundle_preview = _build_bundle_preview(temp_config_path, temp_calibration_path)
    else:
        bundle_preview = _build_bundle_preview(config_path, calibration_targets_path)
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
    command_chain = resolve_command_chain_artifacts(command_chain, Path(data_dir))
    command_chain = apply_command_chain_next_action_policy(
        command_chain,
        next_action=str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
    )
    return {
        "output_path": output_path,
        "summary": {
            "has_recommendations": bool(calibration_targets.get("has_recommendations")),
            "pass": bool(report.get("pass")),
            "evaluation_pass": bool((report.get("evaluation") or {}).get("pass")),
            "completeness_pass": bool((report.get("completeness") or {}).get("pass")),
            "drift_pass": bool((report.get("drift") or {}).get("pass")),
            "guidance_status": str(guidance.get("status") or "unknown"),
            "global_risk_target_count": len(global_risk_targets),
            "risk_factor_target_count": len(risk_factor_targets),
            "temporal_target_count": len(temporal_targets),
            "strategy_target_count": len(strategy_targets),
            "coordinate_strategy_watchlist": list((evaluation.get("coordinate_strategy_watchlist") or [])),
            "top_coordinate_strategy_group": evaluation.get("top_coordinate_strategy_group"),
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
        "report": report,
    }


__all__ = (
    "_run_gate_stage",
)
