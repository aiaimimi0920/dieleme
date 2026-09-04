from __future__ import annotations

from .engine_guards import *  # noqa: F401,F403

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

__all__ = [name for name in globals() if not name.startswith("__")]
