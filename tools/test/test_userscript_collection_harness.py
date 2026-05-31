from __future__ import annotations

from pathlib import Path


def _userscript_collection_harness_html() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "tools" / "userscript_collection_harness.html").read_text(encoding="utf-8")


def test_userscript_collection_harness_references_live_userscript_path():
    html = _userscript_collection_harness_html()

    assert '/tampermonkey_scripts/fapaifang_unified.user.js' in html


def test_userscript_collection_harness_contains_sniff_data_and_list_markers():
    html = _userscript_collection_harness_html()

    for marker in [
        'id="sf-item-list-data"',
        'class="sf-item-list"',
        '"status":"done"',
        '"bidCount":2',
    ]:
        assert marker in html


def test_userscript_collection_harness_stubs_request_collection():
    html = _userscript_collection_harness_html()

    assert "window.__gmRequests" in html
    assert "GM_xmlhttpRequest" in html
