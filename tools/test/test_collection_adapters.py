from __future__ import annotations

import json
from pathlib import Path

from src.analysis_ensemble import (
    GENERIC_ANALYSIS_PROFILE,
    build_field_consensus,
    compose_final_payload,
)
from src.collection import (
    DetailCollectionService,
    GenericProductAdapter,
    SeedCollectionService,
    derive_stage_state,
    generic_product_analysis_missing_fields,
)


def test_generic_adapter_collects_arbitrary_product_seed(tmp_path: Path) -> None:
    target = tmp_path / "products.json"
    persisted: list[dict[str, object]] = []
    service = SeedCollectionService(
        data_root=str(tmp_path),
        adapter=GenericProductAdapter(source_platform="catalog_x"),
    )

    result = service.submit_batch(
        {
            "items": [
                {
                    "sku": "sku-7",
                    "name": "Reusable product",
                    "detail_url": "https://catalog.example/items/sku-7",
                    "inventory": 12,
                }
            ]
        },
        parse_price=lambda value: value,
        safe_int=lambda value: value,
        prefer_db_task_reads=lambda: False,
        get_seen_entry=lambda _item_id: None,
        get_flat_item=lambda _item_id: None,
        get_data_path=lambda _partition: str(target),
        update_file_global=lambda *_args: None,
        persist_item_to_db=lambda item, *_args: persisted.append(dict(item)),
        evict_runtime_item=lambda _item_id: None,
        seen_ids={},
        pending_tasks=[],
        archive_list_payload=lambda *_args: None,
    )

    assert result == {"status": "ok", "new": 1}
    record = persisted[0]
    assert record["source_item_id"] == "sku-7"
    assert record["source_platform"] == "catalog_x"
    assert record["source_title"] == "Reusable product"
    assert record["source_url"] == "https://catalog.example/items/sku-7"
    assert record["inventory"] == 12


def test_generic_adapter_processes_alphanumeric_detail_id(tmp_path: Path) -> None:
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    html_path = html_dir / "item-sku-7.html"
    html_path.write_text("<html><body>price 99</body></html>", encoding="utf-8")
    updated: list[dict[str, object]] = []
    seed = {
        "source_item_id": "sku-7",
        "source_platform": "catalog_x",
        "inventory": 12,
        "url": "https://catalog.example/items/sku-7",
    }

    DetailCollectionService(
        tmp_path,
        adapter=GenericProductAdapter(source_platform="catalog_x"),
    ).process_html_file(
        str(html_path),
        get_working_item=lambda *_args, **_kwargs: {
            "file_path": str(tmp_path / "products.json"),
            "data": seed,
        },
        get_data_path=lambda _partition: str(tmp_path / "products.json"),
        update_item_in_json=lambda _path, _item_id, record: updated.append(dict(record)),
        remove_item_from_json=lambda *_args: None,
        persist_item_to_db=lambda *_args: None,
        mark_item_deleted_in_db=lambda *_args: None,
        evict_runtime_item=lambda *_args: None,
        prefer_db_task_reads=lambda: False,
        sync_avm_risk_aliases=lambda record: record,
        extract_auction_data=lambda *_args, **_kwargs: json.dumps({"name": "Updated", "price": 99}),
        extract_avm_risk_features=lambda *_args, **_kwargs: {},
        log_prediction_event=lambda **_kwargs: None,
        current_processing={str(html_path)},
        seen_ids={},
        pending_tasks=["sku-7"],
    )

    assert updated[0]["source_item_id"] == "sku-7"
    assert updated[0]["inventory"] == 12
    assert updated[0]["price"] == 99
    assert updated[0]["detail_captured"] is True
    assert updated[0]["is_processed"] is True


def test_generic_analysis_profile_has_no_auction_derived_fields() -> None:
    candidates = [{"price": "10"}, {"price": "10"}, {"price": "10"}]
    consensus = build_field_consensus(
        candidates,
        source_text="price 10",
        profile=GENERIC_ANALYSIS_PROFILE,
    )

    payload = compose_final_payload(
        consensus=consensus,
        adjudication=None,
        profile=GENERIC_ANALYSIS_PROFILE,
    )

    assert payload == {"price": "10", "is_processed": True}
    assert "单价" not in payload


def test_default_auction_analysis_profile_keeps_unit_aware_price_derivation() -> None:
    payload = compose_final_payload(
        consensus={
            "locked_fields": {
                "成交价格": {"value": "125万元"},
                "建筑面积": {"value": "100㎡"},
            }
        },
        adjudication=None,
    )

    assert payload["单价"] == 12_500.0


def test_generic_stage_state_does_not_require_auction_or_property_fields() -> None:
    state = derive_stage_state(
        {
            "source_item_id": "sku-7",
            "source_url": "https://catalog.example/items/sku-7",
            "detail_archive_path": "html/sku-7.html",
            "detail_captured": True,
        },
        analysis_requirements=generic_product_analysis_missing_fields,
    )

    assert state["seed_status"] == "stored"
    assert state["detail_status"] == "archived"
    assert state["analysis_ready"] is True
    assert state["analysis_missing_fields"] == []
