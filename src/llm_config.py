from __future__ import annotations

import json
import os
import json as _json
import os as _os


_SECRETS_FILE = _os.path.join(_os.path.dirname(__file__), "..", "secrets.json")


def _has_openai_compatible_env():
    base_url = (
        _os.environ.get("OPENAI_BASE_URL")
        or _os.environ.get("OPENAI_API_BASE")
        or _os.environ.get("OPENAI_COMPATIBLE_BASE_URL")
    )
    return bool(base_url and _os.environ.get("OPENAI_API_KEY"))


def _load_secrets():
    """Load API credentials from secrets.json."""
    if not _os.path.exists(_SECRETS_FILE):
        if not _has_openai_compatible_env():
            print(f"[ERROR] secrets.json not found at {_SECRETS_FILE}")
            print("[ERROR] Please copy secrets.example.json to secrets.json and fill in your API keys.")
        return None
    with open(_SECRETS_FILE, 'r', encoding='utf-8') as f:
        return _json.load(f)


_secrets = _load_secrets()


def _build_model_pool(secrets):
    """Build MODEL_POOL from secrets.json configuration."""
    if not secrets:
        return []
    ws_url = secrets.get("ws_url", "")
    common_models = secrets.get("models", [])

    # Check for new multi-account structure
    accounts = secrets.get("accounts")
    if not accounts:
        # Backward compatibility: Treat top-level as one account
        accounts = [{
            "app_id": secrets.get("app_id", ""),
            "api_key": secrets.get("api_key", ""),
            "api_secret": secrets.get("api_secret", "")
        }]

    pool = []
    for idx, acc in enumerate(accounts):
        acc_name = acc.get("name", f"Acc{idx+1}")
        acc_app_id = acc.get("app_id")
        acc_api_key = acc.get("api_key")
        acc_api_secret = acc.get("api_secret")
        # Allow account to override ws_url or models if needed
        acc_ws_url = acc.get("ws_url", ws_url)
        acc_models = acc.get("models", common_models)

        for m in acc_models:
            # Create a unique name for each account's model instance
            # e.g., "GLM-4.7-Base" becomes "GLM-4.7-Base-Acc1"
            # This allows ModelSelector to track limits independently
            unique_name = f"{m['name']}-{acc_name}"
            pool.append({
                "name": unique_name,
                "base_name": m["name"], # Original name for grouping
                "app_id": acc_app_id,
                "api_key": acc_api_key,
                "api_secret": acc_api_secret,
                "ws_url": acc_ws_url,
                "model_id": m["model_id"],
                "max_concurrent": m.get("max_concurrent", 5)
            })
    return pool


MODEL_POOL = _build_model_pool(_secrets)


CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "datas", "model_config.json")


def load_model_config():
    """Load model concurrency config from file if exists, else use defaults from MODEL_POOL."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                # Merge saved config into MODEL_POOL
                for model in MODEL_POOL:
                    name = model["name"]
                    base = model.get("base_name", name)

                    # Try exact match first, then base name match
                    if name in saved:
                         model["max_concurrent"] = saved[name].get("max_concurrent", model.get("max_concurrent", 5))
                    elif base in saved:
                         model["max_concurrent"] = saved[base].get("max_concurrent", model.get("max_concurrent", 5))
                print(f"[CONFIG] Loaded model config from {CONFIG_FILE}")
        except Exception as e:
            print(f"[CONFIG] Error loading config: {e}, using defaults")
    return MODEL_POOL


_LEGACY_DEFAULT_MODEL = MODEL_POOL[0] if MODEL_POOL else {}


APP_ID = _LEGACY_DEFAULT_MODEL.get("app_id", "")


API_KEY = _LEGACY_DEFAULT_MODEL.get("api_key", "")


API_SECRET = _LEGACY_DEFAULT_MODEL.get("api_secret", "")


WS_URL = _LEGACY_DEFAULT_MODEL.get("ws_url", "")


MODEL_ID = _LEGACY_DEFAULT_MODEL.get("model_id", "")


load_model_config()


__all__ = ['_SECRETS_FILE', '_has_openai_compatible_env', '_load_secrets', '_secrets', '_build_model_pool', 'MODEL_POOL', 'CONFIG_FILE', 'load_model_config', '_LEGACY_DEFAULT_MODEL', 'APP_ID', 'API_KEY', 'API_SECRET', 'WS_URL', 'MODEL_ID']
