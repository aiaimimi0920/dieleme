from tools.test.avm_release_gate_test_context import *


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
