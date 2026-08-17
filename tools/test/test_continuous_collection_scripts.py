from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _script(name: str) -> str:
    return REPO_ROOT.joinpath("scripts", name).read_text(encoding="utf-8")


def _pc2_host_script(name: str) -> str:
    return REPO_ROOT.joinpath("ops", "pc2-host", name).read_text(encoding="utf-8")


def test_generate_all_seed_jobs_script_writes_host_jobs_file_safely() -> None:
    script = _script("generate-all-seed-jobs.ps1")

    assert "tools\\generate_seed_jobs.py" in script
    assert "FAPAI_DATA_ROOT_HOST" in script
    assert "seed_jobs_all.json" in script
    assert "datas\\all_locations.json" in script
    assert "FAPAI_SEED_JOBS_FILE" in script
    assert ".ProviderPath" in script
    assert "PYTHONPATH" in script


def test_taobao_login_watchdog_opens_official_verification_and_refreshes_snapshot() -> None:
    script = _script("taobao-login-watchdog.ps1")

    assert "check-taobao-login-health.ps1" in script
    assert "-SampleUrl" in script
    assert "start-taobao-cdp-browser.ps1" in script
    assert "export-taobao-cookie-snapshot.ps1" in script
    assert '[string]$OutputPath = ""' in script
    assert 'if ($OutputPath)' in script
    assert '"-OutputPath"' in script
    assert "complete Taobao official verification" in script
    assert "FapaiFangTaobaoLoginWatchdog" in script
    assert "Start-Process" in script
    assert "RedirectStandardOutput" in script
    assert "RedirectStandardError" in script
    assert "ExitCode" in script
    assert "cookie value" in script
    assert "cookie2=" not in script
    assert "sgcookie=" not in script
    assert "_tb_token_=" not in script
    assert "--remove-orphans" not in script


def test_taobao_login_watchdog_can_start_browser_with_system_proxy() -> None:
    script = _script("taobao-login-watchdog.ps1")

    assert "[switch]$UseSystemProxy" in script
    assert "if ($UseSystemProxy)" in script
    assert '"-UseSystemProxy"' in script


def test_taobao_login_watchdog_can_trigger_captcha_solver() -> None:
    script = _script("taobao-login-watchdog.ps1")

    assert "[switch]$TriggerCaptchaSolver" in script
    assert "FAPAI_CAPTCHA_SOLVER_ENABLED" in script
    assert '"-TriggerCaptchaSolver"' in script


def test_run_local_mock_slider_regression_script_uses_local_mock_regression_commands() -> None:
    script = _script("run-local-mock-slider-regression.ps1")

    assert "[int]$Runs = 3" in script
    assert "[int]$Workers = 4" in script
    assert "[switch]$SkipPytest" in script
    assert "[switch]$SkipMatrix" in script
    assert "[switch]$Headed" in script
    assert "test_mock_slider_drag_check.py" in script
    assert "test_mock_solver_probe.py" in script
    assert "test_mock_solver_matrix.py" in script
    assert "test_captcha_solver.py" in script
    assert "test_taobao_login_health.py" in script
    assert "test_detail_worker.py" in script
    assert "tools/mock_solver_matrix.py" in script
    assert "--scenario" in script
    assert "Local mock slider regression passed." in script


def test_register_taobao_login_watchdog_task_registers_on_demand_visible_user_task() -> None:
    script = _script("register-taobao-login-watchdog-task.ps1")

    assert "New-ScheduledTaskAction" in script
    assert "New-ScheduledTaskTrigger" not in script
    assert "Register-ScheduledTask" in script
    assert "FapaiFangTaobaoLoginWatchdog" in script
    assert "taobao-login-watchdog.ps1" in script
    assert '[string]$OutputPath = ""' in script
    assert '"-OutputPath"' in script
    assert "Interactive" in script
    assert "Convert-DataRootForScheduledTask" in script
    assert "On-demand FapaiFang Taobao recovery task" in script
    assert "recovery monitor starts it only" in script
    assert "IntervalMinutes" not in script


def test_register_taobao_login_watchdog_task_can_use_system_proxy() -> None:
    script = _script("register-taobao-login-watchdog-task.ps1")

    assert "[switch]$UseSystemProxy" in script
    assert "if ($UseSystemProxy)" in script
    assert '"-UseSystemProxy"' in script


def test_trigger_taobao_login_recovery_if_needed_uses_db_signals_and_safe_watchdog() -> None:
    script = _script("trigger-taobao-login-recovery-if-needed.ps1")

    assert "fapai_seed_item" in script
    assert "fapai_seed_scan_progress" in script
    assert "list_payload_missing" in script
    assert "FapaiFangTaobaoLoginWatchdog" in script
    assert "Get-ScheduledTask" in script
    assert "Start-ScheduledTask" in script
    assert "LastTriggeredAt" in script
    assert "RecoveryCooldownMinutes" in script
    assert "triggered_official_watchdog" in script
    assert "watchdog_already_running" in script
    assert "cookie value" in script
    assert "apiStatusForManualCheck.captcha_solver" in script
    assert "manual_required" in script
    assert '[int]$ManualAuthGraceMinutes = 30' in script
    assert "manual_only" in script
    assert "manual_auth_grace_period" in script
    assert "automatic_solver_recovery_in_progress" in script
    assert "function Stop-DedicatedRecoveryBrowser" in script
    assert "remote-debugging-port=9225" in script
    assert "closed_recovery_browser_count" in script
    grace_start = script.index('status = "manual_auth_grace_period"')
    grace_end = script.index("exit 0", grace_start)
    grace_block = script[grace_start:grace_end]
    assert "closed_recovery_browser_count" in grace_block
    assert "Stop-DedicatedRecoveryBrowser" in script[:grace_start]
    manual_check_index = script.index("$manualAuthRequired = $false")
    pause_guard_index = script.index("if ($snapshot.collection_paused -eq $true")
    assert manual_check_index < pause_guard_index
    assert "if ($snapshot.collection_paused -eq $true -and -not $manualAuthRequired)" in script
    assert "Input.dispatchMouseEvent" not in script
    assert "cookie2=" not in script
    assert "sgcookie=" not in script
    assert "_tb_token_=" not in script
    assert "--remove-orphans" not in script


def test_register_taobao_login_recovery_monitor_task_registers_fast_interactive_monitor() -> None:
    script = _script("register-taobao-login-recovery-monitor-task.ps1")

    assert "New-ScheduledTaskAction" in script
    assert "New-ScheduledTaskTrigger" in script
    assert "Register-ScheduledTask" in script
    assert "FapaiFangTaobaoLoginRecoveryMonitor" in script
    assert "trigger-taobao-login-recovery-if-needed.ps1" in script
    assert "Interactive" in script
    assert "MultipleInstances IgnoreNew" in script
    assert "IntervalMinutes" in script
    assert "MinRecentSeedItems" in script
    assert "StaleSeedMinutes" in script
    assert '[int]$ManualAuthGraceMinutes = 30' in script
    assert "-ManualAuthGraceMinutes" in script
    assert "Convert-DataRootForScheduledTask" in script
    assert "Convert-ToPowerShellSingleQuotedArgument" in script
    assert "run-taobao-login-recovery-monitor.ps1" in script
    assert "taobao-login-recovery-monitor.log" in script
    assert "$wrapperScript" in script
    assert "$taskWorkingDirectory = $runtimeDir" in script
    assert '"`"$wrapperScript`""' in script
    assert "-WorkingDirectory $taskWorkingDirectory" in script
    assert '"`"$TaskPath`""' not in script
    assert "--remove-orphans" not in script


def test_register_pc1_shared_auth_maintenance_registers_watchdog_and_recovery_with_port_9225() -> None:
    script = _script("register-pc1-shared-auth-maintenance.ps1")

    assert '[int]$Port = 9225' in script
    assert "register-taobao-login-watchdog-task.ps1" in script
    assert "register-taobao-login-recovery-monitor-task.ps1" in script
    assert 'Join-Path $resolvedDataRoot "secrets\\nodes\\pc2\\taobao-cookies.json"' in script
    assert 'Enable-ScheduledTask -TaskName "FapaiFangTaobaoLoginWatchdog"' in script
    assert 'Enable-ScheduledTask -TaskName "FapaiFangTaobaoLoginRecoveryMonitor"' in script
    assert '[switch]$StartWatchdogNow' in script
    assert '[int]$ManualAuthGraceMinutes = 30' in script
    assert '"-ManualAuthGraceMinutes", $ManualAuthGraceMinutes' in script
    assert 'Start-ScheduledTask -TaskName "FapaiFangTaobaoLoginWatchdog"' in script
    assert "WatchdogIntervalMinutes" not in script


def test_deploy_pc2_llm_helper_hotfix_uses_ssh_hash_verification_and_optional_analysis_restart() -> None:
    script = _script("deploy-pc2-llm-helper-hotfix.ps1")

    assert "Get-FileHash -LiteralPath $resolvedLocalPath -Algorithm SHA256" in script
    assert "Convert-ToScpRemotePath" in script
    assert "scp.exe" in script
    assert "$remoteScpPath" in script
    assert "PC2 llm_helper hotfix staging copy failed" in script
    assert "pc2-real-analysis-1" in script
    assert "Stop-Process -Id $process.ProcessId -Force" in script


def test_optimize_pc2_external_cdp_host_only_targets_unused_local_9223_edge_profile() -> None:
    script = _script("optimize-pc2-external-cdp-host.ps1")

    assert '[switch]$Apply' in script
    assert "FAPAI_CDP_EXTERNAL" in script
    assert "http://127.0.0.1:9223" in script
    assert "edge-cdp-profile-pc2" in script
    assert "Test-CdpEndpoint" in script
    assert "would_stop_unused_local_browser" in script
    assert "stopped_unused_local_browser" in script
    assert "Stop-Process -Id `$process.ProcessId -Force" in script


def test_register_continuous_collection_task_registers_health_gated_collection_task() -> None:
    script = _script("register-continuous-collection-task.ps1")

    assert "New-ScheduledTaskAction" in script
    assert "New-ScheduledTaskTrigger" in script
    assert "Register-ScheduledTask" in script
    assert "FapaiFangContinuousCollection" in script
    assert "start-continuous-collection.ps1" in script
    assert "Interactive" in script
    assert "MultipleInstances IgnoreNew" in script
    assert "Convert-DataRootForScheduledTask" in script
    assert "-SkipLoginWatchdog" not in script
    assert "-SkipDockerStart" not in script
    assert "--remove-orphans" not in script
    assert "docker-compose.postgres" not in script


def test_start_continuous_collection_generates_jobs_checks_login_and_starts_workers() -> None:
    script = _script("start-continuous-collection.ps1")

    assert "generate-all-seed-jobs.ps1" in script
    assert "start-taobao-cdp-browser.ps1" in script
    assert "taobao-login-watchdog.ps1" in script
    assert "export-taobao-cookie-snapshot.ps1" in script
    assert "docker compose" in script
    assert "fapaifang-seed-collector" in script
    assert "fapaifang-seed-collector-2" in script
    assert "fapaifang-api" in script
    assert "fapaifang-detail-worker" in script
    assert "fapaifang-detail-analysis-worker" in script
    assert "fapaifang-detail-analysis-worker-3" in script
    assert '"--profile", "api"' in script
    assert '"--profile", "analysis"' in script
    assert "FAPAI_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json" in script
    assert "FAPAI_COOKIE_SNAPSHOT=/data/secrets/taobao-cookies.json" in script
    assert "FAPAI_SEED_PAGES_PER_RUN=20" in script
    assert "FAPAI_SEED_LOOP_INTERVAL_SECONDS=60" in script
    assert "FAPAI_SEED_PARALLEL_SORTS=1" in script
    assert "FAPAI_DETAIL_TARGET_SUCCESS=10" in script
    assert "FAPAI_DETAIL_MAX_ATTEMPTS=30" in script
    assert "FAPAI_DETAIL_LOOP_INTERVAL_SECONDS=30" in script
    assert "FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS=0" in script
    assert "FAPAI_DETAIL_ANALYSIS_TARGET_SUCCESS=10" in script
    assert "FAPAI_DETAIL_ANALYSIS_MAX_ATTEMPTS=20" in script
    assert "FAPAI_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS=30" in script
    assert "FAPAI_DETAIL_ANALYSIS_ACTIVE_LOOP_INTERVAL_SECONDS=0" in script
    assert "FAPAI_SEED_RESCAN_INTERVAL_SECONDS=900" in script
    assert "FAPAI_SEED_FAILURE_COOLDOWN_THRESHOLD=3" in script
    assert "FAPAI_SEED_FAILURE_COOLDOWN_SECONDS=1800" in script
    assert "FAPAI_DETAIL_FAILURE_COOLDOWN_THRESHOLD=3" in script
    assert "FAPAI_DETAIL_FAILURE_COOLDOWN_SECONDS=1800" in script
    assert "FAPAI_DETAIL_ANALYSIS_WORKER_RESTART" in script
    assert "FAPAI_DETAIL_ANALYSIS_WORKER_2_RESTART" in script
    assert "FAPAI_DETAIL_ANALYSIS_WORKER_3_RESTART" in script
    assert "-SampleUrl" in script
    assert "200782003__1.htm" in script
    assert "--remove-orphans" not in script
    assert "docker-compose.postgres" not in script


def test_collection_compose_defines_seed_and_detail_worker_pools() -> None:
    compose = REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")
    host_bind = REPO_ROOT.joinpath("docker-compose.collection.host-bind.yml").read_text(encoding="utf-8")

    for service_name in (
        "fapaifang-seed-collector-2:",
        "fapaifang-seed-collector-3:",
        "fapaifang-seed-collector-4:",
        "fapaifang-seed-collector-5:",
        "fapaifang-seed-collector-6:",
        "fapaifang-detail-worker-2:",
        "fapaifang-detail-worker-3:",
        "fapaifang-detail-analysis-worker:",
        "fapaifang-detail-analysis-worker-2:",
        "fapaifang-detail-analysis-worker-3:",
    ):
        assert service_name in compose
        assert service_name in host_bind
    assert "FAPAI_SEED_JOBS_FILE: ${FAPAI_SEED_JOBS_FILE:-}" in compose
    assert "FAPAI_SEED_PARALLEL_SORTS: ${FAPAI_SEED_PARALLEL_SORTS:-1}" in compose
    assert "FAPAI_SEED_PAGES_PER_RUN: ${FAPAI_SEED_PAGES_PER_RUN:-20}" in compose
    assert "FAPAI_SEED_LOOP_INTERVAL_SECONDS: ${FAPAI_SEED_LOOP_INTERVAL_SECONDS:-60}" in compose
    assert "FAPAI_DETAIL_TARGET_SUCCESS: ${FAPAI_DETAIL_TARGET_SUCCESS:-10}" in compose
    assert "FAPAI_DETAIL_MAX_ATTEMPTS: ${FAPAI_DETAIL_MAX_ATTEMPTS:-30}" in compose
    assert "FAPAI_DETAIL_LOOP_INTERVAL_SECONDS: ${FAPAI_DETAIL_LOOP_INTERVAL_SECONDS:-30}" in compose
    assert "FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS: ${FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS:-0}" in compose
    assert "FAPAI_DETAIL_TARGET_SUCCESS: ${FAPAI_DETAIL_ANALYSIS_TARGET_SUCCESS:-10}" in compose
    assert "FAPAI_DETAIL_MAX_ATTEMPTS: ${FAPAI_DETAIL_ANALYSIS_MAX_ATTEMPTS:-20}" in compose
    assert "FAPAI_DETAIL_LOOP_INTERVAL_SECONDS: ${FAPAI_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS:-30}" in compose
    assert "FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS: ${FAPAI_DETAIL_ANALYSIS_ACTIVE_LOOP_INTERVAL_SECONDS:-0}" in compose
    assert "FAPAI_SEED_WORKER_ID: ${FAPAI_SEED_WORKER_ID_2:-seed-2}" in compose
    assert "FAPAI_DETAIL_WORKER_ID: ${FAPAI_DETAIL_WORKER_ID_2:-detail-2}" in compose
    assert "FAPAI_OUTPUT_DIR: /data/output/detail_analysis_worker_2" in compose
    assert "FAPAI_DETAIL_WORKER_ID: ${FAPAI_DETAIL_ANALYSIS_WORKER_ID_2:-analysis-2}" in compose


def test_collection_entrypoints_can_start_cdp_with_system_proxy() -> None:
    for name in (
        "start-continuous-collection.ps1",
        "start-seed-scan-only.ps1",
        "start-detail-analysis-only.ps1",
    ):
        script = _script(name)

        assert "[switch]$UseSystemProxy" in script
        assert "$startBrowserArgs" in script
        assert "$watchdogArgs" in script
        assert "if ($UseSystemProxy)" in script
        assert '"-UseSystemProxy"' in script


def test_pc2_host_worker_env_disables_runtime_db_bootstrap_and_browser_page_scan() -> None:
    script = _pc2_host_script("load-host-worker-env.ps1")

    assert "FAPAI_DB_AUTO_CREATE" in script
    assert "'0'" in script
    assert "FAPAI_DB_ENABLE_POSTGIS" in script
    assert "FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES" in script
    assert "FAPAI_API_BASE_URL" in script
    assert "FAPAI_REPORT_CDP_ENDPOINT" in script
    assert "FAPAI_NODE_ID" in script
    assert "SetEnvironmentVariable('FAPAI_COOKIE_SNAPSHOT_PREFER', '0', 'Process')" in script


def test_pc2_host_seed_worker_uses_resident_loop_without_single_run_cap() -> None:
    script = _pc2_host_script("start-host-seed-worker.ps1")

    assert "FAPAI_HOST_SEED_WORKER_ID" in script
    assert "FAPAI_LIST_BROWSER_FALLBACK" in script
    assert "'1'" in script
    assert "if (-not $env:FAPAI_LIST_BROWSER_FALLBACK)" in script
    assert "'--loop'" in script
    assert "FAPAI_SEED_PAGES_PER_RUN" in script
    assert "'--active-loop-interval-seconds', '10'" in script
    assert "'--loop-interval-seconds', '60'" in script
    assert "'--auth-probe-interval-seconds', '10'" in script
    assert "FAPAI_SEED_FAILURE_COOLDOWN_THRESHOLD" in script
    assert "FAPAI_SEED_FAILURE_COOLDOWN_SECONDS" in script
    assert "'--pages-per-run', '5'" not in script
    assert "'--failure-cooldown-threshold', '1'" not in script
    assert "'--failure-cooldown-seconds', '600'" not in script
    assert "'--max-runs'" not in script


def test_pc2_host_seed_worker_2_wraps_primary_seed_worker_with_distinct_worker_id() -> None:
    script = _pc2_host_script("start-host-seed-worker-2.ps1")

    assert "FAPAI_HOST_SEED_WORKER_ID" in script
    assert "pc2-host-seed-2" in script
    assert "start-host-seed-worker.ps1" in script


def test_pc2_host_detail_worker_uses_resident_loop_and_small_batch_target() -> None:
    script = _pc2_host_script("start-host-detail-worker.ps1")

    assert "FAPAI_HOST_DETAIL_WORKER_ID" in script
    assert "'--loop'" in script
    assert "'--target-success', '2'" in script
    assert "'--max-attempts', '6'" in script
    assert "'--active-loop-interval-seconds', '10'" in script
    assert "'--loop-interval-seconds', '60'" in script
    assert "'--failure-cooldown-seconds', '120'" in script
    assert "'--solver-enabled'" in script


def test_pc2_host_direct_nas_env_maps_home_share_and_uses_real_pc2_cdp_endpoint() -> None:
    script = _pc2_host_script("load-host-direct-nas-env.ps1")

    assert "cmdkey /add:192.168.15.200" in script
    assert "net use \\\\192.168.15.200\\home" in script
    assert "\\\\192.168.15.200\\home\\project\\project\\FPFData" in script
    assert "$cdpEndpoint = if ($env:FAPAI_CDP_ENDPOINT)" in script
    assert "http://127.0.0.1:9223" in script
    assert "$reportCdpEndpoint = if ($env:FAPAI_REPORT_CDP_ENDPOINT)" in script
    assert "http://192.168.15.104:9224" in script
    assert "$cookieSnapshotPrefer = if ($env:FAPAI_COOKIE_SNAPSHOT_PREFER)" in script
    assert "SetEnvironmentVariable('FAPAI_NODE_ID', 'pc2', 'Process')" in script


def test_pc2_host_direct_nas_env_loads_env_file_before_reading_share_credentials() -> None:
    script = _pc2_host_script("load-host-direct-nas-env.ps1")

    env_file_index = script.index("if (Test-Path $envFile)")
    share_user_index = script.index("$shareUser = [string]($env:FAPAI_NAS_SHARE_USER)")
    share_password_index = script.index("$sharePassword = [string]($env:FAPAI_NAS_SHARE_PASSWORD)")

    assert env_file_index < share_user_index < share_password_index


def test_pc2_host_direct_nas_env_maps_worker_node_detail_browser_flags() -> None:
    script = _pc2_host_script("load-host-direct-nas-env.ps1")

    assert "$listBrowserFallback = if ($env:FAPAI_LIST_BROWSER_FALLBACK)" in script
    assert "$detailBrowserFallback = if ($env:FAPAI_DETAIL_BROWSER_FALLBACK)" in script
    assert "$detailLoadOpenBrowserPages = if ($env:FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES)" in script
    assert "$detailCdpEndpoint = if ($env:FAPAI_DETAIL_CDP_ENDPOINT)" in script
    assert "$seedCaptchaSolverEnabled = if ($env:FAPAI_SEED_CAPTCHA_SOLVER_ENABLED)" in script
    assert "$detailCaptchaSolverEnabled = if ($env:FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED)" in script
    assert "$captchaSolverEnabled = if ($env:FAPAI_CAPTCHA_SOLVER_ENABLED) { $env:FAPAI_CAPTCHA_SOLVER_ENABLED } else { '1' }" in script
    assert "SetEnvironmentVariable('FAPAI_LIST_BROWSER_FALLBACK'" in script
    assert "SetEnvironmentVariable('FAPAI_DETAIL_BROWSER_FALLBACK'" in script
    assert "SetEnvironmentVariable('FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES'" in script
    assert "SetEnvironmentVariable('FAPAI_CAPTCHA_SOLVER_ENABLED', $captchaSolverEnabled" in script
    assert "SetEnvironmentVariable('FAPAI_SEED_CAPTCHA_SOLVER_ENABLED'" in script
    assert "SetEnvironmentVariable('FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED'" in script
    assert "SetEnvironmentVariable('FAPAI_DETAIL_CDP_ENDPOINT'" in script


def test_pc2_cookie_only_env_cutover_preserves_unrelated_settings_and_requires_snapshot() -> None:
    script = _pc2_host_script("apply-cookie-only-worker-env.ps1")

    assert "ReadAllLines" in script
    assert "WriteAllLines" in script
    assert "UTF8Encoding($false)" in script
    assert "FAPAI_LIST_BROWSER_FALLBACK = '0'" in script
    assert "FAPAI_DETAIL_BROWSER_FALLBACK = '0'" in script
    assert "FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES = '0'" in script
    assert "FAPAI_COOKIE_SNAPSHOT_PREFER = '1'" in script
    assert "FAPAI_CAPTCHA_SOLVER_ENABLED = '0'" in script
    assert "$null = & $nasLoader" in script
    assert "if (-not (Test-Path -LiteralPath $SnapshotPath))" in script


def test_pc2_cookie_only_install_script_backs_up_validates_and_restarts_watchdog() -> None:
    script = _pc2_host_script("install-cookie-only-runtime.ps1")

    assert "staging\\cookie-only-runtime" in script
    assert "backup\\pc2-cookie-only-runtime" in script
    assert "apply-cookie-only-worker-env.ps1" in script
    assert "register-host-direct-worker-watchdog.ps1" in script
    assert "start-host-direct-analysis-worker-2.ps1" in script
    assert "start-host-direct-analysis-worker-3.ps1" in script
    assert "Parser]::ParseFile" in script
    assert "Stop-ScheduledTask" in script
    assert "Copy-Item" in script
    assert "ConvertFrom-Json" in script
    assert "env.worker.local" in script
    assert "Get-ScheduledTask" in script
    assert "ConvertTo-Json -Compress" in script


def test_pc2_host_direct_seed_worker_uses_db_queue_and_short_loop_for_pc2_real_cutover() -> None:
    script = _pc2_host_script("start-host-direct-seed-worker.ps1")

    assert "load-host-direct-nas-env.ps1" in script
    assert "pc2-real-seed-1" in script
    assert "output\\nodes\\pc2-real\\seed_collector" in script
    assert "'--pages-per-run', '5'" in script
    assert "'--active-loop-interval-seconds', '5'" in script
    assert "'--loop-interval-seconds', '30'" in script
    assert "'--auth-probe-interval-seconds', '10'" in script
    assert "'--failure-cooldown-threshold', '10'" in script
    assert "'--failure-cooldown-seconds', '120'" in script
    assert "'--manual-challenge-reporting'" in script
    assert "manual_captcha_report_v1" in script
    assert "$manualChallengeReportingSupported = $true" in script
    assert "$manualChallengeReportingSupported = $false" not in script
    assert "elseif ($manualChallengeReportingSupported)" in script
    assert "$apiStatusReachable -and" not in script
    assert "-not $manualChallengeReportingSupported -and" not in script
    assert "'--solver-enabled'" in script
    assert "$solverEnabled = if ($env:FAPAI_SEED_CAPTCHA_SOLVER_ENABLED)" in script
    assert "-in @('1', 'true', 'yes', 'on')" in script
    assert "SetEnvironmentVariable('FAPAI_LIST_BROWSER_FALLBACK', '0', 'Process')" in script
    assert "FAPAI_LIST_HTTP_TIMEOUT_SECONDS" in script
    assert "FAPAI_LIST_BROWSER_RECOVERY_MAX_ATTEMPTS" in script
    assert "FAPAI_LIST_BROWSER_RECOVERY_WAIT_SECONDS" in script
    assert "'--job-key'" not in script
    assert "'--jobs-file'" not in script


def test_pc2_host_direct_seed_worker_regenerates_missing_seed_jobs_file_before_start() -> None:
    script = _pc2_host_script("start-host-direct-seed-worker.ps1")

    assert "$jobsFile = Join-Path $ctx.SharedRoot 'jobs\\seed_jobs_all.json'" in script
    assert "if (-not (Test-Path -LiteralPath $jobsFile))" in script
    assert "generate-all-seed-jobs.ps1" in script
    assert "-DataRoot $ctx.SharedRoot" in script
    assert "-Python $ctx.Python" in script


def test_pc2_host_direct_detail_worker_uses_raw_capture_loop_for_pc2_real_cutover() -> None:
    script = _pc2_host_script("start-host-direct-detail-worker.ps1")

    assert "load-host-direct-nas-env.ps1" in script
    assert "pc2-real-detail-1" in script
    assert "output\\nodes\\pc2-real\\detail_worker" in script
    assert "$targetSuccess = if ($env:FAPAI_HOST_DETAIL_TARGET_SUCCESS) { $env:FAPAI_HOST_DETAIL_TARGET_SUCCESS } else { '10' }" in script
    assert "$maxAttempts = if ($env:FAPAI_HOST_DETAIL_MAX_ATTEMPTS) { $env:FAPAI_HOST_DETAIL_MAX_ATTEMPTS } else { '30' }" in script
    assert "'--target-success', $targetSuccess" in script
    assert "'--max-attempts', $maxAttempts" in script
    assert "'--item-max-attempts', '3'" in script
    assert "'--failure-cooldown-seconds', '120'" in script
    assert "$activeLoopIntervalSeconds = if ($env:FAPAI_HOST_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS) { $env:FAPAI_HOST_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS } else { '0' }" in script
    assert "$successDelaySeconds = if ($env:FAPAI_HOST_DETAIL_SUCCESS_DELAY_SECONDS) { $env:FAPAI_HOST_DETAIL_SUCCESS_DELAY_SECONDS } else { '0' }" in script
    assert "$failureDelaySeconds = if ($env:FAPAI_HOST_DETAIL_FAILURE_DELAY_SECONDS) { $env:FAPAI_HOST_DETAIL_FAILURE_DELAY_SECONDS } else { '1' }" in script
    assert "'--success-delay-seconds', $successDelaySeconds" in script
    assert "'--failure-delay-seconds', $failureDelaySeconds" in script
    assert "'--active-loop-interval-seconds', $activeLoopIntervalSeconds" in script
    assert "'--loop-interval-seconds', '30'" in script
    assert "'--raw-only'" in script
    assert "'--manual-challenge-reporting'" in script
    assert "manual_captcha_report_v1" in script
    assert "$manualChallengeReportingSupported = $true" in script
    assert "$manualChallengeReportingSupported = $false" not in script
    assert "elseif ($manualChallengeReportingSupported)" in script
    assert "$apiStatusReachable -and" not in script
    assert "-not $manualChallengeReportingSupported -and" not in script
    assert "'--solver-enabled'" in script
    assert "$detailCdpEndpoint = if ($env:FAPAI_DETAIL_CDP_ENDPOINT)" in script
    assert "$solverEnabled = if ($env:FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED)" in script
    assert "-in @('1', 'true', 'yes', 'on')" in script


def test_pc2_host_direct_detail_worker_2_wraps_primary_direct_detail_worker() -> None:
    script = _pc2_host_script("start-host-direct-detail-worker-2.ps1")

    assert "FAPAI_HOST_DETAIL_WORKER_ID" in script
    assert "pc2-real-detail-2" in script
    assert "start-host-direct-detail-worker.ps1" in script


def test_pc2_host_direct_detail_worker_3_is_http_only() -> None:
    script = _pc2_host_script("start-host-direct-detail-worker-3.ps1")
    primary = _pc2_host_script("start-host-direct-detail-worker.ps1")

    assert "FAPAI_HOST_DETAIL_WORKER_ID" in script
    assert "pc2-real-detail-3" in script
    assert "detail_worker_3" in script
    assert "FAPAI_HOST_DETAIL_BROWSER_FALLBACK_OVERRIDE = '0'" in script
    assert "start-host-direct-detail-worker.ps1" in script
    assert "FAPAI_HOST_DETAIL_BROWSER_FALLBACK_OVERRIDE" in primary
    assert "SetEnvironmentVariable" in primary


def test_pc2_host_direct_analysis_worker_uses_small_retrying_batches_without_cdp() -> None:
    script = _pc2_host_script("start-host-direct-analysis-worker.ps1")

    assert "load-host-direct-nas-env.ps1" in script
    assert "pc2-real-analysis-1" in script
    assert "output\\nodes\\pc2-real\\detail_analysis_worker" in script
    assert "FAPAI_HOST_ANALYSIS_TARGET_SUCCESS" in script
    assert "FAPAI_HOST_ANALYSIS_MAX_ATTEMPTS" in script
    assert "'--analysis-only'" in script
    assert "'--target-success', $targetSuccess" in script
    assert "'--max-attempts', $maxAttempts" in script
    assert "'2'" in script
    assert "'3'" in script
    assert "'--lease-seconds', '900'" in script
    assert "'--llm-preflight'" in script
    assert "OPENAI_API_KEY" in script
    assert "--cdp-endpoint" not in script


def test_pc2_host_direct_analysis_worker_2_uses_distinct_worker_and_output() -> None:
    script = _pc2_host_script("start-host-direct-analysis-worker-2.ps1")

    assert "FAPAI_HOST_ANALYSIS_WORKER_ID" in script
    assert "pc2-real-analysis-2" in script
    assert "FAPAI_HOST_ANALYSIS_OUTPUT_DIR" in script
    assert "detail_analysis_worker_2" in script
    assert "start-host-direct-analysis-worker.ps1" in script


def test_pc2_host_direct_analysis_worker_3_uses_distinct_worker_and_output() -> None:
    script = _pc2_host_script("start-host-direct-analysis-worker-3.ps1")

    assert "FAPAI_HOST_ANALYSIS_WORKER_ID" in script
    assert "pc2-real-analysis-3" in script
    assert "FAPAI_HOST_ANALYSIS_OUTPUT_DIR" in script
    assert "detail_analysis_worker_3" in script
    assert "start-host-direct-analysis-worker.ps1" in script


def test_pc2_analysis_env_import_is_allowlisted_backed_up_and_redacted() -> None:
    script = _pc2_host_script("import-host-direct-analysis-env.ps1")

    assert "load-host-direct-nas-env.ps1" in script
    assert "docker.local.env" in script
    assert "$allowedNames" in script
    assert "OPENAI_API_KEY" in script
    assert "OPENAI_MODEL_CANDIDATES" in script
    assert "analysis-enable-" in script
    assert "Copy-Item" in script
    assert "WriteAllLines" in script
    assert "$staleAllowedNames" in script
    assert "not $updates.ContainsKey($_)" in script
    assert "$lines.RemoveAt($index)" in script
    assert "removed_stale_setting_count" in script
    assert script.index("Copy-Item") < script.index("$lines.RemoveAt($index)")
    assert "source_within_approved_root" in script
    assert "openai_api_key_configured" in script
    assert "ConvertTo-Json -Compress" in script
    assert "Write-Output $value" not in script


def test_pc1_analysis_proxy_bridge_is_loopback_only_and_discovers_current_proxy() -> None:
    script = _script("start-pc1-analysis-proxy-bridge.ps1")

    assert "ProxyServer" in script
    assert "Get-NetTCPConnection" in script
    assert "127.0.0.1:{0}:[::1]:{1}" in script
    assert 'GetFolderPath("UserProfile")' in script
    assert 'GetFolderPath("LocalApplicationData")' in script
    assert "ExitOnForwardFailure=yes" in script
    assert "ServerAliveInterval=15" in script
    assert "Keep SSH in the foreground" in script
    assert "& $ssh @arguments" in script
    assert "remote_loopback_only = $true" not in script
    assert "RemotePassword" not in script


def test_pc1_analysis_proxy_bridge_task_restarts_on_logon() -> None:
    script = _script("register-pc1-analysis-proxy-bridge-task.ps1")

    assert "start-pc1-analysis-proxy-bridge.ps1" in script
    assert 'GetFolderPath("LocalApplicationData")' in script
    assert "Copy-Item" in script
    assert "New-ScheduledTaskAction" in script
    assert "New-ScheduledTaskTrigger -AtLogOn" in script
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in script
    assert "-RestartCount 999" in script
    assert "Register-ScheduledTask" in script


def test_pc2_host_direct_runbook_documents_worker_roles_and_auth_quiescing() -> None:
    runbook = REPO_ROOT.joinpath("docs", "runbooks", "pc2-host-direct-workers.md").read_text(encoding="utf-8")

    for worker_id in (
        "pc2-real-seed-1",
        "pc2-real-detail-1",
        "pc2-real-detail-2",
        "pc2-real-detail-3",
        "pc2-real-analysis-1",
        "pc2-real-analysis-2",
        "pc2-real-analysis-3",
    ):
        assert worker_id in runbook
    assert "import-host-direct-analysis-env.ps1" in runbook
    assert "FOR UPDATE SKIP LOCKED" in runbook
    assert "analysis worker" in runbook
    assert "PC1" in runbook
    assert "automatic solver remains enabled" in runbook


def test_pc2_host_direct_launch_script_runs_persistent_watchdog_with_detached_workers() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    assert "start-host-direct-seed-worker.ps1" in script
    assert "start-host-direct-detail-worker.ps1" in script
    assert "start-host-direct-detail-worker-2.ps1" in script
    assert "start-host-direct-detail-worker-3.ps1" in script
    assert "start-host-direct-analysis-worker.ps1" in script
    assert "start-host-direct-analysis-worker-2.ps1" in script
    assert "start-host-direct-analysis-worker-3.ps1" in script
    assert "pc2-real-seed-1" in script
    assert "pc2-real-detail-1" in script
    assert "pc2-real-detail-2" in script
    assert "pc2-real-detail-3" in script
    assert "pc2-real-analysis-1" in script
    assert "pc2-real-analysis-2" in script
    assert "pc2-real-analysis-3" in script
    assert "Invoke-CimMethod" in script
    assert "Win32_Process" in script
    assert "MethodName Create" in script
    assert "cmd.exe /d /c powershell.exe -WindowStyle Hidden -NonInteractive" in script
    assert "logs\\codex-pc2-real" in script
    assert "seed_collector_summary.json" in script
    assert "detail_worker_summary.json" in script
    assert "LastWriteTime" in script
    assert "summary stale" in script
    assert "duplicate worker root" in script
    assert "Stop-WorkerProcessTree" in script
    assert "Get-CimInstance Win32_Process" in script
    assert "ParentProcessId" in script
    assert "while ($true)" in script
    assert "Start-Sleep -Seconds $PollSeconds" in script
    assert "Start-Process" not in script


def test_pc2_host_watchdog_cools_down_analysis_workers_when_llm_backend_is_unavailable() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    assert "[int]$AnalysisBackendRetryCooldownSeconds = 900" in script
    assert "$analysisBackendRetryAt = @{}" in script
    assert "$analysisUnavailableSummaryWriteTicks = @{}" in script
    assert "IsAnalysis = $true" in script
    assert "IsAnalysis = $false" in script
    assert "function Get-WorkerSummaryState" in script
    assert "ConvertFrom-Json" in script
    assert "detail_worker_llm_unavailable" in script
    assert "function Test-NewAnalysisBackendUnavailableSummary" in script
    assert "function Enter-AnalysisBackendCooldown" in script
    assert "function Test-AnalysisBackendCooldown" in script
    assert "analysis backend unavailable" in script
    assert "analysis backend cooldown expired" in script
    ensure_start = script.index("function Ensure-Worker")
    ensure_end = script.index("Write-WatchdogLog 'pc2 worker watchdog booted'", ensure_start)
    ensure_block = script[ensure_start:ensure_end]
    assert ensure_block.index("Test-NewAnalysisBackendUnavailableSummary") < ensure_block.index(
        "Get-ProcessAgeSeconds"
    )
    assert "Stop-WorkerProcessTree" in ensure_block
    assert "Enter-AnalysisBackendCooldown" in ensure_block
    assert "Test-AnalysisBackendCooldown" in ensure_block


def test_pc2_host_watchdog_recovers_unreachable_cdp_with_bounded_retries() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    assert "[int]$CdpFailureThreshold = 3" in script
    assert "[int]$CdpRestartCooldownSeconds = 300" in script
    assert "function Test-CdpEndpoint" in script
    assert "[System.Net.HttpWebRequest]::Create" in script
    assert "$request.Proxy = $null" in script
    assert "function Ensure-CdpBrowser" in script
    assert "$consecutiveCdpFailures" in script
    assert "$lastCdpRestartAt" in script
    assert "start-taobao-cdp-browser.ps1" in script
    assert "http://127.0.0.1:9223" in script
    assert "edge-cdp-profile-pc2" in script
    assert "'-UseSystemProxy'" in script
    assert "'-DisableExtensions'" in script
    assert "'-StartMinimized'" in script
    assert "'-EnsureOnly'" in script
    assert "'-CdpStartupTimeoutSeconds', '120'" in script
    assert "'about:blank'" in script
    assert "cdp recovery started" in script


def test_pc2_host_watchdog_only_gates_cdp_dependent_workers_on_cdp_health() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    assert "$cdpRequired = @($workerSpecs | Where-Object { $_.RequiresCdp }).Count -gt 0" in script
    assert "$cdpReady = -not $cdpRequired" in script
    assert "$cdpReady = Ensure-CdpBrowser" in script
    assert "RequiresCdp = $collectorRequiresCdp" in script
    assert "RequiresCdp = $false" in script
    assert "$spec.RequiresCdp -and -not $cdpReady" in script
    assert "cdp unavailable; skipping CDP-dependent worker supervision" in script
    assert "if (-not $spec.RequiresCdp)" in script


def test_pc2_external_cookie_snapshot_mode_keeps_collectors_and_analysis_independent_of_cdp() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    ensure_start = script.index("function Ensure-CdpBrowser")
    ensure_end = script.index("function Get-WorkerProcesses", ensure_start)
    ensure_block = script[ensure_start:ensure_end]
    assert "if ($externalCdp)" in ensure_block
    assert "Stop-WorkersForCdpRecovery" in ensure_block
    assert "$collectorRequiresCdp = -not ($externalCdp -and $cookieSnapshotPreferred)" in script

    analysis_start = script.index("Name = 'analysis-1'")
    analysis_end = script.index("},", analysis_start)
    assert "RequiresCdp = $false" in script[analysis_start:analysis_end]

    analysis_2_start = script.index("Name = 'analysis-2'")
    analysis_2_end = script.index("},", analysis_2_start)
    assert "RequiresCdp = $false" in script[analysis_2_start:analysis_2_end]

    analysis_3_start = script.index("Name = 'analysis-3'")
    analysis_3_end = script.index("},", analysis_3_start)
    assert "RequiresCdp = $false" in script[analysis_3_start:analysis_3_end]

    seed_start = script.index("Name = 'seed'")
    seed_end = script.index("},", seed_start)
    assert "RequiresCdp = $collectorRequiresCdp" in script[seed_start:seed_end]
    assert "StopsWhenCollectionPaused = $false" in script[seed_start:seed_end]

    detail3_start = script.index("Name = 'detail-3-http'")
    detail3_end = script.index("}", detail3_start)
    assert "RequiresCdp = $collectorRequiresCdp" in script[detail3_start:detail3_end]
    assert "StopsWhenCollectionPaused = $true" in script[detail3_start:detail3_end]


def test_pc2_collection_pause_keeps_scope_aware_seed_and_analysis_supervised() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    assert "function Test-CollectionPaused" in script
    assert 'Invoke-RestMethod -Uri "$apiBaseUrl/status"' in script
    assert "function Stop-WorkersForCollectionPause" in script
    assert 'Reason "collection paused"' in script
    assert "if ($collectionPaused)" in script
    assert "Stop-WorkersForCollectionPause" in script
    assert "if (-not $spec.StopsWhenCollectionPaused)" in script
    assert "$collectionPaused -and $spec.StopsWhenCollectionPaused" in script


def test_pc2_host_watchdog_stops_workers_before_restarting_cdp() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")
    recovery_start = script.index("function Start-CdpRecovery")
    recovery_end = script.index("function Ensure-CdpBrowser", recovery_start)
    recovery_block = script[recovery_start:recovery_end]

    assert "Stop-WorkersForCdpRecovery" in recovery_block
    assert recovery_block.index("Stop-WorkersForCdpRecovery") < recovery_block.index("& powershell.exe @arguments")
    assert "function Stop-WorkersForCdpRecovery" in script
    assert "Stop-WorkerProcessTree" in script
    assert 'Reason "cdp recovery"' in script


def test_pc2_host_watchdog_task_registration_has_no_runtime_limit_and_restarts() -> None:
    script = _pc2_host_script("register-host-direct-worker-watchdog.ps1")

    assert "launch-host-direct-workers.ps1" in script
    assert "New-ScheduledTaskAction" in script
    assert "'-WindowStyle', 'Hidden'" in script
    assert "New-ScheduledTaskTrigger" in script
    assert "-AtLogOn" in script
    assert "New-ScheduledTaskPrincipal" in script
    assert "-LogonType Interactive" in script
    assert "New-ScheduledTaskSettingsSet" in script
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in script
    assert "-RestartCount 999" in script
    assert "-RestartInterval (New-TimeSpan -Minutes 1)" in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "Register-ScheduledTask" in script
    assert "Start-ScheduledTask" in script
    assert "Unregister-ScheduledTask" in script
    assert "FPF-HostSeedWorker-Logon" in script
    assert "FPF-HostDetailWorker-Logon" in script
    assert "FapaifangPc2RealSeed" in script
    assert "FapaifangPc2RealDetail1" in script
    assert "FapaifangPc2RealDetail2" in script
    assert "FPF-HostCDP-Logon" in script
    assert "FPF-Launch-CDP-Interactive" in script
    assert "FapaiFangPc2CdpInteractive" in script
    assert "FapaiFangPc2HiddenCdpSvc2" in script
    assert "FapaiFangTaobaoCdpBrowser" in script
    assert "FapaiFangTaobaoLoginWatchdog" in script
    assert "$legacyTasks = @(Get-ScheduledTask -TaskName $legacyTaskName" in script
    assert "-TaskPath $legacyTask.TaskPath" in script


def test_pc2_host_open_auth_latest_uses_live_status_and_sanitizes_punish_targets() -> None:
    script = _pc2_host_script("open-auth-latest.ps1")

    assert script.lstrip("\ufeff\r\n ").startswith("param(")
    assert script.index("param(") < script.index("$ErrorActionPreference")
    assert "[string]$RequestedUrl = ''" in script
    assert "$rawTargetUrl = if ($RequestedUrl)" in script
    assert "Invoke-WebRequest -Uri \"$($ApiBaseUrl.TrimEnd('/'))/status\"" in script
    assert "captcha_solver" in script
    assert "last_request" in script
    assert "_____tmd_____/punish" in script
    assert "x5secdata" in script
    assert "__captcha_solver_bg=1" in script
    assert "start-taobao-cdp-browser.ps1" in script
    assert "$defaultUrl = 'https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1'" in script
    assert "-UseSystemProxy" in script
    assert "-DisableExtensions" in script
    assert "-ForceNew" in script
    assert "-CdpStartupTimeoutSeconds 120" in script


def test_pc2_host_open_auth_latest_resets_login_redirect_targets_to_default_list() -> None:
    script = _pc2_host_script("open-auth-latest.ps1")

    assert "login.taobao.com" in script
    assert "havanaone/login" in script
    assert "return $defaultUrl" in script

def test_pc2_host_open_auth_latest_force_restarts_visible_browser_for_manual_auth() -> None:
    script = _pc2_host_script("open-auth-latest.ps1")

    assert "& powershell" in script
    assert "-StartMinimized" not in script
    assert "-EnsureOnly" not in script
    assert "-ForceNew" in script


def test_pc2_host_open_auth_latest_avoids_system_web_in_interactive_task() -> None:
    script = _pc2_host_script("open-auth-latest.ps1")

    assert "Add-Type -AssemblyName System.Web" not in script
    assert "[System.Web.HttpUtility]" not in script
    assert "function ConvertFrom-AuthQueryString" in script
    assert "[System.Uri]::UnescapeDataString" in script
    assert "[System.Uri]::EscapeDataString" in script


def test_pc2_host_auth_trigger_runs_open_auth_in_interactive_hidden_task() -> None:
    script = _pc2_host_script("trigger-open-auth-task.ps1")

    assert "open-auth-latest.ps1" in script
    assert "FapaiPc2OpenAuth" in script
    assert "New-ScheduledTaskAction" in script
    assert "'-WindowStyle', 'Hidden'" in script
    assert "'-RequestedUrl'" in script
    assert "New-ScheduledTaskPrincipal" in script
    assert "-LogonType Interactive" in script
    assert "-RunLevel Limited" in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "Stop-ScheduledTask" in script
    assert "Register-ScheduledTask" in script
    assert "Start-ScheduledTask" in script


def test_solver_force_retry_monitor_prioritizes_seed_targets_and_throttles_detail_targets() -> None:
    script = REPO_ROOT.joinpath(".codex-temp", "bridge-control", "solver-force-retry-monitor.ps1").read_text(encoding="utf-8")

    assert "$seedCooldownSeconds = 60" in script
    assert "$detailCooldownSeconds = 300" in script
    assert "$seedSummaryPath =" in script
    assert "$seedRetryTargetUrl = 'https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1'" in script
    assert "function Get-SolverTargetScope" in script
    assert "function Test-SeedStageHasRemainingWork" in script
    assert "function Resolve-PreferredSolverTargetUrl" in script
    assert "function Test-SeedSummaryCdpUnreachable" in script
    assert "seed_summary=cdp_unreachable" in script
    assert "'sf-item.taobao.com'" in script
    assert "'sf.taobao.com/list/'" in script
    assert "$allowTargetChangeBypass = $targetScope -eq 'seed'" in script


def test_start_seed_scan_only_starts_seed_pool_without_detail_workers() -> None:
    script = _script("start-seed-scan-only.ps1")

    assert "generate-all-seed-jobs.ps1" in script
    assert "taobao-login-watchdog.ps1" in script
    assert "docker compose" in script
    assert "fapaifang-seed-collector" in script
    assert "fapaifang-seed-collector-6" in script
    assert "fapaifang-detail-worker" in script
    assert "stop" in script
    assert "docker update" in script
    assert "--restart=no" in script
    assert "FAPAI_SEED_PAGES_PER_RUN" in script
    assert "FAPAI_SEED_LOOP_INTERVAL_SECONDS=60" in script
    assert "FAPAI_SEED_PARALLEL_SORTS=1" in script
    assert "FAPAI_SEED_FAILURE_COOLDOWN_THRESHOLD=10" in script
    assert "FAPAI_SEED_FAILURE_COOLDOWN_SECONDS=120" in script
    assert "FAPAI_LIST_HTTP_TIMEOUT_SECONDS=8" in script
    assert "FAPAI_LIST_BROWSER_FALLBACK=0" in script
    assert "FAPAI_DETAIL_WORKER_RESTART=no" in script
    assert "FAPAI_DETAIL_ANALYSIS_WORKER_RESTART=no" in script
    assert "FAPAI_DETAIL_ANALYSIS_WORKER_2_RESTART=no" in script
    assert "FAPAI_DETAIL_ANALYSIS_WORKER_3_RESTART=no" in script
    assert "--profile analysis" in script
    assert "Cookie snapshot export failed" in script
    assert "--remove-orphans" not in script
    assert "docker-compose.postgres" not in script


def test_start_detail_analysis_only_starts_detail_and_analysis_pools_without_seed_workers() -> None:
    script = _script("start-detail-analysis-only.ps1")

    assert "taobao-login-watchdog.ps1" in script
    assert "docker compose" in script
    assert "fapaifang-detail-worker" in script
    assert "fapaifang-detail-worker-3" in script
    assert "fapaifang-detail-analysis-worker" in script
    assert "fapaifang-detail-analysis-worker-3" in script
    assert "fapaifang-seed-collector" in script
    assert '"--profile", "analysis"' in script
    assert "stop" in script
    assert "docker update" in script
    assert "--restart=no" in script
    assert "FAPAI_SEED_COLLECTOR_RESTART=no" in script
    assert "FAPAI_DETAIL_TARGET_SUCCESS" in script
    assert "FAPAI_DETAIL_ANALYSIS_TARGET_SUCCESS" in script
    assert "FAPAI_DETAIL_ANALYSIS_WORKER_RESTART=unless-stopped" in script
    assert "FAPAI_DETAIL_ANALYSIS_WORKER_2_RESTART=unless-stopped" in script
    assert "FAPAI_DETAIL_ANALYSIS_WORKER_3_RESTART=unless-stopped" in script
    assert "Cookie snapshot export failed" in script
    assert "--remove-orphans" not in script
    assert "docker-compose.postgres" not in script


def test_check_taobao_login_health_script_uses_multi_sample_health_gate() -> None:
    script = _script("check-taobao-login-health.ps1")

    assert '[string[]]$SampleUrl' in script
    assert "200782003__1.htm" in script
    assert "--sample-url" in script
    assert "foreach ($url in $healthSampleUrls)" in script
    assert "--remove-orphans" not in script


def test_taobao_login_watchdog_force_restarts_browser_when_cdp_websocket_is_dead() -> None:
    script = _script("taobao-login-watchdog.ps1")

    assert '$initial.Status -eq "cdp_unreachable"' in script
    assert "-not $SkipBrowserStart" in script
    assert '"-ForceNew"' in script
    assert "CDP websocket is unreachable" in script


def test_readme_documents_continuous_collection_workflow() -> None:
    readme = REPO_ROOT.joinpath("README.md").read_text(encoding="utf-8")

    assert "start-continuous-collection.ps1" in readme
    assert "generate-all-seed-jobs.ps1" in readme
    assert "taobao-login-watchdog.ps1" in readme
    assert "trigger-taobao-login-recovery-if-needed.ps1" in readme
    assert "register-taobao-login-recovery-monitor-task.ps1" in readme
    assert "register-taobao-login-watchdog-task.ps1" in readme
    assert "register-continuous-collection-task.ps1" in readme
    assert "start-seed-scan-only.ps1" in readme
    assert "start-detail-analysis-only.ps1" in readme
    assert "FAPAI_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json" in readme
    assert "FAPAI_COOKIE_SNAPSHOT=/data/secrets/taobao-cookies.json" in readme
    assert "FAPAI_SEED_PARALLEL_SORTS=1" in readme
    assert "fapaifang-detail-analysis-worker" in readme
    assert "fapaifang-detail-analysis-worker-3" in readme
    assert "detail_analysis_worker_2" in readme
    assert "raw_detail_captured" in readme
    assert "FAPAI_SEED_RESCAN_INTERVAL_SECONDS=900" in readme
    assert "FAPAI_SEED_FAILURE_COOLDOWN_SECONDS=1800" in readme
    assert "FAPAI_DETAIL_FAILURE_COOLDOWN_SECONDS=1800" in readme
    assert "multi-sample" in readme
    assert "50025969" in readme
    assert "200782003" in readme
    assert "事件触发式人工验证恢复器" in readme
