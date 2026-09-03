param(
    [string]$TaskName = "FapaiFangNasAuthRecovery",
    [string]$TaskPath = "\FapaiFang\",
    [string]$ApiBase = "http://192.168.15.200:8001/api",
    [string]$DataRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) "FPFData"),
    [string]$OutputPath = "",
    [string]$TokenPath = "",
    [string]$ProfileDir = (Join-Path (Split-Path -Parent $PSScriptRoot) "FPFData\chrome-cdp-profile-pc1-human-clean"),
    [string]$BrowserPath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    [int]$Port = 9225,
    [int]$IntervalMinutes = 1,
    [int]$LoginWindowSeconds = 300,
    [int]$ExecutionTimeLimitMinutes = 10,
    [switch]$UseSystemProxy,
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
if ($IntervalMinutes -lt 1) { throw "IntervalMinutes must be at least 1." }
if ($LoginWindowSeconds -lt 300) { throw "LoginWindowSeconds must be at least 300." }
if ($ExecutionTimeLimitMinutes -lt 5) { throw "ExecutionTimeLimitMinutes must be at least 5." }

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$watcher = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\watch-pc1-nas-auth-recovery.ps1"))
if (-not (Test-Path -LiteralPath $watcher)) {
    throw "NAS auth recovery watcher not found: $watcher"
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $DataRoot "secrets\nodes\pc2\taobao-cookies.json"
}
if (-not $TokenPath) {
    $TokenPath = Join-Path $DataRoot "secrets\nas-auth-recovery.token"
}

$arguments = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", "`"$watcher`"",
    "-ApiBase", "`"$ApiBase`"",
    "-DataRoot", "`"$DataRoot`"",
    "-OutputPath", "`"$OutputPath`"",
    "-TokenPath", "`"$TokenPath`"",
    "-ProfileDir", "`"$ProfileDir`"",
    "-BrowserPath", "`"$BrowserPath`"",
    "-Port", $Port,
    "-LoginWindowSeconds", $LoginWindowSeconds
)
if ($UseSystemProxy) {
    $arguments += "-UseSystemProxy"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ($arguments -join " ") `
    -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes $ExecutionTimeLimitMinutes)
$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Polls the NAS single-flight auth recovery job, keeps one five-minute PC1 login window, and publishes only validated cookie metadata."
Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -InputObject $task -Force | Out-Null
Enable-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath | Out-Null
if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
}
Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
