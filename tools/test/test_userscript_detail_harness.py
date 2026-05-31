from __future__ import annotations

from pathlib import Path


def _userscript_detail_harness_html() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "tools" / "userscript_detail_harness.html").read_text(encoding="utf-8")


def test_userscript_detail_harness_references_live_userscript_path():
    html = _userscript_detail_harness_html()

    assert '/tampermonkey_scripts/fapaifang_unified.user.js' in html


def test_userscript_detail_harness_contains_detail_page_markers():
    html = _userscript_detail_harness_html()

    for marker in [
        'id="J_NoticeDetail"',
        'class="pm-main"',
        '测试小区',
        '建筑面积',
    ]:
        assert marker in html
