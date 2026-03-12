from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple


COMMUNITY_KEYS = ("所属小区", "小区", "community", "community_name")
DISTRICT_KEYS = ("区", "district")
CITY_KEYS = ("城市", "city")
AREA_KEYS = ("建筑面积", "面积", "area", "area_sqm")
UNIT_PRICE_KEYS = ("单价", "unit_price")
TOTAL_PRICE_KEYS = ("成交价格", "起拍价格", "transaction_price", "starting_price", "price")
TIME_KEYS = ("交易时间", "成交时间", "transaction_time", "deal_time", "date")


def _pick_number(data: Dict[str, Any], keys: Iterable[str]) -> Optional[float]:
    for key in keys:
        if key not in data:
            continue
        value = data.get(key)
        if value in (None, ""):
            continue
        try:
            number = float(value)
            if number > 0:
                return number
        except (TypeError, ValueError):
            continue
    return None


def _pick_text(data: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value).strip()
    return None


def _parse_time(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    fmts = ["%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"]
    for fmt in fmts:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _extract_unit_price(item: Dict[str, Any]) -> Optional[float]:
    unit_price = _pick_number(item, UNIT_PRICE_KEYS)
    if unit_price:
        return unit_price

    area = _pick_number(item, AREA_KEYS)
    total_price = _pick_number(item, TOTAL_PRICE_KEYS)
    if area and total_price and area > 0:
        return total_price / area
    return None


def _build_comparable(item: Dict[str, Any], subject_area: Optional[float]) -> Optional[Dict[str, Any]]:
    unit_price = _extract_unit_price(item)
    if not unit_price:
        return None

    area = _pick_number(item, AREA_KEYS)
    area_similarity = 1.0
    if subject_area and area and area > 0:
        area_similarity = max(0.5, 1 - abs(subject_area - area) / max(subject_area, area))

    comp = {
        "unit_price": unit_price,
        "area": area,
        "community": _pick_text(item, COMMUNITY_KEYS),
        "district": _pick_text(item, DISTRICT_KEYS),
        "city": _pick_text(item, CITY_KEYS),
        "time": _parse_time(_pick_text(item, TIME_KEYS)),
        "area_similarity": area_similarity,
    }
    return comp


def _score_recency(ts: Optional[datetime]) -> float:
    if not ts:
        return 0.8
    days = max(0, (datetime.now() - ts).days)
    if days <= 90:
        return 1.0
    if days <= 365:
        return 0.9
    if days <= 730:
        return 0.75
    return 0.6


def _weighted_price(comparables: List[Dict[str, Any]]) -> Tuple[float, Dict[str, float]]:
    total_weight = 0.0
    weighted_sum = 0.0
    for comp in comparables:
        weight = comp["area_similarity"] * _score_recency(comp["time"])
        total_weight += weight
        weighted_sum += comp["unit_price"] * weight

    if total_weight <= 0:
        return median([c["unit_price"] for c in comparables]), {
            "recency_weight": 0.0,
            "area_weight": 0.0,
            "effective_weight": 0.0,
        }

    avg_recency = sum(_score_recency(c["time"]) for c in comparables) / len(comparables)
    avg_area = sum(c["area_similarity"] for c in comparables) / len(comparables)
    return weighted_sum / total_weight, {
        "recency_weight": round(avg_recency, 3),
        "area_weight": round(avg_area, 3),
        "effective_weight": round(total_weight, 3),
    }


def _dispersion_factor(prices: List[float]) -> float:
    if len(prices) <= 1:
        return 0.55
    med = median(prices)
    if med <= 0:
        return 0.4
    mad = median([abs(p - med) for p in prices])
    ratio = mad / med
    if ratio <= 0.05:
        return 1.0
    if ratio <= 0.1:
        return 0.9
    if ratio <= 0.2:
        return 0.75
    if ratio <= 0.35:
        return 0.6
    return 0.45


def predict_fair_price(subject: Dict[str, Any], dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Predict fair price for a subject property using comparable samples.

    Returns dict with:
    - predicted_price: predicted total price (if area is available) or unit price
    - confidence: 0~1 confidence score
    - comparable_count: matched comparable sample count
    - components: explanation of model components and fallback strategy
    """
    subject_area = _pick_number(subject, AREA_KEYS)
    subject_community = _pick_text(subject, COMMUNITY_KEYS)
    subject_district = _pick_text(subject, DISTRICT_KEYS)
    subject_city = _pick_text(subject, CITY_KEYS)

    all_comps = [
        comp
        for item in dataset
        if (comp := _build_comparable(item, subject_area)) is not None
    ]

    tiered = [
        ("community", [c for c in all_comps if subject_community and c["community"] == subject_community]),
        ("district", [c for c in all_comps if subject_district and c["district"] == subject_district]),
        ("city", [c for c in all_comps if subject_city and c["city"] == subject_city]),
        ("global", all_comps),
    ]

    min_comparables = 3
    selected_tier = "global"
    selected: List[Dict[str, Any]] = []
    for tier_name, comps in tiered:
        if len(comps) >= min_comparables:
            selected_tier = tier_name
            selected = comps
            break

    degraded = False
    if not selected:
        # choose largest non-empty bucket as degraded strategy
        selected_tier, selected = max(tiered, key=lambda x: len(x[1]))
        degraded = True

    if not selected:
        # hard fallback: use subject's own price hints or 0
        area = subject_area
        subject_total = _pick_number(subject, TOTAL_PRICE_KEYS)
        subject_unit = _pick_number(subject, UNIT_PRICE_KEYS)
        if not subject_unit and area and subject_total:
            subject_unit = subject_total / area
        predicted_unit = subject_unit or 0.0
        predicted_total = predicted_unit * area if area else predicted_unit
        return {
            "predicted_price": round(predicted_total, 2),
            "confidence": 0.1,
            "comparable_count": 0,
            "components": {
                "strategy": "hard_fallback_subject_hint",
                "degraded": True,
                "selected_tier": "none",
                "predicted_unit_price": round(predicted_unit, 2),
                "notes": "无可比样本，使用标的自身价格字段兜底。",
            },
        }

    predicted_unit, weight_meta = _weighted_price(selected)
    prices = [c["unit_price"] for c in selected]
    dispersion = _dispersion_factor(prices)

    tier_factor_map = {"community": 1.0, "district": 0.85, "city": 0.7, "global": 0.55}
    tier_factor = tier_factor_map.get(selected_tier, 0.5)
    count_factor = min(1.0, len(selected) / 8)

    confidence = 0.15 + 0.85 * tier_factor * count_factor * dispersion
    if degraded or len(selected) < min_comparables:
        confidence = min(confidence, 0.45)

    predicted_price = predicted_unit * subject_area if subject_area else predicted_unit

    return {
        "predicted_price": round(predicted_price, 2),
        "confidence": round(max(0.05, min(confidence, 0.99)), 3),
        "comparable_count": len(selected),
        "components": {
            "strategy": "comparable_sales",
            "degraded": degraded or len(selected) < min_comparables,
            "selected_tier": selected_tier,
            "predicted_unit_price": round(predicted_unit, 2),
            "subject_area": subject_area,
            "tier_factor": tier_factor,
            "count_factor": round(count_factor, 3),
            "dispersion_factor": round(dispersion, 3),
            **weight_meta,
            "notes": "当可比样本不足时自动降级到更宽区域并降低置信度。",
        },
    }
