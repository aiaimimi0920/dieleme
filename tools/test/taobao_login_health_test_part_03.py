from tools.test.taobao_login_health_test_context import *  # noqa: F401,F403


def test_check_taobao_health_samples_opens_worker_master_before_solver_target() -> None:
    opened_urls: list[str] = []
    reported: list[tuple[str, str, str]] = []

    def _fetch(_endpoint: str, url: str) -> tuple[str, str]:
        return (
            "<html>_____tmd_____/punish 验证码</html>",
            f"{url}/_____tmd_____/punish?keep=visible",
        )

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=[
            "https://contest.local/list-a",
            "https://contest.local/list-b",
        ],
        open_login=True,
        trigger_captcha_solver=True,
        api_base_url="http://127.0.0.1:8001/api",
        fetch_page_func=_fetch,
        open_page_func=lambda _endpoint, url: opened_urls.append(url) or url,
        report_captcha_func=lambda api_base_url, cdp_endpoint, target_url: (
            reported.append((api_base_url, cdp_endpoint, target_url)) or {"status": "solving"}
        ),
    )

    solver_target_url = (
        "https://contest.local/list-a/_____tmd_____/punish?keep=visible&__captcha_solver_bg=1"
    )
    assert result["status"] == "all_samples_blocked"
    assert result["captcha_worker_url"] == "https://sf.taobao.com/?__captcha_worker_master=1"
    assert result["opened_url"] == solver_target_url
    assert opened_urls == [
        "https://sf.taobao.com/?__captcha_worker_master=1",
        solver_target_url,
    ]
    assert reported == [
        (
            "http://127.0.0.1:8001/api",
            "http://127.0.0.1:9223",
            solver_target_url,
        )
    ]

def test_check_taobao_health_samples_triggers_solver_without_open_login_when_requested() -> None:
    opened_urls: list[str] = []
    reported: list[tuple[str, str, str]] = []

    def _fetch(_endpoint: str, url: str) -> tuple[str, str]:
        return (
            "<html>验证码</html>",
            f"{url}/captcha",
        )

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=[
            "https://contest.local/list-a",
            "https://contest.local/list-b",
        ],
        open_login=False,
        trigger_captcha_solver=True,
        api_base_url="http://127.0.0.1:8001/api",
        fetch_page_func=_fetch,
        open_page_func=lambda _endpoint, url: opened_urls.append(url) or url,
        report_captcha_func=lambda api_base_url, cdp_endpoint, target_url: (
            reported.append((api_base_url, cdp_endpoint, target_url)) or {"status": "solving"}
        ),
    )

    solver_target_url = "https://contest.local/list-a/captcha?__captcha_solver_bg=1"
    assert result["status"] == "all_samples_blocked"
    assert result["captcha_solver_triggered"] is True
    assert opened_urls == [
        "https://sf.taobao.com/?__captcha_worker_master=1",
        solver_target_url,
    ]
    assert reported == [
        (
            "http://127.0.0.1:8001/api",
            "http://127.0.0.1:9223",
            solver_target_url,
        )
    ]

def test_check_taobao_health_samples_records_solver_report_failure_without_crashing() -> None:
    opened_urls: list[str] = []

    def _fetch(_endpoint: str, url: str) -> tuple[str, str]:
        return (
            "<html>_____tmd_____/punish 验证码</html>",
            f"{url}/_____tmd_____/punish?keep=visible",
        )

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=[
            "https://contest.local/list-a",
            "https://contest.local/list-b",
        ],
        open_login=False,
        trigger_captcha_solver=True,
        api_base_url="http://127.0.0.1:8001/api",
        fetch_page_func=_fetch,
        open_page_func=lambda _endpoint, url: opened_urls.append(url) or url,
        report_captcha_func=lambda _api_base_url, _cdp_endpoint, _target_url: (_ for _ in ()).throw(
            RuntimeError("sample solver report offline")
        ),
    )

    assert result["status"] == "all_samples_blocked"
    assert result["captcha_solver_triggered"] is False
    assert "sample solver report offline" in str(result["captcha_solver_error"])
    assert opened_urls == [
        "https://sf.taobao.com/?__captcha_worker_master=1",
        "https://contest.local/list-a/_____tmd_____/punish?keep=visible&__captcha_solver_bg=1",
    ]

def test_check_taobao_health_samples_uses_actionable_blocked_sample_when_one_probe_times_out() -> None:
    opened_urls: list[str] = []

    def _fetch(_endpoint: str, url: str) -> tuple[str, str]:
        if url.endswith("/list-a"):
            raise RuntimeError("BrowserType.connect_over_cdp: Timeout 30000ms exceeded")
        return (
            "<html>_____tmd_____/punish 验证码</html>",
            "https://contest.local/list-b/_____tmd_____/punish?keep=visible",
        )

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=[
            "https://contest.local/list-a",
            "https://contest.local/list-b",
        ],
        open_login=True,
        trigger_captcha_solver=True,
        fetch_page_func=_fetch,
        open_page_func=lambda _endpoint, url: opened_urls.append(url) or url,
        report_captcha_func=lambda _api_base_url, _cdp_endpoint, _target_url: {"status": "solving"},
    )

    assert result["status"] == "all_samples_blocked"
    assert result["healthy"] is False
    assert result["sample_results"][0]["status"] == "cdp_unreachable"
    assert result["sample_results"][1]["status"] == "punish_page"
    assert opened_urls == [
        "https://sf.taobao.com/?__captcha_worker_master=1",
        "https://contest.local/list-b/_____tmd_____/punish?keep=visible&__captcha_solver_bg=1",
    ]
    assert result["captcha_solver_target_url"] == opened_urls[1]

def test_check_taobao_health_samples_uses_actionable_operator_hint_when_first_sample_is_unreachable() -> None:
    def _fetch(_endpoint: str, url: str) -> tuple[str, str]:
        if url.endswith("/list-a"):
            raise RuntimeError("BrowserType.connect_over_cdp: Timeout 30000ms exceeded")
        return (
            "<html>_____tmd_____/punish 验证码</html>",
            "https://contest.local/list-b/_____tmd_____/punish?keep=visible",
        )

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=[
            "https://contest.local/list-a",
            "https://contest.local/list-b",
        ],
        fetch_page_func=_fetch,
    )

    assert result["status"] == "all_samples_blocked"
    assert result["healthy"] is False
    assert [sample["status"] for sample in result["sample_results"]] == [
        "cdp_unreachable",
        "punish_page",
    ]
    assert result["operator_hint"]["status"] == "punish_page"
    assert result["operator_hint"]["action"] == "run_taobao_login_health_helper"

def test_check_taobao_health_samples_uses_playwright_batch_when_cookie_probe_is_unavailable(monkeypatch) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def _raise_cookie_probe_failure(_endpoint: str, _urls: tuple[str, ...]) -> list[dict[str, object]]:
        raise RuntimeError("cookie probe unavailable")

    def _fetch_pages(endpoint: str, urls: tuple[str, ...]) -> list[tuple[str, str]]:
        calls.append((endpoint, tuple(urls)))
        return [
            (
                "<html>_____tmd_____/punish x5secdata=secret-token 验证码</html>",
                "https://sf.taobao.com/list/blocked.htm/_____tmd_____/punish?x5secdata=secret-token&keep=visible",
            ),
            (
                '<html><script id="sf-item-list-data" type="application/json">{"data":[{"id":"1001"}]}</script></html>',
                "https://sf.taobao.com/list/healthy.htm",
            ),
        ]

    monkeypatch.setattr(taobao_login_health, "fetch_health_samples_via_cdp_cookie_http", _raise_cookie_probe_failure)
    monkeypatch.setattr(taobao_login_health, "fetch_pages_via_cdp", _fetch_pages)

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=[
            "https://sf.taobao.com/list/blocked.htm",
            "https://sf.taobao.com/list/healthy.htm",
        ],
    )

    assert calls == [
        (
            "http://127.0.0.1:9223",
            (
                "https://sf.taobao.com/list/blocked.htm",
                "https://sf.taobao.com/list/healthy.htm",
            ),
        )
    ]
    assert result["status"] == "partial_available"
    assert result["healthy"] is True
    assert result["healthy_samples"] == 1
    assert result["blocked_samples"] == 1

def test_check_taobao_health_samples_marks_all_samples_cdp_unreachable_when_batch_fetch_raises(monkeypatch) -> None:
    def _raise_cdp_unreachable(_endpoint: str, _urls: tuple[str, ...]) -> list[tuple[str, str]]:
        raise RuntimeError("BrowserType.connect_over_cdp: Timeout 30000ms exceeded")

    monkeypatch.setattr(taobao_login_health, "fetch_pages_via_cdp", _raise_cdp_unreachable)

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=[
            "https://contest.local/list-a",
            "https://contest.local/list-b",
        ],
    )

    assert result["status"] == "cdp_unreachable"
    assert result["healthy"] is False
    assert result["sample_count"] == 2
    assert result["healthy_samples"] == 0
    assert result["blocked_samples"] == 2
    assert [sample["status"] for sample in result["sample_results"]] == [
        "cdp_unreachable",
        "cdp_unreachable",
    ]

def test_check_taobao_health_samples_all_cdp_unreachable_does_not_open_login_or_solver(monkeypatch) -> None:
    open_calls: list[str] = []
    report_calls: list[str] = []

    def _raise_cookie_probe_failure(_endpoint: str, _urls: tuple[str, ...]) -> list[dict[str, object]]:
        raise RuntimeError("cookie probe unavailable")

    def _raise_cdp_unreachable(_endpoint: str, _urls: tuple[str, ...]) -> list[tuple[str, str]]:
        raise RuntimeError("BrowserType.connect_over_cdp: Timeout 30000ms exceeded")

    monkeypatch.setattr(taobao_login_health, "fetch_health_samples_via_cdp_cookie_http", _raise_cookie_probe_failure)
    monkeypatch.setattr(taobao_login_health, "fetch_pages_via_cdp", _raise_cdp_unreachable)

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=[
            "https://contest.local/list-a",
            "https://contest.local/list-b",
        ],
        open_login=True,
        trigger_captcha_solver=True,
        open_page_func=lambda _endpoint, url: open_calls.append(url) or url,
        report_captcha_func=lambda _api_base_url, _cdp_endpoint, target_url: report_calls.append(target_url) or {
            "status": "solving"
        },
    )

    assert result["status"] == "cdp_unreachable"
    assert result["healthy"] is False
    assert open_calls == []
    assert report_calls == []
    assert result["operator_hint"]["status"] == "cdp_unreachable"

def test_check_taobao_health_samples_prefers_cookie_http_probe_before_playwright_batch(monkeypatch) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def _fetch_cookie_http(endpoint: str, urls: tuple[str, ...]) -> list[dict[str, object]]:
        calls.append((endpoint, tuple(urls)))
        return [
            {
                "status": "punish_page",
                "healthy": False,
                "action": "complete_taobao_security_verification",
                "cdp_endpoint": endpoint,
                "check_url": urls[0],
                "final_url": "https://login.taobao.com/havanaone/login/login.htm",
                "probe_transport": "cookie_http",
                "cookie_summary": {
                    "count": 3,
                    "domains": [".taobao.com"],
                    "secure_count": 2,
                    "http_only_count": 1,
                    "session_count": 1,
                    "persistent_count": 2,
                    "earliest_expiry": "2026-06-10 00:00:00",
                    "latest_expiry": "2027-06-10 00:00:00",
                },
                "list_summary": {
                    "has_script": False,
                    "item_count": None,
                    "first_ids": [],
                    "first_urls": [],
                    "body_has_login": True,
                    "body_has_captcha": True,
                    "body_has_punish": False,
                    "body_has_challenge": True,
                    "body_snippet": "blocked",
                },
                "operator_hint": {"status": "punish_page"},
            },
            {
                "status": "healthy_list_payload",
                "healthy": True,
                "action": "none",
                "cdp_endpoint": endpoint,
                "check_url": urls[1],
                "final_url": urls[1],
                "probe_transport": "cookie_http",
                "cookie_summary": {
                    "count": 3,
                    "domains": [".taobao.com"],
                    "secure_count": 2,
                    "http_only_count": 1,
                    "session_count": 1,
                    "persistent_count": 2,
                    "earliest_expiry": "2026-06-10 00:00:00",
                    "latest_expiry": "2027-06-10 00:00:00",
                },
                "list_summary": {
                    "has_script": True,
                    "item_count": 1,
                    "first_ids": ["1001"],
                    "first_urls": ["https://sf.taobao.com/item/1001"],
                    "body_has_login": False,
                    "body_has_captcha": False,
                    "body_has_punish": False,
                    "body_has_challenge": False,
                    "body_snippet": "healthy",
                },
                "operator_hint": {"status": "healthy_list_payload"},
            },
        ]

    def _raise_if_playwright_batch_used(_endpoint: str, _urls: tuple[str, ...]) -> list[tuple[str, str]]:
        raise AssertionError("playwright batch fetch should not run when cookie HTTP probe succeeds")

    monkeypatch.setattr(taobao_login_health, "fetch_health_samples_via_cdp_cookie_http", _fetch_cookie_http)
    monkeypatch.setattr(taobao_login_health, "fetch_pages_via_cdp", _raise_if_playwright_batch_used)

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=[
            "https://sf.taobao.com/list/blocked.htm",
            "https://sf.taobao.com/list/healthy.htm",
        ],
    )

    assert calls == [
        (
            "http://127.0.0.1:9223",
            (
                "https://sf.taobao.com/list/blocked.htm",
                "https://sf.taobao.com/list/healthy.htm",
            ),
        )
    ]
    assert result["status"] == "partial_available"
    assert result["healthy"] is True
    assert result["healthy_samples"] == 1
    assert result["blocked_samples"] == 1
    assert [sample["probe_transport"] for sample in result["sample_results"]] == ["cookie_http", "cookie_http"]

def test_check_taobao_health_samples_falls_back_to_playwright_batch_when_cookie_http_probe_fails(monkeypatch) -> None:
    def _raise_cookie_probe_failure(_endpoint: str, _urls: tuple[str, ...]) -> list[dict[str, object]]:
        raise RuntimeError("cookie probe unavailable")

    calls: list[tuple[str, tuple[str, ...]]] = []

    def _fetch_pages(endpoint: str, urls: tuple[str, ...]) -> list[tuple[str, str]]:
        calls.append((endpoint, tuple(urls)))
        return [
            (
                "<html>_____tmd_____/punish x5secdata=secret-token 验证码</html>",
                "https://sf.taobao.com/list/blocked.htm/_____tmd_____/punish?x5secdata=secret-token&keep=visible",
            ),
            (
                '<html><script id="sf-item-list-data" type="application/json">{\"data\":[{\"id\":\"1001\"}]}</script></html>',
                "https://sf.taobao.com/list/healthy.htm",
            ),
        ]

    monkeypatch.setattr(taobao_login_health, "fetch_health_samples_via_cdp_cookie_http", _raise_cookie_probe_failure)
    monkeypatch.setattr(taobao_login_health, "fetch_pages_via_cdp", _fetch_pages)

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=[
            "https://sf.taobao.com/list/blocked.htm",
            "https://sf.taobao.com/list/healthy.htm",
        ],
    )

    assert calls == [
        (
            "http://127.0.0.1:9223",
            (
                "https://sf.taobao.com/list/blocked.htm",
                "https://sf.taobao.com/list/healthy.htm",
            ),
        )
    ]
    assert result["status"] == "partial_available"
    assert result["healthy"] is True
    assert result["healthy_samples"] == 1
    assert result["blocked_samples"] == 1
