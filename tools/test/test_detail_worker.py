from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.storage.repository import DatabaseSettings, PropertyRepository
from tools import detail_worker


def _make_repo(tmp_path: Path) -> PropertyRepository:
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'detail-worker.sqlite3').resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def _seed_one_item(repo: PropertyRepository) -> None:
    repo.ensure_seed_scan_job(
        {
            "job_key": "guangdong-guangzhou-nansha-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "bid_desc", "sort_name": "出价次数由高到低", "st_param": "2"}],
        max_page=83,
    )
    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None
    repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=1,
        source_page_url=task["url"],
        items=[
            {
                "id": "3001",
                "title": "南沙详情 A",
                "url": "https://sf-item.taobao.com/sf_item/3001.htm",
                "source_page_url": task["url"],
            }
        ],
    )


def _seed_items(repo: PropertyRepository, item_ids: list[str]) -> None:
    repo.ensure_seed_scan_job(
        {
            "job_key": "guangdong-guangzhou-nansha-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "bid_desc", "sort_name": "出价次数由高到低", "st_param": "2"}],
        max_page=83,
    )
    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None
    repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=1,
        source_page_url=task["url"],
        items=[
            {
                "id": item_id,
                "title": f"南沙详情 {item_id}",
                "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
                "source_page_url": task["url"],
            }
            for item_id in item_ids
        ],
    )


def test_run_detail_worker_once_claims_seed_and_marks_completed(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    processed: list[dict[str, Any]] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed.append(seed)
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        final = {
            "id": seed["id"],
            "title": seed["title"],
            "url": seed["url"],
            "source_url": seed["url"],
            "community_name": "南沙稳定片区",
            "community_stable_key": "collector::广州市::南沙区::南沙稳定片区",
            "city": "广州市",
            "district": "南沙区",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text(json.dumps({"item_id": seed["id"]}, ensure_ascii=False), encoding="utf-8")
        return {"item_id": seed["id"], "final_core": {"source_url": seed["url"], "title": seed["title"]}}

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_completed"
    assert summary["item_id"] == "3001"
    assert [row["id"] for row in processed] == ["3001"]
    assert repo.seed_queue_counts()["seed_item_detail_completed"] == 1
    assert repo.get_flat_item("3001")["community_stable_key"] == "collector::广州市::南沙区::南沙稳定片区"


def test_run_detail_worker_once_marks_retryable_failure(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    def _process_item(_http, seed, _browser_pages, *, config):
        raise RuntimeError("detail timeout")

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["item_id"] == "3001"
    assert "detail timeout" in summary["error"]
    retry = repo.claim_seed_detail_item("detail-retry", lease_seconds=30)
    assert retry is not None
    assert retry["id"] == "3001"


def test_run_detail_worker_batch_does_not_retry_same_failed_item_in_same_batch(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001", "3002"])
    processed: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed.append(str(seed["id"]))
        if seed["id"] == "3001":
            raise RuntimeError("llm backend 503")
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        final = {
            "id": seed["id"],
            "title": seed["title"],
            "url": seed["url"],
            "source_url": seed["url"],
            "community_name": "南沙稳定片区",
            "community_stable_key": f"collector::广州市::南沙区::{seed['id']}",
            "city": "广州市",
            "district": "南沙区",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text(json.dumps({"item_id": seed["id"]}, ensure_ascii=False), encoding="utf-8")
        return {"item_id": seed["id"], "final_core": {"source_url": seed["url"], "title": seed["title"]}}

    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=2,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert processed == ["3001", "3002"]
    assert summary["attempts"] == 2
    assert summary["completed"] == 1
    assert [result["item_id"] for result in summary["results"]] == ["3001", "3002"]


def test_run_detail_worker_once_exits_cleanly_when_queue_is_empty(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=lambda *_args, **_kwargs: {},
    )

    assert summary == {"decision": "detail_queue_empty"}


def test_run_detail_worker_loop_refreshes_runtime_context_each_batch(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    contexts: list[tuple[str, dict[str, tuple[str, str]]]] = []
    batches: list[tuple[str, dict[str, tuple[str, str]]]] = []

    def _runtime_context_factory():
        run = len(contexts) + 1
        context = (f"http-{run}", {"page": (f"title-{run}", f"url-{run}")})
        contexts.append(context)
        return context

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        batches.append((http_session, browser_pages))
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 0,
            "completed": 0,
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=1,
            max_runs=2,
        ),
        repository=repo,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=lambda _event: None,
    )

    assert summary["decision"] == "detail_worker_loop_finished"
    assert len(contexts) == 2
    assert batches == contexts


def test_run_detail_worker_loop_emits_compact_batch_and_sleep_events(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 2,
            "completed": 1,
            "target_success": 3,
            "max_attempts": 4,
            "results": [
                {"decision": "detail_item_completed", "item_id": "3001"},
            ],
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=3,
            max_attempts=4,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=7,
            max_runs=2,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        progress_emit_func=events.append,
    )

    assert sleep_calls == [7]
    assert [event["event"] for event in events] == [
        "detail_worker_batch",
        "detail_worker_sleep",
        "detail_worker_batch",
    ]
    assert events[0]["run"] == 1
    assert events[0]["decision"] == "detail_worker_batch_finished"
    assert events[0]["completed"] == 1
    assert events[0]["last_result_decision"] == "detail_item_completed"
    assert events[0]["last_item_id"] == "3001"
    assert events[1] == {
        "event": "detail_worker_sleep",
        "run": 1,
        "sleep_seconds": 7,
        "counts": events[0]["counts"],
    }


def test_run_detail_worker_loop_retries_after_runtime_context_refresh_failure(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    contexts: list[str] = []

    def _runtime_context_factory():
        if not contexts:
            contexts.append("failed")
            raise RuntimeError("cdp unavailable")
        contexts.append("ok")
        return "http-ok", {}

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 0,
            "completed": 0,
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    summary = detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=5,
            max_runs=2,
        ),
        repository=repo,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=events.append,
    )

    assert contexts == ["failed", "ok"]
    assert sleep_calls == [5]
    assert [event["event"] for event in events] == [
        "detail_worker_runtime_refresh_failed",
        "detail_worker_sleep",
        "detail_worker_batch",
    ]
    assert events[0]["run"] == 1
    assert events[0]["decision"] == "detail_runtime_refresh_failed"
    assert "cdp unavailable" in events[0]["error"]
    assert summary["runs"] == 2
    assert summary["last_decision"] == "detail_worker_batch_finished"
