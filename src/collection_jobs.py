"""Bounded background operations with durable receipts and no automatic replay."""

from __future__ import annotations

import copy
import json
import logging
import re
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.archive_json_io import write_json
from src.runtime_json import load_json_file

logger = logging.getLogger(__name__)
JobResult = dict[str, object]
JobWork = Callable[[], JobResult]
ACTIVE = {"queued", "running"}
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class JobQueueFull(RuntimeError):
    pass


class CollectionJobFailure(RuntimeError):
    """A trusted operation stage supplies its public failure code."""

    def __init__(self, code: str) -> None:
        super().__init__("Collection operation failed")
        self.code = code


@dataclass
class PendingJob:
    receipt: JobResult
    work: JobWork
    failure_code: str


class CollectionJobManager:
    """One daemon worker per API instance; only active work occupies memory."""

    def __init__(self, data_root: Path, *, capacity: int = 8) -> None:
        if capacity < 1:
            raise ValueError("Job capacity must be positive")
        self.root = data_root.resolve() / "runtime" / "collection-jobs"
        self._capacity = capacity
        self._lock = threading.Lock()
        self._pending: deque[PendingJob] = deque()
        self._active: set[str] = set()
        self._thread: threading.Thread | None = None
        self._closed = False

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _path(self, job_id: str) -> Path:
        if re.fullmatch(r"[a-f0-9]{32}", job_id) is None:
            raise ValueError("Invalid collection job ID")
        return self.root / f"{job_id}.json"

    def _save(self, receipt: JobResult) -> None:
        write_json(self._path(str(receipt["job_id"])), receipt, indent=2)

    def submit(
        self,
        operation: str,
        work: JobWork,
        failure_code: str,
        *,
        job_id: str | None = None,
    ) -> JobResult:
        with self._lock:
            if self._closed or len(self._active) >= self._capacity:
                raise JobQueueFull("Collection operation queue is unavailable")
            job_id = job_id or uuid4().hex
            if re.fullmatch(r"[a-f0-9]{32}", job_id) is None:
                raise ValueError("Invalid collection job ID")
            if self._path(job_id).exists():
                raise ValueError("Collection job ID already exists")
            receipt: JobResult = {
                "job_id": job_id,
                "operation": operation,
                "status": "queued",
                "created_at": self._now(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
            }
            self.root.mkdir(parents=True, exist_ok=True)
            # Acknowledgement and work both require a durable queued receipt.
            self._save(receipt)
            self._pending.append(PendingJob(receipt, work, failure_code))
            self._active.add(job_id)
            if self._thread is None:
                thread = threading.Thread(
                    target=self._worker, name="collection-operations", daemon=True
                )
                self._thread = thread
                try:
                    thread.start()
                except BaseException:
                    self._thread = None
                    self._pending.pop()
                    self._active.remove(job_id)
                    raise
            return copy.deepcopy(receipt)

    def get(self, job_id: str) -> JobResult | None:
        with self._lock:
            try:
                payload = load_json_file(self._path(job_id))
            except FileNotFoundError:
                return None
            if (
                not isinstance(payload, dict)
                or payload.get("job_id") != job_id
                or not isinstance(payload.get("status"), str)
                or payload["status"] not in ACTIVE | TERMINAL
            ):
                raise ValueError("Invalid collection job receipt")
            if payload["status"] in ACTIVE and job_id not in self._active:
                # A restart never replays potentially completed writes.
                payload["status"] = "interrupted"
                payload["error"] = {
                    "code": "COLLECTION_JOB_INTERRUPTED",
                    "message": "Completion is unconfirmed; inspect outputs before retrying",
                    "error_id": job_id,
                }
            return dict(payload)

    def list(self, *, operation: str | None = None) -> list[JobResult]:
        """Return persisted receipts for compatibility/reporting endpoints.

        Completed receipts are intentionally read from disk instead of the
        in-memory queue so a restarted API can expose the same audit surface.
        ``queued``/``running`` receipts are projected as ``interrupted`` by
        :meth:`get` when this instance does not own them; no work is replayed.
        """
        with self._lock:
            paths = sorted(self.root.glob("[a-f0-9][a-f0-9]*.json")) if self.root.exists() else []
        receipts: list[JobResult] = []
        for path in paths:
            try:
                job_id = path.stem
                if re.fullmatch(r"[a-f0-9]{32}", job_id) is None:
                    continue
                payload = self.get(job_id)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if payload is None:
                continue
            if operation is not None and payload.get("operation") != operation:
                continue
            receipts.append(payload)
        return receipts

    def _worker(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._thread = None
                    return
                entry = self._pending.popleft()
                job_id = str(entry.receipt["job_id"])
            try:
                self._execute(entry)
            except BaseException:
                self.close()
                raise
            finally:
                with self._lock:
                    self._active.remove(job_id)

    def _execute(self, entry: PendingJob) -> None:
        receipt = entry.receipt
        try:
            with self._lock:
                if self._closed:
                    receipt.update(status="cancelled", finished_at=self._now())
                    self._save(receipt)
                    return
                receipt.update(status="running", started_at=self._now())
                self._save(receipt)
            try:
                result = entry.work()
                receipt.update(status="completed", result=result)
            except Exception as error:
                logger.exception("Collection job failed: %s", receipt["job_id"])
                receipt.update(
                    status="failed",
                    error={
                        "code": error.code if isinstance(error, CollectionJobFailure) else entry.failure_code,
                        "message": "Collection operation failed",
                        "error_id": receipt["job_id"],
                    },
                )
            receipt["finished_at"] = self._now()
            with self._lock:
                self._save(receipt)
        except Exception:
            # Keep the last confirmed bytes and any failed temporary snapshot.
            logger.exception(
                "Collection job receipt unavailable: %s", receipt["job_id"]
            )

    def close(self, timeout: float = 0) -> None:
        with self._lock:
            self._closed = True
            while self._pending:
                entry = self._pending.popleft()
                entry.receipt.update(status="cancelled", finished_at=self._now())
                try:
                    self._save(entry.receipt)
                except Exception:
                    logger.exception("Unable to confirm queued job cancellation")
                self._active.remove(str(entry.receipt["job_id"]))
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
