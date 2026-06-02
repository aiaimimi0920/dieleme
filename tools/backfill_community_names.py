#!/usr/bin/env python3
"""Backfill community names using the same resolver as the live collection path."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.avm.collection_template import build_collection_record
from src.avm.community_resolver import (
    CommunityIndex,
    apply_community_resolution,
    load_default_community_index,
    resolve_community_name,
)
from src.storage.repository import create_repository_from_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回填小区标准名")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--index-path", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-path", type=Path, default=Path("datas/avm/community_backfill.json"))
    parser.add_argument("--prefer-db", action="store_true", default=False)
    return parser.parse_args()


def _load_file_rows(file_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _iter_source_files(data_root: Path) -> list[Path]:
    files: list[Path] = []
    archive_root = data_root / "archive"
    if archive_root.exists():
        files.extend(sorted(path for path in archive_root.rglob("*.json") if path.name not in {"model_config.json"}))
    files.extend(sorted(path for path in data_root.glob("*.json") if path.name not in {"all_locations.json", "collected_locations.json", "model_config.json", "mock_data.json"}))
    return files


def backfill_community_names(
    *,
    data_root: Path,
    index_path: Path | None = None,
    dry_run: bool = False,
    prefer_db: bool = False,
) -> dict[str, Any]:
    repo = create_repository_from_env() if prefer_db else None
    index = CommunityIndex.from_path(index_path) if index_path else load_default_community_index()

    candidate_count = 0
    updated_count = 0
    updated_records: list[dict[str, Any]] = []
    touched_files = 0

    for file_path in _iter_source_files(data_root):
        changed = False
        loaded_rows = _load_file_rows(file_path)
        changed_rows: list[dict[str, Any]] = []

        for row in loaded_rows:
            candidate_count += 1
            record = build_collection_record(row)
            payload = {**row, **record["location"]}
            resolution = resolve_community_name(payload, index)
            if not resolution:
                continue
            already_standardized = (
                row.get("community_name") == resolution.name
                and row.get("所属小区") == resolution.name
                and row.get("community_stable_key") == resolution.stable_key
            )
            if already_standardized:
                continue
            apply_community_resolution(row, resolution)
            changed = True
            changed_rows.append(row)
            updated_count += 1
            if len(updated_records) < 50:
                updated_records.append(
                    {
                        "file_path": str(file_path),
                        "item_id": row.get("item_id") or row.get("id"),
                        "source": resolution.source,
                        "stable_key": resolution.stable_key,
                    }
                )

        if changed and not dry_run:
            touched_files += 1
            file_path.write_text(json.dumps(loaded_rows, ensure_ascii=False, indent=2), encoding="utf-8")
            if repo and getattr(repo, "enabled", False) and changed_rows:
                repo.upsert_flat_items(
                    changed_rows,
                    event_type="community_backfill",
                    event_payload_factory=lambda record, _idx, file_path=file_path: {
                        "source_file": str(file_path),
                        "item_id": record["source"]["item_id"],
                    },
                )

    return {
        "candidate_count": candidate_count,
        "updated_count": updated_count,
        "touched_files": touched_files,
        "updated_records": updated_records,
        "dry_run": dry_run,
        "prefer_db": prefer_db,
        "index_path": str(index_path) if index_path else "",
    }


def main() -> None:
    args = parse_args()
    report = backfill_community_names(
        data_root=args.data_root,
        index_path=args.index_path,
        dry_run=args.dry_run,
        prefer_db=args.prefer_db,
    )
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
