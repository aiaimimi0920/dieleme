"""JSON-stdio bridge for PC1 automation, sharing the desktop's verified transport."""

import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pc1_desktop_recovery import RecoveryClient, RecoveryError, api_origin

POST_ACTIONS = frozenset({"claim", "snapshot_ready"})
FIELDS = frozenset({"api_base", "data_root", "token_path", "ca_file", "action", "body"})


def _text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        raise RecoveryError("invalid_request")
    return value


def execute(payload: object) -> dict:
    if not isinstance(payload, dict) or set(payload) - FIELDS:
        raise RecoveryError("invalid_request")
    origin = api_origin(_text(payload, "api_base"))
    action = _text(payload, "action")
    body = payload.get("body")
    if action not in POST_ACTIONS | {"status", "public_status"}:
        raise RecoveryError("invalid_request")
    if (action in POST_ACTIONS and not isinstance(body, dict)) or (
        action not in POST_ACTIONS and body is not None
    ):
        raise RecoveryError("invalid_request")
    root = _text(payload, "data_root")
    if not root:
        raise RecoveryError("invalid_request")
    environment = {**os.environ, "FAPAI_COLLECTOR_API_BASE": origin}
    for field, key in (
        ("token_path", "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE"),
        ("ca_file", "FAPAI_API_CA_FILE"),
    ):
        value = _text(payload, field)
        if value:
            environment[key] = value
    client = RecoveryClient(origin, Path(root), environment=environment)
    if action == "public_status":
        return client.status()
    return client.call("/" + action if action in POST_ACTIONS else "", body)


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise RecoveryError("invalid_request")
        result = execute(json.loads(raw))
    except (ValueError, TypeError, UnicodeError):
        result = {"ok": False, "code": "invalid_request"}
    except RecoveryError as error:
        result = {"ok": False, "code": str(error)}
    print(json.dumps(result, ensure_ascii=True))
    return 1 if result.get("ok") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
