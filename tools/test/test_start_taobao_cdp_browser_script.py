from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_start_taobao_cdp_browser_script_opens_visible_cdp_browser_when_missing() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "FAPAI_DATA_ROOT_HOST" in script
    assert "docker.local.env" in script
    assert "C:\\Users\\Public\\nas_home\\AI\\FPFData" in script
    assert "edge-cdp-profile" in script
    assert "https://sf.taobao.com/" in script
    assert "Microsoft\\Edge\\Application\\msedge.exe" in script
    assert "Google\\Chrome\\Application\\chrome.exe" in script
    assert "Invoke-WebRequest" in script
    assert "Start-Process" in script
    assert "--remote-debugging-port=$Port" in script
    assert "--remote-debugging-address=0.0.0.0" in script
    assert "--remote-allow-origins=*" in script
    assert "--no-proxy-server" in script
    assert "/json/version" in script
    assert "192.168.65.254" in script
    assert "Log in to Taobao" in script


def test_start_taobao_cdp_browser_can_use_system_proxy_when_requested() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "[switch]$UseSystemProxy" in script
    assert "if (-not $UseSystemProxy)" in script
    assert '$arguments += "--no-proxy-server"' in script


def test_start_taobao_cdp_browser_force_new_stops_existing_cdp_profile_processes() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "function Stop-ExistingCdpBrowser" in script
    assert "function Get-CdpBrowserProcesses" in script
    assert "Get-CimInstance Win32_Process" in script
    assert "remote-debugging-port=$Port" in script
    assert "$ProfileDir" in script
    assert "Stop-Process" in script
    assert "AddSeconds(60)" in script
    assert "Start-Sleep -Milliseconds 500" in script
    assert "if ($ForceNew)" in script


def test_start_taobao_cdp_browser_existing_cdp_endpoint_opens_requested_start_url() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "function Open-CdpBrowserPage" in script
    assert "[System.Uri]::EscapeDataString($Url)" in script
    assert "/json/new?$encodedUrl" in script
    assert "/json/activate/$($page.id)" in script
    assert "Open-CdpBrowserPage -Endpoint $hostEndpoint -Url $StartUrl" in script
    assert "Opened auth page in existing CDP browser" in script


def test_start_taobao_cdp_browser_falls_back_when_cdp_new_url_times_out() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "function Open-BrowserProcessPage" in script
    assert "Open-CdpBrowserPage -Endpoint $hostEndpoint -Url $StartUrl" in script
    assert "Open-BrowserProcessPage -Browser $browser -ProfileDir $ProfileDir -Port $Port -Url $StartUrl" in script
    assert "CDP /json/new open failed; falling back to browser process URL open" in script
    assert "Opened auth page via browser process fallback" in script


def test_start_taobao_cdp_browser_uses_process_open_for_long_punish_urls() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "function Test-BrowserProcessOpenPreferred" in script
    assert "_____tmd_____/punish" in script
    assert "x5secdata=" in script
    assert "$Url.Length -gt 1800" in script
    assert "if (Test-BrowserProcessOpenPreferred -Url $StartUrl)" in script
    assert "Skipping CDP /json/new for challenge-sized auth URL" in script


def test_start_taobao_cdp_browser_process_detection_includes_edge_and_chrome() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert '$browserProcessNames = @("chrome.exe", "msedge.exe")' in script


def test_start_taobao_cdp_browser_existing_cdp_endpoint_raises_existing_browser_window() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "function Show-CdpBrowserWindow" in script
    assert "ShowWindowAsync" in script
    assert "SetForegroundWindow" in script
    assert "Show-CdpBrowserWindow -Port $Port -ProfileDir $ProfileDir" in script


def test_start_taobao_cdp_browser_restarts_stale_process_when_endpoint_is_unavailable() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "staleProcesses = @(Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir -TopLevelOnly)" in script
    assert "Existing CDP browser process exists but endpoint is unavailable" in script
    assert "Stop-ExistingCdpBrowser -Port $Port -ProfileDir $ProfileDir -Endpoint $hostEndpoint" in script
    assert "Stale CDP browser processes did not exit cleanly" in script


def test_start_taobao_cdp_browser_force_new_targets_top_level_browser_processes_only() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "[switch]$TopLevelOnly" in script
    assert "Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir -TopLevelOnly" in script
    assert 'if ($TopLevelOnly)' in script
    assert '$cmd -like "* --type=*"' in script
    assert "return $false" in script


def test_start_taobao_cdp_browser_force_new_aborts_if_old_browser_does_not_exit() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "return $false" in script
    assert "return $true" in script
    assert "if (-not (Stop-ExistingCdpBrowser -Port $Port -ProfileDir $ProfileDir -Endpoint $hostEndpoint))" in script
    assert "Existing CDP browser processes did not exit cleanly" in script


def test_start_taobao_cdp_browser_force_new_status_messages_do_not_pollute_boolean_return() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert 'Write-Host "Stopping existing CDP browser processes for port $Port / profile $ProfileDir."' in script
    assert 'Write-Host "Timed out waiting for the top-level CDP browser process and endpoint to exit."' in script
    assert 'Write-Output "Stopping existing CDP browser processes for port $Port / profile $ProfileDir."' not in script
    assert 'Write-Output "Timed out waiting for the top-level CDP browser process and endpoint to exit."' not in script


def test_start_taobao_cdp_browser_waits_for_endpoint_readiness_with_deadline() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "function Wait-CdpEndpoint" in script
    assert "TimeoutSeconds = 30" in script
    assert "PollMilliseconds = 500" in script
    assert "Wait-CdpEndpoint -Endpoint $hostEndpoint -TimeoutSeconds 30" in script
    assert "Started browser but CDP endpoint did not become available within 30 seconds" in script
    assert "Start-Sleep -Seconds 3" not in script


def test_start_taobao_cdp_browser_force_new_waits_for_endpoint_shutdown_and_top_level_exit() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert '[Parameter(Mandatory = $true)][string]$Endpoint' in script
    assert "Stop-ExistingCdpBrowser -Port $Port -ProfileDir $ProfileDir -Endpoint $hostEndpoint" in script
    assert '$remaining = @(Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir -TopLevelOnly)' in script
    assert 'if (($remaining.Count -eq 0) -and -not (Test-CdpEndpoint -Endpoint $Endpoint))' in script
    assert 'Timed out waiting for the top-level CDP browser process and endpoint to exit.' in script


def test_start_taobao_cdp_browser_supports_isolated_profile_and_optional_extension_disable() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "[switch]$IsolatedProfile" in script
    assert "[switch]$DisableExtensions" in script
    assert "edge-cdp-profile-isolated" in script
    assert 'if ($IsolatedProfile)' in script
    assert 'if ($DisableExtensions)' in script
    assert '$arguments += "--disable-extensions"' in script


def test_start_taobao_cdp_browser_includes_low_noise_edge_flags_from_legacy_recovery_flow() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1").read_text(encoding="utf-8")

    assert "--disable-background-networking" in script
    assert "--disable-sync" in script
    assert "--disable-client-side-phishing-detection" in script
    assert "--disable-default-apps" in script
    assert "--disable-blink-features=AutomationControlled" in script


def test_operator_docs_include_cdp_browser_startup_helper() -> None:
    readme = REPO_ROOT.joinpath("README.md").read_text(encoding="utf-8")

    assert "start-taobao-cdp-browser.ps1" in readme
    assert "C:\\Users\\Public\\nas_home\\AI\\FPFData\\edge-cdp-profile" in readme
    assert "http://192.168.65.254:9223" in readme


def test_check_taobao_login_health_script_starts_browser_and_runs_safe_helper() -> None:
    script = REPO_ROOT.joinpath("scripts", "check-taobao-login-health.ps1").read_text(encoding="utf-8")

    assert "start-taobao-cdp-browser.ps1" in script
    assert "tools\\taobao_login_health.py" in script
    assert ".ProviderPath" in script
    assert "http://127.0.0.1:$Port" in script
    assert "https://sf.taobao.com/list/50025969__2.htm" in script
    assert "--open-login" in script
    assert "[switch]$TriggerCaptchaSolver" in script
    assert "if ($TriggerCaptchaSolver)" in script
    assert '$healthArgs += "--trigger-captcha-solver"' in script
    assert '"--trigger-captcha-solver",' not in script
    assert "--wait-seconds" in script
    assert "--poll-seconds" in script
    assert "Invoke-WebRequest" in script
    assert "StartBrowser" in script
    assert "SkipBrowserStart" in script


def test_check_taobao_login_health_script_can_forward_isolated_profile_flags() -> None:
    script = REPO_ROOT.joinpath("scripts", "check-taobao-login-health.ps1").read_text(encoding="utf-8")

    assert "[switch]$IsolatedProfile" in script
    assert "[switch]$DisableExtensions" in script
    assert 'if ($IsolatedProfile)' in script
    assert 'if ($DisableExtensions)' in script
    assert '@("-IsolatedProfile")' in script
    assert '@("-DisableExtensions")' in script


def test_operator_docs_include_login_health_recovery_helper() -> None:
    readme = REPO_ROOT.joinpath("README.md").read_text(encoding="utf-8")

    assert "check-taobao-login-health.ps1" in readme
    assert "taobao_login_health.py" in readme
    assert "login_recovery" in readme
    assert "punish" in readme
    assert "验证码" in readme
    assert "http://127.0.0.1:9223" in readme


def test_export_taobao_cookie_snapshot_script_starts_browser_and_does_not_print_values() -> None:
    script = REPO_ROOT.joinpath("scripts", "export-taobao-cookie-snapshot.ps1").read_text(encoding="utf-8")

    assert "start-taobao-cdp-browser.ps1" in script
    assert "browserless_seed_probe.py" in script
    assert "--write-cookie-snapshot" in script
    assert "FAPAI_DATA_ROOT_HOST" in script
    assert "taobao-cookies.json" in script
    assert "http://127.0.0.1:$Port" in script
    assert "load_cookie_snapshot" in script
    assert "summarize_cookie_snapshot" in script
    assert "ConvertTo-Json" in script
    assert "cookie value" in script
    assert "PYTHONPATH" in script
    assert "$summaryScript" in script
    assert "summary['path']" in script
    assert "summary.pop('names', None)" in script


def test_export_taobao_cookie_snapshot_script_can_forward_isolated_profile_flags() -> None:
    script = REPO_ROOT.joinpath("scripts", "export-taobao-cookie-snapshot.ps1").read_text(encoding="utf-8")

    assert "[switch]$IsolatedProfile" in script
    assert "[switch]$DisableExtensions" in script
    assert 'if ($IsolatedProfile)' in script
    assert 'if ($DisableExtensions)' in script
    assert '@("-IsolatedProfile")' in script
    assert '@("-DisableExtensions")' in script


def test_export_taobao_cookie_snapshot_validates_candidate_before_promoting_official_file() -> None:
    script = REPO_ROOT.joinpath("scripts", "export-taobao-cookie-snapshot.ps1").read_text(encoding="utf-8")

    assert "$candidatePath" in script
    assert "--write-cookie-snapshot $candidatePath" in script
    assert "FAPAI_COOKIE_SNAPSHOT_CANDIDATE" in script
    assert "FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS_JSON" in script
    assert "browserless_seed_probe.probe_seed_page" in script
    assert "taobao_login_health.classify_taobao_health" in script
    assert "Move-Item -LiteralPath $candidatePath -Destination $OutputPath -Force" in script
    assert "official snapshot was not overwritten" in script


def test_export_taobao_cookie_snapshot_redacts_candidate_health_failure_output() -> None:
    script = REPO_ROOT.joinpath("scripts", "export-taobao-cookie-snapshot.ps1").read_text(encoding="utf-8")

    assert "taobao_login_health.redact_taobao_health_output(payload)" in script
    assert "x5secdata" not in script
    assert "cookie2=" not in script
    assert "sgcookie=" not in script
    assert "_tb_token_=" not in script


def test_operator_docs_recommend_isolated_taobao_browser_profile_for_recovery() -> None:
    readme = REPO_ROOT.joinpath("README.md").read_text(encoding="utf-8")

    assert "edge-cdp-profile-isolated" in readme
    assert "-IsolatedProfile" in readme
    assert "-DisableExtensions" in readme
