from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys

from tools import run_isolated_collection_api


def test_build_runtime_config_defaults_to_safe_isolated_flags():
    repo_root = Path(__file__).resolve().parents[2]

    config = run_isolated_collection_api.build_runtime_config(repo_root, port=8011)

    assert config["port"] == 8011
    assert config["repo_root"] == repo_root
    assert config["data_dir"] == repo_root / "datas"
    assert config["ensure_browser"] is False
    assert config["start_watchdog"] is False
    assert config["start_background_processors"] is False
    assert config["start_hot_reload"] is False
    assert config["skip_load_data"] is True
    assert config["db_url"] is None
    assert config["seed_location_codes"] == ["110101"]


def test_run_isolated_collection_api_script_can_run_print_config_from_repo_root():
    repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "run_isolated_collection_api.py"), "--print-config", "--port", "8011"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["port"] == 8011
    assert payload["ensure_browser"] is False
    assert payload["skip_load_data"] is True


def test_build_runtime_config_can_include_db_url():
    repo_root = Path(__file__).resolve().parents[2]

    config = run_isolated_collection_api.build_runtime_config(
        repo_root,
        port=8011,
        db_url="sqlite:///output/fapai-seed.db",
    )

    assert config["db_url"] == "sqlite:///output/fapai-seed.db"


def test_build_runtime_config_can_override_seed_location_codes():
    repo_root = Path(__file__).resolve().parents[2]

    config = run_isolated_collection_api.build_runtime_config(
        repo_root,
        port=8011,
        seed_location_codes=["310101", "440103"],
    )

    assert config["seed_location_codes"] == ["310101", "440103"]
