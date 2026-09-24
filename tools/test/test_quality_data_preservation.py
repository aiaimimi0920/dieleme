from datetime import datetime, timedelta

import pytest

from jobs.job_manager import JobManager
from src.storage.models import FapaiSeedItem, FapaiSeedScanProgress, PropertySearchTask
from src.storage.repository import DatabaseSettings, PropertyRepository
from sqlalchemy.orm import Session


pytestmark = pytest.mark.security


@pytest.fixture
def repository(tmp_path):
    repo = PropertyRepository(DatabaseSettings(
        url=f"sqlite:///{(tmp_path / 'quality.sqlite3').as_posix()}",
        echo=False, enable_postgis=False, auto_create=True, enabled=True,
    ))
    repo.initialize()
    yield repo
    repo.engine.dispose()


def scan(repo, item):
    return repo.upsert_seed_items(
        job_key="test-job", progress_key="test-job::default", sort_key="default",
        sort_name="Default", st_param="0", page=1,
        source_page_url="https://sf.taobao.com/list/50025969__2.htm", items=[item],
    )


def test_rescan_preserves_archived_evidence_and_internal_state(repository):
    scan(repository, {"id": "1001", "title": "first", "evidence": "retained"})
    internal = {
        "_raw_detail_artifacts": {"detail_html_path": "archive/detail.html"},
        "_analysis_attempt_count": 2,
        "_blocked_recovery": {"reason": "needs_review"},
    }
    with repository.session_factory.begin() as session:
        row = session.get(FapaiSeedItem, "1001")
        row.status = "raw_detail_captured"
        row.source_payload = {**row.source_payload, **internal}
    scan(repository, {"id": "1001", "title": "updated", "_analysis_attempt_count": 0})
    with repository.session_factory() as session:
        row = session.get(FapaiSeedItem, "1001")
        assert row.status == "raw_detail_captured"
        assert row.source_payload["title"] == "updated"
        assert row.source_payload["evidence"] == "retained"
        for key, value in internal.items():
            assert row.source_payload[key] == value


def test_new_seed_cannot_inject_internal_state(repository):
    scan(repository, {"id": "1002", "_raw_detail_artifacts": {"detail_html_path": "injected"}})
    with repository.session_factory() as session:
        assert "_raw_detail_artifacts" not in session.get(FapaiSeedItem, "1002").source_payload


@pytest.mark.parametrize("kind", ["search", "page", "detail"])
def test_short_claim_cannot_steal_long_valid_lease(repository, kind):
    until = datetime.utcnow() + timedelta(hours=1)
    with repository.session_factory.begin() as session:
        if kind == "search":
            session.add(PropertySearchTask(
                task_key="440115:50025969:2", location_code="440115", category="50025969",
                sort_param="2", status="in_progress", leased_by="owner", lease_until=until,
            ))
        elif kind == "detail":
            session.add(FapaiSeedItem(
                item_id="1003", source_item_id="1003", source_platform="taobao",
                status="in_progress", detail_leased_by="owner", detail_lease_until=until,
                source_payload={"id": "1003"},
            ))
    if kind == "page":
        repository.ensure_seed_scan_job(
            {"job_key": "lease-job", "location_code": "440115", "category": "50025969"},
            sort_specs=[{"sort_key": "default", "sort_name": "Default", "st_param": "0"}],
        )
        with repository.session_factory.begin() as session:
            row = session.get(FapaiSeedScanProgress, "lease-job:default")
            row.status, row.leased_by, row.lease_until = "in_progress", "owner", until
    claim = {"search": repository.claim_search_task, "page": repository.claim_seed_scan_page,
             "detail": repository.claim_seed_detail_item}[kind]
    assert claim("contender", lease_seconds=1) is None


@pytest.mark.parametrize("contents", [b'{"all_done":false,', b'[]', b'null', b'\xff'])
def test_corrupt_job_file_is_preserved_and_never_treated_as_empty(tmp_path, contents):
    path = tmp_path / "4401.json"
    path.write_bytes(contents)
    manager = JobManager(str(tmp_path))
    with pytest.raises((ValueError, UnicodeError)):
        manager.get_next_job("worker")
    assert path.read_bytes() == contents


def test_missing_job_file_still_starts_empty(tmp_path):
    manager = JobManager(str(tmp_path))
    assert manager._load_job_file(str(tmp_path / "missing.json")) == {"all_done": False}


def test_fallback_insert_conflict_does_not_rollback_other_seed_items(repository, monkeypatch):
    scan(repository, {"id": "1002"})
    original_get = Session.get
    injected = False

    def raced_get(session, entity, identity, **kwargs):
        nonlocal injected
        if entity is FapaiSeedItem and identity == "1002" and not injected:
            injected = True
            return None
        return original_get(session, entity, identity, **kwargs)

    monkeypatch.setattr(repository.engine.dialect, "name", "fallback-test")
    monkeypatch.setattr(Session, "get", raced_get)
    result = repository.upsert_seed_items(
        job_key="test-job", progress_key="test-job::default", sort_key="default",
        sort_name="Default", st_param="0", page=1,
        source_page_url="https://sf.taobao.com/list/50025969__2.htm", items=[{"id": "1001"}, {"id": "1002"}],
    )
    assert result["new_items"] == 1
    assert result["existing_items"] == 1
    with repository.session_factory() as session:
        assert session.get(FapaiSeedItem, "1001") is not None
        assert session.get(FapaiSeedItem, "1002") is not None


def test_missing_artifact_on_claiming_node_does_not_permanently_block_data(repository, tmp_path):
    scan(repository, {"id": "1004"})
    original = str(tmp_path / "not-mounted" / "detail.html")
    with repository.session_factory.begin() as session:
        row = session.get(FapaiSeedItem, "1004")
        row.status = "raw_detail_captured"
        row.source_payload = {**row.source_payload, "_raw_detail_artifacts": {"detail_html_path": original}}
    claimed = repository.claim_seed_raw_detail_item("analysis-worker")
    assert claimed is not None
    repository.mark_seed_detail_analysis_failed("1004", "artifact temporarily unavailable", retryable=True)
    with repository.session_factory() as session:
        row = session.get(FapaiSeedItem, "1004")
        assert row.status == "analysis_failed"
        assert row.source_payload["_raw_detail_artifacts"]["detail_html_path"] == original
