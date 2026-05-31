import json
from pathlib import Path

from src.avm_config import (
    AVM_CONFIG_MANAGER,
    AvmConfigManager,
    DEFAULT_AVM_CONFIG,
    get_effective_alert_threshold,
    get_effective_radius_km,
    get_effective_risk_discount_factor,
    get_effective_weighting,
)


def test_avm_config_manager_load_on_startup_falls_back_for_non_object_json(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps([], ensure_ascii=False), encoding="utf-8")

    manager = AvmConfigManager(str(config_path))
    manager.load_on_startup()

    assert manager.get_config() == DEFAULT_AVM_CONFIG
    assert manager._last_mtime is None


def test_avm_config_manager_hot_reload_falls_back_for_malformed_json(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "radius_km": 3.0,
                "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                "risk_discount_factor": 0.9,
                "alert_threshold": 0.25,
                "risk_factor_overrides": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    manager = AvmConfigManager(str(config_path))
    manager.load_on_startup()
    assert manager.get_config()["weighting"]["time_decay"] == 0.85

    config_path.write_text("{", encoding="utf-8")

    result = manager.hot_reload()

    assert result is False
    assert manager.get_config() == DEFAULT_AVM_CONFIG
    assert manager._last_mtime == config_path.stat().st_mtime


def test_avm_config_manager_load_on_startup_falls_back_for_invalid_object_payload(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "radius_km": 3.0,
                "weighting": [],
                "risk_discount_factor": 0.9,
                "alert_threshold": 0.25,
                "risk_factor_overrides": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    manager = AvmConfigManager(str(config_path))
    manager.load_on_startup()

    assert manager.get_config() == DEFAULT_AVM_CONFIG
    assert manager._last_mtime is None


def test_avm_config_manager_hot_reload_falls_back_for_invalid_object_payload(tmp_path: Path):
    config_path = tmp_path / "datas" / "avm" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "radius_km": 3.0,
                "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                "risk_discount_factor": 0.9,
                "alert_threshold": 0.25,
                "risk_factor_overrides": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    manager = AvmConfigManager(str(config_path))
    manager.load_on_startup()
    assert manager.get_config()["radius_km"] == 3.0

    config_path.write_text(
        json.dumps(
            {
                "radius_km": -1,
                "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                "risk_discount_factor": 0.9,
                "alert_threshold": 0.25,
                "risk_factor_overrides": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = manager.hot_reload()

    assert result is False
    assert manager.get_config() == DEFAULT_AVM_CONFIG
    assert manager._last_mtime == config_path.stat().st_mtime


def test_get_effective_weighting_coerces_invalid_values_and_clamps_time_decay(monkeypatch):
    monkeypatch.setattr(
        AVM_CONFIG_MANAGER,
        "get_config",
        lambda: {
            "weighting": {
                "distance_power": -5,
                "time_decay": 1.7,
                "community_boost": "bad",
            }
        },
    )

    weighting = get_effective_weighting()

    assert weighting["distance_power"] == DEFAULT_AVM_CONFIG["weighting"]["distance_power"]
    assert weighting["time_decay"] == 1.0
    assert weighting["community_boost"] == DEFAULT_AVM_CONFIG["weighting"]["community_boost"]


def test_get_effective_alert_threshold_and_risk_discount_allow_zero(monkeypatch):
    monkeypatch.setattr(
        AVM_CONFIG_MANAGER,
        "get_config",
        lambda: {
            "alert_threshold": 0,
            "risk_discount_factor": 0,
        },
    )

    assert get_effective_alert_threshold(0.25) == 0.0
    assert get_effective_risk_discount_factor(0.9) == 0.0


def test_get_effective_radius_km_rejects_nonpositive_values(monkeypatch):
    monkeypatch.setattr(
        AVM_CONFIG_MANAGER,
        "get_config",
        lambda: {
            "radius_km": 0,
        },
    )

    assert get_effective_radius_km(4.2) == 4.2


def test_get_effective_alert_threshold_and_risk_discount_reject_negative_values(monkeypatch):
    monkeypatch.setattr(
        AVM_CONFIG_MANAGER,
        "get_config",
        lambda: {
            "alert_threshold": -1,
            "risk_discount_factor": -0.1,
        },
    )

    assert get_effective_alert_threshold(0.25) == 0.25
    assert get_effective_risk_discount_factor(0.9) == 0.9


def test_get_effective_getters_fall_back_when_manager_read_fails(monkeypatch):
    def _boom():
        raise RuntimeError("broken manager")

    monkeypatch.setattr(AVM_CONFIG_MANAGER, "get_config", _boom)

    assert get_effective_radius_km(4.2) == 4.2
    assert get_effective_alert_threshold(0.18) == 0.18
    assert get_effective_risk_discount_factor(0.77) == 0.77
    assert get_effective_weighting({"distance_power": 1.7, "time_decay": 0.6, "community_boost": 2.2}) == {
        "distance_power": 1.7,
        "time_decay": 0.6,
        "community_boost": 2.2,
    }


def test_get_effective_weighting_respects_partial_runtime_override_and_default_overrides(monkeypatch):
    monkeypatch.setattr(
        AVM_CONFIG_MANAGER,
        "get_config",
        lambda: {
            "weighting": {
                "distance_power": 1.6,
            }
        },
    )

    weighting = get_effective_weighting(
        {
            "distance_power": 1.4,
            "time_decay": 0.6,
            "community_boost": 2.2,
        }
    )

    assert weighting == {
        "distance_power": 1.6,
        "time_decay": 0.6,
        "community_boost": 2.2,
    }
