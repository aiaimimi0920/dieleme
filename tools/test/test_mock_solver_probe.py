from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from tools import mock_solver_probe


class _FakeBrowser:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.launches: list[tuple[_FakeBrowser, bool, list[str]]] = []
        self.launch_errors: list[dict[str, object]] = []
        self.fail_times = fail_times

    def launch(self, *, headless: bool, args: list[str], executable_path: str | None = None) -> _FakeBrowser:
        if self.fail_times > 0:
            self.fail_times -= 1
            self.launch_errors.append(
                {
                    "headless": headless,
                    "args": list(args),
                    "executable_path": executable_path,
                }
            )
            raise RuntimeError("launch timeout")
        browser = _FakeBrowser(name=f"browser-{len(self.launches) + 1}")
        self.launches.append((browser, headless, list(args)))
        return browser


class _FakeSyncPlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self._playwright = types.SimpleNamespace(chromium=chromium)

    def __enter__(self) -> types.SimpleNamespace:
        return self._playwright

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _install_fake_sync_playwright(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_times: int = 0,
) -> _FakeChromium:
    chromium = _FakeChromium(fail_times=fail_times)
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: _FakeSyncPlaywright(chromium)
    playwright_pkg = types.ModuleType("playwright")
    playwright_pkg.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", playwright_pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    return chromium


def test_run_mock_solver_probe_series_launches_fresh_browser_per_run(monkeypatch: pytest.MonkeyPatch) -> None:
    chromium = _install_fake_sync_playwright(monkeypatch)
    browsers_seen: list[_FakeBrowser] = []

    def fake_run_probe_in_context(**kwargs: object) -> dict[str, object]:
        browser = kwargs["browser"]
        assert isinstance(browser, _FakeBrowser)
        browsers_seen.append(browser)
        return {
            "success": True,
            "reason": "OK",
            "scenario": kwargs["scenario"],
            "target_url": kwargs["target_url"],
            "port": kwargs["port"],
            "run_index": kwargs["run_index"],
        }

    monkeypatch.setattr(mock_solver_probe, "_run_probe_in_context", fake_run_probe_in_context)

    results = mock_solver_probe.run_mock_solver_probe_series(
        scenario="near_miss",
        port=9440,
        headless=True,
        runs=3,
    )

    assert [result["run_index"] for result in results] == [1, 2, 3]
    assert [result["port"] for result in results] == [9440, 9441, 9442]
    assert len(chromium.launches) == 3
    assert [browser for browser, _headless, _args in chromium.launches] == browsers_seen
    assert len({id(browser) for browser in browsers_seen}) == 3
    assert all(headless is True for _browser, headless, _args in chromium.launches)
    assert [args for _browser, _headless, args in chromium.launches] == [
        ["--remote-debugging-port=9440"],
        ["--remote-debugging-port=9441"],
        ["--remote-debugging-port=9442"],
    ]
    assert all(browser.closed for browser, _headless, _args in chromium.launches)


def test_run_mock_solver_probe_series_closes_browser_when_probe_run_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    chromium = _install_fake_sync_playwright(monkeypatch)

    def fake_run_probe_in_context(**kwargs: object) -> dict[str, object]:
        if kwargs["run_index"] == 2:
            raise RuntimeError("probe failed")
        return {
            "success": True,
            "reason": "OK",
            "scenario": kwargs["scenario"],
            "target_url": kwargs["target_url"],
            "port": kwargs["port"],
            "run_index": kwargs["run_index"],
        }

    monkeypatch.setattr(mock_solver_probe, "_run_probe_in_context", fake_run_probe_in_context)

    with pytest.raises(RuntimeError, match="probe failed"):
        mock_solver_probe.run_mock_solver_probe_series(
            scenario="default",
            port=9550,
            headless=False,
            runs=3,
        )

    assert len(chromium.launches) == 2
    assert all(browser.closed for browser, _headless, _args in chromium.launches)
    assert [headless for _browser, headless, _args in chromium.launches] == [False, False]
    assert [args for _browser, _headless, args in chromium.launches] == [
        ["--remote-debugging-port=9550"],
        ["--remote-debugging-port=9551"],
    ]


def test_launch_probe_browser_retries_after_transient_launch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    chromium = _install_fake_sync_playwright(monkeypatch, fail_times=1)
    sleeps: list[float] = []
    fake_playwright = types.SimpleNamespace(chromium=chromium)

    monkeypatch.setattr(mock_solver_probe, "FALLBACK_BROWSERS", ())
    monkeypatch.setattr(mock_solver_probe.time, "sleep", lambda seconds: sleeps.append(seconds))

    browser = mock_solver_probe._launch_probe_browser(
        fake_playwright,
        headless=True,
        port=9660,
    )

    assert isinstance(browser, _FakeBrowser)
    assert len(chromium.launch_errors) == 1
    assert sleeps == [0.1]
    assert [args for _browser, _headless, args in chromium.launches] == [
        ["--remote-debugging-port=9660"],
    ]


def test_launch_probe_browser_uses_fallback_executable_before_retrying(monkeypatch: pytest.MonkeyPatch) -> None:
    chromium = _install_fake_sync_playwright(monkeypatch, fail_times=1)
    fake_playwright = types.SimpleNamespace(chromium=chromium)
    fallback_path = Path(r"C:\fallback\chrome.exe")
    sleeps: list[float] = []

    monkeypatch.setattr(mock_solver_probe, "FALLBACK_BROWSERS", (fallback_path,))
    monkeypatch.setattr(Path, "exists", lambda self: str(self) == str(fallback_path))
    monkeypatch.setattr(mock_solver_probe.time, "sleep", lambda seconds: sleeps.append(seconds))

    browser = mock_solver_probe._launch_probe_browser(
        fake_playwright,
        headless=False,
        port=9770,
    )

    assert isinstance(browser, _FakeBrowser)
    assert sleeps == []
    assert len(chromium.launch_errors) == 1
    assert chromium.launch_errors[0]["executable_path"] is None
    assert [args for _browser, _headless, args in chromium.launches] == [
        ["--remote-debugging-port=9770"],
    ]


def test_run_mock_solver_probe_series_cleans_up_debug_browser_port_before_and_after_each_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chromium = _install_fake_sync_playwright(monkeypatch)
    cleanup_calls: list[int] = []

    monkeypatch.setattr(mock_solver_probe, "cleanup_debug_browser_processes", lambda port, **_kwargs: cleanup_calls.append(port))
    monkeypatch.setattr(
        mock_solver_probe,
        "_run_probe_in_context",
        lambda **kwargs: {
            "success": True,
            "reason": "OK",
            "scenario": kwargs["scenario"],
            "target_url": kwargs["target_url"],
            "port": kwargs["port"],
            "run_index": kwargs["run_index"],
        },
    )

    results = mock_solver_probe.run_mock_solver_probe_series(
        scenario="default",
        port=9880,
        headless=True,
        runs=2,
    )

    assert [result["port"] for result in results] == [9880, 9881]
    assert cleanup_calls == [9880, 9880, 9881, 9881]
    assert all(browser.closed for browser, _headless, _args in chromium.launches)


def test_launch_probe_browser_cleans_up_port_before_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    chromium = _install_fake_sync_playwright(monkeypatch, fail_times=1)
    fake_playwright = types.SimpleNamespace(chromium=chromium)
    cleanup_calls: list[int] = []
    sleeps: list[float] = []

    monkeypatch.setattr(mock_solver_probe, "FALLBACK_BROWSERS", ())
    monkeypatch.setattr(mock_solver_probe, "cleanup_debug_browser_processes", lambda port, **_kwargs: cleanup_calls.append(port))
    monkeypatch.setattr(mock_solver_probe.time, "sleep", lambda seconds: sleeps.append(seconds))

    browser = mock_solver_probe._launch_probe_browser(
        fake_playwright,
        headless=True,
        port=9660,
    )

    assert isinstance(browser, _FakeBrowser)
    assert cleanup_calls == [9660]
    assert sleeps == [0.1]
