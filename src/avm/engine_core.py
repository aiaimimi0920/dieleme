from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.avm_temporal import TemporalAdjuster
from src.avm_config import AVM_CONFIG_MANAGER, get_effective_radius_km, get_effective_risk_discount_factor, get_effective_weighting


EARTH_RADIUS_KM = 6371.0088
DEFAULT_SEARCH_RADIUS_KM = 3.0
DEFAULT_RISK_DISCOUNT_FACTOR = 0.9


# 风控因子：<1 代表折价，>1 代表正向修正
RISK_FACTOR_MAP: Dict[str, float] = {
    "is_occupied": 0.88,
    "has_long_lease": 0.86,
    "clear_delivery": 0.93,
    "land_right_type": 0.95,
    "is_restricted_purchase": 0.97,
    "property_fee_owed": 0.985,
    "tax_is_company_owned": 0.94,
    "is_fractional_share": 0.83,
    "is_haunted": 0.80,
    "has_lease_before_mortgage": 1.04,
}

ATTRIBUTE_FACTOR_RULES = {
    "special_school_tag": 1.03,
    "has_keys_false": 0.98,
    "tax_burden_all_buyer": 0.98,
}


def get_active_risk_factor_overrides() -> Dict[str, float]:
    active: Dict[str, float] = {}
    try:
        config = AVM_CONFIG_MANAGER.get_config()
    except Exception:
        config = {}
    overrides = config.get("risk_factor_overrides") if isinstance(config, dict) else None
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if numeric <= 0:
                continue
            active[str(key)] = numeric
    return active


def get_effective_risk_factor_map() -> Dict[str, float]:
    effective = dict(RISK_FACTOR_MAP)
    effective.update(get_active_risk_factor_overrides())
    return effective


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def distance_weight(distance_km: float, sigma: float = 1.2) -> float:
    if distance_km < 1e-6:
        return 1.0
    return math.exp(-((distance_km**2) / (2 * sigma**2)))


def _get(record: Dict[str, Any], key: str, default: Any = None) -> Any:
    return record.get(key, default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def _subject_temporal_target_dt(subject: Dict[str, Any]) -> Tuple[Optional[datetime], str]:
    for key in ("auction_date", "subject_date", "date"):
        parsed = _parse_dt(_get(subject, key))
        if parsed:
            return parsed, f"subject_{key}"
    return None, "current_time"


def _resolve_valuation_mode(subject: Dict[str, Any]) -> str:
    value = str(_get(subject, "valuation_mode") or "").strip().lower()
    if value == "current_market":
        return "current_market"
    if value == "historical_strict":
        return "historical_strict"
    if _get(subject, "strict_temporal_cutoff") is True:
        return "historical_strict"
    return "historical_strict"


def _resolve_radius_km(subject: Dict[str, Any]) -> float:
    value = _get(subject, "radius_km")
    try:
        numeric = float(value)
        if numeric > 0:
            return numeric
    except (TypeError, ValueError):
        pass
    return get_effective_radius_km(DEFAULT_SEARCH_RADIUS_KM)


def _resolve_weighting() -> Dict[str, float]:
    weighting = get_effective_weighting()
    return {
        "distance_power": float(weighting.get("distance_power", 2.0)),
        "time_decay": float(weighting.get("time_decay", 0.85)),
        "community_boost": float(weighting.get("community_boost", 1.8)),
    }


def _resolve_risk_discount_factor() -> float:
    return float(get_effective_risk_discount_factor(DEFAULT_RISK_DISCOUNT_FACTOR))


def _apply_global_risk_discount_factor(multiplier: float, risk_discount_factor: float) -> float:
    if multiplier <= 0:
        return multiplier
    exponent = risk_discount_factor / DEFAULT_RISK_DISCOUNT_FACTOR
    if abs(exponent - 1.0) < 1e-9:
        return multiplier
    return multiplier ** exponent


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _distance_weight(distance_km: float, method: str = "hybrid", idw_power: float = 2.0, sigma_km: float = 1.2) -> float:
    d = max(distance_km, 0.03)
    idw_w = 1.0 / (d**idw_power)
    gauss_w = math.exp(-0.5 * (distance_km / max(sigma_km, 1e-3)) ** 2)

    if method == "idw":
        return idw_w
    if method == "gaussian":
        return gauss_w
    return idw_w * gauss_w


def _calc_unit_price(record: Dict[str, Any]) -> float:
    unit_price = record.get("unit_price")
    if unit_price:
        return float(unit_price)
    tp = record.get("transaction_price")
    area = record.get("area_sqm")
    if tp and area:
        return float(tp) / float(area)
    return 0.0


def _normalized_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalized_group_text(value: Any) -> str:
    text = _normalized_text(value)
    if text in {"UNK", "未知", "None", "null"}:
        return ""
    return text


def _record_business_area(record: Dict[str, Any]) -> str:
    return _normalized_group_text(
        _get(record, "business_area") or _get(record, "business_district") or _get(record, "biz_circle")
    )


def _is_low_tier_locality(record: Dict[str, Any]) -> bool:
    business_area = _record_business_area(record)
    district = _normalized_group_text(_get(record, "district"))
    return any(token in business_area for token in ("镇", "乡", "村")) or district.endswith(("县", "旗"))


def _has_weak_market_engagement(record: Dict[str, Any]) -> bool:
    bid_count = _to_float(_get(record, "bid_count"), 0.0)
    apply_count = _to_float(_get(record, "apply_count"), 0.0)
    if bid_count <= 0 and apply_count <= 0:
        return False
    return bid_count <= 1 and apply_count <= 1


def _area_similarity(subject_area: float, comparable_area: float) -> float:
    if subject_area <= 0 or comparable_area <= 0:
        return 0.5
    gap = abs(comparable_area - subject_area) / max(subject_area, 1.0)
    return 1.0 / (1.0 + gap)


def _parse_room_count(layout: str) -> Optional[int]:
    match = re.search(r"(\d+)\s*室", layout or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _layout_similarity(subject_layout: str, comparable_layout: str) -> float:
    subject_layout = _normalized_text(subject_layout)
    comparable_layout = _normalized_text(comparable_layout)
    if not subject_layout or not comparable_layout:
        return 1.0
    if subject_layout == comparable_layout:
        return 1.06
    subject_rooms = _parse_room_count(subject_layout)
    comparable_rooms = _parse_room_count(comparable_layout)
    if subject_rooms is not None and comparable_rooms is not None:
        gap = abs(subject_rooms - comparable_rooms)
        if gap == 0:
            return 1.03
        if gap == 1:
            return 0.97
        return 0.92
    return 0.98


def _asset_regime_from_record(record: Dict[str, Any]) -> str:
    housing_type = _normalized_text(_get(record, "housing_type"))
    area = _to_float(_get(record, "area_sqm"), 0.0)

    if housing_type == "车位":
        return "parking"
    if housing_type == "工业":
        if area >= 5000:
            return "industrial_huge"
        if area >= 1000:
            return "industrial_large"
        return "industrial_standard"
    if housing_type == "商业":
        if area <= 20:
            return "commercial_micro"
        if area >= 150:
            return "commercial_large"
        return "commercial_standard"
    if housing_type == "办公":
        if area >= 150:
            return "office_large"
        return "office_standard"
    if housing_type == "住宅":
        if area >= 300:
            return "residential_huge"
        if area >= 150:
            return "residential_large"
        return "residential_standard"
    if housing_type == "别墅":
        return "villa"
    if housing_type == "其他":
        if area <= 20:
            return "other_micro"
        if area >= 150:
            return "other_large"
        return "other_standard"
    return f"type::{housing_type or 'unknown'}"


def _asset_regime_similarity(subject_regime: str, comparable_regime: str) -> float:
    if not subject_regime or not comparable_regime:
        return 1.0
    if subject_regime == comparable_regime:
        return 1.12
    subject_prefix = subject_regime.split("_", 1)[0]
    comparable_prefix = comparable_regime.split("_", 1)[0]
    if subject_prefix == comparable_prefix:
        return 0.9
    return 0.78


def _spatial_filter_and_weight(
    subject: Dict[str, Any],
    normalized: Iterable[Dict[str, Any]],
    radius_km: float = DEFAULT_SEARCH_RADIUS_KM,
    weighting: Optional[Dict[str, float]] = None,
) -> List[Tuple[Dict[str, Any], float]]:
    subject_lat = _to_float(_get(subject, "latitude"), float("nan"))
    subject_lon = _to_float(_get(subject, "longitude"), float("nan"))
    if math.isnan(subject_lat) or math.isnan(subject_lon):
        return []

    subject_community = _normalized_group_text(_get(subject, "community_name"))
    subject_business = _record_business_area(subject)
    subject_district = _normalized_group_text(_get(subject, "district"))
    subject_housing_type = _normalized_text(_get(subject, "housing_type"))
    subject_regime = _asset_regime_from_record(subject)
    subject_layout = _normalized_text(_get(subject, "layout"))
    subject_parking = _get(subject, "includes_parking")
    subject_area = _to_float(_get(subject, "area_sqm"), 0.0)
    weighting = dict(weighting or {})
    distance_power = _to_float(weighting.get("distance_power"), 2.0)
    community_boost = _to_float(weighting.get("community_boost"), 1.8)

    selected: List[Tuple[Dict[str, Any], float]] = []
    for rec in normalized:
        if not rec.get("_has_geo"):
            continue
        dist = _haversine_km(subject_lat, subject_lon, rec["_lat"], rec["_lon"])
        if dist > radius_km:
            continue

        w = _distance_weight(dist, method="hybrid", idw_power=distance_power)
        if subject_community and rec["_community_name"] == subject_community:
            w *= community_boost
        if subject_business and rec["_business_area_name"] == subject_business:
            w *= 1.35
        if subject_district and rec["_district_name"] and rec["_district_name"] != subject_district:
            w *= 0.72
        if subject_housing_type and rec["_housing_type_name"]:
            if rec["_housing_type_name"] == subject_housing_type:
                w *= 1.08
            else:
                w *= 0.92
        w *= _asset_regime_similarity(subject_regime, rec.get("_asset_regime", ""))
        w *= _layout_similarity(subject_layout, rec["_layout_text"])
        if subject_parking is not None and rec["_includes_parking"] is not None:
            if rec["_includes_parking"] == subject_parking:
                w *= 1.04
            else:
                w *= 0.9
        w *= _area_similarity(subject_area, rec["_area"])

        selected.append((rec, w))

    selected.sort(key=lambda item: item[1], reverse=True)
    return selected



__all__ = [name for name in globals() if not name.startswith("__")]
