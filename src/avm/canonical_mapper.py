from typing import Any, Dict, Optional

from .normalize import parse_money_to_yuan, parse_area_sqm, safe_float
from .schema import CanonicalRecord


def _pick(raw: Dict[str, Any], *keys: str) -> Optional[Any]:
    for k in keys:
        if k in raw and raw[k] not in (None, ""):
            return raw[k]
    return None


def map_raw_to_canonical(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map current scraper fields to AVM canonical schema."""
    raw_id = _pick(raw, "item_id", "id", "唯一id")
    if raw_id is None:
        raise ValueError("missing id/item_id/唯一id")

    transaction_price = parse_money_to_yuan(_pick(raw, "transaction_price", "成交价格", "deal_price", "currentPrice"))
    starting_price = parse_money_to_yuan(_pick(raw, "starting_price", "起拍价格", "initialPrice"))
    area_sqm = parse_area_sqm(_pick(raw, "area_sqm", "建筑面积", "建设面积", "building_area"))

    rec = CanonicalRecord(
        item_id=str(raw_id),
        source_url=_pick(raw, "source_url", "url", "原始网站"),
        transaction_price=transaction_price,
        starting_price=starting_price,
        actual_paid_price=parse_money_to_yuan(_pick(raw, "actual_paid_price", "实际支付总价")),
        area_sqm=area_sqm,
        auction_date=_pick(raw, "auction_date", "交易时间"),
        province=_pick(raw, "province", "省份"),
        city=_pick(raw, "city", "城市"),
        district=_pick(raw, "district", "区"),
        community_name=_pick(raw, "community_name", "所属小区"),
        business_area=_pick(raw, "business_area", "最靠近商圈"),
        latitude=safe_float(_pick(raw, "latitude", "lat", "纬度")),
        longitude=safe_float(_pick(raw, "longitude", "lng", "经度")),
        status=str(_pick(raw, "status", "状态", "outcome", "是否成交") or ""),
    )
    return rec.to_dict()
