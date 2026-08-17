param(
    [string]$RemoteHost = "192.168.15.104",
    [string]$RemoteUser = "Admin",
    [string]$RemoteKeyPath = "",
    [string]$LocalPath = "",
    [string]$RemoteRuntimePath = "C:\fapaifang-worker\src\src\llm_helper.py",
    [string]$AnalysisWorkerId = "pc2-real-analysis-1",
    [switch]$RestartAnalysisWorker
)

$ErrorActionPreference = "Stop"

function Resolve-KeyPath {
    if ($RemoteKeyPath) {
        return (Resolve-Path -LiteralPath $RemoteKeyPath).ProviderPath
    }
    foreach ($candidate in @(
            (Join-Path $HOME ".ssh\id_ed25519"),
            (Join-Path $HOME ".ssh\id_rsa")
        )) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).ProviderPath
        }
    }
    throw "No SSH key is available for the PC2 llm_helper hotfix deployment."
}

function Convert-ToEncodedRemoteCommand {
    param([Parameter(Mandatory = $true)][string]$ScriptText)

    $bytes = [System.Text.Encoding]::Unicode.GetBytes($ScriptText)
    return [Convert]::ToBase64String($bytes)
}

function Convert-ToRemoteSingleQuotedLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)

    return "'" + ($Value -replace "'", "''") + "'"
}

function Convert-ToScpRemotePath {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)

    if ($WindowsPath -notmatch '^[A-Za-z]:\\') {
        throw "SCP conversion requires a fully qualified Windows path: $WindowsPath"
    }
    $drive = $WindowsPath.Substring(0, 1).ToUpperInvariant()
    $rest = $WindowsPath.Substring(2).Replace('\', '/')
    return "/{0}:{1}" -f $drive, $rest
}

if (-not $LocalPath) {
    $LocalPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\src\llm_helper.py"))
}
$resolvedLocalPath = (Resolve-Path -LiteralPath $LocalPath).ProviderPath
if (-not (Test-Path -LiteralPath $resolvedLocalPath)) {
    throw "Local llm_helper.py does not exist: $resolvedLocalPath"
}

$sshPath = (Get-Command ssh.exe -ErrorAction Stop).Source
$scpPath = (Get-Command scp.exe -ErrorAction Stop).Source
$keyPath = Resolve-KeyPath
$localHash = (Get-FileHash -LiteralPath $resolvedLocalPath -Algorithm SHA256).Hash

$remotePathLiteral = Convert-ToRemoteSingleQuotedLiteral $RemoteRuntimePath
$localHashLiteral = Convert-ToRemoteSingleQuotedLiteral $localHash
$analysisWorkerLiteral = Convert-ToRemoteSingleQuotedLiteral $AnalysisWorkerId
$restartLiteral = if ($RestartAnalysisWorker) { '$true' } else { '$false' }
$remoteScpPath = Convert-ToScpRemotePath ($RemoteRuntimePath + '.codex-staged')

$remoteScript = @'
$ErrorActionPreference = 'Stop'
$targetPath = __REMOTE_PATH__
$expectedHash = __EXPECTED_HASH__
$analysisWorkerId = __ANALYSIS_WORKER_ID__
$restartAnalysisWorker = __RESTART_ANALYSIS_WORKER__
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = Join-Path 'C:\fapaifang-worker\backups' ('llm-helper-hotfix-' + $timestamp)
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$backupPath = Join-Path $backupDir 'llm_helper.py'
$stagingPath = $targetPath + '.codex-staged'
$stagingHash = (Get-FileHash -LiteralPath $stagingPath -Algorithm SHA256).Hash
if ($stagingHash -ne $expectedHash) {
    throw ('Remote staging hash mismatch: {0} != {1}' -f $stagingHash, $expectedHash)
}
if (Test-Path -LiteralPath $targetPath) {
    Copy-Item -LiteralPath $targetPath -Destination $backupPath -Force
}
Move-Item -LiteralPath $stagingPath -Destination $targetPath -Force
$stoppedPids = @()
if ($restartAnalysisWorker) {
    $scriptPattern = [regex]::Escape('tools\detail_worker.py')
    $workerIdPattern = '--worker-id\s+' + [regex]::Escape($analysisWorkerId)
    $analysisProcesses = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -eq 'python.exe' -and
                $_.CommandLine -match $scriptPattern -and
                $_.CommandLine -match $workerIdPattern
            }
    )
    foreach ($process in $analysisProcesses) {
        $stoppedPids += [int]$process.ProcessId
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
[pscustomobject]@{
    remote_runtime_path = $targetPath
    remote_sha256 = (Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash
    expected_sha256 = $expectedHash
    backup_path = if (Test-Path -LiteralPath $backupPath) { $backupPath } else { $null }
    restart_analysis_worker = $restartAnalysisWorker
    stopped_analysis_pids = @($stoppedPids)
} | ConvertTo-Json -Compress
'@
$remoteScript = $remoteScript.Replace('__REMOTE_PATH__', $remotePathLiteral)
$remoteScript = $remoteScript.Replace('__EXPECTED_HASH__', $localHashLiteral)
$remoteScript = $remoteScript.Replace('__ANALYSIS_WORKER_ID__', $analysisWorkerLiteral)
$remoteScript = $remoteScript.Replace('__RESTART_ANALYSIS_WORKER__', $restartLiteral)

$encodedRemoteCommand = Convert-ToEncodedRemoteCommand -ScriptText $remoteScript
$scpArgs = @(
    "-q",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-i", $keyPath,
    $resolvedLocalPath,
    "${RemoteUser}@${RemoteHost}:$remoteScpPath"
)
$sshArgs = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-i", $keyPath,
    "$RemoteUser@$RemoteHost",
    "powershell",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-EncodedCommand", $encodedRemoteCommand
)

& $scpPath @scpArgs
if ($LASTEXITCODE -ne 0) {
    throw "PC2 llm_helper hotfix staging copy failed with exit code $LASTEXITCODE."
}

$resultJson = & $sshPath @sshArgs
if ($LASTEXITCODE -ne 0) {
    throw "PC2 llm_helper hotfix deployment failed with exit code $LASTEXITCODE."
}

$resultText = @(
    $resultJson |
        Where-Object {
            $_ -is [string] -and
            $_.Trim().StartsWith("{") -and
            $_.Trim().EndsWith("}")
        } |
        Select-Object -Last 1
) -join "`n"
if (-not $resultText) {
    throw "PC2 llm_helper hotfix deployment returned no JSON output."
}

$result = $resultText | ConvertFrom-Json
if ([string]$result.remote_sha256 -ne $localHash) {
    throw "PC2 llm_helper hotfix verification failed: remote hash does not match local hash."
}

[pscustomobject]@{
    remote_host = $RemoteHost
    local_path = $resolvedLocalPath
    local_sha256 = $localHash
    remote_runtime_path = $result.remote_runtime_path
    remote_sha256 = $result.remote_sha256
    backup_path = $result.backup_path
    restart_analysis_worker = [bool]$result.restart_analysis_worker
    stopped_analysis_pids = @($result.stopped_analysis_pids)
} | ConvertTo-Json -Compress
