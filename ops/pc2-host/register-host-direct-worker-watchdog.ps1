param(
  [string]$TaskName = 'FapaiPc2RealWorkerLauncher',
  [string]$TaskPath = '\',
  [string]$UserId = ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = 'C:\fapaifang-worker'
$watchdogScript = Join-Path $root 'ops\launch-host-direct-workers.ps1'
if (-not (Test-Path -LiteralPath $watchdogScript)) {
  throw "Worker watchdog script not found: $watchdogScript"
}

$arguments = @(
  '-WindowStyle', 'Hidden',
  '-NoProfile',
  '-ExecutionPolicy', 'Bypass',
  '-File', ('"{0}"' -f $watchdogScript)
) -join ' '

$action = New-ScheduledTaskAction `
  -Execute 'powershell.exe' `
  -Argument $arguments `
  -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
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
  -Trigger $trigger `
  -Principal $principal `
  -Settings $settings `
  -Description 'Keeps the pc2 FapaiFang seed and detail workers alive and restarts stale workers without visible consoles.'

$legacyTaskNames = @(
  'FapaiFangPc2HostDetailWorker1',
  'FapaiFangPc2HostDetailWorker2',
  'FapaiFangPc2HostDetailWorker3',
  'FPF-HostDetailWorker-Logon',
  'FPF-HostDetailWorker-Minute',
  'FPF-HostSeedWorker-Logon',
  'FPF-HostSeedWorker-Minute',
  'FPF-HostSeedWorker2-Logon',
  'FapaifangPc2RealDetail1',
  'FapaifangPc2RealDetail2',
  'FapaifangPc2RealSeed',
  'FapaiPc2RealSeedWorker',
  'FPF-HostCDP-Logon',
  'FPF-Launch-CDP-Interactive',
  'FapaiFangPc2CdpInteractive',
  'FapaiFangPc2HiddenCdpSvc2',
  'FapaiFangTaobaoCdpBrowser',
  'FapaiFangTaobaoLoginWatchdog'
)
foreach ($legacyTaskName in $legacyTaskNames) {
  $legacyTasks = @(Get-ScheduledTask -TaskName $legacyTaskName -ErrorAction SilentlyContinue)
  foreach ($legacyTask in $legacyTasks) {
    Stop-ScheduledTask `
      -TaskName $legacyTask.TaskName `
      -TaskPath $legacyTask.TaskPath `
      -ErrorAction SilentlyContinue
    Unregister-ScheduledTask `
      -TaskName $legacyTask.TaskName `
      -TaskPath $legacyTask.TaskPath `
      -Confirm:$false
  }
}

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
