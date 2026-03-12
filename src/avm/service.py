import glob
import json
import os
from typing import Any, Dict, List, Optional

from .canonical_mapper import map_raw_to_canonical
from .feature_builder import build_features
from .engine import predict_price


class AVMService:
    def __init__(self, data_dir: str = "datas") -> None:
        self.data_dir = data_dir

    def _iter_raw_records(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        candidates = glob.glob(os.path.join(self.data_dir, "*.json"))
        archive_candidates = glob.glob(os.path.join(self.data_dir, "archive", "**", "*.json"), recursive=True)
        files = candidates + archive_candidates

        skip_names = {
            "all_locations.json",
            "sniff_progress.json",
            "collected_locations.json",
            "model_config.json",
            "tuning_history.json",
            "seen_ids.json",
        }
        for path in files:
            if os.path.basename(path) in skip_names:
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            records.append(item)
            except Exception:
                continue
        return records

    def _build_feature_dataset(self) -> List[Dict[str, Any]]:
        dataset: List[Dict[str, Any]] = []
        for raw in self._iter_raw_records():
            try:
                c = map_raw_to_canonical(raw)
                f = build_features(c)
            except Exception:
                continue
            dataset.append(f)
        return dataset

    def predict_by_item_data(self, item_data: Dict[str, Any]) -> Dict[str, Any]:
        subject = build_features(map_raw_to_canonical(item_data))
        dataset = self._build_feature_dataset()
        return predict_price(subject, dataset)

    def predict_by_item_id(self, item_id: str) -> Dict[str, Any]:
        subject: Optional[Dict[str, Any]] = None
        for raw in self._iter_raw_records():
            raw_id = raw.get("id") or raw.get("唯一id") or raw.get("item_id")
            if str(raw_id) == str(item_id):
                subject = raw
                break
        if not subject:
            return {"error": "item_not_found", "item_id": str(item_id)}
        result = self.predict_by_item_data(subject)
        result["item_id"] = str(item_id)
        if subject.get("起拍价格"):
            try:
                sp = float(str(subject.get("起拍价格")).replace(",", ""))
                pp = result.get("predicted_price")
                if pp:
                    result["margin_of_safety"] = round((pp - sp) / pp, 4)
            except Exception:
                pass
        return result
