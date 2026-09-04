from __future__ import annotations

import json
from pathlib import Path
import os
import shutil
import subprocess
import sys

def _copy_repo_batch_to_fake_repo(repo_root: Path, tmp_path: Path, name: str) -> Path:
    fake_repo = tmp_path / "repo"
    (fake_repo / "auto").mkdir(parents=True, exist_ok=True)
    (fake_repo / "src").mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "auto" / name, fake_repo / "auto" / name)
    for helper_path in (repo_root / "auto").glob("*.ps1"):
        shutil.copy2(helper_path, fake_repo / "auto" / helper_path.name)
    return fake_repo


def _write_fake_python_cmd(fake_repo: Path, log_path: Path) -> Path:
    fake_python = fake_repo / "fake_python.cmd"
    fake_python.write_text(
        "\n".join(
            [
                "@echo off",
                f'echo STUB_CWD=%CD%> "{log_path}"',
                f'echo STUB_ARGS=%*>> "{log_path}"',
                "exit /b 0",
            ]
        ),
        encoding="utf-8",
    )
    return fake_python


def _write_fake_python_cmd_with_exit(fake_repo: Path, log_path: Path, exit_code: int) -> Path:
    fake_python = fake_repo / "fake_python_exit.cmd"
    fake_python.write_text(
        "\n".join(
            [
                "@echo off",
                f'echo STUB_CWD=%CD%> "{log_path}"',
                f'echo STUB_ARGS=%*>> "{log_path}"',
                f"exit /b {exit_code}",
            ]
        ),
        encoding="utf-8",
    )
    return fake_python


def _write_fake_python_cmd_with_exit_and_summary(
    fake_repo: Path,
    log_path: Path,
    *,
    summary_path: Path,
    exit_code: int,
    summary_payload: dict[str, object],
) -> Path:
    fake_python = fake_repo / "fake_python_with_summary.cmd"
    fake_python.write_text(
        "\n".join(
            [
                "@echo off",
                f'echo STUB_CWD=%CD%> "{log_path}"',
                f'echo STUB_ARGS=%*>> "{log_path}"',
                f'echo {json.dumps(summary_payload, ensure_ascii=False)}> "{summary_path}"',
                f"exit /b {exit_code}",
            ]
        ),
        encoding="utf-8",
    )
    return fake_python


def _write_real_python_target(target_path: Path, log_path: Path) -> None:
    target_path.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                f'Path(r"{str(log_path)}").write_text("REAL_PYTHON_INVOKED", encoding="utf-8")',
            ]
        ),
        encoding="utf-8",
    )


def _run_batch(batch_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cmd", "/c", str(batch_path)],
        cwd=str(batch_path.parent),
        env=env,
        input="\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _path_matches_windows_drive_alias(invoked_cwd: Path, expected_cwd: Path) -> bool:
    if invoked_cwd == expected_cwd:
        return True
    try:
        if invoked_cwd.exists() and expected_cwd.exists() and invoked_cwd.samefile(expected_cwd):
            return True
    except OSError:
        pass
    if os.name != "nt" or not invoked_cwd.anchor or not expected_cwd.anchor:
        return False
    invoked_parts = tuple(part.casefold() for part in invoked_cwd.parts[1:])
    expected_parts = tuple(part.casefold() for part in expected_cwd.parts[1:])
    return invoked_parts == expected_parts


def _assert_stub_invocation(
    log_path: Path,
    expected_arg: str,
    expected_cwd: Path | None = None,
) -> None:
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("STUB_CWD=")
    invoked_cwd = Path(lines[0].split("=", 1)[1])
    if expected_cwd is not None:
        assert _path_matches_windows_drive_alias(invoked_cwd, expected_cwd)
    assert lines[1] == f"STUB_ARGS={expected_arg}"

__all__ = [name for name in globals() if not name.startswith("__")]
