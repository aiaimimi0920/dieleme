from tools.test.apply_avm_calibration_patch_test_context import *  # noqa: F401,F403


def test_resolve_command_chain_artifacts_does_not_mark_preview_ready_when_command_is_missing(tmp_path: Path):
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
    ]

def test_resolve_command_chain_artifacts_does_not_advertise_follow_up_for_non_runnable_write(tmp_path: Path):
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
            "artifact_state": "missing",
            "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
            "artifact_check_timing": "post_step",
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

def test_resolve_command_chain_artifacts_inferred_missing_verify_artifact_stays_blocked(tmp_path: Path):
    command_chain = [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "",
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
            "artifact_state": "not_ready_yet",
            "artifact_resolved_path": str(tmp_path / "avm" / "eval_report.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "eval_report.json"}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "pending_rerun",
            "artifact_freshness_reason": "waiting_for_eval_rerun",
            "artifact_next_expected_transition": "pending_rerun->current",
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
            "artifact_state_reason": "eval_not_rerun_yet",
        }
    ]

def test_resolve_command_chain_artifacts_explicit_missing_verify_artifact_stays_blocked(tmp_path: Path):
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
            "artifact_state": "not_ready_yet",
            "artifact_resolved_path": str(tmp_path / "avm" / "eval_report.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "eval_report.json"}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "pending_rerun",
            "artifact_freshness_reason": "waiting_for_eval_rerun",
            "artifact_next_expected_transition": "pending_rerun->current",
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
            "artifact_state_reason": "eval_not_rerun_yet",
        }
    ]

def test_resolve_command_chain_artifacts_inferred_missing_gate_artifact_stays_blocked(tmp_path: Path):
    command_chain = [
        {
            "kind": "gate",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "not_ready_yet",
            "artifact_resolved_path": str(tmp_path / "avm" / "release_gate.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "release_gate.json"}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "pending_rerun",
            "artifact_freshness_reason": "waiting_for_gate_rerun",
            "artifact_next_expected_transition": "pending_rerun->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_gate_rerun",
            "step_ready_recommended_action": "rerun_release_gate",
            "step_ready_action_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "gate_only",
            "step_ready_priority": "later",
            "step_ready_badge": "later-gate-only",
            "step_ready_group_id": "gate-rerun-only",
            "step_ready_group_label": "Gate rerun only",
            "step_ready_sort_key": "3-gate-only",
            "step_ready_display_order": 3,
            "step_ready_lane": "deferred",
            "step_ready_lane_label": "Deferred",
            "artifact_state_reason": "gate_not_rerun_yet",
        }
    ]

def test_resolve_command_chain_artifacts_explicit_missing_gate_artifact_stays_blocked(tmp_path: Path):
    command_chain = [
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "not_ready_yet",
            "artifact_resolved_path": str(tmp_path / "avm" / "release_gate.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "release_gate.json"}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "pending_rerun",
            "artifact_freshness_reason": "waiting_for_gate_rerun",
            "artifact_next_expected_transition": "pending_rerun->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_gate_rerun",
            "step_ready_recommended_action": "rerun_release_gate",
            "step_ready_action_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "gate_only",
            "step_ready_priority": "later",
            "step_ready_badge": "later-gate-only",
            "step_ready_group_id": "gate-rerun-only",
            "step_ready_group_label": "Gate rerun only",
            "step_ready_sort_key": "3-gate-only",
            "step_ready_display_order": 3,
            "step_ready_lane": "deferred",
            "step_ready_lane_label": "Deferred",
            "artifact_state_reason": "gate_not_rerun_yet",
        }
    ]

def test_resolve_command_chain_artifacts_existing_gate_artifact_stays_stale(tmp_path: Path):
    gate_report_path = tmp_path / "avm" / "release_gate.json"
    _write_json(gate_report_path, {"evaluation": {}})

    command_chain = [
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "stale",
            "artifact_resolved_path": str(gate_report_path),
            "artifact_check_command": f'Get-Content "{gate_report_path}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "stale",
            "artifact_freshness_reason": "pre_bundle_gate_report",
            "artifact_next_expected_transition": "stale->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_gate_rerun",
            "step_ready_recommended_action": "rerun_release_gate",
            "step_ready_action_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "gate_only",
            "step_ready_priority": "later",
            "step_ready_badge": "later-gate-only",
            "step_ready_group_id": "gate-rerun-only",
            "step_ready_group_label": "Gate rerun only",
            "step_ready_sort_key": "3-gate-only",
            "step_ready_display_order": 3,
            "step_ready_lane": "deferred",
            "step_ready_lane_label": "Deferred",
            "artifact_state_reason": "pre_bundle_gate_report",
        }
    ]
