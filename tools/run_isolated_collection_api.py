from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def build_runtime_config(
    repo_root: Path,
    *,
    port: int,
    db_url: str | None = None,
    seed_location_codes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "repo_root": repo_root,
        "data_dir": repo_root / "datas",
        "port": port,
        "ensure_browser": False,
        "start_watchdog": False,
        "start_background_processors": False,
        "start_hot_reload": False,
        "skip_load_data": True,
        "db_url": db_url,
        "seed_location_codes": list(seed_location_codes or ["110101"]),
    }


def run_server(config: dict[str, Any]) -> int:
    if config.get("db_url"):
        os.environ["FAPAI_DB_URL"] = str(config["db_url"])
        os.environ["FAPAI_DB_ENABLED"] = "1"
    from src import server as fapai_server
    from src.collection.search_bootstrap import DEFAULT_CATEGORIES
    from src.collection.seed_service import SeedCollectionService

    fapai_server.PORT = int(config["port"])
    fapai_server.DATA_DIR = str(config["data_dir"])
    fapai_server.AVM_DIR = str(Path(fapai_server.DATA_DIR) / "avm")
    fapai_server.AVM_SERVICE.data_dir = fapai_server.DATA_DIR
    fapai_server.AVM_PIPELINE._data_dir = fapai_server.DATA_DIR  # align manager data root
    if config.get("skip_load_data"):
        def _skip_load_data():
            print("[isolated_collection_api] Skipping full load_data() for collection-only startup.", flush=True)
        fapai_server.load_data = _skip_load_data
    if config.get("db_url") and config.get("seed_location_codes"):
        seed_location_codes = list(config["seed_location_codes"])

        def _minimal_bootstrap(self):
            if not (self.repository and getattr(self.repository, "enabled", False)):
                return
            self.repository.ensure_seed_search_tasks(seed_location_codes, DEFAULT_CATEGORIES, sort_param="2")

        SeedCollectionService._bootstrap_db_search_tasks = _minimal_bootstrap
    print(f"[isolated_collection_api] Starting on port {fapai_server.PORT} with data dir {fapai_server.DATA_DIR}")
    fapai_server.initialize_runtime(
        start_watchdog=bool(config["start_watchdog"]),
        ensure_browser=bool(config["ensure_browser"]),
    )
    fapai_server.AVM_CONFIG_MANAGER.load_on_startup()
    with fapai_server.ReusableTCPServer(("", fapai_server.PORT), fapai_server.DataHandler) as httpd:
        print("[isolated_collection_api] Server running. Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("[isolated_collection_api] Stopped by user.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start an isolated collection API without browser watchdog side effects.")
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--seed-location-code", action="append", dest="seed_location_codes")
    parser.add_argument("--print-config", action="store_true")
    args = parser.parse_args(argv)

    config = build_runtime_config(
        REPO_ROOT,
        port=args.port,
        db_url=args.db_url,
        seed_location_codes=args.seed_location_codes,
    )
    if args.print_config:
        printable = dict(config)
        printable["repo_root"] = str(printable["repo_root"])
        printable["data_dir"] = str(printable["data_dir"])
        print(json.dumps(printable, ensure_ascii=False))
        return 0
    return run_server(config)


if __name__ == "__main__":
    raise SystemExit(main())
