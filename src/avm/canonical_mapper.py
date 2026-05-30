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
    "auction_round": ["auction_round", "拍卖轮次", "round"],
    "housing_type": ["housing_type", "房屋用途", "housingType"],
    "bid_count": ["bid_count", "bidCount", "出价次数", "出价人数"],
    "apply_count": ["apply_count", "applyCount", "报名人数", "竞拍人数"],
}

HOUSING_TYPE_EXACT_MAP = {
    "住宅": "住宅",
    "成套住宅": "住宅",
    "居住用房": "住宅",
    "普通住宅": "住宅",
    "公寓": "住宅",
    "别墅": "别墅",
    "联排别墅": "别墅",
    "独栋别墅": "别墅",
    "商业": "商业",
    "商业服务": "商业",
    "商业用房": "商业",
    "商铺": "商业",
    "门面": "商业",
    "商服": "商业",
    "办公": "办公",
    "办公用房": "办公",
    "写字楼": "办公",
    "工业": "工业",
    "工业用房": "工业",
    "工业房地产": "工业",
    "厂房": "工业",
    "仓库": "工业",
    "车位": "车位",
    "停车位": "车位",
    "车库": "车位",
    "库位": "车位",
}

HOUSING_TYPE_HINTS = [
    ("车位", ("车位", "停车位", "车库", "库位")),
    ("办公", ("办公", "写字楼", "办公室")),
    ("商业", ("商铺", "门面", "商场", "商城", "商业", "商服", "营业房", "店面", "底商")),
    ("工业", ("厂房", "工业", "仓库", "厂区", "车间")),
    ("别墅", ("别墅", "联排", "独栋", "双拼", "叠墅")),
    ("住宅", ("住宅", "公寓", "小区", "房屋", "房产", "房地产", "单元", "号楼", "室")),
]

RISK_FEATURE_KEYS = {
    "community_name",
    "build_year",
    "total_floors",
    "floor_level",
    "has_elevator",
    "orientation",
    "land_right_type",
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "tax_burden",
    "is_haunted",
    "housing_type",
    "has_keys",
    "property_fee_owed",
    "special_school_tag",
    "evaluation_price",
    "layout",
    "is_restricted_purchase",
    "includes_parking",
    "is_fractional_share",
    "tax_is_company_owned",
    "has_lease_before_mortgage",
    "extraction_confidence",
    "evidence_span",
    "evidence_source",
    "extraction_version",
}

INT_KEYS = {"auction_round", "bid_count", "apply_count", "build_year", "total_floors"}


def _extract_risk_payload(raw_item: Dict[str, Any]) -> Dict[str, Any]:
    payload = raw_item.get("avm_risk_features")
    return payload if isinstance(payload, dict) else {}


def _first_present(raw_item: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in raw_item and raw_item[key] not in (None, ""):
            return raw_item[key]
    return None


def _coerce_int(value: Any) -> Optional[int]:
    number = safe_float(value)
    if number is None:
        return None
    try:
        return int(number)
    except (TypeError, ValueError):
        return None


def _normalize_status(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "done" if value else "pending"
    text = str(value).strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"true", "成交", "done", "finished", "ended", "success"}:
        return "done"
    if lowered in {"false", "pending", "todo"}:
        return "pending"
    return text


def _normalize_housing_type(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    mapped = HOUSING_TYPE_EXACT_MAP.get(text)
    if mapped:
        return mapped
    for canonical, hints in HOUSING_TYPE_HINTS:
        if any(token in text for token in hints):
            return canonical
    return None


def _infer_housing_type(raw_item: Dict[str, Any], risk_payload: Dict[str, Any]) -> Optional[str]:
    text_parts = [
        raw_item.get("房屋用途"),
        raw_item.get("title"),
        raw_item.get("标题"),
        raw_item.get("名称"),
        raw_item.get("标的物名称"),
        raw_item.get("地点"),
        risk_payload.get("housing_type"),
    ]
    merged = " ".join(str(part).strip() for part in text_parts if part not in (None, ""))
    if not merged:
        return None
    return _normalize_housing_type(merged)


def _normalize_evaluation_price(value: Any, extraction_version: Any = None) -> Optional[float]:
    if value in (None, ""):
        return None

    version = str(extraction_version or "").strip().lower()
    if version == "avm_risk_v1":
        if isinstance(value, str) and any(unit in value for unit in ("元", "万", "亿", "¥", "￥")):
            return parse_money_to_yuan(value)
        numeric = safe_float(value)
        if numeric is None or numeric <= 0:
            return None
        return round(numeric * 10000.0, 2)

    return parse_money_to_yuan(value)


def _normalize_market_evaluation_price(
    value: Any,
    reference_price: Any = None,
) -> Optional[float]:
    if value in (None, ""):
        return None

    if isinstance(value, str) and any(unit in value for unit in ("元", "万", "亿", "¥", "￥")):
        return parse_money_to_yuan(value)

    numeric = safe_float(value)
    if numeric is None or numeric <= 0:
        return None

    reference = safe_float(reference_price)
    if reference is not None and reference > 0:
        for divisor in (10000.0, 1000.0, 100.0):
            adjusted = numeric / divisor
            ratio = adjusted / reference
            if 0.5 <= ratio <= 5.0:
                return round(adjusted, 2)

    if numeric >= 1_000_000_000:
        return round(numeric / 10000.0, 2)
    return round(numeric, 2)


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
    risk_payload = _extract_risk_payload(raw_item)

    housing_type = _first_present(raw_item, FIELD_CANDIDATES["housing_type"])
    if housing_type in (None, ""):
        housing_type = risk_payload.get("housing_type")
    housing_type = _normalize_housing_type(housing_type) or _infer_housing_type(raw_item, risk_payload) or "其他"

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
        community_name=(
            _first_present(raw_item, FIELD_CANDIDATES["community_name"])
            or risk_payload.get("community_name")
        ),
        business_area=_first_present(raw_item, FIELD_CANDIDATES["business_area"]),
        latitude=safe_float(_first_present(raw_item, FIELD_CANDIDATES["latitude"])),
        longitude=safe_float(_first_present(raw_item, FIELD_CANDIDATES["longitude"])),
        status=_normalize_status(_first_present(raw_item, FIELD_CANDIDATES["status"])),
        auction_round=_coerce_int(_first_present(raw_item, FIELD_CANDIDATES["auction_round"])),
        housing_type=housing_type,
        bid_count=_coerce_int(_first_present(raw_item, FIELD_CANDIDATES["bid_count"])),
        apply_count=_coerce_int(_first_present(raw_item, FIELD_CANDIDATES["apply_count"])),
    )

    output = rec.to_dict()
    if output["actual_paid_price"] is None:
        output["actual_paid_price"] = output["transaction_price"]

    for key in RISK_FEATURE_KEYS:
        value = raw_item.get(key)
        if key == "evaluation_price":
            if value not in (None, ""):
                value = _normalize_evaluation_price(value, raw_item.get("extraction_version"))
            elif risk_payload.get(key) not in (None, ""):
                value = _normalize_evaluation_price(
                    risk_payload.get(key),
                    risk_payload.get("extraction_version"),
                )
            elif raw_item.get("市场评估价") not in (None, ""):
                value = _normalize_market_evaluation_price(
                    raw_item.get("市场评估价"),
                    reference_price=(
                        _first_present(raw_item, FIELD_CANDIDATES["transaction_price"])
                        or _first_present(raw_item, FIELD_CANDIDATES["starting_price"])
                    ),
                )
        elif key == "housing_type":
            value = _normalize_housing_type(value)
            if value is None:
                value = _normalize_housing_type(risk_payload.get(key))
            if value is None:
                value = _infer_housing_type(raw_item, risk_payload)
        elif value in (None, ""):
            value = risk_payload.get(key)
        if value in (None, ""):
            continue
        if key in INT_KEYS:
            coerced = _coerce_int(value)
            if coerced is not None:
                output[key] = coerced
            continue
        output[key] = value

    return output
