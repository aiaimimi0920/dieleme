"""In-process ownership of solver executions, independent of wall-clock time."""

import threading
from _thread import RLock
from dataclasses import dataclass, field


@dataclass(frozen=True, eq=False)
class SolverExecution:
    started_at: float
    resume_epoch: float
    cancel_epoch: float
    cancelled: threading.Event = field(
        default_factory=lambda: threading.Event(), repr=False
    )
    superseded: threading.Event = field(
        default_factory=lambda: threading.Event(), repr=False
    )


@dataclass(frozen=True)
class SolverExecutionSnapshot:
    """Immutable view of the current execution without replacing its identity."""

    execution: SolverExecution | None
    started_at: float | None
    resume_epoch: float | None
    cancel_epoch: float | None
    cancelled: bool
    superseded: bool
    running: bool
    pending_token: object | None
    last_status: str
    failure_reason: str | None
    finished_at: float


@dataclass
class SolverExecutionState:
    lock: RLock = field(default_factory=RLock, repr=False)
    current: SolverExecution | None = field(default=None, init=False)
    running: bool = False
    pending_token: object | None = field(default=None, repr=False)
    started_at: float = 0.0
    last_status: str = "idle"
    failure_reason: str | None = None
    finished_at: float = 0.0

    def reserve(self) -> object | None:
        with self.lock:
            if self.running or self.pending_token is not None:
                return None
            self.pending_token = object()
            return self.pending_token

    def release(self, token: object | None) -> None:
        with self.lock:
            if token is not None and self.pending_token is token:
                self.pending_token = None

    def activate(
        self,
        started_at: float,
        *,
        token: object | None,
        resume_epoch: float,
        cancel_epoch: float,
    ) -> tuple[bool, str, float]:
        with self.lock:
            if token is not None:
                if self.pending_token is not token:
                    return False, "stale_submission", 0.0
                self.pending_token = None
            elif self.pending_token is not None:
                return False, "submission_pending", 0.0
            if self.running:
                return False, "solver_running", max(started_at - self.started_at, 0.0)
            self.begin(started_at, resume_epoch=resume_epoch, cancel_epoch=cancel_epoch)
            return True, "started", started_at

    def begin(
        self, started_at: float, *, resume_epoch: float, cancel_epoch: float
    ) -> SolverExecution:
        with self.lock:
            self.clear()
            self.current = SolverExecution(started_at, resume_epoch, cancel_epoch)
            self.running = True
            self.started_at = started_at
            self.last_status = "running"
            self.failure_reason = None
            return self.current

    def clear(self, *, finished_at: float | None = None) -> None:
        with self.lock:
            if self.current is not None:
                self.current.cancelled.set()
                self.current.superseded.set()
            self.current = None
            if self.running and finished_at is not None:
                self.finished_at = finished_at
            self.running = False
            self.pending_token = None
            self.started_at = 0.0

    def record_outcome(
        self,
        status: str,
        failure_reason: str | None = None,
        *,
        execution: SolverExecution | None = None,
    ) -> bool:
        with self.lock:
            if execution is not None and not self.owns(execution):
                return False
            self.last_status = status
            self.failure_reason = failure_reason
            return True

    def require_manual(self) -> bool:
        with self.lock:
            self.pending_token = None
            self.record_outcome("manual_required", "manual_required")
            return self.running

    def clear_manual(self) -> None:
        with self.lock:
            if self.last_status in {"manual_required", "running"}:
                self.last_status = "resumed"
            if self.failure_reason == "manual_required":
                self.failure_reason = None

    def finish(self, execution: SolverExecution, finished_at: float) -> bool:
        with self.lock:
            if not self.owns(execution) or self.started_at != execution.started_at:
                return False
            self.running = False
            self.finished_at = finished_at
            return True

    def cancel(self) -> None:
        with self.lock:
            if self.current is not None:
                self.current.cancelled.set()

    def owns(self, execution: SolverExecution) -> bool:
        with self.lock:
            return self.current is execution

    def snapshot(self) -> SolverExecutionSnapshot:
        """Read the current execution atomically while preserving identity semantics."""
        with self.lock:
            execution = self.current
            return SolverExecutionSnapshot(
                execution=execution,
                started_at=execution.started_at
                if execution is not None
                else self.started_at or None,
                resume_epoch=execution.resume_epoch if execution is not None else None,
                cancel_epoch=execution.cancel_epoch if execution is not None else None,
                cancelled=execution.cancelled.is_set()
                if execution is not None
                else False,
                superseded=execution.superseded.is_set()
                if execution is not None
                else False,
                running=self.running,
                pending_token=self.pending_token,
                last_status=self.last_status,
                failure_reason=self.failure_reason,
                finished_at=self.finished_at,
            )
