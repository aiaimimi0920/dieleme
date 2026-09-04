from tools.test.apply_avm_calibration_patch_test_context import *  # noqa: F401,F403


def test_apply_avm_calibration_patch_can_filter_to_specific_risk_flag_target(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    original_config = {
        "radius_km": 3.0,
        "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
        "risk_discount_factor": 0.9,
        "alert_threshold": 0.25,
        "risk_factor_overrides": {"is_occupied": 0.8, "has_long_lease": 0.85},
    }
    calibration_payload = {
        "config_patch": {
            "risk_factor_overrides": {
                "is_occupied": 0.5,
                "has_long_lease": 0.7,
            }
        },
        "risk_factor_targets": [
            {"target_type": "risk_flag", "name": "is_occupied", "suggested_next_factor": 0.5},
            {"target_type": "risk_flag", "name": "has_long_lease", "suggested_next_factor": 0.7},
        ],
    }

    _write_json(config_path, original_config)
    _write_json(calibration_path, calibration_payload)

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
        target_type="risk_flag",
        target_name="has_long_lease",
    )

    assert result["applied_filter"] == {"target_type": "risk_flag", "target_name": "has_long_lease"}
    assert result["matched_targets"] == [{"target_type": "risk_flag", "target_name": "has_long_lease"}]
    assert result["changed_keys"] == ["risk_factor_overrides.has_long_lease"]
    assert result["merged_config"]["risk_factor_overrides"]["is_occupied"] == 0.8
    assert result["merged_config"]["risk_factor_overrides"]["has_long_lease"] == 0.7

def test_apply_avm_calibration_patch_can_filter_to_global_risk_target(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    original_config = {
        "radius_km": 3.0,
        "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
        "risk_discount_factor": 0.9,
        "alert_threshold": 0.25,
        "risk_factor_overrides": {"is_occupied": 0.8},
    }
    calibration_payload = {
        "config_patch": {
            "weighting": {"time_decay": 0.72},
            "risk_discount_factor": 1.05,
        },
        "temporal_targets": [
            {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
        ],
        "global_risk_targets": [
            {"target_type": "global_risk", "name": "risk_discount_factor", "suggested_next_value": 1.05}
        ],
    }

    _write_json(config_path, original_config)
    _write_json(calibration_path, calibration_payload)

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
        target_type="global_risk",
    )

    assert result["applied_filter"] == {"target_type": "global_risk", "target_name": None}
    assert result["matched_targets"] == [{"target_type": "global_risk", "target_name": "risk_discount_factor"}]
    assert result["changed_keys"] == ["risk_discount_factor"]
    assert result["merged_config"]["risk_discount_factor"] == 1.05
    assert result["merged_config"]["weighting"]["time_decay"] == 0.85

def test_apply_avm_calibration_patch_can_filter_to_multiple_target_types(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    original_config = {
        "radius_km": 3.0,
        "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
        "risk_discount_factor": 0.9,
        "alert_threshold": 0.25,
        "risk_factor_overrides": {"is_occupied": 0.8},
    }
    calibration_payload = {
        "config_patch": {
            "weighting": {"time_decay": 0.72},
            "risk_discount_factor": 1.05,
            "risk_factor_overrides": {"is_occupied": 0.5},
        },
        "temporal_targets": [
            {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
        ],
        "global_risk_targets": [
            {"target_type": "global_risk", "name": "risk_discount_factor", "suggested_next_value": 1.05}
        ],
        "risk_factor_targets": [
            {"target_type": "risk_flag", "name": "is_occupied", "suggested_next_factor": 0.5}
        ],
    }

    _write_json(config_path, original_config)
    _write_json(calibration_path, calibration_payload)

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
        target_types=["temporal", "global_risk"],
    )

    assert result["applied_filter"] == {"target_types": ["temporal", "global_risk"], "target_names": None}
    assert result["matched_targets"] == [
        {"target_type": "temporal", "target_name": "time_decay"},
        {"target_type": "global_risk", "target_name": "risk_discount_factor"},
    ]
    assert result["changed_keys"] == ["weighting.time_decay", "risk_discount_factor"]
    assert result["merged_config"]["weighting"]["time_decay"] == 0.72
    assert result["merged_config"]["risk_discount_factor"] == 1.05
    assert result["merged_config"]["risk_factor_overrides"]["is_occupied"] == 0.8

def test_apply_avm_calibration_patch_can_filter_to_multiple_target_names(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    original_config = {
        "radius_km": 3.0,
        "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
        "risk_discount_factor": 0.9,
        "alert_threshold": 0.25,
        "risk_factor_overrides": {"is_occupied": 0.8, "has_long_lease": 0.85, "property_fee_owed": 0.82},
    }
    calibration_payload = {
        "config_patch": {
            "risk_factor_overrides": {
                "is_occupied": 0.5,
                "has_long_lease": 0.7,
                "property_fee_owed": 0.75,
            }
        },
        "risk_factor_targets": [
            {"target_type": "risk_flag", "name": "is_occupied", "suggested_next_factor": 0.5},
            {"target_type": "risk_flag", "name": "has_long_lease", "suggested_next_factor": 0.7},
            {"target_type": "risk_flag", "name": "property_fee_owed", "suggested_next_factor": 0.75},
        ],
    }

    _write_json(config_path, original_config)
    _write_json(calibration_path, calibration_payload)

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
        target_type="risk_flag",
        target_names=["is_occupied", "has_long_lease"],
    )

    assert result["applied_filter"] == {"target_types": ["risk_flag"], "target_names": ["is_occupied", "has_long_lease"]}
    assert result["matched_targets"] == [
        {"target_type": "risk_flag", "target_name": "is_occupied"},
        {"target_type": "risk_flag", "target_name": "has_long_lease"},
    ]
    assert result["changed_keys"] == [
        "risk_factor_overrides.is_occupied",
        "risk_factor_overrides.has_long_lease",
    ]
    assert result["merged_config"]["risk_factor_overrides"]["is_occupied"] == 0.5
    assert result["merged_config"]["risk_factor_overrides"]["has_long_lease"] == 0.7
    assert result["merged_config"]["risk_factor_overrides"]["property_fee_owed"] == 0.82

def test_resolve_command_chain_artifacts_keeps_playbook_metadata_for_steps_without_artifacts(tmp_path: Path):
    command_chain = [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
                "artifact_kind": "config",
                "artifact_owner": "apply_avm_calibration_patch",
                "artifact": "datas/avm/config.json",
                "artifact_state": "missing",
                "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
                "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
                "artifact_check_timing": "pre_step",
            "artifact_freshness": "pending_write",
            "artifact_freshness_reason": "waiting_for_bundle_write",
            "artifact_next_expected_transition": "pending_write->current",
            "artifact_ready_for_step": True,
            "step_ready_summary": "ready_now",
            "step_ready_recommended_action": "proceed_now",
            "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "step_ready_follow_up_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "step_ready_follow_up_expected_signal": "config_patch_applied",
            "step_ready_follow_up_success_criterion": "ready_for_eval_rerun",
            "step_ready_terminal_outcome": "ready_for_eval_rerun",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "config_not_written_yet",
        }
    ]

def test_resolve_command_chain_artifacts_backfills_missing_metadata_for_known_steps_with_explicit_artifact(tmp_path: Path):
    eval_report_path = tmp_path / "avm" / "eval_report.json"
    _write_json(eval_report_path, {"metrics": {}})

    command_chain = [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "stale",
            "artifact_resolved_path": str(eval_report_path),
            "artifact_check_command": f'Get-Content "{eval_report_path}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "stale",
            "artifact_freshness_reason": "pre_bundle_eval_report",
            "artifact_next_expected_transition": "stale->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_eval_rerun",
            "step_ready_recommended_action": "rerun_evaluate",
            "step_ready_action_command": "python tools/evaluate_avm.py",
            "step_ready_follow_up_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_expected_signal": "release_gate_refreshed",
            "step_ready_follow_up_success_criterion": "ready_for_operator_review",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "evaluate_then_gate",
            "step_ready_priority": "next",
            "step_ready_badge": "next-evaluate-then-gate",
            "step_ready_group_id": "evaluate-and-gate",
            "step_ready_group_label": "Evaluate and gate",
            "step_ready_sort_key": "2-evaluate-then-gate",
            "step_ready_display_order": 2,
            "step_ready_lane": "upcoming",
            "step_ready_lane_label": "Upcoming",
            "artifact_state_reason": "pre_bundle_eval_report",
        }
    ]

def test_known_step_contract_defaults_cover_verify_step():
    assert _known_step_contract_defaults("verify") == {
        "default_command": "python tools/evaluate_avm.py",
        "default_follow_up_kind": "gate",
        "runnable_without_existing_artifact": "false",
        "stage_span": "evaluate_then_gate",
        "expected_signal": "eval_report_refreshed",
        "success_criterion": "ready_for_gate_rerun",
        "surface": "local_cli",
        "artifact_kind": "report",
        "artifact_owner": "evaluate_avm",
        "artifact": "datas/avm/eval_report.json",
        "artifact_check_timing": "post_step",
    }

def test_resolve_command_chain_artifacts_backfills_missing_command_for_known_steps_with_default_command(tmp_path: Path):
    eval_report_path = tmp_path / "avm" / "eval_report.json"
    _write_json(eval_report_path, {"metrics": {}})

    command_chain = [
        {
            "kind": "verify",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "stale",
            "artifact_resolved_path": str(eval_report_path),
            "artifact_check_command": f'Get-Content "{eval_report_path}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "stale",
            "artifact_freshness_reason": "pre_bundle_eval_report",
            "artifact_next_expected_transition": "stale->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_eval_rerun",
            "step_ready_recommended_action": "rerun_evaluate",
            "step_ready_action_command": "python tools/evaluate_avm.py",
            "step_ready_follow_up_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_expected_signal": "release_gate_refreshed",
            "step_ready_follow_up_success_criterion": "ready_for_operator_review",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "evaluate_then_gate",
            "step_ready_priority": "next",
            "step_ready_badge": "next-evaluate-then-gate",
            "step_ready_group_id": "evaluate-and-gate",
            "step_ready_group_label": "Evaluate and gate",
            "step_ready_sort_key": "2-evaluate-then-gate",
            "step_ready_display_order": 2,
            "step_ready_lane": "upcoming",
            "step_ready_lane_label": "Upcoming",
            "artifact_state_reason": "pre_bundle_eval_report",
        }
    ]

def test_resolve_command_chain_artifacts_treats_missing_config_artifact_as_runnable_for_preview(tmp_path: Path):
    command_chain = [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "missing",
            "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
            "artifact_check_timing": "pre_step",
            "artifact_freshness": "pending_write",
            "artifact_freshness_reason": "waiting_for_bundle_write",
            "artifact_next_expected_transition": "pending_write->current",
            "artifact_ready_for_step": True,
            "step_ready_summary": "ready_now",
            "step_ready_recommended_action": "proceed_now",
            "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "step_ready_follow_up_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "step_ready_follow_up_expected_signal": "config_patch_applied",
            "step_ready_follow_up_success_criterion": "ready_for_eval_rerun",
            "step_ready_terminal_outcome": "ready_for_eval_rerun",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "config_not_written_yet",
        }
    ]
