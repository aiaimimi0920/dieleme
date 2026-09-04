from tools.test.avm_engine_service_test_context import *  # noqa: F401,F403


def test_predict_fair_price_falls_back_without_geo():
    subject = {
        "item_id": "subject-1",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
    }
    comparables = [
        {
            "item_id": "c1",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-01-01 10:00:00",
        },
        {
            "item_id": "c2",
            "transaction_price": 1_100_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 1_200_000,
            "area_sqm": 100,
            "community_name": "其他小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    result = predict_fair_price(subject, comparables)

    assert result["predicted_price"] is not None
    assert result["strategy"] != "spatial"
    assert result["comparable_count"] >= 3

def test_predict_fair_price_uses_subject_auction_date_for_temporal_factor():
    subject = {
        "item_id": "subject-temporal-anchor",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
        "latitude": 31.23,
        "longitude": 121.47,
        "auction_date": "2024-03-01 10:00:00",
        "valuation_mode": "historical_strict",
    }
    comparables = [
        {
            "item_id": "c1",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.23,
            "longitude": 121.47,
            "auction_date": "2024-01-01 10:00:00",
        },
        {
            "item_id": "c2",
            "transaction_price": 1_100_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.23,
            "longitude": 121.47,
            "auction_date": "2024-02-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 1_200_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.23,
            "longitude": 121.47,
            "auction_date": "2024-03-01 10:00:00",
        },
    ]

    result = predict_fair_price(subject, comparables)

    assert result["strategy"] == "spatial"
    assert 10_900.0 <= result["predicted_unit_price"] <= 11_100.0
    assert result["trace"]["valuation_mode"] == "historical_strict"
    assert "时间趋势校准系数=1.000" in result["top_factors"]
    assert result["trace"]["temporal_reference_mode"] == "subject_auction_date"
    assert result["trace"]["temporal_target_date"] == "2024-03-01 10:00:00"

def test_predict_fair_price_excludes_future_dated_comparables_for_historical_subject():
    subject = {
        "item_id": "subject-historical-cutoff",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
        "latitude": 31.23,
        "longitude": 121.47,
        "auction_date": "2024-03-01 10:00:00",
        "strict_temporal_cutoff": True,
        "valuation_mode": "historical_strict",
    }
    comparables = [
        {
            "item_id": "past-1",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.23,
            "longitude": 121.47,
            "auction_date": "2024-01-01 10:00:00",
        },
        {
            "item_id": "past-2",
            "transaction_price": 1_100_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.23,
            "longitude": 121.47,
            "auction_date": "2024-02-01 10:00:00",
        },
        {
            "item_id": "past-3",
            "transaction_price": 1_200_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.23,
            "longitude": 121.47,
            "auction_date": "2024-03-01 10:00:00",
        },
        {
            "item_id": "future-outlier",
            "transaction_price": 2_200_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.23,
            "longitude": 121.47,
            "auction_date": "2025-03-01 10:00:00",
        },
    ]

    result = predict_fair_price(subject, comparables)

    assert 10_900.0 <= result["predicted_unit_price"] <= 11_100.0
    assert result["trace"]["valuation_mode"] == "historical_strict"
    assert result["trace"]["future_dated_comparable_count_excluded"] == 1
    assert "未来时间可比剔除数=1" in result["top_factors"]

def test_predict_fair_price_applies_subject_risk_discount():
    clean_subject = {
        "item_id": "subject-clean",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
    }
    risky_subject = dict(clean_subject)
    risky_subject["is_occupied"] = True

    comparables = [
        {
            "item_id": "c1",
            "transaction_price": 800_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-01-01 10:00:00",
            "is_occupied": True,
        },
        {
            "item_id": "c2",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    clean_result = predict_fair_price(clean_subject, comparables)
    risky_result = predict_fair_price(risky_subject, comparables)

    assert clean_result["predicted_unit_price"] > 9_300
    assert risky_result["predicted_price"] < clean_result["predicted_price"]

def test_predict_fair_price_supports_configured_risk_factor_override(monkeypatch):
    clean_subject = {
        "item_id": "subject-clean-override",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
    }
    risky_subject = dict(clean_subject)
    risky_subject["is_occupied"] = True

    comparables = [
        {
            "item_id": "c1",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-01-01 10:00:00",
        },
        {
            "item_id": "c2",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    monkeypatch.setattr("src.avm.engine.AVM_CONFIG_MANAGER.get_config", lambda: {"risk_factor_overrides": {"is_occupied": 0.5}})

    clean_result = predict_fair_price(clean_subject, comparables)
    risky_result = predict_fair_price(risky_subject, comparables)

    assert clean_result["predicted_price"] > risky_result["predicted_price"]
    assert risky_result["trace"]["subject_risk_factor"] == 0.5
    assert risky_result["trace"]["risk_factor_override_count"] >= 1

def test_predict_fair_price_supports_configured_radius_override(monkeypatch):
    subject = {
        "item_id": "subject-radius-override",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
        "latitude": 31.2,
        "longitude": 121.5,
    }

    comparables = [
        {
            "item_id": "near-1",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.20000,
            "longitude": 121.50000,
            "auction_date": "2026-01-01 10:00:00",
        },
        {
            "item_id": "near-2",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.20005,
            "longitude": 121.50005,
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "near-3",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.20008,
            "longitude": 121.50008,
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "far-1",
            "transaction_price": 2_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.20500,
            "longitude": 121.50500,
            "auction_date": "2026-04-01 10:00:00",
        },
    ]

    monkeypatch.setattr("src.avm.engine.AVM_CONFIG_MANAGER.get_config", lambda: {"radius_km": 0.1})

    result = predict_fair_price(subject, comparables)

    assert result["strategy"] == "spatial"
    assert result["comparable_count"] == 3
    assert result["trace"]["spatial_radius_km"] == 0.1

def test_predict_fair_price_supports_configured_risk_discount_factor(monkeypatch):
    subject = {
        "item_id": "subject-risk-discount-factor",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
        "is_occupied": True,
    }

    comparables = [
        {
            "item_id": "c1",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-01-01 10:00:00",
        },
        {
            "item_id": "c2",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    monkeypatch.setattr("src.avm.engine.AVM_CONFIG_MANAGER.get_config", lambda: {"risk_discount_factor": 0.9})
    baseline = predict_fair_price(subject, comparables)

    monkeypatch.setattr("src.avm.engine.AVM_CONFIG_MANAGER.get_config", lambda: {"risk_discount_factor": 0.45})
    weaker_discount = predict_fair_price(subject, comparables)

    assert weaker_discount["predicted_price"] > baseline["predicted_price"]
    assert weaker_discount["trace"]["active_risk_discount_factor"] == 0.45
    assert weaker_discount["trace"]["subject_risk_factor"] > baseline["trace"]["subject_risk_factor"]
