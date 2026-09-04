"""Shared imports, constants, and data types for the split runtime."""

from __future__ import annotations

import argparse

import contextlib

import hashlib

import json

import os

import re

import sys

import tempfile

import threading

import time

from collections.abc import Callable, Mapping, Sequence

from pathlib import Path

from typing import Any

from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from urllib.request import Request, urlopen

import websocket

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.internal_api_http import post_json

DEFAULT_CDP_ENDPOINT = os.environ.get("FAPAI_CDP_ENDPOINT") or os.environ.get("LIVE_BATCH_SMOKE_CDP") or "http://127.0.0.1:9223"

DEFAULT_CHECK_URL = "https://sf.taobao.com/list/50025969__2.htm"

DEFAULT_WAIT_SECONDS = 180

DEFAULT_POLL_SECONDS = 5

DEFAULT_API_BASE_URL = os.environ.get("FAPAI_API_BASE_URL", "http://127.0.0.1:8001/api")

DEFAULT_CDP_CONNECT_TIMEOUT_MS = 120000

DEFAULT_CDP_PAGE_TARGET_LIMIT = 12

DEFAULT_CDP_WEBSOCKET_TIMEOUT_SECONDS = 20

AUTH_PAGE_REUSE_WINDOW_SECONDS = max(
    1.0,
    float(os.environ.get("FAPAI_AUTH_PAGE_REUSE_WINDOW_SECONDS", "300")),
)

_AUTH_PAGE_LOCKS: dict[str, threading.Lock] = {}

_AUTH_PAGE_LOCKS_GUARD = threading.Lock()

HEALTHY_LIST_PAYLOAD = "healthy_list_payload"

PARTIAL_AVAILABLE = "partial_available"

ALL_SAMPLES_BLOCKED = "all_samples_blocked"

LOGIN_REQUIRED = "login_required"

CHALLENGE_REQUIRED = "challenge_required"

PUNISH_PAGE = "punish_page"

CAPTCHA_PAGE = "captcha_page"

CDP_UNREACHABLE = "cdp_unreachable"

UNKNOWN_BLOCKED = "unknown_blocked"

SENSITIVE_QUERY_KEYS = {
    "x5secdata",
    "x5sec",
    "cookie2",
    "sgcookie",
    "_tb_token_",
}

SENSITIVE_INLINE_PATTERNS = (
    re.compile(r"x5secdata\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"cookie2\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"sgcookie\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"_tb_token_\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
)

FetchPageFunc = Callable[[str, str], tuple[str, str]]

OpenPageFunc = Callable[[str, str], str]

ReportCaptchaFunc = Callable[[str, str, str], Mapping[str, object]]

SleepFunc = Callable[[float], None]

CAPTCHA_REPORT_CDP_ENV_NAMES = (
    "FAPAI_REPORT_CDP_ENDPOINT",
    "FAPAI_SOLVER_CDP_ENDPOINT",
)

__all__ = (
    'argparse',
    'contextlib',
    'hashlib',
    'json',
    'os',
    're',
    'sys',
    'tempfile',
    'threading',
    'time',
    'Callable',
    'Mapping',
    'Sequence',
    'Path',
    'Any',
    'parse_qsl',
    'quote',
    'urlencode',
    'urlsplit',
    'urlunsplit',
    'Request',
    'urlopen',
    'websocket',
    'REPO_ROOT',
    'post_json',
    'DEFAULT_CDP_ENDPOINT',
    'DEFAULT_CHECK_URL',
    'DEFAULT_WAIT_SECONDS',
    'DEFAULT_POLL_SECONDS',
    'DEFAULT_API_BASE_URL',
    'DEFAULT_CDP_CONNECT_TIMEOUT_MS',
    'DEFAULT_CDP_PAGE_TARGET_LIMIT',
    'DEFAULT_CDP_WEBSOCKET_TIMEOUT_SECONDS',
    'AUTH_PAGE_REUSE_WINDOW_SECONDS',
    '_AUTH_PAGE_LOCKS',
    '_AUTH_PAGE_LOCKS_GUARD',
    'HEALTHY_LIST_PAYLOAD',
    'PARTIAL_AVAILABLE',
    'ALL_SAMPLES_BLOCKED',
    'LOGIN_REQUIRED',
    'CHALLENGE_REQUIRED',
    'PUNISH_PAGE',
    'CAPTCHA_PAGE',
    'CDP_UNREACHABLE',
    'UNKNOWN_BLOCKED',
    'SENSITIVE_QUERY_KEYS',
    'SENSITIVE_INLINE_PATTERNS',
    'FetchPageFunc',
    'OpenPageFunc',
    'ReportCaptchaFunc',
    'SleepFunc',
    'CAPTCHA_REPORT_CDP_ENV_NAMES',
)
