from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.avm.collection_template import build_collection_record, get_collection_template
from src.storage.repository import DatabaseSettings, PropertyRepository


SKIP_NAMES = {
    "all_locations.json",
    "collected_locations.json",
    "mock_data.json",
    "model_config.json",
    "manual_priority_locations.json",
    "seen_ids.json",
    "sniff_progress.json",
    "tuning_history.json",
}
DATED_ROOT_JSON_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


@dataclass
class SourceRow:
    path: Path
    row_index: int
    item: Dict[str, Any]


def load_contract_meta() -> Dict[str, Any]:
    payload = get_collection_template()
    return {
        "version": payload["version"],
        "sections": list(payload["final_template"].keys()),
        "final_template": payload["final_template"],
    }


def should_skip_root_file(path: Path) -> bool:
    if path.name in SKIP_NAMES:
        return True
    return not bool(DATED_ROOT_JSON_RE.match(path.name))


def iter_source_files(data_root: Path, include_root: bool = True) -> List[Path]:
    archive_root = data_root / "archive"
    archive_files = sorted(
        path for path in archive_root.rglob("*.json")
        if path.name not in SKIP_NAMES
    ) if archive_root.exists() else []

    root_files: List[Path] = []
    if include_root:
        root_files = sorted(
            path for path in data_root.glob("*.json")
            if not should_skip_root_file(path)
        )
    return archive_files + root_files


def _source_date_from_path(path: Path) -> str:
    if path.stem and re.match(r"^\d{4}-\d{2}-\d{2}$", path.stem):
        return path.stem
    return ""


def build_db_row(
    source_row: SourceRow,
    contract_version: str,
    expected_sections: Iterable[str],
) -> Dict[str, Any]:
    item = source_row.item
    item_id = item.get("item_id") or item.get("id") or item.get("唯一id") or item.get("source_item_id")
    if item_id in (None, ""):
        raise ValueError("missing item id")

    record = build_collection_record(item)
    sections = set(record.keys())
    expected = set(expected_sections)
    if sections != expected:
        raise ValueError(f"collection record sections mismatch: {sorted(sections)} vs {sorted(expected)}")

    risk = record["risk_flags"]
    location = record["location"]
    property_section = record["property"]
    source = record["source"]

    return {
        "item_id": str(item_id),
        "contract_version": contract_version,
        "source_date": _source_date_from_path(source_row.path),
        "source_file": source_row.path.as_posix(),
        "row_index": source_row.row_index,
        "community_name": location.get("community_name"),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "detail_archive_path": source.get("detail_archive_path"),
        "is_occupied": risk.get("is_occupied"),
        "collection_record_json": json.dumps(record, ensure_ascii=False),
        "housing_type": property_section.get("housing_type"),
    }


def _repo_from_url(db_url: str) -> PropertyRepository:
    repo = PropertyRepository(
        DatabaseSettings(
            url=db_url,
            enabled=bool(db_url),
            auto_create=True,
            enable_postgis=True,
        )
    )
    repo.initialize()
    return repo


def _load_json_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def backfill_json_to_db(
    data_root: Path,
    contract_version: str,
    expected_sections: Iterable[str],
    *,
    db_url: str | None = None,
    include_root: bool = True,
    dry_run: bool = False,
    limit_files: int = 0,
    limit_records: int = 0,
    report_path: Path | None = None,
    progress_every_files: int = 50,
) -> Dict[str, Any]:
    repo = None if dry_run else _repo_from_url(db_url or "")
    started_at = time.time()

    processed_file_count = 0
    row_seen_count = 0
    candidate_row_count = 0
    row_error_count = 0
    db_write_row_count = 0
    file_error_count = 0
    failed_files: List[Dict[str, Any]] = []
    row_errors: List[Dict[str, Any]] = []
    sample_item_ids: List[str] = []

    files = iter_source_files(data_root, include_root=include_root)
    for file_index, file_path in enumerate(files, start=1):
        if limit_files and processed_file_count >= limit_files:
            break
        try:
            payload = _load_json_payload(file_path)
        except Exception as exc:
            file_error_count += 1
            failed_files.append({"path": file_path.as_posix(), "error": str(exc)})
            continue

        rows = payload if isinstance(payload, list) else [payload]
        valid_items: List[Dict[str, Any]] = []
        valid_ids: List[str] = []

        for row_index, row in enumerate(rows):
            row_seen_count += 1
            if limit_records and row_seen_count > limit_records:
                break
            if not isinstance(row, dict):
                row_error_count += 1
                row_errors.append(
                    {"path": file_path.as_posix(), "row_index": row_index, "error": "row is not a dict"}
                )
                continue
            try:
                db_row = build_db_row(
                    SourceRow(path=file_path, row_index=row_index, item=row),
                    contract_version=contract_version,
                    expected_sections=expected_sections,
                )
            except Exception as exc:
                row_error_count += 1
                row_errors.append({"path": file_path.as_posix(), "row_index": row_index, "error": str(exc)})
                continue

            candidate_row_count += 1
            valid_items.append(row)
            valid_ids.append(db_row["item_id"])
            if len(sample_item_ids) < 10:
                sample_item_ids.append(db_row["item_id"])

        if valid_items and repo is not None:
            try:
                written = repo.upsert_flat_items(
                    valid_items,
                    event_type="json_backfill",
                    event_payload_factory=lambda _record, idx, file_path=file_path: {
                        "source_file": file_path.as_posix(),
                        "row_index": idx,
                    },
                )
                db_write_row_count += written
            except Exception as batch_exc:
                # Fall back to row-level writes so one bad row does not abort the entire backfill.
                for row_index, row in enumerate(valid_items):
                    try:
                        repo.upsert_flat_item(
                            row,
                            event_type="json_backfill",
                            event_payload={"source_file": file_path.as_posix(), "row_index": row_index},
                        )
                        db_write_row_count += 1
                    except Exception as row_exc:
                        row_error_count += 1
                        row_errors.append(
                            {
                                "path": file_path.as_posix(),
                                "row_index": row_index,
                                "error": f"{type(batch_exc).__name__}: {batch_exc}; fallback={type(row_exc).__name__}: {row_exc}",
                            }
                        )

        processed_file_count += 1
        if progress_every_files and processed_file_count % progress_every_files == 0:
            elapsed = time.time() - started_at
            print(
                json.dumps(
                    {
                        "progress_files": processed_file_count,
                        "row_seen_count": row_seen_count,
                        "candidate_row_count": candidate_row_count,
                        "db_write_row_count": db_write_row_count,
                        "row_error_count": row_error_count,
                        "elapsed_sec": round(elapsed, 2),
                    },
                    ensure_ascii=False,
                )
            )

        if limit_records and row_seen_count >= limit_records:
            break

    result = {
        "processed_file_count": processed_file_count,
        "row_seen_count": row_seen_count,
        "candidate_row_count": candidate_row_count,
        "row_error_count": row_error_count,
        "db_write_row_count": db_write_row_count,
        "file_error_count": file_error_count,
        "sample_item_ids": sample_item_ids,
        "row_errors": row_errors[:50],
        "failed_files": failed_files[:50],
        "elapsed_sec": round(time.time() - started_at, 2),
        "dry_run": dry_run,
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill JSON archive into PostgreSQL dual-write schema")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--db-url", default="")
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--limit-records", type=int, default=0)
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--include-root", action="store_true", default=False)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--progress-every-files", type=int, default=50)
    args = parser.parse_args()

    contract_meta = load_contract_meta()
    result = backfill_json_to_db(
        data_root=args.data_root,
        contract_version=contract_meta["version"],
        expected_sections=contract_meta["sections"],
        db_url=args.db_url,
        include_root=args.include_root,
        dry_run=args.dry_run,
        limit_files=args.limit_files,
        limit_records=args.limit_records,
        report_path=args.report_path,
        progress_every_files=args.progress_every_files,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
