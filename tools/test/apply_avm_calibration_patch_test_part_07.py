from tools.test.apply_avm_calibration_patch_test_context import *  # noqa: F401,F403


def test_summarize_patch_command_chain_backfills_preview_from_write_when_preview_kind_is_present():
    chain = summarize_patch_command_chain(
        next_action_command="",
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

def test_summarize_patch_command_chain_backfills_preview_from_malformed_write_when_preview_kind_is_present():
    chain = summarize_patch_command_chain(
        next_action_command="",
        next_action_command_kind="preview",
        follow_up_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
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
