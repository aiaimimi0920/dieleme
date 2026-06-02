from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_sync_script_exports_postgres_dump_to_external_data_root() -> None:
    script = REPO_ROOT.joinpath("scripts", "sync-docker-data-to-host.ps1").read_text(encoding="utf-8")

    assert "$SkipPostgres" in script
    assert "FAPAI_DATA_ROOT_HOST" in script
    assert "postgres\\backups" in script
    assert "pg_dump" in script
    assert "docker cp" in script
    assert "fapaifang-postgres" in script
