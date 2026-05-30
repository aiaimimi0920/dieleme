import json
import time
from pathlib import Path
from unittest import mock

from src.storage.repository import DatabaseSettings, PropertyRepository
import tools.manual_review_receipt_jobs as jobs_module
from tools.manual_review_receipt_audit import (
    append_manual_review_receipt_operation,
    load_manual_review_receipt_operations,
    summarize_manual_review_receipt_operations_snapshot,
)
from tools.manual_review_receipt_jobs import (
    ManualReviewMaintenanceManager,
    load_manual_review_receipt_jobs,
    summarize_manual_review_receipt_jobs_snapshot,
)


def _make_repo(tmp_path: Path) -> PropertyRepository:
    db_path = tmp_path / "receipt-jobs.sqlite3"
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def test_receipt_operation_audit_log_appends_events(tmp_path: Path):
    log_path = tmp_path / "manual_review_receipt_operations.jsonl"

    event = append_manual_review_receipt_operation(
        log_path,
        operation="created",
        receipt={
            "action": "manual_location_review",
            "ready_signal": "location_artifacts_complete",
            "status": "ready_for_reentry",
            "payload": {"full_address": "A"},
        },
        execution_mode="async",
        maintenance_job_id="job-1",
    )

    loaded = load_manual_review_receipt_operations(log_path)
    assert event["operation"] == "created"
    assert event["payload_fingerprint"]
    assert loaded[0]["maintenance_job_id"] == "job-1"
    assert loaded[0]["execution_mode"] == "async"


def test_receipt_operation_audit_log_can_filter_and_summarize(tmp_path: Path):
    log_path = tmp_path / "manual_review_receipt_operations.jsonl"
    append_manual_review_receipt_operation(
        log_path,
        operation="created",
        receipt={
            "action": "manual_location_review",
            "ready_signal": "location_artifacts_complete",
            "status": "ready_for_reentry",
            "payload": {"full_address": "A"},
        },
        execution_mode="async",
        maintenance_job_id="job-1",
    )
    append_manual_review_receipt_operation(
        log_path,
        operation="updated",
        receipt={
            "action": "manual_location_review",
            "ready_signal": "location_artifacts_complete",
            "status": "ready_for_reentry",
            "payload": {"full_address": "B"},
        },
        execution_mode="sync",
    )
    append_manual_review_receipt_operation(
        log_path,
        operation="deleted",
        receipt={
            "action": "manual_status_review",
            "ready_signal": "status_reconciled",
            "status": "",
            "payload": {},
        },
        execution_mode="delete",
        deleted=True,
    )

    filtered = load_manual_review_receipt_operations(
        log_path,
        action="manual_location_review",
        ready_signal="location_artifacts_complete",
    )
    assert len(filtered) == 2

    summary = summarize_manual_review_receipt_operations_snapshot(load_manual_review_receipt_operations(log_path))
    assert summary["operation_count"] == 3
    assert summary["last_operation_type"] == "deleted"
    assert summary["last_delete_receipt_key"]["action"] == "manual_status_review"
    assert summary["last_update_receipt_key"]["action"] == "manual_location_review"
    assert summary["last_async_operation_receipt_key"]["action"] == "manual_location_review"


def test_manual_review_maintenance_manager_runs_async_job_and_persists_state(tmp_path: Path):
    state_path = tmp_path / "manual_review_receipt_jobs.json"
    calls = []

    def _runner(**kwargs):
        calls.append(kwargs)
        return {
            "generated_at": "2026-05-14 21:00:00",
            "manual_review_reentry_application_summary": {"reentry_applied": True},
            "operator_overview": {"handoff_lifecycle_state": "reentry_applied"},
        }

    manager = ManualReviewMaintenanceManager(state_path, maintenance_runner=_runner)
    try:
        job = manager.enqueue(
            receipt_key={
                "action": "manual_location_review",
                "ready_signal": "location_artifacts_complete",
            },
            maintenance_options={"window_days": 7},
        )

        deadline = time.time() + 3
        final_job = job
        while time.time() < deadline:
            final_job = manager.get_job(job["job_id"])
            if final_job and final_job["status"] == "completed":
                break
            time.sleep(0.05)

        assert final_job is not None
        assert final_job["status"] == "completed"
        assert calls == [{"window_days": 7}]

        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert saved["jobs"][0]["job_id"] == job["job_id"]
        assert saved["jobs"][0]["status"] == "completed"

        snapshot = summarize_manual_review_receipt_jobs_snapshot(load_manual_review_receipt_jobs(state_path))
        assert snapshot["queued_count"] == 0
        assert snapshot["running_count"] == 0
        assert snapshot["last_job_status"] == "completed"
        assert snapshot["last_job_receipt_key"]["action"] == "manual_location_review"
    finally:
        manager.shutdown(timeout=1.0)


def test_manual_review_maintenance_manager_persists_failures(tmp_path: Path):
    state_path = tmp_path / "manual_review_receipt_jobs.json"

    def _runner(**kwargs):
        raise RuntimeError("boom")

    manager = ManualReviewMaintenanceManager(state_path, maintenance_runner=_runner)
    try:
        job = manager.enqueue(
            receipt_key={"action": "manual_status_review", "ready_signal": "status_reconciled"},
            maintenance_options={"window_days": 3},
        )

        deadline = time.time() + 3
        final_job = job
        while time.time() < deadline:
            final_job = manager.get_job(job["job_id"])
            if final_job and final_job["status"] == "failed":
                break
            time.sleep(0.05)

        assert final_job is not None
        assert final_job["status"] == "failed"
        assert final_job["error"] == "boom"
        snapshot = summarize_manual_review_receipt_jobs_snapshot(load_manual_review_receipt_jobs(state_path))
        assert snapshot["failed_count"] == 1
        assert snapshot["last_job_status"] == "failed"
    finally:
        manager.shutdown(timeout=1.0)


def test_manual_review_maintenance_manager_can_use_repository_backed_state(tmp_path: Path):
    repo = _make_repo(tmp_path)
    calls = []

    def _runner(**kwargs):
        calls.append(kwargs)
        return {"generated_at": "x"}

    manager = ManualReviewMaintenanceManager(
        tmp_path / "datas" / "avm" / "manual_review_receipt_jobs.json",
        maintenance_runner=_runner,
        repository=repo,
    )
    try:
        job = manager.enqueue(
            receipt_key={"action": "manual_location_review", "ready_signal": "location_artifacts_complete"},
            maintenance_options={"window_days": 5},
        )

        deadline = time.time() + 3
        final_job = job
        while time.time() < deadline:
            final_job = manager.get_job(job["job_id"])
            if final_job and final_job["status"] == "completed":
                break
            time.sleep(0.05)

        assert final_job is not None
        assert final_job["status"] == "completed"
        assert calls == [{"window_days": 5}]
        snapshot = repo.manual_review_receipt_jobs_snapshot()
        assert snapshot["jobs"][0]["job_id"] == job["job_id"]
        backup_path = tmp_path / "datas" / "avm" / "manual_review_receipt_jobs.json"
        assert backup_path.exists()
        backup_payload = json.loads(backup_path.read_text(encoding="utf-8"))
        assert backup_payload["jobs"][0]["job_id"] == job["job_id"]
        assert backup_payload["jobs"][0]["status"] == "completed"
    finally:
        manager.shutdown(timeout=1.0)


def test_manual_review_maintenance_manager_tolerates_repository_backup_sync_failure(tmp_path: Path):
    repo = _make_repo(tmp_path)
    calls = []

    def _runner(**kwargs):
        calls.append(kwargs)
        return {"generated_at": "x"}

    original_sync = jobs_module.sync_manual_review_control_plane_json_backup
    sync_calls = {"count": 0}

    def _flaky_sync(*args, **kwargs):
        sync_calls["count"] += 1
        if sync_calls["count"] >= 2:
            raise PermissionError("locked")
        return original_sync(*args, **kwargs)

    manager = ManualReviewMaintenanceManager(
        tmp_path / "datas" / "avm" / "manual_review_receipt_jobs.json",
        maintenance_runner=_runner,
        repository=repo,
    )
    try:
        with mock.patch.object(jobs_module, "sync_manual_review_control_plane_json_backup", side_effect=_flaky_sync):
            job = manager.enqueue(
                receipt_key={"action": "manual_location_review", "ready_signal": "location_artifacts_complete"},
                maintenance_options={"window_days": 5},
            )

            deadline = time.time() + 3
            final_job = job
            while time.time() < deadline:
                final_job = manager.get_job(job["job_id"])
                if final_job and final_job["status"] == "completed":
                    break
                time.sleep(0.05)

            assert final_job is not None
            assert final_job["status"] == "completed"
            assert calls == [{"window_days": 5}]
            assert sync_calls["count"] >= 2
    finally:
        manager.shutdown(timeout=1.0)
