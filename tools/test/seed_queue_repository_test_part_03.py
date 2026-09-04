from tools.test.seed_queue_repository_test_context import *  # noqa: F401,F403


def test_seed_scan_progress_sequential_mode_skips_cooling_scope_and_claims_next_region(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    sort_specs = [{"sort_key": "default", "sort_name": "默认排序", "st_param": "0", "sort_order": 0}]
    repo.ensure_seed_scan_job(
        {
            "job_key": "440115-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        sort_specs=sort_specs,
        max_page=83,
    )
    repo.ensure_seed_scan_job(
        {
            "job_key": "440106-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "天河区",
            "location_code": "440106",
            "category": "50025969",
        },
        sort_specs=sort_specs,
        max_page=83,
    )

    first = repo.claim_seed_scan_page("seed-worker-1", lease_seconds=30)
    assert first is not None
    assert first["job_key"] == "440115-50025969"
    repo.fail_seed_scan_page(first["progress_key"], "list_challenge_page", retryable=True)

    claimed = repo.claim_seed_scan_page(
        "seed-worker-2",
        lease_seconds=30,
        failure_cooldown_threshold=1,
        failure_cooldown_seconds=300,
    )

    assert claimed is not None
    assert claimed["job_key"] == "440106-50025969"

def test_seed_scan_progress_can_claim_parallel_sorts_for_fast_seed_pool(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)

    first = repo.claim_seed_scan_page("seed-worker-1", lease_seconds=30, parallel_sorts=True)
    second = repo.claim_seed_scan_page("seed-worker-2", lease_seconds=30, parallel_sorts=True)

    assert first is not None
    assert second is not None
    assert first["sort_key"] == "bid_desc"
    assert second["sort_key"] == "end_time_soon"
    assert first["page"] == 1
    assert second["page"] == 1

def test_seed_scan_progress_parallel_mode_keeps_current_region_scope_before_next_region(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    sort_specs = [
        {"sort_key": "default", "sort_name": "默认排序", "st_param": "0", "sort_order": 0},
        {"sort_key": "price_desc", "sort_name": "价格由高到低", "st_param": "3", "sort_order": 1},
    ]
    repo.ensure_seed_scan_job(
        {
            "job_key": "440115-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        sort_specs=sort_specs,
        max_page=83,
    )
    repo.ensure_seed_scan_job(
        {
            "job_key": "440106-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "天河区",
            "location_code": "440106",
            "category": "50025969",
        },
        sort_specs=sort_specs,
        max_page=83,
    )

    first = repo.claim_seed_scan_page("seed-worker-1", lease_seconds=30, parallel_sorts=True)
    second = repo.claim_seed_scan_page("seed-worker-2", lease_seconds=30, parallel_sorts=True)

    assert first is not None
    assert second is not None
    assert first["job_key"] == "440115-50025969"
    assert second["job_key"] == "440115-50025969"
    assert {first["sort_key"], second["sort_key"]} == {"default", "price_desc"}

def test_seed_scan_progress_skips_recent_retry_failures_during_cooldown(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)

    failed = repo.claim_seed_scan_page("seed-worker-1", lease_seconds=30, parallel_sorts=True)
    assert failed is not None
    assert failed["sort_key"] == "bid_desc"
    repo.fail_seed_scan_page(failed["progress_key"], "list_challenge_page", retryable=True)

    claimed = repo.claim_seed_scan_page(
        "seed-worker-2",
        lease_seconds=30,
        parallel_sorts=True,
        failure_cooldown_threshold=1,
        failure_cooldown_seconds=300,
    )

    assert claimed is not None
    assert claimed["progress_key"] != failed["progress_key"]
    assert claimed["sort_key"] == "end_time_soon"
    with repo.session_factory() as session:
        failed_row = session.get(FapaiSeedScanProgress, failed["progress_key"])
        assert failed_row is not None
        assert failed_row.status == "pending"
        assert failed_row.leased_by is None

def test_seed_scan_progress_success_resets_retry_state(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)

    first = repo.claim_seed_scan_page("seed-worker-1", lease_seconds=30)
    assert first is not None
    repo.fail_seed_scan_page(first["progress_key"], "list_challenge_page", retryable=True)

    retry = repo.claim_seed_scan_page("seed-worker-2", lease_seconds=30)
    assert retry is not None
    assert retry["progress_key"] == first["progress_key"]

    repo.complete_seed_scan_page(
        progress_key=retry["progress_key"],
        page=retry["page"],
        item_count=2,
        has_next=True,
        source_url=retry["url"],
    )

    with repo.session_factory() as session:
        row = session.get(FapaiSeedScanProgress, retry["progress_key"])
        assert row is not None
        assert row.retry_count == 0
        assert row.last_error is None

def test_seed_scan_progress_failure_restarts_retry_counter_after_clean_success_state(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)

    task = repo.claim_seed_scan_page("seed-worker-1", lease_seconds=30)
    assert task is not None

    with repo.session_factory.begin() as session:
        row = session.get(FapaiSeedScanProgress, task["progress_key"])
        assert row is not None
        row.retry_count = 99
        row.last_error = None
        row.status = "pending"
        row.leased_by = None
        row.lease_until = None
        session.add(row)

    repo.fail_seed_scan_page(task["progress_key"], "list_challenge_page", retryable=True)

    with repo.session_factory() as session:
        row = session.get(FapaiSeedScanProgress, task["progress_key"])
        assert row is not None
        assert row.retry_count == 1
        assert row.last_error == "list_challenge_page"
        assert row.status == "pending"

def test_seed_scan_progress_retries_failed_page_after_cooldown_expires(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)

    failed = repo.claim_seed_scan_page("seed-worker-1", lease_seconds=30, parallel_sorts=True)
    assert failed is not None
    repo.fail_seed_scan_page(failed["progress_key"], "list_challenge_page", retryable=True)
    with repo.session_factory.begin() as session:
        row = session.get(FapaiSeedScanProgress, failed["progress_key"])
        assert row is not None
        row.updated_at = datetime.utcnow() - timedelta(seconds=301)
        session.add(row)
        for progress in session.scalars(select(FapaiSeedScanProgress)).all():
            if progress.progress_key != failed["progress_key"]:
                progress.status = "exhausted"
                progress.completed_at = datetime.utcnow()
                session.add(progress)

    retry = repo.claim_seed_scan_page(
        "seed-worker-2",
        lease_seconds=30,
        parallel_sorts=True,
        failure_cooldown_threshold=1,
        failure_cooldown_seconds=300,
    )

    assert retry is not None
    assert retry["progress_key"] == failed["progress_key"]
    assert retry["page"] == 1

def test_seed_scan_progress_parallel_mode_prefers_fresh_rows_over_old_retry_rows(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.ensure_seed_scan_job(
        {
            "job_key": "440100-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "同区测试",
            "location_code": "440100",
            "category": "50025969",
        },
        sort_specs=[
            {"sort_key": "default", "sort_name": "默认排序", "st_param": "0", "sort_order": 0},
            {"sort_key": "price_desc", "sort_name": "价格由高到低", "st_param": "3", "sort_order": 1},
        ],
        max_page=83,
    )

    first = repo.claim_seed_scan_page("seed-worker-1", lease_seconds=30, parallel_sorts=True)
    assert first is not None
    assert first["job_key"] == "440100-50025969"
    repo.fail_seed_scan_page(first["progress_key"], "list_challenge_page", retryable=True)

    with repo.session_factory.begin() as session:
        old_retry = session.get(FapaiSeedScanProgress, first["progress_key"])
        assert old_retry is not None
        old_retry.updated_at = datetime.utcnow() - timedelta(seconds=601)
        session.add(old_retry)

    claimed = repo.claim_seed_scan_page(
        "seed-worker-2",
        lease_seconds=30,
        parallel_sorts=True,
        failure_cooldown_threshold=1,
        failure_cooldown_seconds=600,
    )

    assert claimed is not None
    assert claimed["job_key"] == "440100-50025969"
    assert claimed["progress_key"] != first["progress_key"]
    assert claimed["sort_key"] == "price_desc"

def test_seed_scan_progress_sequential_mode_waits_for_cooling_sort_before_later_sort(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)

    failed = repo.claim_seed_scan_page("seed-worker-1", lease_seconds=30)
    assert failed is not None
    assert failed["sort_key"] == "bid_desc"
    repo.fail_seed_scan_page(failed["progress_key"], "list_challenge_page", retryable=True)

    claimed = repo.claim_seed_scan_page(
        "seed-worker-2",
        lease_seconds=30,
        failure_cooldown_threshold=1,
        failure_cooldown_seconds=300,
    )

    assert claimed is None

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

def test_upsert_seed_items_recovers_when_parallel_worker_inserted_same_item(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None

    with repo.session_factory.begin() as session:
        session.add(
            FapaiSeedItem(
                item_id="1001",
                source_item_id="1001",
                source_url="https://sf-item.taobao.com/sf_item/1001.htm",
                title="parallel insert",
                status="pending_detail",
                first_seen_job_key=task["job_key"],
                first_seen_sort_key=task["sort_key"],
                first_seen_at=datetime.now(),
            )
        )

    original_get = SqlAlchemySession.get
    stale_read_once = True

    def fake_stale_get(self, entity, ident, *args, **kwargs):
        nonlocal stale_read_once
        if entity is FapaiSeedItem and str(ident) == "1001" and stale_read_once:
            stale_read_once = False
            return None
        return original_get(self, entity, ident, *args, **kwargs)

    monkeypatch.setattr(SqlAlchemySession, "get", fake_stale_get)

    result = repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=1,
        source_page_url=task["url"],
        items=[
            {
                "id": "1001",
                "title": "same item from another sort",
                "url": "https://sf-item.taobao.com/sf_item/1001.htm",
            }
        ],
    )

    assert result == {"seen": 1, "new_items": 0, "existing_items": 1, "new_occurrences": 1}
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(FapaiSeedItem)) == 1
        assert session.scalar(select(func.count()).select_from(FapaiSeedOccurrence)) == 1

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
