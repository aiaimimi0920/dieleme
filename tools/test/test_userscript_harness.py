from __future__ import annotations

from pathlib import Path


def _userscript_harness_html() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "tools" / "userscript_harness.html").read_text(encoding="utf-8")


def test_userscript_harness_references_live_userscript_path():
    html = _userscript_harness_html()

    assert '/tampermonkey_scripts/fapaifang_unified.user.js' in html


def test_userscript_harness_stubs_required_gm_apis():
    html = _userscript_harness_html()

    for api_name in [
        "GM_xmlhttpRequest",
        "GM_setValue",
        "GM_getValue",
        "GM_listValues",
        "GM_deleteValue",
        "GM_addValueChangeListener",
        "GM_openInTab",
        "GM_registerMenuCommand",
    ]:
        assert f"window.{api_name}" in html


def test_userscript_harness_declares_favicon_to_avoid_default_404():
    html = _userscript_harness_html()

    assert 'rel="icon"' in html
