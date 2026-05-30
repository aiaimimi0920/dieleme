from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any

from tools import hybrid_seed_collector


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
        }
    ]
}


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, url: str, text: str, json_payload: dict[str, Any] | None = None):
        self.status_code = status_code
        self.url = url
        self.text = text
        self._json_payload = json_payload or {}

    def json(self) -> dict[str, Any]:
        return self._json_payload


class _FakeHttpSession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.get_calls: list[dict[str, Any]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: int, allow_redirects: bool):
        self.get_calls.append(
            {
                "url": url,
                "headers": headers,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )
        return self.response


class _FakeApiSession:
    def __init__(self):
        self.post_calls: list[dict[str, Any]] = []

    def post(self, url: str, *, json: dict[str, Any], timeout: int):
        self.post_calls.append({"url": url, "json": json, "timeout": timeout})
        if url.endswith("/collection/seeds/batch"):
            return _FakeResponse(url=url, text="{}", json_payload={"new": 1})
        return _FakeResponse(url=url, text="{}", json_payload={"status": "ok", "updated": True})


def test_classify_probe_summary_marks_login_as_browser_fallback():
    decision = hybrid_seed_collector.classify_probe_summary(
        {
            "has_script": False,
            "body_has_login": True,
            "body_has_challenge": False,
            "body_has_punish": False,
        }
    )

    assert decision == {
        "decision": "browser_fallback_required",
        "reason": "login_required",
    }


def test_classify_probe_summary_marks_punish_as_browser_fallback():
    decision = hybrid_seed_collector.classify_probe_summary(
        {
            "has_script": False,
            "body_has_login": False,
            "body_has_challenge": True,
            "body_has_punish": True,
        }
    )

    assert decision == {
        "decision": "browser_fallback_required",
        "reason": "challenge_detected",
    }


def test_run_hybrid_collection_returns_batch_payload_on_browserless_success():
    html = """
    <script id="sf-item-list-data" type="application/json">
      {"data": [{"id": 747988656830, "title": "测试法拍房 A", "currentPrice": 1234567,
                 "initialPrice": 1000000, "end": "2026-05-18 10:00:00",
                 "startTime": "2026-05-17 10:00:00",
                 "itemUrl": "//sf-item.taobao.com/sf_item/747988656830.htm?track_id=demo-1",
                 "status": "done", "bidCount": 2, "bidUserNumber": 1, "applyCount": 1,
                 "watchCount": 10, "remindCount": 5, "viewCount": 30,
                 "itemAddress": "浙江省杭州市西湖区测试小区 1 幢 2 单元 301 室",
                 "district": "西湖区", "city": "杭州市", "latitude": 30.27, "longitude": 120.15,
                 "auctionRound": "一拍", "housingType": "住宅", "deposit": 100000}]}
    </script>
    """
    result = hybrid_seed_collector.run_hybrid_collection(
        "https://sf.taobao.com/list/50025969__2.htm?page=1",
        cookies=[{"name": "cookie2", "value": "abc", "domain": ".taobao.com", "path": "/"}],
        browserless_session=_FakeHttpSession(
            _FakeResponse(
                url="https://sf.taobao.com/list/50025969__2.htm?page=1",
                text=html,
            )
        ),
        submit=False,
    )

    assert result["decision"] == "browserless_success"
    assert result["reason"] is None
    assert result["probe_summary"]["item_count"] == 1
    assert result["batch_payload"]["source_page_url"] == "https://sf.taobao.com/list/50025969__2.htm?page=1"
    assert len(result["batch_payload"]["items"]) == 1


def test_run_hybrid_collection_submits_batch_and_progress_when_requested():
    html = """
    <script id="sf-item-list-data" type="application/json">
      {"data": [{"id": 747988656830, "title": "测试法拍房 A", "currentPrice": 1234567,
                 "initialPrice": 1000000, "end": "2026-05-18 10:00:00",
                 "startTime": "2026-05-17 10:00:00",
                 "itemUrl": "//sf-item.taobao.com/sf_item/747988656830.htm?track_id=demo-1",
                 "status": "done", "bidCount": 2, "bidUserNumber": 1, "applyCount": 1,
                 "watchCount": 10, "remindCount": 5, "viewCount": 30,
                 "itemAddress": "浙江省杭州市西湖区测试小区 1 幢 2 单元 301 室",
                 "district": "西湖区", "city": "杭州市", "latitude": 30.27, "longitude": 120.15,
                 "auctionRound": "一拍", "housingType": "住宅", "deposit": 100000}]}
    </script>
    """
    api_session = _FakeApiSession()
    result = hybrid_seed_collector.run_hybrid_collection(
        "https://sf.taobao.com/list/50025969__2.htm?page=3",
        cookies=[{"name": "cookie2", "value": "abc", "domain": ".taobao.com", "path": "/"}],
        browserless_session=_FakeHttpSession(
            _FakeResponse(
                url="https://sf.taobao.com/list/50025969__2.htm?page=3",
                text=html,
            )
        ),
        submit=True,
        api_base="http://127.0.0.1:8001/api",
        api_session=api_session,
    )

    assert result["decision"] == "browserless_success"
    assert result["submit_result"] == {
        "batch": {"new": 1},
        "progress": {"status": "ok", "updated": True},
    }
    assert [call["url"] for call in api_session.post_calls] == [
        "http://127.0.0.1:8001/api/collection/seeds/batch",
        "http://127.0.0.1:8001/api/collection/seeds/report_progress",
    ]
    assert api_session.post_calls[1]["json"] == {
        "url": "https://sf.taobao.com/list/50025969__2.htm?page=3",
        "has_next": True,
        "is_empty": False,
        "page_num": 3,
        "zero_bid_detected": False,
    }


def test_run_hybrid_collection_does_not_submit_when_browser_fallback_is_required():
    api_session = _FakeApiSession()
    result = hybrid_seed_collector.run_hybrid_collection(
        "https://sf.taobao.com/list/50025969__2.htm?page=1",
        cookies=[{"name": "cookie2", "value": "abc", "domain": ".taobao.com", "path": "/"}],
        browserless_session=_FakeHttpSession(
            _FakeResponse(
                url="https://sf.taobao.com/list/50025969__2.htm?page=1",
                text="<script>sessionStorage.x5referer='x';var url='//sf.taobao.com/_____tmd_____/punish?x5secdata=demo';</script>",
            )
        ),
        submit=True,
        api_base="http://127.0.0.1:8001/api",
        api_session=api_session,
    )

    assert result["decision"] == "browser_fallback_required"
    assert result["reason"] == "challenge_detected"
    assert api_session.post_calls == []


def test_hybrid_seed_collector_script_can_run_help_from_repo_root():
    repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "hybrid_seed_collector.py"), "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    assert "browserless first" in result.stdout
