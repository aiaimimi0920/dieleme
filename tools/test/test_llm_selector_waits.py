"""Capacity wait cancellation must never grant or leak an unavailable slot."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from src.llm_model_selector import LLMBackendUnavailableError, ModelSelector


@pytest.mark.parametrize("specific", [False, True])
def test_expired_or_cancelled_wait_never_acquires_capacity(specific):
    selector = ModelSelector([{"name": "a", "max_concurrent": 1}])
    acquire = (lambda **kwargs: selector.acquire("a", **kwargs)) if specific else selector.acquire_any
    with pytest.raises(LLMBackendUnavailableError, match="deadline"):
        acquire(deadline=time.monotonic() - 1)
    event = threading.Event()
    event.set()
    with pytest.raises(LLMBackendUnavailableError, match="cancelled"):
        acquire(cancel_event=event)
    assert selector.active_counts == {"a": 0}


@pytest.mark.parametrize("specific", [False, True])
def test_waiter_wakes_on_cancellation_without_leaking_slot(specific):
    selector = ModelSelector([{"name": "a", "max_concurrent": 1}])
    selector.acquire("a")
    event = threading.Event()
    waiting = threading.Event()
    original_wait = selector.condition.wait

    def wait(timeout):
        waiting.set()
        return original_wait(timeout)

    selector.condition.wait = wait
    acquire = (lambda: selector.acquire("a", cancel_event=event)) if specific else (
        lambda: selector.acquire_any(cancel_event=event))
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(acquire)
        assert waiting.wait(2)
        event.set()
        with pytest.raises(LLMBackendUnavailableError, match="cancelled"):
            future.result(timeout=2)
    assert selector.active_counts == {"a": 1}
    selector.release("a")
    assert selector.active_counts == {"a": 0}


def test_disabled_waiter_and_unknown_model_fail_without_mutating_counters():
    selector = ModelSelector([{"name": "a", "max_concurrent": 1}])
    selector.acquire("a")
    with pytest.raises(LLMBackendUnavailableError):
        selector.acquire("unknown")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(selector.acquire, "a")
        selector.disable_model("a", "synthetic authentication failure")
        with pytest.raises(LLMBackendUnavailableError):
            future.result(timeout=2)
    assert selector.active_counts == {"a": 1}
    with pytest.raises(LLMBackendUnavailableError):
        selector.get_next("community_search")
    with pytest.raises(LLMBackendUnavailableError):
        ModelSelector([]).get_next("community_search")
