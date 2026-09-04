from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from src.storage.models import FapaiSeedScanProgress


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_migration(filename: str):
    path = REPO_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_rescan_model_matches_migration_0008() -> None:
    table = FapaiSeedScanProgress.__table__

    assert table.c.last_rescan_at.nullable is True
    assert table.c.rescan_count.nullable is False
    assert str(table.c.rescan_count.server_default.arg) == "0"
    assert "ix_fapai_seed_scan_progress_last_rescan_at" in {
        index.name for index in table.indexes
    }


def test_source_platform_migration_backfills_and_downgrades_on_sqlite() -> None:
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    seed_item = sa.Table(
        "fapai_seed_item",
        metadata,
        sa.Column("item_id", sa.String(64), primary_key=True),
        sa.Column("source_item_id", sa.String(64)),
        sa.Column("source_payload", sa.JSON()),
    )
    metadata.create_all(engine)
    migration = _load_migration("20260905_0011_add_seed_item_source_platform.py")

    with engine.begin() as connection:
        connection.execute(
            seed_item.insert().values(
                item_id="legacy-1",
                source_item_id="legacy-1",
                source_payload={"source_platform": "catalog_x"},
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        columns = {column["name"]: column for column in sa.inspect(connection).get_columns("fapai_seed_item")}
        assert columns["source_platform"]["nullable"] is True
        assert connection.scalar(
            sa.text("SELECT source_platform FROM fapai_seed_item WHERE item_id = 'legacy-1'")
        ) == "catalog_x"
        assert "ix_fapai_seed_item_source_platform" in {
            index["name"] for index in sa.inspect(connection).get_indexes("fapai_seed_item")
        }

        migration.downgrade()
        assert "source_platform" not in {
            column["name"] for column in sa.inspect(connection).get_columns("fapai_seed_item")
        }
