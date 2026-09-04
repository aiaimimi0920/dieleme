"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_evaluation_context import *


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


__all__ = (
    "_quantiles",
    "_group_metric_rows",
    "compute_metrics",
)
