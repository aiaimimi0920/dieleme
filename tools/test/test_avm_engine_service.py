import json
from pathlib import Path

from src.avm.engine import predict_fair_price
from src.avm.service import AVMService


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


def test_predict_fair_price_supports_configured_community_boost(monkeypatch):
    subject = {
        "item_id": "subject-community-boost",
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
            "item_id": "same-community",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.20010,
            "longitude": 121.50010,
            "auction_date": "2026-01-01 10:00:00",
        },
        {
            "item_id": "other-community-1",
            "transaction_price": 1_500_000,
            "area_sqm": 100,
            "community_name": "其他小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.20012,
            "longitude": 121.50012,
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "other-community-2",
            "transaction_price": 1_500_000,
            "area_sqm": 100,
            "community_name": "其他小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.20014,
            "longitude": 121.50014,
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    monkeypatch.setattr(
        "src.avm.engine.AVM_CONFIG_MANAGER.get_config",
        lambda: {"weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.0}},
    )
    low_boost = predict_fair_price(subject, comparables)

    monkeypatch.setattr(
        "src.avm.engine.AVM_CONFIG_MANAGER.get_config",
        lambda: {"weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 3.0}},
    )
    high_boost = predict_fair_price(subject, comparables)

    assert high_boost["predicted_price"] < low_boost["predicted_price"]
    assert high_boost["trace"]["weighting_community_boost"] == 3.0


def test_predict_fair_price_supports_configured_time_decay(monkeypatch):
    subject = {
        "item_id": "subject-time-decay",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
        "latitude": 31.2,
        "longitude": 121.5,
        "auction_date": "2026-06-01 10:00:00",
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
            "latitude": 31.20010,
            "longitude": 121.50010,
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
            "latitude": 31.20012,
            "longitude": 121.50012,
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 1_200_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.20014,
            "longitude": 121.50014,
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    monkeypatch.setattr(
        "src.avm.engine.AVM_CONFIG_MANAGER.get_config",
        lambda: {"weighting": {"distance_power": 2.0, "time_decay": 1.0, "community_boost": 1.3}},
    )
    no_decay = predict_fair_price(subject, comparables)

    monkeypatch.setattr(
        "src.avm.engine.AVM_CONFIG_MANAGER.get_config",
        lambda: {"weighting": {"distance_power": 2.0, "time_decay": 0.4, "community_boost": 1.3}},
    )
    stronger_decay = predict_fair_price(subject, comparables)

    assert stronger_decay["predicted_price"] < no_decay["predicted_price"]
    assert stronger_decay["trace"]["weighting_time_decay"] == 0.4


def test_predict_fair_price_supports_zero_time_decay(monkeypatch):
    subject = {
        "item_id": "subject-zero-time-decay",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
        "latitude": 31.2,
        "longitude": 121.5,
        "auction_date": "2026-06-01 10:00:00",
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
            "latitude": 31.20010,
            "longitude": 121.50010,
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
            "latitude": 31.20012,
            "longitude": 121.50012,
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 1_200_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "latitude": 31.20014,
            "longitude": 121.50014,
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    monkeypatch.setattr(
        "src.avm.engine.AVM_CONFIG_MANAGER.get_config",
        lambda: {"weighting": {"distance_power": 2.0, "time_decay": 1.0, "community_boost": 1.3}},
    )
    no_decay = predict_fair_price(subject, comparables)

    monkeypatch.setattr(
        "src.avm.engine.AVM_CONFIG_MANAGER.get_config",
        lambda: {"weighting": {"distance_power": 2.0, "time_decay": 0.0, "community_boost": 1.3}},
    )
    zero_decay = predict_fair_price(subject, comparables)

    assert zero_decay["predicted_price"] < no_decay["predicted_price"]
    assert zero_decay["trace"]["weighting_time_decay"] == 0.0


def test_predict_fair_price_applies_subject_attribute_adjustment():
    clean_subject = {
        "item_id": "subject-clean-attr",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
    }
    adjusted_subject = dict(clean_subject)
    adjusted_subject.update(
        {
            "build_year": 1995,
            "has_elevator": False,
            "total_floors": 18,
            "floor_level": "顶层",
            "auction_round": 2,
        }
    )

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

    clean_result = predict_fair_price(clean_subject, comparables)
    adjusted_result = predict_fair_price(adjusted_subject, comparables)

    assert adjusted_result["predicted_price"] < clean_result["predicted_price"]
    assert adjusted_result["trace"]["subject_attribute_factor"] < 1.0


def test_predict_fair_price_applies_special_school_tag_premium():
    subject_plain = {
        "item_id": "subject-plain-school",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
    }
    subject_school = dict(subject_plain)
    subject_school["special_school_tag"] = True

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

    plain_result = predict_fair_price(subject_plain, comparables)
    school_result = predict_fair_price(subject_school, comparables)

    assert school_result["predicted_price"] > plain_result["predicted_price"]
    assert school_result["trace"]["subject_attribute_factor"] > 1.0


def test_predict_fair_price_applies_property_fee_discount():
    subject_plain = {
        "item_id": "subject-plain-fee",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
    }
    subject_fee = dict(subject_plain)
    subject_fee["property_fee_owed"] = True

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

    plain_result = predict_fair_price(subject_plain, comparables)
    fee_result = predict_fair_price(subject_fee, comparables)

    assert fee_result["predicted_price"] < plain_result["predicted_price"]
    assert fee_result["trace"]["subject_risk_factor"] < 1.0


def test_predict_fair_price_applies_restricted_purchase_discount():
    subject_plain = {
        "item_id": "subject-plain-limit",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
    }
    subject_limited = dict(subject_plain)
    subject_limited["is_restricted_purchase"] = True

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

    plain_result = predict_fair_price(subject_plain, comparables)
    limited_result = predict_fair_price(subject_limited, comparables)

    assert limited_result["predicted_price"] < plain_result["predicted_price"]
    assert limited_result["trace"]["subject_risk_factor"] < 1.0


def test_predict_fair_price_prefers_matching_layout_and_parking():
    base_subject = {
        "item_id": "subject-layout",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
    }
    subject = dict(base_subject)
    subject.update(
        {
            "layout": "3室2厅1卫",
            "includes_parking": True,
        }
    )
    comparables = [
        {
            "item_id": "c1",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "layout": "3室2厅1卫",
            "includes_parking": True,
            "auction_date": "2026-01-01 10:00:00",
        },
        {
            "item_id": "c2",
            "transaction_price": 800_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "layout": "1室1厅1卫",
            "includes_parking": False,
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 900_000,
            "area_sqm": 100,
            "community_name": "测试小区",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "layout": "2室1厅1卫",
            "includes_parking": False,
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    plain_result = predict_fair_price(base_subject, comparables)
    result = predict_fair_price(subject, comparables)

    assert result["predicted_price"] > plain_result["predicted_price"]


def test_predict_fair_price_does_not_treat_unk_community_as_real_group():
    subject = {
        "item_id": "subject-unk-community",
        "area_sqm": 100,
        "community_name": "UNK",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
    }
    comparables = [
        {
            "item_id": "c1",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "community_name": "UNK",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-01-01 10:00:00",
        },
        {
            "item_id": "c2",
            "transaction_price": 1_050_000,
            "area_sqm": 100,
            "community_name": "UNK",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 1_100_000,
            "area_sqm": 100,
            "community_name": "UNK",
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    result = predict_fair_price(subject, comparables)

    assert result["strategy"] != "community_fallback"


def test_predict_fair_price_rejects_cross_city_same_name_community_matches():
    subject = {
        "item_id": "subject-cross-city-community",
        "area_sqm": 140,
        "community_name": "东方广场",
        "business_area": "洋坪镇集镇",
        "district": "远安县",
        "city": "宜昌市",
        "housing_type": "其他",
    }
    comparables = [
        {
            "item_id": "cross-1",
            "transaction_price": 12_000_000,
            "area_sqm": 100,
            "community_name": "东方广场",
            "district": "东城区",
            "city": "北京市",
            "housing_type": "住宅",
            "auction_date": "2026-01-01 10:00:00",
        },
        {
            "item_id": "cross-2",
            "transaction_price": 13_000_000,
            "area_sqm": 100,
            "community_name": "东方广场",
            "district": "东城区",
            "city": "北京市",
            "housing_type": "住宅",
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "cross-3",
            "transaction_price": 11_500_000,
            "area_sqm": 100,
            "community_name": "东方广场",
            "district": "东城区",
            "city": "北京市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "local-1",
            "transaction_price": 220_000,
            "area_sqm": 140,
            "business_area": "洋坪镇集镇",
            "district": "远安县",
            "city": "宜昌市",
            "housing_type": "其他",
            "auction_date": "2026-01-01 10:00:00",
        },
        {
            "item_id": "local-2",
            "transaction_price": 240_000,
            "area_sqm": 140,
            "business_area": "洋坪镇集镇",
            "district": "远安县",
            "city": "宜昌市",
            "housing_type": "其他",
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "local-3",
            "transaction_price": 230_000,
            "area_sqm": 140,
            "business_area": "洋坪镇集镇",
            "district": "远安县",
            "city": "宜昌市",
            "housing_type": "其他",
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    result = predict_fair_price(subject, comparables)

    assert result["strategy"] != "community_fallback"
    assert result["predicted_unit_price"] < 3000


def test_predict_fair_price_uses_robust_aggregation_under_high_dispersion():
    subject = {
        "item_id": "subject-robust",
        "area_sqm": 100,
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
    }
    comparables = [
        {
            "item_id": "c1",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "c2",
            "transaction_price": 1_050_000,
            "area_sqm": 100,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 4_000_000,
            "area_sqm": 100,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "c4",
            "transaction_price": 1_020_000,
            "area_sqm": 100,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "c5",
            "transaction_price": 1_030_000,
            "area_sqm": 100,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "c6",
            "transaction_price": 1_040_000,
            "area_sqm": 100,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    result = predict_fair_price(subject, comparables)

    assert result["trace"]["robust_unit_blend"] > 0
    assert result["trace"]["trimmed_outlier_count"] >= 1
    assert result["trace"]["uncertainty_blend"] > 0
    assert result["predicted_unit_price"] < 20000


def test_predict_fair_price_applies_area_scale_guard_for_large_subject():
    subject = {
        "item_id": "subject-area-scale",
        "area_sqm": 600,
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "商业",
    }
    comparables = [
        {
            "item_id": "c1",
            "transaction_price": 1_000_000,
            "area_sqm": 80,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "商业",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "c2",
            "transaction_price": 1_100_000,
            "area_sqm": 90,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "商业",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 1_200_000,
            "area_sqm": 100,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "商业",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "c4",
            "transaction_price": 1_300_000,
            "area_sqm": 110,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "商业",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "c5",
            "transaction_price": 1_400_000,
            "area_sqm": 120,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "商业",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "c6",
            "transaction_price": 1_500_000,
            "area_sqm": 130,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "商业",
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    result = predict_fair_price(subject, comparables)

    assert result["trace"]["area_scale_severity"] > 0
    assert result["trace"]["comparable_area_median"] < subject["area_sqm"]


def test_predict_fair_price_applies_locality_guard_for_township_fallback():
    subject = {
        "item_id": "subject-locality",
        "area_sqm": 160,
        "district": "瑞安市",
        "city": "温州市",
        "business_area": "陶山镇",
        "housing_type": "住宅",
        "coordinate_strategy": "missing",
    }
    comparables = [
        {
            "item_id": "c1",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "district": "瑞安市",
            "city": "温州市",
            "business_area": "陶山镇",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "c2",
            "transaction_price": 1_050_000,
            "area_sqm": 100,
            "district": "瑞安市",
            "city": "温州市",
            "business_area": "陶山镇",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 1_100_000,
            "area_sqm": 100,
            "district": "瑞安市",
            "city": "温州市",
            "business_area": "陶山镇",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    result = predict_fair_price(subject, comparables)

    assert result["trace"]["locality_severity"] > 0


def test_predict_fair_price_strengthens_uncertainty_blend_when_community_missing():
    subject = {
        "item_id": "subject-missing-community",
        "area_sqm": 180,
        "district": "新密市",
        "city": "郑州市",
        "housing_type": "其他",
        "coordinate_strategy": "missing",
    }
    comparables = [
        {
            "item_id": f"c{i}",
            "transaction_price": 300_000 + i * 20_000,
            "area_sqm": 120 + i * 10,
            "district": "新密市",
            "city": "郑州市",
            "housing_type": "其他",
            "auction_date": "2026-03-01 10:00:00",
        }
        for i in range(1, 7)
    ]

    result = predict_fair_price(subject, comparables)

    assert result["trace"]["uncertainty_blend"] >= 0.3


def test_predict_fair_price_strengthens_uncertainty_for_low_tier_weak_engagement():
    base_subject = {
        "item_id": "subject-base-township",
        "area_sqm": 160,
        "district": "瑞安市",
        "city": "温州市",
        "community_name": "测试小区",
        "business_area": "瑞安城区",
        "housing_type": "住宅",
        "coordinate_strategy": "observed",
        "bid_count": 8,
        "apply_count": 4,
    }
    guarded_subject = dict(base_subject)
    guarded_subject.update(
        {
            "item_id": "subject-guarded-township",
            "community_name": "",
            "business_area": "陶山镇",
            "coordinate_strategy": "missing",
            "bid_count": 1,
            "apply_count": 1,
        }
    )
    comparables = [
        {
            "item_id": f"c{i}",
            "transaction_price": 1_000_000 + i * 30_000,
            "area_sqm": 100 + i * 5,
            "district": "瑞安市",
            "city": "温州市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        }
        for i in range(1, 7)
    ]

    base_result = predict_fair_price(base_subject, comparables)
    guarded_result = predict_fair_price(guarded_subject, comparables)

    assert guarded_result["trace"]["low_tier_locality"] is True
    assert guarded_result["trace"]["weak_market_engagement"] is True
    assert guarded_result["trace"]["uncertainty_blend"] > base_result["trace"]["uncertainty_blend"]
    assert guarded_result["predicted_unit_price"] < base_result["predicted_unit_price"]


def test_predict_fair_price_hard_caps_starting_price_for_parking_regime():
    subject = {
        "item_id": "subject-parking-cap",
        "area_sqm": 40,
        "district": "武侯区",
        "city": "成都市",
        "community_name": "天府长城",
        "business_area": "人民南路",
        "housing_type": "车位",
        "starting_price": 40000,
        "coordinate_strategy": "missing",
    }
    comparables = [
        {
            "item_id": f"p{i}",
            "transaction_price": 600_000 + i * 30_000,
            "area_sqm": 40,
            "district": "武侯区",
            "city": "成都市",
            "community_name": "天府长城",
            "business_area": "人民南路",
            "housing_type": "车位",
            "auction_date": "2026-03-01 10:00:00",
        }
        for i in range(1, 7)
    ]

    result = predict_fair_price(subject, comparables)

    assert result["trace"]["starting_price_guard_ratio"] > 4.0
    assert result["predicted_unit_price"] <= (40000 / 40) * 1.8 + 1


def test_predict_fair_price_tightens_starting_price_guard_for_low_tier_special_asset():
    base_subject = {
        "item_id": "subject-starting-base",
        "area_sqm": 140,
        "district": "远安县",
        "city": "宜昌市",
        "business_area": "主城区",
        "housing_type": "其他",
        "starting_price": 234048,
        "coordinate_strategy": "observed",
        "bid_count": 5,
        "apply_count": 3,
    }
    guarded_subject = dict(base_subject)
    guarded_subject.update(
        {
            "item_id": "subject-starting-guarded",
            "business_area": "洋坪镇集镇",
            "community_name": "",
            "coordinate_strategy": "missing",
            "bid_count": 1,
            "apply_count": 1,
        }
    )
    comparables = [
        {
            "item_id": f"c{i}",
            "transaction_price": 900_000 + i * 60_000,
            "area_sqm": 100,
            "district": "远安县",
            "city": "宜昌市",
            "housing_type": "其他",
            "auction_date": "2026-03-01 10:00:00",
        }
        for i in range(1, 7)
    ]

    base_result = predict_fair_price(base_subject, comparables)
    guarded_result = predict_fair_price(guarded_subject, comparables)

    assert guarded_result["trace"]["starting_price_guard_blend"] >= base_result["trace"]["starting_price_guard_blend"]
    assert guarded_result["trace"]["starting_price_guard_blend"] > 0
    assert guarded_result["predicted_unit_price"] < base_result["predicted_unit_price"]


def test_predict_fair_price_prefers_matching_asset_regime_for_large_commercial():
    subject = {
        "item_id": "subject-large-commercial",
        "area_sqm": 260,
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "商业",
    }
    comparables = [
        {
            "item_id": "micro-1",
            "transaction_price": 900_000,
            "area_sqm": 15,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "商业",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "micro-2",
            "transaction_price": 1_050_000,
            "area_sqm": 18,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "商业",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "large-1",
            "transaction_price": 900_000,
            "area_sqm": 260,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "商业",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "large-2",
            "transaction_price": 950_000,
            "area_sqm": 250,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "商业",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "large-3",
            "transaction_price": 980_000,
            "area_sqm": 255,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "商业",
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    result = predict_fair_price(subject, comparables)

    assert result["predicted_unit_price"] < 10000


def test_predict_fair_price_skips_zero_same_type_district_tier_for_special_regime():
    subject = {
        "item_id": "subject-commercial-zero-same-type",
        "area_sqm": 230,
        "district": "虎丘区",
        "city": "苏州市",
        "housing_type": "商业",
        "coordinate_strategy": "missing",
    }
    comparables = [
        {
            "item_id": "district-home-1",
            "transaction_price": 1_500_000,
            "area_sqm": 100,
            "district": "虎丘区",
            "city": "苏州市",
            "housing_type": "住宅",
            "auction_date": "2026-01-01 10:00:00",
        },
        {
            "item_id": "district-home-2",
            "transaction_price": 1_650_000,
            "area_sqm": 100,
            "district": "虎丘区",
            "city": "苏州市",
            "housing_type": "住宅",
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "district-home-3",
            "transaction_price": 1_700_000,
            "area_sqm": 100,
            "district": "虎丘区",
            "city": "苏州市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
        {
            "item_id": "city-commercial-1",
            "transaction_price": 230_000,
            "area_sqm": 230,
            "district": "吴中区",
            "city": "苏州市",
            "housing_type": "商业",
            "auction_date": "2026-01-01 10:00:00",
        },
        {
            "item_id": "city-commercial-2",
            "transaction_price": 260_000,
            "area_sqm": 230,
            "district": "相城区",
            "city": "苏州市",
            "housing_type": "商业",
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "city-commercial-3",
            "transaction_price": 280_000,
            "area_sqm": 230,
            "district": "姑苏区",
            "city": "苏州市",
            "housing_type": "商业",
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    result = predict_fair_price(subject, comparables)

    assert result["strategy"] == "city_fallback"
    assert result["predicted_unit_price"] < 2000


def test_evaluate_request_passes_extended_subject_fields(tmp_path: Path):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "4001",
            "url": "https://x/4001",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2,
            "经度": 121.5,
        },
        {
            "id": "4002",
            "url": "https://x/4002",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2026-02-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2001,
            "经度": 121.5001,
        },
    ]
    (data_dir / "2026-01-01.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    service = AVMService(data_dir=str(data_dir))
    result = service.evaluate_request(
        {
            "request_id": "req-ext-1",
            "subject": {
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "area_sqm": 100,
                "housing_type": "住宅",
                "build_year": 1995,
                "total_floors": 18,
                "has_elevator": False,
                "floor_level": "顶层",
                "layout": "3室2厅1卫",
                "includes_parking": True,
                "special_school_tag": True,
                "has_keys": False,
                "bid_count": 12,
                "apply_count": 6,
            },
            "auction": {
                "starting_price": 850000,
                "auction_date": "2026-04-01",
                "auction_round": 2,
                "tax_burden": "买受人承担全部",
            },
            "risk_flags": {
                "property_fee_owed": True,
                "is_restricted_purchase": True,
            },
        }
    )

    assert result["valuation"]["estimated_fair_price"] is not None
    assert result["risk_validation"]["ok"] is False
    assert result["risk_validation"]["missing_required_count"] > 0
    assert result["trace"]["strategy"] in {"spatial", "community_fallback"}
    assert result["trace"]["valuation_mode"] == "current_market"
    assert result["trace"]["temporal_reference_mode"] == "current_time"
    assert any(item["tag"] == "property_fee_owed" for item in result["risk_adjustments"])
    assert any(item["tag"] == "is_restricted_purchase" for item in result["risk_adjustments"])


def test_evaluate_request_supports_historical_strict_mode(tmp_path: Path):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "4501",
            "url": "https://x/4501",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2024-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2,
            "经度": 121.5,
        },
        {
            "id": "4502",
            "url": "https://x/4502",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2024-02-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2001,
            "经度": 121.5001,
        },
        {
            "id": "4503",
            "url": "https://x/4503",
            "成交价格": "120万",
            "起拍价格": "100万",
            "建筑面积": "100㎡",
            "交易时间": "2024-03-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2002,
            "经度": 121.5002,
        },
        {
            "id": "4504",
            "url": "https://x/4504",
            "成交价格": "220万",
            "起拍价格": "180万",
            "建筑面积": "100㎡",
            "交易时间": "2025-03-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2003,
            "经度": 121.5003,
        },
    ]
    (data_dir / "2024-01-01.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    service = AVMService(data_dir=str(data_dir))

    current_market = service.evaluate_request(
        {
            "request_id": "req-current-market",
            "subject": {
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "area_sqm": 100,
                "housing_type": "住宅",
            },
            "auction": {
                "starting_price": 850000,
                "auction_date": "2024-03-01 10:00:00",
            },
        }
    )
    historical = service.evaluate_request(
        {
            "request_id": "req-historical-strict",
            "subject": {
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "area_sqm": 100,
                "housing_type": "住宅",
            },
            "auction": {
                "starting_price": 850000,
                "auction_date": "2024-03-01 10:00:00",
            },
            "options": {
                "valuation_mode": "historical_strict",
            },
        }
    )

    assert current_market["trace"]["valuation_mode"] == "current_market"
    assert current_market["trace"]["future_dated_comparable_count_excluded"] == 0
    assert current_market["trace"]["temporal_reference_mode"] == "current_time"
    assert historical["trace"]["valuation_mode"] == "historical_strict"
    assert historical["trace"]["future_dated_comparable_count_excluded"] == 1
    assert historical["trace"]["temporal_reference_mode"] == "subject_auction_date"


def test_predict_fair_price_applies_evaluation_price_soft_anchor():
    subject_plain = {
        "item_id": "subject-plain-eval",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
    }
    subject_eval = dict(subject_plain)
    subject_eval.update(
        {
            "evaluation_price": 1_300_000,
            "extraction_confidence": 0.9,
        }
    )

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

    plain_result = predict_fair_price(subject_plain, comparables)
    eval_result = predict_fair_price(subject_eval, comparables)

    assert eval_result["predicted_price"] > plain_result["predicted_price"]
    assert eval_result["trace"]["evaluation_anchor_blend"] > 0


def test_predict_fair_price_ignores_extreme_evaluation_anchor():
    subject_plain = {
        "item_id": "subject-plain-eval-skip",
        "area_sqm": 100,
        "community_name": "测试小区",
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
    }
    subject_eval = dict(subject_plain)
    subject_eval.update(
        {
            "evaluation_price": 900_000_000,
            "extraction_confidence": 0.9,
        }
    )

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

    plain_result = predict_fair_price(subject_plain, comparables)
    eval_result = predict_fair_price(subject_eval, comparables)

    assert abs(eval_result["predicted_price"] - plain_result["predicted_price"]) < 1.0
    assert eval_result["trace"]["evaluation_anchor_blend"] == 0.0


def test_predict_fair_price_applies_starting_price_guard_on_extreme_fallback():
    subject = {
        "item_id": "subject-start-guard",
        "area_sqm": 100,
        "district": "浦东新区",
        "city": "上海市",
        "housing_type": "住宅",
        "starting_price": 200000,
        "coordinate_strategy": "missing",
    }

    comparables = [
        {
            "item_id": "c1",
            "transaction_price": 1_000_000,
            "area_sqm": 100,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-01-01 10:00:00",
        },
        {
            "item_id": "c2",
            "transaction_price": 1_050_000,
            "area_sqm": 100,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-02-01 10:00:00",
        },
        {
            "item_id": "c3",
            "transaction_price": 1_100_000,
            "area_sqm": 100,
            "district": "浦东新区",
            "city": "上海市",
            "housing_type": "住宅",
            "auction_date": "2026-03-01 10:00:00",
        },
    ]

    result = predict_fair_price(subject, comparables)

    assert result["trace"]["starting_price_guard_blend"] > 0
    assert result["predicted_unit_price"] < 10000


def test_avm_service_excludes_subject_from_comparables(tmp_path: Path):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "1001",
            "url": "https://x/1001",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
        },
        {
            "id": "1002",
            "url": "https://x/1002",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2026-02-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
        },
        {
            "id": "1003",
            "url": "https://x/1003",
            "成交价格": "120万",
            "起拍价格": "100万",
            "建筑面积": "100㎡",
            "交易时间": "2026-03-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
        },
    ]
    (data_dir / "2026-01-01.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    service = AVMService(data_dir=str(data_dir))
    result = service.predict_by_item_id("1001")

    assert result["item_id"] == "1001"
    assert result["comparable_count"] == 2
    assert result["margin_of_safety"] is not None


def test_avm_service_filters_implausible_comparables(tmp_path: Path):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "5001",
            "url": "https://x/5001",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
        },
        {
            "id": "5002",
            "url": "https://x/5002",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2026-02-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
        },
        {
            "id": "5003",
            "url": "https://x/5003",
            "成交价格": 1,
            "起拍价格": 1,
            "建筑面积": "100㎡",
            "交易时间": "2026-03-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
        },
    ]
    (data_dir / "2026-01-01.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    service = AVMService(data_dir=str(data_dir))
    result = service.predict_by_item_id("5001")
    health = service.health_snapshot()

    assert result["comparable_count"] == 1
    assert health["quality_filtered_records"] == 1


def test_avm_service_marks_manual_review_for_broad_fallback(tmp_path: Path):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "6001",
            "url": "https://x/6001",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
        },
        {
            "id": "6002",
            "url": "https://x/6002",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2026-02-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
        },
        {
            "id": "6003",
            "url": "https://x/6003",
            "成交价格": "120万",
            "起拍价格": "100万",
            "建筑面积": "100㎡",
            "交易时间": "2026-03-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
        },
    ]
    (data_dir / "2026-01-01.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    service = AVMService(data_dir=str(data_dir))
    result = service.evaluate_request(
        {
            "request_id": "manual-review-1",
            "subject": {
                "city": "上海市",
                "district": "浦东新区",
                "area_sqm": 100,
                "housing_type": "其他",
            },
            "auction": {},
        }
    )

    assert result["manual_review"]["recommended"] is True
    assert result["manual_review"]["reasons"]


def test_predict_by_item_id_surfaces_risk_validation_and_review_reason(tmp_path: Path):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "4701",
            "url": "https://x/4701",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2,
            "经度": 121.5,
        },
        {
            "id": "4702",
            "url": "https://x/4702",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2026-02-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2001,
            "经度": 121.5001,
        },
    ]
    (data_dir / "2026-01-01.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    service = AVMService(data_dir=str(data_dir))
    result = service.predict_by_item_id("4701")

    assert result["risk_validation"]["ok"] is False
    assert result["risk_validation"]["missing_required_count"] > 0
    assert "risk_feature_incomplete" in result["manual_review_reasons"]
    assert result["manual_review_recommended"] is True


def test_avm_service_fills_missing_subject_coordinates_from_centroid(tmp_path: Path):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "2001",
            "url": "https://x/2001",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
        },
        {
            "id": "2002",
            "url": "https://x/2002",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2026-02-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.200001,
            "经度": 121.500001,
        },
        {
            "id": "2003",
            "url": "https://x/2003",
            "成交价格": "120万",
            "起拍价格": "100万",
            "建筑面积": "100㎡",
            "交易时间": "2026-03-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.200101,
            "经度": 121.500101,
        },
    ]
    (data_dir / "2026-01-01.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    service = AVMService(data_dir=str(data_dir))
    result = service.predict_by_item_id("2001")

    assert result["predicted_price"] is not None
    assert result["trace"]["subject_coordinate_strategy"] == "community_centroid"


def test_avm_service_predict_by_item_id_uses_repository_subject_without_file_scan(monkeypatch):
    class _FakeRepo:
        enabled = True

        def __init__(self):
            self.lookup_calls = 0

        def get_flat_item(self, item_id: str):
            self.lookup_calls += 1
            if item_id == "repo-1":
                return {
                    "item_id": "repo-1",
                    "source_url": "https://x/repo-1",
                    "transaction_price": 1000000.0,
                    "starting_price": 800000.0,
                    "area_sqm": 100.0,
                    "auction_date": "2026-01-01 10:00:00",
                    "city": "上海市",
                    "district": "浦东新区",
                    "community_name": "测试小区",
                    "housing_type": "住宅",
                }
            return None

        def iter_flat_items(self, limit: int | None = None):
            return [
                {
                    "item_id": "repo-1",
                    "source_url": "https://x/repo-1",
                    "transaction_price": 1000000.0,
                    "starting_price": 800000.0,
                    "area_sqm": 100.0,
                    "auction_date": "2026-01-01 10:00:00",
                    "city": "上海市",
                    "district": "浦东新区",
                    "community_name": "测试小区",
                    "housing_type": "住宅",
                },
                {
                    "item_id": "repo-2",
                    "source_url": "https://x/repo-2",
                    "transaction_price": 1100000.0,
                    "starting_price": 900000.0,
                    "area_sqm": 100.0,
                    "auction_date": "2026-02-01 10:00:00",
                    "city": "上海市",
                    "district": "浦东新区",
                    "community_name": "测试小区",
                    "housing_type": "住宅",
                },
            ]

        def dataset_signature(self):
            return (2, "2026-05-12 00:00:00")

    repo = _FakeRepo()
    service = AVMService(data_dir="unused", repository=repo)
    monkeypatch.setattr(service, "_iter_data_files", lambda: (_ for _ in ()).throw(RuntimeError("file scan should not happen")))

    result = service.predict_by_item_id("repo-1")

    assert result["item_id"] == "repo-1"
    assert result["comparable_count"] == 1
    assert repo.lookup_calls == 1


def test_avm_service_ensure_coordinate_cache_uses_canonical_rows_without_feature_build(monkeypatch):
    class _FakeRepo:
        enabled = True

        def yield_coordinate_rows(self, chunk_size: int = 1000):
            yield {
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "latitude": 31.2,
                "longitude": 121.5,
            }

        def yield_flat_items(self, limit: int | None = None, chunk_size: int = 1000):
            yield {
                "item_id": "coord-1",
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "latitude": 31.2,
                "longitude": 121.5,
            }

        def dataset_signature(self):
            return (1, "2026-05-12 00:00:00")

    service = AVMService(data_dir="unused", repository=_FakeRepo())

    def _forbidden_build_features(_value):
        raise AssertionError("ensure_coordinate_cache should not call build_features")

    monkeypatch.setattr("src.avm.service.build_features", _forbidden_build_features)

    centroids = service.ensure_coordinate_cache()

    assert centroids["community::测试小区"] == (31.2, 121.5)


def test_avm_service_health_snapshot_lightweight_does_not_build_dataset(monkeypatch):
    service = AVMService(data_dir="unused", repository=None)

    def _forbidden_build():
        raise AssertionError("lightweight health snapshot should not build feature dataset when cache is empty")

    monkeypatch.setattr(service, "_build_feature_dataset", _forbidden_build)

    health = service.health_snapshot(lightweight=True)

    assert health["dataset_size"] == 0
    assert health["risk_validation_counts"] == {"ok": 0, "incomplete": 0, "invalid": 0}
    assert health["risk_feature_completeness_avg"] == 0.0
    assert health["feature_cache_ready"] is False
    assert health["model_version"] == service.model_version()


def test_avm_service_health_snapshot_surfaces_risk_validation_summary(tmp_path: Path):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "4801",
            "url": "https://x/4801",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2,
            "经度": 121.5,
            "housing_type": "住宅",
            "is_occupied": False,
            "has_long_lease": False,
            "clear_delivery": True,
            "tax_burden": "各自承担",
            "is_fractional_share": False,
            "build_year": 2010,
            "total_floors": 18,
            "floor_level": "中区",
            "has_elevator": True,
            "orientation": "南",
            "land_right_type": "出让",
            "is_haunted": False,
            "has_keys": True,
            "property_fee_owed": False,
            "special_school_tag": False,
            "evaluation_price": 1000000,
            "layout": "2室1厅1卫",
            "is_restricted_purchase": False,
            "includes_parking": False,
            "tax_is_company_owned": False,
            "has_lease_before_mortgage": False,
        },
        {
            "id": "4802",
            "url": "https://x/4802",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2026-02-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2001,
            "经度": 121.5001,
        },
    ]
    (data_dir / "2026-01-01.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    service = AVMService(data_dir=str(data_dir))
    health = service.health_snapshot(lightweight=False)

    assert health["dataset_size"] == 2
    assert health["risk_validation_counts"]["ok"] == 1
    assert health["risk_validation_counts"]["incomplete"] == 1
    assert health["risk_validation_counts"]["invalid"] == 0
    assert 0.0 < health["risk_feature_completeness_avg"] < 1.0


def test_avm_service_health_snapshot_surfaces_active_risk_factor_overrides(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    (data_dir / "2026-01-01.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        "src.avm.engine.AVM_CONFIG_MANAGER.get_config",
        lambda: {"risk_factor_overrides": {"is_occupied": 0.5}},
    )

    service = AVMService(data_dir=str(data_dir))
    health = service.health_snapshot(lightweight=True)

    assert health["active_risk_factor_override_count"] == 1
    assert health["active_risk_factor_overrides"]["is_occupied"] == 0.5


def test_avm_service_health_snapshot_surfaces_active_weighting(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    (data_dir / "2026-01-01.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        "src.avm.service.get_effective_weighting",
        lambda defaults=None: {"distance_power": 1.7, "time_decay": 0.8, "community_boost": 2.2},
    )

    service = AVMService(data_dir=str(data_dir))
    health = service.health_snapshot(lightweight=True)

    assert health["active_weighting"]["distance_power"] == 1.7
    assert health["active_weighting"]["community_boost"] == 2.2


def test_avm_service_health_snapshot_surfaces_active_risk_discount_factor(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    (data_dir / "2026-01-01.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        "src.avm.service.get_effective_risk_discount_factor",
        lambda default=0.9: 0.45,
    )

    service = AVMService(data_dir=str(data_dir))
    health = service.health_snapshot(lightweight=True)

    assert health["active_risk_discount_factor"] == 0.45


def test_avm_service_health_snapshot_surfaces_coordinate_strategy_counts(tmp_path: Path):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "1",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2,
            "经度": 121.5,
        },
        {
            "id": "2",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-02 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
        },
    ]
    (data_dir / "2026-01-01.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    service = AVMService(data_dir=str(data_dir))
    health = service.health_snapshot(lightweight=False)

    assert health["coordinate_strategy_counts"]["observed"] == 1
    assert health["coordinate_strategy_counts"]["community_centroid"] == 1


def test_avm_service_limits_candidate_pool_for_large_dataset(monkeypatch):
    service = AVMService(data_dir="unused", repository=None)
    dataset = []
    for index in range(6001):
        dataset.append(
            {
                "item_id": f"comp-{index}",
                "auction_date": f"2026-03-{(index % 28) + 1:02d} 10:00:00",
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "business_area": "张江",
                "area_sqm": 100.0,
                "starting_price": 800000.0,
                "transaction_price": 1000000.0 + index,
                "actual_paid_price": 1000000.0 + index,
                "unit_price": 10000.0,
                "housing_type": "住宅",
            }
        )

    monkeypatch.setattr(service, "_dataset_signature", lambda: ("test", 1))
    monkeypatch.setattr(service, "_build_feature_dataset", lambda: dataset)
    monkeypatch.setattr(service, "_centroid_cache", {})

    captured = {}

    def _fake_predict(subject, comparables):
        captured["count"] = len(list(comparables))
        return {
            "predicted_price": 1000000.0,
            "predicted_unit_price": 10000.0,
            "confidence": 0.5,
            "comparable_count": captured["count"],
            "strategy": "city_fallback",
            "trace": {},
            "top_factors": [],
        }

    monkeypatch.setattr("src.avm.service.predict_fair_price", _fake_predict)

    result = service.predict_by_item_data(
        {
            "id": "subject-1",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-03-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "最靠近商圈": "张江",
            "housing_type": "住宅",
        }
    )

    assert captured["count"] == 5000
    assert result["trace"]["candidate_pool_size"] == 5000


def test_avm_service_build_feature_dataset_uses_repository_feature_rows_without_canonical_mapper(monkeypatch):
    class _FakeRepo:
        enabled = True

        def yield_feature_source_rows(self, limit: int | None = None, chunk_size: int = 1000):
            yield {
                "item_id": "repo-1",
                "auction_date": "2026-01-01 10:00:00",
                "province": "上海市",
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "business_area": "张江",
                "area_sqm": 100.0,
                "starting_price": 800000.0,
                "transaction_price": 1000000.0,
                "actual_paid_price": 1000000.0,
                "latitude": 31.2,
                "longitude": 121.5,
                "status": "done",
                "housing_type": "住宅",
            }

        def dataset_signature(self):
            return (1, "2026-05-12 00:00:00")

    service = AVMService(data_dir="unused", repository=_FakeRepo())

    def _forbidden_map(_value):
        raise AssertionError("repository feature rows should bypass map_raw_to_canonical")

    monkeypatch.setattr("src.avm.service.map_raw_to_canonical", _forbidden_map)

    dataset = service._build_feature_dataset()

    assert len(dataset) == 1
    assert dataset[0]["item_id"] == "repo-1"


def test_avm_service_predict_by_item_data_uses_repository_candidate_rows_without_full_dataset(monkeypatch):
    class _FakeRepo:
        enabled = True

        def build_coordinate_centroids(self):
            return {"community::测试小区": (31.2, 121.5)}

        def iter_feature_candidate_rows(self, subject, **kwargs):
            return [
                {
                    "item_id": "repo-2",
                    "auction_date": "2026-02-01 10:00:00",
                    "province": "上海市",
                    "city": "上海市",
                    "district": "浦东新区",
                    "community_name": "测试小区",
                    "business_area": "张江",
                    "area_sqm": 100.0,
                    "starting_price": 900000.0,
                    "transaction_price": 1100000.0,
                    "actual_paid_price": 1100000.0,
                    "latitude": 31.2,
                    "longitude": 121.5,
                    "status": "done",
                    "housing_type": "住宅",
                }
            ]

        def dataset_signature(self):
            return (2, "2026-05-12 00:00:00")

    service = AVMService(data_dir="unused", repository=_FakeRepo())

    def _forbidden_build():
        raise AssertionError("predict_by_item_data fast path should not build full feature dataset")

    monkeypatch.setattr(service, "_build_feature_dataset", _forbidden_build)

    result = service.predict_by_item_data(
        {
            "id": "subject-1",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-03-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "最靠近商圈": "张江",
            "housing_type": "住宅",
        }
    )

    assert result["trace"]["candidate_source"] == "repository_candidates"
    assert result["trace"]["candidate_pool_size"] == 1


def test_avm_service_predict_by_item_data_prefers_repository_analysis_candidate_rows(monkeypatch):
    class _FakeRepo:
        enabled = True

        def build_coordinate_centroids(self):
            return {"community::测试小区": (31.2, 121.5)}

        def iter_analysis_candidate_rows(self, subject, **kwargs):
            return [
                {
                    "item_id": "repo-analysis-1",
                    "auction_date": "2026-02-01 10:00:00",
                    "province": "上海市",
                    "city": "上海市",
                    "district": "浦东新区",
                    "community_name": "测试小区",
                    "business_area": "张江",
                    "area_sqm": 100.0,
                    "starting_price": 900000.0,
                    "transaction_price": 1100000.0,
                    "actual_paid_price": 1100000.0,
                    "latitude": 31.2,
                    "longitude": 121.5,
                    "status": "done",
                    "housing_type": "住宅",
                }
            ]

        def iter_feature_candidate_rows(self, subject, **kwargs):
            raise AssertionError("analysis candidate fast path should take precedence")

        def dataset_signature(self):
            return (2, "2026-05-12 00:00:00")

    service = AVMService(data_dir="unused", repository=_FakeRepo())

    def _forbidden_build():
        raise AssertionError("repository analysis candidate fast path should not build full feature dataset")

    monkeypatch.setattr(service, "_build_feature_dataset", _forbidden_build)

    result = service.predict_by_item_data(
        {
            "id": "subject-analysis-1",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-03-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "最靠近商圈": "张江",
            "housing_type": "住宅",
        }
    )

    assert result["trace"]["candidate_source"] == "repository_analysis_candidates"
    assert result["trace"]["candidate_pool_size"] == 1
