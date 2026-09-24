from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import requests

from src import llm_openai_compatible as backend
from src.llm_request_policy import MAX_OUTPUT_TOKENS, retry_delay


pytestmark = pytest.mark.security


def response(status, headers=None):
    result = requests.Response()
    result.status_code = status
    result.headers.update(headers or {})
    result._content = b'{"choices":[{"message":{"content":"ok"}}]}'
    return result


def run_chat(monkeypatch, responses, calls, sleeps, models=None):
    def post(_url, **kwargs):
        calls.append(kwargs["json"])
        return responses.pop(0)
    monkeypatch.setattr(backend.requests, "Session", lambda: SimpleNamespace(post=post))
    monkeypatch.setattr(backend.time, "sleep", sleeps.append)
    return backend._chat_with_openai_compatible("evidence", {
        "base_url": "http://127.0.0.1:9999/v1", "api_key": "synthetic", "model": "first",
        "models": models or ["first", "second"], "timeout": 1, "max_retries": 3,
    })


def test_rate_limit_waits_before_retry_and_does_not_fan_out(monkeypatch):
    calls, sleeps = [], []
    assert run_chat(monkeypatch, [response(429, {"Retry-After": "7"}), response(200)], calls, sleeps) == "ok"
    assert [call["model"] for call in calls] == ["first", "first"]
    assert sleeps == [7]
    assert all(call["max_tokens"] == MAX_OUTPUT_TOKENS for call in calls)


def test_forbidden_models_are_not_retried_each_round(monkeypatch):
    calls, sleeps = [], []
    assert run_chat(monkeypatch, [response(403), response(503), response(200)], calls, sleeps) == "ok"
    assert [call["model"] for call in calls] == ["first", "second", "second"]


def test_long_provider_cooldown_fails_without_early_retry(monkeypatch):
    calls, sleeps = [], []
    with pytest.raises(requests.HTTPError):
        run_chat(monkeypatch, [response(429, {"Retry-After": "3600"})], calls, sleeps)
    assert len(calls) == 1
    assert sleeps == []


def test_retry_after_date_and_invalid_values():
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    assert retry_delay({"Retry-After": "Sun, 20 Sep 2026 00:00:09 GMT"}, 1, now=now) == 9
    for value in ["NaN", "Infinity", "bad date", "-1"]:
        assert retry_delay({"Retry-After": value}, 2, now=now) == 2
