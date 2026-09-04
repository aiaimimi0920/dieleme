from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from html import unescape
from pathlib import Path
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urlparse, urlsplit, urlunsplit

import requests
import websocket

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    sync_playwright = None

DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9223"
DEFAULT_TARGET_URL = (
    "https://sf.taobao.com/list/50025969__2.htm"
    "?location_code=110101&st_param=2&auction_start_seg=-1&page=1"
)
DEFAULT_COOKIE_ORIGINS = ("https://sf.taobao.com", "https://login.taobao.com")
DEFAULT_CDP_CONNECT_TIMEOUT_MS = 20_000
DEFAULT_CDP_RECONNECT_ATTEMPTS = 3
DEFAULT_CDP_RECONNECT_BACKOFF_SECONDS = 0.5
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
)
DEFAULT_ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9,en;q=0.8"
DEFAULT_NAVIGATION_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8"
)

_SCRIPT_RE = re.compile(
    r"<script[^>]+id=['\"]sf-item-list-data['\"][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_SENSITIVE_INLINE_PATTERNS = (
    re.compile(r"x5secdata\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"cookie2\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"sgcookie\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"_tb_token_\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
)


__all__ = tuple(name for name in globals() if not name.startswith("__"))
