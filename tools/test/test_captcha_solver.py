from __future__ import annotations

import json

from src import captcha_solver


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
    assert ("PUT", "http://host.docker.internal:9223/json/new?https://contest.local/challenge?__captcha_solver_bg=1", 5) in requested
    assert connected_urls == ["ws://host.docker.internal:9223/devtools/page/new-target"]


def test_compact_cdp_pages_closes_all_page_targets_at_threshold(monkeypatch) -> None:
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

    monkeypatch.setattr(captcha_solver.requests, "get", fake_get)

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://contest.local/challenge?__captcha_solver_bg=1",
        cdp_endpoint="http://host.docker.internal:9223",
    )
    solver.ws = FakeWebSocket()
    solver.target_id = "page-3"
    solver.target_ws_url = "ws://cached-target"

    summary = solver._compact_cdp_pages_if_needed()

    assert summary == {"triggered": True, "page_count": 12, "closed": 12}
    assert closed_ws["count"] == 1
    assert solver.ws is None
    assert solver.target_id is None
    assert solver.target_ws_url is None
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
    assert ("PUT", "http://host.docker.internal:9223/json/new?https://contest.local/challenge?__captcha_solver_bg=1", 5) in requested
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


def test_solver_closes_owned_target_tab_after_userscript_success(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://contest.local/challenge?__captcha_solver_bg=1",
        cdp_endpoint="http://host.docker.internal:9223",
    )
    solver.target_id = "owned-target"
    solver._opened_target_ids.add("owned-target")
    closed: list[str] = []

    solver._preflight_current_challenge = lambda: {
        "connected": False,
        "manual_required": False,
        "has_slider": False,
    }
    solver._headed_playwright_enabled = lambda: False
    solver._solve_with_userscript = lambda: True
    solver._close_cdp_target = lambda target_id: closed.append(target_id) or True

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
    connection_kwargs: list[dict[str, bool]] = []

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

    def fake_create_connection(_ws_url: str, **kwargs: bool) -> FakeWebSocket:
        connection_kwargs.append(kwargs)
        return FakeWebSocket()

    monkeypatch.setattr(captcha_solver.websocket, "create_connection", fake_create_connection)

    assert solver.connect_tab() is True
    assert connection_kwargs == [{"suppress_origin": True}]


def test_send_cdp_mouse_event_is_fire_and_forget() -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent_payloads: list[dict[str, object]] = []
            self.recv_count = 0

        def send(self, payload: str) -> None:
            self.sent_payloads.append(json.loads(payload))

        def recv(self) -> str:
            self.recv_count += 1
            return json.dumps({"id": 999, "result": {}})

    ws = FakeWebSocket()
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.ws = ws

    solver._send_cdp(
        "Input.dispatchMouseEvent",
        {"type": "mouseMoved", "x": 10, "y": 20, "button": "none"},
    )

    assert len(ws.sent_payloads) == 1
    assert ws.sent_payloads[0]["method"] == "Input.dispatchMouseEvent"
    assert ws.recv_count == 0


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

    assert solver.solve() is True
    assert calls == ["userscript"]


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
    solver._do_drag = lambda _x, _y, _distance: calls.__setitem__("drag", calls["drag"] + 1)
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
