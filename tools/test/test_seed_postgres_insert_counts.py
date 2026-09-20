"""Opt-in regression against a disposable, loopback-only PostgreSQL database."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from src.storage.models import FapaiSeedItem, FapaiSeedOccurrence
from src.storage.repository import DatabaseSettings, PropertyRepository


def test_postgres_insert_counts_match_committed_rows():
    url = os.environ.get("CROW_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set CROW_TEST_POSTGRES_URL to the disposable PostgreSQL fixture")
    parsed = make_url(url)
    assert parsed.host == "127.0.0.1" and parsed.database == "crow_seed_count_test"
    repo = PropertyRepository(settings=DatabaseSettings(url=url, enabled=True, auto_create=True, enable_postgis=False))
    token = uuid4().hex
    ids = ["count-" + token + "-1", "count-" + token + "-2"]
    arguments = dict(job_key="count-" + token, progress_key="count-" + token + ":sort",
                     sort_key="sort", sort_name="sort", st_param="1", page=1,
                     source_page_url="https://sf.taobao.com/list/50025969__2.htm")
    first = repo.upsert_seed_items(**arguments, items=[{"id": item_id} for item_id in ids])
    duplicate = repo.upsert_seed_items(**arguments, items=[{"id": ids[0]}])
    another_page = repo.upsert_seed_items(**{**arguments, "page": 2}, items=[{"id": ids[0]}])
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(FapaiSeedItem).where(FapaiSeedItem.item_id.in_(ids))) == 2
        assert session.scalar(select(func.count()).select_from(FapaiSeedOccurrence).where(FapaiSeedOccurrence.item_id.in_(ids))) == 3
    assert first == {"seen": 2, "new_items": 2, "existing_items": 0, "new_occurrences": 2}
    assert duplicate == {"seen": 1, "new_items": 0, "existing_items": 1, "new_occurrences": 0}
    assert another_page == {"seen": 1, "new_items": 0, "existing_items": 1, "new_occurrences": 1}
