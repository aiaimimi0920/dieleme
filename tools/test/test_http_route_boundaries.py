"""Routing must preserve query parameters without accepting arbitrary suffixes."""
import json
from types import SimpleNamespace

import pytest

from src import server
from src.server_routes import build_routes
from tools.test.test_quality_http_guards import api


@pytest.mark.parametrize("path,branch", [
    ("/api/get_item", "_get_item"),
    ("/api/collection/items", "_get_collection_items"),
    ("/api/avm/predict", "_get_analysis_prediction"),
])
def test_get_query_reaches_exact_route(api, monkeypatch, path, branch):
    monkeypatch.setattr(server.DataHandler, branch, lambda handler, _parsed, _path, query: handler.send_json(query))
    status, _headers, raw = api("GET", path + "?item_id=kept")
    assert status == 200
    assert json.loads(raw) == {"item_id": ["kept"]}


@pytest.mark.parametrize("path", [
    "/api/avm/predict_extra", "/api/analysis/health_extra",
    "/api/get_item_extra", "/api/collection/seeds/next_task_extra",
])
def test_get_unknown_suffix_is_not_a_route(api, path):
    assert api("GET", path)[0] == 404


def test_upload_unknown_suffix_is_not_a_write_route(api, tmp_path):
    assert api("POST", "/api/upload_extra?id=record&name=detail.html", b"evidence")[0] == 404
    assert not (tmp_path / "downloads").exists()


@pytest.mark.security
@pytest.mark.parametrize("headers,status", [({}, 403), ({"X-FAPAI-Control-Token": "wrong"}, 403)])
def test_control_start_requires_authorization_before_mutation(api, monkeypatch, headers, status):
    monkeypatch.setattr(server, "_collection_operator_start", lambda: pytest.fail("unauthorized start"))
    assert api("POST", "/api/collection/control/start", b"{}", headers)[0] == status


def test_authorized_control_start_still_works(api, monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_collection_operator_start", lambda: (calls.append(True) or {"ok": True}))
    status, _headers, raw = api("POST", "/api/collection/control/start", b"{}", {"X-FAPAI-Control-Token": "test-operator"})
    assert status == 200 and json.loads(raw) == {"ok": True}
    assert calls == [True]


def test_all_post_routes_keep_query_and_reject_suffix(api, monkeypatch):
    def respond(handler):
        handler.rfile.read(int(handler.headers.get("Content-Length", "0")))
        handler.send_json({"path": handler.path})

    for (method, path), handler_name in server.ROUTES.items():
        if method != "POST":
            continue
        with monkeypatch.context() as scoped:
            # Authentication is covered against every real route in test_http_write_access.
            scoped.setattr(server.DataHandler, "_authorize_write", lambda *_: True)
            scoped.setattr(server.DataHandler, handler_name, respond)
            target = path + "?trace=kept"
            status, _headers, raw = api("POST", target, b"{}")
            assert status == 200, target
            assert json.loads(raw) == {"path": target}
            assert api("POST", path + "_extra?trace=kept", b"{}")[0] == 404


def test_duplicate_route_registration_fails_instead_of_shadowing():
    with pytest.raises(ValueError, match="Duplicate route"):
        build_routes({"one": ("/same",), "two": ("/same",)}, {})


def test_query_cannot_turn_pause_into_resume(api, monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_collection_observer_runtime_control_payload",
                        lambda action: (calls.append(action) or {"ok": True}))
    status, _, _ = api("POST", "/api/collection/control/pause?trace=kept", b"{}",
                       {"X-FAPAI-Control-Token": "test-operator"})
    assert status == 200
    assert calls == ["pause"]


def test_recovery_claim_with_query_does_not_dispatch_result(api, monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_nas_auth_recovery_authorized", lambda _headers: (True, None))
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", SimpleNamespace(
        claim=lambda *args: (calls.append(args) or {"ok": True})))
    monkeypatch.setattr(server, "_nas_auth_recovery_result", lambda _: pytest.fail("wrong transition"))
    payload = json.dumps({"recovery_id": "test", "role": "pc2", "node_id": "pc2"}).encode()
    assert api("POST", "/api/collection/auth/recovery/claim?trace=kept", payload)[0] == 200
    assert calls == [("pc2", "test", "pc2")]


def test_auth_recovery_get_is_read_only(monkeypatch):
    calls = []
    manager = SimpleNamespace(
        register_stage_auth_pc2=lambda: calls.append("mutated"),
        snapshot=lambda: {"active": None},
    )
    handler = SimpleNamespace(
        headers={},
        send_json=lambda payload: calls.append(payload),
        send_error_json=lambda **kwargs: pytest.fail(f"unexpected error: {kwargs}"),
    )
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", manager)
    monkeypatch.setattr(server, "_nas_auth_recovery_authorized", lambda _headers: (True, None))

    server._get_auth_recovery(handler, None, "/api/collection/auth/recovery", {
        "protocol_version": ["2"], "node_id": ["pc2"]
    })

    assert calls == [{"ok": True, "auth_recovery": {"active": None}}]


@pytest.mark.security
def test_delete_checks_auth_before_parsing_body_even_with_query(api, monkeypatch):
    monkeypatch.setattr(server, "delete_manual_review_receipt", lambda *_a, **_k: pytest.fail("unauthorized delete"))
    endpoint = next(iter(server.MANUAL_REVIEW_RECEIPT_ENDPOINTS))
    assert api("DELETE", endpoint + "?trace=kept", b"not-json")[0] == 403
