from __future__ import annotations

from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import build_web_app


def web_app_dist_dir(repo_root: Path) -> Path:
    return repo_root / "game" / "web-app" / "dist"


def preview_command(dist_dir: Path, port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "http.server",
        str(port),
        "--directory",
        str(dist_dir),
    ]


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    port = 43173
    print_command_only = False
    if args and args[0] == "--print-command":
        print_command_only = True
        args = args[1:]
    if args:
        port = int(args[0])
    repo_root = REPO_ROOT
    dist_dir = web_app_dist_dir(repo_root)
    local_dist_dirs = build_web_app.resolve_local_workdirs(dist_dir)
    command = preview_command(local_dist_dirs[0], port)
    if print_command_only:
        print(" ".join(command))
        return 0
    build_web_app.build_web_app(repo_root / "game" / "web-app")
    print(f"[preview_web_app] Serving {local_dist_dirs[0]} at http://127.0.0.1:{port}/")
    subprocess.run(command, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
