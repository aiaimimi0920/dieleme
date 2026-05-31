from __future__ import annotations

from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import build_web_app


def repo_root_dir() -> Path:
    return REPO_ROOT


def harness_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/tools/userscript_harness.html"


def preview_command(workdir: Path, port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "http.server",
        str(port),
        "--directory",
        str(workdir),
    ]


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    port = 43180
    print_command_only = False
    if args and args[0] == "--print-command":
        print_command_only = True
        args = args[1:]
    if args:
        port = int(args[0])

    local_root = build_web_app.resolve_local_workdir(repo_root_dir())
    command = preview_command(local_root, port)
    if print_command_only:
        print(" ".join(command))
        print(harness_url(port))
        return 0
    print(f"[preview_userscript_harness] Serving {local_root} at {harness_url(port)}")
    subprocess.run(command, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
