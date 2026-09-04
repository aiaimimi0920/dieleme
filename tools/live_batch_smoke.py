from __future__ import annotations

import functools as _functools
import importlib as _importlib
from pathlib import Path as _Path
import sys as _sys
import types as _types

_REPO_ROOT = _Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

_IMPLEMENTATION_MODULES = (
    'tools.live_smoke_context',
    'tools.live_smoke_resume',
    'tools.live_smoke_list',
    'tools.live_smoke_area',
    'tools.live_smoke_auth',
    'tools.live_smoke_cdp',
    'tools.live_smoke_browser',
    'tools.live_smoke_summary',
    'tools.live_smoke_analysis_config',
    'tools.live_smoke_analysis',
    'tools.live_smoke_runtime',
    'tools.live_smoke_cli',
)
_DIRECT_FUNCTION_ALIASES = set()


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


_loaded_modules = [_importlib.import_module(name) for name in _IMPLEMENTATION_MODULES]
_function_pairs: list[tuple[_types.FunctionType, _types.FunctionType]] = []
for _module in _loaded_modules:
    for _name in _module.__all__:
        _value = getattr(_module, _name)
        if (
            isinstance(_value, _types.FunctionType)
            and _value.__module__ == _module.__name__
            and _name not in _DIRECT_FUNCTION_ALIASES
        ):
            _clone = _clone_function(_value)
            globals()[_name] = _clone
            _function_pairs.append((_value, _clone))
        else:
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
