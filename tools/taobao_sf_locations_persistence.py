"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.taobao_sf_locations_context import *


def _normalize_override_locations(payload: Any) -> list[TaobaoLocationEntry]:
    if not isinstance(payload, dict):
        return []
    raw_locations = payload.get("locations") or []
    if not isinstance(raw_locations, list):
        return []
    return [entry for entry in (normalize_observed_location(item) for item in raw_locations if isinstance(item, dict)) if entry]


def build_override_payload(
    *,
    existing_payload: dict[str, Any] | None,
    observed_payload: dict[str, Any],
) -> dict[str, Any]:
    existing = existing_payload if isinstance(existing_payload, dict) else {}
    completed_provinces = {
        clean_text(value)
        for value in observed_payload.get("completed_provinces", [])
        if clean_text(value)
    }
    observed_entries = observed_entries_from_payload(observed_payload)
    if completed_provinces:
        observed_entries = [entry for entry in observed_entries if entry.province in completed_provinces]
    else:
        completed_provinces = {entry.province for entry in observed_entries}

    retained_existing = [
        entry
        for entry in _normalize_override_locations(existing)
        if entry.province not in completed_provinces
    ]
    merged_entries = dedupe_entries([*retained_existing, *observed_entries])
    replace_provinces = {
        clean_text(value)
        for value in existing.get("replace_admin_provinces", [])
        if clean_text(value)
    }
    replace_provinces.update(completed_provinces)
    return {
        "replace_admin_provinces": sorted(replace_provinces, key=_province_sort_key),
        "locations": [entry.to_override_dict() for entry in merged_entries],
    }


def new_observed_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "completed_provinces": [],
        "province_status": {},
        "locations": [],
    }


def load_observed_payload(path: str | Path) -> dict[str, Any]:
    payload = read_json(path, default=None)
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return new_observed_payload()
    payload.setdefault("completed_provinces", [])
    payload.setdefault("province_status", {})
    payload.setdefault("locations", [])
    return payload


def save_observed_payload(path: str | Path, payload: dict[str, Any]) -> None:
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = utc_now_iso()
    payload["locations"] = [entry.to_observed_dict() for entry in dedupe_entries(observed_entries_from_payload(payload))]
    payload["completed_provinces"] = sorted({clean_text(value) for value in payload.get("completed_provinces", []) if clean_text(value)}, key=_province_sort_key)
    write_json_atomic(path, payload)


def merge_entries_into_observed(
    payload: dict[str, Any],
    entries: Iterable[TaobaoLocationEntry],
) -> None:
    merged = dedupe_entries([*observed_entries_from_payload(payload), *entries])
    payload["locations"] = [entry.to_observed_dict() for entry in merged]


__all__ = (
    '_normalize_override_locations',
    'build_override_payload',
    'new_observed_payload',
    'load_observed_payload',
    'save_observed_payload',
    'merge_entries_into_observed',
)
