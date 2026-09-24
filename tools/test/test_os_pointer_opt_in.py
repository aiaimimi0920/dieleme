"""Pointer policy checks do not access a mouse, browser, or OS input API."""
import pytest

from src.captcha_os_windows import CaptchaOSWindowsMixin


class PointerPolicy(CaptchaOSWindowsMixin):
    def _is_local_mock_slider_target(self):
        return self.mock_target


@pytest.mark.parametrize("setting,expected", [(None, False), ("", False), ("0", False),
                                             ("true", True), ("1", True), ("unknown", False)])
def test_os_pointer_requires_explicit_opt_in(monkeypatch, setting, expected):
    if setting is None:
        monkeypatch.delenv("FAPAI_SOLVER_OS_MOUSE", raising=False)
    else:
        monkeypatch.setenv("FAPAI_SOLVER_OS_MOUSE", setting)
    pointer = PointerPolicy()
    pointer.mock_target = False
    # A pytest marker has no effect on production policy.
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "synthetic")
    assert pointer._os_mouse_enabled() is expected
    pointer.mock_target = True
    assert pointer._os_mouse_enabled() is False
