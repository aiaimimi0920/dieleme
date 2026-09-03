from __future__ import annotations

import base64
import hashlib
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from src import server


class FakeCoordinator:
    enabled = True
    stall_seconds = 1800

    def __init__(self):
        self.claims = []

    def snapshot(self):
        return {
            "enabled": True,
            "stall_seconds": 1800,
            "active": {
                "recovery_id": "auth-recovery-1",
                "status": "requested",
                "snapshot": None,
            },
        }

    def claim(self, role, recovery_id, node_id):
        self.claims.append((role, recovery_id, node_id))
        return {"ok": True, "recovery": self.snapshot()["active"]}


def _request_json(url, *, method="GET", payload=None, recovery_token=""):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Fapai-Recovery-Token": recovery_token,
        },
    )
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def test_recovery_api_exposes_safe_state_and_accepts_exact_pc1_claim(monkeypatch, tmp_path):
    coordinator = FakeCoordinator()
    token_path = tmp_path / "nas-auth-recovery.token"
    token_path.write_text("test-recovery-token\n", encoding="utf-8")
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", coordinator)
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY_TOKEN_FILE", token_path)
    httpd = server.ReusableTCPServer(("127.0.0.1", 0), server.DataHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}/api/collection/auth/recovery"
        with pytest.raises(HTTPError) as forbidden:
            _request_json(base, recovery_token="wrong-token")
        state = _request_json(base, recovery_token="test-recovery-token")
        claim = _request_json(
            f"{base}/claim",
            method="POST",
            payload={"recovery_id": "auth-recovery-1", "role": "pc1", "node_id": "pc1"},
            recovery_token="test-recovery-token",
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    assert state["auth_recovery"]["active"]["status"] == "requested"
    assert forbidden.value.code == 403
    assert claim["ok"] is True
    assert coordinator.claims == [("pc1", "auth-recovery-1", "pc1")]
    assert "cookies" not in json.dumps(state)


def test_recovery_snapshot_endpoint_relays_only_the_active_digest_matched_file(monkeypatch, tmp_path):
    snapshot_path = tmp_path / "taobao-cookies.json"
    raw = json.dumps(
        [{"name": "session", "value": "secret", "domain": ".taobao.com", "path": "/"}]
    ).encode("utf-8")
    snapshot_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    token_path = tmp_path / "nas-auth-recovery.token"
    token_path.write_text("test-recovery-token\n", encoding="utf-8")

    class SnapshotCoordinator:
        enabled = True

        def snapshot(self):
            return {
                "enabled": True,
                "active": {
                    "recovery_id": "auth-recovery-1",
                    "status": "snapshot_ready",
                    "snapshot": {"sha256": digest, "cookie_count": 1},
                },
            }

    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", SnapshotCoordinator())
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY_TOKEN_FILE", token_path)
    monkeypatch.setattr(server, "_resolve_auth_cookie_snapshot_path", lambda _payload: str(snapshot_path))
    httpd = server.ReusableTCPServer(("127.0.0.1", 0), server.DataHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}/api/collection/auth/recovery"
        payload = _request_json(
            f"{base}/snapshot?recovery_id=auth-recovery-1",
            recovery_token="test-recovery-token",
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    assert payload["sha256"] == digest
    assert payload["encoding"] == "base64"
    assert base64.b64decode(payload["snapshot"]) == raw


def test_successful_pc2_result_clears_auth_pause_then_waits_for_real_progress(monkeypatch):
    calls = []

    class ResultCoordinator:
        def result(self, recovery_id, *, success, reason=""):
            calls.append((recovery_id, success, reason))
            return {"ok": True, "status": "verifying"}

    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", ResultCoordinator())
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "_clear_solver_manual_required_pause", lambda: None)
    monkeypatch.setattr(server, "_remember_solver_auth_completion", lambda payload: calls.append(("remember", payload)))
    monkeypatch.setattr(server, "_collection_effectively_paused", lambda: False)
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", lambda: {"paused": False})

    result = server._nas_auth_recovery_result(
        {
            "recovery_id": "auth-recovery-1",
            "success": True,
            "reason": "cookie_import_verified_after_restart",
        }
    )

    assert result["status"] == "verifying"
    assert result["paused"] is False
    assert calls[0] == (
        "auth-recovery-1",
        True,
        "cookie_import_verified_after_restart",
    )
    assert calls[1][0] == "remember"


def test_unhealthy_cookie_signal_requires_an_active_solver_pause(monkeypatch):
    monkeypatch.setattr(
        server,
        "_auth_cookie_snapshot_runtime_status",
        lambda: {
            "status": "failed",
            "result": {"reason": "cookie_snapshot_candidate_unhealthy"},
        },
    )
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", lambda: {"paused": False})
    assert server._nas_auth_recovery_signal() is None

    monkeypatch.setattr(server, "_captcha_solver_runtime_status", lambda: {"paused": True})
    assert server._nas_auth_recovery_signal() == "cookie_snapshot_candidate_unhealthy"

    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {"paused": True, "manual_required": True},
    )
    assert server._nas_auth_recovery_signal() == "captcha_manual_required"


def test_stalled_detail_challenge_is_an_independent_auth_recovery_signal(monkeypatch):
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "captcha_solver")
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS", 300)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_runtime_status", lambda: {"status": "idle"})

    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {
            "paused": True,
            "scopes": {
                "seed": {"paused": True, "challenge_age_seconds": 900},
                "detail": {"paused": True, "challenge_age_seconds": 299},
            },
        },
    )
    assert server._nas_auth_recovery_signal() is None

    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {
            "paused": True,
            "scopes": {
                "seed": {"paused": False, "challenge_age_seconds": 0},
                "detail": {"paused": True, "challenge_age_seconds": 300},
            },
        },
    )
    assert server._nas_auth_recovery_signal() == "detail_challenge_stalled"


def test_node_solver_blocked_report_persists_strong_recovery_signal(monkeypatch, tmp_path):
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "SOLVER_SCOPE_STATE_ROOT", None)
    monkeypatch.setattr(
        server,
        "SOLVER_SCOPE_STATES",
        {scope: server._new_solver_scope_state() for scope in server.CHALLENGE_SCOPES},
    )
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_CHALLENGE_ID", None)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_PENDING_TOKEN", None)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", None)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_exists", lambda: False)

    request = {
        "target_url": "https://sf-item.taobao.com/sf_item/3001.htm",
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "scope": "detail",
        "node_solver_blocked": True,
        "node_solver_blocked_reason": "repeated_solver_failures",
        "node_solver_blocked_attempts": 10,
    }
    first = server._node_solver_blocked_report_payload(request)
    blocked_at = first["captcha_solver"]["scopes"]["detail"][
        "node_solver_blocked_at_epoch"
    ]
    second = server._node_solver_blocked_report_payload(request)

    assert first["status"] == "node_solver_blocked"
    assert first["scope"] == "detail"
    assert first["captcha_solver"]["manual_required"] is False
    assert first["captcha_solver"]["scopes"]["detail"]["node_solver_blocked"] is True
    assert first["captcha_solver"]["scopes"]["detail"][
        "node_solver_blocked_reason"
    ] == "repeated_solver_failures"
    assert first["captcha_solver"]["scopes"]["detail"][
        "node_solver_blocked_attempts"
    ] == 10
    assert second["captcha_solver"]["scopes"]["detail"][
        "node_solver_blocked_at_epoch"
    ] == blocked_at
    assert server._nas_auth_recovery_signal() == "node_solver_retries_exhausted"

    assert server._clear_solver_challenge_state(scope="detail") is None
    assert server._nas_auth_recovery_signal() is None


def test_node_solver_blocked_signal_requires_paused_scoped_failure(monkeypatch):
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "captcha_solver")
    monkeypatch.setattr(server, "_auth_cookie_snapshot_runtime_status", lambda: {"status": "idle"})
    base_scope = {
        "paused": True,
        "node_solver_blocked": True,
        "node_solver_blocked_reason": "repeated_solver_failures",
    }

    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {"paused": True, "scopes": {"detail": {**base_scope, "paused": False}}},
    )
    assert server._nas_auth_recovery_signal() is None

    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "operator")
    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {"paused": True, "scopes": {"detail": base_scope}},
    )
    assert server._nas_auth_recovery_signal() is None

    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "captcha_solver")
    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {
            "paused": True,
            "scopes": {
                "detail": {**base_scope, "node_solver_blocked_reason": "transient_failure"}
            },
        },
    )
    assert server._nas_auth_recovery_signal() is None
