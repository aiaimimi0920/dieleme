from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import tools as tools_package
from tools import taobao_login_health


REPO_ROOT = Path(__file__).resolve().parents[2]


def _force_playwright_open(monkeypatch) -> None:
    def _raise_http_unavailable(_endpoint: str, _url: str) -> str:
        raise RuntimeError("force playwright fallback")

    monkeypatch.setattr(taobao_login_health, "open_page_via_cdp_http", _raise_http_unavailable, raising=False)


def test_classify_healthy_list_payload_when_payload_is_present() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html><script>sf-item-list-data</script></html>",
        final_url="https://sf.taobao.com/list/50025969__2.htm",
        list_summary={
            "body_has_login": False,
            "body_has_punish": False,
            "body_has_challenge": False,
            "body_has_captcha": False,
        },
        payload_present=True,
    )

    assert result["status"] == "healthy_list_payload"
    assert result["healthy"] is True
    assert result["action"] == "none"


def test_classify_login_required_from_login_url() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html>淘宝登录</html>",
        final_url="https://login.taobao.com/member/login.jhtml",
        list_summary={
            "body_has_login": True,
            "body_has_punish": False,
            "body_has_challenge": False,
            "body_has_captcha": False,
        },
        payload_present=False,
    )

    assert result["status"] == "login_required"
    assert result["healthy"] is False
    assert result["action"] == "complete_taobao_login"


def test_classify_punish_page_from_punish_markers() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html>_____tmd_____/punish x5secdata=</html>",
        final_url="https://market.m.taobao.com/app/msd/m-void/_____tmd_____/punish",
        list_summary={
            "body_has_login": False,
            "body_has_punish": True,
            "body_has_challenge": True,
            "body_has_captcha": False,
        },
        payload_present=False,
    )

    assert result["status"] == "punish_page"
    assert result["healthy"] is False
    assert result["action"] == "complete_taobao_security_verification"


def test_operator_hint_points_to_safe_helper_without_cookie_values() -> None:
    hint = taobao_login_health.build_operator_hint(
        status="punish_page",
        cdp_endpoint="http://192.168.65.254:9223",
        check_url="https://sf.taobao.com/list/50025969__2.htm",
    )

    rendered = json.dumps(hint, ensure_ascii=False)
    assert hint["required"] is True
    assert "tools\\taobao_login_health.py" in hint["helper_command"]
    assert "--open-login" in hint["helper_command"]
    assert "--trigger-captcha-solver" not in hint["helper_command"]
    assert "--trigger-captcha-solver" not in hint["host_helper_command"]
    assert "--wait-seconds 180" in hint["helper_command"]
    assert "192.168.65.254:9223" in hint["helper_command"]
    assert "127.0.0.1:9223" in hint["host_helper_command"]
    assert "cookie2=" not in rendered
    assert "sgcookie=" not in rendered
    assert "_tb_token_=" not in rendered


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


def test_direct_script_execution_adds_repo_root_to_python_path() -> None:
    script = REPO_ROOT.joinpath("tools", "taobao_login_health.py").read_text(encoding="utf-8")

    assert "REPO_ROOT = Path(__file__).resolve().parents[1]" in script
    assert "sys.path.insert(0, str(REPO_ROOT))" in script


def test_taobao_login_health_uses_extended_cdp_connect_timeout_like_live_smoke() -> None:
    script = REPO_ROOT.joinpath("tools", "taobao_login_health.py").read_text(encoding="utf-8")

    assert "DEFAULT_CDP_CONNECT_TIMEOUT_MS = 120000" in script
    assert "playwright.chromium.connect_over_cdp(cdp_endpoint, timeout=DEFAULT_CDP_CONNECT_TIMEOUT_MS)" in script


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
        "browser_close",
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


def test_open_page_via_cdp_brings_official_verification_page_to_front(monkeypatch) -> None:
    events: list[str] = []
    _force_playwright_open(monkeypatch)

    class FakePage:
        url = "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish"

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            events.append(f"goto:{url}:{wait_until}:{timeout}")

        def bring_to_front(self) -> None:
            events.append("bring_to_front")

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

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://login.taobao.com/member/login.jhtml",
    )

    assert final_url.endswith("/_____tmd_____/punish")
    assert events[:3] == [
        "connect:http://127.0.0.1:9223",
        "new_page",
        "goto:https://login.taobao.com/member/login.jhtml:domcontentloaded:10000",
    ]
    assert "bring_to_front" in events


def test_open_page_via_cdp_reuses_existing_taobao_verification_tab(monkeypatch) -> None:
    events: list[str] = []
    _force_playwright_open(monkeypatch)

    class ExistingTaobaoPage:
        url = "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish"

        def bring_to_front(self) -> None:
            events.append("existing_bring_to_front")

    class FakeContext:
        pages = [ExistingTaobaoPage()]

        def new_page(self):
            events.append("new_page")
            raise AssertionError("should reuse existing Taobao verification tab")

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

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/50025969__2.htm",
    )

    assert final_url.endswith("/_____tmd_____/punish")
    assert events == [
        "connect:http://127.0.0.1:9223",
        "existing_bring_to_front",
        "browser_close",
        "playwright_close",
    ]


def test_open_page_via_cdp_reuses_existing_solver_target_tab(monkeypatch) -> None:
    events: list[str] = []
    _force_playwright_open(monkeypatch)

    class ExistingSolverPage:
        url = "https://contest.local/auth?__captcha_solver_bg=1"

        def bring_to_front(self) -> None:
            events.append("existing_solver_bring_to_front")

    class FakeContext:
        pages = [ExistingSolverPage()]

        def new_page(self):
            events.append("new_page")
            raise AssertionError("should reuse existing solver target tab")

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

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://contest.local/auth?__captcha_solver_bg=1",
    )

    assert final_url == "https://contest.local/auth?__captcha_solver_bg=1"
    assert events == [
        "connect:http://127.0.0.1:9223",
        "existing_solver_bring_to_front",
        "browser_close",
        "playwright_close",
    ]


def test_open_page_via_cdp_creates_worker_master_even_when_solver_tab_exists(monkeypatch) -> None:
    events: list[str] = []
    _force_playwright_open(monkeypatch)

    class ExistingSolverPage:
        url = "https://sf.taobao.com/list/blocked/_____tmd_____/punish?__captcha_solver_bg=1"

        def bring_to_front(self) -> None:
            events.append("existing_solver_bring_to_front")

    class NewWorkerPage:
        url = "https://sf.taobao.com/?__captcha_worker_master=1"

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            events.append(f"goto:{url}:{wait_until}:{timeout}")
            self.url = url

        def bring_to_front(self) -> None:
            events.append("new_worker_bring_to_front")

    class FakeContext:
        pages = [ExistingSolverPage()]

        def new_page(self) -> NewWorkerPage:
            events.append("new_page")
            return NewWorkerPage()

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

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/?__captcha_worker_master=1",
    )

    assert final_url == "https://sf.taobao.com/?__captcha_worker_master=1"
    assert "existing_solver_bring_to_front" not in events
    assert events[:3] == [
        "connect:http://127.0.0.1:9223",
        "new_page",
        "goto:https://sf.taobao.com/?__captcha_worker_master=1:domcontentloaded:10000",
    ]
    assert "new_worker_bring_to_front" in events


def test_open_page_via_cdp_creates_solver_target_even_when_worker_master_exists(monkeypatch) -> None:
    events: list[str] = []
    _force_playwright_open(monkeypatch)

    class ExistingWorkerPage:
        url = "https://sf.taobao.com/?__captcha_worker_master=1"

        def bring_to_front(self) -> None:
            events.append("existing_worker_bring_to_front")

    class NewSolverPage:
        url = "https://contest.local/auth?__captcha_solver_bg=1"

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            events.append(f"goto:{url}:{wait_until}:{timeout}")
            self.url = url

        def bring_to_front(self) -> None:
            events.append("new_solver_bring_to_front")

    class FakeContext:
        pages = [ExistingWorkerPage()]

        def new_page(self) -> NewSolverPage:
            events.append("new_page")
            return NewSolverPage()

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

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://contest.local/auth?__captcha_solver_bg=1",
    )

    assert final_url == "https://contest.local/auth?__captcha_solver_bg=1"
    assert "existing_worker_bring_to_front" not in events
    assert events[:3] == [
        "connect:http://127.0.0.1:9223",
        "new_page",
        "goto:https://contest.local/auth?__captcha_solver_bg=1:domcontentloaded:10000",
    ]
    assert "new_solver_bring_to_front" in events


def test_open_page_via_cdp_does_not_reuse_plain_sf_taobao_tab(monkeypatch) -> None:
    events: list[str] = []
    _force_playwright_open(monkeypatch)

    class ExistingPlainSfPage:
        url = "https://sf.taobao.com/list/50025969__2.htm"

        def bring_to_front(self) -> None:
            events.append("plain_bring_to_front")

    class NewVerificationPage:
        url = "https://login.taobao.com/member/login.jhtml"

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            events.append(f"goto:{url}:{wait_until}:{timeout}")

        def bring_to_front(self) -> None:
            events.append("new_bring_to_front")

    class FakeContext:
        pages = [ExistingPlainSfPage()]

        def new_page(self) -> NewVerificationPage:
            events.append("new_page")
            return NewVerificationPage()

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

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://login.taobao.com/member/login.jhtml",
    )

    assert final_url == "https://login.taobao.com/member/login.jhtml"
    assert "plain_bring_to_front" not in events
    assert events[:3] == [
        "connect:http://127.0.0.1:9223",
        "new_page",
        "goto:https://login.taobao.com/member/login.jhtml:domcontentloaded:10000",
    ]
    assert "new_bring_to_front" in events
