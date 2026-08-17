param(
    [string]$TaskName = "FapaiPc1AnalysisProxyBridge",
    [string]$UserId = "$env:USERDOMAIN\$env:USERNAME"
)

$ErrorActionPreference = "Stop"
$sourceBridgeScript = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "start-pc1-analysis-proxy-bridge.ps1")).ProviderPath
$installDir = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "FapaiFangCollectorDesktop\scripts"
$bridgeScript = Join-Path $installDir "start-pc1-analysis-proxy-bridge.ps1"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Copy-Item -LiteralPath $sourceBridgeScript -Destination $bridgeScript -Force
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ("-WindowStyle Hidden -NonInteractive -NoProfile -ExecutionPolicy Bypass -File `"{0}`"" -f $bridgeScript) `
    -WorkingDirectory (Split-Path -Parent $bridgeScript)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

[pscustomobject]@{
    registered = $true
    task_name = $TaskName
    state = (Get-ScheduledTask -TaskName $TaskName).State.ToString()
    local_script_installed = Test-Path -LiteralPath $bridgeScript
} | ConvertTo-Json -Compress
