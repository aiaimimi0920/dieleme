from __future__ import annotations

import datetime, json, os, sys, time, traceback, uuid

import multiprocessing

from pathlib import Path

from typing import Any

from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path: sys.path.insert(0, str(REPO_ROOT))

from src.captcha_solver import CaptchaSolver

from tools.internal_api_http import fetch_json, post_json

from tools.pc2_auth_recovery import process_nas_auth_recovery_once

DEFAULT_API_BASE_URL = os.environ.get("FAPAI_API_BASE_URL", "http://192.168.15.200:8001/api")

DEFAULT_CDP_ENDPOINT = os.environ.get("FAPAI_CDP_ENDPOINT", "http://127.0.0.1:9223")

DEFAULT_POLL_SECONDS = int(os.environ.get("FAPAI_LOCAL_SOLVER_POLL_SECONDS", "5"))

DEFAULT_MAX_ATTEMPTS = 1

DEFAULT_DRAG_PROFILE_VARIANTS = 3

AUTH_COMPLETE_REQUEST_ATTEMPTS = int(os.environ.get("FAPAI_AUTH_COMPLETE_REQUEST_ATTEMPTS", "3"))

AUTH_COMPLETE_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("FAPAI_AUTH_COMPLETE_REQUEST_TIMEOUT_SECONDS", "15"))

AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS = float(os.environ.get("FAPAI_AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS", "1"))

AUTH_COMPLETE_RETRY_BASE_SECONDS = float(os.environ.get("FAPAI_AUTH_COMPLETE_RETRY_BASE_SECONDS", "5"))

AUTH_COMPLETE_RETRY_MAX_SECONDS = float(os.environ.get("FAPAI_AUTH_COMPLETE_RETRY_MAX_SECONDS", "60"))

AUTH_COMPLETE_PENDING_MAX_SECONDS = float(
    os.environ.get("FAPAI_AUTH_COMPLETE_PENDING_MAX_SECONDS", "120")
)

RECENT_HEALTHY_AUTH_MAX_AGE_SECONDS = float(
    os.environ.get("FAPAI_RECENT_HEALTHY_AUTH_MAX_AGE_SECONDS", "3600")
)

POST_AUTH_CDP_PROBE_GRACE_SECONDS = float(
    os.environ.get("FAPAI_POST_AUTH_CDP_PROBE_GRACE_SECONDS", "180")
)

SOLVER_EXECUTION_TIMEOUT_SECONDS = float(
    os.environ.get("FAPAI_LOCAL_SOLVER_EXECUTION_TIMEOUT_SECONDS", "180")
)

SOLVER_TERMINATE_GRACE_SECONDS = float(
    os.environ.get("FAPAI_LOCAL_SOLVER_TERMINATE_GRACE_SECONDS", "5")
)

SOLVER_HEARTBEAT_PATH = Path(
    os.environ.get("FAPAI_LOCAL_SOLVER_HEARTBEAT_PATH", "/tmp/fapaifang-local-solver-heartbeat.json")
)

AUTH_RECOVERY_SNAPSHOT_PATH = Path(
    os.environ.get("FAPAI_NAS_AUTH_RECOVERY_SNAPSHOT_PATH")
    or os.environ.get("FAPAI_COOKIE_SNAPSHOT", "/data/secrets/nodes/pc2/taobao-cookies.json")
)

AUTH_RECOVERY_MARKER_PATH = Path(
    os.environ.get(
        "FAPAI_NAS_AUTH_RECOVERY_MARKER_PATH",
        str(REPO_ROOT / ".codex-temp" / "bridge-control" / "pc2-auth-recovery.json"),
    )
)

AUTH_RECOVERY_TOKEN_PATH = Path(
    os.environ.get("FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE", "/data/secrets/nas-auth-recovery.token")
)

__all__ = [name for name in globals() if not name.startswith("__")]
