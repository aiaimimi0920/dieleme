"""Locked recovery metadata shared by solver, retry and authentication workers."""

from _thread import LockType, RLock
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Lock


@dataclass(frozen=True)
class SolverRecoverySnapshot:
    generation: int
    last_request: dict[str, str]
    challenge_id: str | None
    resume_epoch: float
    cancel_epoch: float
    required_epoch: float
    manual_only: bool
    retry_last_epoch: float
    retry_attempts: int
    completed_at: float
    completed_request: dict[str, str]
    completed_detail_count: int | None
    confirmations: dict[str, float]


@dataclass
class SolverRecoveryState:
    lock: RLock = field(default_factory=RLock, repr=False)
    finalize_lock: LockType = field(default_factory=Lock, repr=False)
    generation: int = field(default=0, init=False)
    last_request: dict[str, str] = field(default_factory=dict)
    challenge_id: str | None = None
    resume_epoch: float = 0.0
    cancel_epoch: float = 0.0
    required_epoch: float = 0.0
    manual_only: bool = False
    retry_last_epoch: float = 0.0
    retry_attempts: int = 0
    completed_at: float = 0.0
    completed_request: dict[str, str] = field(default_factory=dict)
    completed_detail_count: int | None = None
    confirmations: dict[str, float] = field(default_factory=dict)

    def snapshot(self) -> SolverRecoverySnapshot:
        with self.lock:
            return SolverRecoverySnapshot(
                self.generation,
                dict(self.last_request),
                self.challenge_id,
                self.resume_epoch,
                self.cancel_epoch,
                self.required_epoch,
                self.manual_only,
                self.retry_last_epoch,
                self.retry_attempts,
                self.completed_at,
                dict(self.completed_request),
                self.completed_detail_count,
                dict(self.confirmations),
            )

    def replace_confirmations(self, confirmations: Mapping[str, float]) -> None:
        with self.lock:
            self.generation += 1
            self.confirmations = {
                str(completion_id): float(epoch)
                for completion_id, epoch in confirmations.items()
            }

    def confirmation_snapshot(self) -> dict[str, float]:
        with self.lock:
            return dict(self.confirmations)

    def was_confirmation_recorded(self, completion_id: str) -> bool:
        with self.lock:
            return completion_id in self.confirmations

    def record_confirmation(
        self,
        completion_id: str,
        now: float,
        *,
        max_entries: int = 256,
        retain_entries: int = 192,
    ) -> None:
        with self.lock:
            self.generation += 1
            self.confirmations[completion_id] = float(now)
            if len(self.confirmations) > max_entries:
                self.confirmations = dict(
                    sorted(self.confirmations.items(), key=lambda item: item[1])[
                        -retain_entries:
                    ]
                )

    def set_request(self, request: Mapping[str, str]) -> dict[str, str]:
        with self.lock:
            self.generation += 1
            self.last_request = dict(request)
            return dict(self.last_request)

    def set_challenge(
        self, challenge_id: str | None, request: Mapping[str, str] | None = None
    ) -> None:
        with self.lock:
            self.generation += 1
            self.challenge_id = challenge_id
            if request is not None:
                self.last_request = dict(request)

    def resume(self, now: float) -> None:
        with self.lock:
            self.generation += 1
            self.resume_epoch = now

    def cancel(self, now: float) -> None:
        with self.lock:
            self.generation += 1
            self.cancel_epoch = now

    def require_manual(self, now: float, *, manual_only: bool) -> None:
        with self.lock:
            self.generation += 1
            self.required_epoch = now
            self.manual_only = manual_only

    def clear_manual(self) -> None:
        with self.lock:
            self.generation += 1
            self.manual_only = False

    def record_retry(self, now: float, *, attempted: bool) -> int:
        with self.lock:
            self.generation += 1
            self.retry_last_epoch = now
            if attempted:
                self.retry_attempts += 1
            return self.retry_attempts

    def record_auth_completion(
        self, now: float, request: Mapping[str, str], detail_count: int | None
    ) -> None:
        with self.lock:
            self.generation += 1
            self.completed_at = now
            self.completed_request = dict(request)
            self.completed_detail_count = detail_count
