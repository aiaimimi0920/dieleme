from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_backup_postgres_script_writes_verified_dump_with_retention() -> None:
    script = REPO_ROOT.joinpath("scripts", "backup-postgres-to-host.ps1").read_text(encoding="utf-8")

    assert "C:\\Users\\Public\\nas_home\\AI\\FPFData" in script
    assert "Z:\\project\\project\\FPFData" not in script
    assert "FAPAI_DATA_ROOT_HOST" in script
    assert "postgres\\backups" in script
    assert "pg_dump" in script
    assert "-Fc" in script
    assert "pg_restore" in script
    assert "-l" in script
    assert "docker cp" in script
    assert "KeepLast" in script
    assert "Get-ChildItem" in script
    assert "Remove-Item" in script
    assert "verifyPath" in script
    assert "copied host dump" in script


def test_backup_postgres_script_bounds_each_docker_command_runtime() -> None:
    script = REPO_ROOT.joinpath("scripts", "backup-postgres-to-host.ps1").read_text(encoding="utf-8")

    assert "CommandTimeoutSeconds" in script
    assert "Invoke-DockerCommand" in script
    assert "System.Diagnostics.ProcessStartInfo" in script
    assert "UseShellExecute = $false" in script
    assert "RedirectStandardOutput = $true" in script
    assert "ConvertTo-ProcessArgument" in script
    assert "WaitForExit" in script
    assert ".Kill()" in script
    assert "timed out after $CommandTimeoutSeconds seconds" in script


def test_register_postgres_backup_task_installs_independent_periodic_task() -> None:
    script = REPO_ROOT.joinpath("scripts", "register-postgres-backup-task.ps1").read_text(encoding="utf-8")

    assert "C:\\Users\\Public\\nas_home\\AI\\FPFData" in script
    assert "Z:\\project\\project\\FPFData" not in script
    assert "FapaiFangPostgresBackup" in script
    assert "backup-postgres-to-host.ps1" in script
    assert "New-ScheduledTaskTrigger" in script
    assert "-RepetitionInterval" in script
    assert "Convert-DataRootForScheduledTask" in script
    assert "DisplayRoot" in script
    assert "-KeepLast" in script
    assert "-CommandTimeoutSeconds" in script
    assert "ExecutionTimeLimitMinutes" in script
    assert "-ExecutionTimeLimit" in script
    assert "Register-ScheduledTask" in script


def test_operator_docs_include_postgres_backup_task_and_restore_probe() -> None:
    readme = REPO_ROOT.joinpath("README.md").read_text(encoding="utf-8")
    runbook = REPO_ROOT.joinpath("docs", "runbooks", "docker-schema-guard.md").read_text(encoding="utf-8")

    assert "C:\\Users\\Public\\nas_home\\AI\\FPFData" in readme
    assert "C:\\Users\\Public\\nas_home\\AI\\FPFData" in runbook
    assert "backup-postgres-to-host.ps1" in readme
    assert "register-postgres-backup-task.ps1" in readme
    assert "check-postgres-backup-health.ps1" in readme
    assert "register-postgres-backup-health-task.ps1" in readme
    assert "FapaiFangPostgresBackup" in readme
    assert "FapaiFangPostgresBackupHealth" in readme
    assert "pg_restore -l" in readme
    assert "backup-postgres-to-host.ps1" in runbook
    assert "check-postgres-backup-health.ps1" in runbook
    assert "FapaiFangPostgresBackup" in runbook
    assert "FapaiFangPostgresBackupHealth" in runbook


def test_backup_health_check_detects_stale_or_invalid_backups() -> None:
    script = REPO_ROOT.joinpath("scripts", "check-postgres-backup-health.ps1").read_text(encoding="utf-8")

    assert "C:\\Users\\Public\\nas_home\\AI\\FPFData" in script
    assert "Z:\\project\\project\\FPFData" not in script
    assert "MaxAgeMinutes" in script
    assert "MinBytes" in script
    assert "FapaiFangPostgresBackup" in script
    assert "Get-ScheduledTaskInfo" in script
    assert "LastTaskResult" in script
    assert '$task.State -ne "Running"' in script
    assert "pg_restore" in script
    assert "-l" in script
    assert "docker cp" in script
    assert "CommandTimeoutSeconds" in script
    assert "Invoke-DockerCommand" in script
    assert "System.Diagnostics.ProcessStartInfo" in script
    assert "UseShellExecute = $false" in script
    assert "RedirectStandardOutput = $true" in script
    assert "WaitForExit" in script
    assert ".Kill()" in script
    assert "timed out after $CommandTimeoutSeconds seconds" in script
    assert "latest Postgres backup is stale" in script


def test_register_backup_health_task_installs_independent_periodic_task() -> None:
    script = REPO_ROOT.joinpath("scripts", "register-postgres-backup-health-task.ps1").read_text(encoding="utf-8")

    assert "C:\\Users\\Public\\nas_home\\AI\\FPFData" in script
    assert "Z:\\project\\project\\FPFData" not in script
    assert "FapaiFangPostgresBackupHealth" in script
    assert "check-postgres-backup-health.ps1" in script
    assert "New-ScheduledTaskTrigger" in script
    assert "-RepetitionInterval" in script
    assert "Convert-DataRootForScheduledTask" in script
    assert "DisplayRoot" in script
    assert "-MaxAgeMinutes" in script
    assert "-MinBytes" in script
    assert "-NonInteractive" in script
    assert "-CommandTimeoutSeconds" in script
    assert "-SkipRestoreList" in script
    assert "ExecutionTimeLimitMinutes" in script
    assert "-ExecutionTimeLimit" in script
    assert "Register-ScheduledTask" in script
