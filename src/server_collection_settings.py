from . import collection_settings_schema as _settings_schema
from . import collection_settings_store as _settings_store
from . import collection_engine_restart as _settings_auth
from .server_context import *  # noqa: F401,F403


def _collection_settings_store():
    return _settings_store.SettingsStore(_settings_auth.runtime_root())


def _server_collection_settings(handler, *, read=False):
    path = urlparse(handler.path).path
    try:
        role = _settings_schema.ROLES.get(path)
        if role is None or (read and path != _settings_schema.PREFIX) or (not read and path == _settings_schema.PREFIX):
            raise _settings_auth.RestartError("Unsupported settings route", 404)
        _settings_auth.authorize(handler.headers, role)
        store = _collection_settings_store()
        if read:
            result = store.status()
        else:
            length = int(handler.headers.get("Content-Length", "0"))
            if not 2 <= length <= 16384:
                raise _settings_auth.RestartError("Invalid settings body length", 400)
            payload = json.loads(handler.rfile.read(length))
            if not isinstance(payload, dict):
                raise _settings_auth.RestartError("Expected a settings object", 400)
            action = path.rsplit("/", 1)[-1]
            result = {"apply": store.apply, "poll": store.poll, "result": store.finish}[action](payload)
        handler.send_json(result)
    except _settings_auth.RestartError as error:
        handler.send_error_json(status=error.status, code="SETTINGS_REJECTED", message=str(error), details={})
    except (ValueError, UnicodeError, TypeError):
        handler.send_error_json(status=400, code="SETTINGS_INVALID", message="Invalid settings request", details={})
    except (OSError, _settings_store.sqlite3.Error):
        handler.send_error_json(status=503, code="SETTINGS_UNAVAILABLE", message="Settings storage unavailable", details={})


__all__ = ["_settings_schema", "_settings_store", "_settings_auth", "_collection_settings_store", "_server_collection_settings"]
