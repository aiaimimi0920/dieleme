import http.server
import socketserver
import json
import os
import datetime
import glob
import math
from pathlib import Path
import threading
import tempfile
import time
import re
import re
from urllib.parse import urlparse, parse_qs, unquote
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import llm_helper
    from avm_config import AVM_CONFIG_MANAGER
    from avm_config import DEFAULT_AVM_CONFIG
    from avm_config import get_effective_alert_threshold
    from captcha_solver import CaptchaSolver
except ModuleNotFoundError:
    from src import llm_helper
    from src.avm_config import AVM_CONFIG_MANAGER
    from src.avm_config import DEFAULT_AVM_CONFIG
    from src.avm_config import get_effective_alert_threshold
    from src.captcha_solver import CaptchaSolver

# Import Captcha Solver
solver = CaptchaSolver(port=9222)

from src.avm.service import AVMService
from src.avm.pipeline import AVMPipelineManager, AVMPipelineConfig
from src.avm.collection_template import sync_collection_record
from src.avm.alert_policy import build_alert_blockers
from src.collection import DetailCollectionService, SeedCollectionService
from src.detail_artifacts import (
    extract_detail_artifacts as _shared_extract_detail_artifacts,
    get_detail_archive_path as _shared_get_detail_archive_path,
)
from src.storage import create_repository_from_env
from tools.analysis_stage_planner import (
    load_action_effectiveness_snapshot,
    load_manual_review_receipt_snapshot,
    load_optimization_loop_progress_snapshot,
    load_recent_gap_audit_snapshot,
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
from tools.manual_review_receipt_audit import (
    append_manual_review_receipt_operation,
    filter_manual_review_receipt_operations,
    load_manual_review_receipt_operations,
    summarize_manual_review_receipt_operations_snapshot,
)
from tools.manual_review_receipt_jobs import (
    ManualReviewMaintenanceManager,
    load_manual_review_receipt_jobs,
    summarize_manual_review_receipt_jobs_snapshot,
)
from tools.manual_review_receipt_store import (
    delete_manual_review_receipt,
    list_manual_review_receipts,
    upsert_manual_review_receipt,
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
from tools.apply_avm_calibration_patch import (
    apply_command_chain_next_action_policy,
    apply_avm_calibration_patch,
    normalize_calibration_targets_payload,
    resolve_command_chain_artifacts,
    summarize_bundle_command_summary,
    summarize_patch_follow_up_command,
    summarize_patch_command_chain,
    summarize_patch_next_action,
    summarize_patch_next_action_command,
    summarize_patch_risk,
)
from tools.run_recent_enrich_maintenance import run_recent_enrich_maintenance

PORT = 8001
BATCH_SIZE = 8  # User Configurable Concurrency
DISPATCH_COOLDOWN_SECONDS = 20  # Task redispatch cooldown (aggressive profile)
# Global Thread Pool for AI tasks (Limit 32 to prevent API overload)
executor = ThreadPoolExecutor(max_workers=32)
DATA_DIR = "datas"
AVM_DIR = os.path.join(DATA_DIR, "avm")
AVM_ALERTS_PATH = os.path.join(AVM_DIR, "alerts.json")

DB_REPOSITORY = create_repository_from_env()
AVM_SERVICE = AVMService(data_dir=DATA_DIR, repository=DB_REPOSITORY)
AVM_PIPELINE = AVMPipelineManager(data_dir=DATA_DIR)

# Global state
SEEN_IDS = {}  # id -> {file_path, status, data}
PENDING_TASKS = [] # list of ids
DISPATCHED_TASKS = {} # id -> timestamp
PAUSED = False
SOLVER_LOCK = threading.Lock()
FILE_LOCK = threading.Lock()
DATA_LOCK = threading.Lock() # Protects SEEN_IDS and PENDING_TASKS
CURRENT_PROCESSING = set() # Track running tasks to avoid duplicate submission
SOLVER_RUNNING = False
SOLVER_START_TIME = 0
RUNTIME_INITIALIZED = False
AVM_SERVICE_START_TIME = time.time()

DEFAULT_MARGIN_THRESHOLD = 0.15
MALIGNANT_RISK_LABELS = {
    "is_haunted": "疑似凶宅/刑事案件",
    "is_occupied": "房屋疑似被占用未腾空",
    "has_long_lease": "存在长租约风险",
    "is_fractional_share": "标的为部分产权",
    "tax_is_company_owned": "企业产权潜在高税费",
}

RISK_ALIAS_KEYS = (
    "community_name",
    "build_year",
    "total_floors",
    "floor_level",
    "has_elevator",
    "orientation",
    "land_right_type",
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "tax_burden",
    "is_haunted",
    "housing_type",
    "has_keys",
    "property_fee_owed",
    "special_school_tag",
    "layout",
    "is_restricted_purchase",
    "includes_parking",
    "is_fractional_share",
    "tax_is_company_owned",
    "has_lease_before_mortgage",
    "extraction_confidence",
    "evidence_span",
    "evidence_source",
    "extraction_version",
)


def _runtime_env_flag(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _prefer_db_task_reads() -> bool:
    return DB_REPOSITORY.enabled and _runtime_env_flag("FAPAI_DB_PREFER_RUNTIME_INDEX", True)


def _db_pending_task_candidates(limit=100):
    if not _prefer_db_task_reads():
        return []
    try:
        return DB_REPOSITORY.iter_pending_task_items(limit=limit)
    except Exception as error:
        print(f"[DB] Pending task query failed: {error}")
    return []


def _db_counts_snapshot():
    if not DB_REPOSITORY.enabled:
        return {
            "db_total_ids": 0,
            "db_processed_ids": 0,
            "db_pending_ids": 0,
            "db_detail_captured_ids": 0,
        }
    try:
        return DB_REPOSITORY.counts_snapshot()
    except Exception:
        return {
            "db_total_ids": DB_REPOSITORY.count_listings(),
            "db_processed_ids": DB_REPOSITORY.count_processed_listings(),
            "db_pending_ids": DB_REPOSITORY.count_pending_task_items(),
            "db_detail_captured_ids": DB_REPOSITORY.count_detail_captured_items(),
        }


def _db_data_supply_snapshot(hours: int = 24):
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "event_type_counts"):
        return {
            "detail_archive_fetch_recent": {},
            "maintenance_writeback_recent": {},
            "stage_transition_recent": {},
        }
    fetch_counts = DB_REPOSITORY.event_type_counts(
        (
            "detail_archive_fetched",
            "detail_archive_fetch_blocked",
            "detail_archive_fetch_failed",
        ),
        hours=hours,
    )
    maintenance_counts = DB_REPOSITORY.event_type_counts(
        (
            "detail_replay_prepared",
            "recent_coordinate_backfill",
            "archived_detail_backfill",
        ),
        hours=hours,
    )
    stage_transition_counts = DB_REPOSITORY.event_type_counts(
        (
            "seed_stage_transition",
            "detail_stage_transition",
            "analysis_stage_transition",
            "analysis_ready_transition",
        ),
        hours=hours,
    )
    return {
        "detail_archive_fetch_recent": fetch_counts,
        "maintenance_writeback_recent": maintenance_counts,
        "stage_transition_recent": stage_transition_counts,
    }


def _db_collection_stage_snapshot():
    action_effectiveness = load_action_effectiveness_snapshot(Path(DATA_DIR) / "avm" / "data_supply_optimization_loop.json")
    scheduler_progress = load_optimization_loop_progress_snapshot(Path(DATA_DIR) / "avm" / "data_supply_optimization_loop.json")
    action_effectiveness_summary = summarize_action_effectiveness_snapshot(action_effectiveness)
    scheduler_feedback_summary = summarize_scheduler_feedback_snapshot(scheduler_progress)
    recent_gap_report = load_recent_gap_audit_snapshot(Path(DATA_DIR) / "avm" / "recent_gap_audit.json")
    recoverability_summary = summarize_recoverability_snapshot(recent_gap_report)
    manual_review_backlog_summary = summarize_manual_review_backlog(recent_gap_report)
    manual_review_receipt_summary = summarize_manual_review_receipt_snapshot(
        _load_manual_review_receipt_snapshot_for_runtime(Path(DATA_DIR)),
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
    hybrid_collection_runtime_summary = _hybrid_collection_runtime_summary(Path(DATA_DIR))
    hybrid_collection_runtime_history_summary = _hybrid_collection_runtime_history_summary(Path(DATA_DIR))
    hybrid_collection_action_hint_trend_summary = _hybrid_collection_action_hint_trend_summary(Path(DATA_DIR))
    hybrid_collection_operator_final_guidance_trend_summary = _hybrid_collection_operator_final_guidance_trend_summary(Path(DATA_DIR))
    hybrid_collection_operator_final_guidance_stability_summary = _hybrid_collection_operator_final_guidance_stability_summary(
        hybrid_collection_operator_final_guidance_trend_summary,
    )
    hybrid_collection_operator_intervention_trend_summary = _hybrid_collection_operator_intervention_trend_summary(Path(DATA_DIR))
    hybrid_collection_mode_switch_event_summary = _hybrid_collection_mode_switch_event_summary(Path(DATA_DIR))
    hybrid_collection_recovery_policy_event_summary = _hybrid_collection_recovery_policy_event_summary(Path(DATA_DIR))
    hybrid_collection_operator_escalation_event_summary = _hybrid_collection_operator_escalation_event_summary(Path(DATA_DIR))
    hybrid_collection_operator_escalation_event_trend_summary = _hybrid_collection_operator_escalation_event_trend_summary(Path(DATA_DIR))
    hybrid_collection_operator_escalation_event_stability_summary = _hybrid_collection_operator_escalation_event_stability_summary(
        hybrid_collection_operator_escalation_event_trend_summary,
    )
    hybrid_collection_operator_escalation_recovery_event_summary = _hybrid_collection_operator_escalation_recovery_event_summary(Path(DATA_DIR))
    hybrid_collection_operator_intervention_event_summary = _hybrid_collection_operator_intervention_event_summary(Path(DATA_DIR))
    hybrid_collection_unresolved_escalation_window_summary = _hybrid_collection_unresolved_escalation_window_summary(
        hybrid_collection_operator_escalation_event_summary,
        hybrid_collection_operator_escalation_recovery_event_summary,
    )
    hybrid_collection_recovery_latency_summary = _hybrid_collection_recovery_latency_summary(Path(DATA_DIR))
    hybrid_collection_escalation_priority_mix_trend_summary = _hybrid_collection_escalation_priority_mix_trend_summary(Path(DATA_DIR))
    hybrid_collection_escalation_resolution_trend_summary = _hybrid_collection_escalation_resolution_trend_summary(
        hybrid_collection_operator_escalation_event_summary,
        hybrid_collection_operator_escalation_recovery_event_summary,
        hybrid_collection_unresolved_escalation_window_summary,
    )
    hybrid_collection_strategy_guidance = _hybrid_collection_strategy_guidance(
        hybrid_collection_runtime_summary,
        hybrid_collection_runtime_history_summary,
    )
    hybrid_collection_recovery_policy = _hybrid_collection_recovery_policy(
        Path(DATA_DIR),
        hybrid_collection_runtime_summary,
        hybrid_collection_runtime_history_summary,
        hybrid_collection_strategy_guidance,
        hybrid_collection_mode_switch_event_summary,
        hybrid_collection_recovery_policy_event_summary,
    )
    hybrid_collection_lifecycle_state_summary = _hybrid_collection_lifecycle_state_summary(
        hybrid_collection_runtime_summary,
        hybrid_collection_recovery_policy,
        hybrid_collection_unresolved_escalation_window_summary,
        hybrid_collection_escalation_priority_mix_trend_summary,
    )
    hybrid_collection_action_hint_consistency_summary = _hybrid_collection_action_hint_consistency_summary(
        hybrid_collection_runtime_summary,
        hybrid_collection_lifecycle_state_summary,
    )
    hybrid_collection_operator_intervention_policy_summary = _hybrid_collection_operator_intervention_policy_summary(
        hybrid_collection_lifecycle_state_summary,
        hybrid_collection_action_hint_consistency_summary,
        hybrid_collection_escalation_resolution_trend_summary,
        hybrid_collection_recovery_latency_summary,
    )
    hybrid_collection_operator_intervention_stability_summary = _hybrid_collection_operator_intervention_stability_summary(
        hybrid_collection_operator_intervention_trend_summary,
    )
    hybrid_collection_operator_final_guidance_summary = _hybrid_collection_operator_final_guidance_summary(
        hybrid_collection_operator_intervention_policy_summary,
        hybrid_collection_operator_intervention_stability_summary,
    )
    hybrid_collection_operator_digest_summary = _hybrid_collection_operator_digest_summary(
        hybrid_collection_operator_intervention_policy_summary,
        hybrid_collection_operator_intervention_stability_summary,
        hybrid_collection_operator_final_guidance_summary,
        hybrid_collection_operator_final_guidance_stability_summary,
    )
    hybrid_collection_operator_digest_trend_summary = _hybrid_collection_operator_digest_trend_summary(Path(DATA_DIR))
    hybrid_collection_operator_digest_stability_summary = _hybrid_collection_operator_digest_stability_summary(
        hybrid_collection_operator_digest_trend_summary,
    )
    default_operator_overview = summarize_operator_overview(
        default_operator_action_summary,
        scheduler_feedback_summary,
    )
    default_operator_overview.update(_hybrid_collection_operator_overview_fields(hybrid_collection_runtime_summary))
    default_operator_overview.update(_hybrid_collection_operator_history_overview_fields(hybrid_collection_runtime_history_summary))
    default_operator_overview.update(_hybrid_collection_operator_action_hint_trend_overview_fields(hybrid_collection_action_hint_trend_summary))
    default_operator_overview.update(_hybrid_collection_operator_final_guidance_trend_overview_fields(hybrid_collection_operator_final_guidance_trend_summary))
    default_operator_overview.update(_hybrid_collection_operator_final_guidance_stability_overview_fields(hybrid_collection_operator_final_guidance_stability_summary))
    default_operator_overview.update(_hybrid_collection_operator_digest_trend_overview_fields(hybrid_collection_operator_digest_trend_summary))
    default_operator_overview.update(_hybrid_collection_operator_digest_stability_overview_fields(hybrid_collection_operator_digest_stability_summary))
    default_operator_overview.update(_hybrid_collection_operator_intervention_trend_overview_fields(hybrid_collection_operator_intervention_trend_summary))
    default_operator_overview.update(_hybrid_collection_operator_guidance_overview_fields(hybrid_collection_strategy_guidance))
    default_operator_overview.update(_hybrid_collection_operator_mode_switch_overview_fields(hybrid_collection_mode_switch_event_summary))
    default_operator_overview.update(_hybrid_collection_operator_recovery_policy_overview_fields(hybrid_collection_recovery_policy))
    default_operator_overview.update(_hybrid_collection_operator_recovery_policy_event_overview_fields(hybrid_collection_recovery_policy_event_summary))
    default_operator_overview.update(_hybrid_collection_operator_escalation_event_overview_fields(hybrid_collection_operator_escalation_event_summary))
    default_operator_overview.update(_hybrid_collection_operator_escalation_event_trend_overview_fields(hybrid_collection_operator_escalation_event_trend_summary))
    default_operator_overview.update(_hybrid_collection_operator_escalation_event_stability_overview_fields(hybrid_collection_operator_escalation_event_stability_summary))
    default_operator_overview.update(_hybrid_collection_operator_escalation_recovery_event_overview_fields(hybrid_collection_operator_escalation_recovery_event_summary))
    default_operator_overview.update(_hybrid_collection_operator_intervention_event_overview_fields(hybrid_collection_operator_intervention_event_summary))
    default_operator_overview.update(_hybrid_collection_operator_unresolved_escalation_window_overview_fields(hybrid_collection_unresolved_escalation_window_summary))
    default_operator_overview.update(_hybrid_collection_operator_lifecycle_state_overview_fields(hybrid_collection_lifecycle_state_summary))
    default_operator_overview.update(_hybrid_collection_operator_action_hint_consistency_overview_fields(hybrid_collection_action_hint_consistency_summary))
    default_operator_overview.update(_hybrid_collection_operator_intervention_stability_overview_fields(hybrid_collection_operator_intervention_stability_summary))
    default_operator_overview.update(_hybrid_collection_operator_intervention_policy_overview_fields(hybrid_collection_operator_intervention_policy_summary))
    default_operator_overview.update(_hybrid_collection_operator_final_guidance_overview_fields(hybrid_collection_operator_final_guidance_summary))
    default_operator_overview.update(_hybrid_collection_operator_digest_overview_fields(hybrid_collection_operator_digest_summary))
    default_operator_overview.update(_hybrid_collection_operator_recovery_latency_overview_fields(hybrid_collection_recovery_latency_summary))
    default_operator_overview.update(_hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(hybrid_collection_escalation_priority_mix_trend_summary))
    default_operator_overview.update(_hybrid_collection_operator_escalation_resolution_trend_overview_fields(hybrid_collection_escalation_resolution_trend_summary))
    manual_review_receipt_jobs_summary = _manual_review_receipt_jobs_summary(Path(DATA_DIR))
    manual_review_receipt_operations_summary = _manual_review_receipt_operations_summary(Path(DATA_DIR))
    control_plane_runtime = _manual_review_control_plane_runtime_summary(Path(DATA_DIR))
    if not DB_REPOSITORY.enabled:
        return {
            "seed_stage": {},
            "detail_stage": {},
            "analysis_stage": {},
            "analysis_blockers": {},
            "recommended_actions": default_recommended_actions,
            "action_effectiveness_summary": action_effectiveness_summary,
            "recoverability_summary": recoverability_summary,
            "manual_review_backlog_summary": manual_review_backlog_summary,
            "manual_review_receipt_summary": manual_review_receipt_summary,
            "manual_review_reentry_application_summary": default_manual_review_reentry_application_summary,
            "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
            "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
            **control_plane_runtime,
            "scheduler_feedback_summary": scheduler_feedback_summary,
            "operator_action_summary": default_operator_action_summary,
            "operator_overview": default_operator_overview,
            "hybrid_collection_runtime_summary": hybrid_collection_runtime_summary,
            "hybrid_collection_runtime_history_summary": hybrid_collection_runtime_history_summary,
            "hybrid_collection_action_hint_trend_summary": hybrid_collection_action_hint_trend_summary,
            "hybrid_collection_operator_final_guidance_trend_summary": hybrid_collection_operator_final_guidance_trend_summary,
            "hybrid_collection_operator_final_guidance_stability_summary": hybrid_collection_operator_final_guidance_stability_summary,
            "hybrid_collection_operator_digest_trend_summary": hybrid_collection_operator_digest_trend_summary,
            "hybrid_collection_operator_digest_stability_summary": hybrid_collection_operator_digest_stability_summary,
            "hybrid_collection_operator_intervention_trend_summary": hybrid_collection_operator_intervention_trend_summary,
            "hybrid_collection_strategy_guidance": hybrid_collection_strategy_guidance,
            "hybrid_collection_mode_switch_event_summary": hybrid_collection_mode_switch_event_summary,
            "hybrid_collection_recovery_policy": hybrid_collection_recovery_policy,
            "hybrid_collection_recovery_policy_event_summary": hybrid_collection_recovery_policy_event_summary,
            "hybrid_collection_operator_escalation_event_summary": hybrid_collection_operator_escalation_event_summary,
            "hybrid_collection_operator_escalation_event_trend_summary": hybrid_collection_operator_escalation_event_trend_summary,
            "hybrid_collection_operator_escalation_event_stability_summary": hybrid_collection_operator_escalation_event_stability_summary,
            "hybrid_collection_operator_escalation_recovery_event_summary": hybrid_collection_operator_escalation_recovery_event_summary,
            "hybrid_collection_operator_intervention_event_summary": hybrid_collection_operator_intervention_event_summary,
            "hybrid_collection_unresolved_escalation_window_summary": hybrid_collection_unresolved_escalation_window_summary,
            "hybrid_collection_lifecycle_state_summary": hybrid_collection_lifecycle_state_summary,
            "hybrid_collection_action_hint_consistency_summary": hybrid_collection_action_hint_consistency_summary,
            "hybrid_collection_operator_intervention_stability_summary": hybrid_collection_operator_intervention_stability_summary,
            "hybrid_collection_operator_intervention_policy_summary": hybrid_collection_operator_intervention_policy_summary,
            "hybrid_collection_operator_final_guidance_summary": hybrid_collection_operator_final_guidance_summary,
            "hybrid_collection_operator_digest_summary": hybrid_collection_operator_digest_summary,
            "hybrid_collection_recovery_latency_summary": hybrid_collection_recovery_latency_summary,
            "hybrid_collection_escalation_priority_mix_trend_summary": hybrid_collection_escalation_priority_mix_trend_summary,
            "hybrid_collection_escalation_resolution_trend_summary": hybrid_collection_escalation_resolution_trend_summary,
            "search_tasks": {},
        }
    try:
        stage_counts = DB_REPOSITORY.stage_status_counts() if hasattr(DB_REPOSITORY, "stage_status_counts") else {}
        search_counts = DB_REPOSITORY.search_task_counts() if hasattr(DB_REPOSITORY, "search_task_counts") else {}
        readiness_snapshot = (
            DB_REPOSITORY.analysis_readiness_snapshot()
            if hasattr(DB_REPOSITORY, "analysis_readiness_snapshot")
            else {}
        )
    except Exception:
        stage_counts = {}
        search_counts = {}
        readiness_snapshot = {}
    recommended_actions = recommend_analysis_stage_actions(
        {"analysis_blockers": readiness_snapshot.get("blockers", {})},
        gap_report=recent_gap_report,
        action_effectiveness=action_effectiveness,
        manual_review_receipt_summary=manual_review_receipt_summary,
    )
    manual_review_reentry_application_summary = summarize_manual_review_reentry_application_summary(
        manual_review_receipt_summary,
        {},
        recent_gap_report,
        recent_gap_report,
        {"analysis_blockers": readiness_snapshot.get("blockers", {})},
        {"analysis_blockers": readiness_snapshot.get("blockers", {})},
    )
    operator_action_summary = summarize_operator_action_surface(
        recommended_actions,
        action_effectiveness_summary,
        recoverability_summary,
    )
    operator_action_summary["manual_review_backlog_summary"] = manual_review_backlog_summary
    operator_action_summary["manual_review_receipt_summary"] = manual_review_receipt_summary
    operator_action_summary["manual_review_reentry_application_summary"] = manual_review_reentry_application_summary
    operator_overview = summarize_operator_overview(
        operator_action_summary,
        scheduler_feedback_summary,
    )
    operator_overview.update(_hybrid_collection_operator_overview_fields(hybrid_collection_runtime_summary))
    operator_overview.update(_hybrid_collection_operator_history_overview_fields(hybrid_collection_runtime_history_summary))
    operator_overview.update(_hybrid_collection_operator_action_hint_trend_overview_fields(hybrid_collection_action_hint_trend_summary))
    operator_overview.update(_hybrid_collection_operator_final_guidance_trend_overview_fields(hybrid_collection_operator_final_guidance_trend_summary))
    operator_overview.update(_hybrid_collection_operator_final_guidance_stability_overview_fields(hybrid_collection_operator_final_guidance_stability_summary))
    operator_overview.update(_hybrid_collection_operator_digest_trend_overview_fields(hybrid_collection_operator_digest_trend_summary))
    operator_overview.update(_hybrid_collection_operator_digest_stability_overview_fields(hybrid_collection_operator_digest_stability_summary))
    operator_overview.update(_hybrid_collection_operator_intervention_trend_overview_fields(hybrid_collection_operator_intervention_trend_summary))
    operator_overview.update(_hybrid_collection_operator_guidance_overview_fields(hybrid_collection_strategy_guidance))
    operator_overview.update(_hybrid_collection_operator_mode_switch_overview_fields(hybrid_collection_mode_switch_event_summary))
    operator_overview.update(_hybrid_collection_operator_recovery_policy_overview_fields(hybrid_collection_recovery_policy))
    operator_overview.update(_hybrid_collection_operator_recovery_policy_event_overview_fields(hybrid_collection_recovery_policy_event_summary))
    operator_overview.update(_hybrid_collection_operator_escalation_event_overview_fields(hybrid_collection_operator_escalation_event_summary))
    operator_overview.update(_hybrid_collection_operator_escalation_event_trend_overview_fields(hybrid_collection_operator_escalation_event_trend_summary))
    operator_overview.update(_hybrid_collection_operator_escalation_event_stability_overview_fields(hybrid_collection_operator_escalation_event_stability_summary))
    operator_overview.update(_hybrid_collection_operator_escalation_recovery_event_overview_fields(hybrid_collection_operator_escalation_recovery_event_summary))
    operator_overview.update(_hybrid_collection_operator_intervention_event_overview_fields(hybrid_collection_operator_intervention_event_summary))
    operator_overview.update(_hybrid_collection_operator_unresolved_escalation_window_overview_fields(hybrid_collection_unresolved_escalation_window_summary))
    operator_overview.update(_hybrid_collection_operator_lifecycle_state_overview_fields(hybrid_collection_lifecycle_state_summary))
    operator_overview.update(_hybrid_collection_operator_action_hint_consistency_overview_fields(hybrid_collection_action_hint_consistency_summary))
    operator_overview.update(_hybrid_collection_operator_intervention_stability_overview_fields(hybrid_collection_operator_intervention_stability_summary))
    operator_overview.update(_hybrid_collection_operator_intervention_policy_overview_fields(hybrid_collection_operator_intervention_policy_summary))
    operator_overview.update(_hybrid_collection_operator_final_guidance_overview_fields(hybrid_collection_operator_final_guidance_summary))
    operator_overview.update(_hybrid_collection_operator_digest_overview_fields(hybrid_collection_operator_digest_summary))
    operator_overview.update(_hybrid_collection_operator_recovery_latency_overview_fields(hybrid_collection_recovery_latency_summary))
    operator_overview.update(_hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(hybrid_collection_escalation_priority_mix_trend_summary))
    operator_overview.update(_hybrid_collection_operator_escalation_resolution_trend_overview_fields(hybrid_collection_escalation_resolution_trend_summary))
    return {
        "seed_stage": {"stored": stage_counts.get("seed_stored", 0)},
        "detail_stage": {
            "pending": stage_counts.get("detail_pending", 0),
            "archived": stage_counts.get("detail_archived", 0),
            "enriched": stage_counts.get("detail_enriched", 0),
            "blocked": stage_counts.get("detail_blocked", 0),
            "failed": stage_counts.get("detail_failed", 0),
            "replay_requested": stage_counts.get("detail_replay_requested", 0),
        },
        "analysis_stage": {
            "ready": stage_counts.get("analysis_ready", 0),
            "not_ready": stage_counts.get("analysis_not_ready", 0),
            "invalid": stage_counts.get("analysis_invalid", 0),
        },
        "analysis_blockers": readiness_snapshot.get("blockers", {}),
        "recommended_actions": recommended_actions,
        "action_effectiveness_summary": action_effectiveness_summary,
        "recoverability_summary": recoverability_summary,
        "manual_review_backlog_summary": manual_review_backlog_summary,
        "manual_review_receipt_summary": manual_review_receipt_summary,
        "manual_review_reentry_application_summary": manual_review_reentry_application_summary,
        "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
        "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
        **control_plane_runtime,
        "scheduler_feedback_summary": scheduler_feedback_summary,
        "operator_action_summary": operator_action_summary,
        "operator_overview": operator_overview,
        "hybrid_collection_runtime_summary": hybrid_collection_runtime_summary,
        "hybrid_collection_runtime_history_summary": hybrid_collection_runtime_history_summary,
        "hybrid_collection_action_hint_trend_summary": hybrid_collection_action_hint_trend_summary,
        "hybrid_collection_operator_final_guidance_trend_summary": hybrid_collection_operator_final_guidance_trend_summary,
        "hybrid_collection_operator_final_guidance_stability_summary": hybrid_collection_operator_final_guidance_stability_summary,
        "hybrid_collection_operator_digest_trend_summary": hybrid_collection_operator_digest_trend_summary,
        "hybrid_collection_operator_digest_stability_summary": hybrid_collection_operator_digest_stability_summary,
        "hybrid_collection_operator_intervention_trend_summary": hybrid_collection_operator_intervention_trend_summary,
        "hybrid_collection_strategy_guidance": hybrid_collection_strategy_guidance,
        "hybrid_collection_mode_switch_event_summary": hybrid_collection_mode_switch_event_summary,
        "hybrid_collection_recovery_policy": hybrid_collection_recovery_policy,
        "hybrid_collection_recovery_policy_event_summary": hybrid_collection_recovery_policy_event_summary,
        "hybrid_collection_operator_escalation_event_summary": hybrid_collection_operator_escalation_event_summary,
        "hybrid_collection_operator_escalation_event_trend_summary": hybrid_collection_operator_escalation_event_trend_summary,
        "hybrid_collection_operator_escalation_event_stability_summary": hybrid_collection_operator_escalation_event_stability_summary,
        "hybrid_collection_operator_escalation_recovery_event_summary": hybrid_collection_operator_escalation_recovery_event_summary,
        "hybrid_collection_operator_intervention_event_summary": hybrid_collection_operator_intervention_event_summary,
        "hybrid_collection_unresolved_escalation_window_summary": hybrid_collection_unresolved_escalation_window_summary,
        "hybrid_collection_lifecycle_state_summary": hybrid_collection_lifecycle_state_summary,
        "hybrid_collection_action_hint_consistency_summary": hybrid_collection_action_hint_consistency_summary,
        "hybrid_collection_operator_intervention_stability_summary": hybrid_collection_operator_intervention_stability_summary,
        "hybrid_collection_operator_intervention_policy_summary": hybrid_collection_operator_intervention_policy_summary,
        "hybrid_collection_operator_final_guidance_summary": hybrid_collection_operator_final_guidance_summary,
        "hybrid_collection_operator_digest_summary": hybrid_collection_operator_digest_summary,
        "hybrid_collection_recovery_latency_summary": hybrid_collection_recovery_latency_summary,
        "hybrid_collection_escalation_priority_mix_trend_summary": hybrid_collection_escalation_priority_mix_trend_summary,
        "hybrid_collection_escalation_resolution_trend_summary": hybrid_collection_escalation_resolution_trend_summary,
        "search_tasks": search_counts,
    }


MANUAL_REVIEW_RECEIPT_ENDPOINTS = (
    "/api/avm/manual_review_receipts",
    "/api/analysis/manual_review_receipts",
)
MANUAL_REVIEW_RECEIPT_JOB_ENDPOINTS = (
    "/api/avm/manual_review_receipt_jobs",
    "/api/analysis/manual_review_receipt_jobs",
)
MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS = (
    "/api/avm/manual_review_receipt_operations",
    "/api/analysis/manual_review_receipt_operations",
)
MANUAL_REVIEW_CONTROL_PLANE_STATUS_ENDPOINTS = (
    "/api/avm/manual_review_control_plane_status",
    "/api/analysis/manual_review_control_plane_status",
)
MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS = (
    "/api/avm/manual_review_control_plane_backup_repairs",
    "/api/analysis/manual_review_control_plane_backup_repairs",
)
MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS = (
    "/api/avm/manual_review_control_plane_integrity_history",
    "/api/analysis/manual_review_control_plane_integrity_history",
)
MANUAL_REVIEW_MAINTENANCE_MANAGERS: dict[str, ManualReviewMaintenanceManager] = {}


def _manual_review_receipt_store_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_receipts.json"


def _manual_review_receipt_operations_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_receipt_operations.jsonl"


def _manual_review_receipt_jobs_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_receipt_jobs.json"


def _normalize_manual_review_maintenance_options(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    return {
        "window_days": int(payload.get("window_days", 7) or 7),
        "archive_limit": int(payload.get("archive_limit", 200) or 200),
        "sample_limit": int(payload.get("sample_limit", 20) or 20),
        "replay_limit": int(payload.get("replay_limit", 100) or 100),
        "fetch_limit": int(payload.get("fetch_limit", 20) or 20),
        "fetch_timeout": int(payload.get("fetch_timeout", 15) or 15),
        "reconcile_limit": int(payload.get("reconcile_limit", 200) or 200),
        "dry_run": bool(payload.get("dry_run", False)),
        "extract_risk": bool(payload.get("extract_risk", False)),
        "prepare_replay": bool(payload.get("prepare_replay", False)),
        "fetch_archives": bool(payload.get("fetch_archives", False)),
    }


def _run_manual_review_receipt_maintenance(data_root: Path, maintenance_options: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_manual_review_maintenance_options(maintenance_options)
    return run_recent_enrich_maintenance(
        data_root=data_root,
        window_days=normalized["window_days"],
        archive_limit=normalized["archive_limit"],
        sample_limit=normalized["sample_limit"],
        replay_limit=normalized["replay_limit"],
        fetch_limit=normalized["fetch_limit"],
        fetch_timeout=normalized["fetch_timeout"],
        reconcile_limit=normalized["reconcile_limit"],
        dry_run=normalized["dry_run"],
        extract_risk=normalized["extract_risk"],
        prepare_replay=normalized["prepare_replay"],
        fetch_archives=normalized["fetch_archives"],
        repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
    )


def _get_manual_review_maintenance_manager(data_root: Path) -> ManualReviewMaintenanceManager:
    key = str(data_root.resolve())
    manager = MANUAL_REVIEW_MAINTENANCE_MANAGERS.get(key)
    if manager is None:
        manager = ManualReviewMaintenanceManager(
            _manual_review_receipt_jobs_path(data_root),
            maintenance_runner=lambda **kwargs: _run_manual_review_receipt_maintenance(data_root, kwargs),
            repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
        )
        MANUAL_REVIEW_MAINTENANCE_MANAGERS[key] = manager
    return manager


def _manual_review_receipt_jobs_summary(data_root: Path) -> dict[str, Any]:
    key = str(data_root.resolve())
    manager = MANUAL_REVIEW_MAINTENANCE_MANAGERS.get(key)
    snapshot = manager.snapshot() if manager is not None else load_manual_review_receipt_jobs(_manual_review_receipt_jobs_path(data_root))
    return summarize_manual_review_receipt_jobs_snapshot(snapshot)


def _manual_review_receipt_operations_summary(data_root: Path) -> dict[str, Any]:
    operations = load_manual_review_receipt_operations(
        _manual_review_receipt_operations_path(data_root),
        limit=200,
        repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
    )
    return summarize_manual_review_receipt_operations_snapshot(operations)


def _manual_review_control_plane_storage(data_root: Path) -> dict[str, Any]:
    return describe_manual_review_control_plane_storage(
        data_root,
        repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
    )


def _manual_review_control_plane_backup(data_root: Path) -> dict[str, Any]:
    return describe_manual_review_control_plane_backup(
        data_root,
        repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
    )


def _manual_review_control_plane_backup_repairs_summary(data_root: Path) -> dict[str, Any]:
    return summarize_manual_review_control_plane_backup_repairs(
        load_manual_review_control_plane_backup_repairs(data_root)
    )


def _manual_review_control_plane_integrity(data_root: Path) -> dict[str, Any]:
    integrity = summarize_manual_review_control_plane_integrity(
        _manual_review_control_plane_storage(data_root),
        _manual_review_control_plane_backup(data_root),
        _manual_review_control_plane_backup_repairs_summary(data_root),
    )
    record_manual_review_control_plane_integrity(data_root, integrity)
    return integrity


def _manual_review_control_plane_integrity_history_summary(data_root: Path) -> dict[str, Any]:
    return summarize_manual_review_control_plane_integrity_history(
        load_manual_review_control_plane_integrity_history(data_root)
    )


def _manual_review_control_plane_stability(data_root: Path) -> dict[str, Any]:
    return summarize_manual_review_control_plane_stability(
        _manual_review_control_plane_integrity(data_root),
        _manual_review_control_plane_integrity_history_summary(data_root),
    )


def _manual_review_control_plane_guidance(data_root: Path) -> dict[str, Any]:
    return summarize_manual_review_control_plane_guidance(
        _manual_review_control_plane_integrity(data_root),
        _manual_review_control_plane_stability(data_root),
        _manual_review_control_plane_backup_repairs_summary(data_root),
    )


def _manual_review_control_plane_runtime_summary(data_root: Path) -> dict[str, Any]:
    storage = describe_manual_review_control_plane_storage(
        data_root,
        repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
    )
    backup = describe_manual_review_control_plane_backup(
        data_root,
        repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
    )
    repairs_summary = summarize_manual_review_control_plane_backup_repairs(
        load_manual_review_control_plane_backup_repairs(data_root)
    )
    integrity = summarize_manual_review_control_plane_integrity(
        storage,
        backup,
        repairs_summary,
    )
    record_manual_review_control_plane_integrity(data_root, integrity)
    integrity_history_summary = summarize_manual_review_control_plane_integrity_history(
        load_manual_review_control_plane_integrity_history(data_root)
    )
    stability = summarize_manual_review_control_plane_stability(
        integrity,
        integrity_history_summary,
    )
    guidance = summarize_manual_review_control_plane_guidance(
        integrity,
        stability,
        repairs_summary,
    )
    return {
        "manual_review_control_plane_storage": storage,
        "manual_review_control_plane_backup": backup,
        "manual_review_control_plane_backup_repairs_summary": repairs_summary,
        "manual_review_control_plane_integrity": integrity,
        "manual_review_control_plane_integrity_history_summary": integrity_history_summary,
        "manual_review_control_plane_stability": stability,
        "manual_review_control_plane_guidance": guidance,
    }


def _load_manual_review_receipt_snapshot_for_runtime(data_root: Path) -> dict[str, Any]:
    receipt_path = data_root / "avm" / "manual_review_receipts.json"
    try:
        return load_manual_review_receipt_snapshot(
            receipt_path,
            repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
        )
    except TypeError:
        return load_manual_review_receipt_snapshot(receipt_path)


def _load_json_snapshot(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _coerce_optional_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_optional_int(value: Any) -> int | None:
    if value in {None, "", "unknown"}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(value: Any) -> float | None:
    if value in {None, "", "unknown"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_bool(value: Any) -> bool | None:
    if value in {None, "", "unknown"}:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
        return None
    return bool(value)


def _coerce_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized in {"", "unknown"}:
        return None
    return normalized


def _load_jsonl_snapshots(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
        return rows
    except Exception:
        return []


def _hybrid_collection_runtime_summary(data_root: Path) -> dict[str, Any]:
    raw = _load_json_snapshot(data_root / "avm" / "hybrid_seed_collection_runtime.json")
    if not raw:
        return {
            "available": False,
            "decision_counts": {},
            "reason_counts": {},
            "top_fallback_reason": None,
            "requested_mode": None,
            "effective_mode_source": None,
            "operator_action_hint": None,
            "effective_mode_counts": {},
            "guidance_applied_count": 0,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_mode_pin_active": False,
            "browserless_success_count": 0,
            "browser_fallback_required_count": 0,
            "browser_worker_dispatched_count": 0,
            "last_decision": None,
            "last_reason": None,
            "last_effective_mode": None,
            "last_task_url": None,
            "last_task_page": None,
            "last_task_location_code": None,
            "last_task_category": None,
            "last_probe_item_count": 0,
            "last_probe_has_script": False,
            "last_probe_body_has_login": False,
            "last_probe_body_has_captcha": False,
            "last_probe_body_has_punish": False,
            "last_probe_body_has_challenge": False,
            "last_submit_batch_status": None,
            "last_submit_batch_new": 0,
            "last_submit_progress_status": None,
            "last_browser_fallback_opened": False,
        }

    decision_counts = {
        normalized_key: parsed_value
        for key, value in _coerce_optional_mapping(raw.get("decision_counts")).items()
        if (normalized_key := _coerce_optional_text(key)) is not None
        and (parsed_value := _coerce_optional_int(value)) is not None
        and parsed_value >= 0
    }
    reason_counts = {
        normalized_key: parsed_value
        for key, value in _coerce_optional_mapping(raw.get("reason_counts")).items()
        if (normalized_key := _coerce_optional_text(key)) is not None
        and (parsed_value := _coerce_optional_int(value)) is not None
        and parsed_value > 0
    }
    top_fallback_reason = _coerce_optional_text(raw.get("top_fallback_reason"))
    if top_fallback_reason is None and reason_counts:
        top_fallback_reason = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    last_task = _coerce_optional_mapping(raw.get("last_task"))
    last_probe_summary = _coerce_optional_mapping(raw.get("last_probe_summary"))
    last_submit_result = _coerce_optional_mapping(raw.get("last_submit_result"))
    last_batch_result = _coerce_optional_mapping(last_submit_result.get("batch"))
    last_progress_result = _coerce_optional_mapping(last_submit_result.get("progress"))
    effective_mode_counts = {
        normalized_key: parsed_value
        for key, value in _coerce_optional_mapping(raw.get("effective_mode_counts")).items()
        if (normalized_key := _coerce_optional_text(key)) is not None
        and (parsed_value := _coerce_optional_int(value)) is not None
        and parsed_value >= 0
    }
    iterations = _coerce_optional_int(raw.get("iterations"))
    if iterations is None or iterations < 0:
        iterations = 0
    guidance_applied_count = _coerce_optional_int(raw.get("guidance_applied_count"))
    if guidance_applied_count is None or guidance_applied_count < 0:
        guidance_applied_count = 0
    last_probe_item_count = _coerce_optional_int(last_probe_summary.get("item_count"))
    if last_probe_item_count is None or last_probe_item_count < 0:
        last_probe_item_count = 0
    last_submit_batch_new = _coerce_optional_int(last_batch_result.get("new"))
    if last_submit_batch_new is None or last_submit_batch_new < 0:
        last_submit_batch_new = 0
    last_task_page = _coerce_optional_int(last_task.get("page"))
    if last_task_page is not None and last_task_page < 0:
        last_task_page = None
    return {
        "available": True,
        "generated_at": _coerce_optional_text(raw.get("generated_at")),
        "runner_mode": _coerce_optional_text(raw.get("runner_mode")),
        "requested_mode": _coerce_optional_text(raw.get("requested_mode")),
        "effective_mode_source": _coerce_optional_text(raw.get("effective_mode_source")),
        "operator_action_hint": _coerce_optional_text(raw.get("operator_action_hint")),
        "loop_mode": _coerce_optional_bool(raw.get("loop_mode")) is True,
        "submit_enabled": _coerce_optional_bool(raw.get("submit_enabled")) is True,
        "session_id": _coerce_optional_text(raw.get("session_id")),
        "iterations": iterations,
        "decision_counts": decision_counts,
        "reason_counts": reason_counts,
        "top_fallback_reason": top_fallback_reason,
        "termination_reason": _coerce_optional_text(raw.get("termination_reason")),
        "effective_mode_counts": effective_mode_counts,
        "guidance_applied_count": guidance_applied_count,
        "guidance_status": _coerce_optional_text(raw.get("guidance_status")),
        "recovery_policy_status": _coerce_optional_text(raw.get("recovery_policy_status")),
        "recovery_policy_mode_pin_active": _coerce_optional_bool(raw.get("recovery_policy_mode_pin_active")) is True,
        "browserless_success_count": int(decision_counts.get("browserless_success", 0) or 0),
        "browser_fallback_required_count": int(decision_counts.get("browser_fallback_required", 0) or 0),
        "browser_worker_dispatched_count": int(decision_counts.get("browser_worker_dispatched", 0) or 0),
        "last_decision": _coerce_optional_text(raw.get("last_decision")),
        "last_reason": _coerce_optional_text(raw.get("last_reason")),
        "last_effective_mode": _coerce_optional_text(raw.get("last_effective_mode"))
        or _coerce_optional_text(raw.get("effective_mode")),
        "last_task_url": _coerce_optional_text(last_task.get("url")),
        "last_task_page": last_task_page,
        "last_task_location_code": _coerce_optional_text(last_task.get("location_code")),
        "last_task_category": _coerce_optional_text(last_task.get("category")),
        "last_probe_item_count": last_probe_item_count,
        "last_probe_has_script": _coerce_optional_bool(last_probe_summary.get("has_script")) is True,
        "last_probe_body_has_login": _coerce_optional_bool(last_probe_summary.get("body_has_login")) is True,
        "last_probe_body_has_captcha": _coerce_optional_bool(last_probe_summary.get("body_has_captcha")) is True,
        "last_probe_body_has_punish": _coerce_optional_bool(last_probe_summary.get("body_has_punish")) is True,
        "last_probe_body_has_challenge": _coerce_optional_bool(last_probe_summary.get("body_has_challenge")) is True,
        "last_submit_batch_status": _coerce_optional_text(last_batch_result.get("status")),
        "last_submit_batch_new": last_submit_batch_new,
        "last_submit_progress_status": _coerce_optional_text(last_progress_result.get("status")),
        "last_browser_fallback_opened": _coerce_optional_bool(raw.get("last_browser_fallback_opened")) is True,
    }


def _hybrid_collection_runtime_history_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_collection_runtime_history.jsonl")
    if not entries:
        return {
            "available": False,
            "entry_count": 0,
            "recent_runs": 0,
            "recent_decision_counts": {},
            "recent_reason_counts": {},
            "recent_browserless_success_count": 0,
            "recent_browser_fallback_required_count": 0,
            "recent_browser_worker_dispatched_count": 0,
            "recent_browserless_success_rate": 0.0,
            "recent_top_fallback_reason": None,
            "recent_top_termination_reason": None,
            "last_generated_at": None,
            "last_session_id": None,
        }

    recent_entries = entries[-limit:]
    decision_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    termination_counts: dict[str, int] = {}
    for entry in recent_entries:
        for key, value in _coerce_optional_mapping(entry.get("decision_counts")).items():
            normalized_key = _coerce_optional_text(key)
            if normalized_key is None:
                continue
            parsed_value = _coerce_optional_int(value)
            if parsed_value is None or parsed_value < 0:
                continue
            decision_counts[normalized_key] = int(decision_counts.get(normalized_key, 0) or 0) + parsed_value
        for key, value in _coerce_optional_mapping(entry.get("reason_counts")).items():
            normalized_key = _coerce_optional_text(key)
            if normalized_key is None:
                continue
            parsed_value = _coerce_optional_int(value)
            if parsed_value is None or parsed_value <= 0:
                continue
            reason_counts[normalized_key] = int(reason_counts.get(normalized_key, 0) or 0) + parsed_value
        normalized_reason = _coerce_optional_text(entry.get("termination_reason"))
        if normalized_reason is not None:
            termination_counts[normalized_reason] = int(termination_counts.get(normalized_reason, 0) or 0) + 1

    browserless_success_count = int(decision_counts.get("browserless_success", 0) or 0)
    browser_fallback_required_count = int(decision_counts.get("browser_fallback_required", 0) or 0)
    browser_worker_dispatched_count = int(decision_counts.get("browser_worker_dispatched", 0) or 0)
    attempts = browserless_success_count + browser_fallback_required_count
    top_fallback_reason = (
        sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if reason_counts
        else None
    )
    top_termination_reason = (
        sorted(termination_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if termination_counts
        else None
    )
    last_entry = recent_entries[-1]
    return {
        "available": True,
        "entry_count": len(entries),
        "recent_runs": len(recent_entries),
        "recent_decision_counts": decision_counts,
        "recent_reason_counts": reason_counts,
        "recent_browserless_success_count": browserless_success_count,
        "recent_browser_fallback_required_count": browser_fallback_required_count,
        "recent_browser_worker_dispatched_count": browser_worker_dispatched_count,
        "recent_browserless_success_rate": (browserless_success_count / attempts) if attempts > 0 else 0.0,
        "recent_top_fallback_reason": top_fallback_reason,
        "recent_top_termination_reason": top_termination_reason,
        "last_generated_at": _coerce_optional_text(last_entry.get("generated_at")),
        "last_session_id": _coerce_optional_text(last_entry.get("session_id")),
    }


def _hybrid_collection_action_hint_trend_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_collection_runtime_history.jsonl")
    if not entries:
        return {
            "available": False,
            "recent_hint_entry_count": 0,
            "recent_action_hint_counts": {},
            "recent_distinct_action_hint_count": 0,
            "recent_change_count": 0,
            "top_action_hint": None,
            "current_action_hint": None,
            "previous_distinct_action_hint": None,
            "last_change_at": None,
        }

    recent_entries = entries[-limit:]
    hint_entries: list[tuple[str | None, str]] = []
    for entry in recent_entries:
        generated_at = _coerce_optional_text(entry.get("generated_at"))
        hint = entry.get("operator_action_hint")
        if isinstance(hint, str) and hint.strip() not in {"", "unknown"}:
            hint_entries.append((generated_at, hint.strip()))

    if not hint_entries:
        return {
            "available": False,
            "recent_hint_entry_count": 0,
            "recent_action_hint_counts": {},
            "recent_distinct_action_hint_count": 0,
            "recent_change_count": 0,
            "top_action_hint": None,
            "current_action_hint": None,
            "previous_distinct_action_hint": None,
            "last_change_at": None,
        }

    action_hint_counts: dict[str, int] = {}
    recent_change_count = 0
    last_change_at = None
    previous_hint = None
    for generated_at, hint in hint_entries:
        action_hint_counts[hint] = action_hint_counts.get(hint, 0) + 1
        if previous_hint is not None and hint != previous_hint:
            recent_change_count += 1
            last_change_at = generated_at
        previous_hint = hint

    current_action_hint = hint_entries[-1][1]
    previous_distinct_action_hint = None
    for _, hint in reversed(hint_entries[:-1]):
        if hint != current_action_hint:
            previous_distinct_action_hint = hint
            break

    top_action_hint = sorted(action_hint_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return {
        "available": True,
        "recent_hint_entry_count": len(hint_entries),
        "recent_action_hint_counts": action_hint_counts,
        "recent_distinct_action_hint_count": len(action_hint_counts),
        "recent_change_count": recent_change_count,
        "top_action_hint": top_action_hint,
        "current_action_hint": current_action_hint,
        "previous_distinct_action_hint": previous_distinct_action_hint,
        "last_change_at": last_change_at,
    }


def _hybrid_collection_operator_final_guidance_trend_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_collection_runtime_history.jsonl")
    if not entries:
        return {
            "available": False,
            "recent_guidance_entry_count": 0,
            "recent_guidance_message_counts": {},
            "recent_distinct_guidance_message_count": 0,
            "recent_change_count": 0,
            "top_guidance_message": None,
            "current_guidance_label": None,
            "current_guidance_priority": None,
            "current_guidance_message": None,
            "previous_distinct_guidance_label": None,
            "previous_distinct_guidance_message": None,
            "last_change_at": None,
        }

    recent_entries = entries[-limit:]
    guidance_entries: list[tuple[str | None, str, str | None, str | None]] = []
    for entry in recent_entries:
        generated_at = _coerce_optional_text(entry.get("generated_at"))
        guidance_message = entry.get("operator_final_guidance_message")
        if isinstance(guidance_message, str) and guidance_message.strip() not in {"", "unknown"}:
            guidance_entries.append(
                (
                    generated_at,
                    guidance_message.strip(),
                    _coerce_optional_text(entry.get("operator_final_guidance_label")),
                    _coerce_optional_text(entry.get("operator_final_guidance_priority")),
                )
            )

    if not guidance_entries:
        return {
            "available": False,
            "recent_guidance_entry_count": 0,
            "recent_guidance_message_counts": {},
            "recent_distinct_guidance_message_count": 0,
            "recent_change_count": 0,
            "top_guidance_message": None,
            "current_guidance_label": None,
            "current_guidance_priority": None,
            "current_guidance_message": None,
            "previous_distinct_guidance_label": None,
            "previous_distinct_guidance_message": None,
            "last_change_at": None,
        }

    guidance_message_counts: dict[str, int] = {}
    recent_change_count = 0
    last_change_at = None
    previous_message = None
    for generated_at, guidance_message, _label, _priority in guidance_entries:
        guidance_message_counts[guidance_message] = guidance_message_counts.get(guidance_message, 0) + 1
        if previous_message is not None and guidance_message != previous_message:
            recent_change_count += 1
            last_change_at = generated_at
        previous_message = guidance_message

    current_generated_at, current_guidance_message, current_guidance_label, current_guidance_priority = guidance_entries[-1]
    previous_distinct_guidance_label = None
    previous_distinct_guidance_message = None
    for _generated_at, guidance_message, label, _priority in reversed(guidance_entries[:-1]):
        if guidance_message != current_guidance_message:
            previous_distinct_guidance_label = label
            previous_distinct_guidance_message = guidance_message
            break

    top_guidance_message = sorted(guidance_message_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return {
        "available": True,
        "recent_guidance_entry_count": len(guidance_entries),
        "recent_guidance_message_counts": guidance_message_counts,
        "recent_distinct_guidance_message_count": len(guidance_message_counts),
        "recent_change_count": recent_change_count,
        "top_guidance_message": top_guidance_message,
        "current_guidance_label": current_guidance_label,
        "current_guidance_priority": current_guidance_priority,
        "current_guidance_message": current_guidance_message,
        "previous_distinct_guidance_label": previous_distinct_guidance_label,
        "previous_distinct_guidance_message": previous_distinct_guidance_message,
        "last_change_at": last_change_at,
    }


def _hybrid_collection_operator_final_guidance_stability_summary(
    final_guidance_trend_summary: dict[str, Any],
) -> dict[str, Any]:
    final_guidance_trend_summary = _coerce_optional_mapping(final_guidance_trend_summary)
    if _coerce_optional_bool(final_guidance_trend_summary.get("available")) is not True:
        return {
            "available": False,
            "stability_status": "unknown",
            "stability_severity": "info",
            "current_guidance_label": None,
            "current_guidance_priority": None,
            "current_guidance_message": None,
            "previous_guidance_message": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": None,
        }

    current_guidance_label = _coerce_optional_text(final_guidance_trend_summary.get("current_guidance_label"))
    current_guidance_priority = _coerce_optional_text(final_guidance_trend_summary.get("current_guidance_priority"))
    current_guidance_message = _coerce_optional_text(final_guidance_trend_summary.get("current_guidance_message"))
    previous_guidance_label = _coerce_optional_text(final_guidance_trend_summary.get("previous_distinct_guidance_label"))
    previous_guidance_message = _coerce_optional_text(final_guidance_trend_summary.get("previous_distinct_guidance_message"))
    recent_change_count = _coerce_optional_int(final_guidance_trend_summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    last_change_at = _coerce_optional_text(final_guidance_trend_summary.get("last_change_at"))

    if current_guidance_priority is None:
        if current_guidance_label in {"Escalating intervention", "Persistent intervention required"}:
            current_guidance_priority = "high"
        elif current_guidance_label in {"Transitioning intervention", "Flapping intervention"}:
            current_guidance_priority = "warning"
        elif current_guidance_label == "Stable ready state":
            current_guidance_priority = "info"

    if recent_change_count >= 2:
        stability_status = "guidance_flapping"
        stability_severity = "warning"
        operator_readable_explanation = "Final guidance changed multiple times recently."
    elif (
        current_guidance_priority in {"warning", "high"}
        and recent_change_count > 0
        and previous_guidance_label
        and current_guidance_label
    ):
        stability_status = "guidance_recently_shifted"
        stability_severity = "high" if current_guidance_priority == "high" else "warning"
        operator_readable_explanation = (
            f"Final guidance recently shifted from {previous_guidance_label} to {current_guidance_label}."
        )
    elif current_guidance_priority in {"warning", "high"} and recent_change_count == 0:
        stability_status = "persistent_noninfo_guidance"
        stability_severity = "high" if current_guidance_priority == "high" else "warning"
        operator_readable_explanation = "Final guidance remains non-info with no recent message changes."
    elif current_guidance_priority == "info" and recent_change_count == 0:
        stability_status = "stable_guidance"
        stability_severity = "info"
        operator_readable_explanation = "Final guidance remains stable with no recent message changes."
    else:
        stability_status = "guidance_transitioning"
        stability_severity = "warning"
        operator_readable_explanation = (
            f"Final guidance is transitioning and currently in {current_guidance_label}."
            if current_guidance_label is not None
            else "Final guidance is transitioning."
        )

    return {
        "available": True,
        "stability_status": stability_status,
        "stability_severity": stability_severity,
        "current_guidance_label": current_guidance_label,
        "current_guidance_priority": current_guidance_priority,
        "current_guidance_message": current_guidance_message,
        "previous_guidance_message": previous_guidance_message,
        "recent_change_count": recent_change_count,
        "last_change_at": last_change_at,
        "operator_readable_explanation": operator_readable_explanation,
    }


def _hybrid_collection_operator_digest_trend_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_collection_runtime_history.jsonl")
    if not entries:
        return {
            "available": False,
            "recent_digest_entry_count": 0,
            "recent_digest_message_counts": {},
            "recent_distinct_digest_message_count": 0,
            "recent_change_count": 0,
            "top_digest_message": None,
            "current_digest_status": None,
            "current_digest_priority": None,
            "current_digest_message": None,
            "previous_distinct_digest_status": None,
            "previous_distinct_digest_message": None,
            "last_change_at": None,
        }

    recent_entries = entries[-limit:]
    digest_entries: list[tuple[str | None, str, str | None, str | None]] = []
    for entry in recent_entries:
        generated_at = _coerce_optional_text(entry.get("generated_at"))
        digest_message = entry.get("operator_digest_message")
        if isinstance(digest_message, str) and digest_message.strip() not in {"", "unknown"}:
            digest_entries.append(
                (
                    generated_at,
                    digest_message.strip(),
                    _coerce_optional_text(entry.get("operator_digest_status")),
                    _coerce_optional_text(entry.get("operator_digest_priority")),
                )
            )

    if not digest_entries:
        return {
            "available": False,
            "recent_digest_entry_count": 0,
            "recent_digest_message_counts": {},
            "recent_distinct_digest_message_count": 0,
            "recent_change_count": 0,
            "top_digest_message": None,
            "current_digest_status": None,
            "current_digest_priority": None,
            "current_digest_message": None,
            "previous_distinct_digest_status": None,
            "previous_distinct_digest_message": None,
            "last_change_at": None,
        }

    digest_message_counts: dict[str, int] = {}
    recent_change_count = 0
    last_change_at = None
    previous_message = None
    for generated_at, digest_message, _status, _priority in digest_entries:
        digest_message_counts[digest_message] = digest_message_counts.get(digest_message, 0) + 1
        if previous_message is not None and digest_message != previous_message:
            recent_change_count += 1
            last_change_at = generated_at
        previous_message = digest_message

    _current_generated_at, current_digest_message, current_digest_status, current_digest_priority = digest_entries[-1]
    previous_distinct_digest_status = None
    previous_distinct_digest_message = None
    for _generated_at, digest_message, status, _priority in reversed(digest_entries[:-1]):
        if digest_message != current_digest_message:
            previous_distinct_digest_status = status
            previous_distinct_digest_message = digest_message
            break

    top_digest_message = sorted(digest_message_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return {
        "available": True,
        "recent_digest_entry_count": len(digest_entries),
        "recent_digest_message_counts": digest_message_counts,
        "recent_distinct_digest_message_count": len(digest_message_counts),
        "recent_change_count": recent_change_count,
        "top_digest_message": top_digest_message,
        "current_digest_status": current_digest_status,
        "current_digest_priority": current_digest_priority,
        "current_digest_message": current_digest_message,
        "previous_distinct_digest_status": previous_distinct_digest_status,
        "previous_distinct_digest_message": previous_distinct_digest_message,
        "last_change_at": last_change_at,
    }


def _hybrid_collection_operator_digest_stability_summary(
    digest_trend_summary: dict[str, Any],
) -> dict[str, Any]:
    digest_trend_summary = _coerce_optional_mapping(digest_trend_summary)
    if _coerce_optional_bool(digest_trend_summary.get("available")) is not True:
        return {
            "available": False,
            "stability_status": "unknown",
            "stability_severity": "info",
            "current_digest_status": None,
            "current_digest_priority": None,
            "current_digest_message": None,
            "previous_digest_status": None,
            "previous_digest_message": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": None,
        }

    current_digest_status = _coerce_optional_text(digest_trend_summary.get("current_digest_status"))
    current_digest_priority = _coerce_optional_text(digest_trend_summary.get("current_digest_priority"))
    current_digest_message = _coerce_optional_text(digest_trend_summary.get("current_digest_message"))
    previous_digest_status = _coerce_optional_text(digest_trend_summary.get("previous_distinct_digest_status"))
    previous_digest_message = _coerce_optional_text(digest_trend_summary.get("previous_distinct_digest_message"))
    recent_change_count = _coerce_optional_int(digest_trend_summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    last_change_at = _coerce_optional_text(digest_trend_summary.get("last_change_at"))

    if current_digest_priority is None:
        if current_digest_status == "intervention_required":
            current_digest_priority = "high"
        elif current_digest_status == "attention_required":
            current_digest_priority = "warning"
        elif current_digest_status == "ready":
            current_digest_priority = "info"

    if recent_change_count >= 2:
        stability_status = "digest_flapping"
        stability_severity = "warning"
        operator_readable_explanation = "Operator digest changed multiple times recently."
    elif (
        current_digest_priority in {"warning", "high"}
        and recent_change_count > 0
        and previous_digest_status
        and current_digest_status
    ):
        stability_status = "digest_recently_shifted"
        stability_severity = "high" if current_digest_priority == "high" else "warning"
        operator_readable_explanation = (
            f"Operator digest recently shifted from {previous_digest_status} to {current_digest_status}."
        )
    elif current_digest_priority in {"warning", "high"} and recent_change_count == 0:
        stability_status = "persistent_noninfo_digest"
        stability_severity = "high" if current_digest_priority == "high" else "warning"
        operator_readable_explanation = "Operator digest remains non-info with no recent message changes."
    elif current_digest_priority == "info" and recent_change_count == 0:
        stability_status = "stable_digest"
        stability_severity = "info"
        operator_readable_explanation = "Operator digest remains stable with no recent message changes."
    else:
        stability_status = "digest_transitioning"
        stability_severity = "warning"
        operator_readable_explanation = (
            f"Operator digest is transitioning and currently in {current_digest_status}."
            if current_digest_status is not None
            else "Operator digest is transitioning."
        )

    return {
        "available": True,
        "stability_status": stability_status,
        "stability_severity": stability_severity,
        "current_digest_status": current_digest_status,
        "current_digest_priority": current_digest_priority,
        "current_digest_message": current_digest_message,
        "previous_digest_status": previous_digest_status,
        "previous_digest_message": previous_digest_message,
        "recent_change_count": recent_change_count,
        "last_change_at": last_change_at,
        "operator_readable_explanation": operator_readable_explanation,
    }


def _hybrid_collection_operator_intervention_trend_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_collection_runtime_history.jsonl")
    if not entries:
        return {
            "available": False,
            "recent_status_entry_count": 0,
            "recent_intervention_status_counts": {},
            "recent_distinct_intervention_status_count": 0,
            "recent_change_count": 0,
            "top_intervention_status": None,
            "current_intervention_status": None,
            "current_intervention_priority": None,
            "current_intervention_reason": None,
            "previous_distinct_intervention_status": None,
            "last_change_at": None,
        }

    recent_entries = entries[-limit:]
    status_entries: list[tuple[str | None, str, str | None, str | None]] = []
    for entry in recent_entries:
        generated_at = _coerce_optional_text(entry.get("generated_at"))
        status = entry.get("intervention_status")
        if isinstance(status, str) and status.strip() not in {"", "unknown"}:
            status_entries.append(
                (
                    generated_at,
                    status.strip(),
                    _coerce_optional_text(entry.get("intervention_priority")),
                    _coerce_optional_text(entry.get("intervention_reason")),
                )
            )

    if not status_entries:
        return {
            "available": False,
            "recent_status_entry_count": 0,
            "recent_intervention_status_counts": {},
            "recent_distinct_intervention_status_count": 0,
            "recent_change_count": 0,
            "top_intervention_status": None,
            "current_intervention_status": None,
            "current_intervention_priority": None,
            "current_intervention_reason": None,
            "previous_distinct_intervention_status": None,
            "last_change_at": None,
        }

    status_counts: dict[str, int] = {}
    recent_change_count = 0
    last_change_at = None
    previous_status = None
    for generated_at, status, _priority, _reason in status_entries:
        status_counts[status] = status_counts.get(status, 0) + 1
        if previous_status is not None and status != previous_status:
            recent_change_count += 1
            last_change_at = generated_at
        previous_status = status

    current_generated_at, current_intervention_status, current_intervention_priority, current_intervention_reason = status_entries[-1]
    previous_distinct_intervention_status = None
    for _generated_at, status, _priority, _reason in reversed(status_entries[:-1]):
        if status != current_intervention_status:
            previous_distinct_intervention_status = status
            break

    top_intervention_status = sorted(status_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return {
        "available": True,
        "recent_status_entry_count": len(status_entries),
        "recent_intervention_status_counts": status_counts,
        "recent_distinct_intervention_status_count": len(status_counts),
        "recent_change_count": recent_change_count,
        "top_intervention_status": top_intervention_status,
        "current_intervention_status": current_intervention_status,
        "current_intervention_priority": current_intervention_priority,
        "current_intervention_reason": current_intervention_reason,
        "previous_distinct_intervention_status": previous_distinct_intervention_status,
        "last_change_at": last_change_at,
    }


def _hybrid_collection_mode_switch_event_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_mode_switch_events.jsonl")
    if not entries:
        return {
            "available": False,
            "entry_count": 0,
            "recent_switch_count": 0,
            "recent_target_mode_counts": {},
            "recent_guidance_status_counts": {},
            "top_target_mode": None,
            "top_guidance_reason": None,
            "last_switch_at": None,
            "last_switch_session_id": None,
        }

    recent_entries = entries[-limit:]
    target_mode_counts: dict[str, int] = {}
    guidance_status_counts: dict[str, int] = {}
    guidance_reason_counts: dict[str, int] = {}
    for entry in recent_entries:
        target_mode = _coerce_optional_text(entry.get("effective_mode"))
        if target_mode:
            target_key = target_mode
            target_mode_counts[target_key] = target_mode_counts.get(target_key, 0) + 1
        guidance_status = _coerce_optional_text(entry.get("guidance_status"))
        if guidance_status:
            status_key = guidance_status
            guidance_status_counts[status_key] = guidance_status_counts.get(status_key, 0) + 1
        guidance_reason = _coerce_optional_text(entry.get("top_guidance_reason"))
        if guidance_reason:
            reason_key = guidance_reason
            guidance_reason_counts[reason_key] = guidance_reason_counts.get(reason_key, 0) + 1

    top_target_mode = (
        sorted(target_mode_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if target_mode_counts
        else None
    )
    top_guidance_reason = (
        sorted(guidance_reason_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if guidance_reason_counts
        else None
    )
    last_entry = recent_entries[-1]
    return {
        "available": True,
        "entry_count": len(entries),
        "recent_switch_count": len(recent_entries),
        "recent_target_mode_counts": target_mode_counts,
        "recent_guidance_status_counts": guidance_status_counts,
        "top_target_mode": top_target_mode,
        "top_guidance_reason": top_guidance_reason,
        "last_switch_at": _coerce_optional_text(last_entry.get("generated_at")),
        "last_switch_session_id": _coerce_optional_text(last_entry.get("session_id")),
    }


def _hybrid_collection_recovery_policy_event_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_recovery_policy_events.jsonl")
    if not entries:
        return {
            "available": False,
            "entry_count": 0,
            "recent_transition_count": 0,
            "recent_transition_kind_counts": {},
            "recent_to_policy_status_counts": {},
            "top_transition_kind": None,
            "top_to_policy_status": None,
            "last_transition_at": None,
            "last_transition_session_id": None,
            "last_transition_kind": None,
            "last_to_policy_status": None,
        }

    recent_entries = entries[-limit:]
    transition_kind_counts: dict[str, int] = {}
    to_policy_status_counts: dict[str, int] = {}
    for entry in recent_entries:
        transition_kind = _coerce_optional_text(entry.get("transition_kind"))
        if transition_kind:
            transition_key = transition_kind
            transition_kind_counts[transition_key] = transition_kind_counts.get(transition_key, 0) + 1
        to_policy_status = _coerce_optional_text(entry.get("to_policy_status"))
        if to_policy_status:
            status_key = to_policy_status
            to_policy_status_counts[status_key] = to_policy_status_counts.get(status_key, 0) + 1

    top_transition_kind = (
        sorted(transition_kind_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if transition_kind_counts
        else None
    )
    top_to_policy_status = (
        sorted(to_policy_status_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if to_policy_status_counts
        else None
    )
    last_entry = recent_entries[-1]
    return {
        "available": True,
        "entry_count": len(entries),
        "recent_transition_count": len(recent_entries),
        "recent_transition_kind_counts": transition_kind_counts,
        "recent_to_policy_status_counts": to_policy_status_counts,
        "top_transition_kind": top_transition_kind,
        "top_to_policy_status": top_to_policy_status,
        "last_transition_at": _coerce_optional_text(last_entry.get("generated_at")),
        "last_transition_session_id": _coerce_optional_text(last_entry.get("session_id")),
        "last_transition_kind": _coerce_optional_text(last_entry.get("transition_kind")),
        "last_to_policy_status": _coerce_optional_text(last_entry.get("to_policy_status")),
    }


def _hybrid_collection_operator_escalation_event_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_operator_escalation_events.jsonl")
    if not entries:
        return {
            "available": False,
            "entry_count": 0,
            "recent_event_count": 0,
            "recent_escalation_kind_counts": {},
            "recent_operator_escalation_source_counts": {},
            "recent_policy_status_counts": {},
            "top_escalation_kind": None,
            "top_operator_escalation_source": None,
            "top_policy_status": None,
            "last_event_at": None,
            "last_event_session_id": None,
            "last_operator_escalation_source": None,
            "last_operator_escalation_audit_message": None,
        }

    recent_entries = entries[-limit:]
    escalation_kind_counts: dict[str, int] = {}
    escalation_source_counts: dict[str, int] = {}
    policy_status_counts: dict[str, int] = {}
    for entry in recent_entries:
        escalation_kind = _coerce_optional_text(entry.get("escalation_kind"))
        if escalation_kind:
            kind_key = escalation_kind
            escalation_kind_counts[kind_key] = escalation_kind_counts.get(kind_key, 0) + 1
        escalation_source = _coerce_optional_text(entry.get("operator_escalation_source"))
        if escalation_source:
            source_key = escalation_source
            escalation_source_counts[source_key] = escalation_source_counts.get(source_key, 0) + 1
        policy_status = _coerce_optional_text(entry.get("policy_status"))
        if policy_status:
            status_key = policy_status
            policy_status_counts[status_key] = policy_status_counts.get(status_key, 0) + 1

    top_escalation_kind = (
        sorted(escalation_kind_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if escalation_kind_counts
        else None
    )
    top_operator_escalation_source = (
        sorted(escalation_source_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if escalation_source_counts
        else None
    )
    top_policy_status = (
        sorted(policy_status_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if policy_status_counts
        else None
    )
    last_entry = recent_entries[-1]
    return {
        "available": True,
        "entry_count": len(entries),
        "recent_event_count": len(recent_entries),
        "recent_escalation_kind_counts": escalation_kind_counts,
        "recent_operator_escalation_source_counts": escalation_source_counts,
        "recent_policy_status_counts": policy_status_counts,
        "top_escalation_kind": top_escalation_kind,
        "top_operator_escalation_source": top_operator_escalation_source,
        "top_policy_status": top_policy_status,
        "last_event_at": _coerce_optional_text(last_entry.get("generated_at")),
        "last_event_session_id": _coerce_optional_text(last_entry.get("session_id")),
        "last_operator_escalation_source": _coerce_optional_text(last_entry.get("operator_escalation_source")),
        "last_operator_escalation_audit_message": _coerce_optional_text(
            last_entry.get("operator_escalation_audit_message")
        ),
    }


def _hybrid_collection_operator_escalation_event_trend_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_operator_escalation_events.jsonl")
    if not entries:
        return {
            "available": False,
            "recent_event_entry_count": 0,
            "recent_operator_escalation_source_counts": {},
            "recent_distinct_operator_escalation_source_count": 0,
            "recent_source_change_count": 0,
            "top_operator_escalation_source": None,
            "current_operator_escalation_source": None,
            "current_escalation_kind": None,
            "current_operator_escalation_audit_message": None,
            "previous_distinct_operator_escalation_source": None,
            "last_source_change_at": None,
        }

    recent_entries = entries[-limit:]
    source_entries: list[tuple[str | None, str, str | None, str | None]] = []
    for entry in recent_entries:
        generated_at = _coerce_optional_text(entry.get("generated_at"))
        source = entry.get("operator_escalation_source")
        if isinstance(source, str) and source.strip() not in {"", "unknown"}:
            source_entries.append(
                (
                    generated_at,
                    source.strip(),
                    _coerce_optional_text(entry.get("escalation_kind")),
                    _coerce_optional_text(entry.get("operator_escalation_audit_message")),
                )
            )

    if not source_entries:
        return {
            "available": False,
            "recent_event_entry_count": 0,
            "recent_operator_escalation_source_counts": {},
            "recent_distinct_operator_escalation_source_count": 0,
            "recent_source_change_count": 0,
            "top_operator_escalation_source": None,
            "current_operator_escalation_source": None,
            "current_escalation_kind": None,
            "current_operator_escalation_audit_message": None,
            "previous_distinct_operator_escalation_source": None,
            "last_source_change_at": None,
        }

    source_counts: dict[str, int] = {}
    recent_source_change_count = 0
    last_source_change_at = None
    previous_source = None
    for generated_at, source, _kind, _audit in source_entries:
        source_counts[source] = source_counts.get(source, 0) + 1
        if previous_source is not None and source != previous_source:
            recent_source_change_count += 1
            last_source_change_at = generated_at
        previous_source = source

    _current_generated_at, current_source, current_kind, current_audit = source_entries[-1]
    previous_distinct_source = None
    for _generated_at, source, _kind, _audit in reversed(source_entries[:-1]):
        if source != current_source:
            previous_distinct_source = source
            break

    top_source = sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return {
        "available": True,
        "recent_event_entry_count": len(source_entries),
        "recent_operator_escalation_source_counts": source_counts,
        "recent_distinct_operator_escalation_source_count": len(source_counts),
        "recent_source_change_count": recent_source_change_count,
        "top_operator_escalation_source": top_source,
        "current_operator_escalation_source": current_source,
        "current_escalation_kind": current_kind,
        "current_operator_escalation_audit_message": current_audit,
        "previous_distinct_operator_escalation_source": previous_distinct_source,
        "last_source_change_at": last_source_change_at,
    }


def _hybrid_collection_operator_escalation_event_stability_summary(
    escalation_event_trend_summary: dict[str, Any],
) -> dict[str, Any]:
    escalation_event_trend_summary = _coerce_optional_mapping(escalation_event_trend_summary)
    if _coerce_optional_bool(escalation_event_trend_summary.get("available")) is not True:
        return {
            "available": False,
            "stability_status": "unknown",
            "stability_severity": "info",
            "current_operator_escalation_source": None,
            "current_escalation_kind": None,
            "current_operator_escalation_audit_message": None,
            "previous_operator_escalation_source": None,
            "recent_source_change_count": 0,
            "last_source_change_at": None,
            "operator_readable_explanation": None,
        }

    current_source = _coerce_optional_text(escalation_event_trend_summary.get("current_operator_escalation_source"))
    current_kind = _coerce_optional_text(escalation_event_trend_summary.get("current_escalation_kind"))
    current_audit = _coerce_optional_text(escalation_event_trend_summary.get("current_operator_escalation_audit_message"))
    previous_source = _coerce_optional_text(escalation_event_trend_summary.get("previous_distinct_operator_escalation_source"))
    recent_source_change_count = (
        _coerce_optional_int(escalation_event_trend_summary.get("recent_source_change_count")) or 0
    )
    if recent_source_change_count < 0:
        recent_source_change_count = 0
    last_source_change_at = _coerce_optional_text(escalation_event_trend_summary.get("last_source_change_at"))

    high_sources = {"recovery_policy", "lifecycle_high_priority_backlog", "intervention_stability"}

    if recent_source_change_count >= 2:
        stability_status = "source_flapping"
        stability_severity = "warning"
        operator_readable_explanation = "Operator escalation source changed multiple times recently."
    elif recent_source_change_count > 0 and previous_source and current_source:
        stability_status = "source_recently_shifted"
        stability_severity = "high" if current_source in high_sources else "warning"
        operator_readable_explanation = (
            f"Operator escalation source recently shifted from {previous_source} to {current_source}."
        )
    elif current_source == "recovery_policy":
        stability_status = "persistent_recovery_policy_source"
        stability_severity = "high"
        operator_readable_explanation = "Operator escalation source remains recovery_policy with no recent source changes."
    elif current_source == "intervention_stability":
        stability_status = "persistent_intervention_stability_source"
        stability_severity = "high"
        operator_readable_explanation = "Operator escalation source remains intervention_stability with no recent source changes."
    elif current_source == "lifecycle_high_priority_backlog":
        stability_status = "persistent_high_priority_backlog_source"
        stability_severity = "high"
        operator_readable_explanation = "Operator escalation source remains lifecycle_high_priority_backlog with no recent source changes."
    elif current_source:
        stability_status = "stable_escalation_source"
        stability_severity = "warning"
        operator_readable_explanation = f"Operator escalation source remains {current_source} with no recent source changes."
    else:
        stability_status = "source_transitioning"
        stability_severity = "warning"
        operator_readable_explanation = "Operator escalation source is transitioning."

    return {
        "available": True,
        "stability_status": stability_status,
        "stability_severity": stability_severity,
        "current_operator_escalation_source": current_source,
        "current_escalation_kind": current_kind,
        "current_operator_escalation_audit_message": current_audit,
        "previous_operator_escalation_source": previous_source,
        "recent_source_change_count": recent_source_change_count,
        "last_source_change_at": last_source_change_at,
        "operator_readable_explanation": operator_readable_explanation,
    }


def _hybrid_collection_operator_escalation_recovery_event_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_operator_escalation_recovery_events.jsonl")
    if not entries:
        return {
            "available": False,
            "entry_count": 0,
            "recent_recovery_count": 0,
            "recent_transition_kind_counts": {},
            "recent_to_policy_status_counts": {},
            "top_transition_kind": None,
            "top_to_policy_status": None,
            "last_event_at": None,
            "last_event_session_id": None,
            "last_to_policy_status": None,
        }

    recent_entries = entries[-limit:]
    transition_kind_counts: dict[str, int] = {}
    to_policy_status_counts: dict[str, int] = {}
    for entry in recent_entries:
        transition_kind = _coerce_optional_text(entry.get("transition_kind"))
        if transition_kind:
            transition_kind_counts[transition_kind] = transition_kind_counts.get(transition_kind, 0) + 1
        to_policy_status = _coerce_optional_text(entry.get("to_policy_status"))
        if to_policy_status:
            to_policy_status_counts[to_policy_status] = to_policy_status_counts.get(to_policy_status, 0) + 1

    top_transition_kind = (
        sorted(transition_kind_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if transition_kind_counts
        else None
    )
    top_to_policy_status = (
        sorted(to_policy_status_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if to_policy_status_counts
        else None
    )
    last_entry = recent_entries[-1]
    return {
        "available": True,
        "entry_count": len(entries),
        "recent_recovery_count": len(recent_entries),
        "recent_transition_kind_counts": transition_kind_counts,
        "recent_to_policy_status_counts": to_policy_status_counts,
        "top_transition_kind": top_transition_kind,
        "top_to_policy_status": top_to_policy_status,
        "last_event_at": _coerce_optional_text(last_entry.get("generated_at")),
        "last_event_session_id": _coerce_optional_text(last_entry.get("session_id")),
        "last_to_policy_status": _coerce_optional_text(last_entry.get("to_policy_status")),
    }


def _hybrid_collection_operator_intervention_event_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_operator_intervention_events.jsonl")
    if not entries:
        return {
            "available": False,
            "entry_count": 0,
            "recent_event_count": 0,
            "recent_transition_kind_counts": {},
            "recent_to_intervention_status_counts": {},
            "top_transition_kind": None,
            "top_to_intervention_status": None,
            "last_event_at": None,
            "last_event_session_id": None,
            "last_transition_kind": None,
            "last_to_intervention_status": None,
            "last_to_intervention_priority": None,
            "last_to_final_guidance_label": None,
            "last_to_final_guidance_priority": None,
            "last_to_final_guidance_message": None,
        }

    recent_entries = entries[-limit:]
    transition_kind_counts: dict[str, int] = {}
    to_intervention_status_counts: dict[str, int] = {}
    for entry in recent_entries:
        transition_kind = _coerce_optional_text(entry.get("transition_kind"))
        if transition_kind:
            kind_key = transition_kind
            transition_kind_counts[kind_key] = transition_kind_counts.get(kind_key, 0) + 1
        to_intervention_status = _coerce_optional_text(entry.get("to_intervention_status"))
        if to_intervention_status:
            status_key = to_intervention_status
            to_intervention_status_counts[status_key] = to_intervention_status_counts.get(status_key, 0) + 1

    top_transition_kind = (
        sorted(transition_kind_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if transition_kind_counts
        else None
    )
    top_to_intervention_status = (
        sorted(to_intervention_status_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if to_intervention_status_counts
        else None
    )
    last_entry = recent_entries[-1]
    return {
        "available": True,
        "entry_count": len(entries),
        "recent_event_count": len(recent_entries),
        "recent_transition_kind_counts": transition_kind_counts,
        "recent_to_intervention_status_counts": to_intervention_status_counts,
        "top_transition_kind": top_transition_kind,
        "top_to_intervention_status": top_to_intervention_status,
        "last_event_at": _coerce_optional_text(last_entry.get("generated_at")),
        "last_event_session_id": _coerce_optional_text(last_entry.get("session_id")),
        "last_transition_kind": _coerce_optional_text(last_entry.get("transition_kind")),
        "last_to_intervention_status": _coerce_optional_text(last_entry.get("to_intervention_status")),
        "last_to_intervention_priority": _coerce_optional_text(last_entry.get("to_intervention_priority")),
        "last_to_final_guidance_label": _coerce_optional_text(last_entry.get("to_final_guidance_label")),
        "last_to_final_guidance_priority": _coerce_optional_text(last_entry.get("to_final_guidance_priority")),
        "last_to_final_guidance_message": _coerce_optional_text(last_entry.get("to_final_guidance_message")),
    }


def _hybrid_collection_unresolved_escalation_window_summary(
    escalation_summary: dict[str, Any],
    recovery_summary: dict[str, Any],
) -> dict[str, Any]:
    escalation_summary = _coerce_optional_mapping(escalation_summary)
    recovery_summary = _coerce_optional_mapping(recovery_summary)
    escalation_available = _coerce_optional_bool(escalation_summary.get("available")) is True
    recovery_available = _coerce_optional_bool(recovery_summary.get("available")) is True
    if not escalation_available and not recovery_available:
        return {
            "available": False,
            "window_status": "no_escalation_history",
            "window_open": False,
            "last_escalation_at": None,
            "last_escalation_policy_status": None,
            "last_recovery_at": None,
            "last_recovery_to_policy_status": None,
            "current_window_duration_seconds": None,
            "current_window_duration_minutes": None,
        }

    last_escalation_at = _coerce_optional_text(escalation_summary.get("last_event_at"))
    last_recovery_at = _coerce_optional_text(recovery_summary.get("last_event_at"))
    last_escalation_policy_status = _coerce_optional_text(escalation_summary.get("top_policy_status"))
    last_recovery_to_policy_status = _coerce_optional_text(recovery_summary.get("last_to_policy_status"))
    duration_seconds = None
    duration_minutes = None
    try:
        if last_escalation_at:
            escalation_dt = datetime.datetime.strptime(str(last_escalation_at), "%Y-%m-%d %H:%M:%S")
            duration_seconds = int((datetime.datetime.now() - escalation_dt).total_seconds())
            duration_minutes = round(duration_seconds / 60, 2)
            if duration_seconds < 0:
                duration_seconds = None
                duration_minutes = None
    except Exception:
        duration_seconds = None
        duration_minutes = None

    if escalation_available and (not recovery_available or str(last_escalation_at or "") > str(last_recovery_at or "")):
        return {
            "available": True,
            "window_status": "open",
            "window_open": True,
            "last_escalation_at": last_escalation_at,
            "last_escalation_policy_status": last_escalation_policy_status,
            "last_recovery_at": last_recovery_at,
            "last_recovery_to_policy_status": last_recovery_to_policy_status,
            "current_window_duration_seconds": duration_seconds,
            "current_window_duration_minutes": duration_minutes,
        }

    return {
        "available": True,
        "window_status": "closed",
        "window_open": False,
        "last_escalation_at": last_escalation_at,
        "last_escalation_policy_status": last_escalation_policy_status,
        "last_recovery_at": last_recovery_at,
        "last_recovery_to_policy_status": last_recovery_to_policy_status,
        "current_window_duration_seconds": None,
        "current_window_duration_minutes": None,
    }


def _hybrid_collection_escalation_resolution_trend_summary(
    escalation_summary: dict[str, Any],
    recovery_summary: dict[str, Any],
    unresolved_window_summary: dict[str, Any],
) -> dict[str, Any]:
    escalation_summary = _coerce_optional_mapping(escalation_summary)
    recovery_summary = _coerce_optional_mapping(recovery_summary)
    unresolved_window_summary = _coerce_optional_mapping(unresolved_window_summary)
    escalation_available = _coerce_optional_bool(escalation_summary.get("available")) is True
    recovery_available = _coerce_optional_bool(recovery_summary.get("available")) is True
    if not escalation_available and not recovery_available:
        return {
            "available": False,
            "recent_escalation_count": 0,
            "recent_recovery_count": 0,
            "recent_resolved_count": 0,
            "recent_unresolved_count": 0,
            "recent_resolution_rate": 0.0,
            "window_open": False,
        }

    recent_escalation_count = _coerce_optional_int(escalation_summary.get("recent_event_count")) or 0
    if recent_escalation_count < 0:
        recent_escalation_count = 0
    recent_recovery_count = _coerce_optional_int(recovery_summary.get("recent_recovery_count")) or 0
    if recent_recovery_count < 0:
        recent_recovery_count = 0
    recent_resolved_count = min(recent_escalation_count, recent_recovery_count)
    recent_unresolved_count = max(0, recent_escalation_count - recent_recovery_count)
    resolution_rate = (recent_resolved_count / recent_escalation_count) if recent_escalation_count > 0 else 0.0
    return {
        "available": True,
        "recent_escalation_count": recent_escalation_count,
        "recent_recovery_count": recent_recovery_count,
        "recent_resolved_count": recent_resolved_count,
        "recent_unresolved_count": recent_unresolved_count,
        "recent_resolution_rate": resolution_rate,
        "window_open": _coerce_optional_bool(unresolved_window_summary.get("window_open")) is True,
    }


def _hybrid_collection_escalation_priority_mix_trend_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    escalation_entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_operator_escalation_events.jsonl")
    recovery_entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_operator_escalation_recovery_events.jsonl")
    if not escalation_entries and not recovery_entries:
        return {
            "available": False,
            "recent_escalation_priority_counts": {},
            "recent_resolved_priority_counts": {},
            "recent_unresolved_priority_counts": {},
            "recent_high_priority_escalation_count": 0,
            "recent_high_priority_resolved_count": 0,
            "recent_high_priority_unresolved_count": 0,
            "top_recent_escalation_priority": None,
            "top_recent_resolved_priority": None,
            "top_recent_unresolved_priority": None,
        }

    recent_escalations = escalation_entries[-limit:]
    recent_recoveries = recovery_entries[-limit:]
    escalation_priority_counts: dict[str, int] = {}
    resolved_priority_counts: dict[str, int] = {}
    matched_escalation_indexes: set[int] = set()

    for entry in recent_escalations:
        priority_key = _coerce_optional_text(entry.get("policy_priority"))
        if priority_key is None:
            continue
        escalation_priority_counts[priority_key] = escalation_priority_counts.get(priority_key, 0) + 1

    for recovery_entry in recent_recoveries:
        recovery_at = _coerce_optional_text(recovery_entry.get("generated_at"))
        matched_index = None
        for index in range(len(recent_escalations) - 1, -1, -1):
            if index in matched_escalation_indexes:
                continue
            escalation_at = _coerce_optional_text(recent_escalations[index].get("generated_at"))
            if escalation_at and recovery_at and escalation_at <= recovery_at:
                matched_index = index
                break
        if matched_index is None:
            continue
        matched_escalation_indexes.add(matched_index)
        priority_key = _coerce_optional_text(recent_escalations[matched_index].get("policy_priority"))
        if priority_key is None:
            continue
        resolved_priority_counts[priority_key] = resolved_priority_counts.get(priority_key, 0) + 1

    unresolved_priority_counts: dict[str, int] = {}
    for priority_key, escalation_count in escalation_priority_counts.items():
        unresolved_count = max(0, escalation_count - resolved_priority_counts.get(priority_key, 0))
        if unresolved_count:
            unresolved_priority_counts[priority_key] = unresolved_count

    def _top_priority(counts: dict[str, int]) -> str | None:
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0] if counts else None

    return {
        "available": True,
        "recent_escalation_priority_counts": escalation_priority_counts,
        "recent_resolved_priority_counts": resolved_priority_counts,
        "recent_unresolved_priority_counts": unresolved_priority_counts,
        "recent_high_priority_escalation_count": int(escalation_priority_counts.get("high", 0) or 0),
        "recent_high_priority_resolved_count": int(resolved_priority_counts.get("high", 0) or 0),
        "recent_high_priority_unresolved_count": int(unresolved_priority_counts.get("high", 0) or 0),
        "top_recent_escalation_priority": _top_priority(escalation_priority_counts),
        "top_recent_resolved_priority": _top_priority(resolved_priority_counts),
        "top_recent_unresolved_priority": _top_priority(unresolved_priority_counts),
    }


def _hybrid_collection_lifecycle_state_summary(
    runtime_summary: dict[str, Any],
    recovery_policy: dict[str, Any],
    unresolved_window_summary: dict[str, Any],
    priority_mix_summary: dict[str, Any],
) -> dict[str, Any]:
    runtime_summary = _coerce_optional_mapping(runtime_summary)
    recovery_policy = _coerce_optional_mapping(recovery_policy)
    unresolved_window_summary = _coerce_optional_mapping(unresolved_window_summary)
    priority_mix_summary = _coerce_optional_mapping(priority_mix_summary)
    active_high_priority_unresolved_count = 0
    active_unresolved_priority = None
    priority_hint = "no_active_priority_backlog"
    window_open = _coerce_optional_bool(unresolved_window_summary.get("window_open")) is True
    runtime_available = _coerce_optional_bool(runtime_summary.get("available")) is True
    if window_open:
        active_high_priority_unresolved_count = (
            _coerce_optional_int(priority_mix_summary.get("recent_high_priority_unresolved_count")) or 0
        )
        if active_high_priority_unresolved_count < 0:
            active_high_priority_unresolved_count = 0
        active_unresolved_priority = _coerce_optional_text(priority_mix_summary.get("top_recent_unresolved_priority"))
        if active_high_priority_unresolved_count > 0:
            priority_hint = "high_priority_backlog_present"
        elif active_unresolved_priority:
            priority_hint = "non_high_priority_backlog_present"
        else:
            priority_hint = "unresolved_priority_backlog_present"
    if not runtime_available and not recovery_policy:
        return {
            "available": False,
            "lifecycle_state": "unknown",
            "lifecycle_reason": "no_runtime_signals",
            "recommended_follow_up": "collect_runtime_history",
            "suggested_mode": "hybrid",
            "operator_action_hint": "collect runtime history; suggested mode=hybrid",
            "priority_hint": "no_priority_data",
            "active_unresolved_priority": active_unresolved_priority,
            "active_high_priority_unresolved_count": active_high_priority_unresolved_count,
            "policy_status": None,
            "window_open": False,
        }

    runtime_policy_status = _coerce_optional_text(runtime_summary.get("recovery_policy_status")) or ""
    computed_policy_status = _coerce_optional_text(recovery_policy.get("policy_status")) or ""
    policy_status = runtime_policy_status or computed_policy_status
    runtime_operator_action_hint = _coerce_optional_text(runtime_summary.get("operator_action_hint"))

    def _resolve_action_hint(lifecycle_state: str, suggested_mode: str) -> str:
        if runtime_operator_action_hint is not None:
            return runtime_operator_action_hint
        if lifecycle_state == "escalated":
            if priority_hint == "high_priority_backlog_present":
                return f"inspect unresolved high-priority backlog; suggested mode={suggested_mode}"
            return f"prefer browser and investigate escalation; suggested mode={suggested_mode}"
        if lifecycle_state == "retrial_window_open":
            return f"continue hybrid with budget watch; suggested mode={suggested_mode}"
        if lifecycle_state == "recovering":
            return f"monitor until stable; suggested mode={suggested_mode}"
        if lifecycle_state == "steady":
            return f"keep hybrid; suggested mode={suggested_mode}"
        return f"collect runtime history; suggested mode={suggested_mode}"

    if window_open:
        return {
            "available": True,
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "operator_action_hint": _resolve_action_hint("escalated", "browser"),
            "priority_hint": priority_hint,
            "active_unresolved_priority": active_unresolved_priority,
            "active_high_priority_unresolved_count": active_high_priority_unresolved_count,
            "policy_status": policy_status or None,
            "window_open": True,
        }
    if policy_status == "allow_hybrid_retrial":
        return {
            "available": True,
            "lifecycle_state": "retrial_window_open",
            "lifecycle_reason": "hybrid_retrial_budget_active",
            "recommended_follow_up": "continue_hybrid_with_budget_watch",
            "suggested_mode": "hybrid",
            "operator_action_hint": _resolve_action_hint("retrial_window_open", "hybrid"),
            "priority_hint": priority_hint,
            "active_unresolved_priority": active_unresolved_priority,
            "active_high_priority_unresolved_count": active_high_priority_unresolved_count,
            "policy_status": policy_status,
            "window_open": False,
        }
    if policy_status == "monitor_hybrid_recovery":
        return {
            "available": True,
            "lifecycle_state": "recovering",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "operator_action_hint": _resolve_action_hint("recovering", "hybrid"),
            "priority_hint": priority_hint,
            "active_unresolved_priority": active_unresolved_priority,
            "active_high_priority_unresolved_count": active_high_priority_unresolved_count,
            "policy_status": policy_status,
            "window_open": False,
        }
    return {
        "available": True,
        "lifecycle_state": "steady",
        "lifecycle_reason": "browserless_fast_path_stable",
        "recommended_follow_up": "keep_hybrid",
        "suggested_mode": "hybrid",
        "operator_action_hint": _resolve_action_hint("steady", "hybrid"),
        "priority_hint": priority_hint,
        "active_unresolved_priority": active_unresolved_priority,
        "active_high_priority_unresolved_count": active_high_priority_unresolved_count,
        "policy_status": policy_status or "steady_hybrid",
        "window_open": False,
    }


def _hybrid_collection_action_hint_consistency_summary(
    runtime_summary: dict[str, Any],
    lifecycle_summary: dict[str, Any],
) -> dict[str, Any]:
    runtime_summary = _coerce_optional_mapping(runtime_summary)
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    runtime_hint = runtime_summary.get("operator_action_hint")
    lifecycle_hint = lifecycle_summary.get("operator_action_hint")
    available = (
        _coerce_optional_bool(runtime_summary.get("available")) is True
        or _coerce_optional_bool(lifecycle_summary.get("available")) is True
    )
    if not available:
        return {
            "available": False,
            "runtime_operator_action_hint": None,
            "lifecycle_operator_action_hint": None,
            "hints_match": False,
            "consistency_status": "no_hint_available",
            "drift_reason": None,
            "consistency_severity": "info",
            "severity_reason": None,
            "hint_source_preference": None,
            "preferred_hint_source_detail": None,
            "preferred_hint_explanation": None,
            "preferred_operator_action_hint": None,
        }

    runtime_hint_str = _coerce_optional_text(runtime_hint)
    lifecycle_hint_str = _coerce_optional_text(lifecycle_hint)
    if runtime_hint_str and lifecycle_hint_str and runtime_hint_str == lifecycle_hint_str:
        consistency_status = "aligned"
        hints_match = True
        drift_reason = None
        consistency_severity = "info"
        severity_reason = "aligned_hints"
        hint_source_preference = "runtime_preferred"
        preferred_hint_source_detail = "runtime_aligned"
        preferred_hint_explanation = "Runtime and lifecycle action hints are aligned; using the runtime-preferred hint."
    elif runtime_hint_str and lifecycle_hint_str:
        consistency_status = "mismatch"
        hints_match = False
        drift_reason = "value_mismatch"
        consistency_severity = "high"
        severity_reason = "conflicting_runtime_and_lifecycle_hints"
        hint_source_preference = "runtime_preferred"
        preferred_hint_source_detail = "runtime_mismatch_wins"
        preferred_hint_explanation = "Runtime and lifecycle action hints conflict; using the runtime-preferred hint."
    elif runtime_hint_str:
        consistency_status = "runtime_only"
        hints_match = False
        drift_reason = "lifecycle_missing"
        consistency_severity = "warning"
        severity_reason = "lifecycle_missing_runtime_only"
        hint_source_preference = "runtime_preferred"
        preferred_hint_source_detail = "runtime_only_available"
        preferred_hint_explanation = "Lifecycle action hint is missing; using the runtime-only hint."
    elif lifecycle_hint_str:
        consistency_status = "lifecycle_only"
        hints_match = False
        drift_reason = "runtime_missing"
        consistency_severity = "warning"
        severity_reason = "runtime_missing_lifecycle_fallback"
        hint_source_preference = "lifecycle_preferred"
        preferred_hint_source_detail = "lifecycle_fallback_used"
        preferred_hint_explanation = "Runtime action hint is missing; using the lifecycle fallback hint."
    else:
        consistency_status = "no_hint_available"
        hints_match = False
        drift_reason = None
        consistency_severity = "info"
        severity_reason = None
        hint_source_preference = None
        preferred_hint_source_detail = None
        preferred_hint_explanation = None

    return {
        "available": True,
        "runtime_operator_action_hint": runtime_hint_str,
        "lifecycle_operator_action_hint": lifecycle_hint_str,
        "hints_match": hints_match,
        "consistency_status": consistency_status,
        "drift_reason": drift_reason,
        "consistency_severity": consistency_severity,
        "severity_reason": severity_reason,
        "hint_source_preference": hint_source_preference,
        "preferred_hint_source_detail": preferred_hint_source_detail,
        "preferred_hint_explanation": preferred_hint_explanation,
        "preferred_operator_action_hint": runtime_hint_str or lifecycle_hint_str,
    }


def _hybrid_collection_operator_intervention_policy_summary(
    lifecycle_summary: dict[str, Any],
    action_hint_consistency_summary: dict[str, Any],
    resolution_trend_summary: dict[str, Any],
    recovery_latency_summary: dict[str, Any],
) -> dict[str, Any]:
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    action_hint_consistency_summary = _coerce_optional_mapping(action_hint_consistency_summary)
    resolution_trend_summary = _coerce_optional_mapping(resolution_trend_summary)
    recovery_latency_summary = _coerce_optional_mapping(recovery_latency_summary)
    available = (
        _coerce_optional_bool(lifecycle_summary.get("available")) is True
        or _coerce_optional_bool(action_hint_consistency_summary.get("available")) is True
    )
    if not available:
        return {
            "available": False,
            "intervention_status": "unknown",
            "intervention_required": False,
            "intervention_priority": "info",
            "intervention_reason": "no_runtime_signals",
            "preferred_operator_action_hint": None,
            "suggested_mode": None,
            "lifecycle_state": None,
            "window_open": False,
            "active_high_priority_unresolved_count": 0,
            "hint_consistency_status": None,
            "hint_consistency_severity": None,
            "resolution_trend_available": False,
            "recent_unresolved_count": 0,
            "recent_resolution_rate": 0.0,
            "recovery_latency_available": False,
            "last_recovery_latency_minutes": None,
        }

    lifecycle_state = _coerce_optional_text(lifecycle_summary.get("lifecycle_state")) or "unknown"
    lifecycle_reason = _coerce_optional_text(lifecycle_summary.get("lifecycle_reason"))
    if lifecycle_reason is None:
        if lifecycle_state == "escalated":
            lifecycle_reason = "unresolved_escalation_window_open"
        elif lifecycle_state == "retrial_window_open":
            lifecycle_reason = "hybrid_retrial_budget_active"
        elif lifecycle_state == "recovering":
            lifecycle_reason = "recovery_policy_monitoring_active"
        elif lifecycle_state == "steady":
            lifecycle_reason = "browserless_fast_path_stable"
        else:
            lifecycle_reason = "no_runtime_signals"
    priority_hint = _coerce_optional_text(lifecycle_summary.get("priority_hint")) or ""
    active_high_priority_unresolved_count = (
        _coerce_optional_int(lifecycle_summary.get("active_high_priority_unresolved_count")) or 0
    )
    if active_high_priority_unresolved_count < 0:
        active_high_priority_unresolved_count = 0
    suggested_mode = _coerce_optional_text(lifecycle_summary.get("suggested_mode"))
    if suggested_mode is None:
        if lifecycle_state == "escalated":
            suggested_mode = "browser"
        elif lifecycle_state in {"retrial_window_open", "recovering", "steady"}:
            suggested_mode = "hybrid"
    preferred_operator_action_hint = _coerce_optional_text(
        action_hint_consistency_summary.get("preferred_operator_action_hint")
    )
    if preferred_operator_action_hint is None:
        preferred_operator_action_hint = _coerce_optional_text(lifecycle_summary.get("operator_action_hint"))
    hint_consistency_status = _coerce_optional_text(action_hint_consistency_summary.get("consistency_status"))
    hint_consistency_severity = _coerce_optional_text(action_hint_consistency_summary.get("consistency_severity"))
    resolution_trend_available = _coerce_optional_bool(resolution_trend_summary.get("available")) is True
    recovery_latency_available = _coerce_optional_bool(recovery_latency_summary.get("available")) is True
    recent_unresolved_count = _coerce_optional_int(resolution_trend_summary.get("recent_unresolved_count")) or 0
    if recent_unresolved_count < 0:
        recent_unresolved_count = 0
    recent_resolution_rate = _coerce_optional_float(resolution_trend_summary.get("recent_resolution_rate")) or 0.0
    if recent_resolution_rate < 0:
        recent_resolution_rate = 0.0
    elif recent_resolution_rate > 1:
        recent_resolution_rate = 1.0
    last_recovery_latency_minutes = _coerce_optional_float(recovery_latency_summary.get("last_recovery_latency_minutes"))
    if last_recovery_latency_minutes is not None and last_recovery_latency_minutes < 0:
        last_recovery_latency_minutes = None
    window_open = _coerce_optional_bool(lifecycle_summary.get("window_open")) is True

    if lifecycle_state == "escalated" and priority_hint == "high_priority_backlog_present" and active_high_priority_unresolved_count > 0:
        intervention_status = "intervention_required"
        intervention_required = True
        intervention_priority = "high"
        intervention_reason = "high_priority_unresolved_escalation_backlog"
    elif lifecycle_state == "escalated":
        intervention_status = "intervention_required"
        intervention_required = True
        intervention_priority = "warning"
        intervention_reason = "unresolved_escalation_window_open"
    elif hint_consistency_severity == "high":
        intervention_status = "attention_required"
        intervention_required = False
        intervention_priority = "warning"
        intervention_reason = "conflicting_runtime_and_lifecycle_hints"
    elif lifecycle_state in {"recovering", "retrial_window_open"}:
        intervention_status = "monitor"
        intervention_required = False
        intervention_priority = "warning"
        intervention_reason = lifecycle_reason
    elif lifecycle_state == "steady":
        intervention_status = "ready"
        intervention_required = False
        intervention_priority = "info"
        intervention_reason = lifecycle_reason
    else:
        intervention_status = "unknown"
        intervention_required = False
        intervention_priority = "info"
        intervention_reason = lifecycle_reason

    return {
        "available": True,
        "intervention_status": intervention_status,
        "intervention_required": intervention_required,
        "intervention_priority": intervention_priority,
        "intervention_reason": intervention_reason,
        "preferred_operator_action_hint": preferred_operator_action_hint,
        "suggested_mode": suggested_mode,
        "lifecycle_state": lifecycle_state,
        "window_open": window_open,
        "active_high_priority_unresolved_count": active_high_priority_unresolved_count,
        "hint_consistency_status": hint_consistency_status,
        "hint_consistency_severity": hint_consistency_severity,
        "resolution_trend_available": resolution_trend_available,
        "recent_unresolved_count": recent_unresolved_count,
        "recent_resolution_rate": recent_resolution_rate,
        "recovery_latency_available": recovery_latency_available,
        "last_recovery_latency_minutes": last_recovery_latency_minutes,
    }


def _hybrid_collection_operator_intervention_stability_summary(
    intervention_trend_summary: dict[str, Any],
) -> dict[str, Any]:
    intervention_trend_summary = _coerce_optional_mapping(intervention_trend_summary)
    if _coerce_optional_bool(intervention_trend_summary.get("available")) is not True:
        return {
            "available": False,
            "stability_status": "unknown",
            "stability_severity": "info",
            "current_intervention_status": None,
            "previous_intervention_status": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": None,
            "stability_action_hint": None,
        }

    current_status = _coerce_optional_text(intervention_trend_summary.get("current_intervention_status"))
    previous_status = _coerce_optional_text(intervention_trend_summary.get("previous_distinct_intervention_status"))
    recent_change_count = _coerce_optional_int(intervention_trend_summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    last_change_at = _coerce_optional_text(intervention_trend_summary.get("last_change_at"))

    if current_status == "intervention_required" and recent_change_count > 0 and previous_status:
        stability_status = "escalating"
        stability_severity = "high"
        operator_readable_explanation = (
            f"Intervention escalated from {previous_status} to intervention_required recently."
        )
        stability_action_hint = "prefer browser and investigate escalating intervention"
    elif current_status == "ready" and recent_change_count == 0:
        stability_status = "stable_ready"
        stability_severity = "info"
        operator_readable_explanation = "Intervention remains ready with no recent status changes."
        stability_action_hint = "keep hybrid and continue monitoring"
    elif current_status == "intervention_required" and recent_change_count == 0:
        stability_status = "persistent_intervention_required"
        stability_severity = "high"
        operator_readable_explanation = "Intervention remains required with no recent status changes."
        stability_action_hint = "treat as sustained intervention and investigate backlog"
    elif recent_change_count >= 2:
        stability_status = "flapping"
        stability_severity = "warning"
        operator_readable_explanation = "Intervention status changed multiple times recently."
        stability_action_hint = "pause automation and inspect instability before resuming"
    else:
        stability_status = "transitioning"
        stability_severity = "warning"
        operator_readable_explanation = (
            f"Intervention is transitioning and currently in {current_status}."
            if current_status is not None
            else "Intervention is transitioning."
        )
        stability_action_hint = "monitor until stable before resuming aggressive intervention"

    return {
        "available": True,
        "stability_status": stability_status,
        "stability_severity": stability_severity,
        "current_intervention_status": current_status,
        "previous_intervention_status": previous_status,
        "recent_change_count": recent_change_count,
        "last_change_at": last_change_at,
        "operator_readable_explanation": operator_readable_explanation,
        "stability_action_hint": stability_action_hint,
    }


def _hybrid_collection_operator_final_guidance_summary(
    intervention_policy_summary: dict[str, Any],
    intervention_stability_summary: dict[str, Any],
) -> dict[str, Any]:
    intervention_policy_summary = _coerce_optional_mapping(intervention_policy_summary)
    intervention_stability_summary = _coerce_optional_mapping(intervention_stability_summary)
    available = (
        _coerce_optional_bool(intervention_policy_summary.get("available")) is True
        or _coerce_optional_bool(intervention_stability_summary.get("available")) is True
    )
    if not available:
        return {
            "available": False,
            "guidance_label": None,
            "guidance_priority": None,
            "guidance_message": None,
            "preferred_action_hint": None,
            "suggested_mode": None,
            "intervention_status": None,
            "stability_status": None,
        }

    stability_status = _coerce_optional_text(intervention_stability_summary.get("stability_status")) or ""
    action_hint = _coerce_optional_text(intervention_stability_summary.get("stability_action_hint")) or ""
    intervention_status = _coerce_optional_text(
        intervention_stability_summary.get("current_intervention_status")
    ) or _coerce_optional_text(intervention_policy_summary.get("intervention_status"))
    suggested_mode = _coerce_optional_text(intervention_policy_summary.get("suggested_mode"))
    normalized_action_hint = action_hint.lower()
    if "browser" in normalized_action_hint and stability_status in {"escalating", "persistent_intervention_required"}:
        suggested_mode = "browser"
    elif "hybrid" in normalized_action_hint and not suggested_mode:
        suggested_mode = "hybrid"

    if stability_status == "escalating":
        guidance_label = "Escalating intervention"
        guidance_priority = "high"
    elif stability_status == "persistent_intervention_required":
        guidance_label = "Persistent intervention required"
        guidance_priority = "high"
    elif stability_status == "flapping":
        guidance_label = "Flapping intervention"
        guidance_priority = "warning"
    elif stability_status == "transitioning":
        guidance_label = "Transitioning intervention"
        guidance_priority = "warning"
    elif stability_status == "stable_ready":
        guidance_label = "Stable ready state"
        guidance_priority = "info"
    else:
        guidance_label = "Operator guidance"
        guidance_priority = _coerce_optional_text(
            intervention_policy_summary.get("intervention_priority")
        )

    guidance_message = f"{guidance_label}: {action_hint}." if action_hint else guidance_label
    return {
        "available": True,
        "guidance_label": guidance_label,
        "guidance_priority": guidance_priority,
        "guidance_message": guidance_message,
        "preferred_action_hint": action_hint or None,
        "suggested_mode": suggested_mode,
        "intervention_status": intervention_status,
        "stability_status": stability_status or None,
    }


def _hybrid_collection_operator_digest_summary(
    intervention_policy_summary: dict[str, Any],
    intervention_stability_summary: dict[str, Any],
    final_guidance_summary: dict[str, Any],
    final_guidance_stability_summary: dict[str, Any],
) -> dict[str, Any]:
    intervention_policy_summary = _coerce_optional_mapping(intervention_policy_summary)
    intervention_stability_summary = _coerce_optional_mapping(intervention_stability_summary)
    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
    final_guidance_stability_summary = _coerce_optional_mapping(final_guidance_stability_summary)
    available = any(
        (
            _coerce_optional_bool(intervention_policy_summary.get("available")) is True,
            _coerce_optional_bool(intervention_stability_summary.get("available")) is True,
            _coerce_optional_bool(final_guidance_summary.get("available")) is True,
            _coerce_optional_bool(final_guidance_stability_summary.get("available")) is True,
        )
    )
    if not available:
        return {
            "available": False,
            "digest_status": "unknown",
            "digest_priority": "info",
            "final_guidance_message": None,
            "intervention_status": None,
            "intervention_stability_status": None,
            "final_guidance_stability_status": None,
            "operator_digest_message": None,
        }

    current_guidance_label = _coerce_optional_text(
        final_guidance_stability_summary.get("current_guidance_label")
    ) or _coerce_optional_text(final_guidance_summary.get("guidance_label"))
    current_guidance_priority = _coerce_optional_text(
        final_guidance_stability_summary.get("current_guidance_priority")
    ) or _coerce_optional_text(final_guidance_summary.get("guidance_priority"))
    current_guidance_message = _coerce_optional_text(
        final_guidance_stability_summary.get("current_guidance_message")
    ) or _coerce_optional_text(final_guidance_summary.get("guidance_message"))
    if not current_guidance_priority:
        if current_guidance_label in {"Escalating intervention", "Persistent intervention required"}:
            current_guidance_priority = "high"
        elif current_guidance_label in {"Transitioning intervention", "Flapping intervention"}:
            current_guidance_priority = "warning"
        elif current_guidance_label == "Stable ready state":
            current_guidance_priority = "info"
    intervention_status = _coerce_optional_text(intervention_policy_summary.get("intervention_status"))
    intervention_stability_status = _coerce_optional_text(intervention_stability_summary.get("stability_status"))
    final_guidance_stability_status = _coerce_optional_text(final_guidance_stability_summary.get("stability_status"))
    final_guidance_priority = (
        _coerce_optional_text(current_guidance_priority)
        or _coerce_optional_text(final_guidance_stability_summary.get("stability_severity"))
        or "info"
    )

    guidance_intervention_status = None
    guidance_intervention_stability_status = None
    if current_guidance_label == "Stable ready state":
        guidance_intervention_status = "ready"
        guidance_intervention_stability_status = "stable_ready"
    elif current_guidance_label == "Transitioning intervention":
        guidance_intervention_status = "monitor"
        guidance_intervention_stability_status = "transitioning"
    elif current_guidance_label == "Escalating intervention":
        guidance_intervention_status = "intervention_required"
        guidance_intervention_stability_status = "escalating"
    elif current_guidance_label == "Persistent intervention required":
        guidance_intervention_status = "intervention_required"
        guidance_intervention_stability_status = "persistent_intervention_required"
    elif current_guidance_label == "Flapping intervention":
        guidance_intervention_status = "monitor"
        guidance_intervention_stability_status = "flapping"

    if guidance_intervention_status is not None:
        intervention_status = guidance_intervention_status

    if guidance_intervention_stability_status is not None:
        intervention_stability_status = guidance_intervention_stability_status

    if final_guidance_priority == "high":
        digest_status = "intervention_required"
        digest_priority = "high"
    elif final_guidance_priority == "warning":
        digest_status = "attention_required"
        digest_priority = "warning"
    else:
        digest_status = "ready"
        digest_priority = "info"

    return {
        "available": True,
        "digest_status": digest_status,
        "digest_priority": digest_priority,
        "final_guidance_message": current_guidance_message,
        "intervention_status": intervention_status or current_guidance_label,
        "intervention_stability_status": intervention_stability_status,
        "final_guidance_stability_status": final_guidance_stability_status,
        "operator_digest_message": current_guidance_message,
    }


def _hybrid_collection_recovery_latency_summary(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    escalation_entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_operator_escalation_events.jsonl")
    recovery_entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_operator_escalation_recovery_events.jsonl")
    if not escalation_entries or not recovery_entries:
        return {
            "available": False,
            "last_recovery_at": None,
            "last_recovery_from_policy_status": None,
            "last_recovery_to_policy_status": None,
            "matched_escalation_at": None,
            "matched_escalation_policy_status": None,
            "last_recovery_latency_seconds": None,
            "last_recovery_latency_minutes": None,
        }

    recent_escalations = escalation_entries[-limit:]
    recent_recoveries = recovery_entries[-limit:]
    last_recovery = recent_recoveries[-1]
    recovery_at = _coerce_optional_text(last_recovery.get("generated_at"))
    matched_escalation = None
    matched_escalation_at = None
    for entry in reversed(recent_escalations):
        escalation_at = _coerce_optional_text(entry.get("generated_at"))
        if escalation_at and recovery_at and escalation_at <= recovery_at:
            matched_escalation = entry
            matched_escalation_at = escalation_at
            break
    if matched_escalation is None:
        return {
            "available": False,
            "last_recovery_at": recovery_at,
            "last_recovery_from_policy_status": _coerce_optional_text(last_recovery.get("from_policy_status")),
            "last_recovery_to_policy_status": _coerce_optional_text(last_recovery.get("to_policy_status")),
            "matched_escalation_at": None,
            "matched_escalation_policy_status": None,
            "last_recovery_latency_seconds": None,
            "last_recovery_latency_minutes": None,
        }

    latency_seconds = None
    latency_minutes = None
    try:
        recovery_dt = datetime.datetime.strptime(recovery_at, "%Y-%m-%d %H:%M:%S")
        escalation_dt = datetime.datetime.strptime(matched_escalation_at, "%Y-%m-%d %H:%M:%S")
        latency_seconds = int((recovery_dt - escalation_dt).total_seconds())
        latency_minutes = round(latency_seconds / 60, 2)
        if latency_seconds < 0:
            latency_seconds = None
            latency_minutes = None
    except Exception:
        latency_seconds = None
        latency_minutes = None

    return {
        "available": True,
        "last_recovery_at": recovery_at,
        "last_recovery_from_policy_status": _coerce_optional_text(last_recovery.get("from_policy_status")),
        "last_recovery_to_policy_status": _coerce_optional_text(last_recovery.get("to_policy_status")),
        "matched_escalation_at": matched_escalation_at,
        "matched_escalation_policy_status": _coerce_optional_text(matched_escalation.get("policy_status")),
        "last_recovery_latency_seconds": latency_seconds,
        "last_recovery_latency_minutes": latency_minutes,
    }


def _hybrid_collection_operator_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    guidance_applied_count = _coerce_optional_int(summary.get("guidance_applied_count")) or 0
    if guidance_applied_count < 0:
        guidance_applied_count = 0
    browserless_success_count = _coerce_optional_int(summary.get("browserless_success_count")) or 0
    if browserless_success_count < 0:
        browserless_success_count = 0
    browser_fallback_required_count = _coerce_optional_int(summary.get("browser_fallback_required_count")) or 0
    if browser_fallback_required_count < 0:
        browser_fallback_required_count = 0
    browser_worker_dispatched_count = _coerce_optional_int(summary.get("browser_worker_dispatched_count")) or 0
    if browser_worker_dispatched_count < 0:
        browser_worker_dispatched_count = 0
    last_task_page = _coerce_optional_int(summary.get("last_task_page"))
    if last_task_page is not None and last_task_page < 0:
        last_task_page = None
    return {
        "hybrid_collection_available": _coerce_optional_bool(summary.get("available")) is True,
        "hybrid_collection_runner_mode": _coerce_optional_text(summary.get("runner_mode")),
        "hybrid_collection_requested_mode": _coerce_optional_text(summary.get("requested_mode")),
        "hybrid_collection_effective_mode_source": _coerce_optional_text(summary.get("effective_mode_source")),
        "hybrid_collection_operator_action_hint": _coerce_optional_text(summary.get("operator_action_hint")),
        "hybrid_collection_last_decision": _coerce_optional_text(summary.get("last_decision")),
        "hybrid_collection_last_reason": _coerce_optional_text(summary.get("last_reason")),
        "hybrid_collection_last_effective_mode": _coerce_optional_text(summary.get("last_effective_mode")),
        "hybrid_collection_top_fallback_reason": _coerce_optional_text(summary.get("top_fallback_reason")),
        "hybrid_collection_termination_reason": _coerce_optional_text(summary.get("termination_reason")),
        "hybrid_collection_guidance_applied_count": guidance_applied_count,
        "hybrid_collection_guidance_status": _coerce_optional_text(summary.get("guidance_status")),
        "hybrid_collection_recovery_policy_status": _coerce_optional_text(summary.get("recovery_policy_status")),
        "hybrid_collection_recovery_mode_pin_active": _coerce_optional_bool(
            summary.get("recovery_policy_mode_pin_active")
        )
        is True,
        "hybrid_collection_browserless_success_count": browserless_success_count,
        "hybrid_collection_browser_fallback_required_count": browser_fallback_required_count,
        "hybrid_collection_browser_worker_dispatched_count": browser_worker_dispatched_count,
        "hybrid_collection_last_task_url": _coerce_optional_text(summary.get("last_task_url")),
        "hybrid_collection_last_task_page": last_task_page,
        "hybrid_collection_last_submit_batch_status": _coerce_optional_text(summary.get("last_submit_batch_status")),
        "hybrid_collection_last_submit_progress_status": _coerce_optional_text(
            summary.get("last_submit_progress_status")
        ),
    }


def _hybrid_collection_operator_history_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_runs = _coerce_optional_int(summary.get("recent_runs")) or 0
    if recent_runs < 0:
        recent_runs = 0
    recent_browserless_success_count = _coerce_optional_int(summary.get("recent_browserless_success_count")) or 0
    if recent_browserless_success_count < 0:
        recent_browserless_success_count = 0
    recent_browser_fallback_required_count = (
        _coerce_optional_int(summary.get("recent_browser_fallback_required_count")) or 0
    )
    if recent_browser_fallback_required_count < 0:
        recent_browser_fallback_required_count = 0
    recent_browser_worker_dispatched_count = (
        _coerce_optional_int(summary.get("recent_browser_worker_dispatched_count")) or 0
    )
    if recent_browser_worker_dispatched_count < 0:
        recent_browser_worker_dispatched_count = 0
    recent_browserless_success_rate = _coerce_optional_float(summary.get("recent_browserless_success_rate")) or 0.0
    if recent_browserless_success_rate < 0:
        recent_browserless_success_rate = 0.0
    elif recent_browserless_success_rate > 1:
        recent_browserless_success_rate = 1.0
    return {
        "hybrid_collection_recent_runs": recent_runs,
        "hybrid_collection_recent_browserless_success_count": recent_browserless_success_count,
        "hybrid_collection_recent_browser_fallback_required_count": recent_browser_fallback_required_count,
        "hybrid_collection_recent_browser_worker_dispatched_count": recent_browser_worker_dispatched_count,
        "hybrid_collection_recent_browserless_success_rate": recent_browserless_success_rate,
        "hybrid_collection_recent_top_fallback_reason": _coerce_optional_text(summary.get("recent_top_fallback_reason")),
        "hybrid_collection_recent_top_termination_reason": _coerce_optional_text(
            summary.get("recent_top_termination_reason")
        ),
    }


def _hybrid_collection_operator_action_hint_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    return {
        "hybrid_collection_current_action_hint": _coerce_optional_text(summary.get("current_action_hint")),
        "hybrid_collection_previous_action_hint": _coerce_optional_text(summary.get("previous_distinct_action_hint")),
        "hybrid_collection_action_hint_change_count": recent_change_count,
        "hybrid_collection_action_hint_last_changed_at": _coerce_optional_text(summary.get("last_change_at")),
    }


def _hybrid_collection_operator_final_guidance_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    return {
        "hybrid_collection_current_final_guidance_label": _coerce_optional_text(summary.get("current_guidance_label")),
        "hybrid_collection_current_final_guidance_priority": _coerce_optional_text(
            summary.get("current_guidance_priority")
        ),
        "hybrid_collection_current_final_guidance_message": _coerce_optional_text(
            summary.get("current_guidance_message")
        ),
        "hybrid_collection_previous_final_guidance_message": _coerce_optional_text(
            summary.get("previous_distinct_guidance_message")
        ),
        "hybrid_collection_final_guidance_change_count": recent_change_count,
        "hybrid_collection_final_guidance_last_changed_at": _coerce_optional_text(summary.get("last_change_at")),
    }


def _hybrid_collection_operator_final_guidance_stability_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_final_guidance_stability_status": _coerce_optional_text(summary.get("stability_status")),
        "hybrid_collection_final_guidance_stability_severity": _coerce_optional_text(
            summary.get("stability_severity")
        ),
        "hybrid_collection_final_guidance_stability_explanation": _coerce_optional_text(
            summary.get("operator_readable_explanation")
        ),
    }


def _hybrid_collection_operator_digest_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    return {
        "hybrid_collection_current_digest_status": _coerce_optional_text(summary.get("current_digest_status")),
        "hybrid_collection_current_digest_priority": _coerce_optional_text(summary.get("current_digest_priority")),
        "hybrid_collection_current_digest_message": _coerce_optional_text(summary.get("current_digest_message")),
        "hybrid_collection_previous_digest_message": _coerce_optional_text(
            summary.get("previous_distinct_digest_message")
        ),
        "hybrid_collection_digest_change_count": recent_change_count,
        "hybrid_collection_digest_last_changed_at": _coerce_optional_text(summary.get("last_change_at")),
    }


def _hybrid_collection_operator_digest_stability_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_digest_stability_status": _coerce_optional_text(summary.get("stability_status")),
        "hybrid_collection_digest_stability_severity": _coerce_optional_text(summary.get("stability_severity")),
        "hybrid_collection_digest_stability_explanation": _coerce_optional_text(
            summary.get("operator_readable_explanation")
        ),
    }


def _hybrid_collection_operator_intervention_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    return {
        "hybrid_collection_current_intervention_status": _coerce_optional_text(
            summary.get("current_intervention_status")
        ),
        "hybrid_collection_current_intervention_priority": _coerce_optional_text(
            summary.get("current_intervention_priority")
        ),
        "hybrid_collection_current_intervention_reason": _coerce_optional_text(
            summary.get("current_intervention_reason")
        ),
        "hybrid_collection_previous_intervention_status": _coerce_optional_text(
            summary.get("previous_distinct_intervention_status")
        ),
        "hybrid_collection_intervention_change_count": recent_change_count,
        "hybrid_collection_intervention_last_changed_at": _coerce_optional_text(summary.get("last_change_at")),
    }


def _hybrid_collection_operator_intervention_event_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_event_count = _coerce_optional_int(summary.get("recent_event_count")) or 0
    if recent_event_count < 0:
        recent_event_count = 0
    return {
        "hybrid_collection_recent_intervention_event_count": recent_event_count,
        "hybrid_collection_last_intervention_event_at": _coerce_optional_text(summary.get("last_event_at")),
        "hybrid_collection_last_intervention_transition_kind": _coerce_optional_text(summary.get("last_transition_kind")),
        "hybrid_collection_last_to_intervention_status": _coerce_optional_text(summary.get("last_to_intervention_status")),
        "hybrid_collection_last_to_intervention_priority": _coerce_optional_text(
            summary.get("last_to_intervention_priority")
        ),
        "hybrid_collection_last_to_final_guidance_label": _coerce_optional_text(
            summary.get("last_to_final_guidance_label")
        ),
        "hybrid_collection_last_to_final_guidance_priority": _coerce_optional_text(
            summary.get("last_to_final_guidance_priority")
        ),
        "hybrid_collection_last_to_final_guidance_message": _coerce_optional_text(
            summary.get("last_to_final_guidance_message")
        ),
    }


def _hybrid_collection_operator_intervention_stability_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_intervention_stability_status": _coerce_optional_text(summary.get("stability_status")),
        "hybrid_collection_intervention_stability_severity": _coerce_optional_text(summary.get("stability_severity")),
        "hybrid_collection_intervention_stability_explanation": _coerce_optional_text(
            summary.get("operator_readable_explanation")
        ),
        "hybrid_collection_intervention_stability_action_hint": _coerce_optional_text(
            summary.get("stability_action_hint")
        ),
    }


def _hybrid_collection_operator_intervention_policy_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_operator_intervention_status": _coerce_optional_text(summary.get("intervention_status")),
        "hybrid_collection_operator_intervention_required": _coerce_optional_bool(
            summary.get("intervention_required")
        )
        is True,
        "hybrid_collection_operator_intervention_priority": _coerce_optional_text(
            summary.get("intervention_priority")
        ),
        "hybrid_collection_operator_intervention_reason": _coerce_optional_text(summary.get("intervention_reason")),
        "hybrid_collection_operator_intervention_action_hint": _coerce_optional_text(
            summary.get("preferred_operator_action_hint")
        ),
        "hybrid_collection_operator_intervention_suggested_mode": _coerce_optional_text(summary.get("suggested_mode")),
    }


def _hybrid_collection_operator_final_guidance_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_operator_final_guidance_label": _coerce_optional_text(summary.get("guidance_label")),
        "hybrid_collection_operator_final_guidance_priority": _coerce_optional_text(summary.get("guidance_priority")),
        "hybrid_collection_operator_final_guidance_message": _coerce_optional_text(summary.get("guidance_message")),
    }


def _hybrid_collection_operator_digest_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_operator_digest_status": _coerce_optional_text(summary.get("digest_status")),
        "hybrid_collection_operator_digest_priority": _coerce_optional_text(summary.get("digest_priority")),
        "hybrid_collection_operator_digest_message": _coerce_optional_text(summary.get("operator_digest_message")),
    }


def _hybrid_collection_strategy_guidance(
    latest_summary: dict[str, Any],
    history_summary: dict[str, Any],
) -> dict[str, Any]:
    history_available = _coerce_optional_bool(history_summary.get("available")) is True
    if not history_available:
        return {
            "guidance_status": "no_history_available",
            "priority": "info",
            "recommended_mode": "hybrid",
            "recommended_actions": ["collect_more_hybrid_runtime_history"],
            "top_guidance_reason": "history_unavailable",
        }

    recent_runs = _coerce_optional_int(history_summary.get("recent_runs")) or 0
    success_rate = _coerce_optional_float(history_summary.get("recent_browserless_success_rate")) or 0.0
    if success_rate < 0:
        success_rate = 0.0
    elif success_rate > 1:
        success_rate = 1.0
    fallback_count = _coerce_optional_int(history_summary.get("recent_browser_fallback_required_count")) or 0
    top_fallback_reason = _coerce_optional_text(history_summary.get("recent_top_fallback_reason"))
    top_termination_reason = _coerce_optional_text(history_summary.get("recent_top_termination_reason"))
    last_decision = _coerce_optional_text(latest_summary.get("last_decision"))

    if (
        top_fallback_reason == "challenge_detected"
        and fallback_count >= 2
        and top_termination_reason == "fallback_escalation_threshold_reached"
    ):
        return {
            "guidance_status": "investigate_challenge_spike",
            "priority": "high",
            "recommended_mode": "browser",
            "recommended_actions": [
                "review_challenge_recovery_path",
                "switch_operator_mode_to_browser",
                "inspect_cookie_or_session_stability",
            ],
            "top_guidance_reason": "challenge_detected",
        }

    if (
        recent_runs >= 3
        and fallback_count > 0
        and success_rate < 0.5
    ):
        return {
            "guidance_status": "prefer_browser_fallback",
            "priority": "warning",
            "recommended_mode": "browser",
            "recommended_actions": [
                "prefer_browser_fallback_for_next_runs",
                "review_browserless_failure_reasons",
            ],
            "top_guidance_reason": str(top_fallback_reason or "browserless_low_success_rate"),
        }

    if recent_runs < 3:
        return {
            "guidance_status": "insufficient_history",
            "priority": "info",
            "recommended_mode": "hybrid",
            "recommended_actions": ["collect_more_hybrid_runtime_history"],
            "top_guidance_reason": "insufficient_history",
        }

    if last_decision == "browserless_success" and success_rate >= 0.8:
        return {
            "guidance_status": "keep_hybrid",
            "priority": "info",
            "recommended_mode": "hybrid",
            "recommended_actions": ["keep_browserless_fast_path_enabled"],
            "top_guidance_reason": "browserless_success_stable",
        }

    return {
        "guidance_status": "monitor_hybrid_runtime",
        "priority": "info",
        "recommended_mode": "hybrid",
        "recommended_actions": ["monitor_recent_fallback_reasons"],
        "top_guidance_reason": str(top_fallback_reason or "mixed_runtime_signals"),
    }


def _hybrid_collection_operator_guidance_overview_fields(guidance: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_guidance_status": _coerce_optional_text(guidance.get("guidance_status")),
        "hybrid_collection_guidance_priority": _coerce_optional_text(guidance.get("priority")),
        "hybrid_collection_recommended_mode": _coerce_optional_text(guidance.get("recommended_mode")),
        "hybrid_collection_top_guidance_reason": _coerce_optional_text(guidance.get("top_guidance_reason")),
    }


def _hybrid_collection_operator_mode_switch_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_switch_count = _coerce_optional_int(summary.get("recent_switch_count")) or 0
    if recent_switch_count < 0:
        recent_switch_count = 0
    return {
        "hybrid_collection_recent_mode_switch_count": recent_switch_count,
        "hybrid_collection_top_switch_target_mode": _coerce_optional_text(summary.get("top_target_mode")),
        "hybrid_collection_top_switch_guidance_reason": _coerce_optional_text(summary.get("top_guidance_reason")),
    }


def _hybrid_collection_recovery_policy(
    data_root: Path,
    latest_summary: dict[str, Any],
    history_summary: dict[str, Any],
    guidance: dict[str, Any],
    switch_summary: dict[str, Any],
    recovery_event_summary: dict[str, Any],
) -> dict[str, Any]:
    latest_summary = _coerce_optional_mapping(latest_summary)
    history_summary = _coerce_optional_mapping(history_summary)
    guidance = _coerce_optional_mapping(guidance)
    switch_summary = _coerce_optional_mapping(switch_summary)
    recovery_event_summary = _coerce_optional_mapping(recovery_event_summary)
    guidance_status = _coerce_optional_text(guidance.get("guidance_status"))
    guidance_recommended_mode = _coerce_optional_text(guidance.get("recommended_mode"))
    top_switch_target_mode = _coerce_optional_text(switch_summary.get("top_target_mode"))
    top_switch_guidance_reason = _coerce_optional_text(switch_summary.get("top_guidance_reason"))
    last_switch_at = _coerce_optional_text(switch_summary.get("last_switch_at"))
    recent_switch_count = _coerce_optional_int(switch_summary.get("recent_switch_count")) or 0
    if recent_switch_count < 0:
        recent_switch_count = 0
    recent_browserless_success_rate = _coerce_optional_float(history_summary.get("recent_browserless_success_rate")) or 0.0
    if recent_browserless_success_rate < 0:
        recent_browserless_success_rate = 0.0
    elif recent_browserless_success_rate > 1:
        recent_browserless_success_rate = 1.0
    history_available = _coerce_optional_bool(history_summary.get("available")) is True
    if not history_available:
        return {
            "policy_status": "no_history_available",
            "priority": "info",
            "effective_recommended_mode": guidance_recommended_mode or "hybrid",
            "mode_pin_active": False,
            "recommended_actions": ["collect_more_hybrid_runtime_history"],
            "top_policy_reason": "history_unavailable",
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_recommended_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": recent_browserless_success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
        }

    guidance_mode = guidance_recommended_mode or "hybrid"
    guidance_priority = _coerce_optional_text(guidance.get("priority")) or "info"
    success_rate = recent_browserless_success_rate
    top_policy_reason = top_switch_guidance_reason or _coerce_optional_text(guidance.get("top_guidance_reason")) or "mixed_runtime_signals"
    last_recovery_transition_kind = _coerce_optional_text(recovery_event_summary.get("last_transition_kind"))
    last_recovery_to_policy_status = _coerce_optional_text(recovery_event_summary.get("last_to_policy_status"))
    last_recovery_transition_at = _coerce_optional_text(recovery_event_summary.get("last_transition_at"))
    last_decision = _coerce_optional_text(latest_summary.get("last_decision")) or ""
    last_reason = _coerce_optional_text(latest_summary.get("last_reason")) or ""
    recovery_transition_kind_counts = _coerce_optional_mapping(
        recovery_event_summary.get("recent_transition_kind_counts")
    )
    pin_released_count = _coerce_optional_int(recovery_transition_kind_counts.get("pin_released")) or 0
    pin_activated_count = _coerce_optional_int(recovery_transition_kind_counts.get("pin_activated")) or 0

    budget_total = 1
    budget_attempts_used = 0
    if last_recovery_transition_kind == "pin_released" and last_recovery_transition_at:
        history_entries = _load_jsonl_snapshots(data_root / "avm" / "hybrid_seed_collection_runtime_history.jsonl")
        for entry in history_entries:
            generated_at = _coerce_optional_text(entry.get("generated_at"))
            if not generated_at or generated_at <= last_recovery_transition_at:
                continue
            decision_counts = _coerce_optional_mapping(entry.get("decision_counts"))
            browserless_success_count = _coerce_optional_int(decision_counts.get("browserless_success")) or 0
            if browserless_success_count < 0:
                browserless_success_count = 0
            browser_fallback_required_count = _coerce_optional_int(
                decision_counts.get("browser_fallback_required")
            ) or 0
            if browser_fallback_required_count < 0:
                browser_fallback_required_count = 0
            budget_attempts_used += browserless_success_count
            budget_attempts_used += browser_fallback_required_count
        latest_generated_at = _coerce_optional_text(latest_summary.get("generated_at"))
        if (
            budget_attempts_used == 0
            and latest_generated_at
            and latest_generated_at > last_recovery_transition_at
            and last_decision in {"browserless_success", "browser_fallback_required"}
        ):
            budget_attempts_used = 1
    budget_remaining = max(0, budget_total - budget_attempts_used)

    common_policy_fields = {
        "hybrid_retrial_budget_total": budget_total,
        "hybrid_retrial_attempts_used": budget_attempts_used,
        "hybrid_retrial_budget_remaining": budget_remaining,
        "last_recovery_transition_kind": last_recovery_transition_kind,
        "last_recovery_transition_at": last_recovery_transition_at,
    }

    if (
        pin_released_count >= 2
        and pin_activated_count >= 2
        and last_decision == "browser_fallback_required"
        and last_reason == "challenge_detected"
    ):
        return {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "recommended_actions": [
                "investigate_repeated_repin_cycle",
                "keep_browser_mode_pinned",
                "inspect_session_recovery_stability",
            ],
            "top_policy_reason": "repeated_repin_cycle_detected",
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
            **common_policy_fields,
        }

    if (
        last_recovery_transition_kind == "pin_released"
        and last_recovery_to_policy_status == "allow_hybrid_retrial"
        and last_decision == "browser_fallback_required"
        and last_reason == "challenge_detected"
    ):
        return {
            "policy_status": "re_pin_browser_mode_temporarily",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "recommended_actions": [
                "re_pin_browser_mode",
                "stop_immediate_hybrid_retrial",
                "review_challenge_recovery_path",
            ],
            "top_policy_reason": "challenge_detected_after_release",
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
            **common_policy_fields,
        }

    if recent_switch_count >= 2 and top_switch_target_mode == "browser" and guidance_mode == "browser":
        return {
            "policy_status": "pin_browser_mode_temporarily",
            "priority": "high" if guidance_priority == "high" else "warning",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "recommended_actions": [
                "keep_browser_mode_pinned",
                "review_browserless_recovery_before_retry",
            ],
            "top_policy_reason": top_policy_reason,
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
            **common_policy_fields,
        }

    if recent_switch_count >= 1 and top_switch_target_mode == "browser" and guidance_mode == "hybrid" and success_rate >= 0.8:
        return {
            "policy_status": "allow_hybrid_retrial",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "recommended_actions": [
                "allow_hybrid_retrial",
                "continue_monitoring_mode_switch_events",
            ],
            "top_policy_reason": "browser_recovery_window_stabilized",
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
            **common_policy_fields,
        }

    if guidance_mode == "browser":
        return {
            "policy_status": "follow_browser_guidance",
            "priority": guidance_priority,
            "effective_recommended_mode": "browser",
            "mode_pin_active": False,
            "recommended_actions": list(guidance.get("recommended_actions") or ["follow_browser_guidance"]),
            "top_policy_reason": top_policy_reason,
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
            **common_policy_fields,
        }

    if guidance_mode == "hybrid" and recent_switch_count == 0:
        return {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "recommended_actions": ["keep_browserless_fast_path_enabled"],
            "top_policy_reason": _coerce_optional_text(guidance.get("top_guidance_reason")) or "hybrid_stable",
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
            **common_policy_fields,
        }

    return {
        "policy_status": "monitor_hybrid_recovery",
        "priority": "info",
        "effective_recommended_mode": guidance_mode,
        "mode_pin_active": False,
        "recommended_actions": ["continue_monitoring_mode_switch_events"],
        "top_policy_reason": top_policy_reason,
        "guidance_status": guidance_status,
        "guidance_recommended_mode": guidance_mode,
        "recent_mode_switch_count": recent_switch_count,
        "recent_browserless_success_rate": success_rate,
        "top_switch_target_mode": top_switch_target_mode,
        "top_switch_guidance_reason": top_switch_guidance_reason,
        "last_switch_at": last_switch_at,
        **common_policy_fields,
    }


def _hybrid_collection_operator_recovery_policy_overview_fields(policy: dict[str, Any]) -> dict[str, Any]:
    budget_remaining = _coerce_optional_int(policy.get("hybrid_retrial_budget_remaining")) or 0
    if budget_remaining < 0:
        budget_remaining = 0
    return {
        "hybrid_collection_recovery_policy_status": _coerce_optional_text(policy.get("policy_status")),
        "hybrid_collection_recovery_policy_priority": _coerce_optional_text(policy.get("priority")),
        "hybrid_collection_recovery_effective_mode": _coerce_optional_text(policy.get("effective_recommended_mode")),
        "hybrid_collection_recovery_mode_pin_active": _coerce_optional_bool(policy.get("mode_pin_active")) is True,
        "hybrid_collection_recovery_top_policy_reason": _coerce_optional_text(policy.get("top_policy_reason")),
        "hybrid_collection_recovery_budget_remaining": budget_remaining,
        "hybrid_collection_recovery_last_transition_kind": _coerce_optional_text(
            policy.get("last_recovery_transition_kind")
        ),
    }


def _hybrid_collection_operator_recovery_policy_event_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_transition_count = _coerce_optional_int(summary.get("recent_transition_count")) or 0
    if recent_transition_count < 0:
        recent_transition_count = 0
    return {
        "hybrid_collection_recent_recovery_policy_transition_count": recent_transition_count,
        "hybrid_collection_last_recovery_transition_kind": _coerce_optional_text(summary.get("last_transition_kind")),
        "hybrid_collection_last_recovery_to_policy_status": _coerce_optional_text(summary.get("last_to_policy_status")),
    }


def _hybrid_collection_operator_escalation_event_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_event_count = _coerce_optional_int(summary.get("recent_event_count")) or 0
    if recent_event_count < 0:
        recent_event_count = 0
    return {
        "hybrid_collection_recent_operator_escalation_count": recent_event_count,
        "hybrid_collection_top_operator_escalation_kind": _coerce_optional_text(summary.get("top_escalation_kind")),
        "hybrid_collection_top_operator_escalation_source": _coerce_optional_text(
            summary.get("top_operator_escalation_source")
        ),
        "hybrid_collection_top_operator_escalation_policy_status": _coerce_optional_text(
            summary.get("top_policy_status")
        ),
        "hybrid_collection_last_operator_escalation_source": _coerce_optional_text(
            summary.get("last_operator_escalation_source")
        ),
        "hybrid_collection_last_operator_escalation_audit_message": _coerce_optional_text(
            summary.get("last_operator_escalation_audit_message")
        ),
    }


def _hybrid_collection_operator_escalation_event_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_source_change_count = _coerce_optional_int(summary.get("recent_source_change_count")) or 0
    if recent_source_change_count < 0:
        recent_source_change_count = 0
    return {
        "hybrid_collection_current_operator_escalation_source": _coerce_optional_text(
            summary.get("current_operator_escalation_source")
        ),
        "hybrid_collection_previous_operator_escalation_source": _coerce_optional_text(
            summary.get("previous_distinct_operator_escalation_source")
        ),
        "hybrid_collection_operator_escalation_source_change_count": recent_source_change_count,
        "hybrid_collection_operator_escalation_source_last_changed_at": _coerce_optional_text(
            summary.get("last_source_change_at")
        ),
    }


def _hybrid_collection_operator_escalation_event_stability_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_operator_escalation_source_stability_status": _coerce_optional_text(
            summary.get("stability_status")
        ),
        "hybrid_collection_operator_escalation_source_stability_severity": _coerce_optional_text(
            summary.get("stability_severity")
        ),
        "hybrid_collection_operator_escalation_source_stability_explanation": _coerce_optional_text(
            summary.get("operator_readable_explanation")
        ),
    }


def _hybrid_collection_operator_escalation_recovery_event_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_recovery_count = _coerce_optional_int(summary.get("recent_recovery_count")) or 0
    if recent_recovery_count < 0:
        recent_recovery_count = 0
    return {
        "hybrid_collection_recent_operator_escalation_recovery_count": recent_recovery_count,
        "hybrid_collection_last_operator_escalation_recovery_policy_status": _coerce_optional_text(
            summary.get("last_to_policy_status")
        ),
    }


def _hybrid_collection_operator_unresolved_escalation_window_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    window_open = _coerce_optional_bool(summary.get("window_open")) is True
    duration_seconds = _coerce_optional_int(summary.get("current_window_duration_seconds"))
    if duration_seconds is not None and duration_seconds < 0:
        duration_seconds = None
    duration_minutes = _coerce_optional_float(summary.get("current_window_duration_minutes"))
    if duration_minutes is not None and duration_minutes < 0:
        duration_minutes = None
    return {
        "hybrid_collection_unresolved_escalation_window_open": window_open,
        "hybrid_collection_unresolved_escalation_policy_status": (
            _coerce_optional_text(summary.get("last_escalation_policy_status"))
            if window_open
            else _coerce_optional_text(summary.get("last_recovery_to_policy_status"))
        ),
        "hybrid_collection_unresolved_escalation_last_event_at": (
            _coerce_optional_text(summary.get("last_escalation_at"))
            if window_open
            else _coerce_optional_text(summary.get("last_recovery_at"))
        ),
        "hybrid_collection_unresolved_escalation_duration_seconds": duration_seconds,
        "hybrid_collection_unresolved_escalation_duration_minutes": duration_minutes,
    }


def _hybrid_collection_operator_lifecycle_state_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    active_high_priority_unresolved_count = _coerce_optional_int(summary.get("active_high_priority_unresolved_count"))
    if active_high_priority_unresolved_count is None or active_high_priority_unresolved_count < 0:
        active_high_priority_unresolved_count = 0
    return {
        "hybrid_collection_lifecycle_state": _coerce_optional_text(summary.get("lifecycle_state")),
        "hybrid_collection_lifecycle_reason": _coerce_optional_text(summary.get("lifecycle_reason")),
        "hybrid_collection_lifecycle_follow_up": _coerce_optional_text(summary.get("recommended_follow_up")),
        "hybrid_collection_lifecycle_suggested_mode": _coerce_optional_text(summary.get("suggested_mode")),
        "hybrid_collection_lifecycle_action_hint": _coerce_optional_text(summary.get("operator_action_hint")),
        "hybrid_collection_lifecycle_priority_hint": _coerce_optional_text(summary.get("priority_hint")),
        "hybrid_collection_lifecycle_active_unresolved_priority": _coerce_optional_text(
            summary.get("active_unresolved_priority")
        ),
        "hybrid_collection_lifecycle_active_high_priority_unresolved_count": active_high_priority_unresolved_count,
    }


def _hybrid_collection_operator_action_hint_consistency_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_action_hint_consistency_status": _coerce_optional_text(summary.get("consistency_status")),
        "hybrid_collection_action_hint_hints_match": _coerce_optional_bool(summary.get("hints_match")) is True,
        "hybrid_collection_action_hint_drift_reason": _coerce_optional_text(summary.get("drift_reason")),
        "hybrid_collection_action_hint_consistency_severity": _coerce_optional_text(
            summary.get("consistency_severity")
        ),
        "hybrid_collection_action_hint_severity_reason": _coerce_optional_text(summary.get("severity_reason")),
        "hybrid_collection_action_hint_source_preference": _coerce_optional_text(
            summary.get("hint_source_preference")
        ),
        "hybrid_collection_action_hint_source_detail": _coerce_optional_text(
            summary.get("preferred_hint_source_detail")
        ),
        "hybrid_collection_action_hint_explanation": _coerce_optional_text(
            summary.get("preferred_hint_explanation")
        ),
        "hybrid_collection_preferred_action_hint": _coerce_optional_text(summary.get("preferred_operator_action_hint")),
    }


def _hybrid_collection_operator_recovery_latency_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    latency_seconds = _coerce_optional_int(summary.get("last_recovery_latency_seconds"))
    if latency_seconds is not None and latency_seconds < 0:
        latency_seconds = None
    latency_minutes = _coerce_optional_float(summary.get("last_recovery_latency_minutes"))
    if latency_minutes is not None and latency_minutes < 0:
        latency_minutes = None
    return {
        "hybrid_collection_last_recovery_latency_seconds": latency_seconds,
        "hybrid_collection_last_recovery_latency_minutes": latency_minutes,
        "hybrid_collection_last_recovery_latency_from_policy_status": _coerce_optional_text(
            summary.get("last_recovery_from_policy_status")
        ),
        "hybrid_collection_last_recovery_latency_to_policy_status": _coerce_optional_text(
            summary.get("last_recovery_to_policy_status")
        ),
    }


def _hybrid_collection_operator_escalation_resolution_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_resolved_count = _coerce_optional_int(summary.get("recent_resolved_count")) or 0
    if recent_resolved_count < 0:
        recent_resolved_count = 0
    recent_unresolved_count = _coerce_optional_int(summary.get("recent_unresolved_count")) or 0
    if recent_unresolved_count < 0:
        recent_unresolved_count = 0
    recent_resolution_rate = _coerce_optional_float(summary.get("recent_resolution_rate")) or 0.0
    if recent_resolution_rate < 0:
        recent_resolution_rate = 0.0
    elif recent_resolution_rate > 1:
        recent_resolution_rate = 1.0
    return {
        "hybrid_collection_recent_escalation_resolved_count": recent_resolved_count,
        "hybrid_collection_recent_escalation_unresolved_count": recent_unresolved_count,
        "hybrid_collection_recent_escalation_resolution_rate": recent_resolution_rate,
    }


def _hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_high_priority_escalation_count = (
        _coerce_optional_int(summary.get("recent_high_priority_escalation_count")) or 0
    )
    if recent_high_priority_escalation_count < 0:
        recent_high_priority_escalation_count = 0
    recent_high_priority_resolved_count = _coerce_optional_int(summary.get("recent_high_priority_resolved_count")) or 0
    if recent_high_priority_resolved_count < 0:
        recent_high_priority_resolved_count = 0
    recent_high_priority_unresolved_count = (
        _coerce_optional_int(summary.get("recent_high_priority_unresolved_count")) or 0
    )
    if recent_high_priority_unresolved_count < 0:
        recent_high_priority_unresolved_count = 0
    return {
        "hybrid_collection_recent_high_priority_escalation_count": recent_high_priority_escalation_count,
        "hybrid_collection_recent_high_priority_resolved_count": recent_high_priority_resolved_count,
        "hybrid_collection_recent_high_priority_unresolved_count": recent_high_priority_unresolved_count,
        "hybrid_collection_top_recent_escalation_priority": _coerce_optional_text(
            summary.get("top_recent_escalation_priority")
        ),
        "hybrid_collection_top_recent_unresolved_priority": _coerce_optional_text(
            summary.get("top_recent_unresolved_priority")
        ),
    }


def _avm_operator_eval_summary(data_root: Path, gate_report_override: dict[str, Any] | None = None) -> dict[str, Any]:
    avm_dir = data_root / "avm"
    gate_report = gate_report_override if isinstance(gate_report_override, dict) else _load_json_snapshot(avm_dir / "release_gate.json")
    evaluation = gate_report.get("evaluation") if isinstance(gate_report.get("evaluation"), dict) else {}
    file_calibration_report = normalize_calibration_targets_payload(_load_json_snapshot(avm_dir / "calibration_targets.json"))
    raw_embedded_calibration_report = (
        evaluation.get("calibration_targets") if isinstance(evaluation.get("calibration_targets"), dict) else {}
    )

    def _merge_calibration_targets(preferred: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        merged = dict(fallback)
        for key, value in preferred.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = _merge_calibration_targets(value, merged[key])
            else:
                merged[key] = value
        return merged

    calibration_report = (
        normalize_calibration_targets_payload(_merge_calibration_targets(raw_embedded_calibration_report, file_calibration_report))
        if raw_embedded_calibration_report
        else file_calibration_report
    )
    guidance = calibration_report.get("guidance") if isinstance(calibration_report.get("guidance"), dict) else {}
    top_calibration_target = calibration_report.get("top_calibration_target")
    if not isinstance(top_calibration_target, dict):
        top_calibration_target = None
    top_calibration_target_hint = calibration_report.get("top_calibration_target_hint")
    if not isinstance(top_calibration_target_hint, dict):
        top_calibration_target_hint = None

    def _serialize_patch_preview(preview_payload: dict[str, Any], *, bundle_id: str | None = None) -> dict[str, Any]:
        return {
            "bundle_id": bundle_id,
            "patch_ready": bool(preview_payload.get("changed_key_count") or 0),
            "applied_filter": preview_payload.get("applied_filter"),
            "matched_targets": list(preview_payload.get("matched_targets") or []),
            "changed_key_count": int(preview_payload.get("changed_key_count") or 0),
            "changed_keys": list(preview_payload.get("changed_keys") or []),
            "changed_paths": dict(preview_payload.get("changed_paths") or {}),
            "rollback_patch": dict(preview_payload.get("rollback_patch") or {}),
        }

    calibration_preview_path = avm_dir / "calibration_targets.json"
    config_preview_path = avm_dir / "config.json"

    def _json_file_is_object(path: Path) -> bool:
        try:
            if not path.exists():
                return False
            payload = json.loads(path.read_text(encoding="utf-8"))
            return isinstance(payload, dict)
        except Exception:
            return False

    use_temp_calibration_path = (
        not calibration_preview_path.exists()
        or calibration_report != file_calibration_report
        or not _json_file_is_object(calibration_preview_path)
    )
    use_temp_config_path = config_preview_path.exists() and not _json_file_is_object(config_preview_path)

    def _build_preview_bundle(config_path: Path, calibration_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        preview_payload = apply_avm_calibration_patch(
            config_path=config_path,
            calibration_path=calibration_path,
            write_back=False,
        )
        top_preview_payload = apply_avm_calibration_patch(
            config_path=config_path,
            calibration_path=calibration_path,
            write_back=False,
            target_type=str(top_calibration_target.get("target_type") or "") if isinstance(top_calibration_target, dict) else None,
            target_name=str(top_calibration_target.get("name") or "") if isinstance(top_calibration_target, dict) else None,
        )
        recommended_bundle = top_calibration_target_hint.get("recommended_bundle") if isinstance(top_calibration_target_hint, dict) and isinstance(top_calibration_target_hint.get("recommended_bundle"), dict) else None
        if recommended_bundle is not None:
            recommended_bundle_preview_payload = apply_avm_calibration_patch(
                config_path=config_path,
                calibration_path=calibration_path,
                write_back=False,
                target_types=list(recommended_bundle.get("target_types") or []),
                target_names=list(recommended_bundle.get("target_names") or []),
            )
        else:
            recommended_bundle_preview_payload = {}
        return preview_payload, top_preview_payload, recommended_bundle_preview_payload

    if use_temp_calibration_path or use_temp_config_path:
        with tempfile.TemporaryDirectory() as tmpdir:
            if use_temp_calibration_path:
                temp_calibration_path = Path(tmpdir) / "calibration_targets.json"
                temp_calibration_path.write_text(json.dumps(calibration_report, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                temp_calibration_path = calibration_preview_path
            if use_temp_config_path:
                temp_config_path = Path(tmpdir) / "config.json"
                temp_config_path.write_text(json.dumps(DEFAULT_AVM_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                temp_config_path = config_preview_path
            preview, top_preview, bundle_preview_payload = _build_preview_bundle(temp_config_path, temp_calibration_path)
    else:
        preview, top_preview, bundle_preview_payload = _build_preview_bundle(config_preview_path, calibration_preview_path)

    recommended_bundle = top_calibration_target_hint.get("recommended_bundle") if isinstance(top_calibration_target_hint, dict) and isinstance(top_calibration_target_hint.get("recommended_bundle"), dict) else None
    if recommended_bundle is not None:
        recommended_bundle_patch_preview = _serialize_patch_preview(
            bundle_preview_payload,
            bundle_id=str(recommended_bundle.get("bundle_id") or ""),
        )
    else:
        recommended_bundle_patch_preview = _serialize_patch_preview({}, bundle_id=None)

    def _bundle_command_summary(top_target_hint_payload: dict | None) -> tuple[str, str, str, str]:
        return summarize_bundle_command_summary(top_target_hint_payload)

    (
        recommended_bundle_preview_command,
        recommended_bundle_write_command,
        recommended_bundle_verify_command,
        recommended_bundle_gate_command,
    ) = _bundle_command_summary(top_calibration_target_hint if isinstance(top_calibration_target_hint, dict) else None)
    recommended_bundle_risk = summarize_patch_risk(recommended_bundle_patch_preview)
    recommended_bundle_next_action = summarize_patch_next_action(recommended_bundle_risk, recommended_bundle_patch_preview)
    next_action_command = summarize_patch_next_action_command(
        recommended_bundle_next_action,
        preview_command=recommended_bundle_preview_command,
        write_command=recommended_bundle_write_command,
    )
    follow_up_command = summarize_patch_follow_up_command(
        recommended_bundle_next_action,
        preview_command=recommended_bundle_preview_command,
        write_command=recommended_bundle_write_command,
        verify_command=recommended_bundle_verify_command,
    )
    command_chain = summarize_patch_command_chain(
        next_action_command=str(next_action_command.get("next_action_command") or ""),
        next_action_command_kind=str(next_action_command.get("next_action_command_kind") or "none"),
        follow_up_command=str(follow_up_command.get("follow_up_command") or ""),
        follow_up_command_kind=str(follow_up_command.get("follow_up_command_kind") or "none"),
        verify_command=recommended_bundle_verify_command,
        gate_command=recommended_bundle_gate_command,
    )
    command_chain = resolve_command_chain_artifacts(command_chain, data_root)
    command_chain = apply_command_chain_next_action_policy(
        command_chain,
        next_action=str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
    )
    return {
        "calibration_guidance": {
            "status": str(guidance.get("status") or "unavailable"),
            "priority": str(guidance.get("priority") or "info"),
            "recommended_actions": list(guidance.get("recommended_actions") or []),
            "top_reason": str(guidance.get("top_reason") or ""),
        },
        "calibration_target_counts": {
            "global_risk": len(calibration_report.get("global_risk_targets") or []),
            "risk_factor": len(calibration_report.get("risk_factor_targets") or []),
            "temporal": len(calibration_report.get("temporal_targets") or []),
            "strategy": len(calibration_report.get("strategy_targets") or []),
        },
        "top_calibration_target": top_calibration_target,
        "top_calibration_target_hint": top_calibration_target_hint,
        "calibration_patch_preview": _serialize_patch_preview(preview),
        "top_calibration_patch_preview": _serialize_patch_preview(top_preview),
        "recommended_bundle_patch_preview": recommended_bundle_patch_preview,
        "recommended_bundle_preview_command": recommended_bundle_preview_command,
        "recommended_bundle_write_command": recommended_bundle_write_command,
        "recommended_bundle_verify_command": recommended_bundle_verify_command,
        "recommended_bundle_gate_command": recommended_bundle_gate_command,
        "recommended_bundle_risk_level": str(recommended_bundle_risk.get("risk_level") or "none"),
        "recommended_bundle_risk_reasons": list(recommended_bundle_risk.get("risk_reasons") or []),
        "recommended_bundle_next_action": str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
        "recommended_bundle_next_action_reasons": list(recommended_bundle_next_action.get("next_action_reasons") or []),
        "recommended_bundle_next_action_command": str(next_action_command.get("next_action_command") or ""),
        "recommended_bundle_next_action_command_kind": str(next_action_command.get("next_action_command_kind") or "none"),
        "recommended_bundle_follow_up_command": str(follow_up_command.get("follow_up_command") or ""),
        "recommended_bundle_follow_up_command_kind": str(follow_up_command.get("follow_up_command_kind") or "none"),
        "recommended_bundle_command_chain": command_chain,
        "coordinate_strategy_watchlist": list(evaluation.get("coordinate_strategy_watchlist") or []),
        "top_coordinate_strategy_group": evaluation.get("top_coordinate_strategy_group"),
    }


def _manual_review_receipt_context(data_root: Path) -> dict:
    avm_dir = data_root / "avm"
    action_effectiveness = load_action_effectiveness_snapshot(avm_dir / "data_supply_optimization_loop.json")
    scheduler_progress = load_optimization_loop_progress_snapshot(avm_dir / "data_supply_optimization_loop.json")
    scheduler_feedback_summary = summarize_scheduler_feedback_snapshot(scheduler_progress)
    recent_gap_report = load_recent_gap_audit_snapshot(avm_dir / "recent_gap_audit.json")
    recoverability_summary = summarize_recoverability_snapshot(recent_gap_report)
    manual_review_backlog_summary = summarize_manual_review_backlog(recent_gap_report)
    manual_review_receipt_summary = summarize_manual_review_receipt_snapshot(
        _load_manual_review_receipt_snapshot_for_runtime(data_root),
        manual_review_backlog_summary,
    )
    manual_review_reentry_application_summary = summarize_manual_review_reentry_application_summary(
        manual_review_receipt_summary,
        {},
        recent_gap_report,
        recent_gap_report,
        {"analysis_blockers": {}},
        {"analysis_blockers": {}},
    )
    recommended_actions = recommend_analysis_stage_actions(
        {"analysis_blockers": {}},
        gap_report=recent_gap_report,
        action_effectiveness=action_effectiveness,
        manual_review_receipt_summary=manual_review_receipt_summary,
    )
    action_effectiveness_summary = summarize_action_effectiveness_snapshot(action_effectiveness)
    operator_action_summary = summarize_operator_action_surface(
        recommended_actions,
        action_effectiveness_summary,
        recoverability_summary,
    )
    operator_action_summary["manual_review_backlog_summary"] = manual_review_backlog_summary
    operator_action_summary["manual_review_receipt_summary"] = manual_review_receipt_summary
    operator_action_summary["manual_review_reentry_application_summary"] = manual_review_reentry_application_summary
    operator_overview = summarize_operator_overview(operator_action_summary, scheduler_feedback_summary)
    manual_review_receipt_jobs_summary = _manual_review_receipt_jobs_summary(data_root)
    manual_review_receipt_operations_summary = _manual_review_receipt_operations_summary(data_root)
    control_plane_runtime = _manual_review_control_plane_runtime_summary(data_root)
    return {
        "recommended_actions": recommended_actions,
        "manual_review_backlog_summary": manual_review_backlog_summary,
        "manual_review_receipt_summary": manual_review_receipt_summary,
        "manual_review_reentry_application_summary": manual_review_reentry_application_summary,
        "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
        "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
        **control_plane_runtime,
        "operator_action_summary": operator_action_summary,
        "operator_overview": operator_overview,
        "scheduler_feedback_summary": scheduler_feedback_summary,
    }


def _validate_manual_review_receipt_payload(payload: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    action = payload.get("action")
    ready_signal = payload.get("ready_signal")
    status = payload.get("status")
    receipt_payload = payload.get("payload")
    mode = str(payload.get("mode", "sync") or "sync").lower()
    if not isinstance(action, str) or not action.strip():
        return False, {"code": "AVM_INVALID_RECEIPT_ACTION", "message": "action 为必填非空字符串", "details": {"required": ["action"]}}
    if not isinstance(ready_signal, str) or not ready_signal.strip():
        return False, {"code": "AVM_INVALID_RECEIPT_SIGNAL", "message": "ready_signal 为必填非空字符串", "details": {"required": ["ready_signal"]}}
    if not isinstance(status, str) or not status.strip():
        return False, {"code": "AVM_INVALID_RECEIPT_STATUS", "message": "status 为必填非空字符串", "details": {"required": ["status"]}}
    if not isinstance(receipt_payload, dict):
        return False, {"code": "AVM_INVALID_RECEIPT_PAYLOAD", "message": "payload 必须是对象", "details": {"required": ["payload"]}}
    if mode not in {"sync", "async"}:
        return False, {"code": "AVM_INVALID_RECEIPT_MODE", "message": "mode 只能是 sync 或 async", "details": {"allowed": ["sync", "async"]}}
    return True, None


def _validate_manual_review_receipt_delete_payload(payload: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    action = payload.get("action")
    ready_signal = payload.get("ready_signal")
    if not isinstance(action, str) or not action.strip():
        return False, {"code": "AVM_INVALID_RECEIPT_ACTION", "message": "action 为必填非空字符串", "details": {"required": ["action"]}}
    if not isinstance(ready_signal, str) or not ready_signal.strip():
        return False, {"code": "AVM_INVALID_RECEIPT_SIGNAL", "message": "ready_signal 为必填非空字符串", "details": {"required": ["ready_signal"]}}
    return True, None


def _verify_control_plane_token(headers) -> tuple[bool, dict[str, Any] | None]:
    expected = str(os.getenv("FAPAI_CONTROL_PLANE_TOKEN") or "").strip()
    if not expected:
        return True, None
    actual = str(headers.get("X-FAPAI-Control-Token") or "").strip()
    if actual == expected:
        return True, None
    return False, {
        "code": "AVM_CONTROL_PLANE_FORBIDDEN",
        "message": "control-plane token 校验失败",
        "details": {},
    }


def _json_payload_type_name(payload: Any) -> str:
    if payload is None:
        return "null"
    if isinstance(payload, dict):
        return "object"
    if isinstance(payload, list):
        return "list"
    if isinstance(payload, bool):
        return "boolean"
    if isinstance(payload, (int, float)):
        return "number"
    if isinstance(payload, str):
        return "string"
    return type(payload).__name__


def _evict_runtime_item(item_id):
    item_id = str(item_id)
    with DATA_LOCK:
        SEEN_IDS.pop(item_id, None)
        if item_id in PENDING_TASKS:
            PENDING_TASKS.remove(item_id)


def _reset_structured_sections_for_resync(item):
    for key in ("source", "archive", "auction", "location", "property", "legal_context", "risk_flags", "audit"):
        item.pop(key, None)


_FLAT_OVERRIDE_ALIAS_MAP = {
    "status": "status",
    "状态": "status",
    "交易时间": "auction_date",
    "auction_date": "auction_date",
    "成交价格": "transaction_price",
    "currentPrice": "transaction_price",
    "transaction_price": "transaction_price",
    "起拍价格": "starting_price",
    "initialPrice": "starting_price",
    "starting_price": "starting_price",
    "保证金": "deposit",
    "deposit": "deposit",
    "竞拍人数": "apply_count",
    "applyCount": "apply_count",
    "apply_count": "apply_count",
    "出价次数": "bid_count",
    "bidCount": "bid_count",
    "bid_count": "bid_count",
    "出价人数": "bidder_count",
    "bidderCount": "bidder_count",
    "bidder_count": "bidder_count",
    "地点": "full_address",
    "完整地址": "full_address",
    "full_address": "full_address",
    "城市": "city",
    "city": "city",
    "区": "district",
    "district": "district",
    "最靠近商圈": "business_area",
    "business_area": "business_area",
    "所属小区": "community_name",
    "community_name": "community_name",
    "纬度": "latitude",
    "latitude": "latitude",
    "经度": "longitude",
    "longitude": "longitude",
    "建筑面积": "area_sqm",
    "建设面积": "area_sqm",
    "area_sqm": "area_sqm",
    "产权建筑面积": "gross_area_sqm",
    "原始建筑面积": "gross_area_sqm",
    "gross_area_sqm": "gross_area_sqm",
    "产权份额比例": "ownership_share_ratio",
    "ownership_share_ratio": "ownership_share_ratio",
}


def _apply_flat_override_patch(item, patch):
    for patch_key, target_key in _FLAT_OVERRIDE_ALIAS_MAP.items():
        if patch_key in patch and patch.get(patch_key) not in (None, ""):
            item[target_key] = patch.get(patch_key)


def _get_working_item(item_id, include_processed=False):
    item_id = str(item_id)
    entry = SEEN_IDS.get(item_id)
    if entry:
        return {
            "data": entry["data"],
            "file_path": entry["file_path"],
            "cached": True,
        }
    if DB_REPOSITORY.enabled:
        try:
            item = DB_REPOSITORY.get_flat_item(item_id)
        except Exception as error:
            print(f"[DB] Working item fetch failed item={item_id}: {error}")
            return None
        if not item:
            return None
        sync_collection_record(item)
        if item.get("is_processed") and not include_processed:
            return None
        return {
            "data": item,
            "file_path": get_data_path(item.get("auction_date") or datetime.datetime.now()),
            "cached": False,
        }
    return None

# --- Watchdog for Service Continuity ---
LAST_REQUEST_TIME = time.time()
WATCHDOG_TIMEOUT = 10 * 60  # 10 minutes in seconds
WATCHDOG_CHECK_INTERVAL = 60  # Check every 60 seconds

def watchdog_thread():
    """Monitor for service continuity. If no requests for 10 minutes, restart Edge with recovery URLs."""
    global LAST_REQUEST_TIME
    import subprocess

    while True:
        time.sleep(WATCHDOG_CHECK_INTERVAL)

        elapsed = time.time() - LAST_REQUEST_TIME
        if elapsed > WATCHDOG_TIMEOUT:
            print(f"[WATCHDOG] No requests for {int(elapsed)}s. Triggering recovery...")

            try:
                # Step 1: Kill all Edge processes
                subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'],
                              capture_output=True, timeout=30)
                print("[WATCHDOG] Killed all Edge processes.")

                # Wait for processes to fully terminate
                time.sleep(5)

                # Step 2: Open 3 independent Edge windows with Remote Debugging
                # Window 1: Sniff Tab #1
                subprocess.Popen(['start', 'msedge', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window',
                                 'https://sf.taobao.com/list/50025969.htm?auto_recovery=1'],
                                shell=True)
                time.sleep(2)

                # Window 2: Sniff Tab #2
                subprocess.Popen(['start', 'msedge', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window',
                                 'https://sf.taobao.com/list/50025969.htm?auto_recovery=2'],
                                shell=True)
                time.sleep(2)

                # Window 3: Worker Tab
                subprocess.Popen(['start', 'msedge', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window',
                                 'https://sf.taobao.com/?auto_worker=1'],
                                shell=True)

                print("[WATCHDOG] Recovery complete. 3 Edge windows opened with Debug Port 9222.")

                # Reset timer to avoid immediate re-trigger
                LAST_REQUEST_TIME = time.time()

            except Exception as e:
                print(f"[WATCHDOG] Recovery failed: {e}")

def check_and_launch_browser():
    """Check if debug port 9222 is open, if not, launch browser."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 9222))
    sock.close()

    if result != 0:
        print("[STARTUP] Debug port 9222 not open. Launching Edge...")
        # Reuse watchdog logic to launch
        try:
             # Kill existing first to ensure port availability
             import subprocess
             subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
             time.sleep(2)

             # Launch windows
             subprocess.Popen(['start', 'msedge', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window', 'https://sf.taobao.com/list/50025969.htm?auto_recovery=1'], shell=True)
             time.sleep(2)
             subprocess.Popen(['start', 'msedge', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window', 'https://sf.taobao.com/list/50025969.htm?auto_recovery=2'], shell=True)
             time.sleep(2)
             subprocess.Popen(['start', 'msedge', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window', 'https://sf.taobao.com/?auto_worker=1'], shell=True)
             print("[STARTUP] Edge launched with debug port 9222.")
        except Exception as e:
            print(f"[STARTUP] Error launching browser: {e}")

JOBS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jobs")


def _seed_collection_service():
    return SeedCollectionService(
        repository=DB_REPOSITORY,
        jobs_dir=JOBS_DIR,
        data_root=DATA_DIR,
    )


def _detail_collection_service(data_root=None):
    return DetailCollectionService(data_root=data_root or DATA_DIR, repository=DB_REPOSITORY)







def submit_task(file_path):
    """
    Thread-safe task submission helper.
    Ensures we don't submit the same file twice.
    """
    with DATA_LOCK:
        if file_path in CURRENT_PROCESSING:
            return
        CURRENT_PROCESSING.add(file_path)

    try:
        # Submit to global executor
        future = executor.submit(process_single_file, file_path)
        # Ensure cleanup
        future.add_done_callback(lambda f: CURRENT_PROCESSING.discard(file_path))
    except Exception as e:
        print(f"Failed to submit task {file_path}: {e}")
        CURRENT_PROCESSING.discard(file_path)


def parse_price(raw_value):
    """Parse price-like fields to float (RMB Yuan)."""
    if raw_value is None:
        return None

    if isinstance(raw_value, (int, float)):
        return float(raw_value)

    if not isinstance(raw_value, str):
        return None

    text = raw_value.strip().replace(",", "")
    if not text:
        return None

    multiplier = 1.0
    if "亿" in text:
        multiplier = 100000000.0
    elif "万元" in text or "万" in text:
        multiplier = 10000.0

    numeric_text = re.sub(r"[^0-9.]", "", text)
    if not numeric_text:
        return None

    try:
        return float(numeric_text) * multiplier
    except ValueError:
        return None


def get_starting_price(item):
    return (
        parse_price(item.get("starting_price"))
        or parse_price(item.get("起拍价格"))
    )


def get_predicted_price(item):
    return (
        parse_price(item.get("predicted_price"))
        or parse_price(item.get("估值"))
        or parse_price(item.get("市场评估价"))
        or parse_price(item.get("evaluation_price"))
        or parse_price(item.get("transaction_price"))
        or parse_price(item.get("成交价格"))
    )


def compute_margin(predicted_price, starting_price):
    """margin = (predicted_price - starting_price) / predicted_price"""
    if not predicted_price or predicted_price <= 0 or starting_price is None:
        return None
    return (predicted_price - starting_price) / predicted_price


def _safe_int(value):
    parsed = parse_price(value)
    if parsed is None:
        return None
    try:
        return int(parsed)
    except (TypeError, ValueError):
        return None


def _get_risk_payload(item):
    payload = item.get("avm_risk_features")
    return payload if isinstance(payload, dict) else {}


def _risk_value(item, key):
    if item.get(key) is not None:
        return item.get(key)
    return _get_risk_payload(item).get(key)


def sync_avm_risk_aliases(item):
    risk_payload = _get_risk_payload(item)
    if not risk_payload:
        return item

    for key in RISK_ALIAS_KEYS:
        value = risk_payload.get(key)
        if value in (None, ""):
            continue
        item.setdefault(key, value)

    if risk_payload.get("community_name") and not item.get("所属小区"):
        item["所属小区"] = risk_payload["community_name"]
    if risk_payload.get("housing_type") and not item.get("housing_type"):
        item["housing_type"] = risk_payload["housing_type"]
    return item


def build_sniff_stub(item):
    return _seed_collection_service().build_seed_stub(item, parse_price=parse_price, safe_int=_safe_int)


def handle_seed_batch_submission(data):
    return _seed_collection_service().submit_batch(
        data,
        parse_price=parse_price,
        safe_int=_safe_int,
        prefer_db_task_reads=_prefer_db_task_reads,
        get_seen_entry=lambda item_id: SEEN_IDS.get(item_id),
        get_flat_item=lambda item_id: DB_REPOSITORY.get_flat_item(item_id) if DB_REPOSITORY.enabled else None,
        get_data_path=get_data_path,
        update_file_global=update_file_global,
        persist_item_to_db=persist_item_to_db,
        evict_runtime_item=_evict_runtime_item,
        seen_ids=SEEN_IDS,
        pending_tasks=PENDING_TASKS,
        archive_list_payload=archive_list_payload,
    )


def extract_risk_signals(item):
    major_risks = []

    for key, label in MALIGNANT_RISK_LABELS.items():
        if _risk_value(item, key) is True:
            major_risks.append(label)

    if _risk_value(item, "clear_delivery") is False:
        major_risks.append("法院不负责清场交付")

    if _risk_value(item, "land_right_type") == "划拨":
        major_risks.append("土地性质为划拨")

    return major_risks


def build_avm_result(item_id, item):
    predicted_price = get_predicted_price(item)
    starting_price = get_starting_price(item)
    margin = compute_margin(predicted_price, starting_price)
    major_risks = extract_risk_signals(item)

    return {
        "id": str(item_id),
        "predicted_price": predicted_price,
        "starting_price": starting_price,
        "margin": margin,
        "is_malignant_risk": len(major_risks) > 0,
        "major_risks": major_risks,
        "risk_summary": "；".join(major_risks) if major_risks else "未发现恶性风控标签",
    }


def _prediction_confidence_bucket(confidence):
    if confidence is None:
        return "unknown"
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return "unknown"
    if value >= 0.75:
        return "high"
    if value >= 0.45:
        return "medium"
    return "low"


def summarize_screen_results(results):
    strategy_counts = {}
    coordinate_strategy_counts = {}
    confidence_bucket_counts = {}
    blocked_reason_counts = {}
    malignant_count = 0
    alert_candidate_count = 0
    manual_review_count = 0
    manual_review_blocked_count = 0
    risk_validation_blocked_count = 0
    margin_values = []

    for result in results:
        prediction = result.get("prediction") or {}
        strategy = str(prediction.get("strategy") or "unknown")
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

        trace = prediction.get("trace") or {}
        coordinate_strategy = str(trace.get("subject_coordinate_strategy") or "unknown")
        coordinate_strategy_counts[coordinate_strategy] = coordinate_strategy_counts.get(coordinate_strategy, 0) + 1

        bucket = _prediction_confidence_bucket(prediction.get("confidence"))
        confidence_bucket_counts[bucket] = confidence_bucket_counts.get(bucket, 0) + 1
        if prediction.get("manual_review_recommended"):
            manual_review_count += 1
        blockers = result.get("alert_blockers") or []
        for blocker in blockers:
            blocked_reason_counts[blocker] = blocked_reason_counts.get(blocker, 0) + 1
        if "manual_review_required" in blockers:
            manual_review_blocked_count += 1
        if "risk_validation_incomplete" in blockers or "risk_validation_invalid" in blockers:
            risk_validation_blocked_count += 1

        if result.get("is_malignant_risk"):
            malignant_count += 1
        if result.get("meets_alert_threshold"):
            alert_candidate_count += 1

        margin = result.get("margin")
        if isinstance(margin, (int, float)):
            margin_values.append(float(margin))

    average_margin = round(sum(margin_values) / len(margin_values), 4) if margin_values else None
    top_result_id = results[0]["id"] if results else None

    return {
        "strategy_counts": dict(sorted(strategy_counts.items())),
        "coordinate_strategy_counts": dict(sorted(coordinate_strategy_counts.items())),
        "confidence_bucket_counts": dict(sorted(confidence_bucket_counts.items())),
        "malignant_risk_count": malignant_count,
        "alert_candidate_count": alert_candidate_count,
        "manual_review_count": manual_review_count,
        "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
        "manual_review_blocked_count": manual_review_blocked_count,
        "risk_validation_blocked_count": risk_validation_blocked_count,
        "average_margin": average_margin,
        "top_result_id": top_result_id,
    }


def write_avm_alerts(alerts):
    if not alerts:
        return

    os.makedirs(AVM_DIR, exist_ok=True)

    with FILE_LOCK:
        existing = []
        if os.path.exists(AVM_ALERTS_PATH):
            try:
                with open(AVM_ALERTS_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        existing = loaded
            except Exception:
                existing = []

        existing_by_id = {str(alert.get("id")): alert for alert in existing}
        for alert in alerts:
            existing_by_id[str(alert["id"])] = alert

        with open(AVM_ALERTS_PATH, "w", encoding="utf-8") as f:
            json.dump(list(existing_by_id.values()), f, ensure_ascii=False, indent=2)



def get_data_path(date_str_or_obj):
    """
    Helper to get the correct archive path: datas/archive/YYYY/YYYY-MM-DD.json
    """
    if isinstance(date_str_or_obj, str):
        try:
            dt = datetime.datetime.strptime(date_str_or_obj[:10], "%Y-%m-%d")
        except:
            dt = datetime.datetime.now()
    elif isinstance(date_str_or_obj, datetime.date) or isinstance(date_str_or_obj, datetime.datetime):
        dt = date_str_or_obj
    else:
        dt = datetime.datetime.now()

    year = dt.strftime("%Y")
    filename = f"{dt.strftime('%Y-%m-%d')}.json"

    archive_dir = os.path.join(DATA_DIR, "archive", year)
    if not os.path.exists(archive_dir):
        os.makedirs(archive_dir)

    return os.path.join(archive_dir, filename)


def get_detail_archive_path(date_str_or_obj, item_id, extension=".html"):
    return str(_shared_get_detail_archive_path(DATA_DIR, date_str_or_obj, item_id, extension))


def get_list_payload_archive_path(date_str_or_obj=None, suffix=".json"):
    if isinstance(date_str_or_obj, str):
        try:
            dt = datetime.datetime.strptime(date_str_or_obj[:10], "%Y-%m-%d")
        except:
            dt = datetime.datetime.now()
    elif isinstance(date_str_or_obj, datetime.date) or isinstance(date_str_or_obj, datetime.datetime):
        dt = date_str_or_obj
    else:
        dt = datetime.datetime.now()

    year = dt.strftime("%Y")
    day = dt.strftime("%Y-%m-%d")
    archive_dir = os.path.join(DATA_DIR, "list_payload_archive", year, day)
    if not os.path.exists(archive_dir):
        os.makedirs(archive_dir)
    timestamp = dt.strftime("%Y%m%d-%H%M%S-%f")
    normalized_suffix = suffix if str(suffix).startswith(".") else f".{suffix}"
    return os.path.join(archive_dir, f"list-{timestamp}{normalized_suffix}")


def archive_list_payload(raw_payload, captured_at=None):
    if raw_payload in (None, "", []):
        return None
    payload_path = get_list_payload_archive_path(captured_at, ".json")
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(raw_payload, f, ensure_ascii=False, indent=2)
    return os.path.relpath(payload_path, DATA_DIR).replace("\\", "/")


def _extract_detail_artifacts(html_content, item_id, auction_date=None, source_url=None):
    return _shared_extract_detail_artifacts(
        data_root=DATA_DIR,
        html_content=html_content,
        item_id=item_id,
        auction_date=auction_date,
        source_url=source_url,
    )


def load_data():
    """Load all json files from datas/ directory (and archives) into memory index"""
    global SEEN_IDS, PENDING_TASKS
    SEEN_IDS = {}
    PENDING_TASKS = []

    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    print("Loading data...")

    prefer_db_runtime_index = DB_REPOSITORY.enabled and _runtime_env_flag("FAPAI_DB_PREFER_RUNTIME_INDEX", True)
    if prefer_db_runtime_index:
        try:
            counts = _db_counts_snapshot()
            total_count = counts["db_total_ids"]
            if total_count:
                pending_count = counts["db_pending_ids"]
                print("[DB] Runtime index is in lazy DB-first mode; pending items will be cached on demand.")
                print(f"Loaded {len(SEEN_IDS)} runtime-cached items. Total DB items: {total_count}. Pending detail tasks in DB: {pending_count}.")
                return
            print("[DB] DB-first runtime index requested, but repository is empty; falling back to JSON scan.")
        except Exception as db_load_error:
            print(f"[DB] DB-first runtime index failed, falling back to JSON scan: {db_load_error}")

    # 1. Scan root JSONs (priority config, current files)
    try:
        root_files = glob.glob(os.path.join(DATA_DIR, '*.json'))
    except:
        root_files = []

    # 2. Scan Archive JSONs (Recursive)
    try:
        archive_pattern = os.path.join(DATA_DIR, 'archive', '**', '*.json')
        archive_files = glob.glob(archive_pattern, recursive=True)
    except:
        archive_files = []

    files = root_files + archive_files

    # Skip non-data json files (config files, progress files, etc.)
    skip_files = [
        "all_locations.json", "sniff_queue", "sniff_status", "sniff_history", "sniff_done",
        "manual_priority_locations.json", "sniff_progress.json", "collected_locations.json",
        "model_config.json", "tuning_history.json", "seen_ids.json"
    ]
    # Filter by basename to be safe with paths
    files = [f for f in files if not any(skip in os.path.basename(f) for skip in skip_files)]

    print(f"Loading data from {len(files)} files...")

    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)

            items = []
            if isinstance(content, list):
                items = content
            elif isinstance(content, dict):
                items = [content]

            for item in items:
                item_id = str(item.get("id"))
                if not item_id:
                    continue
                sync_collection_record(item)

                with DATA_LOCK:
                    SEEN_IDS[item_id] = {
                        "file_path": file_path,
                        "data": item
                    }

                    is_done = item.get("status") in ["done", "成交", "failure", "failed_timeout"] or item.get("是否成交") is True
                    is_processed = item.get("is_processed", False)

                    # QUEUE LOGIC: If it's a valid item (done/failed) AND not processed, queue it.
                    if is_done and not is_processed:
                        PENDING_TASKS.append(item_id)
        except Exception as e:
            # print(f"Error loading {file_path}: {e}")
            pass

    if DB_REPOSITORY.enabled:
        try:
            db_items = DB_REPOSITORY.iter_flat_items()
            for item in db_items:
                item_id = str(item.get("id") or item.get("item_id"))
                if not item_id:
                    continue
                sync_collection_record(item)
                existing = SEEN_IDS.get(item_id, {})
                existing_data = dict(existing.get("data", {}))
                existing_data.update(item)
                sync_collection_record(existing_data)
                file_path = existing.get("file_path")
                if not file_path:
                    file_path = get_data_path(existing_data.get("auction_date") or datetime.datetime.now())
                with DATA_LOCK:
                    SEEN_IDS[item_id] = {"file_path": file_path, "data": existing_data}
                    is_done = existing_data.get("status") in ["done", "成交", "failure", "failed_timeout"] or existing_data.get("是否成交") is True
                    is_processed = existing_data.get("is_processed", False)
                    if is_done and not is_processed and item_id not in PENDING_TASKS:
                        PENDING_TASKS.append(item_id)
            print(f"Hydrated {len(db_items)} items from database into runtime index.")
        except Exception as db_load_error:
            print(f"[DB] Runtime index hydration failed: {db_load_error}")

    print(f"Loaded {len(SEEN_IDS)} items. {len(PENDING_TASKS)} pending detail tasks.")

# Initial load
def cleanup_orphaned_files():
    """Rename *.processing and *.processing.failed files back to original"""
    failed_orphans = glob.glob(os.path.join(DATA_DIR, "*.processing.failed"))
    for p in failed_orphans:
        original_base = p.replace(".processing.failed", "")
        try:
             os.rename(p, original_base)
             with open(original_base + ".failed", "w") as f: f.write("recovered")
        except Exception as e:
             print(f"Failed to reset {p}: {e}")


    # Optimized: Skip aggressive .failed file cleanup on every startup
    # failed_items = glob.glob(os.path.join(DATA_DIR, "item-*.html.failed")) + glob.glob(os.path.join(DATA_DIR, "item-*.txt.failed"))
    # if failed_items:
    #     print(f"Found {len(failed_items)} failed marker files (item-*.failed). Cleaning up...")
    #     for p in failed_items:
    #         try:
    #             os.remove(p)
    #         except Exception as e:
    #             print(f"Failed to remove {p}: {e}")

    orphans = glob.glob(os.path.join(DATA_DIR, "*.processing"))
    if orphans:
        print(f"Found {len(orphans)} orphaned processing files. Resetting...")
        for p in orphans:
            original = p.replace(".processing", "")
            try:
                os.rename(p, original)
            except Exception as e:
                print(f"Failed to reset {p}: {e}")

def initialize_runtime(start_watchdog=True, ensure_browser=True):
    global RUNTIME_INITIALIZED, AVM_SERVICE_START_TIME
    if RUNTIME_INITIALIZED:
        return

    cleanup_orphaned_files()
    load_data()
    try:
        DB_REPOSITORY.initialize()
        if DB_REPOSITORY.enabled:
            print("[DB] Repository initialized for dual-write.")
            try:
                _seed_collection_service()._bootstrap_db_search_tasks()
                print("[DB] Search task bootstrap completed.")
            except Exception as bootstrap_error:
                print(f"[DB] Search task bootstrap failed: {bootstrap_error}")
        else:
            print("[DB] Repository disabled (set FAPAI_DB_URL to enable database dual-write).")
    except Exception as db_init_error:
        print(f"[DB] Initialization failed: {db_init_error}")

    if start_watchdog:
        threading.Thread(target=watchdog_thread, daemon=True).start()
        print("[WATCHDOG] Service continuity watchdog started (timeout: 10 minutes).")

    if ensure_browser:
        threading.Thread(target=check_and_launch_browser, daemon=True).start()

    AVM_SERVICE_START_TIME = time.time()
    RUNTIME_INITIALIZED = True

def update_file_global(file_path, item_id, new_data):
    try:
        with FILE_LOCK:
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    all_data = json.load(f)

                updated = False
                for i, item in enumerate(all_data):
                    if str(item.get("id")) == item_id:
                        all_data[i] = new_data
                        updated = True
                        break

                if updated:
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(all_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"File write error (global): {e}")


def persist_item_to_db(item, event_type, event_payload=None):
    try:
        DB_REPOSITORY.upsert_flat_item(item, event_type=event_type, event_payload=event_payload)
    except Exception as exc:
        print(f"[DB] upsert failed item={item.get('id') or item.get('source', {}).get('item_id')}: {exc}")


def mark_item_deleted_in_db(item_id, reason, payload=None):
    try:
        DB_REPOSITORY.mark_deleted(str(item_id), reason=reason, event_payload=payload)
    except Exception as exc:
        print(f"[DB] mark_deleted failed item={item_id}: {exc}")

def process_single_file(file_path):
    _detail_collection_service().process_html_file(
        file_path,
        get_working_item=_get_working_item,
        get_data_path=get_data_path,
        update_item_in_json=update_item_in_json,
        remove_item_from_json=remove_item_from_json,
        persist_item_to_db=persist_item_to_db,
        mark_item_deleted_in_db=mark_item_deleted_in_db,
        evict_runtime_item=_evict_runtime_item,
        prefer_db_task_reads=_prefer_db_task_reads,
        sync_avm_risk_aliases=sync_avm_risk_aliases,
        extract_auction_data=llm_helper.extract_auction_data,
        extract_avm_risk_features=llm_helper.extract_avm_risk_features,
        log_prediction_event=llm_helper.log_prediction_event,
        current_processing=CURRENT_PROCESSING,
        seen_ids=SEEN_IDS,
        pending_tasks=PENDING_TASKS,
    )

def update_item_in_json(file_path, item_id, new_data):
    """Helper to update a specific item in a JSON file, or append if new."""
    with FILE_LOCK:
        data_list = []
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data_list = json.load(f)
            except:
                data_list = []

        updated = False
        for i, item in enumerate(data_list):
            if str(item.get("id")) == item_id:
                data_list[i] = new_data
                updated = True
                break

        if not updated:
            data_list.append(new_data)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data_list, f, ensure_ascii=False, indent=4)

def remove_item_from_json(file_path, item_id):
    """Helper to remove a specific item from a JSON file."""
    if not file_path or not os.path.exists(file_path):
        return
    with FILE_LOCK:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data_list = json.load(f)

            new_list = [item for item in data_list if str(item.get("id")) != item_id]

            if len(new_list) < len(data_list):
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(new_list, f, ensure_ascii=False, indent=4)
                print(f"Removed item {item_id} from {file_path}")
        except Exception as e:
            print(f"Error removing item {item_id}: {e}")

def background_file_processor():
    """
    Periodically checks for item-*.txt AND item-*.html files and processes them.
    Uses global `executor` to limit total concurrency.
    """
    print("Background AI Processor Started (using global executor).")

    while True:
        try:
            txt_files = glob.glob(os.path.join(DATA_DIR, "item-*.txt"))

            # Scan new html directory + root (legacy)
            html_files = glob.glob(os.path.join(DATA_DIR, 'html', 'item-*.html'))
            html_files += glob.glob(os.path.join(DATA_DIR, "item-*.html"))

            files = txt_files + html_files

            # Simple check to avoid scan overhead if nothing is there
            if not files:
                time.sleep(1)
                continue

            # Submit tasks
            submitted_count = 0
            for f_path in files:
                # Fast check before lock
                if f_path in CURRENT_PROCESSING:
                    continue

                submit_task(f_path)
                submitted_count += 1

            if submitted_count > 0:
                print(f"Background scanner submitted {submitted_count} new tasks.")

            time.sleep(1) # Check every second

        except Exception as outer_e:
            print(f"Background Loop Error: {outer_e}")
            time.sleep(5)


# ==================== AUTO-TUNER BACKGROUND THREAD ====================
def auto_tuner_thread():
    """
    Background thread for automatic concurrency tuning.
    Runs every 5 minutes, analyzes error rates, and adjusts ModelSelector limits.
    """
    from llm_helper import model_selector, MODEL_POOL

    TUNING_INTERVAL = 5 * 60  # 5 minutes
    MIN_REQUESTS = 20
    ERROR_RATE_LOW = 1.0   # Below this: increase
    ERROR_RATE_HIGH = 5.0  # Above this: decrease
    MAX_LIMIT = 20
    MIN_LIMIT = 3
    STEP_SIZE = 2
    STABLE_ROUNDS = 2

    stable_count = {m["name"]: 0 for m in MODEL_POOL}
    is_stable = False

    print("[AUTO-TUNER] Started (5-minute intervals)")

    while True:
        time.sleep(TUNING_INTERVAL)

        if is_stable:
            # Already stable, just monitor
            continue

        try:
            stats = model_selector.get_stats()
            all_stable = True

            print(f"\n[AUTO-TUNER] Analysis @ {time.strftime('%H:%M:%S')}")

            for name, s in stats.items():
                current_limit = model_selector.limits.get(name, 5)
                total = s["success"] + s["error"]

                if total < MIN_REQUESTS:
                    print(f"  [{name}] Requests {total} < {MIN_REQUESTS}, skipping")
                    continue

                error_rate = (s["concurrency_error"] / total * 100) if total > 0 else 0

                if error_rate < ERROR_RATE_LOW and current_limit < MAX_LIMIT:
                    new_limit = min(current_limit + STEP_SIZE, MAX_LIMIT)
                    print(f"  [{name}] Error {error_rate:.1f}% < {ERROR_RATE_LOW}% → {current_limit} → {new_limit}")
                    model_selector.update_limit(name, new_limit)
                    stable_count[name] = 0
                    all_stable = False
                elif error_rate > ERROR_RATE_HIGH and current_limit > MIN_LIMIT:
                    new_limit = max(current_limit - STEP_SIZE, MIN_LIMIT)
                    print(f"  [{name}] Error {error_rate:.1f}% > {ERROR_RATE_HIGH}% → {current_limit} → {new_limit}")
                    model_selector.update_limit(name, new_limit)
                    stable_count[name] = 0
                    all_stable = False
                else:
                    print(f"  [{name}] Error {error_rate:.1f}% OK, keeping {current_limit}")
                    stable_count[name] += 1

            # Reset stats for next round
            with model_selector.stats_lock:
                for name in model_selector.stats:
                    model_selector.stats[name] = {"success": 0, "error": 0, "concurrency_error": 0, "active": model_selector.stats[name]["active"]}

            # Check stability
            if min(stable_count.values()) >= STABLE_ROUNDS:
                is_stable = True
                print(f"[AUTO-TUNER] ✅ Stable! Final config: {model_selector.limits}")

        except Exception as e:
            print(f"[AUTO-TUNER] Error: {e}")

class DataHandler(http.server.SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-FAPAI-Control-Token')
        self.end_headers()

    def do_GET(self):
        global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
        LAST_REQUEST_TIME = time.time()  # Update watchdog timer
        parsed = urlparse(self.path)
        request_path = parsed.path
        query = parse_qs(parsed.query)

        if request_path in MANUAL_REVIEW_RECEIPT_ENDPOINTS:
            try:
                active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
                payload = list_manual_review_receipts(
                    _manual_review_receipt_store_path(active_data_root),
                    repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
                )
                control_plane_runtime = _manual_review_control_plane_runtime_summary(active_data_root)
                self.send_json(
                    {
                        "receipt_count": len(payload.get("receipts") or []),
                        "receipts": list(payload.get("receipts") or []),
                        **control_plane_runtime,
                    }
                )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_MANUAL_REVIEW_RECEIPTS_READ_FAILED",
                    message="manual review receipts 读取失败",
                    details={"error": str(e)},
                )

        elif request_path in MANUAL_REVIEW_RECEIPT_JOB_ENDPOINTS:
            try:
                active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
                manager = _get_manual_review_maintenance_manager(active_data_root)
                snapshot = manager.snapshot()
                jobs = list(snapshot.get("jobs") or [])
                running_job = next((dict(job) for job in jobs if job.get("job_id") == snapshot.get("running_job_id")), None)
                queued_jobs = [dict(job) for job in jobs if job.get("status") == "queued"]
                control_plane_runtime = _manual_review_control_plane_runtime_summary(active_data_root)
                job_id = str((query.get("job_id") or [None])[0] or "").strip()
                if job_id:
                    job = manager.get_job(job_id)
                    self.send_json(
                        {
                            "job_count": len(jobs),
                            "job": job,
                            "running_job": running_job,
                            "queued_jobs": queued_jobs,
                            "manual_review_receipt_summary": _manual_review_receipt_context(active_data_root)["manual_review_receipt_summary"],
                            "operator_overview": _manual_review_receipt_context(active_data_root)["operator_overview"],
                            **control_plane_runtime,
                        }
                    )
                else:
                    self.send_json(
                        {
                            "job_count": len(jobs),
                            "jobs": jobs,
                            "running_job": running_job,
                            "queued_jobs": queued_jobs,
                            **control_plane_runtime,
                        }
                    )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_MANUAL_REVIEW_RECEIPT_JOBS_READ_FAILED",
                    message="manual review receipt jobs 读取失败",
                    details={"error": str(e)},
                )

        elif request_path in MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS:
            try:
                active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
                action = str((query.get("action") or [None])[0] or "").strip() or None
                ready_signal = str((query.get("ready_signal") or [None])[0] or "").strip() or None
                try:
                    limit = int((query.get("limit") or [50])[0] or 50)
                except (TypeError, ValueError):
                    limit = 50
                if limit < 0:
                    limit = 0
                operations = filter_manual_review_receipt_operations(
                    load_manual_review_receipt_operations(
                        _manual_review_receipt_operations_path(active_data_root),
                        repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
                    ),
                    action=action,
                    ready_signal=ready_signal,
                    limit=limit,
                )
                operations = list(reversed(operations))
                control_plane_runtime = _manual_review_control_plane_runtime_summary(active_data_root)
                self.send_json(
                    {
                        "operation_count": len(operations),
                        "operations": operations,
                        "applied_filters": {
                            "action": action,
                            "ready_signal": ready_signal,
                            "limit": limit,
                        },
                        **control_plane_runtime,
                    }
                )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_MANUAL_REVIEW_RECEIPT_OPERATIONS_READ_FAILED",
                    message="manual review receipt operations 读取失败",
                    details={"error": str(e)},
                )

        elif request_path in MANUAL_REVIEW_CONTROL_PLANE_STATUS_ENDPOINTS:
            try:
                active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
                context = _manual_review_receipt_context(active_data_root)
                self.send_json(
                    {
                        "manual_review_receipt_summary": context["manual_review_receipt_summary"],
                        "manual_review_receipt_jobs_summary": context["manual_review_receipt_jobs_summary"],
                        "manual_review_receipt_operations_summary": context["manual_review_receipt_operations_summary"],
                        "manual_review_control_plane_storage": context["manual_review_control_plane_storage"],
                        "manual_review_control_plane_backup": context["manual_review_control_plane_backup"],
                        "manual_review_control_plane_backup_repairs_summary": context["manual_review_control_plane_backup_repairs_summary"],
                        "manual_review_control_plane_integrity": context["manual_review_control_plane_integrity"],
                        "manual_review_control_plane_integrity_history_summary": context["manual_review_control_plane_integrity_history_summary"],
                        "manual_review_control_plane_stability": context["manual_review_control_plane_stability"],
                        "manual_review_control_plane_guidance": context["manual_review_control_plane_guidance"],
                    }
                )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_MANUAL_REVIEW_CONTROL_PLANE_STATUS_FAILED",
                    message="manual review control plane 状态读取失败",
                    details={"error": str(e)},
                )

        elif request_path in MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS:
            try:
                active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
                try:
                    limit = int((query.get("limit") or [50])[0] or 50)
                except (TypeError, ValueError):
                    limit = 50
                if limit < 0:
                    limit = 0
                repairs = load_manual_review_control_plane_backup_repairs(active_data_root)
                if limit >= 0:
                    repairs = [] if limit == 0 else repairs[-limit:]
                repairs = list(reversed(repairs))
                control_plane_runtime = _manual_review_control_plane_runtime_summary(active_data_root)
                self.send_json(
                    {
                        "repair_count": len(repairs),
                        "repairs": repairs,
                        "applied_filters": {"limit": limit},
                        **control_plane_runtime,
                    }
                )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIRS_FAILED",
                    message="manual review control plane backup repairs 读取失败",
                    details={"error": str(e)},
                )

        elif request_path in MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS:
            try:
                active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
                try:
                    limit = int((query.get("limit") or [50])[0] or 50)
                except (TypeError, ValueError):
                    limit = 50
                if limit < 0:
                    limit = 0
                history = load_manual_review_control_plane_integrity_history(active_data_root)
                if limit >= 0:
                    history = [] if limit == 0 else history[-limit:]
                history = list(reversed(history))
                control_plane_runtime = _manual_review_control_plane_runtime_summary(active_data_root)
                self.send_json(
                    {
                        "transition_count": len(history),
                        "history": history,
                        "applied_filters": {"limit": limit},
                        **control_plane_runtime,
                    }
                )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_FAILED",
                    message="manual review control plane integrity history 读取失败",
                    details={"error": str(e)},
                )

        elif self.path == '/api/status':
            try:
                db_total_ids = None
                db_processed_ids = None
                db_pending_ids = None
                db_detail_captured_ids = None
                if _prefer_db_task_reads():
                    counts = _db_counts_snapshot()
                    total_ids = counts["db_total_ids"]
                    ai_finalized_count = counts["db_processed_ids"]
                    detail_captured_count = counts["db_detail_captured_ids"]
                    captured_count = max(ai_finalized_count, detail_captured_count)
                    db_total_ids = total_ids
                    db_processed_ids = ai_finalized_count
                    db_pending_ids = counts["db_pending_ids"]
                    db_detail_captured_ids = detail_captured_count
                    next_batch = []
                    now = datetime.datetime.now()
                    for candidate in _db_pending_task_candidates(limit=100):
                        if len(next_batch) >= 10:
                            break
                        tid = candidate["id"]
                        last_time = DISPATCHED_TASKS.get(tid)
                        if not last_time or (now - last_time).total_seconds() >= DISPATCH_COOLDOWN_SECONDS:
                            next_batch.append(tid)
                else:
                    with DATA_LOCK:
                        total_ids = len(SEEN_IDS)
                    # Captured IDs = (Has raw file in DATA_DIR) UNION (Already finalized in memory/JSON)
                        captured_ids = set()

                    # 1. Add IDs currently in final storage
                        for tid, entry in SEEN_IDS.items():
                            if entry.get("data", {}).get("is_processed"):
                                captured_ids.add(tid)

                        ai_finalized_count = len(captured_ids)

                    # 2. Add IDs currently in raw file form
                        for f in os.listdir(DATA_DIR):
                            if f.startswith("item-") and (f.endswith(".txt") or f.endswith(".html")):
                                m = re.search(r"item-(\d+)", f)
                                if m: captured_ids.add(m.group(1))

                        captured_count = len(captured_ids)

                    # Next Batch Preview (IDs that are known but NOT yet finalized by AI)
                        next_batch = []
                        now = datetime.datetime.now()
                    # Sort PENDING_TASKS to show something consistent or just first 10
                        for tid in PENDING_TASKS[:100]: # Check first 100 for dispatchable ones
                            if len(next_batch) >= 10: break
                            last_time = DISPATCHED_TASKS.get(tid)
                            if not last_time or (now - last_time).total_seconds() >= DISPATCH_COOLDOWN_SECONDS:
                                next_batch.append(tid)

                if _prefer_db_task_reads():
                    pass

                # Task Queue Status (Sniffing / Seed Collection)
                if DB_REPOSITORY.enabled:
                    search_counts = _seed_collection_service().counts_snapshot()
                    status_info = {
                        "pending_locations": search_counts.get("search_pending", 0),
                        "done_locations": search_counts.get("search_done", 0),
                    }
                else:
                    legacy_counts = _seed_collection_service().counts_snapshot()
                    status_info = {
                        "pending_locations": legacy_counts.get("search_pending", 0),
                        "done_locations": legacy_counts.get("search_done", 0),
                    }
                api_metrics = llm_helper.get_api_metrics()
                collection_stage_snapshot = _db_collection_stage_snapshot()
                avm_status = {
                    **AVM_SERVICE.health_snapshot(lightweight=True),
                    **_avm_operator_eval_summary(Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))),
                }

                self.send_json({
                    "paused": PAUSED,
                    "total_ids": total_ids,
                    "captured_count": captured_count,
                    "ai_finalized_count": ai_finalized_count,
                    "db_mode": _prefer_db_task_reads(),
                    "db_total_ids": db_total_ids,
                    "db_processed_ids": db_processed_ids,
                    "db_pending_ids": db_pending_ids,
                    "db_detail_captured_ids": db_detail_captured_ids,
                    "sniff_queue_count": status_info.get("pending_locations", 0),
                    "sniff_done_count": status_info.get("done_locations", 0),
                    "next_batch_preview": next_batch,
                    "api_success_rate": api_metrics.get("success_rate", 0.0),
                    "api_avg_response_time_ms": api_metrics.get("avg_response_time_ms", 0.0),
                    "api_total_calls": api_metrics.get("total_calls", 0),
                    "api_success_calls": api_metrics.get("success_calls", 0),
                    "data_supply_recent_24h": _db_data_supply_snapshot(24) if DB_REPOSITORY.enabled else {},
                    "avm": avm_status,
                    "collection_stage": collection_stage_snapshot,
                })
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_STATUS_FAILED",
                    message="状态概览生成失败",
                    details={"error": str(e)},
                )

        # --- Single Task Dispatch for Detail Helper (Auto Fix) ---
        elif self.path in ('/api/next_task', '/api/collection/details/next_task'):
            if _prefer_db_task_reads():
                try:
                    next_task = _detail_collection_service().next_task(
                        dispatched_tasks=DISPATCHED_TASKS,
                        cooldown_seconds=DISPATCH_COOLDOWN_SECONDS,
                    )
                except Exception as e:
                    self.send_error_json(
                        status=500,
                        code="AVM_DETAIL_NEXT_TASK_FAILED",
                        message="详情任务分发失败",
                        details={"error": str(e)},
                    )
                    return
                if next_task:
                    self.send_json(next_task)
                else:
                    self.send_json({})
                return
            else:
                now = datetime.datetime.now()
                next_task = None
                # Find first valid pending task
                with DATA_LOCK:
                    # Cleanup PENDING_TASKS first (remove processed)
                    PENDING_TASKS[:] = [tid for tid in PENDING_TASKS
                                      if tid in SEEN_IDS and not SEEN_IDS[tid].get("data", {}).get("is_processed")]

                    check_candidates = list(PENDING_TASKS) # Copy to avoid mutation issues during iteration

                    for tid in check_candidates:
                        # Check dispatch throttle
                        last_time = DISPATCHED_TASKS.get(tid)
                        if last_time and (now - last_time).total_seconds() < DISPATCH_COOLDOWN_SECONDS:
                            continue

                        if tid in SEEN_IDS:
                            item = SEEN_IDS[tid]["data"]
                            next_task = {"url": item.get("url")}
                            DISPATCHED_TASKS[tid] = now
                            break

            if next_task:
                self.send_json(next_task)
            else:
                self.send_json({}) # Empty object means no task

        # --- Get Item Data (for Detail Helper) ---

        elif self.path.startswith('/api/avm/predict') or self.path.startswith('/api/analysis/predict'):
            parsed_url = urlparse(self.path)
            params = parse_qs(parsed_url.query)
            item_id = (params.get('id', [''])[0] or '').strip()

            if not item_id:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_ID",
                    message="缺少必填参数 id",
                    details={"required": ["id"]},
                )
                return

            try:
                result = AVM_SERVICE.predict_by_item_id(item_id)
                if result.get("error") == "item_not_found":
                    self.send_error_json(
                        status=404,
                        code="AVM_NOT_FOUND",
                        message=f"ID={item_id} 不存在",
                        details={"id": item_id},
                    )
                    return
                self.send_json(result)
            except Exception as e:
                print(f"[AVM] Predict error: {e}")
                self.send_error_json(
                    status=500,
                    code="AVM_PREDICT_FAILED",
                    message="估值失败",
                    details={"error": str(e), "id": str(item_id)},
                )

        elif self.path.startswith('/api/avm/health') or self.path.startswith('/api/analysis/health') or self.path.startswith('/api/analysis/status'):
            try:
                uptime_sec = max(0, int(time.time() - AVM_SERVICE_START_TIME))
                service_stats = AVM_SERVICE.health_snapshot(lightweight=True)
                operator_eval_summary = _avm_operator_eval_summary(Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR)))
                db_stats = {
                    "db_mode": DB_REPOSITORY.enabled,
                    "db_total_ids": None,
                    "db_processed_ids": None,
                    "db_pending_ids": None,
                    "db_detail_captured_ids": None,
                }
                if DB_REPOSITORY.enabled:
                    try:
                        db_stats.update(_db_counts_snapshot())
                    except Exception as db_health_error:
                        db_stats["db_error"] = str(db_health_error)
                self.send_json(
                    {
                        "status": "ok",
                        "service": "avm",
                        "uptime_sec": uptime_sec,
                        **service_stats,
                        **operator_eval_summary,
                        **db_stats,
                        "data_supply_recent_24h": _db_data_supply_snapshot(24) if DB_REPOSITORY.enabled else {},
                        "collection_stage": _db_collection_stage_snapshot(),
                    }
                )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_HEALTH_FAILED",
                    message="健康概览生成失败",
                    details={"error": str(e)},
                )

        elif self.path.startswith('/api/avm/collection_template'):
            from src.avm.collection_template import get_collection_template

            try:
                self.send_json(get_collection_template())
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_COLLECTION_TEMPLATE_FAILED",
                    message="collection template 生成失败",
                    details={"error": str(e)},
                )

        elif self.path.startswith('/api/avm/drift_status') or self.path.startswith('/api/analysis/drift_status'):
            from tools.check_feature_drift import generate_drift_report

            parsed_url = urlparse(self.path)
            params = parse_qs(parsed_url.query)
            try:
                window_days = int((params.get("window_days", ["30"])[0] or "30"))
            except ValueError:
                window_days = 30
            if window_days < 0:
                window_days = 30

            active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
            active_avm_dir = active_data_root / "avm"
            try:
                output = generate_drift_report(
                    archive_dir=active_data_root / "archive",
                    output_path=active_avm_dir / "drift_alerts.json",
                    window_days=window_days,
                )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_DRIFT_FAILED",
                    message="漂移报告生成失败",
                    details={"error": str(e)},
                )
                return

            self.send_json(output)

        elif self.path.startswith('/api/avm/release_gate') or self.path.startswith('/api/analysis/release_gate'):
            from tools.avm_release_gate import generate_release_gate_report

            parsed_url = urlparse(self.path)
            params = parse_qs(parsed_url.query)
            try:
                window_days = int((params.get("window_days", ["7"])[0] or "7"))
            except ValueError:
                window_days = 7
            if window_days < 0:
                window_days = 7
            try:
                min_sample_size = int((params.get("min_sample_size", ["1000"])[0] or "1000"))
            except ValueError:
                min_sample_size = 1000
            if min_sample_size < 0:
                min_sample_size = 1000
            try:
                smoke_sample_size = int((params.get("smoke_sample_size", ["0"])[0] or "0"))
            except ValueError:
                smoke_sample_size = 0
            if smoke_sample_size < 0:
                smoke_sample_size = 0

            active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
            active_avm_dir = active_data_root / "avm"
            try:
                output = generate_release_gate_report(
                    data_root=active_data_root,
                    eval_report_path=active_avm_dir / "eval_report.json",
                    gate_report_path=active_avm_dir / "release_gate.json",
                    window_days=window_days,
                    min_sample_size=min_sample_size,
                    smoke_sample_size=smoke_sample_size,
                )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_RELEASE_GATE_FAILED",
                    message="发布门禁报告生成失败",
                    details={"error": str(e)},
                )
                return

            if isinstance(output, dict):
                try:
                    output = {
                        **output,
                        **_avm_operator_eval_summary(active_data_root, gate_report_override=output),
                    }
                except Exception as e:
                    self.send_error_json(
                        status=500,
                        code="AVM_RELEASE_GATE_SUMMARY_FAILED",
                        message="发布门禁 operator summary 生成失败",
                        details={"error": str(e)},
                    )
                    return
            self.send_json(output)

        elif self.path.startswith('/api/avm/recent_gap_audit'):
            from tools.audit_recent_avm_gaps import build_recent_gap_audit

            parsed_url = urlparse(self.path)
            params = parse_qs(parsed_url.query)
            try:
                window_days = int((params.get("window_days", ["7"])[0] or "7"))
            except ValueError:
                window_days = 7
            if window_days < 0:
                window_days = 7
            try:
                sample_limit = int((params.get("sample_limit", ["20"])[0] or "20"))
            except ValueError:
                sample_limit = 20
            if sample_limit < 0:
                sample_limit = 20

            active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
            active_avm_dir = active_data_root / "avm"
            try:
                output = build_recent_gap_audit(
                    data_root=active_data_root,
                    window_days=window_days,
                    sample_limit=sample_limit,
                )
                (active_avm_dir / "recent_gap_audit.json").parent.mkdir(parents=True, exist_ok=True)
                (active_avm_dir / "recent_gap_audit.json").write_text(
                    json.dumps(output, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_RECENT_GAP_AUDIT_FAILED",
                    message="recent gap 审计失败",
                    details={"error": str(e)},
                )
                return

            self.send_json(output)

        elif self.path.startswith('/api/avm/recent_detail_replay') or self.path.startswith('/api/collection/details/prepare_replay'):
            parsed_url = urlparse(self.path)
            params = parse_qs(parsed_url.query)
            try:
                window_days = int((params.get("window_days", ["7"])[0] or "7"))
            except ValueError:
                window_days = 7
            if window_days < 0:
                window_days = 7
            try:
                limit = int((params.get("limit", ["100"])[0] or "100"))
            except ValueError:
                limit = 100
            if limit < 0:
                limit = 0
            dry_run = str((params.get("dry_run", ["true"])[0] or "true")).lower() not in {"0", "false", "no"}

            active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
            active_avm_dir = active_data_root / "avm"
            try:
                output = _detail_collection_service(active_data_root).prepare_replay(
                    window_days=window_days,
                    limit=limit,
                    dry_run=dry_run,
                )
                (active_avm_dir / "recent_detail_replay.json").parent.mkdir(parents=True, exist_ok=True)
                (active_avm_dir / "recent_detail_replay.json").write_text(
                    json.dumps(output, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if not dry_run and output.get("prepared_count"):
                    load_data()
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_RECENT_DETAIL_REPLAY_FAILED",
                    message="recent detail replay 准备失败",
                    details={"error": str(e)},
                )
                return

            self.send_json(output)

        elif self.path.startswith('/api/avm/fetch_missing_detail_archives') or self.path.startswith('/api/collection/details/fetch_missing'):
            parsed_url = urlparse(self.path)
            params = parse_qs(parsed_url.query)
            try:
                limit = int((params.get("limit", ["20"])[0] or "20"))
            except ValueError:
                limit = 20
            if limit < 0:
                limit = 0
            try:
                timeout = int((params.get("timeout", ["15"])[0] or "15"))
            except ValueError:
                timeout = 15
            if timeout < 0:
                timeout = 15
            extract_risk = str((params.get("extract_risk", ["false"])[0] or "false")).lower() not in {"0", "false", "no"}
            dry_run = str((params.get("dry_run", ["true"])[0] or "true")).lower() not in {"0", "false", "no"}

            active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
            active_avm_dir = active_data_root / "avm"
            try:
                output = _detail_collection_service(active_data_root).fetch_missing_archives(
                    limit=limit,
                    timeout=timeout,
                    extract_risk=extract_risk,
                    dry_run=dry_run,
                )
                (active_avm_dir / "fetch_missing_detail_archives.json").parent.mkdir(parents=True, exist_ok=True)
                (active_avm_dir / "fetch_missing_detail_archives.json").write_text(
                    json.dumps(output, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if not dry_run and output.get("fetched_count"):
                    load_data()
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED",
                    message="缺失详情归档抓取失败",
                    details={"error": str(e)},
                )
                return

            self.send_json(output)

        elif self.path.startswith('/api/avm/archive_detail_replay'):
            parsed_url = urlparse(self.path)
            params = parse_qs(parsed_url.query)
            try:
                window_days = int((params.get("window_days", ["30"])[0] or "30"))
            except ValueError:
                window_days = 30
            if window_days < 0:
                window_days = 30
            try:
                limit = int((params.get("limit", ["500"])[0] or "500"))
            except ValueError:
                limit = 500
            if limit < 0:
                limit = 0
            dry_run = str((params.get("dry_run", ["true"])[0] or "true")).lower() not in {"0", "false", "no"}

            active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
            active_avm_dir = active_data_root / "avm"
            try:
                output = _detail_collection_service(active_data_root).prepare_replay(
                    window_days=window_days,
                    limit=limit,
                    dry_run=dry_run,
                )
                (active_avm_dir / "archive_detail_replay.json").parent.mkdir(parents=True, exist_ok=True)
                (active_avm_dir / "archive_detail_replay.json").write_text(
                    json.dumps(output, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if not dry_run and output.get("prepared_count"):
                    load_data()
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_ARCHIVE_DETAIL_REPLAY_FAILED",
                    message="archive detail replay 准备失败",
                    details={"error": str(e)},
                )
                return

            self.send_json(output)


        elif self.path.startswith('/api/avm/pipeline_status'):
            try:
                self.send_json(AVM_PIPELINE.status())
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_PIPELINE_STATUS_FAILED",
                    message="pipeline 状态查询失败",
                    details={"error": str(e)},
                )

        elif self.path.startswith('/api/avm/merge_check'):
            try:
                self.send_json(AVM_PIPELINE.verify_merge_completeness())
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_MERGE_CHECK_FAILED",
                    message="merge completeness 校验失败",
                    details={"error": str(e)},
                )

        elif self.path.startswith('/api/get_item'):
            query = urlparse(self.path).query
            params = parse_qs(query)
            item_id = params.get('id', [''])[0]

            if item_id and DB_REPOSITORY.enabled:
                try:
                    db_item = DB_REPOSITORY.get_flat_item(item_id)
                    if db_item:
                        self.send_json(db_item)
                        return
                except Exception as db_get_error:
                    print(f"[DB] /api/get_item DB lookup failed for {item_id}: {db_get_error}")

            if item_id and item_id in SEEN_IDS:
                self.send_json(SEEN_IDS[item_id]["data"])
            else:
                self.send_json({})

        # --- Sniffing API (legacy endpoint removed, use /api/get_or_create_sniff_task) ---

        elif self.path.startswith('/api/get_or_create_sniff_task') or self.path.startswith('/api/collection/seeds/next_task'):
            # Seed collection task assignment
            parsed_url = urlparse(self.path)
            params = parse_qs(parsed_url.query)
            session_id = params.get('session_id', ['default'])[0]
            try:
                self.send_json(_seed_collection_service().next_task(session_id, paused=PAUSED))
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_SEED_NEXT_TASK_FAILED",
                    message="种子任务分发失败",
                    details={"error": str(e)},
                )


        elif self.path in ('/api/get_tasks', '/api/collection/details/tasks'):
            if PAUSED:
                self.send_json({"tasks": []})
                return

            # Dynamic Batch Size (increased to saturate 10 tabs or high concurrency)
            batch_size = 300

            if _prefer_db_task_reads():
                try:
                    result = _detail_collection_service().batch_tasks(
                        dispatched_tasks=DISPATCHED_TASKS,
                        cooldown_seconds=DISPATCH_COOLDOWN_SECONDS,
                        batch_size=batch_size,
                    )
                except Exception as e:
                    self.send_error_json(
                        status=500,
                        code="AVM_DETAIL_BATCH_TASKS_FAILED",
                        message="详情批量任务分发失败",
                        details={"error": str(e)},
                    )
                    return
                self.send_json({"tasks": result["tasks"], "total": result["total"], "done": result["done"]})
                if len(result["tasks"]) > 0:
                    print(f"Dispatched {len(result['tasks'])} tasks (Batch Limit: {batch_size}). Pending: {result['pending']}")
                else:
                    print(f"[DEBUG] Returned 0 tasks. Candidates=0")
                return
            else:
                tasks = []
                now = datetime.datetime.now()
                # Use a copy to iterate safely
                # CLEANUP: Remove finished tasks from PENDING list
                active_pending = []

                for tid in list(PENDING_TASKS):
                    if tid in SEEN_IDS:
                        item = SEEN_IDS[tid].get("data")
                        # If marked processed (saved), it's DONE. Remove from pending.
                        if item and item.get("is_processed"):
                             continue

                    active_pending.append(tid)

                # Update global pending list with cleaned version
                PENDING_TASKS[:] = active_pending

                pending_count = len(PENDING_TASKS)
                total_count = len(SEEN_IDS)
                done_count = total_count - pending_count

                print(f"[DEBUG] /get_tasks: PENDING={pending_count}, TOTAL={total_count}, DONE={done_count}")

                candidates = []
                skipped_cooldown = 0
                for tid in PENDING_TASKS:
                    last_time = DISPATCHED_TASKS.get(tid)
                    if last_time:
                        # Retry after configured cooldown silence window
                        if (now - last_time).total_seconds() < DISPATCH_COOLDOWN_SECONDS:
                            skipped_cooldown += 1
                            continue
                    candidates.append(tid)

            print(f"[DEBUG] Candidates after cooldown filter: {len(candidates)} (Skipped {skipped_cooldown} due to cooldown)")

            for candidate in candidates[:batch_size]:
                if _prefer_db_task_reads():
                    item_id = candidate["id"]
                    tasks.append({
                        "id": item_id,
                        "url": candidate.get("url")
                    })
                    DISPATCHED_TASKS[item_id] = now
                else:
                    item_id = candidate
                    if item_id in SEEN_IDS:
                        item = SEEN_IDS[item_id]["data"]
                        # Double check process status
                        if item.get("is_processed"):
                            continue

                        tasks.append({
                            "id": item_id,
                            "url": item.get("url")
                        })
                        DISPATCHED_TASKS[item_id] = now

            self.send_json({
                "tasks": tasks,
                "total": total_count,
                "done": done_count
            })
            if len(tasks) > 0:
                print(f"Dispatched {len(tasks)} tasks (Batch Limit: {batch_size}). Pending: {pending_count}")
            else:
                print(f"[DEBUG] Returned 0 tasks. Candidates={len(candidates)}")

        elif self.path == '/api/resume':
            PAUSED = False
            # Clear emergency flag if it exists
            flag_path = os.path.join(DATA_DIR, 'force_unlock.flag')
            if os.path.exists(flag_path):
                try: os.remove(flag_path)
                except: pass
            print("System RESUMED (via API).")
            self.send_json({"status": "resumed"})

        else:
            if request_path.startswith('/api/'):
                self.send_error_json(
                    status=404,
                    code="AVM_ENDPOINT_NOT_FOUND",
                    message="未找到接口",
                    details={"path": request_path},
                )
            else:
                self.send_response(404)
                self.end_headers()

    def do_POST(self):
        global PAUSED, LAST_REQUEST_TIME
        LAST_REQUEST_TIME = time.time()  # Update watchdog timer

        # --- Sniffing API (POST to add next pages) ---
        if self.path in ('/api/report_sniff_status', '/api/collection/seeds/report_progress'):
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(data, dict):
                self.send_invalid_request_body(data)
                return
            try:
                url = data.get("url")
                has_next = data.get("has_next", True)
                is_empty = data.get("is_empty", False)
                page_num = data.get("page_num", 1)
                total_pages = data.get("total_pages")
                zero_bid_detected = data.get("zero_bid_detected", False)

                log_msg = f"[SNIFF REPORT] Page {page_num} | Next: {has_next} | Empty: {is_empty} | TotalPages: {total_pages}"
                if zero_bid_detected:
                    log_msg += " | [ZERO-BID EARLY TERMINATION]"
                print(log_msg + f" | URL: {url}")

                if url:
                    self.send_json(_seed_collection_service().report_progress(data))
                else:
                    self.send_error_json(
                        status=400,
                        code="AVM_SEED_PROGRESS_MISSING_URL",
                        message="缺少 URL",
                        details={"required": ["url"]},
                    )
            except Exception as e:
                 print(f"Error in report_sniff_status: {e}")
                 self.send_error_json(
                     status=500,
                     code="AVM_SEED_PROGRESS_FAILED",
                     message="种子进度回报失败",
                     details={"error": str(e)},
                 )





        elif self.path in MANUAL_REVIEW_RECEIPT_ENDPOINTS:
            content_length = int(self.headers['Content-Length']) if self.headers.get('Content-Length') else 0
            try:
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(payload, dict):
                self.send_invalid_request_body(payload)
                return

            token_valid, token_error = _verify_control_plane_token(self.headers)
            if not token_valid:
                self.send_error_json(
                    status=403,
                    code=token_error["code"],
                    message=token_error["message"],
                    details=token_error.get("details", {}),
                )
                return

            valid, error_payload = _validate_manual_review_receipt_payload(payload if isinstance(payload, dict) else {})
            if not valid:
                self.send_error_json(
                    status=400,
                    code=error_payload["code"],
                    message=error_payload["message"],
                    details=error_payload.get("details", {}),
                )
                return

            active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
            try:
                store_path = _manual_review_receipt_store_path(active_data_root)
                receipt = {
                    "action": payload["action"],
                    "ready_signal": payload["ready_signal"],
                    "status": payload["status"],
                    "payload": dict(payload.get("payload") or {}),
                }
                if isinstance(payload.get("resolution_notes"), str) and payload.get("resolution_notes", "").strip():
                    receipt["resolution_notes"] = payload["resolution_notes"].strip()
                if isinstance(payload.get("source"), str) and payload.get("source", "").strip():
                    receipt["source"] = payload["source"].strip()

                operation_result = upsert_manual_review_receipt(
                    store_path,
                    receipt,
                    repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
                )
                context = _manual_review_receipt_context(active_data_root)
                mode = str(payload.get("mode", "sync") or "sync").lower()
                maintenance_options = _normalize_manual_review_maintenance_options(payload.get("maintenance"))
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_MANUAL_REVIEW_RECEIPT_UPSERT_FAILED",
                    message="manual review receipt 写入失败",
                    details={"error": str(e)},
                )
                return
            response = {
                "status": "ok",
                "operation": operation_result["operation"],
                "execution_mode": mode,
                "maintenance_triggered": False,
                "receipt": operation_result["receipt"],
                "manual_review_receipt_summary": context["manual_review_receipt_summary"],
                "manual_review_receipt_jobs_summary": context["manual_review_receipt_jobs_summary"],
                "manual_review_control_plane_storage": context["manual_review_control_plane_storage"],
                "manual_review_control_plane_backup": context["manual_review_control_plane_backup"],
                "manual_review_control_plane_backup_repairs_summary": context["manual_review_control_plane_backup_repairs_summary"],
                "manual_review_control_plane_integrity": context["manual_review_control_plane_integrity"],
                "manual_review_control_plane_integrity_history_summary": context["manual_review_control_plane_integrity_history_summary"],
                "manual_review_control_plane_stability": context["manual_review_control_plane_stability"],
                "manual_review_control_plane_guidance": context["manual_review_control_plane_guidance"],
                "operator_overview": context["operator_overview"],
            }
            if mode == "sync":
                try:
                    maintenance_report = _run_manual_review_receipt_maintenance(active_data_root, maintenance_options)
                except Exception as e:
                    self.send_error_json(
                        status=500,
                        code="AVM_MANUAL_REVIEW_RECEIPT_MAINTENANCE_FAILED",
                        message="receipt 提交后 maintenance 执行失败",
                        details={"error": str(e)},
                    )
                    return
                try:
                    append_manual_review_receipt_operation(
                        _manual_review_receipt_operations_path(active_data_root),
                        operation=operation_result["operation"],
                        receipt=operation_result["receipt"],
                        execution_mode="sync",
                        repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
                    )
                    response["maintenance_triggered"] = True
                    response["maintenance_report"] = maintenance_report
                    response["manual_review_receipt_summary"] = maintenance_report.get("manual_review_receipt_summary", context["manual_review_receipt_summary"])
                    response["operator_overview"] = maintenance_report.get("operator_overview", context["operator_overview"])
                    response["manual_review_receipt_jobs_summary"] = _manual_review_receipt_jobs_summary(active_data_root)
                    response["manual_review_control_plane_storage"] = _manual_review_control_plane_storage(active_data_root)
                    response["manual_review_control_plane_backup"] = _manual_review_control_plane_backup(active_data_root)
                    response["manual_review_control_plane_backup_repairs_summary"] = _manual_review_control_plane_backup_repairs_summary(active_data_root)
                    response["manual_review_control_plane_integrity"] = _manual_review_control_plane_integrity(active_data_root)
                    response["manual_review_control_plane_integrity_history_summary"] = _manual_review_control_plane_integrity_history_summary(active_data_root)
                    response["manual_review_control_plane_stability"] = _manual_review_control_plane_stability(active_data_root)
                    response["manual_review_control_plane_guidance"] = _manual_review_control_plane_guidance(active_data_root)
                except Exception as e:
                    self.send_error_json(
                        status=500,
                        code="AVM_MANUAL_REVIEW_RECEIPT_SYNC_FINALIZE_FAILED",
                        message="manual review receipt 同步 maintenance 收尾失败",
                        details={"error": str(e)},
                    )
                    return
            else:
                try:
                    manager = _get_manual_review_maintenance_manager(active_data_root)
                    job = manager.enqueue(
                        receipt_key={
                            "action": operation_result["receipt"]["action"],
                            "ready_signal": operation_result["receipt"]["ready_signal"],
                        },
                        maintenance_options=maintenance_options,
                    )
                    append_manual_review_receipt_operation(
                        _manual_review_receipt_operations_path(active_data_root),
                        operation=operation_result["operation"],
                        receipt=operation_result["receipt"],
                        execution_mode="async",
                        maintenance_job_id=job["job_id"],
                        repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
                    )
                    response["maintenance_triggered"] = True
                    response["maintenance_job_id"] = job["job_id"]
                    response["maintenance_job_status"] = job["status"]
                    response["manual_review_receipt_jobs_summary"] = _manual_review_receipt_jobs_summary(active_data_root)
                    response["manual_review_control_plane_storage"] = _manual_review_control_plane_storage(active_data_root)
                    response["manual_review_control_plane_backup"] = _manual_review_control_plane_backup(active_data_root)
                    response["manual_review_control_plane_backup_repairs_summary"] = _manual_review_control_plane_backup_repairs_summary(active_data_root)
                    response["manual_review_control_plane_integrity"] = _manual_review_control_plane_integrity(active_data_root)
                    response["manual_review_control_plane_integrity_history_summary"] = _manual_review_control_plane_integrity_history_summary(active_data_root)
                    response["manual_review_control_plane_stability"] = _manual_review_control_plane_stability(active_data_root)
                    response["manual_review_control_plane_guidance"] = _manual_review_control_plane_guidance(active_data_root)
                except Exception as e:
                    self.send_error_json(
                        status=500,
                        code="AVM_MANUAL_REVIEW_RECEIPT_ENQUEUE_FAILED",
                        message="manual review receipt 异步 maintenance 入队失败",
                        details={"error": str(e)},
                    )
                    return
            self.send_json(response)

        elif self.path in ('/api/avm/run', '/api/analysis/pipeline/run'):
            content_length = int(self.headers['Content-Length']) if self.headers.get('Content-Length') else 0
            payload = {}
            if content_length > 0:
                try:
                    payload = json.loads(self.rfile.read(content_length).decode('utf-8'))
                except Exception:
                    self.send_error_json(
                        status=400,
                        code="AVM_INVALID_JSON",
                        message="请求体不是合法 JSON",
                        details={},
                    )
                    return
            if not isinstance(payload, dict):
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_REQUEST_BODY",
                    message="请求体必须是 JSON 对象",
                    details={
                        "expected_type": "object",
                        "received_type": _json_payload_type_name(payload),
                    },
                )
                return

            mode = str(payload.get("mode", "async")).lower()
            invalid_fields = []
            try:
                alerts_threshold = float(payload.get("alerts_threshold", 0.15))
            except (TypeError, ValueError):
                alerts_threshold = None
                invalid_fields.append("alerts_threshold")
            try:
                alerts_limit = int(payload.get("alerts_limit", 500))
            except (TypeError, ValueError):
                alerts_limit = None
                invalid_fields.append("alerts_limit")
            if invalid_fields:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_PIPELINE_CONFIG",
                    message="pipeline 配置参数无效",
                    details={"invalid_fields": invalid_fields},
                )
                return
            config = AVMPipelineConfig(
                data_dir=payload.get("data_dir", DATA_DIR),
                alerts_threshold=alerts_threshold,
                alerts_limit=alerts_limit,
            )
            try:
                result = AVM_PIPELINE.run(async_mode=(mode != "sync"), config=config)
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_PIPELINE_RUN_FAILED",
                    message="pipeline 执行失败",
                    details={"error": str(e)},
                )
                return
            self.send_json(result)

        elif self.path in ('/api/avm/evaluate', '/api/analysis/evaluate'):
            content_length = int(self.headers['Content-Length']) if self.headers.get('Content-Length') else 0
            try:
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(payload, dict):
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_REQUEST_BODY",
                    message="请求体必须是 JSON 对象",
                    details={
                        "expected_type": "object",
                        "received_type": _json_payload_type_name(payload),
                    },
                )
                return

            subject = payload.get("subject") if isinstance(payload.get("subject"), dict) else {}
            if not subject:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_SUBJECT",
                    message="缺少 subject 对象",
                    details={"required": ["subject"]},
                )
                return

            if subject.get("area_sqm") in (None, ""):
                self.send_error_json(
                    status=400,
                    code="AVM_MISSING_AREA",
                    message="subject.area_sqm 为必填",
                    details={"required": ["subject.area_sqm"]},
                )
                return

            try:
                result = AVM_SERVICE.evaluate_request(payload)
            except Exception as e:
                print(f"[AVM] Evaluate failed: {e}")
                self.send_error_json(
                    status=500,
                    code="AVM_EVALUATE_FAILED",
                    message="评估失败",
                    details={"error": str(e)},
                )
                return

            self.send_json(result)

        elif self.path in ('/api/avm/recent_enrich_maintenance', '/api/collection/details/maintenance'):
            content_length = int(self.headers['Content-Length']) if self.headers.get('Content-Length') else 0
            try:
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(payload, dict):
                self.send_invalid_request_body(payload)
                return

            active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
            active_avm_dir = active_data_root / "avm"
            try:
                result = _detail_collection_service(active_data_root).run_maintenance(
                    window_days=int(payload.get("window_days", 7) or 7),
                    archive_limit=int(payload.get("archive_limit", 200) or 200),
                    sample_limit=int(payload.get("sample_limit", 20) or 20),
                    replay_limit=int(payload.get("replay_limit", 100) or 100),
                    fetch_limit=int(payload.get("fetch_limit", 20) or 20),
                    fetch_timeout=int(payload.get("fetch_timeout", 15) or 15),
                    dry_run=bool(payload.get("dry_run", True)),
                    extract_risk=bool(payload.get("extract_risk", False)),
                    prepare_replay=bool(payload.get("prepare_replay", False)),
                    fetch_archives=bool(payload.get("fetch_archives", False)),
                )
                (active_avm_dir / "recent_enrich_maintenance.json").parent.mkdir(parents=True, exist_ok=True)
                (active_avm_dir / "recent_enrich_maintenance.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if not bool(payload.get("dry_run", True)) and result.get("detail_replay_preparation", {}).get("prepared_count"):
                    load_data()
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_RECENT_ENRICH_MAINTENANCE_FAILED",
                    message="recent enrich maintenance 执行失败",
                    details={"error": str(e)},
                )
                return

            self.send_json(result)

        elif self.path in ('/api/avm/fetch_missing_detail_archives', '/api/collection/details/fetch_missing'):
            content_length = int(self.headers['Content-Length']) if self.headers.get('Content-Length') else 0
            try:
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(payload, dict):
                self.send_invalid_request_body(payload)
                return

            active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
            active_avm_dir = active_data_root / "avm"
            try:
                result = _detail_collection_service(active_data_root).fetch_missing_archives(
                    limit=int(payload.get("limit", 20) or 20),
                    timeout=int(payload.get("timeout", 15) or 15),
                    extract_risk=bool(payload.get("extract_risk", False)),
                    dry_run=bool(payload.get("dry_run", True)),
                )
                (active_avm_dir / "fetch_missing_detail_archives.json").parent.mkdir(parents=True, exist_ok=True)
                (active_avm_dir / "fetch_missing_detail_archives.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if not bool(payload.get("dry_run", True)) and result.get("fetched_count"):
                    load_data()
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED",
                    message="缺失详情归档抓取失败",
                    details={"error": str(e)},
                )
                return

            self.send_json(result)

        elif self.path in ('/api/avm/archive_detail_replay', '/api/collection/details/prepare_replay'):
            content_length = int(self.headers['Content-Length']) if self.headers.get('Content-Length') else 0
            try:
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(payload, dict):
                self.send_invalid_request_body(payload)
                return

            active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
            active_avm_dir = active_data_root / "avm"
            try:
                result = _detail_collection_service(active_data_root).prepare_replay(
                    window_days=int(payload.get("window_days", 30) or 30),
                    limit=int(payload.get("limit", 500) or 500),
                    dry_run=bool(payload.get("dry_run", True)),
                )
                (active_avm_dir / "archive_detail_replay.json").parent.mkdir(parents=True, exist_ok=True)
                (active_avm_dir / "archive_detail_replay.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if not bool(payload.get("dry_run", True)) and result.get("prepared_count"):
                    load_data()
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_ARCHIVE_DETAIL_REPLAY_FAILED",
                    message="archive detail replay 执行失败",
                    details={"error": str(e)},
                )
                return

            self.send_json(result)

        elif self.path == '/api/avm/start_all_subtasks':
            try:
                result = AVM_PIPELINE.run(async_mode=True, config=AVMPipelineConfig(data_dir=DATA_DIR))
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_START_ALL_SUBTASKS_FAILED",
                    message="启动全部子任务失败",
                    details={"error": str(e)},
                )
                return
            self.send_json(result)

        elif self.path == '/api/avm/run_all_subtasks_sync':
            try:
                result = AVM_PIPELINE.run(async_mode=False, config=AVMPipelineConfig(data_dir=DATA_DIR))
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_RUN_ALL_SUBTASKS_SYNC_FAILED",
                    message="同步执行全部子任务失败",
                    details={"error": str(e)},
                )
                return
            self.send_json(result)

        elif self.path == '/api/save_locations':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(data, dict):
                self.send_invalid_request_body(data)
                return

            try:
                new_locations = data.get("locations", [])

                loc_file = os.path.join(DATA_DIR, "collected_locations.json")
                existing_locs = {}

                if os.path.exists(loc_file):
                    try:
                        with open(loc_file, "r", encoding="utf-8") as f:
                            existing_locs = {item['code']: item['name'] for item in json.load(f)}
                    except: pass

                updated = False
                for loc in new_locations:
                    code = str(loc.get('code'))
                    name = loc.get('name')
                    if code and name:
                        if code not in existing_locs:
                            existing_locs[code] = name
                            updated = True

                if updated:
                    # Convert back to list
                    final_list = [{"code": k, "name": v} for k, v in existing_locs.items()]
                    with open(loc_file, "w", encoding="utf-8") as f:
                        json.dump(final_list, f, ensure_ascii=False, indent=2)
                    print(f"Saved {len(new_locations)} locations. Total unique: {len(final_list)}")

                self.send_json({"status": "ok", "count": len(new_locations)})
            except Exception as e:
                print(f"Error saving locations: {e}")
                self.send_error_json(
                    status=500,
                    code="AVM_SAVE_LOCATIONS_FAILED",
                    message="行政区划保存失败",
                    details={"error": str(e)},
                )

        elif self.path in ('/api/area_result', '/api/collection/details/area_result'):
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(data, dict):
                self.send_invalid_request_body(data)
                return
            try:
                item_id = str(data.get("id"))
                result = _detail_collection_service().apply_working_item_patch(
                    item_id=item_id,
                    patch_data=data,
                    event_type="area_result",
                    get_working_item=_get_working_item,
                    apply_flat_override_patch=_apply_flat_override_patch,
                    reset_structured_sections_for_resync=_reset_structured_sections_for_resync,
                    update_file_global=update_file_global,
                    persist_item_to_db=persist_item_to_db,
                    evict_runtime_item=_evict_runtime_item,
                    prefer_db_task_reads=_prefer_db_task_reads,
                    pending_tasks=PENDING_TASKS,
                    mark_processed=True,
                )
                if result["status"] == "ok":
                    print(f"[AREA RESULT] Updated {item_id} | Area: {data.get('建筑面积', 0)}")
                    self.send_json(result)
                else:
                    print(f"[AREA RESULT] Item {item_id} not found in index")
                    self.send_error_json(
                        status=404,
                        code="AVM_DETAIL_ITEM_NOT_FOUND",
                        message="未找到目标条目",
                        details={"id": item_id},
                    )
            except Exception as e:
                print(f"Error processing area result: {e}")
                self.send_error_json(
                    status=500,
                    code="AVM_DETAIL_AREA_RESULT_FAILED",
                    message="面积结果回写失败",
                    details={"error": str(e)},
                )

        elif self.path in ('/api/infer_location', '/api/collection/details/infer_location'):
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(data, dict):
                self.send_invalid_request_body(data)
                return
            try:
                address = data.get("address", "")
                title = data.get("title", "")

                print(f"[Infer Location] Request for: {address} | {title}")
                result = _detail_collection_service().infer_location(
                    address=address,
                    title=title,
                    item_id=data.get("id"),
                    chat_with_glm=llm_helper.chat_with_glm,
                    log_prediction_event=llm_helper.log_prediction_event,
                )
                self.send_json(result)

            except Exception as e:
                print(f"Error in infer_location: {e}")
                self.send_error_json(
                    status=500,
                    code="AVM_DETAIL_INFER_LOCATION_FAILED",
                    message="位置推断失败",
                    details={"error": str(e)},
                )

        elif self.path in ('/api/approve_area', '/api/collection/details/approve_area'):
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(data, dict):
                self.send_invalid_request_body(data)
                return
            try:
                item_id = str(data.get("id"))
                result = _detail_collection_service().apply_working_item_patch(
                    item_id=item_id,
                    patch_data=data,
                    event_type="manual_approve_area",
                    get_working_item=_get_working_item,
                    apply_flat_override_patch=_apply_flat_override_patch,
                    reset_structured_sections_for_resync=_reset_structured_sections_for_resync,
                    update_file_global=update_file_global,
                    persist_item_to_db=persist_item_to_db,
                    evict_runtime_item=_evict_runtime_item,
                    prefer_db_task_reads=_prefer_db_task_reads,
                    pending_tasks=PENDING_TASKS,
                    mark_processed=True,
                    force_status="done",
                )
                if result["status"] == "ok":
                    print(f"[APPROVE AREA] Manually Approved {item_id} | Area: {data.get('建筑面积', 0)}")
                    self.send_json(result)
                else:
                    # Treat as new override if ID provided but not found?
                    # For now just error or create new entry if we want to support manual add
                    print(f"[APPROVE AREA] Item {item_id} not found in index")
                    self.send_error_json(
                        status=404,
                        code="AVM_DETAIL_ITEM_NOT_FOUND",
                        message="未找到目标条目",
                        details={"id": item_id},
                    )
            except Exception as e:
                print(f"Error processing area approval: {e}")
                self.send_error_json(
                    status=500,
                    code="AVM_DETAIL_APPROVE_AREA_FAILED",
                    message="面积人工确认失败",
                    details={"error": str(e)},
                )

        elif self.path in ('/api/save', '/api/collection/seeds/batch'):
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data.decode('utf-8'))
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(data, dict):
                self.send_invalid_request_body(data)
                return

            try:
                self.send_json(handle_seed_batch_submission(data))

            except Exception as e:
                print(f"Error processing save: {e}")
                self.send_error_json(
                    status=500,
                    code="AVM_SEED_BATCH_FAILED",
                    message="种子批量提交失败",
                    details={"error": str(e)},
                )


        elif self.path == '/api/avm/screen':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length) if content_length > 0 else b'{}'
            try:
                payload = json.loads(post_data.decode('utf-8')) if post_data else {}
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(payload, dict):
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_REQUEST_BODY",
                    message="请求体必须是 JSON 对象",
                    details={
                        "expected_type": "object",
                        "received_type": _json_payload_type_name(payload),
                    },
                )
                return

            items = payload.get("items", [])
            if not isinstance(items, list):
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_SCREEN_ITEMS",
                    message="items 必须为数组",
                    details={"invalid_fields": ["items"]},
                )
                return

            threshold = payload.get("margin_threshold")
            try:
                if threshold is None:
                    threshold = get_effective_alert_threshold(DEFAULT_MARGIN_THRESHOLD)
                else:
                    threshold = float(threshold)
            except Exception:
                threshold = get_effective_alert_threshold(DEFAULT_MARGIN_THRESHOLD)

            try:
                results = []
                for raw in items:
                    if isinstance(raw, dict):
                        item_id = str(raw.get("id", "")).strip()
                    else:
                        item_id = str(raw).strip()

                    if not item_id:
                        continue

                    with DATA_LOCK:
                        entry = SEEN_IDS.get(item_id)
                    if entry is None and DB_REPOSITORY.enabled:
                        try:
                            db_item = DB_REPOSITORY.get_flat_item(item_id)
                        except Exception as db_screen_error:
                            print(f"[DB] screen item lookup failed item={item_id}: {db_screen_error}")
                            db_item = None
                        if db_item and entry is None:
                            entry = {"data": db_item}

                    source_data = dict(entry.get("data", {})) if entry else {}
                    if isinstance(raw, dict):
                        source_data.update(raw)

                    try:
                        prediction = AVM_SERVICE.predict_by_item_data(source_data)
                    except Exception:
                        prediction = {}
                    if prediction.get("predicted_price") is not None:
                        source_data["predicted_price"] = prediction.get("predicted_price")
                        source_data["predicted_unit_price"] = prediction.get("predicted_unit_price")
                        source_data["prediction"] = prediction

                    result = build_avm_result(item_id, source_data)
                    if prediction:
                        result["prediction"] = prediction
                        result["risk_validation"] = dict(prediction.get("risk_validation") or {})
                        result["manual_review_recommended"] = bool(prediction.get("manual_review_recommended"))
                        result["manual_review_reasons"] = list(prediction.get("manual_review_reasons") or [])
                    else:
                        result["risk_validation"] = {}
                        result["manual_review_recommended"] = False
                        result["manual_review_reasons"] = []
                    result["alert_blockers"] = build_alert_blockers(
                        margin=result.get("margin"),
                        threshold=threshold,
                        is_malignant_risk=bool(result.get("is_malignant_risk")),
                        payload=prediction,
                    )
                    result["meets_alert_threshold"] = len(result["alert_blockers"]) == 0
                    results.append(result)

                results.sort(key=lambda x: x.get("margin") if x.get("margin") is not None else -999, reverse=True)

                alerts = []
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for result in results:
                    if result["meets_alert_threshold"]:
                        alert = dict(result)
                        alert["created_at"] = now
                        alert["margin_threshold"] = threshold
                        alerts.append(alert)

                write_avm_alerts(alerts)
                summary = summarize_screen_results(results)

                self.send_json({
                    "model_version": AVM_SERVICE.model_version(),
                    "margin_formula": "(predicted_price - starting_price) / predicted_price",
                    "margin_threshold": threshold,
                    "total": len(results),
                    "alerts_written": len(alerts),
                    "summary": summary,
                    "results": results
                })
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_SCREEN_FAILED",
                    message="批量筛选执行失败",
                    details={"error": str(e)},
                )

        elif self.path == '/api/report_captcha':
            print("CAPTCHA REPORTED! Triggering Solver...")

            # Using ThreadPool to avoid blocking the server main loop
            try:
                executor.submit(self.run_solver)
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_CAPTCHA_SOLVER_QUEUE_FAILED",
                    message="验证码求解任务入队失败",
                    details={"error": str(e)},
                )
                return

            self.send_json({"status": "solving"})



        elif self.path == '/api/log':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                if not isinstance(data, dict):
                    self.send_invalid_request_body(data)
                    return
                msg = data.get("msg", "")
                is_error = data.get("isError", False)
                prefix = "[Client Error]" if is_error else "[Client Log]"
                print(f"{prefix} {msg}")
                self.send_json({"status": "ok"})
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )

        elif self.path.startswith('/api/upload'):
            try:
                query = urlparse(self.path).query
                params = parse_qs(query)
                item_id = params.get('id', [''])[0]
                filename = params.get('name', [''])[0]
                content_length = int(self.headers['Content-Length']) if self.headers.get('Content-Length') else 0

                if not item_id or not filename:
                    if content_length > 0:
                        self.rfile.read(content_length)
                    self.send_error_json(
                        status=400,
                        code="AVM_INVALID_UPLOAD_REQUEST",
                        message="缺少上传参数",
                        details={"required": ["id", "name"]},
                    )
                    return

                filename = unquote(filename)
                filename = filename.replace("\\", "")

                save_dir = os.path.join(DATA_DIR, "downloads", item_id)
                os.makedirs(save_dir, exist_ok=True)

                file_path = os.path.join(save_dir, filename)

                file_data = self.rfile.read(content_length)

                with open(file_path, "wb") as f:
                    f.write(file_data)

                print(f"Saved file: {filename} ({content_length} bytes)")
                self.send_json({"status": "saved"})

            except Exception as e:
                print(f"Upload failed: {e}")
                self.send_error_json(
                    status=500,
                    code="AVM_UPLOAD_FAILED",
                    message="文件上传失败",
                    details={"error": str(e)},
                )

        elif self.path in ('/api/update_item', '/api/collection/details/update_item'):
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data.decode('utf-8'))
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(data, dict):
                self.send_invalid_request_body(data)
                return
            try:
                item_id = str(data.get("id"))
                force_status = "failed_timeout" if data.get("status") == "failed_timeout" else None
                result = _detail_collection_service().apply_working_item_patch(
                    item_id=item_id,
                    patch_data=data,
                    event_type="update_item",
                    get_working_item=_get_working_item,
                    apply_flat_override_patch=_apply_flat_override_patch,
                    reset_structured_sections_for_resync=_reset_structured_sections_for_resync,
                    update_file_global=update_file_global,
                    persist_item_to_db=persist_item_to_db,
                    evict_runtime_item=_evict_runtime_item,
                    prefer_db_task_reads=_prefer_db_task_reads,
                    pending_tasks=PENDING_TASKS,
                    force_status=force_status,
                )
                if result["status"] == "ok":
                    if force_status == "failed_timeout":
                        print(f"Item {item_id} TIMED OUT.")
                    self.send_json({"status": "updated"})
                else:
                    self.send_json({"status": "id_not_found"})
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_DETAIL_UPDATE_ITEM_FAILED",
                    message="条目更新失败",
                    details={"error": str(e)},
                )

        elif self.path == '/api/get_next_task':
            legacy_entries = None if _prefer_db_task_reads() else list(SEEN_IDS.items())
            try:
                result = _detail_collection_service().next_visit_task(
                    dispatched_tasks=DISPATCHED_TASKS,
                    cooldown_seconds=DISPATCH_COOLDOWN_SECONDS,
                    legacy_entries=legacy_entries,
                )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_NEXT_VISIT_TASK_FAILED",
                    message="下一条访问任务分发失败",
                    details={"error": str(e)},
                )
                return
            self.send_json(result)

        elif self.path in ('/api/analyze_html', '/api/collection/details/html'):
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data.decode('utf-8'))
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(data, dict):
                self.send_invalid_request_body(data)
                return
            try:
                item_id = str(data.get("id"))
                html_content = data.get("html", "")
                status = data.get("status")  # NEW: Handle merged status update
                result = _detail_collection_service().submit_html(
                    item_id=item_id,
                    html_content=html_content,
                    status=status,
                    get_working_item=_get_working_item,
                    apply_flat_override_patch=_apply_flat_override_patch,
                    reset_structured_sections_for_resync=_reset_structured_sections_for_resync,
                    update_file_global=update_file_global,
                    persist_item_to_db=persist_item_to_db,
                    evict_runtime_item=_evict_runtime_item,
                    submit_task=submit_task,
                    prefer_db_task_reads=_prefer_db_task_reads,
                    pending_tasks=PENDING_TASKS,
                )
                self.send_json(result)

            except Exception as e:
                print(f"Error saving HTML content: {e}")
                self.send_error_json(
                    status=500,
                    code="AVM_DETAIL_ANALYZE_HTML_FAILED",
                    message="HTML 分析结果提交失败",
                    details={"error": str(e)},
                )

        else:
            request_path = urlparse(self.path).path
            if request_path.startswith('/api/'):
                self.send_error_json(
                    status=404,
                    code="AVM_ENDPOINT_NOT_FOUND",
                    message="未找到接口",
                    details={"path": request_path},
                )
            else:
                self.send_response(404)
                self.end_headers()

    def do_DELETE(self):
        global LAST_REQUEST_TIME
        LAST_REQUEST_TIME = time.time()

        if self.path in MANUAL_REVIEW_RECEIPT_ENDPOINTS:
            content_length = int(self.headers['Content-Length']) if self.headers.get('Content-Length') else 0
            try:
                payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
            except Exception:
                self.send_error_json(
                    status=400,
                    code="AVM_INVALID_JSON",
                    message="请求体不是合法 JSON",
                    details={},
                )
                return
            if not isinstance(payload, dict):
                self.send_invalid_request_body(payload)
                return

            token_valid, token_error = _verify_control_plane_token(self.headers)
            if not token_valid:
                self.send_error_json(
                    status=403,
                    code=token_error["code"],
                    message=token_error["message"],
                    details=token_error.get("details", {}),
                )
                return

            valid, error_payload = _validate_manual_review_receipt_delete_payload(payload if isinstance(payload, dict) else {})
            if not valid:
                self.send_error_json(
                    status=400,
                    code=error_payload["code"],
                    message=error_payload["message"],
                    details=error_payload.get("details", {}),
                )
                return

            active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
            try:
                result = delete_manual_review_receipt(
                    _manual_review_receipt_store_path(active_data_root),
                    action=str(payload["action"]),
                    ready_signal=str(payload["ready_signal"]),
                    repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
                )
                append_manual_review_receipt_operation(
                    _manual_review_receipt_operations_path(active_data_root),
                    operation="deleted",
                    receipt={
                        "action": payload["action"],
                        "ready_signal": payload["ready_signal"],
                        "status": "",
                        "payload": {},
                    },
                    execution_mode="delete",
                    deleted=bool(result["deleted"]),
                    repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
                )
                context = _manual_review_receipt_context(active_data_root)
                self.send_json(
                    {
                        "status": "ok",
                        "deleted": result["deleted"],
                        "receipt_count": result["receipt_count"],
                        "manual_review_receipt_summary": context["manual_review_receipt_summary"],
                        "manual_review_receipt_jobs_summary": context["manual_review_receipt_jobs_summary"],
                        "manual_review_control_plane_storage": context["manual_review_control_plane_storage"],
                        "manual_review_control_plane_backup": context["manual_review_control_plane_backup"],
                        "manual_review_control_plane_backup_repairs_summary": context["manual_review_control_plane_backup_repairs_summary"],
                        "manual_review_control_plane_integrity": context["manual_review_control_plane_integrity"],
                        "manual_review_control_plane_integrity_history_summary": context["manual_review_control_plane_integrity_history_summary"],
                        "manual_review_control_plane_stability": context["manual_review_control_plane_stability"],
                        "manual_review_control_plane_guidance": context["manual_review_control_plane_guidance"],
                        "operator_overview": context["operator_overview"],
                    }
                )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_MANUAL_REVIEW_RECEIPT_DELETE_FAILED",
                    message="manual review receipt 删除失败",
                    details={"error": str(e)},
                )
            return

        request_path = urlparse(self.path).path
        if request_path.startswith('/api/'):
            self.send_error_json(
                status=404,
                code="AVM_ENDPOINT_NOT_FOUND",
                message="未找到接口",
                details={"path": request_path},
            )
        else:
            self.send_response(404)
            self.end_headers()

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def send_error_json(self, status, code, message, details=None):
        self.send_response(status)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        payload = {
            "error": {
                "code": code,
                "message": message,
                "details": details or {}
            }
        }
        self.wfile.write(json.dumps(payload).encode('utf-8'))

    def send_invalid_request_body(self, payload):
        self.send_error_json(
            status=400,
            code="AVM_INVALID_REQUEST_BODY",
            message="请求体必须是 JSON 对象",
            details={
                "expected_type": "object",
                "received_type": _json_payload_type_name(payload),
            },
        )

    def update_file(self, file_path, item_id, new_data):
        update_file_global(file_path, item_id, new_data)

    def run_solver(self):
        """Run the captcha solver in background with server-level retry."""
        global PAUSED
        global SOLVER_RUNNING, SOLVER_START_TIME

        # Initialize if not present (hack for hot-reload or first run)
        if 'SOLVER_RUNNING' not in globals():
            SOLVER_RUNNING = False
            SOLVER_START_TIME = 0

        # Check existing lock state
        if SOLVER_RUNNING:
            elapsed = time.time() - SOLVER_START_TIME
            if elapsed < 120:  # Extended timeout for retries
                print(f"\033[93m[SOLVER] Solver already running for {int(elapsed)}s. Skipping.\033[0m")
                return
            else:
                print(f"\033[91m[SOLVER] Solver hung for {int(elapsed)}s. FORCE BREAKING LOCK.\033[0m")

        SERVER_MAX_ATTEMPTS = 2  # Server-level retries (solver has its own internal retries)

        try:
            SOLVER_RUNNING = True
            SOLVER_START_TIME = time.time()
            PAUSED = True
            print("\033[93m[SOLVER] Starting solver...\033[0m")

            success = False
            for server_attempt in range(SERVER_MAX_ATTEMPTS):
                if server_attempt > 0:
                    print(f"\033[93m[SOLVER] Server retry {server_attempt + 1}/{SERVER_MAX_ATTEMPTS} after delay...\033[0m")
                    time.sleep(3)

                success = solver.solve()
                if success:
                    break

            if success:
                print("\033[92m[SOLVER] ✅ Captcha Solved! Resuming system...\033[0m")
                PAUSED = False
            else:
                print("\033[91m[SOLVER] ❌ All solve attempts failed. System remains PAUSED.\033[0m")
                print("\033[91m[SOLVER] Manual intervention required. Please solve in Edge, then click 'Resume' or delete 'force_unlock.flag'.\033[0m")

                # Create a lock flag file for easy manual resuming via file system if API is stuck
                flag_path = os.path.join(DATA_DIR, 'force_unlock.flag')
                try:
                    with open(flag_path, 'w') as f:
                        f.write("Delete this file to force resume the queue after manual solving")
                except: pass

                # Wait for user to either hit API resume or delete the file
                while PAUSED:
                    if not os.path.exists(flag_path):
                        print("\033[92m[SOLVER] 🟢 Force unlock flag removed! Auto-resuming system...\033[0m")
                        PAUSED = False
                        break
                    time.sleep(2)

        except Exception as e:
            print(f"[SOLVER] Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            SOLVER_RUNNING = False
            elapsed = time.time() - SOLVER_START_TIME
            print(f"[SOLVER] Finished. Total time: {elapsed:.1f}s")

    def log_message(self, format, *args):
        return

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    print(f"Starting Data Receiver on port {PORT}...")
    print(f"Serving Pending Tasks from: {os.path.abspath(DATA_DIR)}")

    initialize_runtime(start_watchdog=True, ensure_browser=True)

    # Load AVM parameters at startup and enable hot-reload.
    AVM_CONFIG_MANAGER.load_on_startup()
    AVM_CONFIG_MANAGER.start_hot_reload_watcher()
    print(f"[AVM-CONFIG] Active config: {AVM_CONFIG_MANAGER.get_config()}")

    # Start the background AI processor
    import threading
    threading.Thread(target=background_file_processor, daemon=True).start()

    # Start the auto-tuner (adjusts concurrency limits every 5 minutes)
    threading.Thread(target=auto_tuner_thread, daemon=True).start()

    try:
        with ReusableTCPServer(("", PORT), DataHandler) as httpd:
            print("Server running. Press Ctrl+C to stop.")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nServer stopped by user.")
            except Exception as e:
                print(f"\nServer crashed: {e}")
                import traceback
                traceback.print_exc()
    except OSError as e:
        print(f"Error binding to port {PORT}: {e}")
