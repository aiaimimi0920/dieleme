"""Raw -> canonical field mapper based on AVM schema contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from .normalize import parse_area_sqm, parse_money_to_yuan, safe_float
from .schema import CanonicalRecord

CN_TIMEZONE = timezone(timedelta(hours=8))

FIELD_CANDIDATES = {
    "item_id": ["item_id", "id", "唯一id", "source_item_id"],
    "source_item_id": ["source_item_id", "id", "item_id", "唯一id"],
    "source_url": ["source_url", "url", "原始网站"],
    "transaction_price": ["transaction_price", "成交价格", "deal_price", "currentPrice"],
    "starting_price": ["starting_price", "起拍价格", "initialPrice"],
    "actual_paid_price": ["actual_paid_price", "实际支付总价"],
    "area_sqm": ["area_sqm", "建筑面积", "建设面积", "building_area"],
    "auction_date": ["auction_date", "交易时间"],
    "province": ["province", "省份"],
    "city": ["city", "城市"],
    "district": ["district", "区", "行政区"],
    "community_name": ["community_name", "所属小区", "小区", "小区名称"],
    "business_area": ["business_area", "最靠近商圈", "business_area_name"],
    "latitude": ["latitude", "lat", "纬度"],
    "longitude": ["longitude", "lng", "经度"],
    "status": ["status", "状态", "outcome", "是否成交"],
}


def _first_present(raw_item: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in raw_item and raw_item[key] not in (None, ""):
            return raw_item[key]
    return None


def _normalize_datetime(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    try:
        ts = float(text)
        if ts > 10**12:
            ts /= 1000
        if 0 < ts < 10**11:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(CN_TIMEZONE)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass

    text = (
        text.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("T", " ")
        .replace("Z", "")
    )

    known_formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    ]
    for fmt in known_formats:
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in {"%Y-%m-%d", "%Y/%m/%d"}:
                dt = dt.replace(hour=0, minute=0, second=0)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    return None


def map_raw_to_canonical(raw_item: Dict[str, Any]) -> Dict[str, Any]:
    """Map one raw item into AVM canonical schema fields."""
    item_id = _first_present(raw_item, FIELD_CANDIDATES["item_id"])
    if item_id is None:
        raise ValueError("missing id/item_id/唯一id")

    source_item_id = _first_present(raw_item, FIELD_CANDIDATES["source_item_id"])
    source_url = _first_present(raw_item, FIELD_CANDIDATES["source_url"])

    rec = CanonicalRecord(
        item_id=str(item_id),
        source_item_id=str(source_item_id) if source_item_id is not None else str(item_id),
        source_url=str(source_url).strip() if source_url is not None else None,
        transaction_price=parse_money_to_yuan(_first_present(raw_item, FIELD_CANDIDATES["transaction_price"])),
        starting_price=parse_money_to_yuan(_first_present(raw_item, FIELD_CANDIDATES["starting_price"])),
        actual_paid_price=parse_money_to_yuan(_first_present(raw_item, FIELD_CANDIDATES["actual_paid_price"])),
        area_sqm=parse_area_sqm(_first_present(raw_item, FIELD_CANDIDATES["area_sqm"])),
        auction_date=_normalize_datetime(_first_present(raw_item, FIELD_CANDIDATES["auction_date"])),
        province=_first_present(raw_item, FIELD_CANDIDATES["province"]),
        city=_first_present(raw_item, FIELD_CANDIDATES["city"]),
        district=_first_present(raw_item, FIELD_CANDIDATES["district"]),
        community_name=_first_present(raw_item, FIELD_CANDIDATES["community_name"]),
        business_area=_first_present(raw_item, FIELD_CANDIDATES["business_area"]),
        latitude=safe_float(_first_present(raw_item, FIELD_CANDIDATES["latitude"])),
        longitude=safe_float(_first_present(raw_item, FIELD_CANDIDATES["longitude"])),
        status=str(_first_present(raw_item, FIELD_CANDIDATES["status"]) or ""),
    )
    return rec.to_dict()
