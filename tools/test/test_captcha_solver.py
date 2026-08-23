from __future__ import annotations

import ctypes
import json
import sys

from src import captcha_solver


def test_bring_to_front_skips_slow_websocket_focus_after_exact_activation(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(cdp_endpoint="http://127.0.0.1:9223")
    solver.target_id = "challenge-target"
    calls: list[tuple[str, object]] = []

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(
        captcha_solver.requests,
        "get",
        lambda url, timeout: calls.append(("http", (url, timeout))) or FakeResponse(),
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda method, params=None: calls.append(("cdp", method)) or None,
    )
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))

    assert solver._bring_to_front() is True
    assert calls[0] == (
        "http",
        ("http://127.0.0.1:9223/json/activate/challenge-target", 2),
    )
    assert calls[1:] == [("sleep", 0.15)]


def test_bring_to_front_falls_back_to_websocket_focus_when_http_activation_fails(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(cdp_endpoint="http://127.0.0.1:9223")
    solver.target_id = "challenge-target"
    calls: list[str] = []

    class FakeResponse:
        status_code = 500

    monkeypatch.setattr(captcha_solver.requests, "get", lambda *_args, **_kwargs: FakeResponse())
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda method, params=None: calls.append(method) or {"ok": True},
    )
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver._bring_to_front() is True
    assert calls == ["Page.bringToFront", "Runtime.evaluate"]


def test_find_slider_stops_immediately_when_cancel_requested(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.cancel_checker = lambda: True
    cdp_calls: list[tuple[str, dict[str, object]]] = []
    sleeps: list[float] = []

    def fake_send_cdp(method: str, params: dict[str, object]) -> dict[str, object]:
        cdp_calls.append((method, params))
        return {}

    monkeypatch.setattr(solver, "_send_cdp", fake_send_cdp)
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert solver._find_slider() is None
    assert solver.last_failure_reason == "cancelled"
    assert cdp_calls == []
    assert sleeps == []


def test_connect_tab_prioritizes_request_target_url(monkeypatch) -> None:
    sent_methods: list[str] = []
    connected_urls: list[str] = []

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            message = json.loads(payload)
            self.last_message_id = int(message["id"])
            sent_methods.append(str(message["method"]))

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
    solver._get_json = lambda _endpoint: [
        {
            "url": "https://other.local/challenge?__captcha_solver_bg=1",
            "title": "other solver page",
            "webSocketDebuggerUrl": "ws://other",
        },
        {
            "url": target_url,
            "title": "target solver page",
            "webSocketDebuggerUrl": "ws://target",
        },
    ]

    monkeypatch.setattr(
        captcha_solver.websocket,
        "create_connection",
        lambda ws_url, **_kwargs: connected_urls.append(ws_url) or FakeWebSocket(),
    )

    assert solver.connect_tab() is True
    assert connected_urls == ["ws://target"]
    assert sent_methods[:3] == ["DOM.enable", "Runtime.enable", "Page.enable"]


def test_connect_tab_matches_requested_target_url_after_query_normalization(monkeypatch) -> None:
    connected_urls: list[str] = []

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

    target_url = "file:///tmp/mock_slider.html?b=2&a=1&verifyMode=near_miss"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
    solver._get_json = lambda _endpoint: [
        {
            "url": "file:///tmp/mock_slider.html?verifyMode=near_miss&a=1&b=2",
            "title": "target solver page",
            "webSocketDebuggerUrl": "ws://target",
        },
    ]

    monkeypatch.setattr(
        captcha_solver.websocket,
        "create_connection",
        lambda ws_url, **_kwargs: connected_urls.append(ws_url) or FakeWebSocket(),
    )

    assert solver.connect_tab() is True
    assert connected_urls == ["ws://target"]


def test_get_json_uses_configured_cdp_endpoint(monkeypatch) -> None:
    requested_urls: list[str] = []

    class FakeResponse:
        def json(self) -> list[dict[str, str]]:
            return [{"type": "page"}]

    def fake_get(url: str, timeout: int) -> FakeResponse:
        requested_urls.append(url)
        assert timeout == 2
        return FakeResponse()

    monkeypatch.setattr(captcha_solver.requests, "get", fake_get)

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    assert solver._get_json("list") == [{"type": "page"}]
    assert requested_urls == ["http://host.docker.internal:9223/json/list"]


def test_constructor_prefers_env_cdp_endpoint_over_legacy_default_port(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://192.168.65.254:9223")

    solver = captcha_solver.CaptchaSolver(port=9222)

    assert solver.port == 9223
    assert solver.cdp_endpoint == "http://192.168.65.254:9223"


def test_connect_tab_rewrites_loopback_websocket_to_configured_cdp_endpoint(monkeypatch) -> None:
    connected_urls: list[str] = []

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://host.docker.internal:9223",
    )
    solver._get_json = lambda _endpoint: [
        {
            "url": target_url,
            "title": "target solver page",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/abc",
        },
    ]

    monkeypatch.setattr(
        captcha_solver.websocket,
        "create_connection",
        lambda ws_url, **_kwargs: connected_urls.append(ws_url) or FakeWebSocket(),
    )

    assert solver.connect_tab() is True
    assert connected_urls == ["ws://host.docker.internal:9223/devtools/page/abc"]


def test_connect_tab_opens_requested_target_when_missing(monkeypatch) -> None:
    requested: list[tuple[str, str, int]] = []
    connected_urls: list[str] = []
    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"

    class FakeResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def json(self) -> object:
            return self._payload

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

    def fake_get(url: str, timeout: int):
        requested.append(("GET", url, timeout))
        if url.endswith("/json/list"):
            return FakeResponse(
                [
                    {
                        "url": "https://sf.taobao.com/",
                        "title": "home",
                        "webSocketDebuggerUrl": "ws://home",
                    }
                ]
            )
        raise AssertionError(f"unexpected GET {url}")

    def fake_put(url: str, timeout: int):
        requested.append(("PUT", url, timeout))
        return FakeResponse(
            {
                "url": target_url,
                "title": "target solver page",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/new-target",
            }
        )

    monkeypatch.setattr(captcha_solver.requests, "get", fake_get)
    monkeypatch.setattr(captcha_solver.requests, "put", fake_put)
    monkeypatch.setattr(
        captcha_solver.websocket,
        "create_connection",
        lambda ws_url, **_kwargs: connected_urls.append(ws_url) or FakeWebSocket(),
    )

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    assert solver.connect_tab() is True
    assert (
        "PUT",
        "http://host.docker.internal:9223/json/new?https://contest.local/challenge%3F__captcha_solver_bg%3D1",
        5,
    ) in requested
    assert connected_urls == ["ws://host.docker.internal:9223/devtools/page/new-target"]


def test_open_target_tab_encodes_nested_query_delimiters(monkeypatch) -> None:
    requested_urls: list[str] = []
    target_url = (
        "file:///tmp/mock_slider.html"
        "?target=local_mock_slider_wide_delay"
        "&trackWidth=520"
        "&handleWidth=34"
        "&handleHeight=34"
        "&successDelayMs=900"
        "&verifyMode=strict_success_text"
    )

    class FakeResponse:
        def json(self) -> dict[str, str]:
            return {"id": "target-1", "url": target_url, "webSocketDebuggerUrl": "ws://target-1"}

    monkeypatch.setattr(
        captcha_solver.requests,
        "put",
        lambda url, timeout: requested_urls.append(url) or FakeResponse(),
    )

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    payload = solver._open_target_tab()

    assert payload == {"id": "target-1", "url": target_url, "webSocketDebuggerUrl": "ws://target-1"}
    assert requested_urls == [
        "http://host.docker.internal:9223/json/new?"
        "file:///tmp/mock_slider.html%3FhandleHeight%3D34%26handleWidth%3D34%26successDelayMs%3D900"
        "%26target%3Dlocal_mock_slider_wide_delay%26trackWidth%3D520%26verifyMode%3Dstrict_success_text"
    ]


def test_compact_cdp_pages_keeps_browser_alive_at_threshold(monkeypatch) -> None:
    requested: list[tuple[str, str, int]] = []
    closed_ws = {"count": 0}

    class FakeResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def json(self) -> object:
            return self._payload

    class FakeWebSocket:
        def close(self) -> None:
            closed_ws["count"] += 1

    page_targets = [
        {"id": f"page-{index}", "type": "page", "url": f"https://sf.taobao.com/list/{index}"}
        for index in range(12)
    ]
    other_targets = [
        {"id": "worker-1", "type": "service_worker", "url": "chrome-extension://worker"},
        {"id": "iframe-1", "type": "iframe", "url": "https://example.local/frame"},
    ]

    def fake_get(url: str, timeout: int):
        requested.append(("GET", url, timeout))
        if url.endswith("/json/list"):
            return FakeResponse(page_targets + other_targets)
        if "/json/close/" in url:
            return FakeResponse({})
        raise AssertionError(f"unexpected GET {url}")

    def fake_put(url: str, timeout: int):
        requested.append(("PUT", url, timeout))
        if url.endswith("/json/new?about:blank"):
            return FakeResponse({"id": "keepalive-page"})
        raise AssertionError(f"unexpected PUT {url}")

    monkeypatch.setattr(captcha_solver.requests, "get", fake_get)
    monkeypatch.setattr(captcha_solver.requests, "put", fake_put)

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://contest.local/challenge?__captcha_solver_bg=1",
        cdp_endpoint="http://host.docker.internal:9223",
    )
    solver.ws = FakeWebSocket()
    solver.target_id = "page-3"
    solver.target_ws_url = "ws://cached-target"

    summary = solver._compact_cdp_pages_if_needed()

    assert summary == {
        "triggered": True,
        "page_count": 12,
        "closed": 12,
        "keepalive_target_id": "keepalive-page",
    }
    assert closed_ws["count"] == 1
    assert solver.ws is None
    assert solver.target_id is None
    assert solver.target_ws_url is None
    assert ("PUT", "http://host.docker.internal:9223/json/new?about:blank", 5) in requested
    close_urls = [url for method, url, _timeout in requested if method == "GET" and "/json/close/" in url]
    assert close_urls == [
        f"http://host.docker.internal:9223/json/close/page-{index}" for index in range(12)
    ]
    assert "http://host.docker.internal:9223/json/close/worker-1" not in close_urls
    assert "http://host.docker.internal:9223/json/close/iframe-1" not in close_urls


def test_compact_cdp_pages_does_not_close_below_threshold(monkeypatch) -> None:
    requested: list[tuple[str, str, int]] = []

    class FakeResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def json(self) -> object:
            return self._payload

    def fake_get(url: str, timeout: int):
        requested.append(("GET", url, timeout))
        if url.endswith("/json/list"):
            return FakeResponse(
                [{"id": f"page-{index}", "type": "page"} for index in range(11)]
                + [{"id": "worker-1", "type": "service_worker"}]
            )
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(captcha_solver.requests, "get", fake_get)

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    assert solver._compact_cdp_pages_if_needed() == {"triggered": False, "page_count": 11, "closed": 0}
    assert all("/json/close/" not in url for _method, url, _timeout in requested)


def test_connect_tab_compacts_accumulated_pages_then_reopens_current_target(monkeypatch) -> None:
    requested: list[tuple[str, str, int]] = []
    connected_urls: list[str] = []
    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"
    current_targets: list[dict[str, str]] = [
        {"id": f"page-{index}", "type": "page", "url": f"https://stale.local/{index}"}
        for index in range(12)
    ]

    class FakeResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def json(self) -> object:
            return self._payload

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

    def fake_get(url: str, timeout: int):
        requested.append(("GET", url, timeout))
        if url.endswith("/json/list"):
            return FakeResponse(current_targets)
        if "/json/close/" in url:
            target_id = url.rsplit("/", 1)[-1]
            current_targets[:] = [target for target in current_targets if target.get("id") != target_id]
            return FakeResponse({})
        raise AssertionError(f"unexpected GET {url}")

    def fake_put(url: str, timeout: int):
        requested.append(("PUT", url, timeout))
        return FakeResponse(
            {
                "id": "fresh-current-task",
                "type": "page",
                "url": target_url,
                "title": "target solver page",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/fresh-current-task",
            }
        )

    monkeypatch.setattr(captcha_solver.requests, "get", fake_get)
    monkeypatch.setattr(captcha_solver.requests, "put", fake_put)
    monkeypatch.setattr(
        captcha_solver.websocket,
        "create_connection",
        lambda ws_url, **_kwargs: connected_urls.append(ws_url) or FakeWebSocket(),
    )

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    assert solver.connect_tab() is True
    assert len([url for _method, url, _timeout in requested if "/json/close/page-" in url]) == 12
    assert (
        "PUT",
        "http://host.docker.internal:9223/json/new?https://contest.local/challenge%3F__captcha_solver_bg%3D1",
        5,
    ) in requested
    assert solver.target_id == "fresh-current-task"
    assert connected_urls == ["ws://host.docker.internal:9223/devtools/page/fresh-current-task"]


def test_connect_tab_reserves_space_before_opening_twelfth_page(monkeypatch) -> None:
    requested: list[tuple[str, str, int]] = []
    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"
    current_targets: list[dict[str, str]] = [
        {"id": f"page-{index}", "type": "page", "url": f"https://stale.local/{index}"}
        for index in range(11)
    ]

    class FakeResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def json(self) -> object:
            return self._payload

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

    def fake_get(url: str, timeout: int):
        requested.append(("GET", url, timeout))
        if url.endswith("/json/list"):
            return FakeResponse(current_targets)
        if "/json/close/" in url:
            target_id = url.rsplit("/", 1)[-1]
            current_targets[:] = [target for target in current_targets if target.get("id") != target_id]
            return FakeResponse({})
        raise AssertionError(f"unexpected GET {url}")

    def fake_put(url: str, timeout: int):
        requested.append(("PUT", url, timeout))
        return FakeResponse(
            {
                "id": "fresh-current-task",
                "type": "page",
                "url": target_url,
                "title": "target solver page",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/fresh-current-task",
            }
        )

    monkeypatch.setattr(captcha_solver.requests, "get", fake_get)
    monkeypatch.setattr(captcha_solver.requests, "put", fake_put)
    monkeypatch.setattr(
        captcha_solver.websocket,
        "create_connection",
        lambda _ws_url, **_kwargs: FakeWebSocket(),
    )

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    assert solver.connect_tab() is True
    assert len([url for _method, url, _timeout in requested if "/json/close/page-" in url]) == 11
    assert any(method == "PUT" and "/json/new?" in url for method, url, _timeout in requested)


def test_solver_closes_owned_target_tab_after_cdp_success(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://contest.local/challenge?__captcha_solver_bg=1",
        cdp_endpoint="http://host.docker.internal:9223",
    )
    solver.target_id = "owned-target"
    solver._opened_target_ids.add("owned-target")
    closed: list[str] = []

    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._headed_playwright_enabled = lambda: False
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100,
        "y": 100,
        "width": 40,
        "height": 40,
        "selector": "#nc_1_n1z",
        "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag = lambda _x, _y, _distance: 250
    solver._wait_for_verification_success = lambda: True
    solver._close_cdp_target = lambda target_id: closed.append(target_id) or True
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve() is True
    assert closed == ["owned-target"]
    assert solver.target_id is None
    assert solver.target_ws_url is None


def test_connect_tab_reuses_cached_target_websocket_when_list_is_unavailable(monkeypatch) -> None:
    requested: list[tuple[str, str, int]] = []
    connected_urls: list[str] = []
    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"

    class FakeResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def json(self) -> object:
            return self._payload

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

    list_calls = {"count": 0}

    def fake_get(url: str, timeout: int):
        requested.append(("GET", url, timeout))
        if url.endswith("/json/list"):
            list_calls["count"] += 1
            if list_calls["count"] == 1:
                return FakeResponse(
                    [
                        {
                            "url": "https://sf.taobao.com/",
                            "title": "home",
                            "webSocketDebuggerUrl": "ws://home",
                        }
                    ]
                )
            raise RuntimeError("cdp list timed out")
        raise AssertionError(f"unexpected GET {url}")

    def fake_put(url: str, timeout: int):
        requested.append(("PUT", url, timeout))
        return FakeResponse(
            {
                "id": "target-1",
                "url": target_url,
                "title": "target solver page",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/target-1",
            }
        )

    monkeypatch.setattr(captcha_solver.requests, "get", fake_get)
    monkeypatch.setattr(captcha_solver.requests, "put", fake_put)
    monkeypatch.setattr(
        captcha_solver.websocket,
        "create_connection",
        lambda ws_url, **_kwargs: connected_urls.append(ws_url) or FakeWebSocket(),
    )

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    assert solver.connect_tab() is True
    assert solver.connect_tab() is True
    assert connected_urls == [
        "ws://host.docker.internal:9223/devtools/page/target-1",
        "ws://host.docker.internal:9223/devtools/page/target-1",
    ]
    assert len([item for item in requested if item[0] == "PUT"]) == 1


def test_connect_tab_reuses_probed_target_before_page_compaction() -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://sf.taobao.com/list/50025969__2.htm?page=3&__captcha_solver_bg=1",
    )
    solver._remember_target_tab(
        {
            "id": "visible-slider",
            "url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/visible-slider",
        }
    )
    solver._get_json = lambda _endpoint: [
        {
            "id": f"page-{index}",
            "type": "page",
            "url": f"https://example.test/{index}",
            "webSocketDebuggerUrl": f"ws://127.0.0.1:9223/devtools/page/page-{index}",
        }
        for index in range(captcha_solver.DEFAULT_CDP_PAGE_TARGET_LIMIT)
    ]
    solver._compact_cdp_pages_if_needed = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("a live probed target must be reused before compaction")
    )
    connected: list[str] = []
    solver._connect_to_target = lambda target_ws, _title: connected.append(target_ws) or True

    assert solver.connect_tab() is True
    assert connected == ["ws://127.0.0.1:9223/devtools/page/visible-slider"]


def test_connect_tab_prunes_same_route_duplicates_before_cached_target_reuse() -> None:
    target_url = "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
    solver._remember_target_tab(
        {
            "id": "visible-slider",
            "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5secdata=a",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/visible-slider",
        }
    )
    tabs = [
        {
            "id": "visible-slider",
            "type": "page",
            "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5secdata=a",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/visible-slider",
        },
        {
            "id": "duplicate-slider",
            "type": "page",
            "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5secdata=b",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/duplicate-slider",
        },
    ]
    solver._get_json = lambda _endpoint: tabs
    closed: list[str] = []
    connected: list[str] = []
    solver._close_cdp_target = lambda target_id: closed.append(target_id) or True
    solver._connect_to_target = lambda target_ws, _title: connected.append(target_ws) or True

    assert solver.connect_tab() is True
    assert closed == ["duplicate-slider"]
    assert connected == ["ws://127.0.0.1:9223/devtools/page/visible-slider"]


def test_slider_miss_clears_closed_websocket_before_recovery(monkeypatch) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    solver = captcha_solver.CaptchaSolver(port=9223)
    socket = FakeWebSocket()
    solver.ws = socket
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda **_kwargs: None
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "hardBlock": False,
        "hasSlider": False,
        "loginRequired": False,
    }
    solver._reload_page = lambda: None
    recovery_websockets: list[object | None] = []

    def fake_recover() -> bool:
        recovery_websockets.append(solver.ws)
        return False

    solver._recover_authenticated_list_page = fake_recover
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0, slider_find_max_retries=1) is False
    assert socket.closed is True
    assert recovery_websockets == [None]


def test_verification_failure_recovers_before_closing_websocket(monkeypatch) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    solver = captcha_solver.CaptchaSolver(port=9223)
    socket = FakeWebSocket()
    solver.ws = socket
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda **_kwargs: {
        "x": 100,
        "y": 100,
        "width": 40,
        "height": 40,
        "selector": "#nc_1_n1z",
        "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._get_track_rect = lambda: None
    solver._do_drag = lambda *_args, **_kwargs: 260
    solver._wait_for_verification_success = lambda: False
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "hasSlider": False,
        "explicitFailure": False,
    }
    solver._reload_page = lambda: None
    recovery_websockets: list[object | None] = []

    def fake_recover() -> bool:
        recovery_websockets.append(solver.ws)
        return False

    solver._recover_authenticated_list_page = fake_recover
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0, slider_find_max_retries=1) is False
    assert recovery_websockets == [socket]
    assert socket.closed is True
    assert solver.ws is None


def test_connect_tab_falls_back_when_cached_websocket_cdp_bootstrap_times_out(monkeypatch) -> None:
    connected_urls: list[str] = []
    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"

    class StaleWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            raise captcha_solver.websocket.WebSocketTimeoutException("stale target")

        def close(self) -> None:
            return None

    class HealthyWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

        def close(self) -> None:
            return None

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://host.docker.internal:9223",
    )
    solver.target_ws_url = "ws://host.docker.internal:9223/devtools/page/stale-cached"
    solver._get_json = lambda _endpoint: [
        {
            "id": "target-1",
            "url": target_url,
            "title": "fresh solver target",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/target-1",
        },
    ]

    stale = StaleWebSocket()
    healthy = HealthyWebSocket()

    def fake_create_connection(ws_url: str, **_kwargs: bool):
        connected_urls.append(ws_url)
        if ws_url.endswith("/stale-cached"):
            return stale
        return healthy

    monkeypatch.setattr(captcha_solver.websocket, "create_connection", fake_create_connection)

    assert solver.connect_tab() is True
    assert connected_urls == [
        "ws://host.docker.internal:9223/devtools/page/stale-cached",
        "ws://host.docker.internal:9223/devtools/page/target-1",
    ]
    assert solver.target_ws_url == "ws://host.docker.internal:9223/devtools/page/target-1"


def test_punish_target_connection_failure_marks_manual_required(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._remember_target_tab(
        {
            "id": "punish-target",
            "url": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?x5step=1",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/punish-target",
        }
    )
    monkeypatch.setattr(
        captcha_solver.websocket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cdp bootstrap unavailable")),
    )

    assert solver._connect_to_target(solver.target_ws_url, "验证码拦截") is False
    assert solver.last_failure_reason == "manual_required"


def test_target_websocket_connection_has_a_bounded_bootstrap_timeout(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    connection_kwargs: dict[str, object] = {}

    class FakeWebSocket:
        def __init__(self) -> None:
            self.timeout: float | None = None

        def settimeout(self, timeout: float) -> None:
            self.timeout = timeout

        def close(self) -> None:
            return None

    fake_websocket = FakeWebSocket()

    def fake_create_connection(_target_ws: str, **kwargs: object) -> FakeWebSocket:
        connection_kwargs.update(kwargs)
        return fake_websocket

    monkeypatch.setenv("FAPAI_SOLVER_DISABLE_STEALTH", "1")
    monkeypatch.setattr(captcha_solver.websocket, "create_connection", fake_create_connection)
    monkeypatch.setattr(solver, "_send_cdp", lambda *_args, **_kwargs: {})

    assert solver._connect_to_target("ws://127.0.0.1:9223/devtools/page/test", "test") is True
    assert connection_kwargs == {"suppress_origin": True, "timeout": 5}
    assert fake_websocket.timeout == 5


def test_preflight_propagates_manual_required_from_failed_punish_connection() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    def fail_connect() -> bool:
        solver.last_failure_reason = "manual_required"
        return False

    solver.connect_tab = fail_connect

    result = solver._preflight_current_challenge()

    assert result["manual_required"] is True
    assert result["already_authenticated"] is False


def test_connect_tab_reuses_existing_punish_target_before_opening_new_page() -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    )
    connected: list[str] = []
    solver._get_json = lambda _endpoint: [
        {
            "id": "punish-target",
            "url": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?x5step=1",
            "title": "验证码拦截",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/punish-target",
        }
    ]
    solver._open_target_tab = lambda: (_ for _ in ()).throw(
        AssertionError("existing punish target should be reused")
    )
    solver._connect_to_target = lambda target_ws, _title: connected.append(target_ws) or True

    assert solver.connect_tab() is True
    assert connected == ["ws://127.0.0.1:9223/devtools/page/punish-target"]


def test_connect_tab_reuses_existing_login_target_and_bootstraps_websocket(monkeypatch) -> None:
    sent_methods: list[str] = []
    connected_urls: list[str] = []

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            message = json.loads(payload)
            self.last_message_id = int(message["id"])
            sent_methods.append(str(message["method"]))

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

        def close(self) -> None:
            return None

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    )
    solver._get_json = lambda _endpoint: [
        {
            "id": "login-target",
            "url": "https://login.taobao.com/havanaone/login/login.htm",
            "title": "登录",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/login-target",
        }
    ]
    solver._open_target_tab = lambda: (_ for _ in ()).throw(
        AssertionError("existing login target should be reused")
    )
    monkeypatch.setattr(
        captcha_solver.websocket,
        "create_connection",
        lambda ws_url, **_kwargs: connected_urls.append(ws_url) or FakeWebSocket(),
    )

    assert solver.connect_tab() is True
    assert connected_urls == ["ws://localhost:9223/devtools/page/login-target"]
    assert sent_methods[:3] == ["DOM.enable", "Runtime.enable", "Page.enable"]
    assert solver.last_failure_reason is None


def test_manual_challenge_reuse_requires_same_requested_route() -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=(
            "https://sf.taobao.com/list/50025969__2.htm"
            "?auction_start_seg=-1&location_code=110114&page=4&st_param=5"
        ),
    )

    assert solver._manual_challenge_matches_requested_target(
        "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5step=1"
    ) is True
    assert solver._manual_challenge_matches_requested_target(
        "https://sf.taobao.com//list/50025970__2.htm/_____tmd_____/punish?x5step=1"
    ) is False
    assert solver._solver_target_route(
        "https://sf-item.taobao.com/sf_item/601294677898.htm?source=a"
    ) != solver._solver_target_route(
        "https://sf-item.taobao.com/sf_item/601294677898.htm?source=b"
    )
    assert solver._solver_target_route(
        "https://sf-item.taobao.com/sf_item/601294677898.htm?track_id=opaque"
    ) == solver._solver_target_route(
        "https://sf-item.taobao.com//sf_item/601294677898.htm/_____tmd_____/punish?x5step=1"
    )


def test_solver_preserves_owned_challenge_tab_for_manual_verification() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.target_id = "manual-target"
    solver._opened_target_ids.add("manual-target")
    solver._preflight_current_challenge = lambda: {
        "connected": False,
        "manual_required": True,
        "has_slider": False,
        "already_authenticated": False,
    }
    closed: list[str] = []
    solver._close_cdp_target = lambda target_id: closed.append(target_id) or True

    assert solver.solve() is False
    assert closed == []


def test_get_json_retries_transient_timeout_before_success(monkeypatch) -> None:
    attempts: list[int] = []

    class FakeResponse:
        def json(self) -> list[dict[str, str]]:
            return [{"type": "page"}]

    def fake_get(url: str, timeout: int) -> FakeResponse:
        assert url == "http://host.docker.internal:9223/json/list"
        attempts.append(timeout)
        if len(attempts) < 3:
            raise RuntimeError("temporary timeout")
        return FakeResponse()

    monkeypatch.setattr(captcha_solver.requests, "get", fake_get)

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    assert solver._get_json("list") == [{"type": "page"}]
    assert attempts == [2, 4, 6]


def test_connect_tab_suppresses_websocket_origin_for_remote_debugging(monkeypatch) -> None:
    connection_kwargs: list[dict[str, object]] = []

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://192.168.65.254:9223",
    )
    solver._get_json = lambda _endpoint: [
        {
            "url": target_url,
            "title": "target solver page",
            "webSocketDebuggerUrl": "ws://192.168.65.254:9223/devtools/page/abc",
        },
    ]

    def fake_create_connection(_ws_url: str, **kwargs: object) -> FakeWebSocket:
        connection_kwargs.append(kwargs)
        return FakeWebSocket()

    monkeypatch.setattr(captcha_solver.websocket, "create_connection", fake_create_connection)

    assert solver.connect_tab() is True
    assert connection_kwargs == [{"suppress_origin": True, "timeout": 5}]


def test_send_cdp_mouse_event_consumes_matching_response() -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent_payloads: list[dict[str, object]] = []
            self.recv_count = 0
            self.last_message_id = 0

        def send(self, payload: str) -> None:
            message = json.loads(payload)
            self.sent_payloads.append(message)
            self.last_message_id = int(message["id"])

        def recv(self) -> str:
            self.recv_count += 1
            return json.dumps({"id": self.last_message_id, "result": {}})

    ws = FakeWebSocket()
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.ws = ws

    result = solver._send_cdp(
        "Input.dispatchMouseEvent",
        {"type": "mouseMoved", "x": 10, "y": 20, "button": "none"},
    )

    assert result == {}
    assert len(ws.sent_payloads) == 1
    assert ws.sent_payloads[0]["method"] == "Input.dispatchMouseEvent"
    assert ws.recv_count == 1


def test_solver_falls_back_to_manual_when_cdp_mouse_input_times_out(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    cdp_calls: list[str] = []
    reload_calls: list[bool] = []

    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100,
        "y": 100,
        "width": 40,
        "height": 40,
        "selector": "#nc_1_n1z",
        "context": "main",
    }
    solver._get_track_width = lambda: 300

    def fail_mouse_input(method: str, _params: dict[str, object]) -> None:
        cdp_calls.append(method)
        return None

    solver._send_cdp = fail_mouse_input
    solver._wait_for_verification_success = lambda: (_ for _ in ()).throw(
        AssertionError("verification must not run after CDP mouse input fails")
    )
    solver._reload_page = lambda: reload_calls.append(True)
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "manual_required"
    assert [method for method in cdp_calls if method.startswith("Input.")] == [
        "Input.dispatchMouseEvent"
    ]
    assert reload_calls == []


def test_solver_returns_false_quickly_for_baxia_hard_block(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    calls = {"connect": 0, "reload": 0, "sleep": []}

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: None
    solver._reload_page = lambda: calls.__setitem__("reload", calls["reload"] + 1)
    solver._page_challenge_summary = lambda: {
        "hardBlock": True,
        "hasSlider": False,
        "title": "captcha intercept",
        "className": "baxia-punish denyfromx5 pc",
        "bodyText": "blocked by baxia",
    }

    def fake_sleep(seconds: float) -> None:
        calls["sleep"].append(seconds)
        raise AssertionError("solver should not retry/sleep on an unsupported hard block")

    monkeypatch.setattr(captcha_solver.time, "sleep", fake_sleep)

    assert solver.solve() is False
    assert calls["connect"] == 1
    assert calls["reload"] == 0


def test_solver_skips_headed_playwright_branches_without_display(monkeypatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("FAPAI_SOLVER_ENABLE_HEADED_PLAYWRIGHT", raising=False)
    solver = captcha_solver.CaptchaSolver(port=9223)
    calls: list[str] = []

    solver._preflight_current_challenge = lambda: {
        "connected": False,
        "manual_required": False,
        "has_slider": False,
    }
    solver._solve_with_ddddocr = lambda: calls.append("ddddocr") or False
    solver._solve_with_playwright_stealth = lambda: calls.append("playwright_stealth") or False
    solver._solve_with_userscript = lambda: calls.append("userscript") or True
    solver.connect_tab = lambda: calls.append("cdp") or False
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert "ddddocr" not in calls
    assert "playwright_stealth" not in calls
    assert "userscript" not in calls
    assert calls == ["cdp"]


def test_preflight_marks_normal_auction_page_as_already_authenticated() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    class FakeWebSocket:
        closed = False

        def close(self) -> None:
            self.closed = True

    ws = FakeWebSocket()
    solver.ws = ws
    solver.connect_tab = lambda: True
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "explicitFailure": False,
        "hasSlider": False,
        "authenticatedPage": True,
        "title": "司法拍卖",
        "className": "",
        "bodyText": "normal auction list",
    }

    result = solver._preflight_current_challenge()

    assert result["already_authenticated"] is True
    assert result["connected"] is False
    assert ws.closed is True
    assert solver.ws is None


def test_preflight_accepts_valid_auction_payload_with_generic_hidden_challenge_copy() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.connect_tab = lambda: True
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "explicitFailure": False,
        "hasSlider": False,
        "challengePresent": False,
        "challengeMarker": True,
        "validAuctionPayload": True,
        "authenticatedPage": True,
        "title": "司法拍卖",
        "bodyText": "auction list payload",
    }

    result = solver._preflight_current_challenge()

    assert result["already_authenticated"] is True
    assert result["manual_required"] is False


def test_preflight_marks_login_page_as_manual_required() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    class FakeWebSocket:
        closed = False

        def close(self) -> None:
            self.closed = True

    ws = FakeWebSocket()
    solver.ws = ws
    solver.connect_tab = lambda: True
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "explicitFailure": False,
        "hasSlider": False,
        "loginRequired": True,
        "authenticatedPage": False,
        "title": "登录",
        "className": "",
        "bodyText": "请登录后继续",
    }

    result = solver._preflight_current_challenge()

    assert result["manual_required"] is True
    assert result["connected"] is False
    assert ws.closed is True
    assert solver.ws is None
    assert solver.last_failure_reason == "manual_required"


def test_preflight_treats_login_jump_as_login_required() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.connect_tab = lambda: True
    solver._page_challenge_summary = lambda: {
        "hardBlock": True,
        "explicitFailure": False,
        "hasSlider": False,
        "loginRequired": True,
        "authenticatedPage": False,
        "href": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/page/login_jump?x5step=1",
        "title": "登录跳转",
        "className": "",
        "bodyText": "",
    }

    result = solver._preflight_current_challenge()

    assert result["manual_required"] is True
    assert result["already_authenticated"] is False
    assert result["has_slider"] is False
    assert solver.last_failure_reason == "manual_required"


def test_preflight_clears_login_wait_when_page_becomes_authenticated() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.connect_tab = lambda: True
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "explicitFailure": False,
        "hasSlider": False,
        "loginRequired": True,
        "authenticatedPage": False,
        "title": "登录",
        "className": "",
        "bodyText": "请登录后继续",
    }
    solver._poll_until_authenticated = lambda: True

    result = solver._preflight_current_challenge()

    assert result["already_authenticated"] is True
    assert result["manual_required"] is False
    assert solver.last_failure_reason is None


def test_preflight_continues_drag_when_slider_appears_during_login_wait() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.connect_tab = lambda: True
    summaries = [
        {
            "hardBlock": True,
            "explicitFailure": False,
            "hasSlider": False,
            "loginRequired": True,
            "authenticatedPage": False,
            "href": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/page/login_jump",
            "title": "登录跳转",
            "className": "",
            "bodyText": "",
        },
        {
            "hardBlock": True,
            "explicitFailure": False,
            "hasSlider": True,
            "loginRequired": False,
            "authenticatedPage": False,
            "href": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish",
            "title": "验证码拦截",
            "className": "",
            "bodyText": "请按住滑块",
        },
    ]

    def next_summary():
        return summaries.pop(0) if summaries else {
            "hardBlock": True,
            "hasSlider": True,
            "loginRequired": False,
            "authenticatedPage": False,
        }

    solver._page_challenge_summary = next_summary
    solver._poll_until_authenticated = lambda: False

    result = solver._preflight_current_challenge()

    assert result["manual_required"] is False
    assert result["has_slider"] is True
    assert result["connected"] is True
    assert result["already_authenticated"] is False


def test_preflight_keeps_slider_when_login_and_slider_are_both_present() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.connect_tab = lambda: True
    solver._poll_until_authenticated = lambda: (_ for _ in ()).throw(
        AssertionError("login wait should be skipped when a slider is already present")
    )
    solver._page_challenge_summary = lambda: {
        "hardBlock": True,
        "explicitFailure": False,
        "hasSlider": True,
        "loginRequired": True,
        "authenticatedPage": False,
        "href": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/page/login_jump",
        "title": "登录跳转",
        "className": "",
        "bodyText": "请按住滑块",
    }

    result = solver._preflight_current_challenge()

    assert result["manual_required"] is False
    assert result["has_slider"] is True
    assert result["connected"] is True


def test_is_login_url_covers_login_jump() -> None:
    assert captcha_solver.CaptchaSolver._is_login_url(
        "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/page/login_jump?x5step=1"
    )
    assert captcha_solver.CaptchaSolver._is_login_url(
        "https://login.taobao.com/member/login.jhtml"
    )


def test_solver_stops_without_reload_when_login_page_appears_during_attempt(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    reload_calls: list[bool] = []

    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: None
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "explicitFailure": False,
        "hasSlider": False,
        "loginRequired": True,
        "authenticatedPage": False,
        "title": "登录",
        "className": "",
        "bodyText": "请登录后继续",
    }
    solver._reload_page = lambda: reload_calls.append(True)
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "manual_required"
    assert reload_calls == []


def test_solver_returns_success_immediately_when_preflight_is_already_authenticated() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._preflight_current_challenge = lambda: {
        "connected": False,
        "manual_required": False,
        "has_slider": False,
        "already_authenticated": True,
    }
    solver._solve_with_userscript = lambda: (_ for _ in ()).throw(
        AssertionError("authenticated page must not invoke userscript solver")
    )

    assert solver.solve() is True


def test_solver_accepts_authenticated_page_when_slider_disappears_during_attempt(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    calls = {"reload": 0}
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: None
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "explicitFailure": False,
        "hasSlider": False,
        "authenticatedPage": True,
        "title": "司法拍卖",
        "className": "",
        "bodyText": "normal auction list",
    }
    solver._reload_page = lambda: calls.__setitem__("reload", calls["reload"] + 1)
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is True
    assert calls["reload"] == 0


def test_verify_success_rejects_success_signal_while_challenge_still_present() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._send_cdp = lambda _method, _params=None: {
        "result": {
            "value": {
                "sliderGone": True,
                "challengeGone": False,
                "successDetected": True,
                "hasError": False,
                "noError": True,
            }
        }
    }

    assert solver._verify_success() is False


def test_verify_success_accepts_disappeared_challenge_without_explicit_success_class() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._send_cdp = lambda _method, _params=None: {
        "result": {
            "value": {
                "success": False,
                "successDetected": False,
                "sliderGone": True,
                "challengeGone": True,
                "hasError": False,
                "noError": True,
            }
        }
    }

    assert solver._verify_success() is True


def test_solver_returns_false_when_official_challenge_explicitly_rejects_drag(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    calls = {"connect": 0, "drag": 0, "reload": 0}

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100,
        "y": 100,
        "width": 40,
        "height": 40,
        "selector": "#nc_1_n1z",
        "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag = lambda _x, _y, _distance: calls.__setitem__("drag", calls["drag"] + 1) or _distance
    solver._verify_success = lambda: False
    solver._reload_page = lambda: calls.__setitem__("reload", calls["reload"] + 1)
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "hasSlider": True,
        "explicitFailure": True,
        "title": "验证码拦截",
        "className": "",
        "bodyText": "验证失败，点击框体重试(error:KzCFR9)",
    }
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve() is False
    assert calls == {"connect": 1, "drag": 1, "reload": 0}


def test_challenge_failure_diagnostic_keeps_error_code_and_removes_url_query() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    diagnostic = solver._challenge_failure_diagnostic(
        {
            "errorCode": "error:TJiA4d/Vx6urd",
            "title": "  Captcha   intercept ",
            "className": "baxia punish",
            "href": "https://sf.taobao.com/list/1.htm?x5secdata=secret&token=secret",
            "bodyText": "must not be logged",
        }
    )

    assert "code=error:TJiA4d/Vx6urd" in diagnostic
    assert "title=Captcha intercept" in diagnostic
    assert "path=https://sf.taobao.com/list/1.htm" in diagnostic
    assert "x5secdata" not in diagnostic
    assert "secret" not in diagnostic
    assert "must not be logged" not in diagnostic


def test_solver_retries_drag_after_nc_asks_to_click_the_bar(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    calls = {"connect": 0, "drag": 0, "reset": 0, "verify": 0}
    verify_results = [False, True]

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag = lambda _x, _y, _d: calls.__setitem__("drag", calls["drag"] + 1) or _d
    solver._wait_for_verification_success = lambda: (
        calls.__setitem__("verify", calls["verify"] + 1) or verify_results.pop(0)
    )
    solver._reset_failed_nc_challenge = lambda: calls.__setitem__("reset", calls["reset"] + 1) or True
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "explicitFailure": True,
        "hasSlider": True,
    }
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=2) is True
    assert calls == {"connect": 2, "drag": 2, "reset": 1, "verify": 2}
    assert solver.last_failure_reason is None


def test_solver_retries_drag_after_nc_retry_without_spending_main_attempt(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    calls = {"connect": 0, "drag": 0, "reset": 0, "verify": 0}
    verify_results = [False, True]

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag = lambda _x, _y, _d: calls.__setitem__("drag", calls["drag"] + 1) or _d
    solver._wait_for_verification_success = lambda: (
        calls.__setitem__("verify", calls["verify"] + 1) or verify_results.pop(0)
    )
    solver._reset_failed_nc_challenge = lambda: calls.__setitem__("reset", calls["reset"] + 1) or True
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "explicitFailure": True,
        "hasSlider": True,
    }
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is True
    assert calls == {"connect": 2, "drag": 2, "reset": 1, "verify": 2}
    assert solver.last_failure_reason is None


def test_solver_can_disable_nc_replay_for_externally_scheduled_attempt(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    calls = {"connect": 0, "drag": 0, "reset": 0, "verify": 0}

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag = lambda _x, _y, _d: calls.__setitem__("drag", calls["drag"] + 1) or _d
    solver._wait_for_verification_success = lambda: calls.__setitem__("verify", calls["verify"] + 1) or False
    solver._reset_failed_nc_challenge = lambda: calls.__setitem__("reset", calls["reset"] + 1) or True
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "explicitFailure": True,
        "hasSlider": True,
    }
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0) is False
    assert calls == {"connect": 1, "drag": 1, "reset": 0, "verify": 1}
    assert solver.last_failure_reason == "manual_required"


def test_solver_can_limit_slider_lookup_for_externally_scheduled_attempt(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    find_calls: list[tuple[int, int]] = []

    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda *, max_retries, retry_delay: (
        find_calls.append((max_retries, retry_delay)) or None
    )
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "hardBlock": False,
        "loginRequired": False,
    }
    solver._reload_page = lambda: None
    solver._recover_authenticated_list_page = lambda: False
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(
        max_attempts=1,
        nc_retry_replay_limit=0,
        slider_find_max_retries=1,
    ) is False
    assert find_calls == [(1, 0)]


def test_solver_switches_profile_without_reset_when_slider_still_present(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    calls = {"connect": 0, "drag": 0, "reset": 0, "verify": 0}
    profile_indices: list[int] = []
    verify_results = [False, True]

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._os_mouse_enabled = lambda: True
    def fake_drag(_x, _y, _d, **kwargs):
        calls["drag"] += 1
        profile_indices.append(kwargs.get("profile_variant_index"))
        return 1

    solver._do_drag_os = fake_drag
    solver._wait_for_verification_success = lambda: (
        calls.__setitem__("verify", calls["verify"] + 1) or verify_results.pop(0)
    )
    solver._reset_failed_nc_challenge = lambda: calls.__setitem__("reset", calls["reset"] + 1) or True
    summaries = [
        {"authenticatedPage": False, "explicitFailure": False, "hasSlider": True},
        {"authenticatedPage": True, "explicitFailure": False, "hasSlider": False},
    ]
    solver._page_challenge_summary = lambda: summaries.pop(0)
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1, drag_profile_offset=1) is True
    assert calls == {"connect": 1, "drag": 2, "reset": 0, "verify": 2}
    assert profile_indices == [1, 2]
    assert solver.last_failure_reason is None


def test_legacy_exact_release_profile_settles_back_to_exact_target(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    profile = solver._os_drag_profiles()[1]

    assert profile["name"] == "legacy_exact_release"
    assert profile["warmup_steps"] == (2, 3)

    monkeypatch.setattr(captcha_solver.random, "uniform", lambda low, _high: low)
    peak_x, settle_xs, release_x = solver._os_drag_release_plan(100, 256, profile)

    assert peak_x == 360
    assert settle_xs[-1] == 356
    assert release_x == 356


def test_solver_recovers_auth_when_list_page_is_accessible_after_attempts(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver.connect_tab = lambda: True
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: None
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "hardBlock": False,
        "loginRequired": False,
        "hasSlider": False,
        "explicitFailure": False,
    }
    solver._reload_page = lambda: None
    solver._recover_authenticated_list_page = lambda: True
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)
    assert solver.solve(max_attempts=1) is True
    assert solver.last_failure_reason is None


def test_solver_waits_for_delayed_verification_success_before_reloading(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    calls = {"connect": 0, "drag": 0, "reload": 0, "verify": 0}
    verify_results = [False, False, True]

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    def fake_verify() -> bool:
        calls["verify"] += 1
        return verify_results.pop(0)

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100,
        "y": 100,
        "width": 40,
        "height": 40,
        "selector": "#nc_1_n1z",
        "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag = lambda _x, _y, _distance: calls.__setitem__("drag", calls["drag"] + 1) or _distance
    solver._verify_success = fake_verify
    solver._reload_page = lambda: calls.__setitem__("reload", calls["reload"] + 1)
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "hasSlider": True,
        "explicitFailure": False,
        "title": "验证码拦截",
        "className": "",
        "bodyText": "",
    }
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is True
    assert calls == {"connect": 1, "drag": 1, "reload": 0, "verify": 3}


def test_solve_skips_injected_fallbacks_for_local_mock_slider_target(monkeypatch) -> None:
    target_url = "file:///tmp/mock_slider.html"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        solver,
        "_preflight_current_challenge",
        lambda: {
            "connected": False,
            "manual_required": False,
            "has_slider": False,
            "already_authenticated": False,
        },
    )
    monkeypatch.setattr(solver, "_headed_playwright_enabled", lambda: True)
    monkeypatch.setattr(
        solver,
        "_solve_with_ddddocr",
        lambda: (_ for _ in ()).throw(AssertionError("ddddocr fallback must be skipped")),
    )
    monkeypatch.setattr(
        solver,
        "_solve_with_playwright_stealth",
        lambda: (_ for _ in ()).throw(AssertionError("playwright stealth fallback must be skipped")),
    )
    monkeypatch.setattr(
        solver,
        "_solve_with_userscript",
        lambda: (_ for _ in ()).throw(AssertionError("userscript fallback must be skipped")),
    )
    monkeypatch.setattr(
        solver,
        "connect_tab",
        lambda: setattr(solver, "ws", FakeWebSocket()) or True,
    )
    monkeypatch.setattr(solver, "_bring_to_front", lambda: True)
    monkeypatch.setattr(
        solver,
        "_find_slider",
        lambda: {
            "x": 100,
            "y": 200,
            "width": 38,
            "height": 38,
            "selector": "#mock-slider-handle",
            "context": "main",
        },
    )
    monkeypatch.setattr(solver, "_get_track_width", lambda: 420)
    monkeypatch.setattr(solver, "_wait_for_verification_success", lambda: True)
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)

    assert solver.solve(max_attempts=1) is True


def test_local_mock_target_uses_deterministic_drag_distance(monkeypatch) -> None:
    target_url = "file:///tmp/mock_slider.html"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
    dragged_distances: list[float] = []

    class FakeWebSocket:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        solver,
        "_preflight_current_challenge",
        lambda: {
            "connected": False,
            "manual_required": False,
            "has_slider": False,
            "already_authenticated": False,
        },
    )
    monkeypatch.setattr(solver, "_headed_playwright_enabled", lambda: True)
    monkeypatch.setattr(solver, "connect_tab", lambda: setattr(solver, "ws", FakeWebSocket()) or True)
    monkeypatch.setattr(solver, "_bring_to_front", lambda: True)
    monkeypatch.setattr(
        solver,
        "_find_slider",
        lambda: {
            "x": 100,
            "y": 200,
            "width": 38,
            "height": 38,
            "selector": "#mock-slider-handle",
            "context": "main",
        },
    )
    monkeypatch.setattr(solver, "_get_track_width", lambda: 420)
    monkeypatch.setattr(
        solver,
        "_do_drag_local_mock",
        lambda _x, _y, distance: dragged_distances.append(distance) or distance,
    )
    monkeypatch.setattr(solver, "_wait_for_verification_success", lambda: True)
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        captcha_solver.random,
        "uniform",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("local mock path should not use random.uniform")),
    )

    assert solver.solve(max_attempts=1) is True
    assert dragged_distances == [374]


def test_local_mock_target_reloads_without_verifying_after_drag_failure(monkeypatch) -> None:
    target_url = "file:///tmp/mock_slider.html"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
    calls = {"reload": 0}

    class FakeWebSocket:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        solver,
        "_preflight_current_challenge",
        lambda: {
            "connected": False,
            "manual_required": False,
            "has_slider": False,
            "already_authenticated": False,
        },
    )
    monkeypatch.setattr(solver, "connect_tab", lambda: setattr(solver, "ws", FakeWebSocket()) or True)
    monkeypatch.setattr(solver, "_bring_to_front", lambda: True)
    monkeypatch.setattr(
        solver,
        "_find_slider",
        lambda: {
            "x": 100,
            "y": 200,
            "width": 38,
            "height": 38,
            "selector": "#mock-slider-handle",
            "context": "main",
        },
    )
    monkeypatch.setattr(solver, "_get_track_width", lambda: 420)
    monkeypatch.setattr(solver, "_do_drag_local_mock", lambda *_args: None)
    monkeypatch.setattr(
        solver,
        "_wait_for_verification_success",
        lambda: (_ for _ in ()).throw(AssertionError("verification should not run after drag failure")),
    )
    monkeypatch.setattr(solver, "_reload_page", lambda: calls.__setitem__("reload", calls["reload"] + 1))
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "max_attempts_exceeded"
    assert calls == {"reload": 1}


def test_local_mock_verification_mode_defaults_to_strict_success_text() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="file:///tmp/mock_slider.html")

    assert solver._local_mock_verification_mode() == "strict_success_text"


def test_local_mock_verification_mode_reads_query_parameter() -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=teardown_only",
    )

    assert solver._local_mock_verification_mode() == "teardown_only"


def test_local_mock_verification_mode_accepts_retry_then_success() -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=retry_then_success",
    )

    assert solver._local_mock_verification_mode() == "retry_then_success"


def test_verify_success_accepts_local_mock_strict_success_text(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=strict_success_text",
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda _method, _params: {
            "result": {
                "value": {
                    "success": False,
                    "successDetected": False,
                    "sliderGone": True,
                    "challengeGone": True,
                    "hasError": False,
                    "noError": True,
                    "mockStateSuccess": True,
                    "mockStateFailure": False,
                    "mockResolution": "success",
                    "mockStatusText": "拖动机制验证通过",
                    "mockVerifyMode": "strict_success_text",
                    "mockChallengeVisible": True,
                }
            }
        },
    )

    assert solver._verify_success() is True


def test_verify_success_accepts_local_mock_teardown_only(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=teardown_only",
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda _method, _params: {
            "result": {
                "value": {
                    "success": False,
                    "successDetected": False,
                    "sliderGone": True,
                    "challengeGone": True,
                    "hasError": False,
                    "noError": True,
                    "mockStateSuccess": True,
                    "mockStateFailure": False,
                    "mockResolution": "success",
                    "mockStatusText": "验证组件已关闭",
                    "mockVerifyMode": "teardown_only",
                    "mockChallengeVisible": False,
                }
            }
        },
    )

    assert solver._verify_success() is True


def test_verify_success_rejects_local_mock_explicit_fail(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=explicit_fail",
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda _method, _params: {
            "result": {
                "value": {
                    "success": False,
                    "successDetected": False,
                    "sliderGone": True,
                    "challengeGone": True,
                    "hasError": True,
                    "noError": False,
                    "mockStateSuccess": False,
                    "mockStateFailure": True,
                    "mockResolution": "failure",
                    "mockStatusText": "验证失败，点击框体重试(error:KzCFR9)",
                    "mockVerifyMode": "explicit_fail",
                    "mockChallengeVisible": True,
                }
            }
        },
    )

    assert solver._verify_success() is False
    assert solver._last_mock_terminal_state == "manual_required"


def test_verify_success_rejects_official_failure_after_slider_disappears(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://sf.taobao.com/list/50025969__2.htm",
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda _method, _params: {
            "result": {
                "value": {
                    "success": False,
                    "successDetected": False,
                    "sliderGone": True,
                    "challengeGone": False,
                    "hasError": True,
                    "noError": False,
                }
            }
        },
    )

    assert solver._verify_success() is False


def test_verify_success_rejects_local_mock_near_miss_without_manual_required(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=near_miss",
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda _method, _params: {
            "result": {
                "value": {
                    "success": False,
                    "successDetected": False,
                    "sliderGone": True,
                    "challengeGone": True,
                    "hasError": False,
                    "noError": True,
                    "mockStateSuccess": False,
                    "mockStateFailure": True,
                    "mockResolution": "failure",
                    "mockStatusText": "拖动未达标，请重新拖动",
                    "mockVerifyMode": "near_miss",
                    "mockChallengeVisible": True,
                }
            }
        },
    )

    assert solver._verify_success() is False
    assert solver.last_failure_reason is None
    assert solver._last_mock_terminal_state == "terminal_failure"


def test_verify_success_rejects_local_mock_retry_then_success_without_manual_required(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=retry_then_success",
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda _method, _params: {
            "result": {
                "value": {
                    "success": False,
                    "successDetected": False,
                    "sliderGone": False,
                    "challengeGone": False,
                    "hasError": True,
                    "noError": False,
                    "mockStateSuccess": False,
                    "mockStateFailure": True,
                    "mockResolution": "failure",
                    "mockStatusText": "验证失败，点击框体重试(error:KzCFR9)",
                    "mockVerifyMode": "retry_then_success",
                    "mockChallengeVisible": True,
                }
            }
        },
    )

    assert solver._verify_success() is False
    assert solver.last_failure_reason is None
    assert solver._last_mock_terminal_state == "terminal_failure"


def test_wait_for_verification_success_short_circuits_local_mock_explicit_fail(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=explicit_fail",
    )
    calls = {"verify": 0, "sleep": 0}

    def fake_verify() -> bool:
        calls["verify"] += 1
        solver._last_mock_terminal_state = "manual_required"
        return False

    monkeypatch.setattr(solver, "_verify_success", fake_verify)
    monkeypatch.setattr(
        solver,
        "_page_challenge_summary",
        lambda: (_ for _ in ()).throw(AssertionError("explicit_fail terminal state should not need page summary")),
    )
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: calls.__setitem__("sleep", calls["sleep"] + 1))

    assert solver._wait_for_verification_success(max_checks=10) is False
    assert solver.last_failure_reason == "manual_required"
    assert calls == {"verify": 1, "sleep": 0}


def test_wait_for_verification_success_short_circuits_local_mock_near_miss(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=near_miss",
    )
    calls = {"verify": 0, "sleep": 0}

    def fake_verify() -> bool:
        calls["verify"] += 1
        solver._last_mock_terminal_state = "terminal_failure"
        return False

    monkeypatch.setattr(solver, "_verify_success", fake_verify)
    monkeypatch.setattr(
        solver,
        "_page_challenge_summary",
        lambda: (_ for _ in ()).throw(AssertionError("near_miss must not use explicit-fail terminal check")),
    )
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: calls.__setitem__("sleep", calls["sleep"] + 1))

    assert solver._wait_for_verification_success(max_checks=3) is False
    assert solver.last_failure_reason is None
    assert calls == {"verify": 1, "sleep": 0}


def test_wait_for_verification_success_short_circuits_local_mock_retry_then_success(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=retry_then_success",
    )
    calls = {"verify": 0, "sleep": 0}

    def fake_verify() -> bool:
        calls["verify"] += 1
        solver._last_mock_terminal_state = "terminal_failure"
        return False

    monkeypatch.setattr(solver, "_verify_success", fake_verify)
    monkeypatch.setattr(
        solver,
        "_page_challenge_summary",
        lambda: (_ for _ in ()).throw(AssertionError("retry_then_success must not force manual-required summary checks")),
    )
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: calls.__setitem__("sleep", calls["sleep"] + 1))

    assert solver._wait_for_verification_success(max_checks=5) is False
    assert solver.last_failure_reason is None
    assert calls == {"verify": 1, "sleep": 0}


def test_wait_for_verification_success_keeps_polling_local_mock_without_terminal_state(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=strict_success_text",
    )
    calls = {"verify": 0, "sleep": 0}

    def fake_verify() -> bool:
        calls["verify"] += 1
        solver._last_mock_terminal_state = None
        return False

    monkeypatch.setattr(solver, "_verify_success", fake_verify)
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: calls.__setitem__("sleep", calls["sleep"] + 1))

    assert solver._wait_for_verification_success(max_checks=3) is False
    assert calls == {"verify": 10, "sleep": 9}


def test_solver_returns_immediately_when_local_mock_wait_sets_manual_required(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=explicit_fail",
    )
    calls = {"reload": 0}

    class FakeWebSocket:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        solver,
        "_preflight_current_challenge",
        lambda: {
            "connected": False,
            "manual_required": False,
            "has_slider": False,
            "already_authenticated": False,
        },
    )
    monkeypatch.setattr(solver, "connect_tab", lambda: setattr(solver, "ws", FakeWebSocket()) or True)
    monkeypatch.setattr(solver, "_bring_to_front", lambda: True)
    monkeypatch.setattr(
        solver,
        "_find_slider",
        lambda: {
            "x": 100,
            "y": 200,
            "width": 38,
            "height": 38,
            "selector": "#mock-slider-handle",
            "context": "main",
        },
    )
    monkeypatch.setattr(solver, "_get_track_width", lambda: 420)
    monkeypatch.setattr(solver, "_do_drag_local_mock", lambda _x, _y, distance: distance)

    def fake_wait() -> bool:
        solver.last_failure_reason = "manual_required"
        return False

    monkeypatch.setattr(solver, "_wait_for_verification_success", fake_wait)
    monkeypatch.setattr(
        solver,
        "_page_challenge_summary",
        lambda: (_ for _ in ()).throw(AssertionError("challenge summary should not run after terminal manual_required")),
    )
    monkeypatch.setattr(solver, "_reload_page", lambda: calls.__setitem__("reload", calls["reload"] + 1))
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "manual_required"
    assert calls == {"reload": 0}


def test_solver_local_mock_retry_then_success_replays_without_spending_main_attempt(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=retry_then_success",
    )
    calls = {"connect": 0, "drag": 0, "reset": 0, "verify": 0}
    verify_results = [False, True]

    monkeypatch.setattr(
        solver,
        "_preflight_current_challenge",
        lambda: {
            "connected": True,
            "manual_required": False,
            "has_slider": True,
            "already_authenticated": False,
        },
    )
    monkeypatch.setattr(solver, "connect_tab", lambda: calls.__setitem__("connect", calls["connect"] + 1) or True)
    monkeypatch.setattr(solver, "_bring_to_front", lambda: True)
    monkeypatch.setattr(
        solver,
        "_find_slider",
        lambda: {
            "x": 100,
            "y": 200,
            "width": 38,
            "height": 38,
            "selector": "#mock-slider-handle",
            "context": "main",
        },
    )
    monkeypatch.setattr(solver, "_get_track_width", lambda: 420)
    monkeypatch.setattr(
        solver,
        "_do_drag_local_mock",
        lambda _x, _y, distance: calls.__setitem__("drag", calls["drag"] + 1) or distance,
    )
    monkeypatch.setattr(
        solver,
        "_wait_for_verification_success",
        lambda: calls.__setitem__("verify", calls["verify"] + 1) or verify_results.pop(0),
    )
    monkeypatch.setattr(
        solver,
        "_reset_failed_nc_challenge",
        lambda: calls.__setitem__("reset", calls["reset"] + 1) or True,
    )
    summaries = [
        {"authenticatedPage": False, "explicitFailure": True, "hasSlider": False},
        {"authenticatedPage": True, "explicitFailure": False, "hasSlider": False},
    ]
    monkeypatch.setattr(solver, "_page_challenge_summary", lambda: summaries.pop(0))
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is True
    assert calls == {"connect": 1, "drag": 2, "reset": 1, "verify": 2}
    assert solver.last_failure_reason is None


def test_solver_near_miss_reloads_and_exhausts_attempts_without_manual_required(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=near_miss",
    )
    calls = {"reload": 0}

    class FakeWebSocket:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        solver,
        "_preflight_current_challenge",
        lambda: {
            "connected": False,
            "manual_required": False,
            "has_slider": False,
            "already_authenticated": False,
        },
    )
    monkeypatch.setattr(solver, "connect_tab", lambda: setattr(solver, "ws", FakeWebSocket()) or True)
    monkeypatch.setattr(solver, "_bring_to_front", lambda: True)
    monkeypatch.setattr(
        solver,
        "_find_slider",
        lambda: {
            "x": 100,
            "y": 200,
            "width": 38,
            "height": 38,
            "selector": "#mock-slider-handle",
            "context": "main",
        },
    )
    monkeypatch.setattr(solver, "_get_track_width", lambda: 420)
    monkeypatch.setattr(solver, "_do_drag_local_mock", lambda _x, _y, distance: distance)
    monkeypatch.setattr(solver, "_wait_for_verification_success", lambda: False)
    monkeypatch.setattr(solver, "_page_challenge_summary", lambda: {"explicitFailure": False})
    monkeypatch.setattr(solver, "_reload_page", lambda: calls.__setitem__("reload", calls["reload"] + 1))
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "max_attempts_exceeded"
    assert calls == {"reload": 1}


def test_os_mouse_disabled_during_pytest() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    assert solver._os_mouse_enabled() is False


def test_live_solve_uses_os_mouse_when_enabled(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    calls: list[str] = []
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._os_mouse_enabled = lambda: True
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag_os = lambda _x, _y, _d, **_k: calls.append("os") or 250
    solver._do_drag = lambda _x, _y, _d: calls.append("cdp") or 250
    solver._wait_for_verification_success = lambda: True
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)
    assert solver.solve(max_attempts=1) is True
    assert calls == ["os"]


def test_wait_for_verification_success_accepts_authenticated_auction_page(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    solver._verify_success = lambda: False
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": True,
        "hasSlider": False,
        "explicitFailure": False,
    }
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)
    assert solver._wait_for_verification_success(max_checks=2) is True


def test_solve_treats_authenticated_page_after_drag_as_success(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver.connect_tab = lambda: True
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._os_mouse_enabled = lambda: False
    solver._do_drag = lambda _x, _y, _d: 250
    solver._wait_for_verification_success = lambda: False
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": True,
        "explicitFailure": False,
        "hasSlider": False,
    }
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)
    assert solver.solve(max_attempts=1) is True
    assert solver.last_failure_reason is None


def test_map_css_to_screen_uses_screenshot_when_near_win32() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._win32_client_origin = lambda: {
        "hwnd": 1,
        "left": 50.0,
        "top": 80.0,
        "width": 1920.0,
        "height": 1080.0,
    }
    solver._window_metrics = lambda: {"innerWidth": 1600, "innerHeight": 900, "dpr": 1.2}
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: {
        "left": 146.0,
        "top": 116.0,
        "width": 360.0,
        "height": 48.0,
        "shot_w": 360.0,
        "shot_h": 48.0,
        "clipped": True,
        "clip_x": 80.0,
        "clip_y": 30.0,
        "clip_w": 300.0,
        "clip_h": 40.0,
    }
    mapped = solver._map_css_to_screen(100, 50, 260)
    assert mapped["source"] == "screenshot_handle"
    assert abs(mapped["x"] - 170.0) < 0.01
    assert abs(mapped["y"] - 140.0) < 0.01
    assert abs(mapped["distance"] - 312.0) < 0.01


def test_map_css_to_screen_prefers_render_widget_over_screenshot() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._win32_client_origin = lambda: {
        "hwnd": 1,
        "render_hwnd": 2,
        "left": 50.0,
        "top": 80.0,
        "width": 1920.0,
        "height": 1080.0,
        "uses_render_widget": True,
    }
    solver._window_metrics = lambda: {"innerWidth": 1600, "innerHeight": 900, "dpr": 1.2}
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: {
        "left": 62.0,
        "top": 104.0,
        "width": 48.0,
        "height": 48.0,
        "clipped": True,
        "clip_x": 10.0,
        "clip_y": 20.0,
        "clip_w": 40.0,
        "clip_h": 40.0,
    }
    mapped = solver._map_css_to_screen(100, 50, 260)
    assert mapped["source"] == "win32_render"
    assert abs(mapped["x"] - 170.0) < 0.01
    assert abs(mapped["y"] - 140.0) < 0.01
    assert abs(mapped["distance"] - 312.0) < 0.01


def test_map_css_to_screen_prefers_screenshot_for_moderate_render_widget_drift() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._win32_client_origin = lambda: {
        "hwnd": 1,
        "render_hwnd": 2,
        "left": 50.0,
        "top": 80.0,
        "width": 1920.0,
        "height": 1080.0,
        "uses_render_widget": True,
    }
    solver._window_metrics = lambda: {"innerWidth": 1600, "innerHeight": 900, "dpr": 1.2}
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: {
        "left": 62.0,
        "top": 184.0,
        "width": 48.0,
        "height": 48.0,
        "clipped": True,
        "clip_x": 10.0,
        "clip_y": 20.0,
        "clip_w": 40.0,
        "clip_h": 40.0,
    }

    mapped = solver._map_css_to_screen(100, 50, 260)

    assert mapped["source"] == "screenshot_handle"
    assert abs(mapped["x"] - 170.0) < 0.01
    assert abs(mapped["y"] - 220.0) < 0.01


def test_map_css_to_screen_prefers_screenshot_when_render_widget_delta_is_huge() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._win32_client_origin = lambda: {
        "hwnd": 1,
        "render_hwnd": 2,
        "left": 500.0,
        "top": 400.0,
        "width": 1920.0,
        "height": 1080.0,
        "uses_render_widget": True,
    }
    solver._window_metrics = lambda: {"innerWidth": 1600, "innerHeight": 900, "dpr": 1.2}
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: {
        "left": 0.0,
        "top": 0.0,
        "width": 48.0,
        "height": 48.0,
        "clipped": True,
        "clip_x": 10.0,
        "clip_y": 20.0,
        "clip_w": 40.0,
        "clip_h": 40.0,
    }

    mapped = solver._map_css_to_screen(400, 300, 260)

    assert mapped["source"] == "screenshot_handle"
    assert abs(mapped["x"] - 468.0) < 0.01
    assert abs(mapped["y"] - 336.0) < 0.01


def test_map_css_to_screen_prefers_screenshot_over_win32() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._win32_client_origin = lambda: {
        "hwnd": 1,
        "left": 50.0,
        "top": 80.0,
        "width": 1920.0,
        "height": 1080.0,
    }
    solver._window_metrics = lambda: {"innerWidth": 1600, "innerHeight": 900, "dpr": 1.2}
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: {
        "left": 0.0,
        "top": 0.0,
        "width": 48.0,
        "height": 48.0,
        "clipped": True,
        "clip_x": 10.0,
        "clip_y": 20.0,
        "clip_w": 40.0,
        "clip_h": 40.0,
    }
    mapped = solver._map_css_to_screen(100, 50, 260)
    assert mapped["source"] == "screenshot_handle"
    assert abs(mapped["x"] - 108.0) < 0.01
    assert abs(mapped["y"] - 36.0) < 0.01


def test_map_css_to_screen_returns_explicit_failure_when_no_mapping_is_available() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._css_to_client_screen = lambda *_args: None
    solver._css_to_cdp_window_screen = lambda *_args: None
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: None

    assert solver._map_css_to_screen(100, 50, 260) is None
    assert solver.last_failure_reason == "screen_mapping_unavailable"


def test_map_css_to_screen_uses_screenshot_when_exact_target_activation_is_verified() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._target_activation_verified = True
    solver._css_to_client_screen = lambda *_args: {
        "x": 320.0,
        "y": 420.0,
        "distance": 256.0,
        "source": "win32_render",
        "uses_render_widget": True,
        "region": (0, 0, 1920, 1080),
    }
    solver._css_to_cdp_window_screen = lambda *_args: None
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: {
        "left": 0.0,
        "top": 0.0,
        "width": 48.0,
        "height": 48.0,
        "clipped": True,
        "clip_x": 10.0,
        "clip_y": 20.0,
        "clip_w": 40.0,
        "clip_h": 40.0,
    }

    mapped = solver._map_css_to_screen(100, 50, 256, slider_info={"x": 80, "y": 35})

    assert mapped["source"] == "screenshot_handle"
    assert abs(mapped["x"] - 108.0) < 0.01
    assert abs(mapped["y"] - 36.0) < 0.01
    assert mapped["located"] is True
    assert mapped["activation_verified"] is True


def test_prune_challenge_tabs_keeps_only_requested_target_route() -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    )
    closed = []
    solver._close_cdp_target = lambda target_id: closed.append(target_id) or True

    tabs = [
        {
            "type": "page",
            "id": "keep",
            "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5secdata=a",
            "webSocketDebuggerUrl": "ws://keep",
        },
        {
            "type": "page",
            "id": "duplicate",
            "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5secdata=b",
            "webSocketDebuggerUrl": "ws://duplicate",
        },
        {
            "type": "page",
            "id": "other-route",
            "url": "https://sf.taobao.com/list/50025970__2.htm/_____tmd_____/punish?x5secdata=c",
            "webSocketDebuggerUrl": "ws://other-route",
        },
        {
            "type": "page",
            "id": "login",
            "url": "https://login.taobao.com/havanaone/login/login.htm",
            "webSocketDebuggerUrl": "ws://login",
        },
        {
            "type": "page",
            "id": "auction",
            "url": "https://sf.taobao.com/list/50025970__2.htm",
            "webSocketDebuggerUrl": "ws://auction",
        },
    ]

    result = solver._prune_duplicate_challenge_tabs(tabs)

    assert result == {"closed": 2, "kept": "keep"}
    assert closed == ["duplicate", "other-route"]


def test_map_css_to_screen_allows_zero_distance_for_clicks() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._css_to_client_screen = lambda *_args: {
        "x": 120.0,
        "y": 80.0,
        "distance": 0.0,
        "source": "test",
    }
    solver._css_to_cdp_window_screen = lambda *_args: None
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: None

    mapped = solver._map_css_to_screen(100, 50, 0, allow_zero_distance=True)

    assert mapped is not None
    assert mapped["x"] == 120.0
    assert mapped["y"] == 80.0
    assert mapped["distance"] == 0.0


def test_click_css_point_falls_back_to_cdp_when_os_mapping_is_unavailable(monkeypatch) -> None:
    class FakePyAutoGUI:
        FAILSAFE = True
        PAUSE = 0

    dispatched: list[str] = []
    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI())
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._os_mouse_enabled = lambda: True
    solver._focus_os_window = lambda: True
    solver._map_css_to_screen = lambda *_args, **_kwargs: None
    solver._dispatch_mouse = lambda event, *_args, **_kwargs: dispatched.append(event) or True

    assert solver._click_css_point(100, 50) is True
    assert dispatched == ["mousePressed", "mouseReleased"]


def test_bounded_os_cursor_move_uses_fixed_zero_duration_steps(monkeypatch) -> None:
    moves: list[tuple[float, float, float]] = []
    sleeps: list[float] = []

    class FakePyAutoGUI:
        def position(self):
            return (0.0, 0.0)

        def moveTo(self, x, y, duration=0):
            moves.append((x, y, duration))

    monkeypatch.setattr(captcha_solver.time, "sleep", sleeps.append)
    solver = captcha_solver.CaptchaSolver(port=9223)

    solver._move_os_cursor_bounded(FakePyAutoGUI(), 100.0, 50.0, 0.4)

    assert 3 <= len(moves) <= 12
    assert all(duration == 0 for _x, _y, duration in moves)
    assert moves[-1][:2] == (100.0, 50.0)
    assert abs(sum(sleeps) - 0.4) < 0.001


def test_timed_os_cursor_move_preserves_pyautogui_duration_by_default(monkeypatch) -> None:
    moves: list[tuple[float, float, float]] = []

    class FakePyAutoGUI:
        def moveTo(self, x, y, duration=0):
            moves.append((x, y, duration))

    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.delenv("FAPAI_SOLVER_OS_INPUT_BACKEND", raising=False)

    solver._move_os_cursor_timed(FakePyAutoGUI(), 100.0, 50.0, 0.4)

    assert moves == [(100.0, 50.0, 0.4)]


def test_native_os_input_requires_explicit_opt_in(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.setattr(captcha_solver.os, "name", "nt")
    monkeypatch.delenv("FAPAI_SOLVER_OS_INPUT_BACKEND", raising=False)

    assert solver._native_os_input_enabled() is False

    monkeypatch.setenv("FAPAI_SOLVER_OS_INPUT_BACKEND", "win32")
    assert solver._native_os_input_enabled() is True


def test_set_os_cursor_position_falls_back_to_absolute_mouse_event(monkeypatch) -> None:
    events: list[tuple[object, ...]] = []

    class FakeUser32:
        @staticmethod
        def SetCursorPos(x, y):
            events.append(("set", x, y))
            return 0

        @staticmethod
        def GetSystemMetrics(index):
            return {76: 0, 77: 0, 78: 1920, 79: 1080}[index]

        @staticmethod
        def mouse_event(flags, x, y, data, extra_info):
            events.append(("mouse_event", flags, x, y, data, extra_info))

    class FakeWindll:
        user32 = FakeUser32()

    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.setattr(solver, "_native_os_input_enabled", lambda: True)
    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)

    solver._set_os_cursor_position(object(), 960, 540)

    assert events[0] == ("set", 960, 540)
    assert events[1][0] == "mouse_event"
    assert events[1][1] == 0x0001 | 0x4000 | 0x8000
    assert 32760 <= int(events[1][2]) <= 32810
    assert 32760 <= int(events[1][3]) <= 32820


def test_os_drag_skips_when_window_focus_fails(monkeypatch) -> None:
    class FakePyAutoGUI:
        FAILSAFE = True
        PAUSE = 0

        def __getattr__(self, name):
            raise AssertionError(f"unexpected pyautogui call: {name}")

    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI())
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._focus_os_window = lambda: False

    assert solver._do_drag_os(100, 50, 260) is None
    assert solver.last_failure_reason == "window_focus_failed"


def test_os_drag_handles_window_focus_exception(monkeypatch) -> None:
    class FakePyAutoGUI:
        FAILSAFE = True
        PAUSE = 0

        def __getattr__(self, name):
            raise AssertionError(f"unexpected pyautogui call: {name}")

    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI())
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._focus_os_window = lambda: (_ for _ in ()).throw(RuntimeError("focus API failed"))

    assert solver._do_drag_os(100, 50, 260) is None
    assert solver.last_failure_reason == "window_focus_failed"


def test_os_drag_releases_mouse_after_move_exception(monkeypatch) -> None:
    calls: list[str] = []

    class FakePyAutoGUI:
        FAILSAFE = True
        PAUSE = 0

        def moveTo(self, *_args, **_kwargs):
            calls.append("move")
            if calls.count("move") == 3:
                raise RuntimeError("move failed")

        def mouseDown(self):
            calls.append("down")

        def mouseUp(self):
            calls.append("up")

    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI())
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._focus_os_window = lambda: True
    solver._map_css_to_screen = lambda *_args, **_kwargs: {
        "x": 100.0, "y": 50.0, "distance": 260.0, "source": "test",
        "located": False, "clipped": False,
    }
    solver._os_drag_profile = lambda _index=0: {
        "name": "test", "pre_pause": (0, 0), "press_hold": (0, 0),
        "approach_duration": (0, 0), "start_duration": (0, 0),
    }
    solver._os_drag_warmup_points = lambda *_args: []
    solver._os_drag_track = lambda *_args: ([0.5], [0])

    assert solver._do_drag_os(100, 50, 260) is None
    assert solver.last_failure_reason == "mouse_drag_exception"
    assert calls[-1] == "up"


def test_os_drag_skips_unverified_slider_screen_mapping(monkeypatch) -> None:
    class FakePyAutoGUI:
        FAILSAFE = True
        PAUSE = 0

        def __getattr__(self, name):
            raise AssertionError(f"unexpected pyautogui call: {name}")

    map_calls: list[bool] = []
    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI())
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._focus_os_window = lambda: True

    def unverified_map(*_args, **_kwargs):
        map_calls.append(True)
        return {
            "x": 100.0,
            "y": 50.0,
            "distance": 260.0,
            "source": "test",
            "located": False,
            "clipped": False,
        }

    solver._map_css_to_screen = unverified_map

    assert solver._do_drag_os(100, 50, 260, slider_info={"x": 80, "y": 35}) is None
    assert solver.last_failure_reason == "screen_mapping_unverified"
    assert len(map_calls) == 3


def test_clamp_search_region_trims_negative_region_to_screen() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    clamped = solver._clamp_search_region((-65, 212, 2177, 1437), (3840, 2160))

    assert clamped == (0, 212, 2112, 1437)


def test_os_drag_track_produces_monotonic_eased_steps(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.setattr(captcha_solver.random, "uniform", lambda start, end: (start + end) / 2)
    profile = solver._os_drag_profile()

    fracs, dwells = solver._os_drag_track(320, profile)

    assert len(fracs) == len(dwells)
    assert len(fracs) >= 32
    assert fracs[0] > 0
    assert fracs[-1] == 1.0
    assert all(left < right for left, right in zip(fracs, fracs[1:]))
    assert all(0.006 <= dwell <= 0.09 for dwell in dwells)


def test_os_drag_release_plan_releases_beyond_target(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.setattr(captcha_solver.random, "uniform", lambda start, end: (start + end) / 2)
    profile = solver._os_drag_profile()

    peak_x, settle_xs, release_x = solver._os_drag_release_plan(100.0, 300.0, profile)

    assert peak_x > 400.0
    assert release_x > 400.0
    assert release_x < peak_x
    assert settle_xs
    assert settle_xs[-1] == release_x
    assert all(left >= right for left, right in zip(settle_xs, settle_xs[1:]))


def test_os_drag_profile_switches_variants_by_index() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    first = solver._os_drag_profile(0)
    second = solver._os_drag_profile(1)
    third = solver._os_drag_profile(2)

    assert first["name"] == "overshoot_release"
    assert second["name"] == "legacy_exact_release"
    assert third["name"] == "dense_slow_tail"
    assert second["release_mode"] == "exact_release"
    assert second["warmup_steps"] == (2, 3)


def test_os_drag_warmup_points_respect_profile(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.setattr(captcha_solver.random, "uniform", lambda start, end: (start + end) / 2)
    monkeypatch.setattr(captcha_solver.random, "gauss", lambda mean, _sigma: mean)
    profile = solver._os_drag_profile(0)

    points = solver._os_drag_warmup_points(100.0, 200.0, profile)

    assert len(points) == 2
    assert points[0][0] > 100.0
    assert points[-1][0] > points[0][0]


def test_nc_retry_click_candidates_prioritize_retry_text_then_widget() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    candidates = solver._nc_retry_click_candidates({
        "retryText": {"x": 10.0, "y": 20.0, "width": 90.0, "height": 30.0},
        "widget": {"x": 100.0, "y": 200.0, "width": 300.0, "height": 40.0},
    })

    assert candidates
    assert candidates[0]["label"] == "widget_centerline"
    assert any(candidate["label"] == "widget_centerline" for candidate in candidates)


def test_reset_failed_nc_challenge_tries_multiple_click_points_until_slider_returns(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    clicks: list[tuple[float, float]] = []
    outcomes = [
        {"authenticated": False},
        {"slider": {"x": 1, "y": 2, "width": 3, "height": 4}},
    ]

    solver._nc_retry_targets = lambda: {
        "retryText": {"x": 10.0, "y": 20.0, "width": 100.0, "height": 30.0},
        "widget": {"x": 200.0, "y": 300.0, "width": 280.0, "height": 40.0},
    }
    solver._click_css_point = lambda x, y, **_kwargs: clicks.append((x, y)) or True
    solver._nc_retry_outcome = lambda timeout_seconds=8.0: outcomes.pop(0)
    monkeypatch.setattr(captcha_solver.time, "sleep", lambda _seconds: None)

    assert solver._reset_failed_nc_challenge() is True
    assert len(clicks) == 2
