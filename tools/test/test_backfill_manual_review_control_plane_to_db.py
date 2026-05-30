import json
from pathlib import Path

from src.storage.repository import DatabaseSettings, PropertyRepository
from tools.backfill_manual_review_control_plane_to_db import (
    _write_json_payload,
    _write_jsonl_payload,
    backfill_manual_review_control_plane_to_db,
    ensure_manual_review_control_plane_backfilled,
    ensure_manual_review_control_plane_backup_synced,
    export_manual_review_control_plane_to_json,
    generate_manual_review_control_plane_rollout_preflight,
    load_manual_review_control_plane_backup_repairs,
    load_manual_review_control_plane_integrity_history,
    record_manual_review_control_plane_integrity,
    summarize_manual_review_control_plane_guidance,
    summarize_manual_review_control_plane_integrity,
    summarize_manual_review_control_plane_backup_repairs,
    summarize_manual_review_control_plane_integrity_history,
    summarize_manual_review_control_plane_stability,
)


def _make_repo(tmp_path: Path) -> PropertyRepository:
    db_path = tmp_path / "receipt-control-plane.sqlite3"
    repo = PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )
    repo.initialize()
    return repo


def test_write_json_payload_retries_transient_permission_error(tmp_path: Path, monkeypatch):
    path = tmp_path / "payload.json"
    path_type = type(path)
    original_replace = path_type.replace
    calls = {"count": 0}

    def _flaky_replace(self, target):
        if Path(self).name == "payload.json.tmp" and calls["count"] == 0:
            calls["count"] += 1
            raise PermissionError("locked")
        return original_replace(self, target)

    monkeypatch.setattr(path_type, "replace", _flaky_replace)

    _write_json_payload(path, {"ok": True})

    assert calls["count"] == 1
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}


def test_write_jsonl_payload_retries_transient_permission_error(tmp_path: Path, monkeypatch):
    path = tmp_path / "payload.jsonl"
    path_type = type(path)
    original_replace = path_type.replace
    calls = {"count": 0}

    def _flaky_replace(self, target):
        if Path(self).name == "payload.jsonl.tmp" and calls["count"] == 0:
            calls["count"] += 1
            raise PermissionError("locked")
        return original_replace(self, target)

    monkeypatch.setattr(path_type, "replace", _flaky_replace)

    _write_jsonl_payload(path, [{"ok": True}])

    assert calls["count"] == 1
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"ok": True}


def test_backfill_manual_review_control_plane_to_db_imports_receipts_jobs_and_operations(tmp_path: Path):
    data_root = tmp_path / "datas"
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    (avm_root / "manual_review_receipts.json").write_text(
        json.dumps(
            {
                "receipts": [
                    {
                        "action": "manual_location_review",
                        "ready_signal": "location_artifacts_complete",
                        "status": "ready_for_reentry",
                        "payload": {"full_address": "A"},
                        "source": "operator_api",
                        "resolution_notes": "done",
                        "updated_at": "2026-05-15 10:00:00",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (avm_root / "manual_review_receipt_jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "job_id": "job-1",
                        "status": "completed",
                        "receipt_key": {
                            "action": "manual_location_review",
                            "ready_signal": "location_artifacts_complete",
                        },
                        "created_at": "2026-05-15 10:00:01",
                        "started_at": "2026-05-15 10:00:02",
                        "finished_at": "2026-05-15 10:00:03",
                        "maintenance_options": {"window_days": 7},
                        "result_summary": {"reentry_applied": True},
                        "error": None,
                    }
                ],
                "queue": [],
                "running_job_id": None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (avm_root / "manual_review_receipt_operations.jsonl").write_text(
        json.dumps(
            {
                "operation_id": "op-1",
                "operation": "created",
                "action": "manual_location_review",
                "ready_signal": "location_artifacts_complete",
                "status": "ready_for_reentry",
                "payload_fingerprint": "fp-1",
                "source": "operator_api",
                "execution_mode": "async",
                "maintenance_job_id": "job-1",
                "requested_at": "2026-05-15 10:00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    repo = _make_repo(tmp_path)
    result = backfill_manual_review_control_plane_to_db(data_root, repository=repo)

    assert result["receipt_count"] == 1
    assert result["job_count"] == 1
    assert result["operation_count"] == 1

    receipts = repo.list_manual_review_receipts()
    assert receipts["receipts"][0]["action"] == "manual_location_review"
    assert receipts["receipts"][0]["resolution_notes"] == "done"

    jobs_snapshot = repo.manual_review_receipt_jobs_snapshot()
    assert jobs_snapshot["jobs"][0]["job_id"] == "job-1"
    assert jobs_snapshot["jobs"][0]["status"] == "completed"
    assert jobs_snapshot["jobs"][0]["result_summary"]["reentry_applied"] is True

    operations = repo.list_manual_review_receipt_operations(action="manual_location_review")
    assert operations[0]["operation_id"] == "op-1"
    assert operations[0]["maintenance_job_id"] == "job-1"


def test_backfill_manual_review_control_plane_to_db_is_idempotent(tmp_path: Path):
    data_root = tmp_path / "datas"
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "manual_review_receipts.json").write_text(
        json.dumps(
            {
                "receipts": [
                    {
                        "action": "manual_status_review",
                        "ready_signal": "status_reconciled",
                        "status": "ready_for_reentry",
                        "payload": {"status_notes": "ok"},
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    repo = _make_repo(tmp_path)
    first = backfill_manual_review_control_plane_to_db(data_root, repository=repo)
    second = backfill_manual_review_control_plane_to_db(data_root, repository=repo)

    assert first["receipt_count"] == 1
    assert second["receipt_count"] == 1
    assert len(repo.list_manual_review_receipts()["receipts"]) == 1


def test_ensure_manual_review_control_plane_backfilled_only_imports_when_db_is_empty(tmp_path: Path):
    data_root = tmp_path / "datas"
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "manual_review_receipts.json").write_text(
        json.dumps(
            {
                "receipts": [
                    {
                        "action": "manual_area_review",
                        "ready_signal": "area_facts_complete",
                        "status": "ready_for_reentry",
                        "payload": {"area_sqm": 88.0},
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    repo = _make_repo(tmp_path)
    first = ensure_manual_review_control_plane_backfilled(data_root, repository=repo)
    second = ensure_manual_review_control_plane_backfilled(data_root, repository=repo)

    assert first["bootstrapped"] is True
    assert first["receipt_count"] == 1
    assert second["bootstrapped"] is False
    assert second["existing_counts"]["receipt_count"] == 1


def test_export_manual_review_control_plane_to_json_writes_repository_state(tmp_path: Path):
    data_root = tmp_path / "datas"
    repo = _make_repo(tmp_path)

    receipt = {
        "action": "manual_location_review",
        "ready_signal": "location_artifacts_complete",
        "status": "ready_for_reentry",
        "payload": {
            "full_address": "A",
            "community_name": "B",
            "business_area": "C",
            "latitude": 31.2,
            "longitude": 121.5,
        },
        "source": "operator_api",
        "resolution_notes": "complete",
    }
    repo.upsert_manual_review_receipt(receipt)
    job = repo.create_manual_review_receipt_job(
        receipt_key={
            "action": receipt["action"],
            "ready_signal": receipt["ready_signal"],
        },
        maintenance_options={"window_days": 7},
    )
    repo.update_manual_review_receipt_job(
        job["job_id"],
        status="completed",
        started_at="2026-05-15 10:00:02",
        finished_at="2026-05-15 10:00:03",
        result_summary={"reentry_applied": True},
    )
    repo.append_manual_review_receipt_operation(
        operation="updated",
        receipt=receipt,
        execution_mode="async",
        maintenance_job_id=job["job_id"],
    )

    result = export_manual_review_control_plane_to_json(data_root, repository=repo)

    assert result["exported"] is True
    assert result["reason"] == "repository_exported"
    assert result["receipt_count"] == 1
    assert result["job_count"] == 1
    assert result["operation_count"] == 1

    avm_root = data_root / "avm"
    receipts_payload = json.loads((avm_root / "manual_review_receipts.json").read_text(encoding="utf-8"))
    assert receipts_payload["receipts"][0]["action"] == "manual_location_review"
    assert receipts_payload["receipts"][0]["resolution_notes"] == "complete"

    jobs_payload = json.loads((avm_root / "manual_review_receipt_jobs.json").read_text(encoding="utf-8"))
    assert jobs_payload["jobs"][0]["job_id"] == job["job_id"]
    assert jobs_payload["jobs"][0]["status"] == "completed"
    assert jobs_payload["jobs"][0]["result_summary"]["reentry_applied"] is True

    operation_lines = (avm_root / "manual_review_receipt_operations.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(operation_lines) == 1
    operation_payload = json.loads(operation_lines[0])
    assert operation_payload["maintenance_job_id"] == job["job_id"]
    assert operation_payload["execution_mode"] == "async"


def test_export_manual_review_control_plane_to_json_noops_when_repository_is_disabled(tmp_path: Path):
    data_root = tmp_path / "datas"
    repo = PropertyRepository(
        DatabaseSettings(
            url=None,
            echo=False,
            enable_postgis=False,
            auto_create=False,
            enabled=False,
        )
    )

    result = export_manual_review_control_plane_to_json(data_root, repository=repo)

    assert result["exported"] is False
    assert result["reason"] == "repository_disabled"
    assert not (data_root / "avm" / "manual_review_receipts.json").exists()


def test_ensure_manual_review_control_plane_backup_synced_repairs_missing_backup(tmp_path: Path):
    data_root = tmp_path / "datas"
    repo = _make_repo(tmp_path)
    repo.upsert_manual_review_receipt(
        {
            "action": "manual_location_review",
            "ready_signal": "location_artifacts_complete",
            "status": "ready_for_reentry",
            "payload": {"full_address": "A"},
        }
    )

    first = ensure_manual_review_control_plane_backup_synced(data_root, repository=repo)
    second = ensure_manual_review_control_plane_backup_synced(data_root, repository=repo)

    assert first["repaired"] is True
    assert first["reason"] == "repaired_missing_backup"
    assert first["receipt_count"] == 1
    assert (data_root / "avm" / "manual_review_receipts.json").exists()
    repairs = load_manual_review_control_plane_backup_repairs(data_root)
    assert len(repairs) == 1
    assert repairs[0]["reason"] == "repaired_missing_backup"
    repair_summary = summarize_manual_review_control_plane_backup_repairs(repairs)
    assert repair_summary["repair_count"] == 1
    assert repair_summary["last_repair_reason"] == "repaired_missing_backup"
    assert second["repaired"] is False
    assert second["reason"] == "already_in_sync"
    assert len(load_manual_review_control_plane_backup_repairs(data_root)) == 1


def test_summarize_manual_review_control_plane_integrity_covers_runtime_json_and_healthy_repository():
    runtime_json = summarize_manual_review_control_plane_integrity(
        {"repository_enabled": False, "state_source": "json_fallback"},
        {"backup_state": "runtime_json", "backup_reason": "repository_disabled"},
        {"repair_count": 0, "last_repair_reason": None},
    )
    assert runtime_json["integrity_status"] == "healthy_json_runtime"
    assert runtime_json["attention_required"] is False
    assert runtime_json["follow_up_recommended"] is False

    healthy_repo = summarize_manual_review_control_plane_integrity(
        {"repository_enabled": True, "state_source": "repository"},
        {"backup_state": "in_sync", "backup_reason": "already_in_sync"},
        {"repair_count": 0, "last_repair_reason": None},
    )
    assert healthy_repo["integrity_status"] == "healthy_repository"
    assert healthy_repo["attention_required"] is False
    assert healthy_repo["follow_up_recommended"] is False


def test_record_manual_review_control_plane_integrity_dedupes_unchanged_states(tmp_path: Path):
    data_root = tmp_path / "datas"
    runtime_json = summarize_manual_review_control_plane_integrity(
        {"repository_enabled": False, "state_source": "json_fallback"},
        {"backup_state": "runtime_json", "backup_reason": "repository_disabled"},
        {"repair_count": 0, "last_repair_reason": None},
    )
    repaired = summarize_manual_review_control_plane_integrity(
        {"repository_enabled": True, "state_source": "repository"},
        {"backup_state": "in_sync", "backup_reason": "repaired_missing_backup"},
        {"repair_count": 1, "last_repair_reason": "repaired_missing_backup"},
    )

    first = record_manual_review_control_plane_integrity(data_root, runtime_json)
    second = record_manual_review_control_plane_integrity(data_root, runtime_json)
    third = record_manual_review_control_plane_integrity(data_root, repaired)

    assert first["recorded"] is True
    assert second["recorded"] is False
    assert third["recorded"] is True

    history = load_manual_review_control_plane_integrity_history(data_root)
    assert len(history) == 2
    assert history[0]["integrity_status"] == "healthy_json_runtime"
    assert history[1]["integrity_status"] == "repaired_recently"
    summary = summarize_manual_review_control_plane_integrity_history(history)
    assert summary["transition_count"] == 2
    assert summary["last_integrity_status"] == "repaired_recently"


def test_summarize_manual_review_control_plane_stability_covers_stable_and_watch_states():
    stable = summarize_manual_review_control_plane_stability(
        {
            "integrity_status": "healthy_json_runtime",
            "attention_required": False,
            "follow_up_recommended": False,
        },
        {
            "transition_count": 1,
            "last_integrity_status": "healthy_json_runtime",
            "top_integrity_status": "healthy_json_runtime",
        },
    )
    assert stable["stability_status"] == "stable_json_runtime"
    assert stable["attention_required"] is False
    assert stable["follow_up_recommended"] is False

    watch = summarize_manual_review_control_plane_stability(
        {
            "integrity_status": "repaired_recently",
            "attention_required": False,
            "follow_up_recommended": True,
        },
        {
            "transition_count": 2,
            "last_integrity_status": "repaired_recently",
            "top_integrity_status": "healthy_json_runtime",
        },
    )
    assert watch["stability_status"] == "watch_repaired_repository"
    assert watch["attention_required"] is False
    assert watch["follow_up_recommended"] is True


def test_summarize_manual_review_control_plane_guidance_covers_stable_watch_and_degraded_states():
    stable = summarize_manual_review_control_plane_guidance(
        {
            "integrity_status": "healthy_json_runtime",
            "attention_required": False,
            "follow_up_recommended": False,
        },
        {
            "stability_status": "stable_json_runtime",
            "attention_required": False,
            "follow_up_recommended": False,
        },
        {"repair_count": 0, "last_repair_reason": None},
    )
    assert stable["guidance_status"] == "no_action_required"
    assert stable["requires_operator_action"] is False
    assert stable["priority"] == "info"

    watch = summarize_manual_review_control_plane_guidance(
        {
            "integrity_status": "repaired_recently",
            "attention_required": False,
            "follow_up_recommended": True,
        },
        {
            "stability_status": "watch_repaired_repository",
            "attention_required": False,
            "follow_up_recommended": True,
        },
        {"repair_count": 1, "last_repair_reason": "repaired_missing_backup"},
    )
    assert watch["guidance_status"] == "monitor_recent_repair"
    assert watch["requires_operator_action"] is False
    assert watch["priority"] == "warning"
    assert watch["top_guidance_reason"] == "repaired_missing_backup"

    degraded = summarize_manual_review_control_plane_guidance(
        {
            "integrity_status": "degraded_missing_backup",
            "attention_required": True,
            "follow_up_recommended": True,
        },
        {
            "stability_status": "unstable_repository",
            "attention_required": True,
            "follow_up_recommended": True,
        },
        {"repair_count": 3, "last_repair_reason": "repaired_count_mismatch"},
    )
    assert degraded["guidance_status"] == "repair_backup_immediately"
    assert degraded["requires_operator_action"] is True
    assert degraded["priority"] == "critical"


def test_generate_manual_review_control_plane_rollout_preflight_requires_database_configuration(tmp_path: Path):
    data_root = tmp_path / "datas"
    report = generate_manual_review_control_plane_rollout_preflight(data_root)

    assert report["preflight_status"] == "requires_database_configuration"
    assert report["repository_enabled"] is False
    assert "configure_database_repository" in report["recommended_next_steps"]


def test_generate_manual_review_control_plane_rollout_preflight_reports_ready_for_backfill(tmp_path: Path):
    data_root = tmp_path / "datas"
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "manual_review_receipts.json").write_text(
        json.dumps(
            {
                "receipts": [
                    {
                        "action": "manual_location_review",
                        "ready_signal": "location_artifacts_complete",
                        "status": "ready_for_reentry",
                        "payload": {"full_address": "A"},
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    repo = _make_repo(tmp_path)

    report = generate_manual_review_control_plane_rollout_preflight(data_root, repository=repo)

    assert report["preflight_status"] == "ready_for_backfill"
    assert report["repository_enabled"] is True
    assert report["repository_counts"]["receipt_count"] == 0
    assert report["source_json_counts"]["receipt_count"] == 1
    assert "run_control_plane_backfill" in report["recommended_next_steps"]
