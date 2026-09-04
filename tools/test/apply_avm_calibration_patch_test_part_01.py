from tools.test.apply_avm_calibration_patch_test_context import *  # noqa: F401,F403


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
