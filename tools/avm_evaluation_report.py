"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_evaluation_context import *


def build_diagnostics(records: List[dict[str, Any]], predictions: List[dict[str, Any]], case_limit: int) -> dict[str, Any]:
    housing_type_counts: Dict[str, int] = defaultdict(int)
    suspicious_counts = {
        "housing_type_other": 0,
        "actual_unit_price_lt_500": 0,
        "actual_unit_price_lt_1000": 0,
        "actual_unit_price_gt_200000": 0,
        "area_sqm_lt_10": 0,
        "area_sqm_gt_1000": 0,
    }

    by_item_id = {str(row.get("item_id")): row for row in records}
    for row in records:
        housing_type = str(row.get("housing_type") or "其他")
        housing_type_counts[housing_type] += 1
        actual_unit_price = float(row.get("actual_unit_price") or 0.0)
        area_sqm = float(row.get("area_sqm") or 0.0)
        if housing_type == "其他":
            suspicious_counts["housing_type_other"] += 1
        if 0 < actual_unit_price < 500:
            suspicious_counts["actual_unit_price_lt_500"] += 1
        if 0 < actual_unit_price < 1000:
            suspicious_counts["actual_unit_price_lt_1000"] += 1
        if actual_unit_price > 200000:
            suspicious_counts["actual_unit_price_gt_200000"] += 1
        if 0 < area_sqm < 10:
            suspicious_counts["area_sqm_lt_10"] += 1
        if area_sqm > 1000:
            suspicious_counts["area_sqm_gt_1000"] += 1

    worst_cases = []
    sorted_predictions = sorted(predictions, key=lambda row: row.get("ape", 0.0), reverse=True)
    for row in sorted_predictions[:case_limit]:
        feature = by_item_id.get(str(row.get("item_id")), {})
        worst_cases.append(
            {
                "item_id": row.get("item_id"),
                "month": row.get("month"),
                "partition": row.get("partition"),
                "strategy": row.get("strategy"),
                "coordinate_strategy": row.get("coordinate_strategy"),
                "actual_price": row.get("actual_price"),
                "predicted_price": row.get("predicted_price"),
                "ape_pct": round(float(row.get("ape") or 0.0) * 100, 4),
                "bias_pct": round(float(row.get("bias") or 0.0) * 100, 4),
                "confidence": row.get("confidence"),
                "valuation_mode": row.get("valuation_mode"),
                "temporal_reference_mode": row.get("temporal_reference_mode"),
                "future_dated_comparable_count_excluded": row.get("future_dated_comparable_count_excluded"),
                "risk_validation_state": (
                    "invalid"
                    if row.get("risk_invalid_field_count")
                    else "ok"
                    if row.get("risk_validation_ok")
                    else "incomplete"
                ),
                "housing_type": feature.get("housing_type"),
                "community_name": feature.get("community_name"),
                "business_area": feature.get("business_area"),
                "area_sqm": feature.get("area_sqm"),
                "actual_unit_price": round(float(feature.get("actual_unit_price") or 0.0), 2),
            }
        )

    return {
        "housing_type_counts": dict(sorted(housing_type_counts.items(), key=lambda item: item[1], reverse=True)),
        "suspicious_record_counts": suspicious_counts,
        "worst_cases": worst_cases,
    }


def generate_report(config: BacktestConfig) -> dict[str, Any]:
    normalized_records = _normalize_feature_records(config.data_root)
    predictions = run_time_split_backtest(normalized_records, config)
    historical_predictions = [row for row in predictions if str(row.get("valuation_mode") or "") == "historical_strict"]
    valuation_mode_sample_counts: Dict[str, int] = defaultdict(int)
    for row in predictions:
        valuation_mode_sample_counts[str(row.get("valuation_mode") or "unknown")] += 1

    months = [row["month"] for row in normalized_records]
    report: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_summary": {
            "normalized_record_count": len(normalized_records),
            "backtest_sample_count": len(historical_predictions),
            "valuation_mode_sample_counts": dict(sorted(valuation_mode_sample_counts.items())),
            "min_train_months": config.min_train_months,
            "month_range": {
                "start": min(months) if months else None,
                "end": max(months) if months else None,
            },
            "max_candidates_per_subject": config.max_candidates_per_subject,
        },
        "metrics": compute_metrics(predictions),
        "diagnostics": build_diagnostics(normalized_records, predictions, config.diagnostic_case_limit),
    }

    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


__all__ = (
    "build_diagnostics",
    "generate_report",
)
