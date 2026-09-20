"""Private-CA restart contract with synthetic credentials and fake HTTP only."""
import io
import json

import pytest

from tools import desktop_settings_client as client


@pytest.fixture
def transport(tmp_path, monkeypatch):
    token = tmp_path / "operator.token"
    token.write_text("synthetic_operator_token_00000000001")
    monkeypatch.setattr(client, "load_runtime_environment", lambda _: {
        "FAPAI_SETTINGS_API_BASE": "https://nas.example.invalid:18443",
        "FAPAI_SETTINGS_CA_FILE": str(tmp_path / "ca.crt"),
        "FAPAI_ENGINE_OPERATOR_TOKEN_FILE": str(token),
    })
    monkeypatch.setattr(client.ssl, "create_default_context", lambda **_: client.ssl.SSLContext(client.ssl.PROTOCOL_TLS_CLIENT))
    requests = []
    class Opener:
        def open(self, request, **_):
            requests.append(request)
            return io.BytesIO(b'{"ok":true,"available":true}')
    monkeypatch.setattr(client.urllib.request, "build_opener", lambda *_: Opener())
    return tmp_path, requests


def test_restart_uses_https_role_token_and_fixed_route(transport):
    root, requests = transport
    common = {"origin": "https://nas.example.invalid:18443"}
    assert client.execute({**common, "action": "restart_status"}, root)["available"]
    client.execute({**common, "action": "restart", "body": {"request_id": "restart-fixture-001"}}, root)
    assert [r.method for r in requests] == ["GET", "POST"]
    assert all(r.full_url == common["origin"] + "/api/collection/control/restart" for r in requests)
    assert requests[0].data is None
    assert json.loads(requests[1].data) == {"request_id": "restart-fixture-001"}
    assert requests[1].get_header("X-fapai-control-token") == "synthetic_operator_token_00000000001"


@pytest.mark.parametrize("change", [
    {"origin": "https://other.invalid"}, {"action": "restart/poll"},
    {"body": {"request_id": "restart-fixture-001", "command": "shutdown"}},
    {"body": {"request_id": "$(reboot)"}}, {"action": "restart_status", "body": {}},
])
def test_restart_rejects_untrusted_origin_action_and_body_before_http(transport, change):
    root, requests = transport
    request = {"origin": "https://nas.example.invalid:18443", "action": "restart",
               "body": {"request_id": "restart-fixture-001"}, **change}
    with pytest.raises(ValueError):
        client.execute(request, root)
    assert not requests
