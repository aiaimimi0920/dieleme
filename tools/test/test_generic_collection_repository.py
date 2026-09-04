from __future__ import annotations

from pathlib import Path

from src.storage.canonical_backfill import backfill_canonical_payloads
from src.storage.models import PropertyListing
from src.storage.repository import DatabaseSettings, PropertyRepository


def _make_repository(tmp_path: Path) -> PropertyRepository:
    database_path = tmp_path / "generic-collection.sqlite3"
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{database_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def test_repository_uses_generic_readiness_for_non_taobao_sources(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    repository.upsert_flat_item(
        {
            "id": "sku-7",
            "source_item_id": "sku-7",
            "source_platform": "catalog_x",
            "url": "https://catalog.example/items/sku-7",
            "detail_archive_path": "html/sku-7.html",
            "detail_captured": True,
        },
        event_type="detail_archived",
    )

    db_item = repository.get_flat_item("sku-7")
    assert db_item is not None
    assert db_item["source_platform"] == "catalog_x"
    assert db_item["detail_status"] == "archived"
    assert db_item["analysis_status"] == "ready"
    assert db_item["analysis_ready"] is True
    assert db_item.get("analysis_missing_fields", []) == []
    assert db_item["analysis_model_version"] == "generic_product_v1"


def test_repository_round_trips_generic_product_attributes_and_extensions(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    repository.upsert_flat_item(
        {
            "id": "sku-8",
            "source_item_id": "sku-8",
            "source_platform": "catalog_x",
            "url": "https://catalog.example/items/sku-8",
            "name": "Portable battery",
            "inventory": 17,
            "attributes": {"capacity_wh": 72},
            "extensions": {"catalog_x": {"seller_tier": "gold"}},
        },
        event_type="detail_enriched",
    )

    db_item = repository.get_flat_item("sku-8")

    assert db_item is not None
    assert db_item["name"] == "Portable battery"
    assert db_item["inventory"] == 17
    assert db_item["attributes"] == {"capacity_wh": 72}
    assert db_item["extensions"] == {"catalog_x": {"seller_tier": "gold"}}
    assert db_item["record_schema_version"] == 2
    assert db_item["canonical_payload"]["entity_type"] == "product"


def test_repository_preserves_existing_generic_fields_on_partial_update(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    repository.upsert_flat_item(
        {
            "id": "sku-9",
            "source_platform": "catalog_x",
            "name": "Original",
            "seller_note": "keep me",
        },
        event_type="seed_discovered",
    )
    repository.upsert_flat_item(
        {"id": "sku-9", "source_platform": "catalog_x", "name": "Updated"},
        event_type="detail_enriched",
    )

    db_item = repository.get_flat_item("sku-9")

    assert db_item is not None
    assert db_item["name"] == "Updated"
    assert db_item["seller_note"] == "keep me"


def test_legacy_row_without_envelope_uses_normalized_fallback(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    repository.upsert_flat_item(
        {"id": "legacy-1", "source_platform": "catalog_x", "title": "Legacy"},
        event_type="seed_discovered",
    )
    with repository.session_factory.begin() as session:
        listing = session.get(PropertyListing, "legacy-1")
        assert listing is not None
        listing.record_schema_version = None
        listing.canonical_payload = None

    db_item = repository.get_flat_item("legacy-1")

    assert db_item is not None
    assert db_item["title"] == "Legacy"
    assert "canonical_payload" not in db_item


def test_canonical_backfill_is_dry_run_and_idempotent(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    repository.upsert_flat_item(
        {"id": "legacy-2", "source_platform": "catalog_x", "title": "Legacy"},
        event_type="seed_discovered",
    )
    with repository.session_factory.begin() as session:
        listing = session.get(PropertyListing, "legacy-2")
        assert listing is not None
        listing.record_schema_version = None
        listing.canonical_payload = None

    dry_run = backfill_canonical_payloads(repository)
    assert dry_run.scanned == 1
    assert dry_run.changed == 1
    assert repository.get_flat_item("legacy-2") is not None
    with repository.session_factory() as session:
        assert session.get(PropertyListing, "legacy-2").canonical_payload is None

    applied = backfill_canonical_payloads(repository, apply=True)
    repeated = backfill_canonical_payloads(repository, apply=True)
    assert applied.changed == 1
    assert repeated.changed == 0
