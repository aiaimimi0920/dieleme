"""Dispatch cooldowns are temporary; captured evidence must remain durable."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.collection import detail_service


@pytest.mark.parametrize("method", ["next_task", "next_visit_task", "batch_tasks"])
def test_expired_dispatches_are_pruned_even_without_candidates(tmp_path, monkeypatch, method):
    now = datetime(2026, 9, 21, 12)
    monkeypatch.setattr(detail_service, "datetime", SimpleNamespace(datetime=SimpleNamespace(now=lambda: now)))
    archive = tmp_path / "item-old.html"
    archive.write_bytes(b"retained evidence")
    timestamps = {
        "old": now - timedelta(days=10),
        "boundary": now - timedelta(seconds=60),
        "active": now - timedelta(seconds=59),
    }
    service = detail_service.DetailCollectionService(tmp_path)
    getattr(service, method)(dispatched_tasks=timestamps, cooldown_seconds=60)
    assert timestamps == {"active": now - timedelta(seconds=59)}
    assert archive.read_bytes() == b"retained evidence"


@pytest.mark.parametrize("method", ["next_task", "next_visit_task", "batch_tasks"])
def test_cooldown_preserved_and_expired_candidate_can_be_dispatched(tmp_path, monkeypatch, method):
    now = datetime(2026, 9, 21, 12)
    monkeypatch.setattr(detail_service, "datetime", SimpleNamespace(datetime=SimpleNamespace(now=lambda: now)))
    candidates = [{"id": key, "url": "https://example.invalid/" + key} for key in ("active", "ready")]
    repository = SimpleNamespace(
        enabled=True, iter_pending_task_items=lambda **_: candidates,
        iter_pending_flat_items=lambda **_: candidates,
        counts_snapshot=lambda: {"db_total_ids": 2, "db_pending_ids": 2},
    )
    timestamps = {"active": now - timedelta(seconds=59), "ready": now - timedelta(seconds=60)}
    result = getattr(detail_service.DetailCollectionService(tmp_path, repository), method)(
        dispatched_tasks=timestamps, cooldown_seconds=60,
    )
    assert "ready" in str(result)
    assert "active" not in str(result)
    assert timestamps == {"active": now - timedelta(seconds=59), "ready": now.replace(tzinfo=timezone.utc)}
