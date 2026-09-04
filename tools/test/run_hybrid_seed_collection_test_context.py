from __future__ import annotations

from collections import Counter

from decimal import Decimal

import json

from pathlib import Path

import re

import subprocess

import sys

from urllib.parse import parse_qs, urlparse

import requests

from tools import run_hybrid_seed_collection

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

class _FakeHttpSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, timeout: int):
        self.calls.append({"url": url, "timeout": timeout})
        return _FakeResponse(self.payload)

__all__ = [name for name in globals() if not name.startswith("__")]
