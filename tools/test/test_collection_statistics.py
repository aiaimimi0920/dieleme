from concurrent.futures import ThreadPoolExecutor

from src.collection_statistics import StatisticsCache, unique_counts


def test_unique_counts_exclude_occurrences_and_include_all_captured_states():
    assert unique_counts({"seed_item_pending_detail": 10, "seed_item_raw_detail_captured": 4,
                          "seed_item_analysis_failed": 2, "seed_item_analysis_blocked": 1,
                          "seed_item_analysis_in_progress": 3, "seed_item_detail_completed": 5,
                          "seed_occurrence_total": 999}) == [25, 15, 5]


def test_shared_ttl_history_and_copy_isolation():
    now = [0.0]
    cache = StatisticsCache(clock=lambda: now[0], wall_clock=lambda: 1000 + now[0])
    owner = object()
    calls = []

    def load():
        calls.append(now[0])
        return {"seed_item_pending_detail": 100 + int(now[0]), "seed_item_detail_completed": 5}

    first = cache.snapshot(owner, load)
    first["counts"].clear()
    now[0] = 10
    assert cache.snapshot(owner, load)["counts"]["seed_item_pending_detail"] == 100
    now[0] = 60
    result = cache.snapshot(owner, load)
    assert calls == [0, 60]
    assert result["metadata"]["minute_delta"] == [60, 0, 0]
    assert result["metadata"]["window_seconds"] == 60
    assert cache.snapshot(owner, load)["metadata"] == result["metadata"]
    now[0] = 151
    assert cache.snapshot(owner, load)["metadata"]["minute_delta"] == [None] * 3


def test_failed_refresh_is_bounded_stale_and_redacted_then_recovers():
    now = [0.0]
    cache = StatisticsCache(clock=lambda: now[0])
    owner = object()
    cache.snapshot(owner, lambda: {"seed_item_pending_detail": 2})
    calls = []

    def fail():
        calls.append(1)
        raise RuntimeError("secret connection string")

    now[0] = 15
    result = cache.snapshot(owner, fail)
    assert result["counts"]["seed_item_pending_detail"] == 2
    assert result["metadata"]["stale"] is True
    assert result["metadata"]["error_type"] == "RuntimeError"
    assert "secret" not in str(result)
    now[0] = 20
    cache.snapshot(owner, fail)
    assert len(calls) == 1
    now[0] = 30
    assert cache.snapshot(owner, lambda: {})["metadata"]["stale"] is False


def test_owner_change_clock_reset_and_invalid_counts_do_not_reuse_snapshot():
    now = [100.0]
    cache = StatisticsCache(clock=lambda: now[0])
    owner = object()
    cache.snapshot(owner, lambda: {"seed_item_pending_detail": 2})
    assert not cache.snapshot(object(), lambda: {"bad": -1})["metadata"]["valid"]
    cache.snapshot(owner, lambda: {})
    now[0] = 0
    assert cache.snapshot(owner, lambda: {"seed_item_pending_detail": 9})["counts"] == {"seed_item_pending_detail": 9}


def test_parallel_requests_share_one_database_load():
    cache = StatisticsCache()
    owner, calls = object(), []

    def load():
        calls.append(1)
        return {"seed_item_pending_detail": 1}

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: cache.snapshot(owner, load), range(32)))
    assert len(calls) == 1
    assert all(result["counts"]["seed_item_pending_detail"] == 1 for result in results)
