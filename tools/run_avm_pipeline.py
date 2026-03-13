import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.avm.normalize import parse_money_to_yuan
from src.avm.risk_schema import RISK_FEATURE_RULES, validate_risk_features
from src.avm.service import AVMService
from tools.build_avm_features import build_avm_features
from tools.build_canonical_dataset import build_canonical_dataset
from tools.generate_avm_alerts import _load_recent_candidates


def _iter_jsonl(path: str):
    with open(path, "r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if line:
                yield json.loads(line)


def _run_risk_stage(canonical_path: str, output_path: str) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    summary = {
        "total_records": 0,
        "passed_records": 0,
        "failed_records": 0,
    }

    with open(output_path, "w", encoding="utf-8") as fout:
        for row in _iter_jsonl(canonical_path):
            summary["total_records"] += 1
            risk_features = {k: row.get(k) for k in RISK_FEATURE_RULES}
            ok, errors = validate_risk_features(risk_features)
            if ok:
                summary["passed_records"] += 1
            else:
                summary["failed_records"] += 1

            payload = {
                "item_id": row.get("item_id"),
                "ok": ok,
                "error_count": len(errors),
                "errors": errors,
            }
            fout.write(json.dumps(payload, ensure_ascii=False) + "\n")

    return {
        "artifact": output_path,
        "summary": summary,
    }


def _run_predict_stage(data_dir: str, output_path: str, limit: int) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    service = AVMService(data_dir=data_dir)

    summary = {
        "candidate_records": 0,
        "predicted_records": 0,
        "missing_item_id": 0,
        "missing_prediction": 0,
    }

    rows = _load_recent_candidates(data_dir=data_dir, limit=limit)
    with open(output_path, "w", encoding="utf-8") as fout:
        for row in rows:
            summary["candidate_records"] += 1
            item_id = row.get("id") or row.get("唯一id") or row.get("item_id")
            if item_id is None:
                summary["missing_item_id"] += 1
                continue

            result = service.predict_by_item_data(row)
            predicted_price = result.get("predicted_price")
            if not predicted_price:
                summary["missing_prediction"] += 1
                continue

            starting_price = parse_money_to_yuan(
                row.get("起拍价格") or row.get("starting_price") or row.get("initialPrice")
            )
            payload = {
                "item_id": str(item_id),
                "predicted_price": predicted_price,
                "starting_price": starting_price,
                "confidence": result.get("confidence"),
                "comparable_count": result.get("comparable_count"),
            }
            fout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            summary["predicted_records"] += 1

    return {
        "artifact": output_path,
        "summary": summary,
    }


def _run_alert_stage(predictions_path: str, output_path: str, threshold: float) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    alerts: List[Dict[str, Any]] = []

    total_predictions = 0
    with open(predictions_path, "r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            total_predictions += 1
            row = json.loads(line)
            pred = row.get("predicted_price")
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
                        "confidence": row.get("confidence"),
                        "comparable_count": row.get("comparable_count"),
                    }
                )

    alerts.sort(key=lambda x: (-x["margin_of_safety"], x["item_id"]))
    payload = {"threshold": threshold, "count": len(alerts), "alerts": alerts}
    with open(output_path, "w", encoding="utf-8") as fout:
        json.dump(payload, fout, ensure_ascii=False, indent=2)

    return {
        "artifact": output_path,
        "summary": {
            "predictions_scanned": total_predictions,
            "alerts_generated": len(alerts),
            "threshold": threshold,
        },
    }


def run_pipeline(data_dir: str, alerts_threshold: float, predict_limit: int) -> Dict[str, Any]:
    canonical_dir = os.path.join(data_dir, "canonical")
    avm_dir = os.path.join(data_dir, "avm")

    canonical_path = os.path.join(canonical_dir, "canonical.jsonl")
    risk_path = os.path.join(avm_dir, "risk_validation.jsonl")
    feature_path = os.path.join(avm_dir, "features.jsonl")
    feature_stats_path = os.path.join(avm_dir, "feature_stats.json")
    predictions_path = os.path.join(avm_dir, "predictions.jsonl")
    alerts_path = os.path.join(avm_dir, "alerts.json")

    result: Dict[str, Any] = {"stages": []}

    canonical_stage = build_canonical_dataset(data_dir=data_dir, output_dir=canonical_dir)
    result["stages"].append(
        {
            "name": "canonical",
            "artifact": canonical_stage["canonical_path"],
            "summary": canonical_stage["quality"],
        }
    )

    risk_stage = _run_risk_stage(canonical_path=canonical_path, output_path=risk_path)
    result["stages"].append({"name": "risk", **risk_stage})

    feature_stage = build_avm_features(
        canonical_path=canonical_path,
        output_path=feature_path,
        stats_path=feature_stats_path,
    )
    result["stages"].append(
        {
            "name": "feature",
            "artifact": feature_stage["features_path"],
            "summary": feature_stage["stats"],
        }
    )

    predict_stage = _run_predict_stage(data_dir=data_dir, output_path=predictions_path, limit=predict_limit)
    result["stages"].append({"name": "predict", **predict_stage})

    alert_stage = _run_alert_stage(
        predictions_path=predictions_path,
        output_path=alerts_path,
        threshold=alerts_threshold,
    )
    result["stages"].append({"name": "alert", **alert_stage})

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AVM pipeline in order: canonical -> risk -> feature -> predict -> alert")
    parser.add_argument("--data-dir", default="datas", help="Data directory")
    parser.add_argument("--alerts-threshold", type=float, default=0.15, help="Alert margin threshold")
    parser.add_argument("--predict-limit", type=int, default=500, help="Max candidate records for prediction stage")
    args = parser.parse_args()

    result = run_pipeline(
        data_dir=args.data_dir,
        alerts_threshold=args.alerts_threshold,
        predict_limit=args.predict_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
