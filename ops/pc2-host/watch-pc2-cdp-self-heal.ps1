param(
  [string]$ApiBaseUrl = 'http://192.168.15.200:8001/api',
  [string]$CdpEndpoint = 'http://127.0.0.1:9223',
  [int]$PollSeconds = 60,
  [int]$CdpFailureThreshold = 3,
  [int]$StaleChallengeSeconds = 300,
  [int]$RestartCooldownSeconds = 180,
  [int]$SolverAttemptThreshold = 10,
  [int]$SolverProgressGraceSeconds = 180,
  [int]$CdpRecoveryTimeoutSeconds = 240,
  [switch]$Once,
  [switch]$ForceRecovery
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = 'C:\fapaifang-worker'
$logDir = Join-Path $root 'logs\codex-pc2-real'
$stateDir = Join-Path $root 'state'
$logPath = Join-Path $logDir 'cdp-self-heal.log'
$statePath = Join-Path $stateDir 'cdp-self-heal-state.json'
$solverFallbackPath = Join-Path $root 'src\.codex-temp\bridge-control\solver-fallback-state.json'
$openAuthScript = Join-Path $root 'ops\open-auth-latest.ps1'
$solverTaskName = 'FapaiSolver'
$workerTaskName = 'FapaiPc2RealWorkerLauncher'

New-Item -ItemType Directory -Force -Path $logDir, $stateDir | Out-Null

function Write-SelfHealLog {
  param(
    [Parameter(Mandatory = $true)][string]$Event,
    [hashtable]$Details = @{}
  )

  $payload = [ordered]@{
    ts = (Get-Date).ToString('s')
    event = $Event
  }
  foreach ($key in $Details.Keys) {
    $payload[$key] = $Details[$key]
  }
  Add-Content -LiteralPath $logPath -Value ($payload | ConvertTo-Json -Compress -Depth 6) -Encoding UTF8
}

function New-SelfHealState {
  return [ordered]@{
    consecutive_cdp_failures = 0
    observed_challenge_id = ''
    challenge_first_seen_epoch = 0.0
    last_recovery_epoch = 0.0
    recovery_count = 0
    last_result = 'boot'
  }
}

function Read-SelfHealState {
  $state = New-SelfHealState
  if (-not (Test-Path -LiteralPath $statePath)) {
    return $state
  }
  try {
    $stored = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($key in @($state.Keys)) {
      if ($stored.PSObject.Properties.Name -contains $key) {
        $state[$key] = $stored.$key
      }
    }
  } catch {
    Write-SelfHealLog -Event 'state_read_failed' -Details @{ error = $_.Exception.Message }
  }
  return $state
}

function Write-SelfHealState {
  param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$State)

  $temporary = "$statePath.$PID.tmp"
  $json = $State | ConvertTo-Json -Compress -Depth 5
  [IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding($false)))
  Move-Item -LiteralPath $temporary -Destination $statePath -Force
}

function Invoke-JsonRequest {
  param(
    [Parameter(Mandatory = $true)][string]$Uri,
    [ValidateSet('GET', 'POST')][string]$Method = 'GET',
    [object]$Body = $null,
    [int]$TimeoutSeconds = 5
  )

  $request = [System.Net.HttpWebRequest]::Create($Uri)
  $request.Proxy = $null
  $request.Method = $Method
  $request.Timeout = [Math]::Max($TimeoutSeconds, 1) * 1000
  $request.ReadWriteTimeout = [Math]::Max($TimeoutSeconds, 1) * 1000
  $request.KeepAlive = $false
  if ($Method -eq 'POST') {
    $request.ContentType = 'application/json; charset=utf-8'
    $json = if ($null -eq $Body) { '{}' } else { $Body | ConvertTo-Json -Compress -Depth 6 }
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    $request.ContentLength = $bytes.Length
    $stream = $request.GetRequestStream()
    try {
      $stream.Write($bytes, 0, $bytes.Length)
    } finally {
      $stream.Dispose()
    }
  }

  $response = $null
  $reader = $null
  try {
    $response = [System.Net.HttpWebResponse]$request.GetResponse()
    $reader = New-Object IO.StreamReader($response.GetResponseStream(), [Text.Encoding]::UTF8)
    $content = $reader.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($content)) {
      throw "Empty JSON response from $Uri"
    }
    $parsed = $content | ConvertFrom-Json
    if ($parsed -is [System.Array]) {
      foreach ($item in $parsed) {
        Write-Output $item
      }
      return
    }
    return $parsed
  } finally {
    if ($null -ne $reader) { $reader.Dispose() }
    if ($null -ne $response) { $response.Dispose() }
  }
}

function Get-PropertyValue {
  param(
    $InputObject,
    [Parameter(Mandatory = $true)][string]$Name,
    $DefaultValue = $null
  )

  if ($null -eq $InputObject) { return $DefaultValue }
  $property = $InputObject.PSObject.Properties[$Name]
  if ($null -eq $property) { return $DefaultValue }
  return $property.Value
}

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

function Stop-RecoveryProcesses {
  $processes = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object {
        ($_.Name -in 'python.exe', 'pythonw.exe' -and (
          $_.CommandLine -match 'pc2_local_solver.py' -or
          ($_.CommandLine -match 'tools\\(seed_collector|detail_worker)\.py' -and
          $_.CommandLine -notmatch '--analysis-only')
        )) -or
        ($_.Name -eq 'powershell.exe' -and $_.CommandLine -match 'start-host-direct-(seed|detail)-worker|launch-host-direct-workers\.ps1|start-pc2-local-solver\.ps1')
      }
  )
  foreach ($process in ($processes | Sort-Object ProcessId -Descending)) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Seconds 2
  foreach ($taskName in @($workerTaskName, $solverTaskName)) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  }
}

function Get-RecoveryRoleProcess {
  param([ValidateSet('solver', 'worker')][string]$Role)

  $pattern = if ($Role -eq 'solver') {
    'pc2_local_solver\.py'
  } else {
    'launch-host-direct-workers\.ps1'
  }
  return @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -match $pattern } |
      Sort-Object ProcessId
  ) | Select-Object -First 1
}

function Start-RecoveryTasks {
  $startErrors = New-Object System.Collections.Generic.List[string]
  $launchModes = [ordered]@{}
  $roles = @(
    [pscustomobject]@{ task_name = $solverTaskName; role = 'solver' },
    [pscustomobject]@{ task_name = $workerTaskName; role = 'worker' }
  )
  foreach ($entry in $roles) {
    $taskName = [string]$entry.task_name
    $role = [string]$entry.role
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
      $startErrors.Add("missing task: $taskName")
      continue
    }
    if ($null -ne (Get-RecoveryRoleProcess -Role $role)) {
      $launchModes[$role] = 'existing_process'
      continue
    }

    if ([string]$task.State -ne 'Disabled') {
      try {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
        # The worker launcher imports the environment and probes NAS/CDP before
        # its long-running process becomes visible.  Three seconds was too
        # short and caused the direct-action fallback to start a second launcher
        # (and duplicate every worker).  Wait for the scheduled instance first.
        $scheduledDeadline = (Get-Date).AddSeconds(20)
      while (
          $null -eq (Get-RecoveryRoleProcess -Role $role) -and
          (Get-Date) -lt $scheduledDeadline
        ) {
          Start-Sleep -Seconds 1
        }
      } catch {
        $launchModes[$role] = 'scheduled_task_rejected'
      }
    }

    # A scheduled task can remain in the Running state while its active-session
    # wrapper is still importing Python/PowerShell modules.  Never start the
    # same action directly while that task is running: doing so races the task
    # and creates a second launcher/worker set.  Direct fallback is reserved for
    # a task that failed to enter Running at all.
    $taskAfterStart = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    $taskIsRunning = $null -ne $taskAfterStart -and [string]$taskAfterStart.State -eq 'Running'
    if ($null -eq (Get-RecoveryRoleProcess -Role $role) -and -not $taskIsRunning) {
      $action = @($task.Actions)[0]
      $workingDirectory = if ([string]::IsNullOrWhiteSpace([string]$action.WorkingDirectory)) {
        $root
      } else {
        [string]$action.WorkingDirectory
      }
      try {
        Start-Process `
          -FilePath ([string]$action.Execute) `
          -ArgumentList ([string]$action.Arguments) `
          -WorkingDirectory $workingDirectory `
          -WindowStyle Hidden `
          -ErrorAction Stop | Out-Null
        $launchModes[$role] = 'direct_action'
      } catch {
        $startErrors.Add("failed to launch ${taskName} action directly: $($_.Exception.Message)")
        continue
      }
      $deadline = (Get-Date).AddSeconds(15)
      while ($null -eq (Get-RecoveryRoleProcess -Role $role) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
      }
    }
    if ($null -eq (Get-RecoveryRoleProcess -Role $role)) {
      $startErrors.Add("runtime process did not remain running: ${taskName}/${role}")
    }
  }
  $solverTask = Get-ScheduledTask -TaskName $solverTaskName -ErrorAction SilentlyContinue
  $workerTask = Get-ScheduledTask -TaskName $workerTaskName -ErrorAction SilentlyContinue
  $solverState = if ($null -ne $solverTask) { [string]$solverTask.State } else { 'Missing' }
  $workerState = if ($null -ne $workerTask) { [string]$workerTask.State } else { 'Missing' }
  $solverRunning = $null -ne (Get-RecoveryRoleProcess -Role 'solver')
  $workerRunning = $null -ne (Get-RecoveryRoleProcess -Role 'worker')
  $healthy = $startErrors.Count -eq 0 -and $solverRunning -and $workerRunning
  if (-not $healthy) {
    Write-SelfHealLog -Event 'runtime_restart_failed' -Details @{
      solver_task_state = $solverState
      worker_task_state = $workerState
      solver_process_running = $solverRunning
      worker_process_running = $workerRunning
      launch_modes = $launchModes
      errors = @($startErrors)
    }
  }
  return [pscustomobject]@{
    healthy = $healthy
    solver_task_state = $solverState
    worker_task_state = $workerState
    solver_process_running = $solverRunning
    worker_process_running = $workerRunning
    launch_modes = $launchModes
    errors = @($startErrors)
  }
}

function Test-RecoveryTasksRunning {
  return (
    $null -ne (Get-RecoveryRoleProcess -Role 'solver') -and
    $null -ne (Get-RecoveryRoleProcess -Role 'worker')
  )
}

function Invoke-ChallengeReset {
  param([Parameter(Mandatory = $true)][string]$ChallengeId)

  $requestId = 'pc2-cdp-self-heal-{0}-{1}' -f `
    ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()),
    ([guid]::NewGuid().ToString('N'))
  $body = [ordered]@{
    source = 'pc2_local_solver'
    resume_request_id = $requestId
    challenge_id = $ChallengeId
  }
  $result = Invoke-JsonRequest `
    -Uri "$($ApiBaseUrl.TrimEnd('/'))/collection/auth/resume_after_cooldown" `
    -Method POST `
    -Body $body `
    -TimeoutSeconds 20
  if ((Get-PropertyValue -InputObject $result -Name 'stale_challenge' -DefaultValue $false) -eq $true) {
    throw 'NAS challenge changed while PC2 recovery was in progress'
  }
  if (
    (Get-PropertyValue -InputObject $result -Name 'ok' -DefaultValue $false) -ne $true -or
    (Get-PropertyValue -InputObject $result -Name 'auth_state_confirmed' -DefaultValue $false) -ne $true -or
    (Get-PropertyValue -InputObject $result -Name 'paused' -DefaultValue $true) -ne $false
  ) {
    throw 'NAS did not confirm stale challenge reset'
  }
  return [pscustomobject]@{ cleared = $true; stale = $false; request_id = $requestId }
}

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

$mutex = [System.Threading.Mutex]::new($false, 'FapaiPc2CdpSelfHeal')
$lockAcquired = $false
try {
  try {
    $lockAcquired = $mutex.WaitOne([TimeSpan]::FromSeconds(5))
  } catch [System.Threading.AbandonedMutexException] {
    $lockAcquired = $true
  }
  if (-not $lockAcquired) {
    Write-SelfHealLog -Event 'duplicate_instance_skipped'
    exit 0
  }

  $state = Read-SelfHealState
  Write-SelfHealLog -Event 'watchdog_booted' -Details @{
    poll_seconds = $PollSeconds
    cdp_failure_threshold = $CdpFailureThreshold
    stale_challenge_seconds = $StaleChallengeSeconds
    restart_cooldown_seconds = $RestartCooldownSeconds
    solver_attempt_threshold = $SolverAttemptThreshold
    solver_progress_grace_seconds = $SolverProgressGraceSeconds
    cdp_recovery_timeout_seconds = $CdpRecoveryTimeoutSeconds
  }
  while ($true) {
    try {
      Invoke-SelfHealCheck -State $state
    } catch {
      $state.last_result = 'check_failed'
      Write-SelfHealLog -Event 'check_failed' -Details @{ error = $_.Exception.Message }
      Write-SelfHealState -State $state
    }
    if ($Once) { break }
    Start-Sleep -Seconds ([Math]::Max(5, $PollSeconds))
  }
} finally {
  if ($lockAcquired) {
    try { $mutex.ReleaseMutex() } catch {}
  }
  $mutex.Dispose()
}
