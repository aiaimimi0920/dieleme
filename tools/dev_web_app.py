from __future__ import annotations

from pathlib import Path
import sys
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import build_web_app


def web_app_dir(repo_root: Path) -> Path:
    return repo_root / "game" / "web-app"


def dev_command(workdir: Path, port: int) -> list[str]:
    npm_executable = "npm.cmd" if sys.platform.startswith("win") else "npm"
    return [
        npm_executable,
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--strictPort",
    ]


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    port = 43177
    print_command_only = False
    if args and args[0] == "--print-command":
        print_command_only = True
        args = args[1:]
    if args:
        port = int(args[0])

    repo_root = REPO_ROOT
    workdir = build_web_app.resolve_local_workdir(web_app_dir(repo_root))
    command = dev_command(workdir, port)
    if print_command_only:
        print(" ".join(command))
        return 0
    subprocess.run(command, cwd=str(workdir), check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
