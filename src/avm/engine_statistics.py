from __future__ import annotations

from .engine_temporal import *  # noqa: F401,F403


def _normalize_record(comp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize after risk helpers are owned by this module."""

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



__all__ = [name for name in globals() if not name.startswith("__")]
