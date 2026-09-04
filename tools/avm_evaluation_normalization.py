"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_evaluation_context import *


def _normalized_group_value(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"", "UNK", "未知", "None", "null"}:
        return ""
    return text


def _normalize_feature_records(data_root: Path) -> List[dict[str, Any]]:
    normalized: List[dict[str, Any]] = []
    for raw in _load_raw_archive_records(data_root):
        try:
            canonical = map_raw_to_canonical(raw)
            feature = build_features(canonical)
        except Exception:
            continue

        passed, _ = price_plausibility(feature)
        if not passed:
            continue

        actual_price = _actual_total_price(feature)
        actual_unit = _actual_unit_price(feature)
        month = _feature_month(feature)
        if actual_price is None or actual_unit is None or month is None:
            continue

        risk_data = {field: feature.get(field) for field in RISK_FEATURE_RULES.keys()}
        risk_ok, risk_errors = validate_risk_features(risk_data)
        required_fields = [field for field, rule in RISK_FEATURE_RULES.items() if rule.get("required")]
        missing_required_fields = [field for field in required_fields if risk_data.get(field) is None]
        invalid_fields = sorted(
            {
                error.split(":", 1)[0]
                for error in risk_errors
                if ":" in error and "缺失必填字段" not in error and not error.startswith("存在未定义字段")
            }
        )

        record = dict(feature)
        record["actual_price"] = actual_price
        record["actual_unit_price"] = actual_unit
        record["month"] = month
        record["partition"] = f"{record.get('city', 'UNK')}-{record.get('district', 'UNK')}"
        record["coordinate_strategy"] = _derive_coordinate_strategy(record)
        record["risk_validation_ok"] = risk_ok
        record["risk_missing_required_count"] = len(missing_required_fields)
        record["risk_invalid_field_count"] = len(invalid_fields)
        normalized.append(record)
    normalized = _enrich_coordinate_records(normalized)
    normalized.sort(key=lambda row: (row["month"], str(row.get("item_id"))))
    return normalized


__all__ = (
    "_normalized_group_value",
    "_normalize_feature_records",
)
