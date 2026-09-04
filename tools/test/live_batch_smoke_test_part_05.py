from tools.test.live_batch_smoke_test_context import *  # noqa: F401,F403


def test_request_captcha_solver_can_force_manual_auth_handoff(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        taobao_login_health,
        "build_captcha_solver_target_url",
        lambda url: url,
    )

    def _report(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"status": "manual_required"}

    monkeypatch.setattr(taobao_login_health, "report_captcha_via_api", _report)

    result = live_batch_smoke.request_captcha_solver(
        "http://127.0.0.1:9225",
        "https://sf.taobao.com/list/page=10",
        api_base_url="http://collection-api.test/api",
        manual_only=True,
    )

    assert result == {"status": "manual_required"}
    assert captured["kwargs"] == {"manual_only": True}

def test_fetch_list_page_passes_explicit_api_base_url_to_solver(monkeypatch) -> None:
    class _ChallengeResponse:
        text = "<script>location.href='_____tmd_____/punish?x5secdata=abc'</script>"
        url = "https://sf.taobao.com/list/page=2"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _ChallengeHttp:
        @staticmethod
        def get(*_args, **_kwargs):
            return _ChallengeResponse()

    solver_calls: list[dict[str, str | None]] = []

    monkeypatch.setenv("FAPAI_LIST_BROWSER_FALLBACK", "0")
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_browser_list_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser fallback should be disabled")),
    )
    monkeypatch.setattr(
        live_batch_smoke,
        "request_captcha_solver",
        lambda cdp_endpoint, target_url, **kwargs: solver_calls.append(
            {
                "cdp_endpoint": cdp_endpoint,
                "target_url": target_url,
                "api_base_url": kwargs.get("api_base_url"),
            }
        )
        or {"status": "solving"},
    )

    live_batch_smoke.fetch_list_page(
        _ChallengeHttp(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=2",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
        solver_enabled=True,
        api_base_url="http://collection-api.test/api",
    )

    assert solver_calls == [
        {
            "cdp_endpoint": "http://127.0.0.1:9223",
            "target_url": "https://sf.taobao.com/list/page=2",
            "api_base_url": "http://collection-api.test/api",
        }
    ]

def test_fetch_detail_html_raises_challenge_when_browser_fallback_disabled(monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

    class _ChallengeResponse:
        text = "<html>captcha challenge</html>"
        url = "https://login.taobao.com/challenge"
        content = text.encode("utf-8")

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _ChallengeHttp:
        @staticmethod
        def get(*_args, **_kwargs):
            return _ChallengeResponse()

    monkeypatch.setenv("FAPAI_DETAIL_BROWSER_FALLBACK", "0")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "is_challenge_page", lambda _html, _url: True)
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_detail_with_browser",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("detail browser fallback should be disabled")),
    )

    with pytest.raises(RuntimeError, match="anti-bot challenge"):
        live_batch_smoke.fetch_detail_html(
            _ChallengeHttp(),
            {"id": "3001", "url": "https://sf-item.taobao.com/sf_item/3001.htm"},
            {},
            cdp_endpoint="http://127.0.0.1:1",
            referer_url="https://sf.taobao.com/list/50025969__2.htm",
        )

def test_fetch_detail_html_uses_browser_fallback_when_http_detail_returns_challenge(monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

    class _ChallengeResponse:
        text = "<html>captcha challenge</html>"
        url = "https://login.taobao.com/challenge"
        content = text.encode("utf-8")

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _ChallengeHttp:
        @staticmethod
        def get(*_args, **_kwargs):
            return _ChallengeResponse()

    browser_calls: list[tuple[dict[str, object], str]] = []

    monkeypatch.setenv("FAPAI_DETAIL_BROWSER_FALLBACK", "1")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "is_challenge_page", lambda _html, _url: True)
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_detail_with_browser",
        lambda seed, *, cdp_endpoint: browser_calls.append((dict(seed), cdp_endpoint))
        or (
            "<html>browser detail</html>",
            "https://sf-item.taobao.com/sf_item/3002.htm",
            len(b"<html>browser detail</html>"),
            "browser_navigation",
        ),
    )

    html, final_url, content_length, method = live_batch_smoke.fetch_detail_html(
        _ChallengeHttp(),
        {"id": "3002", "url": "https://sf-item.taobao.com/sf_item/3002.htm"},
        {},
        cdp_endpoint="http://127.0.0.1:9223",
        referer_url="https://sf.taobao.com/list/50025969__2.htm",
    )

    assert html == "<html>browser detail</html>"
    assert final_url == "https://sf-item.taobao.com/sf_item/3002.htm"
    assert content_length == len(b"<html>browser detail</html>")
    assert method == "browser_navigation"
    assert browser_calls == [
        (
            {"id": "3002", "url": "https://sf-item.taobao.com/sf_item/3002.htm"},
            "http://127.0.0.1:9223",
        )
    ]

def test_fetch_list_page_uses_browser_navigation_headers(monkeypatch) -> None:
    captured_headers: list[dict[str, str]] = []

    class _OkResponse:
        text = "<html><script>var sf-item-list-data = {};</script></html>"
        url = "https://sf.taobao.com/list/page=7"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _Http:
        @staticmethod
        def get(*_args, **kwargs):
            captured_headers.append(dict(kwargs["headers"]))
            return _OkResponse()

    class _FakeProbe:
        @staticmethod
        def build_navigation_headers(*, target_url: str, user_agent: str, referer_url: str) -> dict[str, str]:
            return {
                "User-Agent": user_agent,
                "Referer": referer_url,
                "Accept": "text/html",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
            }

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "is_challenge_page", lambda _html, _url: False)

    live_batch_smoke.fetch_list_page(
        _Http(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=7",
        user_agent="real-ua",
    )

    assert captured_headers == [
        {
            "User-Agent": "real-ua",
            "Referer": "https://sf.taobao.com/",
            "Accept": "text/html",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
        }
    ]

def test_fetch_list_page_derives_previous_page_referer_for_paginated_list(monkeypatch) -> None:
    captured_headers: list[dict[str, str]] = []

    class _OkResponse:
        text = "<html><script>var sf-item-list-data = {};</script></html>"
        url = "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&page=3"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _Http:
        @staticmethod
        def get(*_args, **kwargs):
            captured_headers.append(dict(kwargs["headers"]))
            return _OkResponse()

    class _FakeProbe:
        @staticmethod
        def build_navigation_headers(*, target_url: str, user_agent: str, referer_url: str) -> dict[str, str]:
            return {
                "User-Agent": user_agent,
                "Referer": referer_url,
                "Accept": "text/html",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
            }

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "is_challenge_page", lambda _html, _url: False)

    live_batch_smoke.fetch_list_page(
        _Http(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url=(
            "https://sf.taobao.com/list/50025969__2.htm"
            "?location_code=440115&st_param=2&page=3"
        ),
        user_agent="real-ua",
    )

    assert captured_headers == [
        {
            "User-Agent": "real-ua",
            "Referer": (
                "https://sf.taobao.com/list/50025969__2.htm"
                "?location_code=440115&st_param=2&page=2"
            ),
            "Accept": "text/html",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
        }
    ]

def test_fetch_detail_html_uses_browser_navigation_headers(monkeypatch) -> None:
    captured_headers: list[dict[str, str]] = []

    class _FakeProbe:
        DEFAULT_USER_AGENT = "fallback-ua"

        @staticmethod
        def build_navigation_headers(*, target_url: str, user_agent: str, referer_url: str) -> dict[str, str]:
            return {
                "User-Agent": user_agent,
                "Referer": referer_url,
                "Accept": "text/html",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-site",
            }

    class _OkResponse:
        text = "<html>detail</html>"
        url = "https://sf-item.taobao.com/sf_item/7001.htm"
        content = text.encode("utf-8")

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _Http:
        @staticmethod
        def get(*_args, **kwargs):
            captured_headers.append(dict(kwargs["headers"]))
            return _OkResponse()

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "is_challenge_page", lambda _html, _url: False)

    live_batch_smoke.fetch_detail_html(
        _Http(),
        {"id": "7001", "url": "https://sf-item.taobao.com/sf_item/7001.htm"},
        {},
        cdp_endpoint="http://127.0.0.1:9223",
        referer_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
        user_agent="real-ua",
    )

    assert captured_headers == [
        {
            "User-Agent": "real-ua",
            "Referer": "https://sf.taobao.com/list/50025969__2.htm?page=1",
            "Accept": "text/html",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-site",
        }
    ]

def test_fetch_list_page_retries_browser_after_http_challenge_until_page_recovers(monkeypatch) -> None:
    class _ChallengeResponse:
        text = "<script>location.href='_____tmd_____/punish?x5secdata=abc'</script>"
        url = "https://sf.taobao.com/list/page=3"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _ChallengeHttp:
        @staticmethod
        def get(*_args, **_kwargs):
            return _ChallengeResponse()

    browser_results = [
        (
            "<html><body>_____tmd_____/punish 验证码</body></html>",
            "https://sf.taobao.com/list/page=3/_____tmd_____/punish?x5secdata=abc",
        ),
        (
            "<html><script>var sf-item-list-data = {};</script><body>ok</body></html>",
            "https://sf.taobao.com/list/page=3",
        ),
    ]
    sleep_calls: list[float] = []

    def _fetch_browser_list_page(_cdp_endpoint: str, _target_url: str):
        return browser_results.pop(0)

    monkeypatch.setattr(live_batch_smoke, "fetch_browser_list_page", _fetch_browser_list_page)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(
        live_batch_smoke,
        "request_captcha_solver",
        lambda _cdp_endpoint, _target_url, **_kwargs: {"status": "solving"},
    )

    html, final_url, status, method = live_batch_smoke.fetch_list_page(
        _ChallengeHttp(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=3",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
    )

    assert "sf-item-list-data" in html
    assert final_url == "https://sf.taobao.com/list/page=3"
    assert status is None
    assert method == "browser_page_after_http_challenge"
    assert sleep_calls == [2]

def test_recover_browser_list_page_after_challenge_stops_after_second_challenge(monkeypatch) -> None:
    browser_results = [
        (
            "<html><body>_____tmd_____/punish 验证码 second</body></html>",
            "https://sf.taobao.com/list/page=5/_____tmd_____/punish?x5secdata=second",
        ),
        (
            "<html><body>_____tmd_____/punish 验证码 third</body></html>",
            "https://sf.taobao.com/list/page=5/_____tmd_____/punish?x5secdata=third",
        ),
    ]
    fetch_calls: list[tuple[str, str]] = []
    sleep_calls: list[float] = []
    report_calls: list[tuple[str, str, dict[str, object]]] = []

    def _fetch_browser_list_page(cdp_endpoint: str, target_url: str):
        fetch_calls.append((cdp_endpoint, target_url))
        return browser_results.pop(0)

    monkeypatch.setattr(live_batch_smoke, "fetch_browser_list_page", _fetch_browser_list_page)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(
        live_batch_smoke,
        "request_captcha_solver",
        lambda cdp_endpoint, target_url, **kwargs: report_calls.append((cdp_endpoint, target_url, kwargs))
        or {"status": "solving"},
    )

    html, final_url = live_batch_smoke.recover_browser_list_page_after_challenge(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page=5",
        (
            "<html><body>_____tmd_____/punish 验证码 first</body></html>",
            "https://sf.taobao.com/list/page=5/_____tmd_____/punish?x5secdata=first",
        ),
    )

    assert "second" in html
    assert final_url.endswith("x5secdata=second")
    assert fetch_calls == [("http://127.0.0.1:9223", "https://sf.taobao.com/list/page=5")]
    assert sleep_calls == [2]
    assert report_calls == [
        (
            "http://127.0.0.1:9223",
            "https://sf.taobao.com/list/page=5/_____tmd_____/punish?x5secdata=first",
            {"api_base_url": None, "manual_only": False},
        )
    ]
