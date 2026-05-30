import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from src.avm.pipeline import AVMPipelineManager, AVMPipelineConfig, _write_calibration_targets
from tools.build_canonical_dataset import build_canonical_dataset
from tools.build_avm_features import build_avm_features
from tools.generate_avm_alerts import generate_avm_alerts
from tools.run_avm_pipeline import _run_alert_stage, _run_calibration_stage, _run_gate_stage, run_pipeline


class TestAVMPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp.name, "datas")
        os.makedirs(self.data_dir, exist_ok=True)
        with open(os.path.join(self.data_dir, "2024-01-01.json"), "w", encoding="utf-8") as f:
            json.dump([
                {
                    "id": "1001",
                    "成交价格": "120万",
                    "起拍价格": "100万",
                    "建筑面积": "80㎡",
                    "交易时间": "2024-01-01",
                    "城市": "上海市",
                    "区": "浦东新区",
                    "所属小区": "测试小区",
                    "最靠近商圈": "张江",
                    "纬度": 31.2,
                    "经度": 121.5,
                }
            ], f, ensure_ascii=False)

    def tearDown(self):
        self.tmp.cleanup()

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


if __name__ == "__main__":
    unittest.main()
