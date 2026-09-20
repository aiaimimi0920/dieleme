"""Detail progress cannot hide a blocked seed page from recovery coordination."""
import io
import json
from types import SimpleNamespace

import pytest

SEED = "https://sf.taobao.com/list/50025969__2.htm?location_code=510302&page=18"
DETAIL = "https://sf-item.taobao.com/sf_item/123456789.htm"


def request(target):
    return {"node_id": "pc2", "cdp_endpoint": "http://browser.test:9224", "target_url": target}


@pytest.fixture
def server(monkeypatch):
    from src import server

    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_COMPLETED_TIME", 100.0)
    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_DETAIL_CAPTURED_COUNT", 10)
    monkeypatch.setattr(server, "SOLVER_AUTH_REPORT_GRACE_SECONDS", 90.0)
    monkeypatch.setattr(server, "SOLVER_DETAIL_PROGRESS_GRACE_SECONDS", 180.0)
    monkeypatch.setattr(server, "SOLVER_DETAIL_PROGRESS_GRACE_MIN_ITEMS", 1)
    monkeypatch.setattr(server, "_solver_detail_captured_count", lambda: 110)
    return server


@pytest.mark.parametrize("completed", [request(DETAIL), {"node_id": "pc2"}])
@pytest.mark.parametrize("now", [150.0, 220.0])
def test_detail_or_unscoped_completion_never_suppresses_seed(server, monkeypatch, completed, now):
    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_COMPLETED_REQUEST", completed)
    assert server._solver_auth_report_suppression(request(SEED), now=now) is None
    assert not server._solver_report_predates_auth_completion({**request(SEED), "timestamp": 99.0})


def test_seed_grace_requires_the_verified_region_and_page(server, monkeypatch):
    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_COMPLETED_REQUEST", request(SEED))
    assert server._solver_auth_report_suppression(request(SEED), now=150)["reason"] == "recent_auth_complete"
    assert server._solver_auth_report_suppression(request(SEED.replace("page=18", "page=19")), now=150) is None
    assert server._solver_auth_report_suppression(request(SEED), now=220) is None


def test_detail_progress_still_protects_detail_recovery(server, monkeypatch):
    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_COMPLETED_REQUEST", request(DETAIL))
    result = server._solver_auth_report_suppression(request(DETAIL), now=220)
    assert result["reason"] == "recent_detail_progress"
    assert result["captured_since_auth"] == 100
    assert server._solver_auth_report_suppression(request(DETAIL), now=281) is None


def test_seed_report_reaches_manual_handoff_while_details_advance(server, monkeypatch):
    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_COMPLETED_REQUEST", request(DETAIL))
    monkeypatch.setattr(server, "time", SimpleNamespace(time=lambda: 150.0))
    monkeypatch.setattr(server, "_solver_report_stale_challenge_id", lambda _: None)
    monkeypatch.setattr(server, "_solver_force_reset_report_suppression", lambda _: None)
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", lambda: {})
    reports = []
    monkeypatch.setattr(server, "_manual_only_captcha_report_payload",
                        lambda payload: reports.append(payload) or {"status": "manual_required"})
    body = json.dumps({**request(SEED), "scope": "seed", "timestamp": 120}).encode()
    outputs = []
    handler = SimpleNamespace(path="/api/report_manual_captcha", headers={"Content-Length": str(len(body))},
                              rfile=io.BytesIO(body), send_json=outputs.append)
    server._server_post_branch_24(handler)
    assert outputs == [{"status": "manual_required"}]
    assert reports[0]["target_url"] == SEED


@pytest.mark.parametrize("legacy", [False, True])
def test_exhausted_seed_challenge_exposes_manual_recovery_without_blocking_details(server, monkeypatch, tmp_path, legacy):
    from tools import seed_collector

    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "SOLVER_SCOPE_STATE_ROOT", None)
    monkeypatch.setattr(server, "SOLVER_SCOPE_STATES", {scope: server._new_solver_scope_state() for scope in server.CHALLENGE_SCOPES})
    for name, value in {"SOLVER_LAST_REQUEST": {}, "SOLVER_CHALLENGE_ID": None,
                        "SOLVER_LAST_STATUS": "idle", "SOLVER_RUNNING": False,
                        "SOLVER_PENDING_TOKEN": None, "PAUSED": False, "COLLECTION_PAUSE_REASON": None}.items():
        monkeypatch.setattr(server, name, value)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_exists", lambda: False)
    before_detail = server._solver_scope_runtime_status("detail")
    if legacy:
        state = {**server._new_solver_scope_state(), "challenge_id": "persisted-seed-challenge",
                 "paused": True, "manual_required": False, "last_status": "node_solver_blocked",
                 "node_solver_blocked": True, "node_solver_blocked_reason": "repeated_solver_failures",
                 "last_request": request(SEED)}
        assert server._persist_solver_scope_state("seed", state) is None
    else:
        server._node_solver_blocked_report_payload({**request(SEED), "scope": "seed",
            "node_solver_blocked": True, "node_solver_blocked_attempts": 10})
        assert server._read_solver_scope_state("seed")["manual_required"] is True
    status = server._solver_scope_runtime_status("seed")
    assert status["paused"] and status["manual_required"] and status["manual_only"]
    pause = seed_collector._normalize_collection_pause_state({"collection_scopes": {"seed": status}})
    assert pause["reason"] == "captcha_solver_manual_required"
    assert server._solver_scope_runtime_status("detail") == before_detail
