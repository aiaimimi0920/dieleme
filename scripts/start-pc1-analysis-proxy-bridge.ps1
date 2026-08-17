param(
    [int]$RemoteProxyPort = 42345,
    [string]$RemoteHost = "192.168.15.104",
    [string]$RemoteUser = "Admin",
    [string]$RemoteKeyPath = "",
    [string]$RuntimeRoot = ""
)

$ErrorActionPreference = "Stop"

function Resolve-KeyPath {
    if ($RemoteKeyPath) {
        return (Resolve-Path -LiteralPath $RemoteKeyPath).ProviderPath
    }
    $profileRoot = [Environment]::GetFolderPath("UserProfile")
    foreach ($candidate in @(
            (Join-Path $profileRoot ".ssh\id_ed25519"),
            (Join-Path $profileRoot ".ssh\id_rsa")
        )) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).ProviderPath
        }
    }
    throw "No SSH key is available for the PC1 analysis proxy bridge."
}

function Resolve-LocalProxyPort {
    $settings = Get-ItemProperty `
        -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" `
        -ErrorAction Stop
    if (-not [bool]$settings.ProxyEnable) {
        throw "The PC1 Windows proxy is disabled."
    }
    $candidates = @(
        ([string]$settings.ProxyServer) -split ";" |
            ForEach-Object { ($_ -split "=")[-1] } |
            Where-Object { $_ -match "^(127\.0\.0\.1|localhost):(\d+)$" } |
            ForEach-Object { [int](($_ -split ":")[-1]) } |
            Select-Object -Unique
    )
    foreach ($port in $candidates) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $listener) {
            return $port
        }
    }
    throw "No listening PC1 loopback proxy was found."
}

$ssh = (Get-Command ssh.exe -ErrorAction Stop).Source
$keyPath = Resolve-KeyPath
$localProxyPort = Resolve-LocalProxyPort
$forwardSpec = "127.0.0.1:{0}:[::1]:{1}" -f $RemoteProxyPort, $localProxyPort
$marker = "-R $forwardSpec"
$existing = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq "ssh.exe" -and
            ([string]$_.CommandLine).IndexOf($marker, [StringComparison]::OrdinalIgnoreCase) -ge 0
        }
)
if ($existing.Count -gt 0) {
    Write-Output "PC1 analysis proxy bridge is already running."
    exit 0
}

$resolvedRuntimeRoot = if ($RuntimeRoot) {
    $RuntimeRoot
} else {
    Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "FapaiFangCollectorDesktop\runtime"
}
$stateDir = Join-Path $resolvedRuntimeRoot "analysis-proxy-bridge"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$arguments = @(
    "-N", "-T",
    "-o", "BatchMode=yes",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
    "-o", "ConnectTimeout=10",
    "-R", $forwardSpec,
    "-i", $keyPath,
    "$RemoteUser@$RemoteHost"
)
$logPath = Join-Path $stateDir "pc1-analysis-proxy-bridge.log"
$errorLogPath = Join-Path $stateDir "pc1-analysis-proxy-bridge.err.log"
Add-Content -LiteralPath $logPath -Value ("[{0}] starting analysis proxy bridge" -f (Get-Date).ToString("o")) -Encoding UTF8

# Keep SSH in the foreground so the logon task owns the tunnel lifetime. A detached
# child is terminated by Task Scheduler when the wrapper exits.
& $ssh @arguments >> $logPath 2>> $errorLogPath
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    throw "PC1 analysis proxy bridge exited with code $exitCode."
}
