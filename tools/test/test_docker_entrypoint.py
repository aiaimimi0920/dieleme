from __future__ import annotations

import subprocess
import sys
import warnings

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SAWarning

from src.storage.models import Base
from tools import docker_entrypoint


def test_dockerfile_supports_offline_wheelhouse_installation() -> None:
    dockerfile = docker_entrypoint.REPO_ROOT.joinpath("Dockerfile").read_text(encoding="utf-8")

    assert "ARG PYTHON_BASE_IMAGE=python:3.10-slim" in dockerfile
    assert "COPY vendor/wheels/ /tmp/wheels/" in dockerfile
    assert "--no-index --find-links=/tmp/wheels" in dockerfile


def test_importing_docker_entrypoint_does_not_eagerly_import_storage_repository() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import tools.docker_entrypoint; print('src.storage.repository' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == "False"


def test_default_compose_uses_docker_volumes_for_verified_persistent_state() -> None:
    compose = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")
    postgres_compose = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.postgres.yml").read_text(encoding="utf-8")

    assert "fapaifang-output:/data/output" in compose
    assert "fapaifang-datas:/data/datas" in compose
    assert "fapaifang-jobs:/data/jobs" in compose
    assert "volumes:\n  fapaifang-output:\n  fapaifang-datas:\n  fapaifang-jobs:" in compose
    assert "postgres_data:/var/lib/postgresql/data" in postgres_compose
    assert "volumes:\n  postgres_data:" in postgres_compose


def test_host_bind_overrides_are_explicit_opt_in() -> None:
    collection_override = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.host-bind.yml").read_text(encoding="utf-8")
    postgres_override = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.postgres.host-bind.yml").read_text(encoding="utf-8")

    assert "source: ${FAPAI_DATA_ROOT_HOST:?set FAPAI_DATA_ROOT_HOST}/output" in collection_override
    assert "target: /data/output" in collection_override
    assert "source: ${FAPAI_DATA_ROOT_HOST:?set FAPAI_DATA_ROOT_HOST}/datas" in collection_override
    assert "target: /data/datas" in collection_override
    assert "source: ${FAPAI_DATA_ROOT_HOST:?set FAPAI_DATA_ROOT_HOST}/jobs" in collection_override
    assert "target: /data/jobs" in collection_override
    assert "source: ${FAPAI_DATA_ROOT_HOST:?set FAPAI_DATA_ROOT_HOST}/postgres" in postgres_override
    assert "target: /var/lib/postgresql/data" in postgres_override


def test_compose_uses_ignored_local_env_file() -> None:
    compose = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")
    gitignore = docker_entrypoint.REPO_ROOT.joinpath(".gitignore").read_text(encoding="utf-8")
    dockerignore = docker_entrypoint.REPO_ROOT.joinpath(".dockerignore").read_text(encoding="utf-8")

    assert "env_file:" in compose
    assert "path: docker.local.env" in compose
    assert "required: false" in compose
    assert "docker.local.env" in gitignore
    assert "docker.local.env" in dockerignore


def test_compose_defaults_to_split_seed_and_detail_workers() -> None:
    compose = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")

    assert "fapaifang-seed-collector:" in compose
    assert "container_name: fapaifang-seed-collector" in compose
    assert "FAPAI_RUN_MODE: seed-collector" in compose
    assert "fapaifang-detail-worker:" in compose
    assert "container_name: fapaifang-detail-worker" in compose
    assert "FAPAI_RUN_MODE: detail-worker" in compose
    assert 'profiles: ["legacy"]' in compose


def test_live_loop_command_uses_persistent_resume_state() -> None:
    command = docker_entrypoint.build_live_command(
        {
            "FAPAI_RUN_MODE": "live-loop",
            "FAPAI_OUTPUT_DIR": "/data/live",
            "FAPAI_RESUME_STATE": "/data/live/resume_state.json",
            "FAPAI_CDP_ENDPOINT": "http://host.docker.internal:9223",
            "FAPAI_TARGET_URL": "https://sf.taobao.com/list/page",
            "FAPAI_TARGET_SUCCESS": "3",
            "FAPAI_MAX_ATTEMPTS": "20",
            "FAPAI_LOOP_INTERVAL_SECONDS": "0",
            "FAPAI_MAX_RUNS": "2",
        }
    )

    assert command[:3] == [sys.executable, "tools/live_batch_smoke.py", "--output-dir"]
    assert "/data/live" in command
    assert "--loop" in command
    assert command[command.index("--resume-state") + 1] == "/data/live/resume_state.json"
    assert command[command.index("--cdp-endpoint") + 1] == "http://host.docker.internal:9223"
    assert command[command.index("--target-success") + 1] == "3"
    assert command[command.index("--max-attempts") + 1] == "20"
    assert command[command.index("--max-runs") + 1] == "2"
    assert command[command.index("--list-st-params") + 1] == "2,1,0,3,4,5"
    assert command[command.index("--list-max-pages") + 1] == "83"
    assert "--llm-preflight" in command


def test_live_command_passes_multi_sort_union_options() -> None:
    command = docker_entrypoint.build_live_command(
        {
            "FAPAI_RUN_MODE": "live-batch",
            "FAPAI_LIST_ST_PARAMS": "2,1",
            "FAPAI_LIST_LOCATION_CODES": "110101,110102",
            "FAPAI_LIST_CATEGORIES": "50025969",
            "FAPAI_LIST_MAX_PAGES": "5",
            "FAPAI_LIST_STOP_ON_EMPTY": "0",
        }
    )

    assert command[command.index("--list-st-params") + 1] == "2,1"
    assert command[command.index("--list-location-codes") + 1] == "110101,110102"
    assert command[command.index("--list-categories") + 1] == "50025969"
    assert command[command.index("--list-max-pages") + 1] == "5"
    assert "--no-list-stop-on-empty" in command


def test_live_command_can_disable_llm_preflight() -> None:
    command = docker_entrypoint.build_live_command(
        {
            "FAPAI_RUN_MODE": "live-batch",
            "FAPAI_LLM_PREFLIGHT": "0",
        }
    )

    assert "--llm-preflight" not in command


def test_seed_collector_command_uses_db_backed_region_sort_progress() -> None:
    command = docker_entrypoint.build_seed_collector_command(
        {
            "FAPAI_OUTPUT_DIR": "/data/output/seed_collector",
            "FAPAI_CDP_ENDPOINT": "http://host.docker.internal:9223",
            "FAPAI_SEED_JOB_KEY": "guangdong-guangzhou-nansha-50025969",
            "FAPAI_SEED_PROVINCE": "广东省",
            "FAPAI_SEED_CITY": "广州市",
            "FAPAI_SEED_DISTRICT": "南沙区",
            "FAPAI_SEED_LOCATION_CODE": "440115",
            "FAPAI_SEED_CATEGORY": "50025969",
            "FAPAI_SEED_SORTS": "bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远",
            "FAPAI_SEED_MAX_PAGE": "83",
            "FAPAI_SEED_PAGES_PER_RUN": "7",
            "FAPAI_SEED_LOOP_INTERVAL_SECONDS": "1800",
            "FAPAI_SEED_MAX_RUNS": "2",
        }
    )

    assert command[:2] == [sys.executable, "tools/seed_collector.py"]
    assert command[command.index("--output-dir") + 1] == "/data/output/seed_collector"
    assert command[command.index("--job-key") + 1] == "guangdong-guangzhou-nansha-50025969"
    assert command[command.index("--location-code") + 1] == "440115"
    assert command[command.index("--sorts") + 1] == "bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远"
    assert command[command.index("--max-page") + 1] == "83"
    assert command[command.index("--pages-per-run") + 1] == "7"
    assert "--loop" in command
    assert command[command.index("--max-runs") + 1] == "2"


def test_detail_worker_command_consumes_db_seed_queue() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_OUTPUT_DIR": "/data/output/detail_worker",
            "FAPAI_CDP_ENDPOINT": "http://host.docker.internal:9223",
            "FAPAI_DETAIL_TARGET_SUCCESS": "3",
            "FAPAI_DETAIL_MAX_ATTEMPTS": "10",
            "FAPAI_DETAIL_LOOP_INTERVAL_SECONDS": "900",
            "FAPAI_DETAIL_MAX_RUNS": "2",
            "FAPAI_ENABLE_RISK": "1",
            "FAPAI_LLM_PREFLIGHT": "1",
        }
    )

    assert command[:2] == [sys.executable, "tools/detail_worker.py"]
    assert command[command.index("--output-dir") + 1] == "/data/output/detail_worker"
    assert command[command.index("--target-success") + 1] == "3"
    assert command[command.index("--max-attempts") + 1] == "10"
    assert "--risk" in command
    assert "--llm-preflight" in command
    assert "--loop" in command
    assert command[command.index("--max-runs") + 1] == "2"


def test_live_batch_command_can_disable_resume_explicitly() -> None:
    command = docker_entrypoint.build_live_command(
        {
            "FAPAI_RUN_MODE": "live-batch",
            "FAPAI_DISABLE_RESUME": "1",
        }
    )

    assert "--loop" not in command
    assert "--no-resume" in command
    assert "--resume-state" not in command


def test_api_command_passes_db_url_and_location_codes() -> None:
    command = docker_entrypoint.build_api_command(
        {
            "FAPAI_API_PORT": "8011",
            "FAPAI_DB_URL": "postgresql+psycopg://user:pass@postgres:5432/fapaifang",
            "FAPAI_SEED_LOCATION_CODES": "110101,110102",
        }
    )

    assert command[:2] == [sys.executable, "tools/run_isolated_collection_api.py"]
    assert command[command.index("--port") + 1] == "8011"
    assert command[command.index("--db-url") + 1] == "postgresql+psycopg://user:pass@postgres:5432/fapaifang"
    assert command.count("--seed-location-code") == 2
    assert "110101" in command
    assert "110102" in command


def test_area_followup_command_supports_apply_and_push() -> None:
    command = docker_entrypoint.build_area_followup_command(
        {
            "FAPAI_AREA_QUEUE": "/data/live/area_followup_queue.json",
            "FAPAI_OUTPUT_DIR": "/data/live",
            "FAPAI_CDP_ENDPOINT": "http://host.docker.internal:9223",
            "FAPAI_AREA_APPLY_PATCHES": "true",
            "FAPAI_AREA_PUSH_URL": "http://fapaifang-api:8001/api/collection/details/area_result",
        }
    )

    assert command[:2] == [sys.executable, "tools/area_followup_runner.py"]
    assert command[command.index("--queue") + 1] == "/data/live/area_followup_queue.json"
    assert command[command.index("--output-dir") + 1] == "/data/live"
    assert "--apply-patches" in command
    assert command[command.index("--push-area-result") + 1] == "http://fapaifang-api:8001/api/collection/details/area_result"


def test_database_schema_guard_fails_fast_when_existing_table_is_missing_required_column(tmp_path) -> None:
    db_path = tmp_path / "old-schema.sqlite3"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE fapai_seed_item (
                    item_id VARCHAR(64) PRIMARY KEY,
                    source_item_id VARCHAR(64)
                )
                """
            )
        )

    with pytest.raises(RuntimeError) as exc_info:
        docker_entrypoint.guard_database_schema(
            {
                "FAPAI_DB_URL": f"sqlite:///{db_path.as_posix()}",
                "FAPAI_DB_ENABLED": "1",
                "FAPAI_DB_SCHEMA_GUARD": "1",
            }
        )

    message = str(exc_info.value)
    assert "database schema is not compatible" in message
    assert "fapai_seed_item" in message
    assert "detail_completed_at" in message


def test_actual_database_schema_suppresses_irrelevant_sqlalchemy_type_warnings(monkeypatch) -> None:
    class _FakeEngine:
        def __init__(self) -> None:
            self.disposed = False

        def dispose(self) -> None:
            self.disposed = True

    class _FakeInspector:
        def get_table_names(self):
            return ["property_listing"]

        def get_columns(self, _table_name):
            warnings.warn("Did not recognize type 'geography' of column 'geom'", SAWarning)
            return [{"name": "item_id"}, {"name": "geom"}]

    fake_engine = _FakeEngine()
    monkeypatch.setattr(docker_entrypoint, "create_engine", lambda *_args, **_kwargs: fake_engine)
    monkeypatch.setattr(docker_entrypoint, "inspect", lambda _engine: _FakeInspector())

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        actual = docker_entrypoint._actual_database_schema("postgresql+psycopg://example")

    assert actual == {"property_listing": {"item_id", "geom"}}
    assert fake_engine.disposed is True
    assert caught == []


def test_database_schema_guard_passes_for_current_model_schema(tmp_path) -> None:
    db_path = tmp_path / "current-schema.sqlite3"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    Base.metadata.create_all(engine)

    docker_entrypoint.guard_database_schema(
        {
            "FAPAI_DB_URL": f"sqlite:///{db_path.as_posix()}",
            "FAPAI_DB_ENABLED": "1",
            "FAPAI_DB_SCHEMA_GUARD": "1",
        }
    )


def test_database_schema_guard_allows_empty_database_for_repository_auto_create(tmp_path) -> None:
    db_path = tmp_path / "empty-schema.sqlite3"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    with engine.begin():
        pass

    docker_entrypoint.guard_database_schema(
        {
            "FAPAI_DB_URL": f"sqlite:///{db_path.as_posix()}",
            "FAPAI_DB_ENABLED": "1",
            "FAPAI_DB_SCHEMA_GUARD": "1",
        }
    )


def test_database_schema_guard_skips_when_database_url_is_absent() -> None:
    docker_entrypoint.guard_database_schema(
        {
            "FAPAI_DB_ENABLED": "1",
            "FAPAI_DB_SCHEMA_GUARD": "1",
        }
    )


def test_database_schema_guard_skips_when_explicitly_disabled(tmp_path) -> None:
    db_path = tmp_path / "old-schema.sqlite3"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE fapai_seed_item (item_id VARCHAR(64) PRIMARY KEY)"))

    docker_entrypoint.guard_database_schema(
        {
            "FAPAI_DB_URL": f"sqlite:///{db_path.as_posix()}",
            "FAPAI_DB_ENABLED": "1",
            "FAPAI_DB_SCHEMA_GUARD": "0",
        }
    )


def test_main_returns_nonzero_and_does_not_exec_when_startup_check_fails(monkeypatch, capsys) -> None:
    executed_commands: list[list[str]] = []

    def _fail_startup_checks(_env):
        raise RuntimeError("schema drift detected")

    def _record_subprocess_call(command):
        executed_commands.append(command)
        return 0

    monkeypatch.setattr(docker_entrypoint, "run_startup_checks", _fail_startup_checks)
    monkeypatch.setattr(docker_entrypoint.subprocess, "call", _record_subprocess_call)

    assert docker_entrypoint.main() == 1
    assert executed_commands == []
    captured = capsys.readouterr()
    assert "[docker-entrypoint] startup check failed:" in captured.err
    assert "schema drift detected" in captured.err
