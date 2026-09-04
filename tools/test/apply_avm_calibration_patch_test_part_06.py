from tools.test.apply_avm_calibration_patch_test_context import *  # noqa: F401,F403


def test_summarize_bundle_command_summary_backfills_verify_and_gate_defaults_when_recommended_bundle_present():
    preview_command, write_command, verify_command, gate_command = summarize_bundle_command_summary(
        {
            "recommended_bundle": {
                "bundle_id": "temporal-only",
                "target_types": ["temporal"],
                "target_names": ["time_decay"],
            }
        }
    )

    assert preview_command == "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay"
    assert write_command == "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write"
    assert verify_command == "python tools/evaluate_avm.py"
    assert gate_command == "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report"

def test_summarize_patch_command_chain_dedupes_verify_step_in_safe_write_flow():
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --write",
        next_action_command_kind="write",
        follow_up_command="python tools/evaluate_avm.py",
        follow_up_command_kind="verify",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert [item["kind"] for item in chain] == ["write", "verify", "gate"]

def test_summarize_patch_follow_up_command_sanitizes_malformed_preview_before_synthesizing_write():
    follow_up = summarize_patch_follow_up_command(
        {"next_action": "preview_only_first"},
        preview_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        write_command="",
        verify_command="python tools/evaluate_avm.py",
    )

    assert follow_up == {
        "follow_up_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "follow_up_command_kind": "write",
    }

def test_summarize_patch_follow_up_command_returns_none_when_verify_command_missing_for_safe_write_flow():
    follow_up = summarize_patch_follow_up_command(
        {"next_action": "safe_to_write_then_verify"},
        preview_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        write_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        verify_command="",
    )

    assert follow_up == {
        "follow_up_command": "",
        "follow_up_command_kind": "none",
    }

def test_summarize_patch_follow_up_command_normalizes_malformed_explicit_write_command():
    follow_up = summarize_patch_follow_up_command(
        {"next_action": "preview_only_first"},
        preview_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        write_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        verify_command="python tools/evaluate_avm.py",
    )

    assert follow_up == {
        "follow_up_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "follow_up_command_kind": "write",
    }

def test_summarize_patch_next_action_command_sanitizes_malformed_preview_command():
    next_action_command = summarize_patch_next_action_command(
        {"next_action": "preview_only_first"},
        preview_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        write_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
    )

    assert next_action_command == {
        "next_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        "next_action_command_kind": "preview",
    }

def test_summarize_patch_next_action_command_normalizes_malformed_write_command():
    next_action_command = summarize_patch_next_action_command(
        {"next_action": "safe_to_write_then_verify"},
        preview_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        write_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
    )

    assert next_action_command == {
        "next_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "next_action_command_kind": "write",
    }

def test_summarize_patch_next_action_command_backfills_preview_from_write_when_preview_missing():
    next_action_command = summarize_patch_next_action_command(
        {"next_action": "preview_only_first"},
        preview_command="",
        write_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
    )

    assert next_action_command == {
        "next_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        "next_action_command_kind": "preview",
    }

def test_summarize_patch_next_action_command_backfills_write_from_preview_when_write_missing():
    next_action_command = summarize_patch_next_action_command(
        {"next_action": "safe_to_write_then_verify"},
        preview_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        write_command="",
    )

    assert next_action_command == {
        "next_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "next_action_command_kind": "write",
    }

def test_summarize_patch_next_action_command_does_not_infer_preview_from_malformed_write_alone():
    next_action_command = summarize_patch_next_action_command(
        {"next_action": "preview_only_first"},
        preview_command="",
        write_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
    )

    assert next_action_command == {
        "next_action_command": "",
        "next_action_command_kind": "preview",
    }

def test_summarize_patch_next_action_uses_changed_keys_when_count_missing():
    preview_payload = {
        "changed_keys": ["weighting.time_decay"],
    }

    risk_summary = summarize_patch_risk(preview_payload)
    next_action = summarize_patch_next_action(risk_summary, preview_payload)

    assert risk_summary == {
        "risk_level": "low",
        "risk_reasons": [],
    }
    assert next_action == {
        "next_action": "safe_to_write_then_verify",
        "next_action_reasons": ["low_risk_bundle"],
    }

def test_summarize_patch_command_chain_stops_at_preview_for_high_risk_split_flow():
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --target-type risk_flag",
        next_action_command_kind="preview",
        follow_up_command="",
        follow_up_command_kind="none",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert chain == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --target-type risk_flag",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]

def test_summarize_patch_command_chain_does_not_append_gate_when_verify_is_missing_in_safe_write_flow():
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        next_action_command_kind="write",
        follow_up_command="",
        follow_up_command_kind="none",
        verify_command="",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert chain == [
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
        }
    ]

def test_apply_command_chain_next_action_policy_relabels_high_risk_preview_stage(tmp_path: Path):
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --target-type risk_flag",
        next_action_command_kind="preview",
        follow_up_command="",
        follow_up_command_kind="none",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )
    resolved = resolve_command_chain_artifacts(chain, tmp_path)

    adjusted = apply_command_chain_next_action_policy(
        resolved,
        next_action="split_bundle_or_single_target_first",
    )

    assert adjusted == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --target-type risk_flag",
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
            "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --target-type risk_flag",
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_write_decision",
            "step_ready_stage_span": "preview_then_split",
            "step_ready_priority": "now",
            "step_ready_badge": "now-preview-then-split",
            "step_ready_group_id": "preview-and-split",
            "step_ready_group_label": "Preview and split",
            "step_ready_sort_key": "0-preview-then-split",
            "step_ready_display_order": 0,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "config_not_written_yet",
        }
    ]

def test_summarize_patch_command_chain_sanitizes_preview_command_with_write_flag():
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        next_action_command_kind="preview",
        follow_up_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        follow_up_command_kind="write",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert chain == [
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
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "unknown",
        },
    ]

def test_summarize_patch_command_chain_normalizes_write_command_with_missing_flag():
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        next_action_command_kind="write",
        follow_up_command="python tools/evaluate_avm.py",
        follow_up_command_kind="verify",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert chain == [
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
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "unknown",
        },
    ]

def test_summarize_patch_command_chain_backfills_write_from_preview_when_write_kind_is_present():
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        next_action_command_kind="preview",
        follow_up_command="",
        follow_up_command_kind="write",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert chain == [
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
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "unknown",
        },
    ]
