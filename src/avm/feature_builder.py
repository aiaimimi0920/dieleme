from datetime import datetime
from typing import Any, Dict, Optional


def _month_index(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.year * 12 + dt.month
        except ValueError:
            continue
    return None


def build_features(canonical_record: Dict[str, Any]) -> Dict[str, Any]:
    transaction_price = canonical_record.get("transaction_price")
    area_sqm = canonical_record.get("area_sqm")
    unit_price = None
    if transaction_price and area_sqm and area_sqm > 0:
        unit_price = round(transaction_price / area_sqm, 2)

    return {
        "item_id": canonical_record.get("item_id"),
        "auction_month_index": _month_index(canonical_record.get("auction_date")),
        "province": canonical_record.get("province") or "UNK",
        "city": canonical_record.get("city") or "UNK",
        "district": canonical_record.get("district") or "UNK",
        "community_name": canonical_record.get("community_name") or "UNK",
        "business_area": canonical_record.get("business_area") or "UNK",
        "area_sqm": area_sqm,
        "starting_price": canonical_record.get("starting_price"),
        "transaction_price": transaction_price,
        "unit_price": unit_price,
        "latitude": canonical_record.get("latitude"),
        "longitude": canonical_record.get("longitude"),
    }
