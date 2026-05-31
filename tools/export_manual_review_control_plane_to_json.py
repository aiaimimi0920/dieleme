#!/usr/bin/env python3
"""Export repository-backed manual review control-plane state into JSON backup files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.backfill_manual_review_control_plane_to_db import export_manual_review_control_plane_to_json


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export manual review receipt/job/audit DB state into JSON backup files")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--db-url", type=str, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    report = export_manual_review_control_plane_to_json(args.data_root, db_url=args.db_url)
    print(json.dumps(report, ensure_ascii=False, indent=2))
