from tools.test.taobao_login_health_test_context import *  # noqa: F401,F403


def test_open_page_via_cdp_opens_solver_target_over_http_when_only_worker_exists(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    solver_url = "https://contest.local/auth?__captcha_solver_bg=1"

    class FakeResponse:
        def __init__(self, body: str) -> None:
            self._body = body.encode("utf-8")

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return self._body

    def _fake_urlopen(request, timeout: int):
        method = getattr(request, "method", "GET")
        full_url = request.get_full_url()
        calls.append((method, full_url))
        if full_url.endswith("/json/list"):
            return FakeResponse(
                json.dumps(
                    [
                        {
                            "id": "worker-1",
                            "type": "page",
                            "url": "https://sf.taobao.com/?__captcha_worker_master=1",
                        }
                    ]
                )
            )
        if "/json/new?" in full_url:
            return FakeResponse(json.dumps({"id": "solver-1", "type": "page", "url": solver_url}))
        raise AssertionError(f"unexpected CDP HTTP call: {full_url}")

    def _raise_if_playwright_used():
        raise AssertionError("HTTP open path should not need Playwright")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = _raise_if_playwright_used
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)
    monkeypatch.setattr(taobao_login_health, "urlopen", _fake_urlopen)

    final_url = taobao_login_health.open_page_via_cdp("http://127.0.0.1:9223", solver_url)

    assert final_url == solver_url
    assert calls[0] == ("GET", "http://127.0.0.1:9223/json/list")
    assert calls[1][0] == "PUT"
    assert calls[1][1].startswith("http://127.0.0.1:9223/json/new?")

def test_open_page_via_cdp_http_closes_accumulated_pages_before_opening_twelfth(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    solver_url = "https://contest.local/auth?__captcha_solver_bg=1"
    current_targets: list[dict[str, str]] = [
        {"id": f"page-{index}", "type": "page", "url": f"https://stale.local/{index}"}
        for index in range(11)
    ]
    current_targets.append({"id": "worker-1", "type": "service_worker", "url": "chrome-extension://worker"})

    class FakeResponse:
        def __init__(self, body: str) -> None:
            self._body = body.encode("utf-8")

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return self._body

    def _fake_urlopen(request, timeout: int):
        method = getattr(request, "method", "GET")
        full_url = request.get_full_url()
        calls.append((method, full_url))
        if full_url.endswith("/json/list"):
            return FakeResponse(json.dumps(current_targets))
        if "/json/close/" in full_url:
            target_id = full_url.rsplit("/", 1)[-1]
            current_targets[:] = [target for target in current_targets if target.get("id") != target_id]
            return FakeResponse("Target is closing")
        if "/json/new?" in full_url:
            return FakeResponse(json.dumps({"id": "solver-1", "type": "page", "url": solver_url}))
        raise AssertionError(f"unexpected CDP HTTP call: {full_url}")

    monkeypatch.setattr(taobao_login_health, "urlopen", _fake_urlopen)

    final_url = taobao_login_health.open_page_via_cdp_http("http://127.0.0.1:9223", solver_url)

    assert final_url == solver_url
    close_urls = [url for method, url in calls if method == "GET" and "/json/close/" in url]
    assert close_urls == [f"http://127.0.0.1:9223/json/close/page-{index}" for index in range(11)]
    assert "http://127.0.0.1:9223/json/close/worker-1" not in close_urls
    assert any(method == "PUT" and "/json/new?" in url for method, url in calls)

def test_queue_captcha_task_via_cdp_reuses_existing_solver_target(monkeypatch) -> None:
    target_url = "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"
    existing_target = {
        "id": "punish-1",
        "type": "page",
        "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5step=1",
    }
    activated: list[tuple[str, object]] = []
    monkeypatch.setattr(
        taobao_login_health,
        "find_cdp_target",
        lambda _endpoint, requested_url: existing_target if requested_url == target_url else None,
    )
    monkeypatch.setattr(
        taobao_login_health,
        "activate_cdp_target",
        lambda endpoint, target: activated.append((endpoint, target)),
    )
    monkeypatch.setattr(
        taobao_login_health,
        "compact_cdp_pages_if_needed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("existing solver target must avoid worker creation")
        ),
    )

    result = taobao_login_health.queue_captcha_task_via_cdp(
        "http://127.0.0.1:9223",
        target_url,
    )

    assert result == {
        "status": "existing_solver_target",
        "worker_url": "https://sf.taobao.com/?__captcha_worker_master=1",
        "target_url": target_url,
    }
    assert activated == [("http://127.0.0.1:9223", existing_target)]

def test_queue_captcha_task_via_cdp_posts_message_to_worker_master(monkeypatch) -> None:
    http_calls: list[tuple[str, str]] = []
    ws_urls: list[str] = []
    ws_messages: list[dict[str, Any]] = []

    class FakeResponse:
        def __init__(self, body: str) -> None:
            self._body = body.encode("utf-8")

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return self._body

    def _fake_urlopen(request, timeout: int):
        method = getattr(request, "method", "GET")
        full_url = request.get_full_url()
        http_calls.append((method, full_url))
        if full_url.endswith("/json/list"):
            return FakeResponse(
                json.dumps(
                    [
                        {
                            "id": "worker-1",
                            "type": "page",
                            "url": "https://sf.taobao.com/?__captcha_worker_master=1",
                            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/worker-1",
                        }
                    ]
                )
            )
        if full_url.endswith("/json/activate/worker-1"):
            return FakeResponse("Target activated")
        raise AssertionError(f"unexpected CDP HTTP call: {full_url}")

    class FakeWebSocket:
        def send(self, raw: str) -> None:
            ws_messages.append(json.loads(raw))

        def recv(self) -> str:
            value = True
            return json.dumps({"id": ws_messages[-1]["id"], "result": {"result": {"type": "boolean", "value": True}}})

        def close(self) -> None:
            ws_messages.append({"closed": True})

    def _fake_create_connection(ws_url: str, **kwargs):
        ws_urls.append(ws_url)
        assert kwargs.get("suppress_origin") is True
        return FakeWebSocket()

    monkeypatch.setattr(taobao_login_health, "urlopen", _fake_urlopen)
    monkeypatch.setattr(taobao_login_health.websocket, "create_connection", _fake_create_connection)

    result = taobao_login_health.queue_captcha_task_via_cdp(
        "http://127.0.0.1:9223",
        "https://contest.local/auth?__captcha_solver_bg=1",
    )

    assert result["status"] == "queued"
    assert result["worker_url"] == "https://sf.taobao.com/?__captcha_worker_master=1"
    assert result["target_url"] == "https://contest.local/auth?__captcha_solver_bg=1"
    assert ("GET", "http://127.0.0.1:9223/json/list") in http_calls
    assert ("GET", "http://127.0.0.1:9223/json/activate/worker-1") in http_calls
    assert ws_urls == [
        "ws://127.0.0.1:9223/devtools/page/worker-1",
        "ws://127.0.0.1:9223/devtools/page/worker-1",
    ]
    evaluate_messages = [message for message in ws_messages if message.get("method") == "Runtime.evaluate"]
    evaluate = evaluate_messages[0]
    assert evaluate["method"] == "Runtime.evaluate"
    assert "window.__fapaifangCaptchaWorkerBridgeInstalled" in evaluate["params"]["expression"]
    assert "data-fapaifang-captcha-worker-bridge" in evaluate["params"]["expression"]
    expression = evaluate_messages[1]["params"]["expression"]
    assert "fapaifang-captcha-worker-bridge" in expression
    assert "queue-captcha-task" in expression
    assert "https://contest.local/auth?__captcha_solver_bg=1" in expression

def test_queue_captcha_task_via_cdp_navigates_worker_when_bridge_is_missing(monkeypatch) -> None:
    ws_messages: list[dict[str, Any]] = []

    class FakeResponse:
        def __init__(self, body: str) -> None:
            self._body = body.encode("utf-8")

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return self._body

    def _fake_urlopen(request, timeout: int):
        full_url = request.get_full_url()
        if full_url.endswith("/json/list"):
            return FakeResponse(
                json.dumps(
                    [
                        {
                            "id": "worker-1",
                            "type": "page",
                            "url": "https://sf.taobao.com/?__captcha_worker_master=1",
                            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/worker-1",
                        }
                    ]
                )
            )
        if full_url.endswith("/json/activate/worker-1"):
            return FakeResponse("Target activated")
        raise AssertionError(f"unexpected CDP HTTP call: {full_url}")

    class FakeWebSocket:
        def send(self, raw: str) -> None:
            ws_messages.append(json.loads(raw))

        def recv(self) -> str:
            expression = ws_messages[-1]["params"]["expression"]
            value = False if "window.__fapaifangCaptchaWorkerBridgeInstalled" in expression else True
            return json.dumps({"id": ws_messages[-1]["id"], "result": {"result": {"type": "boolean", "value": value}}})

        def close(self) -> None:
            ws_messages.append({"closed": True})

    monkeypatch.setattr(taobao_login_health, "urlopen", _fake_urlopen)
    monkeypatch.setattr(
        taobao_login_health.websocket,
        "create_connection",
        lambda _ws_url, **_kwargs: FakeWebSocket(),
    )

    target_url = "https://contest.local/auth?__captcha_solver_bg=1"
    result = taobao_login_health.queue_captcha_task_via_cdp("http://127.0.0.1:9223", target_url)

    assert result["status"] == "worker_navigated_without_bridge"
    assert result["target_url"] == target_url
    evaluate_messages = [message for message in ws_messages if message.get("method") == "Runtime.evaluate"]
    assert "window.__fapaifangCaptchaWorkerBridgeInstalled" in evaluate_messages[0]["params"]["expression"]
    assert "data-fapaifang-captcha-worker-bridge" in evaluate_messages[0]["params"]["expression"]
    assert f"window.location.href = {json.dumps(target_url)}" in evaluate_messages[1]["params"]["expression"]

def test_queue_captcha_task_via_cdp_returns_worker_unavailable_after_open_retry(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    sleeps: list[float] = []
    worker_url = "https://sf.taobao.com/?__captcha_worker_master=1"
    target_url = "https://contest.local/auth?__captcha_solver_bg=1"
    find_results = iter(
        [
            None,
            None,
            None,
        ]
    )

    monkeypatch.setattr(
        taobao_login_health,
        "compact_cdp_pages_if_needed",
        lambda cdp_endpoint, reserve_for_new_page=False: calls.append(
            ("compact", {"cdp_endpoint": cdp_endpoint, "reserve_for_new_page": reserve_for_new_page})
        )
        or {"triggered": False},
    )
    monkeypatch.setattr(
        taobao_login_health,
        "find_cdp_target",
        lambda cdp_endpoint, url: calls.append(("find", {"cdp_endpoint": cdp_endpoint, "url": url})) or next(find_results),
    )
    monkeypatch.setattr(
        taobao_login_health,
        "read_cdp_json",
        lambda cdp_endpoint, path, method="GET": calls.append(
            ("read", {"cdp_endpoint": cdp_endpoint, "path": path, "method": method})
        )
        or {"id": "worker-1", "type": "page", "url": worker_url},
    )
    monkeypatch.setattr(taobao_login_health.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = taobao_login_health.queue_captcha_task_via_cdp("http://127.0.0.1:9223", target_url)

    assert result == {
        "status": "worker_unavailable",
        "worker_url": worker_url,
        "target_url": target_url,
    }
    assert calls == [
        ("find", {"cdp_endpoint": "http://127.0.0.1:9223", "url": target_url}),
        ("compact", {"cdp_endpoint": "http://127.0.0.1:9223", "reserve_for_new_page": True}),
        ("find", {"cdp_endpoint": "http://127.0.0.1:9223", "url": worker_url}),
        ("read", {"cdp_endpoint": "http://127.0.0.1:9223", "path": "/json/new?https%3A%2F%2Fsf.taobao.com%2F%3F__captcha_worker_master%3D1", "method": "PUT"}),
        ("find", {"cdp_endpoint": "http://127.0.0.1:9223", "url": worker_url}),
    ]
    assert sleeps == [1]

def test_queue_captcha_task_via_cdp_returns_worker_missing_websocket_after_refresh(monkeypatch) -> None:
    worker_url = "https://sf.taobao.com/?__captcha_worker_master=1"
    target_url = "https://contest.local/auth?__captcha_solver_bg=1"
    target_without_ws = {
        "id": "worker-1",
        "type": "page",
        "url": worker_url,
    }
    activate_calls: list[tuple[str, str]] = []
    find_results = iter(
        [
            None,
            target_without_ws,
            target_without_ws,
        ]
    )

    monkeypatch.setattr(taobao_login_health, "compact_cdp_pages_if_needed", lambda *_args, **_kwargs: {"triggered": False})
    monkeypatch.setattr(taobao_login_health, "read_cdp_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("open should not run when worker target already exists")))
    monkeypatch.setattr(taobao_login_health, "find_cdp_target", lambda *_args, **_kwargs: next(find_results))
    monkeypatch.setattr(
        taobao_login_health,
        "activate_cdp_target",
        lambda cdp_endpoint, target: activate_calls.append((cdp_endpoint, str(target.get("id")))) or True,
    )
    monkeypatch.setattr(
        taobao_login_health,
        "evaluate_cdp_expression",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("bridge evaluation requires a websocket")),
    )

    result = taobao_login_health.queue_captcha_task_via_cdp("http://127.0.0.1:9223", target_url)

    assert result == {
        "status": "worker_missing_websocket",
        "worker_url": worker_url,
        "target_url": target_url,
    }
    assert activate_calls == [("http://127.0.0.1:9223", "worker-1")]
