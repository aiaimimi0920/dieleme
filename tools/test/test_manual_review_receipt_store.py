import json
from pathlib import Path

from tools.manual_review_receipt_store import (
    delete_manual_review_receipt,
    list_manual_review_receipts,
    upsert_manual_review_receipt,
)


def test_receipt_store_reads_missing_file_as_empty(tmp_path: Path):
    store_path = tmp_path / "manual_review_receipts.json"

    payload = list_manual_review_receipts(store_path)

    assert payload == {"receipts": []}


def test_receipt_store_upsert_creates_new_receipt(tmp_path: Path):
    store_path = tmp_path / "manual_review_receipts.json"

    result = upsert_manual_review_receipt(
        store_path,
        {
            "action": "manual_location_review",
            "ready_signal": "location_artifacts_complete",
            "status": "ready_for_reentry",
            "payload": {"full_address": "A"},
        },
    )

    saved = json.loads(store_path.read_text(encoding="utf-8"))
    assert result["operation"] == "created"
    assert saved["receipts"][0]["action"] == "manual_location_review"
    assert saved["receipts"][0]["ready_signal"] == "location_artifacts_complete"
    assert "updated_at" in saved["receipts"][0]


def test_receipt_store_upsert_overwrites_same_action_and_signal(tmp_path: Path):
    store_path = tmp_path / "manual_review_receipts.json"
    upsert_manual_review_receipt(
        store_path,
        {
            "action": "manual_location_review",
            "ready_signal": "location_artifacts_complete",
            "status": "ready_for_reentry",
            "payload": {"full_address": "A"},
        },
    )

    result = upsert_manual_review_receipt(
        store_path,
        {
            "action": "manual_location_review",
            "ready_signal": "location_artifacts_complete",
            "status": "reentered_auto_pipeline",
            "payload": {"full_address": "B"},
        },
    )

    saved = json.loads(store_path.read_text(encoding="utf-8"))
    assert result["operation"] == "updated"
    assert len(saved["receipts"]) == 1
    assert saved["receipts"][0]["status"] == "reentered_auto_pipeline"
    assert saved["receipts"][0]["payload"]["full_address"] == "B"


def test_receipt_store_delete_existing_receipt(tmp_path: Path):
    store_path = tmp_path / "manual_review_receipts.json"
    upsert_manual_review_receipt(
        store_path,
        {
            "action": "manual_location_review",
            "ready_signal": "location_artifacts_complete",
            "status": "ready_for_reentry",
            "payload": {"full_address": "A"},
        },
    )

    result = delete_manual_review_receipt(
        store_path,
        action="manual_location_review",
        ready_signal="location_artifacts_complete",
    )

    saved = json.loads(store_path.read_text(encoding="utf-8"))
    assert result["deleted"] is True
    assert saved == {"receipts": []}


def test_receipt_store_delete_missing_receipt_is_noop(tmp_path: Path):
    store_path = tmp_path / "manual_review_receipts.json"
    store_path.write_text(json.dumps({"receipts": []}, ensure_ascii=False), encoding="utf-8")

    result = delete_manual_review_receipt(
        store_path,
        action="manual_location_review",
        ready_signal="location_artifacts_complete",
    )

    assert result["deleted"] is False
