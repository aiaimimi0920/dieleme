"""Compatibility facade for the responsibility-split implementation."""

from __future__ import annotations

import functools as _functools
import importlib as _importlib
from pathlib import Path
import sys
import types as _types

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_IMPLEMENTATION_MODULES = (
    "tools.area_followup_context",
    "tools.area_followup_io",
    "tools.area_followup_candidates",
    "tools.area_followup_artifacts",
    "tools.area_followup_persistence",
    "tools.area_followup_service",
    "tools.area_followup_cli",
)
_FACADE_CLASS_NAMES = {}


def _clone_function(function: _types.FunctionType) -> _types.FunctionType:
    clone = _types.FunctionType(
        function.__code__, globals(), function.__name__, function.__defaults__, function.__closure__
    )
    _functools.update_wrapper(clone, function)
    clone.__kwdefaults__ = dict(function.__kwdefaults__ or {})
    clone.__module__ = __name__
    clone.__qualname__ = function.__name__
    return clone


_loaded_modules = [_importlib.import_module(name) for name in _IMPLEMENTATION_MODULES]
_function_pairs: list[tuple[_types.FunctionType, _types.FunctionType]] = []
for _module in _loaded_modules:
    for _name in _module.__all__:
        _value = getattr(_module, _name)
        if isinstance(_value, _types.FunctionType) and _value.__module__ == _module.__name__:
            _clone = _clone_function(_value)
            globals()[_name] = _clone
            _function_pairs.append((_value, _clone))
        else:
            if _name in _FACADE_CLASS_NAMES and isinstance(_value, type):
                _value.__module__ = __name__
            globals()[_name] = _value

_function_map = {id(original): clone for original, clone in _function_pairs}
for _original, _clone in _function_pairs:
    if _original.__defaults__:
        _clone.__defaults__ = tuple(_function_map.get(id(value), value) for value in _original.__defaults__)
    if _original.__kwdefaults__:
        _clone.__kwdefaults__ = {
            key: _function_map.get(id(value), value)
            for key, value in _original.__kwdefaults__.items()
        }


if __name__ == "__main__":
    raise SystemExit(main())
