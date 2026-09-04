from tools.test.avm_pipeline_test_context import *  # noqa: F401,F403


class AvmPipelineTestPart01:
    def test_subtask_functions(self):
        canonical_dir = os.path.join(self.data_dir, "canonical")
        avm_dir = os.path.join(self.data_dir, "avm")

        c = build_canonical_dataset(data_dir=self.data_dir, output_dir=canonical_dir)
        self.assertTrue(os.path.exists(c["canonical_path"]))

        f = build_avm_features(
            canonical_path=os.path.join(canonical_dir, "canonical.jsonl"),
            output_path=os.path.join(avm_dir, "features.jsonl"),
            stats_path=os.path.join(avm_dir, "feature_stats.json"),
        )
        self.assertTrue(os.path.exists(f["features_path"]))

        a = generate_avm_alerts(
            data_dir=self.data_dir,
            output_path=os.path.join(avm_dir, "alerts.json"),
            threshold=0.01,
            limit=20,
        )
        self.assertTrue(os.path.exists(a["output_path"]))

    def test_unified_run_sync_and_async(self):
        mgr = AVMPipelineManager(data_dir=self.data_dir)
        config = AVMPipelineConfig(data_dir=self.data_dir, alerts_threshold=0.01, alerts_limit=20)

        sync_result = mgr.run(async_mode=False, config=config)
        self.assertEqual(sync_result["status"], "completed")
        self.assertFalse(sync_result["state"]["running"])
        self.assertEqual(sync_result["state"]["config"]["alerts_threshold"], 0.01)
        self.assertTrue(sync_result["state"]["merge_check"]["is_fully_merged"])

        merge_info = mgr.verify_merge_completeness()
        self.assertTrue(merge_info["is_fully_merged"])
        self.assertEqual(merge_info["missing_subtasks"], [])
        self.assertIn("evaluate_avm", merge_info["expected_subtasks"])
        self.assertIn("suggest_calibration_targets", merge_info["expected_subtasks"])
        self.assertIn("generate_release_gate_report", merge_info["expected_subtasks"])

        start = mgr.run(async_mode=True, config=config)
        self.assertIn(start["status"], {"started", "already_running"})
        for _ in range(200):
            state = mgr.status()
            if not state.get("running"):
                break
            time.sleep(0.01)
        self.assertFalse(mgr.status().get("running"))

    def test_run_alert_stage_blocks_manual_review_and_risk_validation(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        predictions_path = os.path.join(avm_dir, "predictions.jsonl")
        with open(predictions_path, "w", encoding="utf-8") as fout:
            fout.write(
                json.dumps(
                    {
                        "item_id": "1001",
                        "starting_price": 900000.0,
                        "prediction": {
                            "predicted_price": 1500000.0,
                            "confidence": 0.45,
                            "comparable_count": 2,
                            "manual_review_recommended": True,
                            "risk_validation": {
                                "ok": False,
                                "missing_required_count": 3,
                                "invalid_field_count": 0,
                            },
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        result = _run_alert_stage(
            predictions_path=predictions_path,
            output_path=os.path.join(avm_dir, "alerts.json"),
            threshold=0.2,
        )

        self.assertEqual(result["summary"]["alerts"], 0)
        self.assertEqual(result["summary"]["blocked_reason_counts"]["manual_review_required"], 1)
        self.assertEqual(result["summary"]["blocked_reason_counts"]["risk_validation_incomplete"], 1)

    def test_run_pipeline_includes_evaluate_and_calibration_stages(self):
        result = run_pipeline(data_dir=self.data_dir, alerts_threshold=0.01, predict_limit=20)
        stage_names = [stage["name"] for stage in result["stages"]]

        self.assertIn("evaluate", stage_names)
        self.assertIn("calibration", stage_names)
        self.assertIn("gate", stage_names)
        evaluate_stage = next(stage for stage in result["stages"] if stage["name"] == "evaluate")
        calibration_stage = next(stage for stage in result["stages"] if stage["name"] == "calibration")
        gate_stage = next(stage for stage in result["stages"] if stage["name"] == "gate")
        self.assertIn("backtest_sample_count", evaluate_stage["summary"])
        self.assertIn("valuation_mode_sample_counts", evaluate_stage["summary"])
        self.assertIn("has_recommendations", calibration_stage["summary"])
        self.assertIn("global_risk_target_count", calibration_stage["summary"])
        self.assertIn("risk_factor_target_count", calibration_stage["summary"])
        self.assertIn("temporal_target_count", calibration_stage["summary"])
        self.assertIn("strategy_target_count", calibration_stage["summary"])
        self.assertIn("guidance_status", calibration_stage["summary"])
        self.assertIn("coordinate_strategy_watchlist", calibration_stage["summary"])
        self.assertIn("top_coordinate_strategy_group", calibration_stage["summary"])
        self.assertIn("top_target_name", calibration_stage["summary"])
        self.assertIn("top_target_hint_status", calibration_stage["summary"])
        self.assertIn("top_target_playbook_id", calibration_stage["summary"])
        self.assertIn("recommended_bundle_id", calibration_stage["summary"])
        self.assertIn("recommended_bundle_changed_key_count", calibration_stage["summary"])
        self.assertIn("recommended_bundle_primary_change", calibration_stage["summary"])
        self.assertIn("recommended_bundle_secondary_changes", calibration_stage["summary"])
        self.assertIn("recommended_bundle_preview_command", calibration_stage["summary"])
        self.assertIn("recommended_bundle_write_command", calibration_stage["summary"])
        self.assertIn("recommended_bundle_verify_command", calibration_stage["summary"])
        self.assertIn("recommended_bundle_gate_command", calibration_stage["summary"])
        self.assertIn("recommended_bundle_risk_level", calibration_stage["summary"])
        self.assertIn("recommended_bundle_risk_reasons", calibration_stage["summary"])
        self.assertIn("recommended_bundle_next_action", calibration_stage["summary"])
        self.assertIn("recommended_bundle_next_action_reasons", calibration_stage["summary"])
        self.assertIn("recommended_bundle_next_action_command", calibration_stage["summary"])
        self.assertIn("recommended_bundle_next_action_command_kind", calibration_stage["summary"])
        self.assertIn("recommended_bundle_follow_up_command", calibration_stage["summary"])
        self.assertIn("recommended_bundle_follow_up_command_kind", calibration_stage["summary"])
        self.assertIn("recommended_bundle_command_chain", calibration_stage["summary"])
        self.assertIn("pass", gate_stage["summary"])
        self.assertIn("guidance_status", gate_stage["summary"])
        self.assertIn("coordinate_strategy_watchlist", gate_stage["summary"])
        self.assertIn("top_coordinate_strategy_group", gate_stage["summary"])
        self.assertIn("top_target_name", gate_stage["summary"])
        self.assertIn("top_target_hint_status", gate_stage["summary"])
        self.assertIn("top_target_playbook_id", gate_stage["summary"])
        self.assertIn("recommended_bundle_id", gate_stage["summary"])
        self.assertIn("recommended_bundle_changed_key_count", gate_stage["summary"])
        self.assertIn("recommended_bundle_primary_change", gate_stage["summary"])
        self.assertIn("recommended_bundle_secondary_changes", gate_stage["summary"])
        self.assertIn("recommended_bundle_preview_command", gate_stage["summary"])
        self.assertIn("recommended_bundle_write_command", gate_stage["summary"])
        self.assertIn("recommended_bundle_verify_command", gate_stage["summary"])
        self.assertIn("recommended_bundle_gate_command", gate_stage["summary"])
        self.assertIn("recommended_bundle_risk_level", gate_stage["summary"])
        self.assertIn("recommended_bundle_risk_reasons", gate_stage["summary"])
        self.assertIn("recommended_bundle_next_action", gate_stage["summary"])
        self.assertIn("recommended_bundle_next_action_reasons", gate_stage["summary"])
        self.assertIn("recommended_bundle_next_action_command", gate_stage["summary"])
        self.assertIn("recommended_bundle_next_action_command_kind", gate_stage["summary"])
        self.assertIn("recommended_bundle_follow_up_command", gate_stage["summary"])
        self.assertIn("recommended_bundle_follow_up_command_kind", gate_stage["summary"])
        self.assertIn("recommended_bundle_command_chain", gate_stage["summary"])
        self.assertIn("has_recommendations", gate_stage["summary"])
        self.assertIn("global_risk_target_count", gate_stage["summary"])
        self.assertIn("risk_factor_target_count", gate_stage["summary"])
        self.assertIn("temporal_target_count", gate_stage["summary"])
        self.assertIn("strategy_target_count", gate_stage["summary"])

    def test_run_pipeline_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)

        result = run_pipeline(data_dir=self.data_dir, alerts_threshold=0.01, predict_limit=20)

        calibration_stage = next(stage for stage in result["stages"] if stage["name"] == "calibration")
        gate_stage = next(stage for stage in result["stages"] if stage["name"] == "gate")
        self.assertIn(calibration_stage["summary"]["recommended_bundle_risk_level"], {"none", "low", "medium", "high"})
        self.assertIn(gate_stage["summary"]["recommended_bundle_risk_level"], {"none", "low", "medium", "high"})
        self.assertIn("recommended_bundle_next_action", calibration_stage["summary"])
        self.assertIn("recommended_bundle_next_action", gate_stage["summary"])

    def test_run_pipeline_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            f.write("{")

        result = run_pipeline(data_dir=self.data_dir, alerts_threshold=0.01, predict_limit=20)

        calibration_stage = next(stage for stage in result["stages"] if stage["name"] == "calibration")
        gate_stage = next(stage for stage in result["stages"] if stage["name"] == "gate")
        self.assertIn(calibration_stage["summary"]["recommended_bundle_risk_level"], {"none", "low", "medium", "high"})
        self.assertIn(gate_stage["summary"]["recommended_bundle_risk_level"], {"none", "low", "medium", "high"})
        self.assertIn("recommended_bundle_next_action", calibration_stage["summary"])
        self.assertIn("recommended_bundle_next_action", gate_stage["summary"])

    def test_pipeline_calibration_writer_surfaces_top_target_hint(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "metrics": {
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
                        ]
                    }
                },
                f,
                ensure_ascii=False,
            )

        result = _write_calibration_targets(
            eval_report_path,
            os.path.join(avm_dir, "calibration_targets.json"),
            lambda metrics: __import__("tools.suggest_avm_calibration_targets", fromlist=["suggest_calibration_targets"]).suggest_calibration_targets(metrics),
        )

        self.assertEqual(result["top_target_name"], "time_decay")
        self.assertEqual(result["top_target_hint_status"], "tune_temporal_decay")
        self.assertEqual(result["top_target_playbook_id"], "tune-temporal-decay")
        self.assertEqual(result["recommended_bundle_id"], "")
        self.assertEqual(result["recommended_bundle_changed_key_count"], 0)
        self.assertEqual(result["recommended_bundle_primary_change"], "")
        self.assertEqual(result["recommended_bundle_secondary_changes"], [])
        self.assertEqual(result["recommended_bundle_risk_level"], "none")
        self.assertEqual(result["recommended_bundle_risk_reasons"], [])
        self.assertEqual(result["recommended_bundle_next_action"], "no_action_required")
        self.assertEqual(result["recommended_bundle_next_action_reasons"], [])
        self.assertEqual(result["recommended_bundle_next_action_command"], "")
        self.assertEqual(result["recommended_bundle_next_action_command_kind"], "none")
        self.assertEqual(result["recommended_bundle_follow_up_command"], "")
        self.assertEqual(result["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(result["recommended_bundle_command_chain"], [])
        self.assertEqual(result["recommended_bundle_next_action_command"], "")
        self.assertEqual(result["recommended_bundle_next_action_command_kind"], "none")

    def test_pipeline_calibration_writer_backfills_recommended_bundle_write_command_from_preview(self):
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
        self.assertEqual(
            result["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )

    def test_pipeline_calibration_writer_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        eval_report_path = os.path.join(avm_dir, "eval_report.json")
        config_path = os.path.join(avm_dir, "config.json")
        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump({"metrics": {}}, f, ensure_ascii=False)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)

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

        self.assertEqual(result["top_target_name"], "time_decay")
        self.assertEqual(result["recommended_bundle_changed_key_count"], 1)
        self.assertEqual(result["recommended_bundle_primary_change"], "weighting.time_decay")
        self.assertEqual(result["recommended_bundle_risk_level"], "low")
        self.assertEqual(result["recommended_bundle_next_action"], "safe_to_write_then_verify")
