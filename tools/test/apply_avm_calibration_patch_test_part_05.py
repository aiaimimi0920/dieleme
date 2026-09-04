from tools.test.apply_avm_calibration_patch_test_context import *  # noqa: F401,F403


def test_resolve_command_chain_artifacts_current_config_branch_keeps_missing_preview_non_runnable(tmp_path: Path):
    config_path = tmp_path / "avm" / "config.json"
    _write_json(config_path, {"radius_km": 3.0})

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
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "preview",
            "command": "",
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
            "artifact_ready_for_step": False,
            "step_ready_summary": "unknown",
            "step_ready_recommended_action": "inspect_artifact_state",
            "step_ready_action_command": f'Get-Content "{config_path}"',
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_write_decision",
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

def test_resolve_command_chain_artifacts_current_config_branch_keeps_missing_write_non_runnable(tmp_path: Path):
    config_path = tmp_path / "avm" / "config.json"
    _write_json(config_path, {"radius_km": 3.0})

    command_chain = [
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
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "write",
            "command": "",
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
            "artifact_ready_for_step": False,
            "step_ready_summary": "unknown",
            "step_ready_recommended_action": "inspect_artifact_state",
            "step_ready_action_command": f'Get-Content "{config_path}"',
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
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

def test_resolve_command_chain_artifacts_sanitizes_preview_command_with_write_flag(tmp_path: Path):
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

def test_resolve_command_chain_artifacts_normalizes_write_command_with_missing_flag(tmp_path: Path):
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
    ]

def test_resolve_command_chain_artifacts_does_not_infer_preview_from_malformed_write_command(tmp_path: Path):
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
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
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
        "command": "",
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
        "artifact_ready_for_step": False,
        "step_ready_summary": "unknown",
        "step_ready_recommended_action": "inspect_artifact_state",
        "step_ready_action_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
        "step_ready_follow_up_command": "",
        "step_ready_follow_up_expected_signal": "",
        "step_ready_follow_up_success_criterion": "",
        "step_ready_terminal_outcome": "ready_for_write_decision",
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

def test_resolve_command_chain_artifacts_inferred_missing_write_artifact_uses_pending_write_semantics(tmp_path: Path):
    command_chain = [
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
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
    ]

def test_resolve_command_chain_artifacts_backfills_missing_step_contract_metadata_for_known_steps(tmp_path: Path):
    eval_report_path = tmp_path / "avm" / "eval_report.json"
    _write_json(eval_report_path, {"metrics": {}})

    command_chain = [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
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

def test_stage_semantics_defaults_cover_evaluate_then_gate():
    assert _stage_semantics_defaults("evaluate_then_gate") == {
        "priority": "next",
        "group_id": "evaluate-and-gate",
        "group_label": "Evaluate and gate",
        "badge": "next-evaluate-then-gate",
        "sort_key": "2-evaluate-then-gate",
        "display_order": 2,
        "lane": "upcoming",
        "lane_label": "Upcoming",
    }

def test_stage_semantics_defaults_cover_preview_then_split():
    assert _stage_semantics_defaults("preview_then_split") == {
        "priority": "now",
        "group_id": "preview-and-split",
        "group_label": "Preview and split",
        "badge": "now-preview-then-split",
        "sort_key": "0-preview-then-split",
        "display_order": 0,
        "lane": "current",
        "lane_label": "Current",
    }
