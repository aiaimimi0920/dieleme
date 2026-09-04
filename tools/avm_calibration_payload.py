"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_calibration_context import *


def _load_json_dict(
    path: Path,
    fallback: dict[str, Any] | None = None,
    *,
    coerce_non_object_to_fallback: bool = False,
) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(fallback or {})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        if coerce_non_object_to_fallback:
            return copy.deepcopy(fallback or {})
        raise ValueError(f"invalid JSON object at {path}")
    if not isinstance(payload, dict):
        if coerce_non_object_to_fallback:
            return copy.deepcopy(fallback or {})
        raise ValueError(f"invalid JSON object at {path}")
    return payload


def normalize_calibration_targets_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw_payload = dict(payload) if isinstance(payload, dict) else {}

    def _normalize_target_rows(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, (list, tuple)):
            return []
        return [item for item in value if isinstance(item, dict)]

    global_risk_targets = _normalize_target_rows(raw_payload.get("global_risk_targets"))
    risk_factor_targets = _normalize_target_rows(raw_payload.get("risk_factor_targets"))
    temporal_targets = _normalize_target_rows(raw_payload.get("temporal_targets"))
    strategy_targets = _normalize_target_rows(raw_payload.get("strategy_targets"))

    top_calibration_target = raw_payload.get("top_calibration_target")
    if not isinstance(top_calibration_target, dict) and top_calibration_target is not None:
        top_calibration_target = None
    top_calibration_target_hint = raw_payload.get("top_calibration_target_hint")
    if not isinstance(top_calibration_target_hint, dict) and top_calibration_target_hint is not None:
        top_calibration_target_hint = None

    return {
        **raw_payload,
        "has_recommendations": bool(global_risk_targets or risk_factor_targets or temporal_targets or strategy_targets),
        "global_risk_targets": global_risk_targets,
        "risk_factor_targets": risk_factor_targets,
        "temporal_targets": temporal_targets,
        "strategy_targets": strategy_targets,
        "top_calibration_target": top_calibration_target,
        "top_calibration_target_hint": top_calibration_target_hint,
        "guidance": raw_payload.get("guidance") if isinstance(raw_payload.get("guidance"), dict) else {},
        "config_patch": raw_payload.get("config_patch") if isinstance(raw_payload.get("config_patch"), dict) else {},
    }


def merge_avm_config_patch(config: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    merged = copy.deepcopy(config)
    changed_keys: list[str] = []

    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            for child_key, child_value in value.items():
                if merged[key].get(child_key) != child_value:
                    changed_keys.append(f"{key}.{child_key}")
                merged[key][child_key] = child_value
        else:
            if merged.get(key) != value:
                changed_keys.append(str(key))
            merged[key] = value

    return merged, changed_keys


def _build_changed_path_details(config: dict[str, Any], merged: dict[str, Any], changed_keys: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    changed_paths: dict[str, dict[str, Any]] = {}
    rollback_patch: dict[str, Any] = {}

    for path in changed_keys:
        segments = path.split(".")
        before: Any = config
        after: Any = merged
        for segment in segments:
            before = before.get(segment) if isinstance(before, dict) else None
            after = after.get(segment) if isinstance(after, dict) else None
        changed_paths[path] = {"before": before, "after": after}

        cursor = rollback_patch
        for segment in segments[:-1]:
            cursor = cursor.setdefault(segment, {})
        cursor[segments[-1]] = before

    return changed_paths, rollback_patch


__all__ = (
    '_load_json_dict',
    'normalize_calibration_targets_payload',
    'merge_avm_config_patch',
    '_build_changed_path_details',
)
