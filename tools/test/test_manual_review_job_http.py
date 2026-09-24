"""Manual review submission is admitted before writes and preserves partial work."""

import json
import threading
from unittest.mock import Mock

import pytest

from src import collection_jobs, server
from tools import manual_review_receipt_jobs
from tools.test.test_collection_job_http import HEADERS, fetch, finish
from tools.test.test_collection_job_http import job_api as job_api
from tools.test.test_http_write_access import configured_api as configured_api
from tools.test.test_quality_http_guards import api as api

PATHS = ("/api/avm/manual_review_receipts", "/api/analysis/manual_review_receipts")
RECEIPT = {
    "action": "manual_location_review",
    "ready_signal": "location_artifacts_complete",
    "status": "ready_for_reentry",
    "payload": {"full_address": "operator-reviewed address"},
    "maintenance": {"dry_run": True},
}


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("explicit_mode", [False, True])
def test_submission_returns_before_receipt_write(
    job_api, monkeypatch, tmp_path, path, explicit_mode
):
    entered, release = threading.Event(), threading.Event()
    original_upsert = server.upsert_manual_review_receipt
    maintenance = Mock(return_value={"generated_at": "verified"})

    def upsert(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_upsert(*args, **kwargs)

    monkeypatch.setattr(server, "upsert_manual_review_receipt", upsert)
    monkeypatch.setattr(server, "run_recent_enrich_maintenance", maintenance)
    payload = {**RECEIPT, **({"mode": "sync"} if explicit_mode else {})}
    try:
        status, _, raw = job_api("POST", path, json.dumps(payload).encode(), HEADERS)
        assert status == 202, raw
        assert entered.wait(2)
        accepted = json.loads(raw)
        assert fetch(job_api, accepted["status_url"])["status"] == "running"
        assert not (tmp_path / "avm" / "manual_review_receipts.json").exists()
        maintenance.assert_not_called()
    finally:
        release.set()
    job = finish(job_api, raw)
    assert job["status"] == "completed", job
    assert job["result"]["receipt"]["payload"] == RECEIPT["payload"]
    assert job["result"]["maintenance_report"] == {"generated_at": "verified"}
    assert job["result"]["maintenance_triggered"] is True
    assert maintenance.call_args.kwargs["data_root"] == tmp_path
    assert maintenance.call_args.kwargs["dry_run"] is True
    assert maintenance.call_args.kwargs["repository"] is None


@pytest.mark.parametrize("path", PATHS)
def test_explicit_async_submission_uses_collection_queue(job_api, monkeypatch, path):
    """The legacy async response must still use the durable common queue."""
    legacy_manager = Mock(side_effect=AssertionError("legacy manager must not run"))
    monkeypatch.setattr(
        manual_review_receipt_jobs, "ManualReviewMaintenanceManager", legacy_manager
    )
    monkeypatch.setattr(
        server,
        "run_recent_enrich_maintenance",
        Mock(return_value={"generated_at": "verified"}),
    )

    status, _, raw = job_api(
        "POST",
        path,
        json.dumps({**RECEIPT, "mode": "async"}).encode(),
        HEADERS,
    )
    assert status == 200, raw
    accepted = json.loads(raw)
    assert accepted["status"] == "ok"
    assert accepted["execution_mode"] == "async"
    assert accepted["maintenance_job_status"] == "queued"
    assert accepted["maintenance_job_id"] == accepted["job_id"]
    assert accepted["job_status"] == "queued"
    assert accepted["status_url"].endswith(accepted["job_id"])
    completed = finish(job_api, raw)
    assert completed["status"] == "completed"
    assert completed["result"]["maintenance_job_id"] == accepted["job_id"]
    assert completed["result"]["maintenance_job_status"] == "completed"
    legacy_manager.assert_not_called()


@pytest.mark.parametrize("failure", ["capacity", "persistence"])
def test_rejected_admission_does_not_write_receipt(
    job_api, monkeypatch, tmp_path, failure
):
    upsert = Mock()
    monkeypatch.setattr(server, "upsert_manual_review_receipt", upsert)

    def reject(*_args, **_kwargs):
        if failure == "capacity":
            raise collection_jobs.JobQueueFull()
        raise OSError("simulated receipt storage failure")

    if failure == "capacity":
        monkeypatch.setattr(collection_jobs.CollectionJobManager, "submit", reject)
    else:
        monkeypatch.setattr(collection_jobs, "write_json", reject)
    status, _, raw = job_api("POST", PATHS[0], json.dumps(RECEIPT).encode(), HEADERS)
    assert status == 503, raw
    expected = (
        "COLLECTION_JOB_QUEUE_FULL"
        if failure == "capacity"
        else "COLLECTION_JOB_SUBMISSION_FAILED"
    )
    assert json.loads(raw)["error"]["code"] == expected
    upsert.assert_not_called()
    assert not (tmp_path / "avm" / "manual_review_receipts.json").exists()


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("stage", ["maintenance", "finalize"])
def test_later_failure_preserves_saved_receipt(
    job_api, monkeypatch, tmp_path, path, stage
):
    receipt_path = tmp_path / "avm" / "manual_review_receipts.json"
    saved = []

    def fail(**_options):
        saved.append(receipt_path.read_bytes())
        raise RuntimeError("private-stage-diagnostic")

    def fail_finalize(*_args, **options):
        return fail(**options)

    monkeypatch.setattr(
        server,
        "run_recent_enrich_maintenance",
        fail if stage == "maintenance" else lambda **_options: {},
    )
    if stage == "finalize":
        monkeypatch.setattr(
            server, "append_manual_review_receipt_operation", fail_finalize
        )
    status, _, raw = job_api("POST", path, json.dumps(RECEIPT).encode(), HEADERS)
    assert status == 202, raw
    job = finish(job_api, raw)
    assert job["status"] == "failed"
    code = (
        "AVM_MANUAL_REVIEW_RECEIPT_MAINTENANCE_FAILED"
        if stage == "maintenance"
        else "AVM_MANUAL_REVIEW_RECEIPT_SYNC_FINALIZE_FAILED"
    )
    assert job["error"]["code"] == code
    assert job["error"]["error_id"] == json.loads(raw)["job_id"]
    assert "private-stage-diagnostic" not in json.dumps(job)
    assert saved == [receipt_path.read_bytes()]
    assert RECEIPT["payload"]["full_address"] in saved[0].decode()
