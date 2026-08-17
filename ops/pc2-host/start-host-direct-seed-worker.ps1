$ctx = & 'C:\fapaifang-worker\ops\load-host-direct-nas-env.ps1'
Set-Location $ctx.SrcRoot
$outputDir = Join-Path $ctx.SharedRoot 'output\nodes\pc2-real\seed_collector'
$jobsFile = Join-Path $ctx.SharedRoot 'jobs\seed_jobs_all.json'
$workerId = if ($env:FAPAI_HOST_SEED_WORKER_ID) { $env:FAPAI_HOST_SEED_WORKER_ID } else { 'pc2-real-seed-1' }
$solverEnabled = if ($env:FAPAI_SEED_CAPTCHA_SOLVER_ENABLED) {
  $env:FAPAI_SEED_CAPTCHA_SOLVER_ENABLED
} elseif ($env:FAPAI_CAPTCHA_SOLVER_ENABLED) {
  $env:FAPAI_CAPTCHA_SOLVER_ENABLED
} else {
  '0'
}
$manualChallengeReportingSupported = $true
$apiStatusReachable = $false
try {
  $apiStatus = Invoke-RestMethod -Uri 'http://192.168.15.200:8001/api/status' -TimeoutSec 5
  $apiStatusReachable = $true
  $manualChallengeReportingSupported = $true
  if (
    $null -ne $apiStatus.capabilities -and
    $null -ne $apiStatus.capabilities.manual_captcha_report_v1
  ) {
    $manualChallengeReportingSupported = $apiStatus.capabilities.manual_captcha_report_v1 -eq $true
  }
} catch {
  # The manual-only endpoint is the safe default during a brief API restart.
  $manualChallengeReportingSupported = $true
}

function Find-ExistingWorkerProcess {
  $scriptPattern = [regex]::Escape('tools\seed_collector.py')
  $workerIdPattern = '--worker-id\s+' + [regex]::Escape($workerId)
  return Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Name -eq 'python.exe' -and
      $_.CommandLine -match $scriptPattern -and
      $_.CommandLine -match $workerIdPattern
    } |
    Sort-Object CreationDate -Descending |
    Select-Object -First 1
}

$existing = Find-ExistingWorkerProcess
if ($null -ne $existing) {
  Write-Output "seed already running with pid $($existing.ProcessId)"
  exit 0
}

if (-not $env:FAPAI_LIST_BROWSER_FALLBACK) {
  [Environment]::SetEnvironmentVariable('FAPAI_LIST_BROWSER_FALLBACK', '0', 'Process')
}
if (-not $env:FAPAI_LIST_HTTP_TIMEOUT_SECONDS) {
  [Environment]::SetEnvironmentVariable('FAPAI_LIST_HTTP_TIMEOUT_SECONDS', '8', 'Process')
}
if (-not $env:FAPAI_LIST_BROWSER_RECOVERY_MAX_ATTEMPTS) {
  [Environment]::SetEnvironmentVariable('FAPAI_LIST_BROWSER_RECOVERY_MAX_ATTEMPTS', '2', 'Process')
}
if (-not $env:FAPAI_LIST_BROWSER_RECOVERY_WAIT_SECONDS) {
  [Environment]::SetEnvironmentVariable('FAPAI_LIST_BROWSER_RECOVERY_WAIT_SECONDS', '2', 'Process')
}

if (-not (Test-Path -LiteralPath $jobsFile)) {
  $generateScript = Join-Path $ctx.SrcRoot 'scripts\generate-all-seed-jobs.ps1'
  if (-not (Test-Path -LiteralPath $generateScript)) {
    throw "Missing seed job generator script: $generateScript"
  }
  & $generateScript -DataRoot $ctx.SharedRoot -Python $ctx.Python
}

$args = @(
  'tools\seed_collector.py',
  '--output-dir', $outputDir,
  '--cdp-endpoint', $env:FAPAI_CDP_ENDPOINT,
  '--worker-id', $workerId,
  '--loop',
  '--pages-per-run', '5',
  '--active-loop-interval-seconds', '5',
  '--loop-interval-seconds', '30',
  '--auth-probe-interval-seconds', '10',
  '--api-base-url', 'http://192.168.15.200:8001/api',
  '--failure-cooldown-threshold', '10',
  '--failure-cooldown-seconds', '120'
)

if (
  ([string]$solverEnabled).Trim().ToLowerInvariant() -in @('1', 'true', 'yes', 'on')
) {
  $args += '--solver-enabled'
} elseif ($manualChallengeReportingSupported) {
  $args += '--manual-challenge-reporting'
}

& $ctx.Python @args
