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

$selfHealModuleRoot = Join-Path $PSScriptRoot 'watch-pc2-cdp-self-heal'
. (Join-Path $selfHealModuleRoot 'state-and-http.ps1')
. (Join-Path $selfHealModuleRoot 'cdp-health.ps1')
. (Join-Path $selfHealModuleRoot 'runtime-recovery.ps1')
. (Join-Path $selfHealModuleRoot 'recovery-policy.ps1')

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
