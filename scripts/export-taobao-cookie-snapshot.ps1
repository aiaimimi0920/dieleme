param(
    [int]$Port = 9223,
    [string]$DataRoot = "",
    [string]$OutputPath = "",
    [string]$Python = "python",
    [string[]]$SampleUrl = @(
        "https://sf.taobao.com/list/50025969__2.htm",
        "https://sf.taobao.com/list/200782003__1.htm"
    ),
    [switch]$StartBrowser,
    [switch]$SkipBrowserStart,
    [switch]$IsolatedProfile,
    [switch]$DisableExtensions
)

$ErrorActionPreference = "Stop"

function Resolve-FapaiDataRoot {
    if ($DataRoot) {
        return $DataRoot
    }

    if ($env:FAPAI_DATA_ROOT_HOST) {
        return $env:FAPAI_DATA_ROOT_HOST
    }

    $localEnvPath = Join-Path $PSScriptRoot "..\docker.local.env"
    if (Test-Path -LiteralPath $localEnvPath) {
        $configuredRoot = Select-String -LiteralPath $localEnvPath -Pattern "^FAPAI_DATA_ROOT_HOST=(.+)$" | Select-Object -First 1
        if ($configuredRoot) {
            return $configuredRoot.Matches[0].Groups[1].Value.Trim()
        }
    }

    return "C:\Users\Public\nas_home\AI\FPFData"
}

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
$previousPythonPath = $env:PYTHONPATH
if ($previousPythonPath) {
    $env:PYTHONPATH = "$repoRoot;$previousPythonPath"
}
else {
    $env:PYTHONPATH = $repoRoot
}

$dataRootResolved = Resolve-FapaiDataRoot
if (-not $OutputPath) {
    $OutputPath = Join-Path $dataRootResolved "secrets\taobao-cookies.json"
}

$cdpEndpoint = "http://127.0.0.1:$Port"
$startScript = Join-Path $repoRoot "scripts\start-taobao-cdp-browser.ps1"
$probeScript = Join-Path $repoRoot "tools\browserless_seed_probe.py"

if (-not (Test-Path -LiteralPath $probeScript)) {
    throw "Missing browserless seed probe helper: $probeScript"
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

$outputParent = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outputParent | Out-Null
$candidatePath = Join-Path $outputParent ("taobao-cookies.candidate." + [guid]::NewGuid().ToString() + ".json")

$helperOutput = Join-Path $env:TEMP ("fpf-cookie-export-" + [guid]::NewGuid().ToString() + ".jsonlog")
try {
    & $Python $probeScript `
        --cdp-endpoint $cdpEndpoint `
        --write-cookie-snapshot $candidatePath `
        *> $helperOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Cookie snapshot export helper failed with exit code $LASTEXITCODE. Helper output was not printed to avoid leaking Taobao security tokens or cookie values."
    }
}
finally {
    Remove-Item -LiteralPath $helperOutput -Force -ErrorAction SilentlyContinue
}

$validationScript = Join-Path $env:TEMP ("fpf-cookie-candidate-health-" + [guid]::NewGuid().ToString() + ".py")
$validationOutput = Join-Path $env:TEMP ("fpf-cookie-candidate-health-" + [guid]::NewGuid().ToString() + ".jsonlog")
try {
    @'
import json
import os
import sys
from pathlib import Path
from tools import browserless_seed_probe, taobao_login_health

path = Path(os.environ["FAPAI_COOKIE_SNAPSHOT_CANDIDATE"])
sample_urls = json.loads(os.environ["FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS_JSON"])
cookies = browserless_seed_probe.load_cookie_snapshot(path)
session = browserless_seed_probe.build_session_from_playwright_cookies(cookies)
cookie_summary = browserless_seed_probe.summarize_cookie_snapshot(cookies)
cookie_summary.pop("names", None)
sample_results = []
healthy_samples = 0
for url in sample_urls:
    summary = browserless_seed_probe.probe_seed_page(url, cookies=cookies, session=session, timeout=15)
    classification = taobao_login_health.classify_taobao_health(
        "",
        final_url=str(summary.get("final_url") or url),
        list_summary=summary,
        payload_present=summary.get("has_script") is True,
    )
    result = {
        "check_url": url,
        "status": classification["status"],
        "healthy": classification["healthy"],
        "final_url": classification["final_url"],
        "http_status": summary.get("status"),
        "has_script": summary.get("has_script"),
        "item_count": summary.get("item_count"),
        "body_has_login": summary.get("body_has_login"),
        "body_has_captcha": summary.get("body_has_captcha"),
        "body_has_punish": summary.get("body_has_punish"),
        "body_has_challenge": summary.get("body_has_challenge"),
    }
    if result["healthy"] is True:
        healthy_samples += 1
    sample_results.append(result)
payload = {
    "candidate_path": str(path),
    "cookie_summary": cookie_summary,
    "sample_count": len(sample_results),
    "healthy_samples": healthy_samples,
    "healthy": healthy_samples > 0,
    "sample_results": sample_results,
}
print(json.dumps(taobao_login_health.redact_taobao_health_output(payload), ensure_ascii=False))
sys.exit(0 if payload["healthy"] else 2)
'@ | Set-Content -LiteralPath $validationScript -Encoding UTF8
    $env:FAPAI_COOKIE_SNAPSHOT_CANDIDATE = $candidatePath
    $env:FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS_JSON = ($SampleUrl | ConvertTo-Json -Compress)
    & $Python $validationScript *> $validationOutput
    $validationJson = if (Test-Path -LiteralPath $validationOutput) { Get-Content -Raw -LiteralPath $validationOutput } else { "" }
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $candidatePath -Force -ErrorAction SilentlyContinue
        throw "Cookie snapshot candidate failed Taobao list health validation; official snapshot was not overwritten. Candidate health output: $validationJson"
    }
}
finally {
    Remove-Item -LiteralPath $validationScript -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $validationOutput -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\FAPAI_COOKIE_SNAPSHOT_CANDIDATE -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS_JSON -Force -ErrorAction SilentlyContinue
}

Move-Item -LiteralPath $candidatePath -Destination $OutputPath -Force

$summaryScript = Join-Path $env:TEMP ("fpf-cookie-summary-" + [guid]::NewGuid().ToString() + ".py")
$summaryOutput = Join-Path $env:TEMP ("fpf-cookie-summary-" + [guid]::NewGuid().ToString() + ".jsonlog")
try {
    @'
import json
import os
from pathlib import Path
from tools import browserless_seed_probe

path = Path(os.environ["FAPAI_COOKIE_SNAPSHOT_OUTPUT"])
cookies = browserless_seed_probe.load_cookie_snapshot(path)
summary = browserless_seed_probe.summarize_cookie_snapshot(cookies)
summary.pop('names', None)
summary['path'] = str(path)
print(json.dumps(summary, ensure_ascii=False))
'@ | Set-Content -LiteralPath $summaryScript -Encoding UTF8
    $env:FAPAI_COOKIE_SNAPSHOT_OUTPUT = $OutputPath
    & $Python $summaryScript *> $summaryOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Cookie snapshot summary failed with exit code $LASTEXITCODE. Summary helper output was not printed to avoid leaking Taobao security tokens or cookie values."
    }
    $summaryJson = Get-Content -Raw -LiteralPath $summaryOutput
}
finally {
    Remove-Item -LiteralPath $summaryScript -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $summaryOutput -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\FAPAI_COOKIE_SNAPSHOT_OUTPUT -Force -ErrorAction SilentlyContinue
}
$summary = $summaryJson | ConvertFrom-Json

Write-Output "Exported Taobao cookie snapshot without printing cookie value fields."
Write-Output "Cookie snapshot path: $OutputPath"
Write-Output "Docker worker path when using host-bind data root: /data/secrets/taobao-cookies.json"
$summary | ConvertTo-Json -Depth 6
