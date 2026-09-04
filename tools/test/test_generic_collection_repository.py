from __future__ import annotations

from pathlib import Path

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
