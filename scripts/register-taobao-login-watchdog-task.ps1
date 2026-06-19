param(
    [string]$TaskName = "FapaiFangTaobaoLoginWatchdog",
    [string]$DataRoot = "C:\Users\Public\nas_home\AI\FPFData",
    [int]$IntervalMinutes = 5,
    [int]$WaitSeconds = 600,
    [int]$PollSeconds = 5,
    [int]$Port = 9223,
    [string]$TaskPath = "\FapaiFang\",
    [int]$ExecutionTimeLimitMinutes = 15,
    [switch]$UseSystemProxy
)

$ErrorActionPreference = "Stop"

function Convert-DataRootForScheduledTask {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ($Path -match "^[A-Za-z]:\\") {
        $driveName = $Path.Substring(0, 1)
        $drive = Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue
        if ($drive -and $drive.DisplayRoot) {
            $relativePath = $Path.Substring(3)
            return (Join-Path $drive.DisplayRoot $relativePath)
        }
    }

    return [System.IO.Path]::GetFullPath($Path)
}

if ($IntervalMinutes -lt 1) {
    throw "IntervalMinutes must be at least 1."
}
if ($WaitSeconds -lt 0) {
    throw "WaitSeconds must not be negative."
}
if ($ExecutionTimeLimitMinutes -lt 1) {
    throw "ExecutionTimeLimitMinutes must be at least 1."
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$watchdogScript = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\taobao-login-watchdog.ps1"))
if (-not (Test-Path -LiteralPath $watchdogScript)) {
    throw "Watchdog script not found: $watchdogScript"
}

$taskDataRoot = Convert-DataRootForScheduledTask -Path $DataRoot
$workingDirectory = $repoRoot

$scriptArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$watchdogScript`"",
    "-DataRoot", "`"$taskDataRoot`"",
    "-Port", $Port,
    "-WaitSeconds", $WaitSeconds,
    "-PollSeconds", $PollSeconds
)
if ($UseSystemProxy) {
    $scriptArgs += "-UseSystemProxy"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ($scriptArgs -join " ") `
    -WorkingDirectory $workingDirectory

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
    -Description "FapaiFangTaobaoLoginWatchdog opens official Taobao verification for manual completion and refreshes the local cookie snapshot."

Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath $TaskPath `
    -InputObject $task `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
