from tools.test.seed_queue_repository_test_context import *  # noqa: F401,F403


def test_analysis_claim_skips_rows_whose_raw_detail_artifact_is_missing(tmp_path: Path) -> None:
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
    assert repo.claim_seed_detail_item("detail-worker", lease_seconds=30) is not None
    assert repo.claim_seed_detail_item("detail-worker", lease_seconds=30) is not None

    existing_detail = tmp_path / "detail-1002.html"
    existing_detail.write_text("<html>ok</html>", encoding="utf-8")
    existing_selected = tmp_path / "selected-1002.json"
    existing_selected.write_text("{}", encoding="utf-8")

    repo.mark_seed_raw_detail_captured(
        "1001",
        detail_html_path=str(tmp_path / "missing-detail-1001.html"),
        selected_json_path=str(tmp_path / "missing-selected-1001.json"),
    )
    repo.mark_seed_raw_detail_captured(
        "1002",
        detail_html_path=str(existing_detail),
        selected_json_path=str(existing_selected),
    )

    analysis_claim = repo.claim_seed_raw_detail_item("analysis-worker", lease_seconds=30)

    assert analysis_claim is not None
    assert analysis_claim["id"] == "1002"
    with repo.session_factory() as session:
        missing_row = session.get(FapaiSeedItem, "1001")
        claimed_row = session.get(FapaiSeedItem, "1002")
        assert missing_row is not None
        assert missing_row.status == "analysis_blocked"
        assert "raw detail artifact missing" in (missing_row.detail_last_error or "")
        assert claimed_row is not None
        assert claimed_row.status == "analysis_in_progress"

def test_detail_queue_prioritizes_pending_items_before_retrying_failed_or_same_worker_in_progress(
    tmp_path: Path,
) -> None:
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
            {"id": "1003", "title": "南沙 C", "url": "https://sf-item.taobao.com/sf_item/1003.htm"},
        ],
    )

    with repo.session_factory() as session:
        old_failed = session.get(FapaiSeedItem, "1001")
        same_worker_in_progress = session.get(FapaiSeedItem, "1002")
        pending = session.get(FapaiSeedItem, "1003")
        assert old_failed is not None
        assert same_worker_in_progress is not None
        assert pending is not None
        old_failed.status = "detail_failed"
        old_failed.detail_last_error = "temporary backend failure"
        same_worker_in_progress.status = "in_progress"
        same_worker_in_progress.detail_leased_by = "detail-worker"
        same_worker_in_progress.detail_lease_until = old_failed.first_seen_at.replace(year=2099)
        old_failed.first_seen_at = old_failed.first_seen_at.replace(year=2000)
        same_worker_in_progress.first_seen_at = same_worker_in_progress.first_seen_at.replace(year=2001)
        pending.first_seen_at = pending.first_seen_at.replace(year=2002)
        session.add_all([old_failed, same_worker_in_progress, pending])
        session.commit()

    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)

    assert claimed is not None
    assert claimed["id"] == "1003"

def test_detail_queue_reclaims_expired_in_progress_before_pending_backlog(
    tmp_path: Path,
) -> None:
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
            {"id": "1001", "title": "expired lease", "url": "https://sf-item.taobao.com/sf_item/1001.htm"},
            {"id": "1002", "title": "pending backlog", "url": "https://sf-item.taobao.com/sf_item/1002.htm"},
        ],
    )

    with repo.session_factory() as session:
        expired = session.get(FapaiSeedItem, "1001")
        pending = session.get(FapaiSeedItem, "1002")
        assert expired is not None
        assert pending is not None
        expired.status = "in_progress"
        expired.detail_leased_by = "dead-worker"
        expired.detail_lease_until = datetime.now() - timedelta(hours=1)
        expired.first_seen_at = expired.first_seen_at.replace(year=2099)
        pending.status = "pending_detail"
        pending.first_seen_at = pending.first_seen_at.replace(year=2000)
        session.add_all([expired, pending])
        session.commit()

    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)

    assert claimed is not None
    assert claimed["id"] == "1001"
    with repo.session_factory() as session:
        reclaimed = session.get(FapaiSeedItem, "1001")
        assert reclaimed is not None
        assert reclaimed.status == "in_progress"
        assert reclaimed.detail_leased_by == "detail-worker"

def test_detail_queue_blocks_items_that_reach_retry_limit_before_claiming_next(
    tmp_path: Path,
) -> None:
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
            {"id": "1003", "title": "南沙 C", "url": "https://sf-item.taobao.com/sf_item/1003.htm"},
        ],
    )

    with repo.session_factory() as session:
        failed = session.get(FapaiSeedItem, "1001")
        expired = session.get(FapaiSeedItem, "1002")
        claimable = session.get(FapaiSeedItem, "1003")
        assert failed is not None
        assert expired is not None
        assert claimable is not None
        failed.status = "detail_failed"
        failed.detail_attempt_count = 3
        failed.detail_last_error = "old retryable failure"
        failed.first_seen_at = failed.first_seen_at.replace(year=2000)
        expired.status = "in_progress"
        expired.detail_attempt_count = 3
        expired.detail_leased_by = "detail-worker"
        expired.detail_lease_until = expired.first_seen_at.replace(year=2001)
        expired.detail_last_error = "old leased failure"
        expired.first_seen_at = expired.first_seen_at.replace(year=2001)
        claimable.status = "detail_failed"
        claimable.detail_attempt_count = 2
        claimable.detail_last_error = "still retryable"
        claimable.first_seen_at = claimable.first_seen_at.replace(year=2002)
        session.add_all([failed, expired, claimable])
        session.commit()

    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30, max_item_attempts=3)

    assert claimed is not None
    assert claimed["id"] == "1003"
    with repo.session_factory() as session:
        blocked_failed = session.get(FapaiSeedItem, "1001")
        blocked_expired = session.get(FapaiSeedItem, "1002")
        claimed_row = session.get(FapaiSeedItem, "1003")
        assert blocked_failed is not None and blocked_failed.status == "detail_blocked"
        assert blocked_expired is not None and blocked_expired.status == "detail_blocked"
        assert blocked_failed.detail_leased_by is None
        assert blocked_expired.detail_leased_by is None
        assert blocked_failed.detail_lease_until is None
        assert blocked_expired.detail_lease_until is None
        assert "retry limit reached" in (blocked_failed.detail_last_error or "")
        assert "retry limit reached" in (blocked_expired.detail_last_error or "")
        assert claimed_row is not None and claimed_row.status == "in_progress"
        assert claimed_row.detail_attempt_count == 3

def test_detail_queue_prioritizes_stale_failed_items_before_large_pending_backlog(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None

    items = [
        {
            "id": f"{1000 + index}",
            "title": f"南沙 {index}",
            "url": f"https://sf-item.taobao.com/sf_item/{1000 + index}.htm",
        }
        for index in range(20)
    ]
    repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=1,
        source_page_url=task["url"],
        items=items,
    )

    now = datetime.utcnow().replace(microsecond=0)
    with repo.session_factory() as session:
        stale_failed = session.get(FapaiSeedItem, "1019")
        assert stale_failed is not None
        stale_failed.status = "detail_failed"
        stale_failed.detail_attempt_count = 1
        stale_failed.detail_last_error = "old challenge failure"
        stale_failed.updated_at = now - timedelta(hours=2)
        session.add(stale_failed)
        session.commit()

    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)

    assert claimed is not None
    assert claimed["id"] == "1019"

def test_analysis_queue_prioritizes_stale_failed_items_before_large_raw_backlog(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None

    items = [
        {
            "id": f"{2000 + index}",
            "title": f"南沙分析 {index}",
            "url": f"https://sf-item.taobao.com/sf_item/{2000 + index}.htm",
        }
        for index in range(20)
    ]
    repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=1,
        source_page_url=task["url"],
        items=items,
    )

    for index in range(20):
        item_id = str(2000 + index)
        claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)
        assert claimed is not None
        detail_path = tmp_path / f"detail-{item_id}.html"
        selected_path = tmp_path / f"selected-{item_id}.json"
        detail_path.write_text(f"<html>{item_id}</html>", encoding="utf-8")
        selected_path.write_text("{}", encoding="utf-8")
        repo.mark_seed_raw_detail_captured(
            item_id,
            detail_html_path=str(detail_path),
            selected_json_path=str(selected_path),
        )

    now = datetime.utcnow().replace(microsecond=0)
    with repo.session_factory() as session:
        stale_failed = session.get(FapaiSeedItem, "2019")
        assert stale_failed is not None
        stale_failed.status = "analysis_failed"
        stale_failed.detail_attempt_count = 1
        stale_failed.detail_last_error = "old analysis failure"
        stale_failed.updated_at = now - timedelta(hours=2)
        session.add(stale_failed)
        session.commit()

    claimed = repo.claim_seed_raw_detail_item("analysis-worker", lease_seconds=30)

    assert claimed is not None
    assert claimed["id"] == "2019"

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

def test_release_seed_scan_worker_leases_resets_in_progress_rows_for_worker(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)

    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None

    released = repo.release_seed_scan_worker_leases("seed-worker")

    assert released["released"] == 1
    with repo.session_factory() as session:
        row = session.get(FapaiSeedScanProgress, task["progress_key"])
        assert row is not None
        assert row.status == "pending"
        assert row.leased_by is None
        assert row.lease_until is None

def test_seed_scan_page_claim_uses_utc_naive_clock_for_lease_timestamps(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    base_utc = datetime(2026, 7, 5, 10, 0, 0)

    class SkewedLocalDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return base_utc + timedelta(hours=8)

        @classmethod
        def utcnow(cls):
            return base_utc

    monkeypatch.setattr(repository_module, "datetime", SkewedLocalDateTime)

    claimed = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)

    assert claimed is not None
    with repo.session_factory() as session:
        row = session.get(FapaiSeedScanProgress, claimed["progress_key"])
        assert row is not None
        assert row.lease_until == base_utc + timedelta(seconds=30)

def test_seed_scan_page_reclaims_suspicious_future_lease_written_by_skewed_host(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.ensure_seed_scan_job(
        {
            "job_key": "440115-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "default", "sort_name": "默认排序", "st_param": "0", "sort_order": 0}],
        max_page=83,
    )

    with repo.session_factory.begin() as session:
        row = session.scalars(select(FapaiSeedScanProgress)).first()
        assert row is not None
        row.status = "in_progress"
        row.leased_by = "dead-worker"
        row.updated_at = datetime.now() - timedelta(hours=2)
        row.lease_until = row.updated_at + timedelta(hours=8, seconds=90)
        session.add(row)
        progress_key = row.progress_key

    claimed = repo.claim_seed_scan_page("seed-worker-2", lease_seconds=30)

    assert claimed is not None
    assert claimed["progress_key"] == progress_key
    assert claimed["page"] == 1
