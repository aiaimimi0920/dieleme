#!/usr/bin/env python3
"""Shared JSON persistence for manual review receipts."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.repository import PropertyRepository

from tools.backfill_manual_review_control_plane_to_db import (
    ensure_manual_review_control_plane_backfilled,
    sync_manual_review_control_plane_json_backup,
)


def _normalize_store_payload(payload: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return {"receipts": []}
    receipts = payload.get("receipts")
    if not isinstance(receipts, list):
        return {"receipts": []}
    return {"receipts": [dict(item) for item in receipts if isinstance(item, dict)]}


def _write_store(path: Path, payload: dict[str, list[dict[str, Any]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def list_manual_review_receipts(
    path: str | Path,
    repository: "PropertyRepository | None" = None,
) -> dict[str, list[dict[str, Any]]]:
    if repository is not None and getattr(repository, "enabled", False):
        ensure_manual_review_control_plane_backfilled(Path(path).parent.parent, repository=repository)
        return dict(repository.list_manual_review_receipts())
    store_path = Path(path)
    try:
        raw = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"receipts": []}
    return _normalize_store_payload(raw)


def upsert_manual_review_receipt(
    path: str | Path,
    receipt: dict[str, Any],
    repository: "PropertyRepository | None" = None,
) -> dict[str, Any]:
    if repository is not None and getattr(repository, "enabled", False):
        data_root = Path(path).parent.parent
        ensure_manual_review_control_plane_backfilled(data_root, repository=repository)
        result = dict(repository.upsert_manual_review_receipt(receipt))
        sync_manual_review_control_plane_json_backup(data_root, repository=repository)
        return result
    store_path = Path(path)
    payload = list_manual_review_receipts(store_path)
    receipts = list(payload.get("receipts") or [])
    action = str(receipt.get("action") or "").strip()
    ready_signal = str(receipt.get("ready_signal") or "").strip()
    updated_receipt = dict(receipt)
    updated_receipt["action"] = action
    updated_receipt["ready_signal"] = ready_signal
    updated_receipt["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    operation = "created"
    for index, existing in enumerate(receipts):
        if str(existing.get("action") or "").strip() == action and str(existing.get("ready_signal") or "").strip() == ready_signal:
            receipts[index] = updated_receipt
            operation = "updated"
            break
    else:
        receipts.append(updated_receipt)

    receipts.sort(key=lambda item: (str(item.get("action") or ""), str(item.get("ready_signal") or "")))
    normalized = {"receipts": receipts}
    _write_store(store_path, normalized)
    return {
        "operation": operation,
        "receipt": updated_receipt,
        "receipt_count": len(receipts),
    }


def delete_manual_review_receipt(
    path: str | Path,
    *,
    action: str,
    ready_signal: str,
    repository: "PropertyRepository | None" = None,
) -> dict[str, Any]:
    if repository is not None and getattr(repository, "enabled", False):
        data_root = Path(path).parent.parent
        ensure_manual_review_control_plane_backfilled(data_root, repository=repository)
        result = dict(repository.delete_manual_review_receipt(action, ready_signal))
        sync_manual_review_control_plane_json_backup(data_root, repository=repository)
        return result
    store_path = Path(path)
    payload = list_manual_review_receipts(store_path)
    receipts = list(payload.get("receipts") or [])
    action_key = str(action or "").strip()
    ready_signal_key = str(ready_signal or "").strip()
    kept: list[dict[str, Any]] = []
    deleted = False
    for item in receipts:
        if str(item.get("action") or "").strip() == action_key and str(item.get("ready_signal") or "").strip() == ready_signal_key:
            deleted = True
            continue
        kept.append(item)
    normalized = {"receipts": kept}
    _write_store(store_path, normalized)
    return {
        "deleted": deleted,
        "receipt_count": len(kept),
    }
