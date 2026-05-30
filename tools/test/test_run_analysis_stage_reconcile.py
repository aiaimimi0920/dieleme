import json
from pathlib import Path

from src.storage.models import PropertyListing
from src.storage.repository import DatabaseSettings, PropertyRepository
from tools import run_analysis_stage_reconcile as reconcile_module
from tools.run_analysis_stage_reconcile import run_analysis_stage_reconcile


def _make_repo(tmp_path: Path) -> PropertyRepository:
    db_path = tmp_path / "analysis-stage-reconcile.sqlite3"
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def _base_item(item_id: str) -> dict:
    return {
        "id": item_id,
        "title": f"Item {item_id}",
        "url": f"https://example.com/{item_id}",
        "status": "成交",
        "transaction_price": 1000000,
        "starting_price": 800000,
        "evaluation_price": 1200000,
        "area_sqm": 88.8,
        "auction_date": "2026-03-05 10:00:00",
        "city": "上海市",
        "district": "浦东新区",
        "business_area": "陆家嘴",
        "community_name": "测试小区",
        "latitude": 31.2,
        "longitude": 121.5,
        "detail_archive_path": f"html_archive/2026/2026-03-05/{item_id}.html",
        "detail_captured": True,
    }


def test_run_analysis_stage_reconcile_skips_when_repository_disabled(tmp_path: Path, monkeypatch):
    class _DisabledRepo:
        enabled = False

    monkeypatch.setattr(reconcile_module, "create_repository_from_env", lambda: _DisabledRepo())

    report = run_analysis_stage_reconcile(
        data_root=tmp_path / "datas",
        window_days=7,
        mode="analysis_ready_recheck",
        dry_run=False,
    )

    assert report["skipped"] is True
    assert report["skip_reason"] == "repository_unavailable"
    assert report["updated_count"] == 0


def test_run_analysis_stage_reconcile_updates_stale_analysis_ready_state(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    item = _base_item("recheck-1")
    item.pop("business_area")
    repo.upsert_flat_item(item, event_type="seed")

    with repo.session_factory.begin() as session:
        listing = session.get(PropertyListing, "recheck-1")
        assert listing is not None
        listing.business_area = "陆家嘴"

    monkeypatch.setattr(reconcile_module, "create_repository_from_env", lambda: repo)

    report = run_analysis_stage_reconcile(
        data_root=tmp_path / "datas",
        window_days=7,
        mode="analysis_ready_recheck",
        dry_run=False,
    )

    updated = repo.get_flat_item("recheck-1")
    assert updated is not None
    assert updated["analysis_status"] == "ready"
    assert updated["analysis_ready"] is True
    assert report["candidate_count"] == 1
    assert report["scanned_count"] == 1
    assert report["updated_count"] == 1
    assert report["analysis_stage_transition_count"] >= 1
    assert report["analysis_ready_transition_count"] >= 1
    assert report["samples"][0]["item_id"] == "recheck-1"
    assert "analysis_ready_transition" in report["samples"][0]["triggered_transition_types"]
    event_counts = repo.event_type_counts(("analysis_ready_recheck", "analysis_stage_transition", "analysis_ready_transition"))
    assert event_counts["analysis_ready_recheck"] >= 1
    assert event_counts["analysis_stage_transition"] >= 1
    assert event_counts["analysis_ready_transition"] >= 1


def test_run_analysis_stage_reconcile_dry_run_does_not_write(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    item = _base_item("dryrun-1")
    item["status"] = "pending"
    repo.upsert_flat_item(item, event_type="seed")

    with repo.session_factory.begin() as session:
        listing = session.get(PropertyListing, "dryrun-1")
        assert listing is not None
        listing.status = "成交"

    monkeypatch.setattr(reconcile_module, "create_repository_from_env", lambda: repo)

    report = run_analysis_stage_reconcile(
        data_root=tmp_path / "datas",
        window_days=7,
        mode="stage_state_reconcile",
        dry_run=True,
    )

    current = repo.get_flat_item("dryrun-1")
    assert current is not None
    assert current["analysis_status"] == "not_ready"
    assert current["analysis_ready"] is False
    assert report["candidate_count"] == 1
    assert report["scanned_count"] == 1
    assert report["updated_count"] == 0
    assert report["analysis_stage_transition_count"] == 0
    assert report["analysis_ready_transition_count"] == 0
    event_counts = repo.event_type_counts(("stage_state_reconcile",))
    assert event_counts["stage_state_reconcile"] == 0
