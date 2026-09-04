from tools.test.avm_pipeline_test_context import *  # noqa: F401,F403


class AvmPipelineTestPart02:
    def test_pipeline_calibration_writer_backfills_recommended_bundle_preview_command_from_write(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump({"metrics": {}}, f, ensure_ascii=False)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )

        result = _write_calibration_targets(
            eval_report_path,
            os.path.join(avm_dir, "calibration_targets.json"),
            lambda _metrics: {
                "has_recommendations": True,
                "config_patch": {
                    "weighting": {"time_decay": 0.72},
                    "risk_discount_factor": 0.99,
                },
                "temporal_targets": [
                    {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
                ],
                "global_risk_targets": [
                    {
                        "target_type": "global_risk",
                        "name": "risk_discount_factor",
                        "suggested_next_value": 0.99,
                    }
                ],
                "risk_factor_targets": [],
                "strategy_targets": [],
                "top_calibration_target": {"target_type": "temporal", "name": "time_decay"},
                "top_calibration_target_hint": {
                    "status": "tune_temporal_decay",
                    "playbook_id": "tune-temporal-decay",
                    "recommended_bundle": {
                        "bundle_id": "temporal-global-risk",
                        "target_types": ["temporal", "global_risk"],
                        "target_names": ["time_decay", "risk_discount_factor"],
                    },
                    "suggested_bundle_commands": [
                        "",
                        "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-name time_decay --target-name risk_discount_factor --write",
                    ],
                },
                "guidance": {
                    "status": "tune_temporal_decay",
                    "priority": "medium",
                    "recommended_actions": ["adjust_weighting_time_decay"],
                    "top_reason": "time_decay",
                },
            },
        )

        self.assertEqual(
            result["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-name time_decay --target-name risk_discount_factor",
        )
        self.assertEqual(
            result["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-name time_decay --target-name risk_discount_factor --write",
        )
        self.assertEqual(
            result["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-name time_decay --target-name risk_discount_factor",
        )

    def test_pipeline_calibration_writer_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump({"metrics": {}}, f, ensure_ascii=False)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )

        result = _write_calibration_targets(
            eval_report_path,
            os.path.join(avm_dir, "calibration_targets.json"),
            lambda _metrics: {
                "has_recommendations": True,
                "config_patch": {"weighting": {"time_decay": 0.72}},
                "temporal_targets": [
                    {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
                ],
                "global_risk_targets": [],
                "risk_factor_targets": [],
                "strategy_targets": [],
                "top_calibration_target": {"target_type": "temporal", "name": "time_decay"},
                "top_calibration_target_hint": {
                    "status": "tune_temporal_decay",
                    "playbook_id": "tune-temporal-decay",
                    "recommended_bundle": {
                        "bundle_id": "temporal-only",
                        "target_types": ["temporal"],
                        "target_names": ["time_decay"],
                    },
                },
                "guidance": {
                    "status": "tune_temporal_decay",
                    "priority": "medium",
                    "recommended_actions": ["adjust_weighting_time_decay"],
                    "top_reason": "time_decay",
                },
            },
        )

        self.assertEqual(
            result["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            result["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(result["recommended_bundle_verify_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            result["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(result["recommended_bundle_follow_up_command"], "python tools/evaluate_avm.py")
        self.assertEqual(result["recommended_bundle_follow_up_command_kind"], "verify")
        self.assertEqual(result["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            result["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(
            [item["kind"] for item in result["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_pipeline_calibration_writer_prefers_computed_bundle_summary_over_conflicting_suggestion_fields(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump({"metrics": {}}, f, ensure_ascii=False)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )

        result = _write_calibration_targets(
            eval_report_path,
            os.path.join(avm_dir, "calibration_targets.json"),
            lambda _metrics: {
                "has_recommendations": True,
                "config_patch": {"weighting": {"time_decay": 0.72}},
                "temporal_targets": [
                    {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
                ],
                "global_risk_targets": [],
                "risk_factor_targets": [],
                "strategy_targets": [],
                "top_calibration_target": {"target_type": "temporal", "name": "time_decay"},
                "top_calibration_target_hint": {
                    "status": "tune_temporal_decay",
                    "playbook_id": "tune-temporal-decay",
                    "recommended_bundle": {
                        "bundle_id": "temporal-only",
                        "target_types": ["temporal"],
                        "target_names": ["time_decay"],
                    },
                },
                "recommended_bundle_preview_command": "python bogus_preview.py",
                "recommended_bundle_write_command": "python bogus_write.py --write",
                "recommended_bundle_verify_command": "python bogus_verify.py",
                "recommended_bundle_gate_command": "python bogus_gate.py",
                "recommended_bundle_risk_level": "high",
                "recommended_bundle_next_action": "no_action_required",
                "recommended_bundle_next_action_command": "python bogus_next.py",
                "recommended_bundle_follow_up_command": "python bogus_follow.py",
                "recommended_bundle_command_chain": [{"kind": "preview", "command": "python bogus_preview.py"}],
                "guidance": {
                    "status": "tune_temporal_decay",
                    "priority": "medium",
                    "recommended_actions": ["adjust_weighting_time_decay"],
                    "top_reason": "time_decay",
                },
            },
        )

        self.assertEqual(
            result["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            result["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(result["recommended_bundle_verify_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            result["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(result["recommended_bundle_risk_level"], "low")
        self.assertEqual(result["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            result["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(result["recommended_bundle_follow_up_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            [item["kind"] for item in result["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_pipeline_calibration_writer_normalizes_partial_suggestion_payload(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        output_path = os.path.join(avm_dir, "calibration_targets.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump({"metrics": {}}, f, ensure_ascii=False)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )

        result = _write_calibration_targets(
            eval_report_path,
            output_path,
            lambda _metrics: {
                "config_patch": {"weighting": {"time_decay": 0.72}},
                "temporal_targets": [
                    {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
                ],
                "top_calibration_target": {"target_type": "temporal", "name": "time_decay"},
                "top_calibration_target_hint": {
                    "status": "tune_temporal_decay",
                    "playbook_id": "tune-temporal-decay",
                    "recommended_bundle": {
                        "bundle_id": "temporal-only",
                        "target_types": ["temporal"],
                        "target_names": ["time_decay"],
                    },
                },
            },
        )

        self.assertTrue(result["has_recommendations"])
        self.assertEqual(result["global_risk_targets"], [])
        self.assertEqual(result["risk_factor_targets"], [])
        self.assertEqual(result["strategy_targets"], [])
        self.assertEqual(result["guidance"], {})
        written_payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
        self.assertTrue(written_payload["has_recommendations"])
        self.assertEqual(written_payload["global_risk_targets"], [])
        self.assertEqual(written_payload["risk_factor_targets"], [])
        self.assertEqual(written_payload["strategy_targets"], [])
        self.assertEqual(written_payload["guidance"], {})

    def test_pipeline_calibration_writer_stops_high_risk_chain_at_preview(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump({"metrics": {}}, f, ensure_ascii=False)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {"is_occupied": 0.8},
                },
                f,
                ensure_ascii=False,
            )

        result = _write_calibration_targets(
            eval_report_path,
            os.path.join(avm_dir, "calibration_targets.json"),
            lambda _metrics: {
                "config_patch": {
                    "weighting": {"time_decay": 0.72},
                    "risk_discount_factor": 0.99,
                    "risk_factor_overrides": {"is_occupied": 0.5},
                },
                "temporal_targets": [
                    {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
                ],
                "global_risk_targets": [
                    {
                        "target_type": "global_risk",
                        "name": "risk_discount_factor",
                        "suggested_next_value": 0.99,
                    }
                ],
                "risk_factor_targets": [
                    {
                        "target_type": "risk_flag",
                        "name": "is_occupied",
                        "suggested_next_factor": 0.5,
                    }
                ],
                "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                "top_calibration_target_hint": {
                    "status": "tune_risk_factors",
                    "playbook_id": "split-bundle-or-single-target-first",
                    "recommended_bundle": {
                        "bundle_id": "temporal-global-risk-risk-flag",
                        "target_types": ["temporal", "global_risk", "risk_flag"],
                        "target_names": ["time_decay", "risk_discount_factor", "is_occupied"],
                    },
                    "suggested_bundle_commands": [
                        "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
                        "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write",
                        "python tools/evaluate_avm.py",
                        "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
                    ],
                },
            },
        )

        self.assertEqual(result["recommended_bundle_risk_level"], "high")
        self.assertIn("high_risk_bundle", result["recommended_bundle_next_action_reasons"])
        self.assertEqual(result["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(result["recommended_bundle_next_action_command_kind"], "preview")
        self.assertEqual(result["recommended_bundle_follow_up_command"], "")
        self.assertEqual(result["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(len(result["recommended_bundle_command_chain"]), 1)
        preview_step = result["recommended_bundle_command_chain"][0]
        self.assertEqual(preview_step["kind"], "preview")
        self.assertEqual(preview_step["step_ready_follow_up_command"], "")
        self.assertEqual(preview_step["step_ready_follow_up_expected_signal"], "")
        self.assertEqual(preview_step["step_ready_follow_up_success_criterion"], "")
        self.assertEqual(preview_step["step_ready_terminal_outcome"], "ready_for_write_decision")
        self.assertEqual(preview_step["step_ready_stage_span"], "preview_then_split")
        self.assertEqual(preview_step["step_ready_badge"], "now-preview-then-split")
        self.assertEqual(preview_step["step_ready_group_id"], "preview-and-split")
        self.assertEqual(preview_step["step_ready_display_order"], 0)
