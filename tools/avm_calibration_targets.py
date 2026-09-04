"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_calibration_context import *


def _normalize_filter_values(
    *,
    singular: str | None = None,
    plural: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    values: list[str] = []
    if singular:
        values.append(str(singular))
    for value in plural or []:
        if value:
            values.append(str(value))

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _build_applied_filter_payload(target_types: list[str], target_names: list[str]) -> dict[str, Any] | None:
    if not target_types and not target_names:
        return None
    if len(target_types) <= 1 and len(target_names) <= 1:
        return {
            "target_type": target_types[0] if target_types else None,
            "target_name": target_names[0] if target_names else None,
        }
    return {
        "target_types": target_types or None,
        "target_names": target_names or None,
    }


def _build_target_patch_entries(calibration_report: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    for row in calibration_report.get("temporal_targets", []) or []:
        if not isinstance(row, dict):
            continue
        suggested_next_value = row.get("suggested_next_value")
        if suggested_next_value is None:
            continue
        entries.append(
            {
                "target_type": "temporal",
                "target_name": str(row.get("name") or "time_decay"),
                "patch": {"weighting": {"time_decay": suggested_next_value}},
            }
        )

    for row in calibration_report.get("global_risk_targets", []) or []:
        if not isinstance(row, dict):
            continue
        suggested_next_value = row.get("suggested_next_value")
        if suggested_next_value is None:
            continue
        entries.append(
            {
                "target_type": "global_risk",
                "target_name": str(row.get("name") or "risk_discount_factor"),
                "patch": {"risk_discount_factor": suggested_next_value},
            }
        )

    for row in calibration_report.get("risk_factor_targets", []) or []:
        if not isinstance(row, dict):
            continue
        target_name = str(row.get("name") or "")
        suggested_next_factor = row.get("suggested_next_factor")
        if not target_name or suggested_next_factor is None:
            continue
        entries.append(
            {
                "target_type": "risk_flag",
                "target_name": target_name,
                "patch": {"risk_factor_overrides": {target_name: suggested_next_factor}},
            }
        )

    return entries


def _select_config_patch(
    calibration_report: dict[str, Any],
    *,
    target_type: str | None = None,
    target_name: str | None = None,
    target_types: list[str] | tuple[str, ...] | None = None,
    target_names: list[str] | tuple[str, ...] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    config_patch = calibration_report.get("config_patch") if isinstance(calibration_report.get("config_patch"), dict) else {}
    normalized_target_types = _normalize_filter_values(singular=target_type, plural=target_types)
    normalized_target_names = _normalize_filter_values(singular=target_name, plural=target_names)
    if not normalized_target_types and not normalized_target_names:
        return config_patch, []

    filtered_entries: list[tuple[int, dict[str, Any]]] = []
    for ordinal, entry in enumerate(_build_target_patch_entries(calibration_report)):
        entry_type = str(entry.get("target_type") or "")
        entry_name = str(entry.get("target_name") or "")
        if normalized_target_types and entry_type not in normalized_target_types:
            continue
        if normalized_target_names and entry_name not in normalized_target_names:
            continue
        filtered_entries.append((ordinal, entry))

    def _entry_sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
        ordinal, entry = item
        entry_type = str(entry.get("target_type") or "")
        entry_name = str(entry.get("target_name") or "")
        type_index = normalized_target_types.index(entry_type) if normalized_target_types and entry_type in normalized_target_types else 0
        name_index = normalized_target_names.index(entry_name) if normalized_target_names and entry_name in normalized_target_names else 0
        return type_index, name_index, ordinal

    filtered_entries.sort(key=_entry_sort_key)

    matched_targets: list[dict[str, str]] = []
    filtered_patch: dict[str, Any] = {}
    for _, entry in filtered_entries:
        entry_type = str(entry.get("target_type") or "")
        entry_name = str(entry.get("target_name") or "")
        filtered_patch, _ = merge_avm_config_patch(filtered_patch, entry.get("patch") or {})
        matched_targets.append({"target_type": entry_type, "target_name": entry_name})

    return filtered_patch, matched_targets


__all__ = (
    '_normalize_filter_values',
    '_build_applied_filter_payload',
    '_build_target_patch_entries',
    '_select_config_patch',
)
