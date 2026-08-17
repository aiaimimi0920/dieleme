param(
  [string]$StartUrl = 'https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1',
  [int]$Port = 9223,
  [string]$ProfileDir = 'C:\Users\Public\nas_home\AI\FPFData\edge-cdp-profile-pc2',
  [string]$TaskName = 'FapaiPc2OpenAuth',
  [string]$TaskPath = '\',
  [string]$UserId = ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

foreach ($value in @($StartUrl, $ProfileDir)) {
  if ([string]$value -match '"') {
    throw 'Authentication task arguments must not contain double quotes.'
  }
}

$openAuthScript = Join-Path $PSScriptRoot 'open-auth-latest.ps1'
if (-not (Test-Path -LiteralPath $openAuthScript)) {
  throw "PC2 authentication script not found: $openAuthScript"
}

$arguments = @(
  '-WindowStyle', 'Hidden',
  '-NoProfile',
  '-ExecutionPolicy', 'Bypass',
  '-File', ('"{0}"' -f $openAuthScript),
  '-Port', $Port,
  '-ProfileDir', ('"{0}"' -f $ProfileDir),
  '-RequestedUrl', ('"{0}"' -f $StartUrl)
) -join ' '

$action = New-ScheduledTaskAction `
  -Execute 'powershell.exe' `
  -Argument $arguments `
  -WorkingDirectory $PSScriptRoot
$principal = New-ScheduledTaskPrincipal `
  -UserId $UserId `
  -LogonType Interactive `
  -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 6) `
  -MultipleInstances IgnoreNew
$task = New-ScheduledTask `
  -Action $action `
  -Principal $principal `
  -Settings $settings `
  -Description 'Opens or refreshes the Taobao authentication challenge in the PC2 interactive desktop.'

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
