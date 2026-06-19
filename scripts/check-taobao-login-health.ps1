param(
    [int]$Port = 9223,
    [string]$DataRoot = "",
    [string]$CheckUrl = "https://sf.taobao.com/list/50025969__2.htm",
    [string[]]$SampleUrl = @(),
    [int]$WaitSeconds = 180,
    [int]$PollSeconds = 5,
    [string]$Python = "python",
    [switch]$StartBrowser,
    [switch]$SkipBrowserStart,
    [switch]$IsolatedProfile,
    [switch]$DisableExtensions,
    [switch]$TriggerCaptchaSolver
)

$ErrorActionPreference = "Stop"

function Test-CdpEndpoint {
    param([Parameter(Mandatory = $true)][string]$Endpoint)

    try {
        $response = Invoke-WebRequest -Uri "$($Endpoint.TrimEnd('/'))/json/version" -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$cdpEndpoint = "http://127.0.0.1:$Port"
$startScript = Join-Path $repoRoot "scripts\start-taobao-cdp-browser.ps1"
$healthScript = Join-Path $repoRoot "tools\taobao_login_health.py"

if (-not (Test-Path -LiteralPath $healthScript)) {
    throw "Missing Taobao login health helper: $healthScript"
}

if (-not $SkipBrowserStart) {
    $shouldStart = $StartBrowser -or -not (Test-CdpEndpoint -Endpoint $cdpEndpoint)
    if ($shouldStart) {
        $startArgs = @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $startScript,
            "-Port",
            $Port
        )
        if ($DataRoot) {
            $startArgs += @("-DataRoot", $DataRoot)
        }
        if ($IsolatedProfile) {
            $startArgs += @("-IsolatedProfile")
        }
        if ($DisableExtensions) {
            $startArgs += @("-DisableExtensions")
        }
        & powershell @startArgs
    }
}

Write-Output "Checking Taobao/SF login health through $cdpEndpoint"
Write-Output "If Taobao shows QR login, punish, captcha, or security verification, complete it in the visible browser window."

$healthSampleUrls = @()
if ($SampleUrl -and $SampleUrl.Count -gt 0) {
    $healthSampleUrls += $SampleUrl
}
else {
    $healthSampleUrls += $CheckUrl
    $healthSampleUrls += "https://sf.taobao.com/list/200782003__1.htm"
}

$healthArgs = @(
    $healthScript,
    "--cdp-endpoint", $cdpEndpoint,
    "--check-url", $CheckUrl,
    "--open-login",
    "--wait-seconds", $WaitSeconds,
    "--poll-seconds", $PollSeconds,
    "--json"
)
if ($TriggerCaptchaSolver) {
    $healthArgs += "--trigger-captcha-solver"
}
foreach ($url in $healthSampleUrls) {
    $healthArgs += @("--sample-url", $url)
}

& $Python @healthArgs

exit $LASTEXITCODE
