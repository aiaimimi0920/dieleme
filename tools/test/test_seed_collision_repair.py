from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

import scripts.repair_seed_collisions as collision_cli
from scripts.repair_seed_collisions import _local_sqlite_url, main
from src.collection.seed_scan_policy import GenericSeedScanPolicy
from src.storage.models import (
    FapaiSeedItem,
    FapaiSeedOccurrence,
    FapaiSeedScanJob,
    PropertyListing,
)
from src.storage.seed_collision_audit import (
    audit_seed_item_collision,
    occurrence_key,
)
from src.storage.seed_collision_repair import (
    apply_seed_item_collision_repair,
    rollback_seed_item_collision_repair,
)
from tools.test.seed_queue_repository_test_context import _make_repo


def _add_occurrence(
    session,
    *,
    occurrence_id: int,
    item_id: str,
    platform: str | None,
    source_item_id: str,
    rank: int,
) -> None:
    job_key = f"job-{occurrence_id}"
    session.add(
        FapaiSeedScanJob(
            job_key=job_key,
            location_code="source",
            category=platform or "unknown",
            status="done",
            metadata_json={"source_platform": platform} if platform else {},
        )
    )
    raw_item = {"source_item_id": source_item_id}
    if platform:
        raw_item["source_platform"] = platform
    session.add(
        FapaiSeedOccurrence(
            id=occurrence_id,
            occurrence_key=occurrence_key(
                item_id=item_id,
                job_key=job_key,
                sort_key="source",
                page=1,
                rank=rank,
            ),
            item_id=item_id,
            job_key=job_key,
            progress_key=f"progress-{occurrence_id}",
            sort_key="source",
            sort_name="source",
            st_param="source",
            page=1,
            rank=rank,
            source_page_url=f"https://{platform or 'unknown'}.example/list",
            source_final_url=f"https://{platform or 'unknown'}.example/list",
            raw_item={
                **raw_item,
                "url": f"https://{platform or 'unknown'}.example/items/{source_item_id}",
                "title": f"item {source_item_id}",
            },
        )
    )


def _seed_collision(repo, *, ambiguous: bool = False) -> str:
    item_id = "shared-1"
    repo.initialize()
    with repo.session_factory.begin() as session:
        session.add(
            FapaiSeedItem(
                item_id=item_id,
                source_item_id=item_id,
                source_platform="taobao_sf",
                source_url=f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
                source_payload={
                    "source_item_id": item_id,
                    "source_platform": "taobao_sf",
                },
                status="pending_detail",
            )
        )
        _add_occurrence(
            session,
            occurrence_id=1,
            item_id=item_id,
            platform="taobao_sf",
            source_item_id=item_id,
            rank=1,
        )
        _add_occurrence(
            session,
            occurrence_id=2,
            item_id=item_id,
            platform="catalog_x",
            source_item_id=item_id,
            rank=2,
        )
        if ambiguous:
            _add_occurrence(
                session,
                occurrence_id=3,
                item_id=item_id,
                platform=None,
                source_item_id=item_id,
                rank=3,
            )
    return item_id


def test_collision_audit_is_read_only_and_marks_safe_seed_only_split(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    item_id = _seed_collision(repo)

    with repo.session_factory() as session:
        before = session.scalar(select(func.count()).select_from(FapaiSeedItem))
        report = audit_seed_item_collision(session, item_id)
        after = session.scalar(select(func.count()).select_from(FapaiSeedItem))

    assert before == after == 1
    assert report["decision"] == "auto_split"
    assert {part["source_platform"] for part in report["partitions"]} == {
        "taobao_sf",
        "catalog_x",
    }
    assert report["downstream_counts"] == {
        "analysis_runs": 0,
        "property_listings": 0,
        "ingest_events": 0,
    }


def test_collision_repair_moves_occurrence_and_receipt_rolls_back(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    item_id = _seed_collision(repo)
    target_id = GenericSeedScanPolicy(source_platform="catalog_x").storage_item_id(item_id)

    with repo.session_factory.begin() as session:
        report = audit_seed_item_collision(session, item_id)
        receipt = apply_seed_item_collision_repair(
            session,
            item_id,
            expected_evidence_sha256=report["evidence_sha256"],
        )

    with repo.session_factory() as session:
        target = session.get(FapaiSeedItem, target_id)
        moved = session.get(FapaiSeedOccurrence, 2)
        assert target is not None
        assert target.source_platform == "catalog_x"
        assert target.source_item_id == item_id
        assert moved.item_id == target_id
        assert moved.occurrence_key != receipt["occurrence_moves"][0]["old_occurrence_key"]

    with repo.session_factory.begin() as session:
        rollback = rollback_seed_item_collision_repair(session, receipt)

    with repo.session_factory() as session:
        assert session.get(FapaiSeedItem, target_id) is None
        assert session.get(FapaiSeedOccurrence, 2).item_id == item_id
        assert session.scalar(select(func.count()).select_from(FapaiSeedItem)) == 1
    assert rollback["restored_occurrence_count"] == 1

    with repo.session_factory.begin() as session:
        repeated = rollback_seed_item_collision_repair(session, receipt)
    assert repeated["status"] == "already_rolled_back"


def test_collision_with_incomplete_evidence_requires_manual_review(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    item_id = _seed_collision(repo, ambiguous=True)

    with repo.session_factory() as session:
        report = audit_seed_item_collision(session, item_id)

    assert report["decision"] == "manual_review"
    assert any("missing_source_platform" in issue for issue in report["issues"])


def test_collision_with_downstream_record_is_never_auto_split(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    item_id = _seed_collision(repo)
    with repo.session_factory.begin() as session:
        session.add(PropertyListing(item_id=item_id, source_platform="taobao_sf"))

    with repo.session_factory() as session:
        report = audit_seed_item_collision(session, item_id)

    assert report["decision"] == "manual_review"
    assert "dependent_detail_or_analysis_data" in report["issues"]


def test_collision_cli_rejects_remote_database_and_requires_apply_receipt(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="local SQLite"):
        _local_sqlite_url("postgresql://database.example/crow")
    with pytest.raises(ValueError, match="UNC and network"):
        _local_sqlite_url("sqlite://///server/share/crow.db")

    repo = _make_repo(tmp_path)
    item_id = _seed_collision(repo)
    database_url = str(repo.settings.url)
    with pytest.raises(ValueError, match="--apply requires --receipt"):
        main(["--database-url", database_url, "--item-id", item_id, "--apply"])


def test_collision_cli_applies_and_rolls_back_with_durable_receipt(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    item_id = _seed_collision(repo)
    database_url = str(repo.settings.url)
    receipt_path = tmp_path / "collision-receipt.json"
    target_id = GenericSeedScanPolicy(source_platform="catalog_x").storage_item_id(item_id)

    assert main(
        [
            "--database-url",
            database_url,
            "--item-id",
            item_id,
            "--apply",
            "--receipt",
            str(receipt_path),
        ]
    ) == 0
    assert receipt_path.read_text(encoding="utf-8").startswith("{")
    with repo.session_factory() as session:
        assert session.get(FapaiSeedItem, target_id) is not None

    assert main(
        [
            "--database-url",
            database_url,
            "--rollback",
            str(receipt_path),
        ]
    ) == 0
    with repo.session_factory() as session:
        assert session.get(FapaiSeedItem, target_id) is None
    assert main(
        [
            "--database-url",
            database_url,
            "--rollback",
            str(receipt_path),
        ]
    ) == 0


def test_prepared_receipt_can_recover_when_database_transaction_did_not_commit(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    item_id = _seed_collision(repo)
    with repo.session_factory() as session:
        transaction = session.begin()
        report = audit_seed_item_collision(session, item_id)
        receipt = apply_seed_item_collision_repair(
            session,
            item_id,
            expected_evidence_sha256=report["evidence_sha256"],
        )
        transaction.rollback()

    with repo.session_factory.begin() as session:
        result = rollback_seed_item_collision_repair(session, receipt)

    assert result["status"] == "already_rolled_back"


def test_apply_receipt_failure_rolls_back_entire_database_batch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    item_id = _seed_collision(repo)
    target_id = GenericSeedScanPolicy(source_platform="catalog_x").storage_item_id(item_id)
    with repo.session_factory() as session:
        reports = [audit_seed_item_collision(session, item_id)]
    database_url = _local_sqlite_url(str(repo.settings.url))
    receipt_path = tmp_path / "failed-apply-receipt.json"
    original_write = collision_cli._write_json_atomic

    def fail_prepared_write(path, payload, **kwargs):
        if payload.get("status") == "prepared":
            raise OSError("simulated receipt failure")
        return original_write(path, payload, **kwargs)

    monkeypatch.setattr(collision_cli, "_write_json_atomic", fail_prepared_write)
    with pytest.raises(OSError, match="simulated receipt failure"):
        collision_cli._apply(
            repo,
            reports,
            receipt_path,
            collision_cli._database_fingerprint(database_url),
        )

    with repo.session_factory() as session:
        assert session.get(FapaiSeedItem, target_id) is None
        assert session.get(FapaiSeedOccurrence, 2).item_id == item_id
    assert collision_cli._rollback(
        repo,
        receipt_path,
        collision_cli._database_fingerprint(database_url),
    )["status"] == "rolled_back"
