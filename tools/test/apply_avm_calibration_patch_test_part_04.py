from tools.test.apply_avm_calibration_patch_test_context import *  # noqa: F401,F403


def test_resolve_command_chain_artifacts_backfills_missing_write_command_from_preview(tmp_path: Path):
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
        },
        {
            "kind": "write",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved[1] == {
        "kind": "write",
        "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "expected_signal": "config_patch_applied",
        "success_criterion": "ready_for_eval_rerun",
        "surface": "local_cli",
        "artifact_kind": "config",
        "artifact_owner": "apply_avm_calibration_patch",
        "artifact": "datas/avm/config.json",
        "artifact_state": "missing",
        "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
        "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
        "artifact_check_timing": "post_step",
        "artifact_freshness": "pending_write",
        "artifact_freshness_reason": "waiting_for_bundle_write",
        "artifact_next_expected_transition": "pending_write->current",
        "artifact_ready_for_step": True,
        "step_ready_summary": "ready_now",
        "step_ready_recommended_action": "proceed_now",
        "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "step_ready_follow_up_command": "python tools/evaluate_avm.py",
        "step_ready_follow_up_expected_signal": "eval_report_refreshed",
        "step_ready_follow_up_success_criterion": "ready_for_gate_rerun",
        "step_ready_terminal_outcome": "ready_for_gate_rerun",
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

def test_resolve_command_chain_artifacts_backfills_missing_preview_command_from_write(tmp_path: Path):
    command_chain = [
        {
            "kind": "preview",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved[0] == {
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

def test_resolve_command_chain_artifacts_normalizes_preview_follow_up_when_write_item_is_malformed(tmp_path: Path):
    command_chain = [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved[0]["step_ready_follow_up_command"] == (
        "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write"
    )

def test_resolve_command_chain_artifacts_current_config_branch_keeps_preview_write_flow(tmp_path: Path):
    config_path = tmp_path / "avm" / "config.json"
    _write_json(config_path, {"radius_km": 3.0})

    command_chain = [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "write",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved[0] == {
        "kind": "preview",
        "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        "expected_signal": "inspect_changed_keys_and_risk_summary",
        "success_criterion": "ready_for_write_decision",
        "surface": "local_cli",
        "artifact_kind": "config",
        "artifact_owner": "apply_avm_calibration_patch",
        "artifact": "datas/avm/config.json",
        "artifact_state": "present",
        "artifact_resolved_path": str(config_path),
        "artifact_check_command": f'Get-Content "{config_path}"',
        "artifact_check_timing": "pre_step",
        "artifact_freshness": "current",
        "artifact_freshness_reason": "artifact_current",
        "artifact_next_expected_transition": "current->current",
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
        "artifact_state_reason": "artifact_present",
    }
    assert resolved[1] == {
        "kind": "write",
        "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "expected_signal": "config_patch_applied",
        "success_criterion": "ready_for_eval_rerun",
        "surface": "local_cli",
        "artifact_kind": "config",
        "artifact_owner": "apply_avm_calibration_patch",
        "artifact": "datas/avm/config.json",
        "artifact_state": "present",
        "artifact_resolved_path": str(config_path),
        "artifact_check_command": f'Get-Content "{config_path}"',
        "artifact_check_timing": "post_step",
        "artifact_freshness": "current",
        "artifact_freshness_reason": "artifact_current",
        "artifact_next_expected_transition": "current->current",
        "artifact_ready_for_step": True,
        "step_ready_summary": "ready_now",
        "step_ready_recommended_action": "proceed_now",
        "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "step_ready_follow_up_command": "python tools/evaluate_avm.py",
        "step_ready_follow_up_expected_signal": "eval_report_refreshed",
        "step_ready_follow_up_success_criterion": "ready_for_gate_rerun",
        "step_ready_terminal_outcome": "ready_for_gate_rerun",
        "step_ready_stage_span": "write_then_evaluate",
        "step_ready_priority": "now",
        "step_ready_badge": "now-write-then-evaluate",
        "step_ready_group_id": "bundle-write-and-evaluate",
        "step_ready_group_label": "Bundle write and evaluate",
        "step_ready_sort_key": "1-write-then-evaluate",
        "step_ready_display_order": 1,
        "step_ready_lane": "current",
        "step_ready_lane_label": "Current",
        "artifact_state_reason": "artifact_present",
    }

def test_resolve_command_chain_artifacts_current_config_branch_normalizes_write_command(tmp_path: Path):
    config_path = tmp_path / "avm" / "config.json"
    _write_json(config_path, {"radius_km": 3.0})

    command_chain = [
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "present",
            "artifact_resolved_path": str(config_path),
            "artifact_check_command": f'Get-Content "{config_path}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "current",
            "artifact_freshness_reason": "artifact_current",
            "artifact_next_expected_transition": "current->current",
            "artifact_ready_for_step": True,
            "step_ready_summary": "ready_now",
            "step_ready_recommended_action": "proceed_now",
            "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "step_ready_follow_up_command": "python tools/evaluate_avm.py",
            "step_ready_follow_up_expected_signal": "eval_report_refreshed",
            "step_ready_follow_up_success_criterion": "ready_for_gate_rerun",
            "step_ready_terminal_outcome": "ready_for_gate_rerun",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "artifact_present",
        }
    ]

def test_resolve_command_chain_artifacts_current_config_branch_sanitizes_preview_command(tmp_path: Path):
    config_path = tmp_path / "avm" / "config.json"
    _write_json(config_path, {"radius_km": 3.0})

    command_chain = [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
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
            "artifact_state": "present",
            "artifact_resolved_path": str(config_path),
            "artifact_check_command": f'Get-Content "{config_path}"',
            "artifact_check_timing": "pre_step",
            "artifact_freshness": "current",
            "artifact_freshness_reason": "artifact_current",
            "artifact_next_expected_transition": "current->current",
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
            "artifact_state_reason": "artifact_present",
        }
    ]
