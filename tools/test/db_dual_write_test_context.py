import importlib

import json

from pathlib import Path

import threading

import urllib.request

import pytest

from sqlalchemy import func, select

from src.avm.collection_template import build_collection_record, sync_collection_record

from src.collection.seed_service import SeedCollectionService

from src.collection.adapters import TaobaoJudicialAuctionAdapter

from src.avm.service import AVMService

from src.storage.models import (
    ManualReviewReceipt,
    ManualReviewReceiptJob,
    ManualReviewReceiptOperation,
    PropertyAudit,
    PropertyIngestEvent,
    PropertyLegalContext,
    PropertyListing,
    PropertyRiskFlags,
    PropertySearchTask,
)

from src.storage.repository import DatabaseSettings, PropertyRepository

def _make_repo(tmp_path: Path) -> PropertyRepository:
    db_path = tmp_path / "dual-write.sqlite3"
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )

def _make_flat_item(**overrides):
    item = {
        "id": "9001",
        "title": "Test Listing",
        "url": "https://example.com/item/9001",
        "list_payload_path": "archive_payloads/2026-05-11/list-001.json",
        "detail_archive_path": "html_archive/2026/2026-05-11/item-9001.html",
        "end": "2026-05-11 10:00:00",
        "currentPrice": "1000000",
        "initialPrice": "800000",
        "deposit": "50000",
        "applyCount": "4",
        "bidCount": "7",
        "bidderCount": "3",
        "watchCount": "120",
        "remindCount": "18",
        "viewCount": "300",
        "location": "Shanghai Pudong Test Rd 99",
        "city": "Shanghai",
        "district": "Pudong",
        "business_area_name": "Lujiazui",
        "community_name": "Test Garden",
        "lat": "31.23",
        "lng": "121.56",
        "coordinate_source": "list",
        "housingType": "residential",
        "area_sqm": "89.5",
        "ownership_share_ratio": "1/2",
        "layout": "2br1lr",
        "appraisal_report_urls": "https://example.com/a.pdf; https://example.com/b.pdf",
        "announcement_attachment_urls": ["https://example.com/c.pdf"],
        "avm_risk_features": {
            "is_occupied": "yes",
            "is_fractional_share": "true",
            "has_elevator": "false",
            "build_year": "2001",
            "floor_level": "high",
            "property_fee_owed": 1,
            "tax_burden": "buyer",
            "evidence_span": ["line1", "line2"],
            "evidence_source": "llm",
            "extraction_version": "risk_v2",
        },
    }
    risk_overrides = overrides.pop("avm_risk_features", None)
    item.update(overrides)
    if risk_overrides:
        item["avm_risk_features"].update(risk_overrides)
    return item

__all__ = [name for name in globals() if not name.startswith("__")]
