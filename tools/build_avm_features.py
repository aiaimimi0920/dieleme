import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.avm.feature_builder import build_features


def _stats_template() -> Dict[str, Any]:
    return {
        "total_records": 0,
        "non_null": {
            "auction_month_index": 0,
            "area_sqm": 0,
            "starting_price": 0,
            "transaction_price": 0,
            "unit_price": 0,
            "latitude": 0,
            "longitude": 0,
        },
    }


def build_avm_features(canonical_path: str = "datas/canonical/canonical.jsonl", output_path: str = "datas/avm/features.jsonl", stats_path: str = "datas/avm/feature_stats.json") -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    os.makedirs(os.path.dirname(stats_path), exist_ok=True)

    if not os.path.exists(canonical_path):
        raise FileNotFoundError(f"Canonical file not found: {canonical_path}")

    stats = _stats_template()
    with open(canonical_path, "r", encoding="utf-8") as fin, open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            feat = build_features(row)
            fout.write(json.dumps(feat, ensure_ascii=False) + "\n")
            stats["total_records"] += 1
            for key in stats["non_null"]:
                if feat.get(key) not in (None, ""):
                    stats["non_null"][key] += 1

    total = max(1, stats["total_records"])
    stats["non_null_rate"] = {k: round(v / total, 4) for k, v in stats["non_null"].items()}

    with open(stats_path, "w", encoding="utf-8") as fstats:
        json.dump(stats, fstats, ensure_ascii=False, indent=2)

    return {
        "features_path": output_path,
        "stats_path": stats_path,
        "stats": stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build AVM feature dataset from canonical jsonl")
    parser.add_argument("--canonical", default="datas/canonical/canonical.jsonl", help="Input canonical jsonl path")
    parser.add_argument("--output", default="datas/avm/features.jsonl", help="Output feature jsonl path")
    parser.add_argument("--stats", default="datas/avm/feature_stats.json", help="Output stats path")
    args = parser.parse_args()

    result = build_avm_features(canonical_path=args.canonical, output_path=args.output, stats_path=args.stats)
    print(f"Feature dataset written: {result['features_path']}")
    print(f"Feature stats written: {result['stats_path']}")


if __name__ == "__main__":
    main()
