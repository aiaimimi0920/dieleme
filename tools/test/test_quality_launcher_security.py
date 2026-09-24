"""Exercise generated launchers without replacing an installed application."""

import os
from pathlib import Path
import subprocess

import pytest


pytestmark = [pytest.mark.security, pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")]
ROOT = Path(__file__).resolve().parents[2]


def test_generated_launcher_contains_only_protected_password_reference(tmp_path):
    launcher = tmp_path / "launch.ps1"
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:DEPLOY_SOURCE, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Invalid deployment script' }
foreach ($name in @('Write-Utf8NoBomFile', 'Write-LauncherScript', 'Backup-ExistingInstall')) {
    $function = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    Invoke-Expression $function.Extent.Text
}
$args = @{
    LauncherPath = $env:TEST_LAUNCHER; ExecutablePath = 'fixture.exe'; ApiBaseUrl = 'https://nas.invalid';
    RemoteHost = 'pc2.invalid'; RemoteUserName = 'fixture'; RemotePasswordValue = 'synthetic-password';
    RemoteKeyPath = ''; DataRootValue = 'fixture-data'; CookieSnapshotValue = 'fixture-cookie';
    AuthBrowserModeValue = 'remote'; AuthLocalCdpPortValue = 9225; AuthRemoteCdpPortValue = 9225;
    AuthBrowserProfileDirValue = 'fixture-profile'; AuthBrowserPathValue = 'fixture-browser'
}
Write-LauncherScript @args
$text = [IO.File]::ReadAllText($env:TEST_LAUNCHER)
if ($text.Contains('synthetic-password')) { throw 'Plaintext password in launcher' }
function Start-Process { param($FilePath)
    if ($env:FAPAI_REMOTE_AUTH_PASSWORD -ne 'synthetic-password') { throw 'DPAPI credential did not round trip' }
}
. $env:TEST_LAUNCHER
$root = Split-Path -Parent $env:TEST_LAUNCHER
1..7 | ForEach-Object { New-Item -ItemType Directory -Path (Join-Path $root "backup\old-$_") -Force | Out-Null }
Backup-ExistingInstall -DestinationRoot $root
1..7 | ForEach-Object { if (-not (Test-Path (Join-Path $root "backup\old-$_"))) { throw 'Existing backup deleted' } }
Write-Output 'Protected credential round trip and backup preservation passed'
"""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "DEPLOY_SOURCE": str(ROOT / "scripts/deploy-collector-desktop-local.ps1"), "TEST_LAUNCHER": str(launcher)},
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "synthetic-password" not in launcher.read_text(encoding="utf-8")
