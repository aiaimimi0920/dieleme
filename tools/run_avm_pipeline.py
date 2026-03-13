import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.avm.normalize import parse_money_to_yuan
from src.avm.risk_schema import RISK_FEATURE_RULES, validate_risk_features
from src.avm.service import AVMService
from tools.build_avm_features import build_avm_features
from tools.build_canonical_dataset import build_canonical_dataset

SKIP_FILES = {
    "all_locations.json",
    "sniff_progress.json",
    "collected_locations.json",
    "model_config.json",
    "tuning_history.json",
    "seen_ids.json",
}


def _iter_input_files(data_dir: str) -> List[str]:
    root_files = glob.glob(os.path.join(data_dir, "*.json"))
    archive_files = glob.glob(os.path.join(data_dir, "archive", "**", "*.json"), recursive=True)
    files = [p for p in (root_files + archive_files) if os.path.basename(p) not in SKIP_FILES]
    return sorted(files)


def _load_candidates(data_dir: str, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in _iter_input_files(data_dir):
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue
        if not isinstance(payload, list):
            continue
        for row in payload:
            if isinstance(row, dict):
                rows.append(row)
            if len(rows) >= limit:
                return rows
    return rows


def _extract_risk_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    return {field: row.get(field) for field in RISK_FEATURE_RULES.keys()}


def _run_risk_stage(data_dir: str, output_path: str, summary_path: str) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    records = 0
    valid = 0
    invalid = 0
    missing_counter = {field: 0 for field in RISK_FEATURE_RULES.keys()}

    with open(output_path, "w", encoding="utf-8") as fout:
        for path in _iter_input_files(data_dir):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue
            if not isinstance(payload, list):
                continue

            for row in payload:
                if not isinstance(row, dict):
                    continue
                risk = _extract_risk_fields(row)
                ok, errors = validate_risk_features(risk)
                records += 1
                if ok:
                    valid += 1
                else:
                    invalid += 1
                for key, value in risk.items():
                    if value is None:
                        missing_counter[key] += 1

                fout.write(
                    json.dumps(
                        {
                            "item_id": str(row.get("id") or row.get("唯一id") or row.get("item_id") or ""),
                            "risk_features": risk,
                            "validation_ok": ok,
                            "error_count": len(errors),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    summary = {
        "total_records": records,
        "valid_records": valid,
        "invalid_records": invalid,
        "missing_field_count": missing_counter,
    }
    with open(summary_path, "w", encoding="utf-8") as fsum:
        json.dump(summary, fsum, ensure_ascii=False, indent=2)

    return {"output_path": output_path, "summary_path": summary_path, "summary": summary}


def _run_predict_stage(data_dir: str, output_path: str, limit: int) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    service = AVMService(data_dir=data_dir)
    rows = _load_candidates(data_dir, limit=limit)

    total = 0
    predicted = 0
    with_price = 0

    with open(output_path, "w", encoding="utf-8") as fout:
        for row in rows:
            item_id = str(row.get("id") or row.get("唯一id") or row.get("item_id") or "")
            if not item_id:
                continue
            result = service.predict_by_item_data(row)
            total += 1
            if result.get("predicted_price"):
                predicted += 1

            starting_price = parse_money_to_yuan(row.get("起拍价格") or row.get("starting_price") or row.get("initialPrice"))
            if starting_price:
                with_price += 1

            rec = {
                "item_id": item_id,
                "starting_price": starting_price,
                "prediction": result,
            }
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")

    summary = {
        "total_candidates": total,
        "predicted_count": predicted,
        "with_starting_price": with_price,
    }
    return {"output_path": output_path, "summary": summary}


def _run_alert_stage(predictions_path: str, output_path: str, threshold: float) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    alerts: List[Dict[str, Any]] = []
    total = 0

    with open(predictions_path, "r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            total += 1
            row = json.loads(line)
            pred = (row.get("prediction") or {}).get("predicted_price")
            starting = row.get("starting_price")
            if not pred or not starting:
                continue
            margin = (pred - starting) / pred
            if margin >= threshold:
                alerts.append(
                    {
                        "item_id": row.get("item_id"),
                        "predicted_price": pred,
                        "starting_price": starting,
                        "margin_of_safety": round(margin, 4),
                        "confidence": (row.get("prediction") or {}).get("confidence"),
                        "comparable_count": (row.get("prediction") or {}).get("comparable_count"),
                    }
                )

    alerts.sort(key=lambda x: x["margin_of_safety"], reverse=True)
    payload = {"threshold": threshold, "count": len(alerts), "evaluated": total, "alerts": alerts}
    with open(output_path, "w", encoding="utf-8") as fout:
        json.dump(payload, fout, ensure_ascii=False, indent=2)

    return {"output_path": output_path, "summary": {"evaluated": total, "alerts": len(alerts)}}


def run_pipeline(data_dir: str, alerts_threshold: float, predict_limit: int) -> Dict[str, Any]:
    canonical_dir = os.path.join(data_dir, "canonical")
    avm_dir = os.path.join(data_dir, "avm")

    canonical_path = os.path.join(canonical_dir, "canonical.jsonl")
    feature_path = os.path.join(avm_dir, "features.jsonl")
    feature_stats_path = os.path.join(avm_dir, "feature_stats.json")
    risk_path = os.path.join(avm_dir, "risk.jsonl")
    risk_summary_path = os.path.join(avm_dir, "risk_summary.json")
    predictions_path = os.path.join(avm_dir, "predictions.jsonl")
    alerts_path = os.path.join(avm_dir, "alerts.json")

    stage_results: List[Tuple[str, Dict[str, Any]]] = []

    canonical_result = build_canonical_dataset(data_dir=data_dir, output_dir=canonical_dir)
    stage_results.append(
        (
            "canonical",
            {
                "path": canonical_result["canonical_path"],
                "summary": {
                    "total_records": canonical_result["quality"]["total_records"],
                    "success_records": canonical_result["quality"]["success_records"],
                    "failed_records": canonical_result["quality"]["failed_records"],
                },
            },
        )
    )

    risk_result = _run_risk_stage(data_dir=data_dir, output_path=risk_path, summary_path=risk_summary_path)
    stage_results.append(("risk", {"path": risk_result["output_path"], "summary": risk_result["summary"]}))

    feature_result = build_avm_features(
        canonical_path=canonical_path,
        output_path=feature_path,
        stats_path=feature_stats_path,
    )
    stage_results.append(("feature", {"path": feature_result["features_path"], "summary": feature_result["stats"]}))

    predict_result = _run_predict_stage(data_dir=data_dir, output_path=predictions_path, limit=predict_limit)
    stage_results.append(("predict", {"path": predict_result["output_path"], "summary": predict_result["summary"]}))

    alert_result = _run_alert_stage(predictions_path=predictions_path, output_path=alerts_path, threshold=alerts_threshold)
    stage_results.append(("alert", {"path": alert_result["output_path"], "summary": alert_result["summary"]}))

    return {"data_dir": data_dir, "stages": [{"name": name, **payload} for name, payload in stage_results]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AVM pipeline: canonical -> risk -> feature -> predict -> alert")
    parser.add_argument("--data-dir", default="datas", help="Data directory")
    parser.add_argument("--alerts-threshold", type=float, default=0.15, help="Alert margin threshold")
    parser.add_argument("--predict-limit", type=int, default=500, help="Max candidate rows for prediction stage")
    args = parser.parse_args()

    result = run_pipeline(data_dir=args.data_dir, alerts_threshold=args.alerts_threshold, predict_limit=args.predict_limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
