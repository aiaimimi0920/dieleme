"""Python discovery selects one executable when PATH has multiple matches."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows resolver")


@pytest.mark.parametrize("requested", ["", "python"])
def test_python_resolution_does_not_join_application_paths(requested, tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/resolve-pc1-auth-python.ps1"
    escape = lambda value: str(value).replace("'", "''")
    command = f"""
$ErrorActionPreference = 'Stop'
$env:FAPAI_DESKTOP_PYTHON_PATH = ''
function Get-Command {{
    @([pscustomobject]@{{Source='{escape(sys.executable)}'}},
      [pscustomobject]@{{Source='{escape(tmp_path / "unusable-python.exe")}'}})
}}
. '{escape(script)}'
Resolve-Pc1AuthPython -Requested '{requested}'
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert Path(result.stdout.strip()).resolve() == Path(sys.executable).resolve()
