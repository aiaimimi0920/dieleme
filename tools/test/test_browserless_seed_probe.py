from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

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


def test_write_cookie_snapshot_persists_json_payload(tmp_path: Path):
    output_path = tmp_path / "cookies.json"
    cookies = [{"name": "cookie2", "value": "abc"}]

    browserless_seed_probe.write_cookie_snapshot(cookies, output_path)

    assert json.loads(output_path.read_text(encoding="utf-8")) == cookies
