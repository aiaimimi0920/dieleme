#!/usr/bin/env python3
"""Backfill manual review receipt control-plane JSON state into DB tables."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from src.storage.repository import DatabaseSettings, PropertyRepository, create_repository_from_env


def _build_repo(db_url: str | None, repository: PropertyRepository | None = None) -> PropertyRepository:
    if repository is not None:
        return repository
    if db_url:
        repo = PropertyRepository(
            DatabaseSettings(
                url=db_url,
                echo=False,
                enable_postgis=True,
                auto_create=True,
                enabled=True,
            )
        )
        repo.initialize()
        return repo
    repo = create_repository_from_env()
    repo.initialize()
    return repo


def _load_receipt_snapshot(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"receipts": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("receipts"), list):
        return {"receipts": []}
    return {"receipts": [dict(item) for item in payload.get("receipts") or [] if isinstance(item, dict)]}


def _load_job_snapshot(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"jobs": [], "queue": [], "running_job_id": None}
    jobs = payload.get("jobs") if isinstance(payload, dict) else []
    queue = payload.get("queue") if isinstance(payload, dict) else []
    running_job_id = payload.get("running_job_id") if isinstance(payload, dict) else None
    return {
        "jobs": [dict(item) for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else [],
        "queue": [str(item) for item in queue if str(item or "").strip()] if isinstance(queue, list) else [],
        "running_job_id": str(running_job_id).strip() if running_job_id else None,
    }


def _load_operation_snapshot(path: Path) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    items: List[Dict[str, Any]] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            items.append(payload)
    return items


def _write_json_payload(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _replace_with_retry(temp_path, path)


def _write_jsonl_payload(path: Path, payloads: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    body = "\n".join(json.dumps(payload, ensure_ascii=False) for payload in payloads)
    if body:
        body += "\n"
    temp_path.write_text(body, encoding="utf-8")
    _replace_with_retry(temp_path, path)


def _replace_with_retry(temp_path: Path, path: Path, *, attempts: int = 5, delay_seconds: float = 0.02) -> None:
    last_error: PermissionError | None = None
    for attempt in range(max(attempts, 1)):
        try:
            temp_path.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt >= max(attempts, 1) - 1:
                break
            time.sleep(delay_seconds)
    if temp_path.exists() and path.exists():
        temp_path.unlink(missing_ok=True)
    if last_error is not None:
        raise last_error


def _backup_repair_log_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_control_plane_backup_repairs.jsonl"


def load_manual_review_control_plane_backup_repairs(data_root: Path) -> list[dict[str, Any]]:
    return _load_operation_snapshot(_backup_repair_log_path(data_root))


def _integrity_history_log_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_control_plane_integrity_history.jsonl"


def load_manual_review_control_plane_integrity_history(data_root: Path) -> list[dict[str, Any]]:
    return _load_operation_snapshot(_integrity_history_log_path(data_root))


def _append_manual_review_control_plane_backup_repair(
    data_root: Path,
    *,
    reason: str,
    source_counts: dict[str, int],
    backup_counts_before: dict[str, int],
) -> dict[str, Any]:
    event = {
        "repair_id": str(uuid4()),
        "reason": str(reason or "").strip(),
        "repaired_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_receipt_count": int(source_counts.get("receipt_count", 0) or 0),
        "source_job_count": int(source_counts.get("job_count", 0) or 0),
        "source_operation_count": int(source_counts.get("operation_count", 0) or 0),
        "backup_receipt_count_before": int(backup_counts_before.get("receipt_count", 0) or 0),
        "backup_job_count_before": int(backup_counts_before.get("job_count", 0) or 0),
        "backup_operation_count_before": int(backup_counts_before.get("operation_count", 0) or 0),
    }
    path = _backup_repair_log_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def summarize_manual_review_control_plane_backup_repairs(repairs: list[dict[str, Any]] | None) -> dict[str, Any]:
    normalized = [dict(item) for item in repairs or [] if isinstance(item, dict)]
    last_repair = normalized[-1] if normalized else None
    reason_counts: dict[str, int] = {}
    for item in normalized:
        reason = str(item.get("reason") or "").strip()
        if not reason:
            continue
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    top_reason = None
    if reason_counts:
        top_reason = sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return {
        "repair_count": len(normalized),
        "repair_reason_counts": reason_counts,
        "last_repair_at": last_repair.get("repaired_at") if last_repair else None,
        "last_repair_reason": last_repair.get("reason") if last_repair else None,
        "top_repair_reason": top_reason,
    }


def record_manual_review_control_plane_integrity(
    data_root: Path,
    integrity: dict[str, Any] | None,
) -> dict[str, Any]:
    integrity = dict(integrity or {})
    event = {
        "integrity_id": str(uuid4()),
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "integrity_status": str(integrity.get("integrity_status") or "unknown"),
        "attention_required": bool(integrity.get("attention_required")),
        "follow_up_recommended": bool(integrity.get("follow_up_recommended")),
        "repository_enabled": bool(integrity.get("repository_enabled")),
        "state_source": str(integrity.get("state_source") or ""),
        "backup_state": str(integrity.get("backup_state") or ""),
        "backup_reason": str(integrity.get("backup_reason") or ""),
        "repair_count": int(integrity.get("repair_count", 0) or 0),
        "last_repair_reason": integrity.get("last_repair_reason"),
        "top_repair_reason": integrity.get("top_repair_reason"),
    }
    path = _integrity_history_log_path(data_root)
    history = load_manual_review_control_plane_integrity_history(data_root)
    last = history[-1] if history else None
    if last:
        comparable_keys = (
            "integrity_status",
            "attention_required",
            "follow_up_recommended",
            "repository_enabled",
            "state_source",
            "backup_state",
            "backup_reason",
            "repair_count",
            "last_repair_reason",
            "top_repair_reason",
        )
        if all(last.get(key) == event.get(key) for key in comparable_keys):
            return {"recorded": False, "event": dict(last)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return {"recorded": True, "event": event}


def summarize_manual_review_control_plane_integrity_history(history: list[dict[str, Any]] | None) -> dict[str, Any]:
    normalized = [dict(item) for item in history or [] if isinstance(item, dict)]
    last = normalized[-1] if normalized else None
    status_counts: dict[str, int] = {}
    for item in normalized:
        status = str(item.get("integrity_status") or "").strip()
        if not status:
            continue
        status_counts[status] = status_counts.get(status, 0) + 1
    top_status = None
    if status_counts:
        top_status = sorted(status_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return {
        "transition_count": len(normalized),
        "status_counts": status_counts,
        "last_recorded_at": last.get("recorded_at") if last else None,
        "last_integrity_status": last.get("integrity_status") if last else None,
        "top_integrity_status": top_status,
    }


def summarize_manual_review_control_plane_integrity(
    storage: dict[str, Any] | None,
    backup: dict[str, Any] | None,
    repairs_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    storage = dict(storage or {})
    backup = dict(backup or {})
    repairs_summary = dict(repairs_summary or {})
    repository_enabled = bool(storage.get("repository_enabled"))
    state_source = str(storage.get("state_source") or "")
    backup_state = str(backup.get("backup_state") or "")
    backup_reason = str(backup.get("backup_reason") or "")
    repair_count = int(repairs_summary.get("repair_count", 0) or 0)
    last_repair_reason = repairs_summary.get("last_repair_reason")
    top_repair_reason = repairs_summary.get("top_repair_reason")

    integrity_status = "unknown"
    attention_required = False
    follow_up_recommended = False

    if not repository_enabled and backup_state == "runtime_json":
        integrity_status = "healthy_json_runtime"
    elif repository_enabled and backup_state == "in_sync":
        if backup_reason.startswith("repaired_") or repair_count > 0:
            integrity_status = "repaired_recently"
            follow_up_recommended = True
        else:
            integrity_status = "healthy_repository"
    elif repository_enabled and backup_state == "missing_backup":
        integrity_status = "degraded_missing_backup"
        attention_required = True
        follow_up_recommended = True
    elif repository_enabled and backup_state == "count_mismatch":
        integrity_status = "degraded_count_mismatch"
        attention_required = True
        follow_up_recommended = True

    return {
        "integrity_status": integrity_status,
        "attention_required": attention_required,
        "follow_up_recommended": follow_up_recommended,
        "repository_enabled": repository_enabled,
        "state_source": state_source,
        "backup_state": backup_state,
        "backup_reason": backup_reason,
        "repair_count": repair_count,
        "last_repair_reason": last_repair_reason,
        "top_repair_reason": top_repair_reason,
    }


def summarize_manual_review_control_plane_stability(
    integrity: dict[str, Any] | None,
    integrity_history_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    integrity = dict(integrity or {})
    history = dict(integrity_history_summary or {})
    integrity_status = str(integrity.get("integrity_status") or "unknown")
    attention_required = bool(integrity.get("attention_required"))
    follow_up_recommended = bool(integrity.get("follow_up_recommended"))
    transition_count = int(history.get("transition_count", 0) or 0)
    last_integrity_status = history.get("last_integrity_status")
    top_integrity_status = history.get("top_integrity_status")

    stability_status = "unknown_stability"
    if integrity_status == "healthy_json_runtime":
        stability_status = "stable_json_runtime"
    elif integrity_status == "healthy_repository":
        stability_status = "stable_repository"
    elif integrity_status == "repaired_recently":
        stability_status = "watch_repaired_repository"
    elif integrity_status.startswith("degraded_"):
        stability_status = "unstable_repository"

    return {
        "stability_status": stability_status,
        "attention_required": attention_required,
        "follow_up_recommended": follow_up_recommended,
        "transition_count": transition_count,
        "last_integrity_status": last_integrity_status,
        "top_integrity_status": top_integrity_status,
    }


def summarize_manual_review_control_plane_guidance(
    integrity: dict[str, Any] | None,
    stability: dict[str, Any] | None,
    repairs_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    integrity = dict(integrity or {})
    stability = dict(stability or {})
    repairs_summary = dict(repairs_summary or {})
    integrity_status = str(integrity.get("integrity_status") or "unknown")
    stability_status = str(stability.get("stability_status") or "unknown_stability")
    last_repair_reason = repairs_summary.get("last_repair_reason")

    guidance_status = "unknown_guidance"
    requires_operator_action = False
    priority = "info"
    recommended_actions: list[str] = []

    if stability_status in {"stable_json_runtime", "stable_repository"}:
        guidance_status = "no_action_required"
        recommended_actions = ["continue_monitoring_status_surfaces"]
    elif stability_status == "watch_repaired_repository":
        guidance_status = "monitor_recent_repair"
        priority = "warning"
        recommended_actions = [
            "review_backup_repairs_history",
            "monitor_backend_status",
        ]
    elif integrity_status == "degraded_missing_backup":
        guidance_status = "repair_backup_immediately"
        requires_operator_action = True
        priority = "critical"
        recommended_actions = [
            "inspect_backup_export_path",
            "run_control_plane_backup_export",
            "verify_backend_status_again",
        ]
    elif integrity_status == "degraded_count_mismatch":
        guidance_status = "investigate_backup_mismatch"
        requires_operator_action = True
        priority = "critical"
        recommended_actions = [
            "compare_repository_and_backup_counts",
            "review_backup_repairs_history",
            "verify_backend_status_again",
        ]
    else:
        recommended_actions = ["review_control_plane_status"]

    return {
        "guidance_status": guidance_status,
        "requires_operator_action": requires_operator_action,
        "priority": priority,
        "recommended_actions": recommended_actions,
        "top_guidance_reason": last_repair_reason or integrity_status,
    }


def summarize_manual_review_control_plane_guidance(
    integrity: dict[str, Any] | None,
    stability: dict[str, Any] | None,
    repairs_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    integrity = dict(integrity or {})
    stability = dict(stability or {})
    repairs_summary = dict(repairs_summary or {})
    integrity_status = str(integrity.get("integrity_status") or "unknown")
    stability_status = str(stability.get("stability_status") or "unknown_stability")
    last_repair_reason = repairs_summary.get("last_repair_reason")

    guidance_status = "unknown_guidance"
    requires_operator_action = False
    priority = "info"
    recommended_actions: list[str] = []

    if stability_status in {"stable_json_runtime", "stable_repository"}:
        guidance_status = "no_action_required"
        recommended_actions = ["continue_monitoring_status_surfaces"]
    elif stability_status == "watch_repaired_repository":
        guidance_status = "monitor_recent_repair"
        priority = "warning"
        recommended_actions = [
            "review_backup_repairs_history",
            "monitor_backend_status",
        ]
    elif integrity_status == "degraded_missing_backup":
        guidance_status = "repair_backup_immediately"
        requires_operator_action = True
        priority = "critical"
        recommended_actions = [
            "inspect_backup_export_path",
            "run_control_plane_backup_export",
            "verify_backend_status_again",
        ]
    elif integrity_status == "degraded_count_mismatch":
        guidance_status = "investigate_backup_mismatch"
        requires_operator_action = True
        priority = "critical"
        recommended_actions = [
            "compare_repository_and_backup_counts",
            "review_backup_repairs_history",
            "verify_backend_status_again",
        ]
    else:
        recommended_actions = ["review_control_plane_status"]

    return {
        "guidance_status": guidance_status,
        "requires_operator_action": requires_operator_action,
        "priority": priority,
        "recommended_actions": recommended_actions,
        "top_guidance_reason": last_repair_reason or integrity_status,
    }


def backfill_manual_review_control_plane_to_db(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    avm_root = data_root / "avm"

    receipt_snapshot = _load_receipt_snapshot(avm_root / "manual_review_receipts.json")
    job_snapshot = _load_job_snapshot(avm_root / "manual_review_receipt_jobs.json")
    operation_snapshot = _load_operation_snapshot(avm_root / "manual_review_receipt_operations.jsonl")

    imported_receipts = repo.import_manual_review_receipt_snapshot(receipt_snapshot)
    imported_jobs = repo.import_manual_review_receipt_jobs_snapshot(job_snapshot)
    imported_operations = repo.import_manual_review_receipt_operations(operation_snapshot)

    return {
        "receipt_count": imported_receipts,
        "job_count": imported_jobs,
        "operation_count": imported_operations,
        "source_receipt_count": len(receipt_snapshot.get("receipts") or []),
        "source_job_count": len(job_snapshot.get("jobs") or []),
        "source_operation_count": len(operation_snapshot),
    }


def export_manual_review_control_plane_to_json(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    if not repo.enabled:
        return {
            "exported": False,
            "reason": "repository_disabled",
            "receipt_count": 0,
            "job_count": 0,
            "operation_count": 0,
        }

    avm_root = data_root / "avm"
    receipt_snapshot = repo.list_manual_review_receipts()
    job_snapshot = repo.manual_review_receipt_jobs_snapshot()
    operation_snapshot = repo.list_manual_review_receipt_operations()

    _write_json_payload(avm_root / "manual_review_receipts.json", receipt_snapshot)
    _write_json_payload(avm_root / "manual_review_receipt_jobs.json", job_snapshot)
    _write_jsonl_payload(avm_root / "manual_review_receipt_operations.jsonl", operation_snapshot)

    return {
        "exported": True,
        "reason": "repository_exported",
        "receipt_count": len(receipt_snapshot.get("receipts") or []),
        "job_count": len(job_snapshot.get("jobs") or []),
        "operation_count": len(operation_snapshot),
    }


def sync_manual_review_control_plane_json_backup(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    if not repo.enabled:
        return {
            "exported": False,
            "reason": "repository_disabled",
            "receipt_count": 0,
            "job_count": 0,
            "operation_count": 0,
        }
    return export_manual_review_control_plane_to_json(data_root, repository=repo)


def ensure_manual_review_control_plane_backup_synced(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    if not repo.enabled:
        return {
            "repaired": False,
            "reason": "repository_disabled",
            "receipt_count": 0,
            "job_count": 0,
            "operation_count": 0,
        }

    ensure_manual_review_control_plane_backfilled(data_root, repository=repo)
    avm_root = data_root / "avm"
    receipt_path = avm_root / "manual_review_receipts.json"
    jobs_path = avm_root / "manual_review_receipt_jobs.json"
    operations_path = avm_root / "manual_review_receipt_operations.jsonl"
    files_present = {
        "receipts": receipt_path.exists(),
        "jobs": jobs_path.exists(),
        "operations": operations_path.exists(),
    }
    source_counts = repo.manual_review_control_plane_counts()
    backup_counts = {
        "receipt_count": len(_load_receipt_snapshot(receipt_path).get("receipts") or []),
        "job_count": len(_load_job_snapshot(jobs_path).get("jobs") or []),
        "operation_count": len(_load_operation_snapshot(operations_path)),
    }
    counts_match = (
        source_counts["receipt_count"] == backup_counts["receipt_count"]
        and source_counts["job_count"] == backup_counts["job_count"]
        and source_counts["operation_count"] == backup_counts["operation_count"]
    )
    if all(files_present.values()) and counts_match:
        return {
            "repaired": False,
            "reason": "already_in_sync",
            **source_counts,
        }

    reason = "repaired_missing_backup" if not all(files_present.values()) else "repaired_count_mismatch"
    _append_manual_review_control_plane_backup_repair(
        data_root,
        reason=reason,
        source_counts=source_counts,
        backup_counts_before=backup_counts,
    )
    export = sync_manual_review_control_plane_json_backup(data_root, repository=repo)
    return {
        "repaired": True,
        "reason": reason,
        "receipt_count": int(export.get("receipt_count", 0) or 0),
        "job_count": int(export.get("job_count", 0) or 0),
        "operation_count": int(export.get("operation_count", 0) or 0),
    }


def ensure_manual_review_control_plane_backfilled(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    if not repo.enabled:
        return {
            "bootstrapped": False,
            "reason": "repository_disabled",
            "existing_counts": {"receipt_count": 0, "job_count": 0, "operation_count": 0},
        }

    counts = repo.manual_review_control_plane_counts()
    if any(counts.values()):
        return {
            "bootstrapped": False,
            "reason": "repository_not_empty",
            "existing_counts": counts,
        }

    preview = backfill_manual_review_control_plane_to_db(data_root, repository=repo)
    bootstrapped = any(
        int(preview.get(key, 0) or 0) > 0
        for key in ("receipt_count", "job_count", "operation_count")
    )
    return {
        "bootstrapped": bootstrapped,
        "reason": "imported" if bootstrapped else "source_empty",
        "existing_counts": counts,
        **preview,
    }


def describe_manual_review_control_plane_storage(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    if repo.enabled:
        bootstrap = ensure_manual_review_control_plane_backfilled(data_root, repository=repo)
        counts = repo.manual_review_control_plane_counts()
        return {
            "repository_enabled": True,
            "state_source": "repository",
            "bootstrap_reason": bootstrap.get("reason"),
            "receipt_count": counts["receipt_count"],
            "job_count": counts["job_count"],
            "operation_count": counts["operation_count"],
        }

    receipt_snapshot = _load_receipt_snapshot(data_root / "avm" / "manual_review_receipts.json")
    job_snapshot = _load_job_snapshot(data_root / "avm" / "manual_review_receipt_jobs.json")
    operation_snapshot = _load_operation_snapshot(data_root / "avm" / "manual_review_receipt_operations.jsonl")
    return {
        "repository_enabled": False,
        "state_source": "json_fallback",
        "bootstrap_reason": "repository_disabled",
        "receipt_count": len(receipt_snapshot.get("receipts") or []),
        "job_count": len(job_snapshot.get("jobs") or []),
        "operation_count": len(operation_snapshot),
    }


def describe_manual_review_control_plane_backup(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    avm_root = data_root / "avm"
    receipt_path = avm_root / "manual_review_receipts.json"
    jobs_path = avm_root / "manual_review_receipt_jobs.json"
    operations_path = avm_root / "manual_review_receipt_operations.jsonl"

    receipt_snapshot = _load_receipt_snapshot(receipt_path)
    job_snapshot = _load_job_snapshot(jobs_path)
    operation_snapshot = _load_operation_snapshot(operations_path)
    backup_counts = {
        "backup_receipt_count": len(receipt_snapshot.get("receipts") or []),
        "backup_job_count": len(job_snapshot.get("jobs") or []),
        "backup_operation_count": len(operation_snapshot),
    }
    files_present = {
        "receipts": receipt_path.exists(),
        "jobs": jobs_path.exists(),
        "operations": operations_path.exists(),
    }

    if not repo.enabled:
        return {
            "repository_enabled": False,
            "backup_state": "runtime_json",
            "backup_reason": "repository_disabled",
            "source_receipt_count": backup_counts["backup_receipt_count"],
            "source_job_count": backup_counts["backup_job_count"],
            "source_operation_count": backup_counts["backup_operation_count"],
            "all_backup_files_present": all(files_present.values()),
            "backup_files_present": files_present,
            **backup_counts,
        }

    repair = ensure_manual_review_control_plane_backup_synced(data_root, repository=repo)
    receipt_snapshot = _load_receipt_snapshot(receipt_path)
    job_snapshot = _load_job_snapshot(jobs_path)
    operation_snapshot = _load_operation_snapshot(operations_path)
    backup_counts = {
        "backup_receipt_count": len(receipt_snapshot.get("receipts") or []),
        "backup_job_count": len(job_snapshot.get("jobs") or []),
        "backup_operation_count": len(operation_snapshot),
    }
    files_present = {
        "receipts": receipt_path.exists(),
        "jobs": jobs_path.exists(),
        "operations": operations_path.exists(),
    }
    source_counts = repo.manual_review_control_plane_counts()
    counts_match = (
        source_counts["receipt_count"] == backup_counts["backup_receipt_count"]
        and source_counts["job_count"] == backup_counts["backup_job_count"]
        and source_counts["operation_count"] == backup_counts["backup_operation_count"]
    )
    if all(files_present.values()) and counts_match:
        backup_state = "in_sync"
    elif not any(files_present.values()):
        backup_state = "missing_backup"
    else:
        backup_state = "count_mismatch"
    return {
        "repository_enabled": True,
        "backup_state": backup_state,
        "backup_reason": repair.get("reason"),
        "source_receipt_count": source_counts["receipt_count"],
        "source_job_count": source_counts["job_count"],
        "source_operation_count": source_counts["operation_count"],
        "all_backup_files_present": all(files_present.values()),
        "backup_files_present": files_present,
        **backup_counts,
    }


def generate_manual_review_control_plane_rollout_preflight(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    avm_root = data_root / "avm"
    receipt_snapshot = _load_receipt_snapshot(avm_root / "manual_review_receipts.json")
    job_snapshot = _load_job_snapshot(avm_root / "manual_review_receipt_jobs.json")
    operation_snapshot = _load_operation_snapshot(avm_root / "manual_review_receipt_operations.jsonl")
    source_json_counts = {
        "receipt_count": len(receipt_snapshot.get("receipts") or []),
        "job_count": len(job_snapshot.get("jobs") or []),
        "operation_count": len(operation_snapshot),
    }
    backup_files_present = {
        "receipts": (avm_root / "manual_review_receipts.json").exists(),
        "jobs": (avm_root / "manual_review_receipt_jobs.json").exists(),
        "operations": (avm_root / "manual_review_receipt_operations.jsonl").exists(),
    }

    recommended_next_steps: list[str] = []
    recommended_commands: list[str] = []

    if not repo.settings.url:
        preflight_status = "requires_database_configuration"
        recommended_next_steps = [
            "configure_database_repository",
            "run_alembic_upgrade_head",
            "rerun_rollout_preflight",
        ]
        recommended_commands = [
            "set FAPAI_DB_URL=<your-db-url>",
            "alembic upgrade head",
        ]
        return {
            "preflight_status": preflight_status,
            "repository_enabled": False,
            "repository_counts": {"receipt_count": 0, "job_count": 0, "operation_count": 0},
            "source_json_counts": source_json_counts,
            "backup_files_present": backup_files_present,
            "recommended_next_steps": recommended_next_steps,
            "recommended_commands": recommended_commands,
            "read_only": True,
        }

    if not repo.enabled:
        preflight_status = "repository_disabled_by_config"
        recommended_next_steps = [
            "enable_database_repository",
            "run_alembic_upgrade_head",
            "rerun_rollout_preflight",
        ]
        recommended_commands = [
            "set FAPAI_DB_ENABLED=1",
            "alembic upgrade head",
        ]
        return {
            "preflight_status": preflight_status,
            "repository_enabled": False,
            "repository_counts": {"receipt_count": 0, "job_count": 0, "operation_count": 0},
            "source_json_counts": source_json_counts,
            "backup_files_present": backup_files_present,
            "recommended_next_steps": recommended_next_steps,
            "recommended_commands": recommended_commands,
            "read_only": True,
        }

    repository_counts = repo.manual_review_control_plane_counts()
    counts_match = (
        repository_counts["receipt_count"] == source_json_counts["receipt_count"]
        and repository_counts["job_count"] == source_json_counts["job_count"]
        and repository_counts["operation_count"] == source_json_counts["operation_count"]
    )
    if any(repository_counts.values()):
        if all(backup_files_present.values()) and counts_match:
            preflight_status = "ready_for_runtime_validation"
            recommended_next_steps = [
                "verify_backend_status",
                "verify_release_gate",
                "exercise_control_plane_crud",
            ]
            recommended_commands = [
                'curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_status"',
                'curl "http://127.0.0.1:8001/api/analysis/release_gate"',
            ]
        else:
            preflight_status = "ready_for_backup_sync"
            recommended_next_steps = [
                "run_control_plane_backup_export",
                "verify_backend_status",
                "verify_backup_status",
            ]
            recommended_commands = [
                'python tools/export_manual_review_control_plane_to_json.py --data-root datas --db-url "<your-db-url>"',
                'curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_status"',
            ]
    else:
        if any(source_json_counts.values()):
            preflight_status = "ready_for_backfill"
            recommended_next_steps = [
                "run_control_plane_backfill",
                "verify_backend_status",
                "verify_backup_status",
            ]
            recommended_commands = [
                'python tools/backfill_manual_review_control_plane_to_db.py --data-root datas --db-url "<your-db-url>"',
                'curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_status"',
            ]
        else:
            preflight_status = "ready_for_clean_start"
            recommended_next_steps = [
                "run_alembic_upgrade_head",
                "start_control_plane_runtime",
                "verify_backend_status",
            ]
            recommended_commands = [
                "alembic upgrade head",
                'curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_status"',
            ]

    return {
        "preflight_status": preflight_status,
        "repository_enabled": True,
        "repository_counts": repository_counts,
        "source_json_counts": source_json_counts,
        "backup_files_present": backup_files_present,
        "recommended_next_steps": recommended_next_steps,
        "recommended_commands": recommended_commands,
        "read_only": True,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill manual review receipt/job/audit JSON state into DB tables")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--db-url", type=str, default=None)
    parser.add_argument(
        "--mode",
        choices=("backfill", "export", "describe-storage", "describe-backup"),
        default="backfill",
        help="backfill JSON into DB, export repository state back to JSON, or describe current storage/backup mode",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.mode == "export":
        report = export_manual_review_control_plane_to_json(args.data_root, db_url=args.db_url)
    elif args.mode == "describe-backup":
        report = describe_manual_review_control_plane_backup(args.data_root, db_url=args.db_url)
    elif args.mode == "describe-storage":
        report = describe_manual_review_control_plane_storage(args.data_root, db_url=args.db_url)
    else:
        report = backfill_manual_review_control_plane_to_db(args.data_root, db_url=args.db_url)
    print(json.dumps(report, ensure_ascii=False, indent=2))
