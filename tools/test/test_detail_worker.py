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
