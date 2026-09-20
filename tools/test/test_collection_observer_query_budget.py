from datetime import datetime, timedelta

from sqlalchemy import event
from sqlalchemy.orm import Session

from src.storage.models import FapaiSeedItem, FapaiSeedOccurrence, FapaiSeedScanJob
from tools.test.seed_queue_repository_test_context import _ensure_nansha_job, _make_repo, _upsert_sample_seed


def test_item_page_uses_three_queries_independent_of_page_size(tmp_path):
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    for index in range(20):
        _upsert_sample_seed(repo, str(index))
    statements = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(repo.engine, "before_cursor_execute", record)
    try:
        for limit in (1, 10, 20):
            statements.clear()
            result = repo.collection_observer_items(limit=limit)
            assert len(result["items"]) == limit
            assert all(item["latest_occurrence"] is not None for item in result["items"])
            assert len(statements) == 3
        statements.clear()
        assert repo.collection_observer_items(offset=100)["items"] == []
        assert len(statements) == 2
    finally:
        event.remove(repo.engine, "before_cursor_execute", record)


def test_batch_preserves_active_preference_archived_fallback_and_missing_jobs(tmp_path):
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    _upsert_sample_seed(repo, "active")
    with Session(repo.engine) as session:
        session.add(FapaiSeedScanJob(job_key="archived", status="archived", location_code="old", category="test"))
        session.add_all([FapaiSeedItem(item_id=item_id) for item_id in ("archived-only", "missing-job", "no-occurrence")])
        session.flush()
        now = datetime.now() + timedelta(days=1)
        for index, (item_id, job_key) in enumerate((
            ("active", "archived"), ("archived-only", "archived"), ("missing-job", "missing"),
        )):
            session.add(FapaiSeedOccurrence(
                occurrence_key=f"extra-{index}", item_id=item_id, job_key=job_key,
                progress_key="extra", sort_key="extra", st_param="1", page=1, seen_at=now,
            ))
        session.commit()
        ids = ["active", "archived-only", "missing-job", "no-occurrence"]
        batch = repo._latest_seed_occurrence_payloads(session, ids)
        for item_id in ids:
            assert batch.get(item_id) == repo._latest_seed_occurrence_payload(session, item_id)
        assert batch["active"]["job_key"] != "archived"
        assert batch["archived-only"]["job_key"] == "archived"
        assert batch["missing-job"]["location_code"] is None
        assert "no-occurrence" not in batch
