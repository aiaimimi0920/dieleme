from __future__ import annotations

import json
from pathlib import Path


def _web_package_json() -> dict:
    repo_root = Path(__file__).resolve().parents[2]
    return json.loads((repo_root / "game" / "web-app" / "package.json").read_text(encoding="utf-8"))


def test_web_package_json_declares_runtime_tailwind_build_script():
    pkg = _web_package_json()

    assert pkg["scripts"]["build:runtime-css"]


def test_web_package_json_build_script_runs_runtime_tailwind_generation():
    pkg = _web_package_json()

    assert "build:runtime-css" in pkg["scripts"]["build"]


def test_web_package_json_dev_script_runs_runtime_tailwind_generation():
    pkg = _web_package_json()

    assert "build:runtime-css" in pkg["scripts"]["dev"]
