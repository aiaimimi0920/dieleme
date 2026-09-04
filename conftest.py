from __future__ import annotations

import copy
from collections.abc import Iterator
from pathlib import Path
import time
from typing import Any

import pytest


_AVM_HTTP_CONTRACT = "test_avm_http_contract.py"
_HYBRID_SEED_TEST = "test_run_hybrid_seed_collection.py"
_STATEFUL_TERMS = (
    "captcha",
    "collection",
    "maintenance",
    "manual_review",
    "recovery",
    "solver",
)
_SLOW_TERMS = (
    "async",
    "captcha",
    "job",
    "poll",
    "recovery",
    "solver",
)


def pytest_itemcollected(item: pytest.Item) -> None:
    path = Path(str(item.path))
    if path.name != _AVM_HTTP_CONTRACT:
        item.add_marker(pytest.mark.quick)
        return

    item.add_marker(pytest.mark.integration)
    name = item.name.lower()
    if any(term in name for term in _STATEFUL_TERMS):
        item.add_marker(pytest.mark.stateful)
    if any(term in name for term in _SLOW_TERMS):
        item.add_marker(pytest.mark.slow)


@pytest.fixture(autouse=True)
def _deny_unmocked_hybrid_seed_http(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Keep hybrid seed unit tests offline instead of probing the local API."""

    if Path(str(request.node.path)).name != _HYBRID_SEED_TEST:
        yield
        return

    import requests

    def blocked_get(*_args: Any, **_kwargs: Any) -> None:
        raise requests.ConnectionError("unmocked HTTP is disabled in hybrid seed tests")

    monkeypatch.setattr(requests.Session, "get", blocked_get)
    yield


@pytest.fixture(autouse=True)
def _use_fast_local_server_poll(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    """Isolate HTTP state and avoid the BaseServer 500 ms shutdown tax."""

    if Path(str(request.node.path)).name != _AVM_HTTP_CONTRACT:
        yield
        return

    from src import server as server_module

    ReusableTCPServer = server_module.ReusableTCPServer
    original_serve_forever = ReusableTCPServer.serve_forever

    def serve_forever(server: Any, poll_interval: float = 0.01) -> None:
        original_serve_forever(server, poll_interval=poll_interval)

    monkeypatch.setattr(ReusableTCPServer, "serve_forever", serve_forever)
    isolated_names = (
        "AUTH_COMPLETION_CONFIRMATIONS",
        "AUTH_COOKIE_SNAPSHOT_STATE",
        "AUTH_COOKIE_SNAPSHOT_THREAD",
        "COLLECTION_PAUSE_REASON",
        "CURRENT_PROCESSING",
        "DATA_DIR",
        "DISPATCHED_TASKS",
        "LAST_REQUEST_TIME",
        "PAUSED",
        "PENDING_TASKS",
        "RUNTIME_INITIALIZED",
        "SEEN_IDS",
        "SOLVER_CANCEL_EPOCH",
        "SOLVER_CHALLENGE_ID",
        "SOLVER_LAST_AUTH_COMPLETED_REQUEST",
        "SOLVER_LAST_AUTH_COMPLETED_TIME",
        "SOLVER_LAST_AUTH_DETAIL_CAPTURED_COUNT",
        "SOLVER_LAST_FAILURE_REASON",
        "SOLVER_LAST_FINISHED_TIME",
        "SOLVER_LAST_REQUEST",
        "SOLVER_LAST_STATUS",
        "SOLVER_MANUAL_ONLY",
        "SOLVER_MANUAL_REQUIRED_EPOCH",
        "SOLVER_MANUAL_RESUME_EPOCH",
        "SOLVER_MANUAL_RETRY_ATTEMPTS",
        "SOLVER_MANUAL_RETRY_LAST_EPOCH",
        "SOLVER_PENDING_TOKEN",
        "SOLVER_RUNNING",
        "SOLVER_SCOPE_FORCE_RESET_RECOVERIES",
        "SOLVER_SCOPE_STATE_ROOT",
        "SOLVER_SCOPE_STATES",
        "SOLVER_START_TIME",
    )
    original_state = {
        name: copy.deepcopy(value) if isinstance(value, (dict, list, set)) else value
        for name in isolated_names
        if (value := getattr(server_module, name, None)) is not None or hasattr(server_module, name)
    }
    runtime_root = tmp_path / "server-runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    neutral_state = {
        "AUTH_COMPLETION_CONFIRMATIONS": {},
        "AUTH_COOKIE_SNAPSHOT_STATE": {
            "status": "idle",
            "completion_id": None,
            "attempts": 0,
            "max_attempts": 0,
            "refreshed": False,
            "retry_queued": False,
        },
        "AUTH_COOKIE_SNAPSHOT_THREAD": None,
        "COLLECTION_PAUSE_REASON": None,
        "CURRENT_PROCESSING": set(),
        "DATA_DIR": str(runtime_root),
        "DISPATCHED_TASKS": {},
        "LAST_REQUEST_TIME": time.time(),
        "PAUSED": False,
        "PENDING_TASKS": [],
        "RUNTIME_INITIALIZED": False,
        "SEEN_IDS": {},
        "SOLVER_CANCEL_EPOCH": 0,
        "SOLVER_CHALLENGE_ID": None,
        "SOLVER_LAST_AUTH_COMPLETED_REQUEST": {},
        "SOLVER_LAST_AUTH_COMPLETED_TIME": 0.0,
        "SOLVER_LAST_AUTH_DETAIL_CAPTURED_COUNT": None,
        "SOLVER_LAST_FAILURE_REASON": None,
        "SOLVER_LAST_FINISHED_TIME": 0.0,
        "SOLVER_LAST_REQUEST": {},
        "SOLVER_LAST_STATUS": "idle",
        "SOLVER_MANUAL_ONLY": False,
        "SOLVER_MANUAL_REQUIRED_EPOCH": 0.0,
        "SOLVER_MANUAL_RESUME_EPOCH": 0.0,
        "SOLVER_MANUAL_RETRY_ATTEMPTS": 0,
        "SOLVER_MANUAL_RETRY_LAST_EPOCH": 0.0,
        "SOLVER_PENDING_TOKEN": None,
        "SOLVER_RUNNING": False,
        "SOLVER_SCOPE_FORCE_RESET_RECOVERIES": {scope: {} for scope in server_module.CHALLENGE_SCOPES},
        "SOLVER_SCOPE_STATE_ROOT": None,
        "SOLVER_SCOPE_STATES": {
            scope: server_module._new_solver_scope_state() for scope in server_module.CHALLENGE_SCOPES
        },
        "SOLVER_START_TIME": 0.0,
    }
    for name, value in neutral_state.items():
        setattr(server_module, name, value)
    try:
        yield
    finally:
        snapshot_thread = getattr(server_module, "AUTH_COOKIE_SNAPSHOT_THREAD", None)
        leaked_snapshot_thread = None
        if (
            snapshot_thread is not None
            and snapshot_thread is not original_state.get("AUTH_COOKIE_SNAPSHOT_THREAD")
            and snapshot_thread.is_alive()
        ):
            snapshot_thread.join(timeout=1.0)
            if snapshot_thread.is_alive():
                leaked_snapshot_thread = snapshot_thread.name
        for name, value in original_state.items():
            setattr(server_module, name, value)
        if leaked_snapshot_thread is not None:
            raise AssertionError(
                f"AVM HTTP contract leaked background thread: {leaked_snapshot_thread}"
            )
