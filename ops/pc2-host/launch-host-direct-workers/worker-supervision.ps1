function Ensure-Worker {
  param([Parameter(Mandatory = $true)]$Spec)

  $processes = @(Get-WorkerProcesses -Spec $Spec)
  if ($Spec.IsAnalysis) {
    $summaryState = Get-WorkerSummaryState -Spec $Spec
    if (Test-NewAnalysisBackendUnavailableSummary -Spec $Spec -Summary $summaryState) {
      if ($processes.Count -gt 0) {
        $roots = @(Get-RootWorkerProcesses -Processes $processes)
        if ($roots.Count -eq 0) {
          $roots = @($processes | Sort-Object CreationDate | Select-Object -First 1)
        }
        foreach ($rootProcess in $roots) {
          Stop-WorkerProcessTree -Spec $Spec -RootProcess $rootProcess -Reason 'analysis backend unavailable'
        }
      }
      Enter-AnalysisBackendCooldown -Spec $Spec
      return
    }
    if (Test-AnalysisBackendCooldown -Spec $Spec) {
      if ($processes.Count -gt 0) {
        $roots = @(Get-RootWorkerProcesses -Processes $processes)
        if ($roots.Count -eq 0) {
          $roots = @($processes | Sort-Object CreationDate | Select-Object -First 1)
        }
        foreach ($rootProcess in $roots) {
          Stop-WorkerProcessTree -Spec $Spec -RootProcess $rootProcess -Reason 'analysis backend cooldown'
        }
      }
      return
    }
  }
  if ($processes.Count -eq 0) {
    Start-WorkerDetached -Spec $Spec
    return
  }

  $roots = @(Get-RootWorkerProcesses -Processes $processes)
  if ($roots.Count -eq 0) {
    $roots = @($processes | Sort-Object CreationDate | Select-Object -First 1)
  }
  if ($roots.Count -gt 1) {
    $keeper = $roots[0]
    foreach ($duplicate in @($roots | Select-Object -Skip 1)) {
      Stop-WorkerProcessTree `
        -Spec $Spec `
        -RootProcess $duplicate `
        -Reason "duplicate worker root; keeping pid $($keeper.ProcessId)"
    }
    $roots = @($keeper)
  }
  $root = $roots[0]
  if ((Get-ProcessAgeSeconds -Process $root) -lt [int]$Spec.StartupGraceSeconds) {
    return
  }
  if (Test-SummaryFresh -Path $Spec.SummaryPath -MaxAgeSeconds $Spec.SummaryMaxAgeSeconds) {
    return
  }

  foreach ($rootProcess in $roots) {
    Stop-WorkerProcessTree -Spec $Spec -RootProcess $rootProcess -Reason "summary stale: $($Spec.SummaryPath)"
  }
  Start-WorkerDetached -Spec $Spec
}
