param(
  [string]$TaskName = 'FapaiPc2CdpSelfHealBootstrap',
  [string]$TaskPath = '\',
  [string]$MonitoredTaskName = 'FapaiPc2CdpSelfHeal'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = 'C:\fapaifang-worker'
$interactiveStarter = Join-Path $root 'ops\start-scheduled-task-in-active-session.ps1'
if (-not (Test-Path -LiteralPath $interactiveStarter)) {
  throw "PC2 interactive task starter not found: $interactiveStarter"
}

$arguments = @(
  '-WindowStyle', 'Hidden',
  '-NonInteractive',
  '-NoProfile',
  '-ExecutionPolicy', 'Bypass',
  '-File', ('"{0}"' -f $interactiveStarter),
  '-TaskName', ('"{0}"' -f $MonitoredTaskName),
  '-TimeoutSeconds', '30',
  '-Supervise'
) -join ' '
$action = New-ScheduledTaskAction `
  -Execute 'powershell.exe' `
  -Argument $arguments `
  -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger `
  -Once `
  -At (Get-Date).AddSeconds(30) `
  -RepetitionInterval (New-TimeSpan -Minutes 1) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal `
  -UserId 'SYSTEM' `
  -LogonType ServiceAccount `
  -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew `
  -StartWhenAvailable `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 1)
$task = New-ScheduledTask `
  -Action $action `
  -Trigger $trigger `
  -Principal $principal `
  -Settings $settings `
  -Description 'Every minute, ensures the PC2 CDP self-heal watchdog is running in the active console session without storing a user password.'

$existing = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($null -ne $existing) {
  Stop-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
}
Register-ScheduledTask `
  -TaskName $TaskName `
  -TaskPath $TaskPath `
  -InputObject $task `
  -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
