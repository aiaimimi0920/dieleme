#!/usr/bin/env python3
"""Read-only preflight report for manual review control-plane DB rollout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.backfill_manual_review_control_plane_to_db import (
    generate_manual_review_control_plane_rollout_preflight,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a read-only rollout preflight report for manual review control-plane")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--db-url", type=str, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    report = generate_manual_review_control_plane_rollout_preflight(
        args.data_root,
        db_url=args.db_url,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
