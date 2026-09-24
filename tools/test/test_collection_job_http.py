"""Exercise asynchronous operation receipts through the real HTTP dispatcher."""

import json
import threading
from types import SimpleNamespace

import pytest

from src import collection_jobs, collection_maintenance_jobs, server
from tools.test.collection_job_checks import wait_for_job
from tools.test.test_http_write_access import OPERATOR, WORKER_HEADERS
from tools.test.test_http_write_access import (
    configured_api as configured_api,  # noqa: PLC0414
)
from tools.test.test_quality_http_guards import api as api  # noqa: PLC0414

HEADERS = {"X-FAPAI-Control-Token": OPERATOR}
MAINTENANCE_PATHS = (
    "/api/avm/recent_detail_replay",
    "/api/avm/recent_enrich_maintenance",
    "/api/collection/details/maintenance",
    "/api/avm/fetch_missing_detail_archives",
    "/api/collection/details/fetch_missing",
    "/api/avm/archive_detail_replay",
    "/api/collection/details/prepare_replay",
)
PIPELINE_PATHS = (
    "/api/avm/run",
    "/api/analysis/pipeline/run",
    "/api/avm/start_all_subtasks",
    "/api/avm/run_all_subtasks_sync",
)


@pytest.fixture
def job_api(configured_api, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "AVM_SERVICE", SimpleNamespace(data_dir=str(tmp_path)))
    return configured_api


def fetch(api, path):
    status, _, raw = api("GET", path, headers=HEADERS)
    assert status == 200, raw
    return json.loads(raw)


def finish(api, raw):
    return wait_for_job(lambda url: fetch(api, url), json.loads(raw)["status_url"])


@pytest.mark.parametrize("path", MAINTENANCE_PATHS + PIPELINE_PATHS)
def test_long_operation_returns_before_work_finishes(
    job_api, monkeypatch, path, tmp_path
):
    entered, release = threading.Event(), threading.Event()
    calls = []
    result = {"preserved": ["source-evidence"]}
    if path in PIPELINE_PATHS:
        result["status"] = "completed"

    def run(**options):
        calls.append(options)
        entered.set()
        assert release.wait(5)
        return result

    service = SimpleNamespace(
        prepare_replay=run, fetch_missing_archives=run, run_maintenance=run
    )
    monkeypatch.setattr(server, "_detail_collection_service", lambda _: service)
    monkeypatch.setattr(server, "AVM_PIPELINE", SimpleNamespace(run=run))
    monkeypatch.setattr(
        server.DataHandler,
        "_get_status",
        lambda self, *_: self.send_json({"ready": True}),
    )
    try:
        status, _, raw = job_api("POST", path + "?trace=async", b"{}", HEADERS)
        assert status == 202, raw
        assert entered.wait(2)
        receipt = json.loads(raw)
        assert fetch(job_api, receipt["status_url"])["status"] == "running"
        assert job_api("GET", "/api/status")[0] == 200
        assert len(list((tmp_path / "runtime" / "collection-jobs").glob("*.json"))) == 1
    finally:
        release.set()
    job = finish(job_api, raw)
    assert job["status"] == "completed"
    assert job["result"] == result
    assert len(calls) == 1
    if path in PIPELINE_PATHS:
        assert calls[0]["async_mode"] is False
        assert calls[0]["config"].data_dir == str(tmp_path.resolve())


@pytest.mark.parametrize("path", MAINTENANCE_PATHS + PIPELINE_PATHS)
def test_long_operations_reject_nonobject_input_before_admission(
    job_api, path, tmp_path
):
    status, _, raw = job_api("POST", path, b"[]", HEADERS)
    assert status == 400, raw
    assert not (tmp_path / "runtime").exists()


def test_job_results_require_operator_and_validate_resource_ids(job_api, tmp_path):
    for headers in ({}, WORKER_HEADERS, {"X-FAPAI-Control-Token": "wrong"}):
        assert (
            job_api("GET", "/api/collection/jobs?id=" + "a" * 32, headers=headers)[0]
            == 403
        )
    for suffix in ("", "?id=../outside", "?id=", "?id=" + "f" * 31):
        status, _, raw = job_api(
            "GET", "/api/collection/jobs" + suffix, headers=HEADERS
        )
        assert status == 400
        assert json.loads(raw)["error"]["code"] == "COLLECTION_JOB_INVALID_ID"
    status, _, raw = job_api(
        "GET", "/api/collection/jobs?id=" + "a" * 32, headers=HEADERS
    )
    assert status == 404
    assert json.loads(raw)["error"]["code"] == "COLLECTION_JOB_NOT_FOUND"
    assert not (tmp_path / "runtime").exists()


def test_queue_full_rejects_without_losing_admitted_jobs(job_api, monkeypatch):
    release = threading.Event()

    def run(**_options):
        assert release.wait(5)
        return {}

    monkeypatch.setattr(
        server,
        "_detail_collection_service",
        lambda _: SimpleNamespace(prepare_replay=run),
    )
    admitted = []
    try:
        for _ in range(8):
            status, _, raw = job_api("POST", MAINTENANCE_PATHS[0], b"{}", HEADERS)
            assert status == 202, raw
            admitted.append(raw)
        status, _, raw = job_api("POST", MAINTENANCE_PATHS[0], b"{}", HEADERS)
        assert status == 503
        assert json.loads(raw)["error"]["code"] == "COLLECTION_JOB_QUEUE_FULL"
    finally:
        release.set()
    assert all(finish(job_api, raw)["status"] == "completed" for raw in admitted)


def test_corrupt_job_is_unavailable_without_repair_or_exception_leak(job_api, tmp_path):
    root = tmp_path / "runtime" / "collection-jobs"
    root.mkdir(parents=True)
    job_id = "b" * 32
    path = root / f"{job_id}.json"
    path.write_bytes(b'{"partial":')
    status, _, raw = job_api(
        "GET", "/api/collection/jobs?id=" + job_id, headers=HEADERS
    )
    assert status == 503
    assert json.loads(raw)["error"]["code"] == "COLLECTION_JOB_STATE_UNAVAILABLE"
    assert str(tmp_path).encode() not in raw
    assert path.read_bytes() == b'{"partial":'


def test_failed_report_preserves_previous_bytes_and_skips_reload(
    job_api, monkeypatch, tmp_path
):
    report = tmp_path / "avm" / "recent_detail_replay.json"
    report.parent.mkdir()
    report.write_bytes(b'{"organized":"original"}')
    reloads = []

    def fail(*_args, **_kwargs):
        raise OSError("private filesystem details")

    monkeypatch.setattr(collection_maintenance_jobs, "write_json", fail)
    monkeypatch.setattr(server, "load_data", lambda *_: reloads.append(True))
    monkeypatch.setattr(
        server,
        "_detail_collection_service",
        lambda _: SimpleNamespace(prepare_replay=lambda **_: {"prepared_count": 1}),
    )
    status, _, raw = job_api(
        "POST", MAINTENANCE_PATHS[0], b'{"dry_run": false}', HEADERS
    )
    assert status == 202
    job = finish(job_api, raw)
    assert job["status"] == "failed"
    assert job["error"]["code"] == "AVM_RECENT_DETAIL_REPLAY_FAILED"
    assert "private" not in json.dumps(job)
    assert report.read_bytes() == b'{"organized":"original"}'
    assert reloads == []


@pytest.mark.parametrize(
    "pipeline_status", ["failed", "already_running", "started", None]
)
def test_pipeline_incomplete_work_is_not_a_completed_job(
    job_api, monkeypatch, pipeline_status
):
    monkeypatch.setattr(
        server,
        "AVM_PIPELINE",
        SimpleNamespace(
            run=lambda **_: {
                "status": pipeline_status,
                "state": {"error": "private-error"},
            }
        ),
    )
    status, _, raw = job_api("POST", "/api/avm/run", b'{"mode": "sync"}', HEADERS)
    assert status == 202
    job = finish(job_api, raw)
    assert job["status"] == "failed"
    assert job["error"]["code"] == "AVM_PIPELINE_RUN_FAILED"
    assert "private" not in json.dumps(job)


def test_unpersisted_submission_is_rejected_before_work(job_api, monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("private admission failure")

    monkeypatch.setattr(collection_jobs, "write_json", fail)
    monkeypatch.setattr(
        server,
        "AVM_PIPELINE",
        SimpleNamespace(run=lambda **_: pytest.fail("unpersisted job ran")),
    )
    status, _, raw = job_api("POST", "/api/avm/run", b"{}", HEADERS)
    assert status == 503
    assert json.loads(raw)["error"]["code"] == "COLLECTION_JOB_SUBMISSION_FAILED"
    assert b"private" not in raw


def test_recent_enrich_maintenance_preserves_reconcile_limit(tmp_path):
    calls = []

    def run_maintenance(**options):
        calls.append(options)
        return {"detail_replay_preparation": {}}

    service = SimpleNamespace(run_maintenance=run_maintenance)
    work = collection_maintenance_jobs.prepare_maintenance(
        "recent_enrich_maintenance",
        {"reconcile_limit": 7},
        tmp_path,
        service,
        lambda _root: None,
    )

    assert work() == {"detail_replay_preparation": {}}
    assert calls[0]["reconcile_limit"] == 7


@pytest.mark.parametrize("path", ["/api/save", "/api/collection/seeds/batch"])
def test_explicit_async_seed_batch_returns_durable_job(job_api, monkeypatch, path):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def submit(data):
        calls.append(data)
        entered.set()
        assert release.wait(5)
        return {"status": "ok", "new": 2}

    monkeypatch.setattr(server, "handle_seed_batch_submission", submit)
    payload = {"mode": "async", "items": [{"id": "seed-1"}]}
    try:
        status, _, raw = job_api("POST", path, json.dumps(payload).encode(), HEADERS)
        assert status == 202, raw
        accepted = json.loads(raw)
        assert accepted["status"] == "accepted"
        assert accepted["job_status"] == "queued"
        assert accepted["execution_mode"] == "async"
        assert len(accepted["job_id"]) == 32
        assert all(character in "0123456789abcdef" for character in accepted["job_id"])
        assert accepted["status_url"] == "/api/collection/jobs?id=" + accepted["job_id"]
        assert entered.wait(2)
        assert calls == [{"items": [{"id": "seed-1"}]}]
    finally:
        release.set()

    job = finish(job_api, raw)
    assert job["status"] == "completed", job
    assert job["result"] == {"status": "ok", "new": 2}


def test_explicit_async_seed_batch_records_failure_code(job_api, monkeypatch):
    def fail(_data):
        raise RuntimeError("private seed failure")

    monkeypatch.setattr(server, "handle_seed_batch_submission", fail)
    status, _, raw = job_api(
        "POST",
        "/api/collection/seeds/batch",
        b'{"mode":"async","items":[]}',
        HEADERS,
    )

    assert status == 202, raw
    job = finish(job_api, raw)
    assert job["status"] == "failed"
    assert job["error"]["code"] == "AVM_SEED_BATCH_ASYNC_FAILED"
    assert "private seed failure" not in json.dumps(job)


def test_explicit_async_seed_batch_requires_operator_for_status_access(
    job_api, monkeypatch
):
    submit = pytest.fail
    monkeypatch.setattr(
        server,
        "handle_seed_batch_submission",
        lambda _data: submit("worker credential must not enqueue async seed work"),
    )

    status, _, raw = job_api(
        "POST",
        "/api/collection/seeds/batch",
        b'{"mode":"async","items":[]}',
        WORKER_HEADERS,
    )

    assert status == 403, raw
    assert json.loads(raw)["error"]["code"] == "AVM_CONTROL_PLANE_FORBIDDEN"
