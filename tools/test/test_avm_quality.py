from src.avm.quality import price_plausibility


def test_price_plausibility_rejects_low_unit_other_record():
    passed, reason = price_plausibility(
        {
            "actual_paid_price": 14001,
            "area_sqm": 32.12,
            "housing_type": "其他",
        }
    )

    assert passed is False
    assert reason == "unit_price_too_small"


def test_price_plausibility_rejects_large_area_low_unit_non_industrial_record():
    passed, reason = price_plausibility(
        {
            "actual_paid_price": 2_894_212.72,
            "area_sqm": 9638.0,
            "housing_type": "其他",
        }
    )

    assert passed is False
    assert reason in {"unit_price_too_small", "large_area_low_unit_price"}
