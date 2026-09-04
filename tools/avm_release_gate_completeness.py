"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_release_gate_context import *


def _load_recent_raw_records(data_root: Path, window_days: int) -> List[dict[str, Any]]:
    recent_rows = load_recent_analysis_ready_rows(data_root, window_days, prefer_db=True)
    if recent_rows:
        return recent_rows
    analysis_ready_rows = load_analysis_ready_rows(data_root, prefer_db=True)
    if analysis_ready_rows:
        return analysis_ready_rows
    return load_raw_record_rows(data_root, prefer_db=True)


def _load_recent_canonical_records(data_root: Path, window_days: int) -> List[dict[str, Any]]:
    raw_records = _load_recent_raw_records(data_root, window_days)

    canonical_records: List[dict[str, Any]] = []
    for row in raw_records:
        try:
            canonical = map_raw_to_canonical(row)
        except Exception:
            continue
        canonical_records.append(canonical)

    dated_records = []
    for row in canonical_records:
        raw = row.get("auction_date")
        if not raw:
            continue
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(str(raw), fmt)
                dated_records.append((dt, row))
                break
            except ValueError:
                continue

    if not dated_records:
        return []

    max_date = max(dt for dt, _ in dated_records)
    recent_start = max_date - timedelta(days=window_days - 1)
    return [row for dt, row in dated_records if dt >= recent_start]


def _field_non_null_rate(records: List[dict[str, Any]], field: str) -> float:
    if not records:
        return 0.0
    good = 0
    for row in records:
        value = row.get(field)
        if value in (None, "", "UNK"):
            continue
        if field == "housing_type" and value == "其他":
            continue
        good += 1
    return good / len(records)


def _joint_non_null_rate(records: List[dict[str, Any]], fields: List[str]) -> float:
    if not records:
        return 0.0
    good = 0
    for row in records:
        passed = True
        for field in fields:
            value = row.get(field)
            if value in (None, "", "UNK"):
                passed = False
                break
            if field == "housing_type" and value == "其他":
                passed = False
                break
        if passed:
            good += 1
    return good / len(records)


def _coordinate_strategy_ready_rate(records: List[dict[str, Any]]) -> float:
    if not records:
        return 0.0
    ready = 0
    for row in records:
        lat = row.get("latitude")
        lon = row.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            ready += 1
            continue
        community = row.get("community_name")
        business_area = row.get("business_area")
        district = row.get("district")
        city = row.get("city")
        if community not in (None, "", "UNK"):
            ready += 1
        elif city not in (None, "", "UNK") and district not in (None, "", "UNK") and business_area not in (None, "", "UNK"):
            ready += 1
        elif city not in (None, "", "UNK") and district not in (None, "", "UNK"):
            ready += 1
        elif city not in (None, "", "UNK"):
            ready += 1
    return ready / len(records)


def build_completeness_report(records: List[dict[str, Any]], thresholds: GateThresholds, min_sample_size: int) -> dict[str, Any]:
    valuation_fields = {
        field: round(_field_non_null_rate(records, field), 4)
        for field in VALUATION_CORE_FIELDS
    }
    risk_fields = {
        field: round(_field_non_null_rate(records, field), 4)
        for field in RISK_CORE_FIELDS
    }
    valuation_joint = round(_joint_non_null_rate(records, VALUATION_CORE_FIELDS), 4)
    risk_joint = round(_joint_non_null_rate(records, RISK_CORE_FIELDS), 4)
    coordinate_strategy_ready_rate = round(_coordinate_strategy_ready_rate(records), 4)

    valuation_pass = (
        len(records) >= min_sample_size
        and all(rate >= thresholds.valuation_field_min for rate in valuation_fields.values())
        and valuation_joint >= thresholds.valuation_joint_min
    )
    risk_pass = (
        len(records) >= min_sample_size
        and all(rate >= thresholds.risk_field_min for rate in risk_fields.values())
        and risk_joint >= thresholds.risk_joint_min
    )

    return {
        "sample_size": len(records),
        "min_sample_size": min_sample_size,
        "valuation_fields": valuation_fields,
        "valuation_joint_rate": valuation_joint,
        "coordinate_strategy_ready_rate": coordinate_strategy_ready_rate,
        "risk_fields": risk_fields,
        "risk_joint_rate": risk_joint,
        "valuation_pass": valuation_pass,
        "risk_pass": risk_pass,
        "pass": valuation_pass and risk_pass,
    }


__all__ = (
    "_load_recent_raw_records",
    "_load_recent_canonical_records",
    "_field_non_null_rate",
    "_joint_non_null_rate",
    "_coordinate_strategy_ready_rate",
    "build_completeness_report",
)
