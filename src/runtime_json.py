"""Bounded JSON readers for untrusted or restartable runtime files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_JSON_NESTING = 256


def exceeds_json_nesting(text: str, limit: int = MAX_JSON_NESTING) -> bool:
    """Detect structural nesting before the decoder can exhaust the C stack."""
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in '[{':
            depth += 1
            if depth > limit:
                return True
        elif character in ']}':
            depth = max(depth - 1, 0)
    return False


def loads_bounded_json(text: str) -> Any:
    """Decode JSON while rejecting hostile nesting and decoder recursion."""
    if exceeds_json_nesting(text):
        raise ValueError("JSON nesting exceeds runtime limit")
    try:
        return json.loads(text)
    except RecursionError as error:
        raise ValueError("JSON nesting exceeds runtime limit") from error


def load_json_file(path: str | Path) -> Any:
    """Read UTF-8 JSON through :func:`loads_bounded_json`."""
    return loads_bounded_json(Path(path).read_text(encoding="utf-8"))
