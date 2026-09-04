"""Compatibility facade for the split taobao_sf_locations tool."""

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
    'tools.taobao_sf_locations_context',
    'tools.taobao_sf_locations_normalization',
    'tools.taobao_sf_locations_extraction',
    'tools.taobao_sf_locations_reconcile',
    'tools.taobao_sf_locations_persistence',
    'tools.taobao_sf_locations_crawler',
    'tools.taobao_sf_locations_cli',
)
_FACADE_CLASS_NAMES = {'AdminLocationIndex', 'LocationFilterOptions', 'LocationOption', 'TaobaoLocationEntry'}
_CLONED_CLASS_NAMES = {'AdminLocationIndex'}


def _clone_function(function: _types.FunctionType, *, qualname: str | None = None) -> _types.FunctionType:
    clone = _types.FunctionType(
        function.__code__, globals(), function.__name__, function.__defaults__, function.__closure__
    )
    _functools.update_wrapper(clone, function)
    clone.__kwdefaults__ = dict(function.__kwdefaults__ or {})
    clone.__module__ = __name__
    clone.__qualname__ = qualname or function.__name__
    return clone


def _clone_class(class_value: type) -> type:
    attributes = {}
    for name, value in class_value.__dict__.items():
        if name in {"__dict__", "__weakref__", "__module__", "__qualname__"}:
            continue
        attributes[name] = (
            _clone_function(value, qualname=f"{class_value.__name__}.{name}")
            if isinstance(value, _types.FunctionType)
            else value
        )
    attributes["__module__"] = __name__
    attributes["__qualname__"] = class_value.__name__
    return type(class_value.__name__, class_value.__bases__, attributes)


_loaded_modules = [_importlib.import_module(name) for name in _IMPLEMENTATION_MODULES]
_function_pairs: list[tuple[_types.FunctionType, _types.FunctionType]] = []
for _module in _loaded_modules:
    for _name in _module.__all__:
        _value = getattr(_module, _name)
        if isinstance(_value, _types.FunctionType) and _value.__module__ == _module.__name__:
            _clone = _clone_function(_value)
            globals()[_name] = _clone
            _function_pairs.append((_value, _clone))
        elif _name in _CLONED_CLASS_NAMES and isinstance(_value, type):
            globals()[_name] = _clone_class(_value)
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
