from __future__ import annotations

import importlib


def test_solver_wire_import_is_side_effect_free_and_refuses_response_rewriting(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    def fail_if_called(*args: object, **kwargs: object) -> None:
        calls.append((*args, kwargs))
        raise AssertionError("deprecated solver must not install packages or launch a browser")

    monkeypatch.setattr("subprocess.check_call", fail_if_called)
    module = importlib.import_module("tools.solver_wire")

    assert calls == []
    try:
        module.solve_with_wire("https://example.invalid/captcha")
    except RuntimeError as exc:
        assert "retired" in str(exc)
        assert "must not be rewritten" in str(exc)
    else:  # pragma: no cover - assertion keeps the contract explicit
        raise AssertionError("deprecated solver unexpectedly returned success")
