from tools.test.taobao_login_health_test_context import *  # noqa: F401,F403


def test_main_accepts_repeated_sample_url_and_exits_zero_for_partial_available(monkeypatch, capsys) -> None:
    def _wait_for_samples(**kwargs):
        assert kwargs["sample_urls"] == (
            "https://sf.taobao.com/list/blocked.htm",
            "https://sf.taobao.com/list/healthy.htm",
        )
        assert kwargs["open_login"] is True
        assert kwargs["trigger_captcha_solver"] is True
        assert kwargs["api_base_url"] == "http://127.0.0.1:8001/api"
        return {
            "status": "partial_available",
            "healthy": True,
            "sample_count": 2,
            "healthy_samples": 1,
            "blocked_samples": 1,
        }

    monkeypatch.setattr(taobao_login_health, "wait_for_taobao_health_samples", _wait_for_samples)

    exit_code = taobao_login_health.main(
        [
            "--sample-url",
            "https://sf.taobao.com/list/blocked.htm",
            "--sample-url",
            "https://sf.taobao.com/list/healthy.htm",
            "--open-login",
            "--trigger-captcha-solver",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["status"] == "partial_available"
    assert output["healthy"] is True

def test_wait_for_taobao_health_samples_retries_until_healthy_and_opens_once(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    sleep_calls: list[int] = []
    monotonic_values = iter([100.0, 100.1])
    responses = [
        {
            "status": "all_samples_blocked",
            "healthy": False,
            "opened_url": "https://login.taobao.com/member/login.jhtml",
        },
        {
            "status": "healthy_list_payload",
            "healthy": True,
        },
    ]

    def _check_taobao_health_samples(**kwargs):
        calls.append(
            {
                "open_login": kwargs["open_login"],
                "sample_urls": tuple(kwargs["sample_urls"]),
                "trigger_captcha_solver": kwargs["trigger_captcha_solver"],
            }
        )
        return dict(responses.pop(0))

    monkeypatch.setattr(taobao_login_health, "check_taobao_health_samples", _check_taobao_health_samples)
    monkeypatch.setattr(taobao_login_health.time, "monotonic", lambda: next(monotonic_values))

    result = taobao_login_health.wait_for_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=(
            "https://sf.taobao.com/list/blocked.htm",
            "https://sf.taobao.com/list/healthy.htm",
        ),
        open_login=True,
        trigger_captcha_solver=False,
        api_base_url="http://127.0.0.1:8001/api",
        wait_seconds=10,
        poll_seconds=3,
        sleep_func=lambda seconds: sleep_calls.append(seconds),
    )

    assert result["status"] == "healthy_list_payload"
    assert result["healthy"] is True
    assert result["attempts"] == 2
    assert calls == [
        {
            "open_login": True,
            "sample_urls": (
                "https://sf.taobao.com/list/blocked.htm",
                "https://sf.taobao.com/list/healthy.htm",
            ),
            "trigger_captcha_solver": False,
        },
        {
            "open_login": False,
            "sample_urls": (
                "https://sf.taobao.com/list/blocked.htm",
                "https://sf.taobao.com/list/healthy.htm",
            ),
            "trigger_captcha_solver": False,
        },
    ]
    assert sleep_calls == [3]

def test_direct_script_execution_adds_repo_root_to_python_path() -> None:
    script = REPO_ROOT.joinpath("tools", "taobao_login_health.py").read_text(encoding="utf-8")

    assert "REPO_ROOT = Path(__file__).resolve().parents[1]" in script
    assert "sys.path.insert(0, str(REPO_ROOT))" in script

def test_taobao_login_health_uses_extended_cdp_connect_timeout_like_live_smoke() -> None:
    script = REPO_ROOT.joinpath("tools", "taobao_login_health.py").read_text(encoding="utf-8")

    assert "DEFAULT_CDP_CONNECT_TIMEOUT_MS = 120000" in script
    assert "playwright.chromium.connect_over_cdp(resolve_playwright_cdp_endpoint(cdp_endpoint), timeout=DEFAULT_CDP_CONNECT_TIMEOUT_MS)" in script

def test_resolve_playwright_cdp_endpoint_rewrites_remote_browser_websocket(monkeypatch) -> None:
    from tools import browserless_seed_probe

    calls: list[str] = []
    monkeypatch.setattr(
        browserless_seed_probe,
        "_resolve_cdp_endpoint",
        lambda endpoint: calls.append(endpoint) or "ws://pc2-browser-solver:9224/devtools/browser/browser-id",
    )

    resolved = taobao_login_health.resolve_playwright_cdp_endpoint("http://pc2-browser-solver:9224")

    assert resolved == "ws://pc2-browser-solver:9224/devtools/browser/browser-id"
    assert calls == ["http://pc2-browser-solver:9224"]

def test_resolve_playwright_cdp_endpoint_preserves_loopback_without_probe(monkeypatch) -> None:
    from tools import browserless_seed_probe

    monkeypatch.setattr(
        browserless_seed_probe,
        "_resolve_cdp_endpoint",
        lambda _endpoint: (_ for _ in ()).throw(AssertionError("loopback CDP must not be probed")),
    )

    assert taobao_login_health.resolve_playwright_cdp_endpoint("http://127.0.0.1:9223") == "http://127.0.0.1:9223"

def test_fetch_health_samples_via_cdp_cookie_http_uses_websocket_cookie_export_and_http_probe(monkeypatch) -> None:
    export_calls: list[tuple[str, tuple[str, ...]]] = []
    probe_calls: list[tuple[str, tuple[dict[str, object], ...]]] = []

    class FakeBrowserlessSeedProbe:
        DEFAULT_COOKIE_ORIGINS = ("https://sf.taobao.com", "https://login.taobao.com")

        @staticmethod
        def _export_cdp_cookies_via_websocket(cdp_endpoint: str, origins: tuple[str, ...]) -> list[dict[str, object]]:
            export_calls.append((cdp_endpoint, tuple(origins)))
            return [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]

        @staticmethod
        def build_session_from_playwright_cookies(cookies: list[dict[str, object]]) -> object:
            return {"cookie_count": len(cookies)}

        @staticmethod
        def build_navigation_headers(*, target_url: str, user_agent: str, referer_url: str) -> dict[str, str]:
            return {
                "User-Agent": user_agent,
                "Referer": referer_url,
                "Accept": "text/html",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
            }

        @staticmethod
        def summarize_cookie_snapshot(cookies: list[dict[str, object]]) -> dict[str, object]:
            return {
                "count": len(cookies),
                "domains": [".taobao.com"],
                "names": ["cookie2"],
                "secure_count": 0,
                "http_only_count": 0,
                "session_count": 1,
                "persistent_count": 0,
                "earliest_expiry": None,
                "latest_expiry": None,
            }

        @staticmethod
        def probe_seed_page(url: str, *, cookies, session=None, timeout: int = 30) -> dict[str, object]:
            probe_calls.append((url, tuple(cookies)))
            if url.endswith("healthy.htm"):
                return {
                    "status": 200,
                    "final_url": url,
                    "has_script": True,
                    "item_count": 1,
                    "first_ids": ["1001"],
                    "first_urls": ["https://sf.taobao.com/item/1001"],
                    "body_has_login": False,
                    "body_has_captcha": False,
                    "body_has_punish": False,
                    "body_has_challenge": False,
                    "body_snippet": "healthy",
                }
            return {
                "status": 200,
                "final_url": "https://login.taobao.com/havanaone/login/login.htm",
                "has_script": False,
                "item_count": None,
                "first_ids": [],
                "first_urls": [],
                "body_has_login": True,
                "body_has_captcha": True,
                "body_has_punish": False,
                "body_has_challenge": True,
                "body_snippet": "blocked",
            }

    monkeypatch.setitem(sys.modules, "tools.browserless_seed_probe", FakeBrowserlessSeedProbe)
    monkeypatch.setattr(tools_package, "browserless_seed_probe", FakeBrowserlessSeedProbe, raising=False)

    results = taobao_login_health.fetch_health_samples_via_cdp_cookie_http(
        "http://127.0.0.1:9223",
        (
            "https://sf.taobao.com/list/blocked.htm",
            "https://sf.taobao.com/list/healthy.htm",
        ),
    )

    assert export_calls == [
        (
            "http://127.0.0.1:9223",
            ("https://sf.taobao.com", "https://login.taobao.com"),
        )
    ]
    assert probe_calls == [
        (
            "https://sf.taobao.com/list/blocked.htm",
            ({"name": "cookie2", "value": "abc", "domain": ".taobao.com"},),
        ),
        (
            "https://sf.taobao.com/list/healthy.htm",
            ({"name": "cookie2", "value": "abc", "domain": ".taobao.com"},),
        ),
    ]
    assert [result["status"] for result in results] == ["captcha_page", "healthy_list_payload"]
    assert [result["probe_transport"] for result in results] == ["cookie_http", "cookie_http"]
    assert all("names" not in result["cookie_summary"] for result in results)
    assert all(result["cookie_summary"]["count"] == 1 for result in results)

def test_fetch_pages_via_cdp_reuses_single_browser_connection_across_urls(monkeypatch) -> None:
    events: list[str] = []
    html_by_url = {
        "https://sf.taobao.com/list/a.htm": "<html>A</html>",
        "https://sf.taobao.com/list/b.htm": "<html>B</html>",
    }

    class FakePage:
        def __init__(self) -> None:
            self.url = "about:blank"

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            events.append(f"goto:{url}:{wait_until}:{timeout}")
            self.url = url

        def content(self) -> str:
            return html_by_url[self.url]

        def close(self) -> None:
            events.append(f"close:{self.url}")

    class FakeContext:
        def new_page(self) -> FakePage:
            events.append("new_page")
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self) -> None:
            events.append("browser_close")

    class FakeChromium:
        def connect_over_cdp(self, endpoint: str, timeout: int | None = None) -> FakeBrowser:
            assert timeout == taobao_login_health.DEFAULT_CDP_CONNECT_TIMEOUT_MS
            events.append(f"connect:{endpoint}")
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            events.append("playwright_close")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = lambda: FakeSyncPlaywright()
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    results = taobao_login_health.fetch_pages_via_cdp(
        "http://127.0.0.1:9223",
        (
            "https://sf.taobao.com/list/a.htm",
            "https://sf.taobao.com/list/b.htm",
        ),
    )

    assert results == [
        ("<html>A</html>", "https://sf.taobao.com/list/a.htm"),
        ("<html>B</html>", "https://sf.taobao.com/list/b.htm"),
    ]
    assert events == [
        "connect:http://127.0.0.1:9223",
        "new_page",
        "goto:https://sf.taobao.com/list/a.htm:domcontentloaded:30000",
        "close:https://sf.taobao.com/list/a.htm",
        "new_page",
        "goto:https://sf.taobao.com/list/b.htm:domcontentloaded:30000",
        "close:https://sf.taobao.com/list/b.htm",
        "playwright_close",
    ]

def test_open_page_via_cdp_activates_existing_worker_master_over_http(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

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
        if full_url.endswith("/json/activate/worker-1"):
            return FakeResponse("Target activated")
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

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/?__captcha_worker_master=1",
    )

    assert final_url == "https://sf.taobao.com/?__captcha_worker_master=1"
    assert calls == [
        ("GET", "http://127.0.0.1:9223/json/list"),
        ("GET", "http://127.0.0.1:9223/json/activate/worker-1"),
    ]
