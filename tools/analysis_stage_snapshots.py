from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.manual_review_receipt_store import list_manual_review_receipts


def load_recent_gap_audit_snapshot(report_path: str | Path | None = None) -> dict[str, Any]:
    from src.runtime_snapshot_cache import snapshots

    path = Path(report_path) if report_path is not None else Path("datas/avm/recent_gap_audit.json")
    payload = snapshots.read(path)
    return dict(payload or {})


def load_manual_review_receipt_snapshot(
    report_path: str | Path | None = None,
    repository: Any | None = None,
) -> dict[str, Any]:
    path = Path(report_path) if report_path is not None else Path("datas/avm/manual_review_receipts.json")
    return dict(list_manual_review_receipts(path, repository=repository, cached=True))


def load_action_effectiveness_snapshot(report_path: str | Path | None = None) -> dict[str, Any]:
    from src.runtime_snapshot_cache import snapshots

    path = Path(report_path) if report_path is not None else Path("datas/avm/data_supply_optimization_loop.json")
    payload = snapshots.read(path)
    total_progress = payload.get("total_progress") or {}
    snapshot = total_progress.get("action_effectiveness")
    return dict(snapshot or {})


def load_optimization_loop_progress_snapshot(report_path: str | Path | None = None) -> dict[str, Any]:
    from src.runtime_snapshot_cache import snapshots

    path = Path(report_path) if report_path is not None else Path("datas/avm/data_supply_optimization_loop.json")
    payload = snapshots.read(path)
    total_progress = payload.get("total_progress") or {}
    return dict(total_progress or {})


__all__ = ['load_recent_gap_audit_snapshot', 'load_manual_review_receipt_snapshot', 'load_action_effectiveness_snapshot', 'load_optimization_loop_progress_snapshot']
