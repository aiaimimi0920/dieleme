import math
from typing import Any, Dict, List, Tuple


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
    return math.exp(-((distance_km ** 2) / (2 * sigma ** 2)))


def _calc_unit_price(record: Dict[str, Any]) -> float:
    unit_price = record.get("unit_price")
    if unit_price:
        return float(unit_price)
    tp = record.get("transaction_price")
    area = record.get("area_sqm")
    if tp and area:
        return float(tp) / float(area)
    return 0.0


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
