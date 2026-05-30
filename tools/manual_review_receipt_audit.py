#!/usr/bin/env python3
"""Append-only audit log helpers for manual review receipt mutations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
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


def _payload_fingerprint(payload: Any) -> str:
    normalized = json.dumps(payload if payload is not None else {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def append_manual_review_receipt_operation(
    path: str | Path,
    *,
    operation: str,
    receipt: dict[str, Any] | None,
    execution_mode: str,
    maintenance_job_id: str | None = None,
    deleted: bool | None = None,
    repository: "PropertyRepository | None" = None,
) -> dict[str, Any]:
    if repository is not None and getattr(repository, "enabled", False):
        data_root = Path(path).parent.parent
        ensure_manual_review_control_plane_backfilled(data_root, repository=repository)
        event = dict(
            repository.append_manual_review_receipt_operation(
                operation=operation,
                receipt=receipt,
                execution_mode=execution_mode,
                maintenance_job_id=maintenance_job_id,
                deleted=deleted,
            )
        )
        sync_manual_review_control_plane_json_backup(data_root, repository=repository)
        return event
    store_path = Path(path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = dict(receipt or {})
    payload = receipt.get("payload")
    event: dict[str, Any] = {
        "operation_id": str(uuid4()),
        "operation": str(operation or "").strip(),
        "action": str(receipt.get("action") or "").strip(),
        "ready_signal": str(receipt.get("ready_signal") or "").strip(),
        "status": str(receipt.get("status") or "").strip(),
        "payload_fingerprint": _payload_fingerprint(payload),
        "source": str(receipt.get("source") or "").strip() or None,
        "execution_mode": str(execution_mode or "").strip() or "sync",
        "requested_at": _now_text(),
    }
    if maintenance_job_id:
        event["maintenance_job_id"] = maintenance_job_id
    if deleted is not None:
        event["deleted"] = bool(deleted)
    if isinstance(receipt.get("resolution_notes"), str) and receipt["resolution_notes"].strip():
        event["resolution_notes"] = receipt["resolution_notes"].strip()

    with store_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def load_manual_review_receipt_operations(
    path: str | Path,
    *,
    action: str | None = None,
    ready_signal: str | None = None,
    limit: int | None = None,
    repository: "PropertyRepository | None" = None,
) -> list[dict[str, Any]]:
    if repository is not None and getattr(repository, "enabled", False):
        ensure_manual_review_control_plane_backfilled(Path(path).parent.parent, repository=repository)
        return list(
            repository.list_manual_review_receipt_operations(
                action=action,
                ready_signal=ready_signal,
                limit=limit,
            )
        )
    store_path = Path(path)
    try:
        lines = store_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    items: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            items.append(payload)
    return filter_manual_review_receipt_operations(
        items,
        action=action,
        ready_signal=ready_signal,
        limit=limit,
    )


def filter_manual_review_receipt_operations(
    operations: list[dict[str, Any]] | None,
    *,
    action: str | None = None,
    ready_signal: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    action_key = str(action or "").strip()
    ready_signal_key = str(ready_signal or "").strip()
    filtered: list[dict[str, Any]] = []
    for item in operations or []:
        if not isinstance(item, dict):
            continue
        if action_key and str(item.get("action") or "").strip() != action_key:
            continue
        if ready_signal_key and str(item.get("ready_signal") or "").strip() != ready_signal_key:
            continue
        filtered.append(dict(item))
    if limit is not None and limit >= 0:
        filtered = [] if limit == 0 else filtered[-limit:]
    return filtered


def summarize_manual_review_receipt_operations_snapshot(operations: list[dict[str, Any]] | None) -> dict[str, Any]:
    normalized = [dict(item) for item in operations or [] if isinstance(item, dict)]
    last_operation = normalized[-1] if normalized else None
    last_async = next((item for item in reversed(normalized) if str(item.get("execution_mode") or "") == "async"), None)
    last_delete = next((item for item in reversed(normalized) if str(item.get("operation") or "") == "deleted"), None)
    last_update = next((item for item in reversed(normalized) if str(item.get("operation") or "") == "updated"), None)
    return {
        "operation_count": len(normalized),
        "last_operation_type": last_operation.get("operation") if last_operation else None,
        "last_operation_at": last_operation.get("requested_at") if last_operation else None,
        "last_operation_receipt_key": {
            "action": last_operation.get("action"),
            "ready_signal": last_operation.get("ready_signal"),
        } if last_operation else None,
        "last_async_operation_at": last_async.get("requested_at") if last_async else None,
        "last_async_operation_receipt_key": {
            "action": last_async.get("action"),
            "ready_signal": last_async.get("ready_signal"),
        } if last_async else None,
        "last_delete_at": last_delete.get("requested_at") if last_delete else None,
        "last_delete_receipt_key": {
            "action": last_delete.get("action"),
            "ready_signal": last_delete.get("ready_signal"),
        } if last_delete else None,
        "last_update_at": last_update.get("requested_at") if last_update else None,
        "last_update_receipt_key": {
            "action": last_update.get("action"),
            "ready_signal": last_update.get("ready_signal"),
        } if last_update else None,
    }
