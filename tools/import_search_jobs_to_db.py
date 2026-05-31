"""Import legacy jobs/*.json search progress into property_search_task."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.collection.search_bootstrap import DEFAULT_CATEGORIES, iter_job_snapshots, load_all_location_codes
from src.storage.repository import DatabaseSettings, PropertyRepository, create_repository_from_env


def _build_repo(db_url: str | None) -> PropertyRepository:
    if db_url:
        return PropertyRepository(
            DatabaseSettings(
                url=db_url,
                echo=False,
                enable_postgis=True,
                auto_create=True,
                enabled=True,
            )
        )
    return create_repository_from_env()


def import_search_jobs_to_db(jobs_dir: Path, data_root: Path, db_url: str | None = None) -> dict:
    repo = _build_repo(db_url)
    repo.initialize()
    snapshots = iter_job_snapshots(jobs_dir)
    imported = repo.import_search_task_snapshots(snapshots)
    all_codes = load_all_location_codes(data_root)
    seeded = repo.ensure_seed_search_tasks(all_codes, DEFAULT_CATEGORIES, sort_param="2")
    counts = repo.search_task_counts()
    return {
        "snapshot_count": len(snapshots),
        "imported_rows": imported,
        "all_location_codes": len(all_codes),
        "seeded_primary_tasks": seeded,
        "search_task_counts": counts,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import legacy jobs search progress into property_search_task")
    parser.add_argument("--jobs-dir", type=Path, default=Path("jobs"))
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--db-url", type=str, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    report = import_search_jobs_to_db(args.jobs_dir, args.data_root, db_url=args.db_url)
    print(report)
