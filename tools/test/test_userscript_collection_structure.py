from __future__ import annotations

from pathlib import Path


def _userscript_source() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "tampermonkey_scripts" / "fapaifang_unified.user.js").read_text(encoding="utf-8")


def test_userscript_resume_server_helper_is_not_nested_inside_dashboard():
    source = _userscript_source()
    dashboard_start = source.index("function createDashboard()")
    toggle_start = source.index("function toggleRunState()")
    dashboard_block = source[dashboard_start:toggle_start]

    assert "function resumeServer(" not in dashboard_block


def test_userscript_declares_resume_server_helper_once():
    source = _userscript_source()

    assert source.count("function resumeServer(") == 1
