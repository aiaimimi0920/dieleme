from tools.test.avm_pipeline_test_context import *  # noqa: F401,F403


class AvmPipelineTestPart04:
    def test_run_gate_stage_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump({"metrics": {}}, f, ensure_ascii=False)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)

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
        self.assertEqual(result["summary"]["recommended_bundle_changed_key_count"], 1)
        self.assertEqual(result["summary"]["recommended_bundle_primary_change"], "weighting.time_decay")
        self.assertEqual(result["summary"]["recommended_bundle_risk_level"], "low")
        self.assertEqual(result["summary"]["recommended_bundle_next_action"], "safe_to_write_then_verify")

    def test_run_calibration_stage_tolerates_invalid_object_config_file(self):
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
                    "weighting": [],
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )

        synthetic_result = {
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
        }

        with mock.patch("tools.run_avm_pipeline.suggest_calibration_targets", return_value=synthetic_result):
            result = _run_calibration_stage(
                eval_report_path=eval_report_path,
                output_path=os.path.join(avm_dir, "calibration_targets.json"),
            )

        self.assertEqual(result["summary"]["top_target_name"], "time_decay")
        self.assertEqual(result["summary"]["recommended_bundle_changed_key_count"], 1)
        self.assertEqual(result["summary"]["recommended_bundle_primary_change"], "weighting.time_decay")
        self.assertEqual(result["summary"]["recommended_bundle_risk_level"], "low")
        self.assertEqual(result["summary"]["recommended_bundle_next_action"], "safe_to_write_then_verify")

    def test_run_gate_stage_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump({"metrics": {}}, f, ensure_ascii=False)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": -1,
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
        self.assertEqual(result["summary"]["recommended_bundle_changed_key_count"], 1)
        self.assertEqual(result["summary"]["recommended_bundle_primary_change"], "weighting.time_decay")
        self.assertEqual(result["summary"]["recommended_bundle_risk_level"], "low")
        self.assertEqual(result["summary"]["recommended_bundle_next_action"], "safe_to_write_then_verify")

    def test_run_calibration_stage_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump({"metrics": {}}, f, ensure_ascii=False)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("{")

        synthetic_result = {
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
        }

        with mock.patch("tools.run_avm_pipeline.suggest_calibration_targets", return_value=synthetic_result):
            result = _run_calibration_stage(
                eval_report_path=eval_report_path,
                output_path=os.path.join(avm_dir, "calibration_targets.json"),
            )

        self.assertEqual(result["summary"]["top_target_name"], "time_decay")
        self.assertEqual(result["summary"]["recommended_bundle_changed_key_count"], 1)
        self.assertEqual(result["summary"]["recommended_bundle_primary_change"], "weighting.time_decay")
        self.assertEqual(result["summary"]["recommended_bundle_risk_level"], "low")
        self.assertEqual(result["summary"]["recommended_bundle_next_action"], "safe_to_write_then_verify")

    def test_run_gate_stage_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump({"metrics": {}}, f, ensure_ascii=False)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("{")

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
        self.assertEqual(result["summary"]["recommended_bundle_changed_key_count"], 1)
        self.assertEqual(result["summary"]["recommended_bundle_primary_change"], "weighting.time_decay")
        self.assertEqual(result["summary"]["recommended_bundle_risk_level"], "low")
        self.assertEqual(result["summary"]["recommended_bundle_next_action"], "safe_to_write_then_verify")

    def test_run_calibration_stage_backfills_recommended_bundle_write_command_from_preview(self):
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

        synthetic_result = {
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
                "suggested_bundle_commands": [
                    "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay"
                ],
            },
            "guidance": {
                "status": "tune_temporal_decay",
                "priority": "medium",
                "recommended_actions": ["adjust_weighting_time_decay"],
                "top_reason": "time_decay",
            },
        }

        with mock.patch("tools.run_avm_pipeline.suggest_calibration_targets", return_value=synthetic_result):
            result = _run_calibration_stage(
                eval_report_path=eval_report_path,
                output_path=os.path.join(avm_dir, "calibration_targets.json"),
            )

        self.assertEqual(
            result["summary"]["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            result["summary"]["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(
            result["summary"]["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
