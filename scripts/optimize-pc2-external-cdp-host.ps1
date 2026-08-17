param(
    [string]$RemoteHost = "192.168.15.104",
    [string]$RemoteUser = "Admin",
    [string]$RemoteKeyPath = "",
    [switch]$Apply
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
    throw "No SSH key is available for the PC2 external-CDP optimization script."
}

function Convert-ToEncodedRemoteCommand {
    param([Parameter(Mandatory = $true)][string]$ScriptText)

    $bytes = [System.Text.Encoding]::Unicode.GetBytes($ScriptText)
    return [Convert]::ToBase64String($bytes)
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

$sshPath = (Get-Command ssh.exe -ErrorAction Stop).Source
$scpPath = (Get-Command scp.exe -ErrorAction Stop).Source
$keyPath = Resolve-KeyPath
$applyLiteral = if ($Apply) { '$true' } else { '$false' }

$remoteScript = @"
`$ErrorActionPreference = 'Stop'
`$apply = $applyLiteral
`$envFile = 'C:\fapaifang-worker\env.worker.local'

function Get-EnvValue {
    param([Parameter(Mandatory = `$true)][string]`$Name)

    if (-not (Test-Path -LiteralPath `$envFile)) {
        return ''
    }
    foreach (`$line in Get-Content -LiteralPath `$envFile -Encoding UTF8) {
        if (-not `$line -or `$line.TrimStart().StartsWith('#') -or `$line.IndexOf('=') -lt 1) {
            continue
        }
        `$entryName, `$value = `$line.Split('=', 2)
        if (`$entryName.Trim() -eq `$Name) {
            return [string]`$value
        }
    }
    return ''
}

function Test-CdpEndpoint {
    param([Parameter(Mandatory = `$true)][string]`$Endpoint)

    `$response = `$null
    try {
        `$request = [System.Net.HttpWebRequest]::Create("`$(`$Endpoint.TrimEnd('/'))/json/version")
        `$request.Proxy = `$null
        `$request.Timeout = 3000
        `$request.ReadWriteTimeout = 3000
        `$request.KeepAlive = `$false
        `$response = [System.Net.HttpWebResponse]`$request.GetResponse()
        return [int]`$response.StatusCode -eq 200
    } catch {
        return `$false
    } finally {
        if (`$null -ne `$response) {
            `$response.Close()
        }
    }
}

function Get-FreeMemoryMb {
    return [math]::Round(([double](Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory) / 1024.0, 2)
}

`$externalCdp = (Get-EnvValue -Name 'FAPAI_CDP_EXTERNAL').Trim() -eq '1'
`$cdpEndpoint = (Get-EnvValue -Name 'FAPAI_CDP_ENDPOINT').Trim()
if (-not `$cdpEndpoint) {
    `$cdpEndpoint = 'http://127.0.0.1:9223'
}
`$beforeFreeMemoryMb = Get-FreeMemoryMb
`$localCdpUsers = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            `$_.Name -eq 'python.exe' -and
            [string]`$_.CommandLine -match '--cdp-endpoint\s+http://127\.0\.0\.1:9223'
        } |
        Select-Object -ExpandProperty ProcessId
)
`$edgeProcesses = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            `$_.Name -eq 'msedge.exe' -and
            [string]`$_.CommandLine -match 'edge-cdp-profile-pc2'
        }
)
`$estimatedWorkingSetMb = [math]::Round((@(`$edgeProcesses | ForEach-Object {
    try {
        (Get-Process -Id `$_.ProcessId -ErrorAction Stop).WorkingSet64
    } catch {
        0
    }
}) | Measure-Object -Sum).Sum / 1MB, 2)

if (-not `$externalCdp) {
    `$action = 'skipped_not_external_cdp'
} elseif (`$cdpEndpoint -match '127\.0\.0\.1:9223$') {
    `$action = 'skipped_external_endpoint_points_to_local_9223'
} elseif (-not (Test-CdpEndpoint -Endpoint `$cdpEndpoint)) {
    `$action = 'skipped_external_cdp_unhealthy'
} elseif (`$localCdpUsers.Count -gt 0) {
    `$action = 'skipped_local_9223_still_in_use'
} elseif (`$edgeProcesses.Count -eq 0) {
    `$action = 'skipped_no_unused_local_browser'
} elseif (-not `$apply) {
    `$action = 'would_stop_unused_local_browser'
} else {
    foreach (`$process in `$edgeProcesses) {
        Stop-Process -Id `$process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    `$action = 'stopped_unused_local_browser'
}

`$afterFreeMemoryMb = Get-FreeMemoryMb

[pscustomobject]@{
    action = `$action
    apply = `$apply
    external_cdp = `$externalCdp
    cdp_endpoint = `$cdpEndpoint
    before_free_memory_mb = `$beforeFreeMemoryMb
    after_free_memory_mb = `$afterFreeMemoryMb
    estimated_reclaimed_working_set_mb = `$estimatedWorkingSetMb
    local_9223_user_pids = @(`$localCdpUsers)
    edge_process_count = `$edgeProcesses.Count
    edge_process_pids = @(`$edgeProcesses | Select-Object -ExpandProperty ProcessId)
} | ConvertTo-Json -Compress
"@

$encodedRemoteCommand = Convert-ToEncodedRemoteCommand -ScriptText $remoteScript
$remoteScriptPath = 'C:\Users\Admin\AppData\Local\Temp\codex-optimize-pc2-external-cdp-host.ps1'
$remoteScriptScpPath = Convert-ToScpRemotePath $remoteScriptPath
$localScriptPath = Join-Path $env:TEMP ('codex-optimize-pc2-external-cdp-host-' + [guid]::NewGuid().ToString() + '.ps1')
[System.IO.File]::WriteAllText($localScriptPath, $remoteScript, (New-Object System.Text.UTF8Encoding($false)))
$scpArgs = @(
    "-q",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-i", $keyPath,
    $localScriptPath,
    "${RemoteUser}@${RemoteHost}:$remoteScriptScpPath"
)
$sshArgs = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-i", $keyPath,
    "$RemoteUser@$RemoteHost",
    "powershell",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $remoteScriptPath
)

try {
    & $scpPath @scpArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PC2 external-CDP optimization staging copy failed with exit code $LASTEXITCODE."
    }

    $resultJson = & $sshPath @sshArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PC2 external-CDP optimization failed with exit code $LASTEXITCODE."
    }
} finally {
    Remove-Item -LiteralPath $localScriptPath -Force -ErrorAction SilentlyContinue
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
    throw "PC2 external-CDP optimization returned no JSON output."
}

$resultText
