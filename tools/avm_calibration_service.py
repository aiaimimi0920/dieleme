"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_calibration_context import *


def apply_avm_calibration_patch(
    *,
    config_path: Path,
    calibration_path: Path,
    write_back: bool = False,
    target_type: str | None = None,
    target_name: str | None = None,
    target_types: list[str] | tuple[str, ...] | None = None,
    target_names: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    current_config = _load_json_dict(
        config_path,
        fallback=DEFAULT_AVM_CONFIG,
        coerce_non_object_to_fallback=True,
    )
    try:
        AvmConfigManager(str(config_path))._validate_config(current_config)
    except Exception:
        current_config = copy.deepcopy(DEFAULT_AVM_CONFIG)
    calibration_report = _load_json_dict(calibration_path, fallback={})
    normalized_target_types = _normalize_filter_values(singular=target_type, plural=target_types)
    normalized_target_names = _normalize_filter_values(singular=target_name, plural=target_names)
    config_patch, matched_targets = _select_config_patch(
        calibration_report,
        target_types=normalized_target_types,
        target_names=normalized_target_names,
    )

    merged_config, changed_keys = merge_avm_config_patch(current_config, config_patch)
    changed_paths, rollback_patch = _build_changed_path_details(current_config, merged_config, changed_keys)
    AvmConfigManager(str(config_path))._validate_config(merged_config)

    if write_back:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(merged_config, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "config_path": str(config_path),
        "calibration_path": str(calibration_path),
        "write_back": bool(write_back),
        "applied": bool(write_back and changed_keys),
        "applied_filter": _build_applied_filter_payload(normalized_target_types, normalized_target_names),
        "matched_targets": matched_targets,
        "changed_key_count": len(changed_keys),
        "changed_keys": changed_keys,
        "changed_paths": changed_paths,
        "rollback_patch": rollback_patch,
        "top_calibration_target": calibration_report.get("top_calibration_target"),
        "guidance": calibration_report.get("guidance"),
        "config_patch": config_patch,
        "current_config": current_config,
        "merged_config": merged_config,
    }


__all__ = (
    'apply_avm_calibration_patch',
)
