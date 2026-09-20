from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tools import taobao_inplace_auth_handoff as handoff


def test_handoff_reports_seed_challenge_without_replacing_snapshot(monkeypatch, tmp_path, capsys):
    official = tmp_path / "cookies.json"
    official.write_text("preserved", encoding="utf-8")
    monkeypatch.setattr(handoff, "_healthy_open_detail_page",
                        lambda _: ("healthy", "https://sf-item.taobao.com/sf_item/123456789.htm"))
    monkeypatch.setattr(handoff.browserless_seed_probe, "export_cdp_cookies",
                        lambda *_args, **_kwargs: [{"name": "session", "value": "not-for-output"}])
    monkeypatch.setattr(handoff.browserless_seed_probe, "resolve_cdp_user_agent", lambda _: "test-agent")
    monkeypatch.setattr(handoff, "_validate_cookie_http", lambda *_args, **_kwargs: {
        "healthy": False, "list_healthy_samples": 0, "detail_http_healthy": True, "list_only_mode": False,
    })

    assert handoff.main(["--cdp-endpoint", "http://localhost:9225", "--output-path", str(official)]) == 2
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["blocking_scope"] == "seed"
    assert result["detail_http_healthy"] is True
    assert result["list_healthy_samples"] == 0
    assert result["official_snapshot_promoted"] is False
    assert "not-for-output" not in output
    assert official.read_text(encoding="utf-8") == "preserved"


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows PowerShell required")
def test_seed_prompt_keeps_query_identity_and_reuses_its_own_tab():
    policy = Path(__file__).resolve().parents[2] / "scripts/pc1-auth-recovery-policy.ps1"
    script = r"""
$ErrorActionPreference = 'Stop'
. '__POLICY__'
$target = 'https://sf.taobao.com/list/50025969__2.htm?location_code=120104&st_param=4&page=40&x5secdata=private'
$solver = @{scopes=@{seed=@{last_request=@{target_url=$target}}}}
$script:tabs = @(@{id='wrong-page';type='page';url=($target -replace 'page=40','page=1')})
$script:creates = 0
$script:shows = 0
$script:createdUrl = ''
$state = @{}
function Get-CdpTabs { return $script:tabs }
function Invoke-CdpWebRequest {
    param($Uri, $Method, $TimeoutSec)
    if ($Method -ne 'PUT') { throw 'Unexpected request' }
    $script:creates++
    $script:createdUrl = [Uri]::UnescapeDataString($Uri.Split('?', 2)[1])
    $tab = @{id='owned-seed';type='page';url=$script:createdUrl}
    $script:tabs += $tab
    return @{Content=($tab | ConvertTo-Json -Compress)}
}
function Write-State { param($Path, $State) }
function Show-Pc1RecoveryPrompt { $script:shows++ }
foreach ($poll in 1..3) {
    Show-Pc1RecoverySeedPrompt -State $state -StatePath 'unused' -Endpoint 'http://localhost:9225' `
        -SolverStatus $solver -FallbackUrl 'https://sf.taobao.com/list/50025969__2.htm' -Port 9225 -ProfileDir 'unused'
}
@{creates=$script:creates;shows=$script:shows;url=$script:createdUrl;targetId=$state.seed_target_id;
  status=$state.status;tabCount=$script:tabs.Count} | ConvertTo-Json -Compress
""".replace("__POLICY__", str(policy).replace("'", "''"))
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=20, check=True)
    value = json.loads(result.stdout)
    assert value == {
        "creates": 1, "shows": 1, "targetId": "owned-seed", "status": "waiting_for_seed_auth", "tabCount": 2,
        "url": "https://sf.taobao.com/list/50025969__2.htm?location_code=120104&page=40&st_param=4",
    }
