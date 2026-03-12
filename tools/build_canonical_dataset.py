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

from avm.canonical_mapper import map_raw_to_canonical


@dataclass
class FieldQuality:
    total: int = 0
    non_null: int = 0
    type_errors: int = 0


@dataclass
class QualityReport:
    records_total: int = 0
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


def should_skip(path: Path) -> bool:
    skip_names = {
        "all_locations.json",
        "collected_locations.json",
        "model_config.json",
        "manual_priority_locations.json",
        "seen_ids.json",
        "sniff_progress.json",
        "tuning_history.json",
    }
    parts = set(path.parts)
    if "canonical" in parts:
        return True
    return path.name in skip_names


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


def build_canonical_dataset(limit_files: int | None = None) -> Dict[str, Any]:
    datas_dir = REPO_ROOT / "datas"
    output_dir = datas_dir / "canonical"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_jsonl = output_dir / "dataset.jsonl"
    quality_path = output_dir / "quality_report.json"

    files = sorted(p for p in datas_dir.glob("**/*.json") if not should_skip(p))
    if limit_files is not None:
        files = files[:limit_files]

    quality = QualityReport()
    quality.init_fields(EXPECTED_TYPES.keys())

    processed_files = 0
    with output_jsonl.open("w", encoding="utf-8") as out:
        for file_path in files:
            try:
                for raw_item in iter_raw_items(file_path):
                    canonical = map_raw_to_canonical(raw_item)
                    update_quality(quality, canonical)
                    out.write(json.dumps(canonical, ensure_ascii=False) + "\n")
                processed_files += 1
            except Exception:
                # Keep offline batch resilient to corrupted files.
                continue

    report_json = {
        "processed_files": processed_files,
        "records_total": quality.records_total,
        "fields": {
            name: {
                "non_null_rate": round((f.non_null / f.total), 6) if f.total else 0.0,
                "type_error_count": f.type_errors,
                "non_null": f.non_null,
                "total": f.total,
            }
            for name, f in quality.fields.items()
        },
    }

    with quality_path.open("w", encoding="utf-8") as f:
        json.dump(report_json, f, ensure_ascii=False, indent=2)

    return {
        "output_jsonl": str(output_jsonl),
        "quality_report": str(quality_path),
        "processed_files": processed_files,
        "records_total": quality.records_total,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build AVM canonical dataset")
    parser.add_argument("--limit-files", type=int, default=None, help="Only process first N files")
    args = parser.parse_args()

    result = build_canonical_dataset(limit_files=args.limit_files)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
