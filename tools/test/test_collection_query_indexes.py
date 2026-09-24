"""Index migration is reversible without modifying stored event or item data."""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


@pytest.fixture(params=["sqlite", "postgresql"])
def isolated_engine(request, tmp_path):
    if request.param == "sqlite":
        engine = create_engine("sqlite:///" + str(tmp_path / "indexes.sqlite3"))
    else:
        value = os.getenv("CROW_TEST_POSTGRES_URL")
        if not value:
            pytest.skip("Dedicated PostgreSQL test URL is not configured")
        url = make_url(value)
        if url.host not in {"127.0.0.1", "localhost"} or url.database != "crow_quality":
            pytest.fail("Only a loopback crow_quality database is accepted")
        schema = "index_test_" + uuid4().hex
        admin = create_engine(url)
        try:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        finally:
            admin.dispose()
        engine = create_engine(url.update_query_dict({"options": f"-csearch_path={schema}"}))
    try:
        yield engine
    finally:
        engine.dispose()


def test_index_migration_preserves_records_in_both_directions(isolated_engine):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20260921_0012_add_collection_query_indexes.py"
    spec = importlib.util.spec_from_file_location("collection_query_indexes", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = isolated_engine
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE fapai_seed_item (item_id TEXT PRIMARY KEY, status TEXT, first_seen_at TIMESTAMP, source_payload TEXT)"))
            connection.execute(text("CREATE TABLE property_ingest_event (id INTEGER PRIMARY KEY, event_type TEXT, created_at TIMESTAMP, event_payload TEXT)"))
            connection.execute(text("INSERT INTO fapai_seed_item VALUES ('kept', 'pending_detail', '2026-01-01', :payload)"), {"payload": '{"_raw_detail_artifacts":{"html":"kept.html"}}'})
            connection.execute(text("INSERT INTO property_ingest_event VALUES (1, 'archived', '2026-01-01', :payload)"), {"payload": '{"evidence":"retained"}'})
            before = [connection.execute(text("SELECT * FROM " + name)).all() for name in ("fapai_seed_item", "property_ingest_event")]
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                assert inspect(connection).get_indexes("fapai_seed_item")[0]["column_names"] == ["status", "first_seen_at"]
                assert inspect(connection).get_indexes("property_ingest_event")[0]["column_names"] == ["event_type", "created_at"]
                assert [connection.execute(text("SELECT * FROM " + name)).all() for name in ("fapai_seed_item", "property_ingest_event")] == before
                migration.downgrade()
            assert [connection.execute(text("SELECT * FROM " + name)).all() for name in ("fapai_seed_item", "property_ingest_event")] == before
    finally:
        engine.dispose()
