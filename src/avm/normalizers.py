"""Reusable numeric/unit normalization helpers for AVM pipelines."""

from __future__ import annotations

import re
from typing import Any, Optional


_AMOUNT_CLEAN_RE = re.compile(r"[^\d.\-万亿元整约余]", re.UNICODE)
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def clean_amount_string(value: Any) -> Optional[str]:
    """Normalize amount-like strings, keeping only numeric/unit markers."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value).strip()
    if not text:
        return None

    text = text.replace(",", "").replace("，", "")
    text = _AMOUNT_CLEAN_RE.sub("", text)
    return text or None


def parse_price_to_yuan(value: Any) -> Optional[float]:
    """Parse a price text/number into yuan.

    Supports explicit units in source text (万元/元).
    """
    cleaned = clean_amount_string(value)
    if cleaned is None:
        return None

    original_text = str(value)
    multiplier = 1.0
    if "万元" in original_text or ("万" in cleaned and "亿" not in cleaned):
        multiplier = 10000.0
    elif "亿元" in original_text or "亿" in cleaned:
        multiplier = 100000000.0

    number_match = _NUMBER_RE.search(cleaned)
    if not number_match:
        return None

    amount = float(number_match.group(0)) * multiplier
    if amount < 0:
        return None
    return amount


def parse_area_sqm(value: Any) -> Optional[float]:
    """Parse area text/number into sqm float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "").replace("，", "")
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    area = float(match.group(0))
    if area <= 0:
        return None
    return area
