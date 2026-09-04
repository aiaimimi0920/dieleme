from __future__ import annotations

from .engine_statistics import *  # noqa: F401,F403

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



__all__ = [name for name in globals() if not name.startswith("__")]
