from tools.test.avm_pipeline_test_context import *  # noqa: F401,F403


class AvmPipelineTestPart05:
    def test_run_calibration_stage_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump({"metrics": {}}, f, ensure_ascii=False)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)

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

    def test_run_calibration_stage_backfills_recommended_bundle_preview_command_from_write(self):
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
        }

        with mock.patch("tools.run_avm_pipeline.suggest_calibration_targets", return_value=synthetic_result):
            result = _run_calibration_stage(
                eval_report_path=eval_report_path,
                output_path=os.path.join(avm_dir, "calibration_targets.json"),
            )

        self.assertEqual(
            result["summary"]["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-name time_decay --target-name risk_discount_factor",
        )
        self.assertEqual(
            result["summary"]["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-name time_decay --target-name risk_discount_factor --write",
        )
        self.assertEqual(
            result["summary"]["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-name time_decay --target-name risk_discount_factor",
        )

    def test_run_calibration_stage_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
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
        self.assertEqual(result["summary"]["recommended_bundle_verify_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            result["summary"]["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(result["summary"]["recommended_bundle_follow_up_command"], "python tools/evaluate_avm.py")
        self.assertEqual(result["summary"]["recommended_bundle_follow_up_command_kind"], "verify")
        self.assertEqual(result["summary"]["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            result["summary"]["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(
            [item["kind"] for item in result["summary"]["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_run_calibration_stage_infers_summary_defaults_from_partial_suggestion_payload(self):
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

        partial_result = {
            "config_patch": {"weighting": {"time_decay": 0.72}},
            "temporal_targets": [
                {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
            ],
            "global_risk_targets": [],
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
        }

        with mock.patch("tools.run_avm_pipeline.suggest_calibration_targets", return_value=partial_result):
            result = _run_calibration_stage(
                eval_report_path=eval_report_path,
                output_path=os.path.join(avm_dir, "calibration_targets.json"),
            )

        self.assertTrue(result["summary"]["has_recommendations"])
        self.assertEqual(result["summary"]["global_risk_target_count"], 0)
        self.assertEqual(result["summary"]["risk_factor_target_count"], 0)
        self.assertEqual(result["summary"]["temporal_target_count"], 1)
        self.assertEqual(result["summary"]["strategy_target_count"], 0)
        self.assertEqual(result["summary"]["guidance_status"], "unknown")
        self.assertEqual(result["summary"]["top_target_name"], "time_decay")
        self.assertEqual(
            result["summary"]["recommended_bundle_next_action"],
            "safe_to_write_then_verify",
        )

    def test_run_calibration_stage_surfaces_coordinate_strategy_summary_from_eval_metrics(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "metrics": {
                        "coordinate_strategy_metrics": [
                            {
                                "group": "observed",
                                "sample_count": 10,
                                "mape_pct": 6.0,
                                "mean_bias_pct": 1.0,
                                "p90_ape_pct": 10.0,
                            },
                            {
                                "group": "district_centroid",
                                "sample_count": 4,
                                "mape_pct": 21.0,
                                "mean_bias_pct": 7.0,
                                "p90_ape_pct": 34.0,
                            },
                        ]
                    }
                },
                f,
                ensure_ascii=False,
            )
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

        result = _run_calibration_stage(
            eval_report_path=eval_report_path,
            output_path=os.path.join(avm_dir, "calibration_targets.json"),
        )

        self.assertEqual(result["summary"]["coordinate_strategy_watchlist"], ["district_centroid"])
        self.assertEqual(result["summary"]["top_coordinate_strategy_group"], "district_centroid")
