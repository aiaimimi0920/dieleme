from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from tools import preview_userscript_harness


def test_harness_url_uses_localhost_tools_path():
    assert preview_userscript_harness.harness_url(43180) == "http://127.0.0.1:43180/tools/userscript_harness.html"


def test_preview_command_uses_python_http_server_for_repo_root():
    workdir = Path(r"Z:\project\project\crow")

    assert preview_userscript_harness.preview_command(workdir, 43180) == [
        sys.executable,
        "-m",
        "http.server",
        "43180",
        "--directory",
        str(workdir),
    ]


def test_preview_userscript_harness_helper_can_run_in_print_command_mode():
    repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "preview_userscript_harness.py"), "--print-command", "43180"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    assert "http.server" in result.stdout
    assert "userscript_harness.html" in result.stdout
