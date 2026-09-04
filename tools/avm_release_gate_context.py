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



__all__ = tuple(name for name in globals() if not name.startswith("__"))
