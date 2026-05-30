#!/usr/bin/env python3
"""Async maintenance job state for manual review receipt control-plane."""

from __future__ import annotations

import copy
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from src.storage.repository import PropertyRepository

from tools.backfill_manual_review_control_plane_to_db import (
    ensure_manual_review_control_plane_backfilled,
    sync_manual_review_control_plane_json_backup,
)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _default_state() -> dict[str, Any]:
    return {
        "jobs": [],
        "queue": [],
        "running_job_id": None,
    }


def _normalize_job_state(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _default_state()
    jobs = payload.get("jobs")
    queue = payload.get("queue")
    running_job_id = payload.get("running_job_id")
    return {
        "jobs": [dict(item) for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else [],
        "queue": [str(item) for item in queue if str(item or "").strip()] if isinstance(queue, list) else [],
        "running_job_id": str(running_job_id) if running_job_id else None,
    }


def load_manual_review_receipt_jobs(
    path: str | Path,
    repository: "PropertyRepository | None" = None,
) -> dict[str, Any]:
    if repository is not None and getattr(repository, "enabled", False):
        ensure_manual_review_control_plane_backfilled(Path(path).parent.parent, repository=repository)
        return _normalize_job_state(repository.manual_review_receipt_jobs_snapshot())
    store_path = Path(path)
    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_state()
    return _normalize_job_state(payload)


def _write_job_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    last_error: Exception | None = None
    for _ in range(20):
        try:
            tmp_path.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.01)
    if last_error is not None:
        raise last_error


def summarize_manual_review_receipt_jobs_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = _normalize_job_state(snapshot)
    jobs = list(snapshot.get("jobs") or [])
    running_job_id = snapshot.get("running_job_id")
    queued_count = sum(1 for job in jobs if job.get("status") == "queued")
    failed_jobs = [job for job in jobs if job.get("status") == "failed"]
    completed_jobs = [job for job in jobs if job.get("status") == "completed"]
    running_job = next((job for job in jobs if job.get("job_id") == running_job_id), None)
    last_job = jobs[-1] if jobs else None
    return {
        "queued_count": queued_count,
        "running_count": 1 if running_job else 0,
        "failed_count": len(failed_jobs),
        "last_completed_at": completed_jobs[-1].get("finished_at") if completed_jobs else None,
        "last_failed_at": failed_jobs[-1].get("finished_at") if failed_jobs else None,
        "last_job_status": last_job.get("status") if last_job else None,
        "last_job_receipt_key": copy.deepcopy(last_job.get("receipt_key")) if last_job else None,
    }


class ManualReviewMaintenanceManager:
    """Single-worker FIFO async job runner with JSON state persistence."""

    def __init__(
        self,
        state_path: str | Path,
        *,
        maintenance_runner: Callable[..., dict[str, Any]],
        repository: "PropertyRepository | None" = None,
    ) -> None:
        self.state_path = Path(state_path)
        self._maintenance_runner = maintenance_runner
        self._repository = repository if repository is not None and getattr(repository, "enabled", False) else None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = load_manual_review_receipt_jobs(self.state_path, repository=self._repository)
        if self._state.get("queue"):
            self._ensure_worker()

    def _save(self) -> None:
        if self._repository is not None:
            return
        _write_job_state(self.state_path, self._state)

    def _sync_backup(self) -> None:
        if self._repository is None:
            return
        try:
            sync_manual_review_control_plane_json_backup(self.state_path.parent.parent, repository=self._repository)
        except Exception as exc:
            print(f"[MANUAL-REVIEW-BACKUP] Sync failed: {exc}")

    def _find_job(self, job_id: str) -> dict[str, Any] | None:
        for job in self._state.get("jobs") or []:
            if job.get("job_id") == job_id:
                return job
        return None

    @staticmethod
    def _result_summary(result: dict[str, Any] | None) -> dict[str, Any]:
        result = dict(result or {})
        reentry = dict(result.get("manual_review_reentry_application_summary") or {})
        overview = dict(result.get("operator_overview") or {})
        return {
            "generated_at": result.get("generated_at"),
            "reentry_applied": bool(reentry.get("reentry_applied")),
            "reentry_confirmed": bool(reentry.get("reentry_confirmed")),
            "handoff_lifecycle_state": overview.get("handoff_lifecycle_state"),
        }

    def enqueue(self, *, receipt_key: dict[str, Any], maintenance_options: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._repository is not None:
                job = self._repository.create_manual_review_receipt_job(
                    receipt_key=receipt_key,
                    maintenance_options=maintenance_options,
                )
                self._state = load_manual_review_receipt_jobs(self.state_path, repository=self._repository)
                self._sync_backup()
            else:
                job = {
                    "job_id": str(uuid4()),
                    "status": "queued",
                    "receipt_key": {
                        "action": str(receipt_key.get("action") or "").strip(),
                        "ready_signal": str(receipt_key.get("ready_signal") or "").strip(),
                    },
                    "created_at": _now_text(),
                    "started_at": None,
                    "finished_at": None,
                    "maintenance_options": dict(maintenance_options or {}),
                    "result_summary": None,
                    "error": None,
                }
                self._state["jobs"].append(job)
                self._state["queue"].append(job["job_id"])
                self._save()
            self._ensure_worker()
            return copy.deepcopy(job)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            if self._repository is not None:
                job = self._repository.get_manual_review_receipt_job(str(job_id or "").strip())
            else:
                job = self._find_job(str(job_id or "").strip())
            return copy.deepcopy(job) if job else None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._repository is not None:
                self._state = load_manual_review_receipt_jobs(self.state_path, repository=self._repository)
            return copy.deepcopy(self._state)

    def _ensure_worker(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                queue = self._state.get("queue") or []
                if not queue:
                    self._state["running_job_id"] = None
                    self._save()
                    return
                job_id = queue.pop(0)
                self._state["queue"] = queue
                self._state["running_job_id"] = job_id
                if self._repository is not None:
                    self._repository.update_manual_review_receipt_job(job_id, status="running", started_at=datetime.now())
                    self._state = load_manual_review_receipt_jobs(self.state_path, repository=self._repository)
                    self._sync_backup()
                    job = self._repository.get_manual_review_receipt_job(job_id)
                else:
                    job = self._find_job(job_id)
                if job is None:
                    self._save()
                    continue
                if self._repository is None:
                    job["status"] = "running"
                    job["started_at"] = _now_text()
                    job["error"] = None
                    job["result_summary"] = None
                maintenance_options = dict(job.get("maintenance_options") or {})
                self._save()

            try:
                result = self._maintenance_runner(**maintenance_options)
            except Exception as exc:  # pragma: no cover - exercised in tests through public API
                with self._lock:
                    if self._repository is not None:
                        self._repository.update_manual_review_receipt_job(
                            job_id,
                            status="failed",
                            finished_at=datetime.now(),
                            error=str(exc),
                            result_summary=None,
                        )
                        self._state = load_manual_review_receipt_jobs(self.state_path, repository=self._repository)
                        self._sync_backup()
                    else:
                        job = self._find_job(job_id)
                        if job is not None:
                            job["status"] = "failed"
                            job["finished_at"] = _now_text()
                            job["error"] = str(exc)
                            job["result_summary"] = None
                    self._state["running_job_id"] = None
                    self._save()
                continue

            with self._lock:
                if self._repository is not None:
                    self._repository.update_manual_review_receipt_job(
                        job_id,
                        status="completed",
                        finished_at=datetime.now(),
                        result_summary=self._result_summary(result),
                        error=None,
                    )
                    self._state = load_manual_review_receipt_jobs(self.state_path, repository=self._repository)
                    self._sync_backup()
                else:
                    job = self._find_job(job_id)
                    if job is not None:
                        job["status"] = "completed"
                        job["finished_at"] = _now_text()
                        job["result_summary"] = self._result_summary(result)
                        job["error"] = None
                self._state["running_job_id"] = None
                self._save()

    def shutdown(self, timeout: float | None = None) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
