"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.manual_review_control_plane_context import *


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill manual review receipt/job/audit JSON state into DB tables")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--db-url", type=str, default=None)
    parser.add_argument(
        "--mode",
        choices=("backfill", "export", "describe-storage", "describe-backup"),
        default="backfill",
        help="backfill JSON into DB, export repository state back to JSON, or describe current storage/backup mode",
    )
    return parser.parse_args()


__all__ = (
    '_parse_args',
)
