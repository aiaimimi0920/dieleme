from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event, Lock

import pytest

from src.collection.detail_service import DetailCollectionService


class _Repo:
    enabled = True

    def iter_pending_task_items(self, *, limit: int):
        return [
            {
                "id": "same-item",
                "url": "https://example.invalid/item",
            }
        ]

    def iter_pending_flat_items(self, *, limit: int):
        return [
            {
                "id": "same-item",
                "url": "https://example.invalid/item",
                "is_processed": False,
            }
        ]


def test_next_visit_task_does_not_dispatch_same_item_twice_concurrently(
    tmp_path,
) -> None:
    service = DetailCollectionService(tmp_path, repository=_Repo())
    dispatched: dict[str, datetime] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: service.next_visit_task(
                    dispatched_tasks=dispatched, cooldown_seconds=60
                ),
                range(2),
            )
        )

    assert sum(result.get("task_type") == "visit" for result in results) == 1
    assert sum(result.get("task_type") == "none" for result in results) == 1


def test_dispatch_uses_the_injected_runtime_state_lock(tmp_path) -> None:
    backing_lock = Lock()
    lock_attempted = Event()

    class ObservedLock:
        def __enter__(self):
            lock_attempted.set()
            backing_lock.acquire()
            return self

        def __exit__(self, *_exc):
            backing_lock.release()

    service = DetailCollectionService(tmp_path, dispatch_lock=ObservedLock())
    with ThreadPoolExecutor(max_workers=1) as pool:
        backing_lock.acquire()
        try:
            future = pool.submit(
                service.next_visit_task,
                dispatched_tasks={},
                cooldown_seconds=60,
                legacy_entries=[],
            )
            assert lock_attempted.wait(timeout=1)
            assert not future.done()
        finally:
            backing_lock.release()
        assert future.result(timeout=1) == {"task_type": "none"}


def test_next_task_accepts_runtime_state_lock_per_call(tmp_path) -> None:
    backing_lock = Lock()
    lock_attempted = Event()

    class ObservedLock:
        def __enter__(self):
            lock_attempted.set()
            backing_lock.acquire()
            return self

        def __exit__(self, *_exc):
            backing_lock.release()

    service = DetailCollectionService(tmp_path, repository=_Repo())
    with ThreadPoolExecutor(max_workers=1) as pool:
        backing_lock.acquire()
        try:
            future = pool.submit(
                service.next_task,
                dispatched_tasks={},
                cooldown_seconds=60,
                dispatch_lock=ObservedLock(),
            )
            assert lock_attempted.wait(timeout=1)
            assert not future.done()
        finally:
            backing_lock.release()
        assert future.result(timeout=1) == {"url": "https://example.invalid/item"}


@pytest.mark.parametrize("operation", ["submit_html", "apply_working_item_patch"])
def test_detail_updates_remove_pending_tasks_under_runtime_lock(tmp_path, operation):
    lock = Lock()

    class GuardedPendingTasks(list):
        def _assert_lock_held(self):
            if lock.acquire(blocking=False):
                lock.release()
                pytest.fail("pending task mutations must hold the runtime index lock")

        def __contains__(self, item):
            self._assert_lock_held()
            return super().__contains__(item)

        def remove(self, item):
            self._assert_lock_held()
            return super().remove(item)

    class Adapter:
        def sync_record(self, _record):
            return None

    service = DetailCollectionService(tmp_path, adapter=Adapter(), dispatch_lock=lock)
    pending_tasks = GuardedPendingTasks(["item-1"])
    working_item = {
        "data": {},
        "cached": True,
        "file_path": str(tmp_path / "item.json"),
    }
    common = {
        "item_id": "item-1",
        "get_working_item": lambda *_args, **_kwargs: working_item,
        "apply_flat_override_patch": lambda *_args: None,
        "reset_structured_sections_for_resync": lambda *_args: None,
        "update_file_global": lambda *_args: None,
        "persist_item_to_db": lambda *_args: None,
        "evict_runtime_item": lambda *_args: None,
        "prefer_db_task_reads": lambda: False,
        "pending_tasks": pending_tasks,
    }
    if operation == "submit_html":
        result = service.submit_html(
            html_content="<html></html>",
            status="complete",
            submit_task=lambda _path: None,
            **common,
        )
    else:
        result = service.apply_working_item_patch(
            patch_data={}, event_type="test", **common
        )

    assert result["status"] in {"queued", "ok"}
    assert pending_tasks == []


def test_detail_updates_can_use_runtime_index_remove_callback(tmp_path) -> None:
    removed: list[str] = []

    class Adapter:
        def sync_record(self, _record):
            return None

    service = DetailCollectionService(tmp_path, adapter=Adapter())
    working_item = {
        "data": {},
        "cached": True,
        "file_path": str(tmp_path / "item.json"),
    }
    result = service.apply_working_item_patch(
        item_id="item-1",
        patch_data={},
        event_type="test",
        get_working_item=lambda *_args, **_kwargs: working_item,
        apply_flat_override_patch=lambda *_args: None,
        reset_structured_sections_for_resync=lambda *_args: None,
        update_file_global=lambda *_args: None,
        persist_item_to_db=lambda *_args: None,
        evict_runtime_item=lambda *_args: None,
        prefer_db_task_reads=lambda: False,
        pending_tasks=[],
        remove_pending=lambda item_id: removed.append(item_id),
    )

    assert result["status"] == "ok"
    assert removed == ["item-1"]
