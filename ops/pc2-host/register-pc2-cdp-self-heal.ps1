param(
  [string]$TaskName = 'FapaiPc2CdpSelfHeal',
  [string]$TaskPath = '\',
  [string]$UserId = ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = 'C:\fapaifang-worker'
$watchdogScript = Join-Path $root 'ops\watch-pc2-cdp-self-heal.ps1'
$interactiveStarter = Join-Path $root 'ops\start-scheduled-task-in-active-session.ps1'
$bootstrapRegister = Join-Path $root 'ops\register-pc2-cdp-self-heal-bootstrap.ps1'
if (-not (Test-Path -LiteralPath $watchdogScript)) {
  throw "PC2 CDP self-heal script not found: $watchdogScript"
}
if (-not (Test-Path -LiteralPath $interactiveStarter)) {
  throw "PC2 interactive task starter not found: $interactiveStarter"
}
if (-not (Test-Path -LiteralPath $bootstrapRegister)) {
  throw "PC2 self-heal bootstrap registration script not found: $bootstrapRegister"
}

$arguments = @(
  '-WindowStyle', 'Hidden',
  '-NonInteractive',
  '-NoProfile',
  '-ExecutionPolicy', 'Bypass',
  '-File', ('"{0}"' -f $watchdogScript),
  '-PollSeconds', '60',
  '-CdpFailureThreshold', '3',
  '-StaleChallengeSeconds', '300',
  '-RestartCooldownSeconds', '180',
  '-SolverAttemptThreshold', '10',
  '-SolverProgressGraceSeconds', '180',
  '-CdpRecoveryTimeoutSeconds', '240'
) -join ' '

$action = New-ScheduledTaskAction `
  -Execute 'powershell.exe' `
  -Argument $arguments `
  -WorkingDirectory $root
$triggers = @(
  New-ScheduledTaskTrigger -AtLogOn -User $UserId
  New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(30)
)
$principal = New-ScheduledTaskPrincipal `
  -UserId $UserId `
  -LogonType Interactive `
  -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew `
  -StartWhenAvailable `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1)

$task = New-ScheduledTask `
  -Action $action `
  -Trigger $triggers `
  -Principal $principal `
  -Settings $settings `
  -Description 'Detects stale PC2 CDP or node-owned auth state, force-restarts the auth browser, safely clears the matching challenge, and restores workers.'

$existing = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($null -ne $existing) {
  Stop-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
}
$existingWatchdogs = @(
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'watch-pc2-cdp-self-heal\.ps1' }
)
foreach ($process in $existingWatchdogs) {
  & taskkill.exe /PID $process.ProcessId /T /F 2>$null | Out-Null
  Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($existingWatchdogs.Count -gt 0) {
  Start-Sleep -Seconds 2
}
Register-ScheduledTask `
  -TaskName $TaskName `
  -TaskPath $TaskPath `
  -InputObject $task `
  -Force | Out-Null
& $bootstrapRegister -MonitoredTaskName $TaskName -TaskPath $TaskPath | Out-Null
Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
