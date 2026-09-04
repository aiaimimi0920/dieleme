from tools.test.avm_engine_service_test_context import *  # noqa: F401,F403


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
