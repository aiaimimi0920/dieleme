#!/usr/bin/env python3
"""AVM 多维主链时间切分回测与评估报告生成工具。"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from src.avm.canonical_mapper import map_raw_to_canonical
from src.avm.feature_builder import build_features
from src.avm.engine import predict_fair_price
from src.avm.quality import price_plausibility
from src.avm.risk_schema import RISK_FEATURE_RULES, validate_risk_features
from tools.avm_data_loader import load_analysis_ready_rows, load_raw_record_rows

RISK_DIAGNOSTIC_FLAGS = [
    "is_occupied",
    "has_long_lease",
    "property_fee_owed",
    "is_restricted_purchase",
    "is_fractional_share",
]


@dataclass
class BacktestConfig:
    data_root: Path
    report_path: Path
    min_train_months: int = 6
    max_candidates_per_subject: int = 320
    diagnostic_case_limit: int = 30


def _load_raw_archive_records(data_root: Path) -> List[dict[str, Any]]:
    rows = load_analysis_ready_rows(data_root, prefer_db=True)
    if rows:
        return rows
    return load_raw_record_rows(data_root, prefer_db=True)


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _actual_total_price(feature: dict[str, Any]) -> float | None:
    actual_paid = feature.get("actual_paid_price")
    if isinstance(actual_paid, (int, float)) and actual_paid > 0:
        return float(actual_paid)
    transaction_price = feature.get("transaction_price")
    if isinstance(transaction_price, (int, float)) and transaction_price > 0:
        return float(transaction_price)
    return None


def _actual_unit_price(feature: dict[str, Any]) -> float | None:
    total_price = _actual_total_price(feature)
    area = feature.get("area_sqm")
    if not isinstance(total_price, (int, float)):
        return None
    if not isinstance(area, (int, float)) or area <= 0:
        return None
    return float(total_price) / float(area)


def _feature_month(feature: dict[str, Any]) -> str | None:
    raw = feature.get("auction_date")
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(str(raw), fmt)
            return f"{dt.year:04d}-{dt.month:02d}"
        except ValueError:
            continue
    return None


def _has_valid_coordinates(feature: dict[str, Any]) -> bool:
    lat = feature.get("latitude")
    lon = feature.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    return 3.0 <= float(lat) <= 54.5 and 73.0 <= float(lon) <= 136.0


def _derive_coordinate_strategy(feature: dict[str, Any]) -> str:
    if _has_valid_coordinates(feature):
        return "observed"
    community = _normalized_group_value(feature.get("community_name"))
    business = _normalized_group_value(feature.get("business_area"))
    district = _normalized_group_value(feature.get("district"))
    city = _normalized_group_value(feature.get("city"))
    if community:
        return "community_centroid"
    if city and district and business:
        return "business_area_centroid"
    if city and district:
        return "district_centroid"
    if city:
        return "city_centroid"
    return "missing"


def _coordinate_group_keys(feature: dict[str, Any]) -> list[tuple[str, str]]:
    community = _normalized_group_value(feature.get("community_name"))
    business = _normalized_group_value(feature.get("business_area"))
    district = _normalized_group_value(feature.get("district"))
    city = _normalized_group_value(feature.get("city"))

    keys: list[tuple[str, str]] = []
    if community:
        keys.append(("community_centroid", f"community::{community}"))
    if city and district and business:
        keys.append(("business_area_centroid", f"business::{city}::{district}::{business}"))
    if city and district:
        keys.append(("district_centroid", f"district::{city}::{district}"))
    if city:
        keys.append(("city_centroid", f"city::{city}"))
    return keys


def _build_coordinate_centroids(records: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    aggregates: dict[str, list[float]] = {}
    for record in records:
        if not _has_valid_coordinates(record):
            continue
        lat = float(record["latitude"])
        lon = float(record["longitude"])
        for _, key in _coordinate_group_keys(record):
            bucket = aggregates.setdefault(key, [0.0, 0.0, 0.0])
            bucket[0] += lat
            bucket[1] += lon
            bucket[2] += 1.0

    centroids: dict[str, tuple[float, float]] = {}
    for key, (lat_sum, lon_sum, count) in aggregates.items():
        if count <= 0:
            continue
        centroids[key] = (round(lat_sum / count, 6), round(lon_sum / count, 6))
    return centroids


def _enrich_coordinates(record: dict[str, Any], centroids: dict[str, tuple[float, float]]) -> dict[str, Any]:
    enriched = dict(record)
    if _has_valid_coordinates(enriched):
        enriched["coordinate_strategy"] = "observed"
        return enriched

    for strategy, key in _coordinate_group_keys(enriched):
        centroid = centroids.get(key)
        if centroid is None:
            continue
        enriched["latitude"], enriched["longitude"] = centroid
        enriched["coordinate_strategy"] = strategy
        return enriched

    enriched["coordinate_strategy"] = "missing"
    return enriched


def _enrich_coordinate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    centroids = _build_coordinate_centroids(records)
    return [_enrich_coordinates(record, centroids) for record in records]


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


def _append_index(index: Dict[str, Deque[dict[str, Any]]], key: str, record: dict[str, Any], maxlen: int) -> None:
    if not key:
        return
    bucket = index.setdefault(key, deque(maxlen=maxlen))
    bucket.append(record)


def _extend_candidates(target: Dict[str, dict[str, Any]], records: Iterable[dict[str, Any]]) -> None:
    for record in records:
        target[str(record.get("item_id"))] = record


def _build_candidate_pool(
    subject: dict[str, Any],
    indices: Dict[str, Dict[str, Deque[dict[str, Any]]]],
    global_recent: Deque[dict[str, Any]],
    limit: int,
) -> List[dict[str, Any]]:
    candidates: Dict[str, dict[str, Any]] = {}

    community = _normalized_group_value(subject.get("community_name"))
    business = _normalized_group_value(subject.get("business_area"))
    district = _normalized_group_value(subject.get("district"))
    city = _normalized_group_value(subject.get("city"))

    if community:
        _extend_candidates(candidates, indices["community"].get(community, []))
    if city and district and business:
        _extend_candidates(candidates, indices["business"].get(f"{city}::{district}::{business}", []))
    if city and district:
        _extend_candidates(candidates, indices["district"].get(f"{city}::{district}", []))
    if city:
        _extend_candidates(candidates, indices["city"].get(city, []))
    _extend_candidates(candidates, global_recent)

    ordered = list(candidates.values())
    ordered.sort(key=lambda row: row.get("auction_date") or "", reverse=True)
    return ordered[:limit]


def run_time_split_backtest(records: List[dict[str, Any]], config: BacktestConfig) -> List[dict[str, Any]]:
    records = _enrich_coordinate_records(records)
    months = sorted({row["month"] for row in records})
    if len(months) <= config.min_train_months:
        return []

    records_by_month: Dict[str, List[dict[str, Any]]] = defaultdict(list)
    for row in records:
        records_by_month[row["month"]].append(row)

    indices: Dict[str, Dict[str, Deque[dict[str, Any]]]] = {
        "community": {},
        "business": {},
        "district": {},
        "city": {},
    }
    global_recent: Deque[dict[str, Any]] = deque(maxlen=config.max_candidates_per_subject)
    predictions: List[dict[str, Any]] = []

    for idx, month in enumerate(months):
        month_records = records_by_month[month]
        if idx < config.min_train_months:
            for row in month_records:
                community = _normalized_group_value(row.get("community_name"))
                business = _normalized_group_value(row.get("business_area"))
                district = _normalized_group_value(row.get("district"))
                city = _normalized_group_value(row.get("city"))
                _append_index(indices["community"], community, row, 120)
                _append_index(indices["business"], f"{city}::{district}::{business}", row, 160)
                _append_index(indices["district"], f"{city}::{district}", row, 220)
                _append_index(indices["city"], city, row, 260)
                global_recent.append(row)
            continue

        for row in month_records:
            candidates = _build_candidate_pool(row, indices, global_recent, config.max_candidates_per_subject)
            if not candidates:
                continue

            for valuation_mode, strict_cutoff in (("historical_strict", True), ("current_market", False)):
                subject = dict(row)
                subject["valuation_mode"] = valuation_mode
                subject["strict_temporal_cutoff"] = strict_cutoff
                prediction = predict_fair_price(subject, candidates)
                predicted_price = prediction.get("predicted_price")
                if not isinstance(predicted_price, (int, float)) or predicted_price <= 0:
                    continue

                actual_price = float(row["actual_price"])
                ape = abs(predicted_price - actual_price) / actual_price
                bias = (predicted_price - actual_price) / actual_price
                predictions.append(
                    {
                        "month": month,
                        "item_id": str(row.get("item_id")),
                        "partition": row["partition"],
                        "city": row.get("city"),
                        "strategy": prediction.get("strategy"),
                        "coordinate_strategy": str(row.get("coordinate_strategy") or "missing"),
                        "valuation_mode": prediction.get("trace", {}).get("valuation_mode"),
                        "temporal_reference_mode": prediction.get("trace", {}).get("temporal_reference_mode"),
                        "future_dated_comparable_count_excluded": int(prediction.get("trace", {}).get("future_dated_comparable_count_excluded") or 0),
                        "actual_price": actual_price,
                        "predicted_price": float(predicted_price),
                        "ape": float(ape),
                        "bias": float(bias),
                        "confidence": float(prediction.get("confidence") or 0.0),
                        "risk_validation_ok": bool(row.get("risk_validation_ok")),
                        "risk_missing_required_count": int(row.get("risk_missing_required_count") or 0),
                        "risk_invalid_field_count": int(row.get("risk_invalid_field_count") or 0),
                        **{flag: bool(row.get(flag) is True) for flag in RISK_DIAGNOSTIC_FLAGS},
                    }
                )

        for row in month_records:
            community = _normalized_group_value(row.get("community_name"))
            business = _normalized_group_value(row.get("business_area"))
            district = _normalized_group_value(row.get("district"))
            city = _normalized_group_value(row.get("city"))
            _append_index(indices["community"], community, row, 120)
            _append_index(indices["business"], f"{city}::{district}::{business}", row, 160)
            _append_index(indices["district"], f"{city}::{district}", row, 220)
            _append_index(indices["city"], city, row, 260)
            global_recent.append(row)

    return predictions


def _quantiles(values: np.ndarray) -> dict[str, float]:
    if values.size == 0:
        return {}
    return {
        "p25": float(np.quantile(values, 0.25) * 100),
        "p50": float(np.quantile(values, 0.50) * 100),
        "p75": float(np.quantile(values, 0.75) * 100),
        "p90": float(np.quantile(values, 0.90) * 100),
    }


def _group_metric_rows(predictions: List[dict[str, Any]], key_getter) -> List[dict[str, Any]]:
    grouped: Dict[str, List[dict[str, Any]]] = defaultdict(list)
    for row in predictions:
        grouped[str(key_getter(row) or "unknown")].append(row)

    rows: List[dict[str, Any]] = []
    for key, items in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True):
        ape = np.array([item["ape"] for item in items], dtype=float)
        bias = np.array([item["bias"] for item in items], dtype=float)
        rows.append(
            {
                "group": key,
                "sample_count": len(items),
                "mape_pct": float(np.mean(ape) * 100),
                "mdape_pct": float(np.median(ape) * 100),
                "p50_ape_pct": float(np.quantile(ape, 0.50) * 100),
                "p90_ape_pct": float(np.quantile(ape, 0.90) * 100),
                "mean_bias_pct": float(np.mean(bias) * 100),
                "error_quantiles_pct": _quantiles(ape),
            }
        )
    return rows


def compute_metrics(predictions: List[dict[str, Any]]) -> dict[str, Any]:
    if not predictions:
        return {}

    primary_predictions = [row for row in predictions if str(row.get("valuation_mode") or "") == "historical_strict"] or predictions

    ape_arr = np.array([row["ape"] for row in primary_predictions], dtype=float)
    bias_arr = np.array([row["bias"] for row in primary_predictions], dtype=float)

    partitions: Dict[str, List[dict[str, Any]]] = defaultdict(list)
    strategy_counts: Dict[str, int] = defaultdict(int)
    coordinate_strategy_counts: Dict[str, int] = defaultdict(int)
    valuation_mode_counts: Dict[str, int] = defaultdict(int)
    temporal_reference_mode_counts: Dict[str, int] = defaultdict(int)
    historical_temporal_reference_mode_counts: Dict[str, int] = defaultdict(int)
    risk_validation_counts: Dict[str, int] = defaultdict(int)
    future_excluded_total = 0
    for row in predictions:
        if row in primary_predictions:
            partitions[row["partition"]].append(row)
        strategy_counts[str(row.get("strategy") or "unknown")] += 1
        coordinate_strategy_counts[str(row.get("coordinate_strategy") or "unknown")] += 1
        valuation_mode_counts[str(row.get("valuation_mode") or "unknown")] += 1
        temporal_reference_mode_counts[str(row.get("temporal_reference_mode") or "unknown")] += 1
        if str(row.get("valuation_mode") or "") == "historical_strict":
            historical_temporal_reference_mode_counts[str(row.get("temporal_reference_mode") or "unknown")] += 1
        if row.get("risk_invalid_field_count"):
            risk_validation_counts["invalid"] += 1
        elif row.get("risk_validation_ok"):
            risk_validation_counts["ok"] += 1
        else:
            risk_validation_counts["incomplete"] += 1
        future_excluded_total += int(row.get("future_dated_comparable_count_excluded") or 0)

    partition_stats = []
    for partition, rows in sorted(partitions.items(), key=lambda item: len(item[1]), reverse=True):
        arr = np.array([row["ape"] for row in rows], dtype=float)
        bias = np.array([row["bias"] for row in rows], dtype=float)
        partition_stats.append(
            {
                "partition": partition,
                "sample_count": len(rows),
                "mape_pct": float(np.mean(arr) * 100),
                "mdape_pct": float(np.median(arr) * 100),
                "mean_bias_pct": float(np.mean(bias) * 100),
                "error_quantiles_pct": _quantiles(arr),
            }
        )

    strategy_metrics = _group_metric_rows(primary_predictions, lambda row: row.get("strategy"))
    coordinate_strategy_metrics = _group_metric_rows(primary_predictions, lambda row: row.get("coordinate_strategy"))
    risk_validation_metrics = _group_metric_rows(
        primary_predictions,
        lambda row: (
            "invalid"
            if row.get("risk_invalid_field_count")
            else "ok"
            if row.get("risk_validation_ok")
            else "incomplete"
        ),
    )
    valuation_mode_metrics = _group_metric_rows(predictions, lambda row: row.get("valuation_mode"))
    risk_flag_metrics = [
        {
            "group": flag,
            **metric,
        }
        for flag in RISK_DIAGNOSTIC_FLAGS
        for metric in (_group_metric_rows([row for row in primary_predictions if row.get(flag)], lambda _row, f=flag: f) or [])
    ]

    return {
        "mape_pct": float(np.mean(ape_arr) * 100),
        "mdape_pct": float(np.median(ape_arr) * 100),
        "p50_ape_pct": float(np.quantile(ape_arr, 0.50) * 100),
        "p90_ape_pct": float(np.quantile(ape_arr, 0.90) * 100),
        "overall_error_quantiles_pct": _quantiles(ape_arr),
        "mean_bias_pct": float(np.mean(bias_arr) * 100),
        "max_abs_partition_bias_pct": float(max(abs(item["mean_bias_pct"]) for item in partition_stats)),
        "strategy_counts": dict(sorted(strategy_counts.items())),
        "coordinate_strategy_counts": dict(sorted(coordinate_strategy_counts.items())),
        "valuation_mode_counts": dict(sorted(valuation_mode_counts.items())),
        "temporal_reference_mode_counts": dict(sorted(temporal_reference_mode_counts.items())),
        "historical_temporal_reference_mode_counts": dict(sorted(historical_temporal_reference_mode_counts.items())),
        "risk_validation_counts": dict(sorted(risk_validation_counts.items())),
        "future_dated_comparable_exclusion_total": int(future_excluded_total),
        "strategy_metrics": strategy_metrics,
        "coordinate_strategy_metrics": coordinate_strategy_metrics,
        "risk_validation_metrics": risk_validation_metrics,
        "valuation_mode_metrics": valuation_mode_metrics,
        "risk_flag_metrics": risk_flag_metrics,
        "partition_error_quantiles": partition_stats,
    }


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


def parse_args() -> BacktestConfig:
    parser = argparse.ArgumentParser(description="AVM 多维主链时间切分回测评估")
    parser.add_argument("--data-root", type=Path, default=Path("datas"), help="数据根目录，默认 datas")
    parser.add_argument("--report-path", type=Path, default=Path("datas/avm/eval_report.json"), help="输出评估报告路径")
    parser.add_argument("--min-train-months", type=int, default=6, help="最少训练月份数")
    parser.add_argument("--max-candidates-per-subject", type=int, default=320, help="每个样本最多使用的训练候选数")
    parser.add_argument("--diagnostic-case-limit", type=int, default=30, help="评估报告中保留的最差样本数量")
    args = parser.parse_args()
    return BacktestConfig(
        data_root=args.data_root,
        report_path=args.report_path,
        min_train_months=args.min_train_months,
        max_candidates_per_subject=args.max_candidates_per_subject,
        diagnostic_case_limit=args.diagnostic_case_limit,
    )


def main() -> None:
    config = parse_args()
    report = generate_report(config)
    print(f"[INFO] Backtest samples: {report['data_summary']['backtest_sample_count']}")
    metrics = report.get("metrics", {})
    if metrics:
        print(f"[INFO] MAPE: {metrics['mape_pct']:.2f}%")
        print(f"[INFO] MdAPE: {metrics['mdape_pct']:.2f}%")
        print(f"[INFO] P50 APE: {metrics['p50_ape_pct']:.2f}%")
        print(f"[INFO] P90 APE: {metrics['p90_ape_pct']:.2f}%")
    print(f"[INFO] Report generated: {config.report_path}")


if __name__ == "__main__":
    main()
