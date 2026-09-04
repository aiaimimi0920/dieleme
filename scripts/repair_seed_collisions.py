from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import make_url


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.storage.repository import DatabaseSettings, PropertyRepository
from src.storage.seed_collision_audit import (
    audit_seed_item_collision,
    collision_candidate_item_ids,
)
from src.storage.seed_collision_repair import (
    apply_seed_item_collision_repair,
    rollback_seed_item_collision_repair,
)


BATCH_RECEIPT_SCHEMA_VERSION = "seed_collision_repair_batch_v1"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _windows_path_is_remote(path: Path) -> bool:
    rendered = str(path)
    if rendered.startswith("\\\\"):
        return True
    if os.name != "nt":
        return False
    drive_root = path.anchor
    if not drive_root:
        return False
    drive_remote = 4
    return ctypes.windll.kernel32.GetDriveTypeW(drive_root) == drive_remote


def _local_sqlite_url(raw_url: str) -> str:
    url = make_url(str(raw_url or "").strip())
    if url.get_backend_name() != "sqlite":
        raise ValueError("collision repair only accepts an explicitly supplied local SQLite database")
    if url.host or url.username or url.password or url.query:
        raise ValueError("collision repair SQLite URL cannot contain a host, credentials, or query options")
    database = str(url.database or "").strip()
    if not database:
        raise ValueError("SQLite database path is required")
    if database != ":memory:":
        normalized = database.replace("\\", "/")
        if normalized.startswith("//"):
            raise ValueError("collision repair rejects UNC and network SQLite paths")
        database_path = Path(database).expanduser()
        if not database_path.is_absolute():
            database_path = REPO_ROOT / database_path
        database_path = database_path.resolve()
        if _windows_path_is_remote(database_path):
            raise ValueError("collision repair rejects UNC and network SQLite paths")
        if not database_path.is_file():
            raise ValueError(f"SQLite database does not exist: {database_path}")
        return f"sqlite:///{database_path.as_posix()}"
    return "sqlite:///:memory:"


def _database_fingerprint(database_url: str) -> str:
    return hashlib.sha256(database_url.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any], *, must_not_exist: bool = False) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if must_not_exist:
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise ValueError(f"receipt already exists: {target}") from exc
            temporary.unlink()
        else:
            os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _repository(database_url: str) -> PropertyRepository:
    repository = PropertyRepository(
        DatabaseSettings(
            url=database_url,
            echo=False,
            enable_postgis=False,
            auto_create=False,
            enabled=True,
        )
    )
    repository.initialize()
    return repository


def _candidate_ids(repository: PropertyRepository, selected: list[str]) -> list[str]:
    if selected:
        return sorted(set(selected))
    with repository.session_factory() as session:
        return collision_candidate_item_ids(session)


def _audit(repository: PropertyRepository, item_ids: list[str]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    with repository.session_factory() as session:
        for item_id in item_ids:
            reports.append(audit_seed_item_collision(session, item_id))
    return reports


def _apply(
    repository: PropertyRepository,
    reports: list[dict[str, Any]],
    receipt_path: Path,
    database_fingerprint: str,
) -> dict[str, Any]:
    batch = {
        "schema_version": BATCH_RECEIPT_SCHEMA_VERSION,
        "status": "applying",
        "started_at": _utc_timestamp(),
        "database_fingerprint": database_fingerprint,
        "reports": reports,
        "repairs": [],
    }
    _write_json_atomic(receipt_path, batch, must_not_exist=True)
    eligible_reports = [report for report in reports if report["decision"] == "auto_split"]
    if not eligible_reports:
        batch["status"] = "no_eligible_repairs"
        batch["completed_at"] = _utc_timestamp()
        _write_json_atomic(receipt_path, batch)
        return batch

    with repository.session_factory.begin() as session:
        for report in eligible_reports:
            repair = apply_seed_item_collision_repair(
                session,
                report["item_id"],
                expected_evidence_sha256=report["evidence_sha256"],
            )
            batch["repairs"].append(repair)
        batch["status"] = "prepared"
        batch["prepared_at"] = _utc_timestamp()
        _write_json_atomic(receipt_path, batch)
    batch["status"] = "applied"
    batch["completed_at"] = _utc_timestamp()
    _write_json_atomic(receipt_path, batch)
    return batch


def _rollback(
    repository: PropertyRepository,
    receipt_path: Path,
    database_fingerprint: str,
) -> dict[str, Any]:
    batch = json.loads(receipt_path.read_text(encoding="utf-8"))
    if batch.get("schema_version") != BATCH_RECEIPT_SCHEMA_VERSION:
        raise ValueError("unsupported collision repair batch receipt")
    if batch.get("database_fingerprint") != database_fingerprint:
        raise ValueError("receipt belongs to a different SQLite database")
    if batch.get("status") == "rolled_back":
        return batch
    if batch.get("status") not in {"applied", "applying", "prepared"}:
        raise ValueError("receipt has no applied repairs to roll back")
    rollback_results: list[dict[str, Any]] = []
    with repository.session_factory.begin() as session:
        for repair in reversed(list(batch.get("repairs") or [])):
            rollback_results.append(rollback_seed_item_collision_repair(session, repair))
    batch["status"] = "rolled_back"
    batch["rolled_back_at"] = _utc_timestamp()
    batch["rollbacks"] = rollback_results
    _write_json_atomic(receipt_path, batch)
    return batch


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit and conservatively split historical seed identity collisions."
    )
    parser.add_argument("--database-url", required=True, help="Explicit local SQLite URL.")
    parser.add_argument("--item-id", action="append", default=[], help="Limit audit to one seed item; repeatable.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", help="Apply only auto_split reports.")
    action.add_argument("--rollback", type=Path, help="Roll back the applied repairs in a receipt.")
    parser.add_argument("--receipt", type=Path, help="Required durable receipt path for --apply.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    database_url = _local_sqlite_url(args.database_url)
    fingerprint = _database_fingerprint(database_url)
    repository = _repository(database_url)
    if args.rollback:
        result = _rollback(repository, args.rollback.expanduser().resolve(), fingerprint)
    else:
        item_ids = _candidate_ids(repository, list(args.item_id))
        reports = _audit(repository, item_ids)
        if args.apply:
            if args.receipt is None:
                raise ValueError("--apply requires --receipt")
            result = _apply(repository, reports, args.receipt, fingerprint)
        else:
            result = {
                "schema_version": BATCH_RECEIPT_SCHEMA_VERSION,
                "status": "dry_run",
                "database_fingerprint": fingerprint,
                "reports": reports,
            }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
