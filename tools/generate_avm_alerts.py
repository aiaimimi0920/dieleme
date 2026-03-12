import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.avm.service import AVMService
from src.avm.normalize import parse_money_to_yuan


def _load_recent_candidates(data_dir: str, limit: int = 500) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    files = sorted([p for p in os.listdir(data_dir) if p.endswith('.json')], reverse=True)
    skip = {
        "all_locations.json", "sniff_progress.json", "collected_locations.json",
        "model_config.json", "tuning_history.json", "seen_ids.json"
    }
    for name in files:
        if name in skip:
            continue
        path = os.path.join(data_dir, name)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            if isinstance(payload, list):
                rows.extend([x for x in payload if isinstance(x, dict)])
        except Exception:
            continue
        if len(rows) >= limit:
            break
    return rows[:limit]


def generate_avm_alerts(data_dir: str = "datas", output_path: str = "datas/avm/alerts.json", threshold: float = 0.15, limit: int = 500) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    service = AVMService(data_dir=data_dir)

    alerts: List[Dict[str, Any]] = []
    for row in _load_recent_candidates(data_dir, limit=limit):
        item_id = row.get("id") or row.get("唯一id") or row.get("item_id")
        if item_id is None:
            continue

        result = service.predict_by_item_data(row)
        pred = result.get("predicted_price")
        if not pred:
            continue

        starting = parse_money_to_yuan(row.get("起拍价格") or row.get("starting_price") or row.get("initialPrice"))
        if not starting:
            continue

        margin = (pred - starting) / pred
        if margin >= threshold:
            alerts.append({
                "item_id": str(item_id),
                "predicted_price": pred,
                "starting_price": starting,
                "margin_of_safety": round(margin, 4),
                "confidence": result.get("confidence"),
                "comparable_count": result.get("comparable_count"),
            })

    alerts.sort(key=lambda x: x["margin_of_safety"], reverse=True)
    payload = {"threshold": threshold, "count": len(alerts), "alerts": alerts}
    with open(output_path, "w", encoding="utf-8") as fout:
        json.dump(payload, fout, ensure_ascii=False, indent=2)

    return {"output_path": output_path, "payload": payload}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AVM margin-of-safety alerts")
    parser.add_argument("--data-dir", default="datas", help="Raw data directory")
    parser.add_argument("--output", default="datas/avm/alerts.json", help="Alert output path")
    parser.add_argument("--threshold", type=float, default=0.15, help="Margin threshold")
    parser.add_argument("--limit", type=int, default=500, help="Max candidates to evaluate")
    args = parser.parse_args()

    result = generate_avm_alerts(data_dir=args.data_dir, output_path=args.output, threshold=args.threshold, limit=args.limit)
    print(f"Alerts written: {result['output_path']} (count={result['payload']['count']})")


if __name__ == "__main__":
    main()
