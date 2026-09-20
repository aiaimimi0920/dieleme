from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from src.collection.adapters.taobao_auth_target import auth_target, canonical_auth_target, same_auth_target
from tools import taobao_inplace_auth_handoff as handoff


ORIGINAL = "https://sf-item.taobao.com/sf_item/770335224700.htm"
REDIRECT = "https://susong-item.taobao.com/auction/770335224700.htm"


@pytest.mark.parametrize("url", [ORIGINAL, REDIRECT, REDIRECT + "?source=redirect",
                                      REDIRECT + "/_____tmd_____/punish?x5secdata=not-an-identity"])
def test_redirect_retains_the_original_auction_identity(url):
    assert canonical_auth_target("detail", url) == ORIGINAL


def test_same_detail_identity_accepts_only_the_same_redirected_auction():
    assert same_auth_target("detail", ORIGINAL, REDIRECT)
    assert not same_auth_target("detail", ORIGINAL, REDIRECT.replace("770335224700", "770335224701"))


@pytest.mark.parametrize("url", [
    "https://susong-item.taobao.com.attacker.test/auction/770335224700.htm",
    "https://attacker.test/?next=" + REDIRECT,
    "https://user@susong-item.taobao.com/auction/770335224700.htm",
    "https://susong-item.taobao.com:444/auction/770335224700.htm",
    "http://susong-item.taobao.com/auction/770335224700.htm",
    "https://susong-item.taobao.com/sf_item/770335224700.htm",
])
def test_redirect_does_not_expand_the_authentication_allowlist(url):
    with pytest.raises(ValueError):
        auth_target("detail", url)
    assert handoff._canonical_detail_url(url) == ""


@pytest.mark.parametrize("blocked", [False, True])
def test_selected_redirected_tab_still_requires_a_healthy_page(monkeypatch, blocked):
    inspected = []
    monkeypatch.setattr(handoff.taobao_login_health, "list_cdp_targets", lambda _: [
        {"id": "selected", "type": "page", "url": REDIRECT, "webSocketDebuggerUrl": "ws://selected"},
        {"id": "unrelated", "type": "page", "url": ORIGINAL, "webSocketDebuggerUrl": "ws://other"},
    ])

    def evaluate(endpoint, _expression):
        inspected.append(endpoint)
        value = {"url": REDIRECT, "html": "<html><body>" + "auction " * 200 + "</body></html>"}
        return {"result": {"result": {"value": json.dumps(value)}}}

    monkeypatch.setattr(handoff.taobao_login_health, "evaluate_cdp_expression", evaluate)
    monkeypatch.setattr(handoff.browserless_seed_probe, "summarize_list_page",
                        lambda *_args, **_kwargs: {"body_has_challenge": blocked, "body_has_login": False})
    if blocked:
        with pytest.raises(RuntimeError, match="No healthy open"):
            handoff._healthy_open_taobao_page("http://localhost:9225", required_target_id="selected", require_detail=True)
    else:
        page = handoff._healthy_open_taobao_page("http://localhost:9225", required_target_id="selected", require_detail=True)
        assert (page["kind"], page["url"]) == ("detail", ORIGINAL)
    assert inspected == ["ws://selected"]


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows PowerShell required")
def test_pc1_watcher_reuses_the_same_auction_after_a_cross_host_redirect():
    policy = Path(__file__).resolve().parents[2] / "scripts/pc1-auth-recovery-policy.ps1"
    script = r"""
$ErrorActionPreference = 'Stop'
. '__POLICY__'
$original = 'https://sf-item.taobao.com/sf_item/770335224700.htm'
$redirect = 'https://susong-item.taobao.com/auction/770335224700.htm'
$tab = @{id='redirected';type='page';url=$redirect}
$other = @{id='other';type='page';url=($redirect -replace '770335224700','770335224701')}
$lookalike = @{id='lookalike';type='page';url=($redirect -replace '.com/', '.com.attacker.test/')}
$solver = @{scopes=@{detail=@{last_request=@{target_url=($redirect+'/_____tmd_____/punish?x5secdata=not-copied')}}}}
@{
    selected = (Get-Pc1RecoveryTab -Tabs @($tab) -TargetUrl $original).id
    reverse = (Get-Pc1RecoveryTab -Tabs @(@{id='original';type='page';url=$original}) -TargetUrl $redirect).id
    target = Get-Pc1RecoveryTargetUrl -SolverStatus $solver -FallbackUrl 'https://sf.taobao.com/'
    rejectsOther = $null -eq (Get-Pc1RecoveryTab -Tabs @($other) -TargetUrl $original)
    rejectsLookalike = $null -eq (Get-Pc1RecoveryTab -Tabs @($lookalike) -TargetUrl $original)
} | ConvertTo-Json -Compress
""".replace("__POLICY__", str(policy).replace("'", "''"))
    completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                               capture_output=True, text=True, timeout=20, check=True)
    assert json.loads(completed.stdout) == {
        "selected": "redirected", "reverse": "original", "target": ORIGINAL,
        "rejectsOther": True, "rejectsLookalike": True,
    }
