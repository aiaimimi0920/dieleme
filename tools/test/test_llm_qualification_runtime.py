"""Cancellation must not consume model scores or publish provider requests."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from src.llm_qualification_pool import QualifiedModelPool
from src.llm_qualification_runtime import QualificationCancelled, shared_store
from tools.test.test_llm_qualification_pool import make_pool


def test_store_reuse_is_scoped_by_path_credentials_and_request_policy(tmp_path, monkeypatch):
    config = {"base_url": "https://example.test/v1", "api_key": "synthetic", "timeout": 10}
    monkeypatch.setenv("FAPAI_ANALYSIS_MODEL_POOL_PATH", str(tmp_path / "one.sqlite3"))
    with ThreadPoolExecutor(max_workers=4) as executor:
        stores = list(executor.map(lambda _: shared_store(config), range(12)))
    assert all(store is stores[0] for store in stores)
    stores[0].defer_scan(600)
    assert shared_store(config).snapshot()["next_scan"] > 0
    assert shared_store({**config, "api_key": "rotated"}) is not stores[0]
    assert shared_store({**config, "timeout": 20}) is not stores[0]
    monkeypatch.setenv("FAPAI_ANALYSIS_MODEL_POOL_PATH", str(tmp_path / "two.sqlite3"))
    assert shared_store(config) is not stores[0]
    assert (tmp_path / "one.sqlite3").exists()


def test_cancel_wakes_wait_without_network_or_model_penalty(tmp_path):
    pool = make_pool(tmp_path, {"a": 5})
    pool.ensure()
    before = pool.store.snapshot()["models"]
    calls = len(pool.session.calls)
    waiting = threading.Event()
    event = threading.Event()

    class WaitEvent:
        def is_set(self):
            return event.is_set()

        def wait(self, delay):
            waiting.set()
            return event.wait(delay)

    pool.cancel_event = WaitEvent()
    pool.store.reserve_request_slot = lambda: 5
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(pool.chat, "business evidence")
        assert waiting.wait(2)
        event.set()
        with pytest.raises(QualificationCancelled):
            future.result(timeout=2)
    assert len(pool.session.calls) == calls
    assert pool.store.snapshot()["models"] == before


def test_cancelled_scan_releases_lease_without_cooldown(tmp_path):
    pool = make_pool(tmp_path, {"a": 5})

    def stop_after_discovery():
        pool.cancel_event.set()
        return ["a"]

    pool.discover = stop_after_discovery
    with pytest.raises(QualificationCancelled):
        pool.ensure()
    state = pool.store.snapshot()
    assert state["lease"] == ""
    assert state["models"] == {}
    assert not state.get("cooldown_until")
    assert pool.store.scan_lock.acquire(blocking=False)
    pool.store.scan_lock.release()


def test_shared_store_cannot_run_two_local_scans(tmp_path):
    pool = make_pool(tmp_path, {"a": 5})
    second = QualifiedModelPool(pool.config, store=pool.store, session=pool.session)
    with pool.store.scan_lock:
        assert second.ensure() == []
    assert pool.session.calls == []
