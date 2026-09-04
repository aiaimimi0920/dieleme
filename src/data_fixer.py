from __future__ import annotations

import functools as _functools
from pathlib import Path as _Path
import sys as _sys
import types as _types

_REPO_ROOT = _Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

import src.data_fixer_context as _context
from src.data_fixer_app_part_01 import DataFixerAppPart01 as _Part01
from src.data_fixer_app_part_02 import DataFixerAppPart02 as _Part02
from src.data_fixer_app_part_03 import DataFixerAppPart03 as _Part03
from src.data_fixer_app_part_04 import DataFixerAppPart04 as _Part04
from src.data_fixer_app_part_05 import DataFixerAppPart05 as _Part05


def _clone_function(function: _types.FunctionType, *, qualname: str | None = None) -> _types.FunctionType:
    clone = _types.FunctionType(
        function.__code__, globals(), function.__name__, function.__defaults__, function.__closure__
    )
    _functools.update_wrapper(clone, function)
    clone.__kwdefaults__ = dict(function.__kwdefaults__ or {})
    clone.__module__ = __name__
    clone.__qualname__ = qualname or function.__name__
    return clone


for _name in _context.__all__:
    _value = getattr(_context, _name)
    globals()[_name] = (
        _clone_function(_value)
        if isinstance(_value, _types.FunctionType) and _value.__module__ == _context.__name__
        else _value
    )

_EXPECTED_METHOD_OVERRIDES = {
    "_update_ai_stats",
    "batch_approve",
    "log",
    "pause_scraping",
    "skip_selected",
    "toggle_select_all",
}
_observed_method_overrides: set[str] = set()
_app_attributes = {"__module__": __name__}
for _part in (_Part01, _Part02, _Part03, _Part04, _Part05,):
    for _name, _value in _part.__dict__.items():
        if isinstance(_value, _types.FunctionType):
            if _name in _app_attributes:
                _observed_method_overrides.add(_name)
            _app_attributes[_name] = _clone_function(_value, qualname=f"DataFixerApp.{_name}")
if _observed_method_overrides != _EXPECTED_METHOD_OVERRIDES:
    raise RuntimeError(
        "DataFixerApp legacy override inventory changed: "
        f"expected={sorted(_EXPECTED_METHOD_OVERRIDES)!r}, "
        f"observed={sorted(_observed_method_overrides)!r}"
    )
_app_attributes["save_area"] = _app_attributes["save_record"]
_app_attributes["open_url"] = _app_attributes["open_chrome"]
DataFixerApp = type("DataFixerApp", (), _app_attributes)

from src.data_fixer_runtime import main as _runtime_main
main = _clone_function(_runtime_main)


if __name__ == "__main__":
    main()
