from __future__ import annotations

import argparse

from contextlib import contextmanager

from datetime import datetime

import json

import math

import subprocess

import sys

import threading

import time

from pathlib import Path

from typing import Any, Callable

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import browserless_seed_probe, hybrid_seed_collector

DEFAULT_API_BASE = "http://127.0.0.1:8001/api"

DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9223"

DEFAULT_SESSION_ID = "hybrid-seed-runner"

DEFAULT_PROFILE_DIR = REPO_ROOT / "output" / "taobao-auth-profile"

DEFAULT_MODE = "hybrid"

DEFAULT_RUNTIME_SUMMARY_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_collection_runtime.json"

DEFAULT_RUNTIME_HISTORY_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_collection_runtime_history.jsonl"

DEFAULT_RUNTIME_SWITCH_EVENTS_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_mode_switch_events.jsonl"

DEFAULT_RECOVERY_POLICY_STATE_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_recovery_policy_state.json"

DEFAULT_RECOVERY_POLICY_EVENTS_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_recovery_policy_events.jsonl"

DEFAULT_OPERATOR_ESCALATION_EVENTS_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_operator_escalation_events.jsonl"

DEFAULT_OPERATOR_ESCALATION_STATE_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_operator_escalation_state.json"

DEFAULT_OPERATOR_ESCALATION_RECOVERY_EVENTS_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_operator_escalation_recovery_events.jsonl"

DEFAULT_OPERATOR_INTERVENTION_STATE_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_operator_intervention_state.json"

DEFAULT_OPERATOR_INTERVENTION_EVENTS_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_operator_intervention_events.jsonl"

_HYBRID_COLLECTION_STATUS_SNAPSHOT_CACHE = threading.local()

__all__ = [name for name in globals() if not name.startswith("__")]
