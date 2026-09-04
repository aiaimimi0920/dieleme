function Get-WorkerSummaryState {
  param([Parameter(Mandatory = $true)]$Spec)

  if (-not (Test-Path -LiteralPath $Spec.SummaryPath)) {
    return $null
  }
  try {
    $item = Get-Item -LiteralPath $Spec.SummaryPath -ErrorAction Stop
    $payload = Get-Content -LiteralPath $Spec.SummaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
    return [pscustomobject]@{
      Decision = [string]$payload.decision
      LastWriteTimeUtc = $item.LastWriteTimeUtc
      Fresh = ((Get-Date) - $item.LastWriteTime).TotalSeconds -le [int]$Spec.SummaryMaxAgeSeconds
    }
  } catch {
    return $null
  }
}

function Initialize-AnalysisUnavailableSummaryBaseline {
  # A watchdog restart must get one real backend probe. Otherwise the last
  # unavailable summary from the previous process is treated as a new failure
  # and the worker immediately re-enters cooldown without ever starting.
  foreach ($spec in $workerSpecs) {
    if (-not $spec.IsAnalysis) {
      continue
    }
    $summary = Get-WorkerSummaryState -Spec $spec
    if ($null -eq $summary -or $summary.Decision -ne 'detail_worker_llm_unavailable') {
      continue
    }
    $script:analysisUnavailableSummaryWriteTicks[[string]$spec.Name] = `
      [int64]$summary.LastWriteTimeUtc.Ticks
  }
}

function Test-NewAnalysisBackendUnavailableSummary {
  param(
    [Parameter(Mandatory = $true)]$Spec,
    $Summary
  )

  if (-not $Spec.IsAnalysis -or $null -eq $Summary) {
    return $false
  }
  if (-not $Summary.Fresh -or $Summary.Decision -ne 'detail_worker_llm_unavailable') {
    return $false
  }

  $name = [string]$Spec.Name
  $writeTicks = [int64]$Summary.LastWriteTimeUtc.Ticks
  if (
    $script:analysisUnavailableSummaryWriteTicks.ContainsKey($name) -and
    [int64]$script:analysisUnavailableSummaryWriteTicks[$name] -eq $writeTicks
  ) {
    return $false
  }
  $script:analysisUnavailableSummaryWriteTicks[$name] = $writeTicks
  return $true
}

function Enter-AnalysisBackendCooldown {
  param([Parameter(Mandatory = $true)]$Spec)

  $cooldownSeconds = [Math]::Max(1, $AnalysisBackendRetryCooldownSeconds)
  $retryAt = (Get-Date).AddSeconds($cooldownSeconds)
  $script:analysisBackendRetryAt[[string]$Spec.Name] = $retryAt
  Write-WatchdogLog (
    'analysis backend unavailable for {0}; retry after {1} ({2}s cooldown)' -f `
      $Spec.Name,
      $retryAt.ToString('yyyy-MM-dd HH:mm:ss'),
      $cooldownSeconds
  )
}

function Test-AnalysisBackendCooldown {
  param([Parameter(Mandatory = $true)]$Spec)

  $name = [string]$Spec.Name
  if (-not $script:analysisBackendRetryAt.ContainsKey($name)) {
    return $false
  }
  $retryAt = [datetime]$script:analysisBackendRetryAt[$name]
  if ((Get-Date) -lt $retryAt) {
    return $true
  }

  $script:analysisBackendRetryAt.Remove($name)
  Write-WatchdogLog "analysis backend cooldown expired for $name; allowing one retry"
  return $false
}
