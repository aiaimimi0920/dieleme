import json
from pathlib import Path
import pytest

from tools.apply_avm_calibration_patch import (
    _known_step_contract_defaults,
    _stage_semantics_defaults,
    apply_command_chain_next_action_policy,
    apply_avm_calibration_patch,
    resolve_command_chain_artifacts,
    summarize_bundle_command_summary,
    summarize_patch_command_chain,
    summarize_patch_follow_up_command,
    summarize_patch_next_action,
    summarize_patch_next_action_command,
    summarize_patch_risk,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_apply_avm_calibration_patch_previews_merged_config_without_writing(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    original_config = {
        "radius_km": 3.0,
        "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
        "risk_discount_factor": 0.9,
        "alert_threshold": 0.25,
        "risk_factor_overrides": {},
    }
    calibration_payload = {
        "config_patch": {
            "weighting": {"time_decay": 0.72},
            "risk_factor_overrides": {"is_occupied": 0.5},
        },
        "top_calibration_target": {"target_type": "temporal", "name": "time_decay"},
    }

    _write_json(config_path, original_config)
    _write_json(calibration_path, calibration_payload)

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
    )

    assert result["write_back"] is False
    assert result["changed_key_count"] == 2
    assert "weighting.time_decay" in result["changed_keys"]
    assert "risk_factor_overrides.is_occupied" in result["changed_keys"]
    assert result["changed_paths"]["weighting.time_decay"]["before"] == 0.85
    assert result["changed_paths"]["weighting.time_decay"]["after"] == 0.72
    assert result["rollback_patch"]["weighting"]["time_decay"] == 0.85
    assert result["top_calibration_target"]["name"] == "time_decay"
    assert result["merged_config"]["weighting"]["time_decay"] == 0.72
    assert result["merged_config"]["risk_factor_overrides"]["is_occupied"] == 0.5
    assert json.loads(config_path.read_text(encoding="utf-8")) == original_config


def test_apply_avm_calibration_patch_can_write_back_config(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    _write_json(
        config_path,
        {
            "radius_km": 3.0,
            "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
            "risk_discount_factor": 0.9,
            "alert_threshold": 0.25,
            "risk_factor_overrides": {},
        },
    )
    _write_json(
        calibration_path,
        {
            "config_patch": {"weighting": {"time_decay": 0.7}},
            "top_calibration_target": {"target_type": "temporal", "name": "time_decay"},
        },
    )

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=True,
    )

    assert result["write_back"] is True
    assert result["applied"] is True
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["weighting"]["time_decay"] == 0.7


def test_apply_avm_calibration_patch_tolerates_non_object_config_file_in_preview(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    _write_json(config_path, [])
    _write_json(
        calibration_path,
        {
            "config_patch": {"weighting": {"time_decay": 0.7}},
            "top_calibration_target": {"target_type": "temporal", "name": "time_decay"},
        },
    )

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
    )

    assert result["write_back"] is False
    assert result["changed_key_count"] == 1
    assert result["changed_keys"] == ["weighting.time_decay"]
    assert result["current_config"]["weighting"]["time_decay"] == 0.85
    assert result["merged_config"]["weighting"]["time_decay"] == 0.7
    assert json.loads(config_path.read_text(encoding="utf-8")) == []


def test_apply_avm_calibration_patch_tolerates_non_object_config_file_when_writing(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    _write_json(config_path, [])
    _write_json(
        calibration_path,
        {
            "config_patch": {"weighting": {"time_decay": 0.7}},
            "top_calibration_target": {"target_type": "temporal", "name": "time_decay"},
        },
    )

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=True,
    )

    assert result["write_back"] is True
    assert result["applied"] is True
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["radius_km"] == 3.0
    assert saved["weighting"]["time_decay"] == 0.7
    assert saved["risk_discount_factor"] == 0.9


def test_apply_avm_calibration_patch_tolerates_malformed_config_json_in_preview(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{", encoding="utf-8")
    _write_json(
        calibration_path,
        {
            "config_patch": {"weighting": {"time_decay": 0.7}},
            "top_calibration_target": {"target_type": "temporal", "name": "time_decay"},
        },
    )

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
    )

    assert result["write_back"] is False
    assert result["changed_key_count"] == 1
    assert result["changed_keys"] == ["weighting.time_decay"]
    assert result["current_config"]["weighting"]["time_decay"] == 0.85
    assert result["merged_config"]["weighting"]["time_decay"] == 0.7
    assert config_path.read_text(encoding="utf-8") == "{"


def test_apply_avm_calibration_patch_tolerates_malformed_config_json_when_writing(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{", encoding="utf-8")
    _write_json(
        calibration_path,
        {
            "config_patch": {"weighting": {"time_decay": 0.7}},
            "top_calibration_target": {"target_type": "temporal", "name": "time_decay"},
        },
    )

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=True,
    )

    assert result["write_back"] is True
    assert result["applied"] is True
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["radius_km"] == 3.0
    assert saved["weighting"]["time_decay"] == 0.7
    assert saved["risk_discount_factor"] == 0.9


def test_apply_avm_calibration_patch_tolerates_invalid_object_config_file_in_preview(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    _write_json(
        config_path,
        {
            "radius_km": 3.0,
            "weighting": [],
            "risk_discount_factor": 0.9,
            "alert_threshold": 0.25,
            "risk_factor_overrides": {},
        },
    )
    _write_json(
        calibration_path,
        {
            "config_patch": {"weighting": {"time_decay": 0.7}},
            "top_calibration_target": {"target_type": "temporal", "name": "time_decay"},
        },
    )

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
    )

    assert result["write_back"] is False
    assert result["changed_key_count"] == 1
    assert result["changed_keys"] == ["weighting.time_decay"]
    assert result["current_config"]["weighting"]["time_decay"] == 0.85
    assert result["merged_config"]["weighting"]["time_decay"] == 0.7
    assert json.loads(config_path.read_text(encoding="utf-8"))["weighting"] == []


def test_apply_avm_calibration_patch_tolerates_invalid_object_config_file_when_writing(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    _write_json(
        config_path,
        {
            "radius_km": -1,
            "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
            "risk_discount_factor": 0.9,
            "alert_threshold": 0.25,
            "risk_factor_overrides": {},
        },
    )
    _write_json(
        calibration_path,
        {
            "config_patch": {"weighting": {"time_decay": 0.7}},
            "top_calibration_target": {"target_type": "temporal", "name": "time_decay"},
        },
    )

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=True,
    )

    assert result["write_back"] is True
    assert result["applied"] is True
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["radius_km"] == 3.0
    assert saved["weighting"]["time_decay"] == 0.7
    assert saved["risk_discount_factor"] == 0.9


def test_apply_avm_calibration_patch_rejects_non_object_calibration_file_with_clear_error(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    _write_json(
        config_path,
        {
            "radius_km": 3.0,
            "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
            "risk_discount_factor": 0.9,
            "alert_threshold": 0.25,
            "risk_factor_overrides": {},
        },
    )
    _write_json(calibration_path, [])

    with pytest.raises(ValueError, match=r"invalid JSON object at .*calibration_targets\.json"):
        apply_avm_calibration_patch(
            config_path=config_path,
            calibration_path=calibration_path,
            write_back=False,
        )


def test_apply_avm_calibration_patch_rejects_malformed_calibration_json_with_clear_error(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    _write_json(
        config_path,
        {
            "radius_km": 3.0,
            "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
            "risk_discount_factor": 0.9,
            "alert_threshold": 0.25,
            "risk_factor_overrides": {},
        },
    )
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    calibration_path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match=r"invalid JSON object at .*calibration_targets\.json"):
        apply_avm_calibration_patch(
            config_path=config_path,
            calibration_path=calibration_path,
            write_back=False,
        )


def test_apply_avm_calibration_patch_can_write_back_filtered_target(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    _write_json(
        config_path,
        {
            "radius_km": 3.0,
            "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
            "risk_discount_factor": 0.9,
            "alert_threshold": 0.25,
            "risk_factor_overrides": {"is_occupied": 0.8},
        },
    )
    _write_json(
        calibration_path,
        {
            "config_patch": {
                "weighting": {"time_decay": 0.7},
                "risk_discount_factor": 1.05,
            },
            "temporal_targets": [
                {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.7}
            ],
            "global_risk_targets": [
                {"target_type": "global_risk", "name": "risk_discount_factor", "suggested_next_value": 1.05}
            ],
        },
    )

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=True,
        target_type="global_risk",
    )

    assert result["applied"] is True
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["risk_discount_factor"] == 1.05
    assert saved["weighting"]["time_decay"] == 0.85


def test_apply_avm_calibration_patch_handles_empty_patch(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    original_config = {
        "radius_km": 3.0,
        "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
        "risk_discount_factor": 0.9,
        "alert_threshold": 0.25,
        "risk_factor_overrides": {},
    }
    _write_json(config_path, original_config)
    _write_json(calibration_path, {"config_patch": {}})

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
    )

    assert result["changed_key_count"] == 0
    assert result["changed_keys"] == []
    assert result["merged_config"] == original_config


def test_apply_avm_calibration_patch_can_filter_to_temporal_target(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    original_config = {
        "radius_km": 3.0,
        "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
        "risk_discount_factor": 0.9,
        "alert_threshold": 0.25,
        "risk_factor_overrides": {"is_occupied": 0.8},
    }
    calibration_payload = {
        "config_patch": {
            "weighting": {"time_decay": 0.72},
            "risk_discount_factor": 0.99,
            "risk_factor_overrides": {"is_occupied": 0.5},
        },
        "temporal_targets": [
            {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
        ],
        "global_risk_targets": [
            {"target_type": "global_risk", "name": "risk_discount_factor", "suggested_next_value": 0.99}
        ],
        "risk_factor_targets": [
            {"target_type": "risk_flag", "name": "is_occupied", "suggested_next_factor": 0.5}
        ],
    }

    _write_json(config_path, original_config)
    _write_json(calibration_path, calibration_payload)

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
        target_type="temporal",
        target_name="time_decay",
    )

    assert result["applied_filter"] == {"target_type": "temporal", "target_name": "time_decay"}
    assert result["matched_targets"] == [{"target_type": "temporal", "target_name": "time_decay"}]
    assert result["changed_keys"] == ["weighting.time_decay"]
    assert result["merged_config"]["weighting"]["time_decay"] == 0.72
    assert result["merged_config"]["risk_discount_factor"] == 0.9
    assert result["merged_config"]["risk_factor_overrides"]["is_occupied"] == 0.8


def test_apply_avm_calibration_patch_can_filter_to_specific_risk_flag_target(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    original_config = {
        "radius_km": 3.0,
        "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
        "risk_discount_factor": 0.9,
        "alert_threshold": 0.25,
        "risk_factor_overrides": {"is_occupied": 0.8, "has_long_lease": 0.85},
    }
    calibration_payload = {
        "config_patch": {
            "risk_factor_overrides": {
                "is_occupied": 0.5,
                "has_long_lease": 0.7,
            }
        },
        "risk_factor_targets": [
            {"target_type": "risk_flag", "name": "is_occupied", "suggested_next_factor": 0.5},
            {"target_type": "risk_flag", "name": "has_long_lease", "suggested_next_factor": 0.7},
        ],
    }

    _write_json(config_path, original_config)
    _write_json(calibration_path, calibration_payload)

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
        target_type="risk_flag",
        target_name="has_long_lease",
    )

    assert result["applied_filter"] == {"target_type": "risk_flag", "target_name": "has_long_lease"}
    assert result["matched_targets"] == [{"target_type": "risk_flag", "target_name": "has_long_lease"}]
    assert result["changed_keys"] == ["risk_factor_overrides.has_long_lease"]
    assert result["merged_config"]["risk_factor_overrides"]["is_occupied"] == 0.8
    assert result["merged_config"]["risk_factor_overrides"]["has_long_lease"] == 0.7


def test_apply_avm_calibration_patch_can_filter_to_global_risk_target(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    original_config = {
        "radius_km": 3.0,
        "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
        "risk_discount_factor": 0.9,
        "alert_threshold": 0.25,
        "risk_factor_overrides": {"is_occupied": 0.8},
    }
    calibration_payload = {
        "config_patch": {
            "weighting": {"time_decay": 0.72},
            "risk_discount_factor": 1.05,
        },
        "temporal_targets": [
            {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
        ],
        "global_risk_targets": [
            {"target_type": "global_risk", "name": "risk_discount_factor", "suggested_next_value": 1.05}
        ],
    }

    _write_json(config_path, original_config)
    _write_json(calibration_path, calibration_payload)

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
        target_type="global_risk",
    )

    assert result["applied_filter"] == {"target_type": "global_risk", "target_name": None}
    assert result["matched_targets"] == [{"target_type": "global_risk", "target_name": "risk_discount_factor"}]
    assert result["changed_keys"] == ["risk_discount_factor"]
    assert result["merged_config"]["risk_discount_factor"] == 1.05
    assert result["merged_config"]["weighting"]["time_decay"] == 0.85


def test_apply_avm_calibration_patch_can_filter_to_multiple_target_types(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    original_config = {
        "radius_km": 3.0,
        "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
        "risk_discount_factor": 0.9,
        "alert_threshold": 0.25,
        "risk_factor_overrides": {"is_occupied": 0.8},
    }
    calibration_payload = {
        "config_patch": {
            "weighting": {"time_decay": 0.72},
            "risk_discount_factor": 1.05,
            "risk_factor_overrides": {"is_occupied": 0.5},
        },
        "temporal_targets": [
            {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
        ],
        "global_risk_targets": [
            {"target_type": "global_risk", "name": "risk_discount_factor", "suggested_next_value": 1.05}
        ],
        "risk_factor_targets": [
            {"target_type": "risk_flag", "name": "is_occupied", "suggested_next_factor": 0.5}
        ],
    }

    _write_json(config_path, original_config)
    _write_json(calibration_path, calibration_payload)

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
        target_types=["temporal", "global_risk"],
    )

    assert result["applied_filter"] == {"target_types": ["temporal", "global_risk"], "target_names": None}
    assert result["matched_targets"] == [
        {"target_type": "temporal", "target_name": "time_decay"},
        {"target_type": "global_risk", "target_name": "risk_discount_factor"},
    ]
    assert result["changed_keys"] == ["weighting.time_decay", "risk_discount_factor"]
    assert result["merged_config"]["weighting"]["time_decay"] == 0.72
    assert result["merged_config"]["risk_discount_factor"] == 1.05
    assert result["merged_config"]["risk_factor_overrides"]["is_occupied"] == 0.8


def test_apply_avm_calibration_patch_can_filter_to_multiple_target_names(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    calibration_path = tmp_path / "datas" / "avm" / "calibration_targets.json"

    original_config = {
        "radius_km": 3.0,
        "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
        "risk_discount_factor": 0.9,
        "alert_threshold": 0.25,
        "risk_factor_overrides": {"is_occupied": 0.8, "has_long_lease": 0.85, "property_fee_owed": 0.82},
    }
    calibration_payload = {
        "config_patch": {
            "risk_factor_overrides": {
                "is_occupied": 0.5,
                "has_long_lease": 0.7,
                "property_fee_owed": 0.75,
            }
        },
        "risk_factor_targets": [
            {"target_type": "risk_flag", "name": "is_occupied", "suggested_next_factor": 0.5},
            {"target_type": "risk_flag", "name": "has_long_lease", "suggested_next_factor": 0.7},
            {"target_type": "risk_flag", "name": "property_fee_owed", "suggested_next_factor": 0.75},
        ],
    }

    _write_json(config_path, original_config)
    _write_json(calibration_path, calibration_payload)

    result = apply_avm_calibration_patch(
        config_path=config_path,
        calibration_path=calibration_path,
        write_back=False,
        target_type="risk_flag",
        target_names=["is_occupied", "has_long_lease"],
    )

    assert result["applied_filter"] == {"target_types": ["risk_flag"], "target_names": ["is_occupied", "has_long_lease"]}
    assert result["matched_targets"] == [
        {"target_type": "risk_flag", "target_name": "is_occupied"},
        {"target_type": "risk_flag", "target_name": "has_long_lease"},
    ]
    assert result["changed_keys"] == [
        "risk_factor_overrides.is_occupied",
        "risk_factor_overrides.has_long_lease",
    ]
    assert result["merged_config"]["risk_factor_overrides"]["is_occupied"] == 0.5
    assert result["merged_config"]["risk_factor_overrides"]["has_long_lease"] == 0.7
    assert result["merged_config"]["risk_factor_overrides"]["property_fee_owed"] == 0.82


def test_resolve_command_chain_artifacts_keeps_playbook_metadata_for_steps_without_artifacts(tmp_path: Path):
    command_chain = [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
                "artifact_kind": "config",
                "artifact_owner": "apply_avm_calibration_patch",
                "artifact": "datas/avm/config.json",
                "artifact_state": "missing",
                "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
                "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
                "artifact_check_timing": "pre_step",
            "artifact_freshness": "pending_write",
            "artifact_freshness_reason": "waiting_for_bundle_write",
            "artifact_next_expected_transition": "pending_write->current",
            "artifact_ready_for_step": True,
            "step_ready_summary": "ready_now",
            "step_ready_recommended_action": "proceed_now",
            "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "step_ready_follow_up_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "step_ready_follow_up_expected_signal": "config_patch_applied",
            "step_ready_follow_up_success_criterion": "ready_for_eval_rerun",
            "step_ready_terminal_outcome": "ready_for_eval_rerun",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "config_not_written_yet",
        }
    ]


def test_resolve_command_chain_artifacts_backfills_missing_metadata_for_known_steps_with_explicit_artifact(tmp_path: Path):
    eval_report_path = tmp_path / "avm" / "eval_report.json"
    _write_json(eval_report_path, {"metrics": {}})

    command_chain = [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "stale",
            "artifact_resolved_path": str(eval_report_path),
            "artifact_check_command": f'Get-Content "{eval_report_path}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "stale",
            "artifact_freshness_reason": "pre_bundle_eval_report",
            "artifact_next_expected_transition": "stale->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_eval_rerun",
            "step_ready_recommended_action": "rerun_evaluate",
            "step_ready_action_command": "python tools/evaluate_avm.py",
            "step_ready_follow_up_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_expected_signal": "release_gate_refreshed",
            "step_ready_follow_up_success_criterion": "ready_for_operator_review",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "evaluate_then_gate",
            "step_ready_priority": "next",
            "step_ready_badge": "next-evaluate-then-gate",
            "step_ready_group_id": "evaluate-and-gate",
            "step_ready_group_label": "Evaluate and gate",
            "step_ready_sort_key": "2-evaluate-then-gate",
            "step_ready_display_order": 2,
            "step_ready_lane": "upcoming",
            "step_ready_lane_label": "Upcoming",
            "artifact_state_reason": "pre_bundle_eval_report",
        }
    ]


def test_known_step_contract_defaults_cover_verify_step():
    assert _known_step_contract_defaults("verify") == {
        "default_command": "python tools/evaluate_avm.py",
        "default_follow_up_kind": "gate",
        "runnable_without_existing_artifact": "false",
        "stage_span": "evaluate_then_gate",
        "expected_signal": "eval_report_refreshed",
        "success_criterion": "ready_for_gate_rerun",
        "surface": "local_cli",
        "artifact_kind": "report",
        "artifact_owner": "evaluate_avm",
        "artifact": "datas/avm/eval_report.json",
        "artifact_check_timing": "post_step",
    }


def test_resolve_command_chain_artifacts_backfills_missing_command_for_known_steps_with_default_command(tmp_path: Path):
    eval_report_path = tmp_path / "avm" / "eval_report.json"
    _write_json(eval_report_path, {"metrics": {}})

    command_chain = [
        {
            "kind": "verify",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "stale",
            "artifact_resolved_path": str(eval_report_path),
            "artifact_check_command": f'Get-Content "{eval_report_path}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "stale",
            "artifact_freshness_reason": "pre_bundle_eval_report",
            "artifact_next_expected_transition": "stale->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_eval_rerun",
            "step_ready_recommended_action": "rerun_evaluate",
            "step_ready_action_command": "python tools/evaluate_avm.py",
            "step_ready_follow_up_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_expected_signal": "release_gate_refreshed",
            "step_ready_follow_up_success_criterion": "ready_for_operator_review",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "evaluate_then_gate",
            "step_ready_priority": "next",
            "step_ready_badge": "next-evaluate-then-gate",
            "step_ready_group_id": "evaluate-and-gate",
            "step_ready_group_label": "Evaluate and gate",
            "step_ready_sort_key": "2-evaluate-then-gate",
            "step_ready_display_order": 2,
            "step_ready_lane": "upcoming",
            "step_ready_lane_label": "Upcoming",
            "artifact_state_reason": "pre_bundle_eval_report",
        }
    ]


def test_resolve_command_chain_artifacts_treats_missing_config_artifact_as_runnable_for_preview(tmp_path: Path):
    command_chain = [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "missing",
            "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
            "artifact_check_timing": "pre_step",
            "artifact_freshness": "pending_write",
            "artifact_freshness_reason": "waiting_for_bundle_write",
            "artifact_next_expected_transition": "pending_write->current",
            "artifact_ready_for_step": True,
            "step_ready_summary": "ready_now",
            "step_ready_recommended_action": "proceed_now",
            "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "step_ready_follow_up_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "step_ready_follow_up_expected_signal": "config_patch_applied",
            "step_ready_follow_up_success_criterion": "ready_for_eval_rerun",
            "step_ready_terminal_outcome": "ready_for_eval_rerun",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "config_not_written_yet",
        }
    ]


def test_resolve_command_chain_artifacts_does_not_mark_preview_ready_when_command_is_missing(tmp_path: Path):
    command_chain = [
        {
            "kind": "preview",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "preview",
            "command": "",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "missing",
            "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
            "artifact_check_timing": "pre_step",
            "artifact_freshness": "pending_write",
            "artifact_freshness_reason": "waiting_for_bundle_write",
            "artifact_next_expected_transition": "pending_write->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "unknown",
            "step_ready_recommended_action": "inspect_artifact_state",
            "step_ready_action_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_write_decision",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "config_not_written_yet",
        }
    ]


def test_resolve_command_chain_artifacts_does_not_advertise_follow_up_for_non_runnable_write(tmp_path: Path):
    command_chain = [
        {
            "kind": "write",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "write",
            "command": "",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "missing",
            "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "pending_write",
            "artifact_freshness_reason": "waiting_for_bundle_write",
            "artifact_next_expected_transition": "pending_write->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "unknown",
            "step_ready_recommended_action": "inspect_artifact_state",
            "step_ready_action_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_eval_rerun",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "config_not_written_yet",
        }
    ]


def test_resolve_command_chain_artifacts_inferred_missing_verify_artifact_stays_blocked(tmp_path: Path):
    command_chain = [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "not_ready_yet",
            "artifact_resolved_path": str(tmp_path / "avm" / "eval_report.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "eval_report.json"}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "pending_rerun",
            "artifact_freshness_reason": "waiting_for_eval_rerun",
            "artifact_next_expected_transition": "pending_rerun->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_eval_rerun",
            "step_ready_recommended_action": "rerun_evaluate",
            "step_ready_action_command": "python tools/evaluate_avm.py",
            "step_ready_follow_up_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_expected_signal": "release_gate_refreshed",
            "step_ready_follow_up_success_criterion": "ready_for_operator_review",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "evaluate_then_gate",
            "step_ready_priority": "next",
            "step_ready_badge": "next-evaluate-then-gate",
            "step_ready_group_id": "evaluate-and-gate",
            "step_ready_group_label": "Evaluate and gate",
            "step_ready_sort_key": "2-evaluate-then-gate",
            "step_ready_display_order": 2,
            "step_ready_lane": "upcoming",
            "step_ready_lane_label": "Upcoming",
            "artifact_state_reason": "eval_not_rerun_yet",
        }
    ]


def test_resolve_command_chain_artifacts_explicit_missing_verify_artifact_stays_blocked(tmp_path: Path):
    command_chain = [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "not_ready_yet",
            "artifact_resolved_path": str(tmp_path / "avm" / "eval_report.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "eval_report.json"}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "pending_rerun",
            "artifact_freshness_reason": "waiting_for_eval_rerun",
            "artifact_next_expected_transition": "pending_rerun->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_eval_rerun",
            "step_ready_recommended_action": "rerun_evaluate",
            "step_ready_action_command": "python tools/evaluate_avm.py",
            "step_ready_follow_up_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_expected_signal": "release_gate_refreshed",
            "step_ready_follow_up_success_criterion": "ready_for_operator_review",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "evaluate_then_gate",
            "step_ready_priority": "next",
            "step_ready_badge": "next-evaluate-then-gate",
            "step_ready_group_id": "evaluate-and-gate",
            "step_ready_group_label": "Evaluate and gate",
            "step_ready_sort_key": "2-evaluate-then-gate",
            "step_ready_display_order": 2,
            "step_ready_lane": "upcoming",
            "step_ready_lane_label": "Upcoming",
            "artifact_state_reason": "eval_not_rerun_yet",
        }
    ]


def test_resolve_command_chain_artifacts_inferred_missing_gate_artifact_stays_blocked(tmp_path: Path):
    command_chain = [
        {
            "kind": "gate",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "not_ready_yet",
            "artifact_resolved_path": str(tmp_path / "avm" / "release_gate.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "release_gate.json"}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "pending_rerun",
            "artifact_freshness_reason": "waiting_for_gate_rerun",
            "artifact_next_expected_transition": "pending_rerun->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_gate_rerun",
            "step_ready_recommended_action": "rerun_release_gate",
            "step_ready_action_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "gate_only",
            "step_ready_priority": "later",
            "step_ready_badge": "later-gate-only",
            "step_ready_group_id": "gate-rerun-only",
            "step_ready_group_label": "Gate rerun only",
            "step_ready_sort_key": "3-gate-only",
            "step_ready_display_order": 3,
            "step_ready_lane": "deferred",
            "step_ready_lane_label": "Deferred",
            "artifact_state_reason": "gate_not_rerun_yet",
        }
    ]


def test_resolve_command_chain_artifacts_explicit_missing_gate_artifact_stays_blocked(tmp_path: Path):
    command_chain = [
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "not_ready_yet",
            "artifact_resolved_path": str(tmp_path / "avm" / "release_gate.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "release_gate.json"}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "pending_rerun",
            "artifact_freshness_reason": "waiting_for_gate_rerun",
            "artifact_next_expected_transition": "pending_rerun->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_gate_rerun",
            "step_ready_recommended_action": "rerun_release_gate",
            "step_ready_action_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "gate_only",
            "step_ready_priority": "later",
            "step_ready_badge": "later-gate-only",
            "step_ready_group_id": "gate-rerun-only",
            "step_ready_group_label": "Gate rerun only",
            "step_ready_sort_key": "3-gate-only",
            "step_ready_display_order": 3,
            "step_ready_lane": "deferred",
            "step_ready_lane_label": "Deferred",
            "artifact_state_reason": "gate_not_rerun_yet",
        }
    ]


def test_resolve_command_chain_artifacts_existing_gate_artifact_stays_stale(tmp_path: Path):
    gate_report_path = tmp_path / "avm" / "release_gate.json"
    _write_json(gate_report_path, {"evaluation": {}})

    command_chain = [
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "stale",
            "artifact_resolved_path": str(gate_report_path),
            "artifact_check_command": f'Get-Content "{gate_report_path}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "stale",
            "artifact_freshness_reason": "pre_bundle_gate_report",
            "artifact_next_expected_transition": "stale->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_gate_rerun",
            "step_ready_recommended_action": "rerun_release_gate",
            "step_ready_action_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "gate_only",
            "step_ready_priority": "later",
            "step_ready_badge": "later-gate-only",
            "step_ready_group_id": "gate-rerun-only",
            "step_ready_group_label": "Gate rerun only",
            "step_ready_sort_key": "3-gate-only",
            "step_ready_display_order": 3,
            "step_ready_lane": "deferred",
            "step_ready_lane_label": "Deferred",
            "artifact_state_reason": "pre_bundle_gate_report",
        }
    ]


def test_resolve_command_chain_artifacts_backfills_missing_write_command_from_preview(tmp_path: Path):
    command_chain = [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "write",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved[1] == {
        "kind": "write",
        "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "expected_signal": "config_patch_applied",
        "success_criterion": "ready_for_eval_rerun",
        "surface": "local_cli",
        "artifact_kind": "config",
        "artifact_owner": "apply_avm_calibration_patch",
        "artifact": "datas/avm/config.json",
        "artifact_state": "missing",
        "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
        "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
        "artifact_check_timing": "post_step",
        "artifact_freshness": "pending_write",
        "artifact_freshness_reason": "waiting_for_bundle_write",
        "artifact_next_expected_transition": "pending_write->current",
        "artifact_ready_for_step": True,
        "step_ready_summary": "ready_now",
        "step_ready_recommended_action": "proceed_now",
        "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "step_ready_follow_up_command": "python tools/evaluate_avm.py",
        "step_ready_follow_up_expected_signal": "eval_report_refreshed",
        "step_ready_follow_up_success_criterion": "ready_for_gate_rerun",
        "step_ready_terminal_outcome": "ready_for_gate_rerun",
        "step_ready_stage_span": "write_then_evaluate",
        "step_ready_priority": "now",
        "step_ready_badge": "now-write-then-evaluate",
        "step_ready_group_id": "bundle-write-and-evaluate",
        "step_ready_group_label": "Bundle write and evaluate",
        "step_ready_sort_key": "1-write-then-evaluate",
        "step_ready_display_order": 1,
        "step_ready_lane": "current",
        "step_ready_lane_label": "Current",
        "artifact_state_reason": "config_not_written_yet",
    }


def test_resolve_command_chain_artifacts_backfills_missing_preview_command_from_write(tmp_path: Path):
    command_chain = [
        {
            "kind": "preview",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved[0] == {
        "kind": "preview",
        "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        "expected_signal": "inspect_changed_keys_and_risk_summary",
        "success_criterion": "ready_for_write_decision",
        "surface": "local_cli",
        "artifact_kind": "config",
        "artifact_owner": "apply_avm_calibration_patch",
        "artifact": "datas/avm/config.json",
        "artifact_state": "missing",
        "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
        "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
        "artifact_check_timing": "pre_step",
        "artifact_freshness": "pending_write",
        "artifact_freshness_reason": "waiting_for_bundle_write",
        "artifact_next_expected_transition": "pending_write->current",
        "artifact_ready_for_step": True,
        "step_ready_summary": "ready_now",
        "step_ready_recommended_action": "proceed_now",
        "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        "step_ready_follow_up_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "step_ready_follow_up_expected_signal": "config_patch_applied",
        "step_ready_follow_up_success_criterion": "ready_for_eval_rerun",
        "step_ready_terminal_outcome": "ready_for_eval_rerun",
        "step_ready_stage_span": "write_then_evaluate",
        "step_ready_priority": "now",
        "step_ready_badge": "now-write-then-evaluate",
        "step_ready_group_id": "bundle-write-and-evaluate",
        "step_ready_group_label": "Bundle write and evaluate",
        "step_ready_sort_key": "1-write-then-evaluate",
        "step_ready_display_order": 1,
        "step_ready_lane": "current",
        "step_ready_lane_label": "Current",
        "artifact_state_reason": "config_not_written_yet",
    }


def test_resolve_command_chain_artifacts_normalizes_preview_follow_up_when_write_item_is_malformed(tmp_path: Path):
    command_chain = [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved[0]["step_ready_follow_up_command"] == (
        "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write"
    )


def test_resolve_command_chain_artifacts_current_config_branch_keeps_preview_write_flow(tmp_path: Path):
    config_path = tmp_path / "avm" / "config.json"
    _write_json(config_path, {"radius_km": 3.0})

    command_chain = [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "write",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved[0] == {
        "kind": "preview",
        "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        "expected_signal": "inspect_changed_keys_and_risk_summary",
        "success_criterion": "ready_for_write_decision",
        "surface": "local_cli",
        "artifact_kind": "config",
        "artifact_owner": "apply_avm_calibration_patch",
        "artifact": "datas/avm/config.json",
        "artifact_state": "present",
        "artifact_resolved_path": str(config_path),
        "artifact_check_command": f'Get-Content "{config_path}"',
        "artifact_check_timing": "pre_step",
        "artifact_freshness": "current",
        "artifact_freshness_reason": "artifact_current",
        "artifact_next_expected_transition": "current->current",
        "artifact_ready_for_step": True,
        "step_ready_summary": "ready_now",
        "step_ready_recommended_action": "proceed_now",
        "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        "step_ready_follow_up_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "step_ready_follow_up_expected_signal": "config_patch_applied",
        "step_ready_follow_up_success_criterion": "ready_for_eval_rerun",
        "step_ready_terminal_outcome": "ready_for_eval_rerun",
        "step_ready_stage_span": "write_then_evaluate",
        "step_ready_priority": "now",
        "step_ready_badge": "now-write-then-evaluate",
        "step_ready_group_id": "bundle-write-and-evaluate",
        "step_ready_group_label": "Bundle write and evaluate",
        "step_ready_sort_key": "1-write-then-evaluate",
        "step_ready_display_order": 1,
        "step_ready_lane": "current",
        "step_ready_lane_label": "Current",
        "artifact_state_reason": "artifact_present",
    }
    assert resolved[1] == {
        "kind": "write",
        "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "expected_signal": "config_patch_applied",
        "success_criterion": "ready_for_eval_rerun",
        "surface": "local_cli",
        "artifact_kind": "config",
        "artifact_owner": "apply_avm_calibration_patch",
        "artifact": "datas/avm/config.json",
        "artifact_state": "present",
        "artifact_resolved_path": str(config_path),
        "artifact_check_command": f'Get-Content "{config_path}"',
        "artifact_check_timing": "post_step",
        "artifact_freshness": "current",
        "artifact_freshness_reason": "artifact_current",
        "artifact_next_expected_transition": "current->current",
        "artifact_ready_for_step": True,
        "step_ready_summary": "ready_now",
        "step_ready_recommended_action": "proceed_now",
        "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "step_ready_follow_up_command": "python tools/evaluate_avm.py",
        "step_ready_follow_up_expected_signal": "eval_report_refreshed",
        "step_ready_follow_up_success_criterion": "ready_for_gate_rerun",
        "step_ready_terminal_outcome": "ready_for_gate_rerun",
        "step_ready_stage_span": "write_then_evaluate",
        "step_ready_priority": "now",
        "step_ready_badge": "now-write-then-evaluate",
        "step_ready_group_id": "bundle-write-and-evaluate",
        "step_ready_group_label": "Bundle write and evaluate",
        "step_ready_sort_key": "1-write-then-evaluate",
        "step_ready_display_order": 1,
        "step_ready_lane": "current",
        "step_ready_lane_label": "Current",
        "artifact_state_reason": "artifact_present",
    }


def test_resolve_command_chain_artifacts_current_config_branch_normalizes_write_command(tmp_path: Path):
    config_path = tmp_path / "avm" / "config.json"
    _write_json(config_path, {"radius_km": 3.0})

    command_chain = [
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "present",
            "artifact_resolved_path": str(config_path),
            "artifact_check_command": f'Get-Content "{config_path}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "current",
            "artifact_freshness_reason": "artifact_current",
            "artifact_next_expected_transition": "current->current",
            "artifact_ready_for_step": True,
            "step_ready_summary": "ready_now",
            "step_ready_recommended_action": "proceed_now",
            "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "step_ready_follow_up_command": "python tools/evaluate_avm.py",
            "step_ready_follow_up_expected_signal": "eval_report_refreshed",
            "step_ready_follow_up_success_criterion": "ready_for_gate_rerun",
            "step_ready_terminal_outcome": "ready_for_gate_rerun",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "artifact_present",
        }
    ]


def test_resolve_command_chain_artifacts_current_config_branch_sanitizes_preview_command(tmp_path: Path):
    config_path = tmp_path / "avm" / "config.json"
    _write_json(config_path, {"radius_km": 3.0})

    command_chain = [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "present",
            "artifact_resolved_path": str(config_path),
            "artifact_check_command": f'Get-Content "{config_path}"',
            "artifact_check_timing": "pre_step",
            "artifact_freshness": "current",
            "artifact_freshness_reason": "artifact_current",
            "artifact_next_expected_transition": "current->current",
            "artifact_ready_for_step": True,
            "step_ready_summary": "ready_now",
            "step_ready_recommended_action": "proceed_now",
            "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "step_ready_follow_up_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "step_ready_follow_up_expected_signal": "config_patch_applied",
            "step_ready_follow_up_success_criterion": "ready_for_eval_rerun",
            "step_ready_terminal_outcome": "ready_for_eval_rerun",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "artifact_present",
        }
    ]


def test_resolve_command_chain_artifacts_current_config_branch_keeps_missing_preview_non_runnable(tmp_path: Path):
    config_path = tmp_path / "avm" / "config.json"
    _write_json(config_path, {"radius_km": 3.0})

    command_chain = [
        {
            "kind": "preview",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "preview",
            "command": "",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "present",
            "artifact_resolved_path": str(config_path),
            "artifact_check_command": f'Get-Content "{config_path}"',
            "artifact_check_timing": "pre_step",
            "artifact_freshness": "current",
            "artifact_freshness_reason": "artifact_current",
            "artifact_next_expected_transition": "current->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "unknown",
            "step_ready_recommended_action": "inspect_artifact_state",
            "step_ready_action_command": f'Get-Content "{config_path}"',
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_write_decision",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "artifact_present",
        }
    ]


def test_resolve_command_chain_artifacts_current_config_branch_keeps_missing_write_non_runnable(tmp_path: Path):
    config_path = tmp_path / "avm" / "config.json"
    _write_json(config_path, {"radius_km": 3.0})

    command_chain = [
        {
            "kind": "write",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "write",
            "command": "",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "present",
            "artifact_resolved_path": str(config_path),
            "artifact_check_command": f'Get-Content "{config_path}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "current",
            "artifact_freshness_reason": "artifact_current",
            "artifact_next_expected_transition": "current->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "unknown",
            "step_ready_recommended_action": "inspect_artifact_state",
            "step_ready_action_command": f'Get-Content "{config_path}"',
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_eval_rerun",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "artifact_present",
        }
    ]


def test_resolve_command_chain_artifacts_sanitizes_preview_command_with_write_flag(tmp_path: Path):
    command_chain = [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "missing",
            "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
            "artifact_check_timing": "pre_step",
            "artifact_freshness": "pending_write",
            "artifact_freshness_reason": "waiting_for_bundle_write",
            "artifact_next_expected_transition": "pending_write->current",
            "artifact_ready_for_step": True,
            "step_ready_summary": "ready_now",
            "step_ready_recommended_action": "proceed_now",
            "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "step_ready_follow_up_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "step_ready_follow_up_expected_signal": "config_patch_applied",
            "step_ready_follow_up_success_criterion": "ready_for_eval_rerun",
            "step_ready_terminal_outcome": "ready_for_eval_rerun",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "config_not_written_yet",
        }
    ]


def test_resolve_command_chain_artifacts_normalizes_write_command_with_missing_flag(tmp_path: Path):
    command_chain = [
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "missing",
            "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "pending_write",
            "artifact_freshness_reason": "waiting_for_bundle_write",
            "artifact_next_expected_transition": "pending_write->current",
            "artifact_ready_for_step": True,
            "step_ready_summary": "ready_now",
            "step_ready_recommended_action": "proceed_now",
            "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "step_ready_follow_up_command": "python tools/evaluate_avm.py",
            "step_ready_follow_up_expected_signal": "eval_report_refreshed",
            "step_ready_follow_up_success_criterion": "ready_for_gate_rerun",
            "step_ready_terminal_outcome": "ready_for_gate_rerun",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "config_not_written_yet",
        }
    ]


def test_resolve_command_chain_artifacts_does_not_infer_preview_from_malformed_write_command(tmp_path: Path):
    command_chain = [
        {
            "kind": "preview",
            "command": "",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved[0] == {
        "kind": "preview",
        "command": "",
        "expected_signal": "inspect_changed_keys_and_risk_summary",
        "success_criterion": "ready_for_write_decision",
        "surface": "local_cli",
        "artifact_kind": "config",
        "artifact_owner": "apply_avm_calibration_patch",
        "artifact": "datas/avm/config.json",
        "artifact_state": "missing",
        "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
        "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
        "artifact_check_timing": "pre_step",
        "artifact_freshness": "pending_write",
        "artifact_freshness_reason": "waiting_for_bundle_write",
        "artifact_next_expected_transition": "pending_write->current",
        "artifact_ready_for_step": False,
        "step_ready_summary": "unknown",
        "step_ready_recommended_action": "inspect_artifact_state",
        "step_ready_action_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
        "step_ready_follow_up_command": "",
        "step_ready_follow_up_expected_signal": "",
        "step_ready_follow_up_success_criterion": "",
        "step_ready_terminal_outcome": "ready_for_write_decision",
        "step_ready_stage_span": "write_then_evaluate",
        "step_ready_priority": "now",
        "step_ready_badge": "now-write-then-evaluate",
        "step_ready_group_id": "bundle-write-and-evaluate",
        "step_ready_group_label": "Bundle write and evaluate",
        "step_ready_sort_key": "1-write-then-evaluate",
        "step_ready_display_order": 1,
        "step_ready_lane": "current",
        "step_ready_lane_label": "Current",
        "artifact_state_reason": "config_not_written_yet",
    }


def test_resolve_command_chain_artifacts_inferred_missing_write_artifact_uses_pending_write_semantics(tmp_path: Path):
    command_chain = [
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "missing",
            "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "pending_write",
            "artifact_freshness_reason": "waiting_for_bundle_write",
            "artifact_next_expected_transition": "pending_write->current",
            "artifact_ready_for_step": True,
            "step_ready_summary": "ready_now",
            "step_ready_recommended_action": "proceed_now",
            "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "step_ready_follow_up_command": "python tools/evaluate_avm.py",
            "step_ready_follow_up_expected_signal": "eval_report_refreshed",
            "step_ready_follow_up_success_criterion": "ready_for_gate_rerun",
            "step_ready_terminal_outcome": "ready_for_gate_rerun",
            "step_ready_stage_span": "write_then_evaluate",
            "step_ready_priority": "now",
            "step_ready_badge": "now-write-then-evaluate",
            "step_ready_group_id": "bundle-write-and-evaluate",
            "step_ready_group_label": "Bundle write and evaluate",
            "step_ready_sort_key": "1-write-then-evaluate",
            "step_ready_display_order": 1,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "config_not_written_yet",
        }
    ]


def test_resolve_command_chain_artifacts_backfills_missing_step_contract_metadata_for_known_steps(tmp_path: Path):
    eval_report_path = tmp_path / "avm" / "eval_report.json"
    _write_json(eval_report_path, {"metrics": {}})

    command_chain = [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "",
            "success_criterion": "",
            "surface": "",
            "artifact_kind": "",
            "artifact_owner": "",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        }
    ]

    resolved = resolve_command_chain_artifacts(command_chain, tmp_path)

    assert resolved == [
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "stale",
            "artifact_resolved_path": str(eval_report_path),
            "artifact_check_command": f'Get-Content "{eval_report_path}"',
            "artifact_check_timing": "post_step",
            "artifact_freshness": "stale",
            "artifact_freshness_reason": "pre_bundle_eval_report",
            "artifact_next_expected_transition": "stale->current",
            "artifact_ready_for_step": False,
            "step_ready_summary": "blocked_by_eval_rerun",
            "step_ready_recommended_action": "rerun_evaluate",
            "step_ready_action_command": "python tools/evaluate_avm.py",
            "step_ready_follow_up_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "step_ready_follow_up_expected_signal": "release_gate_refreshed",
            "step_ready_follow_up_success_criterion": "ready_for_operator_review",
            "step_ready_terminal_outcome": "ready_for_operator_review",
            "step_ready_stage_span": "evaluate_then_gate",
            "step_ready_priority": "next",
            "step_ready_badge": "next-evaluate-then-gate",
            "step_ready_group_id": "evaluate-and-gate",
            "step_ready_group_label": "Evaluate and gate",
            "step_ready_sort_key": "2-evaluate-then-gate",
            "step_ready_display_order": 2,
            "step_ready_lane": "upcoming",
            "step_ready_lane_label": "Upcoming",
            "artifact_state_reason": "pre_bundle_eval_report",
        }
    ]


def test_stage_semantics_defaults_cover_evaluate_then_gate():
    assert _stage_semantics_defaults("evaluate_then_gate") == {
        "priority": "next",
        "group_id": "evaluate-and-gate",
        "group_label": "Evaluate and gate",
        "badge": "next-evaluate-then-gate",
        "sort_key": "2-evaluate-then-gate",
        "display_order": 2,
        "lane": "upcoming",
        "lane_label": "Upcoming",
    }


def test_stage_semantics_defaults_cover_preview_then_split():
    assert _stage_semantics_defaults("preview_then_split") == {
        "priority": "now",
        "group_id": "preview-and-split",
        "group_label": "Preview and split",
        "badge": "now-preview-then-split",
        "sort_key": "0-preview-then-split",
        "display_order": 0,
        "lane": "current",
        "lane_label": "Current",
    }


def test_summarize_bundle_command_summary_backfills_verify_and_gate_defaults_when_recommended_bundle_present():
    preview_command, write_command, verify_command, gate_command = summarize_bundle_command_summary(
        {
            "recommended_bundle": {
                "bundle_id": "temporal-only",
                "target_types": ["temporal"],
                "target_names": ["time_decay"],
            }
        }
    )

    assert preview_command == "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay"
    assert write_command == "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write"
    assert verify_command == "python tools/evaluate_avm.py"
    assert gate_command == "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report"


def test_summarize_patch_command_chain_dedupes_verify_step_in_safe_write_flow():
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --write",
        next_action_command_kind="write",
        follow_up_command="python tools/evaluate_avm.py",
        follow_up_command_kind="verify",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert [item["kind"] for item in chain] == ["write", "verify", "gate"]


def test_summarize_patch_follow_up_command_sanitizes_malformed_preview_before_synthesizing_write():
    follow_up = summarize_patch_follow_up_command(
        {"next_action": "preview_only_first"},
        preview_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        write_command="",
        verify_command="python tools/evaluate_avm.py",
    )

    assert follow_up == {
        "follow_up_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "follow_up_command_kind": "write",
    }


def test_summarize_patch_follow_up_command_returns_none_when_verify_command_missing_for_safe_write_flow():
    follow_up = summarize_patch_follow_up_command(
        {"next_action": "safe_to_write_then_verify"},
        preview_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        write_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        verify_command="",
    )

    assert follow_up == {
        "follow_up_command": "",
        "follow_up_command_kind": "none",
    }


def test_summarize_patch_follow_up_command_normalizes_malformed_explicit_write_command():
    follow_up = summarize_patch_follow_up_command(
        {"next_action": "preview_only_first"},
        preview_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        write_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        verify_command="python tools/evaluate_avm.py",
    )

    assert follow_up == {
        "follow_up_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "follow_up_command_kind": "write",
    }


def test_summarize_patch_next_action_command_sanitizes_malformed_preview_command():
    next_action_command = summarize_patch_next_action_command(
        {"next_action": "preview_only_first"},
        preview_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        write_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
    )

    assert next_action_command == {
        "next_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        "next_action_command_kind": "preview",
    }


def test_summarize_patch_next_action_command_normalizes_malformed_write_command():
    next_action_command = summarize_patch_next_action_command(
        {"next_action": "safe_to_write_then_verify"},
        preview_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        write_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
    )

    assert next_action_command == {
        "next_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "next_action_command_kind": "write",
    }


def test_summarize_patch_next_action_command_backfills_preview_from_write_when_preview_missing():
    next_action_command = summarize_patch_next_action_command(
        {"next_action": "preview_only_first"},
        preview_command="",
        write_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
    )

    assert next_action_command == {
        "next_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        "next_action_command_kind": "preview",
    }


def test_summarize_patch_next_action_command_backfills_write_from_preview_when_write_missing():
    next_action_command = summarize_patch_next_action_command(
        {"next_action": "safe_to_write_then_verify"},
        preview_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        write_command="",
    )

    assert next_action_command == {
        "next_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        "next_action_command_kind": "write",
    }


def test_summarize_patch_next_action_command_does_not_infer_preview_from_malformed_write_alone():
    next_action_command = summarize_patch_next_action_command(
        {"next_action": "preview_only_first"},
        preview_command="",
        write_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
    )

    assert next_action_command == {
        "next_action_command": "",
        "next_action_command_kind": "preview",
    }


def test_summarize_patch_next_action_uses_changed_keys_when_count_missing():
    preview_payload = {
        "changed_keys": ["weighting.time_decay"],
    }

    risk_summary = summarize_patch_risk(preview_payload)
    next_action = summarize_patch_next_action(risk_summary, preview_payload)

    assert risk_summary == {
        "risk_level": "low",
        "risk_reasons": [],
    }
    assert next_action == {
        "next_action": "safe_to_write_then_verify",
        "next_action_reasons": ["low_risk_bundle"],
    }


def test_summarize_patch_command_chain_stops_at_preview_for_high_risk_split_flow():
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --target-type risk_flag",
        next_action_command_kind="preview",
        follow_up_command="",
        follow_up_command_kind="none",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert chain == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --target-type risk_flag",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]


def test_summarize_patch_command_chain_does_not_append_gate_when_verify_is_missing_in_safe_write_flow():
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        next_action_command_kind="write",
        follow_up_command="",
        follow_up_command_kind="none",
        verify_command="",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert chain == [
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        }
    ]


def test_apply_command_chain_next_action_policy_relabels_high_risk_preview_stage(tmp_path: Path):
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --target-type risk_flag",
        next_action_command_kind="preview",
        follow_up_command="",
        follow_up_command_kind="none",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )
    resolved = resolve_command_chain_artifacts(chain, tmp_path)

    adjusted = apply_command_chain_next_action_policy(
        resolved,
        next_action="split_bundle_or_single_target_first",
    )

    assert adjusted == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --target-type risk_flag",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "missing",
            "artifact_resolved_path": str(tmp_path / "avm" / "config.json"),
            "artifact_check_command": f'Get-Content "{tmp_path / "avm" / "config.json"}"',
            "artifact_check_timing": "pre_step",
            "artifact_freshness": "pending_write",
            "artifact_freshness_reason": "waiting_for_bundle_write",
            "artifact_next_expected_transition": "pending_write->current",
            "artifact_ready_for_step": True,
            "step_ready_summary": "ready_now",
            "step_ready_recommended_action": "proceed_now",
            "step_ready_action_command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --target-type risk_flag",
            "step_ready_follow_up_command": "",
            "step_ready_follow_up_expected_signal": "",
            "step_ready_follow_up_success_criterion": "",
            "step_ready_terminal_outcome": "ready_for_write_decision",
            "step_ready_stage_span": "preview_then_split",
            "step_ready_priority": "now",
            "step_ready_badge": "now-preview-then-split",
            "step_ready_group_id": "preview-and-split",
            "step_ready_group_label": "Preview and split",
            "step_ready_sort_key": "0-preview-then-split",
            "step_ready_display_order": 0,
            "step_ready_lane": "current",
            "step_ready_lane_label": "Current",
            "artifact_state_reason": "config_not_written_yet",
        }
    ]


def test_summarize_patch_command_chain_sanitizes_preview_command_with_write_flag():
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        next_action_command_kind="preview",
        follow_up_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        follow_up_command_kind="write",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert chain == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "unknown",
        },
    ]


def test_summarize_patch_command_chain_normalizes_write_command_with_missing_flag():
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        next_action_command_kind="write",
        follow_up_command="python tools/evaluate_avm.py",
        follow_up_command_kind="verify",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert chain == [
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "unknown",
        },
    ]


def test_summarize_patch_command_chain_backfills_write_from_preview_when_write_kind_is_present():
    chain = summarize_patch_command_chain(
        next_action_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        next_action_command_kind="preview",
        follow_up_command="",
        follow_up_command_kind="write",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert chain == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "unknown",
        },
    ]


def test_summarize_patch_command_chain_backfills_preview_from_write_when_preview_kind_is_present():
    chain = summarize_patch_command_chain(
        next_action_command="",
        next_action_command_kind="preview",
        follow_up_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        follow_up_command_kind="write",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert chain == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "unknown",
        },
    ]


def test_summarize_patch_command_chain_backfills_preview_from_malformed_write_when_preview_kind_is_present():
    chain = summarize_patch_command_chain(
        next_action_command="",
        next_action_command_kind="preview",
        follow_up_command="python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        follow_up_command_kind="write",
        verify_command="python tools/evaluate_avm.py",
        gate_command="python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
    )

    assert chain == [
        {
            "kind": "preview",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
            "expected_signal": "inspect_changed_keys_and_risk_summary",
            "success_criterion": "ready_for_write_decision",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "write",
            "command": "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
            "expected_signal": "config_patch_applied",
            "success_criterion": "ready_for_eval_rerun",
            "surface": "local_cli",
            "artifact_kind": "config",
            "artifact_owner": "apply_avm_calibration_patch",
            "artifact": "datas/avm/config.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "verify",
            "command": "python tools/evaluate_avm.py",
            "expected_signal": "eval_report_refreshed",
            "success_criterion": "ready_for_gate_rerun",
            "surface": "local_cli",
            "artifact_kind": "report",
            "artifact_owner": "evaluate_avm",
            "artifact": "datas/avm/eval_report.json",
            "artifact_state": "unknown",
        },
        {
            "kind": "gate",
            "command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
            "expected_signal": "release_gate_refreshed",
            "success_criterion": "ready_for_operator_review",
            "surface": "local_cli",
            "artifact_kind": "gate",
            "artifact_owner": "avm_release_gate",
            "artifact": "datas/avm/release_gate.json",
            "artifact_state": "unknown",
        },
    ]
