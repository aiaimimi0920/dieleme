from tools.test.seed_queue_repository_test_context import *  # noqa: F401,F403


def test_mark_seed_detail_failed_can_restore_pending_detail_without_consuming_retry_budget(tmp_path: Path) -> None:
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
        ],
    )

    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)
    assert claimed is not None
    assert claimed["id"] == "1001"

    repo.mark_seed_detail_failed(
        "1001",
        "RuntimeError('HTTP detail request returned anti-bot challenge: https://sf-item.taobao.com/sf_item/1001.htm')",
        retryable=True,
        revert_attempt=True,
        restore_pending=True,
    )

    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "1001")
        assert row is not None
        assert row.status == "pending_detail"
        assert row.detail_attempt_count == 0
        assert row.detail_leased_by is None
        assert row.detail_lease_until is None

    retry = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)
    assert retry is not None
    assert retry["id"] == "1001"

def test_detail_queue_claim_query_limits_locked_row_batch(tmp_path: Path) -> None:
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

    statements: list[str] = []

    def _capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "FROM fapai_seed_item" in statement and "ORDER BY CASE" in statement:
            statements.append(statement)

    event.listen(repo.engine, "before_cursor_execute", _capture_sql)
    try:
        claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)
    finally:
        event.remove(repo.engine, "before_cursor_execute", _capture_sql)

    assert claimed is not None
    assert any("LIMIT" in statement.upper() for statement in statements)

def test_detail_queue_claim_scans_beyond_first_candidate_window_when_front_batch_hits_retry_limit(
    tmp_path: Path,
) -> None:
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
        for index in range(17)
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

    with repo.session_factory() as session:
        for index in range(16):
            row = session.get(FapaiSeedItem, str(1000 + index))
            assert row is not None
            row.status = "pending_detail"
            row.detail_attempt_count = 3
            row.detail_last_error = "retry limit reached earlier"
            row.first_seen_at = row.first_seen_at.replace(year=2000, month=1, day=1) + timedelta(seconds=index)
            session.add(row)
        fallback = session.get(FapaiSeedItem, "1016")
        assert fallback is not None
        fallback.status = "pending_detail"
        fallback.detail_attempt_count = 2
        fallback.first_seen_at = fallback.first_seen_at.replace(year=2001, month=1, day=1)
        session.add(fallback)
        session.commit()

    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30, max_item_attempts=3)

    assert claimed is not None
    assert claimed["id"] == "1016"

def test_detail_queue_skips_recent_failed_items_until_cooldown_expires(tmp_path: Path) -> None:
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
            {"id": "1001", "title": "南沙 recent failed", "url": "https://sf-item.taobao.com/sf_item/1001.htm"},
            {"id": "1002", "title": "南沙 old failed", "url": "https://sf-item.taobao.com/sf_item/1002.htm"},
        ],
    )

    now = datetime.utcnow().replace(microsecond=0)
    with repo.session_factory() as session:
        recent_failed = session.get(FapaiSeedItem, "1001")
        old_failed = session.get(FapaiSeedItem, "1002")
        assert recent_failed is not None
        assert old_failed is not None
        recent_failed.status = "detail_failed"
        recent_failed.detail_attempt_count = 1
        recent_failed.detail_last_error = "recent challenge failure"
        recent_failed.updated_at = now
        recent_failed.first_seen_at = now.replace(year=2000)
        old_failed.status = "detail_failed"
        old_failed.detail_attempt_count = 1
        old_failed.detail_last_error = "old challenge failure"
        old_failed.updated_at = now - timedelta(hours=2)
        old_failed.first_seen_at = now.replace(year=2001)
        session.add_all([recent_failed, old_failed])
        session.commit()

    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30, failure_cooldown_seconds=1800)

    assert claimed is not None
    assert claimed["id"] == "1002"
    assert repo.claim_seed_detail_item(
        "detail-worker",
        lease_seconds=30,
        exclude_item_ids={"1002"},
        failure_cooldown_seconds=1800,
    ) is None
    with repo.session_factory() as session:
        recent_failed = session.get(FapaiSeedItem, "1001")
        assert recent_failed is not None
        assert recent_failed.status == "detail_failed"
        assert recent_failed.detail_attempt_count == 1

def test_raw_detail_captured_items_are_counted_and_not_reclaimed(tmp_path: Path) -> None:
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
        items=[{"id": "1001", "title": "南沙 A", "url": "https://sf-item.taobao.com/sf_item/1001.htm"}],
    )
    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)
    assert claimed is not None

    repo.mark_seed_raw_detail_captured(
        "1001",
        detail_html_path="/data/output/detail_worker/1001/detail.html",
        description_json_path="/data/output/detail_worker/1001/description-data.json",
        selected_json_path="/data/output/detail_worker/1001/selected.json",
    )

    counts = repo.seed_queue_counts()
    assert counts["seed_item_raw_detail_captured"] == 1
    assert counts["seed_item_detail_completed"] == 0
    assert repo.claim_seed_detail_item("detail-worker", lease_seconds=30) is None
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "1001")
        assert row is not None
        assert row.status == "raw_detail_captured"
        assert row.detail_leased_by is None
        assert row.detail_lease_until is None
        assert row.final_json_path is None
        assert row.selected_json_path == "/data/output/detail_worker/1001/selected.json"

def test_raw_detail_items_can_be_claimed_for_analysis_without_raw_reclaim(tmp_path: Path) -> None:
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
        items=[{"id": "1001", "title": "南沙 A", "url": "https://sf-item.taobao.com/sf_item/1001.htm"}],
    )
    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)
    assert claimed is not None
    detail_html = tmp_path / "detail-1001.html"
    description_json = tmp_path / "description-1001.json"
    selected_json = tmp_path / "selected-1001.json"
    detail_html.write_text("<html><body>南沙 A</body></html>", encoding="utf-8")
    description_json.write_text("{}", encoding="utf-8")
    selected_json.write_text("{}", encoding="utf-8")
    repo.mark_seed_raw_detail_captured(
        "1001",
        detail_html_path=str(detail_html),
        description_json_path=str(description_json),
        selected_json_path=str(selected_json),
    )

    analysis_claim = repo.claim_seed_raw_detail_item("analysis-worker", lease_seconds=30)

    assert analysis_claim is not None
    assert analysis_claim["id"] == "1001"
    assert analysis_claim["_raw_detail_artifacts"]["detail_html_path"] == str(detail_html)
    assert repo.claim_seed_detail_item("detail-worker", lease_seconds=30) is None
    counts = repo.seed_queue_counts()
    assert counts["seed_item_raw_detail_captured"] == 0
    assert counts["seed_item_analysis_in_progress"] == 1
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "1001")
        assert row is not None
        assert row.status == "analysis_in_progress"
        assert row.detail_leased_by == "analysis-worker"

def test_analysis_claim_maps_linux_data_artifact_paths_from_shared_host_root(tmp_path: Path, monkeypatch) -> None:
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
        items=[{"id": "1001", "title": "南沙 A", "url": "https://sf-item.taobao.com/sf_item/1001.htm"}],
    )
    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)
    assert claimed is not None

    shared_root = tmp_path / "shared-root"
    artifact_dir = shared_root / "output" / "1001"
    artifact_dir.mkdir(parents=True)
    detail_html = artifact_dir / "detail.html"
    selected_json = artifact_dir / "selected.json"
    detail_html.write_text("<html><body>南沙 A</body></html>", encoding="utf-8")
    selected_json.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("FAPAI_SHARED_DATA_ROOT_HOST", str(shared_root))

    repo.mark_seed_raw_detail_captured(
        "1001",
        detail_html_path="/data/output/1001/detail.html",
        selected_json_path="/data/output/1001/selected.json",
    )

    analysis_claim = repo.claim_seed_raw_detail_item("analysis-worker", lease_seconds=30)

    assert analysis_claim is not None
    assert analysis_claim["id"] == "1001"
    assert analysis_claim["_raw_detail_artifacts"]["detail_html_path"] == str(detail_html)
    assert analysis_claim["_raw_detail_artifacts"]["selected_json_path"] == str(selected_json)

def test_analysis_queue_claim_query_limits_locked_row_batch(tmp_path: Path) -> None:
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
    repo.mark_seed_raw_detail_captured("1001", detail_html_path=str(tmp_path / "detail-1001.html"))
    repo.mark_seed_raw_detail_captured("1002", detail_html_path=str(tmp_path / "detail-1002.html"))
    (tmp_path / "detail-1001.html").write_text("<html>A</html>", encoding="utf-8")
    (tmp_path / "detail-1002.html").write_text("<html>B</html>", encoding="utf-8")

    statements: list[str] = []

    def _capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "FROM fapai_seed_item" in statement and "ORDER BY CASE" in statement:
            statements.append(statement)

    event.listen(repo.engine, "before_cursor_execute", _capture_sql)
    try:
        claimed = repo.claim_seed_raw_detail_item("analysis-worker", lease_seconds=30)
    finally:
        event.remove(repo.engine, "before_cursor_execute", _capture_sql)

    assert claimed is not None
    assert any("LIMIT" in statement.upper() for statement in statements)

def test_analysis_queue_claim_scans_beyond_first_candidate_window_when_front_batch_artifacts_are_missing(
    tmp_path: Path,
) -> None:
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
        for index in range(17)
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

    for index in range(16):
        repo.mark_seed_raw_detail_captured(
            str(2000 + index),
            detail_html_path=str(tmp_path / f"missing-{2000 + index}.html"),
        )
    valid_detail = tmp_path / "detail-2016.html"
    valid_detail.write_text("<html>2016</html>", encoding="utf-8")
    repo.mark_seed_raw_detail_captured("2016", detail_html_path=str(valid_detail))

    claimed = repo.claim_seed_raw_detail_item("analysis-worker", lease_seconds=30)

    assert claimed is not None
    assert claimed["id"] == "2016"
    with repo.session_factory() as session:
        blocked = session.get(FapaiSeedItem, "2000")
        assert blocked is not None
        assert blocked.status == "analysis_blocked"
