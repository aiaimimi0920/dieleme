function Test-CdpRuntime {
  param([switch]$AllowBlankPage)

  try {
    $version = Invoke-JsonRequest -Uri "$($CdpEndpoint.TrimEnd('/'))/json/version" -TimeoutSeconds 5
    if (-not (Get-PropertyValue -InputObject $version -Name 'webSocketDebuggerUrl')) {
      throw 'CDP version response has no webSocketDebuggerUrl'
    }
    $targets = @(Invoke-JsonRequest -Uri "$($CdpEndpoint.TrimEnd('/'))/json/list" -TimeoutSeconds 5)
    $pages = @($targets | Where-Object { $_.type -eq 'page' })
    $challengePages = @(
      $pages | Where-Object {
        $url = [string](Get-PropertyValue -InputObject $_ -Name 'url' -DefaultValue '')
        $url -match '/_____tmd_____/punish|[?&]x5secdata=|[?&]x5step=|sec\.taobao\.com/.*/punish|login\.taobao\.com'
      }
    )
    $loginPages = @(
      $pages | Where-Object {
        $url = [string](Get-PropertyValue -InputObject $_ -Name 'url' -DefaultValue '')
        $url -match '^https?://login\.taobao\.com/'
      }
    )
    $usablePages = @(
      $pages | Where-Object {
        $url = [string](Get-PropertyValue -InputObject $_ -Name 'url' -DefaultValue '')
        $url -and
        $url -notmatch '^(about:blank|edge:|chrome:|devtools:)' -and
        $url -notmatch '/_____tmd_____/punish|[?&]x5secdata=|[?&]x5step=|sec\.taobao\.com/.*/punish|login\.taobao\.com'
      }
    )
    if ($pages.Count -lt 1 -or (-not $AllowBlankPage -and $usablePages.Count -lt 1)) {
      throw 'CDP has no usable page targets'
    }
    return [pscustomobject]@{
      healthy = $true
      page_count = $pages.Count
      usable_page_count = $usablePages.Count
      challenge_page_count = $challengePages.Count
      login_page_count = $loginPages.Count
      error = $null
    }
  } catch {
    return [pscustomobject]@{
      healthy = $false
      page_count = 0
      usable_page_count = 0
      challenge_page_count = 0
      login_page_count = 0
      error = $_.Exception.Message
    }
  }
}

function Get-ApiStatus {
  return Invoke-JsonRequest -Uri "$($ApiBaseUrl.TrimEnd('/'))/status" -TimeoutSeconds 10
}

function Get-RequestEpoch {
  param($LastRequest)

  if ($null -eq $LastRequest) { return 0.0 }
  foreach ($name in @('timestamp', 'timestamp_ms', 'created_at_epoch', 'requested_at_epoch')) {
    if (-not ($LastRequest.PSObject.Properties.Name -contains $name)) { continue }
    $value = 0.0
    if (-not [double]::TryParse([string]$LastRequest.$name, [ref]$value)) { continue }
    if ($value -gt 100000000000) { $value = $value / 1000.0 }
    if ($value -gt 0) { return $value }
  }
  return 0.0
}

function Get-LocalSolverState {
  if (-not (Test-Path -LiteralPath $solverFallbackPath)) { return $null }
  try {
    return Get-Content -LiteralPath $solverFallbackPath -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch {
    return $null
  }
}

function Get-SolverChallengeActivity {
  param(
    $LocalSolverState,
    [string]$ChallengeId,
    [double]$Now
  )

  $matchingChallenge = [bool](
    $null -ne $LocalSolverState -and
    $ChallengeId -and
    [string](Get-PropertyValue -InputObject $LocalSolverState -Name 'challenge_id' -DefaultValue '') -eq $ChallengeId
  )
  $attempts = if ($matchingChallenge) {
    [int](Get-PropertyValue -InputObject $LocalSolverState -Name 'slider_attempts' -DefaultValue 0)
  } else {
    0
  }
  $attemptStartedAt = if ($matchingChallenge) {
    [double](Get-PropertyValue -InputObject $LocalSolverState -Name 'slider_attempt_started_at' -DefaultValue 0)
  } else {
    0.0
  }
  $lastProgressAt = if ($matchingChallenge) {
    [double](Get-PropertyValue -InputObject $LocalSolverState -Name 'slider_last_progress_at' -DefaultValue 0)
  } else {
    0.0
  }
  $cooldownUntil = if ($matchingChallenge) {
    [double](Get-PropertyValue -InputObject $LocalSolverState -Name 'solver_cooldown_until' -DefaultValue 0)
  } else {
    0.0
  }
  $progressEpoch = [Math]::Max($attemptStartedAt, $lastProgressAt)
  $progressAge = if ($progressEpoch -gt 0) { [Math]::Max(0, $Now - $progressEpoch) } else { -1.0 }
  $progressFresh = [bool](
    $matchingChallenge -and
    $attempts -lt [Math]::Max(1, $SolverAttemptThreshold) -and
    $progressEpoch -gt 0 -and
    $progressAge -le [Math]::Max(1, $SolverProgressGraceSeconds)
  )
  $cooldownActive = [bool]($matchingChallenge -and $cooldownUntil -gt $Now)
  return [pscustomobject]@{
    active = [bool]($progressFresh -or $cooldownActive)
    matching_challenge = $matchingChallenge
    attempts = $attempts
    progress_age_seconds = $progressAge
    cooldown_until = $cooldownUntil
    cooldown_active = $cooldownActive
  }
}
