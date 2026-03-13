import argparse
import json
import os
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.avm.normalize import parse_money_to_yuan
from src.avm.service import AVMService
from tools.build_avm_features import build_avm_features
from tools.build_canonical_dataset import build_canonical_dataset
from tools.generate_avm_alerts import _load_recent_candidates, generate_avm_alerts


def _iter_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fout:
        for row in rows:
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")


def _build_risk(canonical_path: str, output_path: str, stats_path: str) -> Dict[str, Any]:
    rows = _iter_jsonl(canonical_path)
    risk_rows: List[Dict[str, Any]] = []
    level_counts = {"low": 0, "medium": 0, "high": 0}

    for row in rows:
        reasons: List[str] = []
        score = 0

        if not row.get("latitude") or not row.get("longitude"):
            score += 20
            reasons.append("missing_geo")

        area = row.get("area_sqm")
        if area is None or area <= 0:
            score += 30
            reasons.append("invalid_area")

        start_price = row.get("starting_price")
        transaction_price = row.get("transaction_price")
        if start_price and transaction_price and start_price > transaction_price:
            score += 30
            reasons.append("starting_above_transaction")

        unit_price = None
        if area and area > 0 and transaction_price:
            unit_price = transaction_price / area
            if unit_price < 500:
                score += 25
                reasons.append("suspiciously_low_unit_price")
            elif unit_price > 300000:
                score += 25
                reasons.append("suspiciously_high_unit_price")

        if score >= 50:
            level = "high"
        elif score >= 20:
            level = "medium"
        else:
            level = "low"
        level_counts[level] += 1

        risk_rows.append(
            {
                "item_id": row.get("item_id"),
                "risk_score": score,
                "risk_level": level,
                "risk_reasons": reasons,
                "unit_price": round(unit_price, 2) if unit_price else None,
            }
        )

    risk_rows.sort(key=lambda x: (x.get("item_id") or ""))
    _write_jsonl(output_path, risk_rows)

    stats = {
        "total_records": len(risk_rows),
        "risk_level_counts": level_counts,
        "high_risk_ratio": round(level_counts["high"] / max(1, len(risk_rows)), 4),
    }
    with open(stats_path, "w", encoding="utf-8") as fout:
        json.dump(stats, fout, ensure_ascii=False, indent=2)

    return {
        "risk_path": output_path,
        "risk_stats_path": stats_path,
        "stats": stats,
    }


def _build_predictions(data_dir: str, output_path: str, limit: int) -> Dict[str, Any]:
    service = AVMService(data_dir=data_dir)
    candidates = _load_recent_candidates(data_dir=data_dir, limit=limit)

    predictions: List[Dict[str, Any]] = []
    confidences: List[float] = []

    for row in candidates:
        item_id = row.get("id") or row.get("唯一id") or row.get("item_id")
        if item_id is None:
            continue

        result = service.predict_by_item_data(row)
        predicted_price = result.get("predicted_price")
        confidence = result.get("confidence")
        starting_price = parse_money_to_yuan(row.get("起拍价格") or row.get("starting_price") or row.get("initialPrice"))

        if isinstance(confidence, (int, float)):
            confidences.append(float(confidence))

        predictions.append(
            {
                "item_id": str(item_id),
                "predicted_price": predicted_price,
                "predicted_unit_price": result.get("predicted_unit_price"),
                "confidence": confidence,
                "comparable_count": result.get("comparable_count"),
                "starting_price": starting_price,
                "has_prediction": predicted_price is not None,
            }
        )

    predictions.sort(key=lambda x: x["item_id"])
    _write_jsonl(output_path, predictions)

    stats = {
        "total_candidates": len(candidates),
        "predicted_records": sum(1 for x in predictions if x["has_prediction"]),
        "avg_confidence": round(mean(confidences), 4) if confidences else None,
    }

    return {
        "predictions_path": output_path,
        "stats": stats,
    }


def run_pipeline(data_dir: str, alerts_threshold: float, alerts_limit: int) -> Dict[str, Any]:
    canonical_dir = os.path.join(data_dir, "canonical")
    avm_dir = os.path.join(data_dir, "avm")
    os.makedirs(canonical_dir, exist_ok=True)
    os.makedirs(avm_dir, exist_ok=True)

    canonical_path = os.path.join(canonical_dir, "canonical.jsonl")
    risk_path = os.path.join(avm_dir, "risk.jsonl")
    risk_stats_path = os.path.join(avm_dir, "risk_stats.json")
    features_path = os.path.join(avm_dir, "features.jsonl")
    feature_stats_path = os.path.join(avm_dir, "feature_stats.json")
    predictions_path = os.path.join(avm_dir, "predictions.jsonl")
    alerts_path = os.path.join(avm_dir, "alerts.json")

    canonical_result = build_canonical_dataset(data_dir=data_dir, output_dir=canonical_dir)
    risk_result = _build_risk(canonical_path=canonical_path, output_path=risk_path, stats_path=risk_stats_path)
    feature_result = build_avm_features(
        canonical_path=canonical_path,
        output_path=features_path,
        stats_path=feature_stats_path,
    )
    predict_result = _build_predictions(data_dir=data_dir, output_path=predictions_path, limit=alerts_limit)
    alert_result = generate_avm_alerts(
        data_dir=data_dir,
        output_path=alerts_path,
        threshold=alerts_threshold,
        limit=alerts_limit,
    )

    return {
        "data_dir": data_dir,
        "idempotent": True,
        "stages": [
            {
                "name": "canonical",
                "artifacts": {
                    "canonical": canonical_result["canonical_path"],
                    "failed": canonical_result["failed_path"],
                    "quality": canonical_result["quality_path"],
                },
                "summary": canonical_result["quality"],
            },
            {
                "name": "risk",
                "artifacts": {
                    "risk": risk_result["risk_path"],
                    "risk_stats": risk_result["risk_stats_path"],
                },
                "summary": risk_result["stats"],
            },
            {
                "name": "feature",
                "artifacts": {
                    "features": feature_result["features_path"],
                    "feature_stats": feature_result["stats_path"],
                },
                "summary": feature_result["stats"],
            },
            {
                "name": "predict",
                "artifacts": {"predictions": predict_result["predictions_path"]},
                "summary": predict_result["stats"],
            },
            {
                "name": "alert",
                "artifacts": {"alerts": alert_result["output_path"]},
                "summary": {
                    "threshold": alert_result["payload"]["threshold"],
                    "count": alert_result["payload"]["count"],
                },
            },
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AVM pipeline: canonical -> risk -> feature -> predict -> alert")
    parser.add_argument("--data-dir", default="datas", help="Data directory")
    parser.add_argument("--alerts-threshold", type=float, default=0.15, help="Alert margin threshold")
    parser.add_argument("--alerts-limit", type=int, default=500, help="Max rows for predict/alert stages")
    args = parser.parse_args()

    result = run_pipeline(
        data_dir=args.data_dir,
        alerts_threshold=args.alerts_threshold,
        alerts_limit=args.alerts_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
