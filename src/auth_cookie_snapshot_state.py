"""Locked in-process state for background cookie snapshot refreshes."""

from __future__ import annotations

from _thread import RLock
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Thread
from typing import Any


DEFAULT_COOKIE_SNAPSHOT_STATE: dict[str, Any] = {
    "status": "idle",
    "completion_id": None,
    "attempts": 0,
    "max_attempts": 0,
    "refreshed": False,
    "retry_queued": False,
}


@dataclass
class AuthCookieSnapshotState:
    """Own refresh status and worker identity under the runtime state lock."""

    lock: RLock
    state: dict[str, Any] = field(
        default_factory=lambda: dict(DEFAULT_COOKIE_SNAPSHOT_STATE)
    )
    thread: Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.state)

    def update(self, updates: Mapping[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.state.update(updates)
            return dict(self.state)

    def replace(self, state: Mapping[str, Any]) -> None:
        with self.lock:
            self.state.clear()
            self.state.update(state)

    def set_thread(self, thread: Thread | None) -> None:
        with self.lock:
            self.thread = thread

    def active_thread(self) -> Thread | None:
        with self.lock:
            return (
                self.thread
                if self.thread is not None and self.thread.is_alive()
                else None
            )
