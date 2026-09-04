function Write-WatchdogLog {
  param([Parameter(Mandatory = $true)][string]$Message)

  $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
  Add-Content -LiteralPath $watchdogLog -Value $line -Encoding UTF8
}

function Test-CdpEndpoint {
  $response = $null
  try {
    $request = [System.Net.HttpWebRequest]::Create(
      "$($cdpEndpoint.TrimEnd('/'))/json/version"
    )
    $request.Proxy = $null
    $request.Timeout = 3000
    $request.ReadWriteTimeout = 3000
    $request.KeepAlive = $false
    $response = [System.Net.HttpWebResponse]$request.GetResponse()
    return [int]$response.StatusCode -eq 200
  } catch {
    return $false
  } finally {
    if ($null -ne $response) {
      $response.Close()
    }
  }
}

function Get-CollectionPauseState {
  try {
    $status = Invoke-RestMethod -Uri "$apiBaseUrl/status" -TimeoutSec 5
    $scopes = $status.collection_scopes
    $seed = if ($null -ne $scopes -and $null -ne $scopes.seed) {
      ([bool]$scopes.seed.paused -or [bool]$scopes.seed.manual_required)
    } else {
      [bool]$status.paused
    }
    $detail = if ($null -ne $scopes -and $null -ne $scopes.detail) {
      ([bool]$scopes.detail.paused -or [bool]$scopes.detail.manual_required)
    } else {
      [bool]$status.paused
    }
    # A global/operator pause has no scoped latch. Preserve fail-safe global
    # behavior in that case, while allowing a seed-only challenge to leave
    # detail collection running.
    $hasScopedPause = $seed -or $detail
    $global = ([bool]$status.paused -and -not $hasScopedPause)
    return [pscustomobject]@{
      global_paused = $global
      seed_paused = ($global -or $seed)
      detail_paused = ($global -or $detail)
    }
  } catch {
    # The NAS control plane is authoritative. Fail closed so an outage cannot
    # restart collection-scoped workers while the real pause state is unknown.
    return [pscustomobject]@{
      global_paused = $true
      seed_paused = $true
      detail_paused = $true
    }
  }
}

function Test-CollectionPaused {
  try {
    return [bool](Get-CollectionPauseState).global_paused
  } catch {
    return $true
  }
}

function Start-CdpRecovery {
  if ($externalCdp) {
    Write-WatchdogLog "external cdp endpoint unavailable; waiting for upstream tunnel: $cdpEndpoint"
    return
  }
  if (-not (Test-Path -LiteralPath $cdpBrowserScript)) {
    Write-WatchdogLog "cannot recover cdp: browser script missing $cdpBrowserScript"
    return
  }

  Write-WatchdogLog "cdp recovery started after $script:consecutiveCdpFailures consecutive failures"
  Stop-WorkersForCdpRecovery
  $arguments = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', $cdpBrowserScript,
    '-Port', '9223',
    '-ProfileDir', $cdpProfileDir,
    '-StartUrl', 'about:blank',
    '-UseSystemProxy',
    '-DisableExtensions',
    '-StartMinimized',
    '-EnsureOnly',
    '-CdpStartupTimeoutSeconds', '120'
  )

  try {
    $output = & powershell.exe @arguments 2>&1
    foreach ($line in @($output)) {
      Add-Content -LiteralPath $cdpRecoveryLog -Value ([string]$line) -Encoding UTF8
    }
  } catch {
    Write-WatchdogLog "cdp recovery failed: $($_.Exception.Message)"
  }
}

function Ensure-CdpBrowser {
  if (Test-CdpEndpoint) {
    if ($script:consecutiveCdpFailures -gt 0) {
      Write-WatchdogLog "cdp endpoint recovered after $script:consecutiveCdpFailures failed probes"
    }
    $script:consecutiveCdpFailures = 0
    return $true
  }

  $script:consecutiveCdpFailures += 1
  if ($script:consecutiveCdpFailures -lt $CdpFailureThreshold) {
    return $false
  }

  $now = Get-Date
  if (($now - $script:lastCdpRestartAt).TotalSeconds -lt $CdpRestartCooldownSeconds) {
    return $false
  }

  $script:lastCdpRestartAt = $now
  if ($externalCdp) {
    Stop-WorkersForCdpRecovery
    Write-WatchdogLog "external cdp endpoint remains unavailable; no local browser restart will be attempted"
    return $false
  }
  Start-CdpRecovery
  if (Test-CdpEndpoint) {
    $script:consecutiveCdpFailures = 0
    Write-WatchdogLog 'cdp endpoint healthy after recovery'
    return $true
  }
  return $false
}
