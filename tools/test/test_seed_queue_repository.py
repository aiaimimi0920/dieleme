from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import event, func, insert, select
from sqlalchemy.orm import Session as SqlAlchemySession

import src.storage.repository as repository_module
from src.storage.models import FapaiSeedItem, FapaiSeedOccurrence, FapaiSeedScanJob, FapaiSeedScanProgress
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


def _upsert_sample_seed(repo: PropertyRepository, item_id: str = "1001") -> None:
    repo.upsert_seed_items(
        job_key="guangdong-guangzhou-nansha-50025969",
        progress_key="guangdong-guangzhou-nansha-50025969::bid_desc",
        sort_key="bid_desc",
        sort_name="出价次数由高到低",
        st_param="2",
        page=1,
        source_page_url="https://sf-item.taobao.com/list/guangzhou?page=1",
        source_final_url="https://sf-item.taobao.com/list/guangzhou?page=1&st=2",
        items=[
            {
                "id": item_id,
                "title": "广州市南沙区测试房产",
                "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
                "extra": "kept-for-observer",
            }
        ],
    )


def test_seed_item_url_normalizes_duplicate_detail_path_slashes() -> None:
    assert PropertyRepository._seed_item_url(
        "570192626894",
        "https://sf-item.taobao.com//sf_item/570192626894.htm?track_id=test",
    ) == "https://sf-item.taobao.com/sf_item/570192626894.htm?track_id=test"


def test_detail_claim_overrides_legacy_duplicate_slash_payload_url(tmp_path: Path) -> None:
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
            {
                "id": "570192626894",
                "url": "https://sf-item.taobao.com//sf_item/570192626894.htm?track_id=test",
            }
        ],
    )

    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)

    assert claimed is not None
    assert claimed["url"] == "https://sf-item.taobao.com/sf_item/570192626894.htm?track_id=test"
    assert claimed["source_url"] == claimed["url"]


def test_collection_observer_lists_seed_links_with_totals(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)

    payload = repo.collection_observer_items(stage="links", limit=20, offset=0)

    assert payload["stage"] == "links"
    assert payload["total"] == 1
    assert payload["items"][0]["item_id"] == "1001"
    assert payload["items"][0]["title"] == "广州市南沙区测试房产"
    assert payload["items"][0]["source_url"] == "https://sf-item.taobao.com/sf_item/1001.htm"
    assert payload["items"][0]["latest_occurrence"]["sort_name"] == "出价次数由高到低"
    assert payload["items"][0]["latest_occurrence"]["source_page_url"].startswith("https://sf-item.taobao.com/list/")


def test_collection_observer_lists_detail_and_analysis_stages(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)
    detail_html = tmp_path / "detail.html"
    selected_json = tmp_path / "selected.json"
    final_json = tmp_path / "final.json"
    detail_html.write_text("<html><body>成交价 123 万元</body></html>", encoding="utf-8")
    selected_json.write_text('{"selected": true, "title": "广州市南沙区测试房产"}', encoding="utf-8")
    final_json.write_text('{"item_id": "1001", "transaction_price": 1230000}', encoding="utf-8")

    repo.mark_seed_raw_detail_captured(
        "1001",
        detail_html_path=str(detail_html),
        description_json_path=None,
        selected_json_path=str(selected_json),
    )

    details = repo.collection_observer_items(stage="details", limit=20, offset=0)
    assert details["total"] == 1
    assert details["items"][0]["status"] == "raw_detail_captured"
    assert details["items"][0]["artifacts"]["detail_html_path"] == str(detail_html)

    repo.mark_seed_detail_completed("1001", final_json_path=str(final_json), selected_json_path=str(selected_json))

    analysis = repo.collection_observer_items(stage="analysis", limit=20, offset=0)
    assert analysis["total"] == 1
    assert analysis["items"][0]["status"] == "detail_completed"
    assert analysis["items"][0]["final_json_path"] == str(final_json)


def test_collection_observer_item_detail_loads_collected_content(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)
    detail_html = tmp_path / "detail.html"
    selected_json = tmp_path / "selected.json"
    final_json = tmp_path / "final.json"
    detail_html.write_text("<html><body>标的物详情文本</body></html>", encoding="utf-8")
    selected_json.write_text('{"raw_text": "标的物详情文本"}', encoding="utf-8")
    final_json.write_text('{"item_id": "1001", "community_name": "测试小区"}', encoding="utf-8")
    repo.mark_seed_raw_detail_captured("1001", detail_html_path=str(detail_html), selected_json_path=str(selected_json))
    repo.mark_seed_detail_completed("1001", final_json_path=str(final_json), selected_json_path=str(selected_json))

    payload = repo.collection_observer_item_detail("1001", max_chars=200)

    assert payload["item"]["item_id"] == "1001"
    assert payload["artifacts"]["detail_html"]["exists"] is True
    assert "标的物详情文本" in payload["artifacts"]["detail_html"]["content"]
    assert payload["artifacts"]["selected_json"]["json"]["raw_text"] == "标的物详情文本"
    assert payload["artifacts"]["final_json"]["json"]["community_name"] == "测试小区"
    assert payload["occurrences"][0]["source_page_url"].startswith("https://sf-item.taobao.com/list/")


def test_collection_observer_item_detail_reads_linux_data_artifact_paths_from_shared_host_root(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)
    shared_root = tmp_path / "shared-root"
    artifact_dir = shared_root / "output" / "1001"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "detail.html").write_text("<html><body>共享详情文本</body></html>", encoding="utf-8")
    (artifact_dir / "selected.json").write_text('{"raw_text": "共享详情文本"}', encoding="utf-8")
    (artifact_dir / "final.json").write_text('{"item_id": "1001", "community_name": "共享小区"}', encoding="utf-8")
    monkeypatch.setenv("FAPAI_SHARED_DATA_ROOT_HOST", str(shared_root))

    repo.mark_seed_raw_detail_captured(
        "1001",
        detail_html_path="/data/output/1001/detail.html",
        selected_json_path="/data/output/1001/selected.json",
    )
    repo.mark_seed_detail_completed(
        "1001",
        final_json_path="/data/output/1001/final.json",
        selected_json_path="/data/output/1001/selected.json",
    )

    payload = repo.collection_observer_item_detail("1001", max_chars=200)

    assert payload["artifacts"]["detail_html"]["exists"] is True
    assert payload["artifacts"]["detail_html"]["resolved_path"] == str(artifact_dir / "detail.html")
    assert "共享详情文本" in payload["artifacts"]["detail_html"]["content"]
    assert payload["artifacts"]["selected_json"]["json"]["raw_text"] == "共享详情文本"
    assert payload["artifacts"]["final_json"]["json"]["community_name"] == "共享小区"


def test_collection_observer_item_detail_reads_unc_fpfdata_artifact_paths_from_shared_root(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)
    shared_root = tmp_path / "shared-root"
    artifact_dir = shared_root / "output" / "nodes" / "pc2-real" / "detail_analysis_worker_3" / "1001"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "detail.html").write_text("<html><body>UNC 详情文本</body></html>", encoding="utf-8")
    (artifact_dir / "selected.json").write_text('{"raw_text": "UNC 详情文本"}', encoding="utf-8")
    (artifact_dir / "final.json").write_text('{"item_id": "1001", "community_name": "UNC 小区"}', encoding="utf-8")
    monkeypatch.setenv("FAPAI_SHARED_ARTIFACT_ROOT", str(shared_root))

    unc_root = r"\\192.168.15.200\home\project\project\FPFData"
    detail_path = unc_root + r"\output\nodes\pc2-real\detail_analysis_worker_3\1001\detail.html"
    selected_path = unc_root + r"\output\nodes\pc2-real\detail_analysis_worker_3\1001\selected.json"
    final_path = unc_root + r"\output\nodes\pc2-real\detail_analysis_worker_3\1001\final.json"
    repo.mark_seed_raw_detail_captured("1001", detail_html_path=detail_path, selected_json_path=selected_path)
    repo.mark_seed_detail_completed("1001", final_json_path=final_path, selected_json_path=selected_path)

    payload = repo.collection_observer_item_detail("1001", max_chars=200)

    assert payload["artifacts"]["detail_html"]["exists"] is True
    assert "UNC 详情文本" in payload["artifacts"]["detail_html"]["content"]
    assert payload["artifacts"]["final_json"]["json"]["community_name"] == "UNC 小区"


def test_collection_observer_derives_missing_raw_paths_from_completed_analysis_path(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)
    shared_root = tmp_path / "shared-root"
    artifact_dir = shared_root / "output" / "nodes" / "pc2-real" / "detail_analysis_worker_3" / "1001"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "detail.html").write_text("<html><body>推导详情</body></html>", encoding="utf-8")
    (artifact_dir / "description-data.json").write_text('{"text": "推导描述"}', encoding="utf-8")
    (artifact_dir / "final.json").write_text('{"item_id": "1001", "community_name": "推导小区"}', encoding="utf-8")
    monkeypatch.setenv("FAPAI_SHARED_ARTIFACT_ROOT", str(shared_root))

    final_path = r"\\192.168.15.200\home\project\project\FPFData\output\nodes\pc2-real\detail_analysis_worker_3\1001\final.json"
    repo.mark_seed_detail_completed("1001", final_json_path=final_path, selected_json_path=None)

    payload = repo.collection_observer_item_detail("1001", max_chars=200)

    assert payload["artifacts"]["detail_html"]["exists"] is True
    assert "推导详情" in payload["artifacts"]["detail_html"]["content"]
    assert payload["artifacts"]["description_json"]["exists"] is True


def test_collection_observer_can_requeue_completed_item_for_ai_reanalysis(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _upsert_sample_seed(repo)
    detail_html = tmp_path / "detail.html"
    selected_json = tmp_path / "selected.json"
    final_json = tmp_path / "final.json"
    detail_html.write_text("<html><body>旧分析输入</body></html>", encoding="utf-8")
    selected_json.write_text('{"raw_text": "旧分析输入"}', encoding="utf-8")
    final_json.write_text('{"item_id": "1001", "community_name": "旧小区"}', encoding="utf-8")
    repo.mark_seed_raw_detail_captured("1001", detail_html_path=str(detail_html), selected_json_path=str(selected_json))
    first_claim = repo.claim_seed_raw_detail_item("analysis-worker", lease_seconds=30)
    assert first_claim is not None
    repo.mark_seed_detail_completed("1001", final_json_path=str(final_json), selected_json_path=str(selected_json))

    result = repo.requeue_seed_detail_analysis("1001", reason="operator_requested")

    assert result["ok"] is True
    assert result["item_id"] == "1001"
    assert result["status"] == "raw_detail_captured"
    assert result["analysis_attempt_count"] == 1
    next_claim = repo.claim_seed_raw_detail_item("analysis-worker-2", lease_seconds=30)
    assert next_claim is not None
    assert next_claim["item_id"] == "1001"
    assert next_claim["_raw_detail_artifacts"]["detail_html_path"] == str(detail_html)


def test_collection_observer_manual_update_merges_standardized_fields_into_flat_item(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        {
            "id": "1001",
            "title": "旧标题",
            "url": "https://example.com/old",
            "currentPrice": "1000000",
            "location": "旧地址",
            "city": "旧城市",
            "district": "旧区",
            "area_sqm": "80",
        },
        event_type="seed",
    )

    result = repo.manual_update_flat_item(
        "1001",
        {
            "title": "新标题",
            "transaction_price": "1234567",
            "full_address": "新地址",
            "city": "新城市",
            "district": "新区",
            "area_sqm": "92.5",
            "court_name": "测试法院",
        },
    )

    assert result["ok"] is True
    updated = repo.get_flat_item("1001")
    assert updated is not None
    assert updated["title"] == "新标题"
    assert updated["成交价格"] == 1234567.0
    assert updated["完整地址"] == "新地址"
    assert updated["城市"] == "新城市"
    assert updated["区"] == "新区"
    assert updated["建筑面积"] == 92.5
    assert updated["法院名称"] == "测试法院"


def test_collection_observer_regions_report_stage_specific_completion(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    _upsert_sample_seed(repo, item_id="1001")

    links_initial = repo.collection_observer_regions(stage="links")
    nansha_initial = links_initial["regions"][0]
    assert nansha_initial["location_code"] == "440115"
    assert nansha_initial["completed"] is False
    assert nansha_initial["status_label"] == "采集中"

    with repo.session_factory.begin() as session:
        for progress in session.scalars(select(FapaiSeedScanProgress)).all():
            progress.status = "exhausted"
            progress.completed_at = datetime.now()
            progress.next_page = 83
            session.add(progress)
        job = session.get(FapaiSeedScanJob, "guangdong-guangzhou-nansha-50025969")
        assert job is not None
        job.status = "completed"
        job.completed_at = datetime.now()
        session.add(job)

    links_done = repo.collection_observer_regions(stage="links")
    assert links_done["regions"][0]["completed"] is True
    assert links_done["regions"][0]["status_label"] == "收集完成"

    details_before = repo.collection_observer_regions(stage="details")
    assert details_before["regions"][0]["completed"] is False
    assert details_before["regions"][0]["counts"]["pending"] == 1

    repo.mark_seed_raw_detail_captured("1001", detail_html_path=str(tmp_path / "detail.html"))
    details_done = repo.collection_observer_regions(stage="details")
    assert details_done["regions"][0]["completed"] is True
    assert details_done["regions"][0]["status_label"] == "收集完成"

    analysis_before = repo.collection_observer_regions(stage="analysis")
    assert analysis_before["regions"][0]["completed"] is False
    assert analysis_before["regions"][0]["counts"]["pending"] == 1

    repo.mark_seed_detail_completed("1001", final_json_path=str(tmp_path / "final.json"))
    analysis_done = repo.collection_observer_regions(stage="analysis")
    assert analysis_done["regions"][0]["completed"] is True
    assert analysis_done["regions"][0]["status_label"] == "收集完成"


def test_collection_observer_regions_hides_admin_legacy_rows_for_replaced_taobao_province(
    tmp_path: Path,
    monkeypatch,
) -> None:
    overrides_path = tmp_path / "taobao_sf_location_overrides.json"
    overrides_path.write_text(
        '{"replace_admin_provinces":["上海市"],"locations":[{"province":"上海市","city":"市辖区","district":"崇明","location_code":"310230"}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_TAOBAO_LOCATIONS_FILE", str(overrides_path))
    repo = _make_repo(tmp_path)
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
    repo.ensure_seed_scan_job(
        {
            "job_key": "shanghai-taobao-chongming-50025969",
            "province": "上海市",
            "city": "市辖区",
            "district": "崇明",
            "location_code": "310230",
            "category": "50025969",
            "metadata": {"location_source": "taobao_sf_location_overrides"},
        },
        sort_specs=[{"sort_key": "default", "sort_name": "默认排序", "st_param": "0"}],
        max_page=83,
    )

    payload = repo.collection_observer_regions(stage="links")

    assert [region["location_code"] for region in payload["regions"]] == ["310230"]
    assert payload["regions"][0]["district"] == "崇明"


def test_collection_observer_regions_orders_taobao_locations_by_code_with_other_last(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    sort_specs = [{"sort_key": "default", "sort_name": "默认排序", "st_param": "0"}]
    for district, code in [
        ("其它", "500385"),
        ("南川", "500384"),
        ("云阳", "500235"),
    ]:
        repo.ensure_seed_scan_job(
            {
                "job_key": f"{code}-50025969",
                "province": "重庆市",
                "city": "市辖区",
                "district": district,
                "location_code": code,
                "category": "50025969",
                "metadata": {"location_source": "taobao_sf_location_overrides"},
            },
            sort_specs=sort_specs,
            max_page=83,
        )

    payload = repo.collection_observer_regions(stage="links")

    assert [region["location_code"] for region in payload["regions"]] == ["500235", "500384", "500385"]
    assert payload["regions"][-1]["district"] == "其它"


def test_collection_observer_regions_batches_link_counts_without_per_region_queries(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.initialize()
    for index in range(8):
        code = f"99010{index}"
        repo.ensure_seed_scan_job(
            {
                "job_key": f"batch-region-{index}-50025969",
                "province": "测试省",
                "city": "测试市",
                "district": f"测试区{index}",
                "location_code": code,
                "category": "50025969",
            },
            sort_specs=[
                {"sort_key": "default", "sort_name": "默认排序", "st_param": "0"},
                {"sort_key": "price_desc", "sort_name": "价格由高到低", "st_param": "3"},
            ],
            max_page=83,
        )

    statements: list[str] = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(repo.engine, "before_cursor_execute", record_statement)
    try:
        payload = repo.collection_observer_regions(stage="links")
    finally:
        event.remove(repo.engine, "before_cursor_execute", record_statement)

    assert len(payload["regions"]) == 8
    assert len(statements) <= 4


def test_collection_observer_items_can_filter_by_location_code(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    _upsert_sample_seed(repo, item_id="1001")
    repo.ensure_seed_scan_job(
        {
            "job_key": "shanghai-shanghai-fengxian-50025969",
            "province": "上海市",
            "city": "上海市",
            "district": "奉贤区",
            "location_code": "310120",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "default", "sort_name": "默认排序", "st_param": "4"}],
        max_page=10,
    )
    repo.upsert_seed_items(
        job_key="shanghai-shanghai-fengxian-50025969",
        progress_key="shanghai-shanghai-fengxian-50025969::default",
        sort_key="default",
        sort_name="默认排序",
        st_param="4",
        page=1,
        source_page_url="https://sf-item.taobao.com/list/shanghai?page=1",
        source_final_url="https://sf-item.taobao.com/list/shanghai?page=1&st=4",
        items=[{"id": "2001", "title": "上海市奉贤区测试房产", "url": "https://sf-item.taobao.com/sf_item/2001.htm"}],
    )

    payload = repo.collection_observer_items(stage="links", limit=20, offset=0, location_code="440115")

    assert payload["total"] == 1
    assert [item["item_id"] for item in payload["items"]] == ["1001"]
    assert payload["location_code"] == "440115"


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
