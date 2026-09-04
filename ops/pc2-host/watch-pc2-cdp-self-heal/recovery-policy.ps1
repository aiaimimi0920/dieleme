function Invoke-CdpRecovery {
  param(
    [Parameter(Mandatory = $true)]$Status,
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][bool]$ResetMatchingChallenge
  )

  if (-not (Test-Path -LiteralPath $openAuthScript)) {
    throw "PC2 auth browser launcher is missing: $openAuthScript"
  }
  $solver = Get-PropertyValue -InputObject $Status -Name 'captcha_solver'
  $lastRequest = Get-PropertyValue -InputObject $solver -Name 'last_request'
  $targetUrl = ''
  if ($null -ne $lastRequest) {
    $reportedTarget = Get-PropertyValue -InputObject $lastRequest -Name 'target_url'
    $reportedUrl = Get-PropertyValue -InputObject $lastRequest -Name 'url'
    if ($reportedTarget) { $targetUrl = [string]$reportedTarget }
    elseif ($reportedUrl) { $targetUrl = [string]$reportedUrl }
  }
  $challengeId = [string](Get-PropertyValue -InputObject $solver -Name 'challenge_id' -DefaultValue '')

  Write-SelfHealLog -Event 'recovery_started' -Details @{
    reason = $Reason
    challenge_id = $challengeId
  }
  Stop-RecoveryProcesses
  Write-SelfHealLog -Event 'recovery_runtime_stopped' -Details @{ reason = $Reason }
  $taskStatus = $null
  $safeReset = [bool]($challengeId -and $ResetMatchingChallenge)
  $arguments = @(
      '-NoProfile',
      '-ExecutionPolicy', 'Bypass',
      '-File', $openAuthScript,
      '-ApiBaseUrl', $ApiBaseUrl,
      '-Port', '9223'
    )
    if ($safeReset) {
      $arguments += '-ResetToBlank'
    } elseif ($targetUrl) {
      $arguments += @('-RequestedUrl', $targetUrl)
    }
    $browserOutput = & powershell.exe @arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
      throw "Auth browser restart failed with exit code $LASTEXITCODE"
    }
    Write-SelfHealLog -Event 'recovery_browser_restarted' -Details @{ reason = $Reason }

    $deadline = (Get-Date).AddSeconds([Math]::Max(30, $CdpRecoveryTimeoutSeconds))
    $cdp = $null
    do {
      $cdp = Test-CdpRuntime -AllowBlankPage:$safeReset
      if ($cdp.healthy) { break }
      Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    if ($null -eq $cdp -or -not $cdp.healthy) {
      throw 'CDP did not expose a usable page target after forced browser restart'
    }
    if ($safeReset -and $cdp.challenge_page_count -gt 0) {
      throw 'CDP safe reset still exposes challenge page targets'
    }
    Write-SelfHealLog -Event 'recovery_cdp_ready' -Details @{
      reason = $Reason
      page_count = $cdp.page_count
      usable_page_count = $cdp.usable_page_count
      challenge_page_count = $cdp.challenge_page_count
      reset_to_blank = $safeReset
    }

  $reset = $null
  if ($challengeId -and $ResetMatchingChallenge) {
    Write-SelfHealLog -Event 'recovery_challenge_reset_started' -Details @{
      reason = $Reason
      challenge_id = $challengeId
    }
    $reset = Invoke-ChallengeReset -ChallengeId $challengeId
    if ($reset.cleared -eq $true -and (Test-Path -LiteralPath $solverFallbackPath)) {
      Remove-Item -LiteralPath $solverFallbackPath -Force
    }
    Write-SelfHealLog -Event 'recovery_challenge_reset_confirmed' -Details @{
      reason = $Reason
      challenge_id = $challengeId
    }
  }

  if ($null -ne $reset -and $reset.cleared -eq $true) {
    $confirmedStatus = Get-ApiStatus
    $confirmedSolver = Get-PropertyValue -InputObject $confirmedStatus -Name 'captcha_solver'
    $confirmedChallengeId = [string](Get-PropertyValue -InputObject $confirmedSolver -Name 'challenge_id' -DefaultValue '')
    if (
      (Get-PropertyValue -InputObject $confirmedStatus -Name 'paused' -DefaultValue $true) -eq $true -or
      $confirmedChallengeId
    ) {
      throw 'NAS challenge marker remained active after matching reset'
    }
  }

  $taskStatus = Start-RecoveryTasks
  if ($null -eq $taskStatus -or -not $taskStatus.healthy) {
    throw 'PC2 solver or worker watchdog did not restart after CDP recovery'
  }
  $verifiedCdp = Test-CdpRuntime -AllowBlankPage:$safeReset
  if (-not $verifiedCdp.healthy) {
    throw "CDP became unhealthy immediately after task restart: $($verifiedCdp.error)"
  }
  if ($safeReset -and $verifiedCdp.challenge_page_count -gt 0) {
    throw 'CDP challenge page reappeared immediately after runtime restart'
  }
  Write-SelfHealLog -Event 'recovery_runtime_restarted' -Details @{
    reason = $Reason
    solver_task_state = $taskStatus.solver_task_state
    worker_task_state = $taskStatus.worker_task_state
    launch_modes = $taskStatus.launch_modes
  }
  Write-SelfHealLog -Event 'recovery_succeeded' -Details @{
    reason = $Reason
    challenge_id = $challengeId
    page_count = $verifiedCdp.page_count
    usable_page_count = $verifiedCdp.usable_page_count
    challenge_page_count = $verifiedCdp.challenge_page_count
    reset_to_blank = $safeReset
    challenge_reset_allowed = $ResetMatchingChallenge
    challenge_cleared = ($null -ne $reset -and $reset.cleared -eq $true)
    challenge_stale = $false
    solver_task_state = $taskStatus.solver_task_state
    worker_task_state = $taskStatus.worker_task_state
    launch_modes = $taskStatus.launch_modes
  }
  return $true
}

function Invoke-SelfHealCheck {
  param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$State)

  $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $status = Get-ApiStatus
  $solver = Get-PropertyValue -InputObject $status -Name 'captcha_solver'
  $challengeId = [string](Get-PropertyValue -InputObject $solver -Name 'challenge_id' -DefaultValue '')
  $lastRequest = Get-PropertyValue -InputObject $solver -Name 'last_request'
  $requestNode = [string](Get-PropertyValue -InputObject $lastRequest -Name 'node_id' -DefaultValue '')
  $challengeOwnedByPc2 = [bool](
    (Get-PropertyValue -InputObject $status -Name 'paused' -DefaultValue $true) -eq $true -and
    $null -ne $solver -and
    (Get-PropertyValue -InputObject $solver -Name 'manual_only' -DefaultValue $true) -ne $true -and
    $requestNode.Trim().ToLowerInvariant() -eq 'pc2' -and
    $challengeId
  )

  if ($challengeId -ne [string]$State.observed_challenge_id) {
    $State.observed_challenge_id = $challengeId
    $reportedEpoch = Get-RequestEpoch -LastRequest $lastRequest
    $State.challenge_first_seen_epoch = if ($reportedEpoch -gt 0 -and $reportedEpoch -le $now) {
      $reportedEpoch
    } else {
      [double]$now
    }
  } elseif (-not $challengeId) {
    $State.challenge_first_seen_epoch = 0.0
  }

  # A deliberate safe reset leaves one about:blank page. The transport is
  # healthy in that state; stale/challenge ownership is evaluated separately.
  $cdp = Test-CdpRuntime -AllowBlankPage
  if ($cdp.healthy) {
    $State.consecutive_cdp_failures = 0
  } else {
    $State.consecutive_cdp_failures = [int]$State.consecutive_cdp_failures + 1
  }

  $localSolverState = Get-LocalSolverState
  $authCompletePending = [bool](
    $null -ne $localSolverState -and
    (Get-PropertyValue -InputObject $localSolverState -Name 'auth_complete_pending' -DefaultValue $false) -eq $true -and
    [string](Get-PropertyValue -InputObject $localSolverState -Name 'challenge_id' -DefaultValue '') -eq $challengeId
  )
  $challengeAge = if ($challengeId -and [double]$State.challenge_first_seen_epoch -gt 0) {
    [Math]::Max(0, $now - [double]$State.challenge_first_seen_epoch)
  } else {
    0
  }
  $cdpFailure = [int]$State.consecutive_cdp_failures -ge [Math]::Max(1, $CdpFailureThreshold)
  $stalePc2ChallengeCandidate = [bool](
    $challengeOwnedByPc2 -and
    $challengeAge -ge [Math]::Max(1, $StaleChallengeSeconds)
  )
  $solverActivity = Get-SolverChallengeActivity `
    -LocalSolverState $localSolverState `
    -ChallengeId $challengeId `
    -Now $now
  $manualLoginDeferred = [bool](
    $stalePc2ChallengeCandidate -and
    -not $authCompletePending -and
    [int](Get-PropertyValue -InputObject $cdp -Name 'login_page_count' -DefaultValue 0) -gt 0
  )
  $staleChallengeDeferred = [bool](
    $stalePc2ChallengeCandidate -and
    -not $authCompletePending -and
    ($solverActivity.active -or $manualLoginDeferred)
  )
  $stalePc2Challenge = [bool]($stalePc2ChallengeCandidate -and -not $staleChallengeDeferred)
  $reason = if ($ForceRecovery) {
    'forced'
  } elseif ($cdpFailure) {
    'cdp_unhealthy'
  } elseif ($stalePc2Challenge) {
    if ($authCompletePending) { 'stuck_auth_completion' } else { 'stale_pc2_challenge' }
  } else {
    ''
  }

  if (-not $reason) {
    if ($cdp.healthy -and -not (Test-RecoveryTasksRunning)) {
      $taskStatus = Start-RecoveryTasks
      $State.last_result = if ($taskStatus.healthy) { 'runtime_restored' } else { 'runtime_restore_failed' }
    } else {
      $State.last_result = if ($manualLoginDeferred) {
        'manual_login_deferred'
      } elseif ($staleChallengeDeferred) {
        'solver_progress_deferred'
      } else {
        'healthy'
      }
    }
    if ($manualLoginDeferred) {
      Write-SelfHealLog -Event 'stale_recovery_deferred_for_manual_login' -Details @{
        challenge_id = $challengeId
        challenge_age_seconds = $challengeAge
        login_page_count = $cdp.login_page_count
      }
    } elseif ($staleChallengeDeferred) {
      Write-SelfHealLog -Event 'stale_recovery_deferred_for_solver' -Details @{
        challenge_id = $challengeId
        challenge_age_seconds = $challengeAge
        slider_attempts = $solverActivity.attempts
        progress_age_seconds = $solverActivity.progress_age_seconds
        cooldown_active = $solverActivity.cooldown_active
        cooldown_until = $solverActivity.cooldown_until
      }
    }
    Write-SelfHealState -State $State
    return
  }
  $sinceRecovery = $now - [double]$State.last_recovery_epoch
  if (-not $ForceRecovery -and $sinceRecovery -lt [Math]::Max(0, $RestartCooldownSeconds)) {
    if ($cdp.healthy -and -not (Test-RecoveryTasksRunning)) {
      $taskStatus = Start-RecoveryTasks
      $State.last_result = if ($taskStatus.healthy) { 'runtime_restored_during_cooldown' } else { 'runtime_restore_failed' }
    } else {
      $State.last_result = 'restart_cooldown'
    }
    Write-SelfHealState -State $State
    return
  }

  $State.last_recovery_epoch = [double]$now
  $State.last_result = 'recovering'
  Write-SelfHealState -State $State
  try {
    $recovered = Invoke-CdpRecovery `
      -Status $status `
      -Reason $reason `
      -ResetMatchingChallenge:$challengeOwnedByPc2
    if ($recovered) {
      $State.consecutive_cdp_failures = 0
      $State.observed_challenge_id = ''
      $State.challenge_first_seen_epoch = 0.0
      $State.recovery_count = [int]$State.recovery_count + 1
      $State.last_result = 'recovered'
    }
  } catch {
    $recoveryError = $_.Exception.Message
    $runtimeRestored = Test-RecoveryTasksRunning
    if (-not $runtimeRestored) {
      try {
        $rollbackStatus = Start-RecoveryTasks
        $runtimeRestored = [bool]($null -ne $rollbackStatus -and $rollbackStatus.healthy)
        Write-SelfHealLog `
          -Event $(if ($runtimeRestored) { 'recovery_runtime_rollback_succeeded' } else { 'recovery_runtime_rollback_failed' }) `
          -Details @{
            reason = $reason
            solver_task_state = $rollbackStatus.solver_task_state
            worker_task_state = $rollbackStatus.worker_task_state
            solver_process_running = $rollbackStatus.solver_process_running
            worker_process_running = $rollbackStatus.worker_process_running
            launch_modes = $rollbackStatus.launch_modes
            errors = $rollbackStatus.errors
          }
      } catch {
        $runtimeRestored = $false
        Write-SelfHealLog -Event 'recovery_runtime_rollback_failed' -Details @{
          reason = $reason
          error = $_.Exception.Message
        }
      }
    }
    $State.last_result = 'recovery_failed'
    Write-SelfHealLog -Event 'recovery_failed' -Details @{
      reason = $reason
      error = $recoveryError
      runtime_restored = $runtimeRestored
    }
  }
  Write-SelfHealState -State $State
}
