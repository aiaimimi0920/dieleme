from tools.test.avm_engine_service_test_context import *  # noqa: F401,F403


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
