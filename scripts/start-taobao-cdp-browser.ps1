param(
    [int]$Port = 9223,
    [string]$DataRoot = "",
    [string]$ProfileDir = "",
    [string]$StartUrl = "https://sf.taobao.com/",
    [switch]$UseSystemProxy,
    [switch]$DisableExtensions,
    [switch]$IsolatedProfile,
    [switch]$ForceNew
)

$ErrorActionPreference = "Stop"

function Resolve-FapaiDataRoot {
    if ($DataRoot) {
        return $DataRoot
    }

    if ($env:FAPAI_DATA_ROOT_HOST) {
        return $env:FAPAI_DATA_ROOT_HOST
    }

    $localEnvPath = Join-Path $PSScriptRoot "..\docker.local.env"
    if (Test-Path -LiteralPath $localEnvPath) {
        $configuredRoot = Select-String -LiteralPath $localEnvPath -Pattern "^FAPAI_DATA_ROOT_HOST=(.+)$" | Select-Object -First 1
        if ($configuredRoot) {
            return $configuredRoot.Matches[0].Groups[1].Value.Trim()
        }
    }

    return "C:\Users\Public\nas_home\AI\FPFData"
}

function Test-CdpEndpoint {
    param([Parameter(Mandatory = $true)][string]$Endpoint)

    try {
        $response = Invoke-WebRequest -Uri "$($Endpoint.TrimEnd('/'))/json/version" -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Wait-CdpEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [int]$TimeoutSeconds = 30,
        [int]$PollMilliseconds = 500
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-CdpEndpoint -Endpoint $Endpoint) {
            return $true
        }
        Start-Sleep -Milliseconds $PollMilliseconds
    }

    return $false
}

function Open-CdpBrowserPage {
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][string]$Url
    )

    $baseEndpoint = $Endpoint.TrimEnd('/')
    $encodedUrl = [System.Uri]::EscapeDataString($Url)
    $response = Invoke-WebRequest -Method Put -Uri "$baseEndpoint/json/new?$encodedUrl" -UseBasicParsing -TimeoutSec 10
    $page = $response.Content | ConvertFrom-Json

    if ($page.id) {
        try {
            Invoke-WebRequest -Uri "$baseEndpoint/json/activate/$($page.id)" -UseBasicParsing -TimeoutSec 3 | Out-Null
        }
        catch {
            Write-Host "Opened page but could not activate tab $($page.id): $($_.Exception.Message)"
        }
    }

    Write-Output "Opened auth page in existing CDP browser: $Url"
}

function Open-BrowserProcessPage {
    param(
        [Parameter(Mandatory = $true)][string]$Browser,
        [Parameter(Mandatory = $true)][string]$ProfileDir,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$Url
    )

    $arguments = @(
        "--remote-debugging-port=$Port",
        "--remote-debugging-address=0.0.0.0",
        "--remote-allow-origins=*",
        "--user-data-dir=$ProfileDir",
        "--no-first-run",
        "--no-default-browser-check",
        $Url
    )

    Start-Process -FilePath $Browser -ArgumentList $arguments -WorkingDirectory (Split-Path -Parent $Browser)
    Write-Output "Opened auth page via browser process fallback: $Url"
}

function Test-BrowserProcessOpenPreferred {
    param([Parameter(Mandatory = $true)][string]$Url)

    $lowerUrl = $Url.ToLowerInvariant()
    return (
        $Url.Length -gt 1800 -or
        $lowerUrl.Contains("_____tmd_____/punish") -or
        $lowerUrl.Contains("x5secdata=")
    )
}

function Get-CdpBrowserProcesses {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$ProfileDir,
        [switch]$TopLevelOnly
    )

    $browserProcessNames = @("chrome.exe", "msedge.exe")
    @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                if ($browserProcessNames -notcontains $_.Name) {
                    return $false
                }

                $cmd = [string]$_.CommandLine
                if (-not $cmd) {
                    return $false
                }

                if ($TopLevelOnly) {
                    if ($cmd -like "* --type=*") {
                        return $false
                    }
                }

                $hasProfile = $false
                if ($ProfileDir) {
                    $hasProfile = $cmd.IndexOf($ProfileDir, [StringComparison]::OrdinalIgnoreCase) -ge 0
                }

                return (($cmd -like "*remote-debugging-port=$Port*") -or $hasProfile)
            }
    )
}

function Show-CdpBrowserWindow {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$ProfileDir
    )

    $processes = @(Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir -TopLevelOnly)
    if ($processes.Count -eq 0) {
        return
    }

    if (-not ("FapaiFangWindowTools" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class FapaiFangWindowTools {
    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@
    }

    foreach ($process in ($processes | Sort-Object ProcessId -Descending)) {
        try {
            $nativeProcess = Get-Process -Id $process.ProcessId -ErrorAction Stop
            if ($nativeProcess.MainWindowHandle -eq [IntPtr]::Zero) {
                continue
            }

            [FapaiFangWindowTools]::ShowWindowAsync($nativeProcess.MainWindowHandle, 9) | Out-Null
            [FapaiFangWindowTools]::SetForegroundWindow($nativeProcess.MainWindowHandle) | Out-Null
            Write-Host "Activated existing CDP browser window: process $($process.ProcessId)."
            return
        }
        catch {
            Write-Host "Could not activate process $($process.ProcessId): $($_.Exception.Message)"
        }
    }
}

function Stop-ExistingCdpBrowser {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$ProfileDir,
        [Parameter(Mandatory = $true)][string]$Endpoint
    )

    $processes = @(Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir -TopLevelOnly)

    if ($processes.Count -eq 0) {
        return $true
    }

    Write-Host "Stopping existing CDP browser processes for port $Port / profile $ProfileDir."
    foreach ($process in ($processes | Sort-Object ProcessId -Descending)) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        }
        catch {
            Write-Host "Could not stop process $($process.ProcessId): $($_.Exception.Message)"
        }
    }

    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        $remaining = @(Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir -TopLevelOnly)
        if (($remaining.Count -eq 0) -and -not (Test-CdpEndpoint -Endpoint $Endpoint)) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }

    Write-Host "Timed out waiting for the top-level CDP browser process and endpoint to exit."
    return $false
}

function Find-BrowserExecutable {
    $candidates = @(
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:LocalAppData\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "No Microsoft Edge or Google Chrome executable found in standard locations."
}

$dataRoot = Resolve-FapaiDataRoot
if (-not $ProfileDir) {
    if ($IsolatedProfile) {
        $ProfileDir = Join-Path $dataRoot "edge-cdp-profile-isolated"
    }
    else {
        $ProfileDir = Join-Path $dataRoot "edge-cdp-profile"
    }
}

$hostEndpoint = "http://127.0.0.1:$Port"
$dockerEndpoint = "http://192.168.65.254:$Port"

if ($ForceNew) {
    if (-not (Stop-ExistingCdpBrowser -Port $Port -ProfileDir $ProfileDir -Endpoint $hostEndpoint)) {
        throw "Existing CDP browser processes did not exit cleanly for port $Port / profile $ProfileDir."
    }
}
elseif (Test-CdpEndpoint -Endpoint $hostEndpoint) {
    Write-Output "Existing CDP endpoint is available: $hostEndpoint"
    if (Test-BrowserProcessOpenPreferred -Url $StartUrl) {
        Write-Host "Skipping CDP /json/new for challenge-sized auth URL; using browser process URL open."
        $browser = Find-BrowserExecutable
        Open-BrowserProcessPage -Browser $browser -ProfileDir $ProfileDir -Port $Port -Url $StartUrl
    }
    else {
        try {
            Open-CdpBrowserPage -Endpoint $hostEndpoint -Url $StartUrl
        }
        catch {
            Write-Host "CDP /json/new open failed; falling back to browser process URL open: $($_.Exception.Message)"
            $browser = Find-BrowserExecutable
            Open-BrowserProcessPage -Browser $browser -ProfileDir $ProfileDir -Port $Port -Url $StartUrl
        }
    }
    Show-CdpBrowserWindow -Port $Port -ProfileDir $ProfileDir
    Write-Output "Docker containers should use: $dockerEndpoint"
    Write-Output "Log in to Taobao in the opened browser window if it is not already authenticated."
    exit 0
}
else {
    $staleProcesses = @(Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir -TopLevelOnly)
    if ($staleProcesses.Count -gt 0) {
        Write-Host "Existing CDP browser process exists but endpoint is unavailable; restarting the dedicated auth browser."
        if (-not (Stop-ExistingCdpBrowser -Port $Port -ProfileDir $ProfileDir -Endpoint $hostEndpoint)) {
            throw "Stale CDP browser processes did not exit cleanly for port $Port / profile $ProfileDir."
        }
    }
}

New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

$browser = Find-BrowserExecutable
$arguments = @(
    "--remote-debugging-port=$Port",
    "--remote-debugging-address=0.0.0.0",
    "--remote-allow-origins=*",
    "--disable-blink-features=AutomationControlled",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-client-side-phishing-detection",
    "--disable-default-apps",
    "--user-data-dir=$ProfileDir",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-session-crashed-bubble",
    "--disable-restore-session-state",
    $StartUrl
)

if (-not $UseSystemProxy) {
    $arguments += "--no-proxy-server"
}
if ($DisableExtensions) {
    $arguments += "--disable-extensions"
}

Start-Process -FilePath $browser -ArgumentList $arguments -WorkingDirectory (Split-Path -Parent $browser)

if (-not (Wait-CdpEndpoint -Endpoint $hostEndpoint -TimeoutSeconds 30)) {
    throw "Started browser but CDP endpoint did not become available within 30 seconds: $hostEndpoint/json/version"
}

Write-Output "Started browser: $browser"
Write-Output "Profile directory: $ProfileDir"
Write-Output "Host CDP endpoint: $hostEndpoint"
Write-Output "Docker CDP endpoint: $dockerEndpoint"
Write-Output "Log in to Taobao in the opened browser window, then keep the window open for collectors."
