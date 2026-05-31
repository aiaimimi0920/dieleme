from __future__ import annotations

from pathlib import Path

from tools import avm_release_gate
from tools import check_feature_drift
from tools import export_to_excel
from tools import generate_avm_alerts
from tools import run_avm_pipeline


def test_run_avm_pipeline_loaders_explicitly_prefer_database(monkeypatch, tmp_path: Path):
    calls: list[tuple[Path, bool | None]] = []

    def _fake_loader(data_root: Path, prefer_db: bool | None = None):
        calls.append((Path(data_root), prefer_db))
        yield {
            "item_id": "db-1",
            "source_url": "https://example.com/db-1",
            "transaction_price": 1000000.0,
            "starting_price": 900000.0,
            "area_sqm": 80.0,
            "auction_date": "2024-01-01 10:00:00",
            "city": "上海市",
            "district": "浦东新区",
        }

    monkeypatch.setattr(run_avm_pipeline, "iter_analysis_ready_rows", _fake_loader)

    rows = run_avm_pipeline._load_candidates(str(tmp_path / "datas"), limit=1)

    assert len(rows) == 1
    assert calls == [(tmp_path / "datas", True)]


def test_export_to_excel_load_data_prefers_database_rows(monkeypatch, tmp_path: Path):
    def _fake_loader(data_root: Path, prefer_db: bool | None = None):
        assert prefer_db is True
        yield {
            "item_id": "db-1",
            "source_title": "测试房源",
            "evaluation_price": 1200000.0,
            "starting_price": 900000.0,
            "transaction_price": 1000000.0,
            "area_sqm": 80.0,
            "province": "上海市",
            "city": "上海市",
            "district": "浦东新区",
            "full_address": "上海市浦东新区测试路 1 号",
            "community_name": "测试花园",
            "business_area": "张江",
            "auction_date": "2024-01-01 10:00:00",
            "apply_count": 3,
            "bidder_count": 2,
            "source_url": "https://example.com/db-1",
        }

    monkeypatch.setattr(export_to_excel, "iter_analysis_ready_rows", _fake_loader)

    rows = export_to_excel.load_data(tmp_path / "datas")

    assert rows == [
        {
            "id": "db-1",
            "title": "测试房源",
            "评估价": 1200000.0,
            "起拍价": 900000.0,
            "成交价": 1000000.0,
            "面积": 80.0,
            "单价": 12500.0,
            "省份": "上海市",
            "城市": "上海市",
            "区": "浦东新区",
            "地点": "上海市浦东新区测试路 1 号",
            "所属小区": "测试花园",
            "最靠近商圈": "张江",
            "交易时间": "2024-01-01 10:00:00",
            "竞拍人数": 3,
            "出价人数": 2,
            "url": "https://example.com/db-1",
            "json_file": "db://property_listing",
        }
    ]


def test_generate_avm_alerts_loads_recent_analysis_ready_rows(monkeypatch, tmp_path: Path):
    calls: list[tuple[Path, int, bool | None]] = []

    def _fake_loader(data_root: Path, window_days: int, prefer_db: bool | None = None):
        calls.append((Path(data_root), window_days, prefer_db))
        return [
            {
                "id": "alert-1",
                "predicted_price": 1200000.0,
                "starting_price": 900000.0,
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试花园",
                "auction_date": "2024-01-01 10:00:00",
            }
        ]

    monkeypatch.setattr(generate_avm_alerts, "load_recent_analysis_ready_rows", _fake_loader)

    result = generate_avm_alerts.generate_avm_alerts(
        data_dir=tmp_path / "datas",
        output_path=tmp_path / "alerts.json",
        threshold=0.2,
        recent_days=7,
    )

    assert result["summary"]["alerts_count"] == 1
    assert calls == [(tmp_path / "datas", 7, True)]


def test_generate_avm_alerts_blocks_manual_review_and_risk_validation(monkeypatch, tmp_path: Path):
    def _fake_loader(data_root: Path, window_days: int, prefer_db: bool | None = None):
        return [
            {
                "id": "alert-2",
                "predicted_price": 1500000.0,
                "starting_price": 900000.0,
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试花园",
                "auction_date": "2024-01-01 10:00:00",
                "manual_review_recommended": True,
                "risk_validation": {
                    "ok": False,
                    "missing_required_count": 3,
                    "invalid_field_count": 0,
                },
            }
        ]

    monkeypatch.setattr(generate_avm_alerts, "load_recent_analysis_ready_rows", _fake_loader)

    result = generate_avm_alerts.generate_avm_alerts(
        data_dir=tmp_path / "datas",
        output_path=tmp_path / "alerts.json",
        threshold=0.2,
        recent_days=7,
    )

    assert result["summary"]["alerts_count"] == 0
    assert result["summary"]["blocked_reason_counts"]["manual_review_required"] == 1
    assert result["summary"]["blocked_reason_counts"]["risk_validation_incomplete"] == 1


def test_generate_avm_alerts_uses_configured_alert_threshold_when_not_provided(monkeypatch, tmp_path: Path):
    def _fake_loader(data_root: Path, window_days: int, prefer_db: bool | None = None):
        return [
            {
                "id": "alert-3",
                "predicted_price": 1000000.0,
                "starting_price": 820000.0,
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试花园",
                "auction_date": "2024-01-01 10:00:00",
                "manual_review_recommended": False,
                "risk_validation": {"ok": True, "missing_required_count": 0, "invalid_field_count": 0},
            }
        ]

    monkeypatch.setattr(generate_avm_alerts, "load_recent_analysis_ready_rows", _fake_loader)
    monkeypatch.setattr(generate_avm_alerts.AVM_CONFIG_MANAGER, "get_config", lambda: {"alert_threshold": 0.2})

    result = generate_avm_alerts.generate_avm_alerts(
        data_dir=tmp_path / "datas",
        output_path=tmp_path / "alerts.json",
        threshold=None,
        recent_days=7,
    )

    assert result["summary"]["alerts_count"] == 0
    assert result["summary"]["blocked_reason_counts"]["margin_below_threshold"] == 1


def test_generate_avm_alerts_allows_zero_alert_threshold_when_configured(monkeypatch, tmp_path: Path):
    def _fake_loader(data_root: Path, window_days: int, prefer_db: bool | None = None):
        return [
            {
                "id": "alert-4",
                "predicted_price": 1000000.0,
                "starting_price": 920000.0,
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试花园",
                "auction_date": "2024-01-01 10:00:00",
                "manual_review_recommended": False,
                "risk_validation": {"ok": True, "missing_required_count": 0, "invalid_field_count": 0},
            }
        ]

    monkeypatch.setattr(generate_avm_alerts, "load_recent_analysis_ready_rows", _fake_loader)
    monkeypatch.setattr(generate_avm_alerts.AVM_CONFIG_MANAGER, "get_config", lambda: {"alert_threshold": 0.0})

    result = generate_avm_alerts.generate_avm_alerts(
        data_dir=tmp_path / "datas",
        output_path=tmp_path / "alerts.json",
        threshold=None,
        recent_days=7,
    )

    assert result["summary"]["alerts_count"] == 1
    assert result["summary"]["blocked_reason_counts"] == {}


def test_release_gate_prefers_analysis_ready_recent_and_sample_rows(monkeypatch, tmp_path: Path):
    recent_calls: list[tuple[Path, int, bool | None]] = []
    sample_calls: list[tuple[Path, int, bool | None]] = []

    def _fake_recent_loader(data_root: Path, window_days: int, prefer_db: bool | None = None):
        recent_calls.append((Path(data_root), window_days, prefer_db))
        return [
            {
                "item_id": "gate-1",
                "auction_date": "2025-01-01 10:00:00",
                "transaction_price": 1200000.0,
                "starting_price": 1000000.0,
                "area_sqm": 80.0,
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试花园",
                "business_area": "张江",
                "latitude": 31.2,
                "longitude": 121.5,
                "housing_type": "住宅",
                "is_occupied": False,
                "has_long_lease": False,
                "clear_delivery": True,
                "tax_burden": "各自承担",
                "is_fractional_share": False,
            }
        ]

    def _fake_sample_loader(data_root: Path, limit: int, prefer_db: bool | None = None):
        sample_calls.append((Path(data_root), limit, prefer_db))
        return [
            {
                "id": "gate-1",
                "城市": "上海市",
                "区": "浦东新区",
                "所属小区": "测试花园",
            }
        ]

    monkeypatch.setattr(avm_release_gate, "load_recent_analysis_ready_rows", _fake_recent_loader)
    monkeypatch.setattr(avm_release_gate, "load_sample_analysis_ready_rows", _fake_sample_loader)
    monkeypatch.setattr(
        avm_release_gate,
        "generate_eval_report",
        lambda config: {"metrics": {"mape_pct": 1, "p50_ape_pct": 1, "p90_ape_pct": 1, "max_abs_partition_bias_pct": 1}},
    )
    monkeypatch.setattr(avm_release_gate, "generate_drift_report", lambda **kwargs: {"alerts": []})
    monkeypatch.setattr(avm_release_gate, "run_api_smoke", lambda *args, **kwargs: {"pass": True, "request_count": 0, "error_count": 0, "error_rate": 0.0, "p95_ms": 0.0, "p99_ms": 0.0})

    report = avm_release_gate.generate_release_gate_report(
        data_root=tmp_path / "datas",
        eval_report_path=tmp_path / "eval.json",
        gate_report_path=tmp_path / "gate.json",
        window_days=7,
        min_sample_size=1,
        smoke_sample_size=1,
    )

    assert report["completeness"]["pass"] is True
    assert recent_calls == [(tmp_path / "datas", 7, True)]
    assert sample_calls == []


def test_check_feature_drift_prefers_analysis_ready_rows(monkeypatch, tmp_path: Path):
    calls: list[tuple[Path, bool | None]] = []

    rows = []
    for idx in range(60):
        rows.append(
            {
                "交易时间": f"2025-01-{(idx % 28) + 1:02d} 10:00:00" if idx < 30 else f"2025-03-{(idx % 28) + 1:02d} 10:00:00",
                "起拍价格": float(100 + idx),
                "成交价格": float(110 + idx),
                "建筑面积": 80.0 + (idx % 5),
                "单价": 12000.0 + idx,
                "出价人数": 2 + (idx % 3),
                "竞拍人数": 3 + (idx % 4),
                "是否成交": True,
                "省份": "上海市",
                "城市": "上海市",
                "区": "浦东新区",
            }
        )

    def _fake_loader(data_root: Path, prefer_db: bool | None = None):
        calls.append((Path(data_root), prefer_db))
        return rows

    monkeypatch.setattr(check_feature_drift, "load_analysis_ready_rows", _fake_loader)

    report = check_feature_drift.generate_drift_report(
        archive_dir=tmp_path / "datas" / "archive",
        output_path=tmp_path / "drift.json",
        window_days=30,
    )

    assert "feature_metrics" in report
    assert calls == [(tmp_path / "datas", True)]
