"""Concurrent recovery must not submit duplicate work or combine unrelated receipts."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.runtime_state import RuntimeState

SEED = {"scope": "seed", "target_url": "https://sf.taobao.com/list/1.htm?page=1"}
DETAIL = {"scope": "detail", "target_url": "https://sf-item.taobao.com/sf_item/123.htm"}


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    return server


def test_concurrent_manual_retry_submits_once(runtime, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    probes = []
    submissions = []
    monkeypatch.setattr(runtime, "_manual_solver_retry_enabled", lambda: True)
    monkeypatch.setattr(runtime, "_captcha_solver_runtime_status", lambda **_: {"manual_required": True})
    monkeypatch.setattr(runtime, "_manual_solver_retry_request", lambda: dict(DETAIL))
    monkeypatch.setattr(runtime, "_solver_request_delegated_to_node", lambda _: False)
    monkeypatch.setattr(runtime, "_manual_solver_retry_next_epoch", lambda _: 0)
    monkeypatch.setattr(runtime, "_clear_solver_manual_required_pause", lambda **_: None)

    def probe(_endpoint):
        probes.append(True)
        if len(probes) == 1:
            entered.set()
            assert release.wait(5)
        return True

    monkeypatch.setattr(runtime, "_probe_solver_cdp_endpoint", probe)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(runtime._trigger_manual_solver_retry_if_due, now=100.0, submit_solver=submissions.append)
        try:
            assert entered.wait(5)
            second = runtime._trigger_manual_solver_retry_if_due(now=100.0, submit_solver=submissions.append)
        finally:
            release.set()
        result = first.result(timeout=5)
    assert result["queued"] is True
    assert second == {"queued": False, "reason": "retry_pending"}
    assert submissions == [DETAIL]
    assert runtime.RUNTIME.recovery.snapshot().retry_attempts == 1


@pytest.mark.parametrize("predates", [False, True])
def test_auth_report_uses_one_completion_receipt(runtime, monkeypatch, predates):
    runtime.RUNTIME.recovery.record_auth_completion(100.0, DETAIL, 10)
    snapshot = runtime.RUNTIME.recovery.snapshot

    def replaced_after_read():
        previous = snapshot()
        runtime.RUNTIME.recovery.record_auth_completion(200.0, SEED, 20)
        return previous

    monkeypatch.setattr(runtime.RUNTIME.recovery, "snapshot", replaced_after_read)
    if predates:
        assert not runtime._solver_report_predates_auth_completion({**SEED, "timestamp": 90.0})
    else:
        assert runtime._solver_auth_report_suppression(SEED, now=150.0) is None


def test_concurrent_scope_reports_share_one_durable_challenge(runtime):
    ready = threading.Barrier(8)

    def begin(_index):
        ready.wait(timeout=5)
        return runtime._begin_solver_challenge(dict(SEED))

    with ThreadPoolExecutor(max_workers=8) as pool:
        challenge_ids = list(pool.map(begin, range(8)))
    assert len(set(challenge_ids)) == 1
    receipt = json.loads(runtime._solver_scope_state_path("seed").read_text(encoding="utf-8"))
    assert receipt["challenge_id"] == challenge_ids[0]
    assert receipt["paused"] is True
    assert runtime._collection_scope_effectively_paused("seed")
    assert not runtime._collection_scope_effectively_paused("detail")
