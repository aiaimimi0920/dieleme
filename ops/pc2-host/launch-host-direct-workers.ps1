param(
  [int]$PollSeconds = 30,
  [int]$SeedSummaryMaxAgeSeconds = 240,
  [int]$DetailSummaryMaxAgeSeconds = 300,
  [int]$AnalysisSummaryMaxAgeSeconds = 600,
  [int]$StartupGraceSeconds = 120,
  [int]$CdpFailureThreshold = 3,
  [int]$CdpRestartCooldownSeconds = 300,
  [int]$AnalysisBackendRetryCooldownSeconds = 900,
  [int]$DetailWorkerCount = 0,
  [int]$AnalysisWorkerCount = 0,
  [switch]$Once
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = 'C:\fapaifang-worker'
$envFile = Join-Path $root 'env.worker.local'
if (Test-Path -LiteralPath $envFile) {
  Get-Content -LiteralPath $envFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    $separator = $line.IndexOf('=')
    if ($separator -lt 1) { return }
    $name = $line.Substring(0, $separator).Trim()
    $value = $line.Substring($separator + 1)
    [Environment]::SetEnvironmentVariable($name, $value, 'Process')
  }
}
$logDir = Join-Path $root 'logs\codex-pc2-real'
$sharedRoot = if ($env:FAPAI_NAS_SHARE_ROOT) {
  $env:FAPAI_NAS_SHARE_ROOT
} else {
  '\\192.168.15.200\home\project\project\FPFData'
}
$watchdogLog = Join-Path $logDir 'worker-watchdog.log'
$cdpRecoveryLog = Join-Path $logDir 'cdp-recovery.log'
$cdpEndpoint = if ($env:FAPAI_CDP_ENDPOINT) {
  $env:FAPAI_CDP_ENDPOINT
} else {
  'http://127.0.0.1:9223'
}
$externalCdp = $env:FAPAI_CDP_EXTERNAL -eq '1'
$cookieSnapshotPreferred = $env:FAPAI_COOKIE_SNAPSHOT_PREFER -eq '1'
$collectorRequiresCdp = -not ($externalCdp -and $cookieSnapshotPreferred)
$apiBaseUrl = if ($env:FAPAI_API_BASE_URL) {
  $env:FAPAI_API_BASE_URL.TrimEnd('/')
} else {
  'http://192.168.15.200:8001/api'
}
$cdpProfileDir = 'C:\Users\Public\nas_home\AI\FPFData\edge-cdp-profile-pc2'
$cdpBrowserScript = Join-Path $root 'src\scripts\start-taobao-cdp-browser.ps1'
$consecutiveCdpFailures = 0
$lastCdpRestartAt = [datetime]::MinValue
$analysisBackendRetryAt = @{}
$analysisUnavailableSummaryWriteTicks = @{}
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$workerSpecs = @(
  [pscustomobject]@{
    Name = 'seed'
    WorkerId = 'pc2-real-seed-1'
    ScriptPattern = 'tools\seed_collector.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-seed-worker.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\seed_collector\seed_collector_summary.json'
    SummaryMaxAgeSeconds = $SeedSummaryMaxAgeSeconds
    StartupGraceSeconds = $StartupGraceSeconds
    RequiresCdp = $collectorRequiresCdp
    IsAnalysis = $false
    # seed_collector performs scope-aware pause handling and can keep scanning
    # while a detail-page challenge waits for manual confirmation.
    StopsWhenCollectionPaused = $false
    StdoutPath = Join-Path $logDir 'seed.out.log'
    StderrPath = Join-Path $logDir 'seed.err.log'
  },
  [pscustomobject]@{
    Name = 'detail-1'
    WorkerId = 'pc2-real-detail-1'
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-detail-worker.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\detail_worker\detail_worker_summary.json'
    SummaryMaxAgeSeconds = $DetailSummaryMaxAgeSeconds
    StartupGraceSeconds = $StartupGraceSeconds
    RequiresCdp = $collectorRequiresCdp
    IsAnalysis = $false
    StopsWhenCollectionPaused = $true
    StdoutPath = Join-Path $logDir 'detail1.out.log'
    StderrPath = Join-Path $logDir 'detail1.err.log'
  },
  [pscustomobject]@{
    Name = 'detail-2'
    WorkerId = 'pc2-real-detail-2'
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-detail-worker-2.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\detail_worker_2\detail_worker_summary.json'
    SummaryMaxAgeSeconds = $DetailSummaryMaxAgeSeconds
    StartupGraceSeconds = $StartupGraceSeconds
    RequiresCdp = $collectorRequiresCdp
    IsAnalysis = $false
    StopsWhenCollectionPaused = $true
    StdoutPath = Join-Path $logDir 'detail2.out.log'
    StderrPath = Join-Path $logDir 'detail2.err.log'
  },
  [pscustomobject]@{
    Name = 'analysis-1'
    WorkerId = 'pc2-real-analysis-1'
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-analysis-worker.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\detail_analysis_worker\detail_worker_summary.json'
    SummaryMaxAgeSeconds = $AnalysisSummaryMaxAgeSeconds
    StartupGraceSeconds = [Math]::Max($StartupGraceSeconds, 420)
    RequiresCdp = $false
    IsAnalysis = $true
    StopsWhenCollectionPaused = $false
    StdoutPath = Join-Path $logDir 'analysis1.out.log'
    StderrPath = Join-Path $logDir 'analysis1.err.log'
  },
  [pscustomobject]@{
    Name = 'analysis-2'
    WorkerId = 'pc2-real-analysis-2'
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-analysis-worker-2.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\detail_analysis_worker_2\detail_worker_summary.json'
    SummaryMaxAgeSeconds = $AnalysisSummaryMaxAgeSeconds
    StartupGraceSeconds = [Math]::Max($StartupGraceSeconds, 420)
    RequiresCdp = $false
    IsAnalysis = $true
    StopsWhenCollectionPaused = $false
    StdoutPath = Join-Path $logDir 'analysis2.out.log'
    StderrPath = Join-Path $logDir 'analysis2.err.log'
  },
  [pscustomobject]@{
    Name = 'analysis-3'
    WorkerId = 'pc2-real-analysis-3'
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-analysis-worker-3.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\detail_analysis_worker_3\detail_worker_summary.json'
    SummaryMaxAgeSeconds = $AnalysisSummaryMaxAgeSeconds
    StartupGraceSeconds = [Math]::Max($StartupGraceSeconds, 420)
    RequiresCdp = $false
    IsAnalysis = $true
    StopsWhenCollectionPaused = $false
    StdoutPath = Join-Path $logDir 'analysis3.out.log'
    StderrPath = Join-Path $logDir 'analysis3.err.log'
  },
  [pscustomobject]@{
    Name = 'detail-3-http'
    WorkerId = 'pc2-real-detail-3'
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-detail-worker-3.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\detail_worker_3\detail_worker_summary.json'
    SummaryMaxAgeSeconds = $DetailSummaryMaxAgeSeconds
    StartupGraceSeconds = $StartupGraceSeconds
    RequiresCdp = $collectorRequiresCdp
    IsAnalysis = $false
    StopsWhenCollectionPaused = $true
    StdoutPath = Join-Path $logDir 'detail3.out.log'
    StderrPath = Join-Path $logDir 'detail3.err.log'
  }
)

function Resolve-WorkerCount {
  param(
    [Parameter(Mandatory = $true)][int]$RequestedCount,
    [Parameter(Mandatory = $true)][string]$EnvironmentName,
    [Parameter(Mandatory = $true)][int]$DefaultCount
  )

  $resolved = $RequestedCount
  if ($resolved -eq 0) {
    $configured = [Environment]::GetEnvironmentVariable($EnvironmentName, 'Process')
    if ($configured) {
      if (-not [int]::TryParse($configured, [ref]$resolved)) {
        throw "$EnvironmentName must be an integer."
      }
    } else {
      $resolved = $DefaultCount
    }
  }
  if ($resolved -lt 3 -or $resolved -gt 8) {
    throw "$EnvironmentName must be between 3 and 8."
  }
  return $resolved
}

$DetailWorkerCount = Resolve-WorkerCount `
  -RequestedCount $DetailWorkerCount `
  -EnvironmentName 'FAPAI_HOST_DETAIL_WORKER_COUNT' `
  -DefaultCount 4
$AnalysisWorkerCount = Resolve-WorkerCount `
  -RequestedCount $AnalysisWorkerCount `
  -EnvironmentName 'FAPAI_HOST_ANALYSIS_WORKER_COUNT' `
  -DefaultCount 4

for ($index = 4; $index -le $DetailWorkerCount; $index++) {
  $workerId = "pc2-real-detail-$index"
  $outputDir = Join-Path $sharedRoot "output\nodes\pc2-real\detail_worker_$index"
  $workerSpecs += [pscustomobject]@{
    Name = "detail-$index-http"
    WorkerId = $workerId
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-detail-worker.ps1'
    ScriptArguments = @(
      '-RequestedWorkerId', $workerId,
      '-RequestedOutputDir', $outputDir,
      '-BrowserFallbackOverride', '0'
    )
    SummaryPath = Join-Path $outputDir 'detail_worker_summary.json'
    SummaryMaxAgeSeconds = $DetailSummaryMaxAgeSeconds
    StartupGraceSeconds = $StartupGraceSeconds
    RequiresCdp = $collectorRequiresCdp
    IsAnalysis = $false
    StopsWhenCollectionPaused = $true
    StdoutPath = Join-Path $logDir "detail$index.out.log"
    StderrPath = Join-Path $logDir "detail$index.err.log"
  }
}

for ($index = 4; $index -le $AnalysisWorkerCount; $index++) {
  $workerId = "pc2-real-analysis-$index"
  $outputDir = Join-Path $sharedRoot "output\nodes\pc2-real\detail_analysis_worker_$index"
  $workerSpecs += [pscustomobject]@{
    Name = "analysis-$index"
    WorkerId = $workerId
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-analysis-worker.ps1'
    ScriptArguments = @(
      '-RequestedWorkerId', $workerId,
      '-RequestedOutputDir', $outputDir
    )
    SummaryPath = Join-Path $outputDir 'detail_worker_summary.json'
    SummaryMaxAgeSeconds = $AnalysisSummaryMaxAgeSeconds
    StartupGraceSeconds = [Math]::Max($StartupGraceSeconds, 420)
    RequiresCdp = $false
    IsAnalysis = $true
    StopsWhenCollectionPaused = $false
    StdoutPath = Join-Path $logDir "analysis$index.out.log"
    StderrPath = Join-Path $logDir "analysis$index.err.log"
  }
}

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

function Test-CollectionPaused {
  try {
    $status = Invoke-RestMethod -Uri "$apiBaseUrl/status" -TimeoutSec 5
    return $status.paused -eq $true
  } catch {
    # The NAS control plane is authoritative. Fail closed so an outage cannot
    # restart collection-scoped workers while the real pause state is unknown.
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
  foreach ($spec in $workerSpecs) {
    if (-not $spec.StopsWhenCollectionPaused) {
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

Write-WatchdogLog 'pc2 worker watchdog booted'
Initialize-AnalysisUnavailableSummaryBaseline
while ($true) {
  $collectionPaused = Test-CollectionPaused
  if ($collectionPaused) {
    Stop-WorkersForCollectionPause
  }
  $cdpRequired = @($workerSpecs | Where-Object { $_.RequiresCdp }).Count -gt 0
  $cdpReady = -not $cdpRequired
  if ($cdpRequired) {
    try {
      $cdpReady = Ensure-CdpBrowser
    } catch {
      Write-WatchdogLog "watchdog cdp check failed: $($_.Exception.Message)"
    }
  }
  foreach ($spec in $workerSpecs) {
    if (($collectionPaused -and $spec.StopsWhenCollectionPaused) -or ($spec.RequiresCdp -and -not $cdpReady)) {
      continue
    }
    try {
      Ensure-Worker -Spec $spec
    } catch {
      Write-WatchdogLog "watchdog error for $($spec.Name): $($_.Exception.Message)"
    }
  }
  if ($cdpRequired -and -not $cdpReady) {
    Write-WatchdogLog 'cdp unavailable; skipping CDP-dependent worker supervision'
  }
  if ($Once) {
    break
  }
  Start-Sleep -Seconds $PollSeconds
}
