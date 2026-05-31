from __future__ import annotations

import os
from pathlib import Path
import json
import re
import subprocess
import sys


_NET_USE_MAPPING_PATTERN = re.compile(r"\b([A-Z]:)\s+(\\\\[^\s]+)", re.IGNORECASE)
_PACKAGE_JSON_EXCLUDE_DIRS = {"node_modules", "dist", ".git", "__pycache__"}


def _parse_net_use_mappings(output: str) -> list[tuple[str, str]]:
    mappings: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _NET_USE_MAPPING_PATTERN.finditer(output):
        drive = match.group(1).upper()
        unc_root = match.group(2).rstrip("\\")
        mapping = (drive, unc_root)
        if mapping in seen:
            continue
        seen.add(mapping)
        mappings.append(mapping)
    return mappings


def _remap_unc_path(path: Path, mappings: list[tuple[str, str]]) -> Path | None:
    raw_path = str(path)
    if not raw_path.startswith("\\\\"):
        return path

    normalized_path = raw_path.rstrip("\\")
    ranked_mappings = sorted(mappings, key=lambda item: len(item[1]), reverse=True)
    for drive, unc_root in ranked_mappings:
        normalized_root = unc_root.rstrip("\\")
        if normalized_path.lower() == normalized_root.lower():
            return Path(f"{drive}\\")
        prefix = normalized_root + "\\"
        if normalized_path.lower().startswith(prefix.lower()):
            suffix = normalized_path[len(prefix) :]
            return Path(f"{drive}\\{suffix}")
    return None


def resolve_local_workdirs(path: Path, net_use_output: str | None = None) -> list[Path]:
    raw_path = str(path)
    if not raw_path.startswith("\\\\"):
        return [path]

    if net_use_output is None:
        result = subprocess.run(
            ["net", "use"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        net_use_output = result.stdout

    mappings = _parse_net_use_mappings(net_use_output)
    ranked_mappings = sorted(mappings, key=lambda item: len(item[1]), reverse=True)
    candidates: list[Path] = []
    seen: set[str] = set()
    for drive, unc_root in ranked_mappings:
        candidate = _remap_unc_path(path, [(drive, unc_root)])
        if candidate is None:
            continue
        normalized = str(candidate).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(candidate)
    if not candidates:
        raise RuntimeError(
            f"No mapped drive alias found for UNC path: {path}. "
            "Map the share to a local drive or run the build from a local-drive mirror."
        )
    return candidates


def resolve_local_workdir(path: Path, net_use_output: str | None = None) -> Path:
    return resolve_local_workdirs(path, net_use_output=net_use_output)[0]


def _npm_build_command() -> list[str]:
    npm_executable = "npm.cmd" if os.name == "nt" else "npm"
    return [npm_executable, "run", "build"]


def repo_web_build_dirs(repo_root: Path) -> list[Path]:
    build_dirs: list[Path] = []
    for package_json in sorted(repo_root.rglob("package.json")):
        relative_parts = package_json.relative_to(repo_root).parts
        if any(part in _PACKAGE_JSON_EXCLUDE_DIRS or part.startswith(".pytest-tmp") for part in relative_parts):
            continue
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        scripts = payload.get("scripts")
        if not isinstance(scripts, dict):
            continue
        build_script = scripts.get("build")
        if isinstance(build_script, str) and build_script.strip():
            build_dirs.append(package_json.parent)
    return build_dirs


def build_web_app(web_app_dir: Path) -> int:
    workdirs = resolve_local_workdirs(web_app_dir)
    failures: list[tuple[Path, subprocess.CompletedProcess[str]]] = []
    for workdir in workdirs:
        result = subprocess.run(
            _npm_build_command(),
            cwd=str(workdir),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
            return 0
        failures.append((workdir, result))

    for workdir, result in failures:
        print(f"[build_web_app] build failed in {workdir}", file=sys.stderr)
        if result.stdout:
            print(result.stdout, end="", file=sys.stderr)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
    return failures[-1][1].returncode if failures else 1


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    web_app_dir = repo_root / "game" / "web-app"
    if not web_app_dir.exists():
        raise SystemExit(f"web app directory not found: {web_app_dir}")
    return build_web_app(web_app_dir)


if __name__ == "__main__":
    sys.exit(main())
