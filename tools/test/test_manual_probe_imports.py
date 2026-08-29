from __future__ import annotations

import importlib


def test_manual_captcha_tools_are_import_safe(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("import slept")))
    importlib.import_module("tools.manual_drag_test")
    importlib.import_module("tools.nc_captcha_probe")
