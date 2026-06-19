from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _script(name: str) -> str:
    return REPO_ROOT.joinpath("scripts", name).read_text(encoding="utf-8")


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


def test_register_taobao_login_watchdog_task_registers_visible_user_task() -> None:
    script = _script("register-taobao-login-watchdog-task.ps1")

    assert "New-ScheduledTaskAction" in script
    assert "New-ScheduledTaskTrigger" in script
    assert "Register-ScheduledTask" in script
    assert "FapaiFangTaobaoLoginWatchdog" in script
    assert "taobao-login-watchdog.ps1" in script
    assert "Interactive" in script
    assert "Convert-DataRootForScheduledTask" in script


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
    assert "captcha_solver" not in script
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
