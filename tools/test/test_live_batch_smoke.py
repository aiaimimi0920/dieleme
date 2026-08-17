from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from src import llm_helper
from tools import live_batch_smoke
from tools import taobao_login_health


def test_preflight_llm_backend_passes_chat_probe_flag(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def _preflight_llm_backend(timeout: float, *, check_chat: bool = False) -> dict[str, object]:
        calls.append({"timeout": timeout, "check_chat": check_chat})
        return {"enabled": True}

    monkeypatch.setattr(llm_helper, "preflight_llm_backend", _preflight_llm_backend)

    result = live_batch_smoke.preflight_llm_backend(timeout=3.5, check_chat=True)

    assert result == {"enabled": True}
    assert calls == [{"timeout": 3.5, "check_chat": True}]


def test_preflight_llm_backend_skips_models_already_disabled_by_auth_failures(monkeypatch) -> None:
    original_pool = llm_helper.MODEL_POOL
    original_selector = llm_helper.model_selector
    pool = [
        {"name": "model-a", "app_id": "a", "api_key": "ak", "api_secret": "as", "ws_url": "wss://unit.test/a", "model_id": "mid-a", "max_concurrent": 1},
        {"name": "model-b", "app_id": "b", "api_key": "bk", "api_secret": "bs", "ws_url": "wss://unit.test/b", "model_id": "mid-b", "max_concurrent": 1},
    ]
    monkeypatch.setattr(llm_helper, "MODEL_POOL", pool)
    monkeypatch.setattr(llm_helper, "model_selector", llm_helper.ModelSelector(pool))
    monkeypatch.setattr(llm_helper, "_get_openai_compatible_config", lambda: None)

    calls = {"count": 0}

    def _fake_get_response(self, _prompt):
        calls["count"] += 1
        self.error_code = 11200
        self.error_msg = "AppIdNoAuthError"
        llm_helper.model_selector.disable_model(
            self.model_config["name"],
            "error_code=11200, error_msg=AppIdNoAuthError",
        )
        return ""

    monkeypatch.setattr(llm_helper.AIService, "get_response", _fake_get_response)

    first = llm_helper.preflight_llm_backend(timeout=1.0, check_chat=True)
    second = llm_helper.preflight_llm_backend(timeout=1.0, check_chat=True)

    assert first["chat_status_code"] == 401
    assert second["chat_status_code"] == 401
    assert calls["count"] == len(pool)

    monkeypatch.setattr(llm_helper, "MODEL_POOL", original_pool)
    monkeypatch.setattr(llm_helper, "model_selector", original_selector)


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
    html = """
    <html>
      <body>
        <input id="J_StartPrice" value="1000000.00" />
        <div id="itemAddress">广东省 广州市 南沙区</div>
        <div id="itemAddressDetail">测试小区1号101房</div>
        广州市南沙区测试小区1号101房，建筑面积88.8平方米
      </body>
    </html>
    """
    live_batch_smoke.write_json(item_dir / "seed.json", seed)
    (item_dir / "detail.html").write_text(html, encoding="utf-8")
    live_batch_smoke.write_json(item_dir / "description-data.json", {"area_sqm": 88.8, "text_len": 20, "has_area_marker": True})
    (item_dir / "description-data.txt").write_text(
        "拍卖标的调查情况表\n面积：88.8平方米，起拍价：1000000元。",
        encoding="utf-8",
    )
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
            "trusted_seed": {
                "title": seed["title"],
                "currentPrice": seed["currentPrice"],
                "initialPrice": seed["initialPrice"],
                "auction_date": seed["auction_date"],
                "bidCount": seed["bidCount"],
                "applyCount": seed["applyCount"],
            },
        },
    )

    def _extract_auction_data(content: str, item_id: str | None = None) -> str:
        assert "【可信种子】" in content
        assert "currentPrice: 1230000" in content
        assert "拍卖标的调查情况表" in content
        assert "<html>" not in content
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


def test_build_detail_analysis_input_prefers_compact_summary_and_redacts_contacts(tmp_path: Path) -> None:
    item_id = "raw-compact-2002"
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
        "status": "done",
    }
    html = """
    <html>
      <head><title>广州市南沙区测试小区1号101房 - 司法拍卖</title></head>
      <body>
        <span class="countdown J_TimeLeft">2026/01/01 10:05:55</span>
        <input id="J_StartPrice" value="900000.00" />
        <div id="itemAddress">广东省 广州市 南沙区</div>
        <div id="itemAddressDetail">测试小区1号101房</div>
        联系方式：张先生 手机：13231377737
      </body>
    </html>
    """
    (item_dir / "description-data.txt").write_text(
        "拍卖标的调查情况表\n面积：88.8平方米，起拍价：900000元，保证金50000元。",
        encoding="utf-8",
    )

    effective_seed, analysis_text = live_batch_smoke._build_detail_analysis_input(
        item_id=item_id,
        item_dir=item_dir,
        seed=seed,
        html=html,
        selected={
            "fetch": {"detail_final_url": seed["url"]},
            "trusted_seed": {"title": seed["title"], "currentPrice": seed["currentPrice"]},
        },
        description_data={"text_path": str(item_dir / "description-data.txt")},
    )

    assert effective_seed["initialPrice"] == 900000.0
    assert "13231377737" not in analysis_text
    assert "张先生" not in analysis_text
    assert "currentPrice: 1230000" in analysis_text
    assert "起拍价_html: 900000.0" in analysis_text
    assert "拍卖标的调查情况表" in analysis_text


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


def test_parse_csv_values_deduplicates_semicolon_and_whitespace() -> None:
    values = live_batch_smoke.parse_csv_values(" 2;1,2,, 3 ;1 ")

    assert values == ("2", "1", "3")


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


def test_export_cookies_uses_node_snapshot_path_when_explicit_snapshot_env_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    shared_root = tmp_path
    expected_snapshot_path = shared_root / "secrets" / "nodes" / "pc2" / "taobao-cookies.json"
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
    monkeypatch.delenv("FAPAI_COOKIE_SNAPSHOT", raising=False)
    monkeypatch.setenv("FAPAI_SHARED_DATA_ROOT_HOST", str(shared_root))
    monkeypatch.setenv("FAPAI_NODE_ID", "pc2")

    cookies = live_batch_smoke.export_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]
    assert calls == [
        ("export", "http://127.0.0.1:9223"),
        ("snapshot", expected_snapshot_path),
    ]


def test_export_cookies_writes_snapshot_after_live_cdp_export(monkeypatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "taobao-cookies.json"
    live_cookies = [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]
    calls: list[tuple[str, object]] = []

    class _FakeProbe:
        @staticmethod
        def export_cdp_cookies(endpoint: str):
            calls.append(("export", endpoint))
            return live_cookies

        @staticmethod
        def write_cookie_snapshot(cookies: object, path: Path):
            calls.append(("write", path, cookies))

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))

    cookies = live_batch_smoke.export_cookies("http://127.0.0.1:9223")

    assert cookies == live_cookies
    assert calls == [
        ("export", "http://127.0.0.1:9223"),
        ("write", snapshot_path, live_cookies),
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
    monkeypatch.setattr(live_batch_smoke, "resolve_playwright_cdp_endpoint", lambda endpoint: endpoint)
    browser = live_batch_smoke.connect_browser_over_cdp(_Playwright(), "http://127.0.0.1:9223")

    assert browser == {"endpoint": "http://127.0.0.1:9223"}
    assert calls == [("http://127.0.0.1:9223", 120000)]
    assert compaction_calls == ["http://127.0.0.1:9223"]


def test_connect_browser_over_cdp_prefers_browser_websocket_url_for_http_endpoint(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    class _Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {
                "webSocketDebuggerUrl": "ws://192.168.15.104:9224/devtools/browser/browser-1",
            }

    class _Chromium:
        @staticmethod
        def connect_over_cdp(endpoint: str, *, timeout: int):
            calls.append((endpoint, timeout))
            return {"endpoint": endpoint}

    class _Playwright:
        chromium = _Chromium()

    monkeypatch.setattr(
        live_batch_smoke,
        "compact_cdp_page_targets_if_needed",
        lambda _endpoint: {"triggered": False},
    )
    monkeypatch.setattr(
        live_batch_smoke,
        "_cdp_http_get",
        lambda endpoint, path, *, timeout_seconds: _Response()
        if (endpoint, path, timeout_seconds) == ("http://192.168.15.104:9224", "/json/version", live_batch_smoke.DEFAULT_CDP_HTTP_TIMEOUT_SECONDS)
        else (_ for _ in ()).throw(AssertionError((endpoint, path, timeout_seconds))),
    )

    browser = live_batch_smoke.connect_browser_over_cdp(_Playwright(), "http://192.168.15.104:9224")

    assert browser == {"endpoint": "ws://192.168.15.104:9224/devtools/browser/browser-1"}
    assert calls == [("ws://192.168.15.104:9224/devtools/browser/browser-1", 120000)]


def test_resolve_playwright_cdp_endpoint_ignores_host_proxy_env(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {"webSocketDebuggerUrl": "ws://192.168.15.104:9224/devtools/browser/browser-2"}

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True

        def get(self, url: str, *, timeout: float):
            calls.append({"url": url, "timeout": timeout, "trust_env": self.trust_env})
            return _Response()

    monkeypatch.setattr(
        live_batch_smoke.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("requests.get should not be used")),
    )
    monkeypatch.setattr(live_batch_smoke.requests, "Session", _Session)

    endpoint = live_batch_smoke.resolve_playwright_cdp_endpoint("http://192.168.15.104:9224")

    assert endpoint == "ws://192.168.15.104:9224/devtools/browser/browser-2"
    assert calls == [
        {
            "url": "http://192.168.15.104:9224/json/version",
            "timeout": live_batch_smoke.DEFAULT_CDP_HTTP_TIMEOUT_SECONDS,
            "trust_env": False,
        }
    ]


def test_resolve_playwright_cdp_endpoint_falls_back_to_cached_websocket_when_http_probe_fails(monkeypatch) -> None:
    class _FakeProbe:
        @staticmethod
        def _load_cached_cdp_websocket(_endpoint: str) -> str:
            return "ws://192.168.15.104:9224/devtools/browser/cached-browser"

    monkeypatch.setattr(
        live_batch_smoke,
        "_cdp_http_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("http 400 /json/version")),
    )
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)

    endpoint = live_batch_smoke.resolve_playwright_cdp_endpoint("http://192.168.15.104:9224")

    assert endpoint == "ws://192.168.15.104:9224/devtools/browser/cached-browser"


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

    html = live_batch_smoke.read_page_content_with_retries(FakePage(), attempts=3, wait_timeout_ms=250)

    assert html == "<html>ok</html>"
    assert events == ["content:1", "wait:250", "content:2"]


def test_wait_for_detail_ready_returns_when_detail_marker_appears() -> None:
    class FakePage:
        url = "https://sf-item.taobao.com/sf_item/3001.htm"

        def __init__(self) -> None:
            self.contents = [
                "<html><body>shell</body></html>",
                '<html><input id="J_StartPrice" value="100" /></html>',
            ]
            self.waits: list[int] = []

        def content(self) -> str:
            return self.contents.pop(0) if len(self.contents) > 1 else self.contents[0]

        def wait_for_timeout(self, timeout: int) -> None:
            self.waits.append(timeout)

    page = FakePage()

    html = live_batch_smoke._wait_for_detail_ready(page, timeout_ms=1000, poll_interval_ms=50)

    assert 'id="J_StartPrice"' in html
    assert len(page.waits) == 1
    assert 0 < page.waits[0] <= 50


def test_wait_for_detail_ready_returns_challenge_without_waiting() -> None:
    class FakePage:
        url = "https://login.taobao.com/challenge"

        def content(self) -> str:
            return "<html>challenge</html>"

        def wait_for_timeout(self, _timeout: int) -> None:
            raise AssertionError("challenge should stop readiness polling")

    html = live_batch_smoke._wait_for_detail_ready(FakePage(), timeout_ms=1000, poll_interval_ms=50)

    assert html == "<html>challenge</html>"


def test_wait_for_detail_ready_returns_last_html_at_bounded_timeout() -> None:
    waits: list[int] = []

    class FakePage:
        url = "https://sf-item.taobao.com/sf_item/3002.htm"

        def content(self) -> str:
            return "<html><body>shell</body></html>"

        def wait_for_timeout(self, timeout: int) -> None:
            waits.append(timeout)

    html = live_batch_smoke._wait_for_detail_ready(FakePage(), timeout_ms=2, poll_interval_ms=1)

    assert html == "<html><body>shell</body></html>"
    assert len(waits) <= 2


def test_fetch_browser_navigation_list_page_closes_raw_cdp_target_without_playwright(monkeypatch) -> None:
    events: list[str] = []

    def _fail_sync_playwright():
        raise AssertionError("playwright path should not be used for list navigation fallback")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = _fail_sync_playwright
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    def _compact(endpoint: str, targets=None, reserve_for_new_page: bool = False):
        events.append(f"compact:{endpoint}:{reserve_for_new_page}")
        return {"triggered": False}

    def _read_cdp_json(endpoint: str, path: str, *, method: str = "GET", timeout: int = 5):
        events.append(f"read:{endpoint}:{method}:{path}")
        assert timeout == 5
        if method == "PUT":
            return {
                "id": "page-2",
                "type": "page",
                "url": "https://sf.taobao.com/list/page=2",
                "webSocketDebuggerUrl": "ws://cdp/page-2",
            }
        raise AssertionError(f"unexpected read_cdp_json call: {method} {path}")

    def _activate(endpoint: str, target: dict[str, object]) -> None:
        events.append(f"activate:{endpoint}:{target['id']}")

    responses = [
        {
            "result": {
                "result": {
                    "value": {
                        "html": '<html><script id="sf-item-list-data" type="application/json">{"data":[]}</script></html>',
                        "url": "https://sf.taobao.com/list/page=2",
                    }
                }
            }
        }
    ]

    def _evaluate(websocket_url: str, expression: str) -> dict[str, object]:
        events.append(f"evaluate:{websocket_url}")
        assert "document.documentElement.outerHTML" in expression
        return responses.pop(0)

    def _close(endpoint: str, target_id: object) -> bool:
        events.append(f"close:{endpoint}:{target_id}")
        return True

    monkeypatch.setattr(taobao_login_health, "compact_cdp_pages_if_needed", _compact)
    monkeypatch.setattr(taobao_login_health, "read_cdp_json", _read_cdp_json)
    monkeypatch.setattr(taobao_login_health, "activate_cdp_target", _activate)
    monkeypatch.setattr(taobao_login_health, "evaluate_cdp_expression", _evaluate)
    monkeypatch.setattr(taobao_login_health, "close_cdp_target", _close)

    html, final_url = live_batch_smoke.fetch_browser_navigation_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page=2",
    )

    assert "sf-item-list-data" in html
    assert final_url == "https://sf.taobao.com/list/page=2"
    assert events == [
        "compact:http://127.0.0.1:9223:True",
        "read:http://127.0.0.1:9223:PUT:/json/new?https%3A%2F%2Fsf.taobao.com%2Flist%2Fpage%3D2",
        "activate:http://127.0.0.1:9223:page-2",
        "evaluate:ws://cdp/page-2",
        "close:http://127.0.0.1:9223:page-2",
    ]


def test_fetch_browser_list_page_falls_back_to_navigation_when_open_page_probe_closes(monkeypatch) -> None:
    events: list[str] = []

    def _open_page(_cdp_endpoint: str, _target_url: str):
        events.append("open_page")
        raise RuntimeError("Page.wait_for_timeout: Target page, context or browser has been closed")

    def _navigation_page(_cdp_endpoint: str, target_url: str):
        events.append("navigation_page")
        return "<html>ok</html>", target_url

    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_list_page", _open_page)
    monkeypatch.setattr(live_batch_smoke, "fetch_browser_navigation_list_page", _navigation_page)

    html, final_url = live_batch_smoke.fetch_browser_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page=2",
    )

    assert html == "<html>ok</html>"
    assert final_url == "https://sf.taobao.com/list/page=2"
    assert events == ["open_page", "navigation_page"]


def test_is_challenge_page_detects_challenge_url_without_summary_markers(monkeypatch) -> None:
    class _FakeProbe:
        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            assert final_url == "https://contest.local/challenge?ticket=abc"
            return {
                "body_has_login": False,
                "body_has_challenge": False,
            }

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)

    assert live_batch_smoke.is_challenge_page(
        "<html><body>normal body</body></html>",
        "https://contest.local/challenge?ticket=abc",
    )


def test_fetch_open_browser_list_page_reuses_resolved_cdp_target_after_solver_bg_param_is_removed(monkeypatch) -> None:
    events: list[str] = []

    def _fail_sync_playwright():
        raise AssertionError("playwright path should not be used for open list-page reuse")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = _fail_sync_playwright
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    monkeypatch.setattr(
        taobao_login_health,
        "list_cdp_targets",
        lambda _endpoint: [
            {
                "id": "page-5",
                "type": "page",
                "url": "https://sf.taobao.com/list/50025969__2.htm?location_code=530121&st_param=1&auction_start_seg=-1&page=5",
                "webSocketDebuggerUrl": "ws://cdp/page-5",
            }
        ],
    )
    monkeypatch.setattr(
        taobao_login_health,
        "activate_cdp_target",
        lambda endpoint, target: events.append(f"activate:{endpoint}:{target['id']}"),
    )
    monkeypatch.setattr(
        taobao_login_health,
        "evaluate_cdp_expression",
        lambda websocket_url, expression: events.append(f"evaluate:{websocket_url}") or {
            "result": {
                "result": {
                    "value": {
                        "html": "<html><script>var sf-item-list-data = {};</script></html>",
                        "url": "https://sf.taobao.com/list/50025969__2.htm?location_code=530121&st_param=1&auction_start_seg=-1&page=5",
                    }
                }
            }
        },
    )

    html, final_url = live_batch_smoke.fetch_open_browser_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=530121&st_param=1&auction_start_seg=-1&page=5&__captcha_solver_bg=1",
    )

    assert "sf-item-list-data" in html
    assert final_url == "https://sf.taobao.com/list/50025969__2.htm?location_code=530121&st_param=1&auction_start_seg=-1&page=5"
    assert events == [
        "activate:http://127.0.0.1:9223:page-5",
        "evaluate:ws://cdp/page-5",
    ]


def test_fetch_open_browser_list_page_skips_punish_url_after_normalization_via_cdp_target(monkeypatch) -> None:
    events: list[str] = []

    def _fail_sync_playwright():
        raise AssertionError("playwright path should not be used for punish-url matching")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = _fail_sync_playwright
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    punish_url = (
        "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish"
        "?x5secdata=abc&location_code=530121&st_param=1&auction_start_seg=-1&page=5&__captcha_solver_bg=1"
    )
    monkeypatch.setattr(
        taobao_login_health,
        "list_cdp_targets",
        lambda _endpoint: [
            {
                "id": "page-punish",
                "type": "page",
                "url": punish_url,
                "webSocketDebuggerUrl": "ws://cdp/page-punish",
            }
        ],
    )
    monkeypatch.setattr(
        taobao_login_health,
        "activate_cdp_target",
        lambda endpoint, target: events.append(f"activate:{endpoint}:{target['id']}"),
    )
    monkeypatch.setattr(
        taobao_login_health,
        "evaluate_cdp_expression",
        lambda websocket_url, expression: events.append(f"evaluate:{websocket_url}") or {
            "result": {
                "result": {
                    "value": {
                        "html": "<html><script>var sf-item-list-data = {};</script></html>",
                        "url": punish_url,
                    }
                }
            }
        },
    )

    result = live_batch_smoke.fetch_open_browser_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=530121&st_param=1&auction_start_seg=-1&page=5",
    )

    assert result is None
    assert events == [
        "activate:http://127.0.0.1:9223:page-punish",
        "evaluate:ws://cdp/page-punish",
    ]


def test_fetch_open_browser_list_page_skips_login_then_uses_second_valid_target(monkeypatch) -> None:
    read_targets: list[str] = []

    monkeypatch.setattr(
        live_batch_smoke,
        "_find_matching_cdp_list_targets",
        lambda _cdp_endpoint, _target_url: [
            {"id": "login-page"},
            {"id": "healthy-page"},
        ],
    )

    def _read_target(_cdp_endpoint: str, target: dict[str, str]) -> tuple[str, str]:
        read_targets.append(target["id"])
        if target["id"] == "login-page":
            return "<html>淘宝登录</html>", "https://login.taobao.com/member/login.jhtml"
        return (
            "<html><script>var sf-item-list-data = {};</script><body>ok</body></html>",
            "https://sf.taobao.com/list/page=8",
        )

    monkeypatch.setattr(live_batch_smoke, "_read_cdp_list_target_html", _read_target)

    html, final_url = live_batch_smoke.fetch_open_browser_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page=8",
    )

    assert "sf-item-list-data" in html
    assert final_url == "https://sf.taobao.com/list/page=8"
    assert read_targets == ["login-page", "healthy-page"]


def test_fetch_browser_list_page_falls_back_to_navigation_after_login_html(monkeypatch) -> None:
    events: list[str] = []

    def _open_page(_cdp_endpoint: str, _target_url: str):
        events.append("open_page")
        return None

    def _navigation_page(_cdp_endpoint: str, target_url: str):
        events.append("navigation_page")
        return "<html>ok</html>", target_url

    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_list_page", _open_page)
    monkeypatch.setattr(live_batch_smoke, "fetch_browser_navigation_list_page", _navigation_page)

    html, final_url = live_batch_smoke.fetch_browser_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page=9",
    )

    assert html == "<html>ok</html>"
    assert final_url == "https://sf.taobao.com/list/page=9"
    assert events == ["open_page", "navigation_page"]


def test_compact_cdp_page_targets_keeps_browser_alive_at_limit(monkeypatch) -> None:
    calls: list[str] = []

    class _Response:
        def __init__(self, payload: object):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self._payload

    def _get(endpoint: str, path: str, *, timeout_seconds: float):
        calls.append(f"{endpoint}{path}")
        if path == "/json/list":
            return _Response(
                [
                    {"id": "page-1", "type": "page", "url": "https://sf.taobao.com/"},
                    {"id": "page-2", "type": "page", "url": "about:blank"},
                    {"id": "worker-1", "type": "service_worker", "url": "chrome-extension://x"},
                    {"id": "page-3", "type": "page", "url": "https://sf.taobao.com/list/1"},
                ]
            )
        return _Response({})

    def _put(endpoint: str, path: str, *, timeout_seconds: float):
        calls.append(f"PUT {endpoint}{path}")
        if path == "/json/new?about:blank":
            return _Response({"id": "keepalive-page"})
        return _Response({})

    monkeypatch.setattr(live_batch_smoke, "_cdp_http_get", _get)
    monkeypatch.setattr(live_batch_smoke, "_cdp_http_put", _put)

    summary = live_batch_smoke.compact_cdp_page_targets_if_needed("http://127.0.0.1:9223", limit=3)

    assert summary["triggered"] is True
    assert summary["page_count"] == 3
    assert summary["closed"] == 3
    assert summary["keepalive_target_id"] == "keepalive-page"
    assert calls == [
        "http://127.0.0.1:9223/json/list",
        "PUT http://127.0.0.1:9223/json/new?about:blank",
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

    def _get(endpoint: str, path: str, *, timeout_seconds: float):
        calls.append(f"{endpoint}{path}")
        return _Response()

    monkeypatch.setattr(live_batch_smoke, "_cdp_http_get", _get)

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


def test_fetch_browser_navigation_list_page_wraps_cdp_target_open_timeout(monkeypatch) -> None:
    monkeypatch.setattr(
        taobao_login_health,
        "compact_cdp_pages_if_needed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("timed out")),
    )

    with pytest.raises(live_batch_smoke.CdpEndpointUnavailableError) as excinfo:
        live_batch_smoke.fetch_browser_navigation_list_page(
            "http://127.0.0.1:9223",
            "https://sf.taobao.com/list/page",
        )

    assert excinfo.value.cdp_endpoint == "http://127.0.0.1:9223"
    assert excinfo.value.operation == "open_list_page_target"


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


def test_fetch_list_page_honors_list_http_timeout_env(monkeypatch) -> None:
    captured: list[float] = []

    class _OkResponse:
        text = "<html><script>var sf-item-list-data = {}</script></html>"
        url = "https://sf.taobao.com/list/page=2"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _Http:
        @staticmethod
        def get(*_args, **kwargs):
            captured.append(kwargs["timeout"])
            return _OkResponse()

    monkeypatch.setenv("FAPAI_LIST_HTTP_TIMEOUT_SECONDS", "8")

    html, final_url, status, method = live_batch_smoke.fetch_list_page(
        _Http(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=2",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
    )

    assert "sf-item-list-data" in html
    assert final_url == "https://sf.taobao.com/list/page=2"
    assert status == 200
    assert method == "http_cookie"
    assert captured == [8.0]


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
        lambda cdp_endpoint, target_url, **_kwargs: report_calls.append((cdp_endpoint, target_url)) or {"status": "solving"},
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


def test_request_captcha_solver_uses_default_api_base_and_normalizes_non_dict_response(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        taobao_login_health,
        "build_captcha_solver_target_url",
        lambda target_url: calls.append(("build", target_url)) or "https://contest.local/auth?__captcha_solver_bg=1",
    )
    monkeypatch.setattr(
        taobao_login_health,
        "report_captcha_via_api",
        lambda api_base_url, cdp_endpoint, target_url: calls.append(
            ("report", {"api_base_url": api_base_url, "cdp_endpoint": cdp_endpoint, "target_url": target_url})
        )
        or ["queued"],
    )

    result = live_batch_smoke.request_captcha_solver(
        "http://127.0.0.1:9223",
        "https://contest.local/auth",
    )

    assert result == {"status": "unknown_response", "raw": ["queued"]}
    assert calls == [
        ("build", "https://contest.local/auth"),
        (
            "report",
            {
                "api_base_url": live_batch_smoke.DEFAULT_API_BASE_URL,
                "cdp_endpoint": "http://127.0.0.1:9223",
                "target_url": "https://contest.local/auth?__captcha_solver_bg=1",
            },
        ),
    ]


def test_request_captcha_solver_preserves_dict_response_and_explicit_api_base(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    target_url = "https://contest.local/auth?__captcha_solver_bg=1"

    monkeypatch.setattr(
        taobao_login_health,
        "build_captcha_solver_target_url",
        lambda url: calls.append(("build", url)) or target_url,
    )
    monkeypatch.setattr(
        taobao_login_health,
        "report_captcha_via_api",
        lambda api_base_url, cdp_endpoint, solver_target_url: calls.append(
            (
                "report",
                {
                    "api_base_url": api_base_url,
                    "cdp_endpoint": cdp_endpoint,
                    "target_url": solver_target_url,
                },
            )
        )
        or {"status": "already_running", "target_url": solver_target_url},
    )

    result = live_batch_smoke.request_captcha_solver(
        "http://127.0.0.1:9223",
        target_url,
        api_base_url="http://collection-api.test/api",
    )

    assert result == {"status": "already_running", "target_url": target_url}
    assert calls == [
        ("build", target_url),
        (
            "report",
            {
                "api_base_url": "http://collection-api.test/api",
                "cdp_endpoint": "http://127.0.0.1:9223",
                "target_url": target_url,
            },
        ),
    ]


def test_request_captcha_solver_keeps_real_taobao_on_automatic_solver_path(monkeypatch) -> None:
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
        "https://sf-item.taobao.com/sf_item/3001.htm",
        api_base_url="http://collection-api.test/api",
    )

    assert result == {"status": "manual_required"}
    assert captured["kwargs"] == {}


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
    report_calls: list[tuple[str, str]] = []

    def _fetch_browser_list_page(cdp_endpoint: str, target_url: str):
        fetch_calls.append((cdp_endpoint, target_url))
        return browser_results.pop(0)

    monkeypatch.setattr(live_batch_smoke, "fetch_browser_list_page", _fetch_browser_list_page)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(
        live_batch_smoke,
        "request_captcha_solver",
        lambda cdp_endpoint, target_url, **_kwargs: report_calls.append((cdp_endpoint, target_url)) or {"status": "solving"},
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
        ("http://127.0.0.1:9223", "https://sf.taobao.com/list/page=5/_____tmd_____/punish?x5secdata=first")
    ]


def test_recover_browser_list_page_after_challenge_retries_login_page_until_healthy(monkeypatch) -> None:
    browser_results = [
        (
            "<html><script>var sf-item-list-data = {};</script><body>ok</body></html>",
            "https://sf.taobao.com/list/page=10",
        ),
    ]
    fetch_calls: list[tuple[str, str]] = []
    sleep_calls: list[float] = []
    report_calls: list[tuple[str, str]] = []

    def _fetch_browser_list_page(cdp_endpoint: str, target_url: str):
        fetch_calls.append((cdp_endpoint, target_url))
        return browser_results.pop(0)

    monkeypatch.setattr(live_batch_smoke, "fetch_browser_list_page", _fetch_browser_list_page)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(
        live_batch_smoke,
        "request_captcha_solver",
        lambda cdp_endpoint, target_url, **_kwargs: report_calls.append((cdp_endpoint, target_url)) or {"status": "solving"},
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
            "https://login.taobao.com/member/login.jhtml?redirect=https://sf.taobao.com/list/page=10",
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
    report_calls: list[tuple[str, str]] = []

    def _fetch_browser_list_page(cdp_endpoint: str, target_url: str):
        fetch_calls.append((cdp_endpoint, target_url))
        return browser_results.pop(0)

    monkeypatch.setattr(live_batch_smoke, "fetch_browser_list_page", _fetch_browser_list_page)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(
        live_batch_smoke,
        "request_captcha_solver",
        lambda cdp_endpoint, target_url, **_kwargs: report_calls.append((cdp_endpoint, target_url)) or {"status": "solving"},
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
            "https://login.taobao.com/member/login.jhtml?redirect=https://sf.taobao.com/list/page=11&step=1",
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


def test_collect_list_union_preserves_first_fetch_status_method_and_metadata(monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "has_script": True,
                "item_count": 2,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
                "final_url": final_url,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"data": [{"id": "first"}, {"id": "second"}]}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [
                    {"id": "first", "url": "https://sf-item.taobao.com/sf_item/first.htm"},
                    {"id": "second", "url": "https://sf-item.taobao.com/sf_item/second.htm"},
                ],
            }

    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: (
            "list-html",
            "https://sf.taobao.com/list/page=1&redirected=1",
            206,
            "browser_page_after_http_challenge",
        ),
    )

    result = live_batch_smoke.collect_list_union(
        _FakeProbe,
        object(),
        live_batch_smoke.LiveSmokeConfig(
            output_dir=Path("out"),
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page=1",
            target_success=1,
            max_attempts=1,
            do_risk=False,
        ),
    )

    assert result["first_fetch"] == {
        "url": "https://sf.taobao.com/list/page=1?st_param=2&page=1",
        "location_code": "",
        "category": "",
        "st_param": "2",
        "page": 1,
        "list_status": 206,
        "list_final_url": "https://sf.taobao.com/list/page=1&redirected=1",
        "list_fetch_method": "browser_page_after_http_challenge",
        "list_item_count": 2,
        "body_has_challenge": False,
        "body_has_login": False,
        "body_has_punish": False,
        "payload_present": True,
    }
    assert result["list_union"]["sources"][0]["list_status"] == 206
    assert result["list_union"]["sources"][0]["list_fetch_method"] == "browser_page_after_http_challenge"
    assert result["list_union"]["sources"][0]["eligible_item_count"] == 2


def test_collect_list_union_raises_when_first_page_fetch_error_leaves_no_successful_payload(monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            raise AssertionError("summary should not run when fetch fails")

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            raise AssertionError("payload extraction should not run when fetch fails")

    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: (_ for _ in ()).throw(
            RuntimeError("browser challenge timeout")
        ),
    )

    with pytest.raises(RuntimeError, match="list payload missing for all list sources"):
        live_batch_smoke.collect_list_union(
            _FakeProbe,
            object(),
            live_batch_smoke.LiveSmokeConfig(
                output_dir=Path("out"),
                cdp_endpoint="http://127.0.0.1:9223",
                target_url="https://sf.taobao.com/list/page=1",
                target_success=1,
                max_attempts=1,
                do_risk=False,
            ),
        )


def test_collect_list_union_challenge_stops_only_same_sort_key(monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(html: str, *, final_url: str) -> dict[str, object]:
            is_challenge = html == "challenge"
            return {
                "has_script": not is_challenge,
                "item_count": 1 if not is_challenge else None,
                "body_has_challenge": is_challenge,
                "body_has_login": False,
                "body_has_punish": is_challenge,
                "final_url": final_url,
            }

        @staticmethod
        def extract_list_payload(html: str) -> dict[str, object] | None:
            return None if html == "challenge" else {"data": [{"id": html}]}

        @staticmethod
        def build_userscript_like_batch_payload(payload, *, source_page_url: str) -> dict[str, object]:
            item_id = payload["data"][0]["id"]
            return {
                "source_page_url": source_page_url,
                "items": [{"id": item_id, "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm"}],
            }

    fetched: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint, target_url, user_agent):
        fetched.append(target_url)
        query = parse_qs(urlparse(target_url).query)
        page = int(query.get("page", ["1"])[0])
        st_param = query.get("st_param", ["2"])[0]
        if st_param == "2" and page == 1:
            return "st2-page1", target_url, 200, "http_cookie"
        if st_param == "2" and page == 2:
            return "challenge", target_url, 200, "http_cookie_challenge"
        return f"st{st_param}-page{page}", target_url, 200, "http_cookie"

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
            list_st_params=("2", "1"),
            list_location_codes=("110101",),
            list_categories=("50025969",),
            list_max_pages=3,
            list_stop_on_empty=True,
        ),
    )

    assert len(fetched) == 5
    assert "st_param=2&page=3" not in "".join(fetched)
    assert any("st_param=1&page=3" in url for url in fetched)
    sources = result["list_union"]["sources"]
    assert sources[2]["skipped"] is True
    assert sources[2]["skip_reason"] == "previous_empty_page"
    assert sources[5]["eligible_item_count"] == 1
    assert [item["id"] for item in result["items"]] == [
        "st2-page1",
        "st1-page1",
        "st1-page2",
        "st1-page3",
    ]


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


def test_load_resume_state_recovers_invalid_json_and_non_mapping_payload(tmp_path: Path) -> None:
    invalid_json_path = tmp_path / "invalid-resume.json"
    invalid_json_path.write_text("{", encoding="utf-8")

    invalid_json_state = live_batch_smoke.load_resume_state(invalid_json_path)
    assert invalid_json_state["schema_version"] == live_batch_smoke.RESUME_SCHEMA_VERSION
    assert invalid_json_state["items"] == {}

    list_payload_path = tmp_path / "list-resume.json"
    list_payload_path.write_text(json.dumps(["not-a-dict"]), encoding="utf-8")

    list_payload_state = live_batch_smoke.load_resume_state(list_payload_path)
    assert list_payload_state["schema_version"] == live_batch_smoke.RESUME_SCHEMA_VERSION
    assert list_payload_state["items"] == {}


def test_load_resume_state_normalizes_missing_schema_and_non_mapping_items(tmp_path: Path) -> None:
    state_path = tmp_path / "resume_state.json"
    state_path.write_text(
        json.dumps({"schema_version": "", "items": [], "updated_at": "2026-08-13T00:00:00Z"}),
        encoding="utf-8",
    )

    loaded = live_batch_smoke.load_resume_state(state_path)

    assert loaded["schema_version"] == live_batch_smoke.RESUME_SCHEMA_VERSION
    assert loaded["items"] == {}
    assert loaded["updated_at"] == "2026-08-13T00:00:00Z"


def test_hydrate_resume_state_requires_both_final_and_selected_artifacts(tmp_path: Path) -> None:
    state = live_batch_smoke.new_resume_state()
    (tmp_path / "final-only").mkdir()
    (tmp_path / "selected-only").mkdir()
    (tmp_path / "complete").mkdir()
    (tmp_path / "final-only" / "final.json").write_text("{}", encoding="utf-8")
    (tmp_path / "selected-only" / "selected.json").write_text("{}", encoding="utf-8")
    (tmp_path / "complete" / "final.json").write_text("{}", encoding="utf-8")
    (tmp_path / "complete" / "selected.json").write_text("{}", encoding="utf-8")

    hydrated = live_batch_smoke.hydrate_resume_state_from_artifacts(
        state,
        [
            {"id": "final-only", "url": "https://example.test/final-only", "title": "final only"},
            {"id": "selected-only", "url": "https://example.test/selected-only", "title": "selected only"},
            {"id": "complete", "url": "https://example.test/complete", "title": "complete"},
        ],
        output_dir=tmp_path,
    )

    assert hydrated == ["complete"]
    assert live_batch_smoke.is_resume_completed(state, "final-only") is False
    assert live_batch_smoke.is_resume_completed(state, "selected-only") is False
    assert live_batch_smoke.is_resume_completed(state, "complete") is True


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


def test_run_live_smoke_preserves_browser_recovered_list_fetch_method_when_all_candidates_are_completed(
    tmp_path: Path, monkeypatch
) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "item_count": 1,
                "final_url": final_url,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [{"id": "a", "url": "https://sf-item.taobao.com/sf_item/a.htm"}],
            }

    item_dir = tmp_path / "a"
    item_dir.mkdir()
    (item_dir / "final.json").write_text("{}", encoding="utf-8")
    (item_dir / "selected.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: (
            "list",
            target_url,
            None,
            "browser_page_after_http_challenge",
        ),
    )
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(
        live_batch_smoke,
        "process_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("all candidates should already be completed")),
    )

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            resume_state_path=tmp_path / "resume_state.json",
            resume_enabled=True,
        )
    )

    assert exit_code == 0
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["list_fetch_method"] == "browser_page_after_http_challenge"
    assert summary["artifact_completed_items"] == 1
    assert summary["skipped_completed_items"] == 1
    assert summary["no_candidate_reason"] == "all_candidates_already_completed"


def test_run_live_smoke_records_browser_recovered_list_fetch_and_result_detail_methods(
    tmp_path: Path, monkeypatch
) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "item_count": 2,
                "final_url": final_url,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [
                    {"id": "open-detail", "url": "https://sf-item.taobao.com/sf_item/open-detail.htm"},
                    {"id": "nav-detail", "url": "https://sf-item.taobao.com/sf_item/nav-detail.htm"},
                ],
            }

    processed_ids: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        result = _result(str(seed["id"]), area_sqm=88.8, unit_price=12345, desc_area=88.8)
        result["fetch"]["method"] = "open_browser_page" if seed["id"] == "open-detail" else "browser_navigation"
        return result

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: (
            "list",
            target_url,
            None,
            "browser_page_after_http_challenge",
        ),
    )
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=2,
            max_attempts=2,
            do_risk=False,
            resume_state_path=tmp_path / "resume_state.json",
            resume_enabled=True,
        )
    )

    assert exit_code == 0
    assert processed_ids == ["open-detail", "nav-detail"]
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["list_fetch_method"] == "browser_page_after_http_challenge"
    assert summary["processed_items"] == 2
    assert [row["fetch"]["method"] for row in summary["results"]] == [
        "open_browser_page",
        "browser_navigation",
    ]


def test_run_live_smoke_no_eligible_items_records_summary_and_followup_queue(tmp_path: Path, monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "item_count": 0,
                "final_url": final_url,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {"source_page_url": source_page_url, "items": []}

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: (
            "list",
            "https://sf.taobao.com/list/page=1&redirected=1",
            206,
            "browser_page_after_http_challenge",
        ),
    )
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(
        live_batch_smoke,
        "process_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no items should be processed")),
    )

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page=1",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            resume_state_path=tmp_path / "resume_state.json",
            resume_enabled=True,
        )
    )

    assert exit_code == 1
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["no_candidate_reason"] == "no_eligible_done_items"
    assert summary["eligible_done_item_count"] == 0
    assert summary["attempted_items"] == 0
    assert summary["processed_items"] == 0
    assert summary["list_status"] == 206
    assert summary["list_fetch_method"] == "browser_page_after_http_challenge"
    assert summary["list_final_url"] == "https://sf.taobao.com/list/page=1&redirected=1"
    queue = live_batch_smoke.load_json(tmp_path / "area_followup_queue.json")
    assert queue["job_count"] == 0
    assert queue["source_summary"] == str(tmp_path / "summary.json")


def test_run_live_smoke_marks_failed_item_in_resume_state_and_summary_error(tmp_path: Path, monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "item_count": 1,
                "final_url": final_url,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [
                    {
                        "id": "failed-item",
                        "url": "https://sf-item.taobao.com/sf_item/failed-item.htm",
                        "title": "失败标的",
                    }
                ],
            }

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: ("list", target_url, 200, "http_cookie"),
    )
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(
        live_batch_smoke,
        "process_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("detail pipeline exploded")),
    )
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda _seconds: None)

    resume_state_path = tmp_path / "resume_state.json"
    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page=1",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            resume_state_path=resume_state_path,
            resume_enabled=True,
        )
    )

    assert exit_code == 1
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["attempted_items"] == 1
    assert summary["processed_items"] == 0
    assert summary["error_count"] == 1
    assert summary["errors"][0]["item_id"] == "failed-item"
    assert "detail pipeline exploded" in summary["errors"][0]["error"]
    error_payload = live_batch_smoke.load_json(tmp_path / "failed-item.error.json")
    assert error_payload["item_id"] == "failed-item"
    assert "detail pipeline exploded" in error_payload["error"]
    resume_state = live_batch_smoke.load_resume_state(resume_state_path)
    assert resume_state["items"]["failed-item"]["status"] == "failed"
    assert resume_state["items"]["failed-item"]["attempts"] == 1
    assert "detail pipeline exploded" in resume_state["items"]["failed-item"]["error"]


def test_run_live_smoke_stops_after_target_success_without_processing_remaining_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "item_count": 3,
                "final_url": final_url,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [
                    {"id": "a", "url": "https://sf-item.taobao.com/sf_item/a.htm"},
                    {"id": "b", "url": "https://sf-item.taobao.com/sf_item/b.htm"},
                    {"id": "c", "url": "https://sf-item.taobao.com/sf_item/c.htm"},
                ],
            }

    processed_ids: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        return _result(str(seed["id"]), area_sqm=88.8, unit_price=12345, desc_area=88.8)

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: ("list", target_url, 200, "http_cookie"),
    )
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda _seconds: None)

    resume_state_path = tmp_path / "resume_state.json"
    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page=1",
            target_success=1,
            max_attempts=3,
            do_risk=False,
            resume_state_path=resume_state_path,
            resume_enabled=True,
        )
    )

    assert exit_code == 0
    assert processed_ids == ["a"]
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["attempted_items"] == 1
    assert summary["processed_items"] == 1
    resume_state = live_batch_smoke.load_resume_state(resume_state_path)
    assert live_batch_smoke.is_resume_completed(resume_state, "a") is True
    assert "b" not in resume_state["items"]
    assert "c" not in resume_state["items"]


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


def test_positive_int_rejects_zero_and_negative() -> None:
    assert live_batch_smoke.positive_int("3") == 3

    for raw in ("0", "-2"):
        try:
            live_batch_smoke.positive_int(raw)
        except Exception as exc:
            assert isinstance(exc, live_batch_smoke.argparse.ArgumentTypeError)
            assert str(exc) == "must be >= 1"
        else:
            raise AssertionError(f"expected positive_int({raw!r}) to raise ArgumentTypeError")


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
