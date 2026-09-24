"""A default page's successful auth cannot release a different regional task."""
import io
import json
import time
from types import SimpleNamespace

import pytest

from src.collection.adapters.taobao_auth_target import matches_challenge_target, same_auth_target
from src.nas_auth_recovery import NasAuthRecoveryCoordinator

BASE = "https://sf.taobao.com/list/50025969__2.htm"
TARGET = BASE + "?location_code=510302&st_param=5&auction_start_seg=-1&page=18"


def status(target=TARGET):
    return {"challenge_id": "regional-challenge", "last_request": {"target_url": target}}


def setup_server(tmp_path, monkeypatch):
    from src import server
    manager = NasAuthRecoveryCoordinator(tmp_path / "state.json")
    manager.register_stage_auth_pc2()
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", manager)
    monkeypatch.setattr(server, "_nas_auth_recovery_authorized", lambda _: (True, ""))
    monkeypatch.setattr(server, "_solver_scope_runtime_status", lambda _: status())
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server, "_solver_detail_captured_count", lambda: 30)
    return server, manager


def request(server, target):
    raw = json.dumps({"request_id": "a" * 32, "scope": "seed", "protocol_version": 2,
                      "challenge_id": "regional-challenge", "target_url": target}).encode()
    outputs = []
    handler = SimpleNamespace(headers={"Content-Length": str(len(raw))}, rfile=io.BytesIO(raw),
                              send_json=outputs.append, send_error_json=lambda **kw: outputs.append(kw))
    server._server_desktop_auth_request(handler)
    return outputs[0]


@pytest.mark.parametrize("wrong", [BASE, TARGET.replace("page=18", "page=1"),
                                  TARGET.replace("510302", "440115"), TARGET.replace("st_param=5", "st_param=2")])
def test_request_rejects_same_challenge_id_with_different_collection_target(tmp_path, monkeypatch, wrong):
    server, manager = setup_server(tmp_path, monkeypatch)
    pauses = []
    monkeypatch.setattr(server, "_set_collection_pause_state", lambda *a, **kw: pauses.append(kw))
    result = request(server, wrong)
    assert result["status"] == 409
    assert manager.snapshot()["active"] is None and not pauses
    assert request(server, TARGET)["recovery"]["target_url"] == TARGET
    assert pauses == [{"scope": "seed"}]


def test_receipt_from_preexisting_generic_recovery_does_not_clear_regional_challenge(tmp_path, monkeypatch):
    server, manager = setup_server(tmp_path, monkeypatch)
    active = manager.request_manual("a" * 32, scope="seed", challenge_id="regional-challenge", target_url=BASE)["recovery"]
    rid = active["recovery_id"]
    manager.claim("pc1", rid, "pc1")
    manager.snapshot_ready(rid, sha256="b" * 64, cookie_count=1, created_at_epoch=time.time())
    manager.claim("pc2", rid, "pc2")
    manager.pc2_restarting(rid)
    clears = []
    monkeypatch.setattr(server, "_clear_solver_manual_required_pause", lambda **kw: clears.append(kw))
    result = server._nas_auth_recovery_result({"recovery_id": rid, "node_id": "pc2", "scope": "seed",
        "protocol_version": 2, "success": True, "probe_authenticated": True,
        "snapshot_sha256": "b" * 64, "target_url": BASE})
    assert result["status"] == "failed" and not clears
    assert manager.snapshot()["last_result"]["reason"] == "challenge_changed"


def test_legacy_seed_probe_cannot_clear_different_target(tmp_path, monkeypatch):
    server, _ = setup_server(tmp_path, monkeypatch)
    result = server._collection_observer_auth_complete_payload({
        "source": "seed_auth_probe", "scope": "seed", "target_url": BASE, "refresh_cookie_snapshot": False})
    assert result["ok"] is False and result["auth_state_confirmed"] is False
    assert result["stale_challenge"] is True


def test_challenge_target_canonicalization_preserves_region_page_and_sort():
    redirected = TARGET.replace("/list/", "//list/").replace(".htm?", ".htm/_____tmd_____/punish?") + "&x5secdata=redacted"
    assert matches_challenge_target("seed", TARGET, status(redirected))
    reordered = BASE + "?page=18&st_param=5&location_code=510302&auction_start_seg=-1&__captcha_solver_bg=1"
    assert same_auth_target("seed", TARGET, reordered)
    assert not matches_challenge_target("seed", BASE, status(redirected))
    assert not matches_challenge_target("seed", TARGET, {"challenge_id": "missing-target"})
    assert matches_challenge_target("seed", BASE, {"challenge_id": ""})
