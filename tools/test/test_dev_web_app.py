from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from tools import dev_web_app


def test_web_app_dir_points_to_repo_frontend_root():
    repo_root = Path(__file__).resolve().parents[2]

    assert dev_web_app.web_app_dir(repo_root) == repo_root / "game" / "web-app"


def test_dev_command_uses_npm_cmd_and_localhost_port():
    workdir = Path(r"Z:\project\project\crow\game\web-app")

    assert dev_web_app.dev_command(workdir, port=43177) == [
        "npm.cmd",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "43177",
        "--strictPort",
    ]


def test_dev_helper_can_run_in_print_command_mode_from_repo_root():
    repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "dev_web_app.py"), "--print-command", "43177"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    assert "npm.cmd run dev" in result.stdout
