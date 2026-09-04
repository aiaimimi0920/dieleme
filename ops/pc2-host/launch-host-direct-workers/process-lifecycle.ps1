function Get-WorkerProcesses {
  param([Parameter(Mandatory = $true)]$Spec)

  $scriptPattern = [regex]::Escape([string]$Spec.ScriptPattern)
  $workerIdPattern = (
    '--worker-id\s+["'']?' +
    [regex]::Escape([string]$Spec.WorkerId) +
    '["'']?(?=\s|$)'
  )
  return @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object {
        $_.Name -eq 'python.exe' -and
        $_.CommandLine -match $scriptPattern -and
        $_.CommandLine -match $workerIdPattern
      }
  )
}

function Get-RootWorkerProcesses {
  param([Parameter(Mandatory = $true)][object[]]$Processes)

  $ids = @{}
  foreach ($process in $Processes) {
    $ids[[int]$process.ProcessId] = $true
  }
  return @(
    $Processes |
      Where-Object { -not $ids.ContainsKey([int]$_.ParentProcessId) } |
      Sort-Object CreationDate
  )
}

function Get-ProcessAgeSeconds {
  param([Parameter(Mandatory = $true)]$Process)

  try {
    $startedAt = [datetime]$Process.CreationDate
    return [int]((Get-Date) - $startedAt).TotalSeconds
  } catch {
    return [int]::MaxValue
  }
}

function Test-SummaryFresh {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][int]$MaxAgeSeconds
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    return $false
  }
  try {
    $summary = Get-Item -LiteralPath $Path -ErrorAction Stop
    return ((Get-Date) - $summary.LastWriteTime).TotalSeconds -le $MaxAgeSeconds
  } catch {
    return $false
  }
}

function Get-ChildProcessIds {
  param(
    [Parameter(Mandatory = $true)][int]$ParentProcessId,
    [Parameter(Mandatory = $true)][object[]]$AllProcesses
  )

  $queue = New-Object System.Collections.Generic.Queue[int]
  $children = New-Object System.Collections.Generic.List[int]
  $queue.Enqueue($ParentProcessId)
  while ($queue.Count -gt 0) {
    $currentParentId = $queue.Dequeue()
    foreach ($process in $AllProcesses) {
      if ([int]$process.ParentProcessId -ne $currentParentId) {
        continue
      }
      $childId = [int]$process.ProcessId
      if ($children.Contains($childId)) {
        continue
      }
      $children.Add($childId) | Out-Null
      $queue.Enqueue($childId)
    }
  }
  return @($children)
}

function Stop-WorkerProcessTree {
  param(
    [Parameter(Mandatory = $true)]$Spec,
    [Parameter(Mandatory = $true)]$RootProcess,
    [Parameter(Mandatory = $true)][string]$Reason
  )

  $allProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
  $rootId = [int]$RootProcess.ProcessId
  $processIds = @($rootId) + @(Get-ChildProcessIds -ParentProcessId $rootId -AllProcesses $allProcesses)
  foreach ($processId in ($processIds | Sort-Object -Descending -Unique)) {
    try {
      Stop-Process -Id $processId -Force -ErrorAction Stop
    } catch {
    }
  }
  Write-WatchdogLog "stopped $($Spec.Name): $Reason (root pid $rootId)"
}

function Stop-WorkersForCdpRecovery {
  foreach ($spec in $workerSpecs) {
    if (-not $spec.RequiresCdp) {
      continue
    }
    $processes = @(Get-WorkerProcesses -Spec $spec)
    if ($processes.Count -eq 0) {
      continue
    }
    $roots = @(Get-RootWorkerProcesses -Processes $processes)
    if ($roots.Count -eq 0) {
      $roots = @($processes | Sort-Object CreationDate | Select-Object -First 1)
    }
    foreach ($rootProcess in $roots) {
      Stop-WorkerProcessTree -Spec $spec -RootProcess $rootProcess -Reason "cdp recovery"
    }
  }
}

function Stop-WorkersForCollectionPause {
  param(
    [Parameter(Mandatory = $true)][bool]$SeedPaused,
    [Parameter(Mandatory = $true)][bool]$DetailPaused
  )
  foreach ($spec in $workerSpecs) {
    if (-not $spec.StopsWhenCollectionPaused) {
      continue
    }
    $scopePaused = if ([string]$spec.Name -eq 'seed') {
      $SeedPaused
    } else {
      $DetailPaused
    }
    if (-not $scopePaused) {
      continue
    }
    $processes = @(Get-WorkerProcesses -Spec $spec)
    if ($processes.Count -eq 0) {
      continue
    }
    $roots = @(Get-RootWorkerProcesses -Processes $processes)
    if ($roots.Count -eq 0) {
      $roots = @($processes | Sort-Object CreationDate | Select-Object -First 1)
    }
    foreach ($rootProcess in $roots) {
      Stop-WorkerProcessTree -Spec $spec -RootProcess $rootProcess -Reason "collection paused"
    }
  }
}

function Start-WorkerDetached {
  param([Parameter(Mandatory = $true)]$Spec)

  if (-not (Test-Path -LiteralPath $Spec.ScriptPath)) {
    Write-WatchdogLog "cannot start $($Spec.Name): script missing $($Spec.ScriptPath)"
    return
  }

  $quoteNativeArgument = {
    param([Parameter(Mandatory = $true)][string]$Value)
    return '"{0}"' -f $Value.Replace('"', '\"')
  }
  $scriptPathText = & $quoteNativeArgument ([string]$Spec.ScriptPath)
  $stdoutPathText = & $quoteNativeArgument ([string]$Spec.StdoutPath)
  $stderrPathText = & $quoteNativeArgument ([string]$Spec.StderrPath)
  $scriptArgumentText = ''
  if ($Spec.PSObject.Properties.Name -contains 'ScriptArguments') {
    $scriptArgumentText = @(
      $Spec.ScriptArguments |
        ForEach-Object { & $quoteNativeArgument ([string]$_) }
    ) -join ' '
  }
  $commandLine = 'cmd.exe /d /c powershell.exe -WindowStyle Hidden -NonInteractive -NoProfile -ExecutionPolicy Bypass -File {0} {1} 1>>{2} 2>>{3}' -f `
    $scriptPathText,
    $scriptArgumentText,
    $stdoutPathText,
    $stderrPathText
  $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $commandLine }
  if ([int]$created.ReturnValue -ne 0) {
    Write-WatchdogLog "failed to start $($Spec.Name): Win32_Process.Create returned $($created.ReturnValue)"
    return
  }
  Write-WatchdogLog "started $($Spec.Name) via detached Win32_Process pid $($created.ProcessId)"
}
