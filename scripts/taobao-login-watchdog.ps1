param(
    [int]$Port = 9223,
    [string]$DataRoot = "",
    [string]$CheckUrl = "https://sf.taobao.com/list/50025969__2.htm",
    [string[]]$SampleUrl = @(
        "https://sf.taobao.com/list/50025969__2.htm",
        "https://sf.taobao.com/list/200782003__1.htm"
    ),
    [int]$WaitSeconds = 600,
    [int]$PollSeconds = 5,
    [string]$Python = "python",
    [switch]$SkipBrowserStart,
    [switch]$UseSystemProxy,
    [switch]$TriggerCaptchaSolver,
    [switch]$NoSnapshotExport
)

$ErrorActionPreference = "Stop"
$captchaSolverEnv = [string]$env:FAPAI_CAPTCHA_SOLVER_ENABLED
$effectiveTriggerCaptchaSolver = [bool]($TriggerCaptchaSolver -or ($captchaSolverEnv -match '^(?i:1|true|yes|y|on)$'))

function Invoke-HealthCheck {
    param([int]$Wait)

    $stdout = Join-Path $env:TEMP ("fpf-taobao-login-watchdog-" + [guid]::NewGuid().ToString() + ".stdout")
    $stderr = Join-Path $env:TEMP ("fpf-taobao-login-watchdog-" + [guid]::NewGuid().ToString() + ".stderr")
    try {
        $arguments = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $healthScript,
            "-SkipBrowserStart",
            "-Port", $Port,
            "-CheckUrl", $CheckUrl,
            "-WaitSeconds", $Wait,
            "-PollSeconds", $PollSeconds,
            "-Python", $Python
        )
        if ($SampleUrl -and $SampleUrl.Count -gt 0) {
            $arguments += "-SampleUrl"
            $arguments += $SampleUrl
        }
        if ($effectiveTriggerCaptchaSolver) {
            $arguments += "-TriggerCaptchaSolver"
        }
        $process = Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList $arguments `
            -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr `
            -Wait `
            -PassThru `
            -NoNewWindow
        $exitCode = $process.ExitCode
        $stdoutText = if (Test-Path -LiteralPath $stdout) { Get-Content -Raw -LiteralPath $stdout } else { "" }
        $stderrText = if (Test-Path -LiteralPath $stderr) { Get-Content -Raw -LiteralPath $stderr } else { "" }
        $text = "$stdoutText`n$stderrText"
        $status = if ($text -match '"status"\s*:\s*"([^"]+)"') { $Matches[1] } else { "<missing>" }
        $healthy = if ($text -match '"healthy"\s*:\s*(true|false)') { $Matches[1] } else { "false" }
        $sensitiveAssignmentPattern = ("x5secdata" + "=|" + "cookie2" + "=|" + "sgcookie" + "=|" + "_tb_token_" + "=|" + "x5sec" + "=")
        $hasSensitive = $text -match $sensitiveAssignmentPattern
        return @{
            ExitCode = $exitCode
            Status = $status
            Healthy = ($healthy -eq "true")
            ContainsSensitive = [bool]$hasSensitive
        }
    }
    finally {
        Remove-Item -LiteralPath $stdout -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stderr -Force -ErrorAction SilentlyContinue
    }
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$startScript = Join-Path $repoRoot "scripts\start-taobao-cdp-browser.ps1"
$healthScript = Join-Path $repoRoot "scripts\check-taobao-login-health.ps1"
$exportScript = Join-Path $repoRoot "scripts\export-taobao-cookie-snapshot.ps1"

foreach ($required in @($startScript, $healthScript, $exportScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing required watchdog helper: $required"
    }
}

Write-Output "FapaiFangTaobaoLoginWatchdog: checking Taobao/SF login health."
if (-not $SkipBrowserStart) {
    $startArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $startScript,
        "-Port", $Port
    )
    if ($DataRoot) {
        $startArgs += @("-DataRoot", $DataRoot)
    }
    if ($UseSystemProxy) {
        $startArgs += "-UseSystemProxy"
    }
    & powershell @startArgs
}

$initial = Invoke-HealthCheck -Wait 0
Write-Output "FapaiFangTaobaoLoginWatchdog: status=$($initial.Status), healthy=$($initial.Healthy), contains_sensitive=$($initial.ContainsSensitive)"

if ($initial.Status -eq "cdp_unreachable" -and -not $SkipBrowserStart) {
    Write-Output "FapaiFangTaobaoLoginWatchdog: CDP websocket is unreachable; force-restarting the dedicated browser."
    $restartArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $startScript,
        "-Port", $Port,
        "-ForceNew"
    )
    if ($DataRoot) {
        $restartArgs += @("-DataRoot", $DataRoot)
    }
    if ($UseSystemProxy) {
        $restartArgs += "-UseSystemProxy"
    }
    & powershell @restartArgs
    $initial = Invoke-HealthCheck -Wait 0
    Write-Output "FapaiFangTaobaoLoginWatchdog: after_restart_status=$($initial.Status), healthy=$($initial.Healthy), contains_sensitive=$($initial.ContainsSensitive)"
}

if (-not $initial.Healthy) {
    Write-Output "FapaiFangTaobaoLoginWatchdog: complete Taobao official verification in the visible browser window if the configured captcha solver cannot finish it. This script queues the configured captcha solver and does not print cookie value fields."
    $recovered = Invoke-HealthCheck -Wait $WaitSeconds
    Write-Output "FapaiFangTaobaoLoginWatchdog: recovered_status=$($recovered.Status), healthy=$($recovered.Healthy), contains_sensitive=$($recovered.ContainsSensitive)"
    if (-not $recovered.Healthy) {
        exit 2
    }
}

if (-not $NoSnapshotExport) {
    $exportArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $exportScript,
        "-Port", $Port,
        "-Python", $Python,
        "-SkipBrowserStart"
    )
    if ($DataRoot) {
        $exportArgs += @("-DataRoot", $DataRoot)
    }
    & powershell @exportArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Cookie snapshot export failed with exit code $LASTEXITCODE."
    }
}

Write-Output "FapaiFangTaobaoLoginWatchdog: healthy."
