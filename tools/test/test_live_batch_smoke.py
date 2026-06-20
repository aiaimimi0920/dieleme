from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import llm_helper
from tools import live_batch_smoke


def test_preflight_llm_backend_passes_chat_probe_flag(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def _preflight_openai_compatible_backend(timeout: float, *, check_chat: bool = False) -> dict[str, object]:
        calls.append({"timeout": timeout, "check_chat": check_chat})
        return {"enabled": True}

    monkeypatch.setattr(llm_helper, "preflight_openai_compatible_backend", _preflight_openai_compatible_backend)

    result = live_batch_smoke.preflight_llm_backend(timeout=3.5, check_chat=True)

    assert result == {"enabled": True}
    assert calls == [{"timeout": 3.5, "check_chat": True}]


def test_process_item_raw_only_writes_raw_artifacts_without_llm(tmp_path: Path, monkeypatch) -> None:
    html = '<html><script>var description-data = {"area":"88.8㎡"};</script>建筑面积88.8平方米</html>'
    seed = {
        "id": "raw-1001",
        "title": "原始详情测试",
        "url": "https://sf-item.taobao.com/sf_item/raw-1001.htm",
        "source_page_url": "https://sf.taobao.com/list/page",
    }

    def _fetch_detail_html(*_args, **_kwargs):
        return html, seed["url"], len(html.encode("utf-8")), "unit-test"

    def _extract_auction_data(*_args, **_kwargs):
        raise AssertionError("raw-only detail capture must not call the LLM extractor")

    monkeypatch.setattr(live_batch_smoke, "fetch_detail_html", _fetch_detail_html)
    monkeypatch.setattr(llm_helper, "extract_auction_data", _extract_auction_data)

    selected = live_batch_smoke.process_item(
        object(),
        seed,
        {},
        config=live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            raw_only=True,
        ),
    )

    item_dir = tmp_path / "raw-1001"
    assert selected["item_id"] == "raw-1001"
    assert selected["detail_capture_mode"] == "raw"
    assert selected["fetch"]["detail_final_url"] == seed["url"]
    assert (item_dir / "seed.json").exists()
    assert (item_dir / "detail.html").read_text(encoding="utf-8") == html
    assert (item_dir / "description-data.json").exists()
    assert (item_dir / "selected.json").exists()
    assert not (item_dir / "extracted.json").exists()
    assert not (item_dir / "final.json").exists()


def test_analyze_raw_item_reads_artifacts_and_writes_ai_outputs(tmp_path: Path, monkeypatch) -> None:
    item_id = "raw-2001"
    item_dir = tmp_path / item_id
    item_dir.mkdir()
    seed = {
        "id": item_id,
        "title": "广州市南沙区测试小区1号101房",
        "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
        "currentPrice": 1230000,
        "initialPrice": 1000000,
        "auction_date": "2026-01-01 10:00:00",
        "bidCount": 4,
        "applyCount": 2,
    }
    html = "<html><body>广州市南沙区测试小区1号101房，建筑面积88.8平方米</body></html>"
    live_batch_smoke.write_json(item_dir / "seed.json", seed)
    (item_dir / "detail.html").write_text(html, encoding="utf-8")
    live_batch_smoke.write_json(item_dir / "description-data.json", {"area_sqm": 88.8, "text_len": 20, "has_area_marker": True})
    live_batch_smoke.write_json(
        item_dir / "selected.json",
        {
            "item_id": item_id,
            "detail_capture_mode": "raw",
            "fetch": {
                "method": "http_cookie",
                "detail_final_url": seed["url"],
                "detail_html_bytes": len(html.encode("utf-8")),
            },
        },
    )

    def _extract_auction_data(content: str, item_id: str | None = None) -> str:
        assert "建筑面积88.8" in content
        return json.dumps(
            {
                "标题": "AI 标题",
                "完整地址": "广州市南沙区测试小区1号101房",
                "城市": "广州市",
                "区": "南沙区",
                "所属小区": "测试小区",
                "建筑面积": 88.8,
                "成交价格": 1230000,
                "起拍价格": 1000000,
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(llm_helper, "extract_auction_data", _extract_auction_data)

    selected = live_batch_smoke.analyze_raw_item(
        item_id,
        output_dir=tmp_path,
        do_risk=False,
    )

    assert selected["item_id"] == item_id
    assert selected["fetch"]["method"] == "http_cookie"
    assert selected["auction_and_property"]["area_sqm"] == 88.8
    assert (item_dir / "extracted.json").exists()
    assert (item_dir / "final.json").exists()
    final_item = live_batch_smoke.load_json(item_dir / "final.json")
    assert final_item["detail_captured"] is True
    assert final_item["is_processed"] is True


def _result(
    item_id: str,
    *,
    area_sqm,
    unit_price,
    desc_area,
    community_name: str = "贡院西街片区",
) -> dict[str, object]:
    return {
        "item_id": item_id,
        "fetch": {
            "detail_final_url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
            "detail_html_bytes": 102950,
            "html_has_description_data": True,
        },
        "trusted_seed": {
            "title": f"标的 {item_id}",
            "currentPrice": 11632000,
            "initialPrice": 8200000,
            "auction_date": "2026-01-01 10:00:00",
            "bidCount": 421,
            "applyCount": 9,
        },
        "final_core": {
            "source_url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
            "title": f"标的 {item_id}",
        },
        "location_and_stable_index": {
            "full_address": "北京市东城区贡院西街某号",
            "city": "北京市",
            "district": "东城区",
            "business_area": "建国门",
            "community_name": community_name,
            "community_stable_key": f"collector::北京市::东城区::{community_name}",
        },
        "auction_and_property": {
            "transaction_price": 11632000,
            "starting_price": 8200000,
            "auction_date": "2026-01-01 10:00:00",
            "bid_count": 421,
            "apply_count": 9,
            "area_sqm": area_sqm,
            "gross_area_sqm": area_sqm,
            "unit_price": unit_price,
        },
        "ai_extracted_raw_core": {
            "建筑面积": desc_area,
            "单价": unit_price,
        },
        "description_data": {
            "area_sqm": desc_area,
            "text_len": 48 if desc_area is None else 300,
            "has_area_marker": desc_area is not None,
        },
    }


def test_compute_area_stats_counts_missing_and_description_fallbacks() -> None:
    results = [
        _result("has-area", area_sqm=117.06, unit_price=115792.59, desc_area=117.06),
        _result("missing-area", area_sqm=None, unit_price=0, desc_area=None),
    ]

    stats = live_batch_smoke.compute_area_stats(results)

    assert stats == {
        "total": 2,
        "area_present_count": 1,
        "area_missing_count": 1,
        "unit_price_present_count": 1,
        "unit_price_missing_count": 1,
        "description_area_present_count": 1,
        "description_area_missing_count": 1,
        "area_present_ratio": 0.5,
    }


def test_build_http_can_use_explicit_fapai_proxy(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_HTTP_PROXY", "http://proxy.local:3128")
    monkeypatch.setenv("FAPAI_HTTPS_PROXY", "http://proxy.local:3128")

    session = live_batch_smoke.build_http([])

    assert session.trust_env is False
    assert session.proxies == {
        "http": "http://proxy.local:3128",
        "https": "http://proxy.local:3128",
    }


def test_build_http_ignores_generic_proxy_env(monkeypatch) -> None:
    monkeypatch.delenv("FAPAI_HTTP_PROXY", raising=False)
    monkeypatch.delenv("FAPAI_HTTPS_PROXY", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://generic-proxy.local:3128")

    session = live_batch_smoke.build_http([])

    assert session.trust_env is False
    assert session.proxies == {"http": None, "https": None}


def test_export_cookies_falls_back_to_snapshot_when_live_cdp_export_fails(monkeypatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "taobao-cookies.json"
    calls: list[tuple[str, object]] = []

    class _FakeProbe:
        @staticmethod
        def export_cdp_cookies(endpoint: str):
            calls.append(("export", endpoint))
            raise RuntimeError("cdp unavailable")

        @staticmethod
        def load_cookie_snapshot(path: Path):
            calls.append(("snapshot", path))
            return [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))

    cookies = live_batch_smoke.export_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]
    assert calls == [
        ("export", "http://127.0.0.1:9223"),
        ("snapshot", snapshot_path),
    ]


def test_export_cookies_can_prefer_verified_snapshot_without_live_cdp(monkeypatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "taobao-cookies.json"
    calls: list[tuple[str, object]] = []

    class _FakeProbe:
        @staticmethod
        def export_cdp_cookies(endpoint: str):
            calls.append(("export", endpoint))
            raise AssertionError("live CDP export should not be used")

        @staticmethod
        def load_cookie_snapshot(path: Path):
            calls.append(("snapshot", path))
            return [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT_PREFER", "1")

    cookies = live_batch_smoke.export_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]
    assert calls == [("snapshot", snapshot_path)]


def test_export_cookies_falls_back_to_live_cdp_when_preferred_snapshot_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "missing-taobao-cookies.json"
    calls: list[tuple[str, object]] = []

    class _FakeProbe:
        @staticmethod
        def export_cdp_cookies(endpoint: str):
            calls.append(("export", endpoint))
            return [{"name": "live-cookie", "value": "abc", "domain": ".taobao.com"}]

        @staticmethod
        def load_cookie_snapshot(path: Path):
            calls.append(("snapshot", path))
            raise FileNotFoundError(path)

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT_PREFER", "1")

    cookies = live_batch_smoke.export_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "live-cookie", "value": "abc", "domain": ".taobao.com"}]
    assert calls == [
        ("snapshot", snapshot_path),
        ("export", "http://127.0.0.1:9223"),
    ]


def test_export_cookies_raises_combined_error_when_cdp_and_snapshot_both_fail(monkeypatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "taobao-cookies.json"

    class _FakeProbe:
        @staticmethod
        def export_cdp_cookies(_endpoint: str):
            raise RuntimeError("cdp unavailable")

        @staticmethod
        def load_cookie_snapshot(_path: Path):
            raise FileNotFoundError("snapshot missing")

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))

    with pytest.raises(RuntimeError, match="snapshot fallback failed"):
        live_batch_smoke.export_cookies("http://127.0.0.1:9223")


def test_connect_browser_over_cdp_uses_extended_timeout(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    compaction_calls: list[str] = []

    class _Chromium:
        @staticmethod
        def connect_over_cdp(endpoint: str, *, timeout: int):
            calls.append((endpoint, timeout))
            return {"endpoint": endpoint}

    class _Playwright:
        chromium = _Chromium()

    def _compact(endpoint: str) -> dict[str, object]:
        compaction_calls.append(endpoint)
        return {"triggered": False}

    monkeypatch.setattr(live_batch_smoke, "compact_cdp_page_targets_if_needed", _compact)
    browser = live_batch_smoke.connect_browser_over_cdp(_Playwright(), "http://127.0.0.1:9223")

    assert browser == {"endpoint": "http://127.0.0.1:9223"}
    assert calls == [("http://127.0.0.1:9223", 120000)]
    assert compaction_calls == ["http://127.0.0.1:9223"]


def test_compact_cdp_page_targets_closes_all_page_targets_at_limit(monkeypatch) -> None:
    calls: list[str] = []

    class _Response:
        def __init__(self, payload: object):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self._payload

    def _get(url: str, *, timeout: float):
        calls.append(url)
        if url.endswith("/json/list"):
            return _Response(
                [
                    {"id": "page-1", "type": "page", "url": "https://sf.taobao.com/"},
                    {"id": "page-2", "type": "page", "url": "about:blank"},
                    {"id": "worker-1", "type": "service_worker", "url": "chrome-extension://x"},
                    {"id": "page-3", "type": "page", "url": "https://sf.taobao.com/list/1"},
                ]
            )
        return _Response({})

    monkeypatch.setattr(live_batch_smoke.requests, "get", _get)

    summary = live_batch_smoke.compact_cdp_page_targets_if_needed("http://127.0.0.1:9223", limit=3)

    assert summary["triggered"] is True
    assert summary["page_count"] == 3
    assert summary["closed"] == 3
    assert calls == [
        "http://127.0.0.1:9223/json/list",
        "http://127.0.0.1:9223/json/close/page-1",
        "http://127.0.0.1:9223/json/close/page-2",
        "http://127.0.0.1:9223/json/close/page-3",
    ]


def test_compact_cdp_page_targets_does_not_close_below_limit(monkeypatch) -> None:
    calls: list[str] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return [
                {"id": "page-1", "type": "page", "url": "https://sf.taobao.com/"},
                {"id": "page-2", "type": "page", "url": "https://sf.taobao.com/list/1"},
            ]

    def _get(url: str, *, timeout: float):
        calls.append(url)
        return _Response()

    monkeypatch.setattr(live_batch_smoke.requests, "get", _get)

    summary = live_batch_smoke.compact_cdp_page_targets_if_needed("http://127.0.0.1:9223", limit=3)

    assert summary == {"triggered": False, "page_count": 2, "closed": 0, "errors": []}
    assert calls == ["http://127.0.0.1:9223/json/list"]


def test_load_open_browser_pages_returns_empty_when_cdp_page_cache_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_open_browser_pages",
        lambda _endpoint: (_ for _ in ()).throw(RuntimeError("cdp unstable")),
    )

    pages = live_batch_smoke.load_open_browser_pages("http://127.0.0.1:9223")

    assert pages == {}


def test_fetch_list_page_falls_back_to_open_browser_page(monkeypatch) -> None:
    class _FailingHttp:
        @staticmethod
        def get(*_args, **_kwargs):
            import requests

            raise requests.exceptions.ProxyError("proxy exhausted")

    monkeypatch.setattr(live_batch_smoke, "fetch_browser_list_page", lambda cdp_endpoint, target_url: ("<html>browser-list</html>", target_url))

    html, final_url, status, method = live_batch_smoke.fetch_list_page(
        _FailingHttp(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
    )

    assert html == "<html>browser-list</html>"
    assert final_url == "https://sf.taobao.com/list/page"
    assert status is None
    assert method == "browser_page"


def test_fetch_list_page_falls_back_to_browser_when_http_returns_punish(monkeypatch) -> None:
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

    monkeypatch.setattr(live_batch_smoke, "fetch_browser_list_page", lambda cdp_endpoint, target_url: ("<html>browser-ok</html>", target_url))

    html, final_url, status, method = live_batch_smoke.fetch_list_page(
        _ChallengeHttp(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=2",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
    )

    assert html == "<html>browser-ok</html>"
    assert final_url == "https://sf.taobao.com/list/page=2"
    assert status is None
    assert method == "browser_page_after_http_challenge"


def test_fetch_list_page_can_disable_browser_fallback_for_http_challenge(monkeypatch) -> None:
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

    monkeypatch.setenv("FAPAI_LIST_BROWSER_FALLBACK", "0")
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_browser_list_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser fallback should be disabled")),
    )

    html, final_url, status, method = live_batch_smoke.fetch_list_page(
        _ChallengeHttp(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=2",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
    )

    assert html == _ChallengeResponse.text
    assert final_url == "https://sf.taobao.com/list/page=2"
    assert status == 200
    assert method == "http_cookie_challenge"


def test_fetch_list_page_reports_solver_when_browser_fallback_disabled(monkeypatch) -> None:
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

    report_calls: list[tuple[str, str]] = []

    monkeypatch.setenv("FAPAI_LIST_BROWSER_FALLBACK", "0")
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_browser_list_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser fallback should be disabled")),
    )
    monkeypatch.setattr(
        live_batch_smoke,
        "request_captcha_solver",
        lambda cdp_endpoint, target_url: report_calls.append((cdp_endpoint, target_url)) or {"status": "solving"},
    )

    html, final_url, status, method = live_batch_smoke.fetch_list_page(
        _ChallengeHttp(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=2",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
        solver_enabled=True,
    )

    assert html == _ChallengeResponse.text
    assert final_url == "https://sf.taobao.com/list/page=2"
    assert status == 200
    assert method == "http_cookie_challenge"
    assert report_calls == [("http://127.0.0.1:9223", "https://sf.taobao.com/list/page=2")]


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
    monkeypatch.setattr(live_batch_smoke, "request_captcha_solver", lambda _cdp_endpoint, _target_url: {"status": "solving"})

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
    assert sleep_calls == [5]


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
        lambda cdp_endpoint, target_url: report_calls.append((cdp_endpoint, target_url)) or {"status": "solving"},
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


def test_collect_list_union_stops_remaining_pages_after_fetch_error(monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {"has_script": True, "item_count": 1, "body_has_challenge": False}

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"data": []}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {"source_page_url": source_page_url, "items": [{"id": "first"}]}

    fetched_urls: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint, target_url, user_agent):
        fetched_urls.append(target_url)
        if "page=2" in target_url:
            raise RuntimeError("browser challenge timeout")
        return "ok", target_url, 200, "http_cookie"

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
    assert result["list_union"]["sources"][1]["error"] == "RuntimeError('browser challenge timeout')"
    assert result["list_union"]["sources"][2]["skipped"] is True
    assert result["list_union"]["sources"][3]["skipped"] is True


def test_build_area_followup_queue_includes_only_area_missing_items(tmp_path: Path) -> None:
    summary = {
        "summary_path": str(tmp_path / "summary.json"),
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
        "results": [
            _result("has-area", area_sqm=117.06, unit_price=115792.59, desc_area=117.06),
            _result("missing-area", area_sqm=None, unit_price=0, desc_area=None),
        ],
    }
    existing_item_dir = tmp_path / "missing-area"
    existing_item_dir.mkdir()
    (existing_item_dir / "detail.html").write_text("<html></html>", encoding="utf-8")
    (existing_item_dir / "description-data.json").write_text(
        '{"area_sqm": null, "text_len": 48, "has_area_marker": false, "text_path": "desc.txt"}',
        encoding="utf-8",
    )

    queue = live_batch_smoke.build_area_followup_queue(summary, artifact_root=tmp_path)

    assert queue["schema_version"] == "area_followup_queue_v1"
    assert queue["source_summary"] == str(tmp_path / "summary.json")
    assert queue["job_count"] == 1
    job = queue["jobs"][0]
    assert job["item_id"] == "missing-area"
    assert job["reason"] == "area_missing_after_detail_and_description_data"
    assert job["missing_fields"] == ["area_sqm", "gross_area_sqm", "unit_price"]
    assert job["priority"] == "P1"
    assert job["source_url"] == "https://sf-item.taobao.com/sf_item/missing-area.htm"
    assert job["community_name"] == "贡院西街片区"
    assert job["community_stable_key"] == "collector::北京市::东城区::贡院西街片区"
    assert job["transaction_price"] == 11632000
    assert job["current_unit_price"] == 0
    assert job["desc_text_len"] == 48
    assert job["desc_has_area_marker"] is False
    assert job["description_data_path"] == str(existing_item_dir / "description-data.json")
    assert job["detail_html_path"] == str(existing_item_dir / "detail.html")
    assert job["next_attempts"] == [
        "announcement_attachment",
        "appraisal_report_attachment",
        "detail_page_images_ocr",
        "external_property_or_community_index",
    ]


def test_attach_area_stats_and_queue_paths_returns_new_summary(tmp_path: Path) -> None:
    summary = {
        "results": [
            _result("missing-area", area_sqm=None, unit_price=None, desc_area=None),
        ],
    }

    enriched = live_batch_smoke.attach_area_artifacts(summary, output_dir=tmp_path)

    assert "area_stats" in enriched
    assert enriched["area_stats"]["area_missing_count"] == 1
    assert enriched["area_followup_queue_path"] == str(tmp_path / "area_followup_queue.json")
    assert "area_followup_queue" not in enriched
    assert summary.get("area_stats") is None


def test_resume_state_persists_completed_items_and_skips_them(tmp_path: Path) -> None:
    state_path = tmp_path / "resume_state.json"
    state = live_batch_smoke.load_resume_state(state_path)

    live_batch_smoke.mark_resume_item(
        state,
        "a",
        status="completed",
        metadata={"selected_json_path": "a/selected.json"},
    )
    live_batch_smoke.save_resume_state(state_path, state)

    loaded = live_batch_smoke.load_resume_state(state_path)
    candidates, skipped = live_batch_smoke.select_resume_candidates(
        [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        loaded,
        limit=2,
    )

    assert live_batch_smoke.is_resume_completed(loaded, "a") is True
    assert [item["id"] for item in candidates] == ["b", "c"]
    assert skipped == ["a"]


def test_resume_state_retries_non_completed_items(tmp_path: Path) -> None:
    state = live_batch_smoke.load_resume_state(tmp_path / "missing.json")
    live_batch_smoke.mark_resume_item(state, "a", status="completed")
    live_batch_smoke.mark_resume_item(state, "b", status="failed", metadata={"error": "timeout"})
    live_batch_smoke.mark_resume_item(state, "c", status="in_progress")

    candidates, skipped = live_batch_smoke.select_resume_candidates(
        [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
        state,
        limit=3,
    )

    assert [item["id"] for item in candidates] == ["b", "c", "d"]
    assert skipped == ["a"]


def test_run_live_smoke_uses_resume_state_to_continue_after_restart(tmp_path: Path, monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {"item_count": 4, "final_url": final_url}

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
            }

    class _FakeResponse:
        text = "<html>list</html>"
        url = "https://sf.taobao.com/list/page"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _FakeHttp:
        @staticmethod
        def get(*_args, **_kwargs) -> _FakeResponse:
            return _FakeResponse()

    processed_ids: list[str] = []
    resume_state_path = tmp_path / "resume_state.json"
    state = live_batch_smoke.load_resume_state(resume_state_path)
    live_batch_smoke.mark_resume_item(state, "a", status="completed")
    live_batch_smoke.mark_resume_item(state, "b", status="completed")
    live_batch_smoke.save_resume_state(resume_state_path, state)

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: _FakeHttp())
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        return _result(str(seed["id"]), area_sqm=88.8, unit_price=12345, desc_area=88.8)

    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=2,
            max_attempts=3,
            do_risk=False,
            resume_state_path=resume_state_path,
            resume_enabled=True,
        )
    )

    assert exit_code == 0
    assert processed_ids == ["c", "d"]
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["attempted_items"] == 2
    assert summary["skipped_completed_items"] == 2
    assert summary["resume_state_path"] == str(resume_state_path)

    reloaded = live_batch_smoke.load_resume_state(resume_state_path)
    assert live_batch_smoke.is_resume_completed(reloaded, "a") is True
    assert live_batch_smoke.is_resume_completed(reloaded, "b") is True
    assert live_batch_smoke.is_resume_completed(reloaded, "c") is True
    assert live_batch_smoke.is_resume_completed(reloaded, "d") is True


def test_run_live_smoke_recovers_completed_items_from_existing_artifacts(tmp_path: Path, monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {"item_count": 3, "final_url": final_url}

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            }

    class _FakeResponse:
        text = "<html>list</html>"
        url = "https://sf.taobao.com/list/page"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _FakeHttp:
        @staticmethod
        def get(*_args, **_kwargs) -> _FakeResponse:
            return _FakeResponse()

    item_dir = tmp_path / "a"
    item_dir.mkdir()
    (item_dir / "final.json").write_text("{}", encoding="utf-8")
    (item_dir / "selected.json").write_text("{}", encoding="utf-8")
    processed_ids: list[str] = []
    resume_state_path = tmp_path / "resume_state.json"

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: _FakeHttp())
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        return _result(str(seed["id"]), area_sqm=88.8, unit_price=12345, desc_area=88.8)

    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=1,
            max_attempts=2,
            do_risk=False,
            resume_state_path=resume_state_path,
            resume_enabled=True,
        )
    )

    assert exit_code == 0
    assert processed_ids == ["b"]
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["artifact_completed_items"] == 1
    assert summary["skipped_completed_items"] == 1

    reloaded = live_batch_smoke.load_resume_state(resume_state_path)
    assert live_batch_smoke.is_resume_completed(reloaded, "a") is True
    assert live_batch_smoke.is_resume_completed(reloaded, "b") is True


def test_run_live_smoke_fetches_multiple_sort_pages_before_detail_processing(tmp_path: Path, monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(html: str, *, final_url: str) -> dict[str, object]:
            item_count = 2 if "empty" not in html else 0
            return {"item_count": item_count, "final_url": final_url}

        @staticmethod
        def extract_list_payload(html: str) -> dict[str, object]:
            return {"source": html}

        @staticmethod
        def build_userscript_like_batch_payload(payload, *, source_page_url: str) -> dict[str, object]:
            if "st_param=2" in source_page_url and "page=1" in source_page_url:
                items = [{"id": "time-a"}, {"id": "shared"}]
            elif "st_param=1" in source_page_url and "page=1" in source_page_url:
                items = [{"id": "shared"}, {"id": "price-only"}]
            else:
                items = []
            return {
                "source_page_url": source_page_url,
                "items": items,
            }

    fetched_urls: list[str] = []
    processed_ids: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint, target_url, user_agent):
        fetched_urls.append(target_url)
        html = "empty" if "page=2" in target_url else "list"
        return html, target_url, 200, "http"

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        return _result(str(seed["id"]), area_sqm=88.8, unit_price=12345, desc_area=88.8)

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(live_batch_smoke, "fetch_list_page", _fetch_list_page)
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/50025969__2.htm?location_code=110101&st_param=2&auction_start_seg=-1&page=1",
            target_success=3,
            max_attempts=10,
            do_risk=False,
            resume_state_path=tmp_path / "resume_state.json",
            resume_enabled=True,
            list_st_params=("2", "1"),
            list_location_codes=("110101",),
            list_categories=("50025969",),
            list_max_pages=2,
            list_stop_on_empty=True,
        )
    )

    assert exit_code == 0
    assert len(fetched_urls) == 4
    assert processed_ids == ["time-a", "shared", "price-only"]
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["list_union"]["source_count"] == 4
    assert summary["list_union"]["unique_item_count"] == 3
    assert summary["list_union"]["duplicate_item_count"] == 1


def test_run_live_smoke_llm_preflight_failure_aborts_before_detail_items(tmp_path: Path, monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {"item_count": 1, "final_url": final_url}

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {"source_page_url": source_page_url, "items": [{"id": "preflight-blocked"}]}

    class _FakeResponse:
        text = "<html>list</html>"
        url = "https://sf.taobao.com/list/page"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _FakeHttp:
        @staticmethod
        def get(*_args, **_kwargs) -> _FakeResponse:
            return _FakeResponse()

    processed_ids: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        return _result(str(seed["id"]), area_sqm=88.8, unit_price=12345, desc_area=88.8)

    def _preflight_llm_backend(*, timeout: float) -> dict[str, object]:
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: _FakeHttp())
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)
    monkeypatch.setattr(live_batch_smoke, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with pytest.raises(RuntimeError, match="llm unavailable"):
        live_batch_smoke.run_live_smoke(
            live_batch_smoke.LiveSmokeConfig(
                output_dir=tmp_path,
                cdp_endpoint="http://127.0.0.1:9223",
                target_url="https://sf.taobao.com/list/page",
                target_success=1,
                max_attempts=1,
                do_risk=False,
                resume_state_path=tmp_path / "resume_state.json",
                resume_enabled=True,
                llm_preflight_enabled=True,
                llm_preflight_timeout_seconds=3.5,
            )
        )

    assert processed_ids == []
    assert not (tmp_path / "preflight-blocked.error.json").exists()


def test_run_live_smoke_llm_preflight_failure_aborts_before_taobao_network(tmp_path: Path, monkeypatch) -> None:
    def _preflight_llm_backend(*, timeout: float) -> dict[str, object]:
        raise RuntimeError("llm unavailable")

    def _export_cookies(_endpoint: str):
        raise AssertionError("Taobao/CDP should not be touched when LLM preflight already fails")

    monkeypatch.setattr(live_batch_smoke, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", _export_cookies)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with pytest.raises(RuntimeError, match="llm unavailable"):
        live_batch_smoke.run_live_smoke(
            live_batch_smoke.LiveSmokeConfig(
                output_dir=tmp_path,
                cdp_endpoint="http://127.0.0.1:9223",
                target_url="https://sf.taobao.com/list/page",
                target_success=1,
                max_attempts=1,
                do_risk=False,
                llm_preflight_enabled=True,
            )
        )


def test_run_loop_continues_across_batches_with_same_resume_state(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[Path | None, bool]] = []

    def _run_live_smoke(config: live_batch_smoke.LiveSmokeConfig) -> int:
        calls.append((config.resume_state_path, config.resume_enabled))
        return 0

    monkeypatch.setattr(live_batch_smoke, "run_live_smoke", _run_live_smoke)
    summary = live_batch_smoke.run_loop(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=2,
            max_attempts=4,
            do_risk=False,
            resume_state_path=tmp_path / "resume_state.json",
            resume_enabled=True,
        ),
        max_runs=2,
        interval_seconds=0,
    )

    assert summary["run_count"] == 2
    assert summary["exit_codes"] == [0, 0]
    assert calls == [
        (tmp_path / "resume_state.json", True),
        (tmp_path / "resume_state.json", True),
    ]


def test_run_loop_keeps_process_alive_after_transient_batch_error(tmp_path: Path, monkeypatch) -> None:
    calls = 0

    def _run_live_smoke(_config: live_batch_smoke.LiveSmokeConfig) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("cdp temporarily unavailable")
        return 0

    monkeypatch.setattr(live_batch_smoke, "run_live_smoke", _run_live_smoke)

    summary = live_batch_smoke.run_loop(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=2,
            max_attempts=4,
            do_risk=False,
            resume_state_path=tmp_path / "resume_state.json",
            resume_enabled=True,
        ),
        max_runs=2,
        interval_seconds=0,
    )

    assert summary["run_count"] == 2
    assert summary["exit_codes"] == [1, 0]
    assert summary["ok"] is False
    assert len(summary["errors"]) == 1
    assert summary["errors"][0]["error"] == "RuntimeError('cdp temporarily unavailable')"
