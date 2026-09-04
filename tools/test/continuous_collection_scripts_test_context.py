from __future__ import annotations

from pathlib import Path

from tools.test.powershell_script_test_support import read_powershell_script_tree

REPO_ROOT = Path(__file__).resolve().parents[2]

def _script(name: str) -> str:
    return read_powershell_script_tree(REPO_ROOT.joinpath("scripts", name))

def _pc2_host_script(name: str) -> str:
    return read_powershell_script_tree(REPO_ROOT.joinpath("ops", "pc2-host", name))


__all__ = [name for name in globals() if not name.startswith("__")]
