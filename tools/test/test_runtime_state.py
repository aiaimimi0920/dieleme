"""RuntimeState owns mutable solver and recovery metadata."""

from types import SimpleNamespace

import pytest

from src.runtime_state import RuntimeState


def test_recovery_confirmation_store_is_copied_and_pruned():
    state = RuntimeState()
    source = {"first": 1.0}
    state.recovery.replace_confirmations(source)
    source["first"] = 99.0
    assert state.recovery.confirmation_snapshot() == {"first": 1.0}

    for index in range(256):
        state.recovery.record_confirmation(f"id-{index}", float(index))
    confirmations = state.recovery.confirmation_snapshot()
    assert len(confirmations) == 192
    assert "id-0" not in confirmations
    assert confirmations["id-255"] == 255.0


def test_runtime_components_use_the_shared_control_lock():
    state = RuntimeState()
    assert state.solver.lock is state.lock
    assert state.recovery.lock is state.lock
    assert state.control.lock is state.lock
    state.cookie_snapshot.update({"status": "pending"})
    assert state.cookie_snapshot.snapshot()["status"] == "pending"
    assert state.cookie_snapshot.active_thread() is None
    assert state.processing.snapshot() == frozenset()


def test_scope_pause_decision_uses_one_control_snapshot(monkeypatch):
    from src import server

    state = RuntimeState()
    monkeypatch.setattr(server, "RUNTIME", state)
    snapshots = iter(
        (
            SimpleNamespace(paused=False, reason="manual_required"),
            SimpleNamespace(paused=True, reason="operator"),
        )
    )
    snapshot_reads = []

    def snapshot():
        snapshot_reads.append(None)
        return next(snapshots)

    monkeypatch.setattr(state.control, "snapshot", snapshot)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_exists", lambda: False)
    monkeypatch.setattr(server, "_normalize_challenge_scope", lambda _scope: "seed")
    monkeypatch.setattr(server, "_solver_scope_runtime_status", lambda _scope: {})

    assert server._collection_scope_effectively_paused("seed") is True
    assert len(snapshot_reads) == 1


def test_auth_helpers_read_the_injected_runtime(monkeypatch):
    from src import server

    state = RuntimeState()
    state.cookie_snapshot.update({"completion_id": "current", "status": "pending"})
    state.recovery.record_confirmation("current", 42.0)
    monkeypatch.setattr(server, "RUNTIME", state)

    assert server._auth_completion_recovery_state() is state.recovery
    assert server._auth_completion_recovery_state().confirmation_snapshot() == {"current": 42.0}
    assert server._auth_cookie_snapshot_runtime_state() is state.cookie_snapshot
    assert server._auth_cookie_snapshot_runtime_status()["completion_id"] == "current"


def test_runtime_index_owns_collection_containers():
    state = RuntimeState()
    state.collection.seen_ids["item"] = {"data": {"id": "item"}}
    assert state.collection.snapshot() == (
        {"item": {"data": {"id": "item"}}},
        (),
    )
    assert state.collection.queue_pending("item") is True
    assert state.collection.queue_pending("item") is False
    state.collection.set_seen("item", {"data": {"is_processed": False}})
    state.collection.mark_dispatched("item", 123.0)
    assert state.collection.dispatched_tasks["item"] == 123.0
    assert state.collection.prune_processed_pending() == 0
    state.collection.queue_pending("missing")
    assert state.collection.prune_unavailable_pending() == 1
    state.collection.remove_pending("item")
    assert state.collection.snapshot()[1] == ()


def test_get_item_reads_runtime_index_inside_its_lock(monkeypatch):
    from threading import Lock

    from src import server

    lock = Lock()

    class GuardedSeenIds(dict):
        def _assert_lock_held(self):
            if lock.acquire(blocking=False):
                lock.release()
                pytest.fail("runtime index access must hold its shared lock")

        def __contains__(self, key):
            self._assert_lock_held()
            return super().__contains__(key)

        def get(self, key, default=None):
            self._assert_lock_held()
            return super().get(key, default)

    runtime_index = SimpleNamespace(
        lock=lock,
        seen_ids=GuardedSeenIds({"item-1": {"data": {"id": "item-1"}}}),
    )
    response = []
    errors = []
    handler = SimpleNamespace(
        path="/api/get_item?id=item-1",
        send_json=response.append,
        send_error_json=lambda **kwargs: errors.append(kwargs),
    )
    monkeypatch.setattr(server, "_collection_runtime_index", lambda: runtime_index)
    monkeypatch.setattr(server, "DB_REPOSITORY", SimpleNamespace(enabled=False))

    server._get_item(handler, None, None, {})

    assert response == [{"id": "item-1"}]
    assert errors == []


def test_next_visit_snapshots_runtime_index_inside_its_lock(monkeypatch):
    from threading import Lock

    from src import server

    lock = Lock()

    class GuardedSeenIds(dict):
        def items(self):
            if lock.acquire(blocking=False):
                lock.release()
                pytest.fail("runtime index access must hold its shared lock")
            return super().items()

    runtime_index = SimpleNamespace(
        lock=lock,
        seen_ids=GuardedSeenIds(
            {"item-1": {"data": {"url": "https://example.invalid/item"}}}
        ),
        dispatched_tasks={},
    )
    service_calls = []
    response = []
    handler = SimpleNamespace(
        send_json=response.append,
        send_error_json=lambda **kwargs: pytest.fail(str(kwargs)),
    )

    class Service:
        def next_visit_task(self, **kwargs):
            service_calls.append(kwargs)
            return {"task_type": "none"}

    monkeypatch.setattr(server, "_collection_runtime_index", lambda: runtime_index)
    monkeypatch.setattr(server, "_read_json_body", lambda _handler: (True, {}))
    monkeypatch.setattr(server, "_prefer_db_task_reads", lambda: False)
    monkeypatch.setattr(server, "_detail_collection_service", lambda: Service())

    server._post_detail_next_visit(handler)

    assert service_calls[0]["legacy_entries"] == [
        ("item-1", {"data": {"url": "https://example.invalid/item"}})
    ]
    assert response == [{"task_type": "none"}]


def test_runtime_replacement_keeps_its_own_index(monkeypatch):
    from src import server

    first = RuntimeState()
    first.collection.seen_ids["first"] = {}
    first.collection.pending_tasks.append("first")
    second = RuntimeState()
    second.collection.seen_ids["second"] = {}
    second.collection.pending_tasks.append("second")
    monkeypatch.setattr(server, "RUNTIME", first)
    assert server._collection_runtime_index() is first.collection
    monkeypatch.setattr(server, "RUNTIME", second)
    assert server._collection_runtime_index().snapshot() == ({"second": {}}, ("second",))
    assert first.collection.snapshot() == ({"first": {}}, ("first",))


def test_runtime_lifecycle_starts_uninitialized_with_a_stable_clock():
    state = RuntimeState()
    assert state.initialized is False
    assert state.started_at > 0


def test_runtime_index_clear_resets_dispatch_cooldowns():
    state = RuntimeState()
    state.collection.seen_ids["item"] = {"data": {"id": "item"}}
    state.collection.pending_tasks.append("item")
    state.collection.dispatched_tasks["item"] = 123.0

    state.collection.clear()

    assert state.collection.seen_ids == {}
    assert state.collection.pending_tasks == []
    assert state.collection.dispatched_tasks == {}


@pytest.mark.parametrize("handler_name", ["_post_area_result", "_post_approve_area"])
def test_area_handlers_use_the_injected_runtime_pending_queue(
    monkeypatch, handler_name
):
    from src import server

    state = RuntimeState()
    monkeypatch.setattr(server, "RUNTIME", state)
    pending_tasks = ["item-1"]
    captured = {}

    class DetailService:
        def apply_working_item_patch(self, **kwargs):
            captured.update(kwargs)
            return {"status": "ok"}

    response = []
    handler = SimpleNamespace(
        send_json=response.append,
        send_error_json=lambda **_kwargs: pytest.fail("unexpected handler error"),
    )
    monkeypatch.setattr(state.collection, "pending_tasks", pending_tasks)
    monkeypatch.setattr(
        server, "_read_json_body", lambda _handler: (True, {"id": "item-1"})
    )
    monkeypatch.setattr(server, "_detail_collection_service", lambda: DetailService())

    getattr(server, handler_name)(handler)

    assert captured["pending_tasks"] is pending_tasks
    assert state.collection.pending_tasks is pending_tasks
    assert response == [{"status": "ok"}]


def test_runtime_initialization_side_effects_run_once_under_concurrent_calls(
    monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    from src import server

    runtime = RuntimeState()
    monkeypatch.setattr(server, "RUNTIME", runtime)
    restore_entered = Event()
    second_restore_entered = Event()
    release_first_restore = Event()
    restore_count = 0
    count_lock = Lock()

    def restore_solver_challenge_state():
        nonlocal restore_count
        with count_lock:
            restore_count += 1
            call_number = restore_count
        if call_number == 1:
            restore_entered.set()
            assert release_first_restore.wait(timeout=5)
        else:
            second_restore_entered.set()
        return False

    monkeypatch.setattr(
        server,
        "_restore_solver_challenge_state",
        restore_solver_challenge_state,
    )
    monkeypatch.setattr(server, "_restore_solver_scope_states", lambda: False)
    monkeypatch.setattr(server, "cleanup_orphaned_files", lambda: None)
    monkeypatch.setattr(server, "load_data", lambda: None)
    monkeypatch.setattr(
        server,
        "DB_REPOSITORY",
        SimpleNamespace(enabled=False, initialize=lambda: None),
    )
    monkeypatch.setattr(server, "manual_solver_retry_thread", lambda: None)
    monkeypatch.setattr(server, "_manual_solver_retry_interval_seconds", lambda: 1)
    monkeypatch.setattr(server, "_manual_solver_retry_poll_seconds", lambda: 1)
    monkeypatch.setattr(server, "_sample_nas_auth_recovery", lambda: None)
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", SimpleNamespace(enabled=False))

    started_targets = []

    class FakeThread:
        def __init__(self, *, target, daemon):
            started_targets.append((target, daemon))

        def start(self):
            return None

    monkeypatch.setattr(server, "threading", SimpleNamespace(Thread=FakeThread))

    def initialize():
        server.initialize_runtime()

    second_called = Event()
    second_future = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(initialize)
        try:
            assert restore_entered.wait(timeout=5)

            def initialize_second():
                second_called.set()
                initialize()

            second_future = pool.submit(initialize_second)
            assert second_called.wait(timeout=5)
            assert not second_restore_entered.wait(timeout=0.1)
        finally:
            release_first_restore.set()

        first_future.result(timeout=5)
        if second_future is not None:
            second_future.result(timeout=5)

    assert restore_count == 1
    assert len(started_targets) == 1
    assert runtime.initialized is True
