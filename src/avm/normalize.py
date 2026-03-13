"""AVM字段标准化工具。"""

from __future__ import annotations

import re
from typing import Any


_NUM_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def _extract_first_number(text: str) -> str | None:
    """从字符串中提取第一个数字片段。"""
    match = _NUM_PATTERN.search(text)
    return match.group(0) if match else None


def safe_float(value: Any, default: float = 0.0) -> float:
    """安全地将输入转换为 float，支持字符串中混杂符号。"""
    if value is None:
        return default

    if isinstance(value, bool):
        return default

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return default

    normalized = text.replace(",", "")
    number_text = _extract_first_number(normalized)
    if number_text is None:
        return default

    try:
        return float(number_text)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """安全地将输入转换为 int（向下截断浮点）。"""
    number = safe_float(value, default=float(default))
    try:
        return int(number)
    except (TypeError, ValueError, OverflowError):
        return default


def parse_money_to_yuan(value: Any, default: float = 0.0) -> float:
    """将金额解析为“元”。支持 ¥ / ￥ / 逗号 / 万 等混合格式。"""
    if value is None:
        return default

    if isinstance(value, bool):
        return default

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return default

    normalized = (
        text.replace("¥", "")
        .replace("￥", "")
        .replace("人民币", "")
        .replace("元", "")
        .replace(",", "")
        .strip()
    )

    unit_factor = 1.0
    if "亿" in normalized:
        unit_factor = 100_000_000.0
    elif "万" in normalized:
        unit_factor = 10_000.0

    number_text = _extract_first_number(normalized)
    if number_text is None:
        return default

    try:
        return float(number_text) * unit_factor
    except (TypeError, ValueError):
        return default


def parse_area_sqm(value: Any, default: float = 0.0) -> float:
    """将面积解析为平方米。支持 平方米 / 平米 / ㎡ / m² 等格式。"""
    if value is None:
        return default

    if isinstance(value, bool):
        return default

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return default

    normalized = (
        text.lower()
        .replace(",", "")
        .replace("平方米", "")
        .replace("平米", "")
        .replace("㎡", "")
        .replace("m²", "")
        .replace("m2", "")
        .strip()
    )

    number_text = _extract_first_number(normalized)
    if number_text is None:
        return default

    try:
        return float(number_text)
    except (TypeError, ValueError):
        return default
