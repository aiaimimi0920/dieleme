from tools.test.live_batch_smoke_test_context import *  # noqa: F401,F403


def test_recover_browser_list_page_after_challenge_retries_login_page_until_healthy(monkeypatch) -> None:
    browser_results = [
        (
            "<html><script>var sf-item-list-data = {};</script><body>ok</body></html>",
            "https://sf.taobao.com/list/page=10",
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
        "https://sf.taobao.com/list/page=10",
        (
            "<html>淘宝登录</html>",
            "https://login.taobao.com/member/login.jhtml?redirect=https://sf.taobao.com/list/page=10",
        ),
    )

    assert "sf-item-list-data" in html
    assert final_url == "https://sf.taobao.com/list/page=10"
    assert fetch_calls == [("http://127.0.0.1:9223", "https://sf.taobao.com/list/page=10")]
    assert sleep_calls == [2]
    assert report_calls == [
        (
            "http://127.0.0.1:9223",
            "https://sf.taobao.com/list/page=10",
            {"api_base_url": None, "manual_only": True},
        )
    ]

def test_recover_browser_list_page_after_challenge_returns_login_terminal_after_max_attempts(monkeypatch) -> None:
    browser_results = [
        (
            "<html>淘宝登录 second</html>",
            "https://login.taobao.com/member/login.jhtml?redirect=https://sf.taobao.com/list/page=11&step=2",
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
        "https://sf.taobao.com/list/page=11",
        (
            "<html>淘宝登录 first</html>",
            "https://login.taobao.com/member/login.jhtml?redirect=https://sf.taobao.com/list/page=11&step=1",
        ),
        max_attempts=2,
        wait_seconds=3,
    )

    assert html == "<html>淘宝登录 second</html>"
    assert final_url.endswith("&step=2")
    assert fetch_calls == [("http://127.0.0.1:9223", "https://sf.taobao.com/list/page=11")]
    assert sleep_calls == [3]
    assert report_calls == [
        (
            "http://127.0.0.1:9223",
            "https://sf.taobao.com/list/page=11",
            {"api_base_url": None, "manual_only": True},
        )
    ]

def test_recover_browser_list_page_after_challenge_ignores_solver_failures_and_keeps_retrying(monkeypatch) -> None:
    browser_results = [
        (
            "<html><script>var sf-item-list-data = {};</script><body>ok</body></html>",
            "https://sf.taobao.com/list/page=5",
        ),
    ]
    fetch_calls: list[tuple[str, str]] = []
    sleep_calls: list[float] = []
    report_calls: list[tuple[str, str]] = []

    def _fetch_browser_list_page(cdp_endpoint: str, target_url: str):
        fetch_calls.append((cdp_endpoint, target_url))
        return browser_results.pop(0)

    def _request_captcha_solver(cdp_endpoint: str, target_url: str, **_kwargs):
        report_calls.append((cdp_endpoint, target_url))
        raise RuntimeError("solver api offline")

    monkeypatch.setattr(live_batch_smoke, "fetch_browser_list_page", _fetch_browser_list_page)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(
        live_batch_smoke,
        "request_captcha_solver",
        _request_captcha_solver,
    )

    html, final_url = live_batch_smoke.recover_browser_list_page_after_challenge(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page=5",
        (
            "<html><body>_____tmd_____/punish 验证码 first</body></html>",
            "https://sf.taobao.com/list/page=5/_____tmd_____/punish?x5secdata=first",
        ),
    )

    assert "sf-item-list-data" in html
    assert final_url == "https://sf.taobao.com/list/page=5"
    assert report_calls == [
        ("http://127.0.0.1:9223", "https://sf.taobao.com/list/page=5/_____tmd_____/punish?x5secdata=first")
    ]
    assert sleep_calls == [2]
    assert fetch_calls == [("http://127.0.0.1:9223", "https://sf.taobao.com/list/page=5")]

def test_recover_browser_list_page_after_challenge_honors_env_retry_window(monkeypatch) -> None:
    browser_results = [
        (
            "<html><body>_____tmd_____/punish 验证码 second</body></html>",
            "https://sf.taobao.com/list/page=6/_____tmd_____/punish?x5secdata=second",
        ),
        (
            "<html><body>_____tmd_____/punish 验证码 third</body></html>",
            "https://sf.taobao.com/list/page=6/_____tmd_____/punish?x5secdata=third",
        ),
        (
            "<html><script>var sf-item-list-data = {};</script><body>ok</body></html>",
            "https://sf.taobao.com/list/page=6",
        ),
    ]
    fetch_calls: list[tuple[str, str]] = []
    sleep_calls: list[float] = []

    def _fetch_browser_list_page(cdp_endpoint: str, target_url: str):
        fetch_calls.append((cdp_endpoint, target_url))
        return browser_results.pop(0)

    monkeypatch.setenv("FAPAI_LIST_BROWSER_RECOVERY_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("FAPAI_LIST_BROWSER_RECOVERY_WAIT_SECONDS", "5")
    monkeypatch.setattr(live_batch_smoke, "fetch_browser_list_page", _fetch_browser_list_page)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(
        live_batch_smoke,
        "request_captcha_solver",
        lambda _cdp_endpoint, _target_url, **_kwargs: {"status": "solving"},
    )

    html, final_url = live_batch_smoke.recover_browser_list_page_after_challenge(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page=6",
        (
            "<html><body>_____tmd_____/punish 验证码 first</body></html>",
            "https://sf.taobao.com/list/page=6/_____tmd_____/punish?x5secdata=first",
        ),
    )

    assert "sf-item-list-data" in html
    assert final_url == "https://sf.taobao.com/list/page=6"
    assert fetch_calls == [
        ("http://127.0.0.1:9223", "https://sf.taobao.com/list/page=6"),
        ("http://127.0.0.1:9223", "https://sf.taobao.com/list/page=6"),
        ("http://127.0.0.1:9223", "https://sf.taobao.com/list/page=6"),
    ]
    assert sleep_calls == [5.0, 5.0, 5.0]

def test_fetch_list_page_reports_captcha_before_waiting_for_browser_recovery(monkeypatch) -> None:
    class _ChallengeResponse:
        text = "<script>location.href='_____tmd_____/punish?x5secdata=abc'</script>"
        url = "https://sf.taobao.com/list/page=4"
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
            "https://sf.taobao.com/list/page=4/_____tmd_____/punish?x5secdata=abc",
        ),
        (
            "<html><script>var sf-item-list-data = {};</script><body>ok</body></html>",
            "https://sf.taobao.com/list/page=4",
        ),
    ]
    report_calls: list[tuple[str, str]] = []

    def _fetch_browser_list_page(_cdp_endpoint: str, _target_url: str):
        return browser_results.pop(0)

    monkeypatch.setattr(live_batch_smoke, "fetch_browser_list_page", _fetch_browser_list_page)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        live_batch_smoke,
        "request_captcha_solver",
        lambda cdp_endpoint, target_url, **_kwargs: report_calls.append((cdp_endpoint, target_url)) or {"status": "solving"},
    )

    live_batch_smoke.fetch_list_page(
        _ChallengeHttp(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=4",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
    )

    assert report_calls == [
        ("http://127.0.0.1:9223", "https://sf.taobao.com/list/page=4/_____tmd_____/punish?x5secdata=abc")
    ]

def test_expand_list_urls_builds_sort_page_union_specs() -> None:
    config = live_batch_smoke.LiveSmokeConfig(
        output_dir=Path("out"),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/50025969__2.htm?location_code=110101&st_param=2&auction_start_seg=-1&page=1",
        target_success=1,
        max_attempts=1,
        do_risk=False,
        list_st_params=("2", "1"),
        list_location_codes=("110101", "110102"),
        list_categories=("50025969",),
        list_max_pages=2,
    )

    specs = live_batch_smoke.expand_list_urls(config)

    assert [spec["url"] for spec in specs] == [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=110101&st_param=2&auction_start_seg=-1&page=1",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=110101&st_param=2&auction_start_seg=-1&page=2",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=110101&st_param=1&auction_start_seg=-1&page=1",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=110101&st_param=1&auction_start_seg=-1&page=2",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=110102&st_param=2&auction_start_seg=-1&page=1",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=110102&st_param=2&auction_start_seg=-1&page=2",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=110102&st_param=1&auction_start_seg=-1&page=1",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=110102&st_param=1&auction_start_seg=-1&page=2",
    ]

def test_deduplicate_list_items_preserves_first_sort_source() -> None:
    items, duplicate_count = live_batch_smoke.deduplicate_list_items(
        [
            {"id": "a", "title": "first", "source_page_url": "time"},
            {"id": "b", "title": "second", "source_page_url": "time"},
            {"id": "a", "title": "duplicate", "source_page_url": "price"},
            {"id": "c", "title": "third", "source_page_url": "price"},
        ]
    )

    assert duplicate_count == 1
    assert [item["id"] for item in items] == ["a", "b", "c"]
    assert items[0]["title"] == "first"
    assert items[0]["list_union_sources"] == ["time", "price"]

def test_collect_list_union_stops_remaining_pages_after_unsolved_challenge(monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(html: str, *, final_url: str) -> dict[str, object]:
            return {
                "has_script": html == "ok",
                "item_count": 1 if html == "ok" else None,
                "body_has_challenge": html == "challenge",
                "body_has_punish": html == "challenge",
                "body_has_login": False,
                "body_snippet": html,
            }

        @staticmethod
        def extract_list_payload(html: str) -> dict[str, object] | None:
            return {"data": []} if html == "ok" else None

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {"source_page_url": source_page_url, "items": [{"id": "first"}]}

    fetched_urls: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint, target_url, user_agent):
        fetched_urls.append(target_url)
        html = "ok" if "page=1" in target_url else "challenge"
        return html, target_url, 200, "http_cookie"

    monkeypatch.setattr(live_batch_smoke, "fetch_list_page", _fetch_list_page)

    result = live_batch_smoke.collect_list_union(
        _FakeProbe,
        object(),
        live_batch_smoke.LiveSmokeConfig(
            output_dir=Path("out"),
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/50025969__2.htm?location_code=110101&st_param=2&page=1",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            list_st_params=("2",),
            list_location_codes=("110101",),
            list_categories=("50025969",),
            list_max_pages=4,
            list_stop_on_empty=True,
        ),
    )

    assert len(fetched_urls) == 2
    assert [item["id"] for item in result["items"]] == ["first"]
    sources = result["list_union"]["sources"]
    assert sources[1]["body_has_challenge"] is True
    assert sources[2]["skipped"] is True
    assert sources[3]["skipped"] is True

def test_collect_list_union_stops_remaining_pages_after_unsolved_challenge_even_when_empty_stop_disabled(
    monkeypatch,
) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(html: str, *, final_url: str) -> dict[str, object]:
            return {
                "has_script": html == "ok",
                "item_count": 1 if html == "ok" else None,
                "body_has_challenge": html == "challenge",
                "body_has_punish": html == "challenge",
                "body_has_login": False,
                "body_snippet": html,
            }

        @staticmethod
        def extract_list_payload(html: str) -> dict[str, object] | None:
            return {"data": []} if html == "ok" else None

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {"source_page_url": source_page_url, "items": [{"id": "first"}]}

    fetched_urls: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint, target_url, user_agent):
        fetched_urls.append(target_url)
        html = "ok" if "page=1" in target_url else "challenge"
        return html, target_url, 200, "http_cookie"

    monkeypatch.setattr(live_batch_smoke, "fetch_list_page", _fetch_list_page)

    result = live_batch_smoke.collect_list_union(
        _FakeProbe,
        object(),
        live_batch_smoke.LiveSmokeConfig(
            output_dir=Path("out"),
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/50025969__2.htm?location_code=110101&st_param=2&page=1",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            list_st_params=("2",),
            list_location_codes=("110101",),
            list_categories=("50025969",),
            list_max_pages=4,
            list_stop_on_empty=False,
        ),
    )

    assert len(fetched_urls) == 2
    assert [item["id"] for item in result["items"]] == ["first"]
    sources = result["list_union"]["sources"]
    assert sources[1]["body_has_challenge"] is True
    assert sources[2]["skipped"] is True
    assert sources[3]["skipped"] is True
