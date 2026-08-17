param(
    [string]$DataRoot = "",
    [string]$AlertWebhookUrl = "",
    [int]$Port = 9225,
    [int]$WatchdogIntervalMinutes = 5,
    [int]$WatchdogWaitSeconds = 180,
    [int]$WatchdogPollSeconds = 5,
    [int]$RecoveryMonitorIntervalMinutes = 1,
    [int]$RecentMinutes = 3,
    [int]$MinRecentSeedItems = 1,
    [int]$StaleSeedMinutes = 3,
    [int]$MissingPayloadThreshold = 20,
    [int]$RecoveryCooldownMinutes = 10,
    [string]$TaskPath = "\FapaiFang\",
    [switch]$UseSystemProxy,
    [switch]$StartWatchdogNow
)

$ErrorActionPreference = "Stop"

function Resolve-DefaultDataRoot {
    if ($DataRoot) {
        return $DataRoot
    }
    if ($env:FAPAI_DATA_ROOT_HOST) {
        return $env:FAPAI_DATA_ROOT_HOST
    }
    return "Z:\project\project\FPFData"
}

$resolvedDataRoot = Resolve-DefaultDataRoot
$outputPath = Join-Path $resolvedDataRoot "secrets\nodes\pc2\taobao-cookies.json"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$registerWatchdogScript = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\register-taobao-login-watchdog-task.ps1"))
$registerRecoveryScript = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\register-taobao-login-recovery-monitor-task.ps1"))

foreach ($required in @($registerWatchdogScript, $registerRecoveryScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing shared-auth maintenance helper: $required"
    }
}

$watchdogArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $registerWatchdogScript,
    "-DataRoot", $resolvedDataRoot,
    "-OutputPath", $outputPath,
    "-Port", $Port,
    "-IntervalMinutes", $WatchdogIntervalMinutes,
    "-WaitSeconds", $WatchdogWaitSeconds,
    "-PollSeconds", $WatchdogPollSeconds,
    "-TaskPath", $TaskPath
)
if ($AlertWebhookUrl) {
    $watchdogArgs += @("-AlertWebhookUrl", $AlertWebhookUrl)
}
if ($UseSystemProxy) {
    $watchdogArgs += "-UseSystemProxy"
}

$recoveryArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $registerRecoveryScript,
    "-DataRoot", $resolvedDataRoot,
    "-IntervalMinutes", $RecoveryMonitorIntervalMinutes,
    "-RecentMinutes", $RecentMinutes,
    "-MinRecentSeedItems", $MinRecentSeedItems,
    "-StaleSeedMinutes", $StaleSeedMinutes,
    "-MissingPayloadThreshold", $MissingPayloadThreshold,
    "-RecoveryCooldownMinutes", $RecoveryCooldownMinutes,
    "-TaskPath", $TaskPath
)

& powershell.exe @watchdogArgs | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Watchdog task registration failed with exit code $LASTEXITCODE."
}

& powershell.exe @recoveryArgs | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Recovery monitor task registration failed with exit code $LASTEXITCODE."
}

Enable-ScheduledTask -TaskName "FapaiFangTaobaoLoginWatchdog" -TaskPath $TaskPath | Out-Null
Enable-ScheduledTask -TaskName "FapaiFangTaobaoLoginRecoveryMonitor" -TaskPath $TaskPath | Out-Null

if ($StartWatchdogNow) {
    Start-ScheduledTask -TaskName "FapaiFangTaobaoLoginWatchdog" -TaskPath $TaskPath
}

$watchdogTask = Get-ScheduledTask -TaskName "FapaiFangTaobaoLoginWatchdog" -TaskPath $TaskPath
$watchdogInfo = Get-ScheduledTaskInfo -TaskName "FapaiFangTaobaoLoginWatchdog" -TaskPath $TaskPath
$recoveryTask = Get-ScheduledTask -TaskName "FapaiFangTaobaoLoginRecoveryMonitor" -TaskPath $TaskPath
$recoveryInfo = Get-ScheduledTaskInfo -TaskName "FapaiFangTaobaoLoginRecoveryMonitor" -TaskPath $TaskPath

[pscustomobject]@{
    data_root = $resolvedDataRoot
    port = $Port
    use_system_proxy = [bool]$UseSystemProxy
    start_watchdog_now = [bool]$StartWatchdogNow
    watchdog = [pscustomobject]@{
        task_name = $watchdogTask.TaskName
        task_path = $watchdogTask.TaskPath
        state = [string]$watchdogTask.State
        last_run_time = $watchdogInfo.LastRunTime
        last_task_result = $watchdogInfo.LastTaskResult
    }
    recovery_monitor = [pscustomobject]@{
        task_name = $recoveryTask.TaskName
        task_path = $recoveryTask.TaskPath
        state = [string]$recoveryTask.State
        last_run_time = $recoveryInfo.LastRunTime
        last_task_result = $recoveryInfo.LastTaskResult
    }
    thresholds = [pscustomobject]@{
        recent_minutes = $RecentMinutes
        min_recent_seed_items = $MinRecentSeedItems
        stale_seed_minutes = $StaleSeedMinutes
        missing_payload_threshold = $MissingPayloadThreshold
        recovery_cooldown_minutes = $RecoveryCooldownMinutes
    }
} | ConvertTo-Json -Compress
