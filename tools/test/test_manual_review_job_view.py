"""Manual-review history remains readable without restarting retired work."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import server
from src.manual_review_job_view import merge_job_snapshot, persisted_receipts
from tools.manual_review_receipt_jobs import ManualReviewMaintenanceManager
from tools.test.test_collection_job_http import fetch
from tools.test.test_collection_job_http import job_api as job_api
from tools.test.test_http_write_access import configured_api as configured_api
from tools.test.test_quality_http_guards import api as api


def test_projection_deduplicates_and_orders_mixed_timestamp_formats():
    legacy = {
        "jobs": [
            {
                "job_id": "older",
                "status": "completed",
                "created_at": "2026-09-23 03:00:00",
            },
            {
                "job_id": "current",
                "status": "running",
                "created_at": "2026-09-23 04:00:00",
            },
        ]
    }
    receipt = {
        "job_id": "current",
        "operation": "manual_review_receipt",
        "status": "completed",
        "created_at": "2026-09-23T12:30:00+08:00",
        "result": {
            "receipt": {
                "action": "manual_location_review",
                "ready_signal": "location_artifacts_complete",
            }
        },
    }
    before = deepcopy((legacy, receipt))
    snapshot = merge_job_snapshot(legacy, [receipt])
    assert [job["job_id"] for job in snapshot["jobs"]] == ["older", "current"]
    assert snapshot["jobs"][-1]["status"] == "completed"
    assert snapshot["jobs"][-1]["receipt_key"] == receipt["result"]["receipt"]
    assert snapshot["running_job_id"] is None
    assert snapshot["queue"] == []
    snapshot["jobs"][-1]["result"]["receipt"]["action"] = "changed"
    assert (legacy, receipt) == before


def test_persisted_view_does_not_create_a_queue(tmp_path):
    assert persisted_receipts(tmp_path) == []
    assert list(tmp_path.iterdir()) == []


def test_invalid_durable_job_is_not_silently_hidden(tmp_path):
    root = tmp_path / "runtime" / "collection-jobs"
    root.mkdir(parents=True)
    path = root / f"{'a' * 32}.json"
    path.write_text(
        json.dumps({"job_id": "wrong-id", "status": "completed"}), encoding="utf-8"
    )
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Invalid collection job receipt"):
        persisted_receipts(tmp_path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("prefix", ["avm", "analysis"])
def test_history_get_does_not_restart_legacy_pending_jobs(
    job_api, monkeypatch, tmp_path, prefix
):
    start_worker = Mock(side_effect=AssertionError("GET must not restart maintenance"))
    monkeypatch.setattr(ManualReviewMaintenanceManager, "_ensure_worker", start_worker)
    path = tmp_path / "avm" / "manual_review_receipt_jobs.json"
    path.parent.mkdir(parents=True)
    legacy = {
        "jobs": [
            {
                "job_id": "legacy-pending",
                "status": "queued",
                "created_at": "2026-09-20 10:00:00",
            }
        ],
        "queue": ["legacy-pending"],
        "running_job_id": None,
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    before = path.read_bytes()
    result = fetch(
        job_api, f"/api/{prefix}/manual_review_receipt_jobs?job_id=legacy-pending"
    )
    assert result["job_count"] == 1
    assert result["job"]["status"] == "interrupted"
    assert result["queued_jobs"] == []
    assert path.read_bytes() == before
    start_worker.assert_not_called()


def test_manual_review_lookup_cannot_read_another_operation(job_api, tmp_path):
    root = tmp_path / "runtime" / "collection-jobs"
    root.mkdir(parents=True)
    job_id = "b" * 32
    (root / f"{job_id}.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "operation": "other_operation",
                "status": "completed",
                "result": {"private": "unrelated-job-content"},
            }
        ),
        encoding="utf-8",
    )
    result = fetch(job_api, f"/api/avm/manual_review_receipt_jobs?job_id={job_id}")
    assert result["job"] is None
    assert result["job_count"] == 0
    assert "unrelated-job-content" not in json.dumps(result)


def test_summary_reads_completed_common_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB_REPOSITORY", SimpleNamespace(enabled=False))
    root = tmp_path / "runtime" / "collection-jobs"
    root.mkdir(parents=True)
    job_id = "c" * 32
    (root / f"{job_id}.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "operation": "manual_review_receipt",
                "status": "completed",
                "created_at": "2026-09-23T10:00:00Z",
                "finished_at": "2026-09-23T10:01:00Z",
                "result": {"receipt": {"action": "review", "ready_signal": "ready"}},
            }
        ),
        encoding="utf-8",
    )
    summary = server._manual_review_receipt_jobs_summary(tmp_path)
    assert summary["last_job_status"] == "completed"
    assert summary["last_job_receipt_key"] == {
        "action": "review",
        "ready_signal": "ready",
    }
