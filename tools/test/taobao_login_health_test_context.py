from __future__ import annotations

import json

import sys

import types

from pathlib import Path

from typing import Any

import tools as tools_package

from tools import taobao_login_health

REPO_ROOT = Path(__file__).resolve().parents[2]

def _force_playwright_open(monkeypatch) -> None:
    def _raise_http_unavailable(_endpoint: str, _url: str) -> str:
        raise RuntimeError("force playwright fallback")

    monkeypatch.setattr(taobao_login_health, "open_page_via_cdp_http", _raise_http_unavailable, raising=False)

__all__ = [name for name in globals() if not name.startswith("__")]
