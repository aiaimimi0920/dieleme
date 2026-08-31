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
import re
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

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


def _runtime_env_flag(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _real_taobao_auto_solver_enabled() -> bool:
    """Require an explicit production opt-in for automatic Taobao solving."""
    return _runtime_env_flag("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", False)


def _normalize_challenge_scope(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"list", "seed", "search", "listing"}:
        return "seed"
    if normalized in {"detail", "details", "item"}:
        return "detail"
    return ""


def _challenge_scope_for_request(request_payload: dict[str, Any] | None) -> str:
    payload = request_payload if isinstance(request_payload, dict) else {}
    explicit = _normalize_challenge_scope(payload.get("scope"))
    if explicit:
        return explicit
    target_url = str(
        payload.get("challenge_target_url")
        or payload.get("target_url")
        or payload.get("url")
        or ""
    )
    return _normalize_challenge_scope(_solver_request_scope_from_target_url(target_url))


def _new_solver_scope_state() -> dict[str, Any]:
    return {
        "challenge_id": None,
        "last_request": {},
        "first_seen_epoch": 0.0,
        "pause_started_epoch": 0.0,
        "paused": False,
        "pause_reason": None,
        "manual_required": False,
        "last_status": "idle",
        "last_failure_reason": None,
        "force_reset_required": False,
    }


def _solver_scope_state_path(scope: str) -> Path:
    normalized_scope = _normalize_challenge_scope(scope) or "unknown"
    return _solver_scope_state_root_path() / f"solver-challenge-state-{normalized_scope}.json"


def _solver_scope_state_root_path() -> Path:
    global SOLVER_SCOPE_STATE_ROOT
    configured_state_dir = str(os.getenv("FAPAI_SOLVER_STATE_DIR") or "").strip()
    if configured_state_dir:
        state_dir = configured_state_dir
    else:
        # Keep scoped receipts beside the legacy receipt.  Besides preserving
        # one durable state root in production, this lets callers/tests that
        # redirect the legacy path atomically redirect both state machines.
        try:
            state_dir = str(Path(_solver_challenge_state_path()).parent)
        except Exception:
            state_dir = DATA_DIR
    state_dir = str(state_dir).strip() or DATA_DIR
    try:
        root = str(Path(state_dir).expanduser().resolve())
    except OSError:
        root = str(Path(state_dir).expanduser())
    with SOLVER_SCOPE_LOCK:
        if SOLVER_SCOPE_STATE_ROOT != root:
            SOLVER_SCOPE_STATE_ROOT = root
            SOLVER_SCOPE_STATES.clear()
            SOLVER_SCOPE_STATES.update({scope: _new_solver_scope_state() for scope in CHALLENGE_SCOPES})
    return Path(root)


def _read_solver_scope_state(scope: str) -> dict[str, Any]:
    normalized_scope = _normalize_challenge_scope(scope)
    if not normalized_scope:
        return _new_solver_scope_state()
    with SOLVER_SCOPE_LOCK:
        state = dict(SOLVER_SCOPE_STATES.get(normalized_scope) or _new_solver_scope_state())
    state_path = _solver_scope_state_path(normalized_scope)
    if state.get("challenge_id") and not state_path.exists():
        # Do not let an in-memory latch from a previous runtime/test leak into
        # a new state directory. Persisted latches are the source of truth for
        # scopes that are not the latest request.
        return _new_solver_scope_state()
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return state
    if not isinstance(payload, dict) or payload.get("active") is not True:
        # An explicit inactive receipt wins over any in-memory state left by a
        # prior test/process.  This also prevents a cleared scope from keeping
        # the aggregate pause latch set after a restart.
        cleared = _new_solver_scope_state()
        with SOLVER_SCOPE_LOCK:
            SOLVER_SCOPE_STATES[normalized_scope] = dict(cleared)
        return cleared
    state.update(
        {
            "challenge_id": str(payload.get("challenge_id") or "").strip() or None,
            "last_request": dict(payload.get("last_request") or {}) if isinstance(payload.get("last_request"), dict) else {},
            "first_seen_epoch": float(payload.get("first_seen_epoch") or payload.get("created_at_epoch") or 0),
            "pause_started_epoch": float(payload.get("pause_started_epoch") or payload.get("created_at_epoch") or 0),
            "paused": bool(payload.get("paused", True)),
            "pause_reason": str(payload.get("pause_reason") or "captcha_solver").strip() or "captcha_solver",
            "manual_required": bool(payload.get("manual_required", False)),
            "manual_only": bool(payload.get("manual_only", False)),
            "last_status": str(payload.get("last_status") or "running"),
            "last_failure_reason": str(payload.get("last_failure_reason") or "").strip() or None,
        }
    )
    return state


def _persist_solver_scope_state(scope: str, state: dict[str, Any]) -> str | None:
    normalized_scope = _normalize_challenge_scope(scope)
    if not normalized_scope:
        return None
    path = _solver_scope_state_path(normalized_scope)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    payload = {
        "active": bool(state.get("challenge_id")),
        "scope": normalized_scope,
        "challenge_id": state.get("challenge_id"),
        "first_seen_epoch": float(state.get("first_seen_epoch") or 0),
        "pause_started_epoch": float(state.get("pause_started_epoch") or 0),
        "updated_at_epoch": time.time(),
        "paused": bool(state.get("paused")),
        "pause_reason": state.get("pause_reason"),
        "manual_required": bool(state.get("manual_required")),
        "manual_only": bool(state.get("manual_only")),
        "last_status": state.get("last_status"),
        "last_failure_reason": state.get("last_failure_reason"),
        "last_request": dict(state.get("last_request") or {}),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
        with SOLVER_SCOPE_LOCK:
            SOLVER_SCOPE_STATES[normalized_scope] = dict(state)
    except Exception as error:
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            pass
        return repr(error)
    return None


def _scope_challenge_age(scope: str, now: float | None = None) -> float:
    state = _read_solver_scope_state(scope)
    first_seen = float(state.get("first_seen_epoch") or 0)
    if first_seen <= 0 or not state.get("challenge_id"):
        return 0.0
    return max(0.0, (time.time() if now is None else float(now)) - first_seen)


def _force_reset_solver_scope(
    scope: str | None,
    challenge_id: str | None = None,
) -> dict[str, Any]:
    """Reset one stuck list/detail challenge after the safety timeout."""
    normalized_scope = _normalize_challenge_scope(scope)
    if normalized_scope not in CHALLENGE_SCOPES:
        return {"ok": False, "force_reset": False, "error": "scope must be seed or detail"}
    status = _solver_scope_runtime_status(normalized_scope)
    active_id = str(status.get("challenge_id") or "").strip()
    reported_id = str(challenge_id or "").strip()
    if not active_id:
        return {"ok": True, "force_reset": False, "scope": normalized_scope, "reason": "no_active_challenge"}
    if reported_id and reported_id != active_id:
        return {
            "ok": False,
            "force_reset": False,
            "scope": normalized_scope,
            "challenge_id": active_id,
            "stale_challenge": True,
            "error": "challenge_id does not match the active scoped challenge",
        }
    age = float(status.get("challenge_age_seconds") or 0)
    if age < CHALLENGE_FORCE_RESET_SECONDS:
        return {
            "ok": False,
            "force_reset": False,
            "scope": normalized_scope,
            "challenge_id": active_id,
            "challenge_age_seconds": age,
            "retry_after_seconds": max(0, int(math.ceil(CHALLENGE_FORCE_RESET_SECONDS - age))),
            "error": "challenge has not reached the force-reset safety timeout",
        }
    recovery_request = dict(status.get("last_request") or {})
    clear_error = _clear_solver_challenge_state(normalized_scope)
    if clear_error:
        return {
            "ok": False,
            "force_reset": False,
            "scope": normalized_scope,
            "challenge_id": active_id,
            "error": clear_error,
        }
    _set_collection_pause_state(False, scope=normalized_scope)
    try:
        Path(_solver_scope_manual_flag_path(normalized_scope)).unlink(missing_ok=True)
    except Exception:
        pass
    # The legacy flag is aggregate state.  Once the reset scope is clear, only
    # keep it if another independent scope still requires manual recovery;
    # otherwise it would continue to report a global pause after both scoped
    # collectors have resumed.
    try:
        other_scope_requires_manual = any(
            bool(_read_solver_scope_state(candidate).get("manual_required"))
            for candidate in CHALLENGE_SCOPES
            if candidate != normalized_scope
        )
        if not other_scope_requires_manual:
            Path(_solver_force_unlock_flag_path()).unlink(missing_ok=True)
    except Exception:
        pass
    _remember_solver_force_reset_recovery(normalized_scope, recovery_request)
    return {
        "ok": True,
        "force_reset": True,
        "scope": normalized_scope,
        "previous_challenge_id": active_id,
        "challenge_age_seconds": age,
        "report_grace_seconds": SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS,
        "paused": _collection_effectively_paused(),
        "captcha_solver": _captcha_solver_runtime_status(),
    }


def _solver_force_unlock_flag_path() -> str:
    state_dir = str(os.getenv("FAPAI_SOLVER_STATE_DIR") or DATA_DIR).strip() or DATA_DIR
    return os.path.join(state_dir, "force_unlock.flag")


def _solver_scope_manual_flag_path(scope: str) -> str:
    normalized = _normalize_challenge_scope(scope)
    state_dir = str(os.getenv("FAPAI_SOLVER_STATE_DIR") or DATA_DIR).strip() or DATA_DIR
    return str(Path(state_dir) / f"force_unlock-{normalized}.flag")


def _solver_force_unlock_flag_exists() -> bool:
    try:
        return os.path.exists(_solver_force_unlock_flag_path())
    except Exception:
        return False


def _is_client_disconnect_error(error: BaseException) -> bool:
    return isinstance(error, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)) or getattr(
        error,
        "errno",
        None,
    ) in {32, 104, 10053, 10054}


def _collection_effectively_paused() -> bool:
    if _solver_force_unlock_flag_exists():
        return True
    if not PAUSED:
        return False
    if _solver_transient_pause_active():
        return False
    return True


def _collection_scope_effectively_paused(scope: str) -> bool:
    """Return pause state for one collector without inheriting the other scope."""
    normalized = _normalize_challenge_scope(scope)
    if normalized not in CHALLENGE_SCOPES:
        return _collection_effectively_paused()
    scoped = _solver_scope_runtime_status(normalized)
    if scoped.get("paused") or scoped.get("manual_required"):
        return True
    # Operator pause is intentionally global. A solver pause is scoped and
    # must not stop the other collector.
    if COLLECTION_PAUSE_REASON == "operator":
        return True
    if COLLECTION_PAUSE_REASON in {"manual_required"} and not any(
        _solver_scope_runtime_status(candidate).get("paused")
        for candidate in CHALLENGE_SCOPES
    ):
        return True
    return False


def _set_collection_pause_state(
    paused: bool,
    reason: str | None = None,
    *,
    scope: str | None = None,
) -> None:
    global PAUSED, COLLECTION_PAUSE_REASON
    normalized_scope = _normalize_challenge_scope(scope)
    if normalized_scope:
        with SOLVER_SCOPE_LOCK:
            state = dict(SOLVER_SCOPE_STATES.get(normalized_scope) or _new_solver_scope_state())
            state["paused"] = bool(paused)
            state["pause_reason"] = str(reason or "").strip() or None if paused else None
            if paused and not state.get("pause_started_epoch"):
                state["pause_started_epoch"] = time.time()
            if not paused:
                state["force_reset_required"] = False
        _persist_solver_scope_state(normalized_scope, state)
        if paused:
            PAUSED = True
            if COLLECTION_PAUSE_REASON not in {"operator", "manual_required"}:
                COLLECTION_PAUSE_REASON = str(reason or "captcha_solver").strip() or "captcha_solver"
        elif not any(
            bool(_read_solver_scope_state(candidate).get("paused"))
            for candidate in CHALLENGE_SCOPES
        ) and COLLECTION_PAUSE_REASON in {"captcha_solver", "manual_required"}:
            PAUSED = False
            COLLECTION_PAUSE_REASON = None
        return
    PAUSED = bool(paused)
    if PAUSED:
        COLLECTION_PAUSE_REASON = str(reason or "").strip() or None
    else:
        COLLECTION_PAUSE_REASON = None


def _solver_transient_pause_active() -> bool:
    return bool(
        PAUSED
        and COLLECTION_PAUSE_REASON == "captcha_solver"
        and SOLVER_RUNNING
        and SOLVER_LAST_STATUS == "running"
        and SOLVER_LAST_FAILURE_REASON != "manual_required"
    )


def _solver_scope_runtime_status(scope: str, now: float | None = None) -> dict[str, Any]:
    normalized_scope = _normalize_challenge_scope(scope) or "seed"
    current_time = time.time() if now is None else float(now)
    state = _read_solver_scope_state(normalized_scope)
    challenge_id = str(state.get("challenge_id") or "").strip() or None
    first_seen = float(state.get("first_seen_epoch") or 0)
    age = max(0.0, current_time - first_seen) if challenge_id and first_seen > 0 else 0.0
    force_reset_required = bool(
        challenge_id
        and bool(state.get("paused"))
        and age >= CHALLENGE_FORCE_RESET_SECONDS
    )
    state["force_reset_required"] = force_reset_required
    return {
        "scope": normalized_scope,
        "challenge_id": challenge_id,
        "first_seen_epoch": first_seen or None,
        "pause_started_epoch": float(state.get("pause_started_epoch") or 0) or None,
        "challenge_age_seconds": age,
        "paused": bool(state.get("paused")),
        "pause_reason": state.get("pause_reason"),
        "manual_required": bool(state.get("manual_required")),
        "manual_only": bool(state.get("manual_only")),
        "force_reset_required": force_reset_required,
        "last_status": state.get("last_status") or "idle",
        "last_failure_reason": state.get("last_failure_reason"),
        "last_request": dict(state.get("last_request") or {}),
    }


def _captcha_solver_runtime_status(now: float | None = None) -> dict[str, Any]:
    current_time = time.time() if now is None else now
    with SOLVER_LOCK:
        active_run = bool(SOLVER_RUNNING)
        queued = SOLVER_PENDING_TOKEN is not None
        started_at = float(SOLVER_START_TIME or 0)
    running = bool(active_run or queued)
    force_unlock_flag_exists = _solver_force_unlock_flag_exists()
    last_request = dict(SOLVER_LAST_REQUEST) if isinstance(SOLVER_LAST_REQUEST, dict) else {}
    if not last_request and force_unlock_flag_exists:
        last_request = _solver_manual_flag_request()
    elapsed_seconds = max(int(current_time - started_at), 0) if active_run and started_at > 0 else 0
    if not last_request and SOLVER_LAST_STATUS == "idle" and not force_unlock_flag_exists:
        scope_statuses = {scope: _solver_scope_runtime_status(scope, now=current_time) for scope in CHALLENGE_SCOPES}
        for status in scope_statuses.values():
            status.update({"challenge_id": None, "paused": False, "manual_required": False, "force_reset_required": False})
    else:
        scope_statuses = {
            scope: _solver_scope_runtime_status(scope, now=current_time)
            for scope in CHALLENGE_SCOPES
        }
    active_scope = _challenge_scope_for_request(last_request)
    if active_scope not in CHALLENGE_SCOPES:
        active_scope = next(
            (
                scope
                for scope, status in scope_statuses.items()
                if status.get("challenge_id")
            ),
            None,
        )
    selected_scope = scope_statuses.get(active_scope or "", {})
    manual_required = bool(
        force_unlock_flag_exists
        or (PAUSED and SOLVER_LAST_STATUS == "manual_required")
        or any(status.get("manual_required") for status in scope_statuses.values())
    )
    scoped_manual_only = bool(selected_scope.get("manual_only")) if selected_scope else False
    manual_only = bool(
        scoped_manual_only
        or (
            active_scope not in CHALLENGE_SCOPES
            and (SOLVER_MANUAL_ONLY or _solver_manual_flag_is_manual_only())
        )
        or _solver_target_requires_manual_only(last_request)
    )
    delegated_to_node = bool(last_request and _solver_request_delegated_to_node(last_request))
    request_node_id = str(last_request.get("node_id") or "").strip().lower()
    request_owner = (request_node_id or "node") if delegated_to_node else ("nas" if last_request else None)
    execution_mode = (
        "manual"
        if manual_only
        else "delegated_node"
        if delegated_to_node
        else "nas_local"
        if last_request
        else "idle"
    )
    manual_retry_next_epoch = _manual_solver_retry_next_epoch(current_time) if manual_required else None
    return {
        "running": running,
        "queued": queued,
        "started_at_epoch": started_at if started_at > 0 else None,
        "elapsed_seconds": elapsed_seconds,
        "last_status": SOLVER_LAST_STATUS,
        "last_failure_reason": SOLVER_LAST_FAILURE_REASON,
        "last_finished_at_epoch": SOLVER_LAST_FINISHED_TIME if SOLVER_LAST_FINISHED_TIME else None,
        "manual_required": manual_required,
        "manual_only": manual_only,
        "execution_mode": execution_mode,
        "request_owner": request_owner,
        "delegated_to_node_solver": delegated_to_node,
        "nas_solver_active": running,
        "node_solver_expected": bool(delegated_to_node and not manual_only),
        "real_taobao_auto_solver_enabled": _real_taobao_auto_solver_enabled(),
        "force_unlock_flag_exists": force_unlock_flag_exists,
        "paused": bool(
            _collection_effectively_paused()
            or any(status.get("paused") for status in scope_statuses.values())
        ),
        "pause_reason": COLLECTION_PAUSE_REASON,
        "last_request": last_request,
        "manual_retry_enabled": _manual_solver_retry_enabled(),
        "manual_retry_interval_seconds": _manual_solver_retry_interval_seconds(),
        "solver_max_runtime_seconds": _solver_max_runtime_seconds(),
        "manual_retry_attempts": int(SOLVER_MANUAL_RETRY_ATTEMPTS or 0),
        "manual_retry_last_epoch": SOLVER_MANUAL_RETRY_LAST_EPOCH or None,
        "manual_retry_next_epoch": manual_retry_next_epoch,
        "challenge_id": SOLVER_CHALLENGE_ID,
        "cookie_snapshot_refresh": _auth_cookie_snapshot_runtime_status(),
        # New consumers use these independent state machines.  The legacy
        # singleton fields above remain for older workers and API clients.
        "scope": active_scope or None,
        "scopes": scope_statuses,
        "collection_scopes": scope_statuses,
        "collection_pause_markers": {
            scope: "paused" if bool(status.get("paused") or status.get("manual_required")) else "collecting"
            for scope, status in scope_statuses.items()
        },
    }


def _solver_challenge_state_path() -> Path:
    state_dir = str(os.getenv("FAPAI_SOLVER_STATE_DIR") or DATA_DIR).strip() or DATA_DIR
    return Path(state_dir) / "solver-challenge-state.json"


def _read_solver_challenge_state() -> dict[str, Any]:
    try:
        payload = json.loads(_solver_challenge_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict) or payload.get("active") is not True:
        return {}
    challenge_id = str(payload.get("challenge_id") or "").strip()
    if not challenge_id:
        return {}
    last_request = payload.get("last_request")
    payload["challenge_id"] = challenge_id
    payload["last_request"] = dict(last_request) if isinstance(last_request, dict) else {}
    return payload


def _solver_challenge_request_key(request_payload: dict[str, Any] | None) -> tuple[str, str, str]:
    payload = request_payload if isinstance(request_payload, dict) else {}
    node_id = str(payload.get("node_id") or "").strip().lower()
    cdp_endpoint = str(payload.get("cdp_endpoint") or "").strip().lower().rstrip("/")
    target_url = _normalize_solver_target_url(
        payload.get("challenge_target_url") or payload.get("target_url") or payload.get("url") or ""
    )
    return node_id, cdp_endpoint, target_url


def _solver_challenge_owner_key(request_payload: dict[str, Any] | None) -> tuple[str, str]:
    node_id, cdp_endpoint, _target_url = _solver_challenge_request_key(request_payload)
    return node_id, cdp_endpoint


def _solver_detail_captured_count() -> int | None:
    if not getattr(DB_REPOSITORY, "enabled", False):
        return None
    try:
        counts = DB_REPOSITORY.seed_queue_counts()
    except Exception:
        return None
    if not isinstance(counts, dict):
        return None
    captured_status_keys = (
        "seed_item_raw_detail_captured",
        # Analysis states are included because each can only be entered after
        # raw detail HTML was captured successfully. Moving between these
        # states therefore keeps the total stable instead of inventing progress.
        "seed_item_analysis_in_progress",
        "seed_item_analysis_failed",
        "seed_item_analysis_blocked",
        "seed_item_detail_completed",
    )
    try:
        return sum(max(int(counts.get(key, 0) or 0), 0) for key in captured_status_keys)
    except (TypeError, ValueError):
        return None


def _nas_auth_recovery_pending_detail_count() -> int:
    if not getattr(DB_REPOSITORY, "enabled", False):
        return 0
    try:
        counts = DB_REPOSITORY.seed_queue_counts()
    except Exception:
        return 0
    if not isinstance(counts, dict):
        return 0
    try:
        return max(int(counts.get("seed_item_pending_detail", 0) or 0), 0) + max(
            int(counts.get("seed_item_in_progress", 0) or 0),
            0,
        )
    except (TypeError, ValueError):
        return 0


def _nas_auth_recovery_signal() -> str | None:
    solver_status = _captcha_solver_runtime_status()
    if not solver_status.get("paused"):
        return None
    if solver_status.get("manual_required"):
        return "captcha_manual_required"
    snapshot_status = _auth_cookie_snapshot_runtime_status()
    snapshot_result = snapshot_status.get("result")
    if not isinstance(snapshot_result, dict):
        snapshot_result = {}
    if (
        snapshot_status.get("status") == "failed"
        and snapshot_result.get("reason") == "cookie_snapshot_candidate_unhealthy"
    ):
        return "cookie_snapshot_candidate_unhealthy"
    return None


def _sample_nas_auth_recovery() -> dict[str, Any]:
    return NAS_AUTH_RECOVERY.sample(
        _solver_detail_captured_count(),
        _nas_auth_recovery_pending_detail_count(),
        operator_paused=COLLECTION_PAUSE_REASON == "operator",
        recovery_signal=_nas_auth_recovery_signal(),
        recovery_signal_stall_seconds=NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS,
    )


def _nas_auth_recovery_authorized(headers: Any) -> tuple[bool, str]:
    if not NAS_AUTH_RECOVERY.enabled:
        return False, "auth recovery is disabled"
    try:
        expected = NAS_AUTH_RECOVERY_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        expected = ""
    supplied = str(headers.get("X-Fapai-Recovery-Token") or "").strip()
    if not expected:
        return False, "auth recovery token is not configured"
    if not supplied or not hmac.compare_digest(supplied, expected):
        return False, "auth recovery token is invalid"
    return True, ""


def nas_auth_recovery_watchdog_thread() -> None:
    while True:
        try:
            snapshot = _sample_nas_auth_recovery()
            active = snapshot.get("active")
            if isinstance(active, dict) and active.get("status") == "requested":
                print(
                    "[AUTH-RECOVERY] Collection stalled; PC1 authentication "
                    f"recovery requested ({active.get('recovery_id')}, "
                    f"trigger={active.get('trigger_reason')})."
                )
        except Exception as error:
            print(f"[AUTH-RECOVERY] Watchdog sample failed: {error!r}")
        time.sleep(NAS_AUTH_RECOVERY_POLL_SECONDS)


def _nas_auth_recovery_result(payload: dict[str, Any]) -> dict[str, Any]:
    recovery_id = str(payload.get("recovery_id") or "").strip()
    success = payload.get("success") is True
    reason = str(payload.get("reason") or "").strip()
    if not recovery_id:
        return {"ok": False, "error": "recovery_id is required"}
    if not success:
        return NAS_AUTH_RECOVERY.result(
            recovery_id,
            success=False,
            reason=reason or "pc2_recovery_failed",
        )
    if COLLECTION_PAUSE_REASON == "operator":
        return NAS_AUTH_RECOVERY.result(
            recovery_id,
            success=False,
            reason="operator_pause_active",
        )

    result = NAS_AUTH_RECOVERY.result(recovery_id, success=True, reason=reason)
    if not result.get("ok"):
        return result
    clear_error = _clear_solver_manual_required_pause()
    if clear_error:
        NAS_AUTH_RECOVERY.result(
            recovery_id,
            success=False,
            reason=f"clear_collection_pause_failed:{clear_error}",
        )
        return {"ok": False, "error": clear_error}
    _remember_solver_auth_completion(
        {
            "node_id": "pc2",
            "source": "nas_auth_recovery",
        }
    )
    return {
        **result,
        "paused": _collection_effectively_paused(),
        "captcha_solver": _captcha_solver_runtime_status(),
    }


def _remember_solver_auth_completion(request_payload: dict[str, Any] | None) -> None:
    global SOLVER_LAST_AUTH_COMPLETED_TIME, SOLVER_LAST_AUTH_COMPLETED_REQUEST
    global SOLVER_LAST_AUTH_DETAIL_CAPTURED_COUNT
    request = _build_solver_request(request_payload or {})
    SOLVER_LAST_AUTH_COMPLETED_TIME = time.time()
    SOLVER_LAST_AUTH_COMPLETED_REQUEST = dict(request)
    SOLVER_LAST_AUTH_DETAIL_CAPTURED_COUNT = _solver_detail_captured_count()


def _solver_request_matches_auth_source(
    completed_request: dict[str, Any],
    incoming_request: dict[str, Any],
) -> bool:
    completed_node, completed_cdp, completed_target = _solver_challenge_request_key(
        completed_request
    )
    incoming_node, incoming_cdp, incoming_target = _solver_challenge_request_key(
        incoming_request
    )
    if completed_node and incoming_node:
        return completed_node == incoming_node
    if completed_cdp and incoming_cdp:
        return completed_cdp == incoming_cdp
    return bool(
        completed_target
        and incoming_target
        and completed_target == incoming_target
    )


def _remember_solver_force_reset_recovery(
    scope: str,
    request_payload: dict[str, Any] | None,
    *,
    now: float | None = None,
) -> None:
    """Remember a scoped reset so its just-closed page cannot immediately re-lock collection."""
    normalized_scope = _normalize_challenge_scope(scope)
    request = _build_solver_request(request_payload or {})
    if normalized_scope not in CHALLENGE_SCOPES or not request:
        return
    with SOLVER_SCOPE_LOCK:
        SOLVER_SCOPE_FORCE_RESET_RECOVERIES[normalized_scope] = {
            "completed_at_epoch": time.time() if now is None else float(now),
            "request": dict(request),
        }


def _solver_force_reset_report_suppression(
    request_payload: dict[str, Any] | None,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Ignore same-scope reports briefly after a forced recovery attempt."""
    incoming = _build_solver_request(request_payload or {})
    scope = _challenge_scope_for_request(incoming)
    if scope not in CHALLENGE_SCOPES or SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS <= 0:
        return None
    with SOLVER_SCOPE_LOCK:
        recovery = dict(SOLVER_SCOPE_FORCE_RESET_RECOVERIES.get(scope) or {})
    completed_at = float(recovery.get("completed_at_epoch") or 0)
    completed_request = _build_solver_request(recovery.get("request") or {})
    if completed_at <= 0 or not completed_request or not incoming:
        return None
    current_time = time.time() if now is None else float(now)
    age = current_time - completed_at
    if age < 0 or age > SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS:
        return None
    if not _solver_request_matches_auth_source(completed_request, incoming):
        return None
    return {
        "reason": "recent_force_reset",
        "scope": scope,
        "age_seconds": age,
        "grace_seconds": SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS,
    }


def _solver_auth_report_suppression(
    request_payload: dict[str, Any] | None,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    completed_at = float(SOLVER_LAST_AUTH_COMPLETED_TIME or 0)
    if completed_at <= 0:
        return None
    current_time = time.time() if now is None else float(now)
    age = current_time - completed_at
    max_grace_seconds = max(
        SOLVER_AUTH_REPORT_GRACE_SECONDS,
        SOLVER_DETAIL_PROGRESS_GRACE_SECONDS,
    )
    if age < 0 or age > max_grace_seconds:
        return None

    completed = _build_solver_request(SOLVER_LAST_AUTH_COMPLETED_REQUEST)
    incoming = _build_solver_request(request_payload or {})
    if not completed or not incoming:
        return None
    if not _solver_request_matches_auth_source(completed, incoming):
        return None

    if SOLVER_AUTH_REPORT_GRACE_SECONDS > 0 and age <= SOLVER_AUTH_REPORT_GRACE_SECONDS:
        return {
            "reason": "recent_auth_complete",
            "age_seconds": age,
            "grace_seconds": SOLVER_AUTH_REPORT_GRACE_SECONDS,
            "captured_since_auth": 0,
        }

    baseline = SOLVER_LAST_AUTH_DETAIL_CAPTURED_COUNT
    current_count = _solver_detail_captured_count()
    if baseline is None or current_count is None:
        return None
    captured_since_auth = max(current_count - baseline, 0)
    if (
        age > SOLVER_DETAIL_PROGRESS_GRACE_SECONDS
        or captured_since_auth < SOLVER_DETAIL_PROGRESS_GRACE_MIN_ITEMS
    ):
        return None
    return {
        "reason": "recent_detail_progress",
        "age_seconds": age,
        "grace_seconds": SOLVER_DETAIL_PROGRESS_GRACE_SECONDS,
        "captured_since_auth": captured_since_auth,
    }


def _solver_report_is_recent_auth_duplicate(
    request_payload: dict[str, Any] | None,
    *,
    now: float | None = None,
) -> bool:
    """Reject delayed captcha reports from the node that just completed auth.

    Worker captcha reports are fire-and-forget and do not carry the active
    challenge id.  A report already in flight can therefore arrive after the
    solver has cleared the challenge and otherwise create a new pause.  Keep a
    short, same-node grace window so the next worker cycle can observe the
    authenticated cookie instead of reopening the just-cleared challenge. If
    detail capture then advances, extend only that same-node protection to the
    configured progress-backed window.
    """
    return _solver_auth_report_suppression(request_payload, now=now) is not None


def _solver_report_predates_auth_completion(
    payload: dict[str, Any] | None,
) -> bool:
    """Identify an in-flight worker report created before auth completed."""
    completed_at = float(SOLVER_LAST_AUTH_COMPLETED_TIME or 0)
    if completed_at <= 0 or not isinstance(payload, dict):
        return False
    raw_timestamp = payload.get("timestamp")
    if isinstance(raw_timestamp, bool):
        return False
    try:
        reported_at = float(raw_timestamp)
    except (TypeError, ValueError):
        return False
    if reported_at > 10_000_000_000:
        reported_at /= 1000.0
    if reported_at <= 0 or reported_at > completed_at:
        return False

    completed = _build_solver_request(SOLVER_LAST_AUTH_COMPLETED_REQUEST)
    incoming = _build_solver_request(payload)
    if not completed or not incoming:
        return False
    return _solver_request_matches_auth_source(completed, incoming)


def _solver_report_stale_challenge_id(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    reported_challenge_id = str(payload.get("challenge_id") or "").strip()
    if not reported_challenge_id:
        return None
    scope = _challenge_scope_for_request(payload)
    if scope in CHALLENGE_SCOPES:
        active_challenge_id = str(
            _solver_scope_runtime_status(scope).get("challenge_id") or ""
        ).strip()
    else:
        active_challenge_id = str(SOLVER_CHALLENGE_ID or "").strip()
    if reported_challenge_id == active_challenge_id:
        return None
    return reported_challenge_id


def _persist_solver_challenge_state(challenge_id: str, last_request: dict[str, Any]) -> str | None:
    path = _solver_challenge_state_path()
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    existing = _read_solver_challenge_state()
    created_at_epoch = time.time()
    if existing.get("challenge_id") == challenge_id:
        created_at_epoch = float(existing.get("created_at_epoch") or 0) or created_at_epoch
    payload = {
        "active": True,
        "challenge_id": challenge_id,
        "created_at_epoch": created_at_epoch,
        "updated_at_epoch": time.time(),
        "pause_reason": "captcha_solver",
        "last_request": dict(last_request),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except Exception as error:
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            pass
        return repr(error)
    return None


def _scope_for_challenge_id(challenge_id: str | None) -> str | None:
    normalized = str(challenge_id or "").strip()
    if not normalized:
        return None
    for scope in CHALLENGE_SCOPES:
        if str(_solver_scope_runtime_status(scope).get("challenge_id") or "").strip() == normalized:
            return scope
    return None


def _clear_solver_challenge_state(scope: str | None = None) -> str | None:
    """Clear one scoped challenge, or all challenge state for legacy callers."""
    global SOLVER_CHALLENGE_ID, SOLVER_LAST_REQUEST
    normalized_scope = _normalize_challenge_scope(scope)
    scopes = (normalized_scope,) if normalized_scope else CHALLENGE_SCOPES
    errors: list[str] = []
    legacy_payload = _read_solver_challenge_state() if normalized_scope else {}
    scoped_challenge_id = (
        str(_read_solver_scope_state(normalized_scope).get("challenge_id") or "")
        if normalized_scope
        else ""
    )
    for candidate in scopes:
        with SOLVER_SCOPE_LOCK:
            SOLVER_SCOPE_STATES[candidate] = _new_solver_scope_state()
        try:
            _solver_scope_state_path(candidate).unlink(missing_ok=True)
        except Exception as error:
            errors.append(f"{candidate}: {error!r}")
    if not normalized_scope:
        path = _solver_challenge_state_path()
        legacy_cleared = True
        try:
            path.unlink(missing_ok=True)
        except Exception as error:
            errors.append(f"legacy: {error!r}")
            legacy_cleared = False
        if legacy_cleared:
            SOLVER_CHALLENGE_ID = None
    elif str(SOLVER_CHALLENGE_ID or "").strip() and _challenge_scope_for_request(SOLVER_LAST_REQUEST) == normalized_scope:
        SOLVER_CHALLENGE_ID = None
        for other_scope in CHALLENGE_SCOPES:
            if other_scope == normalized_scope:
                continue
            other_state = _read_solver_scope_state(other_scope)
            if other_state.get("challenge_id"):
                SOLVER_CHALLENGE_ID = str(other_state.get("challenge_id"))
                SOLVER_LAST_REQUEST = dict(other_state.get("last_request") or {})
                break
    if normalized_scope and scoped_challenge_id and legacy_payload.get("challenge_id") == scoped_challenge_id:
        # A scoped solve may have refreshed the compatibility receipt. Remove
        # it only when it represented this scoped challenge; leave a newer
        # receipt from the other scope untouched.
        try:
            _solver_challenge_state_path().unlink(missing_ok=True)
        except Exception as error:
            errors.append(f"legacy: {error!r}")
    return "; ".join(errors) if errors else None


def _restore_solver_challenge_state() -> bool:
    global SOLVER_CHALLENGE_ID, SOLVER_LAST_REQUEST
    payload = _read_solver_challenge_state()
    if not payload:
        return False
    SOLVER_CHALLENGE_ID = payload["challenge_id"]
    persisted_request = payload.get("last_request")
    if isinstance(persisted_request, dict) and persisted_request:
        SOLVER_LAST_REQUEST = dict(persisted_request)
    _set_collection_pause_state(True, str(payload.get("pause_reason") or "captcha_solver"))
    return True


def _restore_solver_scope_states() -> bool:
    """Restore independent list/detail challenge latches after a process restart."""
    global SOLVER_CHALLENGE_ID, SOLVER_LAST_REQUEST
    restored = False
    for scope in CHALLENGE_SCOPES:
        state = _read_solver_scope_state(scope)
        if not state.get("challenge_id"):
            continue
        with SOLVER_SCOPE_LOCK:
            SOLVER_SCOPE_STATES[scope] = dict(state)
        _set_collection_pause_state(True, str(state.get("pause_reason") or "captcha_solver"), scope=scope)
        if not SOLVER_CHALLENGE_ID:
            SOLVER_CHALLENGE_ID = str(state.get("challenge_id"))
            SOLVER_LAST_REQUEST = dict(state.get("last_request") or {})
        restored = True
    return restored


def _begin_solver_challenge(request_payload: dict[str, Any] | None = None) -> str:
    """Create/reuse the unique challenge latch for the request's collection scope."""
    global SOLVER_CHALLENGE_ID, SOLVER_LAST_REQUEST
    supplied_request = request_payload if isinstance(request_payload, dict) else SOLVER_LAST_REQUEST
    last_request = _build_solver_request(supplied_request or {})
    # Direct legacy callers without a request use the singleton state. New
    # collection workers always pass their request explicitly, enabling scope
    # isolation without breaking old plugins/tests that only know the legacy ID.
    scope = _challenge_scope_for_request(last_request) if isinstance(request_payload, dict) else ""
    if scope in CHALLENGE_SCOPES:
        now = time.time()
        with SOLVER_SCOPE_LOCK:
            state = dict(SOLVER_SCOPE_STATES.get(scope) or _new_solver_scope_state())
        persisted = _read_solver_scope_state(scope)
        if not state.get("challenge_id") and persisted.get("challenge_id"):
            state.update(persisted)
        challenge_id = str(state.get("challenge_id") or "").strip() or f"captcha-{time.time_ns()}"
        first_seen = float(state.get("first_seen_epoch") or 0) or now
        state.update(
            {
                "challenge_id": challenge_id,
                "last_request": dict(last_request),
                "first_seen_epoch": first_seen,
                "pause_started_epoch": float(state.get("pause_started_epoch") or 0) or now,
                "paused": True,
                "pause_reason": "captcha_solver",
                "manual_required": False,
                "manual_only": False,
                "last_status": "running",
                "last_failure_reason": None,
            }
        )
        persist_error = _persist_solver_scope_state(scope, state)
        if persist_error:
            print(f"[SOLVER] Failed to persist {scope} challenge state: {persist_error}")
        # Keep the legacy singleton receipt for older operators/clients. The
        # scoped files above remain authoritative when list and detail overlap.
        legacy_error = _persist_solver_challenge_state(challenge_id, last_request)
        if legacy_error:
            print(f"[SOLVER] Failed to refresh legacy challenge state: {legacy_error}")
        _set_collection_pause_state(True, "captcha_solver", scope=scope)
        SOLVER_CHALLENGE_ID = challenge_id
        SOLVER_LAST_REQUEST = dict(last_request)
        return challenge_id

    # Legacy/unknown request path retained for older API clients and tests.
    last_request = dict(SOLVER_LAST_REQUEST) if isinstance(SOLVER_LAST_REQUEST, dict) else {}
    persisted = _read_solver_challenge_state()
    if SOLVER_CHALLENGE_ID and _collection_effectively_paused():
        if (
            not persisted
            or _solver_challenge_owner_key(persisted.get("last_request"))
            == _solver_challenge_owner_key(last_request)
        ):
            persist_error = _persist_solver_challenge_state(SOLVER_CHALLENGE_ID, last_request)
            if persist_error:
                print(f"[SOLVER] Failed to refresh persisted challenge state: {persist_error}")
            return SOLVER_CHALLENGE_ID
    if (
        persisted
        and _solver_challenge_request_key(persisted.get("last_request"))
        == _solver_challenge_request_key(last_request)
    ):
        SOLVER_CHALLENGE_ID = persisted["challenge_id"]
    else:
        SOLVER_CHALLENGE_ID = f"captcha-{time.time_ns()}"
    persist_error = _persist_solver_challenge_state(SOLVER_CHALLENGE_ID, last_request)
    if persist_error:
        print(f"[SOLVER] Failed to persist challenge state: {persist_error}")
    return SOLVER_CHALLENGE_ID


def _solver_last_request_target_url(solver_status: dict[str, Any] | None = None) -> str:
    payload = solver_status if isinstance(solver_status, dict) else _captcha_solver_runtime_status()
    last_request = payload.get("last_request")
    if not isinstance(last_request, dict):
        return ""
    return str(last_request.get("target_url") or last_request.get("url") or "").strip()


def _solver_request_scope_from_target_url(target_url: str) -> str:
    normalized_target_url = str(target_url or "").strip().lower()
    if not normalized_target_url:
        return "unknown"
    if "sf-item.taobao.com" in normalized_target_url or "/sf_item/" in normalized_target_url:
        return "detail"
    if "sf.taobao.com/list/" in normalized_target_url or "sf.taobao.com//list/" in normalized_target_url:
        return "seed"
    if "/punish" in normalized_target_url and "/list/" in normalized_target_url:
        return "seed"
    return "unknown"


def _solver_last_request_scope(solver_status: dict[str, Any] | None = None) -> str:
    payload = solver_status if isinstance(solver_status, dict) else _captcha_solver_runtime_status()
    last_request = payload.get("last_request")
    if isinstance(last_request, dict):
        scoped = _challenge_scope_for_request(last_request)
        if scoped in CHALLENGE_SCOPES:
            return scoped
    return _solver_request_scope_from_target_url(_solver_last_request_target_url(payload))


def _solver_request_scope(request_payload: dict[str, Any] | None = None) -> str:
    if not isinstance(request_payload, dict):
        return "unknown"
    target_url = request_payload.get("target_url") or request_payload.get("url") or ""
    return _solver_request_scope_from_target_url(str(target_url))


def _seed_stage_has_remaining_work(status_payload: dict[str, Any]) -> bool:
    return any(
        int(status_payload.get(key, 0) or 0) > 0
        for key in (
            "seed_scan_job_pending",
            "seed_scan_job_in_progress",
            "seed_scan_progress_pending",
            "seed_scan_progress_in_progress",
        )
    )


def _collection_runtime_state_label_from_status_payload(status_payload: dict[str, Any]) -> str:
    solver_status = status_payload.get("captcha_solver")
    if not isinstance(solver_status, dict):
        solver_status = {}

    manual_required = bool(solver_status.get("manual_required") or solver_status.get("force_unlock_flag_exists"))
    if manual_required:
        if _solver_last_request_scope(solver_status) == "detail" and _seed_stage_has_remaining_work(status_payload):
            return "运行中"
        return "待认证"

    if bool(status_payload.get("paused")):
        return "暂停中"

    total_items = int(status_payload.get("total_ids", 0) or 0)
    raw_pending = int(status_payload.get("raw_capture_pending_count", 0) or 0)
    detail_failed = int(status_payload.get("detail_failed_count", 0) or 0)
    detail_blocked = int(status_payload.get("detail_blocked_count", 0) or 0)
    analysis_pending = int(status_payload.get("analysis_pending_count", 0) or 0)
    analysis_blocked = int(status_payload.get("analysis_blocked_count", 0) or 0)
    if total_items > 0 and raw_pending == 0 and detail_failed == 0 and detail_blocked == 0 and analysis_pending == 0 and analysis_blocked == 0:
        return "已完成"
    return "运行中"


def _clear_auth_lock_after_solver_success(scope: str | None = None) -> None:
    """After an automated captcha pass, drop the durable auth lock so workers resume."""
    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON, SOLVER_MANUAL_ONLY, SOLVER_MANUAL_RESUME_EPOCH
    normalized_scope = _normalize_challenge_scope(scope)
    if not normalized_scope:
        normalized_scope = _challenge_scope_for_request(SOLVER_LAST_REQUEST)
    completed_request = dict(SOLVER_LAST_REQUEST) if isinstance(SOLVER_LAST_REQUEST, dict) else {}
    challenge_state_error = _clear_solver_challenge_state(normalized_scope or None)
    if challenge_state_error:
        SOLVER_LAST_STATUS = "manual_required"
        SOLVER_LAST_FAILURE_REASON = "manual_required"
        _set_collection_pause_state(True, "manual_required", scope=normalized_scope or None)
        print(f"[SOLVER] Failed to clear persisted challenge state after success: {challenge_state_error}")
        return
    SOLVER_LAST_STATUS = "solved"
    SOLVER_LAST_FAILURE_REASON = None
    SOLVER_MANUAL_ONLY = False
    SOLVER_MANUAL_RESUME_EPOCH = time.time()
    _remember_solver_auth_completion(completed_request)
    if normalized_scope:
        _set_collection_pause_state(False, scope=normalized_scope)
    elif PAUSED and COLLECTION_PAUSE_REASON in {None, "captcha_solver", "manual_required"}:
        _set_collection_pause_state(False)
    flag_path = _solver_force_unlock_flag_path()
    flag_scope = _solver_manual_flag_scope()
    if os.path.exists(flag_path) and (
        not normalized_scope or not flag_scope or flag_scope == normalized_scope
    ):
        try:
            os.remove(flag_path)
            print("[SOLVER] Cleared force_unlock.flag after automated captcha success.")
        except Exception as error:
            print(f"[SOLVER] Failed to remove force_unlock.flag after success: {error}")
    if normalized_scope:
        try:
            Path(_solver_scope_manual_flag_path(normalized_scope)).unlink(missing_ok=True)
        except Exception as error:
            print(f"[SOLVER] Failed to remove scoped manual flag after success: {error}")


def _clear_solver_manual_required_state() -> None:
    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON, SOLVER_MANUAL_ONLY
    if SOLVER_LAST_STATUS == "manual_required":
        SOLVER_LAST_STATUS = "resumed"
    if SOLVER_LAST_FAILURE_REASON == "manual_required":
        SOLVER_LAST_FAILURE_REASON = None
    SOLVER_MANUAL_ONLY = False


def _clear_solver_running_state() -> None:
    global SOLVER_RUNNING, SOLVER_PENDING_TOKEN, SOLVER_START_TIME, SOLVER_LAST_FINISHED_TIME
    with SOLVER_LOCK:
        if SOLVER_RUNNING:
            SOLVER_LAST_FINISHED_TIME = time.time()
        SOLVER_RUNNING = False
        SOLVER_PENDING_TOKEN = None
        SOLVER_START_TIME = 0


def _request_solver_cancel() -> None:
    global SOLVER_CANCEL_EPOCH
    SOLVER_CANCEL_EPOCH = time.time()


def _clear_solver_manual_required_pause(
    *, preserve_running_state: bool = False, scope: str | None = None
) -> str | None:
    global SOLVER_MANUAL_RESUME_EPOCH
    normalized_scope = _normalize_challenge_scope(scope)
    flag_path = _solver_force_unlock_flag_path()
    flag_scope = _solver_manual_flag_scope()
    if os.path.exists(flag_path) and (
        not normalized_scope or not flag_scope or flag_scope == normalized_scope
    ):
        try:
            os.remove(flag_path)
        except Exception as error:
            return str(error)
    if normalized_scope:
        scoped_flag_path = _solver_scope_manual_flag_path(normalized_scope)
        try:
            Path(scoped_flag_path).unlink(missing_ok=True)
        except Exception as error:
            return str(error)
    challenge_state_error = _clear_solver_challenge_state(normalized_scope or None)
    if challenge_state_error:
        return challenge_state_error
    _set_collection_pause_state(False, scope=normalized_scope or None)
    SOLVER_MANUAL_RESUME_EPOCH = time.time()
    if not preserve_running_state:
        _clear_solver_running_state()
    _clear_solver_manual_required_state()
    return None


def _clear_solver_manual_required_pause_compat(scope: str | None = None) -> str | None:
    """Call the scoped cleanup while tolerating legacy test/plugin overrides."""
    try:
        return _clear_solver_manual_required_pause(scope=scope)
    except TypeError as error:
        if "unexpected keyword" not in str(error):
            raise
        return _clear_solver_manual_required_pause()


def _mark_solver_manual_required(
    *, manual_only: bool = False, scope: str | None = None
) -> str | None:
    global SOLVER_PENDING_TOKEN, SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON, SOLVER_MANUAL_REQUIRED_EPOCH
    global SOLVER_MANUAL_ONLY
    with SOLVER_LOCK:
        SOLVER_PENDING_TOKEN = None
        solver_running = bool(SOLVER_RUNNING)
    SOLVER_MANUAL_REQUIRED_EPOCH = time.time()
    SOLVER_LAST_STATUS = "manual_required"
    SOLVER_LAST_FAILURE_REASON = "manual_required"
    SOLVER_MANUAL_ONLY = bool(manual_only)
    if solver_running:
        _request_solver_cancel()
    normalized_scope = _normalize_challenge_scope(scope)
    if normalized_scope:
        with SOLVER_SCOPE_LOCK:
            state = dict(SOLVER_SCOPE_STATES.get(normalized_scope) or _new_solver_scope_state())
            state.update(
                {
                    "paused": True,
                    "pause_reason": "manual_required",
                    "manual_required": True,
                    "manual_only": bool(manual_only),
                    "last_status": "manual_required",
                    "last_failure_reason": "manual_required",
                }
            )
        _persist_solver_scope_state(normalized_scope, state)
    _set_collection_pause_state(True, "manual_required", scope=normalized_scope or None)
    flag_error = _write_solver_manual_required_flag(
        SOLVER_MANUAL_REQUIRED_EPOCH,
        scope=normalized_scope or None,
    )
    if normalized_scope:
        # Retain the legacy flag for old operators while the scoped flag above
        # is authoritative for independent workers.
        legacy_error = _write_solver_manual_required_flag(SOLVER_MANUAL_REQUIRED_EPOCH)
        return flag_error or legacy_error
    return flag_error


def _write_solver_manual_required_flag(
    created_at_epoch: float, *, scope: str | None = None
) -> str | None:
    normalized_scope = _normalize_challenge_scope(scope)
    flag_path = (
        _solver_scope_manual_flag_path(normalized_scope)
        if normalized_scope
        else _solver_force_unlock_flag_path()
    )
    try:
        os.makedirs(os.path.dirname(flag_path) or ".", exist_ok=True)
        with open(flag_path, "w", encoding="utf-8") as flag_file:
            json.dump(
                {
                    "manual_required": True,
                    "manual_only": bool(SOLVER_MANUAL_ONLY),
                    "scope": _normalize_challenge_scope(scope) or None,
                    "created_at_epoch": created_at_epoch,
                    "last_request": dict(SOLVER_LAST_REQUEST) if isinstance(SOLVER_LAST_REQUEST, dict) else {},
                    "message": "Delete this file to force resume the queue after manual solving",
                },
                flag_file,
                ensure_ascii=False,
            )
    except Exception as error:
        return repr(error)
    return None


def _solver_manual_flag_scope() -> str | None:
    try:
        with open(_solver_force_unlock_flag_path(), "r", encoding="utf-8") as flag_file:
            payload = json.load(flag_file)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return _normalize_challenge_scope(payload.get("scope")) or None


def _solver_manual_flag_is_manual_only() -> bool:
    try:
        with open(_solver_force_unlock_flag_path(), "r", encoding="utf-8") as flag_file:
            payload = json.load(flag_file)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    value = payload.get("manual_only")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _manual_solver_retry_enabled(scope: str | None = None) -> bool:
    normalized_scope = _normalize_challenge_scope(scope)
    if normalized_scope not in CHALLENGE_SCOPES:
        inferred_scope = _challenge_scope_for_request(SOLVER_LAST_REQUEST)
        if inferred_scope in CHALLENGE_SCOPES:
            normalized_scope = inferred_scope
    if normalized_scope in CHALLENGE_SCOPES:
        scoped = _solver_scope_runtime_status(normalized_scope)
        if scoped.get("manual_only"):
            return False
        flag_scope = _solver_manual_flag_scope()
        if flag_scope and flag_scope != normalized_scope:
            return True
        if scoped.get("challenge_id") or scoped.get("manual_required"):
            # The global manual-only bit is retained for legacy clients, but
            # must not disable retry for this independent scope.
            return _runtime_env_flag("FAPAI_SOLVER_MANUAL_RETRY_ENABLED", True)
    if SOLVER_MANUAL_ONLY or _solver_manual_flag_is_manual_only():
        return False
    return _runtime_env_flag("FAPAI_SOLVER_MANUAL_RETRY_ENABLED", True)


def _manual_solver_retry_interval_seconds() -> int:
    raw = os.getenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "180")
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 180
    if value < 0:
        return 180
    return value


def _solver_max_runtime_seconds() -> int:
    raw = os.getenv("FAPAI_SOLVER_MAX_RUNTIME_SECONDS", "180")
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 180
    if value <= 0:
        return 180
    return value


def _solver_worker_quiesce_seconds() -> int:
    raw = os.getenv("FAPAI_SOLVER_WORKER_QUIESCE_SECONDS", "0")
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 0
    return max(0, min(value, 300))


def _solver_cdp_ready_timeout_seconds() -> int:
    raw = os.getenv("FAPAI_SOLVER_CDP_READY_TIMEOUT_SECONDS", "0")
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 0
    return max(0, min(value, 600))


def _wait_for_solver_cdp_ready(solver_request: dict[str, Any] | None) -> bool:
    timeout_seconds = _solver_cdp_ready_timeout_seconds()
    request_payload = solver_request if isinstance(solver_request, dict) else {}
    cdp_endpoint = str(request_payload.get("cdp_endpoint") or "").strip().rstrip("/")
    if timeout_seconds <= 0 or not cdp_endpoint:
        return True

    print(
        f"[SOLVER] Waiting up to {timeout_seconds}s for a stable CDP target list at "
        f"{cdp_endpoint}."
    )
    deadline = time.monotonic() + timeout_seconds
    consecutive_healthy_probes = 0
    while time.monotonic() < deadline:
        try:
            request = Request(f"{cdp_endpoint}/json/list", headers={"Accept": "application/json"})
            with urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            healthy = isinstance(payload, list)
        except Exception:
            healthy = False

        if healthy:
            consecutive_healthy_probes += 1
            if consecutive_healthy_probes >= 2:
                print("[SOLVER] CDP target list is stable; starting solver control.")
                return True
        else:
            consecutive_healthy_probes = 0
        time.sleep(2)

    print(f"[SOLVER] CDP did not become stable within {timeout_seconds}s.")
    return False


def _solver_cdp_probe_timeout_seconds() -> float:
    raw = os.getenv("FAPAI_SOLVER_CDP_PROBE_TIMEOUT_SECONDS", "3")
    try:
        value = float(str(raw or "").strip())
    except ValueError:
        value = 3.0
    return max(0.5, min(value, 30.0))


def _probe_solver_cdp_endpoint(cdp_endpoint: str) -> bool:
    """轻量探测 CDP 是否可达；没有 endpoint 时视为通过。

    manual retry 会先走这里，避免浏览器已经掉线时还不停地清 pause、重投
    solver，最后把 manual_retry_attempts 刷到几千次。
    """
    endpoint = str(cdp_endpoint or "").strip().rstrip("/")
    if not endpoint:
        return True
    try:
        request = Request(f"{endpoint}/json/version", headers={"Accept": "application/json"})
        with urlopen(request, timeout=_solver_cdp_probe_timeout_seconds()) as response:
            json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    return True


def _manual_solver_retry_poll_seconds() -> int:
    raw = os.getenv("FAPAI_SOLVER_MANUAL_RETRY_POLL_SECONDS", "30")
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 30
    return max(value, 1)


def _captcha_solver_background_url(url: str) -> str:
    target_url = str(url or "").strip()
    if not target_url:
        return ""
    if "__captcha_solver_bg=1" in target_url:
        return target_url
    separator = "&" if "?" in target_url else "?"
    return f"{target_url}{separator}__captcha_solver_bg=1"


def _solver_manual_flag_request() -> dict[str, Any]:
    flag_path = _solver_force_unlock_flag_path()
    try:
        with open(flag_path, "r", encoding="utf-8") as flag_file:
            payload = json.load(flag_file)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    last_request = payload.get("last_request")
    return dict(last_request) if isinstance(last_request, dict) else {}


def _default_manual_solver_retry_request() -> dict[str, Any]:
    default_url = _captcha_solver_background_url(_auth_cookie_snapshot_sample_urls({})[0])
    return {"target_url": default_url} if default_url else {}


def _prefer_seed_manual_solver_retry_request() -> bool:
    try:
        status_payload = _collection_api_lightweight_status_payload()
    except Exception:
        return False
    return _solver_last_request_scope() == "detail" and _seed_stage_has_remaining_work(status_payload)


def _seed_priority_manual_solver_retry_request(
    current_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = dict(current_request or {})
    default_request = _build_solver_request(_default_manual_solver_retry_request())
    if default_request.get("target_url"):
        request["target_url"] = default_request["target_url"]
    return request


def _prefer_seed_solver_request_for_payload(
    request_payload: dict[str, Any] | None = None,
    *,
    status_payload: dict[str, Any] | None = None,
) -> bool:
    if _solver_request_scope(request_payload) != "detail":
        return False
    if status_payload is None:
        try:
            status_payload = _collection_api_lightweight_status_payload()
        except Exception:
            return False
    if not isinstance(status_payload, dict):
        return False
    return _seed_stage_has_remaining_work(status_payload)


def _seed_priority_solver_request(
    request_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    solver_request = _build_solver_request(request_payload or {})
    if not solver_request.get("target_url"):
        return solver_request
    if _prefer_seed_solver_request_for_payload(solver_request):
        solver_request["challenge_target_url"] = solver_request["target_url"]
        return _seed_priority_manual_solver_retry_request(solver_request)
    return solver_request


def _manual_solver_retry_request() -> dict[str, Any]:
    solver_request = _build_solver_request(SOLVER_LAST_REQUEST if isinstance(SOLVER_LAST_REQUEST, dict) else {})
    if solver_request.get("target_url"):
        if _prefer_seed_manual_solver_retry_request():
            return _seed_priority_manual_solver_retry_request(solver_request)
        return solver_request
    solver_request = _build_solver_request(_solver_manual_flag_request())
    if solver_request.get("target_url"):
        return solver_request
    return _build_solver_request(_default_manual_solver_retry_request())


def _manual_solver_retry_next_epoch(now: float | None = None) -> float | None:
    retry_scope = _challenge_scope_for_request(SOLVER_LAST_REQUEST)
    if not _manual_solver_retry_enabled(retry_scope or None):
        return None
    interval = _manual_solver_retry_interval_seconds()
    current_time = time.time() if now is None else now
    base_epoch = max(
        float(SOLVER_MANUAL_REQUIRED_EPOCH or 0),
        float(SOLVER_MANUAL_RETRY_LAST_EPOCH or 0),
        float(SOLVER_LAST_FINISHED_TIME or 0),
    )
    if base_epoch <= 0:
        return current_time
    return base_epoch + interval


def _solver_submission_pending() -> bool:
    with SOLVER_LOCK:
        return SOLVER_PENDING_TOKEN is not None


def _reserve_solver_submission() -> object | None:
    global SOLVER_PENDING_TOKEN
    with SOLVER_LOCK:
        if SOLVER_RUNNING or SOLVER_PENDING_TOKEN is not None:
            return None
        token = object()
        SOLVER_PENDING_TOKEN = token
        return token


def _release_solver_submission(token: object | None) -> None:
    global SOLVER_PENDING_TOKEN
    if token is None:
        return
    with SOLVER_LOCK:
        if SOLVER_PENDING_TOKEN is token:
            SOLVER_PENDING_TOKEN = None


def _activate_solver_submission(
    solver_request: dict[str, Any] | None,
    token: object | None,
) -> tuple[bool, str, float]:
    global SOLVER_RUNNING, SOLVER_PENDING_TOKEN, SOLVER_START_TIME
    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON, SOLVER_LAST_REQUEST

    with SOLVER_LOCK:
        if token is not None:
            if SOLVER_PENDING_TOKEN is not token:
                return False, "stale_submission", 0.0
            SOLVER_PENDING_TOKEN = None
        elif SOLVER_PENDING_TOKEN is not None:
            return False, "submission_pending", 0.0

        if SOLVER_RUNNING:
            elapsed = max(time.time() - float(SOLVER_START_TIME or 0), 0.0)
            return False, "solver_running", elapsed

        started_at = time.time()
        SOLVER_RUNNING = True
        SOLVER_START_TIME = started_at
        SOLVER_LAST_STATUS = "running"
        SOLVER_LAST_FAILURE_REASON = None
        SOLVER_LAST_REQUEST = dict(solver_request) if isinstance(solver_request, dict) else {}
        return True, "started", started_at


def _solver_cdp_endpoint_is_remote(cdp_endpoint: str) -> bool:
    """Check if the CDP endpoint belongs to a remote node (not the local machine).

    Returns True when the endpoint hostname is not a loopback address, indicating
    the solver runs on a different host than the CDP browser. In that case the
    local solver cannot use OS-level mouse drag and must defer to the node's
    own solver process.
    """
    endpoint = str(cdp_endpoint or "").strip().rstrip("/")
    if not endpoint:
        return False
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return False
    hostname = str(parsed.hostname or "").lower()
    if not hostname:
        return False
    # Local loopback addresses are on the same machine.
    if hostname in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}:
        return False
    # host.docker.internal resolves to the Docker host — same machine when
    # the solver runs inside a container on the host.
    if hostname in {"host.docker.internal", "192.168.65.254"}:
        return False
    return True


def _solver_request_delegated_to_node(solver_request: dict[str, Any] | None) -> bool:
    request = solver_request if isinstance(solver_request, dict) else {}
    node_id = str(request.get("node_id") or "").strip().lower()
    if node_id == "pc2":
        return True
    return _solver_cdp_endpoint_is_remote(str(request.get("cdp_endpoint") or ""))


def _submit_solver_request(solver_request: dict[str, Any]) -> bool:
    token = _reserve_solver_submission()
    if token is None:
        return False

    handler = object.__new__(DataHandler)
    try:
        executor.submit(handler.run_solver, solver_request, token)
    except Exception:
        _release_solver_submission(token)
        raise
    return True


def _trigger_manual_solver_retry_if_due(
    *,
    now: float | None = None,
    submit_solver: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    global SOLVER_MANUAL_RETRY_LAST_EPOCH, SOLVER_MANUAL_RETRY_ATTEMPTS
    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON

    current_time = time.time() if now is None else now
    if not _manual_solver_retry_enabled():
        return {"queued": False, "reason": "disabled"}
    if _solver_submission_pending():
        return {"queued": False, "reason": "solver_pending"}
    if SOLVER_RUNNING:
        elapsed_seconds = max(int(current_time - float(SOLVER_START_TIME or 0)), 0) if SOLVER_START_TIME else 0
        max_runtime_seconds = _solver_max_runtime_seconds()
        if elapsed_seconds >= max_runtime_seconds:
            flag_error = _mark_solver_manual_required(
                scope=_challenge_scope_for_request(SOLVER_LAST_REQUEST) or None
            )
            result: dict[str, Any] = {
                "queued": False,
                "reason": "running_solver_timed_out",
                "elapsed_seconds": elapsed_seconds,
                "max_runtime_seconds": max_runtime_seconds,
            }
            if flag_error:
                result["flag_error"] = flag_error
            return result
        return {
            "queued": False,
            "reason": "solver_running",
            "elapsed_seconds": elapsed_seconds,
            "max_runtime_seconds": max_runtime_seconds,
        }

    solver_status = _captcha_solver_runtime_status(now=current_time)
    if not solver_status.get("manual_required"):
        return {"queued": False, "reason": "not_manual_required"}

    solver_request = _manual_solver_retry_request()
    if not solver_request.get("target_url"):
        return {"queued": False, "reason": "missing_target_url"}
    solver_scope = _challenge_scope_for_request(solver_request)

    # PC2 owns its browser and runs the persistent 20s/10-attempt state
    # machine. The NAS monitor must not clear its manual pause or submit a
    # competing central solver request.
    if _solver_request_delegated_to_node(solver_request):
        return {
            "queued": False,
            "reason": "delegated_to_node_solver",
            "solver_request": solver_request,
        }

    next_retry_epoch = _manual_solver_retry_next_epoch(current_time)
    if next_retry_epoch is not None and current_time < next_retry_epoch:
        return {
            "queued": False,
            "reason": "cooldown_active",
            "next_retry_epoch": next_retry_epoch,
        }

    # CDP 掉线时直接跳过本轮：保留 manual_required，不清 pause、不投 solver。
    # 只吃掉一个 cooldown，这样探测按 retry interval 走而不是每轮轮询都打一次。
    retry_cdp_endpoint = str(solver_request.get("cdp_endpoint") or "").strip().rstrip("/")
    if not _probe_solver_cdp_endpoint(retry_cdp_endpoint):
        SOLVER_MANUAL_RETRY_LAST_EPOCH = current_time
        return {
            "queued": False,
            "reason": "cdp_endpoint_unhealthy",
            "cdp_endpoint": retry_cdp_endpoint,
        }

    clear_error = _clear_solver_manual_required_pause(scope=solver_scope or None)
    if clear_error:
        return {"queued": False, "reason": "clear_manual_required_failed", "error": clear_error}
    if (
        solver_scope in CHALLENGE_SCOPES
        and COLLECTION_PAUSE_REASON in {"captcha_solver", "manual_required"}
        and not any(
            _solver_scope_runtime_status(other).get("paused")
            for other in CHALLENGE_SCOPES
            if other != solver_scope
        )
    ):
        # A retry is a transient hand-off: the worker will establish its own
        # scoped pause when it observes the next challenge.
        _set_collection_pause_state(False)

    SOLVER_MANUAL_RETRY_LAST_EPOCH = current_time
    SOLVER_MANUAL_RETRY_ATTEMPTS = int(SOLVER_MANUAL_RETRY_ATTEMPTS or 0) + 1
    SOLVER_LAST_STATUS = "manual_retry_queued"
    SOLVER_LAST_FAILURE_REASON = None

    try:
        submit_result = (submit_solver or _submit_solver_request)(solver_request)
    except Exception as error:
        _mark_solver_manual_required(scope=solver_scope or None)
        return {
            "queued": False,
            "reason": "submit_failed",
            "error": repr(error),
        }
    if submit_solver is None and submit_result is False:
        _mark_solver_manual_required(scope=solver_scope or None)
        return {
            "queued": False,
            "reason": "solver_active",
        }

    return {
        "queued": True,
        "reason": "manual_required_retry_due",
        "attempt": SOLVER_MANUAL_RETRY_ATTEMPTS,
        "solver_request": solver_request,
    }


def _payload_flag(payload: dict[str, Any], key: str, default: bool) -> bool:
    if key not in payload:
        return default
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return default
    return text not in {"0", "false", "no", "off"}


def _payload_force_solver_retry(payload: dict[str, Any]) -> bool:
    return any(
        _payload_flag(payload, key, False)
        for key in ("force_retry", "force_manual_retry", "operator_retry")
    )


def _payload_manual_only(payload: dict[str, Any]) -> bool:
    return _payload_flag(payload, "manual_only", False)


def _manual_only_captcha_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    solver_request = _build_solver_request(payload)
    if solver_request:
        _refresh_solver_last_request(solver_request)
    scope = _challenge_scope_for_request(solver_request)
    _begin_solver_challenge(solver_request)
    flag_error = _mark_solver_manual_required(manual_only=True, scope=scope or None)
    response_payload: dict[str, Any] = {
        "status": "manual_required",
        "captcha_solver": _captcha_solver_runtime_status(),
    }
    if flag_error:
        response_payload["flag_error"] = flag_error
    return response_payload


def _auth_cookie_snapshot_sample_urls(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("sample_urls")
    if isinstance(raw, list):
        urls = [str(value).strip() for value in raw if str(value or "").strip()]
        if urls:
            return urls

    env_raw = os.getenv("FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS")
    if env_raw:
        urls = [part.strip() for part in re.split(r"[;,]", env_raw) if part.strip()]
        if urls:
            return urls

    return [
        "https://sf.taobao.com/list/50025969__2.htm",
        "https://sf.taobao.com/list/200782003__1.htm",
    ]


def _normalize_auth_cookie_snapshot_node_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", text):
        return ""
    return text


def _auth_cookie_snapshot_root_candidates() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def _add(path_value: str | Path | None) -> None:
        if not path_value:
            return
        path = Path(path_value).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        candidates.append(resolved)

    _add(os.getenv("FAPAI_COOKIE_SNAPSHOT_ROOT"))
    _add(os.getenv("FAPAI_SHARED_DATA_ROOT_HOST"))
    _add(REPO_ROOT.parent / "FPFData")

    data_root = Path(DATA_DIR).expanduser()
    try:
        data_root = data_root.resolve()
    except OSError:
        pass
    if data_root.name.lower() == "datas":
        _add(data_root.parent)
    return candidates


def _resolve_auth_cookie_snapshot_path(payload: dict[str, Any]) -> str:
    explicit_path = str(payload.get("cookie_snapshot_path") or "").strip()
    if explicit_path:
        return explicit_path

    env_path = str(os.getenv("FAPAI_COOKIE_SNAPSHOT") or "").strip()
    if env_path:
        return env_path

    last_request = SOLVER_LAST_REQUEST if isinstance(SOLVER_LAST_REQUEST, dict) else {}
    request_path = str(last_request.get("cookie_snapshot_path") or "").strip()
    if request_path:
        return request_path

    node_id = _normalize_auth_cookie_snapshot_node_id(
        payload.get("node_id")
        or last_request.get("node_id")
        or os.getenv("FAPAI_NODE_ID")
    )
    if not node_id:
        return ""

    roots = _auth_cookie_snapshot_root_candidates()
    if not roots:
        return ""

    existing_roots = [root for root in roots if root.exists()]
    selected_root = existing_roots[0] if existing_roots else roots[0]
    return str(selected_root / "secrets" / "nodes" / node_id / "taobao-cookies.json")


def _export_auth_cdp_cookies(cdp_endpoint: str) -> list[dict[str, Any]]:
    from tools.browserless_seed_probe import export_cdp_cookies

    return export_cdp_cookies(cdp_endpoint)


def _summarize_auth_cookies(cookies: list[dict[str, Any]]) -> dict[str, Any]:
    from tools.browserless_seed_probe import summarize_cookie_snapshot

    return summarize_cookie_snapshot(cookies)


def _write_auth_cookie_snapshot(cookies: list[dict[str, Any]], snapshot_path: str) -> None:
    from tools.browserless_seed_probe import write_cookie_snapshot

    write_cookie_snapshot(cookies, snapshot_path)


def _probe_auth_cookie_snapshot_health(
    cookies: list[dict[str, Any]],
    sample_urls: list[str],
    *,
    cdp_endpoint: str = "",
) -> dict[str, Any]:
    from tools import browserless_seed_probe, taobao_login_health

    session = browserless_seed_probe.build_session_from_playwright_cookies(cookies)
    user_agent = browserless_seed_probe.resolve_cdp_user_agent(cdp_endpoint)
    sample_results: list[dict[str, Any]] = []
    healthy_samples = 0
    for url in sample_urls:
        try:
            summary = browserless_seed_probe.probe_seed_page(
                url,
                cookies=cookies,
                session=session,
                timeout=15,
                user_agent=user_agent,
            )
            classification = taobao_login_health.classify_taobao_health(
                "",
                final_url=str(summary.get("final_url") or url),
                list_summary=summary,
                payload_present=summary.get("has_script") is True,
            )
            result = {
                "check_url": url,
                "status": classification.get("status"),
                "healthy": bool(classification.get("healthy")),
                "final_url": classification.get("final_url"),
                "http_status": summary.get("status"),
                "has_script": summary.get("has_script"),
                "item_count": summary.get("item_count"),
                "body_has_login": summary.get("body_has_login"),
                "body_has_captcha": summary.get("body_has_captcha"),
                "body_has_punish": summary.get("body_has_punish"),
                "body_has_challenge": summary.get("body_has_challenge"),
            }
        except Exception as error:
            result = {
                "check_url": url,
                "status": "probe_error",
                "healthy": False,
                "error": repr(error),
            }
        if result.get("healthy") is True:
            healthy_samples += 1
        sample_results.append(result)

    return {
        "healthy": healthy_samples > 0,
        "healthy_samples": healthy_samples,
        "sample_count": len(sample_results),
        "sample_results": sample_results,
    }


def _refresh_auth_cookie_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    if not _payload_flag(payload, "refresh_cookie_snapshot", True):
        return {"refreshed": False, "reason": "disabled_by_request"}

    snapshot_path = _resolve_auth_cookie_snapshot_path(payload)
    if not snapshot_path:
        return {"refreshed": False, "reason": "cookie_snapshot_path_not_configured"}

    request_cdp_endpoint = payload.get("cdp_endpoint")
    if not request_cdp_endpoint and isinstance(SOLVER_LAST_REQUEST, dict):
        request_cdp_endpoint = SOLVER_LAST_REQUEST.get("cdp_endpoint")
    cdp_endpoint = _normalize_solver_cdp_endpoint(request_cdp_endpoint or os.getenv("FAPAI_CDP_ENDPOINT") or "")
    if not cdp_endpoint:
        return {"refreshed": False, "reason": "cdp_endpoint_not_configured", "path": snapshot_path}

    cookies = _export_auth_cdp_cookies(cdp_endpoint)
    summary = _summarize_auth_cookies(cookies)
    sample_urls = _auth_cookie_snapshot_sample_urls(payload)
    health = _probe_auth_cookie_snapshot_health(
        cookies,
        sample_urls,
        cdp_endpoint=cdp_endpoint,
    )
    cookie_count = int(summary.get("count") or 0)
    if not health.get("healthy"):
        return {
            "refreshed": False,
            "reason": "cookie_snapshot_candidate_unhealthy",
            "path": snapshot_path,
            "cdp_endpoint": cdp_endpoint,
            "cookie_count": cookie_count,
            "health": health,
        }

    _write_auth_cookie_snapshot(cookies, snapshot_path)
    return {
        "refreshed": True,
        "path": snapshot_path,
        "cdp_endpoint": cdp_endpoint,
        "cookie_count": cookie_count,
        "domains": summary.get("domains") or [],
        "shape_fingerprint": summary.get("shape_fingerprint"),
        "value_fingerprint": summary.get("value_fingerprint"),
        "health": health,
    }


def _auth_cookie_snapshot_retry_attempts() -> int:
    raw = os.getenv("FAPAI_AUTH_COOKIE_RETRY_ATTEMPTS", "3")
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = 3
    return max(1, min(value, 10))


def _auth_cookie_snapshot_retry_backoff_seconds() -> float:
    raw = os.getenv("FAPAI_AUTH_COOKIE_RETRY_BACKOFF_SECONDS", "2")
    try:
        value = float(str(raw or "").strip())
    except ValueError:
        value = 2.0
    return max(0.0, min(value, 300.0))


def _auth_cookie_snapshot_runtime_status() -> dict[str, Any]:
    with AUTH_COOKIE_SNAPSHOT_LOCK:
        return dict(AUTH_COOKIE_SNAPSHOT_STATE)


def _set_auth_cookie_snapshot_state(**updates: Any) -> dict[str, Any]:
    with AUTH_COOKIE_SNAPSHOT_LOCK:
        AUTH_COOKIE_SNAPSHOT_STATE.update(updates)
        return dict(AUTH_COOKIE_SNAPSHOT_STATE)


def _run_auth_cookie_snapshot_retry(
    payload: dict[str, Any],
    completion_id: str | None,
    *,
    finalize_auth: bool = False,
    expected_challenge_id: str | None = None,
    completion_request: dict[str, Any] | None = None,
) -> None:
    max_attempts = _auth_cookie_snapshot_retry_attempts()
    base_backoff = _auth_cookie_snapshot_retry_backoff_seconds()
    last_result: dict[str, Any] = {"refreshed": False, "reason": "not_started"}

    for attempt in range(1, max_attempts + 1):
        _set_auth_cookie_snapshot_state(
            status="running",
            completion_id=completion_id,
            attempts=attempt,
            max_attempts=max_attempts,
            refreshed=False,
            retry_queued=False,
            next_retry_at_epoch=None,
            last_started_at_epoch=time.time(),
        )
        try:
            refreshed = _refresh_auth_cookie_snapshot(payload)
            last_result = dict(refreshed) if isinstance(refreshed, dict) else {
                "refreshed": False,
                "reason": "invalid_refresh_result",
            }
        except Exception as error:
            last_result = {"refreshed": False, "error": repr(error)}

        if last_result.get("refreshed") is True:
            auth_finalization = None
            if finalize_auth:
                auth_finalization = _finalize_auth_completion_after_cookie_snapshot(
                    completion_id,
                    expected_challenge_id=expected_challenge_id,
                    completion_request=completion_request,
                )
                last_result["auth_finalization"] = auth_finalization
            _set_auth_cookie_snapshot_state(
                status="completed",
                completion_id=completion_id,
                attempts=attempt,
                max_attempts=max_attempts,
                refreshed=True,
                retry_queued=False,
                next_retry_at_epoch=None,
                last_finished_at_epoch=time.time(),
                auth_state_confirmed=bool(
                    auth_finalization and auth_finalization.get("auth_state_confirmed") is True
                ),
                result=last_result,
            )
            return
        if last_result.get("reason") == "disabled_by_request":
            _set_auth_cookie_snapshot_state(
                status="skipped",
                completion_id=completion_id,
                attempts=attempt,
                max_attempts=max_attempts,
                refreshed=False,
                retry_queued=False,
                next_retry_at_epoch=None,
                last_finished_at_epoch=time.time(),
                result=last_result,
            )
            return
        if attempt < max_attempts:
            delay = min(base_backoff * (2 ** (attempt - 1)), 300.0)
            _set_auth_cookie_snapshot_state(
                status="pending",
                completion_id=completion_id,
                attempts=attempt,
                max_attempts=max_attempts,
                refreshed=False,
                retry_queued=True,
                next_retry_at_epoch=time.time() + delay,
                result=last_result,
            )
            if delay > 0:
                time.sleep(delay)

    _set_auth_cookie_snapshot_state(
        status="failed",
        completion_id=completion_id,
        attempts=max_attempts,
        max_attempts=max_attempts,
        refreshed=False,
        retry_queued=False,
        next_retry_at_epoch=None,
        last_finished_at_epoch=time.time(),
        result=last_result,
    )


def _schedule_auth_cookie_snapshot_refresh(
    payload: dict[str, Any],
    completion_id: str | None,
    *,
    finalize_auth: bool = False,
    expected_challenge_id: str | None = None,
    completion_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    global AUTH_COOKIE_SNAPSHOT_THREAD

    if not _payload_flag(payload, "refresh_cookie_snapshot", True):
        return _set_auth_cookie_snapshot_state(
            status="skipped",
            completion_id=completion_id,
            attempts=0,
            max_attempts=0,
            refreshed=False,
            retry_queued=False,
            next_retry_at_epoch=None,
            result={"refreshed": False, "reason": "disabled_by_request"},
        )

    with AUTH_COOKIE_SNAPSHOT_LOCK:
        current = dict(AUTH_COOKIE_SNAPSHOT_STATE)
        if AUTH_COOKIE_SNAPSHOT_THREAD is not None and AUTH_COOKIE_SNAPSHOT_THREAD.is_alive():
            current["retry_queued"] = True
            current["reason"] = "refresh_already_running"
            return current
        if completion_id and current.get("completion_id") == completion_id and current.get("status") == "completed":
            return current
        AUTH_COOKIE_SNAPSHOT_STATE.clear()
        AUTH_COOKIE_SNAPSHOT_STATE.update(
            {
                "status": "pending",
                "completion_id": completion_id,
                "attempts": 0,
                "max_attempts": _auth_cookie_snapshot_retry_attempts(),
                "refreshed": False,
                "retry_queued": True,
                "next_retry_at_epoch": time.time(),
                "auth_finalize_requested": bool(finalize_auth),
                "expected_challenge_id": expected_challenge_id,
            }
        )
        thread = threading.Thread(
            target=_run_auth_cookie_snapshot_retry,
            args=(dict(payload), completion_id),
            kwargs={
                "finalize_auth": bool(finalize_auth),
                "expected_challenge_id": expected_challenge_id,
                "completion_request": dict(completion_request or {}),
            },
            name="auth-cookie-snapshot-refresh",
            daemon=True,
        )
        AUTH_COOKIE_SNAPSHOT_THREAD = thread
        scheduled = dict(AUTH_COOKIE_SNAPSHOT_STATE)
        thread.start()
        return scheduled


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


def _collection_api_lightweight_status_enabled() -> bool:
    return _runtime_env_flag("FAPAI_COLLECTION_API_LIGHTWEIGHT_STATUS", False)


def _build_info_payload() -> dict[str, str]:
    return {
        "version": str(os.getenv("FAPAI_BUILD_VERSION") or "development"),
        "commit": str(os.getenv("FAPAI_BUILD_COMMIT") or "unknown"),
        "built_at": str(os.getenv("FAPAI_BUILD_TIME") or "unknown"),
        "source_digest": str(os.getenv("FAPAI_SOURCE_DIGEST") or "unknown"),
    }


def _empty_seed_queue_counts() -> dict[str, Any]:
    return {
        "seed_scan_job_pending": 0,
        "seed_scan_job_in_progress": 0,
        "seed_scan_job_completed": 0,
        "seed_scan_job_blocked": 0,
        "seed_scan_progress_pending": 0,
        "seed_scan_progress_in_progress": 0,
        "seed_scan_progress_exhausted": 0,
        "seed_scan_progress_blocked": 0,
        "seed_item_pending_detail": 0,
        "seed_item_in_progress": 0,
        "seed_item_raw_detail_captured": 0,
        "seed_item_analysis_in_progress": 0,
        "seed_item_analysis_failed": 0,
        "seed_item_analysis_blocked": 0,
        "seed_item_detail_completed": 0,
        "seed_item_detail_failed": 0,
        "seed_item_detail_blocked": 0,
        "seed_occurrence_total": 0,
    }


def _collection_api_lightweight_status_payload() -> dict[str, Any]:
    seed_queue_counts = _empty_seed_queue_counts()
    if DB_REPOSITORY.enabled and hasattr(DB_REPOSITORY, "seed_queue_counts"):
        try:
            seed_queue_counts.update(DB_REPOSITORY.seed_queue_counts())
        except Exception as error:
            seed_queue_counts["error"] = str(error)
    elif DB_REPOSITORY.enabled and hasattr(DB_REPOSITORY, "search_task_counts"):
        try:
            search_counts = DB_REPOSITORY.search_task_counts()
            seed_queue_counts["seed_scan_job_pending"] = int(search_counts.get("search_pending", 0) or 0)
            seed_queue_counts["seed_scan_job_in_progress"] = int(search_counts.get("search_in_progress", 0) or 0)
            seed_queue_counts["seed_scan_job_completed"] = int(search_counts.get("search_done", 0) or 0)
            seed_queue_counts["seed_scan_job_blocked"] = int(search_counts.get("search_pruned", 0) or 0)
        except Exception as error:
            seed_queue_counts["error"] = str(error)

    pending_detail = int(seed_queue_counts.get("seed_item_pending_detail", 0) or 0)
    in_progress = int(seed_queue_counts.get("seed_item_in_progress", 0) or 0)
    raw_detail_captured = int(seed_queue_counts.get("seed_item_raw_detail_captured", 0) or 0)
    analysis_in_progress = int(seed_queue_counts.get("seed_item_analysis_in_progress", 0) or 0)
    analysis_failed = int(seed_queue_counts.get("seed_item_analysis_failed", 0) or 0)
    analysis_blocked = int(seed_queue_counts.get("seed_item_analysis_blocked", 0) or 0)
    detail_completed = int(seed_queue_counts.get("seed_item_detail_completed", 0) or 0)
    detail_failed = int(seed_queue_counts.get("seed_item_detail_failed", 0) or 0)
    detail_blocked = int(seed_queue_counts.get("seed_item_detail_blocked", 0) or 0)
    raw_capture_pending = pending_detail + in_progress
    analysis_ready = raw_detail_captured + analysis_failed
    analysis_pending = raw_detail_captured + analysis_in_progress + analysis_failed
    analysis_terminal = analysis_blocked
    captured_items = analysis_pending + analysis_terminal + detail_completed
    total_items = pending_detail + in_progress + captured_items + detail_failed + detail_blocked
    api_metrics = llm_helper.get_api_metrics()
    top_level_seed_queue_counts = {
        key: int(seed_queue_counts.get(key, 0) or 0)
        for key in _empty_seed_queue_counts().keys()
    }
    solver_status_snapshot = _captcha_solver_runtime_status()

    payload = {
        "collection_api_lightweight": True,
        "build_info": _build_info_payload(),
        "capabilities": {
            "manual_captcha_report_v1": True,
            "nas_auth_recovery_v1": True,
        },
        "paused": bool(solver_status_snapshot.get("paused")),
        "total_ids": total_items,
        "captured_count": captured_items,
        "ai_finalized_count": detail_completed,
        "db_mode": DB_REPOSITORY.enabled,
        "db_total_ids": total_items,
        "db_processed_ids": detail_completed,
        "db_pending_ids": pending_detail + in_progress,
        "db_detail_captured_ids": captured_items,
        "db_analysis_pending_ids": analysis_pending,
        "raw_capture_pending_count": raw_capture_pending,
        "raw_captured_count": raw_detail_captured,
        "analysis_ready_count": analysis_ready,
        "analysis_in_progress_count": analysis_in_progress,
        "analysis_failed_count": analysis_failed,
        "analysis_pending_count": analysis_pending,
        "analysis_backlog_count": analysis_pending,
        "analysis_blocked_count": analysis_blocked,
        "analysis_finalized_count": detail_completed,
        "detail_failed_count": detail_failed,
        "detail_blocked_count": detail_blocked,
        "sniff_queue_count": int(seed_queue_counts.get("seed_scan_job_pending", 0) or 0),
        "sniff_done_count": int(seed_queue_counts.get("seed_scan_job_completed", 0) or 0),
        "next_batch_preview": [],
        "api_success_rate": api_metrics.get("success_rate", 0.0),
        "api_avg_response_time_ms": api_metrics.get("avg_response_time_ms", 0.0),
        "api_total_calls": api_metrics.get("total_calls", 0),
        "api_success_calls": api_metrics.get("success_calls", 0),
        **top_level_seed_queue_counts,
        "captcha_solver": solver_status_snapshot,
        "auth_recovery": NAS_AUTH_RECOVERY.snapshot(),
        "collection_scopes": solver_status_snapshot.get("collection_scopes", {}),
        "data_supply_recent_24h": {},
        "avm": {"lightweight_skipped": True},
        "collection_stage": {
            "lightweight": True,
            "seed_queue": seed_queue_counts,
            "seed_stage": {"stored": int(seed_queue_counts.get("seed_occurrence_total", 0) or 0)},
            "detail_stage": {
                "pending": pending_detail,
                "in_progress": in_progress,
                "raw_pending": pending_detail,
                "raw_in_progress": in_progress,
                "raw_archived": raw_detail_captured,
                "raw_captured": raw_detail_captured,
                "raw_failed": detail_failed,
                "raw_blocked": detail_blocked,
                "analysis_ready": analysis_ready,
                "analysis_in_progress": analysis_in_progress,
                "analysis_failed": analysis_failed,
                "analysis_blocked": analysis_blocked,
                "analysis_pending": analysis_pending,
                "analysis_backlog": analysis_pending,
                "archived": captured_items,
                "ai_finalized": detail_completed,
                "analysis_finalized": detail_completed,
                "failed": detail_failed,
                "blocked": detail_blocked,
            },
            "search_tasks": {
                "search_pending": int(seed_queue_counts.get("seed_scan_job_pending", 0) or 0),
                "search_in_progress": int(seed_queue_counts.get("seed_scan_job_in_progress", 0) or 0),
                "search_done": int(seed_queue_counts.get("seed_scan_job_completed", 0) or 0),
                "search_pruned": int(seed_queue_counts.get("seed_scan_job_blocked", 0) or 0),
            },
        },
    }
    payload["runtime_state"] = _collection_runtime_state_label_from_status_payload(payload)
    return payload


def _collection_query_int(query: dict[str, list[str]], key: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int((query.get(key) or [default])[0])
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _collection_observer_overview_payload() -> dict[str, Any]:
    status = _collection_api_lightweight_status_payload()
    seed_queue = dict((status.get("collection_stage") or {}).get("seed_queue") or {})
    active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
    return {
        "ok": True,
        "status": status,
        "runtime_state": status.get("runtime_state"),
        "challenge_metrics": _hybrid_collection_challenge_metrics_summary(active_data_root),
        "auth_watcher": _pc1_auth_auto_resume_state_summary(active_data_root),
        "modules": {
            "links": {
                "label": "商品链接采集",
                "total": int(seed_queue.get("seed_occurrence_total", 0) or 0),
                "unique_items": int(status.get("total_ids", 0) or 0),
            },
            "details": {
                "label": "商品详情页采集",
                "pending": int(status.get("raw_capture_pending_count", 0) or 0),
                "raw_captured": int(status.get("raw_captured_count", 0) or 0),
                "captured": int(status.get("captured_count", 0) or 0),
                "failed": int(status.get("detail_failed_count", 0) or 0),
                "blocked": int(status.get("detail_blocked_count", 0) or 0),
            },
            "analysis": {
                "label": "商品详情页 AI 分析",
                "ready": int(status.get("analysis_ready_count", 0) or 0),
                "pending": int(status.get("analysis_pending_count", 0) or 0),
                "failed": int(status.get("analysis_failed_count", 0) or 0),
                "blocked": int(status.get("analysis_blocked_count", 0) or 0),
                "finalized": int(status.get("analysis_finalized_count", status.get("ai_finalized_count", 0)) or 0),
            },
        },
    }


def _collection_observer_items_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    stage = str((query.get("stage") or ["links"])[0] or "links").strip().lower()
    if stage not in {"links", "details", "analysis"}:
        stage = "links"
    limit = _collection_query_int(query, "limit", 100, minimum=1, maximum=500)
    offset = _collection_query_int(query, "offset", 0, minimum=0, maximum=1_000_000)
    location_code = str((query.get("location_code") or [""])[0] or "").strip()
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "collection_observer_items"):
        return {
            "stage": stage,
            "limit": limit,
            "offset": offset,
            "location_code": location_code or None,
            "total": 0,
            "items": [],
            "db_mode": DB_REPOSITORY.enabled,
        }
    payload = DB_REPOSITORY.collection_observer_items(
        stage=stage,
        limit=limit,
        offset=offset,
        location_code=location_code or None,
    )
    payload["location_code"] = location_code or payload.get("location_code")
    payload["db_mode"] = DB_REPOSITORY.enabled
    return payload


def _collection_observer_regions_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    stage = str((query.get("stage") or ["links"])[0] or "links").strip().lower()
    if stage not in {"links", "details", "analysis"}:
        stage = "links"
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "collection_observer_regions"):
        return {"ok": True, "stage": stage, "regions": [], "db_mode": DB_REPOSITORY.enabled}
    payload = DB_REPOSITORY.collection_observer_regions(stage=stage)
    payload["db_mode"] = DB_REPOSITORY.enabled
    return payload


def _collection_observer_item_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    item_id = str((query.get("item_id") or [""])[0] or "").strip()
    max_chars = _collection_query_int(query, "max_chars", 100_000, minimum=1, maximum=1_000_000)
    if not item_id:
        return {"found": False, "error": "item_id is required", "item_id": ""}
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "collection_observer_item_detail"):
        return {"found": False, "item_id": item_id, "item": None, "occurrences": [], "artifacts": {}, "db_mode": DB_REPOSITORY.enabled}
    payload = DB_REPOSITORY.collection_observer_item_detail(item_id, max_chars=max_chars)
    payload["db_mode"] = DB_REPOSITORY.enabled
    return payload


def _collection_observer_reanalysis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    item_id = str((payload.get("item_id") or "")).strip()
    reason = str(payload.get("reason") or "operator_requested").strip() or "operator_requested"
    if not item_id:
        return {"ok": False, "error": "item_id is required", "item_id": ""}
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "requeue_seed_detail_analysis"):
        return {"ok": False, "item_id": item_id, "error": "database repository is not available", "db_mode": DB_REPOSITORY.enabled}
    result = DB_REPOSITORY.requeue_seed_detail_analysis(item_id, reason=reason)
    result["db_mode"] = DB_REPOSITORY.enabled
    return result


def _collection_observer_manual_update_payload(payload: dict[str, Any]) -> dict[str, Any]:
    item_id = str((payload.get("item_id") or "")).strip()
    updates = payload.get("updates")
    if not item_id:
        return {"ok": False, "error": "item_id is required", "item_id": ""}
    if not isinstance(updates, dict) or not updates:
        return {"ok": False, "item_id": item_id, "error": "updates must be a non-empty object"}
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "manual_update_flat_item"):
        return {"ok": False, "item_id": item_id, "error": "database repository is not available", "db_mode": DB_REPOSITORY.enabled}
    result = DB_REPOSITORY.manual_update_flat_item(item_id, updates)
    result["db_mode"] = DB_REPOSITORY.enabled
    return result


def _collection_observer_reset_region_links_payload(payload: dict[str, Any]) -> dict[str, Any]:
    location_code = str((payload.get("location_code") or "")).strip()
    if not location_code:
        return {"ok": False, "error": "location_code is required", "location_code": ""}
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "reset_seed_link_region"):
        return {"ok": False, "location_code": location_code, "error": "database repository is not available", "db_mode": DB_REPOSITORY.enabled}
    result = DB_REPOSITORY.reset_seed_link_region(location_code)
    result["db_mode"] = DB_REPOSITORY.enabled
    return result


def _collection_runtime_state_label() -> str:
    try:
        status_payload = _collection_api_lightweight_status_payload()
        runtime_state = str(status_payload.get("runtime_state") or "").strip()
        if runtime_state:
            return runtime_state
    except Exception:
        pass
    if _collection_effectively_paused():
        return "暂停中"
    return "运行中"


def _collection_observer_runtime_control_payload(action: str) -> dict[str, Any]:
    global SOLVER_MANUAL_RESUME_EPOCH
    safe_action = str(action or "").strip().lower()
    if safe_action not in {"pause", "resume"}:
        return {"ok": False, "error": "action must be pause or resume", "action": safe_action}
    if safe_action == "pause":
        _set_collection_pause_state(True, "operator")
    else:
        _set_collection_pause_state(False)
        SOLVER_MANUAL_RESUME_EPOCH = time.time()
        _clear_solver_running_state()
        _clear_solver_manual_required_state()
        flag_path = _solver_force_unlock_flag_path()
        if os.path.exists(flag_path):
            try:
                os.remove(flag_path)
            except Exception as error:
                return {
                    "ok": False,
                    "error": f"failed to clear force unlock flag: {error}",
                    "action": safe_action,
                    "paused": _collection_effectively_paused(),
                    "captcha_solver": _captcha_solver_runtime_status(),
                }
        challenge_state_error = _clear_solver_challenge_state()
        if challenge_state_error:
            return {
                "ok": False,
                "error": f"failed to clear persisted challenge state: {challenge_state_error}",
                "action": safe_action,
                "paused": _collection_effectively_paused(),
                "captcha_solver": _captcha_solver_runtime_status(),
            }
    return {
        "ok": True,
        "action": safe_action,
        "paused": _collection_effectively_paused(),
        "runtime_state": _collection_runtime_state_label(),
        "captcha_solver": _captcha_solver_runtime_status(),
    }


def _normalize_auth_completion_id(value: Any) -> str | None:
    completion_id = str(value or "").strip()
    return completion_id[:160] if completion_id else None


def _auth_completion_confirmation_path() -> Path:
    state_dir = str(os.getenv("FAPAI_SOLVER_STATE_DIR") or DATA_DIR).strip() or DATA_DIR
    return Path(state_dir) / "auth-completion-confirmations.json"


def _read_auth_completion_confirmations() -> dict[str, float]:
    path = _auth_completion_confirmation_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    raw_confirmations = payload.get("confirmations") if isinstance(payload, dict) else None
    if not isinstance(raw_confirmations, dict):
        return {}
    confirmations: dict[str, float] = {}
    for raw_id, raw_epoch in raw_confirmations.items():
        completion_id = _normalize_auth_completion_id(raw_id)
        if not completion_id:
            continue
        try:
            confirmations[completion_id] = float(raw_epoch)
        except (TypeError, ValueError):
            continue
    return confirmations


def _auth_completion_was_confirmed(completion_id: str | None) -> bool:
    if not completion_id:
        return False
    with AUTH_COMPLETION_LOCK:
        AUTH_COMPLETION_CONFIRMATIONS.update(_read_auth_completion_confirmations())
        return completion_id in AUTH_COMPLETION_CONFIRMATIONS


def _remember_auth_completion_confirmation(completion_id: str | None) -> str | None:
    if not completion_id:
        return None
    with AUTH_COMPLETION_LOCK:
        confirmations = _read_auth_completion_confirmations()
        confirmations.update(AUTH_COMPLETION_CONFIRMATIONS)
        confirmations[completion_id] = time.time()
        if len(confirmations) > 256:
            confirmations = dict(sorted(confirmations.items(), key=lambda item: item[1])[-192:])
        path = _auth_completion_confirmation_path()
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps({"confirmations": confirmations}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except Exception as error:
            try:
                temporary.unlink(missing_ok=True)
            except Exception:
                pass
            return repr(error)
        AUTH_COMPLETION_CONFIRMATIONS.clear()
        AUTH_COMPLETION_CONFIRMATIONS.update(confirmations)
    return None


def _auth_state_is_confirmed(
    solver_status: dict[str, Any], scope: str | None = None
) -> bool:
    normalized_scope = _normalize_challenge_scope(scope)
    if normalized_scope:
        scoped = _solver_scope_runtime_status(normalized_scope)
        return bool(
            not scoped.get("paused")
            and not scoped.get("manual_required")
            and not scoped.get("force_reset_required")
        )
    return bool(
        not solver_status.get("paused")
        and not solver_status.get("running")
        and not solver_status.get("manual_required")
        and not solver_status.get("force_unlock_flag_exists")
    )


def _finalize_auth_completion_after_cookie_snapshot(
    completion_id: str | None,
    *,
    expected_challenge_id: str | None,
    completion_request: dict[str, Any] | None,
) -> dict[str, Any]:
    """Clear a manual pause only after a healthy cookie snapshot is durable."""

    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON
    normalized_expected = str(expected_challenge_id or "").strip() or None
    completion_scope = _challenge_scope_for_request(completion_request)
    if completion_scope not in CHALLENGE_SCOPES:
        completion_scope = _scope_for_challenge_id(normalized_expected)
    if (
        completion_scope in CHALLENGE_SCOPES
        and not _solver_scope_runtime_status(completion_scope).get("challenge_id")
        and normalized_expected == str(SOLVER_CHALLENGE_ID or "").strip()
    ):
        completion_scope = None
    with AUTH_COMPLETION_FINALIZE_LOCK:
        normalized_current = (
            str(_solver_scope_runtime_status(completion_scope).get("challenge_id") or "").strip() or None
            if completion_scope in CHALLENGE_SCOPES
            else str(SOLVER_CHALLENGE_ID or "").strip() or None
        )
        if normalized_current != normalized_expected:
            return {
                "auth_state_confirmed": False,
                "stale_challenge": True,
                "expected_challenge_id": normalized_expected,
                "challenge_id": normalized_current,
                "error": "cookie snapshot belongs to an older captcha challenge",
            }

        previously_confirmed = _auth_completion_was_confirmed(completion_id)
        before_status = _captcha_solver_runtime_status()
        if previously_confirmed and _auth_state_is_confirmed(before_status, completion_scope):
            return {
                "auth_state_confirmed": True,
                "idempotent": True,
                "challenge_id": normalized_current,
            }

        clear_error = _clear_solver_manual_required_pause_compat(completion_scope or None)
        cleared_status = _captcha_solver_runtime_status()
        auth_state_confirmed = clear_error is None and _auth_state_is_confirmed(cleared_status, completion_scope)
        receipt_error: str | None = None
        if auth_state_confirmed:
            receipt_error = _remember_auth_completion_confirmation(completion_id)
            auth_state_confirmed = receipt_error is None

        if auth_state_confirmed:
            SOLVER_LAST_STATUS = "manual_auth_completed"
            SOLVER_LAST_FAILURE_REASON = None
            _remember_solver_auth_completion(completion_request)
        else:
            recovery_error: str | None = None
            if clear_error is None:
                if isinstance(completion_request, dict) and completion_request:
                    _refresh_solver_last_request(completion_request)
                _begin_solver_challenge(completion_request)
                recovery_error = _mark_solver_manual_required(
                    manual_only=_solver_target_requires_manual_only(completion_request),
                    scope=completion_scope or None,
                )
            SOLVER_LAST_STATUS = "manual_required"
            SOLVER_LAST_FAILURE_REASON = "manual_required"
            _set_collection_pause_state(True, "manual_required")

        result: dict[str, Any] = {
            "auth_state_confirmed": auth_state_confirmed,
            "idempotent": bool(previously_confirmed and auth_state_confirmed),
            "challenge_id": SOLVER_CHALLENGE_ID,
        }
        if clear_error is not None:
            result["error"] = f"failed to clear force unlock flag: {clear_error}"
        elif receipt_error is not None:
            result["error"] = f"failed to persist auth completion receipt: {receipt_error}"
        elif not auth_state_confirmed:
            result["error"] = "auth state remained paused or manual_required after cleanup"
        if not auth_state_confirmed and recovery_error is not None:
            result["recovery_error"] = recovery_error
        return result


def _node_auth_challenge_matches(payload: dict[str, Any], source: str) -> bool:
    challenge_id = str(payload.get("challenge_id") or "").strip()
    scope = _normalize_challenge_scope(payload.get("scope")) or _scope_for_challenge_id(challenge_id)
    active_id = (
        str(_solver_scope_runtime_status(scope).get("challenge_id") or "").strip()
        if scope in CHALLENGE_SCOPES
        else str(SOLVER_CHALLENGE_ID or "").strip()
    )
    if source != "pc2_local_solver" or not active_id:
        return True
    return bool(challenge_id and challenge_id == active_id)


def _collection_observer_resume_after_cooldown_payload(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resume collection after a node-local cooldown without claiming a solve.

    The request id is recorded in the same durable receipt store as auth
    completions so a NAS timeout or PC2 restart can safely replay the request.
    """
    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON
    payload = payload if isinstance(payload, dict) else {}
    request_id = _normalize_auth_completion_id(payload.get("resume_request_id"))
    source = str(payload.get("source") or "pc2_local_solver")
    resume_scope = _normalize_challenge_scope(payload.get("scope")) or _scope_for_challenge_id(payload.get("challenge_id"))
    if resume_scope not in CHALLENGE_SCOPES:
        reported_resume_id = str(payload.get("challenge_id") or "").strip()
        if reported_resume_id and reported_resume_id == str(SOLVER_CHALLENGE_ID or "").strip():
            resume_scope = None
        else:
            resume_scope = _challenge_scope_for_request(SOLVER_LAST_REQUEST)
    if not request_id:
        return {
            "ok": False,
            "action": "resume_after_cooldown",
            "source": source,
            "resume_request_id": None,
            "auth_state_confirmed": False,
            "paused": bool(_collection_effectively_paused()),
            "captcha_solver": _captcha_solver_runtime_status(),
            "error": "resume_request_id is required",
        }
    if not _node_auth_challenge_matches(payload, source):
        solver_status = _captcha_solver_runtime_status()
        return {
            "ok": False,
            "action": "resume_after_cooldown",
            "source": source,
            "resume_request_id": request_id,
            "auth_state_confirmed": False,
            "stale_challenge": True,
            "challenge_id": SOLVER_CHALLENGE_ID,
            "paused": bool(solver_status.get("paused")),
            "captcha_solver": solver_status,
            "error": "resume request belongs to an older captcha challenge",
        }

    receipt_id = f"resume-after-cooldown:{request_id}"
    previously_confirmed = _auth_completion_was_confirmed(receipt_id)
    before_status = _captcha_solver_runtime_status()
    already_clear = _auth_state_is_confirmed(before_status, resume_scope)
    clear_error: str | None = None
    receipt_error: str | None = None
    if previously_confirmed:
        auth_state_confirmed = already_clear
    else:
        clear_error = _clear_solver_manual_required_pause_compat(resume_scope or None)
        cleared_status = _captcha_solver_runtime_status()
        auth_state_confirmed = clear_error is None and _auth_state_is_confirmed(cleared_status, resume_scope)
        if auth_state_confirmed:
            receipt_error = _remember_auth_completion_confirmation(receipt_id)
            auth_state_confirmed = receipt_error is None

    if auth_state_confirmed:
        SOLVER_LAST_STATUS = "resumed_after_cooldown"
        SOLVER_LAST_FAILURE_REASON = None
        resume_request = SOLVER_LAST_REQUEST
        if resume_scope in CHALLENGE_SCOPES:
            scoped_request = _solver_scope_runtime_status(resume_scope).get("last_request")
            if isinstance(scoped_request, dict) and scoped_request:
                resume_request = scoped_request
        _remember_solver_auth_completion(resume_request)
    else:
        SOLVER_LAST_STATUS = "manual_required"
        SOLVER_LAST_FAILURE_REASON = "manual_required"
        _set_collection_pause_state(True, "manual_required", scope=resume_scope or None)
    solver_status = _captcha_solver_runtime_status()
    scoped_result_status = (
        _solver_scope_runtime_status(resume_scope)
        if resume_scope in CHALLENGE_SCOPES
        else solver_status
    )
    result: dict[str, Any] = {
        "ok": auth_state_confirmed,
        "action": "resume_after_cooldown",
        "source": source,
        "resume_request_id": request_id,
        "auth_state_confirmed": auth_state_confirmed,
        "idempotent": bool(previously_confirmed or (already_clear and auth_state_confirmed)),
        "manual_auth_completed": False,
        "paused": bool(solver_status.get("paused")),
        "scope": resume_scope or None,
        "scope_paused": bool(scoped_result_status.get("paused")),
        "scope_manual_required": bool(scoped_result_status.get("manual_required")),
        "scope_force_reset_required": bool(scoped_result_status.get("force_reset_required")),
        "scope_force_unlock_flag_exists": bool(
            resume_scope in CHALLENGE_SCOPES
            and os.path.exists(_solver_scope_manual_flag_path(resume_scope))
        ),
        "runtime_state": _collection_runtime_state_label(),
        "captcha_solver": solver_status,
        "cookie_snapshot": {"status": "skipped", "reason": "resume_after_cooldown"},
    }
    if clear_error is not None:
        result["error"] = f"failed to clear force unlock flag: {clear_error}"
    elif receipt_error is not None:
        result["error"] = f"failed to persist resume receipt: {receipt_error}"
    elif previously_confirmed and not auth_state_confirmed:
        result["error"] = "confirmed resume_request_id is stale for the current auth state"
    elif not auth_state_confirmed:
        result["error"] = "auth state remained paused or manual_required after cleanup"
    return result


def _collection_observer_auth_complete_payload(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON
    payload = payload if isinstance(payload, dict) else {}
    completion_id = _normalize_auth_completion_id(payload.get("completion_id"))
    source = str(payload.get("source") or "operator")
    completion_scope = _normalize_challenge_scope(payload.get("scope")) or _scope_for_challenge_id(payload.get("challenge_id"))
    if source == "pc2_local_solver" and not completion_id:
        solver_status = _captcha_solver_runtime_status()
        return {
            "ok": False,
            "action": "auth_complete",
            "source": source,
            "completion_id": None,
            "auth_state_confirmed": False,
            "challenge_id": SOLVER_CHALLENGE_ID,
            "paused": bool(solver_status.get("paused")),
            "captcha_solver": solver_status,
            "error": "completion_id is required for pc2_local_solver",
        }
    if not _node_auth_challenge_matches(payload, source):
        solver_status = _captcha_solver_runtime_status()
        return {
            "ok": False,
            "action": "auth_complete",
            "source": source,
            "completion_id": completion_id,
            "auth_state_confirmed": False,
            "stale_challenge": True,
            "challenge_id": SOLVER_CHALLENGE_ID,
            "paused": bool(solver_status.get("paused")),
            "captcha_solver": solver_status,
            "error": "completion belongs to an older captcha challenge",
        }
    previously_confirmed = _auth_completion_was_confirmed(completion_id)
    before_status = _captcha_solver_runtime_status()
    completion_request = before_status.get("last_request")
    if not isinstance(completion_request, dict) or not completion_request:
        completion_request = SOLVER_LAST_REQUEST
    if completion_scope not in CHALLENGE_SCOPES:
        completion_scope = _challenge_scope_for_request(completion_request)
    if completion_scope in CHALLENGE_SCOPES:
        scoped_request = _solver_scope_runtime_status(completion_scope).get("last_request")
        if isinstance(scoped_request, dict) and scoped_request:
            completion_request = scoped_request
    reported_completion_id = str(payload.get("challenge_id") or "").strip()
    if (
        completion_scope in CHALLENGE_SCOPES
        and not _solver_scope_runtime_status(completion_scope).get("challenge_id")
        and reported_completion_id == str(SOLVER_CHALLENGE_ID or "").strip()
    ):
        completion_scope = None
    already_clear = _auth_state_is_confirmed(before_status, completion_scope)
    refresh_cookie_snapshot = _payload_flag(payload, "refresh_cookie_snapshot", True)
    snapshot_gate_required = bool(
        refresh_cookie_snapshot
        or source == "pc2_local_solver"
        or _solver_target_requires_manual_only(completion_request)
    )
    snapshot_payload = dict(payload)
    if snapshot_gate_required:
        snapshot_payload["refresh_cookie_snapshot"] = True
    expected_challenge_id = (
        str(_solver_scope_runtime_status(completion_scope).get("challenge_id") or "").strip() or None
        if completion_scope in CHALLENGE_SCOPES
        else str(SOLVER_CHALLENGE_ID or "").strip() or None
    )

    clear_error: str | None = None
    receipt_error: str | None = None
    finalization_error: str | None = None
    if previously_confirmed:
        auth_state_confirmed = already_clear
        cookie_snapshot = _auth_cookie_snapshot_runtime_status()
    elif not snapshot_gate_required or already_clear:
        clear_error = _clear_solver_manual_required_pause_compat(completion_scope or None)
        cleared_status = _captcha_solver_runtime_status()
        auth_state_confirmed = clear_error is None and _auth_state_is_confirmed(cleared_status, completion_scope)
        if auth_state_confirmed:
            receipt_error = _remember_auth_completion_confirmation(completion_id)
            auth_state_confirmed = receipt_error is None
        cookie_snapshot = _schedule_auth_cookie_snapshot_refresh(snapshot_payload, completion_id)
    else:
        # Phase one: the operator/node reported a completed browser challenge,
        # but HTTP workers must remain paused until those cookies pass the same
        # health probe used by collection.  The background retry performs phase
        # two and clears this exact challenge only after a healthy snapshot.
        auth_state_confirmed = False
        SOLVER_LAST_STATUS = "manual_required"
        SOLVER_LAST_FAILURE_REASON = "manual_required"
        _set_collection_pause_state(True, "manual_required", scope=completion_scope or None)
        cookie_snapshot = _schedule_auth_cookie_snapshot_refresh(
            snapshot_payload,
            completion_id,
            finalize_auth=True,
            expected_challenge_id=expected_challenge_id,
            completion_request=(
                dict(completion_request) if isinstance(completion_request, dict) else None
            ),
        )
        if cookie_snapshot.get("status") == "completed" and cookie_snapshot.get("refreshed") is True:
            finalization = _finalize_auth_completion_after_cookie_snapshot(
                completion_id,
                expected_challenge_id=expected_challenge_id,
                completion_request=(
                    dict(completion_request) if isinstance(completion_request, dict) else None
                ),
            )
            auth_state_confirmed = finalization.get("auth_state_confirmed") is True
            finalization_error = str(finalization.get("error") or "").strip() or None
            cookie_snapshot = {
                **cookie_snapshot,
                "auth_state_confirmed": auth_state_confirmed,
                "auth_finalization": finalization,
            }

    if auth_state_confirmed:
        SOLVER_LAST_STATUS = "manual_auth_completed"
        SOLVER_LAST_FAILURE_REASON = None
        _remember_solver_auth_completion(completion_request)
    elif not previously_confirmed:
        SOLVER_LAST_STATUS = "manual_required"
        SOLVER_LAST_FAILURE_REASON = "manual_required"
        _set_collection_pause_state(True, "manual_required", scope=completion_scope or None)
    solver_status = _captcha_solver_runtime_status()
    scoped_result_status = (
        _solver_scope_runtime_status(completion_scope)
        if completion_scope in CHALLENGE_SCOPES
        else solver_status
    )
    snapshot_status = str(cookie_snapshot.get("status") or "").strip().lower()
    auth_confirmation_pending = bool(
        not auth_state_confirmed and snapshot_status in {"pending", "running"}
    )
    result = {
        "ok": bool(auth_state_confirmed or auth_confirmation_pending),
        "action": "auth_complete",
        "source": source,
        "completion_id": completion_id,
        "auth_state_confirmed": auth_state_confirmed,
        "idempotent": bool(previously_confirmed or (already_clear and auth_state_confirmed)),
        "manual_auth_completed": auth_state_confirmed,
        "auth_confirmation_pending": auth_confirmation_pending,
        "paused": bool(solver_status.get("paused")),
        "scope": completion_scope or None,
        "scope_paused": bool(scoped_result_status.get("paused")),
        "scope_manual_required": bool(scoped_result_status.get("manual_required")),
        "scope_force_reset_required": bool(scoped_result_status.get("force_reset_required")),
        "scope_force_unlock_flag_exists": bool(
            completion_scope in CHALLENGE_SCOPES
            and os.path.exists(_solver_scope_manual_flag_path(completion_scope))
        ),
        "runtime_state": _collection_runtime_state_label(),
        "captcha_solver": solver_status,
        "cookie_snapshot": cookie_snapshot,
    }
    if clear_error is not None:
        result["error"] = f"failed to clear force unlock flag: {clear_error}"
    elif receipt_error is not None:
        result["error"] = f"failed to persist auth completion receipt: {receipt_error}"
    elif finalization_error is not None:
        result["error"] = finalization_error
    elif previously_confirmed and not auth_state_confirmed:
        result["error"] = "confirmed completion_id is stale for the current auth state"
    elif snapshot_status == "failed":
        result["error"] = "cookie snapshot refresh failed; collection remains paused"
    elif snapshot_status == "completed" and not auth_state_confirmed:
        result["error"] = "cookie snapshot completed but auth state could not be confirmed"
    elif not auth_state_confirmed:
        result["pending_reason"] = "waiting for a healthy cookie snapshot"
    return result


def _safe_collection_static_path(request_path: str) -> Path | None:
    if request_path.startswith("/collection/"):
        relative = unquote(request_path[len("/collection/") :]).strip("/")
    elif request_path.startswith("/assets/"):
        relative = unquote(request_path.lstrip("/")).strip("/")
    else:
        return None
    if not relative:
        relative = "index.html"
    candidate = (COLLECTOR_DESKTOP_DIST / relative).resolve()
    root = COLLECTOR_DESKTOP_DIST.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _collection_observer_static_asset(request_path: str) -> tuple[bytes, str] | None:
    path = _safe_collection_static_path(request_path)
    if path is None:
        return None
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix == ".js":
        content_type = "application/javascript"
    elif path.suffix == ".css":
        content_type = "text/css"
    elif path.suffix == ".html":
        content_type = "text/html; charset=utf-8"
    return path.read_bytes(), content_type


def _collection_observer_page_html() -> str:
    index_path = COLLECTOR_DESKTOP_DIST / "index.html"
    if index_path.is_file():
        return index_path.read_text(encoding="utf-8")
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FapaiFang 采集观察台</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%232459d6'/%3E%3Cpath d='M18 38h28v6H18zm4-18h20v6H22zm-4 9h28v6H18z' fill='white'/%3E%3C/svg%3E">
  <style>
    :root { color-scheme: light; --bg:#f5f7fb; --panel:#fff; --line:#d9e0ea; --text:#172033; --muted:#667085; --primary:#2459d6; --ok:#047857; --warn:#b45309; --bad:#b42318; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Inter, "Segoe UI", Arial, "Microsoft YaHei", sans-serif; background:var(--bg); color:var(--text); }
    header { padding:20px 24px 14px; background:linear-gradient(135deg,#172033,#2459d6); color:white; }
    header h1 { margin:0 0 8px; font-size:24px; }
    header p { margin:0; color:rgba(255,255,255,.78); }
    main { padding:18px 24px 28px; display:grid; gap:16px; }
    .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; }
    .card, .panel { background:var(--panel); border:1px solid var(--line); border-radius:14px; box-shadow:0 8px 24px rgba(16,24,40,.06); }
    .card { padding:14px 16px; }
    .card .label { color:var(--muted); font-size:13px; }
    .card .value { font-size:28px; font-weight:760; margin-top:5px; }
    .card .hint { color:var(--muted); margin-top:6px; font-size:12px; }
    .toolbar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding:12px; }
    .tabs { display:flex; gap:8px; flex-wrap:wrap; }
    button { border:1px solid var(--line); background:white; color:var(--text); padding:8px 12px; border-radius:10px; cursor:pointer; }
    button.active { background:var(--primary); color:white; border-color:var(--primary); }
    button:hover { border-color:var(--primary); }
    input, select { border:1px solid var(--line); border-radius:10px; padding:8px 10px; }
    .layout { display:grid; grid-template-columns:minmax(420px,1.15fr) minmax(360px,.85fr); gap:16px; align-items:start; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th, td { border-top:1px solid var(--line); padding:9px 10px; text-align:left; vertical-align:top; }
    th { color:var(--muted); background:#f8fafc; font-weight:650; position:sticky; top:0; }
    tr.item-row { cursor:pointer; }
    tr.item-row:hover { background:#eef4ff; }
    .table-wrap { max-height:68vh; overflow:auto; }
    .pill { display:inline-flex; align-items:center; border-radius:999px; padding:2px 8px; font-size:12px; background:#eef2ff; color:#3538cd; }
    .pill.ok { background:#ecfdf3; color:var(--ok); }
    .pill.warn { background:#fffaeb; color:var(--warn); }
    .pill.bad { background:#fef3f2; color:var(--bad); }
    .detail { padding:14px; }
    .detail h2 { margin:0 0 8px; font-size:18px; }
    .kv { display:grid; grid-template-columns:112px 1fr; gap:6px 10px; font-size:13px; margin:10px 0 12px; }
    .kv .k { color:var(--muted); }
    pre { white-space:pre-wrap; word-break:break-word; background:#0b1020; color:#dbeafe; border-radius:12px; padding:12px; max-height:360px; overflow:auto; font-size:12px; line-height:1.45; }
    details { border-top:1px solid var(--line); padding:10px 0; }
    summary { cursor:pointer; font-weight:650; }
    a { color:var(--primary); word-break:break-all; }
    .status-line { display:flex; gap:8px; align-items:center; flex-wrap:wrap; color:var(--muted); font-size:13px; }
    .error { color:var(--bad); }
    @media (max-width: 980px) { .layout { grid-template-columns:1fr; } .table-wrap { max-height:none; } }
  </style>
</head>
<body>
  <header>
    <h1>FapaiFang 采集观察台</h1>
    <p>只读观察采集三段流水：商品链接采集、商品详情页采集、商品详情页 AI 分析。暂不包含房价分析引擎。</p>
  </header>
  <main>
    <section class="cards" id="cards"></section>
    <section class="panel">
      <div class="toolbar">
        <div class="tabs">
          <button data-stage="links" class="active">商品链接采集</button>
          <button data-stage="details">商品详情页采集</button>
          <button data-stage="analysis">商品详情页 AI 分析</button>
        </div>
        <label>每页 <select id="limit"><option>50</option><option selected>100</option><option>200</option><option>500</option></select></label>
        <button id="refresh">刷新</button>
        <button id="prev">上一页</button>
        <button id="next">下一页</button>
        <span class="status-line" id="listStatus"></span>
      </div>
    </section>
    <section class="layout">
      <div class="panel table-wrap"><table><thead><tr><th>商品</th><th>状态</th><th>列表来源</th><th>详情/AI文件</th></tr></thead><tbody id="items"></tbody></table></div>
      <aside class="panel detail" id="detail"><h2>商品详情</h2><p class="status-line">点击左侧任一商品查看采集到的实际数据。</p></aside>
    </section>
  </main>
  <script>
    const state = { stage: 'links', limit: 100, offset: 0, total: 0 };
    const $ = (id) => document.getElementById(id);
    const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const fmt = (v) => v === null || v === undefined || v === '' ? '-' : esc(v);
    const statusClass = (s) => s === 'detail_completed' ? 'ok' : (String(s || '').includes('failed') || String(s || '').includes('blocked') ? 'bad' : 'warn');

    async function getJson(url) {
      const resp = await fetch(url, { cache: 'no-store' });
      if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
      return await resp.json();
    }

    async function loadOverview() {
      const data = await getJson('/api/collection/overview');
      const m = data.modules || {};
      const paused = data.status && data.status.paused;
      $('cards').innerHTML = `
        <div class="card"><div class="label">运行状态</div><div class="value">${paused ? '已暂停' : '运行中'}</div><div class="hint">captcha/manual 状态也会计入暂停判定</div></div>
        <div class="card"><div class="label">商品链接采集</div><div class="value">${fmt(m.links && m.links.total)}</div><div class="hint">总链接出现次数；唯一商品 ${fmt(m.links && m.links.unique_items)}</div></div>
        <div class="card"><div class="label">商品详情页采集</div><div class="value">${fmt(m.details && m.details.captured)}</div><div class="hint">待抓 ${fmt(m.details && m.details.pending)} / 失败 ${fmt(m.details && m.details.failed)} / 阻塞 ${fmt(m.details && m.details.blocked)}</div></div>
        <div class="card"><div class="label">商品详情页 AI 分析</div><div class="value">${fmt(m.analysis && m.analysis.finalized)}</div><div class="hint">待分析 ${fmt(m.analysis && m.analysis.pending)} / 失败 ${fmt(m.analysis && m.analysis.failed)} / 阻塞 ${fmt(m.analysis && m.analysis.blocked)}</div></div>
      `;
    }

    function renderItems(data) {
      state.total = data.total || 0;
      $('listStatus').textContent = `阶段 ${state.stage}，总数 ${state.total}，当前 ${state.offset + 1}-${Math.min(state.offset + state.limit, state.total)}`;
      $('items').innerHTML = (data.items || []).map(item => {
        const occ = item.latest_occurrence || {};
        const artifacts = item.artifacts || {};
        const fileHint = state.stage === 'analysis' ? item.final_json_path : artifacts.detail_html_path;
        return `<tr class="item-row" data-id="${esc(item.item_id)}">
          <td><strong>${fmt(item.title || item.item_id)}</strong><br><a href="${esc(item.source_url || '#')}" target="_blank">${fmt(item.source_url)}</a><br><span class="status-line">ID ${fmt(item.item_id)} · ${fmt(item.last_seen_at || item.updated_at)}</span></td>
          <td><span class="pill ${statusClass(item.status)}">${fmt(item.status)}</span><br>attempts ${fmt(item.detail_attempt_count)}</td>
          <td>${fmt(occ.sort_name || occ.sort_key)}<br>page ${fmt(occ.page)} / rank ${fmt(occ.rank)}<br><a href="${esc(occ.source_page_url || '#')}" target="_blank">${fmt(occ.source_page_url)}</a></td>
          <td>${fmt(fileHint)}</td>
        </tr>`;
      }).join('');
      document.querySelectorAll('tr.item-row').forEach(row => row.addEventListener('click', () => loadDetail(row.dataset.id)));
    }

    async function loadItems() {
      $('listStatus').textContent = '加载中...';
      const data = await getJson(`/api/collection/items?stage=${encodeURIComponent(state.stage)}&limit=${state.limit}&offset=${state.offset}`);
      renderItems(data);
    }

    function artifactBlock(title, artifact) {
      artifact = artifact || {};
      const content = artifact.json ? JSON.stringify(artifact.json, null, 2) : (artifact.content || '');
      return `<details open><summary>${esc(title)} ${artifact.exists ? '' : '(未找到文件)'}</summary><div class="status-line">${fmt(artifact.path)} ${artifact.truncated ? ' · 已截断' : ''} ${artifact.error ? ' · ' + esc(artifact.error) : ''}</div><pre>${esc(content || '无内容')}</pre></details>`;
    }

    async function loadDetail(itemId) {
      $('detail').innerHTML = '<h2>商品详情</h2><p class="status-line">加载中...</p>';
      const data = await getJson(`/api/collection/item?item_id=${encodeURIComponent(itemId)}&max_chars=200000`);
      if (!data.found) {
        $('detail').innerHTML = `<h2>商品详情</h2><p class="error">未找到商品 ${esc(itemId)}</p>`;
        return;
      }
      const item = data.item || {};
      const artifacts = data.artifacts || {};
      const flat = data.flat_item ? JSON.stringify(data.flat_item, null, 2) : '';
      $('detail').innerHTML = `
        <h2>${fmt(item.title || item.item_id)}</h2>
        <div class="kv">
          <div class="k">商品 ID</div><div>${fmt(item.item_id)}</div>
          <div class="k">状态</div><div><span class="pill ${statusClass(item.status)}">${fmt(item.status)}</span></div>
          <div class="k">商品链接</div><div><a href="${esc(item.source_url || '#')}" target="_blank">${fmt(item.source_url)}</a></div>
          <div class="k">首次发现</div><div>${fmt(item.first_seen_at)}</div>
          <div class="k">最后更新</div><div>${fmt(item.updated_at)}</div>
        </div>
        ${artifactBlock('详情页 HTML / 文本', artifacts.detail_html)}
        ${artifactBlock('详情页 selected.json', artifacts.selected_json)}
        ${artifactBlock('详情页 description-data.json', artifacts.description_json)}
        ${artifactBlock('AI 标准化 final.json', artifacts.final_json)}
        <details ${flat ? 'open' : ''}><summary>数据库标准化字段</summary><pre>${esc(flat || '暂无 property_listing 标准化字段')}</pre></details>
        <details><summary>列表出现记录</summary><pre>${esc(JSON.stringify(data.occurrences || [], null, 2))}</pre></details>
      `;
    }

    document.querySelectorAll('button[data-stage]').forEach(btn => btn.addEventListener('click', async () => {
      document.querySelectorAll('button[data-stage]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.stage = btn.dataset.stage;
      state.offset = 0;
      await loadItems();
    }));
    $('limit').addEventListener('change', async e => { state.limit = Number(e.target.value || 100); state.offset = 0; await loadItems(); });
    $('refresh').addEventListener('click', async () => { await loadOverview(); await loadItems(); });
    $('prev').addEventListener('click', async () => { state.offset = Math.max(0, state.offset - state.limit); await loadItems(); });
    $('next').addEventListener('click', async () => { if (state.offset + state.limit < state.total) state.offset += state.limit; await loadItems(); });
    (async function init(){ try { await loadOverview(); await loadItems(); } catch (err) { $('listStatus').innerHTML = `<span class="error">${esc(err.message)}</span>`; } })();
  </script>
</body>
</html>"""


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


def _coerce_optional_iso_datetime(value: Any) -> datetime.datetime | None:
    text = _coerce_optional_text(value)
    if text is None:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _collection_shared_data_root(data_root: Path) -> Path:
    expanded = Path(data_root).expanduser()
    try:
        resolved = expanded.resolve()
    except OSError:
        resolved = expanded
    if resolved.name.lower() == "datas":
        return resolved.parent
    return resolved


def _hybrid_collection_challenge_metrics_summary(data_root: Path) -> dict[str, Any]:
    runtime_summary = _hybrid_collection_runtime_summary(data_root)
    history_summary = _hybrid_collection_runtime_history_summary(data_root)
    current_reason_counts = _coerce_optional_mapping(runtime_summary.get("reason_counts"))
    recent_reason_counts = _coerce_optional_mapping(history_summary.get("recent_reason_counts"))
    current_challenge_detected_count = int(current_reason_counts.get("challenge_detected", 0) or 0)
    recent_challenge_detected_count = int(recent_reason_counts.get("challenge_detected", 0) or 0)
    current_browserless_attempt_count = max(
        int(runtime_summary.get("browserless_success_count", 0) or 0)
        + int(runtime_summary.get("browser_fallback_required_count", 0) or 0),
        0,
    )
    recent_browserless_attempt_count = max(
        int(history_summary.get("recent_browserless_success_count", 0) or 0)
        + int(history_summary.get("recent_browser_fallback_required_count", 0) or 0),
        0,
    )
    current_challenge_hit_rate = (
        current_challenge_detected_count / current_browserless_attempt_count
        if current_browserless_attempt_count > 0
        else None
    )
    recent_challenge_hit_rate = (
        recent_challenge_detected_count / recent_browserless_attempt_count
        if recent_browserless_attempt_count > 0
        else None
    )
    return {
        "available": bool(runtime_summary.get("available") or history_summary.get("available")),
        "current_challenge_detected_count": current_challenge_detected_count,
        "current_browserless_attempt_count": current_browserless_attempt_count,
        "current_challenge_hit_rate": current_challenge_hit_rate,
        "recent_challenge_detected_count": recent_challenge_detected_count,
        "recent_browserless_attempt_count": recent_browserless_attempt_count,
        "recent_challenge_hit_rate": recent_challenge_hit_rate,
        "recent_runs": int(history_summary.get("recent_runs", 0) or 0),
        "last_reason": _coerce_optional_text(runtime_summary.get("last_reason")),
        "last_decision": _coerce_optional_text(runtime_summary.get("last_decision")),
        "last_probe_body_has_challenge": _coerce_optional_bool(
            runtime_summary.get("last_probe_body_has_challenge")
        )
        is True,
        "top_fallback_reason": _coerce_optional_text(runtime_summary.get("top_fallback_reason")),
        "recent_top_fallback_reason": _coerce_optional_text(
            history_summary.get("recent_top_fallback_reason")
        ),
    }


def _pc1_auth_auto_resume_state_summary(data_root: Path) -> dict[str, Any]:
    shared_root = _collection_shared_data_root(data_root)
    raw = _load_json_snapshot(shared_root / "secrets" / "pc1-auth-auto-resume-state.json")
    if not raw:
        return {
            "available": False,
            "mode": None,
            "status": None,
            "started_at": None,
            "completed_at": None,
            "wait_elapsed_seconds": None,
            "poll_seconds": 0,
            "max_wait_seconds": 0,
            "api_base": None,
            "cdp_endpoint": None,
            "last_error": None,
        }

    started_at = _coerce_optional_iso_datetime(raw.get("started_at"))
    completed_at = _coerce_optional_iso_datetime(raw.get("completed_at"))
    wait_elapsed_seconds = None
    if started_at is not None:
        ended_at = completed_at or datetime.datetime.now(datetime.timezone.utc)
        wait_elapsed_seconds = max(int((ended_at - started_at).total_seconds()), 0)

    poll_seconds = _coerce_optional_int(raw.get("poll_seconds"))
    if poll_seconds is None or poll_seconds < 0:
        poll_seconds = 0
    max_wait_seconds = _coerce_optional_int(raw.get("max_wait_seconds"))
    if max_wait_seconds is None or max_wait_seconds < 0:
        max_wait_seconds = 0

    return {
        "available": True,
        "mode": _coerce_optional_text(raw.get("mode")),
        "status": _coerce_optional_text(raw.get("status")),
        "started_at": _coerce_optional_text(raw.get("started_at")),
        "completed_at": _coerce_optional_text(raw.get("completed_at")),
        "wait_elapsed_seconds": wait_elapsed_seconds,
        "poll_seconds": poll_seconds,
        "max_wait_seconds": max_wait_seconds,
        "api_base": _coerce_optional_text(raw.get("api_base")),
        "cdp_endpoint": _coerce_optional_text(raw.get("cdp_endpoint")),
        "last_error": _coerce_optional_text(raw.get("last_error")),
    }


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

            # Disabled: Do not kill user's browser or open recovery windows
            # This was interrupting user's active browser sessions
            print("[WATCHDOG] Auto-recovery disabled to avoid interrupting user browser.")
            return
            # try:
            #     # Step 1: Kill all Chrome processes
            #     subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'],
            #                   capture_output=True, timeout=30)
            #     print("[WATCHDOG] Killed all Chrome processes.")
            #
            #     # Wait for processes to fully terminate
            #     time.sleep(5)
            #
            #     # Step 2: Open 3 independent Chrome windows with Remote Debugging
            #     # Window 1: Sniff Tab #1
            #     subprocess.Popen(['start', 'chrome', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window',
            #                      'https://sf.taobao.com/list/50025969.htm?auto_recovery=1'],
            #                     shell=True)
            #     time.sleep(2)
            #
            #     # Window 2: Sniff Tab #2
            #     subprocess.Popen(['start', 'chrome', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window',
            #                      'https://sf.taobao.com/list/50025969.htm?auto_recovery=2'],
            #                     shell=True)
            #     time.sleep(2)
            #
            #     # Window 3: Worker Tab
            #     subprocess.Popen(['start', 'chrome', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window',
            #                      'https://sf.taobao.com/?auto_worker=1'],
            #                     shell=True)
            #
            #     print("[WATCHDOG] Recovery complete. 3 Chrome windows opened with Debug Port 9222.")
            #
            #     # Reset timer to avoid immediate re-trigger
            #     LAST_REQUEST_TIME = time.time()
            #
            # except Exception as e:
            #     print(f"[WATCHDOG] Recovery failed: {e}")


def manual_solver_retry_thread():
    """Retry the automated solver at a controlled interval while manual verification is required."""
    while True:
        try:
            result = _trigger_manual_solver_retry_if_due()
            if result.get("queued"):
                solver_request = result.get("solver_request") if isinstance(result.get("solver_request"), dict) else {}
                print(
                    "[SOLVER] Manual-required auto retry queued "
                    f"(attempt {result.get('attempt')}, target={solver_request.get('target_url')})."
                )
        except Exception as error:
            print(f"[SOLVER] Manual-required auto retry monitor failed: {error}")
        time.sleep(_manual_solver_retry_poll_seconds())


def check_and_launch_browser():
    """Check if debug port 9222 is open, if not, launch browser."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 9222))
    sock.close()

    if result != 0:
        print("[STARTUP] Debug port 9222 not open. Auto-launch disabled to avoid interrupting user browser.")
        # Disabled: Do not kill browser or launch windows
        # try:
        #      # Kill existing first to ensure port availability
        #      import subprocess
        #      subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], capture_output=True)
        #      time.sleep(2)
        #
        #      # Launch windows
        #      subprocess.Popen(['start', 'chrome', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window', 'https://sf.taobao.com/list/50025969.htm?auto_recovery=1'], shell=True)
        #      time.sleep(2)
        #      subprocess.Popen(['start', 'chrome', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window', 'https://sf.taobao.com/list/50025969.htm?auto_recovery=2'], shell=True)
        #      time.sleep(2)
        #      subprocess.Popen(['start', 'chrome', '--remote-debugging-port=9222', '--remote-allow-origins=*', '--disable-blink-features=AutomationControlled', '--disable-background-networking', '--disable-sync', '--disable-client-side-phishing-detection', '--disable-default-apps', '--no-default-browser-check', '--new-window', 'https://sf.taobao.com/?auto_worker=1'], shell=True)
        #      print("[STARTUP] Chrome launched with debug port 9222.")
        # except Exception as e:
        #     print(f"[STARTUP] Error launching browser: {e}")

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


def load_data(data_root: str | Path | None = None):
    """Load all json files from datas/ directory (and archives) into memory index"""
    global SEEN_IDS, PENDING_TASKS
    active_data_root = os.fspath(data_root or DATA_DIR)
    SEEN_IDS = {}
    PENDING_TASKS = []

    if not os.path.exists(active_data_root):
        os.makedirs(active_data_root)

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
        root_files = glob.glob(os.path.join(active_data_root, '*.json'))
    except:
        root_files = []

    # 2. Scan Archive JSONs (Recursive)
    try:
        archive_pattern = os.path.join(active_data_root, 'archive', '**', '*.json')
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

    if _restore_solver_challenge_state():
        print(
            f"[SOLVER] Restored persisted challenge {SOLVER_CHALLENGE_ID}; "
            "collection remains paused until node confirmation."
        )
    if _restore_solver_scope_states():
        print("[SOLVER] Restored independent list/detail challenge latches.")

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

    threading.Thread(target=manual_solver_retry_thread, daemon=True).start()
    print(
        "[SOLVER] Manual-required auto retry monitor started "
        f"(interval: {_manual_solver_retry_interval_seconds()}s, poll: {_manual_solver_retry_poll_seconds()}s)."
    )

    try:
        _sample_nas_auth_recovery()
    except Exception as auth_recovery_error:
        print(f"[AUTH-RECOVERY] Initial progress sample failed: {auth_recovery_error!r}")
    if NAS_AUTH_RECOVERY.enabled:
        threading.Thread(target=nas_auth_recovery_watchdog_thread, daemon=True).start()
        print(
            "[AUTH-RECOVERY] NAS stall recovery watchdog started "
            f"(stall: {NAS_AUTH_RECOVERY.stall_seconds:.0f}s, poll: {NAS_AUTH_RECOVERY_POLL_SECONDS:.0f}s)."
        )

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

        if request_path in ("/collection", "/collection/"):
            body = _collection_observer_page_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif request_path.startswith("/collection/") or request_path.startswith("/assets/"):
            asset = _collection_observer_static_asset(request_path)
            if asset is None:
                self.send_error_json(
                    status=404,
                    code="COLLECTION_STATIC_ASSET_NOT_FOUND",
                    message="collection console 静态资源不存在",
                    details={"path": request_path},
                )
                return
            body, content_type = asset
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif request_path == "/api/collection/overview":
            try:
                self.send_json(_collection_observer_overview_payload())
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="COLLECTION_OBSERVER_OVERVIEW_FAILED",
                    message="collection observer overview 读取失败",
                    details={"error": str(e)},
                )

        elif request_path == "/api/collection/items":
            try:
                self.send_json(_collection_observer_items_payload(query))
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="COLLECTION_OBSERVER_ITEMS_FAILED",
                    message="collection observer item 列表读取失败",
                    details={"error": str(e)},
                )

        elif request_path == "/api/collection/regions":
            try:
                self.send_json(_collection_observer_regions_payload(query))
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="COLLECTION_OBSERVER_REGIONS_FAILED",
                    message="collection observer 地区状态读取失败",
                    details={"error": str(e)},
                )

        elif request_path == "/api/collection/item" or request_path.startswith("/api/collection/items/"):
            try:
                if request_path.startswith("/api/collection/items/"):
                    query = dict(query)
                    query["item_id"] = [unquote(request_path.rsplit("/", 1)[-1])]
                self.send_json(_collection_observer_item_payload(query))
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="COLLECTION_OBSERVER_ITEM_FAILED",
                    message="collection observer item 详情读取失败",
                    details={"error": str(e)},
                )

        elif request_path in MANUAL_REVIEW_RECEIPT_ENDPOINTS:
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

        elif request_path == "/api/collection/auth/recovery":
            authorized, auth_error = _nas_auth_recovery_authorized(self.headers)
            if not authorized:
                self.send_error_json(
                    status=403,
                    code="COLLECTION_AUTH_RECOVERY_FORBIDDEN",
                    message="跨设备认证恢复凭据无效",
                    details={"error": auth_error},
                )
                return
            self.send_json({"ok": True, "auth_recovery": NAS_AUTH_RECOVERY.snapshot()})

        elif request_path == "/api/collection/auth/recovery/snapshot":
            authorized, auth_error = _nas_auth_recovery_authorized(self.headers)
            if not authorized:
                self.send_error_json(
                    status=403,
                    code="COLLECTION_AUTH_RECOVERY_FORBIDDEN",
                    message="跨设备认证恢复凭据无效",
                    details={"error": auth_error},
                )
                return
            recovery_id = str((query.get("recovery_id") or [""])[0] or "").strip()
            recovery_state = NAS_AUTH_RECOVERY.snapshot()
            active = recovery_state.get("active") if isinstance(recovery_state, dict) else None
            if not recovery_id or not isinstance(active, dict) or str(active.get("recovery_id") or "") != recovery_id:
                self.send_error_json(
                    status=409,
                    code="COLLECTION_AUTH_RECOVERY_NOT_ACTIVE",
                    message="认证恢复任务已变化，请重新拉取状态",
                )
                return
            status = str(active.get("status") or "")
            snapshot = active.get("snapshot") if isinstance(active.get("snapshot"), dict) else {}
            expected_sha256 = str(snapshot.get("sha256") or "").strip().lower()
            if status not in {"snapshot_ready", "pc2_claimed", "restarting"} or not expected_sha256:
                self.send_error_json(
                    status=409,
                    code="COLLECTION_AUTH_RECOVERY_SNAPSHOT_NOT_READY",
                    message="认证快照尚未就绪",
                )
                return
            snapshot_path = Path(_resolve_auth_cookie_snapshot_path({"node_id": "pc2"}))
            try:
                raw_snapshot = snapshot_path.read_bytes()
            except OSError:
                self.send_error_json(
                    status=404,
                    code="COLLECTION_AUTH_RECOVERY_SNAPSHOT_MISSING",
                    message="NAS 认证快照文件不存在",
                )
                return
            if not raw_snapshot or len(raw_snapshot) > 5 * 1024 * 1024:
                self.send_error_json(
                    status=409,
                    code="COLLECTION_AUTH_RECOVERY_SNAPSHOT_INVALID",
                    message="NAS 认证快照大小无效",
                )
                return
            actual_sha256 = hashlib.sha256(raw_snapshot).hexdigest()
            if actual_sha256 != expected_sha256:
                self.send_error_json(
                    status=409,
                    code="COLLECTION_AUTH_RECOVERY_SNAPSHOT_CHANGED",
                    message="NAS 认证快照摘要已变化，请等待 PC1 重新发布",
                )
                return
            self.send_json(
                {
                    "ok": True,
                    "recovery_id": recovery_id,
                    "sha256": actual_sha256,
                    "encoding": "base64",
                    "snapshot": base64.b64encode(raw_snapshot).decode("ascii"),
                }
            )

        elif request_path == '/api/status':
            try:
                if _collection_api_lightweight_status_enabled():
                    self.send_json(_collection_api_lightweight_status_payload())
                    return
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

                solver_status_snapshot = _captcha_solver_runtime_status()
                self.send_json({
                    "paused": _collection_effectively_paused(),
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
                    "captcha_solver": solver_status_snapshot,
                    "auth_recovery": NAS_AUTH_RECOVERY.snapshot(),
                    "collection_scopes": solver_status_snapshot.get("collection_scopes", {}),
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
                    load_data(active_data_root)
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
                    load_data(active_data_root)
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
                    load_data(active_data_root)
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
                self.send_json(
                    _seed_collection_service().next_task(
                        session_id,
                        paused=_collection_scope_effectively_paused("seed"),
                    )
                )
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_SEED_NEXT_TASK_FAILED",
                    message="种子任务分发失败",
                    details={"error": str(e)},
                )


        elif self.path in ('/api/get_tasks', '/api/collection/details/tasks'):
            if _collection_scope_effectively_paused("detail"):
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
            _set_collection_pause_state(False)
            _clear_solver_running_state()
            _clear_solver_manual_required_state()
            # Clear emergency flag if it exists
            flag_path = _solver_force_unlock_flag_path()
            if os.path.exists(flag_path):
                try: os.remove(flag_path)
                except: pass
            challenge_state_error = _clear_solver_challenge_state()
            if challenge_state_error:
                print(f"[SOLVER] Failed to clear persisted challenge state on API resume: {challenge_state_error}")
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





        elif self.path == "/api/collection/region/reset_links":
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
            try:
                result = _collection_observer_reset_region_links_payload(payload)
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="COLLECTION_OBSERVER_REGION_RESET_FAILED",
                    message="地区链接采集重置失败",
                    details={"error": str(e)},
                )
                return
            status = 200 if result.get("ok") else 400
            if status != 200:
                self.send_error_json(
                    status=status,
                    code="COLLECTION_OBSERVER_REGION_RESET_REJECTED",
                    message="地区链接采集重置请求被拒绝",
                    details=result,
                )
                return
            self.send_json(result)

        elif self.path == "/api/collection/item/reanalyze":
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
            try:
                result = _collection_observer_reanalysis_payload(payload)
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="COLLECTION_OBSERVER_REANALYZE_FAILED",
                    message="AI 再分析入队失败",
                    details={"error": str(e)},
                )
                return
            status = 200 if result.get("ok") else 400
            if status != 200:
                self.send_error_json(
                    status=status,
                    code="COLLECTION_OBSERVER_REANALYZE_REJECTED",
                    message="AI 再分析请求被拒绝",
                    details=result,
                )
                return
            self.send_json(result)

        elif self.path == "/api/collection/item/manual_update":
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
            try:
                result = _collection_observer_manual_update_payload(payload)
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="COLLECTION_OBSERVER_MANUAL_UPDATE_FAILED",
                    message="手动更新标准化数据失败",
                    details={"error": str(e)},
                )
                return
            status = 200 if result.get("ok") else 400
            if status != 200:
                self.send_error_json(
                    status=status,
                    code="COLLECTION_OBSERVER_MANUAL_UPDATE_REJECTED",
                    message="手动更新标准化数据请求被拒绝",
                    details=result,
                )
                return
            self.send_json(result)

        elif self.path in ("/api/collection/control/pause", "/api/collection/control/resume"):
            action = "pause" if self.path.endswith("/pause") else "resume"
            try:
                result = _collection_observer_runtime_control_payload(action)
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="COLLECTION_OBSERVER_RUNTIME_CONTROL_FAILED",
                    message="采集运行状态切换失败",
                    details={"error": str(e), "action": action},
                )
                return
            status = 200 if result.get("ok") else 400
            if status != 200:
                self.send_error_json(
                    status=status,
                    code="COLLECTION_OBSERVER_RUNTIME_CONTROL_REJECTED",
                    message="采集运行状态切换请求被拒绝",
                    details=result,
                )
                return
            self.send_json(result)

        elif self.path in {
            "/api/collection/auth/recovery/claim",
            "/api/collection/auth/recovery/snapshot_ready",
            "/api/collection/auth/recovery/pc2_restarting",
            "/api/collection/auth/recovery/result",
        }:
            authorized, auth_error = _nas_auth_recovery_authorized(self.headers)
            if not authorized:
                self.send_error_json(
                    status=403,
                    code="COLLECTION_AUTH_RECOVERY_FORBIDDEN",
                    message="跨设备认证恢复凭据无效",
                    details={"error": auth_error},
                )
                return
            content_length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length > 0 else {}
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

            recovery_id = str(payload.get("recovery_id") or "").strip()
            if not recovery_id:
                result = {"ok": False, "error": "recovery_id is required"}
            elif self.path.endswith("/claim"):
                role = str(payload.get("role") or "").strip().lower()
                node_id = str(payload.get("node_id") or "").strip().lower()
                if (role, node_id) not in {("pc1", "pc1"), ("pc2", "pc2")}:
                    result = {"ok": False, "error": "role and node_id must identify pc1 or pc2"}
                else:
                    result = NAS_AUTH_RECOVERY.claim(role, recovery_id, node_id)
            elif self.path.endswith("/snapshot_ready"):
                try:
                    result = NAS_AUTH_RECOVERY.snapshot_ready(
                        recovery_id,
                        sha256=str(payload.get("sha256") or ""),
                        cookie_count=int(payload.get("cookie_count") or 0),
                        created_at_epoch=float(payload.get("created_at_epoch") or time.time()),
                    )
                except (TypeError, ValueError) as error:
                    result = {"ok": False, "error": str(error)}
            elif self.path.endswith("/pc2_restarting"):
                result = NAS_AUTH_RECOVERY.pc2_restarting(recovery_id)
            else:
                result = _nas_auth_recovery_result(payload)

            if not result.get("ok"):
                self.send_error_json(
                    status=409 if result.get("stale_recovery") else 400,
                    code="COLLECTION_AUTH_RECOVERY_REJECTED",
                    message="跨设备认证恢复请求被拒绝",
                    details=result,
                )
                return
            self.send_json(result)

        elif self.path == "/api/collection/auth/force_reset":
            content_length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length > 0 else {}
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
            result = _force_reset_solver_scope(payload.get("scope"), payload.get("challenge_id"))
            status = 200 if result.get("ok") or result.get("stale_challenge") else 409
            if status != 200:
                self.send_error_json(
                    status=status,
                    code="COLLECTION_CHALLENGE_FORCE_RESET_REJECTED",
                    message="验证码尚未达到保底重置时间或状态不匹配",
                    details=result,
                )
                return
            self.send_json(result)

        elif self.path == "/api/collection/auth/complete":
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
            try:
                result = _collection_observer_auth_complete_payload(payload)
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="COLLECTION_OBSERVER_AUTH_COMPLETE_FAILED",
                    message="人工认证完成通知失败",
                    details={"error": str(e)},
                )
                return
            status = 200 if result.get("ok") or result.get("stale_challenge") else 400
            if status != 200:
                self.send_error_json(
                    status=status,
                    code="COLLECTION_OBSERVER_AUTH_COMPLETE_REJECTED",
                    message="人工认证完成通知被拒绝",
                    details=result,
                )
                return
            self.send_json(result)

        elif self.path == "/api/collection/auth/resume_after_cooldown":
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
            try:
                result = _collection_observer_resume_after_cooldown_payload(payload)
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="COLLECTION_OBSERVER_AUTH_RESUME_FAILED",
                    message="冷却后恢复采集失败",
                    details={"error": str(e)},
                )
                return
            status = 200 if result.get("ok") or result.get("stale_challenge") else 400
            if status != 200:
                self.send_error_json(
                    status=status,
                    code="COLLECTION_OBSERVER_AUTH_RESUME_REJECTED",
                    message="冷却后恢复采集请求被拒绝",
                    details=result,
                )
                return
            self.send_json(result)

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
                    load_data(active_data_root)
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
                    load_data(active_data_root)
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
                    load_data(active_data_root)
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

        elif self.path in ('/api/report_captcha', '/api/report_manual_captcha'):
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
            # List/search and detail challenges are independent state machines.
            # Never rewrite a detail report to the seed request; doing so makes
            # one scope pause (and invalidate) the other scope's solver.
            solver_request = _build_solver_request(payload)
            challenge_scope = _challenge_scope_for_request(solver_request)
            stale_challenge_id = _solver_report_stale_challenge_id(payload)
            if stale_challenge_id:
                print(
                    "[SOLVER] captcha report ignored; stale challenge id "
                    f"{stale_challenge_id!r} does not match the active challenge."
                )
                self.send_json({
                    "status": "stale_challenge",
                    "challenge_id": SOLVER_CHALLENGE_ID,
                    "captcha_solver": _captcha_solver_runtime_status(),
                })
                return
            if _solver_report_predates_auth_completion(payload):
                print(
                    "[SOLVER] captcha report ignored; it was created before "
                    "the same node completed auth."
                )
                self.send_json({
                    "status": "stale_auth_report",
                    "captcha_solver": _captcha_solver_runtime_status(),
                })
                return
            force_reset_suppression = _solver_force_reset_report_suppression(solver_request)
            if force_reset_suppression is not None:
                retry_after = max(
                    0.0,
                    float(force_reset_suppression["grace_seconds"])
                    - float(force_reset_suppression["age_seconds"]),
                )
                print(
                    "[SOLVER] report_captcha ignored after scoped force reset; "
                    f"scope={force_reset_suppression['scope']} "
                    f"({retry_after:.0f}s grace remaining)."
                )
                self.send_json({
                    "status": "recent_force_reset",
                    "reason": force_reset_suppression["reason"],
                    "scope": force_reset_suppression["scope"],
                    "retry_after_seconds": int(math.ceil(retry_after)),
                    "captcha_solver": _captcha_solver_runtime_status(),
                })
                return
            auth_report_suppression = _solver_auth_report_suppression(solver_request)
            if auth_report_suppression is not None:
                retry_after = max(
                    0.0,
                    float(auth_report_suppression["grace_seconds"])
                    - float(auth_report_suppression["age_seconds"]),
                )
                print(
                    "[SOLVER] report_captcha ignored after recent auth; "
                    f"reason={auth_report_suppression['reason']} "
                    f"captured_since_auth={auth_report_suppression['captured_since_auth']} "
                    f"({retry_after:.0f}s grace remaining)."
                )
                self.send_json({
                    "status": "recent_auth_complete",
                    "reason": auth_report_suppression["reason"],
                    "captured_since_auth": auth_report_suppression["captured_since_auth"],
                    "retry_after_seconds": int(math.ceil(retry_after)),
                    "captcha_solver": _captcha_solver_runtime_status(),
                })
                return
            manual_only = (
                self.path == '/api/report_manual_captcha'
                or _payload_manual_only(payload)
                or _solver_target_requires_manual_only(solver_request)
            )
            if manual_only:
                self.send_json(_manual_only_captcha_report_payload(payload))
                return
            if solver_request:
                _refresh_solver_last_request(solver_request)
            force_retry = _payload_force_solver_retry(payload)
            solver_status = _captcha_solver_runtime_status()
            scope_status = (
                _solver_scope_runtime_status(challenge_scope)
                if challenge_scope in CHALLENGE_SCOPES
                else solver_status
            )
            if scope_status.get("manual_required"):
                if force_retry:
                    solver_was_running = bool(solver_status.get("running"))
                    clear_error = _clear_solver_manual_required_pause(
                        preserve_running_state=solver_was_running,
                        scope=challenge_scope or None,
                    )
                    if clear_error:
                        self.send_error_json(
                            status=500,
                            code="AVM_CAPTCHA_SOLVER_FORCE_RETRY_FAILED",
                            message="清除验证码人工认证锁失败",
                            details={"error": clear_error},
                        )
                        return
                    solver_status = _captcha_solver_runtime_status()
                    scope_status = (
                        _solver_scope_runtime_status(challenge_scope)
                        if challenge_scope in CHALLENGE_SCOPES
                        else solver_status
                    )
                    print("[SOLVER] report_captcha force retry cleared manual verification state.")
                    if solver_was_running and SOLVER_RUNNING:
                        self.send_json({"status": "resuming", "captcha_solver": solver_status})
                        return
                else:
                    print("[SOLVER] report_captcha ignored; manual verification is already required.")
                    self.send_json({"status": "manual_required", "captcha_solver": solver_status})
                    return
            if scope_status.get("manual_required"):
                print("[SOLVER] report_captcha ignored; manual verification is already required.")
                self.send_json({"status": "manual_required", "captcha_solver": solver_status})
                return
            if solver_status.get("queued"):
                print("[SOLVER] report_captcha ignored; solver submission is already queued.")
                self.send_json({
                    "status": "already_running",
                    "elapsed_seconds": 0,
                    "captcha_solver": solver_status,
                })
                return
            if SOLVER_RUNNING:
                elapsed = max(int(time.time() - SOLVER_START_TIME), 0)
                max_runtime_seconds = _solver_max_runtime_seconds()
                if elapsed < max_runtime_seconds:
                    print(f"[SOLVER] report_captcha ignored; solver already running for {elapsed}s.")
                    self.send_json({
                        "status": "already_running",
                        "elapsed_seconds": elapsed,
                        "captcha_solver": solver_status,
                    })
                    return
                print(
                    f"[SOLVER] report_captcha ignored; solver still running after {elapsed}s. "
                    f"Configured limit is {max_runtime_seconds}s; marking manual verification "
                    "required instead of starting a parallel solver."
                )
                flag_error = _mark_solver_manual_required(scope=challenge_scope or None)
                response_payload = {
                    "status": "manual_required",
                    "elapsed_seconds": elapsed,
                    "captcha_solver": _captcha_solver_runtime_status(),
                }
                if flag_error:
                    response_payload["flag_error"] = flag_error
                self.send_json(response_payload)
                return
            # 远端 CDP 节点走本地求解器，不由 API 服务器直接求解。
            solver_cdp = str(solver_request.get("cdp_endpoint") or "").strip()
            if solver_cdp and _solver_cdp_endpoint_is_remote(solver_cdp):
                node_id = str(solver_request.get("node_id") or "").strip()
                _begin_solver_challenge(solver_request)
                print(
                    f"[SOLVER] Remote CDP endpoint {solver_cdp} detected "
                    f"(node={node_id or 'unknown'}); deferring to node-local solver. "
                    "Pausing collection; node solver will clear when solved."
                )
                _set_collection_pause_state(True, "captcha_solver", scope=challenge_scope or None)
                self.send_json({
                    "status": "deferred_to_node_solver",
                    "captcha_solver": _captcha_solver_runtime_status(),
                })
                return

            print("CAPTCHA REPORTED! Triggering Solver...")
            _begin_solver_challenge(solver_request)

            # Using ThreadPool to avoid blocking the server main loop
            try:
                queued = _submit_solver_request(solver_request)
            except Exception as e:
                self.send_error_json(
                    status=500,
                    code="AVM_CAPTCHA_SOLVER_QUEUE_FAILED",
                    message="验证码求解任务入队失败",
                    details={"error": str(e)},
                )
                return
            if not queued:
                self.send_json({
                    "status": "already_running",
                    "elapsed_seconds": 0,
                    "captcha_solver": _captcha_solver_runtime_status(),
                })
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
        try:
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
        except Exception as error:
            if _is_client_disconnect_error(error):
                return
            raise

    def send_error_json(self, status, code, message, details=None):
        payload = {
            "error": {
                "code": code,
                "message": message,
                "details": details or {}
            }
        }
        try:
            self.send_response(status)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode('utf-8'))
        except Exception as error:
            if _is_client_disconnect_error(error):
                return
            raise

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

    def run_solver(self, solver_request=None, submission_token=None):
        """Run the captcha solver in background with server-level retry."""
        global SOLVER_RUNNING, SOLVER_START_TIME, SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON
        global SOLVER_LAST_FINISHED_TIME, SOLVER_LAST_REQUEST, SOLVER_MANUAL_RESUME_EPOCH
        global SOLVER_CANCEL_EPOCH, COLLECTION_PAUSE_REASON, SOLVER_MANUAL_REQUIRED_EPOCH

        # Initialize if not present (hack for hot-reload or first run)
        if 'SOLVER_RUNNING' not in globals():
            SOLVER_RUNNING = False
            SOLVER_START_TIME = 0

        solver_scope = _challenge_scope_for_request(solver_request)
        solver_status_snapshot = _captcha_solver_runtime_status()
        scoped_snapshot = (
            _solver_scope_runtime_status(solver_scope)
            if solver_scope in CHALLENGE_SCOPES
            else {}
        )
        if solver_scope in CHALLENGE_SCOPES and scoped_snapshot.get("challenge_id"):
            scope_requires_manual = bool(scoped_snapshot.get("manual_required"))
        elif solver_scope in CHALLENGE_SCOPES:
            latest_scope = _challenge_scope_for_request(SOLVER_LAST_REQUEST)
            scope_requires_manual = bool(
                solver_status_snapshot.get("manual_required")
                if latest_scope not in CHALLENGE_SCOPES or latest_scope == solver_scope
                else False
            )
        else:
            scope_requires_manual = bool(solver_status_snapshot.get("manual_required"))
        if scope_requires_manual:
            already_authenticated = False
            try:
                probe_solver = _build_solver_for_request(solver_request)
                preflight = probe_solver._preflight_current_challenge()
                already_authenticated = bool(preflight.get("already_authenticated"))
            except Exception as error:
                print(f"[SOLVER] Stale auth-lock preflight failed: {error}")
            if already_authenticated:
                print("\033[92m[SOLVER] Page already authenticated; clearing stale captcha auth lock.\033[0m")
                _clear_auth_lock_after_solver_success(scope=solver_scope or None)
                _release_solver_submission(submission_token)
                return
            _release_solver_submission(submission_token)
            print("\033[93m[SOLVER] Manual verification already required. Skipping solver run.\033[0m")
            return

        activated, activation_reason, activation_value = _activate_solver_submission(
            solver_request,
            submission_token,
        )
        if not activated:
            if activation_reason == "solver_running":
                print(
                    f"\033[93m[SOLVER] Solver already running for "
                    f"{int(activation_value)}s. Skipping duplicate submission.\033[0m"
                )
            else:
                print(f"[SOLVER] Skipping {activation_reason} solver submission.")
            return

        SERVER_MAX_ATTEMPTS = 2  # Server-level retries (solver has its own internal retries)

        solver_started_at = activation_value
        try:
            if not PAUSED or COLLECTION_PAUSE_REASON is None:
                _set_collection_pause_state(True, "captcha_solver", scope=solver_scope or None)
            worker_quiesce_seconds = _solver_worker_quiesce_seconds()
            if worker_quiesce_seconds > 0:
                print(
                    f"[SOLVER] Waiting {worker_quiesce_seconds}s for node workers "
                    "to release the shared CDP browser."
                )
                time.sleep(worker_quiesce_seconds)
            if not _wait_for_solver_cdp_ready(solver_request):
                print("[SOLVER] Deferring solve attempt because the node CDP browser is unavailable.")
                _mark_solver_manual_required(scope=solver_scope or None)
                SOLVER_LAST_FAILURE_REASON = "cdp_unavailable"
                return
            print("\033[93m[SOLVER] Starting solver...\033[0m")
            active_solver = _build_solver_for_request(solver_request)
            try:
                active_solver.cancel_checker = lambda: (
                    SOLVER_MANUAL_RESUME_EPOCH >= solver_started_at
                    or SOLVER_CANCEL_EPOCH >= solver_started_at
                )
            except Exception:
                pass
            if solver_request:
                print(
                    f"[SOLVER] Using request-scoped solver "
                    f"cdp_endpoint={solver_request.get('cdp_endpoint')!r} "
                    f"target_url_set={bool(solver_request.get('target_url'))}"
                )

            success = False
            for server_attempt in range(SERVER_MAX_ATTEMPTS):
                if server_attempt > 0:
                    print(f"\033[93m[SOLVER] Server retry {server_attempt + 1}/{SERVER_MAX_ATTEMPTS} after delay...\033[0m")
                    time.sleep(3)

                success = active_solver.solve()
                if success:
                    break
                if getattr(active_solver, "last_failure_reason", None) in {"manual_required", "cancelled"}:
                    print("[SOLVER] Manual-required/cancelled failure detected; skipping server retry.")
                    break

            if success:
                print("\033[92m[SOLVER] ✅ Captcha Solved! Resuming system...\033[0m")
                _clear_auth_lock_after_solver_success(scope=solver_scope or None)
            else:
                SOLVER_LAST_FAILURE_REASON = getattr(active_solver, "last_failure_reason", None) or "solve_failed"
                if SOLVER_MANUAL_RESUME_EPOCH >= solver_started_at:
                    print("[SOLVER] Manual resume happened after this solver started; suppressing stale failure pause.")
                    SOLVER_LAST_STATUS = "resumed"
                    SOLVER_LAST_FAILURE_REASON = None
                    _set_collection_pause_state(False, scope=solver_scope or None)
                    SOLVER_RUNNING = False
                    SOLVER_LAST_FINISHED_TIME = time.time()
                    return
                if SOLVER_CANCEL_EPOCH >= solver_started_at and _captcha_solver_runtime_status().get("manual_required"):
                    print("[SOLVER] Solver cancel requested after manual_required was marked; leaving collection paused for operator verification.")
                    SOLVER_LAST_STATUS = "manual_required"
                    SOLVER_LAST_FAILURE_REASON = "manual_required"
                    SOLVER_RUNNING = False
                    SOLVER_LAST_FINISHED_TIME = time.time()
                    return
                if SOLVER_LAST_FAILURE_REASON == "manual_required":
                    SOLVER_LAST_STATUS = "manual_required"
                else:
                    SOLVER_LAST_STATUS = "failed"
                print("\033[91m[SOLVER] ❌ All solve attempts failed. System remains PAUSED.\033[0m")
                print("\033[91m[SOLVER] Manual intervention required. Please solve in Edge, then click 'Resume' or delete 'force_unlock.flag'.\033[0m")
                # Create a retryable scoped lock flag for file-system/API
                # manual resume and restart-safe solver retries.  The helper
                # also refreshes the legacy flag for older operators.
                flag_error = _mark_solver_manual_required(scope=solver_scope or None)
                flag_path = _solver_force_unlock_flag_path()
                if flag_error:
                    print(f"[SOLVER] Failed to write force unlock flag: {flag_error}")

                # The automated solve attempt is finished at this point. Keep the
                # collection paused, but do not report the solver as actively
                # running while it waits for operator/manual verification.
                SOLVER_RUNNING = False
                SOLVER_LAST_FINISHED_TIME = time.time()

                # Wait until the operator resumes, the flag is deleted, or the
                # live page becomes authenticated after a later captcha pass.
                def _current_solver_scope_manual_required() -> bool:
                    if solver_scope not in CHALLENGE_SCOPES:
                        return bool(_captcha_solver_runtime_status().get("manual_required"))
                    scoped_status = _solver_scope_runtime_status(solver_scope)
                    if scoped_status.get("challenge_id"):
                        return bool(scoped_status.get("manual_required"))
                    # Legacy callers may mark manual_required before a scoped
                    # challenge receipt exists.  Keep that compatibility path,
                    # but do not inherit a different active scope's pause.
                    latest_scope = _challenge_scope_for_request(SOLVER_LAST_REQUEST)
                    if latest_scope in CHALLENGE_SCOPES and latest_scope != solver_scope:
                        return False
                    return bool(_captcha_solver_runtime_status().get("manual_required"))

                while _current_solver_scope_manual_required():
                    if not os.path.exists(flag_path):
                        print("\033[92m[SOLVER] 🟢 Force unlock flag removed! Auto-resuming system...\033[0m")
                        _set_collection_pause_state(False, scope=solver_scope or None)
                        _clear_solver_manual_required_state()
                        challenge_state_error = _clear_solver_challenge_state(solver_scope or None)
                        if challenge_state_error:
                            print(
                                "[SOLVER] Failed to clear persisted challenge state "
                                f"after force unlock: {challenge_state_error}"
                            )
                        break
                    try:
                        preflight = active_solver._preflight_current_challenge()
                    except Exception as error:
                        preflight = {}
                        print(f"[SOLVER] Auth-lock recovery preflight failed: {error}")
                    if preflight.get("already_authenticated"):
                        print("\033[92m[SOLVER] 🟢 Page authenticated while waiting; clearing captcha auth lock.\033[0m")
                        _clear_auth_lock_after_solver_success(scope=solver_scope or None)
                        break
                    time.sleep(2)

        except Exception as e:
            SOLVER_LAST_STATUS = "error"
            SOLVER_LAST_FAILURE_REASON = str(e)
            print(f"[SOLVER] Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            finished_at = time.time()
            is_current_solver_run = (
                solver_started_at <= 0
                or not SOLVER_START_TIME
                or float(SOLVER_START_TIME) == float(solver_started_at)
            )
            if is_current_solver_run:
                SOLVER_RUNNING = False
                SOLVER_LAST_FINISHED_TIME = finished_at
            else:
                print("[SOLVER] A newer solver run is active; not clearing its running state.")
            started_for_log = solver_started_at or SOLVER_START_TIME
            elapsed = max(finished_at - started_for_log, 0) if started_for_log > 0 else 0
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
