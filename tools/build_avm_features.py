#!/usr/bin/env python3
"""Build AVM training features from canonical data + risk labels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.avm.feature_builder import build_feature_samples, build_feature_stats


def _load_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Input not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    if suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "records" in data and isinstance(data["records"], list):
                return data["records"]
            return list(data.values())
        raise ValueError(f"Unsupported JSON structure in {path}")
    if suffix == ".parquet":
        return pd.read_parquet(path).to_dict(orient="records")

    raise ValueError(f"Unsupported input format: {path}")


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build AVM features and feature stats")
    parser.add_argument("--canonical", default="datas/avm/canonical.jsonl", help="canonical source path (.json/.jsonl/.parquet)")
    parser.add_argument("--risk", default="datas/avm/risk_labels.jsonl", help="risk labels path (.json/.jsonl/.parquet)")
    parser.add_argument("--output", default="datas/avm/features.parquet", help="output features path")
    parser.add_argument("--stats", default="datas/avm/feature_stats.json", help="output stats path")
    parser.add_argument("--format", choices=["auto", "parquet", "jsonl"], default="auto", help="feature output format")
    args = parser.parse_args()

    canonical_path = Path(args.canonical)
    risk_path = Path(args.risk)
    output_path = Path(args.output)
    stats_path = Path(args.stats)

    canonical_records = _load_records(canonical_path)
    risk_records: List[Dict[str, Any]] = _load_records(risk_path) if risk_path.exists() else []

    samples, metadata = build_feature_samples(canonical_records, risk_records)
    stats = build_feature_stats(samples, metadata)

    fmt = args.format
    if fmt == "auto":
        fmt = "parquet" if output_path.suffix.lower() == ".parquet" else "jsonl"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    written_output = output_path
    if fmt == "parquet":
        try:
            pd.DataFrame(samples).to_parquet(output_path, index=False)
        except Exception:
            written_output = output_path.with_suffix(".jsonl")
            _write_jsonl(written_output, samples)
    else:
        if output_path.suffix.lower() != ".jsonl":
            output_path = output_path.with_suffix(".jsonl")
        written_output = output_path
        _write_jsonl(written_output, samples)

    stats_path.parent.mkdir(parents=True, exist_ok=True)
    with stats_path.open("w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"features: {written_output}")
    print(f"stats: {stats_path}")
    print(f"samples: {len(samples)}")
    print(f"duplicate_dropped: {metadata.get('duplicate_dropped', 0)}")


if __name__ == "__main__":
    main()
