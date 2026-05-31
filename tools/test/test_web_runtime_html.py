from __future__ import annotations

from pathlib import Path


def _web_app_index_html() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "game" / "web-app" / "index.html").read_text(encoding="utf-8")


def test_web_runtime_html_uses_production_vue_cdn_build():
    html = _web_app_index_html()

    assert "vue.global.prod.js" in html
    assert "vue.global.js" not in html


def test_web_runtime_html_declares_favicon_to_avoid_default_404():
    html = _web_app_index_html()

    assert 'rel="icon"' in html


def test_web_runtime_html_does_not_use_tailwind_cdn_runtime_script():
    html = _web_app_index_html()

    assert "cdn.tailwindcss.com" not in html


def test_web_runtime_html_links_local_runtime_tailwind_stylesheet():
    html = _web_app_index_html()

    assert 'href="/runtime-tailwind.css"' in html
