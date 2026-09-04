import http.server
import socketserver
import json
import os
import base64
import datetime
import hashlib
import glob
import mimetypes
import math
import hmac
from pathlib import Path
import threading
import tempfile
import time
import re
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from src import llm_helper
from src.avm_config import AVM_CONFIG_MANAGER
from src.avm_config import DEFAULT_AVM_CONFIG
from src.avm_config import get_effective_alert_threshold
from src.captcha_solver import CaptchaSolver

# Import Captcha Solver
solver = CaptchaSolver()


def _normalize_solver_target_url(value: Any) -> str:
    target_url = str(value or "").strip()
    if not target_url:
        return ""

    try:
        parsed = urlsplit(target_url)
    except ValueError:
        return target_url

    if (parsed.hostname or "").lower() != "sf.taobao.com":
        return target_url

    path = parsed.path
    punish_marker = "/_____tmd_____/punish"
    marker_index = path.lower().find(punish_marker)
    was_punish_url = marker_index >= 0
    if marker_index >= 0:
        path = path[:marker_index]
    while "//" in path:
        path = path.replace("//", "/")
    if "/list/" not in path.lower():
        return target_url

    source_query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query = [
        (key, source_query[key])
        for key in ("location_code", "st_param", "auction_start_seg", "page")
        if str(source_query.get(key) or "").strip()
    ]
    if was_punish_url or "__captcha_solver_bg" in source_query:
        query.append(("__captcha_solver_bg", "1"))
    return urlunsplit((parsed.scheme or "https", parsed.netloc, path, urlencode(query), ""))


def _solver_target_requires_manual_only(solver_request: dict[str, Any] | None) -> bool:
    request = solver_request if isinstance(solver_request, dict) else {}
    target_url = str(request.get("target_url") or request.get("url") or "").strip()
    if not target_url:
        return False
    try:
        hostname = str(urlsplit(target_url).hostname or "").strip().lower()
    except ValueError:
        return False
    is_taobao = hostname == "taobao.com" or hostname.endswith(".taobao.com")
    return bool(is_taobao and not _real_taobao_auto_solver_enabled())


def _normalize_solver_cdp_endpoint(value):
    cdp_endpoint = str(value or "").strip()
    runtime_endpoint = str(os.getenv("FAPAI_CDP_ENDPOINT") or "").strip().rstrip("/")

    if not cdp_endpoint:
        return runtime_endpoint
    if not runtime_endpoint:
        return cdp_endpoint

    try:
        requested = urlparse(cdp_endpoint)
        runtime = urlparse(runtime_endpoint)
    except ValueError:
        return cdp_endpoint

    if requested.hostname not in {"127.0.0.1", "localhost", "0.0.0.0"}:
        return cdp_endpoint

    scheme = runtime.scheme or requested.scheme or "http"
    host = runtime.hostname or requested.hostname
    port = requested.port or runtime.port
    if not host:
        return runtime_endpoint
    if port is None:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _build_solver_request(payload):
    if not isinstance(payload, dict):
        return {}

    request: dict[str, str] = {}
    cdp_endpoint = _normalize_solver_cdp_endpoint(payload.get("cdp_endpoint"))
    target_url = _normalize_solver_target_url(payload.get("target_url") or payload.get("url"))
    challenge_target_url = _normalize_solver_target_url(payload.get("challenge_target_url"))

    if cdp_endpoint:
        request["cdp_endpoint"] = cdp_endpoint
    if target_url:
        request["target_url"] = target_url
    if challenge_target_url:
        request["challenge_target_url"] = challenge_target_url
    node_id = str(payload.get("node_id") or "").strip()
    if node_id:
        request["node_id"] = node_id
    cookie_snapshot_path = str(payload.get("cookie_snapshot_path") or "").strip()
    if cookie_snapshot_path:
        request["cookie_snapshot_path"] = cookie_snapshot_path
    scope = _normalize_challenge_scope(payload.get("scope"))
    if scope:
        request["scope"] = scope
    return request


def _refresh_solver_last_request(request_payload):
    global SOLVER_LAST_REQUEST

    request = _build_solver_request(request_payload)
    if not request:
        return dict(SOLVER_LAST_REQUEST) if isinstance(SOLVER_LAST_REQUEST, dict) else {}

    merged = dict(SOLVER_LAST_REQUEST) if isinstance(SOLVER_LAST_REQUEST, dict) else {}
    merged.update(request)
    SOLVER_LAST_REQUEST = _build_solver_request(merged)
    return dict(SOLVER_LAST_REQUEST)


def _build_solver_for_request(request_payload):
    if request_payload and isinstance(request_payload, dict):
        target_url = request_payload.get("challenge_target_url") or request_payload.get("target_url")
        if request_payload.get("cdp_endpoint") or target_url:
            return CaptchaSolver(
                cdp_endpoint=_normalize_solver_cdp_endpoint(request_payload.get("cdp_endpoint")),
                target_url=target_url,
            )
    return solver

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
from src.nas_auth_recovery import NasAuthRecoveryCoordinator
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
REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_DESKTOP_DIST = REPO_ROOT / "collector-desktop" / "dist"
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
COLLECTION_PAUSE_REASON = None
SOLVER_LOCK = threading.Lock()
FILE_LOCK = threading.Lock()
DATA_LOCK = threading.Lock() # Protects SEEN_IDS and PENDING_TASKS
CURRENT_PROCESSING = set() # Track running tasks to avoid duplicate submission
SOLVER_RUNNING = False
SOLVER_PENDING_TOKEN = None
SOLVER_START_TIME = 0
SOLVER_LAST_STATUS = "idle"
SOLVER_LAST_FAILURE_REASON = None
SOLVER_LAST_FINISHED_TIME = 0
SOLVER_LAST_REQUEST = {}
SOLVER_MANUAL_RESUME_EPOCH = 0
SOLVER_CANCEL_EPOCH = 0
SOLVER_MANUAL_REQUIRED_EPOCH = 0
SOLVER_MANUAL_ONLY = False
SOLVER_MANUAL_RETRY_LAST_EPOCH = 0
SOLVER_MANUAL_RETRY_ATTEMPTS = 0
SOLVER_CHALLENGE_ID = None
CHALLENGE_SCOPES = ("seed", "detail")
SOLVER_SCOPE_LOCK = threading.RLock()
SOLVER_SCOPE_STATES: dict[str, dict[str, Any]] = {
    scope: {
        "challenge_id": None,
        "last_request": {},
        "first_seen_epoch": 0.0,
        "pause_started_epoch": 0.0,
        "paused": False,
        "pause_reason": None,
        "manual_required": False,
        "manual_only": False,
        "last_status": "idle",
        "last_failure_reason": None,
        "force_reset_required": False,
    }
    for scope in CHALLENGE_SCOPES
}
SOLVER_SCOPE_STATE_ROOT: str | None = None
CHALLENGE_FORCE_RESET_SECONDS = max(
    1.0,
    float(os.getenv("FAPAI_CHALLENGE_FORCE_RESET_SECONDS", "900")),
)
SOLVER_LAST_AUTH_COMPLETED_TIME = 0.0
SOLVER_LAST_AUTH_COMPLETED_REQUEST: dict[str, Any] = {}
SOLVER_LAST_AUTH_DETAIL_CAPTURED_COUNT: int | None = None
SOLVER_AUTH_REPORT_GRACE_SECONDS = max(
    0.0,
    float(os.getenv("FAPAI_SOLVER_AUTH_REPORT_GRACE_SECONDS", "90")),
)
SOLVER_DETAIL_PROGRESS_GRACE_SECONDS = max(
    SOLVER_AUTH_REPORT_GRACE_SECONDS,
    float(os.getenv("FAPAI_SOLVER_DETAIL_PROGRESS_GRACE_SECONDS", "180")),
)
SOLVER_DETAIL_PROGRESS_GRACE_MIN_ITEMS = max(
    1,
    int(os.getenv("FAPAI_SOLVER_DETAIL_PROGRESS_GRACE_MIN_ITEMS", "1")),
)
SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS = max(
    0.0,
    float(os.getenv("FAPAI_SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS", "180")),
)
SOLVER_SCOPE_FORCE_RESET_RECOVERIES: dict[str, dict[str, Any]] = {
    scope: {} for scope in CHALLENGE_SCOPES
}
AUTH_COMPLETION_LOCK = threading.Lock()
AUTH_COMPLETION_CONFIRMATIONS: dict[str, float] = {}
AUTH_COMPLETION_FINALIZE_LOCK = threading.Lock()
AUTH_COOKIE_SNAPSHOT_LOCK = threading.Lock()
AUTH_COOKIE_SNAPSHOT_THREAD: threading.Thread | None = None
AUTH_COOKIE_SNAPSHOT_STATE: dict[str, Any] = {
    "status": "idle",
    "completion_id": None,
    "attempts": 0,
    "max_attempts": 0,
    "refreshed": False,
    "retry_queued": False,
}
NAS_AUTH_RECOVERY_POLL_SECONDS = max(
    5.0,
    float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_POLL_SECONDS", "60")),
)
NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS = max(
    60.0,
    float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS", "300")),
)
NAS_AUTH_RECOVERY_STATE_PATH = Path(
    os.getenv("FAPAI_NAS_AUTH_RECOVERY_STATE_PATH")
    or Path(os.getenv("FAPAI_SOLVER_STATE_DIR") or DATA_DIR) / "nas-auth-recovery.json"
)
NAS_AUTH_RECOVERY_TOKEN_FILE = Path(
    os.getenv("FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE")
    or Path(os.getenv("FAPAI_SOLVER_STATE_DIR") or DATA_DIR) / "nas-auth-recovery.token"
)
NAS_AUTH_RECOVERY = NasAuthRecoveryCoordinator(
    NAS_AUTH_RECOVERY_STATE_PATH,
    enabled=str(os.getenv("FAPAI_NAS_AUTH_RECOVERY_ENABLED", "0")).strip().lower()
    in {"1", "true", "yes", "on"},
    stall_seconds=float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_STALL_SECONDS", "1800")),
    pc1_timeout_seconds=float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_PC1_TIMEOUT_SECONDS", "1800")),
    pc2_timeout_seconds=float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_PC2_TIMEOUT_SECONDS", "600")),
    verify_timeout_seconds=float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_VERIFY_TIMEOUT_SECONDS", "600")),
    cooldown_seconds=float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_COOLDOWN_SECONDS", "1800")),
)
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

__all__ = [name for name in globals() if not name.startswith("__")]
