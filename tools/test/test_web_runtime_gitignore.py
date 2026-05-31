from __future__ import annotations

from pathlib import Path


def test_web_gitignore_ignores_generated_runtime_tailwind_css():
    repo_root = Path(__file__).resolve().parents[2]
    gitignore = (repo_root / "game" / "web-app" / ".gitignore").read_text(encoding="utf-8")

    assert "public/runtime-tailwind.css" in gitignore
