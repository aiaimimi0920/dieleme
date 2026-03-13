from __future__ import annotations

from typing import Any


_FIELD_CANDIDATES = {
    "item_id": ["id", "item_id", "itemId", "拍卖ID", "标的ID"],
    "source_url": ["url", "source_url", "sourceUrl", "链接", "详情链接"],
    "transaction_price": [
        "成交价格",
        "成交价",
        "transaction_price",
        "deal_price",
        "final_price",
    ],
    "starting_price": ["起拍价格", "起拍价", "starting_price", "start_price"],
    "area_sqm": ["建筑面积", "面积", "建筑面积(㎡)", "area_sqm", "area"],
    "auction_date": ["交易时间", "成交时间", "auction_date", "auction_time", "date"],
    "community_name": ["所属小区", "小区", "community_name", "community"],
}


_LOCATION_KEYS = {
    "province": ["省", "所在省", "province"],
    "city": ["市", "所在市", "city"],
    "district": ["区", "县", "所在区", "district"],
}


def _pick_first(raw: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def map_raw_to_canonical(raw: dict) -> dict:
    """将原始字典映射为统一字段。

    优先映射字段：
    id/url/成交价格/起拍价格/建筑面积/交易时间/所属小区/省市区。
    """
    canonical: dict[str, Any] = {
        target: _pick_first(raw, source_keys)
        for target, source_keys in _FIELD_CANDIDATES.items()
    }

    if not canonical["community_name"]:
        province = _pick_first(raw, _LOCATION_KEYS["province"])
        city = _pick_first(raw, _LOCATION_KEYS["city"])
        district = _pick_first(raw, _LOCATION_KEYS["district"])
        location = "".join(str(part) for part in (province, city, district) if part)
        canonical["community_name"] = location or None

    return canonical
