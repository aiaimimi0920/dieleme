#!/usr/bin/env python3
"""Run AVM offline pipeline: canonical -> risk -> feature -> predict -> alert.

The pipeline is deterministic, repeatable, and idempotent:
- each stage output is a full snapshot JSONL
- files are only rewritten when content changes
- running multiple times with same input yields identical outputs
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple

JsonDict = Dict[str, Any]


def _read_jsonl(path: Path) -> List[JsonDict]:
    if not path.exists():
        return []
    rows: List[JsonDict] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_no}: {exc}") from exc
    return rows


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_if_changed(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是", "有"}
    return False


def stage_canonical(rows: List[JsonDict], _: Path) -> Tuple[List[JsonDict], JsonDict]:
    canonical_rows: List[JsonDict] = []
    missing_item_id = 0
    with_geo = 0
    with_price = 0

    for row in rows:
        item_id = row.get("item_id") or row.get("source_item_id") or row.get("id")
        if not item_id:
            missing_item_id += 1
            item_id = f"missing-{len(canonical_rows)+1}"

        latitude = _to_float(row.get("latitude") or row.get("lat"))
        longitude = _to_float(row.get("longitude") or row.get("lng") or row.get("lon"))
        transaction_price = _to_float(row.get("transaction_price") or row.get("成交价格"))
        starting_price = _to_float(row.get("starting_price") or row.get("起拍价格"))
        area_sqm = _to_float(row.get("area_sqm") or row.get("建筑面积"))

        if latitude is not None and longitude is not None:
            with_geo += 1
        if transaction_price is not None:
            with_price += 1

        canonical_rows.append(
            {
                **row,
                "item_id": str(item_id),
                "source_item_id": str(row.get("source_item_id") or row.get("id") or item_id),
                "latitude": latitude,
                "longitude": longitude,
                "transaction_price": transaction_price,
                "starting_price": starting_price,
                "area_sqm": area_sqm,
            }
        )

    summary = {
        "records": len(canonical_rows),
        "missing_item_id_filled": missing_item_id,
        "with_geo": with_geo,
        "with_transaction_price": with_price,
    }
    return canonical_rows, summary


def stage_risk(rows: List[JsonDict], _: Path) -> Tuple[List[JsonDict], JsonDict]:
    risk_rows: List[JsonDict] = []
    high_risk = 0

    keys = [
        "is_occupied",
        "has_long_lease",
        "is_haunted",
        "is_fractional_share",
        "tax_is_company_owned",
        "clear_delivery",
    ]

    for row in rows:
        risk_flags = {
            "is_occupied": _normalize_bool(row.get("is_occupied")),
            "has_long_lease": _normalize_bool(row.get("has_long_lease")),
            "is_haunted": _normalize_bool(row.get("is_haunted")),
            "is_fractional_share": _normalize_bool(row.get("is_fractional_share")),
            "tax_is_company_owned": _normalize_bool(row.get("tax_is_company_owned")),
            "clear_delivery": _normalize_bool(row.get("clear_delivery")),
        }

        score = (
            25 * int(risk_flags["is_occupied"])
            + 25 * int(risk_flags["has_long_lease"])
            + 30 * int(risk_flags["is_haunted"])
            + 35 * int(risk_flags["is_fractional_share"])
            + 15 * int(risk_flags["tax_is_company_owned"])
            + 20 * int(not risk_flags["clear_delivery"])
        )
        level = "high" if score >= 40 else "medium" if score >= 20 else "low"
        if level == "high":
            high_risk += 1

        risk_rows.append({**row, **risk_flags, "risk_score": score, "risk_level": level})

    summary = {
        "records": len(risk_rows),
        "high_risk": high_risk,
        "risk_fields": keys,
    }
    return risk_rows, summary


def stage_feature(rows: List[JsonDict], _: Path) -> Tuple[List[JsonDict], JsonDict]:
    feature_rows: List[JsonDict] = []
    with_unit_price = 0

    current_year = dt.datetime.now().year
    for row in rows:
        area = _to_float(row.get("area_sqm"))
        txn_price = _to_float(row.get("transaction_price"))
        build_year = _to_float(row.get("build_year"))

        unit_price = None
        if area and area > 0 and txn_price is not None:
            unit_price = round(txn_price / area, 2)
            with_unit_price += 1

        age = None
        if build_year and build_year > 1800:
            age = max(0, current_year - int(build_year))

        if area is None:
            area_bucket = "unknown"
        elif area < 60:
            area_bucket = "small"
        elif area < 120:
            area_bucket = "medium"
        else:
            area_bucket = "large"

        feature_rows.append(
            {
                **row,
                "feature_unit_price": unit_price,
                "feature_building_age": age,
                "feature_area_bucket": area_bucket,
            }
        )

    summary = {"records": len(feature_rows), "with_unit_price": with_unit_price}
    return feature_rows, summary


def stage_predict(rows: List[JsonDict], _: Path) -> Tuple[List[JsonDict], JsonDict]:
    predict_rows: List[JsonDict] = []
    predicted = 0

    for row in rows:
        area = _to_float(row.get("area_sqm"))
        unit_price = _to_float(row.get("feature_unit_price"))
        if area is None or unit_price is None:
            predict_rows.append({**row, "predicted_price": None, "predict_confidence": 0.0})
            continue

        risk_score = _to_float(row.get("risk_score")) or 0.0
        discount = max(0.7, 1 - risk_score / 300)
        predicted_price = round(area * unit_price * discount, 2)
        confidence = round(max(0.2, min(0.95, 0.9 - risk_score / 200)), 3)

        predict_rows.append(
            {**row, "predicted_price": predicted_price, "predict_confidence": confidence}
        )
        predicted += 1

    summary = {"records": len(predict_rows), "predicted_count": predicted}
    return predict_rows, summary


def stage_alert(rows: List[JsonDict], _: Path) -> Tuple[List[JsonDict], JsonDict]:
    alert_rows: List[JsonDict] = []
    high_opportunity = 0

    for row in rows:
        predicted = _to_float(row.get("predicted_price"))
        starting = _to_float(row.get("starting_price"))

        margin = None
        margin_ratio = None
        alert_level = "none"
        if predicted is not None and starting is not None and predicted > 0:
            margin = round(predicted - starting, 2)
            margin_ratio = round(margin / predicted, 4)
            risk_level = row.get("risk_level")
            if margin_ratio >= 0.25 and risk_level == "low":
                alert_level = "high_opportunity"
                high_opportunity += 1
            elif margin_ratio >= 0.15:
                alert_level = "watch"

        alert_rows.append(
            {
                **row,
                "alert_margin": margin,
                "alert_margin_ratio": margin_ratio,
                "alert_level": alert_level,
            }
        )

    summary = {"records": len(alert_rows), "high_opportunity": high_opportunity}
    return alert_rows, summary


STAGES: List[Tuple[str, Callable[[List[JsonDict], Path], Tuple[List[JsonDict], JsonDict]]]] = [
    ("canonical", stage_canonical),
    ("risk", stage_risk),
    ("feature", stage_feature),
    ("predict", stage_predict),
    ("alert", stage_alert),
]


def _records_to_jsonl(records: Iterable[JsonDict]) -> str:
    return "\n".join(_json_dumps(r) for r in records) + "\n"


def run_pipeline(input_path: Path, out_dir: Path) -> JsonDict:
    data = _read_jsonl(input_path)
    report: JsonDict = {
        "input_path": str(input_path),
        "input_records": len(data),
        "stages": [],
    }

    current_rows = data
    for stage_name, stage_fn in STAGES:
        stage_dir = out_dir / stage_name
        records, summary = stage_fn(current_rows, stage_dir)
        output_file = stage_dir / f"{stage_name}.jsonl"
        summary_file = stage_dir / f"{stage_name}.summary.json"

        output_changed = _write_if_changed(output_file, _records_to_jsonl(records))
        summary_changed = _write_if_changed(summary_file, _json_dumps(summary) + "\n")

        stage_meta = {
            "stage": stage_name,
            "output_path": str(output_file),
            "summary_path": str(summary_file),
            "records": len(records),
            "summary": summary,
            "updated": output_changed or summary_changed,
            "content_sha256": hashlib.sha256(_records_to_jsonl(records).encode("utf-8")).hexdigest(),
        }
        report["stages"].append(stage_meta)
        current_rows = records

    final_report_file = out_dir / "pipeline_report.json"
    _write_if_changed(final_report_file, _json_dumps(report) + "\n")
    report["report_path"] = str(final_report_file)
    return report


def print_human_report(report: JsonDict) -> None:
    print(f"Input: {report['input_path']} ({report['input_records']} records)")
    print("=" * 72)
    for stage in report["stages"]:
        status = "updated" if stage["updated"] else "unchanged"
        print(f"[{stage['stage']}] {status}")
        print(f"  artifact: {stage['output_path']}")
        print(f"  summary : {stage['summary_path']}")
        print(f"  stats   : {_json_dumps(stage['summary'])}")
    print("=" * 72)
    print(f"Pipeline report: {report['report_path']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run AVM pipeline (canonical -> risk -> feature -> predict -> alert)."
    )
    parser.add_argument(
        "--input",
        default="datas/avm/input/raw_items.jsonl",
        help="Input JSONL file path (default: datas/avm/input/raw_items.jsonl)",
    )
    parser.add_argument(
        "--output-dir",
        default="datas/avm/pipeline",
        help="Pipeline output directory (default: datas/avm/pipeline)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    out_dir = Path(args.output_dir)
    report = run_pipeline(input_path=input_path, out_dir=out_dir)
    print_human_report(report)


if __name__ == "__main__":
    main()
