from __future__ import annotations

from pathlib import Path

from tools import docker_entrypoint


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_node_id_scopes_seed_worker_id_and_output_dir() -> None:
    command = docker_entrypoint.build_seed_collector_command(
        {
            "FAPAI_NODE_ID": "pc1",
            "FAPAI_OUTPUT_DIR": "/data/output/seed_collector_2",
            "FAPAI_SEED_WORKER_ID": "seed-2",
        }
    )

    assert command[command.index("--output-dir") + 1] == "/data/output/nodes/pc1/seed_collector_2"
    assert command[command.index("--worker-id") + 1] == "pc1-seed-2"


def test_node_id_scopes_detail_default_worker_id_and_output_dir() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_NODE_ID": "pc2",
            "FAPAI_OUTPUT_DIR": "/data/output/detail_worker",
            "FAPAI_RUN_MODE": "detail-worker",
        }
    )

    assert command[command.index("--output-dir") + 1] == "/data/output/nodes/pc2/detail_worker"
    assert command[command.index("--worker-id") + 1] == "pc2-detail-1"


def test_node_id_scoping_does_not_double_prefix_existing_values() -> None:
    command = docker_entrypoint.build_seed_collector_command(
        {
            "FAPAI_NODE_ID": "pc1",
            "FAPAI_OUTPUT_DIR": "/data/output/nodes/pc1/seed_collector",
            "FAPAI_SEED_WORKER_ID": "pc1-seed-1",
        }
    )

    assert command[command.index("--output-dir") + 1] == "/data/output/nodes/pc1/seed_collector"
    assert command[command.index("--worker-id") + 1] == "pc1-seed-1"


def test_nas_and_worker_compose_templates_exist_and_separate_roles() -> None:
    nas_compose = (REPO_ROOT / "docker-compose.nas-central.yml").read_text(encoding="utf-8")
    worker_compose = (REPO_ROOT / "docker-compose.worker-node.yml").read_text(encoding="utf-8")
    nas_env = (REPO_ROOT / "env.nas.example").read_text(encoding="utf-8")
    worker_env = (REPO_ROOT / "env.worker.example").read_text(encoding="utf-8")

    assert "fapaifang-postgres" in nas_compose
    assert "fapaifang-api" in nas_compose
    assert "fapaifang-seed-collector" not in nas_compose
    assert "fapaifang-postgres" not in worker_compose
    assert "fapaifang-api" not in worker_compose
    assert "FAPAI_NODE_ID" in worker_compose
    assert "FAPAI_LIST_BROWSER_FALLBACK" in worker_compose
    assert "FAPAI_DETAIL_CDP_ENDPOINT" in worker_env
    assert "FAPAI_SEED_CAPTCHA_SOLVER_ENABLED" in worker_env
    assert "FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED" in worker_env
    assert "FAPAI_SEED_AUTH_PROBE_INTERVAL_SECONDS" in worker_compose
    assert "192.168.15.200:55432" in worker_env
    assert "192.168.15.200:8001" in worker_env
    assert "FAPAI_NAS_DATA_ROOT" in nas_env


def test_nas_api_image_exposes_verifiable_build_identity_and_hotfix_dockerfile() -> None:
    compose = (REPO_ROOT / "docker-compose.nas-central.yml").read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    hotfix = (REPO_ROOT / "Dockerfile.nas-hotfix").read_text(encoding="utf-8")
    nas_env = (REPO_ROOT / "env.nas.example").read_text(encoding="utf-8")

    for name in (
        "FAPAI_BUILD_VERSION",
        "FAPAI_BUILD_COMMIT",
        "FAPAI_BUILD_TIME",
        "FAPAI_SOURCE_DIGEST",
    ):
        assert name in compose
        assert name in dockerfile
        assert name in hotfix
        assert name in nas_env
    assert "dockerfile: ${FAPAI_DOCKERFILE:-Dockerfile}" in compose
    assert "BASE_IMAGE: ${FAPAI_BASE_IMAGE:-fapaifang-collector:local}" in compose
    assert "org.opencontainers.image.revision" in compose
    assert "io.fapaifang.source-digest" in compose


def test_nas_api_deploy_helper_requires_backup_identity_health_gate_and_rollback() -> None:
    script = (REPO_ROOT / "scripts" / "deploy-nas-central-api.sh").read_text(encoding="utf-8")

    assert "set -euo pipefail" in script
    assert "pg_dump" in script
    assert "pg_restore -l" in script
    assert "docker image tag" in script
    assert "FAPAI_BUILD_VERSION" in script
    assert "FAPAI_SOURCE_DIGEST" in script
    assert 'build.get("version")' in script
    assert 'build.get("source_digest")' in script
    assert "up -d --no-deps --no-build fapaifang-api" in script
    assert "/api/collection/overview" in script
    assert "--dry-run" in script


def test_detail_worker_command_passes_durable_archive_root() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_NODE_ID": "pc2",
            "FAPAI_DETAIL_ARCHIVE_ROOT": "/data/datas",
        }
    )

    assert command[command.index("--detail-archive-root") + 1] == "/data/datas"


def test_detail_worker_command_omits_archive_root_when_unset() -> None:
    command = docker_entrypoint.build_detail_worker_command({"FAPAI_NODE_ID": "pc2"})

    assert "--detail-archive-root" not in command


def test_worker_node_compose_defaults_archive_root_to_mounted_datas() -> None:
    """容器里 /data/datas 是必挂的 bind，默认打开归档避免这一步被忘掉。

    代码层保持 opt-in（不配就不归档），但 worker 容器里挂载一定存在，
    所以在 compose 里给默认值。否则漏配一个环境变量就会让持久归档静默失效，
    而这正是 228,959 行没有归档原料的成因。
    """
    compose = (REPO_ROOT / "docker-compose.worker-node.yml").read_text(encoding="utf-8")

    assert "${FAPAI_DETAIL_ARCHIVE_ROOT:-/data/datas}" in compose

    detail_env_block = compose.split("x-worker-node-detail-env:")[1].split("x-worker-node-volumes:")[0]
    assert "FAPAI_DETAIL_ARCHIVE_ROOT" in detail_env_block, "归档变量必须在 detail env 块里"


def test_worker_nodes_prefer_live_cdp_cookies_before_snapshot_fallback() -> None:
    worker_compose = (REPO_ROOT / "docker-compose.worker-node.yml").read_text(encoding="utf-8")
    worker_env = (REPO_ROOT / "env.worker.example").read_text(encoding="utf-8")

    assert "FAPAI_COOKIE_SNAPSHOT_PREFER: ${FAPAI_COOKIE_SNAPSHOT_PREFER:-0}" in worker_compose
    assert "FAPAI_COOKIE_SNAPSHOT_PREFER=0" in worker_env


def test_worker_nodes_expose_report_cdp_endpoint_for_central_solver_callbacks() -> None:
    worker_compose = (REPO_ROOT / "docker-compose.worker-node.yml").read_text(encoding="utf-8")
    worker_env = (REPO_ROOT / "env.worker.example").read_text(encoding="utf-8")

    assert "FAPAI_REPORT_CDP_ENDPOINT: ${FAPAI_REPORT_CDP_ENDPOINT:-}" in worker_compose
    assert "FAPAI_REPORT_CDP_ENDPOINT=" in worker_env


def test_worker_node_compose_enables_real_solver_integration_for_seed_and_detail_paths() -> None:
    compose = (REPO_ROOT / "docker-compose.worker-node.yml").read_text(encoding="utf-8")

    assert "${FAPAI_DETAIL_CDP_ENDPOINT:-http://host.docker.internal:9223}" in compose
    assert "${FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED:-1}" in compose
    assert "${FAPAI_DETAIL_BROWSER_FALLBACK:-1}" in compose
    assert "${FAPAI_SEED_CAPTCHA_SOLVER_ENABLED:-1}" not in compose
    assert "${FAPAI_SEED_CAPTCHA_SOLVER_ENABLED:-0}" not in compose


def test_nas_deployment_doc_requires_seed_and_detail_solver_flags_for_real_module_integration() -> None:
    runbook = (REPO_ROOT / "docs" / "nas-central-deployment.md").read_text(encoding="utf-8")

    assert "FAPAI_SEED_CAPTCHA_SOLVER_ENABLED=1" in runbook
    assert "FAPAI_DETAIL_CDP_ENDPOINT=http://host.docker.internal:9223" in runbook
    assert "FAPAI_DETAIL_BROWSER_FALLBACK=1" in runbook
    assert "FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED=1" in runbook


def test_dockerfile_builds_and_copies_collector_desktop_dist_for_html_console() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "AS collector_desktop_builder" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "COPY --from=collector_desktop_builder" in dockerfile
    assert "/app/collector-desktop/dist" in dockerfile
    assert "!collector-desktop/index.html" in dockerignore
