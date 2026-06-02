from __future__ import annotations

from pathlib import Path
from typing import Any

from src.storage.repository import DatabaseSettings, PropertyRepository
from tools import seed_collector


class _FakeProbe:
    DEFAULT_USER_AGENT = "fake-agent"

    @staticmethod
    def summarize_list_page(html: str, *, final_url: str) -> dict[str, Any]:
        if html == "challenge":
            return {
                "item_count": None,
                "body_has_challenge": True,
                "body_has_login": False,
                "body_has_punish": True,
            }
        return {
            "item_count": 2,
            "body_has_challenge": False,
            "body_has_login": False,
            "body_has_punish": False,
        }

    @staticmethod
    def extract_list_payload(html: str) -> dict[str, Any] | None:
        if html == "challenge":
            return None
        return {"data": [{"id": "2001"}, {"id": "2002"}]}

    @staticmethod
    def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, Any]:
        return {
            "source_page_url": source_page_url,
            "items": [
                {"id": "2001", "title": "南沙 A", "url": "https://sf-item.taobao.com/sf_item/2001.htm"},
                {"id": "2002", "title": "南沙 B", "url": "https://sf-item.taobao.com/sf_item/2002.htm"},
            ],
        }


def _make_repo(tmp_path: Path) -> PropertyRepository:
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'seed-collector.sqlite3').resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def test_parse_seed_sort_specs_accepts_named_final_sort_contract() -> None:
    specs = seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远")

    assert [spec.as_dict() for spec in specs] == [
        {"sort_key": "bid_desc", "st_param": "2", "sort_name": "出价次数由高到低", "sort_order": 0},
        {"sort_key": "end_time_soon", "st_param": "1", "sort_name": "结拍时间由近到远", "sort_order": 1},
    ]


def test_run_seed_collector_once_claims_one_page_and_populates_detail_queue(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    fetched_urls: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint: str, target_url: str, user_agent: str):
        fetched_urls.append(target_url)
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)

    summary = seed_collector.run_seed_collector_once(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_page_collected"
    assert summary["task"]["sort_key"] == "bid_desc"
    assert summary["task"]["page"] == 1
    assert summary["upsert"] == {"seen": 2, "new_items": 2, "existing_items": 0, "new_occurrences": 2}
    assert fetched_urls == [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1"
    ]
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 2


def test_run_seed_collector_once_marks_scan_page_retryable_on_challenge(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)

    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: ("challenge", target_url, 200, "browser_page"),
    )

    summary = seed_collector.run_seed_collector_once(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_page_retryable_failure"
    assert summary["reason"] == "list_payload_missing"
    retry = repo.claim_seed_scan_page("seed-retry", lease_seconds=30)
    assert retry is not None
    assert retry["page"] == 1


def test_run_seed_collector_loop_collects_multiple_pages_per_cycle(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    fetched_urls: list[str] = []
    sleep_calls: list[int] = []

    def _fetch_list_page(_http, *, cdp_endpoint: str, target_url: str, user_agent: str):
        fetched_urls.append(target_url)
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    summary = seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            max_runs=1,
            pages_per_run=3,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_collector_loop_finished"
    assert summary["runs"] == 1
    assert summary["pages_attempted"] == 3
    assert [result["task"]["page"] for result in summary["results"]] == [1, 2, 3]
    assert len(fetched_urls) == 3
    assert sleep_calls == []
    assert repo.seed_queue_counts()["seed_scan_progress_pending"] == 1
