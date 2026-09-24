"""In-process pause and challenge state; durable receipts remain in the I/O layer."""

from _thread import RLock
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field

CHALLENGE_SCOPES = ("seed", "detail")


def new_scope_state() -> dict[str, object]:
    return {
        "challenge_id": None,
        "last_request": {},
        "first_seen_epoch": 0.0,
        "pause_started_epoch": 0.0,
        "paused": False,
        "pause_reason": None,
        "manual_required": False,
        "manual_only": False,
        "last_status": "idle",
        "last_failure_reason": None,
        "node_solver_blocked": False,
        "node_solver_blocked_at_epoch": 0.0,
        "node_solver_blocked_reason": None,
        "node_solver_blocked_attempts": 0,
        "force_reset_required": False,
    }


@dataclass(frozen=True)
class CollectionPauseSnapshot:
    paused: bool
    reason: str | None


@dataclass
class CollectionControlState:
    lock: RLock = field(default_factory=RLock, repr=False)
    paused: bool = False
    reason: str | None = None
    scope_root: str | None = None
    scopes: dict[str, dict[str, object]] = field(
        default_factory=lambda: {scope: new_scope_state() for scope in CHALLENGE_SCOPES}
    )
    force_reset_recoveries: dict[str, dict[str, object]] = field(default_factory=dict)

    def snapshot(self) -> CollectionPauseSnapshot:
        with self.lock:
            return CollectionPauseSnapshot(self.paused, self.reason)

    def set_pause(self, paused: bool, reason: str | None = None) -> None:
        with self.lock:
            self.paused = bool(paused)
            self.reason = str(reason or "").strip() or None if paused else None

    def bind_root(self, root: str) -> None:
        with self.lock:
            if self.scope_root != root:
                self.scope_root = root
                self.scopes.clear()
                self.scopes.update(
                    {scope: new_scope_state() for scope in CHALLENGE_SCOPES}
                )
                self.force_reset_recoveries.clear()

    def scope_snapshot(self, scope: str) -> dict[str, object]:
        with self.lock:
            return deepcopy(self.scopes.get(scope, new_scope_state()))

    def set_scope(self, scope: str, state: Mapping[str, object]) -> None:
        if scope not in CHALLENGE_SCOPES:
            raise ValueError("Unknown collection scope")
        with self.lock:
            self.scopes[scope] = deepcopy(dict(state))

    def remember_force_reset(
        self, scope: str, now: float, request: Mapping[str, str]
    ) -> None:
        with self.lock:
            self.force_reset_recoveries[scope] = {
                "completed_at_epoch": now,
                "request": dict(request),
            }

    def force_reset_snapshot(self, scope: str) -> dict[str, object]:
        with self.lock:
            return deepcopy(self.force_reset_recoveries.get(scope, {}))
