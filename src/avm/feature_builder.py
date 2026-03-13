"""AVM feature building utilities.

Inputs:
- Canonical auction records (normalized transaction records)
- Risk label records (boolean/enum risk factors)

Outputs:
- Flattened training samples keyed by (item_id, auction_date)
- Feature statistics used as pre-training data quality gates
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

PRIMARY_KEY = ("item_id", "auction_date")

CANONICAL_ALIASES = {
    "item_id": ["item_id", "id", "auction_id"],
    "auction_date": ["auction_date", "deal_date", "成交日期", "交易时间"],
    "longitude": ["longitude", "lng", "lon", "经度"],
    "latitude": ["latitude", "lat", "纬度"],
    "province": ["province", "省", "province_name"],
    "city": ["city", "城市", "city_name"],
    "district": ["district", "行政区", "区县", "area"],
    "deal_price": ["deal_price", "transaction_price", "成交价", "成交价格", "price"],
    "start_price": ["start_price", "起拍价", "starting_price"],
    "eval_price": ["eval_price", "评估价", "assessment_price"],
    "building_area": ["building_area", "area", "建筑面积", "面积"],
    "floor": ["floor", "楼层", "floor_info"],
    "orientation": ["orientation", "朝向", "house_orientation"],
}


class EnumEncoder:
    """Stable enum->index encoder per field."""

    def __init__(self) -> None:
        self._mapping: Dict[str, Dict[str, int]] = defaultdict(dict)

    def fit_value(self, field: str, value: Any) -> Optional[int]:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None
        m = self._mapping[field]
        if text not in m:
            m[text] = len(m)
        return m[text]

    def mapping(self) -> Dict[str, Dict[str, int]]:
        return dict(self._mapping)


def _pick(record: Mapping[str, Any], candidates: Sequence[str]) -> Any:
    for key in candidates:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)

    text = str(value).strip().replace(",", "")
    if text == "":
        return None

    filtered = "".join(ch for ch in text if ch in "0123456789.-")
    if filtered in ("", "-", ".", "-."):
        return None

    try:
        return float(filtered)
    except ValueError:
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        return None

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _to_timestamp_index(dt: Optional[datetime]) -> Optional[int]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() // 86400)


def _normalize_bool_like(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        if value in (0, 1):
            return int(value)
        return None

    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "是", "有", "命中", "高", "高风险"}:
        return 1
    if text in {"0", "false", "no", "n", "否", "无", "未命中", "低", "低风险"}:
        return 0
    return None


def _extract_base_features(record: Mapping[str, Any], encoder: EnumEncoder) -> Dict[str, Any]:
    auction_dt = _parse_datetime(_pick(record, CANONICAL_ALIASES["auction_date"]))

    district_value = _pick(record, CANONICAL_ALIASES["district"])
    floor_value = _pick(record, CANONICAL_ALIASES["floor"])
    orientation_value = _pick(record, CANONICAL_ALIASES["orientation"])

    return {
        "item_id": str(_pick(record, CANONICAL_ALIASES["item_id"]) or "").strip() or None,
        "auction_date": auction_dt.isoformat() if auction_dt else None,
        # 空间特征
        "longitude": _to_float(_pick(record, CANONICAL_ALIASES["longitude"])),
        "latitude": _to_float(_pick(record, CANONICAL_ALIASES["latitude"])),
        "province": _pick(record, CANONICAL_ALIASES["province"]),
        "city": _pick(record, CANONICAL_ALIASES["city"]),
        "district": district_value,
        "district_code": encoder.fit_value("district", district_value),
        # 时间特征
        "auction_day_index": _to_timestamp_index(auction_dt),
        "auction_year": auction_dt.year if auction_dt else None,
        "auction_month": auction_dt.month if auction_dt else None,
        # 价格特征
        "deal_price": _to_float(_pick(record, CANONICAL_ALIASES["deal_price"])),
        "start_price": _to_float(_pick(record, CANONICAL_ALIASES["start_price"])),
        "eval_price": _to_float(_pick(record, CANONICAL_ALIASES["eval_price"])),
        # 结构特征
        "building_area": _to_float(_pick(record, CANONICAL_ALIASES["building_area"])),
        "floor": floor_value,
        "floor_code": encoder.fit_value("floor", floor_value),
        "orientation": orientation_value,
        "orientation_code": encoder.fit_value("orientation", orientation_value),
    }


def _index_risk_records(risk_records: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str], Mapping[str, Any]]:
    indexed: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    for risk in risk_records:
        item_id = _pick(risk, CANONICAL_ALIASES["item_id"])
        auction_dt = _parse_datetime(_pick(risk, CANONICAL_ALIASES["auction_date"]))
        if not item_id or not auction_dt:
            continue
        key = (str(item_id), auction_dt.isoformat())
        indexed[key] = risk
    return indexed


def _encode_risk_features(
    risk_record: Optional[Mapping[str, Any]],
    enum_encoder: EnumEncoder,
) -> Dict[str, Any]:
    if not risk_record:
        return {}

    encoded: Dict[str, Any] = {}
    for field, raw_value in risk_record.items():
        if field in CANONICAL_ALIASES["item_id"] or field in CANONICAL_ALIASES["auction_date"]:
            continue
        feature_name = f"risk_{field}"
        bool_val = _normalize_bool_like(raw_value)
        if bool_val is not None:
            encoded[feature_name] = bool_val
            continue

        numeric_val = _to_float(raw_value)
        if numeric_val is not None and float(int(numeric_val)) == numeric_val:
            encoded[feature_name] = int(numeric_val)
            continue

        enum_val = enum_encoder.fit_value(feature_name, raw_value)
        encoded[feature_name] = enum_val

    return encoded


def build_feature_samples(
    canonical_records: Iterable[Mapping[str, Any]],
    risk_records: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Build flattened samples and generation metadata."""
    base_encoder = EnumEncoder()
    risk_encoder = EnumEncoder()

    indexed_risk = _index_risk_records(risk_records or [])

    deduped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    duplicates = 0
    invalid_primary_keys = 0

    for record in canonical_records:
        base = _extract_base_features(record, base_encoder)
        key = (base.get("item_id"), base.get("auction_date"))
        if not all(key):
            invalid_primary_keys += 1
            continue

        risk = indexed_risk.get(key)
        feature_row = {**base, **_encode_risk_features(risk, risk_encoder)}

        if key in deduped:
            duplicates += 1
            continue
        deduped[key] = feature_row

    samples = list(deduped.values())
    metadata = {
        "primary_key": list(PRIMARY_KEY),
        "sample_count": len(samples),
        "duplicate_dropped": duplicates,
        "invalid_primary_key_dropped": invalid_primary_keys,
        "enum_mappings": {
            "base": base_encoder.mapping(),
            "risk": risk_encoder.mapping(),
        },
    }
    return samples, metadata


def _iqr_outlier_count(values: Sequence[float]) -> int:
    if len(values) < 4:
        return 0
    arr = sorted(values)
    q1 = arr[len(arr) // 4]
    q3 = arr[(len(arr) * 3) // 4]
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return sum(1 for v in values if v < lower or v > upper)


def build_feature_stats(samples: Sequence[Mapping[str, Any]], metadata: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Compute distribution / missing / outlier stats for training gate checks."""
    if not samples:
        return {"summary": {"sample_count": 0}, "features": {}, "metadata": metadata or {}}

    fields = sorted({k for row in samples for k in row.keys()})
    total = len(samples)
    stats: Dict[str, Any] = {}

    for field in fields:
        values = [row.get(field) for row in samples]
        missing = sum(1 for v in values if v is None or v == "")
        non_missing = [v for v in values if v is not None and v != ""]
        numeric_values = [float(v) for v in non_missing if isinstance(v, (int, float)) and not isinstance(v, bool)]

        field_stat: Dict[str, Any] = {
            "missing_count": missing,
            "missing_rate": round(missing / total, 6),
        }

        if len(numeric_values) == len(non_missing) and numeric_values:
            sorted_values = sorted(numeric_values)
            p95_idx = int((len(sorted_values) - 1) * 0.95)
            field_stat.update(
                {
                    "type": "numeric",
                    "min": min(sorted_values),
                    "max": max(sorted_values),
                    "mean": sum(sorted_values) / len(sorted_values),
                    "median": median(sorted_values),
                    "p95": sorted_values[p95_idx],
                    "outlier_count": _iqr_outlier_count(sorted_values),
                }
            )
        else:
            counter = Counter(str(v) for v in non_missing)
            field_stat.update(
                {
                    "type": "categorical",
                    "distinct": len(counter),
                    "top_values": counter.most_common(20),
                    "outlier_count": 0,
                }
            )

        stats[field] = field_stat

    return {
        "summary": {
            "sample_count": total,
            "feature_count": len(fields),
        },
        "metadata": metadata or {},
        "features": stats,
    }
