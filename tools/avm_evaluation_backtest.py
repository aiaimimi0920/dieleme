"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_evaluation_context import *


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


__all__ = (
    "_append_index",
    "_extend_candidates",
    "_build_candidate_pool",
    "run_time_split_backtest",
)
