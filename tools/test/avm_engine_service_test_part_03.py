from tools.test.avm_engine_service_test_context import *  # noqa: F401,F403


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
