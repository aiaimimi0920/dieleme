import json
import time
from email.utils import formatdate

import pytest

from src.llm_model_selector import LLMBackendUnavailableError
from src.llm_qualification_store import QualificationStore
from tools.test.test_llm_qualification_pool import Response, make_pool


@pytest.mark.parametrize("probe", [False, True])
@pytest.mark.parametrize("effort", [None, "none", "low"])
def test_requests_preserve_configured_reasoning(tmp_path, probe, effort):
    pool = make_pool(tmp_path, {"a": 5}, reasoning_effort=effort)
    payloads = []
    original = pool.session.post

    def capture(url, **kwargs):
        payloads.append(kwargs["json"])
        return original(url, **kwargs)

    pool.session.post = capture
    pool.request("a", "test", probe=probe)
    if effort is None:
        assert "reasoning_effort" not in payloads[0]
    else:
        assert payloads[0]["reasoning_effort"] == effort
    assert ("max_tokens" in payloads[0]) is probe


@pytest.mark.parametrize("settings", [{"reasoning_effort": "none"}, {"timeout": 60}])
def test_request_settings_cannot_reuse_a_different_qualification(tmp_path, settings):
    old = make_pool(tmp_path, {"a": 5})
    old.ensure()
    new = make_pool(tmp_path, {"a": 5}, **settings)
    assert new.store.key != old.store.key
    assert new.available() == []
    assert old.available() == ["a"]
    assert b"test-key" not in new.store.path.read_bytes()


def test_five_cases_and_business_requests_use_nonreasoning_mode(tmp_path):
    pool = make_pool(tmp_path, {"a": 5}, reasoning_effort="none")
    original = pool.session.post

    def backend(url, **kwargs):
        if kwargs["json"].get("reasoning_effort") != "none":
            return Response({"choices": [{"message": {"content": "", "reasoning_content": "thinking"}}]})
        return original(url, **kwargs)

    pool.session.post = backend
    assert pool.ensure() == ["a"]
    assert pool.store.snapshot()["models"]["a"]["matches"] == [1, 1, 1, 1, 1]
    assert pool.chat("real item") == "production"


def test_shared_slots_bound_all_workers_and_preserve_server_cooldown(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    config = {"base_url": "https://models.example.test/v1", "api_key": "fixture"}
    stores = [QualificationStore(config, tmp_path / "pool.sqlite3") for _ in range(4)]
    assert stores[0].claim()
    starts = []
    for i in range(16):
        delay = stores[i % 4].reserve_request_slot()
        if delay:
            clock[0] += delay
            assert stores[i % 4].reserve_request_slot() == 0
        starts.append(clock[0])
    assert starts == [1000 + i * 4 for i in range(16)]
    assert sum(start < 1060 for start in starts) == 15
    stores[1].cool_down(600)
    assert all(store.reserve_request_slot() is None for store in stores)
    stores[0].finish(0)
    assert stores[0].snapshot()["next_scan"] >= 1660
    assert not stores[2].claim()
    clock[0] = 1660
    assert stores[2].claim()
    assert stores[2].reserve_request_slot() == 0


@pytest.mark.parametrize("phase", ["qualification", "business"])
def test_rate_limit_stops_alias_fanout_without_scoring_or_disabling_models(tmp_path, phase):
    pool = make_pool(tmp_path, {"a": 5, "b": 5})
    if phase == "business":
        pool.ensure()
    before = pool.store.snapshot()["models"]
    calls = []

    def limited(*_args, **_kwargs):
        calls.append(1)
        response = Response({"error": {"message": "secret provider body"}})
        response.status_code = 429
        response.headers = {"Retry-After": "600"}
        return response

    pool.session.post = limited
    if phase == "qualification":
        assert pool.ensure() == []
    else:
        with pytest.raises(LLMBackendUnavailableError):
            pool.chat("real item")
    state = pool.store.snapshot()
    assert calls == [1]
    assert state["models"] == before
    assert state["cooldown_until"] > time.time() + 590
    assert state["next_scan"] >= state["cooldown_until"]
    assert pool.available() == []
    assert pool.refresh_in_background() == []
    assert "secret provider body" not in json.dumps(state)


@pytest.mark.parametrize("configured,expected", [(180, 60), (30, 30), (10, 10)])
def test_probe_timeout_respects_config_with_a_bounded_cap(tmp_path, configured, expected):
    pool = make_pool(tmp_path, {"a": 5}, timeout=configured)
    options = []
    original = pool.session.post

    def capture(url, **kwargs):
        options.append(kwargs)
        return original(url, **kwargs)

    pool.session.post = capture
    pool.request("a", "test", probe=True)
    assert options[0]["timeout"] == expected


@pytest.mark.parametrize("header,seconds", [("120", 120), ("invalid", 60), (None, 60),
    (formatdate(1125, usegmt=True), 125)])
def test_retry_after_is_preserved_and_response_is_closed(header, seconds, monkeypatch):
    from src.llm_qualification_transport import ModelRateLimitedError, request_json

    monkeypatch.setattr(time, "time", lambda: 1000)
    response = Response({})
    response.status_code = 429
    response.headers = {"Retry-After": header} if header else {}
    closed = []
    response.close = lambda: closed.append(True)

    class Session:
        def post(self, *_args, **_kwargs):
            return response

    with pytest.raises(ModelRateLimitedError) as failure:
        request_json(Session(), "post", "https://models.example.test", timeout=10, max_bytes=64)
    assert failure.value.retry_after_seconds == seconds
    assert closed == [True]


@pytest.mark.parametrize("status,minimum", [(400, 600), (403, 3600), (408, 600), (500, 600), (503, 600)])
def test_failed_probe_is_unscored_and_stops_before_account_abuse_limit(tmp_path, status, minimum):
    pool = make_pool(tmp_path, {"a": 5, "b": 5})
    calls = []

    def unavailable(*_args, **_kwargs):
        calls.append(1)
        response = Response({"error": "private provider detail"})
        response.status_code = status
        return response

    pool.session.post = unavailable
    assert pool.ensure() == []
    assert calls == [1]
    state = pool.store.snapshot()
    row = next(iter(state["models"].values()))
    assert row["score"] is None and row["status"] == "probe_error"
    assert row["matches"] == []
    assert state["next_scan"] > time.time() + minimum - 5
    assert "private provider detail" not in json.dumps(state)
    assert pool.ensure() == []
    assert calls == [1]


def test_catalog_rate_limit_preserves_retry_after(tmp_path):
    pool = make_pool(tmp_path, {"a": 5})
    response = Response({})
    response.status_code = 429
    response.headers = {"Retry-After": "7200"}
    pool.session.get = lambda *_args, **_kwargs: response
    assert pool.ensure() == []
    state = pool.store.snapshot()
    assert state["models"] == {}
    assert state["next_scan"] > time.time() + 7190
    assert state["cooldown_until"] == state["next_scan"]


@pytest.mark.parametrize("phase", ["qualification", "business"])
def test_slot_wait_is_bounded_without_poisoning_model_scores(tmp_path, monkeypatch, phase):
    pool = make_pool(tmp_path, {"a": 5})
    if phase == "business":
        pool.ensure()
    before = pool.store.snapshot()["models"]
    calls = len(pool.session.calls)
    pool.store.reserve_request_slot = lambda: 500
    monkeypatch.setattr(time, "sleep", lambda _: pytest.fail("unbounded wait"))
    if phase == "qualification":
        assert pool.ensure() == []
    else:
        with pytest.raises(LLMBackendUnavailableError):
            pool.chat("real item")
    assert len(pool.session.calls) == calls
    assert pool.store.snapshot()["models"] == before
    assert not pool.store.snapshot().get("cooldown_until")
