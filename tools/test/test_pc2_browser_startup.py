from __future__ import annotations

import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.request

import pytest


class NavigationTimeout(TimeoutError):
    pass


def run_initial_navigation(monkeypatch, responses):
    script = (Path(__file__).resolve().parents[2] / "ops/pc2-linux/start-browser-solver.sh").read_text(encoding="utf-8")
    source = script.split('python - "$start_url" <<\'PY\'\n', 1)[1].split("\nPY\n", 1)[0]
    target = {"type": "page", "url": "about:blank", "webSocketDebuggerUrl": "ws://127.0.0.1/mock"}

    class Connection:
        sent = []
        closed = False

        def send(self, message):
            self.sent.append(json.loads(message))

        def recv(self):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return json.dumps(response)

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(json.dumps([target]).encode()))
    monkeypatch.setattr(sys, "argv", ["startup", "https://example.invalid/"])
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(
        create_connection=lambda *_args, **_kwargs: connection,
        WebSocketTimeoutException=NavigationTimeout,
    ))
    return source, connection


def test_initial_navigation_timeout_keeps_browser_under_supervision(monkeypatch, capsys):
    source, connection = run_initial_navigation(monkeypatch, [NavigationTimeout("slow upstream")])

    exec(compile(source, "initial-navigation", "exec"), {})

    assert connection.closed
    assert len(connection.sent) == 1
    assert connection.sent[0]["method"] == "Page.navigate"
    assert "initial_navigation_pending" in capsys.readouterr().out


def test_initial_navigation_command_error_still_fails_startup(monkeypatch):
    source, connection = run_initial_navigation(monkeypatch, [{"id": 1, "error": {"code": -32602}}])

    with pytest.raises(SystemExit, match="initial navigation failed"):
        exec(compile(source, "initial-navigation", "exec"), {})

    assert connection.closed


def test_initial_navigation_ignores_unrelated_cdp_events(monkeypatch):
    source, connection = run_initial_navigation(monkeypatch, [
        {"method": "Page.frameStartedLoading"}, {"id": 1, "result": {"frameId": "mock-frame"}},
    ])

    exec(compile(source, "initial-navigation", "exec"), {})

    assert connection.closed
    assert len(connection.sent) == 1
