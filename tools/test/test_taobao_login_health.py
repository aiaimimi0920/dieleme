from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import tools as tools_package
from tools import taobao_login_health


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_taobao_login_health_bootstraps_repo_path_before_tools_import() -> None:
    script = REPO_ROOT.joinpath("tools", "taobao_login_health.py").read_text(encoding="utf-8")

    assert script.index("REPO_ROOT =") < script.index("from tools.internal_api_http import post_json")


def test_build_captcha_solver_target_url_normalizes_duplicate_path_slashes() -> None:
    result = taobao_login_health.build_captcha_solver_target_url(
        "https://sf-item.taobao.com//sf_item/598568414650.htm?foo=1#details"
    )

    assert result == (
        "https://sf-item.taobao.com/sf_item/598568414650.htm"
        "?foo=1&__captcha_solver_bg=1#details"
    )


def test_build_captcha_solver_target_url_keeps_existing_solver_marker_once() -> None:
    result = taobao_login_health.build_captcha_solver_target_url(
        "https://sf-item.taobao.com//sf_item/598568414650.htm?__captcha_solver_bg=1"
    )

    assert result == (
        "https://sf-item.taobao.com/sf_item/598568414650.htm?__captcha_solver_bg=1"
    )


def _force_playwright_open(monkeypatch) -> None:
    def _raise_http_unavailable(_endpoint: str, _url: str) -> str:
        raise RuntimeError("force playwright fallback")

    monkeypatch.setattr(taobao_login_health, "open_page_via_cdp_http", _raise_http_unavailable, raising=False)


def test_compact_cdp_pages_keeps_browser_alive_when_triggered(monkeypatch) -> None:
    closed_targets: list[object] = []
    monkeypatch.setenv("FAPAI_CDP_MAX_PAGE_TARGETS", "3")
    monkeypatch.setattr(
        taobao_login_health,
        "open_cdp_keepalive_tab",
        lambda _endpoint: "keepalive-page",
    )
    monkeypatch.setattr(
        taobao_login_health,
        "close_cdp_target",
        lambda _endpoint, target_id: closed_targets.append(target_id) or True,
    )

    summary = taobao_login_health.compact_cdp_pages_if_needed(
        "http://127.0.0.1:9223",
        [
            {"id": "page-1", "type": "page"},
            {"id": "page-2", "type": "page"},
            {"id": "worker-1", "type": "service_worker"},
            {"id": "page-3", "type": "page"},
        ],
    )

    assert summary == {
        "triggered": True,
        "page_count": 3,
        "closed": 3,
        "keepalive_target_id": "keepalive-page",
    }
    assert closed_targets == ["page-1", "page-2", "page-3"]


def test_report_captcha_via_api_prefers_explicit_report_cdp_endpoint_override(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post_json(url: str, payload: dict[str, object], *, timeout: float):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["payload"] = dict(payload)
        return {"status": "queued"}

    monkeypatch.setenv("FAPAI_REPORT_CDP_ENDPOINT", "http://192.168.15.104:9224")
    monkeypatch.setenv("FAPAI_NODE_ID", "pc2")
    monkeypatch.setattr(taobao_login_health, "post_json", _fake_post_json)

    result = taobao_login_health.report_captcha_via_api(
        "http://192.168.15.200:8001/api",
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page",
        scope="detail",
    )

    assert result == {"status": "queued"}
    assert captured["url"] == "http://192.168.15.200:8001/api/report_captcha"
    assert captured["timeout"] == 10
    assert captured["payload"]["cdp_endpoint"] == "http://192.168.15.104:9224"
    assert captured["payload"]["node_id"] == "pc2"
    assert captured["payload"]["url"] == "https://sf.taobao.com/list/page"
    assert captured["payload"]["scope"] == "detail"


def test_report_captcha_via_api_can_request_manual_only_authentication(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post_json(url: str, payload: dict[str, object], *, timeout: float):
        captured["endpoint"] = url
        captured.update(payload)
        return {"status": "manual_required"}

    monkeypatch.setattr(taobao_login_health, "post_json", _fake_post_json)

    result = taobao_login_health.report_captcha_via_api(
        "http://collector.local/api",
        "http://127.0.0.1:9225",
        "https://sf-item.taobao.com/sf_item/3001.htm",
        manual_only=True,
    )

    assert result == {"status": "manual_required"}
    assert captured["endpoint"] == "http://collector.local/api/report_manual_captcha"
    assert captured["manual_only"] is True


def test_report_captcha_via_api_returns_request_failed_on_transport_error(monkeypatch) -> None:
    monkeypatch.setattr(
        taobao_login_health,
        "post_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("connection reset by peer")),
    )

    result = taobao_login_health.report_captcha_via_api(
        "http://collector.local/api",
        "http://127.0.0.1:9225",
        "https://sf-item.taobao.com/sf_item/3001.htm",
    )

    assert result["status"] == "request_failed"
    assert "connection reset by peer" in str(result["error"])


def test_report_captcha_via_api_normalizes_non_mapping_response(monkeypatch) -> None:
    monkeypatch.setattr(
        taobao_login_health,
        "post_json",
        lambda *_args, **_kwargs: ["queued"],
    )

    result = taobao_login_health.report_captcha_via_api(
        "http://collector.local/api",
        "http://127.0.0.1:9225",
        "https://sf-item.taobao.com/sf_item/3001.htm",
    )

    assert result == {"status": "unknown_response", "raw": ["queued"]}


def test_read_page_content_with_retries_waits_for_navigation_to_settle() -> None:
    events: list[str] = []

    class FakePage:
        def __init__(self) -> None:
            self.calls = 0

        def content(self) -> str:
            self.calls += 1
            events.append(f"content:{self.calls}")
            if self.calls == 1:
                raise RuntimeError("Page.content: page is navigating")
            return "<html>ok</html>"

        def wait_for_timeout(self, timeout: int) -> None:
            events.append(f"wait:{timeout}")

    html = taobao_login_health.read_page_content_with_retries(FakePage(), attempts=3, wait_timeout_ms=250)

    assert html == "<html>ok</html>"
    assert events == ["content:1", "wait:250", "content:2"]


def test_evaluate_cdp_expression_applies_websocket_timeout_and_closes_socket(monkeypatch) -> None:
    events: list[object] = []

    class FakeWebSocket:
        def settimeout(self, timeout: int) -> None:
            events.append(("settimeout", timeout))

        def send(self, payload: str) -> None:
            events.append(("send", json.loads(payload)["id"]))

        def recv(self) -> str:
            raise taobao_login_health.websocket.WebSocketTimeoutException("stale target")

        def close(self) -> None:
            events.append("close")

    def _fake_create_connection(url: str, **kwargs):
        events.append(("connect", url, kwargs.get("timeout")))
        return FakeWebSocket()

    monkeypatch.setattr(taobao_login_health.websocket, "create_connection", _fake_create_connection)

    try:
        taobao_login_health.evaluate_cdp_expression(
            "ws://127.0.0.1:9223/devtools/page/test",
            "(() => true)()",
        )
    except taobao_login_health.websocket.WebSocketTimeoutException as exc:
        assert "stale target" in str(exc)
    else:
        raise AssertionError("expected websocket timeout to propagate")

    assert events[0] == ("connect", "ws://127.0.0.1:9223/devtools/page/test", 20)
    assert ("settimeout", 20) in events
    assert ("send", 1) in events
    assert events[-1] == "close"


def test_read_cdp_json_rewrites_loopback_websockets_to_remote_endpoint(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def read() -> bytes:
            return json.dumps(
                [
                    {
                        "id": "page-1",
                        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/page-1",
                    }
                ]
            ).encode("utf-8")

    monkeypatch.setattr(taobao_login_health, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    assert taobao_login_health.read_cdp_json(
        "http://192.168.15.104:9224",
        "/json/list",
    ) == [
        {
            "id": "page-1",
            "webSocketDebuggerUrl": "ws://192.168.15.104:9224/devtools/page/page-1",
        }
    ]


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


def test_classify_valid_payload_ignores_generic_captcha_copy_in_normal_page_html() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html><script>sf-item-list-data</script><div hidden>captcha 验证码 challenge</div></html>",
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


def test_classify_login_required_from_mobile_or_havana_login_urls() -> None:
    for url in (
        "https://login.m.taobao.com/login.htm?redirect=https://sf.taobao.com/list/page=1",
        "https://login.taobao.com/havanaone/login/login.htm?redirect=https://sf.taobao.com/list/page=1",
    ):
        result = taobao_login_health.classify_taobao_health(
            "<html>淘宝登录</html>",
            final_url=url,
            list_summary={},
            payload_present=False,
        )

        assert result["status"] == "login_required"
        assert result["healthy"] is False
        assert result["action"] == "complete_taobao_login"


def test_classify_captcha_page_from_body_marker_without_payload() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html><body>请先完成验证码</body></html>",
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=6",
        list_summary={},
        payload_present=False,
    )

    assert result["status"] == "captcha_page"
    assert result["healthy"] is False
    assert result["action"] == "complete_taobao_security_verification"


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


def test_classify_punish_page_precedes_captcha_and_login_markers() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html>_____tmd_____/punish x5secdata= 验证码 淘宝登录</html>",
        final_url="https://market.m.taobao.com/app/msd/m-void/_____tmd_____/punish",
        list_summary={
            "body_has_login": True,
            "body_has_punish": True,
            "body_has_challenge": True,
            "body_has_captcha": True,
        },
        payload_present=False,
    )

    assert result["status"] == "punish_page"
    assert result["healthy"] is False
    assert result["action"] == "complete_taobao_security_verification"


def test_classify_challenge_required_when_body_contains_anti_bot_without_payload() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html><body>anti-bot challenge</body></html>",
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=7",
        list_summary={},
        payload_present=False,
    )

    assert result["status"] == "challenge_required"
    assert result["healthy"] is False
    assert result["action"] == "complete_taobao_security_verification"


def test_classify_challenge_required_from_challenge_url_even_with_payload() -> None:
    result = taobao_login_health.classify_taobao_health(
        '<html><script id="sf-item-list-data" type="application/json">{"data":[{"id":"1001"}]}</script></html>',
        final_url="https://contest.local/challenge?ticket=abc",
        list_summary={
            "body_has_login": False,
            "body_has_punish": False,
            "body_has_challenge": False,
            "body_has_captcha": False,
        },
        payload_present=True,
    )

    assert result["status"] == "challenge_required"
    assert result["healthy"] is False
    assert result["action"] == "complete_taobao_security_verification"


def test_classify_unknown_blocked_when_page_has_no_known_markers_or_payload() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html><body>unexpected interstitial</body></html>",
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=8",
        list_summary={},
        payload_present=False,
    )

    assert result["status"] == "unknown_blocked"
    assert result["healthy"] is False
    assert result["action"] == "inspect_taobao_session"


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


def test_build_cdp_verification_page_matcher_requires_worker_master_marker() -> None:
    matcher = taobao_login_health.build_cdp_verification_page_matcher(
        "https://sf.taobao.com/?__captcha_worker_master=1"
    )

    assert matcher("https://sf.taobao.com/?foo=1&__captcha_worker_master=1") is True
    assert matcher("https://contest.local/auth?__captcha_solver_bg=1") is False
    assert (
        matcher(
            "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?x5secdata=abc"
        )
        is False
    )


def test_build_cdp_verification_page_matcher_reuses_matching_punish_redirect() -> None:
    matcher = taobao_login_health.build_cdp_verification_page_matcher(
        "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"
    )

    assert (
        matcher(
            "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish"
            "?x5secdata=secret&x5step=1"
        )
        is True
    )
    # List challenges share one scope even when the source page/job changes.
    assert matcher(
        "https://sf.taobao.com//list/200782003__1.htm/_____tmd_____/punish"
        "?x5secdata=secret&x5step=1"
    ) is True
    detail_matcher = taobao_login_health.build_cdp_verification_page_matcher(
        "https://sf-item.taobao.com/sf_item/570192626894.htm?__captcha_solver_bg=1"
    )
    assert detail_matcher(
        "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish"
        "?x5secdata=secret&x5step=1"
    ) is False


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
