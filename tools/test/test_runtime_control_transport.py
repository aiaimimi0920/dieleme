"""Synthetic TLS gateway to a loopback runtime; never contacts installed Crow."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from src.collection_engine_restart import RestartError
from tools.collection_control_https import dispatch
from tools.collection_runtime_proxy import runtime_origin
from tools.desktop_settings_client import execute
from tools.test.test_collection_control_https import control
from tools.test.test_desktop_restart_transport import transport


@pytest.mark.parametrize("action,body,path", [
    ("start", {}, "/api/collection/control/start"),
    ("pause", {}, "/api/collection/control/pause"),
    ("resume", {}, "/api/collection/control/resume"),
    ("manual_update", {"item_id": "fixture", "updates": {"phone": "00123"}}, "/api/collection/item/manual_update"),
    ("reanalyze", {"item_id": "fixture", "reason": "operator_requested"}, "/api/collection/item/reanalyze"),
    ("reset_links", {"location_code": "330100"}, "/api/collection/region/reset_links"),
])
def test_native_transport_uses_only_fixed_authenticated_routes(transport, action, body, path):
    root, requests = transport
    origin = "https://nas.example.invalid:18443"
    assert execute({"action": action, "origin": origin, "body": body}, root)["ok"]
    assert requests[0].full_url == origin + path
    assert requests[0].method == "POST"
    assert json.loads(requests[0].data) == body
    assert requests[0].get_header("X-fapai-control-token")
    with pytest.raises(ValueError):
        execute({"action": action, "origin": origin, "body": {**body, "url": "http://untrusted.invalid"}}, root)
    assert len(requests) == 1


@pytest.mark.parametrize("value", [
    "", "http://nas.example.invalid:8001", "http://192.0.2.1:8001",
    "http://127.0.0.1", "http://127.0.0.1:8001/other", "http://user@127.0.0.1:8001",
    "http://127.0.0.1:8001?url=other", "http://127.0.0.1:8001#other",
])
def test_proxy_rejects_nonlocal_or_ambiguous_configuration(monkeypatch, value):
    monkeypatch.setenv("FAPAI_CONTROL_LOCAL_API_BASE", value)
    with pytest.raises(RestartError) as error:
        runtime_origin()
    assert error.value.status == 503


def test_tls_runtime_roundtrip_role_boundary_and_redirect_denial(control, monkeypatch):
    origin, _, tokens, root = control
    received = []
    redirect = False

    class Runtime(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            received.append((self.path, self.headers.get("X-FAPAI-Control-Token"),
                             self.rfile.read(int(self.headers["Content-Length"]))))
            raw = json.dumps({"ok": True, "action": self.path.rsplit("/", 1)[-1]}).encode()
            self.send_response(302 if redirect else 200)
            self.send_header("Content-Length", str(len(raw)))
            if redirect:
                self.send_header("Location", origin + "/untrusted")
            self.end_headers()
            self.wfile.write(raw)

    runtime = ThreadingHTTPServer(("127.0.0.1", 0), Runtime)
    thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("FAPAI_CONTROL_LOCAL_API_BASE", f"http://127.0.0.1:{runtime.server_port}")
    try:
        cases = [
            ("start", {}), ("pause", {}), ("resume", {}),
            ("manual_update", {"item_id": "fixture", "updates": {"phone": "00123"}}),
            ("reanalyze", {"item_id": "fixture"}), ("reset_links", {"location_code": "330100"}),
        ]
        for action, body in cases:
            assert execute({"action": action, "origin": origin, "body": body}, root) == {"ok": True, "action": action}
        assert len(received) == len(cases)
        assert all(token == "o" * 48 for _, token, _ in received)
        assert [json.loads(body) for _, _, body in received] == [body for _, body in cases]
        for headers in ({}, {"X-FAPAI-Control-Token": tokens["agent"].read_text()}):
            with pytest.raises(RestartError) as error:
                dispatch(root, "POST", "/api/collection/control/pause", headers, {})
            assert error.value.status == 403
        assert len(received) == len(cases)
        operator = {"X-FAPAI-Control-Token": "o" * 48}
        with pytest.raises(RestartError):
            dispatch(root, "GET", "/api/collection/control/resume", operator, {})
        assert len(received) == len(cases)
        redirect = True
        result = execute({"action": "pause", "origin": origin, "body": {}}, root)
        assert result == {"ok": False, "error": "control_http_error", "status": 502}
        assert len(received) == len(cases) + 1
    finally:
        runtime.shutdown()
        runtime.server_close()
        thread.join(timeout=5)
