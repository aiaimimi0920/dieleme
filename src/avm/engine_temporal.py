from __future__ import annotations

from .engine_core import *  # noqa: F401,F403

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



__all__ = [name for name in globals() if not name.startswith("__")]
