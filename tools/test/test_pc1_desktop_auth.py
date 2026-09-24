import io
import json

import pytest

from src.nas_auth_recovery import NasAuthRecoveryCoordinator
from tools import pc1_desktop_auth as desktop
from tools.pc1_desktop_recovery import RecoveryClient, RecoveryError, recovery_phase
from tools.manual_auth_snapshot import snapshot_path, completion_lock, publish_snapshot

REQUEST_ID = "a" * 32
URL = "https://sf-item.taobao.com/sf_item/123456789.htm"


class FixtureClient:
    def __init__(self, tmp_path):
        self.coordinator = NasAuthRecoveryCoordinator(tmp_path / "state.json")
        self.coordinator.sample(100, 20)
        self.calls = []

    def call(self, path="", body=None):
        self.calls.append((path, body))
        if path == "/request":
            return self.coordinator.request_manual(body["request_id"])
        if path == "/claim":
            return self.coordinator.claim(body["role"], body["recovery_id"], body["node_id"])
        if path == "/snapshot_ready":
            return self.coordinator.snapshot_ready(**body)
        assert path == ""
        return {"ok": True, "auth_recovery": self.coordinator.snapshot()}


def setup_handoff(monkeypatch, *, ready=True):
    monkeypatch.setattr(desktop.handoff.taobao_login_health, "list_cdp_targets", lambda _: [
        {"type": "page", "id": "selected", "url": URL},
        {"type": "page", "id": "different", "url": URL.replace("123456789", "987654321")},
    ])
    def capture(**args):
        assert args["required_target_id"] == "selected"
        assert not args["allow_list_only"]
        if not ready:
            raise RuntimeError("not reusable yet")
        args["output_path"].write_text(json.dumps([{"name": "fixture", "value": "synthetic-cookie", "domain": ".taobao.com"}]), encoding="utf-8")
        return {"ok": True}
    monkeypatch.setattr(desktop.handoff, "complete_inplace_auth", capture)


def complete(client, output, challenge_id="fixture-challenge"):
    return desktop.complete_challenge(client, endpoint="http://127.0.0.1:9225", output_path=output,
                                      request_id=REQUEST_ID, challenge_id=challenge_id, url=URL, target_id="selected")


@pytest.mark.parametrize("challenge_id", ["fixture-challenge", ""])
def test_manual_completion_transfers_metadata_then_waits_for_pc2_and_progress(tmp_path, monkeypatch, challenge_id):
    client = FixtureClient(tmp_path)
    setup_handoff(monkeypatch)
    output = tmp_path / "cookies.json"
    result = complete(client, output, challenge_id)
    assert result["phase"] == "pending_pc2"
    active = client.coordinator.snapshot()["active"]
    assert snapshot_path(output, active["recovery_id"], active["snapshot"]["sha256"]).is_file()
    assert not output.exists()
    assert "synthetic-cookie" not in json.dumps(client.calls)
    assert next(body for path, body in client.calls if path == "/request")["challenge_id"] == challenge_id
    recovery_id = result["recovery_id"]
    manager = client.coordinator
    manager.sample(101, 20)
    assert manager.snapshot()["active"]["status"] == "snapshot_ready"
    manager.claim("pc2", recovery_id, "pc2")
    manager.pc2_restarting(recovery_id)
    manager.result(recovery_id, success=True)
    assert recovery_phase(manager.snapshot(), recovery_id)["phase"] == "pending_pc2"
    manager.sample(102, 20)
    assert recovery_phase(manager.snapshot(), recovery_id)["phase"] == "succeeded"
    assert complete(client, output)["phase"] == "succeeded"


def test_unready_session_preserves_previous_snapshot_and_never_announces_ready(tmp_path, monkeypatch):
    client = FixtureClient(tmp_path)
    setup_handoff(monkeypatch, ready=False)
    output = tmp_path / "cookies.json"
    output.write_text("previous", encoding="utf-8")
    assert complete(client, output)["phase"] == "pending_human"
    assert output.read_text() == "previous"
    assert not any(path == "/snapshot_ready" for path, _ in client.calls)


def test_retry_while_pc2_is_receiving_never_exports_again(tmp_path, monkeypatch):
    client = FixtureClient(tmp_path)
    setup_handoff(monkeypatch)
    output = tmp_path / "cookies.json"
    complete(client, output)
    monkeypatch.setattr(desktop.handoff, "complete_inplace_auth", lambda **_: pytest.fail("duplicate export"))
    assert complete(client, output)["phase"] == "pending_pc2"


def test_target_mismatch_cannot_use_an_unrelated_healthy_tab(monkeypatch):
    setup_handoff(monkeypatch)
    with pytest.raises(RecoveryError, match="challenge_page_not_ready"):
        desktop.find_target("http://127.0.0.1:9225", URL, "different")


@pytest.mark.parametrize("url", ["https://example.invalid/list/1", "http://sf.taobao.com/list/1", "https://user:pass@sf.taobao.com/list/1"])
def test_browser_targets_are_bounded(url):
    with pytest.raises(RecoveryError):
        desktop.target_identity(url)


def test_recovery_token_is_never_sent_to_an_unconfigured_api(tmp_path, monkeypatch):
    monkeypatch.setenv("FAPAI_COLLECTOR_API_BASE", "https://crow.example:8001")
    with pytest.raises(RecoveryError, match="api_not_configured"):
        RecoveryClient("https://example.invalid", tmp_path)


def test_manual_requests_are_single_flight_and_survive_reloads(tmp_path):
    manager = NasAuthRecoveryCoordinator(tmp_path / "state.json")
    first = manager.request_manual(REQUEST_ID)
    second = NasAuthRecoveryCoordinator(tmp_path / "state.json").request_manual(REQUEST_ID)
    assert first["recovery"]["recovery_id"] == second["recovery"]["recovery_id"]
    assert not manager.request_manual("../../outside")["ok"]
    assert manager.request_manual("b" * 32)["recovery"]["recovery_id"] == first["recovery"]["recovery_id"]


@pytest.mark.parametrize("current", ["current", ""])
def test_new_route_rejects_bad_auth_and_stale_challenge_before_mutation(tmp_path, monkeypatch, current):
    from src import server
    manager = NasAuthRecoveryCoordinator(tmp_path / "state.json")
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", manager)
    monkeypatch.setattr(server, "_nas_auth_recovery_authorized", lambda headers: (headers.get("fixture") == "yes", ""))
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", lambda: {"challenge_id": current})
    pauses = []
    monkeypatch.setattr(server, "_set_collection_pause_state", lambda *args: pauses.append(args))
    class Handler:
        def __init__(self, authorized, challenge):
            raw = json.dumps({"request_id": REQUEST_ID, "challenge_id": challenge}).encode()
            self.headers = {"fixture": "yes" if authorized else "no", "Content-Length": str(len(raw))}
            self.rfile = io.BytesIO(raw)
        def send_json(self, value): self.result = value
        def send_error_json(self, **value): self.result = value
    rejected = [(False, current, 403), (True, "stale", 409)]
    if current:
        rejected.append((True, "", 409))
    for authorized, challenge, status in rejected:
        handler = Handler(authorized, challenge)
        server._server_desktop_auth_request(handler)
        assert handler.result["status"] == status and not pauses
        assert manager.snapshot()["active"] is None
    handler = Handler(True, current)
    server._server_desktop_auth_request(handler)
    assert handler.result["ok"] and pauses == [(True, "manual_required")]


@pytest.mark.parametrize("status", ["snapshot_ready", "pc2_claimed", "restarting", "verifying"])
def test_existing_automatic_recovery_is_not_relabelled_or_recaptured(tmp_path, monkeypatch, status):
    client = FixtureClient(tmp_path)
    coordinator = client.coordinator
    coordinator.request_manual(REQUEST_ID)
    with coordinator._locked_state():
        coordinator._state["active"]["status"] = status
        coordinator._state["active"].pop("manual_request_id")
        coordinator._persist_locked()
    setup_handoff(monkeypatch)
    monkeypatch.setattr(desktop.handoff, "complete_inplace_auth", lambda **_: pytest.fail("automatic task stolen"))
    result = complete(client, tmp_path / "cookies.json")
    assert result["code"] == "existing_recovery"
    assert not coordinator.snapshot()["active"].get("manual_request_id")


def test_missing_target_id_never_creates_a_recovery(tmp_path):
    client = FixtureClient(tmp_path)
    with pytest.raises(RecoveryError, match="challenge_page_not_ready"):
        desktop.complete_challenge(client, endpoint="unused", output_path=tmp_path / "cookies.json",
                                   request_id=REQUEST_ID, challenge_id="", url=URL)
    assert not client.calls


def test_list_target_query_is_part_of_its_identity(monkeypatch):
    monkeypatch.setattr(desktop.handoff.taobao_login_health, "list_cdp_targets", lambda _: [
        {"type": "page", "id": "selected", "url": "https://sf.taobao.com/list/50025969.htm?city=other"}])
    with pytest.raises(RecoveryError):
        desktop.find_target("unused", "https://sf.taobao.com/list/50025969.htm?city=selected", "selected")


def test_snapshot_publish_failure_does_not_overwrite_previous_session(tmp_path, monkeypatch):
    client = FixtureClient(tmp_path)
    setup_handoff(monkeypatch)
    output = tmp_path / "cookies.json"
    output.write_bytes(b"previous-session")
    original = client.call
    def fail_ready(path="", body=None):
        if path == "/snapshot_ready":
            raise RecoveryError("api_unavailable")
        return original(path, body)
    monkeypatch.setattr(client, "call", fail_ready)
    with pytest.raises(RecoveryError):
        complete(client, output)
    assert output.read_bytes() == b"previous-session"
    assert client.coordinator.snapshot()["active"]["status"] == "pc1_claimed"


@pytest.mark.parametrize("raw", [b"{}", b"[]", b'[{"name":"fixture"}]', b"invalid"])
def test_invalid_cookie_payload_cannot_be_published(tmp_path, raw):
    with pytest.raises(RecoveryError, match="invalid_snapshot"):
        publish_snapshot(tmp_path / "cookies.json", "auth-recovery-" + REQUEST_ID, raw)
    assert not (tmp_path / "desktop-auth").exists()


def test_completion_file_lock_blocks_another_process_and_releases(tmp_path):
    import subprocess
    import sys
    output = tmp_path / "cookies.json"
    code = "from pathlib import Path; from tools.manual_auth_snapshot import completion_lock; import sys\nwith completion_lock(Path(sys.argv[1])): pass"
    with completion_lock(output):
        locked = subprocess.run([sys.executable, "-c", code, str(output)], capture_output=True)
        assert locked.returncode != 0 and b"handoff_busy" in locked.stderr
    assert subprocess.run([sys.executable, "-c", code, str(output)], capture_output=True).returncode == 0


def test_reopened_desktop_can_finish_its_previous_unpublished_manual_task(tmp_path, monkeypatch):
    client = FixtureClient(tmp_path)
    original = client.coordinator.request_manual("b" * 32)["recovery"]
    client.coordinator.claim("pc1", original["recovery_id"], "pc1")
    setup_handoff(monkeypatch)
    result = complete(client, tmp_path / "cookies.json")
    assert result["phase"] == "pending_pc2" and result["recovery_id"] == original["recovery_id"]


def test_nas_serves_immutable_manual_snapshot_and_preserves_legacy_file(tmp_path, monkeypatch):
    import base64
    from src import server
    client = FixtureClient(tmp_path)
    setup_handoff(monkeypatch)
    output = tmp_path / "cookies.json"
    output.write_bytes(b"previous-session")
    result = complete(client, output)
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", client.coordinator)
    monkeypatch.setattr(server, "_nas_auth_recovery_authorized", lambda _: (True, ""))
    monkeypatch.setattr(server, "_resolve_auth_cookie_snapshot_path", lambda _: str(output))
    class Handler:
        headers = {}
        def send_json(self, value): self.result = value
        def send_error_json(self, **value): self.result = value
    handler = Handler()
    server._get_auth_recovery_snapshot(handler, None, "", {"recovery_id": [result["recovery_id"]]})
    assert handler.result["ok"]
    assert json.loads(base64.b64decode(handler.result["snapshot"]))[0]["name"] == "fixture"
    assert output.read_bytes() == b"previous-session"


def test_open_preserves_the_new_tab_identity_during_login_redirect(tmp_path, monkeypatch):
    from types import SimpleNamespace
    sequence = iter([[], [{"type": "page", "id": "new-login", "url": "https://login.taobao.com/member/login.jhtml"}],
                     [{"type": "page", "id": "new-login", "url": "https://login.taobao.com/member/login.jhtml"}]])
    monkeypatch.setattr(desktop.handoff.taobao_login_health, "list_cdp_targets", lambda _: next(sequence))
    def start(command, **kwargs):
        assert "-HumanAuthMode" in command and "-ForceNew" not in command
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(desktop.subprocess, "run", start)
    result = desktop.open_challenge(URL, "http://127.0.0.1:9225", 9225, tmp_path)
    assert result == {"phase": "ready_for_human", "target_id": "new-login"}


@pytest.mark.parametrize("status", ["requested", "pc1_claimed"])
def test_manual_completion_replaces_unpublished_automatic_task_not_its_old_tab(tmp_path, monkeypatch, status):
    client = FixtureClient(tmp_path)
    manager = client.coordinator
    old = manager.request_manual("b" * 32)["recovery"]["recovery_id"]
    with manager._locked_state():
        manager._state["active"].pop("manual_request_id")
        manager._state["active"]["status"] = status
        manager._persist_locked()
    setup_handoff(monkeypatch)
    output = tmp_path / "cookies.json"
    result = complete(client, output)
    assert result["phase"] == "pending_pc2" and result["recovery_id"] != old
    active = manager.snapshot()["active"]
    assert active["manual_request_id"] == REQUEST_ID
    assert active["status"] == "snapshot_ready"
    assert not manager.snapshot_ready(old, sha256="0" * 64, cookie_count=1)["ok"]
    assert manager.snapshot()["active"]["recovery_id"] == result["recovery_id"]
