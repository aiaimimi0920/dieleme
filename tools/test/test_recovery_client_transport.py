"""Recovery credentials never leave through untrusted or plaintext transports."""

from pathlib import Path

import pytest

from tools import internal_api_http
from tools.pc1_desktop_recovery import RecoveryClient, RecoveryError
from tools.test import test_collection_control_https as tls_fixtures

control = tls_fixtures.control


@pytest.mark.parametrize(
    "header",
    ["X-Fapai-Recovery-Token", "X-FAPAI-Control-Token", "X-FAPAI-Collection-Token"],
)
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_explicit_credentials_cannot_bypass_https(monkeypatch, header, method):
    for key in (
        "FAPAI_COLLECTION_WORKER_TOKEN_FILE",
        "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE",
        "FAPAI_API_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        internal_api_http,
        "_build_session",
        lambda: pytest.fail("plaintext credential request reached the network"),
    )
    url = "http://198.51.100.42:8001/api/status"
    with pytest.raises(OSError, match="HTTPS"):
        if method == "GET":
            internal_api_http.fetch_json(url, timeout=1, headers={header: "fixture"})
        else:
            internal_api_http.post_json(url, {}, timeout=1, headers={header: "fixture"})


def test_pc1_rejects_remote_http_before_reading_a_token(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "read_text", lambda *_, **__: pytest.fail("token read"))
    origin = "http://198.51.100.42:8001"
    with pytest.raises(RecoveryError, match="invalid_api"):
        RecoveryClient(
            origin, tmp_path, environment={"FAPAI_COLLECTOR_API_BASE": origin}
        )


def test_pc1_requires_an_explicit_api_configuration(tmp_path):
    with pytest.raises(RecoveryError, match="api_not_configured"):
        RecoveryClient("https://crow.example", tmp_path, environment={})


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:secret@crow.example",
        "https://crow.example?redirect=1",
        "https://crow.example/#fragment",
        "https://crow.example\\@elsewhere.example",
        "https://crow.example\r\nX-Other: value",
        "https://crow.example:99999",
    ],
)
def test_pc1_rejects_ambiguous_destinations_before_credentials(tmp_path, origin):
    with pytest.raises(RecoveryError, match="invalid_api"):
        RecoveryClient(
            origin, tmp_path, environment={"FAPAI_COLLECTOR_API_BASE": origin}
        )


def environment(origin, ca, root):
    token = root / "recovery.token"
    token.write_text("first-recovery-fixture-" + "r" * 32, encoding="utf-8")
    return {
        "FAPAI_COLLECTOR_API_BASE": origin + "/api",
        "FAPAI_API_CA_FILE": str(ca),
        "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE": str(token),
    }, token


def test_pc1_tls_roundtrip_rotation_and_untrusted_ca_rejection(control, monkeypatch):
    origin, ca, _, root = control
    env, token = environment(origin, ca, root)
    received = []

    def dispatch(_root, method, path, headers, body):
        received.append((method, path, headers.get("X-Fapai-Recovery-Token"), body))
        return {"ok": True}

    monkeypatch.setattr("tools.collection_control_https.dispatch", dispatch)
    client = RecoveryClient(origin, root, environment=env)
    assert client.call() == {"ok": True}
    first = token.read_text(encoding="utf-8")
    token.write_text("rotated-recovery-fixture-" + "n" * 32, encoding="utf-8")
    assert client.call("/claim", {"role": "pc1"}) == {"ok": True}
    assert received == [
        ("GET", "/api/collection/auth/recovery", first, {}),
        (
            "POST",
            "/api/collection/auth/recovery/claim",
            token.read_text(encoding="utf-8"),
            {"role": "pc1"},
        ),
    ]
    env.pop("FAPAI_API_CA_FILE")
    with pytest.raises(RecoveryError, match="api_unavailable"):
        RecoveryClient(origin, root, environment=env).call()
    assert len(received) == 2


def test_pc1_missing_private_ca_fails_before_token_read(tmp_path):
    origin = "https://crow.example"
    with pytest.raises(RecoveryError, match="ca_unavailable"):
        RecoveryClient(
            origin,
            tmp_path,
            environment={
                "FAPAI_COLLECTOR_API_BASE": origin,
                "FAPAI_API_CA_FILE": str(tmp_path / "missing-ca.pem"),
            },
        )


def test_pc1_refuses_redirect_without_resending_credential(control, monkeypatch):
    origin, ca, _, root = control
    env, _ = environment(origin, ca, root)
    received = []

    def redirect(handler):
        received.append(handler.path)
        handler.send_response(302)
        handler.send_header("Location", origin + "/api/leaked")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    monkeypatch.setattr("tools.collection_control_https.Handler.do_GET", redirect)
    with pytest.raises(RecoveryError, match="redirect_refused"):
        RecoveryClient(origin, root, environment=env).call()
    assert received == ["/api/collection/auth/recovery"]
