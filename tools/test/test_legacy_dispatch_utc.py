from datetime import datetime, timezone
from threading import RLock
from types import SimpleNamespace

from src import server


def test_dispatch_timestamp_normalization_handles_naive_and_aware_values():
    naive = datetime(2026, 9, 22, 12, 0, 0)
    aware = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)

    assert server._as_utc_timestamp(naive) == aware
    assert server._as_utc_timestamp(aware) == aware


def test_legacy_detail_next_task_skips_recent_aware_dispatch(monkeypatch):
    responses = []
    handler = SimpleNamespace(send_json=responses.append)
    monkeypatch.setattr(server, "_read_json_body", lambda _handler: (True, {}))
    monkeypatch.setattr(server, "_prefer_db_task_reads", lambda: False)
    monkeypatch.setattr(server, "PENDING_TASKS", ["item-1"])
    monkeypatch.setattr(
        server.RUNTIME.collection, "seen_ids", {"item-1": {"data": {"url": "https://example.test/item-1"}}}
    )
    monkeypatch.setattr(server, "DISPATCHED_TASKS", {"item-1": server._utc_now()})
    monkeypatch.setattr(server, "DATA_LOCK", RLock())

    server._post_detail_next_task(handler)

    assert responses == [{}]


def test_legacy_detail_batch_skips_recent_aware_dispatch(monkeypatch):
    responses = []
    handler = SimpleNamespace(send_json=responses.append)
    monkeypatch.setattr(server, "_read_json_body", lambda _handler: (True, {}))
    monkeypatch.setattr(server, "_prefer_db_task_reads", lambda: False)
    monkeypatch.setattr(
        server, "_collection_scope_effectively_paused", lambda _scope: False
    )
    monkeypatch.setattr(server, "PENDING_TASKS", ["item-1"])
    monkeypatch.setattr(
        server.RUNTIME.collection, "seen_ids", {"item-1": {"data": {"url": "https://example.test/item-1"}}}
    )
    monkeypatch.setattr(server, "DISPATCHED_TASKS", {"item-1": server._utc_now()})
    monkeypatch.setattr(server, "DATA_LOCK", RLock())

    server._post_detail_tasks(handler)

    assert responses == [{"tasks": [], "total": 1, "done": 0}]
