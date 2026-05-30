"""AVM 数据质量辅助函数。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def actual_total_price(record: Dict[str, Any]) -> Optional[float]:
    for key in ("actual_paid_price", "transaction_price"):
        value = _to_float(record.get(key))
        if value is not None and value > 0:
            return value
    return None


def unit_price(record: Dict[str, Any]) -> Optional[float]:
    price = actual_total_price(record)
    area = _to_float(record.get("area_sqm"))
    if price is None or area is None or area <= 0:
        return None
    return price / area


def price_plausibility(record: Dict[str, Any]) -> Tuple[bool, str | None]:
    price = actual_total_price(record)
    area = _to_float(record.get("area_sqm"))
    if price is None:
        return False, "missing_price"
    if price < 1000:
        return False, "price_too_small"
    if area is None or area <= 0:
        return False, "missing_area"

    per_sqm = price / area
    housing_type = str(record.get("housing_type") or "其他")

    min_unit = 500.0
    max_unit = 300000.0
    if housing_type == "工业":
        min_unit = 120.0
        max_unit = 120000.0
    elif housing_type == "车位":
        min_unit = 1000.0
        max_unit = 500000.0
    elif housing_type in {"商业", "办公"}:
        min_unit = 800.0
    elif housing_type == "别墅":
        min_unit = 800.0
        max_unit = 500000.0

    if per_sqm < min_unit:
        return False, "unit_price_too_small"
    if per_sqm > max_unit:
        return False, "unit_price_too_large"
    if area > 5000 and housing_type != "工业" and per_sqm < 500:
        return False, "huge_area_low_unit_price"
    if area > 1000 and housing_type in {"住宅", "商业", "办公", "别墅", "其他"} and per_sqm < 800:
        return False, "large_area_low_unit_price"
    return True, None
