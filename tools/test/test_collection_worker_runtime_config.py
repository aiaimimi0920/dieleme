from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]


def _service_block(compose_text: str, service_name: str) -> str:
    match = re.search(rf"^  {re.escape(service_name)}:\n", compose_text, flags=re.MULTILINE)
    assert match is not None
    next_service = re.search(r"^  [A-Za-z0-9_-]+:\n", compose_text[match.end() :], flags=re.MULTILINE)
    if next_service is None:
        return compose_text[match.start() :]
    return compose_text[match.start() : match.end() + next_service.start()]


def test_seed_and_detail_workers_use_internal_db_without_runtime_ddl() -> None:
    compose = REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")

    for service_name in ("fapaifang-seed-collector", "fapaifang-detail-worker"):
        block = _service_block(compose, service_name)
        assert "FAPAI_DB_URL: ${FAPAI_WORKER_DB_URL:-postgresql+psycopg://fapaifang:fapaifang@postgres:5432/fapaifang}" in block
        assert "FAPAI_DB_SCHEMA_GUARD: ${FAPAI_WORKER_DB_SCHEMA_GUARD:-0}" in block
        assert "FAPAI_DB_AUTO_CREATE: ${FAPAI_WORKER_DB_AUTO_CREATE:-0}" in block
        assert "FAPAI_DB_ENABLE_POSTGIS: ${FAPAI_WORKER_DB_ENABLE_POSTGIS:-0}" in block
