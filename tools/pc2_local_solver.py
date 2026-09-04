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
    'tools.pc2_solver_context',
    'tools.pc2_solver_transport',
    'tools.pc2_solver_scope',
    'tools.pc2_solver_auth',
    'tools.pc2_solver_fallback',
    'tools.pc2_solver_auth_pending',
    'tools.pc2_solver_cdp',
    'tools.pc2_solver_execution',
    'tools.pc2_solver_loop_control',
    'tools.pc2_solver_loop',
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
    import argparse
    parser = argparse.ArgumentParser(description="PC2 local captcha solver daemon")
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--cdp-endpoint", default=DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--node-id", default=None)
    args = parser.parse_args()
    local_solver_loop(
        api_base_url=str(args.api_base_url),
        cdp_endpoint=str(args.cdp_endpoint),
        poll_seconds=int(args.poll_seconds),
        max_attempts=int(args.max_attempts),
        expected_node_id=str(args.node_id).strip() if args.node_id else None,
    )
