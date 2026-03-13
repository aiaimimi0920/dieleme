"""AVM engine helpers."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any


EARTH_RADIUS_KM = 6371.0


def _to_float(value: Any) -> float | None:
    """Safely convert values to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_lat_lon(record: dict[str, Any]) -> tuple[float | None, float | None]:
    """Read latitude and longitude from common field aliases."""
    lat = _to_float(record.get("lat", record.get("latitude")))
    lon = _to_float(record.get("lon", record.get("lng", record.get("longitude"))))
    return lat, lon


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points in kilometers."""
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)

    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)

    a = sin(d_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(d_lon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return EARTH_RADIUS_KM * c


def find_comparables(
    subject: dict[str, Any],
    dataset: list[dict[str, Any]],
    radius_km: float = 3,
) -> list[dict[str, Any]]:
    """Find nearby comparable transactions around a subject property.

    Rules:
    - Uses Haversine distance to compute geographic proximity.
    - Excludes records missing required fields: coordinates, transaction price, or area.
    - Returns only records within ``radius_km`` sorted by distance ascending.
    """
    subject_lat, subject_lon = _get_lat_lon(subject)
    if subject_lat is None or subject_lon is None:
        return []

    comparables: list[dict[str, Any]] = []

    for record in dataset:
        lat, lon = _get_lat_lon(record)
        price = _to_float(record.get("transaction_price", record.get("price")))
        area = _to_float(record.get("area"))

        if lat is None or lon is None or price is None or area is None:
            continue

        distance_km = haversine_distance_km(subject_lat, subject_lon, lat, lon)
        if distance_km <= radius_km:
            comparable = dict(record)
            comparable["distance_km"] = distance_km
            comparables.append(comparable)

    comparables.sort(key=lambda item: item["distance_km"])
    return comparables
