import json
from pathlib import Path

from tools.evaluate_avm import BacktestConfig, generate_report, run_time_split_backtest


def _write_month(path: Path, month: str, rows):
    year = month.split("-")[0]
    target_dir = path / "archive" / year
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / f"{month}-01.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def test_generate_eval_report_uses_multidim_pipeline(tmp_path: Path):
    data_root = tmp_path / "datas"

    monthly_prices = [100, 102, 104, 106, 108, 110, 112, 114]
    for idx, price in enumerate(monthly_prices, start=1):
        month = f"2025-{idx:02d}"
        rows = [
            {
                "id": f"{idx}001",
                "url": f"https://x/{idx}001",
                "成交价格": f"{price}万",
                "起拍价格": f"{price - 10}万",
                "建筑面积": "100㎡",
                "交易时间": f"{month}-01 10:00:00",
                "城市": "上海市",
                "区": "浦东新区",
                "所属小区": "测试小区",
                "最靠近商圈": "张江",
                "纬度": 31.2,
                "经度": 121.5,
                "housing_type": "住宅",
                "is_occupied": idx % 2 == 0,
                "has_long_lease": False,
                "clear_delivery": True,
                "tax_burden": "各自承担",
                "is_fractional_share": False,
            }
        ]
        _write_month(data_root, month, rows)

    report = generate_report(
        BacktestConfig(
            data_root=data_root,
            report_path=tmp_path / "eval_report.json",
            min_train_months=2,
            max_candidates_per_subject=50,
        )
    )

    assert report["data_summary"]["normalized_record_count"] == len(monthly_prices)
    assert report["data_summary"]["backtest_sample_count"] > 0
    assert report["data_summary"]["valuation_mode_sample_counts"]["historical_strict"] == report["data_summary"]["backtest_sample_count"]
    assert report["data_summary"]["valuation_mode_sample_counts"]["current_market"] > 0
    assert "strategy_counts" in report["metrics"]
    assert report["metrics"]["valuation_mode_counts"]["historical_strict"] == report["data_summary"]["backtest_sample_count"]
    assert report["metrics"]["valuation_mode_counts"]["current_market"] > 0
    assert "valuation_mode_metrics" in report["metrics"]
    groups = {row["group"] for row in report["metrics"]["valuation_mode_metrics"]}
    assert "historical_strict" in groups
    assert "current_market" in groups
    assert "temporal_reference_mode_counts" in report["metrics"]
    assert "historical_temporal_reference_mode_counts" in report["metrics"]
    assert report["metrics"]["historical_temporal_reference_mode_counts"]["subject_auction_date"] == report["data_summary"]["backtest_sample_count"]
    assert "risk_validation_counts" in report["metrics"]
    assert "strategy_metrics" in report["metrics"]
    assert report["metrics"]["strategy_metrics"][0]["group"] in {"spatial", "community_fallback", "business_area_fallback", "district_fallback", "city_fallback", "global_fallback"}
    assert "coordinate_strategy_metrics" in report["metrics"]
    assert "risk_validation_metrics" in report["metrics"]
    assert report["metrics"]["risk_validation_metrics"][0]["group"] in {"ok", "incomplete", "invalid"}
    assert "risk_flag_metrics" in report["metrics"]
    assert any(row["group"] == "is_occupied" for row in report["metrics"]["risk_flag_metrics"])
    assert "diagnostics" in report
    assert "housing_type_counts" in report["diagnostics"]
    assert "worst_cases" in report["diagnostics"]
    assert "risk_validation_state" in report["diagnostics"]["worst_cases"][0]
    assert "coordinate_strategy" in report["diagnostics"]["worst_cases"][0]


def test_run_time_split_backtest_can_use_centroid_fill_for_missing_subject_coordinates(tmp_path: Path):
    records = [
        {
            "item_id": "train-1",
            "month": "2025-01",
            "auction_date": "2025-01-01 10:00:00",
            "partition": "上海市-浦东新区",
            "city": "上海市",
            "district": "浦东新区",
            "community_name": "测试小区",
            "business_area": "张江",
            "housing_type": "住宅",
            "area_sqm": 100.0,
            "transaction_price": 1_000_000.0,
            "actual_price": 1_000_000.0,
            "actual_unit_price": 10_000.0,
            "latitude": 31.2,
            "longitude": 121.5,
            "coordinate_strategy": "observed",
            "risk_validation_ok": True,
            "risk_missing_required_count": 0,
            "risk_invalid_field_count": 0,
        },
        {
            "item_id": "train-2",
            "month": "2025-02",
            "auction_date": "2025-02-01 10:00:00",
            "partition": "上海市-浦东新区",
            "city": "上海市",
            "district": "浦东新区",
            "community_name": "测试小区",
            "business_area": "张江",
            "housing_type": "住宅",
            "area_sqm": 100.0,
            "transaction_price": 1_100_000.0,
            "actual_price": 1_100_000.0,
            "actual_unit_price": 11_000.0,
            "latitude": 31.2001,
            "longitude": 121.5001,
            "coordinate_strategy": "observed",
            "risk_validation_ok": True,
            "risk_missing_required_count": 0,
            "risk_invalid_field_count": 0,
        },
        {
            "item_id": "subject-missing-geo",
            "item_id": "train-3",
            "month": "2025-03",
            "auction_date": "2025-03-01 10:00:00",
            "partition": "上海市-浦东新区",
            "city": "上海市",
            "district": "浦东新区",
            "community_name": "测试小区",
            "business_area": "张江",
            "housing_type": "住宅",
            "area_sqm": 100.0,
            "transaction_price": 1_050_000.0,
            "actual_price": 1_050_000.0,
            "actual_unit_price": 10_500.0,
            "latitude": 31.2002,
            "longitude": 121.5002,
            "coordinate_strategy": "observed",
            "risk_validation_ok": True,
            "risk_missing_required_count": 0,
            "risk_invalid_field_count": 0,
        },
        {
            "item_id": "subject-missing-geo",
            "month": "2025-04",
            "auction_date": "2025-04-01 10:00:00",
            "partition": "上海市-浦东新区",
            "city": "上海市",
            "district": "浦东新区",
            "community_name": "测试小区",
            "business_area": "张江",
            "housing_type": "住宅",
            "area_sqm": 100.0,
            "transaction_price": 1_080_000.0,
            "actual_price": 1_080_000.0,
            "actual_unit_price": 10_800.0,
            "latitude": None,
            "longitude": None,
            "coordinate_strategy": "community_centroid",
            "risk_validation_ok": True,
            "risk_missing_required_count": 0,
            "risk_invalid_field_count": 0,
        },
    ]

    predictions = run_time_split_backtest(
        records,
        BacktestConfig(
            data_root=tmp_path / "datas",
            report_path=tmp_path / "eval_report.json",
            min_train_months=3,
            max_candidates_per_subject=20,
        ),
    )

    subject_predictions = [row for row in predictions if row["item_id"] == "subject-missing-geo" and row["valuation_mode"] == "historical_strict"]
    assert subject_predictions
    assert subject_predictions[0]["coordinate_strategy"] == "community_centroid"
    assert subject_predictions[0]["strategy"] == "spatial"
