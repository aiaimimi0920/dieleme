import datetime
import glob
import json
import os
from typing import Any, Dict, Optional

DATA_DIR = "datas"


class AVMItemNotFoundError(ValueError):
    """Raised when a requested item id cannot be found in data files."""


def _iter_data_files(data_dir: str = DATA_DIR):
    root_pattern = os.path.join(data_dir, "*.json")
    archive_pattern = os.path.join(data_dir, "archive", "**", "*.json")

    skip_files = {
        "all_locations.json",
        "manual_priority_locations.json",
        "sniff_progress.json",
        "collected_locations.json",
        "model_config.json",
        "tuning_history.json",
        "seen_ids.json",
    }

    files = glob.glob(root_pattern) + glob.glob(archive_pattern, recursive=True)
    for path in files:
        if os.path.basename(path) in skip_files:
            continue
        yield path


def _read_item_by_id(item_id: str, data_dir: str = DATA_DIR) -> Dict[str, Any]:
    target_id = str(item_id)

    for file_path in _iter_data_files(data_dir):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
        except Exception:
            continue

        rows = content if isinstance(content, list) else [content]
        for row in rows:
            if str(row.get("id")) == target_id:
                return row

    raise AVMItemNotFoundError(f"Item not found: {target_id}")


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    text = text.replace(",", "")
    multiplier = 1.0
    if text.endswith("万"):
        multiplier = 10000.0
        text = text[:-1]

    match = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
    if not match:
        return None

    try:
        return float(match) * multiplier
    except ValueError:
        return None


def _map_raw_to_canonical(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "item_id": str(raw.get("id", "")),
        "source_url": raw.get("url"),
        "transaction_price": _to_float(raw.get("成交价格")),
        "starting_price": _to_float(raw.get("起拍价格")),
        "area_sqm": _to_float(raw.get("建筑面积")),
        "auction_date": raw.get("交易时间"),
        "community_name": raw.get("所属小区") or raw.get("小区"),
        "latitude": _to_float(raw.get("latitude") or raw.get("纬度")),
        "longitude": _to_float(raw.get("longitude") or raw.get("经度")),
    }


def _build_features(canonical: Dict[str, Any]) -> Dict[str, Any]:
    transaction_price = canonical.get("transaction_price")
    starting_price = canonical.get("starting_price")
    area_sqm = canonical.get("area_sqm")

    unit_price = None
    if transaction_price and area_sqm and area_sqm > 0:
        unit_price = transaction_price / area_sqm

    premium_rate = None
    if transaction_price and starting_price and starting_price > 0:
        premium_rate = (transaction_price - starting_price) / starting_price

    has_geo = canonical.get("latitude") is not None and canonical.get("longitude") is not None

    return {
        "unit_price": unit_price,
        "premium_rate": premium_rate,
        "has_geo": has_geo,
        "area_sqm": area_sqm,
    }


def _predict(features: Dict[str, Any]) -> Dict[str, Any]:
    # Phase-0 baseline predictor: use transaction unit price as current fair unit price anchor
    fair_unit_price = features.get("unit_price")

    confidence = 0.4
    if fair_unit_price is not None:
        confidence += 0.3
    if features.get("has_geo"):
        confidence += 0.2
    if features.get("premium_rate") is not None:
        confidence += 0.1

    confidence = min(1.0, max(0.0, confidence))

    return {
        "estimated_fair_unit_price": fair_unit_price,
        "confidence": round(confidence, 4),
        "model_version": "baseline-v0",
        "predicted_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def predict_by_item_id(item_id: str, data_dir: str = DATA_DIR) -> Dict[str, Any]:
    """Read data -> map -> feature engineering -> predict by item id."""
    raw = _read_item_by_id(item_id=item_id, data_dir=data_dir)
    canonical = _map_raw_to_canonical(raw)
    features = _build_features(canonical)
    prediction = _predict(features)

    return {
        "item_id": str(item_id),
        "canonical": canonical,
        "features": features,
        "prediction": prediction,
    }
