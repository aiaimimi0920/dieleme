"""AVM 特征构建器。"""

from __future__ import annotations

from datetime import datetime
from typing import Any


EPOCH_YEAR = 1970
EPOCH_MONTH = 1


RISK_BOOL_FIELDS: tuple[str, ...] = (
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "is_haunted",
    "has_keys",
    "property_fee_owed",
    "special_school_tag",
    "is_restricted_purchase",
    "includes_parking",
    "is_fractional_share",
    "tax_is_company_owned",
    "has_lease_before_mortgage",
)


_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
)


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(cleaned, fmt)
            except ValueError:
                continue
    return None


def _month_index(value: Any) -> int | None:
    dt = _coerce_datetime(value)
    if dt is None:
        return None
    return (dt.year - EPOCH_YEAR) * 12 + (dt.month - EPOCH_MONTH)


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {"1", "true", "yes", "y", "是", "有", "真"}:
            return True
        if norm in {"0", "false", "no", "n", "否", "无", "假", ""}:
            return False
    return False


def build_features(record: dict[str, Any], risk: dict[str, Any]) -> dict[str, Any]:
    """构建首版 AVM 特征。

    首版特征：
    - 时间（月序号）
    - 价格
    - 面积
    - 行政区
    - 小区
    - 风控布尔 one-hot

    Args:
        record: 规范层基础字段，至少包含拍卖时间、价格、面积、行政区、小区等。
        risk: 风控字段字典。

    Returns:
        统一 dict，可直接用于 parquet/jsonl 写盘。
    """

    features: dict[str, Any] = {
        "month_index": _month_index(record.get("auction_date")),
        "price": _to_float(
            record.get("transaction_price")
            if record.get("transaction_price") is not None
            else record.get("actual_paid_price")
        ),
        "area_sqm": _to_float(record.get("area_sqm")),
        "district": record.get("district") or record.get("admin_district"),
        "community_name": record.get("community_name"),
    }

    for key in RISK_BOOL_FIELDS:
        features[f"risk_{key}"] = 1 if _to_bool(risk.get(key)) else 0

    return features
