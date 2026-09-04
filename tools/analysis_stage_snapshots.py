from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.manual_review_receipt_store import list_manual_review_receipts


def load_recent_gap_audit_snapshot(report_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(report_path) if report_path is not None else Path("datas/avm/recent_gap_audit.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload or {})


def load_manual_review_receipt_snapshot(
    report_path: str | Path | None = None,
    repository: Any | None = None,
) -> dict[str, Any]:
    path = Path(report_path) if report_path is not None else Path("datas/avm/manual_review_receipts.json")
    return dict(list_manual_review_receipts(path, repository=repository))


def load_action_effectiveness_snapshot(report_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(report_path) if report_path is not None else Path("datas/avm/data_supply_optimization_loop.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    total_progress = payload.get("total_progress") or {}
    snapshot = total_progress.get("action_effectiveness")
    return dict(snapshot or {})


def load_optimization_loop_progress_snapshot(report_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(report_path) if report_path is not None else Path("datas/avm/data_supply_optimization_loop.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    total_progress = payload.get("total_progress") or {}
    return dict(total_progress or {})


__all__ = ['load_recent_gap_audit_snapshot', 'load_manual_review_receipt_snapshot', 'load_action_effectiveness_snapshot', 'load_optimization_loop_progress_snapshot']
