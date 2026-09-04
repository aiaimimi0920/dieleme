from tools.test.taobao_login_health_test_context import *  # noqa: F401,F403


def test_open_page_via_cdp_http_reuses_matching_punish_redirect(monkeypatch) -> None:
    punish_url = (
        "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish"
        "?x5secdata=secret&x5step=1"
    )
    target = {"id": "punish-1", "type": "page", "url": punish_url}
    activated: list[tuple[str, object]] = []
    monkeypatch.setattr(taobao_login_health, "list_cdp_targets", lambda _endpoint: [target])
    monkeypatch.setattr(
        taobao_login_health,
        "activate_cdp_target",
        lambda endpoint, candidate: activated.append((endpoint, candidate)),
    )
    monkeypatch.setattr(
        taobao_login_health,
        "read_cdp_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("matching punish target must not open a new tab")
        ),
    )

    result = taobao_login_health.open_page_via_cdp_http(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    )

    assert result == punish_url
    assert activated == [("http://127.0.0.1:9223", target)]

def test_build_cdp_verification_page_matcher_reuses_login_tabs_only_for_login_urls() -> None:
    matcher = taobao_login_health.build_cdp_verification_page_matcher(
        "https://login.taobao.com/member/login.jhtml?redirectURL=https%3A%2F%2Fsf.taobao.com%2Flist%2F50025969__2.htm"
    )

    assert matcher("https://login.taobao.com/havanaone/login/login.htm") is True
    assert matcher("https://login.m.taobao.com/login.htm") is True
    assert (
        matcher(
            "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/page/login_jump?x5step=1"
        )
        is False
    )
    assert matcher("https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish") is False

def test_solver_target_matcher_reuses_encoded_login_redirect_across_scopes() -> None:
    matcher = taobao_login_health.build_cdp_verification_page_matcher(
        "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"
    )

    assert matcher("https://login.taobao.com/havanaone/login/login.htm?uuid=abc") is True
    assert matcher("https://login.m.taobao.com/login.htm") is True
    assert matcher("https://sf-item.taobao.com/sf_item/123.htm?__captcha_solver_bg=1") is False

def test_cdp_response_bool_value_requires_nested_true_boolean() -> None:
    assert taobao_login_health.cdp_response_bool_value({}) is False
    assert taobao_login_health.cdp_response_bool_value({"result": {}}) is False
    assert (
        taobao_login_health.cdp_response_bool_value({"result": {"result": {"value": 1}}})
        is False
    )
    assert (
        taobao_login_health.cdp_response_bool_value({"result": {"result": {"value": True}}})
        is True
    )

def test_check_taobao_health_opens_login_url_when_requested() -> None:
    opened_urls: list[str] = []

    result = taobao_login_health.check_taobao_health(
        cdp_endpoint="http://192.168.65.254:9223",
        check_url="https://sf.taobao.com/list/50025969__2.htm",
        open_login=True,
        fetch_page_func=lambda _endpoint, _url: (
            "<html>淘宝登录</html>",
            "https://login.taobao.com/member/login.jhtml",
        ),
        open_page_func=lambda _endpoint, url: opened_urls.append(url) or url,
    )

    assert result["status"] == "login_required"
    assert result["opened_url"] == taobao_login_health.build_login_url(
        "https://sf.taobao.com/list/50025969__2.htm"
    )
    assert opened_urls == [result["opened_url"]]

def test_check_taobao_health_redacts_punish_tokens_from_output_urls() -> None:
    raw_punish_url = (
        "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish"
        "?x5secdata=secret-token&x5step=1&keep=visible"
    )

    result = taobao_login_health.check_taobao_health(
        cdp_endpoint="http://127.0.0.1:9223",
        check_url="https://sf.taobao.com/list/50025969__2.htm",
        open_login=True,
        fetch_page_func=lambda _endpoint, _url: (
            "<html>_____tmd_____/punish x5secdata=secret-token 验证码</html>",
            raw_punish_url,
        ),
        open_page_func=lambda _endpoint, _url: raw_punish_url.replace("secret-token", "opened-secret"),
    )

    rendered = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "punish_page"
    assert "x5secdata" not in rendered
    assert "secret-token" not in rendered
    assert "opened-secret" not in rendered
    assert "keep=visible" in rendered

def test_check_taobao_health_triggers_solver_for_blocked_verification_url() -> None:
    opened_urls: list[str] = []
    reported: list[tuple[str, str, str]] = []

    result = taobao_login_health.check_taobao_health(
        cdp_endpoint="http://127.0.0.1:9223",
        check_url="https://contest.local/list",
        open_login=True,
        trigger_captcha_solver=True,
        api_base_url="http://127.0.0.1:8001/api",
        fetch_page_func=lambda _endpoint, _url: (
            "<html>_____tmd_____/punish 验证码</html>",
            "https://contest.local/challenge?ticket=abc",
        ),
        open_page_func=lambda _endpoint, url: opened_urls.append(url) or url,
        report_captcha_func=lambda api_base_url, cdp_endpoint, target_url: (
            reported.append((api_base_url, cdp_endpoint, target_url)) or {"status": "solving"}
        ),
    )

    assert result["status"] == "punish_page"
    assert result["captcha_solver_triggered"] is True
    assert opened_urls == [
        "https://sf.taobao.com/?__captcha_worker_master=1",
        "https://contest.local/challenge?ticket=abc&__captcha_solver_bg=1",
    ]
    assert reported == [
        (
            "http://127.0.0.1:8001/api",
            "http://127.0.0.1:9223",
            "https://contest.local/challenge?ticket=abc&__captcha_solver_bg=1",
        )
    ]

def test_check_taobao_health_triggers_solver_without_open_login_when_requested() -> None:
    opened_urls: list[str] = []
    reported: list[tuple[str, str, str]] = []

    result = taobao_login_health.check_taobao_health(
        cdp_endpoint="http://127.0.0.1:9223",
        check_url="https://contest.local/list",
        open_login=False,
        trigger_captcha_solver=True,
        api_base_url="http://127.0.0.1:8001/api",
        fetch_page_func=lambda _endpoint, _url: (
            "<html>验证码</html>",
            "https://contest.local/captcha",
        ),
        open_page_func=lambda _endpoint, url: opened_urls.append(url) or url,
        report_captcha_func=lambda api_base_url, cdp_endpoint, target_url: (
            reported.append((api_base_url, cdp_endpoint, target_url)) or {"status": "solving"}
        ),
    )

    assert result["status"] == "captcha_page"
    assert result["captcha_solver_triggered"] is True
    assert opened_urls == [
        "https://sf.taobao.com/?__captcha_worker_master=1",
        "https://contest.local/captcha?__captcha_solver_bg=1",
    ]
    assert reported == [
        (
            "http://127.0.0.1:8001/api",
            "http://127.0.0.1:9223",
            "https://contest.local/captcha?__captcha_solver_bg=1",
        )
    ]

def test_check_taobao_health_records_solver_report_failure_without_crashing() -> None:
    opened_urls: list[str] = []

    result = taobao_login_health.check_taobao_health(
        cdp_endpoint="http://127.0.0.1:9223",
        check_url="https://contest.local/list",
        open_login=False,
        trigger_captcha_solver=True,
        api_base_url="http://127.0.0.1:8001/api",
        fetch_page_func=lambda _endpoint, _url: (
            "<html>验证码</html>",
            "https://contest.local/captcha",
        ),
        open_page_func=lambda _endpoint, url: opened_urls.append(url) or url,
        report_captcha_func=lambda _api_base_url, _cdp_endpoint, _target_url: (_ for _ in ()).throw(
            RuntimeError("solver report offline")
        ),
    )

    assert result["status"] == "captcha_page"
    assert result["captcha_solver_triggered"] is False
    assert "solver report offline" in str(result["captcha_solver_error"])
    assert opened_urls == [
        "https://sf.taobao.com/?__captcha_worker_master=1",
        "https://contest.local/captcha?__captcha_solver_bg=1",
    ]

def test_check_taobao_health_reports_cdp_unreachable_without_opening_login() -> None:
    opened_urls: list[str] = []

    def _raise_cdp_unreachable(_endpoint: str, _url: str) -> tuple[str, str]:
        raise RuntimeError("cdp offline")

    result = taobao_login_health.check_taobao_health(
        cdp_endpoint="http://127.0.0.1:1",
        check_url="https://sf.taobao.com/list/50025969__2.htm",
        open_login=True,
        fetch_page_func=_raise_cdp_unreachable,
        open_page_func=lambda _endpoint, url: opened_urls.append(url) or url,
    )

    assert result["status"] == "cdp_unreachable"
    assert result["healthy"] is False
    assert result["error"] == "cdp offline"
    assert opened_urls == []

def test_check_taobao_health_prefers_cookie_http_probe_before_playwright_fetch(monkeypatch) -> None:
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
            }
        ]

    def _raise_if_playwright_fetch_used(_endpoint: str, _url: str) -> tuple[str, str]:
        raise AssertionError("playwright fetch should not run when cookie HTTP probe succeeds")

    monkeypatch.setattr(taobao_login_health, "fetch_health_samples_via_cdp_cookie_http", _fetch_cookie_http)
    monkeypatch.setattr(taobao_login_health, "fetch_page_via_cdp", _raise_if_playwright_fetch_used)

    result = taobao_login_health.check_taobao_health(
        cdp_endpoint="http://127.0.0.1:9223",
        check_url="https://sf.taobao.com/list/50025969__2.htm",
    )

    assert calls == [
        (
            "http://127.0.0.1:9223",
            ("https://sf.taobao.com/list/50025969__2.htm",),
        )
    ]
    assert result["status"] == "punish_page"
    assert result["healthy"] is False
    assert result["probe_transport"] == "cookie_http"
    assert result["cookie_summary"]["domains"] == [".taobao.com"]

def test_check_taobao_health_falls_back_to_playwright_fetch_when_cookie_http_probe_fails(monkeypatch) -> None:
    def _raise_cookie_probe_failure(_endpoint: str, _urls: tuple[str, ...]) -> list[dict[str, object]]:
        raise RuntimeError("cookie probe unavailable")

    calls: list[tuple[str, str]] = []

    def _fetch_page(endpoint: str, url: str) -> tuple[str, str]:
        calls.append((endpoint, url))
        return (
            '<html><script id="sf-item-list-data" type="application/json">{"data":[{"id":"1001"}]}</script></html>',
            url,
        )

    monkeypatch.setattr(taobao_login_health, "fetch_health_samples_via_cdp_cookie_http", _raise_cookie_probe_failure)
    monkeypatch.setattr(taobao_login_health, "fetch_page_via_cdp", _fetch_page)

    result = taobao_login_health.check_taobao_health(
        cdp_endpoint="http://127.0.0.1:9223",
        check_url="https://sf.taobao.com/list/50025969__2.htm",
    )

    assert calls == [
        (
            "http://127.0.0.1:9223",
            "https://sf.taobao.com/list/50025969__2.htm",
        )
    ]
    assert result["status"] == "healthy_list_payload"
    assert result["healthy"] is True

def test_check_taobao_health_samples_reports_partial_available_when_any_sample_is_healthy() -> None:
    calls: list[str] = []

    def _fetch(_endpoint: str, url: str) -> tuple[str, str]:
        calls.append(url)
        if "healthy" in url:
            return (
                '<html><script id="sf-item-list-data" type="application/json">{"data":[{"id":"1001"}]}</script></html>',
                url,
            )
        return (
            "<html>_____tmd_____/punish x5secdata=secret-token 验证码</html>",
            f"{url}/_____tmd_____/punish?x5secdata=secret-token&keep=visible",
        )

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=[
            "https://sf.taobao.com/list/blocked.htm?x5secdata=query-secret",
            "https://sf.taobao.com/list/healthy.htm",
        ],
        fetch_page_func=_fetch,
    )

    rendered = json.dumps(result, ensure_ascii=False)
    assert calls == [
        "https://sf.taobao.com/list/blocked.htm?x5secdata=query-secret",
        "https://sf.taobao.com/list/healthy.htm",
    ]
    assert result["status"] == "partial_available"
    assert result["healthy"] is True
    assert result["sample_count"] == 2
    assert result["healthy_samples"] == 1
    assert result["blocked_samples"] == 1
    assert "x5secdata" not in rendered
    assert "secret-token" not in rendered
    assert "query-secret" not in rendered
    assert "keep=visible" in rendered

def test_check_taobao_health_samples_defaults_blank_urls_to_default_check_url() -> None:
    calls: list[tuple[str, str]] = []

    def _fetch(endpoint: str, url: str) -> tuple[str, str]:
        calls.append((endpoint, url))
        return (
            '<html><script id="sf-item-list-data" type="application/json">{"data":[{"id":"1001"}]}</script></html>',
            url,
        )

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=["", "   "],
        fetch_page_func=_fetch,
    )

    assert calls == [("http://127.0.0.1:9223", taobao_login_health.DEFAULT_CHECK_URL)]
    assert result["status"] == "healthy_list_payload"
    assert result["healthy"] is True
    assert result["sample_count"] == 1
    assert result["operator_hint"]["status"] == "healthy_list_payload"
    assert result["operator_hint"]["login_url"] == taobao_login_health.build_login_url(
        taobao_login_health.DEFAULT_CHECK_URL
    )

def test_check_taobao_health_samples_opens_login_once_when_all_samples_are_blocked() -> None:
    opened_urls: list[str] = []

    def _fetch(_endpoint: str, url: str) -> tuple[str, str]:
        return (
            "<html>_____tmd_____/punish x5secdata=secret-token 验证码</html>",
            f"{url}/_____tmd_____/punish?x5secdata=secret-token&keep=visible",
        )

    result = taobao_login_health.check_taobao_health_samples(
        cdp_endpoint="http://127.0.0.1:9223",
        sample_urls=[
            "https://sf.taobao.com/list/50025969__2.htm",
            "https://sf.taobao.com/list/200782003__1.htm",
        ],
        open_login=True,
        fetch_page_func=_fetch,
        open_page_func=lambda _endpoint, url: opened_urls.append(url) or url,
    )

    assert result["status"] == "all_samples_blocked"
    assert result["healthy"] is False
    assert result["sample_count"] == 2
    assert result["healthy_samples"] == 0
    assert result["blocked_samples"] == 2
    assert opened_urls == [
        taobao_login_health.build_login_url("https://sf.taobao.com/list/50025969__2.htm")
    ]
    assert result["opened_url"] == opened_urls[0]
