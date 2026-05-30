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


def _normalize_record(comp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    price = _to_float(_get(comp, "actual_paid_price") or _get(comp, "transaction_price"), 0.0)
    area = max(_to_float(_get(comp, "area_sqm"), 0.0), 0.0)
    lat = _to_float(_get(comp, "latitude"), float("nan"))
    lon = _to_float(_get(comp, "longitude"), float("nan"))
    if price <= 0 or area <= 0:
        return None

    rec = dict(comp)
    rec["_unit_price"] = price / area
    risk_factor, _ = _risk_adjustment(rec)
    rec["_risk_factor"] = max(risk_factor, 1e-6)
    rec["_neutral_unit_price"] = rec["_unit_price"] / rec["_risk_factor"]
    rec["_area"] = area
    rec["_lat"] = lat
    rec["_lon"] = lon
    rec["_has_geo"] = not math.isnan(lat) and not math.isnan(lon)
    rec["_community_name"] = _normalized_group_text(_get(rec, "community_name"))
    rec["_business_area_name"] = _record_business_area(rec)
    rec["_district_name"] = _normalized_group_text(_get(rec, "district"))
    rec["_city_name"] = _normalized_group_text(_get(rec, "city"))
    rec["_housing_type_name"] = _normalized_text(_get(rec, "housing_type"))
    rec["_asset_regime"] = _asset_regime_from_record(rec)
    rec["_layout_text"] = _normalized_text(_get(rec, "layout"))
    rec["_includes_parking"] = _get(rec, "includes_parking")
    return rec


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


def _build_temporal_factor(
    subject: Dict[str, Any],
    normalized: Iterable[Dict[str, Any]],
    weighting: Optional[Dict[str, float]] = None,
) -> Tuple[float, str, int, datetime, str]:
    valuation_mode = _resolve_valuation_mode(subject)
    if valuation_mode == "current_market":
        target_dt = datetime.now()
        reference_mode = "current_time"
    else:
        target_dt, reference_mode = _subject_temporal_target_dt(subject)
        target_dt = target_dt or datetime.now()

    weighting = dict(weighting or {})
    adjuster = TemporalAdjuster(
        normalized,
        current_date=target_dt.date(),
        time_decay=_to_float(weighting.get("time_decay"), 1.0),
    )
    factor, sample_count = adjuster.trend_factor(
        region={
            "city": _normalized_group_text(_get(subject, "city")),
            "district": _normalized_group_text(_get(subject, "district")),
            "business_area": _record_business_area(subject),
        },
        target_date=target_dt.date(),
        reference_date=None,
        clamp=(0.75, 1.25),
    )
    if sample_count < 2:
        return 1.0, "时间趋势样本不足，使用空间层基线", sample_count, target_dt, reference_mode
    if factor <= 0:
        return 1.0, "时间趋势异常，回退空间层基线", sample_count, target_dt, reference_mode
    return factor, f"时间趋势校准系数={factor:.3f}", sample_count, target_dt, reference_mode


def _exclude_future_dated_comparables(
    subject: Dict[str, Any],
    normalized: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    if _resolve_valuation_mode(subject) != "historical_strict":
        return list(normalized), 0

    target_dt, _ = _subject_temporal_target_dt(subject)
    if target_dt is None:
        target_dt = datetime.now()

    filtered: List[Dict[str, Any]] = []
    excluded_count = 0
    for rec in normalized:
        comparable_dt = _parse_dt(_get(rec, "auction_date"))
        if comparable_dt is not None and comparable_dt > target_dt:
            excluded_count += 1
            continue
        filtered.append(rec)
    return filtered, excluded_count


def _fallback_filter_and_weight(
    subject: Dict[str, Any],
    normalized: Sequence[Dict[str, Any]],
    weighting: Optional[Dict[str, float]] = None,
) -> Tuple[List[Tuple[Dict[str, Any], float]], str]:
    subject_community = _normalized_group_text(_get(subject, "community_name"))
    subject_business = _record_business_area(subject)
    subject_district = _normalized_group_text(_get(subject, "district"))
    subject_city = _normalized_group_text(_get(subject, "city"))
    subject_housing_type = _normalized_text(_get(subject, "housing_type"))
    subject_regime = _asset_regime_from_record(subject)
    subject_layout = _normalized_text(_get(subject, "layout"))
    subject_parking = _get(subject, "includes_parking")
    subject_area = _to_float(_get(subject, "area_sqm"), 0.0)
    weighting = dict(weighting or {})
    community_boost = _to_float(weighting.get("community_boost"), 1.8)
    strict_same_type_regimes = {
        "commercial_micro",
        "commercial_large",
        "parking",
        "other_large",
        "other_standard",
    }

    def maybe_match_housing_type(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not subject_housing_type:
            return records
        matched = [rec for rec in records if rec["_housing_type_name"] == subject_housing_type]
        return matched if len(matched) >= 3 else records

    def maybe_match_asset_regime(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not subject_regime:
            return records
        matched = [rec for rec in records if rec.get("_asset_regime") == subject_regime]
        return matched if len(matched) >= 2 else records

    def enforce_strict_same_type_requirement(strategy: str, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if strategy == "spatial" or subject_regime not in strict_same_type_regimes or not subject_housing_type:
            return records
        same_type = [rec for rec in records if rec["_housing_type_name"] == subject_housing_type]
        return same_type if same_type else []

    tiers: List[Tuple[str, List[Dict[str, Any]]]] = [
        (
            "community_fallback",
            [
                rec
                for rec in normalized
                if subject_community
                and rec["_community_name"] == subject_community
                and (not subject_city or rec["_city_name"] == subject_city)
                and (not subject_district or rec["_district_name"] == subject_district)
            ],
        ),
        ("business_area_fallback", [rec for rec in normalized if subject_business and rec["_business_area_name"] == subject_business]),
        ("district_fallback", [rec for rec in normalized if subject_district and rec["_district_name"] == subject_district]),
        ("city_fallback", [rec for rec in normalized if subject_city and rec["_city_name"] == subject_city]),
        ("global_fallback", list(normalized)),
    ]

    selected_strategy = "global_fallback"
    selected_records: List[Dict[str, Any]] = []
    for strategy, records in tiers:
        records = maybe_match_asset_regime(records)
        records = maybe_match_housing_type(records)
        records = enforce_strict_same_type_requirement(strategy, records)
        if len(records) >= 3:
            selected_strategy = strategy
            selected_records = records
            break
        if not selected_records and records:
            selected_strategy = strategy
            selected_records = records

    weighted: List[Tuple[Dict[str, Any], float]] = []
    for rec in selected_records:
        weight = _area_similarity(subject_area, rec["_area"])
        if subject_community and rec["_community_name"] == subject_community:
            weight *= community_boost
        elif subject_business and rec["_business_area_name"] == subject_business:
            weight *= 1.35
        elif subject_district and rec["_district_name"] == subject_district:
            weight *= 1.15
        elif subject_city and rec["_city_name"] == subject_city:
            weight *= 1.0
        else:
            weight *= 0.8

        if subject_housing_type and rec["_housing_type_name"]:
            if rec["_housing_type_name"] == subject_housing_type:
                weight *= 1.08
            else:
                weight *= 0.9
        weight *= _asset_regime_similarity(subject_regime, rec.get("_asset_regime", ""))
        weight *= _layout_similarity(subject_layout, rec["_layout_text"])
        if subject_parking is not None and rec["_includes_parking"] is not None:
            if rec["_includes_parking"] == subject_parking:
                weight *= 1.04
            else:
                weight *= 0.9

        weighted.append((rec, weight))

    weighted.sort(key=lambda item: item[1], reverse=True)
    return weighted[:80], selected_strategy


def _risk_adjustment(subject: Dict[str, Any]) -> Tuple[float, List[str]]:
    factor = 1.0
    reasons: List[str] = []
    risk_factor_map = get_effective_risk_factor_map()
    risk_discount_factor = _resolve_risk_discount_factor()

    def apply(multiplier: float, label: str) -> None:
        nonlocal factor
        factor *= _apply_global_risk_discount_factor(multiplier, risk_discount_factor)
        reasons.append(label)

    if _get(subject, "is_occupied") is True:
        apply(risk_factor_map["is_occupied"], "占用未腾退折价")
    if _get(subject, "has_long_lease") is True:
        apply(risk_factor_map["has_long_lease"], "长期租约折价")
    if _get(subject, "clear_delivery") is False:
        apply(risk_factor_map["clear_delivery"], "法院不负责清场折价")
    if _get(subject, "land_right_type") == "划拨":
        apply(risk_factor_map["land_right_type"], "划拨土地折价")
    if _get(subject, "is_restricted_purchase") is True:
        apply(risk_factor_map["is_restricted_purchase"], "限购约束导致流动性折价")
    if _get(subject, "tax_is_company_owned") is True:
        apply(risk_factor_map["tax_is_company_owned"], "企业产权税费折价")
    if _get(subject, "property_fee_owed") is True:
        apply(risk_factor_map["property_fee_owed"], "欠费成本折价")
    if _get(subject, "is_fractional_share") is True:
        apply(risk_factor_map["is_fractional_share"], "部分产权折价")
    if _get(subject, "is_haunted") is True:
        apply(risk_factor_map["is_haunted"], "重大负面事件折价")
    if _get(subject, "has_lease_before_mortgage") is True:
        apply(risk_factor_map["has_lease_before_mortgage"], "先抵后租可套利正向修正")

    return factor, reasons


def _subject_attribute_adjustment(subject: Dict[str, Any]) -> Tuple[float, List[str]]:
    factor = 1.0
    reasons: List[str] = []

    def apply(multiplier: float, label: str) -> None:
        nonlocal factor
        factor *= multiplier
        reasons.append(label)

    build_year = _to_float(_get(subject, "build_year"), 0.0)
    total_floors = _to_float(_get(subject, "total_floors"), 0.0)
    floor_level = _normalized_text(_get(subject, "floor_level"))
    orientation = _normalized_text(_get(subject, "orientation"))
    auction_round = int(_to_float(_get(subject, "auction_round"), 1.0) or 1)
    has_elevator = _get(subject, "has_elevator")
    special_school_tag = _get(subject, "special_school_tag")
    has_keys = _get(subject, "has_keys")
    tax_burden = _normalized_text(_get(subject, "tax_burden"))

    if build_year and build_year < 2000:
        apply(0.985, "老房龄折价")
    if has_elevator is False and total_floors >= 7:
        apply(0.95, "高层无电梯折价")
    elif has_elevator is False:
        apply(0.98, "无电梯轻微折价")

    if floor_level == "顶层":
        apply(0.985, "顶层折价")
    elif floor_level == "底层":
        apply(0.98, "底层折价")
    elif floor_level == "高区":
        apply(1.01, "高区轻微溢价")

    if orientation in {"南", "南北"}:
        apply(1.01, "朝向优势溢价")
    elif orientation in {"北", "西"}:
        apply(0.99, "朝向劣势折价")

    if special_school_tag is True:
        apply(ATTRIBUTE_FACTOR_RULES["special_school_tag"], "学区标签溢价")
    if has_keys is False:
        apply(ATTRIBUTE_FACTOR_RULES["has_keys_false"], "无钥匙折价")
    if tax_burden == "买受人承担全部":
        apply(ATTRIBUTE_FACTOR_RULES["tax_burden_all_buyer"], "税费全由买受人承担折价")

    if auction_round == 2:
        apply(0.97, "二拍市场折价")
    elif auction_round >= 3:
        apply(0.93, "变卖/多轮拍卖折价")

    return factor, reasons


def _coefficient_of_variation(samples: Sequence[Tuple[Dict[str, Any], float]]) -> float:
    if not samples:
        return 1.0
    units = [rec["_neutral_unit_price"] for rec, _ in samples if rec.get("_neutral_unit_price")]
    if len(units) <= 1:
        return 0.0
    mean = sum(units) / len(units)
    if mean <= 0:
        return 1.0
    variance = sum((unit - mean) ** 2 for unit in units) / len(units)
    return math.sqrt(variance) / mean


def _weighted_quantile_numeric(
    samples: Sequence[Tuple[Dict[str, Any], float]],
    q: float,
    value_getter,
) -> float:
    pairs = sorted(
        (
            (float(value_getter(rec)), float(weight))
            for rec, weight in samples
            if value_getter(rec) is not None and float(value_getter(rec)) > 0 and weight > 0
        ),
        key=lambda item: item[0],
    )
    if not pairs:
        return 0.0
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        idx = max(0, min(len(pairs) - 1, int(round((len(pairs) - 1) * q))))
        return pairs[idx][0]
    cutoff = max(0.0, min(1.0, q)) * total_weight
    cumulative = 0.0
    for unit_price, weight in pairs:
        cumulative += weight
        if cumulative >= cutoff:
            return unit_price
    return pairs[-1][0]


def _weighted_median_unit_price(samples: Sequence[Tuple[Dict[str, Any], float]]) -> float:
    return _weighted_quantile_numeric(samples, 0.5, lambda rec: rec.get("_neutral_unit_price"))


def _weighted_quantile_unit_price(samples: Sequence[Tuple[Dict[str, Any], float]], q: float) -> float:
    return _weighted_quantile_numeric(samples, q, lambda rec: rec.get("_neutral_unit_price"))


def _weighted_quantile_area(samples: Sequence[Tuple[Dict[str, Any], float]], q: float) -> float:
    return _weighted_quantile_numeric(samples, q, lambda rec: rec.get("_area"))


def _robust_unit_price(
    weighted_samples: Sequence[Tuple[Dict[str, Any], float]],
    weighted_mean: float,
    strategy: str,
    dispersion_cv: float,
) -> Tuple[float, float, float]:
    weighted_median = _weighted_median_unit_price(weighted_samples)
    if weighted_median <= 0 or weighted_mean <= 0:
        return weighted_mean, weighted_median, 0.0

    blend = {
        "spatial": 0.0,
        "community_fallback": 0.12,
        "business_area_fallback": 0.2,
        "district_fallback": 0.28,
        "city_fallback": 0.38,
        "global_fallback": 0.48,
    }.get(strategy, 0.3)

    if dispersion_cv >= 1.0:
        blend += 0.2
    elif dispersion_cv >= 0.7:
        blend += 0.12
    elif dispersion_cv >= 0.45:
        blend += 0.06

    blend = max(0.0, min(blend, 0.7))
    robust_price = weighted_mean * (1.0 - blend) + weighted_median * blend
    return robust_price, weighted_median, blend


def _trim_outlier_samples(
    weighted_samples: Sequence[Tuple[Dict[str, Any], float]],
    strategy: str,
    subject_housing_type: str,
) -> Tuple[List[Tuple[Dict[str, Any], float]], int]:
    if len(weighted_samples) < 6:
        return list(weighted_samples), 0

    median = _weighted_median_unit_price(weighted_samples)
    if median <= 0:
        return list(weighted_samples), 0

    lower_ratio, upper_ratio = {
        "spatial": (0.28, 3.2),
        "community_fallback": (0.32, 2.8),
        "business_area_fallback": (0.38, 2.4),
        "district_fallback": (0.42, 2.1),
        "city_fallback": (0.48, 1.9),
        "global_fallback": (0.55, 1.75),
    }.get(strategy, (0.4, 2.2))

    if subject_housing_type in {"其他", ""}:
        upper_ratio *= 0.92
    if subject_housing_type in {"商业", "办公"}:
        lower_ratio *= 1.05

    trimmed = [
        (rec, weight)
        for rec, weight in weighted_samples
        if median * lower_ratio <= float(rec.get("_neutral_unit_price") or 0.0) <= median * upper_ratio
    ]

    min_kept = max(3, len(weighted_samples) // 3)
    if len(trimmed) < min_kept:
        return list(weighted_samples), 0
    return trimmed, len(weighted_samples) - len(trimmed)


def _apply_uncertainty_conservative_blend(
    subject: Dict[str, Any],
    strategy: str,
    weighted_samples: Sequence[Tuple[Dict[str, Any], float]],
    predicted_unit_price: float,
    temporal_factor: float,
    subject_risk_factor: float,
    subject_attr_factor: float,
    dispersion_cv: float,
) -> Tuple[float, str, float, float, float]:
    subject_housing_type = _normalized_text(_get(subject, "housing_type"))
    subject_area = _to_float(_get(subject, "area_sqm"), 0.0)
    community_missing = not _normalized_group_text(_get(subject, "community_name"))
    business_missing = not _record_business_area(subject)
    low_tier_locality = _is_low_tier_locality(subject)
    weak_market_engagement = _has_weak_market_engagement(subject)
    small_special_asset = subject_area <= 40 and subject_housing_type in {"其他", "商业", "办公", "车位"}
    large_low_liquidity_asset = subject_area >= 120 and subject_housing_type in {"其他", "商业", "办公"}

    quantile = 0.35
    if strategy in {"district_fallback", "city_fallback", "global_fallback"}:
        quantile = 0.3
    if community_missing:
        quantile -= 0.05
    if business_missing:
        quantile -= 0.03
    if subject_housing_type in {"其他", "商业", "办公", "车位"}:
        quantile -= 0.04
    if low_tier_locality:
        quantile -= 0.05
    if small_special_asset:
        quantile -= 0.05
    if subject_area >= 120 and strategy != "spatial":
        quantile -= 0.03
    if large_low_liquidity_asset and strategy != "spatial":
        quantile -= 0.04
    if subject_area >= 300:
        quantile -= 0.03
    if weak_market_engagement:
        quantile -= 0.03
    quantile = max(0.15, min(0.45, quantile))

    lower_neutral_quantile = _weighted_quantile_unit_price(weighted_samples, quantile)
    if lower_neutral_quantile <= 0 or predicted_unit_price <= 0:
        return predicted_unit_price, "无保守混合", 1.0, 0.0, 0.0

    conservative_unit_price = lower_neutral_quantile * temporal_factor * subject_risk_factor * subject_attr_factor
    if conservative_unit_price <= 0:
        return predicted_unit_price, "保守混合无效", 1.0, 0.0, lower_neutral_quantile

    blend = {
        "spatial": 0.0,
        "community_fallback": 0.06,
        "business_area_fallback": 0.12,
        "district_fallback": 0.18,
        "city_fallback": 0.24,
        "global_fallback": 0.32,
    }.get(strategy, 0.12)

    if dispersion_cv >= 0.9:
        blend += 0.12
    elif dispersion_cv >= 0.6:
        blend += 0.08
    elif dispersion_cv >= 0.4:
        blend += 0.04

    if subject_housing_type in {"", "其他"}:
        blend += 0.04
    if subject_housing_type in {"商业", "办公", "车位"}:
        blend += 0.05
    if not _normalized_group_text(_get(subject, "community_name")):
        blend += 0.08
    if not _record_business_area(subject):
        blend += 0.06
    if low_tier_locality:
        blend += 0.08
    if small_special_asset:
        blend += 0.07
    if large_low_liquidity_asset and strategy != "spatial":
        blend += 0.05
    if weak_market_engagement:
        blend += 0.05

    coordinate_strategy = _normalized_text(_get(subject, "coordinate_strategy"))
    if coordinate_strategy in {"missing", "city_centroid"}:
        blend += 0.05
    elif coordinate_strategy == "district_centroid":
        blend += 0.03

    if subject_area > 150 and strategy != "spatial":
        blend += 0.03
    if subject_area > 500 and subject_housing_type not in {"工业"}:
        blend += 0.04

    blend = max(0.0, min(blend, 0.55))
    if blend <= 0:
        return predicted_unit_price, "保守混合未触发", 1.0, 0.0, lower_neutral_quantile

    blended_unit_price = predicted_unit_price * (1.0 - blend) + conservative_unit_price * blend
    confidence_factor = 1.0 - min(blend * 0.15, 0.08)
    note = f"保守混合分位单价={conservative_unit_price:.0f}元/㎡ blend={blend:.2f}"
    return blended_unit_price, note, confidence_factor, blend, lower_neutral_quantile


def _apply_area_scale_guard(
    subject: Dict[str, Any],
    strategy: str,
    weighted_samples: Sequence[Tuple[Dict[str, Any], float]],
    predicted_unit_price: float,
) -> Tuple[float, str, float, float, float]:
    subject_area = _to_float(_get(subject, "area_sqm"), 0.0)
    if subject_area <= 0 or predicted_unit_price <= 0:
        return predicted_unit_price, "无面积尺度护栏", 1.0, 0.0, 0.0

    median_area = _weighted_quantile_area(weighted_samples, 0.5)
    if median_area <= 0:
        return predicted_unit_price, "面积尺度护栏无效", 1.0, 0.0, 0.0

    area_ratio = subject_area / median_area
    if area_ratio <= 1.2:
        return predicted_unit_price, "面积尺度护栏未触发", 1.0, 0.0, median_area

    subject_housing_type = _normalized_text(_get(subject, "housing_type"))
    severity = {
        "spatial": 0.0,
        "community_fallback": 0.04,
        "business_area_fallback": 0.08,
        "district_fallback": 0.12,
        "city_fallback": 0.18,
        "global_fallback": 0.24,
    }.get(strategy, 0.08)

    if subject_housing_type in {"商业", "办公", "其他"}:
        severity += 0.05
        if subject_area >= 200:
            severity += 0.06
    elif subject_housing_type == "工业":
        severity += 0.08
    if area_ratio >= 6:
        severity += 0.16
    elif area_ratio >= 3:
        severity += 0.10
    elif area_ratio >= 2:
        severity += 0.06

    severity = max(0.0, min(severity, 0.45))
    if severity <= 0:
        return predicted_unit_price, "面积尺度护栏未触发", 1.0, 0.0, median_area

    adjusted_unit_price = predicted_unit_price * (1.0 - severity)
    confidence_factor = 1.0 - min(severity * 0.12, 0.06)
    note = f"面积尺度护栏中位面积={median_area:.0f}㎡ ratio={area_ratio:.2f} severity={severity:.2f}"
    return adjusted_unit_price, note, confidence_factor, severity, median_area


def _apply_locality_guard(
    subject: Dict[str, Any],
    strategy: str,
    predicted_unit_price: float,
) -> Tuple[float, str, float, float]:
    if predicted_unit_price <= 0:
        return predicted_unit_price, "无低层级位置护栏", 1.0, 0.0

    business_area = _record_business_area(subject)
    district = _normalized_group_text(_get(subject, "district"))
    community = _normalized_group_text(_get(subject, "community_name"))
    coordinate_strategy = _normalized_text(_get(subject, "coordinate_strategy"))
    housing_type = _normalized_text(_get(subject, "housing_type"))

    severity = 0.0
    if any(token in business_area for token in ("镇", "乡", "村")):
        severity += 0.07
    if district.endswith("县") or district.endswith("旗"):
        severity += 0.04
    if strategy in {"district_fallback", "city_fallback", "global_fallback"}:
        severity += 0.03
    if coordinate_strategy in {"missing", "city_centroid", "district_centroid"}:
        severity += 0.03
    if housing_type in {"商业", "办公", "其他"}:
        severity += 0.03
    if not community:
        severity += 0.02

    severity = max(0.0, min(severity, 0.18))
    if severity <= 0:
        return predicted_unit_price, "低层级位置护栏未触发", 1.0, 0.0

    adjusted_unit_price = predicted_unit_price * (1.0 - severity)
    confidence_factor = 1.0 - min(severity * 0.1, 0.05)
    note = f"低层级位置护栏 severity={severity:.2f}"
    return adjusted_unit_price, note, confidence_factor, severity


def _apply_evaluation_anchor(subject: Dict[str, Any], predicted_unit_price: float) -> Tuple[float, str, float, float, Optional[float]]:
    evaluation_price = _to_float(_get(subject, "evaluation_price"), 0.0)
    subject_area = _to_float(_get(subject, "area_sqm"), 0.0)
    if evaluation_price <= 0 or subject_area <= 0 or predicted_unit_price <= 0:
        return predicted_unit_price, "无评估价锚点", 1.0, 0.0, None

    evaluation_unit_price = evaluation_price / subject_area
    if evaluation_unit_price <= 0:
        return predicted_unit_price, "评估价锚点无效", 1.0, 0.0, None

    extraction_confidence = _to_float(_get(subject, "extraction_confidence"), 0.5)
    extraction_confidence = max(0.1, min(extraction_confidence if extraction_confidence > 0 else 0.5, 1.0))

    ratio = evaluation_unit_price / predicted_unit_price
    deviation = abs(ratio - 1.0)
    if ratio >= 4.0 or ratio <= 0.25:
        return predicted_unit_price, f"评估价锚点偏离过大，忽略 ratio={ratio:.2f}", 1.0, 0.0, ratio
    if deviation <= 0.15:
        blend = 0.18
    elif deviation <= 0.35:
        blend = 0.12
    elif deviation <= 0.60:
        blend = 0.06
    else:
        blend = 0.03

    blend *= 0.5 + 0.5 * extraction_confidence
    anchored_unit_price = predicted_unit_price * (1.0 - blend) + evaluation_unit_price * blend

    if deviation <= 0.20:
        confidence_factor = 1.03
    elif deviation >= 0.80:
        confidence_factor = 0.97
    else:
        confidence_factor = 1.0

    note = f"评估价锚点单价={evaluation_unit_price:.0f}元/㎡ blend={blend:.2f}"
    return anchored_unit_price, note, confidence_factor, blend, ratio


def _apply_starting_price_guard(subject: Dict[str, Any], predicted_unit_price: float, strategy: str) -> Tuple[float, str, float, float, Optional[float]]:
    starting_price = _to_float(_get(subject, "starting_price"), 0.0)
    subject_area = _to_float(_get(subject, "area_sqm"), 0.0)
    if starting_price <= 0 or subject_area <= 0 or predicted_unit_price <= 0:
        return predicted_unit_price, "无起拍价护栏", 1.0, 0.0, None

    starting_unit_price = starting_price / subject_area
    if starting_unit_price <= 0:
        return predicted_unit_price, "起拍价护栏无效", 1.0, 0.0, None

    ratio = predicted_unit_price / starting_unit_price
    subject_regime = _asset_regime_from_record(subject)
    subject_housing_type = _normalized_text(_get(subject, "housing_type"))
    threshold = {
        "spatial": 8.0,
        "community_fallback": 5.0,
        "business_area_fallback": 4.0,
        "district_fallback": 3.5,
        "city_fallback": 3.0,
        "global_fallback": 2.5,
    }.get(strategy, 3.5)

    regime_threshold = {
        "parking": 1.8,
        "commercial_micro": 2.0,
        "commercial_large": 2.3,
        "other_large": 2.2,
        "office_large": 2.4,
    }.get(subject_regime)
    if regime_threshold is not None:
        threshold = min(threshold, regime_threshold)

    coordinate_strategy = _normalized_text(_get(subject, "coordinate_strategy"))
    if coordinate_strategy in {"missing", "district_centroid", "city_centroid"}:
        threshold *= 0.9
    if not _normalized_group_text(_get(subject, "community_name")):
        threshold *= 0.9
    if _is_low_tier_locality(subject):
        threshold *= 0.82
    if _has_weak_market_engagement(subject):
        threshold *= 0.92
    if subject_area <= 40 and subject_housing_type in {"其他", "商业", "办公", "车位"}:
        threshold *= 0.86
    if subject_area >= 120 and strategy != "spatial" and subject_housing_type in {"其他", "商业", "办公"}:
        threshold *= 0.9

    if ratio <= threshold:
        return predicted_unit_price, "起拍价护栏未触发", 1.0, 0.0, ratio

    capped_unit_price = starting_unit_price * threshold
    overshoot = ratio / max(threshold, 1e-6)
    if overshoot <= 2.0:
        blend = 0.45
    elif overshoot <= 4.0:
        blend = 0.65
    else:
        blend = 0.82
    if coordinate_strategy in {"missing", "district_centroid", "city_centroid"} and strategy != "spatial":
        blend = min(0.9, blend + 0.08)
    if _is_low_tier_locality(subject):
        blend = min(0.92, blend + 0.06)
    if _has_weak_market_engagement(subject):
        blend = min(0.92, blend + 0.04)

    guarded_unit_price = predicted_unit_price * (1.0 - blend) + capped_unit_price * blend
    strict_hard_cap_regimes = {
        "parking",
        "commercial_micro",
        "commercial_large",
        "other_large",
        "other_standard",
    }
    should_hard_cap = (
        subject_regime in strict_hard_cap_regimes
        and strategy != "spatial"
        and (
            ratio >= max(threshold * 2.5, 8.0)
            or (_is_low_tier_locality(subject) and ratio >= threshold * 1.8)
        )
    )
    if should_hard_cap:
        guarded_unit_price = min(guarded_unit_price, capped_unit_price)
    if regime_threshold is not None and ratio >= threshold * 4.0:
        guarded_unit_price = min(guarded_unit_price, capped_unit_price)
    confidence_factor = 0.94 if blend < 0.7 else 0.9
    note = f"起拍价护栏单价={starting_unit_price:.0f}元/㎡ threshold={threshold:.2f} blend={blend:.2f}"
    return guarded_unit_price, note, confidence_factor, blend, ratio


def predict_price(subject: Dict[str, Any], dataset: List[Dict[str, Any]], radius_km: float = 3.0) -> Dict[str, Any]:
    lat = subject.get("latitude")
    lon = subject.get("longitude")
    area = subject.get("area_sqm")

    if not lat or not lon or not area:
        return {
            "predicted_price": None,
            "confidence": 0.0,
            "comparable_count": 0,
            "message": "subject missing latitude/longitude/area_sqm",
        }

    weighted_sum = 0.0
    weight_sum = 0.0
    comps: List[Tuple[float, float]] = []

    for row in dataset:
        rlat = row.get("latitude")
        rlon = row.get("longitude")
        if not rlat or not rlon:
            continue
        unit_price = _calc_unit_price(row)
        if unit_price <= 0:
            continue

        distance = haversine_km(float(lat), float(lon), float(rlat), float(rlon))
        if distance > radius_km:
            continue

        w = distance_weight(distance)
        if row.get("community_name") and row.get("community_name") == subject.get("community_name"):
            w *= 1.5
        elif row.get("business_area") and row.get("business_area") == subject.get("business_area"):
            w *= 1.2
        if row.get("district") and subject.get("district") and row.get("district") != subject.get("district"):
            w *= 0.7

        weighted_sum += unit_price * w
        weight_sum += w
        comps.append((distance, w))

    if weight_sum <= 0:
        return {
            "predicted_price": None,
            "confidence": 0.0,
            "comparable_count": 0,
            "message": "no comparables within radius",
        }

    pred_unit_price = weighted_sum / weight_sum
    predicted_price = round(pred_unit_price * float(area), 2)

    count = len(comps)
    confidence = min(1.0, 0.25 + 0.1 * count)
    return {
        "predicted_price": predicted_price,
        "predicted_unit_price": round(pred_unit_price, 2),
        "confidence": round(confidence, 3),
        "comparable_count": count,
        "radius_km": radius_km,
    }


def predict_fair_price(subject: Dict[str, Any], comparables: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    valuation_mode = _resolve_valuation_mode(subject)
    subject_area = _to_float(_get(subject, "area_sqm"), 0.0)
    if subject_area <= 0:
        return {
            "predicted_price": None,
            "confidence": 0.0,
            "comparable_count": 0,
            "top_factors": ["标的面积缺失或非法，无法估值"],
            "strategy": "invalid_subject",
        }

    normalized = [rec for rec in (_normalize_record(c) for c in comparables) if rec is not None]
    if not normalized:
        return {
            "predicted_price": None,
            "confidence": 0.0,
            "comparable_count": 0,
            "top_factors": ["缺少有效可比样本"],
            "strategy": "no_comparables",
        }

    normalized, future_dated_excluded_count = _exclude_future_dated_comparables(subject, normalized)
    if not normalized:
        return {
            "predicted_price": None,
            "confidence": 0.0,
            "comparable_count": 0,
            "top_factors": ["可比样本全部晚于标的时间，无法估值"],
            "strategy": "no_comparables",
        }

    radius_km = _resolve_radius_km(subject)
    weighting = _resolve_weighting()
    weighted_samples = _spatial_filter_and_weight(subject, normalized, radius_km=radius_km, weighting=weighting)
    strategy = "spatial"
    if len(weighted_samples) < 3:
        weighted_samples, strategy = _fallback_filter_and_weight(subject, normalized, weighting=weighting)
    subject_housing_type = _normalized_text(_get(subject, "housing_type"))
    weighted_samples, trimmed_outlier_count = _trim_outlier_samples(
        weighted_samples,
        strategy,
        subject_housing_type,
    )

    if not weighted_samples:
        return {
            "predicted_price": None,
            "confidence": 0.0,
            "comparable_count": 0,
            "top_factors": ["可比样本筛选后为空"],
            "strategy": "no_comparables",
        }

    weight_sum = sum(weight for _, weight in weighted_samples)
    neutral_unit_price_mean = (
        sum(rec["_neutral_unit_price"] * weight for rec, weight in weighted_samples) / max(weight_sum, 1e-12)
    )
    cv = _coefficient_of_variation(weighted_samples)
    neutral_unit_price, neutral_unit_price_median, robust_unit_blend = _robust_unit_price(
        weighted_samples,
        neutral_unit_price_mean,
        strategy,
        cv,
    )

    temporal_factor, temporal_note, trend_count, temporal_target_dt, temporal_reference_mode = _build_temporal_factor(
        subject,
        normalized,
        weighting=weighting,
    )
    temporal_unit_price = neutral_unit_price * temporal_factor

    subject_risk_factor, subject_risk_reasons = _risk_adjustment(subject)
    subject_attr_factor, subject_attr_reasons = _subject_attribute_adjustment(subject)
    predicted_unit_price = temporal_unit_price * subject_risk_factor * subject_attr_factor
    predicted_unit_price, uncertainty_note, uncertainty_conf_factor, uncertainty_blend, uncertainty_lower_quantile = _apply_uncertainty_conservative_blend(
        subject,
        strategy,
        weighted_samples,
        predicted_unit_price,
        temporal_factor,
        subject_risk_factor,
        subject_attr_factor,
        cv,
    )
    predicted_unit_price, area_scale_note, area_scale_conf_factor, area_scale_severity, comparable_area_median = _apply_area_scale_guard(
        subject,
        strategy,
        weighted_samples,
        predicted_unit_price,
    )
    predicted_unit_price, locality_note, locality_conf_factor, locality_severity = _apply_locality_guard(
        subject,
        strategy,
        predicted_unit_price,
    )
    predicted_unit_price, evaluation_anchor_note, evaluation_conf_factor, evaluation_anchor_blend, evaluation_anchor_ratio = _apply_evaluation_anchor(
        subject,
        predicted_unit_price,
    )
    predicted_unit_price, starting_price_guard_note, starting_price_conf_factor, starting_price_guard_blend, starting_price_guard_ratio = _apply_starting_price_guard(
        subject,
        predicted_unit_price,
        strategy,
    )
    predicted_price = predicted_unit_price * subject_area

    n = len(weighted_samples)
    sample_conf = min(1.0, n / 15.0)

    entropy = 0.0
    for _, w in weighted_samples:
        p = w / max(weight_sum, 1e-12)
        if p > 0:
            entropy -= p * math.log(p)
    max_entropy = math.log(max(n, 2))
    concentration = 1.0 - min(1.0, entropy / max(max_entropy, 1e-12))

    dispersion_conf = max(0.15, 1.0 - min(cv, 1.0))
    trend_conf = min(1.0, trend_count / 12.0)
    strategy_factor = {
        "spatial": 1.0,
        "community_fallback": 0.92,
        "business_area_fallback": 0.86,
        "district_fallback": 0.78,
        "city_fallback": 0.68,
        "global_fallback": 0.55,
    }.get(strategy, 0.5)
    bid_count = _to_float(_get(subject, "bid_count"), 0.0)
    apply_count = _to_float(_get(subject, "apply_count"), 0.0)
    market_signal_factor = 1.0
    if bid_count >= 10 or apply_count >= 5:
        market_signal_factor = 1.04
    elif bid_count <= 1 and apply_count <= 1 and (bid_count > 0 or apply_count > 0):
        market_signal_factor = 0.96
    confidence = (
        0.30 * sample_conf
        + 0.25 * concentration
        + 0.20 * trend_conf
        + 0.15 * dispersion_conf
        + 0.10 * strategy_factor
    )
    confidence *= market_signal_factor * uncertainty_conf_factor * area_scale_conf_factor * locality_conf_factor * evaluation_conf_factor * starting_price_conf_factor
    confidence = max(0.0, min(1.0, confidence))

    top_factors = [
        f"主策略={strategy}",
        f"去风险后可比单价={neutral_unit_price:.0f}元/㎡",
        temporal_note,
        f"目标标的风控修正系数={subject_risk_factor:.3f}",
        f"目标标的属性修正系数={subject_attr_factor:.3f}",
        f"样本数={n}",
    ]
    if trimmed_outlier_count > 0:
        top_factors.append(f"离群样本裁剪数={trimmed_outlier_count}")
    if future_dated_excluded_count > 0:
        top_factors.append(f"未来时间可比剔除数={future_dated_excluded_count}")
    if robust_unit_blend > 0:
        top_factors.append(f"鲁棒聚合中位单价={neutral_unit_price_median:.0f}元/㎡ blend={robust_unit_blend:.2f}")
    if uncertainty_blend > 0:
        top_factors.append(uncertainty_note)
    if area_scale_severity > 0:
        top_factors.append(area_scale_note)
    if locality_severity > 0:
        top_factors.append(locality_note)
    if evaluation_anchor_blend > 0:
        top_factors.append(evaluation_anchor_note)
    if starting_price_guard_blend > 0:
        top_factors.append(starting_price_guard_note)
    top_factors.extend(subject_risk_reasons[:3])
    top_factors.extend(subject_attr_reasons[:2])

    return {
        "predicted_price": round(predicted_price, 2),
        "predicted_unit_price": round(predicted_unit_price, 2),
        "confidence": round(confidence, 4),
        "comparable_count": n,
        "strategy": strategy,
        "trace": {
            "strategy": strategy,
            "valuation_mode": valuation_mode,
            "spatial_radius_km": radius_km,
            "weighting_distance_power": round(weighting["distance_power"], 4),
            "weighting_time_decay": round(weighting["time_decay"], 4),
            "weighting_community_boost": round(weighting["community_boost"], 4),
            "trend_sample_count": trend_count,
            "future_dated_comparable_count_excluded": int(future_dated_excluded_count),
            "temporal_target_date": temporal_target_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "temporal_reference_mode": temporal_reference_mode,
            "weight_sum": round(weight_sum, 4),
            "dispersion_cv": round(cv, 4),
            "robust_unit_blend": round(robust_unit_blend, 4),
            "neutral_unit_price_mean": round(neutral_unit_price_mean, 2),
            "neutral_unit_price_median": round(neutral_unit_price_median, 2),
            "trimmed_outlier_count": int(trimmed_outlier_count),
            "uncertainty_blend": round(uncertainty_blend, 4),
            "uncertainty_lower_quantile": round(uncertainty_lower_quantile, 2),
            "area_scale_severity": round(area_scale_severity, 4),
            "comparable_area_median": round(comparable_area_median, 2),
            "locality_severity": round(locality_severity, 4),
            "low_tier_locality": _is_low_tier_locality(subject),
            "weak_market_engagement": _has_weak_market_engagement(subject),
            "subject_risk_factor": round(subject_risk_factor, 4),
            "active_risk_discount_factor": round(_resolve_risk_discount_factor(), 4),
            "subject_attribute_factor": round(subject_attr_factor, 4),
            "risk_factor_override_count": len(get_active_risk_factor_overrides()),
            "market_signal_factor": round(market_signal_factor, 4),
            "evaluation_anchor_blend": round(evaluation_anchor_blend, 4),
            "evaluation_anchor_ratio": round(evaluation_anchor_ratio, 4) if evaluation_anchor_ratio is not None else None,
            "starting_price_guard_blend": round(starting_price_guard_blend, 4),
            "starting_price_guard_ratio": round(starting_price_guard_ratio, 4) if starting_price_guard_ratio is not None else None,
        },
        "top_factors": top_factors,
    }
