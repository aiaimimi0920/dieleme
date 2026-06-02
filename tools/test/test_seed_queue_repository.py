from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from src.storage.models import FapaiSeedItem, FapaiSeedOccurrence, FapaiSeedScanProgress
from src.storage.repository import DatabaseSettings, PropertyRepository


def _make_repo(tmp_path: Path) -> PropertyRepository:
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'seed-queue.sqlite3').resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def _ensure_nansha_job(repo: PropertyRepository) -> None:
    repo.ensure_seed_scan_job(
        {
            "job_key": "guangdong-guangzhou-nansha-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        sort_specs=[
            {"sort_key": "bid_desc", "sort_name": "出价次数由高到低", "st_param": "2"},
            {"sort_key": "end_time_soon", "sort_name": "结拍时间由近到远", "st_param": "1"},
        ],
        max_page=83,
    )


def test_seed_scan_progress_runs_one_sort_to_exhaustion_before_next_sort(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)

    first = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert first is not None
    assert first["job_key"] == "guangdong-guangzhou-nansha-50025969"
    assert first["sort_key"] == "bid_desc"
    assert first["sort_name"] == "出价次数由高到低"
    assert first["st_param"] == "2"
    assert first["page"] == 1
    assert "location_code=440115" in first["url"]
    assert "st_param=2" in first["url"]
    assert "page=1" in first["url"]

    repo.complete_seed_scan_page(
        progress_key=first["progress_key"],
        page=1,
        item_count=2,
        has_next=True,
        source_url=first["url"],
    )

    second = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert second is not None
    assert second["sort_key"] == "bid_desc"
    assert second["page"] == 2

    repo.complete_seed_scan_page(
        progress_key=second["progress_key"],
        page=2,
        item_count=0,
        has_next=False,
        source_url=second["url"],
    )

    third = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert third is not None
    assert third["sort_key"] == "end_time_soon"
    assert third["sort_name"] == "结拍时间由近到远"
    assert third["page"] == 1

    repo.complete_seed_scan_page(
        progress_key=third["progress_key"],
        page=1,
        item_count=0,
        has_next=False,
        source_url=third["url"],
    )

    assert repo.claim_seed_scan_page("seed-worker", lease_seconds=30) is None
    counts = repo.seed_queue_counts()
    assert counts["seed_scan_job_completed"] == 1
    assert counts["seed_scan_progress_exhausted"] == 2


def test_upsert_seed_items_deduplicates_items_and_keeps_occurrences(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None

    first = repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=1,
        source_page_url=task["url"],
        items=[
            {"id": "1001", "title": "南沙 A", "url": "https://sf-item.taobao.com/sf_item/1001.htm"},
            {"id": "1002", "title": "南沙 B", "url": "https://sf-item.taobao.com/sf_item/1002.htm"},
        ],
    )
    duplicate = repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=1,
        source_page_url=task["url"],
        items=[
            {"id": "1001", "title": "南沙 A duplicate", "url": "https://sf-item.taobao.com/sf_item/1001.htm"},
        ],
    )

    assert first == {"seen": 2, "new_items": 2, "existing_items": 0, "new_occurrences": 2}
    assert duplicate == {"seen": 1, "new_items": 0, "existing_items": 1, "new_occurrences": 0}

    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(FapaiSeedItem)) == 2
        assert session.scalar(select(func.count()).select_from(FapaiSeedOccurrence)) == 2
        row = session.get(FapaiSeedItem, "1001")
        assert row is not None
        assert row.status == "pending_detail"
        assert row.first_seen_job_key == "guangdong-guangzhou-nansha-50025969"


def test_detail_queue_claims_once_and_retries_failed_items(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
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
            {"id": "1001", "title": "南沙 A", "url": "https://sf-item.taobao.com/sf_item/1001.htm"},
            {"id": "1002", "title": "南沙 B", "url": "https://sf-item.taobao.com/sf_item/1002.htm"},
        ],
    )

    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)
    assert claimed is not None
    assert claimed["id"] == "1001"
    assert claimed["url"] == "https://sf-item.taobao.com/sf_item/1001.htm"

    repo.mark_seed_detail_completed(
        "1001",
        final_json_path="/data/output/detail_worker/1001/final.json",
        selected_json_path="/data/output/detail_worker/1001/selected.json",
    )
    assert repo.claim_seed_detail_item("detail-worker", lease_seconds=30)["id"] == "1002"
    repo.mark_seed_detail_failed("1002", "temporary failure", retryable=True)

    retry = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)
    assert retry is not None
    assert retry["id"] == "1002"

    with repo.session_factory() as session:
        completed = session.get(FapaiSeedItem, "1001")
        failed = session.get(FapaiSeedItem, "1002")
        assert completed is not None and completed.status == "detail_completed"
        assert failed is not None and failed.status == "in_progress"
        assert failed.detail_attempt_count == 2


def test_seed_scan_page_failure_releases_progress_for_retry(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None

    repo.fail_seed_scan_page(task["progress_key"], "browser challenge", retryable=True)

    retry = repo.claim_seed_scan_page("seed-worker-2", lease_seconds=30)
    assert retry is not None
    assert retry["progress_key"] == task["progress_key"]
    assert retry["page"] == 1

    with repo.session_factory() as session:
        row = session.get(FapaiSeedScanProgress, task["progress_key"])
        assert row is not None
        assert row.leased_by == "seed-worker-2"
