from tools.test.avm_pipeline_test_context import *  # noqa: F401,F403


class AvmPipelineTestPart06:
    def test_run_calibration_stage_surfaces_recommended_bundle_summary(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "metrics": {
                        "risk_flag_metrics": [
                            {
                                "group": "is_occupied",
                                "sample_count": 8,
                                "mape_pct": 18.0,
                                "mean_bias_pct": 9.0,
                                "p90_ape_pct": 30.0,
                            },
                            {
                                "group": "has_long_lease",
                                "sample_count": 6,
                                "mape_pct": 16.0,
                                "mean_bias_pct": 7.0,
                                "p90_ape_pct": 26.0,
                            },
                        ],
                        "valuation_mode_metrics": [
                            {
                                "group": "historical_strict",
                                "sample_count": 12,
                                "mape_pct": 18.0,
                                "mean_bias_pct": 8.0,
                                "p90_ape_pct": 30.0,
                            },
                            {
                                "group": "current_market",
                                "sample_count": 12,
                                "mape_pct": 8.0,
                                "mean_bias_pct": 2.0,
                                "p90_ape_pct": 16.0,
                            },
                        ],
                    }
                },
                f,
                ensure_ascii=False,
            )

        result = _run_calibration_stage(
            eval_report_path=eval_report_path,
            output_path=os.path.join(avm_dir, "calibration_targets.json"),
        )

        self.assertEqual(result["summary"]["recommended_bundle_id"], "temporal-global-risk")
        self.assertEqual(result["summary"]["recommended_bundle_changed_key_count"], 2)
        self.assertEqual(result["summary"]["recommended_bundle_primary_change"], "risk_discount_factor")
        self.assertEqual(result["summary"]["recommended_bundle_secondary_changes"], ["weighting.time_decay"])
        self.assertEqual(
            result["summary"]["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        )
        self.assertEqual(
            result["summary"]["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        )
        self.assertEqual(
            result["summary"]["recommended_bundle_verify_command"],
            "python tools/evaluate_avm.py",
        )
        self.assertEqual(
            result["summary"]["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(result["summary"]["recommended_bundle_risk_level"], "medium")
        self.assertIn("multiple_changed_keys", result["summary"]["recommended_bundle_risk_reasons"])
        self.assertIn("cross_knob_bundle", result["summary"]["recommended_bundle_risk_reasons"])
        self.assertEqual(result["summary"]["recommended_bundle_next_action"], "preview_only_first")
        self.assertIn("medium_risk_bundle", result["summary"]["recommended_bundle_next_action_reasons"])
        self.assertEqual(
            result["summary"]["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        )
        self.assertEqual(result["summary"]["recommended_bundle_next_action_command_kind"], "preview")
        self.assertEqual(
            result["summary"]["recommended_bundle_follow_up_command"],
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        )
        self.assertEqual(result["summary"]["recommended_bundle_follow_up_command_kind"], "write")
        self.assertEqual(
            result["summary"]["recommended_bundle_command_chain"],
            [
                {
                    "kind": "preview",
                    "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
                    "expected_signal": "inspect_changed_keys_and_risk_summary",
                    "success_criterion": "ready_for_write_decision",
                    "surface": "local_cli",
                    "artifact_kind": "config",
                    "artifact_owner": "apply_avm_calibration_patch",
                    "artifact": "datas/avm/config.json",
                    "artifact_resolved_path": os.path.join(self.data_dir, "avm", "config.json"),
                    "artifact_check_command": f'Get-Content "{os.path.join(self.data_dir, "avm", "config.json")}"',
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
                     "artifact_state": "missing",
                     "artifact_state_reason": "config_not_written_yet",
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
                    "artifact_resolved_path": os.path.join(self.data_dir, "avm", "config.json"),
                    "artifact_check_command": f'Get-Content "{os.path.join(self.data_dir, "avm", "config.json")}"',
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
                     "artifact_state": "missing",
                     "artifact_state_reason": "config_not_written_yet",
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
                    "artifact_resolved_path": os.path.join(self.data_dir, "avm", "eval_report.json"),
                    "artifact_check_command": f'Get-Content "{os.path.join(self.data_dir, "avm", "eval_report.json")}"',
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
                     "artifact_state": "stale",
                     "artifact_state_reason": "pre_bundle_eval_report",
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
                    "artifact_resolved_path": os.path.join(self.data_dir, "avm", "release_gate.json"),
                    "artifact_check_command": f'Get-Content "{os.path.join(self.data_dir, "avm", "release_gate.json")}"',
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
                     "artifact_state": "not_ready_yet",
                     "artifact_state_reason": "gate_not_rerun_yet",
                 },
            ],
        )
