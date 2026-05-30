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
        "auction_date": canonical_record.get("auction_date"),
        "province": canonical_record.get("province") or "UNK",
        "city": canonical_record.get("city") or "UNK",
        "district": canonical_record.get("district") or "UNK",
        "community_name": canonical_record.get("community_name") or "UNK",
        "business_area": canonical_record.get("business_area") or "UNK",
        "area_sqm": area_sqm,
        "starting_price": canonical_record.get("starting_price"),
        "transaction_price": transaction_price,
        "actual_paid_price": canonical_record.get("actual_paid_price") or transaction_price,
        "unit_price": unit_price,
        "latitude": canonical_record.get("latitude"),
        "longitude": canonical_record.get("longitude"),
        "status": canonical_record.get("status"),
        "auction_round": canonical_record.get("auction_round"),
        "housing_type": canonical_record.get("housing_type"),
        "bid_count": canonical_record.get("bid_count"),
        "apply_count": canonical_record.get("apply_count"),
        "build_year": canonical_record.get("build_year"),
        "total_floors": canonical_record.get("total_floors"),
        "floor_level": canonical_record.get("floor_level"),
        "has_elevator": canonical_record.get("has_elevator"),
        "orientation": canonical_record.get("orientation"),
        "land_right_type": canonical_record.get("land_right_type"),
        "is_occupied": canonical_record.get("is_occupied"),
        "has_long_lease": canonical_record.get("has_long_lease"),
        "clear_delivery": canonical_record.get("clear_delivery"),
        "tax_burden": canonical_record.get("tax_burden"),
        "is_haunted": canonical_record.get("is_haunted"),
        "has_keys": canonical_record.get("has_keys"),
        "property_fee_owed": canonical_record.get("property_fee_owed"),
        "special_school_tag": canonical_record.get("special_school_tag"),
        "evaluation_price": canonical_record.get("evaluation_price"),
        "layout": canonical_record.get("layout"),
        "is_restricted_purchase": canonical_record.get("is_restricted_purchase"),
        "includes_parking": canonical_record.get("includes_parking"),
        "is_fractional_share": canonical_record.get("is_fractional_share"),
        "tax_is_company_owned": canonical_record.get("tax_is_company_owned"),
        "has_lease_before_mortgage": canonical_record.get("has_lease_before_mortgage"),
        "extraction_confidence": canonical_record.get("extraction_confidence"),
        "evidence_source": canonical_record.get("evidence_source"),
        "extraction_version": canonical_record.get("extraction_version"),
    }
