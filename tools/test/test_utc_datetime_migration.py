from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.engine import make_url

from alembic import command
from src.storage.models import Base, FapaiSeedItem
from src.storage.utc_datetime import UtcNaiveDateTime

ROOT = Path(__file__).resolve().parents[2]
REVISION_PATH = (
    ROOT / "alembic" / "versions" / "20260922_0013_store_system_timestamps_as_utc.py"
)
SPEC = spec_from_file_location("utc_datetime_revision", REVISION_PATH)
assert SPEC is not None and SPEC.loader is not None
REVISION = module_from_spec(SPEC)
SPEC.loader.exec_module(REVISION)

SEMANTIC_DATETIME_EXCEPTIONS = {
    ("property_listing", "auction_date"),
    ("property_listing", "auction_start_time"),
    ("property_legal_context", "appraisal_benchmark_date"),
}


def _render_migration(dialect_name: str, operation) -> str:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name=dialect_name,
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        operation()
    return output.getvalue()


def test_utc_timestamp_revision_follows_current_schema_head():
    assert REVISION.revision == "20260922_0013"
    assert REVISION.down_revision == "20260921_0012"


def test_migration_covers_all_instant_columns_but_not_civil_dates():
    model_columns = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, UtcNaiveDateTime)
    }

    assert set(REVISION.INSTANT_COLUMNS) == model_columns
    assert not (set(REVISION.INSTANT_COLUMNS) & SEMANTIC_DATETIME_EXCEPTIONS)


def test_postgresql_upgrade_and_downgrade_use_reversible_utc_interpretation():
    upgrade_sql = _render_migration("postgresql", REVISION.upgrade)
    downgrade_sql = _render_migration("postgresql", REVISION.downgrade)
    count = len(REVISION.INSTANT_COLUMNS)

    assert upgrade_sql.count(" AT TIME ZONE 'UTC'") == count
    assert upgrade_sql.count("TYPE TIMESTAMP WITH TIME ZONE") == count
    assert downgrade_sql.count(" AT TIME ZONE 'UTC'") == count
    assert downgrade_sql.count("TYPE TIMESTAMP WITHOUT TIME ZONE") == count
    for table_name, column_name in REVISION.INSTANT_COLUMNS:
        assert f"ALTER TABLE {table_name} ALTER COLUMN {column_name}" in upgrade_sql
        assert f"ALTER TABLE {table_name} ALTER COLUMN {column_name}" in downgrade_sql


def test_non_postgresql_migration_is_a_noop():
    assert _render_migration("sqlite", REVISION.upgrade) == ""
    assert _render_migration("sqlite", REVISION.downgrade) == ""


@pytest.fixture
def postgres_engine(monkeypatch):
    configured = os.environ.get("CROW_TEST_POSTGRES_URL")
    if not configured:
        pytest.skip("Dedicated PostgreSQL gate not configured")
    url = make_url(configured)
    if url.host not in {"127.0.0.1", "localhost"} or url.database != "crow_quality":
        pytest.fail("UTC migration tests require loopback crow_quality")
    schema = "utc_migration_" + uuid4().hex
    admin = create_engine(url)
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    finally:
        admin.dispose()
    engine = create_engine(
        url.update_query_dict({"options": f"-csearch_path={schema},public"})
    )
    monkeypatch.delenv("FAPAI_DB_URL", raising=False)
    try:
        yield engine
    finally:
        # Keep the isolated schema and its evidence for inspection.
        engine.dispose()


@pytest.mark.parametrize("session_zone", ["America/Los_Angeles", "Asia/Shanghai"])
def test_postgres_utc_migration_preserves_instants_and_civil_dates(
    postgres_engine, session_zone
):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    instant = datetime(2026, 11, 1, 8, 30, 17, 123456)
    lease = instant + timedelta(minutes=15)
    civil = datetime(2026, 11, 1, 1, 30, 17, 123456)
    evidence = '{"_raw_detail_artifacts":{"detail_html_path":"retained.html"}}'
    with postgres_engine.begin() as connection:
        config.attributes["connection"] = connection
        connection.execute(
            text("SELECT set_config('TimeZone', :zone, true)"), {"zone": session_zone}
        )
        command.upgrade(config, REVISION.down_revision)
        connection.execute(
            text(
                "INSERT INTO property_listing (item_id, is_deleted, created_at, updated_at, auction_date, last_synced_at) "
                "VALUES ('utc-legacy', false, :instant, :instant, :civil, NULL)"
            ),
            {"instant": instant, "civil": civil},
        )
        connection.execute(
            text(
                "INSERT INTO fapai_seed_item (item_id, status, detail_attempt_count, source_payload, "
                "created_at, updated_at, detail_lease_until) "
                "VALUES ('utc-legacy', 'raw_detail_captured', 0, :evidence, :instant, :instant, :lease)"
            ),
            {"evidence": evidence, "instant": instant, "lease": lease},
        )
        before = connection.execute(
            text(
                "SELECT source_payload FROM fapai_seed_item WHERE item_id='utc-legacy'"
            )
        ).scalar_one()

        for _cycle in range(2):
            command.upgrade(config, REVISION.revision)
            columns = {
                (table, column["name"]): column["type"]
                for table in {table for table, _name in REVISION.INSTANT_COLUMNS}
                for column in inspect(connection).get_columns(table)
            }
            assert all(columns[key].timezone for key in REVISION.INSTANT_COLUMNS)
            assert all(
                not columns[key].timezone for key in SEMANTIC_DATETIME_EXCEPTIONS
            )
            raw = connection.execute(
                text(
                    "SELECT created_at, auction_date, last_synced_at FROM property_listing WHERE item_id='utc-legacy'"
                )
            ).one()
            assert raw.created_at.astimezone(timezone.utc) == instant.replace(tzinfo=timezone.utc)
            assert raw.auction_date == civil
            assert raw.last_synced_at is None
            assert (
                connection.execute(
                    select(FapaiSeedItem.detail_lease_until)
                ).scalar_one()
                == lease
            )

            # New writers must not interpret naive UTC values in the session timezone.
            connection.execute(update(FapaiSeedItem).values(detail_lease_until=lease))
            raw_lease = connection.execute(
                text("SELECT detail_lease_until FROM fapai_seed_item")
            ).scalar_one()
            assert raw_lease.astimezone(timezone.utc) == lease.replace(tzinfo=timezone.utc)
            command.check(config)
            command.downgrade(config, REVISION.down_revision)
            restored = connection.execute(
                text(
                    "SELECT created_at, auction_date, last_synced_at FROM property_listing WHERE item_id='utc-legacy'"
                )
            ).one()
            assert tuple(restored) == (instant, civil, None)
            assert (
                connection.execute(
                    text("SELECT detail_lease_until FROM fapai_seed_item")
                ).scalar_one()
                == lease
            )
            assert (
                connection.execute(
                    text("SELECT source_payload FROM fapai_seed_item")
                ).scalar_one()
                == before
            )
        command.upgrade(config, REVISION.revision)
        command.check(config)
