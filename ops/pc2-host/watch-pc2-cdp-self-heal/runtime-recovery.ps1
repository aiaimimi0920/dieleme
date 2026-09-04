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
