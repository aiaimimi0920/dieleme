$ctx = & 'C:\fapaifang-worker\ops\load-host-direct-nas-env.ps1'
if ($null -ne $env:FAPAI_HOST_DETAIL_BROWSER_FALLBACK_OVERRIDE -and $env:FAPAI_HOST_DETAIL_BROWSER_FALLBACK_OVERRIDE -ne '') {
  [Environment]::SetEnvironmentVariable(
    'FAPAI_DETAIL_BROWSER_FALLBACK',
    $env:FAPAI_HOST_DETAIL_BROWSER_FALLBACK_OVERRIDE,
    'Process'
  )
}
Set-Location $ctx.SrcRoot
$workerId = if ($env:FAPAI_HOST_DETAIL_WORKER_ID) { $env:FAPAI_HOST_DETAIL_WORKER_ID } else { 'pc2-real-detail-1' }
$outputDir = if ($env:FAPAI_HOST_DETAIL_OUTPUT_DIR) {
  $env:FAPAI_HOST_DETAIL_OUTPUT_DIR
} else {
  Join-Path $ctx.SharedRoot 'output\nodes\pc2-real\detail_worker'
}
$detailCdpEndpoint = if ($env:FAPAI_DETAIL_CDP_ENDPOINT) { $env:FAPAI_DETAIL_CDP_ENDPOINT } else { $env:FAPAI_CDP_ENDPOINT }
$targetSuccess = if ($env:FAPAI_HOST_DETAIL_TARGET_SUCCESS) { $env:FAPAI_HOST_DETAIL_TARGET_SUCCESS } else { '10' }
$maxAttempts = if ($env:FAPAI_HOST_DETAIL_MAX_ATTEMPTS) { $env:FAPAI_HOST_DETAIL_MAX_ATTEMPTS } else { '30' }
$activeLoopIntervalSeconds = if ($env:FAPAI_HOST_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS) { $env:FAPAI_HOST_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS } else { '0' }
$successDelaySeconds = if ($env:FAPAI_HOST_DETAIL_SUCCESS_DELAY_SECONDS) { $env:FAPAI_HOST_DETAIL_SUCCESS_DELAY_SECONDS } else { '0' }
$failureDelaySeconds = if ($env:FAPAI_HOST_DETAIL_FAILURE_DELAY_SECONDS) { $env:FAPAI_HOST_DETAIL_FAILURE_DELAY_SECONDS } else { '1' }
$solverEnabled = if ($env:FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED) {
  $env:FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED
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
  $scriptPattern = [regex]::Escape('tools\detail_worker.py')
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
  Write-Output "detail already running with pid $($existing.ProcessId)"
  exit 0
}

$args = @(
  'tools\detail_worker.py',
  '--output-dir', $outputDir,
  '--cdp-endpoint', $detailCdpEndpoint,
  '--target-success', $targetSuccess,
  '--max-attempts', $maxAttempts,
  '--item-max-attempts', '3',
  '--worker-id', $workerId,
  '--failure-cooldown-seconds', '120',
  '--loop',
  '--success-delay-seconds', $successDelaySeconds,
  '--failure-delay-seconds', $failureDelaySeconds,
  '--active-loop-interval-seconds', $activeLoopIntervalSeconds,
  '--loop-interval-seconds', '30',
  '--api-base-url', 'http://192.168.15.200:8001/api',
  '--raw-only'
)

if (
  ([string]$solverEnabled).Trim().ToLowerInvariant() -in @('1', 'true', 'yes', 'on')
) {
  $args += '--solver-enabled'
} elseif ($manualChallengeReportingSupported) {
  $args += '--manual-challenge-reporting'
}

& $ctx.Python @args
