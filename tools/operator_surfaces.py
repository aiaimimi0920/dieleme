from __future__ import annotations

from pathlib import Path
import json


_EXCLUDE_DIRS = {"node_modules", "dist", ".git", "__pycache__", "venv", ".debug", "output"}
_LOCAL_HTML_TEST_PREFIXES = ("mock_", "test_")


def _is_excluded(path: Path) -> bool:
    return any(part in _EXCLUDE_DIRS for part in path.parts)


def first_party_package_script_manifests(repo_root: Path) -> list[Path]:
    manifests: list[Path] = []
    for package_json in sorted(repo_root.rglob("package.json")):
        if _is_excluded(package_json):
            continue
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        scripts = payload.get("scripts")
        if isinstance(scripts, dict) and scripts:
            manifests.append(package_json)
    return manifests


def first_party_batch_files(repo_root: Path) -> list[Path]:
    batch_files: list[Path] = []
    for path in sorted(repo_root.rglob("*.bat")):
        if _is_excluded(path):
            continue
        batch_files.append(path)
    return batch_files


def first_party_html_surfaces(repo_root: Path) -> list[Path]:
    html_files: list[Path] = []
    for path in sorted(repo_root.rglob("*.html")):
        if _is_excluded(path):
            continue
        if path.parent.name == "tools" and path.name.startswith(_LOCAL_HTML_TEST_PREFIXES):
            continue
        html_files.append(path)
    return html_files
