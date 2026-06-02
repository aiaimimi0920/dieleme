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


def _make_repo_at(db_path: Path) -> PropertyRepository:
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
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


def test_run_seed_collector_once_resumes_after_restart_without_researching_completed_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "seed-resume.sqlite3"
    config = seed_collector.SeedCollectorConfig(
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
    )
    fetched_urls: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint: str, target_url: str, user_agent: str):
        fetched_urls.append(target_url)
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)

    first_repo = _make_repo_at(db_path)
    first_summary = seed_collector.run_seed_collector_once(
        config,
        repository=first_repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    restarted_repo = _make_repo_at(db_path)
    second_summary = seed_collector.run_seed_collector_once(
        config,
        repository=restarted_repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert first_summary["task"]["sort_key"] == "bid_desc"
    assert first_summary["task"]["page"] == 1
    assert second_summary["task"]["sort_key"] == "bid_desc"
    assert second_summary["task"]["page"] == 2
    assert fetched_urls == [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=2",
    ]
    assert restarted_repo.seed_queue_counts()["seed_occurrence_total"] == 4


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


def test_run_seed_collector_loop_waits_instead_of_exiting_when_queue_is_empty(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    sleep_calls: list[int] = []

    monkeypatch.setattr(
        seed_collector,
        "run_seed_collector_once",
        lambda *_args, **_kwargs: {"decision": "seed_scan_queue_empty", "counts": {"seed_item_pending_detail": 0}},
    )
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
            loop_interval_seconds=7,
            max_runs=2,
            pages_per_run=3,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_collector_loop_finished"
    assert summary["runs"] == 2
    assert summary["pages_attempted"] == 0
    assert summary["last_decision"] == "seed_scan_queue_empty"
    assert sleep_calls == [7]


def test_run_seed_collector_loop_refreshes_runtime_context_each_cycle(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    contexts: list[str] = []
    used_sessions: list[str] = []

    def _runtime_context_factory() -> str:
        context = f"http-{len(contexts) + 1}"
        contexts.append(context)
        return context

    def _run_once(_config, *, repository, http_session, browserless_seed_probe):
        used_sessions.append(http_session)
        return {"decision": "seed_scan_queue_empty", "counts": repository.seed_queue_counts()}

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", _run_once)
    monkeypatch.setattr(seed_collector.time, "sleep", lambda _seconds: None)

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
            loop_interval_seconds=1,
            max_runs=2,
            pages_per_run=3,
        ),
        repository=repo,
        browserless_seed_probe=_FakeProbe,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=lambda _event: None,
    )

    assert summary["decision"] == "seed_collector_loop_finished"
    assert contexts == ["http-1", "http-2"]
    assert used_sessions == contexts


def test_run_seed_collector_loop_emits_compact_run_and_sleep_events(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    run_results = iter(
        [
            {"decision": "seed_page_collected", "item_count": 2, "has_next": True, "counts": {"seed_item_pending_detail": 2}},
            {"decision": "seed_scan_queue_empty", "counts": {"seed_item_pending_detail": 2}},
            {"decision": "seed_scan_queue_empty", "counts": {"seed_item_pending_detail": 2}},
        ]
    )

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", lambda *_args, **_kwargs: next(run_results))
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    seed_collector.run_seed_collector_loop(
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
            loop_interval_seconds=7,
            max_runs=2,
            pages_per_run=2,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
        progress_emit_func=events.append,
    )

    assert sleep_calls == [7]
    assert [event["event"] for event in events] == [
        "seed_collector_run",
        "seed_collector_sleep",
        "seed_collector_run",
    ]
    assert events[0]["run"] == 1
    assert events[0]["pages_attempted"] == 1
    assert events[0]["last_decision"] == "seed_scan_queue_empty"
    assert events[0]["last_item_count"] is None
    assert events[1] == {
        "event": "seed_collector_sleep",
        "run": 1,
        "sleep_seconds": 7,
        "counts": events[0]["counts"],
    }


def test_run_seed_collector_loop_retries_after_runtime_context_refresh_failure(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    contexts: list[str] = []

    def _runtime_context_factory() -> str:
        if not contexts:
            contexts.append("failed")
            raise RuntimeError("cdp unavailable")
        contexts.append("ok")
        return "http-ok"

    def _run_once(_config, *, repository, http_session, browserless_seed_probe):
        return {"decision": "seed_scan_queue_empty", "counts": repository.seed_queue_counts()}

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", _run_once)
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
            loop_interval_seconds=5,
            max_runs=2,
            pages_per_run=2,
        ),
        repository=repo,
        browserless_seed_probe=_FakeProbe,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=events.append,
    )

    assert contexts == ["failed", "ok"]
    assert sleep_calls == [5]
    assert [event["event"] for event in events] == [
        "seed_collector_runtime_refresh_failed",
        "seed_collector_sleep",
        "seed_collector_run",
    ]
    assert events[0]["run"] == 1
    assert events[0]["decision"] == "seed_runtime_refresh_failed"
    assert "cdp unavailable" in events[0]["error"]
    assert summary["runs"] == 2
    assert summary["last_decision"] == "seed_scan_queue_empty"
