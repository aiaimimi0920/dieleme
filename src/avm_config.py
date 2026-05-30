import copy
import json
import os
import threading
import time

DEFAULT_AVM_CONFIG = {
    "radius_km": 3.0,
    "weighting": {
        "distance_power": 2.0,
        "time_decay": 0.85,
        "community_boost": 1.3,
    },
    "risk_discount_factor": 0.9,
    "alert_threshold": 0.25,
    "risk_factor_overrides": {},
}


def _coerce_positive_number(value, fallback):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if numeric <= 0:
        return float(fallback)
    return float(numeric)


def _coerce_nonnegative_number(value, fallback):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if numeric < 0:
        return float(fallback)
    return float(numeric)


def _coerce_time_decay(value, fallback):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(fallback)
    if numeric < 0:
        numeric = float(fallback)
    return max(0.0, min(1.0, float(numeric)))


class AvmConfigManager:
    def __init__(self, config_path, defaults=None):
        self.config_path = config_path
        self.defaults = copy.deepcopy(defaults or DEFAULT_AVM_CONFIG)
        self._config = copy.deepcopy(self.defaults)
        self._lock = threading.Lock()
        self._last_mtime = None
        self._watcher_started = False

    def _validate_config(self, config):
        required_keys = ["radius_km", "weighting", "risk_discount_factor", "alert_threshold"]
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Missing required key: {key}")

        if not isinstance(config["radius_km"], (int, float)) or config["radius_km"] <= 0:
            raise ValueError("radius_km must be a positive number")

        weighting = config["weighting"]
        if not isinstance(weighting, dict):
            raise ValueError("weighting must be an object")

        for wkey in ["distance_power", "time_decay", "community_boost"]:
            if wkey not in weighting:
                raise ValueError(f"Missing weighting key: {wkey}")
            if not isinstance(weighting[wkey], (int, float)):
                raise ValueError(f"weighting.{wkey} must be numeric")

        if not isinstance(config["risk_discount_factor"], (int, float)):
            raise ValueError("risk_discount_factor must be numeric")

        if not isinstance(config["alert_threshold"], (int, float)) or config["alert_threshold"] < 0:
            raise ValueError("alert_threshold must be a non-negative number")

        overrides = config.get("risk_factor_overrides", {})
        if not isinstance(overrides, dict):
            raise ValueError("risk_factor_overrides must be an object")
        for key, value in overrides.items():
            if not isinstance(key, str):
                raise ValueError("risk_factor_overrides keys must be strings")
            if not isinstance(value, (int, float)) or value <= 0:
                raise ValueError("risk_factor_overrides values must be positive numbers")

    def _read_and_validate(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        self._validate_config(config)
        return config

    def load_on_startup(self):
        try:
            config = self._read_and_validate()
            with self._lock:
                self._config = config
                self._last_mtime = os.path.getmtime(self.config_path)
            print(f"[AVM-CONFIG] Loaded config from {self.config_path}")
        except Exception as e:
            with self._lock:
                self._config = copy.deepcopy(self.defaults)
                self._last_mtime = None
            print(f"[AVM-CONFIG] Startup load failed, using defaults. reason={e}")

    def hot_reload(self):
        try:
            config = self._read_and_validate()
            with self._lock:
                self._config = config
                self._last_mtime = os.path.getmtime(self.config_path)
            print(f"[AVM-CONFIG] Hot-reload applied: {self.config_path}")
            return True
        except Exception as e:
            with self._lock:
                self._config = copy.deepcopy(self.defaults)
                if os.path.exists(self.config_path):
                    self._last_mtime = os.path.getmtime(self.config_path)
                else:
                    self._last_mtime = None
            print(f"[AVM-CONFIG] Hot-reload failed, fallback to defaults. reason={e}")
            return False

    def get_config(self):
        with self._lock:
            return copy.deepcopy(self._config)

    def start_hot_reload_watcher(self, interval_seconds=3):
        if self._watcher_started:
            return
        self._watcher_started = True

        def _watch_loop():
            while True:
                try:
                    if os.path.exists(self.config_path):
                        mtime = os.path.getmtime(self.config_path)
                        if self._last_mtime is None:
                            self._last_mtime = mtime
                        elif mtime != self._last_mtime:
                            self.hot_reload()
                    else:
                        if self._last_mtime is not None:
                            self.hot_reload()
                    time.sleep(interval_seconds)
                except Exception as e:
                    print(f"[AVM-CONFIG] Watcher error: {e}")
                    time.sleep(interval_seconds)

        threading.Thread(target=_watch_loop, daemon=True).start()
        print(f"[AVM-CONFIG] Hot-reload watcher started (interval={interval_seconds}s)")


_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "datas", "avm", "config.json")
AVM_CONFIG_MANAGER = AvmConfigManager(_CONFIG_PATH)


def get_effective_alert_threshold(default: float) -> float:
    try:
        config = AVM_CONFIG_MANAGER.get_config()
    except Exception:
        config = {}
    return _coerce_nonnegative_number((config or {}).get("alert_threshold"), default)


def get_effective_radius_km(default: float) -> float:
    try:
        config = AVM_CONFIG_MANAGER.get_config()
    except Exception:
        config = {}
    return _coerce_positive_number((config or {}).get("radius_km"), default)


def get_effective_risk_discount_factor(default: float) -> float:
    try:
        config = AVM_CONFIG_MANAGER.get_config()
    except Exception:
        config = {}
    return _coerce_nonnegative_number((config or {}).get("risk_discount_factor"), default)


def get_effective_weighting(defaults=None):
    base = copy.deepcopy(DEFAULT_AVM_CONFIG["weighting"])
    if isinstance(defaults, dict):
        base.update(defaults)

    try:
        config = AVM_CONFIG_MANAGER.get_config()
    except Exception:
        config = {}

    weighting = (config or {}).get("weighting")
    if isinstance(weighting, dict):
        for key, fallback in base.items():
            if key == "time_decay":
                base[key] = _coerce_time_decay(weighting.get(key), fallback)
            else:
                base[key] = _coerce_positive_number(weighting.get(key), fallback)

    return base
