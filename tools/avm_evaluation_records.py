"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_evaluation_context import *


def _load_raw_archive_records(data_root: Path) -> List[dict[str, Any]]:
    rows = load_analysis_ready_rows(data_root, prefer_db=True)
    if rows:
        return rows
    return load_raw_record_rows(data_root, prefer_db=True)


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _actual_total_price(feature: dict[str, Any]) -> float | None:
    actual_paid = feature.get("actual_paid_price")
    if isinstance(actual_paid, (int, float)) and actual_paid > 0:
        return float(actual_paid)
    transaction_price = feature.get("transaction_price")
    if isinstance(transaction_price, (int, float)) and transaction_price > 0:
        return float(transaction_price)
    return None


def _actual_unit_price(feature: dict[str, Any]) -> float | None:
    total_price = _actual_total_price(feature)
    area = feature.get("area_sqm")
    if not isinstance(total_price, (int, float)):
        return None
    if not isinstance(area, (int, float)) or area <= 0:
        return None
    return float(total_price) / float(area)


def _feature_month(feature: dict[str, Any]) -> str | None:
    raw = feature.get("auction_date")
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(str(raw), fmt)
            return f"{dt.year:04d}-{dt.month:02d}"
        except ValueError:
            continue
    return None



__all__ = (
    "_load_raw_archive_records",
    "_safe_div",
    "_actual_total_price",
    "_actual_unit_price",
    "_feature_month",
)
