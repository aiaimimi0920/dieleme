#!/usr/bin/env python3
"""Recompute recent analysis-stage state for receipt-driven recovery paths."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.avm.collection_template import build_collection_record
from src.collection.stage_state import derive_stage_state
from src.storage.repository import PropertyRepository, create_repository_from_env


ReconcileMode = Literal["analysis_ready_recheck", "stage_state_reconcile"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recompute recent analysis-stage state from DB-first recent rows")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--mode", choices=["analysis_ready_recheck", "stage_state_reconcile"], required=True)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _stage_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "seed_status": row.get("seed_status"),
        "detail_status": row.get("detail_status"),
        "analysis_status": row.get("analysis_status"),
        "analysis_ready": row.get("analysis_ready"),
        "analysis_missing_fields": list(row.get("analysis_missing_fields") or []),
        "analysis_last_scored_at": row.get("analysis_last_scored_at"),
        "analysis_model_version": row.get("analysis_model_version"),
        "detail_last_error": row.get("detail_last_error"),
        "detail_retry_count": row.get("detail_retry_count"),
        "detail_lease_until": row.get("detail_lease_until"),
    }


def _transition_types(repo: PropertyRepository, before_state: dict[str, Any], after_state: dict[str, Any]) -> list[str]:
    return [event_type for event_type, _payload in repo._changed_stage_events(before_state, after_state)]


def run_analysis_stage_reconcile(
    *,
    data_root: Path,
    window_days: int,
    mode: ReconcileMode,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    repo = create_repository_from_env()
    if not repo.enabled:
        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": mode,
            "window_days": window_days,
            "dry_run": dry_run,
            "candidate_count": 0,
            "scanned_count": 0,
            "updated_count": 0,
            "analysis_stage_transition_count": 0,
            "analysis_ready_transition_count": 0,
            "detail_stage_transition_count": 0,
            "samples": [],
            "skipped": True,
            "skip_reason": "repository_unavailable",
        }

    rows = repo.iter_recent_flat_items(window_days, limit=limit)
    candidate_count = len(rows)
    scanned_count = 0
    updated_count = 0
    analysis_stage_transition_count = 0
    analysis_ready_transition_count = 0
    detail_stage_transition_count = 0
    samples: list[dict[str, Any]] = []

    for row in rows:
        scanned_count += 1
        before_state = _stage_snapshot(row)
        record = build_collection_record(row)
        after_state = derive_stage_state(
            record,
            row,
            event_type=mode,
            existing=before_state,
            now=datetime.now(),
        )
        transition_types = _transition_types(repo, before_state, after_state)
        if not transition_types:
            continue
        if len(samples) < 5:
            samples.append(
                {
                    "item_id": row.get("item_id") or row.get("id"),
                    "analysis_status_before": before_state.get("analysis_status"),
                    "analysis_status_after": after_state.get("analysis_status"),
                    "analysis_ready_before": before_state.get("analysis_ready"),
                    "analysis_ready_after": after_state.get("analysis_ready"),
                    "analysis_missing_fields_before": list(before_state.get("analysis_missing_fields") or []),
                    "analysis_missing_fields_after": list(after_state.get("analysis_missing_fields") or []),
                    "triggered_transition_types": transition_types,
                }
            )
        if dry_run:
            continue
        repo.upsert_flat_item(
            row,
            event_type=mode,
            event_payload={"mode": mode, "triggered_transition_types": transition_types},
        )
        updated_count += 1
        if "analysis_stage_transition" in transition_types:
            analysis_stage_transition_count += 1
        if "analysis_ready_transition" in transition_types:
            analysis_ready_transition_count += 1
        if "detail_stage_transition" in transition_types:
            detail_stage_transition_count += 1

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "window_days": window_days,
        "dry_run": dry_run,
        "candidate_count": candidate_count,
        "scanned_count": scanned_count,
        "updated_count": updated_count,
        "analysis_stage_transition_count": analysis_stage_transition_count,
        "analysis_ready_transition_count": analysis_ready_transition_count,
        "detail_stage_transition_count": detail_stage_transition_count,
        "samples": samples,
        "skipped": False,
    }


def main() -> None:
    args = parse_args()
    report = run_analysis_stage_reconcile(
        data_root=args.data_root,
        window_days=args.window_days,
        mode=args.mode,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
