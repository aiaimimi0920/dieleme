#!/usr/bin/env python3
"""Build canonical AVM dataset from raw JSON files under datas/."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from avm.canonical_mapper import map_raw_to_canonical
from src.storage.repository import create_repository_from_env


@dataclass
class FieldQuality:
    total: int = 0
    non_null: int = 0
    type_errors: int = 0


@dataclass
class QualityReport:
    records_total: int = 0
    file_error_count: int = 0
    failed_records: int = 0
    fields: Dict[str, FieldQuality] = field(default_factory=dict)

    def init_fields(self, names: Iterable[str]) -> None:
        for name in names:
            self.fields.setdefault(name, FieldQuality())


EXPECTED_TYPES = {
    "item_id": str,
    "source_url": str,
    "transaction_price": (int, float),
    "starting_price": (int, float),
    "area_sqm": (int, float),
    "auction_date": str,
}


SKIP_NAMES = {
    "all_locations.json",
    "collected_locations.json",
    "model_config.json",
    "manual_priority_locations.json",
    "seen_ids.json",
    "sniff_progress.json",
    "tuning_history.json",
}


def iter_raw_items(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item
    elif isinstance(data, dict):
        if "id" in data or "item_id" in data:
            yield data
        elif isinstance(data.get("items"), list):
            for item in data["items"]:
                if isinstance(item, dict):
                    yield item


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if "canonical" in parts:
        return True
    return path.name in SKIP_NAMES


def _database_row_stream(prefer_db: bool):
    if not prefer_db:
        return None, None
    repo = create_repository_from_env()
    if not repo.enabled:
        return None, None
    try:
        if hasattr(repo, "count_analysis_ready_items") and hasattr(repo, "yield_analysis_ready_flat_items"):
            if repo.count_analysis_ready_items() > 0:
                return repo.yield_analysis_ready_flat_items(), "analysis_ready"
        if repo.count_listings() <= 0:
            return None, None
        rows = repo.yield_flat_items()
    except Exception:
        return None, None
    return rows, "all_listings"


def _db_record_source(row: Dict[str, Any]) -> str:
    return (
        str(row.get("__file_path") or "").strip()
        or str(row.get("json_file") or "").strip()
        or str(row.get("list_payload_path") or "").strip()
        or str(row.get("detail_archive_path") or "").strip()
        or "db://property_listing"
    )


def update_quality(report: QualityReport, record: Dict[str, Any]) -> None:
    report.records_total += 1
    for field_name, expected in EXPECTED_TYPES.items():
        q = report.fields[field_name]
        q.total += 1
        value = record.get(field_name)
        if value is not None:
            q.non_null += 1
            if not isinstance(value, expected):
                q.type_errors += 1


def build_canonical_dataset(
    data_dir: str | Path = "datas",
    output_dir: str | Path = "datas/canonical",
    limit_files: int | None = None,
    datas_dir: Path | None = None,
    prefer_db: bool = True,
) -> Dict[str, Any]:
    datas_root = Path(datas_dir) if datas_dir is not None else Path(data_dir)
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    canonical_path = output_root / "canonical.jsonl"
    dataset_path = output_root / "dataset.jsonl"
    failed_path = output_root / "failed_records.jsonl"
    quality_path = output_root / "quality_report.json"

    files = sorted(p for p in datas_root.glob("**/*.json") if not should_skip(p))
    if limit_files is not None:
        files = files[:limit_files]

    quality = QualityReport()
    quality.init_fields(EXPECTED_TYPES.keys())
    processed_files = 0
    errored_files: list[dict[str, str]] = []
    source_mode = "files"
    source_scope = "files"
    db_rows, db_scope = _database_row_stream(prefer_db=prefer_db)

    with canonical_path.open("w", encoding="utf-8") as c_out, dataset_path.open("w", encoding="utf-8") as d_out, failed_path.open("w", encoding="utf-8") as f_out:
        if db_rows is not None:
            source_mode = "database"
            source_scope = db_scope or "database"
            for raw_item in db_rows:
                try:
                    canonical = map_raw_to_canonical(raw_item)
                    update_quality(quality, canonical)
                    line = json.dumps(canonical, ensure_ascii=False) + "\n"
                    c_out.write(line)
                    d_out.write(line)
                except Exception as exc:
                    quality.failed_records += 1
                    f_out.write(
                        json.dumps(
                            {
                                "file": _db_record_source(raw_item),
                                "record_id": raw_item.get("id") or raw_item.get("唯一id") or raw_item.get("item_id"),
                                "error": str(exc),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        else:
            for file_path in files:
                try:
                    for raw_item in iter_raw_items(file_path):
                        try:
                            canonical = map_raw_to_canonical(raw_item)
                            update_quality(quality, canonical)
                            line = json.dumps(canonical, ensure_ascii=False) + "\n"
                            c_out.write(line)
                            d_out.write(line)
                        except Exception as exc:
                            quality.failed_records += 1
                            f_out.write(
                                json.dumps(
                                    {
                                        "file": str(file_path),
                                        "record_id": raw_item.get("id") or raw_item.get("唯一id") or raw_item.get("item_id"),
                                        "error": str(exc),
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                    processed_files += 1
                except Exception as exc:
                    quality.file_error_count += 1
                    errored_files.append({"path": str(file_path), "error": str(exc)})
                    continue

    success_total = max(1, quality.records_total)
    report_json = {
        "source_mode": source_mode,
        "source_scope": source_scope,
        "processed_files": processed_files,
        "file_error_count": quality.file_error_count,
        "records_total": quality.records_total,
        "failed_records": quality.failed_records,
        "fields": {
            name: {
                "non_null_rate": round((f.non_null / f.total), 6) if f.total else 0.0,
                "type_error_count": f.type_errors,
                "non_null": f.non_null,
                "total": f.total,
            }
            for name, f in quality.fields.items()
        },
        "non_null_rate": {
            name: round((f.non_null / success_total), 4) for name, f in quality.fields.items()
        },
        "errored_files": errored_files[:50],
    }

    with quality_path.open("w", encoding="utf-8") as f:
        json.dump(report_json, f, ensure_ascii=False, indent=2)

    return {
        "source_mode": source_mode,
        "source_scope": source_scope,
        "canonical_path": str(canonical_path),
        "dataset_path": str(dataset_path),
        "failed_path": str(failed_path),
        "quality_path": str(quality_path),
        "processed_files": processed_files,
        "file_error_count": quality.file_error_count,
        "records_total": quality.records_total,
        "failed_records": quality.failed_records,
        "quality": report_json,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build AVM canonical dataset")
    parser.add_argument("--data-dir", default="datas", help="Input raw data directory")
    parser.add_argument("--output-dir", default="datas/canonical", help="Output canonical dir")
    parser.add_argument("--limit-files", type=int, default=None, help="Only process first N files")
    args = parser.parse_args()

    result = build_canonical_dataset(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        limit_files=args.limit_files,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
