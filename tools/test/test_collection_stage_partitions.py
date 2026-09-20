"""The observer is a partition of unique items, not occurrences or stale files."""

from sqlalchemy.orm import Session

from src.storage.models import FapaiSeedItem
from tools.test.seed_queue_repository_test_context import _ensure_nansha_job, _make_repo, _upsert_sample_seed


def test_three_stage_filters_are_disjoint_including_failures_and_reanalysis(tmp_path):
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    expected = {
        "links": {"pending_detail", "in_progress", "detail_failed", "detail_blocked"},
        "details": {"raw_detail_captured", "analysis_in_progress", "analysis_failed", "analysis_blocked"},
        "analysis": {"detail_completed"},
    }
    statuses = sorted(set.union(*expected.values()))
    for index, status in enumerate(statuses):
        item_id = str(1000 + index)
        _upsert_sample_seed(repo, item_id)
        _upsert_sample_seed(repo, item_id)
        with Session(repo.engine) as session:
            row = session.get(FapaiSeedItem, item_id)
            row.status = status
            row.final_json_path = "retained-old-analysis.json"
            session.commit()
    stage_ids = []
    for stage, allowed in expected.items():
        payload = repo.collection_observer_items(stage=stage, location_code="440115", limit=20)
        assert payload["total"] == len(allowed)
        assert {row["status"] for row in payload["items"]} == allowed
        ids = {row["item_id"] for row in payload["items"]}
        assert len(ids) == payload["total"]
        stage_ids.append(ids)
        page = repo.collection_observer_items(stage=stage, limit=1, offset=1)
        assert page["total"] == len(allowed)
        assert len(page["items"]) == (1 if len(allowed) > 1 else 0)
    assert len(set.union(*stage_ids)) == len(statuses)
    assert all(not left.intersection(right) for index, left in enumerate(stage_ids) for right in stage_ids[index + 1:])
