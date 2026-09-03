from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from tools import preview_web_app


def test_web_app_dist_dir_points_to_repo_dist_artifact():
    repo_root = Path(__file__).resolve().parents[2]

    assert preview_web_app.web_app_dist_dir(repo_root) == repo_root / "game" / "web-app" / "dist"


def test_preview_command_uses_python_http_server_for_selected_port():
    dist_dir = Path(r"Z:\project\project\crow\game\web-app\dist")

    assert preview_web_app.preview_command(dist_dir, port=43173) == [
        sys.executable,
        "-m",
        "http.server",
        "43173",
        "--directory",
        str(dist_dir),
    ]


def test_preview_helper_can_run_in_print_command_mode_from_repo_root():
    repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "preview_web_app.py"), "--print-command", "43174"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    assert "http.server" in result.stdout
