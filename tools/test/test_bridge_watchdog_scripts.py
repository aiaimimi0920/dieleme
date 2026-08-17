from __future__ import annotations

from pathlib import Path


def _read_script(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_bridge_seed_script_manages_pid_file() -> None:
    script = _read_script(".codex-temp/bridge-seed/start-bridge-seed.ps1")

    assert "bridge-seed.pid" in script
    assert "Set-Content -Path $pidFile" in script
    assert "Remove-Item -Path $pidFile" in script


def test_bridge_seed_script_enables_list_browser_fallback() -> None:
    script = _read_script(".codex-temp/bridge-seed/start-bridge-seed.ps1")

    assert "FAPAI_LIST_BROWSER_FALLBACK" in script
    assert "'1'" in script
    assert "FAPAI_LIST_BROWSER_RECOVERY_MAX_ATTEMPTS" in script
    assert "FAPAI_LIST_BROWSER_RECOVERY_WAIT_SECONDS" in script


def test_bridge_seed_script_tunes_list_http_timeout_for_fast_seed_retries() -> None:
    script = _read_script(".codex-temp/bridge-seed/start-bridge-seed.ps1")

    assert "FAPAI_LIST_HTTP_TIMEOUT_SECONDS" in script
    assert "'8'" in script


def test_bridge_worker_scripts_refuse_duplicate_launches_for_same_worker_id() -> None:
    seed = _read_script(".codex-temp/bridge-seed/start-bridge-seed.ps1")
    detail1 = _read_script(".codex-temp/bridge-detail/start-bridge-detail.ps1")
    detail2 = _read_script(".codex-temp/bridge-detail/start-bridge-detail-2.ps1")

    for script in (seed, detail1, detail2):
        assert "Get-CimInstance Win32_Process" in script
        assert "function Find-ExistingWorkerProcess" in script
        assert "already running" in script
        assert "--worker-id" in script
        assert "exit 0" in script.lower()


def test_bridge_worker_scripts_use_real_python_binary_instead_of_scoop_shim() -> None:
    seed = _read_script(".codex-temp/bridge-seed/start-bridge-seed.ps1")
    detail1 = _read_script(".codex-temp/bridge-detail/start-bridge-detail.ps1")
    detail2 = _read_script(".codex-temp/bridge-detail/start-bridge-detail-2.ps1")

    for script in (seed, detail1, detail2):
        assert "scoop\\shims\\python.exe" not in script
        assert "scoop\\apps\\python310\\current\\python.exe" in script


def test_bridge_detail_scripts_manage_distinct_pid_files() -> None:
    detail1 = _read_script(".codex-temp/bridge-detail/start-bridge-detail.ps1")
    detail2 = _read_script(".codex-temp/bridge-detail/start-bridge-detail-2.ps1")

    assert "bridge-detail.pid" in detail1
    assert "Set-Content -Path $pidFile" in detail1
    assert "Remove-Item -Path $pidFile" in detail1

    assert "bridge-detail-2.pid" in detail2
    assert "Set-Content -Path $pidFile" in detail2
    assert "Remove-Item -Path $pidFile" in detail2


def test_bridge_watchdog_tracks_detail_worker_2_and_uses_live_timestamps() -> None:
    script = _read_script(".codex-temp/bridge-control/bridge-watchdog.ps1")

    assert "bridge-detail-2.pid" in script
    assert "start-bridge-detail-2.ps1" in script
    assert "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'" in script


def test_bridge_watchdog_restarts_workers_when_runtime_summaries_go_stale() -> None:
    script = _read_script(".codex-temp/bridge-control/bridge-watchdog.ps1")

    assert "seed_collector_summary.json" in script
    assert "detail_worker_summary.json" in script
    assert "LastWriteTime" in script
    assert "TotalSeconds" in script
    assert "summary stale" in script
    assert "seedSummaryMaxAgeSeconds" in script
    assert "detailSummaryMaxAgeSeconds" in script


def test_bridge_watchdog_stops_process_tree_not_only_wrapper_when_restarting_stale_worker() -> None:
    script = _read_script(".codex-temp/bridge-control/bridge-watchdog.ps1")

    assert "Stop-BridgeProcessTree" in script
    assert "Get-CimInstance Win32_Process" in script
    assert "ParentProcessId" in script
    assert "Stop-Process -Id" in script


def test_solver_force_retry_monitor_uses_no_proxy_http_client() -> None:
    script = _read_script(".codex-temp/bridge-control/solver-force-retry-monitor.ps1")

    assert "HttpClientHandler" in script
    assert "UseProxy = $false" in script
    assert "Invoke-RestMethod" not in script


def test_solver_force_retry_monitor_manages_pid_file() -> None:
    script = _read_script(".codex-temp/bridge-control/solver-force-retry-monitor.ps1")

    assert "solver-force-retry-monitor.pid" in script
    assert "Set-Content -Path $pidFile" in script
    assert "Remove-Item -Path $pidFile" in script


def test_bridge_control_scripts_skip_duplicate_wrapper_launches_when_pid_is_alive() -> None:
    for path in (
        ".codex-temp/bridge-control/solver-force-retry-monitor.ps1",
        ".codex-temp/bridge-control/start-local-cdp-forwarder.ps1",
    ):
        script = _read_script(path)

        assert "function Get-TrackedProcessId" in script
        assert "function Test-TrackedProcess" in script
        assert "already running" in script
        assert "Set-Content -Path $pidFile" in script
        assert "exit 0" in script.lower()


def test_solver_force_retry_monitor_guards_missing_last_request_properties() -> None:
    script = _read_script(".codex-temp/bridge-control/solver-force-retry-monitor.ps1")

    assert "Get-ObjectPropertyValueOrDefault" in script
    assert "target_url" in script
    assert "PSObject.Properties" in script


def test_solver_force_retry_monitor_loads_system_net_http_before_httpclient_use() -> None:
    script = _read_script(".codex-temp/bridge-control/solver-force-retry-monitor.ps1")

    assert "Add-Type -AssemblyName 'System.Net.Http'" in script
    assert "HttpClientHandler" in script


def test_solver_force_retry_monitor_skips_bad_cdp_endpoints_and_running_solver_loops() -> None:
    script = _read_script(".codex-temp/bridge-control/solver-force-retry-monitor.ps1")

    assert "function Test-CdpEndpointHealthy" in script
    assert "/json/list" in script
    assert "/json/version" in script
    assert "cdp_endpoint_unhealthy" in script
    assert "solver_max_runtime_seconds" in script
    assert "elapsed_seconds" in script
    assert "solver_still_running" in script


def test_solver_force_retry_monitor_canonicalizes_seed_targets_to_single_retry_url() -> None:
    script = _read_script(".codex-temp/bridge-control/solver-force-retry-monitor.ps1")

    assert "if ($targetScope -eq 'seed')" in script
    assert "return $seedRetryTargetUrl" in script


def test_solver_force_retry_monitor_rewrites_container_only_cdp_hosts_for_local_health_checks() -> None:
    script = _read_script(".codex-temp/bridge-control/solver-force-retry-monitor.ps1")

    assert "function Normalize-OperatorCdpEndpoint" in script
    assert "host.docker.internal" in script
    assert "192.168.65.254" in script
    assert "127.0.0.1" in script
    assert "$endpointHost" in script
    assert "$operatorCdpEndpoint = Normalize-OperatorCdpEndpoint $cdpEndpoint" in script
    assert "cdp_endpoint = $operatorCdpEndpoint" in script
