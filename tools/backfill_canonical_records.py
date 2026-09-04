from __future__ import annotations

import argparse
import json

from src.storage.canonical_backfill import backfill_canonical_payloads
from src.storage.repository import DatabaseSettings, PropertyRepository


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill source-neutral canonical product envelopes.")
    parser.add_argument("--database-url", required=True, help="Explicit SQLAlchemy URL; ambient live config is never used.")
    parser.add_argument("--apply", action="store_true", help="Persist changes. Without this flag the command is read-only.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repository = PropertyRepository(
        DatabaseSettings(
            url=args.database_url,
            echo=False,
            enable_postgis=False,
            auto_create=False,
            enabled=True,
        )
    )
    result = backfill_canonical_payloads(repository, apply=args.apply)
    print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
