from tools.test.avm_engine_service_test_context import *  # noqa: F401,F403


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
