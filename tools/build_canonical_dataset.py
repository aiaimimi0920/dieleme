import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.avm.canonical_mapper import map_raw_to_canonical


SKIP_FILES = {
    "all_locations.json",
    "sniff_progress.json",
    "collected_locations.json",
    "model_config.json",
    "tuning_history.json",
    "seen_ids.json",
}


def iter_input_files(data_dir: str):
    root_files = glob.glob(os.path.join(data_dir, "*.json"))
    archive_files = glob.glob(os.path.join(data_dir, "archive", "**", "*.json"), recursive=True)
    for path in root_files + archive_files:
        if os.path.basename(path) in SKIP_FILES:
            continue
        yield path


def quality_template() -> Dict[str, Any]:
    return {
        "total_records": 0,
        "success_records": 0,
        "failed_records": 0,
        "non_null": {
            "item_id": 0,
            "transaction_price": 0,
            "starting_price": 0,
            "area_sqm": 0,
            "auction_date": 0,
            "community_name": 0,
            "city": 0,
            "district": 0,
            "latitude": 0,
            "longitude": 0,
        },
    }


def build_canonical_dataset(data_dir: str = "datas", output_dir: str = "datas/canonical") -> Dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    canonical_path = os.path.join(output_dir, "canonical.jsonl")
    failed_path = os.path.join(output_dir, "failed_records.jsonl")
    quality_path = os.path.join(output_dir, "quality_report.json")

    quality = quality_template()

    with open(canonical_path, "w", encoding="utf-8") as c_out, open(failed_path, "w", encoding="utf-8") as f_out:
        for path in iter_input_files(data_dir):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception as exc:
                f_out.write(json.dumps({"file": path, "error": f"load_error: {exc}"}, ensure_ascii=False) + "\n")
                continue

            if not isinstance(payload, list):
                continue

            for record in payload:
                quality["total_records"] += 1
                try:
                    mapped = map_raw_to_canonical(record)
                    c_out.write(json.dumps(mapped, ensure_ascii=False) + "\n")
                    quality["success_records"] += 1

                    for key in quality["non_null"]:
                        if mapped.get(key) not in (None, ""):
                            quality["non_null"][key] += 1
                except Exception as exc:
                    quality["failed_records"] += 1
                    f_out.write(
                        json.dumps(
                            {
                                "file": path,
                                "record_id": record.get("id") or record.get("唯一id") or record.get("item_id"),
                                "error": str(exc),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

    total = max(1, quality["success_records"])
    quality["non_null_rate"] = {k: round(v / total, 4) for k, v in quality["non_null"].items()}

    with open(quality_path, "w", encoding="utf-8") as q_out:
        json.dump(quality, q_out, ensure_ascii=False, indent=2)

    return {
        "canonical_path": canonical_path,
        "failed_path": failed_path,
        "quality_path": quality_path,
        "quality": quality,
    }


def main():
    parser = argparse.ArgumentParser(description="Build AVM canonical dataset from raw datas/*.json files")
    parser.add_argument("--data-dir", default="datas", help="Input raw data directory")
    parser.add_argument("--output-dir", default="datas/canonical", help="Output directory")
    args = parser.parse_args()

    result = build_canonical_dataset(data_dir=args.data_dir, output_dir=args.output_dir)
    print(f"Canonical dataset written: {result['canonical_path']}")
    print(f"Failed records log: {result['failed_path']}")
    print(f"Quality report: {result['quality_path']}")


if __name__ == "__main__":
    main()
