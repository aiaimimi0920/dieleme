from __future__ import annotations

import json
import builtins
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

from tools import browserless_seed_probe


LIVE_LIKE_LIST_HTML = """
<!DOCTYPE html>
<html>
<head><title>住宅用房拍卖</title></head>
<body>
  <div class="site-nav">淘宝网首页 登录 帮助中心</div>
  <script id="sf-item-list-data" type="application/json">
    {
      "data": [
        {
          "id": 747988656830,
          "itemUrl": "//sf-item.taobao.com/sf_item/747988656830.htm?track_id=demo-1"
        },
        {
          "id": 660720568820,
          "itemUrl": "//sf-item.taobao.com/sf_item/660720568820.htm?track_id=demo-2"
        }
      ]
    }
  </script>
</body>
</html>
""".strip()

RAW_LIST_PAYLOAD = {
    "data": [
        {
            "id": 747988656830,
            "title": "测试法拍房 A",
            "currentPrice": 1234567,
            "initialPrice": 1000000,
            "end": "2026-05-18 10:00:00",
            "startTime": "2026-05-17 10:00:00",
            "itemUrl": "//sf-item.taobao.com/sf_item/747988656830.htm?track_id=demo-1",
            "status": "done",
            "bidCount": 2,
            "bidUserNumber": 1,
            "applyCount": 1,
            "watchCount": 10,
            "remindCount": 5,
            "viewCount": 30,
            "itemAddress": "浙江省杭州市西湖区测试小区 1 幢 2 单元 301 室",
            "district": "西湖区",
            "city": "杭州市",
            "latitude": 30.27,
            "longitude": 120.15,
            "auctionRound": "一拍",
            "housingType": "住宅",
            "deposit": 100000,
        },
        {
            "id": 111111111111,
            "title": "未成交测试",
            "itemUrl": "//sf-item.taobao.com/sf_item/111111111111.htm",
            "status": "todo",
            "bidCount": 0,
        },
    ]
}


LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head><title>登录</title></head>
<body>
  <div>扫码登录</div>
  <div>账户登录</div>
</body>
</html>
""".strip()

PUNISH_HTML = """
<script>
sessionStorage.x5referer = window.location.href;
var url = window.location.protocol + "//sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5secdata=demo";
</script>
""".strip()


class _FakeResponse:
    def __init__(self, *, status_code: int, url: str, text: str):
        self.status_code = status_code
        self.url = url
        self.text = text


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: int, allow_redirects: bool):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )
        return self.response


def test_summarize_list_page_extracts_live_like_payload_without_false_login_signal():
    summary = browserless_seed_probe.summarize_list_page(
        LIVE_LIKE_LIST_HTML,
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    assert summary["has_script"] is True
    assert summary["item_count"] == 2
    assert summary["first_ids"] == [747988656830, 660720568820]
    assert summary["first_urls"] == [
        "//sf-item.taobao.com/sf_item/747988656830.htm?track_id=demo-1",
        "//sf-item.taobao.com/sf_item/660720568820.htm?track_id=demo-2",
    ]
    assert summary["body_has_login"] is False
    assert summary["body_has_captcha"] is False


def test_summarize_list_page_prefers_valid_payload_over_hidden_generic_captcha_copy():
    html = LIVE_LIKE_LIST_HTML.replace("</body>", "<div hidden>验证码</div></body>")

    summary = browserless_seed_probe.summarize_list_page(
        html,
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    assert summary["has_script"] is True
    assert summary["item_count"] == 2
    assert summary["body_has_captcha"] is False
    assert summary["body_has_challenge"] is False


def test_summarize_list_page_marks_login_page_from_final_url():
    summary = browserless_seed_probe.summarize_list_page(
        LOGIN_HTML,
        final_url="https://login.taobao.com/havanaone/login/login.htm?bizName=taobao",
    )

    assert summary["has_script"] is False
    assert summary["item_count"] is None
    assert summary["body_has_login"] is True


def test_summarize_list_page_marks_x5sec_punish_page_as_challenge():
    summary = browserless_seed_probe.summarize_list_page(
        PUNISH_HTML,
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    assert summary["has_script"] is False
    assert summary["body_has_punish"] is True
    assert summary["body_has_challenge"] is True


def test_summarize_list_page_marks_punish_final_url_as_challenge_even_when_html_shell_hides_tokens():
    summary = browserless_seed_probe.summarize_list_page(
        "<html><head><meta charset='utf-8'></head><body>browser shell</body></html>",
        final_url="https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?x5secdata=abc",
    )

    assert summary["has_script"] is False
    assert summary["body_has_punish"] is True
    assert summary["body_has_challenge"] is True


def test_summarize_list_page_redacts_x5secdata_from_body_snippet():
    summary = browserless_seed_probe.summarize_list_page(
        PUNISH_HTML,
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    assert "x5secdata" not in summary["body_snippet"]
    assert "demo" not in summary["body_snippet"]
    assert "taobao_security_value=<redacted>" in summary["body_snippet"]


def test_summarize_list_page_marks_additional_human_verification_markers_as_challenge():
    markers = ("滑动验证", "人机验证", "异常流量", "访问受限")

    for marker in markers:
        summary = browserless_seed_probe.summarize_list_page(
            f"<html><body>{marker}，请稍后重试</body></html>",
            final_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
        )

        assert summary["has_script"] is False
        assert summary["body_has_captcha"] is True
        assert summary["body_has_challenge"] is True


def test_build_session_from_playwright_cookies_adds_cookie_values():
    session = browserless_seed_probe.build_session_from_playwright_cookies(
        [
            {"name": "cookie2", "value": "abc", "domain": ".taobao.com", "path": "/"},
            {"name": "_tb_token_", "value": "xyz", "domain": ".taobao.com", "path": "/"},
        ]
    )

    cookie_map = {(cookie.name, cookie.domain, cookie.path): cookie.value for cookie in session.cookies}

    assert cookie_map[("cookie2", ".taobao.com", "/")] == "abc"
    assert cookie_map[("_tb_token_", ".taobao.com", "/")] == "xyz"
    assert session.trust_env is False


def test_filter_cdp_cookies_to_requested_origins():
    cookies = [
        {"name": "cookie2", "domain": ".taobao.com"},
        {"name": "XSRF-TOKEN", "domain": "login.taobao.com"},
        {"name": "MUID", "domain": ".bing.com"},
    ]

    filtered = browserless_seed_probe.filter_cdp_cookies_to_origins(
        cookies,
        ("https://sf.taobao.com", "https://login.taobao.com"),
    )

    assert filtered == [
        {"name": "cookie2", "domain": ".taobao.com"},
        {"name": "XSRF-TOKEN", "domain": "login.taobao.com"},
    ]


def test_export_cdp_cookies_falls_back_to_raw_websocket_when_playwright_export_fails(monkeypatch):
    monkeypatch.setattr(
        browserless_seed_probe,
        "_export_cdp_cookies_via_playwright",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("playwright timeout")),
    )
    monkeypatch.setattr(
        browserless_seed_probe,
        "_export_cdp_cookies_via_websocket",
        lambda *_args, **_kwargs: [{"name": "cookie2", "domain": ".taobao.com"}],
    )

    cookies = browserless_seed_probe.export_cdp_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "cookie2", "domain": ".taobao.com"}]


def test_export_cdp_cookies_prefers_raw_websocket_before_playwright_when_available(monkeypatch):
    calls: list[str] = []

    def _websocket_export(*_args, **_kwargs):
        calls.append("websocket")
        return [{"name": "cookie2", "domain": ".taobao.com"}]

    def _playwright_export(*_args, **_kwargs):
        calls.append("playwright")
        return [{"name": "playwright-cookie", "domain": ".taobao.com"}]

    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_websocket", _websocket_export)
    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_playwright", _playwright_export)

    cookies = browserless_seed_probe.export_cdp_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "cookie2", "domain": ".taobao.com"}]
    assert calls == ["websocket"]


def test_export_cdp_cookies_falls_back_to_playwright_when_websocket_export_fails(monkeypatch):
    calls: list[str] = []

    def _websocket_export(*_args, **_kwargs):
        calls.append("websocket")
        raise RuntimeError("ws blocked")

    def _playwright_export(*_args, **_kwargs):
        calls.append("playwright")
        return [{"name": "cookie2", "domain": ".taobao.com"}]

    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_websocket", _websocket_export)
    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_playwright", _playwright_export)

    cookies = browserless_seed_probe.export_cdp_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "cookie2", "domain": ".taobao.com"}]
    assert calls == ["websocket", "playwright"]


def test_export_cdp_cookies_reconnects_after_connection_reset(monkeypatch):
    calls: list[str] = []
    websocket_attempts = [ConnectionResetError("connection reset"), [{"name": "cookie2", "domain": ".taobao.com"}]]

    def websocket_export(*_args, **_kwargs):
        calls.append("websocket")
        result = websocket_attempts.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def playwright_export(*_args, **_kwargs):
        calls.append("playwright")
        raise ConnectionResetError("read ECONNRESET")

    monkeypatch.setenv("FAPAI_CDP_RECONNECT_ATTEMPTS", "3")
    monkeypatch.setenv("FAPAI_CDP_RECONNECT_BACKOFF_SECONDS", "0")
    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_websocket", websocket_export)
    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_playwright", playwright_export)
    monkeypatch.setattr(
        browserless_seed_probe,
        "cdp_endpoint_is_healthy",
        lambda endpoint: calls.append(f"health:{endpoint}") or True,
    )

    cookies = browserless_seed_probe.export_cdp_cookies("http://192.168.15.104:9224")

    assert cookies == [{"name": "cookie2", "domain": ".taobao.com"}]
    assert calls == [
        "websocket",
        "playwright",
        "health:http://192.168.15.104:9224",
        "websocket",
    ]


def test_export_cdp_cookies_stops_after_bounded_reconnect_attempts(monkeypatch):
    calls: list[str] = []

    def fail(transport: str):
        def _fail(*_args, **_kwargs):
            calls.append(transport)
            raise ConnectionResetError(transport)

        return _fail

    monkeypatch.setenv("FAPAI_CDP_RECONNECT_ATTEMPTS", "2")
    monkeypatch.setenv("FAPAI_CDP_RECONNECT_BACKOFF_SECONDS", "0")
    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_websocket", fail("websocket"))
    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_playwright", fail("playwright"))
    monkeypatch.setattr(
        browserless_seed_probe,
        "cdp_endpoint_is_healthy",
        lambda endpoint: calls.append(f"health:{endpoint}") or False,
    )

    with pytest.raises(RuntimeError, match="2 bounded attempts"):
        browserless_seed_probe.export_cdp_cookies("http://192.168.15.104:9224")

    assert calls == [
        "websocket",
        "playwright",
        "health:http://192.168.15.104:9224",
    ]


def test_browserless_seed_probe_imports_when_playwright_is_not_installed(monkeypatch):
    real_import = builtins.__import__

    def import_without_playwright(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api" or name.startswith("playwright."):
            raise ModuleNotFoundError("No module named 'playwright'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_playwright)

    module_path = Path(browserless_seed_probe.__file__)
    spec = importlib.util.spec_from_file_location("browserless_seed_probe_no_playwright", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.sync_playwright is None


def test_export_cdp_cookies_playwright_fallback_uses_bounded_cdp_connect_timeout(monkeypatch):
    events: list[object] = []

    class FakeBrowser:
        contexts = []

        def close(self) -> None:
            events.append("browser_close")

    class FakeChromium:
        def connect_over_cdp(self, endpoint: str, timeout: int | None = None) -> FakeBrowser:
            events.append((endpoint, timeout))
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            events.append("playwright_close")

    monkeypatch.setattr(browserless_seed_probe, "sync_playwright", lambda: FakeSyncPlaywright())

    cookies = browserless_seed_probe._export_cdp_cookies_via_playwright(
        "http://127.0.0.1:9223",
        ("https://sf.taobao.com", "https://login.taobao.com"),
    )

    assert cookies == []
    assert events == [
        ("http://127.0.0.1:9223", browserless_seed_probe.DEFAULT_CDP_CONNECT_TIMEOUT_MS),
        "playwright_close",
    ]


def test_export_cdp_cookies_websocket_probe_ignores_host_proxy_env(monkeypatch):
    calls: list[dict[str, object]] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {"webSocketDebuggerUrl": "ws://127.0.0.1:9224/devtools/browser/browser-1"}

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True

        def get(self, url: str, *, timeout: int):
            calls.append({"url": url, "timeout": timeout, "trust_env": self.trust_env})
            return _Response()

    class _FakeWebSocket:
        def send(self, _payload: str) -> None:
            return None

        @staticmethod
        def recv() -> str:
            return json.dumps({"result": {"cookies": [{"name": "cookie2", "domain": ".taobao.com"}]}})

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        browserless_seed_probe.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("requests.get should not be used")),
    )
    monkeypatch.setattr(browserless_seed_probe.requests, "Session", _Session)
    monkeypatch.setattr(browserless_seed_probe.websocket, "create_connection", lambda *_args, **_kwargs: _FakeWebSocket())

    cookies = browserless_seed_probe._export_cdp_cookies_via_websocket(
        "http://127.0.0.1:9224",
        ("https://sf.taobao.com", "https://login.taobao.com"),
    )

    assert cookies == [{"name": "cookie2", "domain": ".taobao.com"}]
    assert calls == [
        {
            "url": "http://127.0.0.1:9224/json/version",
            "timeout": 10,
            "trust_env": False,
        }
    ]


def test_export_cdp_cookies_websocket_probe_falls_back_to_json_target_list(monkeypatch):
    calls: list[str] = []

    class _Response:
        def __init__(self, payload: object):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self._payload

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True

        def get(self, url: str, *, timeout: int):
            calls.append(url)
            if url.endswith("/json/version"):
                raise TimeoutError("version endpoint stalled")
            if url.endswith("/json"):
                return _Response(
                    [
                        {
                            "id": "page-1",
                            "type": "page",
                            "url": "https://sf.taobao.com/list/demo",
                            "webSocketDebuggerUrl": "ws://127.0.0.1:9224/devtools/page/page-1",
                        }
                    ]
                )
            raise AssertionError(url)

    class _FakeWebSocket:
        def send(self, _payload: str) -> None:
            return None

        @staticmethod
        def recv() -> str:
            return json.dumps({"result": {"cookies": [{"name": "cookie2", "domain": ".taobao.com"}]}})

        def close(self) -> None:
            return None

    monkeypatch.setattr(browserless_seed_probe.requests, "Session", _Session)
    monkeypatch.setattr(browserless_seed_probe.websocket, "create_connection", lambda *_args, **_kwargs: _FakeWebSocket())

    cookies = browserless_seed_probe._export_cdp_cookies_via_websocket(
        "http://127.0.0.1:9224",
        ("https://sf.taobao.com", "https://login.taobao.com"),
    )

    assert cookies == [{"name": "cookie2", "domain": ".taobao.com"}]
    assert calls == [
        "http://127.0.0.1:9224/json/version",
        "http://127.0.0.1:9224/json",
    ]


def test_export_cdp_cookies_websocket_probe_uses_cached_websocket_when_http_endpoints_fail(monkeypatch, tmp_path):
    cache_path = tmp_path / "cdp-websocket-cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "http://127.0.0.1:9224": "ws://127.0.0.1:9224/devtools/browser/browser-cache",
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True

        def get(self, url: str, *, timeout: int):
            calls.append(url)
            raise TimeoutError("cdp endpoint stalled")

    class _FakeWebSocket:
        def send(self, _payload: str) -> None:
            return None

        @staticmethod
        def recv() -> str:
            return json.dumps({"result": {"cookies": [{"name": "cookie2", "domain": ".taobao.com"}]}})

        def close(self) -> None:
            return None

    monkeypatch.setenv("FAPAI_CDP_WEBSOCKET_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(browserless_seed_probe.requests, "Session", _Session)
    monkeypatch.setattr(browserless_seed_probe.websocket, "create_connection", lambda *_args, **_kwargs: _FakeWebSocket())

    cookies = browserless_seed_probe._export_cdp_cookies_via_websocket(
        "http://127.0.0.1:9224",
        ("https://sf.taobao.com", "https://login.taobao.com"),
    )

    assert cookies == [{"name": "cookie2", "domain": ".taobao.com"}]
    assert calls == [
        "http://127.0.0.1:9224/json/version",
        "http://127.0.0.1:9224/json",
    ]


def test_resolve_cdp_endpoint_uses_cached_websocket_when_http_probe_fails(monkeypatch, tmp_path):
    cache_path = tmp_path / "cdp-websocket-cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "http://127.0.0.1:9224": "ws://127.0.0.1:9224/devtools/browser/browser-cache",
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True

        def get(self, url: str, *, timeout: int):
            calls.append(url)
            raise TimeoutError("cdp endpoint stalled")

    monkeypatch.setenv("FAPAI_CDP_WEBSOCKET_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(browserless_seed_probe.requests, "Session", _Session)

    endpoint = browserless_seed_probe._resolve_cdp_endpoint("http://127.0.0.1:9224")

    assert endpoint == "ws://127.0.0.1:9224/devtools/browser/browser-cache"
    assert calls == ["http://127.0.0.1:9224/json/version"]


def test_probe_seed_page_includes_response_status_and_final_url():
    fake_session = _FakeSession(
        _FakeResponse(
            status_code=200,
            url="https://sf.taobao.com/list/50025969__2.htm?page=1",
            text=LIVE_LIKE_LIST_HTML,
        )
    )

    summary = browserless_seed_probe.probe_seed_page(
        "https://sf.taobao.com/list/50025969__2.htm?page=1",
        cookies=[],
        session=fake_session,
    )

    assert summary["status"] == 200
    assert summary["final_url"] == "https://sf.taobao.com/list/50025969__2.htm?page=1"
    assert summary["item_count"] == 2
    assert len(fake_session.calls) == 1
    assert fake_session.calls[0]["allow_redirects"] is True
    assert "Mozilla/5.0" in fake_session.calls[0]["headers"]["User-Agent"]
    assert fake_session.calls[0]["headers"]["Accept"].startswith("text/html")
    assert fake_session.calls[0]["headers"]["Sec-Fetch-Mode"] == "navigate"
    assert fake_session.calls[0]["headers"]["Sec-Fetch-Site"] == "same-origin"
    assert fake_session.calls[0]["headers"]["Upgrade-Insecure-Requests"] == "1"


def test_build_userscript_like_batch_payload_matches_current_collection_contract_shape():
    payload = browserless_seed_probe.build_userscript_like_batch_payload(
        RAW_LIST_PAYLOAD,
        source_page_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    assert payload["source_page_url"] == "https://sf.taobao.com/list/50025969__2.htm?page=1"
    assert payload["raw_payload"] == RAW_LIST_PAYLOAD["data"]
    assert len(payload["items"]) == 1
    assert payload["items"][0] == {
        "id": 747988656830,
        "title": "测试法拍房 A",
        "currentPrice": 1234567,
        "initialPrice": 1000000,
        "auction_date": "2026-05-18 10:00:00",
        "auction_start_time": "2026-05-17 10:00:00",
        "end": "2026-05-18 10:00:00",
        "url": "https://sf-item.taobao.com/sf_item/747988656830.htm?track_id=demo-1",
        "status": "done",
        "bidCount": 2,
        "bidderCount": 1,
        "applyCount": 1,
        "watchCount": 10,
        "remindCount": 5,
        "viewCount": 30,
        "location": "浙江省杭州市西湖区测试小区 1 幢 2 单元 301 室",
        "full_address": "浙江省杭州市西湖区测试小区 1 幢 2 单元 301 室",
        "district": "西湖区",
        "city": "杭州市",
        "latitude": 30.27,
        "longitude": 120.15,
        "coordinate_source": "list",
        "auction_round": "一拍",
        "housing_type": "住宅",
        "deposit": 100000,
        "is_processed": False,
    }


def test_build_userscript_like_batch_payload_formats_epoch_milliseconds_like_userscript():
    payload = browserless_seed_probe.build_userscript_like_batch_payload(
        {
            "data": [
                {
                    "id": 1,
                    "title": "毫秒时间戳测试",
                    "currentPrice": 1,
                    "initialPrice": 1,
                    "end": 1702453541000,
                    "startTime": 1702346400000,
                    "itemUrl": "//sf-item.taobao.com/sf_item/1.htm",
                    "status": "done",
                    "bidCount": 1,
                }
            ]
        },
        source_page_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    first_item = payload["items"][0]
    assert first_item["auction_date"] == datetime.fromtimestamp(1702453541000 / 1000).strftime("%Y-%m-%d %H:%M:%S")
    assert first_item["auction_start_time"] == datetime.fromtimestamp(1702346400000 / 1000).strftime("%Y-%m-%d %H:%M:%S")


def test_build_userscript_like_batch_payload_normalizes_duplicate_detail_path_slashes():
    payload = browserless_seed_probe.build_userscript_like_batch_payload(
        {
            "data": [
                {
                    "id": 570192626894,
                    "itemUrl": "//sf-item.taobao.com//sf_item/570192626894.htm?track_id=test",
                    "status": "done",
                    "bidCount": 1,
                }
            ]
        },
        source_page_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    assert payload["items"][0]["url"] == (
        "https://sf-item.taobao.com/sf_item/570192626894.htm?track_id=test"
    )


def test_write_cookie_snapshot_persists_json_payload(tmp_path: Path):
    output_path = tmp_path / "cookies.json"
    cookies = [{"name": "cookie2", "value": "abc"}]

    browserless_seed_probe.write_cookie_snapshot(cookies, output_path)

    assert json.loads(output_path.read_text(encoding="utf-8")) == cookies


def test_load_cookie_snapshot_reads_json_payload_from_disk(tmp_path: Path):
    output_path = tmp_path / "cookies.json"
    cookies = [
        {"name": "cookie2", "value": "abc", "domain": ".taobao.com"},
        {"name": "_tb_token_", "value": "xyz", "domain": "login.taobao.com"},
    ]
    output_path.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")

    loaded = browserless_seed_probe.load_cookie_snapshot(output_path)

    assert loaded == cookies


def test_summarize_cookie_snapshot_reports_safe_metadata_without_cookie_values():
    summary = browserless_seed_probe.summarize_cookie_snapshot(
        [
            {
                "name": "cookie2",
                "value": "abc",
                "domain": ".taobao.com",
                "secure": True,
                "httpOnly": False,
                "expires": 1893456000,
            },
            {
                "name": "_tb_token_",
                "value": "xyz",
                "domain": "login.taobao.com",
                "secure": False,
                "httpOnly": True,
                "expires": -1,
            },
        ]
    )

    assert summary == {
        "count": 2,
        "domains": [".taobao.com", "login.taobao.com"],
        "names": ["_tb_token_", "cookie2"],
        "secure_count": 1,
        "http_only_count": 1,
        "session_count": 1,
        "persistent_count": 1,
        "earliest_expiry": datetime.fromtimestamp(1893456000).strftime("%Y-%m-%d %H:%M:%S"),
        "latest_expiry": datetime.fromtimestamp(1893456000).strftime("%Y-%m-%d %H:%M:%S"),
        "shape_fingerprint": summary["shape_fingerprint"],
        "value_fingerprint": summary["value_fingerprint"],
    }


def test_summarize_cookie_snapshot_stable_shape_fingerprint_changes_only_when_structure_changes():
    base = browserless_seed_probe.summarize_cookie_snapshot(
        [
            {"name": "cookie2", "value": "abc", "domain": ".taobao.com", "secure": True, "httpOnly": False, "expires": 1893456000},
            {"name": "_tb_token_", "value": "xyz", "domain": "login.taobao.com", "secure": False, "httpOnly": True, "expires": -1},
        ]
    )
    same_shape_new_values = browserless_seed_probe.summarize_cookie_snapshot(
        [
            {"name": "cookie2", "value": "new-abc", "domain": ".taobao.com", "secure": True, "httpOnly": False, "expires": 1893456000},
            {"name": "_tb_token_", "value": "new-xyz", "domain": "login.taobao.com", "secure": False, "httpOnly": True, "expires": -1},
        ]
    )
    changed_shape = browserless_seed_probe.summarize_cookie_snapshot(
        [
            {"name": "cookie2", "value": "abc", "domain": ".taobao.com", "secure": True, "httpOnly": False, "expires": 1893456000},
        ]
    )

    assert base["shape_fingerprint"] == same_shape_new_values["shape_fingerprint"]
    assert base["value_fingerprint"] != same_shape_new_values["value_fingerprint"]
    assert base["shape_fingerprint"] != changed_shape["shape_fingerprint"]


def test_diff_cookie_snapshots_reports_added_and_removed_cookie_keys_safely():
    diff = browserless_seed_probe.diff_cookie_snapshots(
        [
            {"name": "cookie2", "value": "abc", "domain": ".taobao.com", "path": "/"},
            {"name": "_tb_token_", "value": "xyz", "domain": ".taobao.com", "path": "/"},
        ],
        [
            {"name": "cookie2", "value": "abc-2", "domain": ".taobao.com", "path": "/"},
            {"name": "XSRF-TOKEN", "value": "token", "domain": "login.taobao.com", "path": "/"},
        ],
    )

    assert diff["added_domains"] == ["login.taobao.com"]
    assert diff["removed_domains"] == []
    assert diff["added_names"] == ["XSRF-TOKEN"]
    assert diff["removed_names"] == ["_tb_token_"]
    assert diff["added_keys"] == ["XSRF-TOKEN|login.taobao.com|/"]
    assert diff["removed_keys"] == ["_tb_token_|.taobao.com|/"]
    assert diff["shared_key_count"] == 1
    assert diff["shape_fingerprint_equal"] is False
    assert diff["value_fingerprint_equal"] is False
