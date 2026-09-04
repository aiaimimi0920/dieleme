from tools.test.avm_pipeline_test_context import *  # noqa: F401,F403


class AvmPipelineTestPart03:
    def test_run_calibration_stage_stops_high_risk_chain_at_preview(self):
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

        synthetic_result = {
            "has_recommendations": True,
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
            "strategy_targets": [],
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
            "guidance": {
                "status": "tune_risk_factors",
                "priority": "high",
                "recommended_actions": ["split_bundle_or_single_target_first"],
                "top_reason": "multi_flag_bundle",
            },
        }

        with mock.patch("tools.run_avm_pipeline.suggest_calibration_targets", return_value=synthetic_result):
            result = _run_calibration_stage(
                eval_report_path=eval_report_path,
                output_path=os.path.join(avm_dir, "calibration_targets.json"),
            )

        self.assertEqual(result["summary"]["recommended_bundle_risk_level"], "high")
        self.assertIn("high_risk_bundle", result["summary"]["recommended_bundle_next_action_reasons"])
        self.assertEqual(result["summary"]["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(result["summary"]["recommended_bundle_next_action_command_kind"], "preview")
        self.assertEqual(result["summary"]["recommended_bundle_follow_up_command"], "")
        self.assertEqual(result["summary"]["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(len(result["summary"]["recommended_bundle_command_chain"]), 1)
        preview_step = result["summary"]["recommended_bundle_command_chain"][0]
        self.assertEqual(preview_step["kind"], "preview")
        self.assertEqual(preview_step["step_ready_follow_up_command"], "")
        self.assertEqual(preview_step["step_ready_follow_up_expected_signal"], "")
        self.assertEqual(preview_step["step_ready_follow_up_success_criterion"], "")
        self.assertEqual(preview_step["step_ready_terminal_outcome"], "ready_for_write_decision")
        self.assertEqual(preview_step["step_ready_stage_span"], "preview_then_split")
        self.assertEqual(preview_step["step_ready_badge"], "now-preview-then-split")
        self.assertEqual(preview_step["step_ready_group_id"], "preview-and-split")
        self.assertEqual(preview_step["step_ready_display_order"], 0)

    def test_run_gate_stage_uses_calibration_targets_fallback_when_gate_report_omits_bundle_context(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        calibration_targets_path = os.path.join(avm_dir, "calibration_targets.json")
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
        with open(calibration_targets_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "has_recommendations": True,
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
                    "strategy_targets": [],
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
                    "guidance": {
                        "status": "tune_risk_factors",
                        "priority": "high",
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "top_reason": "multi_flag_bundle",
                    },
                },
                f,
                ensure_ascii=False,
            )

        synthetic_gate = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": [],
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
        }

        with mock.patch("tools.run_avm_pipeline.generate_release_gate_report", return_value=synthetic_gate):
            result = _run_gate_stage(
                data_dir=self.data_dir,
                eval_report_path=eval_report_path,
                output_path=os.path.join(avm_dir, "release_gate.json"),
            )

        self.assertEqual(result["summary"]["recommended_bundle_risk_level"], "high")
        self.assertIn("high_risk_bundle", result["summary"]["recommended_bundle_next_action_reasons"])
        self.assertEqual(result["summary"]["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(result["summary"]["recommended_bundle_next_action_command_kind"], "preview")
        self.assertEqual(result["summary"]["recommended_bundle_follow_up_command"], "")
        self.assertEqual(result["summary"]["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(len(result["summary"]["recommended_bundle_command_chain"]), 1)
        preview_step = result["summary"]["recommended_bundle_command_chain"][0]
        self.assertEqual(preview_step["kind"], "preview")
        self.assertEqual(preview_step["step_ready_follow_up_command"], "")
        self.assertEqual(preview_step["step_ready_stage_span"], "preview_then_split")
        self.assertEqual(preview_step["step_ready_group_id"], "preview-and-split")
        self.assertEqual(preview_step["step_ready_display_order"], 0)

    def test_run_gate_stage_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        calibration_targets_path = os.path.join(avm_dir, "calibration_targets.json")
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
        with open(calibration_targets_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "has_recommendations": True,
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
                    "strategy_targets": [],
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
                    "guidance": {
                        "status": "tune_risk_factors",
                        "priority": "high",
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "top_reason": "multi_flag_bundle",
                    },
                },
                f,
                ensure_ascii=False,
            )

        synthetic_gate = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": [],
                "calibration_targets": {
                    "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                },
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
        }

        with mock.patch("tools.run_avm_pipeline.generate_release_gate_report", return_value=synthetic_gate):
            result = _run_gate_stage(
                data_dir=self.data_dir,
                eval_report_path=eval_report_path,
                output_path=os.path.join(avm_dir, "release_gate.json"),
            )

        self.assertEqual(result["summary"]["recommended_bundle_risk_level"], "high")
        self.assertIn("high_risk_bundle", result["summary"]["recommended_bundle_next_action_reasons"])
        self.assertEqual(result["summary"]["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(result["summary"]["recommended_bundle_next_action_command_kind"], "preview")
        self.assertEqual(result["summary"]["recommended_bundle_follow_up_command"], "")
        self.assertEqual(result["summary"]["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(len(result["summary"]["recommended_bundle_command_chain"]), 1)
        preview_step = result["summary"]["recommended_bundle_command_chain"][0]
        self.assertEqual(preview_step["kind"], "preview")
        self.assertEqual(preview_step["step_ready_follow_up_command"], "")
        self.assertEqual(preview_step["step_ready_stage_span"], "preview_then_split")
        self.assertEqual(preview_step["step_ready_group_id"], "preview-and-split")
        self.assertEqual(preview_step["step_ready_display_order"], 0)

    def test_run_gate_stage_uses_embedded_calibration_targets_when_file_is_missing(self):
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

        synthetic_gate = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": [],
                "top_coordinate_strategy_group": "district_centroid",
                "calibration_targets": {
                    "config_patch": {"weighting": {"time_decay": 0.72}},
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
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
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
        }

        with mock.patch("tools.run_avm_pipeline.generate_release_gate_report", return_value=synthetic_gate):
            result = _run_gate_stage(
                data_dir=self.data_dir,
                eval_report_path=eval_report_path,
                output_path=os.path.join(avm_dir, "release_gate.json"),
            )

        self.assertEqual(result["summary"]["top_target_name"], "time_decay")
        self.assertTrue(result["summary"]["has_recommendations"])
        self.assertEqual(result["summary"]["top_coordinate_strategy_group"], "district_centroid")
        self.assertEqual(result["summary"]["recommended_bundle_changed_key_count"], 1)
        self.assertEqual(result["summary"]["recommended_bundle_primary_change"], "weighting.time_decay")
        self.assertEqual(result["summary"]["recommended_bundle_risk_level"], "low")
        self.assertEqual(result["summary"]["global_risk_target_count"], 0)
        self.assertEqual(result["summary"]["risk_factor_target_count"], 0)
        self.assertEqual(result["summary"]["temporal_target_count"], 1)
        self.assertEqual(result["summary"]["strategy_target_count"], 0)
        self.assertEqual(result["summary"]["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            result["summary"]["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(result["summary"]["recommended_bundle_follow_up_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            [item["kind"] for item in result["summary"]["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )
        self.assertEqual(result["summary"]["guidance_status"], "tune_temporal_decay")
