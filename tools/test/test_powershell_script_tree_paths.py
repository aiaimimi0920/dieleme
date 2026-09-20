from pathlib import Path

import pytest

from tools.test.powershell_script_test_support import read_powershell_script_tree


def test_script_root_imports_resolve_sibling_and_nested_modules(tmp_path: Path):
    entry = tmp_path / "watch.ps1"
    entry.write_text('. (Join-Path $PSScriptRoot "policy.ps1")\n'
                     '. (Join-Path $PSScriptRoot "browser\\window.ps1")', encoding="utf-8")
    (tmp_path / "policy.ps1").write_text("policy-first", encoding="utf-8")
    (tmp_path / "browser").mkdir()
    (tmp_path / "browser/window.ps1").write_text("window-second", encoding="utf-8")
    assert read_powershell_script_tree(entry) == "policy-first\nwindow-second"


def test_facade_modules_still_reject_unreferenced_files(tmp_path: Path):
    entry = tmp_path / "watch.ps1"
    entry.write_text('. (Join-Path $moduleRoot "policy.ps1")', encoding="utf-8")
    modules = tmp_path / "watch"
    modules.mkdir()
    (modules / "policy.ps1").write_text("referenced", encoding="utf-8")
    (modules / "forgotten.ps1").write_text("unreferenced", encoding="utf-8")
    with pytest.raises(ValueError, match="unreferenced files"):
        read_powershell_script_tree(entry)
