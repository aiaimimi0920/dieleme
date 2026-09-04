"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_evaluation_context import *


def _has_valid_coordinates(feature: dict[str, Any]) -> bool:
    lat = feature.get("latitude")
    lon = feature.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    return 3.0 <= float(lat) <= 54.5 and 73.0 <= float(lon) <= 136.0


def _derive_coordinate_strategy(feature: dict[str, Any]) -> str:
    if _has_valid_coordinates(feature):
        return "observed"
    community = _normalized_group_value(feature.get("community_name"))
    business = _normalized_group_value(feature.get("business_area"))
    district = _normalized_group_value(feature.get("district"))
    city = _normalized_group_value(feature.get("city"))
    if community:
        return "community_centroid"
    if city and district and business:
        return "business_area_centroid"
    if city and district:
        return "district_centroid"
    if city:
        return "city_centroid"
    return "missing"


def _coordinate_group_keys(feature: dict[str, Any]) -> list[tuple[str, str]]:
    community = _normalized_group_value(feature.get("community_name"))
    business = _normalized_group_value(feature.get("business_area"))
    district = _normalized_group_value(feature.get("district"))
    city = _normalized_group_value(feature.get("city"))

    keys: list[tuple[str, str]] = []
    if community:
        keys.append(("community_centroid", f"community::{community}"))
    if city and district and business:
        keys.append(("business_area_centroid", f"business::{city}::{district}::{business}"))
    if city and district:
        keys.append(("district_centroid", f"district::{city}::{district}"))
    if city:
        keys.append(("city_centroid", f"city::{city}"))
    return keys


def _build_coordinate_centroids(records: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    aggregates: dict[str, list[float]] = {}
    for record in records:
        if not _has_valid_coordinates(record):
            continue
        lat = float(record["latitude"])
        lon = float(record["longitude"])
        for _, key in _coordinate_group_keys(record):
            bucket = aggregates.setdefault(key, [0.0, 0.0, 0.0])
            bucket[0] += lat
            bucket[1] += lon
            bucket[2] += 1.0

    centroids: dict[str, tuple[float, float]] = {}
    for key, (lat_sum, lon_sum, count) in aggregates.items():
        if count <= 0:
            continue
        centroids[key] = (round(lat_sum / count, 6), round(lon_sum / count, 6))
    return centroids


def _enrich_coordinates(record: dict[str, Any], centroids: dict[str, tuple[float, float]]) -> dict[str, Any]:
    enriched = dict(record)
    if _has_valid_coordinates(enriched):
        enriched["coordinate_strategy"] = "observed"
        return enriched

    for strategy, key in _coordinate_group_keys(enriched):
        centroid = centroids.get(key)
        if centroid is None:
            continue
        enriched["latitude"], enriched["longitude"] = centroid
        enriched["coordinate_strategy"] = strategy
        return enriched

    enriched["coordinate_strategy"] = "missing"
    return enriched


def _enrich_coordinate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    centroids = _build_coordinate_centroids(records)
    return [_enrich_coordinates(record, centroids) for record in records]


__all__ = (
    "_has_valid_coordinates",
    "_derive_coordinate_strategy",
    "_coordinate_group_keys",
    "_build_coordinate_centroids",
    "_enrich_coordinates",
    "_enrich_coordinate_records",
)
