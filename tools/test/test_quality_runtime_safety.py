from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from tools import internal_api_http, pc2_collection_controller
from tools.browserless_seed_probe import write_cookie_snapshot
from tools.pc2_collection_controller import RestartController
from tools.pc2_settings_controller import SettingsController


pytestmark = pytest.mark.security


@pytest.mark.parametrize("controller_type", [RestartController, SettingsController])
@pytest.mark.parametrize("status", [409, 401, 403, 429, 503])
def test_receipt_rejection_never_replays_operation(tmp_path, controller_type, status):
    calls = []

    def post(action, body):
        calls.append(action)
        if action == "result":
            raise HTTPError("https://example.invalid", status, "rejected", {}, None)
        return {}

    runtime = SimpleNamespace(root=tmp_path, inspect=lambda: None, snapshot=lambda: {})
    client = SimpleNamespace(post=post)
    controller = (controller_type(client, runtime, tmp_path) if controller_type is RestartController
                  else controller_type(client, runtime))
    raw = '{"request_id":"test","claim":"old","result":"interrupted"}'
    controller.journal.write_text(raw, encoding="utf-8")
    if status == 409:
        controller.step()
        assert not controller.journal.exists()
        assert [path.read_text(encoding="utf-8") for path in (tmp_path / "receipts").glob("*.json")] == [raw]
        controller.step()
        assert calls == ["result", "poll"]
    else:
        with pytest.raises(HTTPError):
            controller.step()
        assert controller.journal.read_text(encoding="utf-8") == raw
        assert calls == ["result"]


def test_watchdog_restart_ends_tick_before_settings_or_manual_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(pc2_collection_controller, "operation_lock", lambda _: nullcontext())
    settings = SimpleNamespace(journal=tmp_path / "settings.json")
    restart = SimpleNamespace(journal=tmp_path / "restart.json")
    watchdog = SimpleNamespace(step=lambda: "restart_requested")
    pc2_collection_controller.step(tmp_path, settings, restart, watchdog)


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_internal_redirect_never_forwards_token(method):
    visited = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            visited.append(self.path)
            if self.path == "/start":
                self.send_response(307)
                self.send_header("Location", "/target")
            else:
                self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        do_POST = do_GET

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/start"
            headers = {"X-Fapai-Recovery-Token": "synthetic-test-token"}
            with pytest.raises(OSError, match="redirects"):
                if method == "GET":
                    internal_api_http.fetch_json(url, timeout=2, headers=headers)
                else:
                    internal_api_http.post_json(url, {}, timeout=2, headers=headers)
            assert visited == ["/start"]
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_cookie_snapshot_failure_preserves_existing_bytes(tmp_path, monkeypatch):
    target = tmp_path / "cookies.json"
    original = b'[{"name":"old","value":"test"}]'
    target.write_bytes(original)

    def failed_replace(source, destination):
        assert target.read_bytes() == original
        with open(source, encoding="utf-8") as stream:
            assert json.load(stream) == [{"name": "new"}]
        raise OSError("synthetic rename failure")

    monkeypatch.setattr(os, "replace", failed_replace)
    with pytest.raises(OSError, match="synthetic"):
        write_cookie_snapshot([{"name": "new"}], target)
    assert target.read_bytes() == original
    assert list(tmp_path.iterdir()) == [target]


def test_cookie_snapshot_is_complete_and_private(tmp_path):
    target = tmp_path / "cookies.json"
    write_cookie_snapshot([{"name": "new"}], target)
    assert json.loads(target.read_text(encoding="utf-8")) == [{"name": "new"}]
    if os.name == "posix":
        assert target.stat().st_mode & 0o777 == 0o600
