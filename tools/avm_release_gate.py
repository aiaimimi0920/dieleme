#!/usr/bin/env python3
"""AVM 发布门禁预检：字段完整率、离线误差、接口 smoke、漂移告警。"""

from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.avm.canonical_mapper import map_raw_to_canonical
from src.avm.service import AVMService
from src.storage.repository import create_repository_from_env
from tools.analysis_stage_planner import (
    load_action_effectiveness_snapshot,
    load_manual_review_receipt_snapshot,
    load_optimization_loop_progress_snapshot,
    recommend_analysis_stage_actions,
    summarize_action_effectiveness_snapshot,
    summarize_manual_review_backlog,
    summarize_manual_review_reentry_application_summary,
    summarize_manual_review_receipt_snapshot,
    summarize_operator_action_surface,
    summarize_operator_overview,
    summarize_recoverability_snapshot,
    summarize_scheduler_feedback_snapshot,
)
from tools.audit_recent_avm_gaps import build_recent_gap_audit
from tools.avm_data_loader import (
    load_recent_analysis_ready_rows,
    load_analysis_ready_rows,
    load_raw_record_rows,
    load_sample_analysis_ready_rows,
)
from tools.check_feature_drift import generate_drift_report
from tools.evaluate_avm import BacktestConfig, generate_report as generate_eval_report
from tools.apply_avm_calibration_patch import normalize_calibration_targets_payload
from tools.suggest_avm_calibration_targets import suggest_calibration_targets
from tools.manual_review_receipt_jobs import (
    load_manual_review_receipt_jobs,
    summarize_manual_review_receipt_jobs_snapshot,
)
from tools.manual_review_receipt_audit import (
    load_manual_review_receipt_operations,
    summarize_manual_review_receipt_operations_snapshot,
)
from tools.backfill_manual_review_control_plane_to_db import (
    describe_manual_review_control_plane_backup,
    describe_manual_review_control_plane_storage,
    load_manual_review_control_plane_backup_repairs,
    load_manual_review_control_plane_integrity_history,
    record_manual_review_control_plane_integrity,
    summarize_manual_review_control_plane_guidance,
    summarize_manual_review_control_plane_integrity,
    summarize_manual_review_control_plane_backup_repairs,
    summarize_manual_review_control_plane_integrity_history,
    summarize_manual_review_control_plane_stability,
)
import src.server as server_module


VALUATION_CORE_FIELDS = [
    "item_id",
    "auction_date",
    "latitude",
    "longitude",
    "transaction_price",
    "area_sqm",
    "housing_type",
]

RISK_CORE_FIELDS = [
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "tax_burden",
    "is_fractional_share",
]


@dataclass
class GateThresholds:
    valuation_field_min: float = 0.99
    valuation_joint_min: float = 0.97
    risk_field_min: float = 0.95
    risk_joint_min: float = 0.92
    max_mape_pct: float = 12.0
    max_p50_ape_pct: float = 8.0
    max_p90_ape_pct: float = 25.0
    max_abs_partition_bias_pct: float = 10.0
    max_smoke_error_rate: float = 0.001
    max_smoke_p95_ms: float = 800.0
    max_smoke_p99_ms: float = 1500.0
    drift_alert_budget: int = 0
    min_historical_strict_ratio: float = 0.95
    max_risk_invalid_ratio: float = 0.0
    max_historical_current_time_ratio: float = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AVM 发布门禁预检")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--min-sample-size", type=int, default=1000)
    parser.add_argument("--smoke-sample-size", type=int, default=8)
    parser.add_argument("--eval-report-path", type=Path, default=Path("datas/avm/eval_report.json"))
    parser.add_argument("--gate-report-path", type=Path, default=Path("datas/avm/release_gate.json"))
    parser.add_argument("--reuse-eval-report", action="store_true", help="复用已存在的评估报告")
    parser.add_argument("--reuse-drift-report", action="store_true", help="复用已存在的漂移报告")
    return parser.parse_args()


def _parse_date_from_filename(path: Path) -> datetime | None:
    try:
        return datetime.strptime(path.stem, "%Y-%m-%d")
    except ValueError:
        return None


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


def build_eval_gate(metrics: dict[str, Any], thresholds: GateThresholds) -> dict[str, Any]:
    if not metrics:
        return {"pass": False, "reason": "missing_metrics"}

    valuation_mode_counts = metrics.get("valuation_mode_counts", {}) or {}
    risk_validation_counts = metrics.get("risk_validation_counts", {}) or {}
    temporal_reference_mode_counts = metrics.get("temporal_reference_mode_counts", {}) or {}
    historical_temporal_reference_mode_counts = metrics.get("historical_temporal_reference_mode_counts", {}) or {}
    strategy_metrics = metrics.get("strategy_metrics", []) or []
    coordinate_strategy_metrics = metrics.get("coordinate_strategy_metrics", []) or []
    risk_validation_metrics = metrics.get("risk_validation_metrics", []) or []
    valuation_mode_metrics = metrics.get("valuation_mode_metrics", []) or []
    risk_flag_metrics = metrics.get("risk_flag_metrics", []) or []
    calibration_targets = normalize_calibration_targets_payload(suggest_calibration_targets(metrics))

    historical_strict_count = int(valuation_mode_counts.get("historical_strict") or 0)
    current_market_count = int(valuation_mode_counts.get("current_market") or 0)
    historical_ratio = 1.0 if historical_strict_count > 0 else 0.0
    historical_strict_primary = historical_strict_count > 0 and historical_strict_count >= current_market_count

    risk_validation_total = max(sum(int(v) for v in risk_validation_counts.values()), 0)
    risk_invalid_count = int(risk_validation_counts.get("invalid") or 0)
    risk_invalid_ratio = 0.0 if risk_validation_total <= 0 else risk_invalid_count / risk_validation_total
    risk_validation_invalid_pass = risk_invalid_ratio <= thresholds.max_risk_invalid_ratio

    historical_current_time_count = int(historical_temporal_reference_mode_counts.get("current_time") or 0)
    historical_current_time_ratio = 0.0 if historical_strict_count <= 0 else historical_current_time_count / historical_strict_count
    historical_temporal_reference_pass = historical_current_time_ratio <= thresholds.max_historical_current_time_ratio

    top_strategy_group = None
    if strategy_metrics:
        top_strategy_group = max(strategy_metrics, key=lambda row: float(row.get("mape_pct") or 0.0)).get("group")
    top_coordinate_strategy_group = None
    if coordinate_strategy_metrics:
        top_coordinate_strategy_group = max(coordinate_strategy_metrics, key=lambda row: float(row.get("mape_pct") or 0.0)).get("group")
    top_risk_validation_group = None
    if risk_validation_metrics:
        top_risk_validation_group = max(risk_validation_metrics, key=lambda row: float(row.get("mape_pct") or 0.0)).get("group")

    valuation_mode_mape_gap_pct = 0.0
    valuation_mode_gap_warning = False
    valuation_mode_metric_map = {
        str(row.get("group")): row
        for row in valuation_mode_metrics
        if isinstance(row, dict)
    }
    historical_metric = valuation_mode_metric_map.get("historical_strict")
    current_metric = valuation_mode_metric_map.get("current_market")
    if historical_metric and current_metric:
        valuation_mode_mape_gap_pct = round(
            abs(float(current_metric.get("mape_pct") or 0.0) - float(historical_metric.get("mape_pct") or 0.0)),
            4,
        )
        valuation_mode_gap_warning = valuation_mode_mape_gap_pct > thresholds.max_mape_pct / 2

    strategy_watchlist = [
        str(row.get("group"))
        for row in strategy_metrics
        if int(row.get("sample_count") or 0) >= 3
        and (
            float(row.get("mape_pct") or 0.0) > thresholds.max_mape_pct
            or float(row.get("p90_ape_pct") or 0.0) > thresholds.max_p90_ape_pct
        )
    ]
    coordinate_strategy_watchlist = [
        str(row.get("group"))
        for row in coordinate_strategy_metrics
        if int(row.get("sample_count") or 0) >= 1
        and (
            float(row.get("mape_pct") or 0.0) > thresholds.max_mape_pct
            or float(row.get("p90_ape_pct") or 0.0) > thresholds.max_p90_ape_pct
        )
    ]
    risk_validation_watchlist = [
        str(row.get("group"))
        for row in risk_validation_metrics
        if int(row.get("sample_count") or 0) >= 1
        and (
            float(row.get("mape_pct") or 0.0) > thresholds.max_mape_pct
            or float(row.get("p90_ape_pct") or 0.0) > thresholds.max_p90_ape_pct
        )
    ]

    return {
        "mape_pct": metrics.get("mape_pct"),
        "p50_ape_pct": metrics.get("p50_ape_pct"),
        "p90_ape_pct": metrics.get("p90_ape_pct"),
        "max_abs_partition_bias_pct": metrics.get("max_abs_partition_bias_pct"),
        "valuation_mode_counts": valuation_mode_counts,
        "valuation_mode_metrics": valuation_mode_metrics,
        "temporal_reference_mode_counts": temporal_reference_mode_counts,
        "historical_temporal_reference_mode_counts": historical_temporal_reference_mode_counts,
        "risk_validation_counts": risk_validation_counts,
        "future_dated_comparable_exclusion_total": metrics.get("future_dated_comparable_exclusion_total", 0),
        "strategy_metrics": strategy_metrics,
        "coordinate_strategy_metrics": coordinate_strategy_metrics,
        "risk_validation_metrics": risk_validation_metrics,
        "risk_flag_metrics": risk_flag_metrics,
        "calibration_targets": calibration_targets,
        "top_strategy_group": top_strategy_group,
        "top_coordinate_strategy_group": top_coordinate_strategy_group,
        "top_risk_validation_group": top_risk_validation_group,
        "valuation_mode_mape_gap_pct": valuation_mode_mape_gap_pct,
        "valuation_mode_gap_warning": valuation_mode_gap_warning,
        "strategy_watchlist": strategy_watchlist,
        "coordinate_strategy_watchlist": coordinate_strategy_watchlist,
        "risk_validation_watchlist": risk_validation_watchlist,
        "historical_strict_ratio": round(historical_ratio, 4),
        "historical_strict_primary": historical_strict_primary,
        "historical_current_time_ratio": round(historical_current_time_ratio, 4),
        "historical_temporal_reference_pass": historical_temporal_reference_pass,
        "risk_validation_invalid_ratio": round(risk_invalid_ratio, 4),
        "risk_validation_invalid_pass": risk_validation_invalid_pass,
        "pass": (
            float(metrics.get("mape_pct") or 9999) <= thresholds.max_mape_pct
            and float(metrics.get("p50_ape_pct") or 9999) <= thresholds.max_p50_ape_pct
            and float(metrics.get("p90_ape_pct") or 9999) <= thresholds.max_p90_ape_pct
            and float(metrics.get("max_abs_partition_bias_pct") or 9999) <= thresholds.max_abs_partition_bias_pct
            and historical_strict_primary
            and historical_temporal_reference_pass
            and risk_validation_invalid_pass
        ),
    }


def _find_sample_records(data_root: Path, limit: int) -> List[dict[str, Any]]:
    return load_sample_analysis_ready_rows(data_root, limit, prefer_db=True)


def _load_manual_review_receipt_snapshot_for_gate(data_root: Path, repo) -> dict[str, Any]:
    receipt_path = data_root / "avm" / "manual_review_receipts.json"
    try:
        return load_manual_review_receipt_snapshot(
            receipt_path,
            repository=repo if repo.enabled else None,
        )
    except TypeError:
        return load_manual_review_receipt_snapshot(receipt_path)


def _analysis_readiness_context(data_root: Path, window_days: int = 7) -> dict[str, Any]:
    repo = create_repository_from_env()
    action_effectiveness = load_action_effectiveness_snapshot()
    scheduler_progress = load_optimization_loop_progress_snapshot()
    action_effectiveness_summary = summarize_action_effectiveness_snapshot(action_effectiveness)
    scheduler_feedback_summary = summarize_scheduler_feedback_snapshot(scheduler_progress)
    recent_gap_report = build_recent_gap_audit(data_root, window_days, sample_limit=20)
    recoverability_summary = summarize_recoverability_snapshot(recent_gap_report)
    manual_review_backlog_summary = summarize_manual_review_backlog(recent_gap_report)
    manual_review_receipt_summary = summarize_manual_review_receipt_snapshot(
        _load_manual_review_receipt_snapshot_for_gate(data_root, repo),
        manual_review_backlog_summary,
    )
    default_manual_review_reentry_application_summary = summarize_manual_review_reentry_application_summary(
        manual_review_receipt_summary,
        {},
        recent_gap_report,
        recent_gap_report,
        {"analysis_blockers": {}},
        {"analysis_blockers": {}},
    )
    default_recommended_actions = recommend_analysis_stage_actions(
        {"analysis_blockers": {}},
        gap_report=recent_gap_report,
        action_effectiveness=action_effectiveness,
        manual_review_receipt_summary=manual_review_receipt_summary,
    )
    default_operator_action_summary = summarize_operator_action_surface(
        default_recommended_actions,
        action_effectiveness_summary,
        recoverability_summary,
    )
    default_operator_action_summary["manual_review_backlog_summary"] = manual_review_backlog_summary
    default_operator_action_summary["manual_review_receipt_summary"] = manual_review_receipt_summary
    default_operator_action_summary["manual_review_reentry_application_summary"] = default_manual_review_reentry_application_summary
    default_operator_overview = summarize_operator_overview(
        default_operator_action_summary,
        scheduler_feedback_summary,
    )
    manual_review_receipt_jobs_summary = summarize_manual_review_receipt_jobs_snapshot(
        load_manual_review_receipt_jobs(
            data_root / "avm" / "manual_review_receipt_jobs.json",
            repository=repo if repo.enabled else None,
        )
    )
    manual_review_receipt_operations_summary = summarize_manual_review_receipt_operations_snapshot(
        load_manual_review_receipt_operations(
            data_root / "avm" / "manual_review_receipt_operations.jsonl",
            limit=200,
            repository=repo if repo.enabled else None,
        )
    )
    manual_review_control_plane_storage = describe_manual_review_control_plane_storage(
        data_root,
        repository=repo if repo.enabled else None,
    )
    manual_review_control_plane_backup = describe_manual_review_control_plane_backup(
        data_root,
        repository=repo if repo.enabled else None,
    )
    manual_review_control_plane_backup_repairs_summary = summarize_manual_review_control_plane_backup_repairs(
        load_manual_review_control_plane_backup_repairs(data_root)
    )
    manual_review_control_plane_integrity = summarize_manual_review_control_plane_integrity(
        manual_review_control_plane_storage,
        manual_review_control_plane_backup,
        manual_review_control_plane_backup_repairs_summary,
    )
    record_manual_review_control_plane_integrity(data_root, manual_review_control_plane_integrity)
    manual_review_control_plane_integrity_history_summary = summarize_manual_review_control_plane_integrity_history(
        load_manual_review_control_plane_integrity_history(data_root)
    )
    manual_review_control_plane_stability = summarize_manual_review_control_plane_stability(
        manual_review_control_plane_integrity,
        manual_review_control_plane_integrity_history_summary,
    )
    manual_review_control_plane_guidance = summarize_manual_review_control_plane_guidance(
        manual_review_control_plane_integrity,
        manual_review_control_plane_stability,
        manual_review_control_plane_backup_repairs_summary,
    )
    if not repo.enabled or not hasattr(repo, "analysis_readiness_snapshot"):
        return {
            "ready": 0,
            "not_ready": 0,
            "invalid": 0,
            "blockers": {},
            "recommended_actions": default_recommended_actions,
            "action_effectiveness_summary": action_effectiveness_summary,
            "recoverability_summary": recoverability_summary,
            "manual_review_backlog_summary": manual_review_backlog_summary,
            "manual_review_receipt_summary": manual_review_receipt_summary,
            "manual_review_reentry_application_summary": default_manual_review_reentry_application_summary,
            "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
            "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
            "manual_review_control_plane_storage": manual_review_control_plane_storage,
            "manual_review_control_plane_backup": manual_review_control_plane_backup,
            "manual_review_control_plane_backup_repairs_summary": manual_review_control_plane_backup_repairs_summary,
            "manual_review_control_plane_integrity": manual_review_control_plane_integrity,
            "manual_review_control_plane_integrity_history_summary": manual_review_control_plane_integrity_history_summary,
            "manual_review_control_plane_stability": manual_review_control_plane_stability,
            "manual_review_control_plane_guidance": manual_review_control_plane_guidance,
            "scheduler_feedback_summary": scheduler_feedback_summary,
            "operator_action_summary": default_operator_action_summary,
            "operator_overview": default_operator_overview,
        }
    try:
        snapshot = repo.analysis_readiness_snapshot()
        snapshot["recommended_actions"] = recommend_analysis_stage_actions(
            {"analysis_blockers": snapshot.get("blockers", {})},
            gap_report=recent_gap_report,
            action_effectiveness=action_effectiveness,
            manual_review_receipt_summary=manual_review_receipt_summary,
        )
        snapshot["action_effectiveness_summary"] = action_effectiveness_summary
        snapshot["recoverability_summary"] = recoverability_summary
        snapshot["manual_review_backlog_summary"] = manual_review_backlog_summary
        snapshot["manual_review_receipt_summary"] = manual_review_receipt_summary
        snapshot["manual_review_receipt_jobs_summary"] = manual_review_receipt_jobs_summary
        snapshot["manual_review_receipt_operations_summary"] = manual_review_receipt_operations_summary
        snapshot["manual_review_control_plane_storage"] = manual_review_control_plane_storage
        snapshot["manual_review_control_plane_backup"] = manual_review_control_plane_backup
        snapshot["manual_review_control_plane_backup_repairs_summary"] = manual_review_control_plane_backup_repairs_summary
        snapshot["manual_review_control_plane_integrity"] = manual_review_control_plane_integrity
        snapshot["manual_review_control_plane_integrity_history_summary"] = manual_review_control_plane_integrity_history_summary
        snapshot["manual_review_control_plane_stability"] = manual_review_control_plane_stability
        snapshot["manual_review_control_plane_guidance"] = manual_review_control_plane_guidance
        snapshot["manual_review_reentry_application_summary"] = summarize_manual_review_reentry_application_summary(
            manual_review_receipt_summary,
            {},
            recent_gap_report,
            recent_gap_report,
            {"analysis_blockers": snapshot.get("blockers", {})},
            {"analysis_blockers": snapshot.get("blockers", {})},
        )
        snapshot["scheduler_feedback_summary"] = scheduler_feedback_summary
        snapshot["operator_action_summary"] = summarize_operator_action_surface(
            snapshot["recommended_actions"],
            action_effectiveness_summary,
            recoverability_summary,
        )
        snapshot["operator_action_summary"]["manual_review_backlog_summary"] = manual_review_backlog_summary
        snapshot["operator_action_summary"]["manual_review_receipt_summary"] = manual_review_receipt_summary
        snapshot["operator_action_summary"]["manual_review_reentry_application_summary"] = snapshot["manual_review_reentry_application_summary"]
        snapshot["operator_overview"] = summarize_operator_overview(
            snapshot["operator_action_summary"],
            scheduler_feedback_summary,
        )
        return snapshot
    except Exception:
        return {
            "ready": 0,
            "not_ready": 0,
            "invalid": 0,
            "blockers": {},
            "recommended_actions": default_recommended_actions,
            "action_effectiveness_summary": action_effectiveness_summary,
            "recoverability_summary": recoverability_summary,
            "manual_review_backlog_summary": manual_review_backlog_summary,
            "manual_review_receipt_summary": manual_review_receipt_summary,
            "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
            "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
            "manual_review_control_plane_storage": manual_review_control_plane_storage,
            "manual_review_control_plane_backup": manual_review_control_plane_backup,
            "manual_review_control_plane_backup_repairs_summary": manual_review_control_plane_backup_repairs_summary,
            "manual_review_control_plane_integrity": manual_review_control_plane_integrity,
            "manual_review_control_plane_integrity_history_summary": manual_review_control_plane_integrity_history_summary,
            "manual_review_control_plane_stability": manual_review_control_plane_stability,
            "manual_review_control_plane_guidance": manual_review_control_plane_guidance,
            "scheduler_feedback_summary": scheduler_feedback_summary,
            "operator_action_summary": default_operator_action_summary,
            "operator_overview": default_operator_overview,
        }


def _request_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any], float]:
    started = time.perf_counter()
    if method == "POST":
        req = urllib.request.Request(
            url,
            data=json.dumps(payload or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    else:
        req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        elapsed_ms = (time.perf_counter() - started) * 1000
        return resp.status, body, elapsed_ms


def run_api_smoke(data_root: Path, thresholds: GateThresholds, sample_size: int) -> dict[str, Any]:
    if sample_size <= 0:
        return {"request_count": 0, "error_count": 0, "error_rate": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "pass": True, "skipped": True}

    samples = _find_sample_records(data_root, limit=max(sample_size, 2))
    if not samples:
        return {"pass": False, "reason": "no_samples"}

    smoke_temp = tempfile.TemporaryDirectory()
    smoke_data_root = Path(smoke_temp.name) / "datas"
    smoke_data_root.mkdir(parents=True, exist_ok=True)
    (smoke_data_root / "smoke_samples.json").write_text(
        json.dumps(samples, ensure_ascii=False),
        encoding="utf-8",
    )

    original_service = server_module.AVM_SERVICE
    original_start = server_module.AVM_SERVICE_START_TIME
    server_module.AVM_SERVICE = AVMService(data_dir=str(smoke_data_root))
    server_module.AVM_SERVICE_START_TIME = time.time()

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    latencies: List[float] = []
    errors = 0
    try:
        for row in samples[:sample_size]:
            item_id = str(row.get("id") or row.get("item_id") or "")
            if not item_id:
                continue
            try:
                _, _, elapsed = _request_json(
                    f"http://127.0.0.1:{port}/api/avm/predict?id={urllib.parse.quote(item_id)}"
                )
                latencies.append(elapsed)
            except Exception:
                errors += 1

        try:
            subject = {
                "city": samples[0].get("城市"),
                "district": samples[0].get("区"),
                "community_name": samples[0].get("所属小区"),
                "area_sqm": 100,
                "housing_type": "住宅",
            }
            _, _, elapsed = _request_json(
                f"http://127.0.0.1:{port}/api/avm/evaluate",
                method="POST",
                payload={"request_id": "gate-smoke", "subject": subject, "auction": {"starting_price": 1000000}},
            )
            latencies.append(elapsed)
        except Exception:
            errors += 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_module.AVM_SERVICE = original_service
        server_module.AVM_SERVICE_START_TIME = original_start
        smoke_temp.cleanup()

    if not latencies:
        return {"pass": False, "reason": "no_successful_requests"}

    arr = np.array(latencies, dtype=float)
    error_rate = errors / max(len(latencies) + errors, 1)
    p95 = float(np.quantile(arr, 0.95))
    p99 = float(np.quantile(arr, 0.99))
    return {
        "request_count": len(latencies) + errors,
        "error_count": errors,
        "error_rate": round(error_rate, 6),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "pass": (
            error_rate <= thresholds.max_smoke_error_rate
            and p95 <= thresholds.max_smoke_p95_ms
            and p99 <= thresholds.max_smoke_p99_ms
        ),
    }


def generate_release_gate_report(
    data_root: Path,
    eval_report_path: Path,
    gate_report_path: Path,
    window_days: int = 7,
    min_sample_size: int = 1000,
    smoke_sample_size: int = 8,
    reuse_eval_report: bool = False,
    reuse_drift_report: bool = False,
    thresholds: GateThresholds | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or GateThresholds()

    recent_records = _load_recent_canonical_records(data_root, window_days)
    completeness = build_completeness_report(recent_records, thresholds, min_sample_size)

    if reuse_eval_report and eval_report_path.exists():
        eval_report = json.loads(eval_report_path.read_text(encoding="utf-8"))
    else:
        eval_report = generate_eval_report(
            BacktestConfig(
                data_root=data_root,
                report_path=eval_report_path,
                min_train_months=6,
                max_candidates_per_subject=320,
            )
        )
    eval_gate = build_eval_gate(eval_report.get("metrics", {}), thresholds)

    drift_output_path = data_root / "avm" / "drift_alerts.json"
    if reuse_drift_report and drift_output_path.exists():
        drift_report = json.loads(drift_output_path.read_text(encoding="utf-8"))
    else:
        drift_report = generate_drift_report(
            archive_dir=data_root / "archive",
            output_path=drift_output_path,
            window_days=30,
        )
    drift_gate = {
        "alert_count": len(drift_report.get("alerts", [])),
        "pass": len(drift_report.get("alerts", [])) <= thresholds.drift_alert_budget,
    }

    api_smoke = run_api_smoke(data_root, thresholds, smoke_sample_size)

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": window_days,
        "thresholds": thresholds.__dict__,
        "analysis_readiness": _analysis_readiness_context(data_root, window_days),
        "completeness": completeness,
        "evaluation": eval_gate,
        "drift": drift_gate,
        "api_smoke": api_smoke,
        "pass": completeness["pass"] and eval_gate["pass"] and api_smoke["pass"] and drift_gate["pass"],
    }
    gate_report_path.parent.mkdir(parents=True, exist_ok=True)
    gate_report_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> None:
    args = parse_args()
    output = generate_release_gate_report(
        data_root=args.data_root,
        eval_report_path=args.eval_report_path,
        gate_report_path=args.gate_report_path,
        window_days=args.window_days,
        min_sample_size=args.min_sample_size,
        smoke_sample_size=args.smoke_sample_size,
        reuse_eval_report=args.reuse_eval_report,
        reuse_drift_report=args.reuse_drift_report,
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
