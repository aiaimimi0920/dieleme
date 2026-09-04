#!/usr/bin/env python3
"""Compatibility facade for blocker-aware analysis-stage planning."""

from __future__ import annotations

import functools as _functools
import importlib as _importlib
import json
from pathlib import Path
import types as _types
from typing import Any

from tools.manual_review_receipt_store import list_manual_review_receipts


_IMPLEMENTATION_MODULES = (
    "tools.analysis_stage_policy",
    "tools.analysis_stage_actions",
    "tools.analysis_stage_snapshots",
    "tools.analysis_stage_receipts",
    "tools.analysis_stage_backlog",
    "tools.analysis_stage_operator",
)


def _clone_function(function: _types.FunctionType) -> _types.FunctionType:
    clone = _types.FunctionType(
        function.__code__,
        globals(),
        function.__name__,
        function.__defaults__,
        function.__closure__,
    )
    _functools.update_wrapper(clone, function)
    clone.__kwdefaults__ = dict(function.__kwdefaults__ or {})
    clone.__module__ = __name__
    clone.__qualname__ = function.__name__
    return clone


for _module_name in _IMPLEMENTATION_MODULES:
    _module = _importlib.import_module(_module_name)
    for _name in _module.__all__:
        _value = getattr(_module, _name)
        globals()[_name] = (
            _clone_function(_value)
            if isinstance(_value, _types.FunctionType)
            and _value.__module__ == _module.__name__
            else _value
        )
