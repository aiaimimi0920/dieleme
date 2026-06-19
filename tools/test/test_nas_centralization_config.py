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
    assert "FAPAI_SEED_AUTH_PROBE_INTERVAL_SECONDS" in worker_compose
    assert "192.168.15.200:55432" in worker_env
    assert "192.168.15.200:8001" in worker_env
    assert "FAPAI_NAS_DATA_ROOT" in nas_env


def test_dockerfile_builds_and_copies_collector_desktop_dist_for_html_console() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "AS collector_desktop_builder" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "COPY --from=collector_desktop_builder" in dockerfile
    assert "/app/collector-desktop/dist" in dockerfile
    assert "!collector-desktop/index.html" in dockerignore
