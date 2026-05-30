import json
from pathlib import Path

from tools import avm_release_gate as gate_module
from tools.avm_release_gate import GateThresholds, build_eval_gate, generate_release_gate_report


def _write_month(path: Path, month: str, rows):
    year = month.split("-")[0]
    target_dir = path / "archive" / year
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / f"{month}-01.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def test_generate_release_gate_report_returns_sections(tmp_path: Path):
    data_root = tmp_path / "datas"

    for idx in range(1, 9):
        month = f"2025-{idx:02d}"
        rows = [
            {
                "id": f"{idx}001",
                "url": f"https://x/{idx}001",
                "成交价格": f"{100 + idx}万",
                "起拍价格": f"{90 + idx}万",
                "建筑面积": "100㎡",
                "交易时间": f"{month}-01 10:00:00",
                "城市": "上海市",
                "区": "浦东新区",
                "所属小区": "测试小区",
                "最靠近商圈": "张江",
                "纬度": 31.2,
                "经度": 121.5,
                "housing_type": "住宅",
                "is_occupied": False,
                "has_long_lease": False,
                "clear_delivery": True,
                "tax_burden": "各自承担",
                "is_fractional_share": False,
            }
        ]
        _write_month(data_root, month, rows)

    report = generate_release_gate_report(
        data_root=data_root,
        eval_report_path=tmp_path / "eval_report.json",
        gate_report_path=tmp_path / "gate_report.json",
        window_days=7,
        min_sample_size=1,
        smoke_sample_size=2,
    )

    assert "completeness" in report
    assert "evaluation" in report
    assert "valuation_mode_counts" in report["evaluation"]
    assert "valuation_mode_metrics" in report["evaluation"]
    assert "risk_validation_counts" in report["evaluation"]
    assert "strategy_metrics" in report["evaluation"]
    assert "coordinate_strategy_metrics" in report["evaluation"]
    assert "risk_validation_metrics" in report["evaluation"]
    assert "risk_flag_metrics" in report["evaluation"]
    assert "calibration_targets" in report["evaluation"]
    assert "drift" in report
    assert "api_smoke" in report
    assert "analysis_readiness" in report
    assert "blockers" in report["analysis_readiness"]
    assert "recommended_actions" in report["analysis_readiness"]


def test_build_eval_gate_requires_historical_strict_primary():
    gate = build_eval_gate(
        {
            "mape_pct": 5.0,
            "p50_ape_pct": 4.0,
            "p90_ape_pct": 8.0,
            "max_abs_partition_bias_pct": 2.0,
            "valuation_mode_counts": {"current_market": 5},
            "risk_validation_counts": {"ok": 5},
            "historical_temporal_reference_mode_counts": {},
        },
        GateThresholds(),
    )

    assert gate["historical_strict_primary"] is False
    assert gate["pass"] is False


def test_build_eval_gate_accepts_dual_mode_when_historical_mode_exists():
    gate = build_eval_gate(
        {
            "mape_pct": 5.0,
            "p50_ape_pct": 4.0,
            "p90_ape_pct": 8.0,
            "max_abs_partition_bias_pct": 2.0,
            "valuation_mode_counts": {"historical_strict": 10, "current_market": 10},
            "risk_validation_counts": {"ok": 20},
            "temporal_reference_mode_counts": {"subject_auction_date": 10, "current_time": 10},
            "historical_temporal_reference_mode_counts": {"subject_auction_date": 10},
        },
        GateThresholds(),
    )

    assert gate["historical_strict_primary"] is True
    assert gate["historical_current_time_ratio"] == 0.0
    assert gate["historical_temporal_reference_pass"] is True


def test_build_eval_gate_rejects_invalid_risk_validation_budget():
    gate = build_eval_gate(
        {
            "mape_pct": 5.0,
            "p50_ape_pct": 4.0,
            "p90_ape_pct": 8.0,
            "max_abs_partition_bias_pct": 2.0,
            "valuation_mode_counts": {"historical_strict": 10},
            "risk_validation_counts": {"ok": 9, "invalid": 1},
            "historical_temporal_reference_mode_counts": {"subject_auction_date": 10},
        },
        GateThresholds(),
    )

    assert gate["risk_validation_invalid_pass"] is False
    assert gate["pass"] is False


def test_build_eval_gate_rejects_current_time_temporal_fallback_in_historical_mode():
    gate = build_eval_gate(
        {
            "mape_pct": 5.0,
            "p50_ape_pct": 4.0,
            "p90_ape_pct": 8.0,
            "max_abs_partition_bias_pct": 2.0,
            "valuation_mode_counts": {"historical_strict": 10},
            "risk_validation_counts": {"ok": 10},
            "temporal_reference_mode_counts": {"subject_auction_date": 9, "current_time": 1},
            "historical_temporal_reference_mode_counts": {"subject_auction_date": 9, "current_time": 1},
        },
        GateThresholds(),
    )

    assert gate["historical_temporal_reference_pass"] is False
    assert gate["pass"] is False


def test_build_eval_gate_surfaces_cohort_watchlists():
    gate = build_eval_gate(
        {
            "mape_pct": 5.0,
            "p50_ape_pct": 4.0,
            "p90_ape_pct": 8.0,
            "max_abs_partition_bias_pct": 2.0,
            "valuation_mode_counts": {"historical_strict": 10},
            "risk_validation_counts": {"ok": 8, "incomplete": 2},
            "temporal_reference_mode_counts": {"subject_auction_date": 10},
            "historical_temporal_reference_mode_counts": {"subject_auction_date": 10},
            "strategy_metrics": [
                {"group": "spatial", "sample_count": 6, "mape_pct": 4.0, "p90_ape_pct": 7.0},
                {"group": "global_fallback", "sample_count": 4, "mape_pct": 16.0, "p90_ape_pct": 30.0},
            ],
            "coordinate_strategy_metrics": [
                {"group": "observed", "sample_count": 8, "mape_pct": 4.0, "p90_ape_pct": 7.0},
                {"group": "district_centroid", "sample_count": 2, "mape_pct": 19.0, "p90_ape_pct": 31.0},
            ],
            "risk_validation_metrics": [
                {"group": "ok", "sample_count": 8, "mape_pct": 4.0, "p90_ape_pct": 7.0},
                {"group": "incomplete", "sample_count": 2, "mape_pct": 18.0, "p90_ape_pct": 32.0},
            ],
        },
        GateThresholds(),
    )

    assert gate["top_strategy_group"] == "global_fallback"
    assert gate["top_coordinate_strategy_group"] == "district_centroid"
    assert gate["top_risk_validation_group"] == "incomplete"
    assert gate["strategy_watchlist"] == ["global_fallback"]
    assert gate["coordinate_strategy_watchlist"] == ["district_centroid"]
    assert gate["risk_validation_watchlist"] == ["incomplete"]


def test_build_eval_gate_surfaces_valuation_mode_gap():
    gate = build_eval_gate(
        {
            "mape_pct": 5.0,
            "p50_ape_pct": 4.0,
            "p90_ape_pct": 8.0,
            "max_abs_partition_bias_pct": 2.0,
            "valuation_mode_counts": {"historical_strict": 10, "current_market": 10},
            "valuation_mode_metrics": [
                {"group": "historical_strict", "sample_count": 10, "mape_pct": 5.0, "p90_ape_pct": 8.0},
                {"group": "current_market", "sample_count": 10, "mape_pct": 16.0, "p90_ape_pct": 28.0},
            ],
            "risk_validation_counts": {"ok": 10},
            "temporal_reference_mode_counts": {"subject_auction_date": 10},
            "historical_temporal_reference_mode_counts": {"subject_auction_date": 10},
        },
        GateThresholds(),
    )

    assert gate["valuation_mode_mape_gap_pct"] == 11.0
    assert gate["valuation_mode_gap_warning"] is True


def test_build_eval_gate_surfaces_calibration_targets():
    gate = build_eval_gate(
        {
            "mape_pct": 5.0,
            "p50_ape_pct": 4.0,
            "p90_ape_pct": 8.0,
            "max_abs_partition_bias_pct": 2.0,
            "valuation_mode_counts": {"historical_strict": 10},
            "risk_validation_counts": {"ok": 10},
            "temporal_reference_mode_counts": {"subject_auction_date": 10},
            "historical_temporal_reference_mode_counts": {"subject_auction_date": 10},
            "risk_flag_metrics": [
                {"group": "is_occupied", "sample_count": 5, "mape_pct": 18.0, "mean_bias_pct": 9.0, "p90_ape_pct": 30.0}
            ],
        },
        GateThresholds(),
    )

    assert gate["calibration_targets"]["has_recommendations"] is True
    assert gate["calibration_targets"]["risk_factor_targets"][0]["name"] == "is_occupied"
    assert gate["calibration_targets"]["guidance"]["status"] == "tune_risk_factors"


def test_build_eval_gate_can_surface_global_risk_discount_target():
    gate = build_eval_gate(
        {
            "mape_pct": 5.0,
            "p50_ape_pct": 4.0,
            "p90_ape_pct": 8.0,
            "max_abs_partition_bias_pct": 2.0,
            "valuation_mode_counts": {"historical_strict": 10},
            "risk_validation_counts": {"ok": 10},
            "temporal_reference_mode_counts": {"subject_auction_date": 10},
            "historical_temporal_reference_mode_counts": {"subject_auction_date": 10},
            "risk_flag_metrics": [
                {"group": "is_occupied", "sample_count": 8, "mape_pct": 18.0, "mean_bias_pct": 9.0, "p90_ape_pct": 30.0},
                {"group": "has_long_lease", "sample_count": 6, "mape_pct": 16.0, "mean_bias_pct": 7.0, "p90_ape_pct": 26.0},
            ],
        },
        GateThresholds(),
    )

    assert gate["calibration_targets"]["global_risk_targets"][0]["name"] == "risk_discount_factor"
    assert gate["calibration_targets"]["guidance"]["status"] == "tune_global_risk_discount"


def test_build_eval_gate_surfaces_temporal_calibration_targets():
    gate = build_eval_gate(
        {
            "mape_pct": 5.0,
            "p50_ape_pct": 4.0,
            "p90_ape_pct": 8.0,
            "max_abs_partition_bias_pct": 2.0,
            "valuation_mode_counts": {"historical_strict": 12, "current_market": 12},
            "valuation_mode_metrics": [
                {"group": "historical_strict", "sample_count": 12, "mape_pct": 18.0, "mean_bias_pct": 8.0, "p90_ape_pct": 30.0},
                {"group": "current_market", "sample_count": 12, "mape_pct": 8.0, "mean_bias_pct": 2.0, "p90_ape_pct": 16.0},
            ],
            "risk_validation_counts": {"ok": 12},
            "temporal_reference_mode_counts": {"subject_auction_date": 12, "current_time": 12},
            "historical_temporal_reference_mode_counts": {"subject_auction_date": 12},
        },
        GateThresholds(),
    )

    assert gate["calibration_targets"]["has_recommendations"] is True
    assert gate["calibration_targets"]["temporal_targets"][0]["name"] == "time_decay"
    assert gate["calibration_targets"]["top_calibration_target_hint"]["target_name"] == "time_decay"


def test_build_eval_gate_can_surface_coordinate_quality_guidance():
    gate = build_eval_gate(
        {
            "mape_pct": 5.0,
            "p50_ape_pct": 4.0,
            "p90_ape_pct": 8.0,
            "max_abs_partition_bias_pct": 2.0,
            "valuation_mode_counts": {"historical_strict": 12},
            "risk_validation_counts": {"ok": 12},
            "temporal_reference_mode_counts": {"subject_auction_date": 12},
            "historical_temporal_reference_mode_counts": {"subject_auction_date": 12},
            "coordinate_strategy_metrics": [
                {"group": "observed", "sample_count": 10, "mape_pct": 6.0, "mean_bias_pct": 1.0, "p90_ape_pct": 10.0},
                {"group": "district_centroid", "sample_count": 4, "mape_pct": 21.0, "mean_bias_pct": 7.0, "p90_ape_pct": 34.0},
            ],
        },
        GateThresholds(),
    )

    assert gate["calibration_targets"]["guidance"]["status"] == "fix_coordinate_quality"


def test_build_eval_gate_normalizes_partial_calibration_targets_payload(monkeypatch):
    monkeypatch.setattr(
        gate_module,
        "suggest_calibration_targets",
        lambda metrics: {
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

    gate = build_eval_gate(
        {
            "mape_pct": 5.0,
            "p50_ape_pct": 4.0,
            "p90_ape_pct": 8.0,
            "max_abs_partition_bias_pct": 2.0,
            "valuation_mode_counts": {"historical_strict": 12, "current_market": 12},
            "valuation_mode_metrics": [
                {"group": "historical_strict", "sample_count": 12, "mape_pct": 18.0, "mean_bias_pct": 8.0, "p90_ape_pct": 30.0},
                {"group": "current_market", "sample_count": 12, "mape_pct": 8.0, "mean_bias_pct": 2.0, "p90_ape_pct": 16.0},
            ],
            "risk_validation_counts": {"ok": 12},
            "temporal_reference_mode_counts": {"subject_auction_date": 12, "current_time": 12},
            "historical_temporal_reference_mode_counts": {"subject_auction_date": 12},
        },
        GateThresholds(),
    )

    assert gate["calibration_targets"]["has_recommendations"] is True
    assert gate["calibration_targets"]["global_risk_targets"] == []
    assert gate["calibration_targets"]["risk_factor_targets"] == []
    assert gate["calibration_targets"]["strategy_targets"] == []
    assert gate["calibration_targets"]["guidance"] == {}


def test_release_gate_analysis_readiness_can_reflect_action_effectiveness(monkeypatch, tmp_path: Path):
    data_root = tmp_path / "datas"
    _write_month(
        data_root,
        "2025-01",
        [
            {
                "id": "1001",
                "url": "https://x/1001",
                "成交价格": "100万",
                "起拍价格": "90万",
                "建筑面积": "100㎡",
                "交易时间": "2025-01-01 10:00:00",
                "城市": "上海市",
                "区": "浦东新区",
                "所属小区": "测试小区",
                "最靠近商圈": "张江",
                "纬度": 31.2,
                "经度": 121.5,
            }
        ],
    )

    monkeypatch.setattr(
        gate_module,
        "load_action_effectiveness_snapshot",
        lambda path=None: {
            "detail_archive_fetch": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )

    report = generate_release_gate_report(
        data_root=data_root,
        eval_report_path=tmp_path / "eval_report.json",
        gate_report_path=tmp_path / "gate_report.json",
        window_days=7,
        min_sample_size=1,
        smoke_sample_size=1,
    )

    recommended = report["analysis_readiness"]["recommended_actions"]
    assert "fetch_archives" in recommended["deprioritized_actions"]
    assert "detail_archive_fetch_low_yield" in recommended["feedback_hints"]
    assert "next_best_alternative_actions" in recommended
    assert "operator_summary" in recommended
    summary = report["analysis_readiness"]["action_effectiveness_summary"]
    assert "detail_archive_fetch" in summary["low_yield_actions"]
    assert summary["top_low_yield_action"] == "detail_archive_fetch"
    assert summary["top_low_yield_actions"] == ["detail_archive_fetch"]
    operator_summary = report["analysis_readiness"]["operator_action_summary"]
    assert operator_summary["top_low_yield_actions"] == ["detail_archive_fetch"]
    assert "fetch_archives" in operator_summary["deprioritized_actions"]


def test_release_gate_analysis_readiness_can_surface_manual_review_fallback(monkeypatch, tmp_path: Path):
    data_root = tmp_path / "datas"
    _write_month(
        data_root,
        "2025-01",
        [
            {
                "id": "1002",
                "url": "https://x/1002",
                "成交价格": "100万",
                "起拍价格": "90万",
                "建筑面积": "100㎡",
                "交易时间": "2025-01-01 10:00:00",
                "城市": "上海市",
                "区": "浦东新区",
            }
        ],
    )

    monkeypatch.setattr(
        gate_module,
        "load_action_effectiveness_snapshot",
        lambda path=None: {
            "detail_replay_preparation": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )

    report = generate_release_gate_report(
        data_root=data_root,
        eval_report_path=tmp_path / "eval_report.json",
        gate_report_path=tmp_path / "gate_report.json",
        window_days=7,
        min_sample_size=1,
        smoke_sample_size=1,
    )

    recommended = report["analysis_readiness"]["recommended_actions"]
    assert recommended["manual_review_candidate"] is True
    assert recommended["fallback_routes"]["prepare_replay"] == "manual_review"
    operator_summary = report["analysis_readiness"]["operator_action_summary"]
    assert operator_summary["manual_review_candidates"] == ["manual_review"]


def test_release_gate_analysis_readiness_can_surface_recoverability_summary(monkeypatch, tmp_path: Path):
    data_root = tmp_path / "datas"
    _write_month(
        data_root,
        "2025-01",
        [
            {
                "id": "1003",
                "url": "https://x/1003",
                "成交价格": "100万",
                "起拍价格": "90万",
                "建筑面积": "100㎡",
                "交易时间": "2025-01-01 10:00:00",
                "城市": "上海市",
                "区": "浦东新区",
            }
        ],
    )

    monkeypatch.setattr(
        gate_module,
        "build_recent_gap_audit",
        lambda data_root, window_days, sample_limit: {
            "recoverability_counts": {
                "future_fixable": 0,
                "historical_unrecoverable": 2,
                "archive_backfill_candidate": 0,
                "replay_candidate": 0,
                "coordinate_infer_candidate": 0,
            },
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["detail_stage"], "missing_fields": ["latitude"]},
                {"item_id": "mr-2", "title": "样本2", "historical_unrecoverable": True, "analysis_missing_fields": ["price_anchor"], "missing_fields": ["is_occupied"]},
            ],
        },
    )
    monkeypatch.setattr(
        gate_module,
        "load_optimization_loop_progress_snapshot",
        lambda path=None: {
            "manual_review_candidate_rounds": 2,
            "manual_review_reasons": {"historical_unrecoverable_gap": 2},
            "top_manual_review_reason": "historical_unrecoverable_gap",
            "human_action_counts": {"manual_location_review": 4, "manual_price_anchor_review": 1},
            "retry_policy_counts": {"human_fix_required_before_retry": 2},
            "top_retry_policy": "human_fix_required_before_retry",
            "handoff_lifecycle_counts": {"awaiting_human_receipt_hard_stop": 2},
            "top_handoff_lifecycle_state": "awaiting_human_receipt_hard_stop",
            "pending_ready_signal_counts": {"location_artifacts_complete": 2},
            "top_pending_ready_signal": "location_artifacts_complete",
            "invalid_receipt_reason_counts": {"missing_required_fields": 2},
            "top_invalid_receipt_reason": "missing_required_fields",
            "fallback_usage": {"fetch_archives": {"prepare_replay": 3}},
        },
    )

    report = generate_release_gate_report(
        data_root=data_root,
        eval_report_path=tmp_path / "eval_report.json",
        gate_report_path=tmp_path / "gate_report.json",
        window_days=7,
        min_sample_size=1,
        smoke_sample_size=1,
    )

    recoverability = report["analysis_readiness"]["recoverability_summary"]
    assert recoverability["future_fixable"] == 0
    assert recoverability["historical_unrecoverable"] == 2
    operator_summary = report["analysis_readiness"]["operator_action_summary"]
    assert operator_summary["top_manual_review_reason"] == "historical_unrecoverable_gap"
    assert operator_summary["manual_review_required"] is True
    scheduler_summary = report["analysis_readiness"]["scheduler_feedback_summary"]
    assert scheduler_summary["manual_review_candidate_rounds"] == 2
    assert scheduler_summary["top_fallback_routes"] == ["fetch_archives->prepare_replay"]
    assert scheduler_summary["top_human_actions"] == ["manual_location_review", "manual_price_anchor_review"]
    assert scheduler_summary["top_retry_policy"] == "human_fix_required_before_retry"
    assert scheduler_summary["top_handoff_lifecycle_state"] == "awaiting_human_receipt_hard_stop"
    assert scheduler_summary["top_pending_ready_signal"] == "location_artifacts_complete"
    assert scheduler_summary["top_invalid_receipt_reason"] == "missing_required_fields"
    backlog_summary = report["analysis_readiness"]["manual_review_backlog_summary"]
    assert backlog_summary["candidate_count"] == 2
    assert backlog_summary["sample_item_ids"] == ["mr-1", "mr-2"]
    assert backlog_summary["top_human_actions"][0] == "manual_location_review"
    assert "full_address" in backlog_summary["top_human_action_instructions"][0]
    assert backlog_summary["human_action_queues"]["manual_location_review"]["count"] == 2
    assert backlog_summary["human_action_queues"]["manual_location_review"]["expected_reentry_path"] == "infer_location_or_coordinate_backfill"
    assert backlog_summary["human_action_queues"]["manual_location_review"]["priority_label"] == "high"
    assert backlog_summary["human_action_queues"]["manual_location_review"]["suggested_handoff_priority"] == "P0"
    assert "full_address" in backlog_summary["human_action_queues"]["manual_location_review"]["queue_level_checklist"][0]
    assert "重新打开" in backlog_summary["human_action_queues"]["manual_location_review"]["suggested_handoff_priority_reason"]
    assert "latitude/longitude" in backlog_summary["human_action_queues"]["manual_location_review"]["queue_level_completion_criteria"][0]
    assert "coordinate_backfill" in backlog_summary["human_action_queues"]["manual_location_review"]["reentry_validation_checklist"][0]
    assert "full_address" in backlog_summary["human_action_queues"]["manual_location_review"]["handoff_artifact_fields"]
    assert "坐标" in backlog_summary["human_action_queues"]["manual_location_review"]["required_human_evidence"][0]
    assert "location blocker" in backlog_summary["human_action_queues"]["manual_location_review"]["reentry_blockers_if_incomplete"][0]
    assert "核对结论" in backlog_summary["human_action_queues"]["manual_location_review"]["required_human_resolution_notes"][0]
    assert backlog_summary["human_action_queues"]["manual_location_review"]["reentry_ready_signal"] == "location_artifacts_complete"
    assert "full_address" in backlog_summary["human_action_queues"]["manual_location_review"]["handoff_completion_payload"]["required_fields"]
    overview = report["analysis_readiness"]["operator_overview"]
    assert overview["manual_review_required"] is True
    assert overview["top_manual_review_reason"] == "historical_unrecoverable_gap"
    assert overview["top_human_actions"][0] == "manual_location_review"
    assert "full_address" in overview["top_human_action_instructions"][0]
    assert overview["handoff_mode"] == "manual_required_hard_stop"
    assert overview["handoff_lifecycle_state"] == "awaiting_human_receipt_hard_stop"
    assert overview["auto_retry_policy"]["policy"] == "human_fix_required_before_retry"
    assert overview["top_pending_ready_signal"] == "location_artifacts_complete"
    assert overview["top_human_action_queue"]["expected_reentry_path"] == "infer_location_or_coordinate_backfill"
    assert overview["top_human_action_queue"]["priority_label"] == "high"
    assert overview["top_human_action_queue"]["suggested_handoff_priority"] == "P0"
    assert "full_address" in overview["top_human_action_queue"]["queue_level_checklist"][0]
    assert "重新打开" in overview["top_human_action_queue"]["suggested_handoff_priority_reason"]
    assert "latitude/longitude" in overview["top_human_action_queue"]["queue_level_completion_criteria"][0]
    assert "coordinate_backfill" in overview["top_human_action_queue"]["reentry_validation_checklist"][0]
    assert "full_address" in overview["top_human_action_queue"]["handoff_artifact_fields"]
    assert "坐标" in overview["top_human_action_queue"]["required_human_evidence"][0]
    assert "location blocker" in overview["top_human_action_queue"]["reentry_blockers_if_incomplete"][0]
    assert "核对结论" in overview["top_human_action_queue"]["required_human_resolution_notes"][0]
    assert overview["top_human_action_queue"]["reentry_ready_signal"] == "location_artifacts_complete"
    assert "full_address" in overview["top_human_action_queue"]["handoff_completion_payload"]["required_fields"]
    assert report["analysis_readiness"]["scheduler_feedback_summary"]["top_handoff_mode"] == "manual_required_hard_stop"


def test_release_gate_analysis_readiness_can_surface_receipt_ready_state(monkeypatch, tmp_path: Path):
    data_root = tmp_path / "datas"
    _write_month(
        data_root,
        "2025-01",
        [
            {
                "id": "1004",
                "url": "https://x/1004",
                "成交价格": "100万",
                "建筑面积": "100㎡",
                "交易时间": "2025-01-01 10:00:00",
                "城市": "上海市",
                "区": "浦东新区",
            }
        ],
    )

    monkeypatch.setattr(
        gate_module,
        "build_recent_gap_audit",
        lambda data_root, window_days, sample_limit: {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
            ],
        },
    )
    monkeypatch.setattr(gate_module, "load_action_effectiveness_snapshot", lambda path=None: {})
    monkeypatch.setattr(gate_module, "load_optimization_loop_progress_snapshot", lambda path=None: {})
    (data_root / "avm").mkdir(parents=True, exist_ok=True)
    (data_root / "avm" / "manual_review_receipt_jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "job_id": "job-1",
                        "status": "completed",
                        "receipt_key": {
                            "action": "manual_location_review",
                            "ready_signal": "location_artifacts_complete",
                        },
                        "created_at": "2026-05-14T20:00:00",
                        "finished_at": "2026-05-14T20:00:01",
                    }
                ],
                "queue": [],
                "running_job_id": None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_root / "avm" / "manual_review_receipt_operations.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "operation_id": "op-1",
                        "operation": "created",
                        "action": "manual_location_review",
                        "ready_signal": "location_artifacts_complete",
                        "status": "ready_for_reentry",
                        "payload_fingerprint": "fp-1",
                        "source": "operator_api",
                        "execution_mode": "async",
                        "requested_at": "2026-05-14 20:00:00",
                        "maintenance_job_id": "job-1",
                    },
                    ensure_ascii=False,
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gate_module,
        "load_manual_review_receipt_snapshot",
        lambda path=None: {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {
                        "full_address": "A",
                        "community_name": "B",
                        "business_area": "C",
                        "latitude": 1.0,
                        "longitude": 2.0,
                    },
                }
            ]
        },
    )

    report = generate_release_gate_report(
        data_root=data_root,
        eval_report_path=tmp_path / "eval_report.json",
        gate_report_path=tmp_path / "gate_report.json",
        window_days=7,
        min_sample_size=1,
        smoke_sample_size=1,
    )

    receipt_summary = report["analysis_readiness"]["manual_review_receipt_summary"]
    assert receipt_summary["top_matched_ready_signal"] == "location_artifacts_complete"
    assert receipt_summary["top_receipt_status"] == "ready_for_reentry"
    assert report["analysis_readiness"]["recommended_actions"]["run_coordinate_backfill"] is True
    reentry_summary = report["analysis_readiness"]["manual_review_reentry_application_summary"]
    assert reentry_summary["reentry_applied"] is False
    overview = report["analysis_readiness"]["operator_overview"]
    assert overview["handoff_lifecycle_state"] == "receipt_ready_for_reentry"
    assert overview["should_resume_automation"] is True
    assert overview["matched_ready_signals"] == ["location_artifacts_complete"]
    jobs_summary = report["analysis_readiness"]["manual_review_receipt_jobs_summary"]
    assert jobs_summary["last_job_status"] == "completed"
    assert jobs_summary["last_job_receipt_key"]["action"] == "manual_location_review"
    operations_summary = report["analysis_readiness"]["manual_review_receipt_operations_summary"]
    assert operations_summary["last_operation_type"] == "created"
    assert operations_summary["last_operation_receipt_key"]["action"] == "manual_location_review"
    storage_summary = report["analysis_readiness"]["manual_review_control_plane_storage"]
    assert storage_summary["state_source"] == "json_fallback"
    assert storage_summary["repository_enabled"] is False
    backup_summary = report["analysis_readiness"]["manual_review_control_plane_backup"]
    assert backup_summary["backup_state"] == "runtime_json"
    assert backup_summary["repository_enabled"] is False
    repairs_summary = report["analysis_readiness"]["manual_review_control_plane_backup_repairs_summary"]
    assert repairs_summary["repair_count"] == 0
    integrity = report["analysis_readiness"]["manual_review_control_plane_integrity"]
    assert integrity["integrity_status"] == "healthy_json_runtime"
    assert integrity["attention_required"] is False
    stability = report["analysis_readiness"]["manual_review_control_plane_stability"]
    assert stability["stability_status"] == "stable_json_runtime"
    assert stability["attention_required"] is False
    guidance = report["analysis_readiness"]["manual_review_control_plane_guidance"]
    assert guidance["guidance_status"] == "no_action_required"
    assert guidance["requires_operator_action"] is False
    integrity_history_summary = report["analysis_readiness"]["manual_review_control_plane_integrity_history_summary"]
    assert integrity_history_summary["transition_count"] >= 1
    assert integrity_history_summary["last_integrity_status"] == "healthy_json_runtime"


def test_release_gate_analysis_readiness_can_surface_incomplete_receipt_state(monkeypatch, tmp_path: Path):
    data_root = tmp_path / "datas"
    _write_month(
        data_root,
        "2025-01",
        [
            {
                "id": "1005",
                "url": "https://x/1005",
                "成交价格": "100万",
                "建筑面积": "100㎡",
                "交易时间": "2025-01-01 10:00:00",
                "城市": "上海市",
                "区": "浦东新区",
            }
        ],
    )

    monkeypatch.setattr(
        gate_module,
        "build_recent_gap_audit",
        lambda data_root, window_days, sample_limit: {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
            ],
        },
    )
    monkeypatch.setattr(gate_module, "load_action_effectiveness_snapshot", lambda path=None: {})
    monkeypatch.setattr(gate_module, "load_optimization_loop_progress_snapshot", lambda path=None: {})
    monkeypatch.setattr(
        gate_module,
        "load_manual_review_receipt_snapshot",
        lambda path=None: {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                }
            ]
        },
    )

    report = generate_release_gate_report(
        data_root=data_root,
        eval_report_path=tmp_path / "eval_report.json",
        gate_report_path=tmp_path / "gate_report.json",
        window_days=7,
        min_sample_size=1,
        smoke_sample_size=1,
    )

    receipt_summary = report["analysis_readiness"]["manual_review_receipt_summary"]
    assert receipt_summary["top_receipt_status"] == "receipt_incomplete"
    assert receipt_summary["invalid_receipt_count"] == 1
    assert receipt_summary["top_invalid_receipt_reason"] == "missing_required_fields"
    assert receipt_summary["top_receipt_fix_actions"] == ["complete_required_fields"]
    overview = report["analysis_readiness"]["operator_overview"]
    assert overview["handoff_lifecycle_state"] == "awaiting_valid_receipt"
    assert overview["should_resume_automation"] is False
    assert overview["top_invalid_receipt_reason"] == "missing_required_fields"
    assert overview["top_receipt_fix_actions"] == ["complete_required_fields"]
