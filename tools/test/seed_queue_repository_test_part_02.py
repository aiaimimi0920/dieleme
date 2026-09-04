from tools.test.seed_queue_repository_test_context import *  # noqa: F401,F403


def test_reset_seed_link_region_preserves_collected_items_and_reopens_scan_progress(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    _upsert_sample_seed(repo, item_id="1001")
    repo.mark_seed_raw_detail_captured("1001", detail_html_path=str(tmp_path / "detail.html"))
    with repo.session_factory.begin() as session:
        for progress in session.scalars(select(FapaiSeedScanProgress)).all():
            progress.status = "exhausted"
            progress.next_page = 83
            progress.last_success_page = 83
            progress.retry_count = 5
            progress.last_error = "old error"
            progress.leased_by = "worker"
            progress.lease_until = datetime.now() + timedelta(minutes=5)
            progress.completed_at = datetime.now()
            session.add(progress)
        job = session.get(FapaiSeedScanJob, "guangdong-guangzhou-nansha-50025969")
        assert job is not None
        job.status = "completed"
        job.completed_at = datetime.now()
        session.add(job)

    result = repo.reset_seed_link_region("440115")

    assert result["ok"] is True
    assert result["location_code"] == "440115"
    assert result["reset"]["jobs"] == 1
    assert result["reset"]["progress"] == 2
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(FapaiSeedItem)) == 1
        assert session.scalar(select(func.count()).select_from(FapaiSeedOccurrence)) == 1
        item = session.get(FapaiSeedItem, "1001")
        assert item is not None
        assert item.status == "raw_detail_captured"
        job = session.get(FapaiSeedScanJob, "guangdong-guangzhou-nansha-50025969")
        assert job is not None
        assert job.status == "pending"
        assert job.completed_at is None
        for progress in session.scalars(select(FapaiSeedScanProgress)).all():
            assert progress.status == "pending"
            assert progress.next_page == 1
            assert progress.last_success_page is None
            assert progress.completed_at is None
            assert progress.leased_by is None
            assert progress.lease_until is None
            assert progress.retry_count == 0
            assert progress.last_error is None

def test_ensure_seed_scan_job_keeps_completed_scan_state_when_refreshing_metadata(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    completed_at = datetime(2026, 1, 2, 3, 4, 5)
    with repo.session_factory.begin() as session:
        job = session.get(FapaiSeedScanJob, "guangdong-guangzhou-nansha-50025969")
        assert job is not None
        job.status = "completed"
        job.completed_at = completed_at
        session.add(job)
        for progress in session.scalars(select(FapaiSeedScanProgress)).all():
            progress.status = "exhausted"
            progress.completed_at = completed_at
            progress.next_page = 83
            session.add(progress)

    repo.ensure_seed_scan_job(
        {
            "job_key": "guangdong-guangzhou-nansha-50025969",
            "province": "广东",
            "city": "广州",
            "district": "南沙",
            "location_code": "440115",
            "category": "50025969",
            "metadata": {"location_source": "taobao_sf_location_overrides"},
        },
        sort_specs=[
            {"sort_key": "bid_desc", "sort_name": "出价次数由高到低", "st_param": "2"},
            {"sort_key": "end_time_soon", "sort_name": "结拍时间由近到远", "st_param": "1"},
        ],
        max_page=83,
    )

    with repo.session_factory() as session:
        job = session.get(FapaiSeedScanJob, "guangdong-guangzhou-nansha-50025969")
        assert job is not None
        assert job.province == "广东"
        assert job.city == "广州"
        assert job.district == "南沙"
        assert job.status == "completed"
        assert job.completed_at == completed_at
        assert job.metadata_json == {"location_source": "taobao_sf_location_overrides"}
        for progress in session.scalars(select(FapaiSeedScanProgress)).all():
            assert progress.status == "exhausted"
            assert progress.completed_at == completed_at

def test_archive_seed_scan_jobs_except_soft_archives_stale_queue_without_deleting_items(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    repo.ensure_seed_scan_job(
        {
            "job_key": "shanghai-admin-chongming-50025969",
            "province": "上海市",
            "city": "市辖区",
            "district": "崇明区",
            "location_code": "310151",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "default", "sort_name": "默认排序", "st_param": "0"}],
        max_page=83,
    )
    repo.upsert_seed_items(
        job_key="shanghai-admin-chongming-50025969",
        progress_key="shanghai-admin-chongming-50025969::default",
        sort_key="default",
        sort_name="默认排序",
        st_param="0",
        page=1,
        source_page_url="https://example.test/shanghai?page=1",
        source_final_url="https://example.test/shanghai?page=1",
        items=[{"id": "2001", "title": "上海崇明测试房产", "url": "https://sf-item.taobao.com/sf_item/2001.htm"}],
    )

    result = repo.archive_seed_scan_jobs_except(["guangdong-guangzhou-nansha-50025969"])

    assert result["active_job_count"] == 1
    assert result["archived_jobs"] == 1
    assert result["archived_progress"] == 1
    with repo.session_factory() as session:
        active_job = session.get(FapaiSeedScanJob, "guangdong-guangzhou-nansha-50025969")
        archived_job = session.get(FapaiSeedScanJob, "shanghai-admin-chongming-50025969")
        assert active_job is not None and active_job.status == "pending"
        assert archived_job is not None and archived_job.status == "archived"
        archived_progress = session.get(FapaiSeedScanProgress, "shanghai-admin-chongming-50025969:default")
        assert archived_progress is not None and archived_progress.status == "archived"
        assert session.scalar(select(func.count()).select_from(FapaiSeedOccurrence)) == 1
        assert session.scalar(select(func.count()).select_from(FapaiSeedItem)) == 1

    link_regions = repo.collection_observer_regions(stage="links")
    assert [region["location_code"] for region in link_regions["regions"]] == ["440115"]

    item_payload = repo.collection_observer_item_detail("2001")
    assert item_payload["found"] is True
    assert item_payload["item"]["latest_occurrence"]["job_key"] == "shanghai-admin-chongming-50025969"

def test_ensure_seed_scan_job_recovers_when_another_worker_inserts_same_job(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.initialize()
    job = {
        "job_key": "guangdong-guangzhou-nansha-50025969",
        "province": "广东省",
        "city": "广州市",
        "district": "南沙区",
        "location_code": "440115",
        "category": "50025969",
    }
    inserted_by_race = False

    def insert_job_from_parallel_worker(session, _flush_context, _instances) -> None:
        nonlocal inserted_by_race
        if inserted_by_race:
            return
        if not any(isinstance(row, FapaiSeedScanJob) and row.job_key == job["job_key"] for row in session.new):
            return
        inserted_by_race = True
        with repo.engine.begin() as connection:
            connection.execute(
                insert(FapaiSeedScanJob).values(
                    job_key=job["job_key"],
                    province="广东省",
                    city="广州市",
                    district="南沙区",
                    location_code="440115",
                    category="50025969",
                    status="pending",
                    source_url_template="https://example.invalid/preexisting",
                    metadata_json={},
                )
            )

    event.listen(repo.session_factory.class_, "before_flush", insert_job_from_parallel_worker)
    try:
        result = repo.ensure_seed_scan_job(
            job,
            sort_specs=[
                {"sort_key": "bid_desc", "sort_name": "出价次数由高到低", "st_param": "2"},
                {"sort_key": "end_time_soon", "sort_name": "结拍时间由近到远", "st_param": "1"},
            ],
            max_page=83,
        )
    finally:
        event.remove(repo.session_factory.class_, "before_flush", insert_job_from_parallel_worker)

    assert inserted_by_race is True
    assert result["job_key"] == job["job_key"]
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(FapaiSeedScanJob)) == 1
        assert session.scalar(select(func.count()).select_from(FapaiSeedScanProgress)) == 2

def test_ensure_seed_scan_job_recovers_when_another_worker_inserts_same_progress(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.initialize()
    job = {
        "job_key": "guangdong-guangzhou-nansha-50025969",
        "province": "广东省",
        "city": "广州市",
        "district": "南沙区",
        "location_code": "440115",
        "category": "50025969",
    }
    inserted_by_race = False

    def insert_progress_from_parallel_worker(session, _flush_context, _instances) -> None:
        nonlocal inserted_by_race
        if inserted_by_race:
            return
        pending_progress = [row for row in session.new if isinstance(row, FapaiSeedScanProgress)]
        if not pending_progress:
            return
        progress = pending_progress[0]
        inserted_by_race = True
        with repo.engine.begin() as connection:
            connection.execute(
                insert(FapaiSeedScanProgress).values(
                    progress_key=progress.progress_key,
                    job_key=progress.job_key,
                    sort_key=progress.sort_key,
                    sort_name="出价次数由高到低",
                    st_param=progress.st_param,
                    sort_order=0,
                    next_page=1,
                    max_page=83,
                    status="pending",
                    retry_count=0,
                )
            )

    event.listen(repo.session_factory.class_, "before_flush", insert_progress_from_parallel_worker)
    try:
        result = repo.ensure_seed_scan_job(
            job,
            sort_specs=[{"sort_key": "bid_desc", "sort_name": "出价次数由高到低", "st_param": "2"}],
            max_page=83,
        )
    finally:
        event.remove(repo.session_factory.class_, "before_flush", insert_progress_from_parallel_worker)

    assert inserted_by_race is True
    assert result["job_key"] == job["job_key"]
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(FapaiSeedScanJob)) == 1
        assert session.scalar(select(func.count()).select_from(FapaiSeedScanProgress)) == 1

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

def test_seed_scan_progress_completes_region_categories_sorts_and_pages_before_next_region(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    sort_specs = [
        {"sort_key": "default", "sort_name": "默认排序", "st_param": "0", "sort_order": 0},
        {"sort_key": "price_desc", "sort_name": "价格由高到低", "st_param": "3", "sort_order": 1},
    ]
    for job in [
        {
            "job_key": "440115-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        {
            "job_key": "440115-200782003",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "200782003",
        },
        {
            "job_key": "440106-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "天河区",
            "location_code": "440106",
            "category": "50025969",
        },
    ]:
        repo.ensure_seed_scan_job(job, sort_specs=sort_specs, max_page=83)

    expected = [
        ("440115-50025969", "default", 1, True),
        ("440115-50025969", "default", 2, False),
        ("440115-50025969", "price_desc", 1, False),
        ("440115-200782003", "default", 1, False),
        ("440115-200782003", "price_desc", 1, False),
        ("440106-50025969", "default", 1, False),
        ("440106-50025969", "price_desc", 1, False),
    ]

    seen: list[tuple[str, str, int]] = []
    for job_key, sort_key, page, has_next in expected:
        task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
        assert task is not None
        seen.append((task["job_key"], task["sort_key"], task["page"]))
        repo.complete_seed_scan_page(
            progress_key=task["progress_key"],
            page=task["page"],
            item_count=2 if has_next else 0,
            has_next=has_next,
            source_url=task["url"],
        )

    assert seen == [(job_key, sort_key, page) for job_key, sort_key, page, _has_next in expected]
    assert repo.claim_seed_scan_page("seed-worker", lease_seconds=30) is None

def test_seed_scan_progress_sequential_mode_skips_leased_scope_and_claims_next_region(tmp_path: Path) -> None:
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

    second = repo.claim_seed_scan_page("seed-worker-2", lease_seconds=30)

    assert second is not None
    assert second["job_key"] == "440106-50025969"
