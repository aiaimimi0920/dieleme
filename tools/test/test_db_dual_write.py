import importlib
import json
from pathlib import Path
import threading
import urllib.request

import pytest
from sqlalchemy import func, select

from src.avm.collection_template import build_collection_record, sync_collection_record
from src.collection.seed_service import SeedCollectionService
from src.avm.service import AVMService
from src.storage.models import (
    ManualReviewReceipt,
    ManualReviewReceiptJob,
    ManualReviewReceiptOperation,
    PropertyAudit,
    PropertyIngestEvent,
    PropertyLegalContext,
    PropertyListing,
    PropertyRiskFlags,
    PropertySearchTask,
)
from src.storage.repository import DatabaseSettings, PropertyRepository


def _make_repo(tmp_path: Path) -> PropertyRepository:
    db_path = tmp_path / "dual-write.sqlite3"
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def _make_flat_item(**overrides):
    item = {
        "id": "9001",
        "title": "Test Listing",
        "url": "https://example.com/item/9001",
        "list_payload_path": "archive_payloads/2026-05-11/list-001.json",
        "detail_archive_path": "html_archive/2026/2026-05-11/item-9001.html",
        "end": "2026-05-11 10:00:00",
        "currentPrice": "1000000",
        "initialPrice": "800000",
        "deposit": "50000",
        "applyCount": "4",
        "bidCount": "7",
        "bidderCount": "3",
        "watchCount": "120",
        "remindCount": "18",
        "viewCount": "300",
        "location": "Shanghai Pudong Test Rd 99",
        "city": "Shanghai",
        "district": "Pudong",
        "business_area_name": "Lujiazui",
        "community_name": "Test Garden",
        "lat": "31.23",
        "lng": "121.56",
        "coordinate_source": "list",
        "housingType": "residential",
        "area_sqm": "89.5",
        "ownership_share_ratio": "1/2",
        "layout": "2br1lr",
        "appraisal_report_urls": "https://example.com/a.pdf; https://example.com/b.pdf",
        "announcement_attachment_urls": ["https://example.com/c.pdf"],
        "avm_risk_features": {
            "is_occupied": "yes",
            "is_fractional_share": "true",
            "has_elevator": "false",
            "build_year": "2001",
            "floor_level": "high",
            "property_fee_owed": 1,
            "tax_burden": "buyer",
            "evidence_span": ["line1", "line2"],
            "evidence_source": "llm",
            "extraction_version": "risk_v2",
        },
    }
    risk_overrides = overrides.pop("avm_risk_features", None)
    item.update(overrides)
    if risk_overrides:
        item["avm_risk_features"].update(risk_overrides)
    return item


def test_build_collection_record_normalizes_flat_json_into_template_record():
    record = build_collection_record(_make_flat_item())

    assert record["source"]["item_id"] == "9001"
    assert record["source"]["source_item_id"] == "9001"
    assert record["source"]["source_platform"] == "taobao_sf"
    assert record["source"]["source_title"] == "Test Listing"

    assert record["auction"]["auction_date"] == "2026-05-11 10:00:00"
    assert record["auction"]["transaction_price"] == pytest.approx(1_000_000.0)
    assert record["auction"]["starting_price"] == pytest.approx(800_000.0)
    assert record["auction"]["deposit"] == pytest.approx(50_000.0)
    assert record["auction"]["apply_count"] == 4
    assert record["auction"]["bid_count"] == 7
    assert record["auction"]["bidder_count"] == 3

    assert record["location"]["full_address"] == "Shanghai Pudong Test Rd 99"
    assert record["location"]["community_name"] == "Test Garden"
    assert record["location"]["latitude"] == pytest.approx(31.23)
    assert record["location"]["longitude"] == pytest.approx(121.56)

    assert record["property"]["area_sqm"] == pytest.approx(89.5)
    assert record["property"]["gross_area_sqm"] == pytest.approx(179.0)
    assert record["property"]["ownership_share_ratio"] == pytest.approx(0.5)
    assert record["property"]["has_elevator"] is False
    assert record["property"]["build_year"] == 2001

    assert record["legal_context"]["appraisal_report_urls"] == [
        "https://example.com/a.pdf",
        "https://example.com/b.pdf",
    ]
    assert record["legal_context"]["announcement_attachment_urls"] == ["https://example.com/c.pdf"]

    assert record["risk_flags"]["is_occupied"] is True
    assert record["risk_flags"]["is_fractional_share"] is True
    assert record["risk_flags"]["property_fee_owed"] is True
    assert record["audit"]["evidence_source"] == "llm"
    assert record["audit"]["evidence_span"] == "['line1', 'line2']"


def test_repository_upsert_flat_item_updates_existing_listing_without_duplicate_rows(tmp_path: Path):
    repo = _make_repo(tmp_path)

    repo.upsert_flat_item(_make_flat_item(), event_type="sniff_saved", event_payload={"seq": 1, "source_file": "datas/archive/2026/2026-05-11.json"})
    repo.upsert_flat_item(
        _make_flat_item(
            title="Updated Listing",
            currentPrice="1120000",
            bidCount="9",
            lat="31.231",
            announcement_attachment_urls="https://example.com/updated.pdf",
            avm_risk_features={"is_occupied": "no", "build_year": "2003"},
        ),
        event_type="detail_saved",
        event_payload={"seq": 2},
    )

    assert repo.count_listings() == 1

    with repo.session_factory() as session:
        listing = session.get(PropertyListing, "9001")
        risk_row = session.get(PropertyRiskFlags, "9001")
        legal_row = session.get(PropertyLegalContext, "9001")
        audit_row = session.get(PropertyAudit, "9001")
        events = session.scalars(
            select(PropertyIngestEvent)
            .where(PropertyIngestEvent.item_id == "9001")
            .order_by(PropertyIngestEvent.id.asc())
        ).all()

        assert listing is not None
        assert listing.source_title == "Updated Listing"
        assert float(listing.transaction_price) == pytest.approx(1_120_000.0)
        assert listing.bid_count == 9
        assert listing.latitude == pytest.approx(31.231)
        assert listing.build_year == 2003
        assert listing.is_deleted is False
        assert listing.deleted_reason is None

        assert risk_row is not None
        assert risk_row.is_occupied is False

        assert legal_row is not None
        assert legal_row.announcement_attachment_urls == ["https://example.com/updated.pdf"]

        assert audit_row is not None
        assert audit_row.detail_archive_path == "html_archive/2026/2026-05-11/item-9001.html"
        assert audit_row.source_json_path == "datas/archive/2026/2026-05-11.json"
        assert audit_row.evidence_source == "llm"

        assert session.scalar(select(func.count()).select_from(PropertyListing)) == 1
        assert session.scalar(select(func.count()).select_from(PropertyRiskFlags)) == 1
        assert session.scalar(select(func.count()).select_from(PropertyLegalContext)) == 1
        assert session.scalar(select(func.count()).select_from(PropertyAudit)) == 1
        event_types = [event.event_type for event in events]
        assert "sniff_saved" in event_types
        assert "detail_saved" in event_types
        assert "seed_stage_transition" in event_types
        assert "detail_stage_transition" in event_types
        assert "analysis_stage_transition" in event_types
        assert "analysis_ready_transition" in event_types
        assert events[-1].event_payload == {"seq": 2}

    flat_item = repo.get_flat_item("9001")
    assert flat_item is not None
    assert flat_item["json_file"] == "datas/archive/2026/2026-05-11.json"
    assert flat_item["__file_path"] == "datas/archive/2026/2026-05-11.json"


def test_dual_write_keeps_json_snapshot_and_db_row_on_single_item_upsert(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)

    json_path = tmp_path / "2026-05-11.json"

    first_item = _make_flat_item()
    sync_collection_record(first_item)
    server_module.update_item_in_json(str(json_path), "9001", first_item)
    server_module.persist_item_to_db(first_item, event_type="sniff_saved", event_payload={"seq": 1})

    second_item = _make_flat_item(
        title="Dual Write Updated",
        currentPrice="1135000",
        bidCount="10",
        source_platform="manual_test",
        avm_risk_features={"is_occupied": "no"},
    )
    sync_collection_record(second_item)
    server_module.update_item_in_json(str(json_path), "9001", second_item)
    server_module.persist_item_to_db(second_item, event_type="sniff_saved", event_payload={"seq": 2})

    stored_items = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(stored_items) == 1
    assert stored_items[0]["id"] == "9001"
    assert stored_items[0]["source"]["source_title"] == "Dual Write Updated"
    assert stored_items[0]["source"]["source_platform"] == "manual_test"
    assert stored_items[0]["auction"]["transaction_price"] == pytest.approx(1_135_000.0)
    assert stored_items[0]["auction"]["bid_count"] == 10

    with repo.session_factory() as session:
        listing = session.get(PropertyListing, "9001")
        events = session.scalars(
            select(PropertyIngestEvent)
            .where(PropertyIngestEvent.item_id == "9001")
            .order_by(PropertyIngestEvent.id.asc())
        ).all()

        assert listing is not None
        assert listing.source_title == "Dual Write Updated"
        assert listing.source_platform == "manual_test"
        assert float(listing.transaction_price) == pytest.approx(1_135_000.0)
        assert listing.bid_count == 10
        assert session.scalar(select(func.count()).select_from(PropertyListing)) == 1
        business_event_payloads = [event.event_payload for event in events if event.event_type == "sniff_saved"]
        assert business_event_payloads == [{"seq": 1}, {"seq": 2}]


def test_load_data_db_first_keeps_runtime_cache_empty_until_items_are_requested(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9101", currentPrice="980000"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "empty-datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.load_data()

    assert server_module.SEEN_IDS == {}
    assert server_module.PENDING_TASKS == []


def test_repository_counts_snapshot_and_coordinate_centroids(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        _make_flat_item(
            id="centroid-1",
            city="上海市",
            district="浦东新区",
            community_name="测试花园",
            lat="31.2000",
            lng="121.5000",
        ),
        event_type="seed",
        event_payload={"source_file": "datas/archive/2026/2026-05-11.json"},
    )
    repo.upsert_flat_item(
        _make_flat_item(
            id="centroid-2",
            city="上海市",
            district="浦东新区",
            community_name="测试花园",
            lat="31.3000",
            lng="121.7000",
            avm_risk_features={"is_occupied": "no"},
        ),
        event_type="seed",
        event_payload={"source_file": "datas/archive/2026/2026-05-12.json"},
    )

    counts = repo.counts_snapshot()
    centroids = repo.build_coordinate_centroids()

    assert counts["db_total_ids"] == 2
    assert counts["db_pending_ids"] == 2
    assert centroids["community::测试花园"] == (31.25, 121.6)


def test_repository_analysis_readiness_snapshot_counts_blockers(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        _make_flat_item(
            id="blocker-1",
            city="上海市",
            district="浦东新区",
            business_area_name="",
            community_name="",
            lat="",
            lng="",
            area_sqm="",
            currentPrice="",
            initialPrice="",
            detail_archive_path=None,
            status="pending",
        ),
        event_type="seed",
        event_payload={"source_file": "datas/archive/2026/2026-05-11.json"},
    )

    snapshot = repo.analysis_readiness_snapshot()

    assert snapshot["ready"] == 0
    assert snapshot["not_ready"] == 1
    assert snapshot["invalid"] == 0
    assert snapshot["blockers"]["area_sqm"] == 1
    assert snapshot["blockers"]["business_area"] == 1
    assert snapshot["blockers"]["price_anchor"] == 1
    assert snapshot["blockers"]["detail_stage"] == 1
    assert snapshot["blockers"]["status"] == 1
    assert snapshot["blockers"]["location_precision"] == 1


def test_repository_event_type_counts_and_detail_fetch_candidate_block_cooldown(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        _make_flat_item(id="cooldown-1", detail_archive_path=None, url="https://example.com/item/cooldown-1"),
        event_type="detail_archive_fetch_blocked",
        event_payload={"source_file": "datas/archive/2026/2026-05-11.json"},
    )

    counts = repo.event_type_counts(("detail_archive_fetch_blocked",), hours=24)
    blocked_ids = repo.recent_event_item_ids(("detail_archive_fetch_blocked",), hours=24)
    candidates = repo.iter_detail_fetch_candidates(limit=10)

    assert counts["detail_archive_fetch_blocked"] == 1
    assert "cooldown-1" in blocked_ids
    assert all(row["item_id"] != "cooldown-1" for row in candidates)


def test_load_data_prefers_database_over_stale_json_when_db_is_enabled(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9201", title="DB Title", currentPrice="980000"), event_type="seed")

    data_dir = tmp_path / "datas"
    data_dir.mkdir(parents=True, exist_ok=True)
    stale_file = data_dir / "2026-05-11.json"
    stale_file.write_text(
        json.dumps(
            [
                {
                    "id": "9201",
                    "title": "Stale JSON Title",
                    "成交价格": "1万",
                    "交易时间": "2026-05-11 10:00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(data_dir))
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.load_data()

    assert server_module.SEEN_IDS == {}
    working = server_module._get_working_item("9201", include_processed=True)
    assert working["data"]["source_title"] == "DB Title"
    assert server_module.SEEN_IDS == {}


def test_repository_pending_task_queries_and_processed_counts(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9301", title="Pending", url="https://x/9301"), event_type="seed")
    repo.upsert_flat_item(
        _make_flat_item(id="9302", title="Processed", url="https://x/9302", avm_risk_features={"is_occupied": "no"}),
        event_type="seed",
    )

    with repo.session_factory.begin() as session:
        audit_row = session.get(PropertyAudit, "9302")
        audit_row.is_processed = True

    pending = repo.iter_pending_task_items(limit=10)
    pending_ids = [row["id"] for row in pending]

    assert "9301" in pending_ids
    assert "9302" not in pending_ids
    assert repo.count_pending_task_items() == 1


def test_repository_manual_review_receipt_persistence_and_audit(tmp_path: Path):
    repo = _make_repo(tmp_path)

    upsert = repo.upsert_manual_review_receipt(
        {
            "action": "manual_location_review",
            "ready_signal": "location_artifacts_complete",
            "status": "ready_for_reentry",
            "payload": {"full_address": "A"},
            "source": "operator_api",
        }
    )
    repo.append_manual_review_receipt_operation(
        operation="created",
        receipt=upsert["receipt"],
        execution_mode="async",
        maintenance_job_id="job-1",
    )
    job = repo.create_manual_review_receipt_job(
        receipt_key={"action": "manual_location_review", "ready_signal": "location_artifacts_complete"},
        maintenance_options={"window_days": 7},
    )
    repo.update_manual_review_receipt_job(
        job["job_id"],
        status="completed",
        result_summary={"generated_at": "x", "reentry_applied": True},
        finished_at="2026-05-15 10:00:00",
    )

    receipts = repo.list_manual_review_receipts()
    assert receipts["receipts"][0]["action"] == "manual_location_review"

    operations = repo.list_manual_review_receipt_operations(action="manual_location_review")
    assert len(operations) == 1
    assert operations[0]["maintenance_job_id"] == "job-1"

    jobs_snapshot = repo.manual_review_receipt_jobs_snapshot()
    assert jobs_snapshot["jobs"][0]["job_id"] == job["job_id"]
    assert jobs_snapshot["jobs"][0]["status"] == "completed"

    deleted = repo.delete_manual_review_receipt("manual_location_review", "location_artifacts_complete")
    assert deleted["deleted"] is True
    assert deleted["receipt_count"] == 0

    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ManualReviewReceipt)) == 0
        assert session.scalar(select(func.count()).select_from(ManualReviewReceiptOperation)) == 1
        assert session.scalar(select(func.count()).select_from(ManualReviewReceiptJob)) == 1


def test_repository_persists_collection_stage_state_and_search_task_cursors(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        _make_flat_item(
            id="stage-1",
            status="done",
            detail_captured=True,
            source_page_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
            business_area="Lujiazui",
        ),
        event_type="sniff_saved",
        event_payload={
            "source_file": "datas/archive/2026/2026-05-11.json",
            "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
        },
    )

    db_item = repo.get_flat_item("stage-1")
    assert db_item["seed_status"] == "stored"
    assert db_item["detail_status"] in {"archived", "enriched"}
    assert db_item["analysis_status"] == "ready"
    assert db_item["analysis_ready"] is True
    assert db_item["analysis_model_version"] == "avm_multidim_v1"
    assert db_item["seed_source_page_url"] == "https://sf.taobao.com/list/50025969__2.htm?page=1"

    task = {
        "location_code": "310115",
        "category": "50025969",
        "st_param": "2",
        "page": 1,
        "url": "https://sf.taobao.com/list/50025969__2.htm?location_code=310115&st_param=2&auction_start_seg=-1&page=1",
    }
    repo.bootstrap_search_task(task, leased_by="sess-a")
    claimed = repo.claim_search_task("sess-a")
    assert claimed is not None
    assert claimed["location_code"] == "310115"
    assert claimed["page"] == 1

    repo.report_search_task_progress(url=claimed["url"], page_num=1, has_next=True, max_page=3)
    counts = repo.search_task_counts()
    assert counts["search_pending"] == 1

    claimed_next = repo.claim_search_task("sess-b")
    assert claimed_next is not None
    assert claimed_next["page"] == 2
    repo.report_search_task_progress(url=claimed_next["url"], page_num=2, has_next=False)
    counts = repo.search_task_counts()
    assert counts["search_done"] == 1

    with repo.session_factory() as session:
        task_row = session.get(PropertySearchTask, "310115:50025969:2")
        assert task_row is not None
        assert task_row.status == "done"


def test_seed_collection_service_bootstraps_and_claims_db_search_tasks(tmp_path: Path):
    repo = _make_repo(tmp_path)
    data_root = tmp_path / "datas"
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "all_locations.json").write_text(
        json.dumps([{"code": "310115", "name": "浦东新区"}], ensure_ascii=False),
        encoding="utf-8",
    )
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    (jobs_root / "priority.json").write_text(json.dumps(["310115"], ensure_ascii=False), encoding="utf-8")

    service = SeedCollectionService(repository=repo, jobs_dir=str(jobs_root), data_root=str(data_root))
    result = service.next_task("seed-session-1", paused=False)

    assert result["task"] is not None
    assert result["task"]["location_code"] == "310115"
    assert result["task"]["st_param"] == "2"
    counts = repo.search_task_counts()
    assert counts["search_in_progress"] == 1


def test_http_status_exposes_collection_stage_snapshot_from_database(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-1", url="https://x/stage-http-1"), event_type="seed")
    repo.ensure_seed_search_tasks(["310115"], ["50025969"], sort_param="2")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body["collection_stage"]["seed_stage"]["stored"] >= 1
        assert body["collection_stage"]["search_tasks"]["search_pending"] == 1
        assert "analysis_blockers" in body["collection_stage"]
        assert "recommended_actions" in body["collection_stage"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_recommended_actions_can_reflect_persisted_action_effectiveness(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-2", url="https://x/stage-http-2", status="pending", detail_archive_path=None), event_type="seed")
    repo.ensure_seed_search_tasks(["310115"], ["50025969"], sort_param="2")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    monkeypatch.setattr(
        server_module,
        "load_action_effectiveness_snapshot",
        lambda path=None: {
            "detail_archive_fetch": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        recommended = body["collection_stage"]["recommended_actions"]
        assert "fetch_archives" in recommended["deprioritized_actions"]
        assert "detail_archive_fetch_low_yield" in recommended["feedback_hints"]
        assert "next_best_alternative_actions" in recommended
        assert "operator_summary" in recommended
        summary = body["collection_stage"]["action_effectiveness_summary"]
        assert "detail_archive_fetch" in summary["low_yield_actions"]
        assert summary["top_low_yield_action"] == "detail_archive_fetch"
        assert summary["top_low_yield_actions"] == ["detail_archive_fetch"]
        operator_summary = body["collection_stage"]["operator_action_summary"]
        assert operator_summary["top_low_yield_actions"] == ["detail_archive_fetch"]
        assert operator_summary["top_alternative_actions"][0] == "prepare_replay"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_recommended_actions_can_surface_manual_review_fallback(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-3", url="https://x/stage-http-3", status="pending", detail_archive_path=None), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    monkeypatch.setattr(
        server_module,
        "load_action_effectiveness_snapshot",
        lambda path=None: {
            "detail_replay_preparation": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        recommended = body["collection_stage"]["recommended_actions"]
        assert recommended["manual_review_candidate"] is True
        assert recommended["fallback_routes"]["prepare_replay"] == "manual_review"
        operator_summary = body["collection_stage"]["operator_action_summary"]
        assert operator_summary["manual_review_candidates"] == ["manual_review"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_recoverability_summary_and_manual_review_reason(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-4", url="https://x/stage-http-4", status="pending", detail_archive_path=None), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    monkeypatch.setattr(
        server_module,
        "load_recent_gap_audit_snapshot",
        lambda path=None: {
            "recoverability_counts": {
                "future_fixable": 0,
                "historical_unrecoverable": 2,
                "archive_backfill_candidate": 0,
                "replay_candidate": 0,
                "coordinate_infer_candidate": 0,
            },
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["detail_stage"], "missing_fields": ["latitude"]},
                {"item_id": "mr-2", "title": "样本2", "historical_unrecoverable": True, "analysis_missing_fields": ["price_anchor"], "missing_fields": ["is_occupied"]},
            ],
        },
    )
    monkeypatch.setattr(
        server_module,
        "load_optimization_loop_progress_snapshot",
        lambda path=None: {
            "manual_review_candidate_rounds": 2,
            "manual_review_reasons": {"historical_unrecoverable_gap": 2},
            "top_manual_review_reason": "historical_unrecoverable_gap",
            "human_action_counts": {"manual_location_review": 4, "manual_price_anchor_review": 1},
            "retry_policy_counts": {"human_fix_required_before_retry": 2},
            "top_retry_policy": "human_fix_required_before_retry",
            "handoff_lifecycle_counts": {"awaiting_human_receipt_hard_stop": 2},
            "top_handoff_lifecycle_state": "awaiting_human_receipt_hard_stop",
            "pending_ready_signal_counts": {"location_artifacts_complete": 2},
            "top_pending_ready_signal": "location_artifacts_complete",
            "invalid_receipt_reason_counts": {"missing_required_fields": 2},
            "top_invalid_receipt_reason": "missing_required_fields",
            "fallback_usage": {"fetch_archives": {"prepare_replay": 3}},
        },
    )
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        recoverability = body["collection_stage"]["recoverability_summary"]
        assert recoverability["future_fixable"] == 0
        assert recoverability["historical_unrecoverable"] == 2
        operator_summary = body["collection_stage"]["operator_action_summary"]
        assert operator_summary["top_manual_review_reason"] == "historical_unrecoverable_gap"
        assert operator_summary["manual_review_required"] is True
        scheduler_summary = body["collection_stage"]["scheduler_feedback_summary"]
        assert scheduler_summary["manual_review_candidate_rounds"] == 2
        assert scheduler_summary["top_fallback_routes"] == ["fetch_archives->prepare_replay"]
        assert scheduler_summary["top_human_actions"] == ["manual_location_review", "manual_price_anchor_review"]
        assert scheduler_summary["top_retry_policy"] == "human_fix_required_before_retry"
        assert scheduler_summary["top_handoff_lifecycle_state"] == "awaiting_human_receipt_hard_stop"
        assert scheduler_summary["top_pending_ready_signal"] == "location_artifacts_complete"
        assert scheduler_summary["top_invalid_receipt_reason"] == "missing_required_fields"
        backlog_summary = body["collection_stage"]["manual_review_backlog_summary"]
        assert backlog_summary["candidate_count"] == 2
        assert backlog_summary["sample_item_ids"] == ["mr-1", "mr-2"]
        assert backlog_summary["top_human_actions"][0] == "manual_location_review"
        assert "full_address" in backlog_summary["top_human_action_instructions"][0]
        assert backlog_summary["human_action_queues"]["manual_location_review"]["count"] == 2
        assert backlog_summary["human_action_queues"]["manual_location_review"]["expected_reentry_path"] == "infer_location_or_coordinate_backfill"
        assert backlog_summary["human_action_queues"]["manual_location_review"]["priority_label"] == "high"
        assert backlog_summary["human_action_queues"]["manual_location_review"]["suggested_handoff_priority"] == "P0"
        assert "full_address" in backlog_summary["human_action_queues"]["manual_location_review"]["queue_level_checklist"][0]
        assert "重新打开" in backlog_summary["human_action_queues"]["manual_location_review"]["suggested_handoff_priority_reason"]
        assert "latitude/longitude" in backlog_summary["human_action_queues"]["manual_location_review"]["queue_level_completion_criteria"][0]
        assert "coordinate_backfill" in backlog_summary["human_action_queues"]["manual_location_review"]["reentry_validation_checklist"][0]
        assert "full_address" in backlog_summary["human_action_queues"]["manual_location_review"]["handoff_artifact_fields"]
        assert "坐标" in backlog_summary["human_action_queues"]["manual_location_review"]["required_human_evidence"][0]
        assert "location blocker" in backlog_summary["human_action_queues"]["manual_location_review"]["reentry_blockers_if_incomplete"][0]
        assert "核对结论" in backlog_summary["human_action_queues"]["manual_location_review"]["required_human_resolution_notes"][0]
        assert backlog_summary["human_action_queues"]["manual_location_review"]["reentry_ready_signal"] == "location_artifacts_complete"
        assert "full_address" in backlog_summary["human_action_queues"]["manual_location_review"]["handoff_completion_payload"]["required_fields"]
        overview = body["collection_stage"]["operator_overview"]
        assert overview["manual_review_required"] is True
        assert overview["top_manual_review_reason"] == "historical_unrecoverable_gap"
        assert overview["top_human_actions"][0] == "manual_location_review"
        assert "full_address" in overview["top_human_action_instructions"][0]
        assert overview["handoff_mode"] == "manual_required_hard_stop"
        assert overview["handoff_lifecycle_state"] == "awaiting_human_receipt_hard_stop"
        assert overview["auto_retry_policy"]["policy"] == "human_fix_required_before_retry"
        assert overview["top_pending_ready_signal"] == "location_artifacts_complete"
        assert overview["top_human_action_queue"]["expected_reentry_path"] == "infer_location_or_coordinate_backfill"
        assert overview["top_human_action_queue"]["priority_label"] == "high"
        assert overview["top_human_action_queue"]["suggested_handoff_priority"] == "P0"
        assert "full_address" in overview["top_human_action_queue"]["queue_level_checklist"][0]
        assert "重新打开" in overview["top_human_action_queue"]["suggested_handoff_priority_reason"]
        assert "latitude/longitude" in overview["top_human_action_queue"]["queue_level_completion_criteria"][0]
        assert "coordinate_backfill" in overview["top_human_action_queue"]["reentry_validation_checklist"][0]
        assert "full_address" in overview["top_human_action_queue"]["handoff_artifact_fields"]
        assert "坐标" in overview["top_human_action_queue"]["required_human_evidence"][0]
        assert "location blocker" in overview["top_human_action_queue"]["reentry_blockers_if_incomplete"][0]
        assert "核对结论" in overview["top_human_action_queue"]["required_human_resolution_notes"][0]
        assert overview["top_human_action_queue"]["reentry_ready_signal"] == "location_artifacts_complete"
        assert "full_address" in overview["top_human_action_queue"]["handoff_completion_payload"]["required_fields"]
        assert body["collection_stage"]["scheduler_feedback_summary"]["top_handoff_mode"] == "manual_required_hard_stop"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_manual_review_receipt_ready_state(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-5", url="https://x/stage-http-5", status="pending", detail_archive_path=None), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    monkeypatch.setattr(
        server_module,
        "load_recent_gap_audit_snapshot",
        lambda path=None: {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
            ],
        },
    )
    monkeypatch.setattr(server_module, "load_action_effectiveness_snapshot", lambda path=None: {})
    monkeypatch.setattr(server_module, "load_optimization_loop_progress_snapshot", lambda path=None: {})
    monkeypatch.setattr(
        server_module,
        "load_manual_review_receipt_snapshot",
        lambda path=None: {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {
                        "full_address": "A",
                        "community_name": "B",
                        "business_area": "C",
                        "latitude": 1.0,
                        "longitude": 2.0,
                    },
                }
            ]
        },
    )
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        receipt_summary = body["collection_stage"]["manual_review_receipt_summary"]
        assert receipt_summary["top_matched_ready_signal"] == "location_artifacts_complete"
        assert receipt_summary["top_receipt_status"] == "ready_for_reentry"
        assert body["collection_stage"]["recommended_actions"]["run_coordinate_backfill"] is True
        reentry_summary = body["collection_stage"]["manual_review_reentry_application_summary"]
        assert reentry_summary["reentry_applied"] is False
        overview = body["collection_stage"]["operator_overview"]
        assert overview["handoff_lifecycle_state"] == "receipt_ready_for_reentry"
        assert overview["should_resume_automation"] is True
        assert overview["matched_ready_signals"] == ["location_artifacts_complete"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_incomplete_manual_review_receipt(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-6", url="https://x/stage-http-6", status="pending", detail_archive_path=None), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    monkeypatch.setattr(
        server_module,
        "load_recent_gap_audit_snapshot",
        lambda path=None: {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
            ],
        },
    )
    monkeypatch.setattr(server_module, "load_action_effectiveness_snapshot", lambda path=None: {})
    monkeypatch.setattr(server_module, "load_optimization_loop_progress_snapshot", lambda path=None: {})
    monkeypatch.setattr(
        server_module,
        "load_manual_review_receipt_snapshot",
        lambda path=None: {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                }
            ]
        },
    )
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        receipt_summary = body["collection_stage"]["manual_review_receipt_summary"]
        assert receipt_summary["top_receipt_status"] == "receipt_incomplete"
        assert receipt_summary["invalid_receipt_count"] == 1
        assert receipt_summary["top_invalid_receipt_reason"] == "missing_required_fields"
        assert receipt_summary["top_receipt_fix_actions"] == ["complete_required_fields"]
        overview = body["collection_stage"]["operator_overview"]
        assert overview["handoff_lifecycle_state"] == "awaiting_valid_receipt"
        assert overview["should_resume_automation"] is False
        assert overview["top_invalid_receipt_reason"] == "missing_required_fields"
        assert overview["top_receipt_fix_actions"] == ["complete_required_fields"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_receipt_control_plane_can_feed_status_summary_end_to_end(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-7", url="https://x/stage-http-7", status="pending", detail_archive_path=None), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    monkeypatch.setattr(
        server_module,
        "load_recent_gap_audit_snapshot",
        lambda path=None: {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
            ],
        },
    )
    monkeypatch.setattr(server_module, "load_action_effectiveness_snapshot", lambda path=None: {})
    monkeypatch.setattr(server_module, "load_optimization_loop_progress_snapshot", lambda path=None: {})
    original_service = server_module.AVM_SERVICE
    original_start_time = server_module.AVM_SERVICE_START_TIME
    server_module.AVM_SERVICE = AVMService(data_dir=server_module.DATA_DIR, repository=repo)
    server_module.AVM_SERVICE_START_TIME = 0
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False
    monkeypatch.setattr(server_module, "run_recent_enrich_maintenance", lambda **kwargs: {"generated_at": "x"})

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/analysis/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {
                        "full_address": "A",
                        "community_name": "B",
                        "business_area": "C",
                        "latitude": 1.0,
                        "longitude": 2.0,
                    },
                    "mode": "async",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            write_body = json.loads(resp.read().decode("utf-8"))
        assert write_body["operation"] == "created"
        assert write_body["execution_mode"] == "async"

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            status_body = json.loads(resp.read().decode("utf-8"))
        receipt_summary = status_body["collection_stage"]["manual_review_receipt_summary"]
        assert receipt_summary["top_matched_ready_signal"] == "location_artifacts_complete"
        assert receipt_summary["top_receipt_status"] == "ready_for_reentry"
        overview = status_body["collection_stage"]["operator_overview"]
        assert overview["handoff_lifecycle_state"] == "receipt_ready_for_reentry"
        assert overview["matched_ready_signals"] == ["location_artifacts_complete"]
        jobs_summary = status_body["collection_stage"]["manual_review_receipt_jobs_summary"]
        assert jobs_summary["last_job_status"] in {"queued", "running", "completed"}
        assert jobs_summary["last_job_receipt_key"]["action"] == "manual_location_review"
        operations_summary = status_body["collection_stage"]["manual_review_receipt_operations_summary"]
        assert operations_summary["last_operation_type"] == "created"
        assert operations_summary["last_operation_receipt_key"]["action"] == "manual_location_review"
        assert operations_summary["last_async_operation_receipt_key"]["action"] == "manual_location_review"
        storage_summary = status_body["collection_stage"]["manual_review_control_plane_storage"]
        assert storage_summary["state_source"] == "repository"
        assert storage_summary["repository_enabled"] is True
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_module.AVM_SERVICE = original_service
        server_module.AVM_SERVICE_START_TIME = original_start_time


def test_http_receipt_control_plane_prefers_database_backed_state_when_repo_enabled(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server_module, "run_recent_enrich_maintenance", lambda **kwargs: {"generated_at": "x"})
    monkeypatch.setattr(
        server_module,
        "load_recent_gap_audit_snapshot",
        lambda path=None: {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
            ],
        },
    )
    monkeypatch.setattr(server_module, "load_action_effectiveness_snapshot", lambda path=None: {})
    monkeypatch.setattr(server_module, "load_optimization_loop_progress_snapshot", lambda path=None: {})
    original_service = server_module.AVM_SERVICE
    original_start_time = server_module.AVM_SERVICE_START_TIME
    server_module.AVM_SERVICE = AVMService(data_dir=server_module.DATA_DIR, repository=repo)
    server_module.AVM_SERVICE_START_TIME = 0
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/analysis/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {
                        "full_address": "A",
                        "community_name": "B",
                        "business_area": "C",
                        "latitude": 1.0,
                        "longitude": 2.0,
                    },
                    "mode": "async",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            write_body = json.loads(resp.read().decode("utf-8"))
        assert write_body["operation"] == "created"
        assert write_body["execution_mode"] == "async"

        avm_root = Path(server_module.DATA_DIR) / "avm"
        receipt_path = avm_root / "manual_review_receipts.json"
        operations_path = avm_root / "manual_review_receipt_operations.jsonl"
        jobs_path = avm_root / "manual_review_receipt_jobs.json"
        assert receipt_path.exists()
        assert operations_path.exists()
        assert jobs_path.exists()

        receipt_backup = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt_backup["receipts"][0]["action"] == "manual_location_review"

        jobs_backup = json.loads(jobs_path.read_text(encoding="utf-8"))
        assert jobs_backup["jobs"][0]["job_id"] == write_body["maintenance_job_id"]

        operation_lines = operations_path.read_text(encoding="utf-8").splitlines()
        assert len(operation_lines) == 1
        assert json.loads(operation_lines[0])["operation"] == "created"

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_receipts") as resp:
            receipts_body = json.loads(resp.read().decode("utf-8"))
        assert receipts_body["receipt_count"] == 1
        assert receipts_body["receipts"][0]["action"] == "manual_location_review"
        backup_summary = receipts_body["manual_review_control_plane_backup"]
        assert backup_summary["backup_state"] == "in_sync"
        assert backup_summary["source_receipt_count"] == 1
        assert backup_summary["backup_receipt_count"] == 1
        assert backup_summary["all_backup_files_present"] is True

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_receipt_operations") as resp:
            operations_body = json.loads(resp.read().decode("utf-8"))
        assert operations_body["operation_count"] == 1
        assert operations_body["operations"][0]["operation"] == "created"
        assert operations_body["manual_review_control_plane_backup"]["backup_state"] == "in_sync"
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_module.AVM_SERVICE = original_service
        server_module.AVM_SERVICE_START_TIME = original_start_time


def test_http_receipt_control_plane_bootstraps_db_from_existing_json_files(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    data_root = tmp_path / "datas"
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "manual_review_receipts.json").write_text(
        json.dumps(
            {
                "receipts": [
                    {
                        "action": "manual_location_review",
                        "ready_signal": "location_artifacts_complete",
                        "status": "ready_for_reentry",
                        "payload": {
                            "full_address": "A",
                            "community_name": "B",
                            "business_area": "C",
                            "latitude": 1.0,
                            "longitude": 2.0,
                        },
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (avm_root / "manual_review_receipt_operations.jsonl").write_text(
        json.dumps(
            {
                "operation_id": "op-1",
                "operation": "created",
                "action": "manual_location_review",
                "ready_signal": "location_artifacts_complete",
                "status": "ready_for_reentry",
                "payload_fingerprint": "fp-1",
                "execution_mode": "async",
                "requested_at": "2026-05-15 10:00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(data_root))
    monkeypatch.setattr(
        server_module,
        "load_recent_gap_audit_snapshot",
        lambda path=None: {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
            ],
        },
    )
    monkeypatch.setattr(server_module, "load_action_effectiveness_snapshot", lambda path=None: {})
    monkeypatch.setattr(server_module, "load_optimization_loop_progress_snapshot", lambda path=None: {})
    original_service = server_module.AVM_SERVICE
    original_start_time = server_module.AVM_SERVICE_START_TIME
    server_module.AVM_SERVICE = AVMService(data_dir=server_module.DATA_DIR, repository=repo)
    server_module.AVM_SERVICE_START_TIME = 0
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_receipts") as resp:
            receipts_body = json.loads(resp.read().decode("utf-8"))
        assert receipts_body["receipt_count"] == 1
        assert receipts_body["receipts"][0]["action"] == "manual_location_review"
        assert receipts_body["manual_review_control_plane_storage"]["state_source"] == "repository"

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_receipt_operations") as resp:
            operations_body = json.loads(resp.read().decode("utf-8"))
        assert operations_body["operation_count"] == 1
        assert operations_body["manual_review_control_plane_storage"]["state_source"] == "repository"

        assert repo.manual_review_control_plane_counts()["receipt_count"] == 1
        assert repo.manual_review_control_plane_counts()["operation_count"] == 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_module.AVM_SERVICE = original_service
        server_module.AVM_SERVICE_START_TIME = original_start_time


def test_http_status_can_surface_hybrid_collection_runtime_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-1", url="https://x/stage-http-hybrid-1"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:40:00",
                "runner_mode": "hybrid",
                "loop_mode": True,
                "submit_enabled": True,
                "session_id": "hybrid-live-ops",
                "decision_counts": {
                    "browserless_success": 3,
                    "browser_fallback_required": 2,
                },
                "reason_counts": {
                    "challenge_detected": 2,
                },
                "termination_reason": "fallback_escalation_threshold_reached",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
                "effective_mode_counts": {"hybrid": 1, "browser": 2},
                "guidance_applied_count": 2,
                "guidance_status": "investigate_challenge_spike",
                "guidance_recommended_mode": "browser",
                "last_decision": "browser_fallback_required",
                "last_reason": "challenge_detected",
                "last_task": {
                    "url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440112&page=7",
                    "page": 7,
                    "location_code": "440112",
                    "category": "50025969",
                },
                "last_probe_summary": {
                    "item_count": 0,
                    "has_script": False,
                    "body_has_login": False,
                    "body_has_captcha": False,
                    "body_has_punish": True,
                    "body_has_challenge": True,
                },
                "last_submit_result": {
                    "batch": {"status": "skipped", "new": 0},
                    "progress": {"status": "skipped"},
                },
                "last_browser_fallback_opened": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        hybrid_summary = body["collection_stage"]["hybrid_collection_runtime_summary"]
        assert hybrid_summary["runner_mode"] == "hybrid"
        assert hybrid_summary["loop_mode"] is True
        assert hybrid_summary["decision_counts"]["browserless_success"] == 3
        assert hybrid_summary["decision_counts"]["browser_fallback_required"] == 2
        assert hybrid_summary["browserless_success_count"] == 3
        assert hybrid_summary["browser_fallback_required_count"] == 2
        assert hybrid_summary["top_fallback_reason"] == "challenge_detected"
        assert hybrid_summary["last_decision"] == "browser_fallback_required"
        assert hybrid_summary["last_reason"] == "challenge_detected"
        assert hybrid_summary["requested_mode"] == "hybrid"
        assert hybrid_summary["last_effective_mode"] == "browser"
        assert hybrid_summary["operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert hybrid_summary["effective_mode_counts"]["browser"] == 2
        assert hybrid_summary["guidance_applied_count"] == 2
        assert hybrid_summary["guidance_status"] == "investigate_challenge_spike"
        assert hybrid_summary["last_task_page"] == 7
        assert hybrid_summary["last_task_location_code"] == "440112"
        assert hybrid_summary["last_probe_body_has_challenge"] is True
        assert hybrid_summary["last_probe_body_has_punish"] is True
        assert hybrid_summary["last_submit_batch_status"] == "skipped"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_last_decision"] == "browser_fallback_required"
        assert overview["hybrid_collection_top_fallback_reason"] == "challenge_detected"
        assert overview["hybrid_collection_last_effective_mode"] == "browser"
        assert overview["hybrid_collection_operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert overview["hybrid_collection_guidance_applied_count"] == 2
        assert overview["hybrid_collection_browserless_success_count"] == 3
        assert overview["hybrid_collection_browser_fallback_required_count"] == 2
        assert overview["hybrid_collection_last_task_page"] == 7
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_runtime_summary_treats_unknown_nested_payloads_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:40:00",
                "runner_mode": "hybrid",
                "decision_counts": "unknown",
                "reason_counts": "unknown",
                "effective_mode_counts": "unknown",
                "iterations": "unknown",
                "guidance_applied_count": "unknown",
                "last_task": "unknown",
                "last_probe_summary": "unknown",
                "last_submit_result": "unknown",
                "last_browser_fallback_opened": "unknown",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_summary(data_root)

    assert summary["available"] is True
    assert summary["decision_counts"] == {}
    assert summary["reason_counts"] == {}
    assert summary["effective_mode_counts"] == {}
    assert summary["iterations"] == 0
    assert summary["guidance_applied_count"] == 0
    assert summary["last_task_url"] is None
    assert summary["last_task_page"] is None
    assert summary["last_probe_item_count"] == 0
    assert summary["last_submit_batch_status"] is None
    assert summary["last_submit_batch_new"] == 0
    assert summary["last_submit_progress_status"] is None
    assert summary["last_browser_fallback_opened"] is False


def test_hybrid_collection_runtime_summary_treats_negative_numeric_scalars_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:40:00",
                "runner_mode": "hybrid",
                "iterations": -3,
                "guidance_applied_count": -2,
                "last_task": {"page": -7},
                "last_probe_summary": {"item_count": -4},
                "last_submit_result": {"batch": {"new": -5}},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_summary(data_root)

    assert summary["available"] is True
    assert summary["iterations"] == 0
    assert summary["guidance_applied_count"] == 0
    assert summary["last_task_page"] is None
    assert summary["last_probe_item_count"] == 0
    assert summary["last_submit_batch_new"] == 0


def test_hybrid_collection_runtime_summary_treats_unknown_count_keys_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:40:00",
                "runner_mode": "hybrid",
                "decision_counts": {"unknown": 4, "browserless_success": 2},
                "reason_counts": {"unknown": 3, "challenge_detected": 1},
                "effective_mode_counts": {"unknown": 5, "hybrid": 2},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_summary(data_root)

    assert summary["available"] is True
    assert summary["decision_counts"] == {"browserless_success": 2}
    assert summary["reason_counts"] == {"challenge_detected": 1}
    assert summary["effective_mode_counts"] == {"hybrid": 2}
    assert summary["top_fallback_reason"] == "challenge_detected"


def test_hybrid_collection_runtime_summary_treats_unknown_text_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "generated_at": "unknown",
                "runner_mode": "unknown",
                "requested_mode": "unknown",
                "effective_mode_source": "unknown",
                "session_id": "unknown",
                "top_fallback_reason": "unknown",
                "termination_reason": "unknown",
                "operator_action_hint": "unknown",
                "guidance_status": "unknown",
                "recovery_policy_status": "unknown",
                "last_decision": "unknown",
                "last_reason": "unknown",
                "last_effective_mode": "unknown",
                "last_task": {
                    "url": "unknown",
                    "location_code": "unknown",
                    "category": "unknown",
                },
                "last_submit_result": {
                    "batch": {"status": "unknown"},
                    "progress": {"status": "unknown"},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_summary(data_root)

    assert summary["generated_at"] is None
    assert summary["runner_mode"] is None
    assert summary["requested_mode"] is None
    assert summary["effective_mode_source"] is None
    assert summary["session_id"] is None
    assert summary["top_fallback_reason"] is None
    assert summary["termination_reason"] is None
    assert summary["operator_action_hint"] is None
    assert summary["guidance_status"] is None
    assert summary["recovery_policy_status"] is None
    assert summary["last_decision"] is None
    assert summary["last_reason"] is None
    assert summary["last_effective_mode"] is None
    assert summary["last_task_url"] is None
    assert summary["last_task_location_code"] is None
    assert summary["last_task_category"] is None
    assert summary["last_submit_batch_status"] is None
    assert summary["last_submit_progress_status"] is None


def test_http_status_can_surface_hybrid_collection_runtime_history_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-2", url="https://x/stage-http-hybrid-2"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:01:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "hist-1",
        },
        {
            "generated_at": "2026-05-18 18:02:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "stop_on_fallback",
            "session_id": "hist-2",
        },
        {
            "generated_at": "2026-05-18 18:03:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "hist-3",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        history_summary = body["collection_stage"]["hybrid_collection_runtime_history_summary"]
        assert history_summary["available"] is True
        assert history_summary["entry_count"] == 3
        assert history_summary["recent_runs"] == 3
        assert history_summary["recent_decision_counts"]["browserless_success"] == 2
        assert history_summary["recent_decision_counts"]["browser_fallback_required"] == 1
        assert history_summary["recent_browserless_success_count"] == 2
        assert history_summary["recent_browser_fallback_required_count"] == 1
        assert history_summary["recent_browserless_success_rate"] == pytest.approx(2 / 3)
        assert history_summary["recent_reason_counts"]["challenge_detected"] == 1
        assert history_summary["recent_top_fallback_reason"] == "challenge_detected"
        assert history_summary["recent_top_termination_reason"] == "max_runs_reached"
        assert history_summary["last_generated_at"] == "2026-05-18 18:03:00"
        assert history_summary["last_session_id"] == "hist-3"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_runs"] == 3
        assert overview["hybrid_collection_recent_browserless_success_count"] == 2
        assert overview["hybrid_collection_recent_browser_fallback_required_count"] == 1
        assert overview["hybrid_collection_recent_browserless_success_rate"] == pytest.approx(2 / 3)
        assert overview["hybrid_collection_recent_top_fallback_reason"] == "challenge_detected"
        assert overview["hybrid_collection_recent_top_termination_reason"] == "max_runs_reached"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_runtime_history_summary_treats_unknown_nested_payloads_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:01:00",
            "session_id": "hist-unknown-1",
            "decision_counts": "unknown",
            "reason_counts": "unknown",
            "termination_reason": "unknown",
        },
        {
            "generated_at": "unknown",
            "session_id": "unknown",
            "decision_counts": {"browserless_success": "unknown"},
            "reason_counts": {"challenge_detected": "unknown"},
            "termination_reason": "max_runs_reached",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_history_summary(data_root)

    assert summary["available"] is True
    assert summary["entry_count"] == 2
    assert summary["recent_runs"] == 2
    assert summary["recent_decision_counts"] == {}
    assert summary["recent_reason_counts"] == {}
    assert summary["recent_browserless_success_count"] == 0
    assert summary["recent_browser_fallback_required_count"] == 0
    assert summary["recent_browser_worker_dispatched_count"] == 0
    assert summary["recent_browserless_success_rate"] == 0.0
    assert summary["recent_top_fallback_reason"] is None
    assert summary["recent_top_termination_reason"] == "max_runs_reached"
    assert summary["last_generated_at"] is None
    assert summary["last_session_id"] is None


def test_hybrid_collection_runtime_history_summary_treats_unknown_count_keys_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:01:00",
            "session_id": "hist-key-1",
            "decision_counts": {"unknown": 5, "browserless_success": 2},
            "reason_counts": {"unknown": 4, "challenge_detected": 1},
            "termination_reason": "unknown",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_history_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_decision_counts"] == {"browserless_success": 2}
    assert summary["recent_reason_counts"] == {"challenge_detected": 1}
    assert summary["recent_browserless_success_count"] == 2
    assert summary["recent_top_fallback_reason"] == "challenge_detected"
    assert summary["recent_top_termination_reason"] is None


def test_hybrid_collection_runtime_history_summary_treats_whitespace_unknown_termination_reason_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:01:00",
            "session_id": "hist-term-1",
            "termination_reason": " unknown ",
        },
        {
            "generated_at": "2026-05-18 18:02:00",
            "session_id": "hist-term-2",
            "termination_reason": "max_runs_reached",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_history_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_top_termination_reason"] == "max_runs_reached"


def test_hybrid_collection_runtime_history_summary_treats_negative_counts_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:01:00",
            "session_id": "hist-neg-1",
            "decision_counts": {"browserless_success": -2, "browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": -3, "captcha_detected": 2},
            "termination_reason": "max_runs_reached",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_runtime_history_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_decision_counts"] == {"browser_fallback_required": 1}
    assert summary["recent_reason_counts"] == {"captcha_detected": 2}
    assert summary["recent_browserless_success_count"] == 0
    assert summary["recent_browser_fallback_required_count"] == 1
    assert summary["recent_browserless_success_rate"] == 0.0
    assert summary["recent_top_fallback_reason"] == "captcha_detected"


def test_hybrid_collection_strategy_guidance_treats_unknown_history_available_as_missing():
    server_module = importlib.import_module("src.server")

    guidance = server_module._hybrid_collection_strategy_guidance(
        {},
        {"available": "unknown"},
    )

    assert guidance == {
        "guidance_status": "no_history_available",
        "priority": "info",
        "recommended_mode": "hybrid",
        "recommended_actions": ["collect_more_hybrid_runtime_history"],
        "top_guidance_reason": "history_unavailable",
    }


def test_hybrid_collection_strategy_guidance_treats_unknown_history_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    guidance = server_module._hybrid_collection_strategy_guidance(
        {},
        {
            "available": True,
            "recent_runs": "unknown",
            "recent_browserless_success_rate": "unknown",
            "recent_browser_fallback_required_count": "unknown",
            "recent_top_fallback_reason": "unknown",
            "recent_top_termination_reason": "unknown",
        },
    )

    assert guidance == {
        "guidance_status": "insufficient_history",
        "priority": "info",
        "recommended_mode": "hybrid",
        "recommended_actions": ["collect_more_hybrid_runtime_history"],
        "top_guidance_reason": "insufficient_history",
    }


def test_http_status_can_surface_hybrid_collection_action_hint_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-22", url="https://x/stage-http-hybrid-22"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:11:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_worker_dispatched": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "operator_escalation",
            "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "session_id": "hint-trend-1",
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "operator_action_hint": "continue hybrid with budget watch; suggested mode=hybrid",
            "session_id": "hint-trend-2",
        },
        {
            "generated_at": "2026-05-18 18:13:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "operator_action_hint": "continue hybrid with budget watch; suggested mode=hybrid",
            "session_id": "hint-trend-3",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        trend_summary = body["collection_stage"]["hybrid_collection_action_hint_trend_summary"]
        assert trend_summary["available"] is True
        assert trend_summary["recent_hint_entry_count"] == 3
        assert trend_summary["recent_action_hint_counts"] == {
            "inspect unresolved high-priority backlog; suggested mode=browser": 1,
            "continue hybrid with budget watch; suggested mode=hybrid": 2,
        }
        assert trend_summary["recent_distinct_action_hint_count"] == 2
        assert trend_summary["recent_change_count"] == 1
        assert trend_summary["top_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert trend_summary["current_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert trend_summary["previous_distinct_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert trend_summary["last_change_at"] == "2026-05-18 18:12:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_current_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert overview["hybrid_collection_previous_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert overview["hybrid_collection_action_hint_change_count"] == 1
        assert overview["hybrid_collection_action_hint_last_changed_at"] == "2026-05-18 18:12:00"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_action_hint_trend_summary_treats_unknown_hints_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:11:00",
            "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "session_id": "hint-unknown-1",
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "operator_action_hint": "unknown",
            "session_id": "hint-unknown-2",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_action_hint_trend_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_hint_entry_count"] == 1
    assert summary["recent_action_hint_counts"] == {
        "inspect unresolved high-priority backlog; suggested mode=browser": 1,
    }
    assert summary["recent_distinct_action_hint_count"] == 1
    assert summary["recent_change_count"] == 0
    assert summary["top_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
    assert summary["current_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
    assert summary["previous_distinct_action_hint"] is None
    assert summary["last_change_at"] is None


def test_hybrid_collection_trend_summaries_treat_unknown_change_timestamps_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    runtime_history_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:10:00",
                        "session_id": "trend-ts-1",
                        "operator_action_hint": "keep hybrid; suggested mode=hybrid",
                        "operator_final_guidance_label": "Stable ready state",
                        "operator_final_guidance_priority": "info",
                        "operator_final_guidance_message": "Stable ready state: keep hybrid and continue monitoring.",
                        "operator_digest_status": "ready",
                        "operator_digest_priority": "info",
                        "operator_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
                        "intervention_status": "ready",
                        "intervention_priority": "info",
                        "intervention_reason": "browserless_fast_path_stable",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "trend-ts-2",
                        "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
                        "operator_final_guidance_label": "Escalating intervention",
                        "operator_final_guidance_priority": "high",
                        "operator_final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                        "operator_digest_status": "intervention_required",
                        "operator_digest_priority": "high",
                        "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                        "intervention_status": "intervention_required",
                        "intervention_priority": "high",
                        "intervention_reason": "high_priority_unresolved_escalation_backlog",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    escalation_events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:10:00",
                        "session_id": "trend-ts-esc-1",
                        "operator_escalation_source": "recovery_policy",
                        "escalation_kind": "repeated_repin_cycle",
                        "operator_escalation_audit_message": "Persistent intervention required [source=recovery_policy]",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "trend-ts-esc-2",
                        "operator_escalation_source": "intervention_stability",
                        "escalation_kind": "intervention_stability",
                        "operator_escalation_audit_message": "Escalating intervention [source=intervention_stability]",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    action_hint_summary = server_module._hybrid_collection_action_hint_trend_summary(data_root)
    final_guidance_summary = server_module._hybrid_collection_operator_final_guidance_trend_summary(data_root)
    digest_summary = server_module._hybrid_collection_operator_digest_trend_summary(data_root)
    intervention_summary = server_module._hybrid_collection_operator_intervention_trend_summary(data_root)
    escalation_summary = server_module._hybrid_collection_operator_escalation_event_trend_summary(data_root)

    assert action_hint_summary["recent_change_count"] == 1
    assert action_hint_summary["last_change_at"] is None
    assert final_guidance_summary["recent_change_count"] == 1
    assert final_guidance_summary["last_change_at"] is None
    assert digest_summary["recent_change_count"] == 1
    assert digest_summary["last_change_at"] is None
    assert intervention_summary["recent_change_count"] == 1
    assert intervention_summary["last_change_at"] is None
    assert escalation_summary["recent_source_change_count"] == 1
    assert escalation_summary["last_source_change_at"] is None


def test_http_status_can_surface_hybrid_collection_operator_intervention_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16b", url="https://x/stage-http-hybrid-16b"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:10:00",
            "session_id": "intervention-trend-1",
            "operator_action_hint": "keep hybrid; suggested mode=hybrid",
            "intervention_status": "ready",
            "intervention_priority": "info",
            "intervention_reason": "browserless_fast_path_stable",
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "intervention-trend-2",
            "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "intervention_status": "intervention_required",
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
        },
        {
            "generated_at": "2026-05-18 18:13:00",
            "session_id": "intervention-trend-3",
            "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "intervention_status": "intervention_required",
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
        },
    ]
    runtime_history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        trend_summary = body["collection_stage"]["hybrid_collection_operator_intervention_trend_summary"]
        assert trend_summary["available"] is True
        assert trend_summary["recent_status_entry_count"] == 3
        assert trend_summary["recent_intervention_status_counts"] == {
            "ready": 1,
            "intervention_required": 2,
        }
        assert trend_summary["recent_distinct_intervention_status_count"] == 2
        assert trend_summary["recent_change_count"] == 1
        assert trend_summary["top_intervention_status"] == "intervention_required"
        assert trend_summary["current_intervention_status"] == "intervention_required"
        assert trend_summary["current_intervention_priority"] == "high"
        assert trend_summary["current_intervention_reason"] == "high_priority_unresolved_escalation_backlog"
        assert trend_summary["previous_distinct_intervention_status"] == "ready"
        assert trend_summary["last_change_at"] == "2026-05-18 18:12:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_current_intervention_status"] == "intervention_required"
        assert overview["hybrid_collection_current_intervention_priority"] == "high"
        assert overview["hybrid_collection_current_intervention_reason"] == "high_priority_unresolved_escalation_backlog"
        assert overview["hybrid_collection_previous_intervention_status"] == "ready"
        assert overview["hybrid_collection_intervention_change_count"] == 1
        assert overview["hybrid_collection_intervention_last_changed_at"] == "2026-05-18 18:12:00"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_operator_intervention_trend_summary_treats_unknown_status_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:11:00",
            "session_id": "intervention-unknown-1",
            "intervention_status": "ready",
            "intervention_priority": "info",
            "intervention_reason": "browserless_fast_path_stable",
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "intervention-unknown-2",
            "intervention_status": "unknown",
            "intervention_priority": "unknown",
            "intervention_reason": "unknown",
        },
    ]
    runtime_history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    trend_summary = server_module._hybrid_collection_operator_intervention_trend_summary(data_root)

    assert trend_summary["available"] is True
    assert trend_summary["recent_status_entry_count"] == 1
    assert trend_summary["recent_intervention_status_counts"] == {"ready": 1}
    assert trend_summary["recent_distinct_intervention_status_count"] == 1
    assert trend_summary["recent_change_count"] == 0
    assert trend_summary["top_intervention_status"] == "ready"
    assert trend_summary["current_intervention_status"] == "ready"
    assert trend_summary["current_intervention_priority"] == "info"
    assert trend_summary["current_intervention_reason"] == "browserless_fast_path_stable"
    assert trend_summary["previous_distinct_intervention_status"] is None
    assert trend_summary["last_change_at"] is None


def test_hybrid_collection_operator_intervention_trend_summary_treats_unknown_priority_and_reason_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    runtime_history_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:11:00",
                        "session_id": "intervention-unknown-priority-1",
                        "intervention_status": "ready",
                        "intervention_priority": "unknown",
                        "intervention_reason": "unknown",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:12:00",
                        "session_id": "intervention-unknown-priority-2",
                        "intervention_status": "unknown",
                        "intervention_priority": "unknown",
                        "intervention_reason": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trend_summary = server_module._hybrid_collection_operator_intervention_trend_summary(data_root)

    assert trend_summary["available"] is True
    assert trend_summary["recent_status_entry_count"] == 1
    assert trend_summary["recent_intervention_status_counts"] == {"ready": 1}
    assert trend_summary["recent_distinct_intervention_status_count"] == 1
    assert trend_summary["recent_change_count"] == 0
    assert trend_summary["top_intervention_status"] == "ready"
    assert trend_summary["current_intervention_status"] == "ready"
    assert trend_summary["current_intervention_priority"] is None
    assert trend_summary["current_intervention_reason"] is None
    assert trend_summary["previous_distinct_intervention_status"] is None
    assert trend_summary["last_change_at"] is None


def test_http_status_can_surface_hybrid_collection_operator_final_guidance_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16f", url="https://x/stage-http-hybrid-16f"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    transitioning_message = "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    history_entries = [
        {
            "generated_at": "2026-05-18 18:10:00",
            "session_id": "final-guidance-trend-1",
            "operator_final_guidance_label": "Stable ready state",
            "operator_final_guidance_priority": "info",
            "operator_final_guidance_message": stable_message,
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "final-guidance-trend-2",
            "operator_final_guidance_label": "Transitioning intervention",
            "operator_final_guidance_priority": "warning",
            "operator_final_guidance_message": transitioning_message,
        },
        {
            "generated_at": "2026-05-18 18:13:00",
            "session_id": "final-guidance-trend-3",
            "operator_final_guidance_label": "Transitioning intervention",
            "operator_final_guidance_priority": "warning",
            "operator_final_guidance_message": transitioning_message,
        },
    ]
    runtime_history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        trend_summary = body["collection_stage"]["hybrid_collection_operator_final_guidance_trend_summary"]
        assert trend_summary["available"] is True
        assert trend_summary["recent_guidance_entry_count"] == 3
        assert trend_summary["recent_guidance_message_counts"] == {
            stable_message: 1,
            transitioning_message: 2,
        }
        assert trend_summary["recent_distinct_guidance_message_count"] == 2
        assert trend_summary["recent_change_count"] == 1
        assert trend_summary["top_guidance_message"] == transitioning_message
        assert trend_summary["current_guidance_label"] == "Transitioning intervention"
        assert trend_summary["current_guidance_priority"] == "warning"
        assert trend_summary["current_guidance_message"] == transitioning_message
        assert trend_summary["previous_distinct_guidance_message"] == stable_message
        assert trend_summary["last_change_at"] == "2026-05-18 18:12:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_current_final_guidance_label"] == "Transitioning intervention"
        assert overview["hybrid_collection_current_final_guidance_priority"] == "warning"
        assert overview["hybrid_collection_current_final_guidance_message"] == transitioning_message
        assert overview["hybrid_collection_previous_final_guidance_message"] == stable_message
        assert overview["hybrid_collection_final_guidance_change_count"] == 1
        assert overview["hybrid_collection_final_guidance_last_changed_at"] == "2026-05-18 18:12:00"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_operator_final_guidance_trend_summary_treats_unknown_messages_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    history_entries = [
        {
            "generated_at": "2026-05-18 18:10:00",
            "session_id": "final-guidance-unknown-1",
            "operator_final_guidance_label": "Stable ready state",
            "operator_final_guidance_priority": "info",
            "operator_final_guidance_message": stable_message,
        },
        {
            "generated_at": "2026-05-18 18:11:00",
            "session_id": "final-guidance-unknown-2",
            "operator_final_guidance_label": "unknown",
            "operator_final_guidance_priority": "unknown",
            "operator_final_guidance_message": "unknown",
        },
    ]
    runtime_history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    trend_summary = server_module._hybrid_collection_operator_final_guidance_trend_summary(data_root)

    assert trend_summary["available"] is True
    assert trend_summary["recent_guidance_entry_count"] == 1
    assert trend_summary["recent_guidance_message_counts"] == {stable_message: 1}
    assert trend_summary["recent_distinct_guidance_message_count"] == 1
    assert trend_summary["recent_change_count"] == 0
    assert trend_summary["top_guidance_message"] == stable_message
    assert trend_summary["current_guidance_label"] == "Stable ready state"
    assert trend_summary["current_guidance_priority"] == "info"
    assert trend_summary["current_guidance_message"] == stable_message
    assert trend_summary["previous_distinct_guidance_label"] is None
    assert trend_summary["previous_distinct_guidance_message"] is None
    assert trend_summary["last_change_at"] is None


def test_hybrid_collection_operator_final_guidance_trend_summary_treats_unknown_label_and_priority_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    runtime_history_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:10:00",
                        "session_id": "final-guidance-unknown-meta-1",
                        "operator_final_guidance_label": "unknown",
                        "operator_final_guidance_priority": "unknown",
                        "operator_final_guidance_message": stable_message,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:11:00",
                        "session_id": "final-guidance-unknown-meta-2",
                        "operator_final_guidance_label": "unknown",
                        "operator_final_guidance_priority": "unknown",
                        "operator_final_guidance_message": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trend_summary = server_module._hybrid_collection_operator_final_guidance_trend_summary(data_root)

    assert trend_summary["available"] is True
    assert trend_summary["recent_guidance_entry_count"] == 1
    assert trend_summary["recent_guidance_message_counts"] == {stable_message: 1}
    assert trend_summary["recent_distinct_guidance_message_count"] == 1
    assert trend_summary["recent_change_count"] == 0
    assert trend_summary["top_guidance_message"] == stable_message
    assert trend_summary["current_guidance_label"] is None
    assert trend_summary["current_guidance_priority"] is None
    assert trend_summary["current_guidance_message"] == stable_message
    assert trend_summary["previous_distinct_guidance_label"] is None
    assert trend_summary["previous_distinct_guidance_message"] is None
    assert trend_summary["last_change_at"] is None


def test_hybrid_collection_operator_final_guidance_stability_summary_treats_unknown_summary_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_stability_summary("unknown")

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_guidance_label": None,
        "current_guidance_priority": None,
        "current_guidance_message": None,
        "previous_guidance_message": None,
        "recent_change_count": 0,
        "last_change_at": None,
        "operator_readable_explanation": None,
    }


def test_hybrid_collection_operator_final_guidance_stability_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_stability_summary(
        {"available": "unknown"}
    )

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_guidance_label": None,
        "current_guidance_priority": None,
        "current_guidance_message": None,
        "previous_guidance_message": None,
        "recent_change_count": 0,
        "last_change_at": None,
        "operator_readable_explanation": None,
    }


def test_hybrid_collection_operator_digest_stability_summary_treats_unknown_summary_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_stability_summary("unknown")

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_digest_status": None,
        "current_digest_priority": None,
        "current_digest_message": None,
        "previous_digest_status": None,
        "previous_digest_message": None,
        "recent_change_count": 0,
        "last_change_at": None,
        "operator_readable_explanation": None,
    }


def test_hybrid_collection_operator_digest_stability_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_stability_summary(
        {"available": "unknown"}
    )

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_digest_status": None,
        "current_digest_priority": None,
        "current_digest_message": None,
        "previous_digest_status": None,
        "previous_digest_message": None,
        "recent_change_count": 0,
        "last_change_at": None,
        "operator_readable_explanation": None,
    }


def test_hybrid_collection_operator_final_guidance_stability_summary_treats_unknown_scalar_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_stability_summary(
        {
            "available": True,
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "unknown",
            "current_guidance_message": "unknown",
            "previous_distinct_guidance_label": "unknown",
            "previous_distinct_guidance_message": "unknown",
            "recent_change_count": 0,
            "last_change_at": "2026-05-18 18:20:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "stable_guidance"
    assert summary["stability_severity"] == "info"
    assert summary["current_guidance_label"] == "Stable ready state"
    assert summary["current_guidance_priority"] == "info"
    assert summary["current_guidance_message"] is None
    assert summary["previous_guidance_message"] is None
    assert summary["recent_change_count"] == 0
    assert summary["last_change_at"] == "2026-05-18 18:20:00"
    assert summary["operator_readable_explanation"] == "Final guidance remains stable with no recent message changes."


def test_hybrid_collection_operator_final_guidance_stability_summary_treats_missing_current_label_with_recent_change_as_transitioning():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_stability_summary(
        {
            "available": True,
            "current_guidance_label": "unknown",
            "current_guidance_priority": "warning",
            "current_guidance_message": "unknown",
            "previous_distinct_guidance_label": "Stable ready state",
            "previous_distinct_guidance_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:20:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "guidance_transitioning"
    assert summary["stability_severity"] == "warning"
    assert summary["current_guidance_label"] is None
    assert summary["current_guidance_priority"] == "warning"
    assert summary["current_guidance_message"] is None
    assert summary["previous_guidance_message"] == "Stable ready state: keep hybrid and continue monitoring."
    assert summary["recent_change_count"] == 1
    assert summary["last_change_at"] == "2026-05-18 18:20:00"
    assert summary["operator_readable_explanation"] == "Final guidance is transitioning."


def test_hybrid_collection_operator_digest_stability_summary_treats_unknown_scalar_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_stability_summary(
        {
            "available": True,
            "current_digest_status": "ready",
            "current_digest_priority": "unknown",
            "current_digest_message": "unknown",
            "previous_distinct_digest_status": "unknown",
            "previous_distinct_digest_message": "unknown",
            "recent_change_count": 0,
            "last_change_at": "2026-05-18 18:21:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "stable_digest"
    assert summary["stability_severity"] == "info"
    assert summary["current_digest_status"] == "ready"
    assert summary["current_digest_priority"] == "info"
    assert summary["current_digest_message"] is None
    assert summary["previous_digest_status"] is None
    assert summary["previous_digest_message"] is None
    assert summary["recent_change_count"] == 0
    assert summary["last_change_at"] == "2026-05-18 18:21:00"
    assert summary["operator_readable_explanation"] == "Operator digest remains stable with no recent message changes."


def test_hybrid_collection_operator_digest_stability_summary_treats_missing_current_status_with_recent_change_as_transitioning():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_stability_summary(
        {
            "available": True,
            "current_digest_status": "unknown",
            "current_digest_priority": "warning",
            "current_digest_message": "unknown",
            "previous_distinct_digest_status": "ready",
            "previous_distinct_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:22:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "digest_transitioning"
    assert summary["stability_severity"] == "warning"
    assert summary["current_digest_status"] is None
    assert summary["current_digest_priority"] == "warning"
    assert summary["current_digest_message"] is None
    assert summary["previous_digest_status"] == "ready"
    assert summary["previous_digest_message"] == "Stable ready state: keep hybrid and continue monitoring."
    assert summary["recent_change_count"] == 1
    assert summary["last_change_at"] == "2026-05-18 18:22:00"
    assert summary["operator_readable_explanation"] == "Operator digest is transitioning."


def test_hybrid_collection_stability_summaries_treat_unknown_change_timestamps_as_missing():
    server_module = importlib.import_module("src.server")

    final_guidance = server_module._hybrid_collection_operator_final_guidance_stability_summary(
        {
            "available": True,
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "info",
            "current_guidance_message": "All clear",
            "previous_distinct_guidance_label": "unknown",
            "previous_distinct_guidance_message": "unknown",
            "recent_change_count": 0,
            "last_change_at": "unknown",
        }
    )
    assert final_guidance["last_change_at"] is None

    digest = server_module._hybrid_collection_operator_digest_stability_summary(
        {
            "available": True,
            "current_digest_status": "ready",
            "current_digest_priority": "info",
            "current_digest_message": "All clear",
            "previous_distinct_digest_status": "unknown",
            "previous_distinct_digest_message": "unknown",
            "recent_change_count": 0,
            "last_change_at": "unknown",
        }
    )
    assert digest["last_change_at"] is None

    intervention = server_module._hybrid_collection_operator_intervention_stability_summary(
        {
            "available": True,
            "current_intervention_status": "ready",
            "previous_distinct_intervention_status": "unknown",
            "recent_change_count": 0,
            "last_change_at": "unknown",
        }
    )
    assert intervention["last_change_at"] is None

    escalation = server_module._hybrid_collection_operator_escalation_event_stability_summary(
        {
            "available": True,
            "current_operator_escalation_source": "recovery_policy",
            "current_escalation_kind": "policy",
            "current_operator_escalation_audit_message": "watch",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": 0,
            "last_source_change_at": "unknown",
        }
    )
    assert escalation["last_source_change_at"] is None


def test_hybrid_collection_stability_summaries_treat_negative_change_counts_as_missing():
    server_module = importlib.import_module("src.server")

    final_guidance = server_module._hybrid_collection_operator_final_guidance_stability_summary(
        {
            "available": True,
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "info",
            "current_guidance_message": "All clear",
            "previous_distinct_guidance_label": "unknown",
            "previous_distinct_guidance_message": "unknown",
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:20:00",
        }
    )
    assert final_guidance["recent_change_count"] == 0
    assert final_guidance["stability_status"] == "stable_guidance"

    digest = server_module._hybrid_collection_operator_digest_stability_summary(
        {
            "available": True,
            "current_digest_status": "ready",
            "current_digest_priority": "info",
            "current_digest_message": "All clear",
            "previous_distinct_digest_status": "unknown",
            "previous_distinct_digest_message": "unknown",
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:21:00",
        }
    )
    assert digest["recent_change_count"] == 0
    assert digest["stability_status"] == "stable_digest"

    intervention = server_module._hybrid_collection_operator_intervention_stability_summary(
        {
            "available": True,
            "current_intervention_status": "ready",
            "previous_distinct_intervention_status": "unknown",
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:22:00",
        }
    )
    assert intervention["recent_change_count"] == 0
    assert intervention["stability_status"] == "stable_ready"

    escalation = server_module._hybrid_collection_operator_escalation_event_stability_summary(
        {
            "available": True,
            "current_operator_escalation_source": "recovery_policy",
            "current_escalation_kind": "policy",
            "current_operator_escalation_audit_message": "watch",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": -1,
            "last_source_change_at": "2026-05-18 18:23:00",
        }
    )
    assert escalation["recent_source_change_count"] == 0
    assert escalation["stability_status"] == "persistent_recovery_policy_source"


def test_hybrid_collection_operator_escalation_event_stability_summary_treats_unknown_summary_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_escalation_event_stability_summary("unknown")

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_operator_escalation_source": None,
        "current_escalation_kind": None,
        "current_operator_escalation_audit_message": None,
        "previous_operator_escalation_source": None,
        "recent_source_change_count": 0,
        "last_source_change_at": None,
        "operator_readable_explanation": None,
    }


def test_hybrid_collection_operator_escalation_event_stability_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_escalation_event_stability_summary(
        {"available": "unknown"}
    )

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_operator_escalation_source": None,
        "current_escalation_kind": None,
        "current_operator_escalation_audit_message": None,
        "previous_operator_escalation_source": None,
        "recent_source_change_count": 0,
        "last_source_change_at": None,
        "operator_readable_explanation": None,
    }


def test_hybrid_collection_operator_escalation_event_stability_summary_treats_unknown_scalar_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_escalation_event_stability_summary(
        {
            "available": True,
            "current_operator_escalation_source": "unknown",
            "current_escalation_kind": "unknown",
            "current_operator_escalation_audit_message": "unknown",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": 0,
            "last_source_change_at": "2026-05-18 18:22:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "source_transitioning"
    assert summary["stability_severity"] == "warning"
    assert summary["current_operator_escalation_source"] is None
    assert summary["current_escalation_kind"] is None
    assert summary["current_operator_escalation_audit_message"] is None
    assert summary["previous_operator_escalation_source"] is None
    assert summary["recent_source_change_count"] == 0
    assert summary["last_source_change_at"] == "2026-05-18 18:22:00"
    assert summary["operator_readable_explanation"] == "Operator escalation source is transitioning."


def test_hybrid_collection_operator_escalation_event_stability_summary_treats_missing_current_source_with_recent_change_as_transitioning():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_escalation_event_stability_summary(
        {
            "available": True,
            "current_operator_escalation_source": "unknown",
            "current_escalation_kind": "unknown",
            "current_operator_escalation_audit_message": "unknown",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "source_transitioning"
    assert summary["stability_severity"] == "warning"
    assert summary["current_operator_escalation_source"] is None
    assert summary["current_escalation_kind"] is None
    assert summary["current_operator_escalation_audit_message"] is None
    assert summary["previous_operator_escalation_source"] == "recovery_policy"
    assert summary["recent_source_change_count"] == 1
    assert summary["last_source_change_at"] == "2026-05-18 18:24:00"
    assert summary["operator_readable_explanation"] == "Operator escalation source is transitioning."


def test_hybrid_collection_operator_intervention_policy_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        "unknown",
        "unknown",
        "unknown",
        "unknown",
    )

    assert summary == {
        "available": False,
        "intervention_status": "unknown",
        "intervention_required": False,
        "intervention_priority": "info",
        "intervention_reason": "no_runtime_signals",
        "preferred_operator_action_hint": None,
        "suggested_mode": None,
        "lifecycle_state": None,
        "window_open": False,
        "active_high_priority_unresolved_count": 0,
        "hint_consistency_status": None,
        "hint_consistency_severity": None,
        "resolution_trend_available": False,
        "recent_unresolved_count": 0,
        "recent_resolution_rate": 0.0,
        "recovery_latency_available": False,
        "last_recovery_latency_minutes": None,
    }


def test_hybrid_collection_operator_intervention_policy_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        {"available": "unknown"},
        {"available": "unknown"},
        {},
        {},
    )

    assert summary == {
        "available": False,
        "intervention_status": "unknown",
        "intervention_required": False,
        "intervention_priority": "info",
        "intervention_reason": "no_runtime_signals",
        "preferred_operator_action_hint": None,
        "suggested_mode": None,
        "lifecycle_state": None,
        "window_open": False,
        "active_high_priority_unresolved_count": 0,
        "hint_consistency_status": None,
        "hint_consistency_severity": None,
        "resolution_trend_available": False,
        "recent_unresolved_count": 0,
        "recent_resolution_rate": 0.0,
        "recovery_latency_available": False,
        "last_recovery_latency_minutes": None,
    }


def test_hybrid_collection_operator_intervention_policy_summary_treats_unknown_resolution_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        {
            "available": True,
            "lifecycle_state": "steady",
            "lifecycle_reason": "browserless_fast_path_stable",
            "priority_hint": "no_active_priority_backlog",
            "active_high_priority_unresolved_count": "unknown",
            "suggested_mode": "hybrid",
            "window_open": "unknown",
        },
        {
            "available": True,
        },
        {
            "available": "unknown",
            "recent_unresolved_count": "unknown",
            "recent_resolution_rate": "unknown",
        },
        {
            "available": "unknown",
            "last_recovery_latency_minutes": "unknown",
        },
    )

    assert summary["available"] is True
    assert summary["intervention_status"] == "ready"
    assert summary["intervention_required"] is False
    assert summary["intervention_priority"] == "info"
    assert summary["intervention_reason"] == "browserless_fast_path_stable"
    assert summary["preferred_operator_action_hint"] is None
    assert summary["suggested_mode"] == "hybrid"
    assert summary["lifecycle_state"] == "steady"
    assert summary["window_open"] is False
    assert summary["active_high_priority_unresolved_count"] == 0
    assert summary["hint_consistency_status"] is None
    assert summary["hint_consistency_severity"] is None
    assert summary["resolution_trend_available"] is False
    assert summary["recent_unresolved_count"] == 0
    assert summary["recent_resolution_rate"] == 0.0
    assert summary["recovery_latency_available"] is False
    assert summary["last_recovery_latency_minutes"] is None


def test_hybrid_collection_operator_intervention_policy_summary_treats_unknown_lifecycle_hint_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        {
            "available": True,
            "lifecycle_state": "steady",
            "lifecycle_reason": "unknown",
            "priority_hint": "unknown",
            "active_high_priority_unresolved_count": 0,
            "suggested_mode": "unknown",
            "window_open": False,
        },
        {
            "available": True,
            "preferred_operator_action_hint": "unknown",
            "consistency_status": "unknown",
            "consistency_severity": "unknown",
        },
        {},
        {
            "available": True,
            "last_recovery_latency_minutes": "unknown",
        },
    )

    assert summary["available"] is True
    assert summary["intervention_status"] == "ready"
    assert summary["intervention_required"] is False
    assert summary["intervention_priority"] == "info"
    assert summary["intervention_reason"] == "browserless_fast_path_stable"
    assert summary["preferred_operator_action_hint"] is None
    assert summary["suggested_mode"] == "hybrid"
    assert summary["lifecycle_state"] == "steady"
    assert summary["window_open"] is False
    assert summary["active_high_priority_unresolved_count"] == 0
    assert summary["hint_consistency_status"] is None
    assert summary["hint_consistency_severity"] is None
    assert summary["resolution_trend_available"] is False
    assert summary["recent_unresolved_count"] == 0
    assert summary["recent_resolution_rate"] == 0.0
    assert summary["recovery_latency_available"] is True
    assert summary["last_recovery_latency_minutes"] is None


def test_hybrid_collection_operator_intervention_policy_summary_treats_negative_resolution_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        {
            "available": True,
            "lifecycle_state": "steady",
            "lifecycle_reason": "browserless_fast_path_stable",
            "priority_hint": "no_active_priority_backlog",
            "active_high_priority_unresolved_count": -2,
            "suggested_mode": "hybrid",
            "window_open": False,
        },
        {
            "available": True,
        },
        {
            "available": True,
            "recent_unresolved_count": -3,
            "recent_resolution_rate": -0.5,
        },
        {
            "available": True,
            "last_recovery_latency_minutes": -1.5,
        },
    )

    assert summary["available"] is True
    assert summary["intervention_status"] == "ready"
    assert summary["intervention_required"] is False
    assert summary["intervention_priority"] == "info"
    assert summary["intervention_reason"] == "browserless_fast_path_stable"
    assert summary["active_high_priority_unresolved_count"] == 0
    assert summary["recent_unresolved_count"] == 0
    assert summary["recent_resolution_rate"] == 0.0
    assert summary["last_recovery_latency_minutes"] is None


def test_hybrid_collection_operator_intervention_policy_summary_treats_overfull_resolution_rate_as_clamped():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        {
            "available": True,
            "lifecycle_state": "steady",
            "lifecycle_reason": "browserless_fast_path_stable",
            "priority_hint": "no_active_priority_backlog",
            "active_high_priority_unresolved_count": 0,
            "suggested_mode": "hybrid",
            "window_open": False,
        },
        {
            "available": True,
        },
        {
            "available": True,
            "recent_unresolved_count": 0,
            "recent_resolution_rate": 1.5,
        },
        {
            "available": True,
        },
    )

    assert summary["available"] is True
    assert summary["intervention_status"] == "ready"
    assert summary["recent_resolution_rate"] == 1.0


def test_hybrid_collection_operator_intervention_stability_summary_treats_unknown_summary_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_stability_summary("unknown")

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_intervention_status": None,
        "previous_intervention_status": None,
        "recent_change_count": 0,
        "last_change_at": None,
        "operator_readable_explanation": None,
        "stability_action_hint": None,
    }


def test_hybrid_collection_operator_intervention_stability_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_stability_summary(
        {"available": "unknown"}
    )

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_intervention_status": None,
        "previous_intervention_status": None,
        "recent_change_count": 0,
        "last_change_at": None,
        "operator_readable_explanation": None,
        "stability_action_hint": None,
    }


def test_hybrid_collection_operator_intervention_stability_summary_treats_unknown_scalar_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_stability_summary(
        {
            "available": True,
            "current_intervention_status": "unknown",
            "previous_distinct_intervention_status": "unknown",
            "recent_change_count": 0,
            "last_change_at": "2026-05-18 18:23:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "transitioning"
    assert summary["stability_severity"] == "warning"
    assert summary["current_intervention_status"] is None
    assert summary["previous_intervention_status"] is None
    assert summary["recent_change_count"] == 0
    assert summary["last_change_at"] == "2026-05-18 18:23:00"
    assert summary["operator_readable_explanation"] == "Intervention is transitioning."
    assert summary["stability_action_hint"] == "monitor until stable before resuming aggressive intervention"


def test_hybrid_collection_operator_final_guidance_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_summary("unknown", "unknown")

    assert summary == {
        "available": False,
        "guidance_label": None,
        "guidance_priority": None,
        "guidance_message": None,
        "preferred_action_hint": None,
        "suggested_mode": None,
        "intervention_status": None,
        "stability_status": None,
    }


def test_hybrid_collection_operator_final_guidance_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_summary(
        {"available": "unknown"},
        {"available": "unknown"},
    )

    assert summary == {
        "available": False,
        "guidance_label": None,
        "guidance_priority": None,
        "guidance_message": None,
        "preferred_action_hint": None,
        "suggested_mode": None,
        "intervention_status": None,
        "stability_status": None,
    }


def test_hybrid_collection_operator_digest_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_summary(
        "unknown",
        "unknown",
        "unknown",
        "unknown",
    )

    assert summary == {
        "available": False,
        "digest_status": "unknown",
        "digest_priority": "info",
        "final_guidance_message": None,
        "intervention_status": None,
        "intervention_stability_status": None,
        "final_guidance_stability_status": None,
        "operator_digest_message": None,
    }


def test_hybrid_collection_operator_digest_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_summary(
        {"available": "unknown"},
        {"available": "unknown"},
        {"available": "unknown"},
        {"available": "unknown"},
    )

    assert summary == {
        "available": False,
        "digest_status": "unknown",
        "digest_priority": "info",
        "final_guidance_message": None,
        "intervention_status": None,
        "intervention_stability_status": None,
        "final_guidance_stability_status": None,
        "operator_digest_message": None,
    }


def test_hybrid_collection_unresolved_escalation_window_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_unresolved_escalation_window_summary("unknown", "unknown")

    assert summary == {
        "available": False,
        "window_status": "no_escalation_history",
        "window_open": False,
        "last_escalation_at": None,
        "last_escalation_policy_status": None,
        "last_recovery_at": None,
        "last_recovery_to_policy_status": None,
        "current_window_duration_seconds": None,
        "current_window_duration_minutes": None,
    }


def test_hybrid_collection_unresolved_escalation_window_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_unresolved_escalation_window_summary(
        {"available": "unknown"},
        {"available": "unknown"},
    )

    assert summary == {
        "available": False,
        "window_status": "no_escalation_history",
        "window_open": False,
        "last_escalation_at": None,
        "last_escalation_policy_status": None,
        "last_recovery_at": None,
        "last_recovery_to_policy_status": None,
        "current_window_duration_seconds": None,
        "current_window_duration_minutes": None,
    }


def test_hybrid_collection_escalation_resolution_trend_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_escalation_resolution_trend_summary(
        "unknown",
        "unknown",
        "unknown",
    )

    assert summary == {
        "available": False,
        "recent_escalation_count": 0,
        "recent_recovery_count": 0,
        "recent_resolved_count": 0,
        "recent_unresolved_count": 0,
        "recent_resolution_rate": 0.0,
        "window_open": False,
    }


def test_hybrid_collection_escalation_resolution_trend_summary_treats_unknown_scalar_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_escalation_resolution_trend_summary(
        {"available": True, "recent_event_count": "unknown"},
        {"available": True, "recent_recovery_count": "unknown"},
        {"window_open": "unknown"},
    )

    assert summary == {
        "available": True,
        "recent_escalation_count": 0,
        "recent_recovery_count": 0,
        "recent_resolved_count": 0,
        "recent_unresolved_count": 0,
        "recent_resolution_rate": 0.0,
        "window_open": False,
    }


def test_hybrid_collection_escalation_resolution_trend_summary_treats_negative_counts_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_escalation_resolution_trend_summary(
        {"available": True, "recent_event_count": -3},
        {"available": True, "recent_recovery_count": -2},
        {"window_open": True},
    )

    assert summary == {
        "available": True,
        "recent_escalation_count": 0,
        "recent_recovery_count": 0,
        "recent_resolved_count": 0,
        "recent_unresolved_count": 0,
        "recent_resolution_rate": 0.0,
        "window_open": True,
    }


def test_hybrid_collection_lifecycle_state_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_lifecycle_state_summary(
        "unknown",
        "unknown",
        "unknown",
        "unknown",
    )

    assert summary == {
        "available": False,
        "lifecycle_state": "unknown",
        "lifecycle_reason": "no_runtime_signals",
        "recommended_follow_up": "collect_runtime_history",
        "suggested_mode": "hybrid",
        "operator_action_hint": "collect runtime history; suggested mode=hybrid",
        "priority_hint": "no_priority_data",
        "active_unresolved_priority": None,
        "active_high_priority_unresolved_count": 0,
        "policy_status": None,
        "window_open": False,
    }


def test_hybrid_collection_lifecycle_state_summary_treats_unknown_available_and_window_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_lifecycle_state_summary(
        {"available": "unknown", "recovery_policy_status": "steady_hybrid"},
        {},
        {"window_open": "unknown"},
        {
            "recent_high_priority_unresolved_count": "unknown",
            "top_recent_unresolved_priority": "unknown",
        },
    )

    assert summary == {
        "available": False,
        "lifecycle_state": "unknown",
        "lifecycle_reason": "no_runtime_signals",
        "recommended_follow_up": "collect_runtime_history",
        "suggested_mode": "hybrid",
        "operator_action_hint": "collect runtime history; suggested mode=hybrid",
        "priority_hint": "no_priority_data",
        "active_unresolved_priority": None,
        "active_high_priority_unresolved_count": 0,
        "policy_status": None,
        "window_open": False,
    }


def test_hybrid_collection_lifecycle_state_summary_treats_unknown_policy_status_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_lifecycle_state_summary(
        {
            "available": True,
            "recovery_policy_status": "unknown",
        },
        {
            "policy_status": "unknown",
        },
        {
            "window_open": False,
        },
        {},
    )

    assert summary == {
        "available": True,
        "lifecycle_state": "steady",
        "lifecycle_reason": "browserless_fast_path_stable",
        "recommended_follow_up": "keep_hybrid",
        "suggested_mode": "hybrid",
        "operator_action_hint": "keep hybrid; suggested mode=hybrid",
        "priority_hint": "no_active_priority_backlog",
        "active_unresolved_priority": None,
        "active_high_priority_unresolved_count": 0,
        "policy_status": "steady_hybrid",
        "window_open": False,
    }


def test_hybrid_collection_lifecycle_state_summary_treats_negative_high_priority_count_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_lifecycle_state_summary(
        {
            "available": True,
            "recovery_policy_status": "steady_hybrid",
        },
        {
            "policy_status": "steady_hybrid",
        },
        {
            "window_open": True,
        },
        {
            "top_recent_unresolved_priority": "medium",
            "recent_high_priority_unresolved_count": -2,
        },
    )

    assert summary["available"] is True
    assert summary["lifecycle_state"] == "escalated"
    assert summary["priority_hint"] == "non_high_priority_backlog_present"
    assert summary["active_unresolved_priority"] == "medium"
    assert summary["active_high_priority_unresolved_count"] == 0


def test_hybrid_collection_action_hint_consistency_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_action_hint_consistency_summary("unknown", "unknown")

    assert summary == {
        "available": False,
        "runtime_operator_action_hint": None,
        "lifecycle_operator_action_hint": None,
        "hints_match": False,
        "consistency_status": "no_hint_available",
        "drift_reason": None,
        "consistency_severity": "info",
        "severity_reason": None,
        "hint_source_preference": None,
        "preferred_hint_source_detail": None,
        "preferred_hint_explanation": None,
        "preferred_operator_action_hint": None,
    }


def test_hybrid_collection_action_hint_consistency_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_action_hint_consistency_summary(
        {"available": "unknown"},
        {"available": "unknown"},
    )

    assert summary == {
        "available": False,
        "runtime_operator_action_hint": None,
        "lifecycle_operator_action_hint": None,
        "hints_match": False,
        "consistency_status": "no_hint_available",
        "drift_reason": None,
        "consistency_severity": "info",
        "severity_reason": None,
        "hint_source_preference": None,
        "preferred_hint_source_detail": None,
        "preferred_hint_explanation": None,
        "preferred_operator_action_hint": None,
    }


def test_hybrid_collection_recovery_policy_treats_unknown_summaries_as_missing(tmp_path: Path, monkeypatch):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        "unknown",
        "unknown",
        "unknown",
        "unknown",
        "unknown",
    )

    assert summary == {
        "policy_status": "no_history_available",
        "priority": "info",
        "effective_recommended_mode": "hybrid",
        "mode_pin_active": False,
        "recommended_actions": ["collect_more_hybrid_runtime_history"],
        "top_policy_reason": "history_unavailable",
        "guidance_status": None,
        "guidance_recommended_mode": None,
        "recent_mode_switch_count": 0,
        "recent_browserless_success_rate": 0.0,
        "top_switch_target_mode": None,
        "top_switch_guidance_reason": None,
        "last_switch_at": None,
    }


def test_hybrid_collection_recovery_policy_treats_unknown_history_available_as_missing(tmp_path: Path, monkeypatch):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {"available": "unknown"},
        {"recommended_mode": "hybrid"},
        {},
        {},
    )

    assert summary == {
        "policy_status": "no_history_available",
        "priority": "info",
        "effective_recommended_mode": "hybrid",
        "mode_pin_active": False,
        "recommended_actions": ["collect_more_hybrid_runtime_history"],
        "top_policy_reason": "history_unavailable",
        "guidance_status": None,
        "guidance_recommended_mode": "hybrid",
        "recent_mode_switch_count": 0,
        "recent_browserless_success_rate": 0.0,
        "top_switch_target_mode": None,
        "top_switch_guidance_reason": None,
        "last_switch_at": None,
    }


def test_hybrid_collection_recovery_policy_treats_unknown_no_history_aux_text_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {"available": "unknown"},
        {"guidance_status": "unknown", "recommended_mode": "unknown"},
        {
            "recent_switch_count": "unknown",
            "top_target_mode": "unknown",
            "top_guidance_reason": "unknown",
            "last_switch_at": "unknown",
        },
        {},
    )

    assert summary["policy_status"] == "no_history_available"
    assert summary["priority"] == "info"
    assert summary["effective_recommended_mode"] == "hybrid"
    assert summary["mode_pin_active"] is False
    assert summary["top_policy_reason"] == "history_unavailable"
    assert summary["guidance_status"] is None
    assert summary["guidance_recommended_mode"] is None
    assert summary["recent_mode_switch_count"] == 0
    assert summary["top_switch_target_mode"] is None
    assert summary["top_switch_guidance_reason"] is None
    assert summary["last_switch_at"] is None


def test_hybrid_collection_recovery_policy_treats_unknown_summary_scalars_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {
            "available": True,
            "recent_browserless_success_rate": "unknown",
        },
        {
            "recommended_mode": "hybrid",
            "priority": "info",
            "top_guidance_reason": "browserless_success_stable",
        },
        {
            "recent_switch_count": "unknown",
        },
        {
            "recent_transition_kind_counts": {
                "pin_released": "unknown",
                "pin_activated": "unknown",
            }
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["priority"] == "info"
    assert summary["effective_recommended_mode"] == "hybrid"
    assert summary["mode_pin_active"] is False
    assert summary["top_policy_reason"] == "browserless_success_stable"
    assert summary["recent_mode_switch_count"] == 0
    assert summary["recent_browserless_success_rate"] == 0.0
    assert summary["top_switch_target_mode"] is None
    assert summary["top_switch_guidance_reason"] is None
    assert summary["hybrid_retrial_budget_total"] == 1
    assert summary["hybrid_retrial_attempts_used"] == 0
    assert summary["hybrid_retrial_budget_remaining"] == 1


def test_hybrid_collection_recovery_policy_treats_negative_summary_scalars_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {
            "available": True,
            "recent_browserless_success_rate": -0.5,
        },
        {
            "recommended_mode": "hybrid",
            "priority": "info",
            "top_guidance_reason": "browserless_success_stable",
        },
        {
            "recent_switch_count": -1,
        },
        {
            "recent_transition_kind_counts": {},
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["priority"] == "info"
    assert summary["effective_recommended_mode"] == "hybrid"
    assert summary["mode_pin_active"] is False
    assert summary["top_policy_reason"] == "browserless_success_stable"
    assert summary["recent_mode_switch_count"] == 0
    assert summary["recent_browserless_success_rate"] == 0.0
    assert summary["top_switch_target_mode"] is None
    assert summary["top_switch_guidance_reason"] is None


def test_hybrid_collection_recovery_policy_treats_overfull_success_rate_as_clamped(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {
            "available": True,
            "recent_browserless_success_rate": 1.5,
        },
        {
            "recommended_mode": "hybrid",
            "priority": "info",
            "top_guidance_reason": "browserless_success_stable",
        },
        {
            "recent_switch_count": 0,
        },
        {
            "recent_transition_kind_counts": {},
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["recent_browserless_success_rate"] == 1.0


def test_hybrid_collection_recovery_policy_treats_unknown_guidance_reason_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {
            "available": True,
            "recent_browserless_success_rate": 0.75,
        },
        {
            "recommended_mode": "hybrid",
            "priority": "info",
            "top_guidance_reason": "unknown",
        },
        {
            "recent_switch_count": 0,
        },
        {},
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["priority"] == "info"
    assert summary["effective_recommended_mode"] == "hybrid"
    assert summary["mode_pin_active"] is False
    assert summary["top_policy_reason"] == "hybrid_stable"
    assert summary["recent_mode_switch_count"] == 0
    assert summary["recent_browserless_success_rate"] == 0.75


def test_hybrid_collection_recovery_policy_treats_unknown_guidance_status_and_switch_timestamp_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {
            "available": True,
            "recent_browserless_success_rate": 0.85,
        },
        {
            "guidance_status": "unknown",
            "recommended_mode": "hybrid",
            "priority": "info",
            "top_guidance_reason": "browserless_success_stable",
        },
        {
            "recent_switch_count": 0,
            "last_switch_at": "unknown",
        },
        {},
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["guidance_status"] is None
    assert summary["guidance_recommended_mode"] == "hybrid"
    assert summary["last_switch_at"] is None


def test_hybrid_collection_recovery_policy_treats_unknown_transition_kind_counts_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {"available": True, "recent_browserless_success_rate": 0.0},
        {"recommended_mode": "hybrid", "priority": "info", "top_guidance_reason": "browserless_success_stable"},
        {},
        {"recent_transition_kind_counts": "unknown"},
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["priority"] == "info"
    assert summary["effective_recommended_mode"] == "hybrid"
    assert summary["mode_pin_active"] is False
    assert summary["top_policy_reason"] == "browserless_success_stable"
    assert summary["recent_mode_switch_count"] == 0
    assert summary["hybrid_retrial_budget_total"] == 1
    assert summary["hybrid_retrial_attempts_used"] == 0
    assert summary["hybrid_retrial_budget_remaining"] == 1
    assert summary["last_recovery_transition_kind"] is None
    assert summary["last_recovery_transition_at"] is None


def test_hybrid_collection_recovery_policy_treats_unknown_history_decision_counts_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:27:00",
                "session_id": "policy-unknown-1",
                "decision_counts": "unknown",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {"generated_at": "2026-05-18 18:28:00", "last_decision": "browserless_success"},
        {"available": True, "recent_browserless_success_rate": 0.0},
        {"recommended_mode": "hybrid", "priority": "info", "top_guidance_reason": "browserless_success_stable"},
        {},
        {
            "last_transition_kind": "pin_released",
            "last_transition_at": "2026-05-18 18:26:00",
            "recent_transition_kind_counts": {},
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["priority"] == "info"
    assert summary["effective_recommended_mode"] == "hybrid"
    assert summary["mode_pin_active"] is False
    assert summary["top_policy_reason"] == "browserless_success_stable"
    assert summary["hybrid_retrial_budget_total"] == 1
    assert summary["hybrid_retrial_attempts_used"] == 1
    assert summary["hybrid_retrial_budget_remaining"] == 0
    assert summary["last_recovery_transition_kind"] == "pin_released"
    assert summary["last_recovery_transition_at"] == "2026-05-18 18:26:00"


def test_hybrid_collection_recovery_policy_treats_negative_history_decision_counts_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:27:00",
                "session_id": "policy-neg-1",
                "decision_counts": {
                    "browserless_success": -1,
                    "browser_fallback_required": -2,
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {"generated_at": "2026-05-18 18:28:00"},
        {"available": True, "recent_browserless_success_rate": 0.0},
        {"recommended_mode": "hybrid", "priority": "info", "top_guidance_reason": "browserless_success_stable"},
        {},
        {
            "last_transition_kind": "pin_released",
            "last_transition_at": "2026-05-18 18:26:00",
            "recent_transition_kind_counts": {},
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["hybrid_retrial_budget_total"] == 1
    assert summary["hybrid_retrial_attempts_used"] == 0
    assert summary["hybrid_retrial_budget_remaining"] == 1


def test_hybrid_collection_recovery_policy_treats_unknown_history_timestamp_as_missing_for_budget_usage(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "generated_at": "unknown",
                "session_id": "policy-ts-unknown-1",
                "decision_counts": {"browserless_success": 1},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {"generated_at": "2026-05-18 18:24:00"},
        {"available": True, "recent_browserless_success_rate": 0.0},
        {"recommended_mode": "hybrid", "priority": "info", "top_guidance_reason": "browserless_success_stable"},
        {},
        {
            "last_transition_kind": "pin_released",
            "last_transition_at": "2026-05-18 18:23:00",
            "recent_transition_kind_counts": {},
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["hybrid_retrial_budget_total"] == 1
    assert summary["hybrid_retrial_attempts_used"] == 0
    assert summary["hybrid_retrial_budget_remaining"] == 1


def test_hybrid_collection_recovery_policy_treats_unknown_latest_summary_timestamp_as_missing_for_budget_usage(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {
            "generated_at": "unknown",
            "last_decision": "browserless_success",
        },
        {"available": True, "recent_browserless_success_rate": 0.0},
        {"recommended_mode": "hybrid", "priority": "info", "top_guidance_reason": "browserless_success_stable"},
        {},
        {
            "last_transition_kind": "pin_released",
            "last_transition_at": "2026-05-18 18:23:00",
            "recent_transition_kind_counts": {},
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["hybrid_retrial_budget_total"] == 1
    assert summary["hybrid_retrial_attempts_used"] == 0
    assert summary["hybrid_retrial_budget_remaining"] == 1


def test_hybrid_collection_lifecycle_state_summary_treats_unknown_runtime_action_hint_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_lifecycle_state_summary(
        {
            "available": True,
            "operator_action_hint": "unknown",
        },
        {
            "policy_status": "steady_hybrid",
        },
        {},
        {},
    )

    assert summary["available"] is True
    assert summary["lifecycle_state"] == "steady"
    assert summary["lifecycle_reason"] == "browserless_fast_path_stable"
    assert summary["suggested_mode"] == "hybrid"
    assert summary["operator_action_hint"] == "keep hybrid; suggested mode=hybrid"
    assert summary["policy_status"] == "steady_hybrid"
    assert summary["window_open"] is False


def test_hybrid_collection_action_hint_consistency_summary_treats_unknown_hints_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_action_hint_consistency_summary(
        {
            "available": True,
            "operator_action_hint": "unknown",
        },
        {
            "available": True,
            "operator_action_hint": "unknown",
        },
    )

    assert summary["available"] is True
    assert summary["runtime_operator_action_hint"] is None
    assert summary["lifecycle_operator_action_hint"] is None
    assert summary["hints_match"] is False
    assert summary["consistency_status"] == "no_hint_available"
    assert summary["drift_reason"] is None
    assert summary["consistency_severity"] == "info"
    assert summary["severity_reason"] is None
    assert summary["hint_source_preference"] is None
    assert summary["preferred_hint_source_detail"] is None
    assert summary["preferred_hint_explanation"] is None
    assert summary["preferred_operator_action_hint"] is None

def test_hybrid_collection_operator_intervention_policy_summary_treats_unknown_action_hints_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        {
            "available": True,
            "lifecycle_state": "steady",
            "lifecycle_reason": "browserless_fast_path_stable",
            "operator_action_hint": "unknown",
            "suggested_mode": "hybrid",
            "window_open": False,
            "active_high_priority_unresolved_count": 0,
        },
        {
            "available": True,
            "preferred_operator_action_hint": "unknown",
        },
        {},
        {},
    )

    assert summary["available"] is True
    assert summary["intervention_status"] == "ready"
    assert summary["intervention_required"] is False
    assert summary["intervention_priority"] == "info"
    assert summary["intervention_reason"] == "browserless_fast_path_stable"
    assert summary["preferred_operator_action_hint"] is None
    assert summary["suggested_mode"] == "hybrid"
    assert summary["lifecycle_state"] == "steady"
    assert summary["window_open"] is False
    assert summary["active_high_priority_unresolved_count"] == 0


def test_hybrid_collection_operator_final_guidance_summary_treats_unknown_action_hint_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_summary(
        {
            "available": True,
            "intervention_priority": "warning",
            "suggested_mode": "hybrid",
            "intervention_status": "monitor",
        },
        {
            "available": True,
            "stability_status": "transitioning",
            "stability_action_hint": "unknown",
            "current_intervention_status": "monitor",
        },
    )

    assert summary["available"] is True
    assert summary["guidance_label"] == "Transitioning intervention"
    assert summary["guidance_priority"] == "warning"
    assert summary["guidance_message"] == "Transitioning intervention"
    assert summary["preferred_action_hint"] is None
    assert summary["suggested_mode"] == "hybrid"
    assert summary["intervention_status"] == "monitor"
    assert summary["stability_status"] == "transitioning"


def test_hybrid_collection_operator_final_guidance_summary_treats_unknown_status_and_mode_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_summary(
        {
            "available": True,
            "intervention_priority": "warning",
            "suggested_mode": "unknown",
            "intervention_status": "monitor",
        },
        {
            "available": True,
            "stability_status": "transitioning",
            "stability_action_hint": "unknown",
            "current_intervention_status": "unknown",
        },
    )

    assert summary["available"] is True
    assert summary["guidance_label"] == "Transitioning intervention"
    assert summary["guidance_priority"] == "warning"
    assert summary["guidance_message"] == "Transitioning intervention"
    assert summary["preferred_action_hint"] is None
    assert summary["suggested_mode"] is None
    assert summary["intervention_status"] == "monitor"
    assert summary["stability_status"] == "transitioning"


def test_hybrid_collection_operator_final_guidance_summary_treats_unknown_fallback_priority_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_summary(
        {
            "available": True,
            "intervention_priority": "unknown",
            "suggested_mode": "hybrid",
            "intervention_status": "monitor",
        },
        {
            "available": True,
            "stability_status": "unknown",
            "stability_action_hint": "inspect backlog",
            "current_intervention_status": "monitor",
        },
    )

    assert summary["available"] is True
    assert summary["guidance_label"] == "Operator guidance"
    assert summary["guidance_priority"] is None
    assert summary["guidance_message"] == "Operator guidance: inspect backlog."
    assert summary["preferred_action_hint"] == "inspect backlog"
    assert summary["suggested_mode"] == "hybrid"
    assert summary["intervention_status"] == "monitor"
    assert summary["stability_status"] is None


def test_hybrid_collection_operator_digest_summary_treats_unknown_guidance_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_summary(
        {
            "available": True,
            "intervention_status": "ready",
        },
        {
            "available": True,
            "stability_status": "stable_ready",
        },
        {
            "available": True,
            "guidance_label": "Stable ready state",
            "guidance_priority": "unknown",
            "guidance_message": "unknown",
        },
        {
            "available": True,
            "stability_status": "stable_guidance",
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "unknown",
            "current_guidance_message": "unknown",
        },
    )

    assert summary["available"] is True
    assert summary["digest_status"] == "ready"
    assert summary["digest_priority"] == "info"
    assert summary["final_guidance_message"] is None
    assert summary["intervention_status"] == "ready"
    assert summary["intervention_stability_status"] == "stable_ready"
    assert summary["final_guidance_stability_status"] == "stable_guidance"
    assert summary["operator_digest_message"] is None


def test_hybrid_collection_operator_intervention_policy_overview_fields_treat_unknown_required_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_intervention_policy_overview_fields(
        {
            "intervention_status": "ready",
            "intervention_required": "unknown",
            "intervention_priority": "info",
            "intervention_reason": "browserless_fast_path_stable",
            "preferred_operator_action_hint": None,
            "suggested_mode": "hybrid",
        }
    )

    assert overview["hybrid_collection_operator_intervention_status"] == "ready"
    assert overview["hybrid_collection_operator_intervention_required"] is False
    assert overview["hybrid_collection_operator_intervention_priority"] == "info"
    assert overview["hybrid_collection_operator_intervention_reason"] == "browserless_fast_path_stable"
    assert overview["hybrid_collection_operator_intervention_action_hint"] is None
    assert overview["hybrid_collection_operator_intervention_suggested_mode"] == "hybrid"


def test_hybrid_collection_operator_recovery_policy_overview_fields_treat_unknown_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_recovery_policy_overview_fields(
        {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": "unknown",
            "top_policy_reason": "unknown",
            "hybrid_retrial_budget_remaining": "unknown",
            "last_recovery_transition_kind": "unknown",
        }
    )

    assert overview["hybrid_collection_recovery_policy_status"] == "steady_hybrid"
    assert overview["hybrid_collection_recovery_policy_priority"] == "info"
    assert overview["hybrid_collection_recovery_effective_mode"] == "hybrid"
    assert overview["hybrid_collection_recovery_mode_pin_active"] is False
    assert overview["hybrid_collection_recovery_top_policy_reason"] is None
    assert overview["hybrid_collection_recovery_budget_remaining"] == 0
    assert overview["hybrid_collection_recovery_last_transition_kind"] is None


def test_hybrid_collection_operator_unresolved_escalation_window_overview_fields_treat_unknown_window_open_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_unresolved_escalation_window_overview_fields(
        {
            "window_open": "unknown",
            "last_escalation_policy_status": "escalate_repeated_repin",
            "last_recovery_to_policy_status": "allow_hybrid_retrial",
            "last_escalation_at": "2026-05-18 18:40:00",
            "last_recovery_at": "2026-05-18 18:41:00",
            "current_window_duration_seconds": "unknown",
            "current_window_duration_minutes": "unknown",
        }
    )

    assert overview["hybrid_collection_unresolved_escalation_window_open"] is False
    assert overview["hybrid_collection_unresolved_escalation_policy_status"] == "allow_hybrid_retrial"
    assert overview["hybrid_collection_unresolved_escalation_last_event_at"] == "2026-05-18 18:41:00"
    assert overview["hybrid_collection_unresolved_escalation_duration_seconds"] is None
    assert overview["hybrid_collection_unresolved_escalation_duration_minutes"] is None


def test_hybrid_collection_operator_unresolved_escalation_window_overview_fields_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_unresolved_escalation_window_overview_fields(
        {
            "window_open": False,
            "last_escalation_policy_status": "unknown",
            "last_recovery_to_policy_status": "unknown",
            "last_escalation_at": "unknown",
            "last_recovery_at": "unknown",
            "current_window_duration_seconds": "unknown",
            "current_window_duration_minutes": "unknown",
        }
    )

    assert overview["hybrid_collection_unresolved_escalation_window_open"] is False
    assert overview["hybrid_collection_unresolved_escalation_policy_status"] is None
    assert overview["hybrid_collection_unresolved_escalation_last_event_at"] is None
    assert overview["hybrid_collection_unresolved_escalation_duration_seconds"] is None
    assert overview["hybrid_collection_unresolved_escalation_duration_minutes"] is None


def test_hybrid_collection_operator_action_hint_consistency_overview_fields_treat_unknown_hints_match_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_action_hint_consistency_overview_fields(
        {
            "consistency_status": "unknown",
            "hints_match": "unknown",
            "drift_reason": "unknown",
            "consistency_severity": "unknown",
            "severity_reason": "unknown",
            "hint_source_preference": "unknown",
            "preferred_hint_source_detail": "unknown",
            "preferred_hint_explanation": "unknown",
            "preferred_operator_action_hint": "unknown",
        }
    )

    assert overview["hybrid_collection_action_hint_consistency_status"] is None
    assert overview["hybrid_collection_action_hint_hints_match"] is False
    assert overview["hybrid_collection_action_hint_drift_reason"] is None
    assert overview["hybrid_collection_action_hint_consistency_severity"] is None
    assert overview["hybrid_collection_action_hint_severity_reason"] is None
    assert overview["hybrid_collection_action_hint_source_preference"] is None
    assert overview["hybrid_collection_action_hint_source_detail"] is None
    assert overview["hybrid_collection_action_hint_explanation"] is None
    assert overview["hybrid_collection_preferred_action_hint"] is None


def test_hybrid_collection_operator_intervention_overview_helpers_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    intervention_event_overview = server_module._hybrid_collection_operator_intervention_event_overview_fields(
        {
            "recent_event_count": "unknown",
            "last_event_at": "unknown",
            "last_transition_kind": "unknown",
            "last_to_intervention_status": "unknown",
            "last_to_intervention_priority": "unknown",
            "last_to_final_guidance_label": "unknown",
            "last_to_final_guidance_priority": "unknown",
            "last_to_final_guidance_message": "unknown",
        }
    )
    intervention_stability_overview = server_module._hybrid_collection_operator_intervention_stability_overview_fields(
        {
            "stability_status": "unknown",
            "stability_severity": "unknown",
            "operator_readable_explanation": "unknown",
            "stability_action_hint": "unknown",
        }
    )
    intervention_policy_overview = server_module._hybrid_collection_operator_intervention_policy_overview_fields(
        {
            "intervention_status": "unknown",
            "intervention_required": "unknown",
            "intervention_priority": "unknown",
            "intervention_reason": "unknown",
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "unknown",
        }
    )

    assert intervention_event_overview["hybrid_collection_recent_intervention_event_count"] == 0
    assert intervention_event_overview["hybrid_collection_last_intervention_event_at"] is None
    assert intervention_event_overview["hybrid_collection_last_intervention_transition_kind"] is None
    assert intervention_event_overview["hybrid_collection_last_to_intervention_status"] is None
    assert intervention_event_overview["hybrid_collection_last_to_intervention_priority"] is None
    assert intervention_event_overview["hybrid_collection_last_to_final_guidance_label"] is None
    assert intervention_event_overview["hybrid_collection_last_to_final_guidance_priority"] is None
    assert intervention_event_overview["hybrid_collection_last_to_final_guidance_message"] is None
    assert intervention_stability_overview["hybrid_collection_intervention_stability_status"] is None
    assert intervention_stability_overview["hybrid_collection_intervention_stability_severity"] is None
    assert intervention_stability_overview["hybrid_collection_intervention_stability_explanation"] is None
    assert intervention_stability_overview["hybrid_collection_intervention_stability_action_hint"] is None
    assert intervention_policy_overview["hybrid_collection_operator_intervention_status"] is None
    assert intervention_policy_overview["hybrid_collection_operator_intervention_required"] is False
    assert intervention_policy_overview["hybrid_collection_operator_intervention_priority"] is None
    assert intervention_policy_overview["hybrid_collection_operator_intervention_reason"] is None
    assert intervention_policy_overview["hybrid_collection_operator_intervention_action_hint"] is None
    assert intervention_policy_overview["hybrid_collection_operator_intervention_suggested_mode"] is None


def test_hybrid_collection_operator_guidance_overview_helpers_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    final_guidance_overview = server_module._hybrid_collection_operator_final_guidance_overview_fields(
        {
            "guidance_label": "unknown",
            "guidance_priority": "unknown",
            "guidance_message": "unknown",
        }
    )
    digest_overview = server_module._hybrid_collection_operator_digest_overview_fields(
        {
            "digest_status": "unknown",
            "digest_priority": "unknown",
            "operator_digest_message": "unknown",
        }
    )

    assert final_guidance_overview["hybrid_collection_operator_final_guidance_label"] is None
    assert final_guidance_overview["hybrid_collection_operator_final_guidance_priority"] is None
    assert final_guidance_overview["hybrid_collection_operator_final_guidance_message"] is None
    assert digest_overview["hybrid_collection_operator_digest_status"] is None
    assert digest_overview["hybrid_collection_operator_digest_priority"] is None
    assert digest_overview["hybrid_collection_operator_digest_message"] is None


def test_hybrid_collection_operator_lifecycle_state_overview_fields_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_lifecycle_state_overview_fields(
        {
            "lifecycle_state": "unknown",
            "lifecycle_reason": "unknown",
            "recommended_follow_up": "unknown",
            "suggested_mode": "unknown",
            "operator_action_hint": "unknown",
            "priority_hint": "unknown",
            "active_unresolved_priority": "unknown",
            "active_high_priority_unresolved_count": "unknown",
        }
    )

    assert overview["hybrid_collection_lifecycle_state"] is None
    assert overview["hybrid_collection_lifecycle_reason"] is None
    assert overview["hybrid_collection_lifecycle_follow_up"] is None
    assert overview["hybrid_collection_lifecycle_suggested_mode"] is None
    assert overview["hybrid_collection_lifecycle_action_hint"] is None
    assert overview["hybrid_collection_lifecycle_priority_hint"] is None
    assert overview["hybrid_collection_lifecycle_active_unresolved_priority"] is None
    assert overview["hybrid_collection_lifecycle_active_high_priority_unresolved_count"] == 0


def test_hybrid_collection_unresolved_window_and_lifecycle_overview_fields_treat_negative_numeric_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    unresolved_overview = server_module._hybrid_collection_operator_unresolved_escalation_window_overview_fields(
        {
            "window_open": True,
            "last_escalation_policy_status": "escalate_repeated_repin",
            "last_escalation_at": "2026-05-18 18:40:00",
            "current_window_duration_seconds": -300,
            "current_window_duration_minutes": -5.0,
        }
    )
    lifecycle_overview = server_module._hybrid_collection_operator_lifecycle_state_overview_fields(
        {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "priority_hint": "high_priority_backlog_present",
            "active_unresolved_priority": "high",
            "active_high_priority_unresolved_count": -2,
        }
    )

    assert unresolved_overview["hybrid_collection_unresolved_escalation_duration_seconds"] is None
    assert unresolved_overview["hybrid_collection_unresolved_escalation_duration_minutes"] is None
    assert lifecycle_overview["hybrid_collection_lifecycle_active_high_priority_unresolved_count"] == 0


def test_hybrid_collection_operator_recovery_latency_overview_fields_treat_unknown_policy_status_fields_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_recovery_latency_overview_fields(
        {
            "last_recovery_latency_seconds": "unknown",
            "last_recovery_latency_minutes": "unknown",
            "last_recovery_from_policy_status": "unknown",
            "last_recovery_to_policy_status": "unknown",
        }
    )

    assert overview["hybrid_collection_last_recovery_latency_seconds"] is None
    assert overview["hybrid_collection_last_recovery_latency_minutes"] is None
    assert overview["hybrid_collection_last_recovery_latency_from_policy_status"] is None
    assert overview["hybrid_collection_last_recovery_latency_to_policy_status"] is None


def test_hybrid_collection_operator_recovery_latency_overview_fields_treat_negative_latency_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_recovery_latency_overview_fields(
        {
            "last_recovery_latency_seconds": -90,
            "last_recovery_latency_minutes": -1.5,
            "last_recovery_from_policy_status": "escalate_repeated_repin",
            "last_recovery_to_policy_status": "steady_hybrid",
        }
    )

    assert overview["hybrid_collection_last_recovery_latency_seconds"] is None
    assert overview["hybrid_collection_last_recovery_latency_minutes"] is None
    assert overview["hybrid_collection_last_recovery_latency_from_policy_status"] == "escalate_repeated_repin"
    assert overview["hybrid_collection_last_recovery_latency_to_policy_status"] == "steady_hybrid"


def test_hybrid_collection_operator_recovery_policy_event_overview_fields_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_recovery_policy_event_overview_fields(
        {
            "recent_transition_count": "unknown",
            "last_transition_kind": "unknown",
            "last_to_policy_status": "unknown",
        }
    )

    assert overview["hybrid_collection_recent_recovery_policy_transition_count"] == 0
    assert overview["hybrid_collection_last_recovery_transition_kind"] is None
    assert overview["hybrid_collection_last_recovery_to_policy_status"] is None


def test_hybrid_collection_operator_escalation_event_overview_fields_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_escalation_event_overview_fields(
        {
            "recent_event_count": "unknown",
            "top_escalation_kind": "unknown",
            "top_operator_escalation_source": "unknown",
            "top_policy_status": "unknown",
            "last_operator_escalation_source": "unknown",
            "last_operator_escalation_audit_message": "unknown",
        }
    )

    assert overview["hybrid_collection_recent_operator_escalation_count"] == 0
    assert overview["hybrid_collection_top_operator_escalation_kind"] is None
    assert overview["hybrid_collection_top_operator_escalation_source"] is None
    assert overview["hybrid_collection_top_operator_escalation_policy_status"] is None
    assert overview["hybrid_collection_last_operator_escalation_source"] is None
    assert overview["hybrid_collection_last_operator_escalation_audit_message"] is None


def test_hybrid_collection_operator_escalation_recovery_event_overview_fields_treat_unknown_policy_status_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_escalation_recovery_event_overview_fields(
        {
            "recent_recovery_count": "unknown",
            "last_to_policy_status": "unknown",
        }
    )

    assert overview["hybrid_collection_recent_operator_escalation_recovery_count"] == 0
    assert overview["hybrid_collection_last_operator_escalation_recovery_policy_status"] is None


def test_hybrid_collection_operator_overview_fields_treat_unknown_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_overview_fields(
        {
            "available": "unknown",
            "runner_mode": "unknown",
            "requested_mode": "unknown",
            "effective_mode_source": "unknown",
            "operator_action_hint": "unknown",
            "last_decision": "unknown",
            "last_reason": "unknown",
            "last_effective_mode": "unknown",
            "top_fallback_reason": "unknown",
            "termination_reason": "unknown",
            "guidance_applied_count": -2,
            "guidance_status": "unknown",
            "recovery_policy_status": "unknown",
            "recovery_policy_mode_pin_active": "unknown",
            "browserless_success_count": -1,
            "browser_fallback_required_count": -3,
            "browser_worker_dispatched_count": -4,
            "last_task_url": "unknown",
            "last_task_page": -1,
            "last_submit_batch_status": "unknown",
            "last_submit_progress_status": "unknown",
        }
    )

    assert overview["hybrid_collection_available"] is False
    assert overview["hybrid_collection_runner_mode"] is None
    assert overview["hybrid_collection_requested_mode"] is None
    assert overview["hybrid_collection_effective_mode_source"] is None
    assert overview["hybrid_collection_operator_action_hint"] is None
    assert overview["hybrid_collection_last_decision"] is None
    assert overview["hybrid_collection_last_reason"] is None
    assert overview["hybrid_collection_last_effective_mode"] is None
    assert overview["hybrid_collection_top_fallback_reason"] is None
    assert overview["hybrid_collection_termination_reason"] is None
    assert overview["hybrid_collection_guidance_applied_count"] == 0
    assert overview["hybrid_collection_guidance_status"] is None
    assert overview["hybrid_collection_recovery_policy_status"] is None
    assert overview["hybrid_collection_recovery_mode_pin_active"] is False
    assert overview["hybrid_collection_browserless_success_count"] == 0
    assert overview["hybrid_collection_browser_fallback_required_count"] == 0
    assert overview["hybrid_collection_browser_worker_dispatched_count"] == 0
    assert overview["hybrid_collection_last_task_url"] is None
    assert overview["hybrid_collection_last_task_page"] is None
    assert overview["hybrid_collection_last_submit_batch_status"] is None
    assert overview["hybrid_collection_last_submit_progress_status"] is None


def test_hybrid_collection_operator_history_overview_fields_treat_unknown_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_history_overview_fields(
        {
            "recent_runs": -2,
            "recent_browserless_success_count": -1,
            "recent_browser_fallback_required_count": -3,
            "recent_browser_worker_dispatched_count": -4,
            "recent_browserless_success_rate": 1.5,
            "recent_top_fallback_reason": "unknown",
            "recent_top_termination_reason": "unknown",
        }
    )

    assert overview["hybrid_collection_recent_runs"] == 0
    assert overview["hybrid_collection_recent_browserless_success_count"] == 0
    assert overview["hybrid_collection_recent_browser_fallback_required_count"] == 0
    assert overview["hybrid_collection_recent_browser_worker_dispatched_count"] == 0
    assert overview["hybrid_collection_recent_browserless_success_rate"] == 1.0
    assert overview["hybrid_collection_recent_top_fallback_reason"] is None
    assert overview["hybrid_collection_recent_top_termination_reason"] is None


def test_hybrid_collection_operator_guidance_and_mode_switch_overview_fields_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    guidance_overview = server_module._hybrid_collection_operator_guidance_overview_fields(
        {
            "guidance_status": "unknown",
            "priority": "unknown",
            "recommended_mode": "unknown",
            "top_guidance_reason": "unknown",
        }
    )
    mode_switch_overview = server_module._hybrid_collection_operator_mode_switch_overview_fields(
        {
            "recent_switch_count": "unknown",
            "top_target_mode": "unknown",
            "top_guidance_reason": "unknown",
        }
    )

    assert guidance_overview["hybrid_collection_guidance_status"] is None
    assert guidance_overview["hybrid_collection_guidance_priority"] is None
    assert guidance_overview["hybrid_collection_recommended_mode"] is None
    assert guidance_overview["hybrid_collection_top_guidance_reason"] is None
    assert mode_switch_overview["hybrid_collection_recent_mode_switch_count"] == 0
    assert mode_switch_overview["hybrid_collection_top_switch_target_mode"] is None
    assert mode_switch_overview["hybrid_collection_top_switch_guidance_reason"] is None


def test_hybrid_collection_trend_overview_fields_treat_unknown_change_counts_as_missing():
    server_module = importlib.import_module("src.server")

    action_hint_overview = server_module._hybrid_collection_operator_action_hint_trend_overview_fields(
        {
            "current_action_hint": "keep hybrid; suggested mode=hybrid",
            "previous_distinct_action_hint": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:24:00",
        }
    )
    final_guidance_overview = server_module._hybrid_collection_operator_final_guidance_trend_overview_fields(
        {
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "info",
            "current_guidance_message": "Stable ready state",
            "previous_distinct_guidance_message": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:25:00",
        }
    )
    digest_overview = server_module._hybrid_collection_operator_digest_trend_overview_fields(
        {
            "current_digest_status": "ready",
            "current_digest_priority": "info",
            "current_digest_message": "Stable ready state",
            "previous_distinct_digest_message": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:26:00",
        }
    )
    intervention_overview = server_module._hybrid_collection_operator_intervention_trend_overview_fields(
        {
            "current_intervention_status": "ready",
            "current_intervention_priority": "info",
            "current_intervention_reason": "browserless_fast_path_stable",
            "previous_distinct_intervention_status": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:27:00",
        }
    )

    assert action_hint_overview["hybrid_collection_action_hint_change_count"] == 0
    assert final_guidance_overview["hybrid_collection_final_guidance_change_count"] == 0
    assert digest_overview["hybrid_collection_digest_change_count"] == 0
    assert intervention_overview["hybrid_collection_intervention_change_count"] == 0


def test_hybrid_collection_overview_helpers_treat_negative_counts_as_missing():
    server_module = importlib.import_module("src.server")

    mode_switch_overview = server_module._hybrid_collection_operator_mode_switch_overview_fields(
        {
            "recent_switch_count": -2,
            "top_target_mode": "browser",
            "top_guidance_reason": "challenge_detected",
        }
    )
    action_hint_overview = server_module._hybrid_collection_operator_action_hint_trend_overview_fields(
        {
            "current_action_hint": "keep hybrid; suggested mode=hybrid",
            "previous_distinct_action_hint": None,
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:24:00",
        }
    )
    final_guidance_overview = server_module._hybrid_collection_operator_final_guidance_trend_overview_fields(
        {
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "info",
            "current_guidance_message": "Stable ready state",
            "previous_distinct_guidance_message": None,
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:25:00",
        }
    )
    digest_overview = server_module._hybrid_collection_operator_digest_trend_overview_fields(
        {
            "current_digest_status": "ready",
            "current_digest_priority": "info",
            "current_digest_message": "Stable ready state",
            "previous_distinct_digest_message": None,
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:26:00",
        }
    )
    intervention_trend_overview = server_module._hybrid_collection_operator_intervention_trend_overview_fields(
        {
            "current_intervention_status": "ready",
            "current_intervention_priority": "info",
            "current_intervention_reason": "browserless_fast_path_stable",
            "previous_distinct_intervention_status": None,
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:27:00",
        }
    )
    intervention_event_overview = server_module._hybrid_collection_operator_intervention_event_overview_fields(
        {
            "recent_event_count": -2,
            "last_event_at": "2026-05-18 18:28:00",
            "last_transition_kind": "status_changed",
        }
    )
    recovery_policy_overview = server_module._hybrid_collection_operator_recovery_policy_overview_fields(
        {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browserless_success_stable",
            "hybrid_retrial_budget_remaining": -1,
            "last_recovery_transition_kind": "pin_released",
        }
    )
    recovery_policy_event_overview = server_module._hybrid_collection_operator_recovery_policy_event_overview_fields(
        {
            "recent_transition_count": -2,
            "last_transition_kind": "pin_released",
            "last_to_policy_status": "allow_hybrid_retrial",
        }
    )
    escalation_event_overview = server_module._hybrid_collection_operator_escalation_event_overview_fields(
        {
            "recent_event_count": -2,
            "top_escalation_kind": "repeated_repin_cycle",
        }
    )
    escalation_event_trend_overview = server_module._hybrid_collection_operator_escalation_event_trend_overview_fields(
        {
            "current_operator_escalation_source": "recovery_policy",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": -2,
            "last_source_change_at": "2026-05-18 18:29:00",
        }
    )
    escalation_recovery_event_overview = server_module._hybrid_collection_operator_escalation_recovery_event_overview_fields(
        {
            "recent_recovery_count": -2,
            "last_to_policy_status": "steady_hybrid",
        }
    )

    assert mode_switch_overview["hybrid_collection_recent_mode_switch_count"] == 0
    assert action_hint_overview["hybrid_collection_action_hint_change_count"] == 0
    assert final_guidance_overview["hybrid_collection_final_guidance_change_count"] == 0
    assert digest_overview["hybrid_collection_digest_change_count"] == 0
    assert intervention_trend_overview["hybrid_collection_intervention_change_count"] == 0
    assert intervention_event_overview["hybrid_collection_recent_intervention_event_count"] == 0
    assert recovery_policy_overview["hybrid_collection_recovery_budget_remaining"] == 0
    assert recovery_policy_event_overview["hybrid_collection_recent_recovery_policy_transition_count"] == 0
    assert escalation_event_overview["hybrid_collection_recent_operator_escalation_count"] == 0
    assert escalation_event_trend_overview["hybrid_collection_operator_escalation_source_change_count"] == 0
    assert escalation_recovery_event_overview["hybrid_collection_recent_operator_escalation_recovery_count"] == 0


def test_hybrid_collection_trend_overview_helpers_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    action_hint_overview = server_module._hybrid_collection_operator_action_hint_trend_overview_fields(
        {
            "current_action_hint": "unknown",
            "previous_distinct_action_hint": "unknown",
            "recent_change_count": "unknown",
            "last_change_at": "unknown",
        }
    )
    final_guidance_overview = server_module._hybrid_collection_operator_final_guidance_trend_overview_fields(
        {
            "current_guidance_label": "unknown",
            "current_guidance_priority": "unknown",
            "current_guidance_message": "unknown",
            "previous_distinct_guidance_message": "unknown",
            "recent_change_count": "unknown",
            "last_change_at": "unknown",
        }
    )
    digest_overview = server_module._hybrid_collection_operator_digest_trend_overview_fields(
        {
            "current_digest_status": "unknown",
            "current_digest_priority": "unknown",
            "current_digest_message": "unknown",
            "previous_distinct_digest_message": "unknown",
            "recent_change_count": "unknown",
            "last_change_at": "unknown",
        }
    )
    intervention_overview = server_module._hybrid_collection_operator_intervention_trend_overview_fields(
        {
            "current_intervention_status": "unknown",
            "current_intervention_priority": "unknown",
            "current_intervention_reason": "unknown",
            "previous_distinct_intervention_status": "unknown",
            "recent_change_count": "unknown",
            "last_change_at": "unknown",
        }
    )

    assert action_hint_overview["hybrid_collection_current_action_hint"] is None
    assert action_hint_overview["hybrid_collection_previous_action_hint"] is None
    assert action_hint_overview["hybrid_collection_action_hint_change_count"] == 0
    assert action_hint_overview["hybrid_collection_action_hint_last_changed_at"] is None
    assert final_guidance_overview["hybrid_collection_current_final_guidance_label"] is None
    assert final_guidance_overview["hybrid_collection_current_final_guidance_priority"] is None
    assert final_guidance_overview["hybrid_collection_current_final_guidance_message"] is None
    assert final_guidance_overview["hybrid_collection_previous_final_guidance_message"] is None
    assert final_guidance_overview["hybrid_collection_final_guidance_change_count"] == 0
    assert final_guidance_overview["hybrid_collection_final_guidance_last_changed_at"] is None
    assert digest_overview["hybrid_collection_current_digest_status"] is None
    assert digest_overview["hybrid_collection_current_digest_priority"] is None
    assert digest_overview["hybrid_collection_current_digest_message"] is None
    assert digest_overview["hybrid_collection_previous_digest_message"] is None
    assert digest_overview["hybrid_collection_digest_change_count"] == 0
    assert digest_overview["hybrid_collection_digest_last_changed_at"] is None
    assert intervention_overview["hybrid_collection_current_intervention_status"] is None
    assert intervention_overview["hybrid_collection_current_intervention_priority"] is None
    assert intervention_overview["hybrid_collection_current_intervention_reason"] is None
    assert intervention_overview["hybrid_collection_previous_intervention_status"] is None
    assert intervention_overview["hybrid_collection_intervention_change_count"] == 0
    assert intervention_overview["hybrid_collection_intervention_last_changed_at"] is None


def test_hybrid_collection_stability_overview_helpers_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    final_guidance_stability_overview = server_module._hybrid_collection_operator_final_guidance_stability_overview_fields(
        {
            "stability_status": "unknown",
            "stability_severity": "unknown",
            "operator_readable_explanation": "unknown",
        }
    )
    digest_stability_overview = server_module._hybrid_collection_operator_digest_stability_overview_fields(
        {
            "stability_status": "unknown",
            "stability_severity": "unknown",
            "operator_readable_explanation": "unknown",
        }
    )

    assert final_guidance_stability_overview["hybrid_collection_final_guidance_stability_status"] is None
    assert final_guidance_stability_overview["hybrid_collection_final_guidance_stability_severity"] is None
    assert final_guidance_stability_overview["hybrid_collection_final_guidance_stability_explanation"] is None
    assert digest_stability_overview["hybrid_collection_digest_stability_status"] is None
    assert digest_stability_overview["hybrid_collection_digest_stability_severity"] is None
    assert digest_stability_overview["hybrid_collection_digest_stability_explanation"] is None


def test_hybrid_collection_event_overview_fields_treat_unknown_recent_counts_as_missing():
    server_module = importlib.import_module("src.server")

    intervention_event_overview = server_module._hybrid_collection_operator_intervention_event_overview_fields(
        {
            "recent_event_count": "unknown",
            "last_event_at": "2026-05-18 18:28:00",
            "last_transition_kind": "status_changed",
        }
    )
    recovery_policy_event_overview = server_module._hybrid_collection_operator_recovery_policy_event_overview_fields(
        {
            "recent_transition_count": "unknown",
            "last_transition_kind": "pin_released",
            "last_to_policy_status": "allow_hybrid_retrial",
        }
    )
    escalation_event_overview = server_module._hybrid_collection_operator_escalation_event_overview_fields(
        {
            "recent_event_count": "unknown",
            "top_escalation_kind": "repeated_repin_cycle",
        }
    )
    escalation_event_trend_overview = server_module._hybrid_collection_operator_escalation_event_trend_overview_fields(
        {
            "current_operator_escalation_source": "recovery_policy",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": "unknown",
            "last_source_change_at": "2026-05-18 18:29:00",
        }
    )
    escalation_recovery_event_overview = server_module._hybrid_collection_operator_escalation_recovery_event_overview_fields(
        {
            "recent_recovery_count": "unknown",
            "last_to_policy_status": "steady_hybrid",
        }
    )

    assert intervention_event_overview["hybrid_collection_recent_intervention_event_count"] == 0
    assert recovery_policy_event_overview["hybrid_collection_recent_recovery_policy_transition_count"] == 0
    assert escalation_event_overview["hybrid_collection_recent_operator_escalation_count"] == 0
    assert escalation_event_trend_overview["hybrid_collection_operator_escalation_source_change_count"] == 0
    assert escalation_recovery_event_overview["hybrid_collection_recent_operator_escalation_recovery_count"] == 0


def test_hybrid_collection_stability_helpers_treat_unknown_recent_counts_as_missing():
    server_module = importlib.import_module("src.server")

    final_guidance_stability = server_module._hybrid_collection_operator_final_guidance_stability_summary(
        {
            "available": True,
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "info",
            "current_guidance_message": "Stable ready state",
            "previous_distinct_guidance_label": None,
            "previous_distinct_guidance_message": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:30:00",
        }
    )
    digest_stability = server_module._hybrid_collection_operator_digest_stability_summary(
        {
            "available": True,
            "current_digest_status": "ready",
            "current_digest_priority": "info",
            "current_digest_message": "Stable ready state",
            "previous_distinct_digest_status": None,
            "previous_distinct_digest_message": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:31:00",
        }
    )
    intervention_stability = server_module._hybrid_collection_operator_intervention_stability_summary(
        {
            "available": True,
            "current_intervention_status": "ready",
            "previous_distinct_intervention_status": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:32:00",
        }
    )
    escalation_event_stability = server_module._hybrid_collection_operator_escalation_event_stability_summary(
        {
            "available": True,
            "current_operator_escalation_source": "recovery_policy",
            "current_escalation_kind": "repeated_repin_cycle",
            "current_operator_escalation_audit_message": "audit",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": "unknown",
            "last_source_change_at": "2026-05-18 18:33:00",
        }
    )

    assert final_guidance_stability["recent_change_count"] == 0
    assert final_guidance_stability["stability_status"] == "stable_guidance"
    assert digest_stability["recent_change_count"] == 0
    assert digest_stability["stability_status"] == "stable_digest"
    assert intervention_stability["recent_change_count"] == 0
    assert intervention_stability["stability_status"] == "stable_ready"
    assert escalation_event_stability["recent_source_change_count"] == 0
    assert escalation_event_stability["stability_status"] == "persistent_recovery_policy_source"


def test_hybrid_collection_operator_mode_switch_overview_fields_treat_unknown_switch_count_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_mode_switch_overview_fields(
        {
            "recent_switch_count": "unknown",
            "top_target_mode": "browser",
            "top_guidance_reason": "challenge_detected",
        }
    )

    assert overview["hybrid_collection_recent_mode_switch_count"] == 0
    assert overview["hybrid_collection_top_switch_target_mode"] == "browser"
    assert overview["hybrid_collection_top_switch_guidance_reason"] == "challenge_detected"


def test_hybrid_collection_lifecycle_resolution_overview_fields_treat_unknown_numeric_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    lifecycle_overview = server_module._hybrid_collection_operator_lifecycle_state_overview_fields(
        {
            "lifecycle_state": "steady",
            "lifecycle_reason": "browserless_fast_path_stable",
            "recommended_follow_up": "keep_hybrid",
            "suggested_mode": "hybrid",
            "operator_action_hint": "keep hybrid; suggested mode=hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": "unknown",
        }
    )
    resolution_overview = server_module._hybrid_collection_operator_escalation_resolution_trend_overview_fields(
        {
            "recent_resolved_count": "unknown",
            "recent_unresolved_count": "unknown",
            "recent_resolution_rate": "unknown",
        }
    )
    priority_mix_overview = server_module._hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(
        {
            "recent_high_priority_escalation_count": "unknown",
            "recent_high_priority_resolved_count": "unknown",
            "recent_high_priority_unresolved_count": "unknown",
            "top_recent_escalation_priority": "high",
            "top_recent_unresolved_priority": "high",
        }
    )

    assert lifecycle_overview["hybrid_collection_lifecycle_active_high_priority_unresolved_count"] == 0
    assert resolution_overview["hybrid_collection_recent_escalation_resolved_count"] == 0
    assert resolution_overview["hybrid_collection_recent_escalation_unresolved_count"] == 0
    assert resolution_overview["hybrid_collection_recent_escalation_resolution_rate"] == 0.0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_escalation_count"] == 0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_resolved_count"] == 0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_unresolved_count"] == 0


def test_hybrid_collection_escalation_overview_helpers_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    escalation_trend_overview = server_module._hybrid_collection_operator_escalation_event_trend_overview_fields(
        {
            "current_operator_escalation_source": "unknown",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": "unknown",
            "last_source_change_at": "unknown",
        }
    )
    escalation_stability_overview = server_module._hybrid_collection_operator_escalation_event_stability_overview_fields(
        {
            "stability_status": "unknown",
            "stability_severity": "unknown",
            "operator_readable_explanation": "unknown",
        }
    )
    priority_mix_overview = server_module._hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(
        {
            "recent_high_priority_escalation_count": "unknown",
            "recent_high_priority_resolved_count": "unknown",
            "recent_high_priority_unresolved_count": "unknown",
            "top_recent_escalation_priority": "unknown",
            "top_recent_unresolved_priority": "unknown",
        }
    )

    assert escalation_trend_overview["hybrid_collection_current_operator_escalation_source"] is None
    assert escalation_trend_overview["hybrid_collection_previous_operator_escalation_source"] is None
    assert escalation_trend_overview["hybrid_collection_operator_escalation_source_change_count"] == 0
    assert escalation_trend_overview["hybrid_collection_operator_escalation_source_last_changed_at"] is None
    assert escalation_stability_overview["hybrid_collection_operator_escalation_source_stability_status"] is None
    assert escalation_stability_overview["hybrid_collection_operator_escalation_source_stability_severity"] is None
    assert escalation_stability_overview["hybrid_collection_operator_escalation_source_stability_explanation"] is None
    assert priority_mix_overview["hybrid_collection_recent_high_priority_escalation_count"] == 0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_resolved_count"] == 0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_unresolved_count"] == 0
    assert priority_mix_overview["hybrid_collection_top_recent_escalation_priority"] is None
    assert priority_mix_overview["hybrid_collection_top_recent_unresolved_priority"] is None


def test_hybrid_collection_resolution_and_priority_overview_helpers_treat_negative_counts_as_missing():
    server_module = importlib.import_module("src.server")

    resolution_overview = server_module._hybrid_collection_operator_escalation_resolution_trend_overview_fields(
        {
            "recent_resolved_count": -2,
            "recent_unresolved_count": -3,
            "recent_resolution_rate": -0.5,
        }
    )
    priority_mix_overview = server_module._hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(
        {
            "recent_high_priority_escalation_count": -1,
            "recent_high_priority_resolved_count": -2,
            "recent_high_priority_unresolved_count": -3,
            "top_recent_escalation_priority": "high",
            "top_recent_unresolved_priority": "high",
        }
    )

    assert resolution_overview["hybrid_collection_recent_escalation_resolved_count"] == 0
    assert resolution_overview["hybrid_collection_recent_escalation_unresolved_count"] == 0
    assert resolution_overview["hybrid_collection_recent_escalation_resolution_rate"] == 0.0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_escalation_count"] == 0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_resolved_count"] == 0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_unresolved_count"] == 0


def test_hybrid_collection_resolution_overview_treats_overfull_rate_as_clamped():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_escalation_resolution_trend_overview_fields(
        {
            "recent_resolved_count": 2,
            "recent_unresolved_count": 0,
            "recent_resolution_rate": 1.5,
        }
    )

    assert overview["hybrid_collection_recent_escalation_resolved_count"] == 2
    assert overview["hybrid_collection_recent_escalation_unresolved_count"] == 0
    assert overview["hybrid_collection_recent_escalation_resolution_rate"] == 1.0


def test_http_status_can_surface_shifted_hybrid_collection_operator_final_guidance_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16g", url="https://x/stage-http-hybrid-16g"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    transitioning_message = "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    history_entries = [
        {
            "generated_at": "2026-05-18 18:10:00",
            "session_id": "final-guidance-stability-1",
            "operator_final_guidance_label": "Stable ready state",
            "operator_final_guidance_priority": "info",
            "operator_final_guidance_message": stable_message,
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "final-guidance-stability-2",
            "operator_final_guidance_label": "Transitioning intervention",
            "operator_final_guidance_priority": "warning",
            "operator_final_guidance_message": transitioning_message,
        },
    ]
    runtime_history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_operator_final_guidance_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "guidance_recently_shifted"
        assert summary["stability_severity"] == "warning"
        assert summary["current_guidance_label"] == "Transitioning intervention"
        assert summary["current_guidance_message"] == transitioning_message
        assert summary["previous_guidance_message"] == stable_message
        assert summary["recent_change_count"] == 1
        assert summary["last_change_at"] == "2026-05-18 18:12:00"
        assert summary["operator_readable_explanation"] == "Final guidance recently shifted from Stable ready state to Transitioning intervention."
        digest = body["collection_stage"]["hybrid_collection_operator_digest_summary"]
        assert digest["available"] is True
        assert digest["digest_status"] == "attention_required"
        assert digest["digest_priority"] == "warning"
        assert digest["final_guidance_message"] == transitioning_message
        assert digest["intervention_status"] == "monitor"
        assert digest["intervention_stability_status"] == "transitioning"
        assert digest["final_guidance_stability_status"] == "guidance_recently_shifted"
        assert digest["operator_digest_message"] == "Transitioning intervention: monitor until stable before resuming aggressive intervention."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_final_guidance_stability_status"] == "guidance_recently_shifted"
        assert overview["hybrid_collection_final_guidance_stability_severity"] == "warning"
        assert overview["hybrid_collection_final_guidance_stability_explanation"] == "Final guidance recently shifted from Stable ready state to Transitioning intervention."
        assert overview["hybrid_collection_operator_digest_status"] == "attention_required"
        assert overview["hybrid_collection_operator_digest_priority"] == "warning"
        assert overview["hybrid_collection_operator_digest_message"] == "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_stable_hybrid_collection_operator_final_guidance_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16h", url="https://x/stage-http-hybrid-16h"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    runtime_history_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:20:00",
                "session_id": "final-guidance-stability-3",
                "operator_final_guidance_label": "Stable ready state",
                "operator_final_guidance_priority": "info",
                "operator_final_guidance_message": stable_message,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_operator_final_guidance_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "stable_guidance"
        assert summary["stability_severity"] == "info"
        assert summary["current_guidance_label"] == "Stable ready state"
        assert summary["current_guidance_message"] == stable_message
        assert summary["previous_guidance_message"] is None
        assert summary["recent_change_count"] == 0
        assert summary["last_change_at"] is None
        assert summary["operator_readable_explanation"] == "Final guidance remains stable with no recent message changes."
        digest = body["collection_stage"]["hybrid_collection_operator_digest_summary"]
        assert digest["available"] is True
        assert digest["digest_status"] == "ready"
        assert digest["digest_priority"] == "info"
        assert digest["final_guidance_message"] == stable_message
        assert digest["intervention_status"] == "ready"
        assert digest["intervention_stability_status"] == "stable_ready"
        assert digest["final_guidance_stability_status"] == "stable_guidance"
        assert digest["operator_digest_message"] == "Stable ready state: keep hybrid and continue monitoring."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_final_guidance_stability_status"] == "stable_guidance"
        assert overview["hybrid_collection_final_guidance_stability_severity"] == "info"
        assert overview["hybrid_collection_final_guidance_stability_explanation"] == "Final guidance remains stable with no recent message changes."
        assert overview["hybrid_collection_operator_digest_status"] == "ready"
        assert overview["hybrid_collection_operator_digest_priority"] == "info"
        assert overview["hybrid_collection_operator_digest_message"] == "Stable ready state: keep hybrid and continue monitoring."
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_hybrid_collection_operator_digest_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16i", url="https://x/stage-http-hybrid-16i"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    transitioning_message = "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    history_entries = [
        {
            "generated_at": "2026-05-18 18:10:00",
            "session_id": "digest-trend-1",
            "operator_digest_status": "ready",
            "operator_digest_priority": "info",
            "operator_digest_message": stable_message,
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "digest-trend-2",
            "operator_digest_status": "attention_required",
            "operator_digest_priority": "warning",
            "operator_digest_message": transitioning_message,
        },
        {
            "generated_at": "2026-05-18 18:13:00",
            "session_id": "digest-trend-3",
            "operator_digest_status": "attention_required",
            "operator_digest_priority": "warning",
            "operator_digest_message": transitioning_message,
        },
    ]
    runtime_history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        trend_summary = body["collection_stage"]["hybrid_collection_operator_digest_trend_summary"]
        assert trend_summary["available"] is True
        assert trend_summary["recent_digest_entry_count"] == 3
        assert trend_summary["recent_digest_message_counts"] == {
            stable_message: 1,
            transitioning_message: 2,
        }
        assert trend_summary["recent_distinct_digest_message_count"] == 2
        assert trend_summary["recent_change_count"] == 1
        assert trend_summary["top_digest_message"] == transitioning_message
        assert trend_summary["current_digest_status"] == "attention_required"
        assert trend_summary["current_digest_priority"] == "warning"
        assert trend_summary["current_digest_message"] == transitioning_message
        assert trend_summary["previous_distinct_digest_status"] == "ready"
        assert trend_summary["previous_distinct_digest_message"] == stable_message
        assert trend_summary["last_change_at"] == "2026-05-18 18:12:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_current_digest_status"] == "attention_required"
        assert overview["hybrid_collection_current_digest_priority"] == "warning"
        assert overview["hybrid_collection_current_digest_message"] == transitioning_message
        assert overview["hybrid_collection_previous_digest_message"] == stable_message
        assert overview["hybrid_collection_digest_change_count"] == 1
        assert overview["hybrid_collection_digest_last_changed_at"] == "2026-05-18 18:12:00"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_operator_digest_trend_summary_treats_unknown_messages_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    history_entries = [
        {
            "generated_at": "2026-05-18 18:10:00",
            "session_id": "digest-unknown-1",
            "operator_digest_status": "ready",
            "operator_digest_priority": "info",
            "operator_digest_message": stable_message,
        },
        {
            "generated_at": "2026-05-18 18:11:00",
            "session_id": "digest-unknown-2",
            "operator_digest_status": "unknown",
            "operator_digest_priority": "unknown",
            "operator_digest_message": "unknown",
        },
    ]
    runtime_history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    trend_summary = server_module._hybrid_collection_operator_digest_trend_summary(data_root)

    assert trend_summary["available"] is True
    assert trend_summary["recent_digest_entry_count"] == 1
    assert trend_summary["recent_digest_message_counts"] == {stable_message: 1}
    assert trend_summary["recent_distinct_digest_message_count"] == 1
    assert trend_summary["recent_change_count"] == 0
    assert trend_summary["top_digest_message"] == stable_message
    assert trend_summary["current_digest_status"] == "ready"
    assert trend_summary["current_digest_priority"] == "info"
    assert trend_summary["current_digest_message"] == stable_message
    assert trend_summary["previous_distinct_digest_status"] is None
    assert trend_summary["previous_distinct_digest_message"] is None
    assert trend_summary["last_change_at"] is None


def test_hybrid_collection_operator_digest_trend_summary_treats_unknown_status_and_priority_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    runtime_history_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:10:00",
                        "session_id": "digest-unknown-meta-1",
                        "operator_digest_status": "unknown",
                        "operator_digest_priority": "unknown",
                        "operator_digest_message": stable_message,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:11:00",
                        "session_id": "digest-unknown-meta-2",
                        "operator_digest_status": "unknown",
                        "operator_digest_priority": "unknown",
                        "operator_digest_message": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trend_summary = server_module._hybrid_collection_operator_digest_trend_summary(data_root)

    assert trend_summary["available"] is True
    assert trend_summary["recent_digest_entry_count"] == 1
    assert trend_summary["recent_digest_message_counts"] == {stable_message: 1}
    assert trend_summary["recent_distinct_digest_message_count"] == 1
    assert trend_summary["recent_change_count"] == 0
    assert trend_summary["top_digest_message"] == stable_message
    assert trend_summary["current_digest_status"] is None
    assert trend_summary["current_digest_priority"] is None
    assert trend_summary["current_digest_message"] == stable_message
    assert trend_summary["previous_distinct_digest_status"] is None
    assert trend_summary["previous_distinct_digest_message"] is None
    assert trend_summary["last_change_at"] is None


def test_http_status_can_surface_shifted_hybrid_collection_operator_digest_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16j", url="https://x/stage-http-hybrid-16j"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    transitioning_message = "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    history_entries = [
        {
            "generated_at": "2026-05-18 18:10:00",
            "session_id": "digest-stability-1",
            "operator_digest_status": "ready",
            "operator_digest_priority": "info",
            "operator_digest_message": stable_message,
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "digest-stability-2",
            "operator_digest_status": "attention_required",
            "operator_digest_priority": "warning",
            "operator_digest_message": transitioning_message,
        },
    ]
    runtime_history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_operator_digest_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "digest_recently_shifted"
        assert summary["stability_severity"] == "warning"
        assert summary["current_digest_status"] == "attention_required"
        assert summary["current_digest_priority"] == "warning"
        assert summary["current_digest_message"] == transitioning_message
        assert summary["previous_digest_message"] == stable_message
        assert summary["recent_change_count"] == 1
        assert summary["last_change_at"] == "2026-05-18 18:12:00"
        assert summary["operator_readable_explanation"] == "Operator digest recently shifted from ready to attention_required."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_digest_stability_status"] == "digest_recently_shifted"
        assert overview["hybrid_collection_digest_stability_severity"] == "warning"
        assert overview["hybrid_collection_digest_stability_explanation"] == "Operator digest recently shifted from ready to attention_required."
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_stable_hybrid_collection_operator_digest_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16k", url="https://x/stage-http-hybrid-16k"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    stable_message = "Stable ready state: keep hybrid and continue monitoring."
    runtime_history_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:20:00",
                "session_id": "digest-stability-3",
                "operator_digest_status": "ready",
                "operator_digest_priority": "info",
                "operator_digest_message": stable_message,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_operator_digest_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "stable_digest"
        assert summary["stability_severity"] == "info"
        assert summary["current_digest_status"] == "ready"
        assert summary["current_digest_priority"] == "info"
        assert summary["current_digest_message"] == stable_message
        assert summary["previous_digest_message"] is None
        assert summary["recent_change_count"] == 0
        assert summary["last_change_at"] is None
        assert summary["operator_readable_explanation"] == "Operator digest remains stable with no recent message changes."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_digest_stability_status"] == "stable_digest"
        assert overview["hybrid_collection_digest_stability_severity"] == "info"
        assert overview["hybrid_collection_digest_stability_explanation"] == "Operator digest remains stable with no recent message changes."
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_hybrid_collection_operator_intervention_event_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16c", url="https://x/stage-http-hybrid-16c"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_intervention_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-18 18:11:00",
            "session_id": "intervention-evt-1",
            "transition_kind": "status_changed",
            "from_intervention_status": "ready",
            "to_intervention_status": "monitor",
            "from_intervention_required": False,
            "to_intervention_required": False,
            "from_intervention_priority": "info",
            "to_intervention_priority": "warning",
            "from_intervention_reason": "browserless_fast_path_stable",
            "to_intervention_reason": "hybrid_retrial_budget_active",
            "to_action_hint": "continue hybrid with budget watch; suggested mode=hybrid",
            "to_suggested_mode": "hybrid",
            "to_final_guidance_label": "Transitioning intervention",
            "to_final_guidance_priority": "warning",
            "to_final_guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "effective_mode": "hybrid",
            "task_url": "https://sf.taobao.com/list/50025969__2.htm?page=20",
            "task_page": 20,
        },
        {
            "generated_at": "2026-05-18 18:13:00",
            "session_id": "intervention-evt-2",
            "transition_kind": "status_changed",
            "from_intervention_status": "monitor",
            "to_intervention_status": "intervention_required",
            "from_intervention_required": False,
            "to_intervention_required": True,
            "from_intervention_priority": "warning",
            "to_intervention_priority": "high",
            "from_intervention_reason": "hybrid_retrial_budget_active",
            "to_intervention_reason": "high_priority_unresolved_escalation_backlog",
            "to_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "to_suggested_mode": "browser",
            "to_final_guidance_label": "Escalating intervention",
            "to_final_guidance_priority": "high",
            "to_final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "effective_mode": "browser",
            "task_url": "https://sf.taobao.com/list/50025969__2.htm?page=21",
            "task_page": 21,
        },
    ]
    events_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_operator_intervention_event_summary"]
        assert summary["available"] is True
        assert summary["entry_count"] == 2
        assert summary["recent_event_count"] == 2
        assert summary["recent_transition_kind_counts"] == {"status_changed": 2}
        assert summary["recent_to_intervention_status_counts"] == {
            "monitor": 1,
            "intervention_required": 1,
        }
        assert summary["top_transition_kind"] == "status_changed"
        assert summary["top_to_intervention_status"] == "intervention_required"
        assert summary["last_event_at"] == "2026-05-18 18:13:00"
        assert summary["last_event_session_id"] == "intervention-evt-2"
        assert summary["last_transition_kind"] == "status_changed"
        assert summary["last_to_intervention_status"] == "intervention_required"
        assert summary["last_to_intervention_priority"] == "high"
        assert summary["last_to_final_guidance_label"] == "Escalating intervention"
        assert summary["last_to_final_guidance_priority"] == "high"
        assert summary["last_to_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_intervention_event_count"] == 2
        assert overview["hybrid_collection_last_intervention_event_at"] == "2026-05-18 18:13:00"
        assert overview["hybrid_collection_last_intervention_transition_kind"] == "status_changed"
        assert overview["hybrid_collection_last_to_intervention_status"] == "intervention_required"
        assert overview["hybrid_collection_last_to_intervention_priority"] == "high"
        assert overview["hybrid_collection_last_to_final_guidance_label"] == "Escalating intervention"
        assert overview["hybrid_collection_last_to_final_guidance_priority"] == "high"
        assert overview["hybrid_collection_last_to_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_escalating_hybrid_collection_operator_intervention_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16d", url="https://x/stage-http-hybrid-16d"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    runtime_history_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:10:00",
                        "session_id": "intervention-stability-1",
                        "intervention_status": "ready",
                        "intervention_priority": "info",
                        "intervention_reason": "browserless_fast_path_stable",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:12:00",
                        "session_id": "intervention-stability-2",
                        "intervention_status": "intervention_required",
                        "intervention_priority": "high",
                        "intervention_reason": "high_priority_unresolved_escalation_backlog",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_operator_intervention_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "escalating"
        assert summary["stability_severity"] == "high"
        assert summary["current_intervention_status"] == "intervention_required"
        assert summary["previous_intervention_status"] == "ready"
        assert summary["recent_change_count"] == 1
        assert summary["last_change_at"] == "2026-05-18 18:12:00"
        assert summary["operator_readable_explanation"] == "Intervention escalated from ready to intervention_required recently."
        assert summary["stability_action_hint"] == "prefer browser and investigate escalating intervention"
        final_guidance = body["collection_stage"]["hybrid_collection_operator_final_guidance_summary"]
        assert final_guidance["available"] is True
        assert final_guidance["guidance_label"] == "Escalating intervention"
        assert final_guidance["guidance_priority"] == "high"
        assert final_guidance["guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
        assert final_guidance["preferred_action_hint"] == "prefer browser and investigate escalating intervention"
        assert final_guidance["suggested_mode"] == "browser"
        assert final_guidance["intervention_status"] == "intervention_required"
        assert final_guidance["stability_status"] == "escalating"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_intervention_stability_status"] == "escalating"
        assert overview["hybrid_collection_intervention_stability_severity"] == "high"
        assert overview["hybrid_collection_intervention_stability_explanation"] == "Intervention escalated from ready to intervention_required recently."
        assert overview["hybrid_collection_intervention_stability_action_hint"] == "prefer browser and investigate escalating intervention"
        assert overview["hybrid_collection_operator_final_guidance_label"] == "Escalating intervention"
        assert overview["hybrid_collection_operator_final_guidance_priority"] == "high"
        assert overview["hybrid_collection_operator_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_stable_ready_hybrid_collection_operator_intervention_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16e", url="https://x/stage-http-hybrid-16e"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    runtime_history_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:20:00",
                "session_id": "intervention-stability-3",
                "intervention_status": "ready",
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_operator_intervention_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "stable_ready"
        assert summary["stability_severity"] == "info"
        assert summary["current_intervention_status"] == "ready"
        assert summary["previous_intervention_status"] is None
        assert summary["recent_change_count"] == 0
        assert summary["last_change_at"] is None
        assert summary["operator_readable_explanation"] == "Intervention remains ready with no recent status changes."
        assert summary["stability_action_hint"] == "keep hybrid and continue monitoring"
        final_guidance = body["collection_stage"]["hybrid_collection_operator_final_guidance_summary"]
        assert final_guidance["available"] is True
        assert final_guidance["guidance_label"] == "Stable ready state"
        assert final_guidance["guidance_priority"] == "info"
        assert final_guidance["guidance_message"] == "Stable ready state: keep hybrid and continue monitoring."
        assert final_guidance["preferred_action_hint"] == "keep hybrid and continue monitoring"
        assert final_guidance["suggested_mode"] == "hybrid"
        assert final_guidance["intervention_status"] == "ready"
        assert final_guidance["stability_status"] == "stable_ready"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_intervention_stability_status"] == "stable_ready"
        assert overview["hybrid_collection_intervention_stability_severity"] == "info"
        assert overview["hybrid_collection_intervention_stability_explanation"] == "Intervention remains ready with no recent status changes."
        assert overview["hybrid_collection_intervention_stability_action_hint"] == "keep hybrid and continue monitoring"
        assert overview["hybrid_collection_operator_final_guidance_label"] == "Stable ready state"
        assert overview["hybrid_collection_operator_final_guidance_priority"] == "info"
        assert overview["hybrid_collection_operator_final_guidance_message"] == "Stable ready state: keep hybrid and continue monitoring."
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_hybrid_collection_strategy_guidance(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-3", url="https://x/stage-http-hybrid-3"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:05:00",
                "runner_mode": "hybrid",
                "loop_mode": True,
                "submit_enabled": True,
                "session_id": "guidance-live",
                "decision_counts": {"browser_fallback_required": 1},
                "reason_counts": {"challenge_detected": 1},
                "top_fallback_reason": "challenge_detected",
                "termination_reason": "fallback_escalation_threshold_reached",
                "last_decision": "browser_fallback_required",
                "last_reason": "challenge_detected",
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=9", "page": 9},
                "last_probe_summary": {"item_count": 0, "has_script": False, "body_has_challenge": True, "body_has_punish": True},
                "last_submit_result": {},
                "last_browser_fallback_opened": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:01:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "fallback_escalation_threshold_reached",
            "session_id": "g-1",
        },
        {
            "generated_at": "2026-05-18 18:02:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "g-2",
        },
        {
            "generated_at": "2026-05-18 18:03:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "fallback_escalation_threshold_reached",
            "session_id": "g-3",
        },
        {
            "generated_at": "2026-05-18 18:04:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "stop_on_fallback",
            "session_id": "g-4",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        guidance = body["collection_stage"]["hybrid_collection_strategy_guidance"]
        assert guidance["guidance_status"] == "investigate_challenge_spike"
        assert guidance["priority"] == "high"
        assert guidance["recommended_mode"] == "browser"
        assert guidance["top_guidance_reason"] == "challenge_detected"
        assert "review_challenge_recovery_path" in guidance["recommended_actions"]
        assert "switch_operator_mode_to_browser" in guidance["recommended_actions"]
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_guidance_status"] == "investigate_challenge_spike"
        assert overview["hybrid_collection_recommended_mode"] == "browser"
        assert overview["hybrid_collection_guidance_priority"] == "high"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_operator_intervention_event_summary_treats_unknown_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_intervention_events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:11:00",
                        "session_id": "intervention-unknown-1",
                        "transition_kind": "status_changed",
                        "to_intervention_status": "monitor",
                        "to_intervention_priority": "warning",
                        "to_final_guidance_label": "Transitioning intervention",
                        "to_final_guidance_priority": "warning",
                        "to_final_guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "unknown",
                        "transition_kind": "unknown",
                        "to_intervention_status": "unknown",
                        "to_intervention_priority": "unknown",
                        "to_final_guidance_label": "unknown",
                        "to_final_guidance_priority": "unknown",
                        "to_final_guidance_message": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_operator_intervention_event_summary(data_root)

    assert summary["available"] is True
    assert summary["entry_count"] == 2
    assert summary["recent_event_count"] == 2
    assert summary["recent_transition_kind_counts"] == {"status_changed": 1}
    assert summary["recent_to_intervention_status_counts"] == {"monitor": 1}
    assert summary["top_transition_kind"] == "status_changed"
    assert summary["top_to_intervention_status"] == "monitor"
    assert summary["last_event_at"] is None
    assert summary["last_event_session_id"] is None
    assert summary["last_transition_kind"] is None
    assert summary["last_to_intervention_status"] is None
    assert summary["last_to_intervention_priority"] is None
    assert summary["last_to_final_guidance_label"] is None
    assert summary["last_to_final_guidance_priority"] is None
    assert summary["last_to_final_guidance_message"] is None


def test_http_status_can_surface_hybrid_collection_mode_switch_event_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-4", url="https://x/stage-http-hybrid-4"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    switch_path = avm_root / "hybrid_seed_mode_switch_events.jsonl"
    switch_entries = [
        {
            "generated_at": "2026-05-18 18:11:00",
            "session_id": "s-1",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "guidance_status": "prefer_browser_fallback",
            "top_guidance_reason": "challenge_detected",
        },
        {
            "generated_at": "2026-05-18 18:12:00",
            "session_id": "s-2",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "guidance_status": "investigate_challenge_spike",
            "top_guidance_reason": "challenge_detected",
        },
    ]
    switch_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in switch_entries) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        switch_summary = body["collection_stage"]["hybrid_collection_mode_switch_event_summary"]
        assert switch_summary["available"] is True
        assert switch_summary["entry_count"] == 2
        assert switch_summary["recent_switch_count"] == 2
        assert switch_summary["recent_target_mode_counts"]["browser"] == 2
        assert switch_summary["top_target_mode"] == "browser"
        assert switch_summary["recent_guidance_status_counts"]["prefer_browser_fallback"] == 1
        assert switch_summary["recent_guidance_status_counts"]["investigate_challenge_spike"] == 1
        assert switch_summary["top_guidance_reason"] == "challenge_detected"
        assert switch_summary["last_switch_at"] == "2026-05-18 18:12:00"
        assert switch_summary["last_switch_session_id"] == "s-2"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_mode_switch_count"] == 2
        assert overview["hybrid_collection_top_switch_target_mode"] == "browser"
        assert overview["hybrid_collection_top_switch_guidance_reason"] == "challenge_detected"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_mode_switch_event_summary_treats_unknown_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    switch_path = avm_root / "hybrid_seed_mode_switch_events.jsonl"
    switch_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:11:00",
                        "session_id": "switch-unknown-1",
                        "effective_mode": "browser",
                        "guidance_status": "prefer_browser_fallback",
                        "top_guidance_reason": "challenge_detected",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "unknown",
                        "effective_mode": "unknown",
                        "guidance_status": "unknown",
                        "top_guidance_reason": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_mode_switch_event_summary(data_root)

    assert summary["available"] is True
    assert summary["entry_count"] == 2
    assert summary["recent_switch_count"] == 2
    assert summary["recent_target_mode_counts"] == {"browser": 1}
    assert summary["recent_guidance_status_counts"] == {"prefer_browser_fallback": 1}
    assert summary["top_target_mode"] == "browser"
    assert summary["top_guidance_reason"] == "challenge_detected"
    assert summary["last_switch_at"] is None
    assert summary["last_switch_session_id"] is None


def test_http_status_can_surface_hybrid_collection_recovery_policy(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-5", url="https://x/stage-http-hybrid-5"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_path = avm_root / "hybrid_seed_collection_runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:20:00",
                "runner_mode": "browser",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "guidance_applied": True,
                "guidance_status": "prefer_browser_fallback",
                "guidance_recommended_mode": "browser",
                "top_guidance_reason": "challenge_detected",
                "decision_counts": {"browser_worker_dispatched": 1},
                "reason_counts": {},
                "effective_mode_counts": {"browser": 1},
                "guidance_applied_count": 1,
                "last_effective_mode": "browser",
                "termination_reason": "max_runs_reached",
                "last_decision": "browser_worker_dispatched",
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=12", "page": 12},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:17:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "fallback_escalation_threshold_reached",
            "session_id": "rp-1",
        },
        {
            "generated_at": "2026-05-18 18:18:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "fallback_escalation_threshold_reached",
            "session_id": "rp-2",
        },
        {
            "generated_at": "2026-05-18 18:19:00",
            "runner_mode": "browser",
            "decision_counts": {"browser_worker_dispatched": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "rp-3",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    switch_path = avm_root / "hybrid_seed_mode_switch_events.jsonl"
    switch_entries = [
        {
            "generated_at": "2026-05-18 18:17:30",
            "session_id": "sw-1",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "guidance_status": "prefer_browser_fallback",
            "top_guidance_reason": "challenge_detected",
        },
        {
            "generated_at": "2026-05-18 18:18:30",
            "session_id": "sw-2",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "guidance_status": "investigate_challenge_spike",
            "top_guidance_reason": "challenge_detected",
        },
    ]
    switch_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in switch_entries) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        policy = body["collection_stage"]["hybrid_collection_recovery_policy"]
        assert policy["policy_status"] == "pin_browser_mode_temporarily"
        assert policy["priority"] == "high"
        assert policy["effective_recommended_mode"] == "browser"
        assert policy["mode_pin_active"] is True
        assert policy["top_policy_reason"] == "challenge_detected"
        assert policy["recent_mode_switch_count"] == 2
        assert policy["top_switch_target_mode"] == "browser"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recovery_policy_status"] == "pin_browser_mode_temporarily"
        assert overview["hybrid_collection_recovery_effective_mode"] == "browser"
        assert overview["hybrid_collection_recovery_mode_pin_active"] is True
        assert overview["hybrid_collection_recovery_top_policy_reason"] == "challenge_detected"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_hybrid_collection_recovery_policy_event_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-6", url="https://x/stage-http-hybrid-6"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_recovery_policy_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-18 18:21:00",
            "session_id": "rp-ev-1",
            "transition_kind": "pin_activated",
            "from_policy_status": "steady_hybrid",
            "to_policy_status": "pin_browser_mode_temporarily",
            "from_mode_pin_active": False,
            "to_mode_pin_active": True,
            "to_effective_recommended_mode": "browser",
        },
        {
            "generated_at": "2026-05-18 18:22:00",
            "session_id": "rp-ev-2",
            "transition_kind": "pin_released",
            "from_policy_status": "pin_browser_mode_temporarily",
            "to_policy_status": "allow_hybrid_retrial",
            "from_mode_pin_active": True,
            "to_mode_pin_active": False,
            "to_effective_recommended_mode": "hybrid",
        },
    ]
    events_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_recovery_policy_event_summary"]
        assert summary["available"] is True
        assert summary["entry_count"] == 2
        assert summary["recent_transition_count"] == 2
        assert summary["recent_transition_kind_counts"]["pin_activated"] == 1
        assert summary["recent_transition_kind_counts"]["pin_released"] == 1
        assert summary["recent_to_policy_status_counts"]["pin_browser_mode_temporarily"] == 1
        assert summary["recent_to_policy_status_counts"]["allow_hybrid_retrial"] == 1
        assert summary["last_transition_kind"] == "pin_released"
        assert summary["last_to_policy_status"] == "allow_hybrid_retrial"
        assert summary["last_transition_session_id"] == "rp-ev-2"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_recovery_policy_transition_count"] == 2
        assert overview["hybrid_collection_last_recovery_transition_kind"] == "pin_released"
        assert overview["hybrid_collection_last_recovery_to_policy_status"] == "allow_hybrid_retrial"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_recovery_policy_event_summary_treats_unknown_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_recovery_policy_events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:21:00",
                        "session_id": "rp-unknown-1",
                        "transition_kind": "pin_activated",
                        "to_policy_status": "pin_browser_mode_temporarily",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "unknown",
                        "transition_kind": "unknown",
                        "to_policy_status": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_policy_event_summary(data_root)

    assert summary["available"] is True
    assert summary["entry_count"] == 2
    assert summary["recent_transition_count"] == 2
    assert summary["recent_transition_kind_counts"] == {"pin_activated": 1}
    assert summary["recent_to_policy_status_counts"] == {"pin_browser_mode_temporarily": 1}
    assert summary["top_transition_kind"] == "pin_activated"
    assert summary["top_to_policy_status"] == "pin_browser_mode_temporarily"
    assert summary["last_transition_at"] is None
    assert summary["last_transition_session_id"] is None
    assert summary["last_transition_kind"] is None
    assert summary["last_to_policy_status"] is None


def test_http_status_can_surface_hybrid_collection_operator_escalation_event_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-10", url="https://x/stage-http-hybrid-10"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-18 18:23:00",
            "session_id": "oe-1",
            "escalation_kind": "repeated_repin_cycle",
            "operator_escalation_source": "recovery_policy",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "operator_escalation_audit_message": "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]",
        },
        {
            "generated_at": "2026-05-18 18:24:00",
            "session_id": "oe-2",
            "escalation_kind": "repeated_repin_cycle",
            "operator_escalation_source": "recovery_policy",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "operator_escalation_audit_message": "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]",
        },
    ]
    events_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_operator_escalation_event_summary"]
        assert summary["available"] is True
        assert summary["entry_count"] == 2
        assert summary["recent_event_count"] == 2
        assert summary["recent_escalation_kind_counts"]["repeated_repin_cycle"] == 2
        assert summary["recent_policy_status_counts"]["escalate_repeated_repin"] == 2
        assert summary["recent_operator_escalation_source_counts"]["recovery_policy"] == 2
        assert summary["top_escalation_kind"] == "repeated_repin_cycle"
        assert summary["top_operator_escalation_source"] == "recovery_policy"
        assert summary["top_policy_status"] == "escalate_repeated_repin"
        assert summary["last_event_session_id"] == "oe-2"
        assert summary["last_operator_escalation_source"] == "recovery_policy"
        assert summary["last_operator_escalation_audit_message"] == "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_operator_escalation_count"] == 2
        assert overview["hybrid_collection_top_operator_escalation_kind"] == "repeated_repin_cycle"
        assert overview["hybrid_collection_top_operator_escalation_source"] == "recovery_policy"
        assert overview["hybrid_collection_top_operator_escalation_policy_status"] == "escalate_repeated_repin"
        assert overview["hybrid_collection_last_operator_escalation_source"] == "recovery_policy"
        assert overview["hybrid_collection_last_operator_escalation_audit_message"] == "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_operator_escalation_event_summary_treats_unknown_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:23:00",
                        "session_id": "oe-unknown-1",
                        "escalation_kind": "repeated_repin_cycle",
                        "operator_escalation_source": "recovery_policy",
                        "policy_status": "escalate_repeated_repin",
                        "operator_escalation_audit_message": "audit",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "unknown",
                        "escalation_kind": "unknown",
                        "operator_escalation_source": "unknown",
                        "policy_status": "unknown",
                        "operator_escalation_audit_message": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_operator_escalation_event_summary(data_root)

    assert summary["available"] is True
    assert summary["entry_count"] == 2
    assert summary["recent_event_count"] == 2
    assert summary["recent_escalation_kind_counts"] == {"repeated_repin_cycle": 1}
    assert summary["recent_operator_escalation_source_counts"] == {"recovery_policy": 1}
    assert summary["recent_policy_status_counts"] == {"escalate_repeated_repin": 1}
    assert summary["top_escalation_kind"] == "repeated_repin_cycle"
    assert summary["top_operator_escalation_source"] == "recovery_policy"
    assert summary["top_policy_status"] == "escalate_repeated_repin"
    assert summary["last_event_at"] is None
    assert summary["last_event_session_id"] is None
    assert summary["last_operator_escalation_source"] is None
    assert summary["last_operator_escalation_audit_message"] is None


def test_http_status_can_surface_hybrid_collection_operator_escalation_event_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-10b", url="https://x/stage-http-hybrid-10b"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-18 18:23:00",
            "session_id": "oe-trend-1",
            "escalation_kind": "repeated_repin_cycle",
            "operator_escalation_source": "recovery_policy",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "operator_escalation_audit_message": "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]",
        },
        {
            "generated_at": "2026-05-18 18:24:00",
            "session_id": "oe-trend-2",
            "escalation_kind": "intervention_stability",
            "operator_escalation_source": "intervention_stability",
            "policy_status": "",
            "policy_priority": "high",
            "top_policy_reason": "unresolved_escalation_window_open",
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        },
        {
            "generated_at": "2026-05-18 18:25:00",
            "session_id": "oe-trend-3",
            "escalation_kind": "intervention_stability",
            "operator_escalation_source": "intervention_stability",
            "policy_status": "",
            "policy_priority": "high",
            "top_policy_reason": "unresolved_escalation_window_open",
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        },
    ]
    events_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_operator_escalation_event_trend_summary"]
        assert summary["available"] is True
        assert summary["recent_event_entry_count"] == 3
        assert summary["recent_operator_escalation_source_counts"] == {
            "recovery_policy": 1,
            "intervention_stability": 2,
        }
        assert summary["recent_distinct_operator_escalation_source_count"] == 2
        assert summary["recent_source_change_count"] == 1
        assert summary["top_operator_escalation_source"] == "intervention_stability"
        assert summary["current_operator_escalation_source"] == "intervention_stability"
        assert summary["current_escalation_kind"] == "intervention_stability"
        assert summary["current_operator_escalation_audit_message"] == "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
        assert summary["previous_distinct_operator_escalation_source"] == "recovery_policy"
        assert summary["last_source_change_at"] == "2026-05-18 18:24:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_current_operator_escalation_source"] == "intervention_stability"
        assert overview["hybrid_collection_previous_operator_escalation_source"] == "recovery_policy"
        assert overview["hybrid_collection_operator_escalation_source_change_count"] == 1
        assert overview["hybrid_collection_operator_escalation_source_last_changed_at"] == "2026-05-18 18:24:00"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_operator_escalation_event_trend_summary_treats_unknown_sources_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-18 18:23:00",
            "session_id": "oe-trend-unknown-1",
            "escalation_kind": "repeated_repin_cycle",
            "operator_escalation_source": "recovery_policy",
            "operator_escalation_audit_message": "Persistent intervention required [source=recovery_policy]",
        },
        {
            "generated_at": "2026-05-18 18:24:00",
            "session_id": "oe-trend-unknown-2",
            "escalation_kind": "unknown",
            "operator_escalation_source": "unknown",
            "operator_escalation_audit_message": "unknown",
        },
    ]
    events_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_operator_escalation_event_trend_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_event_entry_count"] == 1
    assert summary["recent_operator_escalation_source_counts"] == {"recovery_policy": 1}
    assert summary["recent_distinct_operator_escalation_source_count"] == 1
    assert summary["recent_source_change_count"] == 0
    assert summary["top_operator_escalation_source"] == "recovery_policy"
    assert summary["current_operator_escalation_source"] == "recovery_policy"
    assert summary["current_escalation_kind"] == "repeated_repin_cycle"
    assert summary["current_operator_escalation_audit_message"] == "Persistent intervention required [source=recovery_policy]"
    assert summary["previous_distinct_operator_escalation_source"] is None
    assert summary["last_source_change_at"] is None


def test_hybrid_collection_operator_escalation_event_trend_summary_treats_unknown_kind_and_audit_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:24:00",
                "session_id": "oe-trend-unknown-adjacent-1",
                "operator_escalation_source": "recovery_policy",
                "escalation_kind": "unknown",
                "operator_escalation_audit_message": "unknown",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_operator_escalation_event_trend_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_event_entry_count"] == 1
    assert summary["recent_operator_escalation_source_counts"] == {"recovery_policy": 1}
    assert summary["recent_distinct_operator_escalation_source_count"] == 1
    assert summary["recent_source_change_count"] == 0
    assert summary["top_operator_escalation_source"] == "recovery_policy"
    assert summary["current_operator_escalation_source"] == "recovery_policy"
    assert summary["current_escalation_kind"] is None
    assert summary["current_operator_escalation_audit_message"] is None
    assert summary["previous_distinct_operator_escalation_source"] is None
    assert summary["last_source_change_at"] is None


def test_http_status_can_surface_shifted_hybrid_collection_operator_escalation_event_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-10c", url="https://x/stage-http-hybrid-10c"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-18 18:23:00",
            "session_id": "oe-stability-1",
            "escalation_kind": "repeated_repin_cycle",
            "operator_escalation_source": "recovery_policy",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "operator_escalation_audit_message": "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]",
        },
        {
            "generated_at": "2026-05-18 18:24:00",
            "session_id": "oe-stability-2",
            "escalation_kind": "intervention_stability",
            "operator_escalation_source": "intervention_stability",
            "policy_status": "",
            "policy_priority": "high",
            "top_policy_reason": "unresolved_escalation_window_open",
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        },
    ]
    events_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_operator_escalation_event_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "source_recently_shifted"
        assert summary["stability_severity"] == "high"
        assert summary["current_operator_escalation_source"] == "intervention_stability"
        assert summary["current_escalation_kind"] == "intervention_stability"
        assert summary["current_operator_escalation_audit_message"] == "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
        assert summary["previous_operator_escalation_source"] == "recovery_policy"
        assert summary["recent_source_change_count"] == 1
        assert summary["last_source_change_at"] == "2026-05-18 18:24:00"
        assert summary["operator_readable_explanation"] == "Operator escalation source recently shifted from recovery_policy to intervention_stability."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_operator_escalation_source_stability_status"] == "source_recently_shifted"
        assert overview["hybrid_collection_operator_escalation_source_stability_severity"] == "high"
        assert overview["hybrid_collection_operator_escalation_source_stability_explanation"] == "Operator escalation source recently shifted from recovery_policy to intervention_stability."
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_persistent_hybrid_collection_operator_escalation_event_stability_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-10d", url="https://x/stage-http-hybrid-10d"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:26:00",
                "session_id": "oe-stability-3",
                "escalation_kind": "repeated_repin_cycle",
                "operator_escalation_source": "recovery_policy",
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "operator_escalation_audit_message": "Persistent intervention required: treat as sustained intervention and investigate backlog. [source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_operator_escalation_event_stability_summary"]
        assert summary["available"] is True
        assert summary["stability_status"] == "persistent_recovery_policy_source"
        assert summary["stability_severity"] == "high"
        assert summary["current_operator_escalation_source"] == "recovery_policy"
        assert summary["current_escalation_kind"] == "repeated_repin_cycle"
        assert summary["previous_operator_escalation_source"] is None
        assert summary["recent_source_change_count"] == 0
        assert summary["last_source_change_at"] is None
        assert summary["operator_readable_explanation"] == "Operator escalation source remains recovery_policy with no recent source changes."
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_operator_escalation_source_stability_status"] == "persistent_recovery_policy_source"
        assert overview["hybrid_collection_operator_escalation_source_stability_severity"] == "high"
        assert overview["hybrid_collection_operator_escalation_source_stability_explanation"] == "Operator escalation source remains recovery_policy with no recent source changes."
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_hybrid_collection_operator_escalation_recovery_event_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-11", url="https://x/stage-http-hybrid-11"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    events = [
        {
            "generated_at": "2026-05-19 00:01:00",
            "session_id": "or-1",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "escalate_repeated_repin",
            "to_policy_status": "steady_hybrid",
            "effective_mode": "hybrid",
        },
        {
            "generated_at": "2026-05-19 00:02:00",
            "session_id": "or-2",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "escalate_repeated_repin",
            "to_policy_status": "allow_hybrid_retrial",
            "effective_mode": "hybrid",
        },
    ]
    events_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_operator_escalation_recovery_event_summary"]
        assert summary["available"] is True
        assert summary["entry_count"] == 2
        assert summary["recent_recovery_count"] == 2
        assert summary["recent_transition_kind_counts"]["escalation_cleared"] == 2
        assert summary["recent_to_policy_status_counts"]["steady_hybrid"] == 1
        assert summary["recent_to_policy_status_counts"]["allow_hybrid_retrial"] == 1
        assert summary["top_transition_kind"] == "escalation_cleared"
        assert summary["last_to_policy_status"] == "allow_hybrid_retrial"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_operator_escalation_recovery_count"] == 2
        assert overview["hybrid_collection_last_operator_escalation_recovery_policy_status"] == "allow_hybrid_retrial"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_operator_escalation_recovery_event_summary_treats_unknown_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    events_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-19 00:01:00",
                        "session_id": "or-unknown-1",
                        "transition_kind": "escalation_cleared",
                        "to_policy_status": "steady_hybrid",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "unknown",
                        "session_id": "unknown",
                        "transition_kind": "unknown",
                        "to_policy_status": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_operator_escalation_recovery_event_summary(data_root)

    assert summary["available"] is True
    assert summary["entry_count"] == 2
    assert summary["recent_recovery_count"] == 2
    assert summary["recent_transition_kind_counts"] == {"escalation_cleared": 1}
    assert summary["recent_to_policy_status_counts"] == {"steady_hybrid": 1}
    assert summary["top_transition_kind"] == "escalation_cleared"
    assert summary["top_to_policy_status"] == "steady_hybrid"
    assert summary["last_event_at"] is None
    assert summary["last_event_session_id"] is None
    assert summary["last_to_policy_status"] is None


def test_hybrid_collection_unresolved_escalation_window_summary_treats_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_unresolved_escalation_window_summary(
        {
            "available": True,
            "last_event_at": "unknown",
            "top_policy_status": "unknown",
        },
        {
            "available": True,
            "last_event_at": "2026-05-18 18:41:00",
            "last_to_policy_status": "unknown",
        },
    )

    assert summary["available"] is True
    assert summary["window_status"] == "closed"
    assert summary["window_open"] is False
    assert summary["last_escalation_at"] is None
    assert summary["last_escalation_policy_status"] is None
    assert summary["last_recovery_at"] == "2026-05-18 18:41:00"
    assert summary["last_recovery_to_policy_status"] is None
    assert summary["current_window_duration_seconds"] is None
    assert summary["current_window_duration_minutes"] is None


def test_hybrid_collection_unresolved_escalation_window_summary_treats_future_duration_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_unresolved_escalation_window_summary(
        {
            "available": True,
            "last_event_at": "2099-01-01 00:00:00",
            "top_policy_status": "escalate_repeated_repin",
        },
        {
            "available": False,
        },
    )

    assert summary["available"] is True
    assert summary["window_status"] == "open"
    assert summary["window_open"] is True
    assert summary["last_escalation_at"] == "2099-01-01 00:00:00"
    assert summary["current_window_duration_seconds"] is None
    assert summary["current_window_duration_minutes"] is None


def test_http_status_can_surface_open_unresolved_escalation_window_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-12", url="https://x/stage-http-hybrid-12"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:10:00",
                "session_id": "uw-esc-1",
                "escalation_kind": "repeated_repin_cycle",
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:09:00",
                "session_id": "uw-rec-1",
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
                "effective_mode": "hybrid",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_unresolved_escalation_window_summary"]
        assert summary["available"] is True
        assert summary["window_status"] == "open"
        assert summary["window_open"] is True
        assert summary["last_escalation_policy_status"] == "escalate_repeated_repin"
        assert summary["last_escalation_at"] == "2026-05-19 00:10:00"
        assert summary["last_recovery_at"] == "2026-05-19 00:09:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_unresolved_escalation_window_open"] is True
        assert overview["hybrid_collection_unresolved_escalation_policy_status"] == "escalate_repeated_repin"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_closed_unresolved_escalation_window_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-13", url="https://x/stage-http-hybrid-13"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:10:00",
                "session_id": "cw-esc-1",
                "escalation_kind": "repeated_repin_cycle",
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:11:00",
                "session_id": "cw-rec-1",
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
                "effective_mode": "hybrid",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_unresolved_escalation_window_summary"]
        assert summary["available"] is True
        assert summary["window_status"] == "closed"
        assert summary["window_open"] is False
        assert summary["last_escalation_policy_status"] == "escalate_repeated_repin"
        assert summary["last_recovery_to_policy_status"] == "steady_hybrid"
        assert summary["last_recovery_at"] == "2026-05-19 00:11:00"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_unresolved_escalation_window_open"] is False
        assert overview["hybrid_collection_unresolved_escalation_policy_status"] == "steady_hybrid"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_open_unresolved_escalation_window_duration(tmp_path: Path, monkeypatch):
    import datetime

    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-16", url="https://x/stage-http-hybrid-16"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))

    class _FakeDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 5, 19, 0, 15, 0)

    monkeypatch.setattr(server_module.datetime, "datetime", _FakeDateTime)

    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:10:00",
                "session_id": "uwd-esc-1",
                "escalation_kind": "repeated_repin_cycle",
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_unresolved_escalation_window_summary"]
        assert summary["window_open"] is True
        assert summary["current_window_duration_seconds"] == 300
        assert summary["current_window_duration_minutes"] == 5.0
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_unresolved_escalation_duration_seconds"] == 300
        assert overview["hybrid_collection_unresolved_escalation_duration_minutes"] == 5.0
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_escalated_lifecycle_state_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-17", url="https://x/stage-http-hybrid-17"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_path = avm_root / "hybrid_seed_collection_runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:40:00",
                "runner_mode": "browser",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "effective_mode_source": "recovery_policy",
                "guidance_applied": True,
                "guidance_status": "monitor_hybrid_runtime",
                "guidance_recommended_mode": "hybrid",
                "top_guidance_reason": "repeated_repin_cycle_detected",
                "decision_counts": {"browser_worker_dispatched": 1},
                "reason_counts": {},
                "effective_mode_counts": {"browser": 1},
                "guidance_applied_count": 1,
                "last_effective_mode": "browser",
                "termination_reason": "operator_escalation",
                "last_decision": "browser_worker_dispatched",
                "last_reason": None,
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=21", "page": 21},
                "recovery_policy_status": "escalate_repeated_repin",
                "recovery_policy_priority": "high",
                "recovery_policy_mode_pin_active": True,
                "recovery_policy_effective_recommended_mode": "browser",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:40:00",
                "session_id": "life-esc-1",
                "escalation_kind": "repeated_repin_cycle",
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_lifecycle_state_summary"]
        assert summary["available"] is True
        assert summary["lifecycle_state"] == "escalated"
        assert summary["lifecycle_reason"] == "unresolved_escalation_window_open"
        assert summary["window_open"] is True
        assert summary["policy_status"] == "escalate_repeated_repin"
        assert summary["recommended_follow_up"] == "prefer_browser_and_investigate_escalation"
        assert summary["suggested_mode"] == "browser"
        assert summary["priority_hint"] == "high_priority_backlog_present"
        assert summary["active_unresolved_priority"] == "high"
        assert summary["active_high_priority_unresolved_count"] == 1
        assert summary["operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        intervention_summary = body["collection_stage"]["hybrid_collection_operator_intervention_policy_summary"]
        assert intervention_summary["available"] is True
        assert intervention_summary["intervention_status"] == "intervention_required"
        assert intervention_summary["intervention_required"] is True
        assert intervention_summary["intervention_priority"] == "high"
        assert intervention_summary["intervention_reason"] == "high_priority_unresolved_escalation_backlog"
        assert intervention_summary["preferred_operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert intervention_summary["suggested_mode"] == "browser"
        assert intervention_summary["lifecycle_state"] == "escalated"
        assert intervention_summary["window_open"] is True
        assert intervention_summary["active_high_priority_unresolved_count"] == 1
        assert intervention_summary["hint_consistency_status"] == "lifecycle_only"
        assert intervention_summary["hint_consistency_severity"] == "warning"
        assert intervention_summary["resolution_trend_available"] is True
        assert intervention_summary["recent_unresolved_count"] == 1
        assert intervention_summary["recent_resolution_rate"] == 0.0
        assert intervention_summary["recovery_latency_available"] is False
        assert intervention_summary["last_recovery_latency_minutes"] is None
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_lifecycle_state"] == "escalated"
        assert overview["hybrid_collection_lifecycle_reason"] == "unresolved_escalation_window_open"
        assert overview["hybrid_collection_lifecycle_follow_up"] == "prefer_browser_and_investigate_escalation"
        assert overview["hybrid_collection_lifecycle_suggested_mode"] == "browser"
        assert overview["hybrid_collection_lifecycle_priority_hint"] == "high_priority_backlog_present"
        assert overview["hybrid_collection_lifecycle_active_unresolved_priority"] == "high"
        assert overview["hybrid_collection_lifecycle_active_high_priority_unresolved_count"] == 1
        assert overview["hybrid_collection_lifecycle_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert overview["hybrid_collection_operator_intervention_status"] == "intervention_required"
        assert overview["hybrid_collection_operator_intervention_required"] is True
        assert overview["hybrid_collection_operator_intervention_priority"] == "high"
        assert overview["hybrid_collection_operator_intervention_reason"] == "high_priority_unresolved_escalation_backlog"
        assert overview["hybrid_collection_operator_intervention_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert overview["hybrid_collection_operator_intervention_suggested_mode"] == "browser"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_retrial_window_lifecycle_state_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-18", url="https://x/stage-http-hybrid-18"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_path = avm_root / "hybrid_seed_collection_runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:41:00",
                "runner_mode": "hybrid",
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "effective_mode_source": "guidance",
                "guidance_applied": False,
                "guidance_status": "keep_hybrid",
                "guidance_recommended_mode": "hybrid",
                "top_guidance_reason": "browserless_success_stable",
                "decision_counts": {"browserless_success": 1},
                "reason_counts": {},
                "effective_mode_counts": {"hybrid": 1},
                "guidance_applied_count": 0,
                "last_effective_mode": "hybrid",
                "termination_reason": "max_runs_reached",
                "last_decision": "browserless_success",
                "last_reason": None,
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=22", "page": 22},
                "recovery_policy_status": "allow_hybrid_retrial",
                "recovery_policy_priority": "info",
                "recovery_policy_mode_pin_active": False,
                "recovery_policy_effective_recommended_mode": "hybrid",
                "top_policy_reason": "browser_recovery_window_stabilized",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:40:30",
                "session_id": "life-rec-1",
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "allow_hybrid_retrial",
                "effective_mode": "hybrid",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:40:00",
                "session_id": "life-rec-esc-1",
                "escalation_kind": "repeated_repin_cycle",
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_lifecycle_state_summary"]
        assert summary["available"] is True
        assert summary["lifecycle_state"] == "retrial_window_open"
        assert summary["lifecycle_reason"] == "hybrid_retrial_budget_active"
        assert summary["policy_status"] == "allow_hybrid_retrial"
        assert summary["recommended_follow_up"] == "continue_hybrid_with_budget_watch"
        assert summary["suggested_mode"] == "hybrid"
        assert summary["priority_hint"] == "no_active_priority_backlog"
        assert summary["active_unresolved_priority"] is None
        assert summary["active_high_priority_unresolved_count"] == 0
        assert summary["operator_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        intervention_summary = body["collection_stage"]["hybrid_collection_operator_intervention_policy_summary"]
        assert intervention_summary["available"] is True
        assert intervention_summary["intervention_status"] == "monitor"
        assert intervention_summary["intervention_required"] is False
        assert intervention_summary["intervention_priority"] == "warning"
        assert intervention_summary["intervention_reason"] == "hybrid_retrial_budget_active"
        assert intervention_summary["preferred_operator_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert intervention_summary["suggested_mode"] == "hybrid"
        assert intervention_summary["lifecycle_state"] == "retrial_window_open"
        assert intervention_summary["window_open"] is False
        assert intervention_summary["active_high_priority_unresolved_count"] == 0
        assert intervention_summary["hint_consistency_status"] == "lifecycle_only"
        assert intervention_summary["hint_consistency_severity"] == "warning"
        assert intervention_summary["resolution_trend_available"] is True
        assert intervention_summary["recent_unresolved_count"] == 0
        assert intervention_summary["recent_resolution_rate"] == 1.0
        assert intervention_summary["recovery_latency_available"] is True
        assert intervention_summary["last_recovery_latency_minutes"] == 0.5
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_lifecycle_state"] == "retrial_window_open"
        assert overview["hybrid_collection_lifecycle_reason"] == "hybrid_retrial_budget_active"
        assert overview["hybrid_collection_lifecycle_follow_up"] == "continue_hybrid_with_budget_watch"
        assert overview["hybrid_collection_lifecycle_suggested_mode"] == "hybrid"
        assert overview["hybrid_collection_lifecycle_priority_hint"] == "no_active_priority_backlog"
        assert overview["hybrid_collection_lifecycle_active_unresolved_priority"] is None
        assert overview["hybrid_collection_lifecycle_active_high_priority_unresolved_count"] == 0
        assert overview["hybrid_collection_lifecycle_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert overview["hybrid_collection_operator_intervention_status"] == "monitor"
        assert overview["hybrid_collection_operator_intervention_required"] is False
        assert overview["hybrid_collection_operator_intervention_priority"] == "warning"
        assert overview["hybrid_collection_operator_intervention_reason"] == "hybrid_retrial_budget_active"
        assert overview["hybrid_collection_operator_intervention_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert overview["hybrid_collection_operator_intervention_suggested_mode"] == "hybrid"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_steady_lifecycle_state_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-19", url="https://x/stage-http-hybrid-19"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_path = avm_root / "hybrid_seed_collection_runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:42:00",
                "runner_mode": "hybrid",
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "effective_mode_source": "guidance",
                "guidance_applied": False,
                "guidance_status": "keep_hybrid",
                "guidance_recommended_mode": "hybrid",
                "top_guidance_reason": "browserless_success_stable",
                "decision_counts": {"browserless_success": 1},
                "reason_counts": {},
                "effective_mode_counts": {"hybrid": 1},
                "guidance_applied_count": 0,
                "last_effective_mode": "hybrid",
                "termination_reason": "max_runs_reached",
                "last_decision": "browserless_success",
                "last_reason": None,
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=23", "page": 23},
                "recovery_policy_status": "steady_hybrid",
                "recovery_policy_priority": "info",
                "recovery_policy_mode_pin_active": False,
                "recovery_policy_effective_recommended_mode": "hybrid",
                "top_policy_reason": "browserless_success_stable",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-19 00:39:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "life-steady-1",
        },
        {
            "generated_at": "2026-05-19 00:40:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "life-steady-2",
        },
        {
            "generated_at": "2026-05-19 00:41:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "life-steady-3",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_lifecycle_state_summary"]
        assert summary["available"] is True
        assert summary["lifecycle_state"] == "steady"
        assert summary["lifecycle_reason"] == "browserless_fast_path_stable"
        assert summary["recommended_follow_up"] == "keep_hybrid"
        assert summary["suggested_mode"] == "hybrid"
        assert summary["policy_status"] == "steady_hybrid"
        assert summary["priority_hint"] == "no_active_priority_backlog"
        assert summary["active_unresolved_priority"] is None
        assert summary["active_high_priority_unresolved_count"] == 0
        assert summary["operator_action_hint"] == "keep hybrid; suggested mode=hybrid"
        intervention_summary = body["collection_stage"]["hybrid_collection_operator_intervention_policy_summary"]
        assert intervention_summary["available"] is True
        assert intervention_summary["intervention_status"] == "ready"
        assert intervention_summary["intervention_required"] is False
        assert intervention_summary["intervention_priority"] == "info"
        assert intervention_summary["intervention_reason"] == "browserless_fast_path_stable"
        assert intervention_summary["preferred_operator_action_hint"] == "keep hybrid; suggested mode=hybrid"
        assert intervention_summary["suggested_mode"] == "hybrid"
        assert intervention_summary["lifecycle_state"] == "steady"
        assert intervention_summary["window_open"] is False
        assert intervention_summary["active_high_priority_unresolved_count"] == 0
        assert intervention_summary["hint_consistency_status"] == "lifecycle_only"
        assert intervention_summary["hint_consistency_severity"] == "warning"
        assert intervention_summary["resolution_trend_available"] is False
        assert intervention_summary["recent_unresolved_count"] == 0
        assert intervention_summary["recent_resolution_rate"] == 0.0
        assert intervention_summary["recovery_latency_available"] is False
        assert intervention_summary["last_recovery_latency_minutes"] is None
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_lifecycle_state"] == "steady"
        assert overview["hybrid_collection_lifecycle_reason"] == "browserless_fast_path_stable"
        assert overview["hybrid_collection_lifecycle_follow_up"] == "keep_hybrid"
        assert overview["hybrid_collection_lifecycle_suggested_mode"] == "hybrid"
        assert overview["hybrid_collection_lifecycle_priority_hint"] == "no_active_priority_backlog"
        assert overview["hybrid_collection_lifecycle_active_unresolved_priority"] is None
        assert overview["hybrid_collection_lifecycle_active_high_priority_unresolved_count"] == 0
        assert overview["hybrid_collection_lifecycle_action_hint"] == "keep hybrid; suggested mode=hybrid"
        assert overview["hybrid_collection_operator_intervention_status"] == "ready"
        assert overview["hybrid_collection_operator_intervention_required"] is False
        assert overview["hybrid_collection_operator_intervention_priority"] == "info"
        assert overview["hybrid_collection_operator_intervention_reason"] == "browserless_fast_path_stable"
        assert overview["hybrid_collection_operator_intervention_action_hint"] == "keep hybrid; suggested mode=hybrid"
        assert overview["hybrid_collection_operator_intervention_suggested_mode"] == "hybrid"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_aligned_hybrid_collection_action_hint_consistency_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-20", url="https://x/stage-http-hybrid-20"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_path = avm_root / "hybrid_seed_collection_runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:50:00",
                "runner_mode": "hybrid",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "effective_mode_source": "recovery_policy",
                "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
                "decision_counts": {"browser_worker_dispatched": 1},
                "reason_counts": {},
                "effective_mode_counts": {"browser": 1},
                "guidance_applied_count": 0,
                "last_effective_mode": "browser",
                "termination_reason": "operator_escalation",
                "last_decision": "browser_worker_dispatched",
                "last_reason": None,
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=25", "page": 25},
                "recovery_policy_status": "escalate_repeated_repin",
                "recovery_policy_priority": "high",
                "recovery_policy_mode_pin_active": True,
                "recovery_policy_effective_recommended_mode": "browser",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:50:00",
                "session_id": "hint-align-esc-1",
                "escalation_kind": "repeated_repin_cycle",
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_action_hint_consistency_summary"]
        assert summary["available"] is True
        assert summary["runtime_operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert summary["lifecycle_operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        assert summary["hints_match"] is True
        assert summary["consistency_status"] == "aligned"
        assert summary["drift_reason"] is None
        assert summary["consistency_severity"] == "info"
        assert summary["severity_reason"] == "aligned_hints"
        assert summary["hint_source_preference"] == "runtime_preferred"
        assert summary["preferred_hint_source_detail"] == "runtime_aligned"
        assert summary["preferred_hint_explanation"] == "Runtime and lifecycle action hints are aligned; using the runtime-preferred hint."
        assert summary["preferred_operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_action_hint_consistency_status"] == "aligned"
        assert overview["hybrid_collection_action_hint_hints_match"] is True
        assert overview["hybrid_collection_action_hint_drift_reason"] is None
        assert overview["hybrid_collection_action_hint_consistency_severity"] == "info"
        assert overview["hybrid_collection_action_hint_severity_reason"] == "aligned_hints"
        assert overview["hybrid_collection_action_hint_source_preference"] == "runtime_preferred"
        assert overview["hybrid_collection_action_hint_source_detail"] == "runtime_aligned"
        assert overview["hybrid_collection_action_hint_explanation"] == "Runtime and lifecycle action hints are aligned; using the runtime-preferred hint."
        assert overview["hybrid_collection_preferred_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_lifecycle_only_hybrid_collection_action_hint_consistency_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-21", url="https://x/stage-http-hybrid-21"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_path = avm_root / "hybrid_seed_collection_runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:51:00",
                "runner_mode": "hybrid",
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "effective_mode_source": "guidance",
                "decision_counts": {"browserless_success": 1},
                "reason_counts": {},
                "effective_mode_counts": {"hybrid": 1},
                "guidance_applied_count": 0,
                "last_effective_mode": "hybrid",
                "termination_reason": "max_runs_reached",
                "last_decision": "browserless_success",
                "last_reason": None,
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=26", "page": 26},
                "recovery_policy_status": "allow_hybrid_retrial",
                "recovery_policy_priority": "info",
                "recovery_policy_mode_pin_active": False,
                "recovery_policy_effective_recommended_mode": "hybrid",
                "top_policy_reason": "browser_recovery_window_stabilized",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:50:30",
                "session_id": "hint-lifecycle-only-rec-1",
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "allow_hybrid_retrial",
                "effective_mode": "hybrid",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_action_hint_consistency_summary"]
        assert summary["available"] is True
        assert summary["runtime_operator_action_hint"] is None
        assert summary["lifecycle_operator_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        assert summary["hints_match"] is False
        assert summary["consistency_status"] == "lifecycle_only"
        assert summary["drift_reason"] == "runtime_missing"
        assert summary["consistency_severity"] == "warning"
        assert summary["severity_reason"] == "runtime_missing_lifecycle_fallback"
        assert summary["hint_source_preference"] == "lifecycle_preferred"
        assert summary["preferred_hint_source_detail"] == "lifecycle_fallback_used"
        assert summary["preferred_hint_explanation"] == "Runtime action hint is missing; using the lifecycle fallback hint."
        assert summary["preferred_operator_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_action_hint_consistency_status"] == "lifecycle_only"
        assert overview["hybrid_collection_action_hint_hints_match"] is False
        assert overview["hybrid_collection_action_hint_drift_reason"] == "runtime_missing"
        assert overview["hybrid_collection_action_hint_consistency_severity"] == "warning"
        assert overview["hybrid_collection_action_hint_severity_reason"] == "runtime_missing_lifecycle_fallback"
        assert overview["hybrid_collection_action_hint_source_preference"] == "lifecycle_preferred"
        assert overview["hybrid_collection_action_hint_source_detail"] == "lifecycle_fallback_used"
        assert overview["hybrid_collection_action_hint_explanation"] == "Runtime action hint is missing; using the lifecycle fallback hint."
        assert overview["hybrid_collection_preferred_action_hint"] == "continue hybrid with budget watch; suggested mode=hybrid"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_escalation_resolution_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-14", url="https://x/stage-http-hybrid-14"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_events = [
        {
            "generated_at": "2026-05-19 00:20:00",
            "session_id": "trend-esc-1",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        },
        {
            "generated_at": "2026-05-19 00:21:00",
            "session_id": "trend-esc-2",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        },
        {
            "generated_at": "2026-05-19 00:22:00",
            "session_id": "trend-esc-3",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        },
    ]
    escalation_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in escalation_events) + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_events = [
        {
            "generated_at": "2026-05-19 00:20:30",
            "session_id": "trend-rec-1",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "escalate_repeated_repin",
            "to_policy_status": "steady_hybrid",
            "effective_mode": "hybrid",
        },
        {
            "generated_at": "2026-05-19 00:21:30",
            "session_id": "trend-rec-2",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "escalate_repeated_repin",
            "to_policy_status": "allow_hybrid_retrial",
            "effective_mode": "hybrid",
        },
    ]
    recovery_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in recovery_events) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_escalation_resolution_trend_summary"]
        assert summary["available"] is True
        assert summary["recent_escalation_count"] == 3
        assert summary["recent_recovery_count"] == 2
        assert summary["recent_resolved_count"] == 2
        assert summary["recent_unresolved_count"] == 1
        assert summary["recent_resolution_rate"] == 2 / 3
        assert summary["window_open"] is True
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_escalation_resolved_count"] == 2
        assert overview["hybrid_collection_recent_escalation_unresolved_count"] == 1
        assert overview["hybrid_collection_recent_escalation_resolution_rate"] == 2 / 3
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_hybrid_collection_recovery_latency_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-15", url="https://x/stage-http-hybrid-15"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_events = [
        {
            "generated_at": "2026-05-19 00:30:00",
            "session_id": "lat-esc-1",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        }
    ]
    escalation_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in escalation_events) + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_events = [
        {
            "generated_at": "2026-05-19 00:31:30",
            "session_id": "lat-rec-1",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "escalate_repeated_repin",
            "to_policy_status": "steady_hybrid",
            "effective_mode": "hybrid",
        }
    ]
    recovery_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in recovery_events) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_recovery_latency_summary"]
        assert summary["available"] is True
        assert summary["last_recovery_at"] == "2026-05-19 00:31:30"
        assert summary["last_recovery_from_policy_status"] == "escalate_repeated_repin"
        assert summary["last_recovery_to_policy_status"] == "steady_hybrid"
        assert summary["matched_escalation_at"] == "2026-05-19 00:30:00"
        assert summary["matched_escalation_policy_status"] == "escalate_repeated_repin"
        assert summary["last_recovery_latency_seconds"] == 90
        assert summary["last_recovery_latency_minutes"] == 1.5
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_last_recovery_latency_seconds"] == 90
        assert overview["hybrid_collection_last_recovery_latency_minutes"] == 1.5
        assert overview["hybrid_collection_last_recovery_latency_from_policy_status"] == "escalate_repeated_repin"
        assert overview["hybrid_collection_last_recovery_latency_to_policy_status"] == "steady_hybrid"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_recovery_latency_summary_treats_unknown_policy_status_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:30:00",
                "session_id": "lat-unknown-esc-1",
                "policy_status": "unknown",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:31:30",
                "session_id": "lat-unknown-rec-1",
                "from_policy_status": "unknown",
                "to_policy_status": "unknown",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_latency_summary(data_root)

    assert summary["available"] is True
    assert summary["last_recovery_at"] == "2026-05-19 00:31:30"
    assert summary["last_recovery_from_policy_status"] is None
    assert summary["last_recovery_to_policy_status"] is None
    assert summary["matched_escalation_at"] == "2026-05-19 00:30:00"
    assert summary["matched_escalation_policy_status"] is None
    assert summary["last_recovery_latency_seconds"] == 90
    assert summary["last_recovery_latency_minutes"] == 1.5


def test_hybrid_collection_recovery_latency_summary_treats_unknown_recovery_timestamp_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:30:00",
                "session_id": "lat-ts-esc-1",
                "policy_status": "escalate_repeated_repin",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "unknown",
                "session_id": "lat-ts-rec-1",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_latency_summary(data_root)

    assert summary["available"] is False
    assert summary["last_recovery_at"] is None
    assert summary["last_recovery_from_policy_status"] == "escalate_repeated_repin"
    assert summary["last_recovery_to_policy_status"] == "steady_hybrid"
    assert summary["matched_escalation_at"] is None
    assert summary["matched_escalation_policy_status"] is None
    assert summary["last_recovery_latency_seconds"] is None
    assert summary["last_recovery_latency_minutes"] is None


def test_hybrid_collection_recovery_latency_summary_treats_whitespace_escalation_timestamp_as_normalized(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": " 2026-05-19 00:30:00 ",
                "session_id": "lat-ws-esc-1",
                "policy_status": "escalate_repeated_repin",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:31:30",
                "session_id": "lat-ws-rec-1",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_latency_summary(data_root)

    assert summary["available"] is True
    assert summary["matched_escalation_at"] == "2026-05-19 00:30:00"
    assert summary["last_recovery_latency_seconds"] == 90
    assert summary["last_recovery_latency_minutes"] == 1.5


def test_hybrid_collection_recovery_latency_summary_treats_negative_latency_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-19 00:30:00",
                "session_id": "lat-neg-esc-1",
                "policy_status": "escalate_repeated_repin",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-2-19 00:31:30",
                "session_id": "lat-neg-rec-1",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_latency_summary(data_root)

    assert summary["available"] is True
    assert summary["last_recovery_at"] == "2026-2-19 00:31:30"
    assert summary["last_recovery_from_policy_status"] == "escalate_repeated_repin"
    assert summary["last_recovery_to_policy_status"] == "steady_hybrid"
    assert summary["matched_escalation_at"] == "2026-10-19 00:30:00"
    assert summary["matched_escalation_policy_status"] == "escalate_repeated_repin"
    assert summary["last_recovery_latency_seconds"] is None
    assert summary["last_recovery_latency_minutes"] is None


def test_http_status_can_surface_hybrid_collection_escalation_priority_mix_trend_summary(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-19", url="https://x/stage-http-hybrid-19"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_events = [
        {
            "generated_at": "2026-05-19 00:40:00",
            "session_id": "prio-esc-1",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        },
        {
            "generated_at": "2026-05-19 00:41:00",
            "session_id": "prio-esc-2",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "pin_browser_mode_temporarily",
            "policy_priority": "warning",
            "top_policy_reason": "challenge_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        },
        {
            "generated_at": "2026-05-19 00:42:00",
            "session_id": "prio-esc-3",
            "escalation_kind": "repeated_repin_cycle",
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
        },
    ]
    escalation_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in escalation_events) + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_events = [
        {
            "generated_at": "2026-05-19 00:40:30",
            "session_id": "prio-rec-1",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "escalate_repeated_repin",
            "to_policy_status": "steady_hybrid",
            "effective_mode": "hybrid",
        },
        {
            "generated_at": "2026-05-19 00:41:30",
            "session_id": "prio-rec-2",
            "transition_kind": "escalation_cleared",
            "from_policy_status": "pin_browser_mode_temporarily",
            "to_policy_status": "allow_hybrid_retrial",
            "effective_mode": "hybrid",
        },
    ]
    recovery_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in recovery_events) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        summary = body["collection_stage"]["hybrid_collection_escalation_priority_mix_trend_summary"]
        assert summary["available"] is True
        assert summary["recent_escalation_priority_counts"] == {"high": 2, "warning": 1}
        assert summary["recent_resolved_priority_counts"] == {"high": 1, "warning": 1}
        assert summary["recent_unresolved_priority_counts"] == {"high": 1}
        assert summary["recent_high_priority_escalation_count"] == 2
        assert summary["recent_high_priority_resolved_count"] == 1
        assert summary["recent_high_priority_unresolved_count"] == 1
        assert summary["top_recent_escalation_priority"] == "high"
        assert summary["top_recent_unresolved_priority"] == "high"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recent_high_priority_escalation_count"] == 2
        assert overview["hybrid_collection_recent_high_priority_resolved_count"] == 1
        assert overview["hybrid_collection_recent_high_priority_unresolved_count"] == 1
        assert overview["hybrid_collection_top_recent_escalation_priority"] == "high"
        assert overview["hybrid_collection_top_recent_unresolved_priority"] == "high"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hybrid_collection_escalation_priority_mix_trend_summary_treats_unknown_priorities_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-19 00:40:00",
                        "session_id": "prio-unknown-1",
                        "policy_priority": "unknown",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-19 00:41:00",
                        "session_id": "prio-unknown-2",
                        "policy_priority": "high",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:41:30",
                "session_id": "prio-rec-unknown-1",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_escalation_priority_mix_trend_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_escalation_priority_counts"] == {"high": 1}
    assert summary["recent_resolved_priority_counts"] == {"high": 1}
    assert summary["recent_unresolved_priority_counts"] == {}
    assert summary["recent_high_priority_escalation_count"] == 1
    assert summary["recent_high_priority_resolved_count"] == 1
    assert summary["recent_high_priority_unresolved_count"] == 0
    assert summary["top_recent_escalation_priority"] == "high"
    assert summary["top_recent_resolved_priority"] == "high"
    assert summary["top_recent_unresolved_priority"] is None


def test_hybrid_collection_escalation_priority_mix_trend_summary_treats_unknown_recovery_timestamp_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    escalation_path = avm_root / "hybrid_seed_operator_escalation_events.jsonl"
    escalation_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19 00:41:00",
                "session_id": "prio-ts-1",
                "policy_priority": "high",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    recovery_path = avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    recovery_path.write_text(
        json.dumps(
            {
                "generated_at": "unknown",
                "session_id": "prio-rec-ts-1",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_escalation_priority_mix_trend_summary(data_root)

    assert summary["available"] is True
    assert summary["recent_escalation_priority_counts"] == {"high": 1}
    assert summary["recent_resolved_priority_counts"] == {}
    assert summary["recent_unresolved_priority_counts"] == {"high": 1}
    assert summary["recent_high_priority_escalation_count"] == 1
    assert summary["recent_high_priority_resolved_count"] == 0
    assert summary["recent_high_priority_unresolved_count"] == 1
    assert summary["top_recent_escalation_priority"] == "high"
    assert summary["top_recent_resolved_priority"] is None
    assert summary["top_recent_unresolved_priority"] == "high"


def test_http_status_can_surface_re_pin_browser_mode_temporarily_after_failed_release_window(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-7", url="https://x/stage-http-hybrid-7"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_path = avm_root / "hybrid_seed_collection_runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:30:00",
                "runner_mode": "hybrid",
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "effective_mode_source": "guidance",
                "guidance_applied": False,
                "guidance_status": "keep_hybrid",
                "guidance_recommended_mode": "hybrid",
                "top_guidance_reason": "browserless_success_stable",
                "decision_counts": {"browser_fallback_required": 1},
                "reason_counts": {"challenge_detected": 1},
                "effective_mode_counts": {"hybrid": 1},
                "guidance_applied_count": 0,
                "last_effective_mode": "hybrid",
                "termination_reason": "stop_on_fallback",
                "last_decision": "browser_fallback_required",
                "last_reason": "challenge_detected",
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=13", "page": 13},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:27:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "guard-1",
        },
        {
            "generated_at": "2026-05-18 18:28:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "guard-2",
        },
        {
            "generated_at": "2026-05-18 18:29:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "guard-3",
        },
        {
            "generated_at": "2026-05-18 18:30:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "stop_on_fallback",
            "session_id": "guard-4",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    switch_path = avm_root / "hybrid_seed_mode_switch_events.jsonl"
    switch_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:25:30",
                "session_id": "guard-switch-1",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "guidance_status": "prefer_browser_fallback",
                "top_guidance_reason": "challenge_detected",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    recovery_events_path = avm_root / "hybrid_seed_recovery_policy_events.jsonl"
    recovery_events_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:26:00",
                "session_id": "guard-release-1",
                "transition_kind": "pin_released",
                "from_policy_status": "pin_browser_mode_temporarily",
                "to_policy_status": "allow_hybrid_retrial",
                "from_mode_pin_active": True,
                "to_mode_pin_active": False,
                "from_effective_recommended_mode": "browser",
                "to_effective_recommended_mode": "hybrid",
                "from_top_policy_reason": "challenge_detected",
                "to_top_policy_reason": "browser_recovery_window_stabilized",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        policy = body["collection_stage"]["hybrid_collection_recovery_policy"]
        assert policy["policy_status"] == "re_pin_browser_mode_temporarily"
        assert policy["priority"] == "high"
        assert policy["effective_recommended_mode"] == "browser"
        assert policy["mode_pin_active"] is True
        assert policy["top_policy_reason"] == "challenge_detected_after_release"
        assert "re_pin_browser_mode" in policy["recommended_actions"]
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recovery_policy_status"] == "re_pin_browser_mode_temporarily"
        assert overview["hybrid_collection_recovery_effective_mode"] == "browser"
        assert overview["hybrid_collection_recovery_mode_pin_active"] is True
        assert overview["hybrid_collection_recovery_top_policy_reason"] == "challenge_detected_after_release"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_hybrid_retrial_budget_after_pin_release(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-8", url="https://x/stage-http-hybrid-8"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_path = avm_root / "hybrid_seed_collection_runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:40:00",
                "runner_mode": "hybrid",
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "effective_mode_source": "guidance",
                "guidance_applied": False,
                "guidance_status": "keep_hybrid",
                "guidance_recommended_mode": "hybrid",
                "top_guidance_reason": "browserless_success_stable",
                "decision_counts": {"browserless_success": 1},
                "reason_counts": {},
                "effective_mode_counts": {"hybrid": 1},
                "guidance_applied_count": 0,
                "last_effective_mode": "hybrid",
                "termination_reason": "max_runs_reached",
                "last_decision": "browserless_success",
                "last_reason": None,
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=14", "page": 14},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:37:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "budget-1",
        },
        {
            "generated_at": "2026-05-18 18:38:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "budget-2",
        },
        {
            "generated_at": "2026-05-18 18:39:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "budget-3",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    switch_path = avm_root / "hybrid_seed_mode_switch_events.jsonl"
    switch_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:35:30",
                "session_id": "budget-switch-1",
                "requested_mode": "hybrid",
                "effective_mode": "browser",
                "guidance_status": "prefer_browser_fallback",
                "top_guidance_reason": "challenge_detected",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    recovery_events_path = avm_root / "hybrid_seed_recovery_policy_events.jsonl"
    recovery_events_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:39:30",
                "session_id": "budget-release-1",
                "transition_kind": "pin_released",
                "from_policy_status": "pin_browser_mode_temporarily",
                "to_policy_status": "allow_hybrid_retrial",
                "from_mode_pin_active": True,
                "to_mode_pin_active": False,
                "from_effective_recommended_mode": "browser",
                "to_effective_recommended_mode": "hybrid",
                "from_top_policy_reason": "challenge_detected",
                "to_top_policy_reason": "browser_recovery_window_stabilized",
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        policy = body["collection_stage"]["hybrid_collection_recovery_policy"]
        assert policy["policy_status"] == "allow_hybrid_retrial"
        assert policy["effective_recommended_mode"] == "hybrid"
        assert policy["mode_pin_active"] is False
        assert policy["hybrid_retrial_budget_total"] == 1
        assert policy["hybrid_retrial_attempts_used"] == 1
        assert policy["hybrid_retrial_budget_remaining"] == 0
        assert policy["last_recovery_transition_kind"] == "pin_released"
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recovery_budget_remaining"] == 0
        assert overview["hybrid_collection_recovery_last_transition_kind"] == "pin_released"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_can_surface_escalate_repeated_repin_after_multiple_release_cycles(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="stage-http-hybrid-9", url="https://x/stage-http-hybrid-9"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    runtime_path = avm_root / "hybrid_seed_collection_runtime.json"
    runtime_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:50:00",
                "runner_mode": "hybrid",
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "effective_mode_source": "guidance",
                "guidance_applied": False,
                "guidance_status": "monitor_hybrid_runtime",
                "guidance_recommended_mode": "hybrid",
                "top_guidance_reason": "mixed_runtime_signals",
                "decision_counts": {"browser_fallback_required": 1},
                "reason_counts": {"challenge_detected": 1},
                "effective_mode_counts": {"hybrid": 1},
                "guidance_applied_count": 0,
                "last_effective_mode": "hybrid",
                "termination_reason": "stop_on_fallback",
                "last_decision": "browser_fallback_required",
                "last_reason": "challenge_detected",
                "last_task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=15", "page": 15},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_entries = [
        {
            "generated_at": "2026-05-18 18:47:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browserless_success": 1},
            "reason_counts": {},
            "termination_reason": "max_runs_reached",
            "session_id": "cycle-1",
        },
        {
            "generated_at": "2026-05-18 18:48:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "stop_on_fallback",
            "session_id": "cycle-2",
        },
        {
            "generated_at": "2026-05-18 18:49:00",
            "runner_mode": "hybrid",
            "decision_counts": {"browser_fallback_required": 1},
            "reason_counts": {"challenge_detected": 1},
            "termination_reason": "stop_on_fallback",
            "session_id": "cycle-3",
        },
    ]
    history_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in history_entries) + "\n",
        encoding="utf-8",
    )

    switch_path = avm_root / "hybrid_seed_mode_switch_events.jsonl"
    switch_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:45:10",
                        "session_id": "cycle-switch-1",
                        "requested_mode": "hybrid",
                        "effective_mode": "browser",
                        "guidance_status": "prefer_browser_fallback",
                        "top_guidance_reason": "challenge_detected",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:46:10",
                        "session_id": "cycle-switch-2",
                        "requested_mode": "hybrid",
                        "effective_mode": "browser",
                        "guidance_status": "investigate_challenge_spike",
                        "top_guidance_reason": "challenge_detected",
                    },
                    ensure_ascii=False,
                ),
            ]
        ) + "\n",
        encoding="utf-8",
    )

    recovery_events_path = avm_root / "hybrid_seed_recovery_policy_events.jsonl"
    recovery_events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:45:00",
                        "session_id": "cycle-rel-1",
                        "transition_kind": "pin_released",
                        "from_policy_status": "pin_browser_mode_temporarily",
                        "to_policy_status": "allow_hybrid_retrial",
                        "from_mode_pin_active": True,
                        "to_mode_pin_active": False,
                        "from_effective_recommended_mode": "browser",
                        "to_effective_recommended_mode": "hybrid",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:46:00",
                        "session_id": "cycle-pin-1",
                        "transition_kind": "pin_activated",
                        "from_policy_status": "allow_hybrid_retrial",
                        "to_policy_status": "pin_browser_mode_temporarily",
                        "from_mode_pin_active": False,
                        "to_mode_pin_active": True,
                        "to_effective_recommended_mode": "browser",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:47:00",
                        "session_id": "cycle-rel-2",
                        "transition_kind": "pin_released",
                        "from_policy_status": "pin_browser_mode_temporarily",
                        "to_policy_status": "allow_hybrid_retrial",
                        "from_mode_pin_active": True,
                        "to_mode_pin_active": False,
                        "to_effective_recommended_mode": "hybrid",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "generated_at": "2026-05-18 18:48:00",
                        "session_id": "cycle-pin-2",
                        "transition_kind": "pin_activated",
                        "from_policy_status": "allow_hybrid_retrial",
                        "to_policy_status": "pin_browser_mode_temporarily",
                        "from_mode_pin_active": False,
                        "to_mode_pin_active": True,
                        "to_effective_recommended_mode": "browser",
                    },
                    ensure_ascii=False,
                ),
            ]
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            body = json.loads(resp.read().decode("utf-8"))
        policy = body["collection_stage"]["hybrid_collection_recovery_policy"]
        assert policy["policy_status"] == "escalate_repeated_repin"
        assert policy["priority"] == "high"
        assert policy["effective_recommended_mode"] == "browser"
        assert policy["mode_pin_active"] is True
        assert policy["top_policy_reason"] == "repeated_repin_cycle_detected"
        assert "investigate_repeated_repin_cycle" in policy["recommended_actions"]
        overview = body["collection_stage"]["operator_overview"]
        assert overview["hybrid_collection_recovery_policy_status"] == "escalate_repeated_repin"
        assert overview["hybrid_collection_recovery_effective_mode"] == "browser"
        assert overview["hybrid_collection_recovery_mode_pin_active"] is True
        assert overview["hybrid_collection_recovery_top_policy_reason"] == "repeated_repin_cycle_detected"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_receipt_control_plane_can_repair_missing_backup_from_repository_state(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_manual_review_receipt(
        {
            "action": "manual_location_review",
            "ready_signal": "location_artifacts_complete",
            "status": "ready_for_reentry",
            "payload": {
                "full_address": "A",
                "community_name": "B",
                "business_area": "C",
                "latitude": 1.0,
                "longitude": 2.0,
            },
        }
    )

    data_root = tmp_path / "datas"
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(data_root))
    monkeypatch.setattr(
        server_module,
        "load_recent_gap_audit_snapshot",
        lambda path=None: {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
            ],
        },
    )
    monkeypatch.setattr(server_module, "load_action_effectiveness_snapshot", lambda path=None: {})
    monkeypatch.setattr(server_module, "load_optimization_loop_progress_snapshot", lambda path=None: {})
    original_service = server_module.AVM_SERVICE
    original_start_time = server_module.AVM_SERVICE_START_TIME
    server_module.AVM_SERVICE = AVMService(data_dir=server_module.DATA_DIR, repository=repo)
    server_module.AVM_SERVICE_START_TIME = 0
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_control_plane_status") as resp:
            status_body = json.loads(resp.read().decode("utf-8"))
        backup_summary = status_body["manual_review_control_plane_backup"]
        assert backup_summary["backup_state"] == "in_sync"
        assert backup_summary["backup_reason"] == "repaired_missing_backup"
        assert backup_summary["all_backup_files_present"] is True
        repairs_summary = status_body["manual_review_control_plane_backup_repairs_summary"]
        assert repairs_summary["repair_count"] == 1
        assert repairs_summary["last_repair_reason"] == "repaired_missing_backup"
        integrity = status_body["manual_review_control_plane_integrity"]
        assert integrity["integrity_status"] == "repaired_recently"
        assert integrity["attention_required"] is False
        assert integrity["follow_up_recommended"] is True
        stability = status_body["manual_review_control_plane_stability"]
        assert stability["stability_status"] == "watch_repaired_repository"
        assert stability["attention_required"] is False
        assert stability["follow_up_recommended"] is True
        guidance = status_body["manual_review_control_plane_guidance"]
        assert guidance["guidance_status"] == "monitor_recent_repair"
        assert guidance["requires_operator_action"] is False
        assert guidance["priority"] == "warning"
        assert status_body["manual_review_control_plane_storage"]["state_source"] == "repository"
        assert "manual_review_receipt_jobs_summary" in status_body
        assert "manual_review_receipt_operations_summary" in status_body
        assert (data_root / "avm" / "manual_review_receipts.json").exists()

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_control_plane_backup_repairs") as resp:
            repairs_body = json.loads(resp.read().decode("utf-8"))
        assert repairs_body["repair_count"] == 1
        assert repairs_body["repairs"][0]["reason"] == "repaired_missing_backup"
        assert repairs_body["manual_review_control_plane_backup_repairs_summary"]["repair_count"] == 1

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/analysis/manual_review_control_plane_integrity_history") as resp:
            integrity_body = json.loads(resp.read().decode("utf-8"))
        assert integrity_body["transition_count"] >= 1
        assert integrity_body["history"][0]["integrity_status"] == "repaired_recently"
        assert integrity_body["manual_review_control_plane_integrity_history_summary"]["last_integrity_status"] == "repaired_recently"
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_module.AVM_SERVICE = original_service
        server_module.AVM_SERVICE_START_TIME = original_start_time


def test_http_endpoints_can_read_pending_and_item_data_from_database(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9401", title="DB Pending", url="https://x/9401"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "empty-datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/get_item?id=9401") as resp:
            item_body = json.loads(resp.read().decode("utf-8"))
        assert item_body["item_id"] == "9401"
        assert item_body["source_title"] == "DB Pending"
        assert server_module.SEEN_IDS == {}

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/get_tasks") as resp:
            task_body = json.loads(resp.read().decode("utf-8"))
        assert task_body["total"] == 1
        assert len(task_body["tasks"]) == 1
        assert task_body["tasks"][0]["id"] == "9401"
        assert task_body["tasks"][0]["url"] == "https://x/9401"
        assert server_module.SEEN_IDS == {}
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_status_and_next_task_can_use_database_pending_counts(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9451", title="DB Pending A", url="https://x/9451"), event_type="seed")
    repo.upsert_flat_item(_make_flat_item(id="9452", title="DB Pending B", url="https://x/9452"), event_type="seed")

    with repo.session_factory.begin() as session:
        audit_row = session.get(PropertyAudit, "9452")
        audit_row.detail_captured = True

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "empty-datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            status_body = json.loads(resp.read().decode("utf-8"))
        assert status_body["total_ids"] == 2
        assert status_body["ai_finalized_count"] == 0
        assert status_body["captured_count"] == 1
        assert status_body["db_mode"] is True
        assert status_body["db_total_ids"] == 2
        assert status_body["db_processed_ids"] == 0
        assert status_body["db_pending_ids"] == 2
        assert status_body["db_detail_captured_ids"] == 1
        assert len(status_body["next_batch_preview"]) >= 1
        assert server_module.SEEN_IDS == {}

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/next_task") as resp:
            next_body = json.loads(resp.read().decode("utf-8"))
        assert next_body["url"] in {"https://x/9451", "https://x/9452"}
        assert server_module.SEEN_IDS == {}
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_get_next_task_can_use_database_pending_counts(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9461", title="DB Pending Visit", url="https://x/9461"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/get_next_task",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body["task_type"] == "visit"
        assert body["id"] == "9461"
        assert body["url"] == "https://x/9461"
        assert server_module.SEEN_IDS == {}
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_update_and_analyze_can_on_demand_cache_item_from_database(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9601", title="DB Analyze", url="https://x/9601"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    submitted = []
    monkeypatch.setattr(server_module, "submit_task", lambda path: submitted.append(path))

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/update_item",
            data=json.dumps({"id": "9601", "status": "failed_timeout"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            update_body = json.loads(resp.read().decode("utf-8"))
        assert update_body["status"] == "updated"
        assert "9601" not in server_module.SEEN_IDS
        stored = repo.get_flat_item("9601")
        assert stored["status"] == "failed_timeout"

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/analyze_html",
            data=json.dumps({"id": "9601", "html": "<html>ok</html>", "status": "done"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            analyze_body = json.loads(resp.read().decode("utf-8"))
        assert analyze_body["status"] == "queued"
        assert submitted
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_analyze_html_failed_timeout_persists_without_runtime_residency(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9602", title="DB Analyze Timeout", url="https://x/9602"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    submitted = []
    monkeypatch.setattr(server_module, "submit_task", lambda path: submitted.append(path))

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/analyze_html",
            data=json.dumps({"id": "9602", "html": "<html>ok</html>", "status": "failed_timeout"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            analyze_body = json.loads(resp.read().decode("utf-8"))
        assert analyze_body["status"] == "queued"
        assert submitted == []
        stored = repo.get_flat_item("9602")
        assert stored["status"] == "failed_timeout"
        assert "9602" not in server_module.SEEN_IDS
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_area_result_persists_to_db_and_evicts_runtime_cache_in_db_first_mode(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9801", title="DB Area", url="https://x/9801"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/area_result",
            data=json.dumps({"id": "9801", "建筑面积": 88.8}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        assert "9801" not in server_module.SEEN_IDS
        stored = repo.get_flat_item("9801")
        assert stored["建筑面积"] == pytest.approx(88.8)
        assert stored["is_processed"] is True
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_api_save_and_screen_can_pull_existing_item_from_database(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        _make_flat_item(id="9701", title="DB Existing", url="https://x/9701", currentPrice="1000000"),
        event_type="seed",
    )

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False
    original_service = server_module.AVM_SERVICE
    original_start_time = server_module.AVM_SERVICE_START_TIME
    server_module.AVM_SERVICE = AVMService(data_dir=server_module.DATA_DIR, repository=repo)
    server_module.AVM_SERVICE_START_TIME = 0

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/save",
            data=json.dumps(
                {
                    "items": [
                        {
                            "id": "9701",
                            "title": "New Scan Title",
                            "url": "https://x/9701",
                            "status": "done",
                            "currentPrice": "100万",
                            "initialPrice": "80万",
                            "auction_date": "2026-05-11 10:00:00",
                        }
                    ]
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            save_body = json.loads(resp.read().decode("utf-8"))
        assert save_body["status"] == "ok"
        assert "9701" not in server_module.SEEN_IDS

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/avm/screen",
            data=json.dumps({"items": [{"id": "9701"}], "margin_threshold": 0.01}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            screen_body = json.loads(resp.read().decode("utf-8"))
        assert screen_body["total"] == 1
        assert screen_body["results"][0]["id"] == "9701"
        assert "9701" not in server_module.SEEN_IDS
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_module.AVM_SERVICE = original_service
        server_module.AVM_SERVICE_START_TIME = original_start_time


def test_process_single_file_can_work_from_database_without_runtime_preload(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        _make_flat_item(id="9901", title="DB HTML", url="https://x/9901", currentPrice="1000000"),
        event_type="seed",
    )

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []

    monkeypatch.setattr(
        server_module.llm_helper,
        "extract_auction_data",
        lambda content, item_id=None: json.dumps(
            {
                "id": 9901,
                "status": "done",
                "交易时间": "2026-05-11 10:00:00",
                "成交价格": "100万",
                "起拍价格": "80万",
                "建筑面积": "88.8㎡",
                "地点": "上海市浦东新区测试路99号",
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(server_module.llm_helper, "extract_avm_risk_features", lambda content, item_id=None: {})
    monkeypatch.setattr(server_module.llm_helper, "log_prediction_event", lambda **kwargs: None)

    html_path = Path(server_module.DATA_DIR) / "item-9901.html"
    html_path.write_text("<html><body>mock</body></html>", encoding="utf-8")

    server_module.process_single_file(str(html_path))

    stored = repo.get_flat_item("9901")
    assert stored["is_processed"] is True
    assert stored["建筑面积"] == pytest.approx(88.8)
    assert "9901" not in server_module.SEEN_IDS
    assert not html_path.exists()


def test_load_data_db_first_uses_lazy_runtime_cache_for_pending_items(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9501", title="Pending", url="https://x/9501"), event_type="seed")
    repo.upsert_flat_item(_make_flat_item(id="9502", title="Processed", url="https://x/9502"), event_type="seed")

    with repo.session_factory.begin() as session:
        audit_row = session.get(PropertyAudit, "9502")
        audit_row.is_processed = True

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "empty-datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.load_data()

    assert server_module.SEEN_IDS == {}
    assert server_module.PENDING_TASKS == []
    assert repo.count_pending_task_items() == 1
