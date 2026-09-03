param(
    [int]$Port = 9223,
    [string]$DataRoot = "",
    [string]$ProfileDir = "",
    [string]$BrowserPath = "",
    [string]$DebuggingAddress = "0.0.0.0",
    [string]$StartUrl = "https://sf.taobao.com/",
    [switch]$UseSystemProxy,
    [switch]$DisableExtensions,
    [switch]$HumanAuthMode,
    [switch]$StartMinimized,
    [switch]$EnsureOnly,
    [int]$CdpStartupTimeoutSeconds = 30,
    [int]$StartupLockTimeoutSeconds = 180,
    [switch]$IsolatedProfile,
    [switch]$ForceNew,
    [switch]$TerminateAllBrowserProcesses
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

    return (Join-Path (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath "FPFData")
}

function Invoke-CdpWebRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [ValidateSet("GET", "PUT")][string]$Method = "GET",
        [int]$TimeoutSec = 3,
        [int]$MaxResponseBytes = 1048576
    )

    $timeoutMilliseconds = [Math]::Max($TimeoutSec, 1) * 1000
    $request = [System.Net.HttpWebRequest]::Create($Uri)
    $request.Method = $Method
    $request.Proxy = $null
    $request.Timeout = $timeoutMilliseconds
    $request.ReadWriteTimeout = $timeoutMilliseconds
    $request.KeepAlive = $false
    if ($Method -eq "PUT") {
        $request.ContentLength = 0
    }

    $response = $null
    try {
        $response = [System.Net.HttpWebResponse]$request.GetResponse()
        $stream = $response.GetResponseStream()
        try {
            if ($stream.CanTimeout) {
                $stream.ReadTimeout = $timeoutMilliseconds
            }

            $expectedLength = [int64]$response.ContentLength
            if ($expectedLength -gt $MaxResponseBytes) {
                throw "CDP response exceeds the configured limit of $MaxResponseBytes bytes."
            }

            $readLimit = if ($expectedLength -ge 0) {
                $expectedLength
            }
            else {
                [int64]$MaxResponseBytes
            }

            $buffer = New-Object byte[] 8192
            $memory = New-Object System.IO.MemoryStream
            try {
                while ($memory.Length -lt $readLimit) {
                    $remaining = [int][Math]::Min(
                        [int64]$buffer.Length,
                        $readLimit - $memory.Length
                    )
                    if ($remaining -le 0) {
                        break
                    }

                    $read = $stream.Read($buffer, 0, $remaining)
                    if ($read -le 0) {
                        break
                    }
                    $memory.Write($buffer, 0, $read)
                }

                if ($expectedLength -ge 0 -and $memory.Length -lt $expectedLength) {
                    throw "CDP response ended before its advertised content length."
                }

                $content = [System.Text.Encoding]::UTF8.GetString($memory.ToArray())
            }
            finally {
                $memory.Dispose()
            }
        }
        finally {
            $stream.Dispose()
        }

        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Content = $content
        }
    }
    finally {
        if ($null -ne $response) {
            $response.Close()
        }
    }
}

function Test-CdpEndpoint {
    param([Parameter(Mandatory = $true)][string]$Endpoint)

    try {
        $response = Invoke-CdpWebRequest -Uri "$($Endpoint.TrimEnd('/'))/json/version" -TimeoutSec 3
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

function Get-CdpPageScope {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $parsed = [Uri]$Url
        $host = $parsed.Host.ToLowerInvariant()
        $path = $parsed.AbsolutePath.ToLowerInvariant()
        while ($path.Contains('//')) { $path = $path.Replace('//', '/') }
        if ($host -eq 'sf-item.taobao.com' -or $path.Contains('/sf_item/')) {
            return 'detail'
        }
        if (($host -eq 'sf.taobao.com' -and $path.Contains('/list/')) -or
            ($path.Contains('/list/') -and $path.Contains('/punish'))) {
            return 'seed'
        }
    }
    catch {
    }
    return ''
}

function Open-CdpBrowserPage {
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][string]$Url
    )

    $baseEndpoint = $Endpoint.TrimEnd('/')

    # Authentication/challenge pages are operator-facing state.  Never create
    # a second tab when one already exists: a new login tab invalidates the QR
    # or password flow in the first tab.  This check is deliberately performed
    # while the caller holds the per-port startup mutex, so concurrent watchdog
    # invocations share one find-or-create critical section.
    try {
        $targetsResponse = Invoke-CdpWebRequest -Uri "$baseEndpoint/json/list" -TimeoutSec 5
        $targets = @($targetsResponse.Content | ConvertFrom-Json)
        $requested = [Uri]$Url
        $requestedPath = $requested.AbsolutePath
        while ($requestedPath.Contains('//')) { $requestedPath = $requestedPath.Replace('//', '/') }
        $requestedIsLogin = $requested.Host.ToLowerInvariant().Contains('login.taobao.com') -or
            $requested.Host.ToLowerInvariant().Contains('login.tmall.com') -or
            $requestedPath.ToLowerInvariant().Contains('havanaone/login')
        $requestedRoute = ($requestedPath.ToLowerInvariant() -split '/_____tmd_____/')[0]
        $requestedScope = Get-CdpPageScope -Url $Url
        foreach ($candidate in $targets) {
            if ([string]$candidate.type -ne 'page') { continue }
            $candidateUrl = [string]$candidate.url
            if (-not $candidateUrl) { continue }
            $candidateParsed = $null
            try { $candidateParsed = [Uri]$candidateUrl } catch { continue }
            $candidatePath = $candidateParsed.AbsolutePath.ToLowerInvariant()
            while ($candidatePath.Contains('//')) { $candidatePath = $candidatePath.Replace('//', '/') }
            $candidateIsLogin = $candidateParsed.Host.ToLowerInvariant().Contains('login.taobao.com') -or
                $candidateParsed.Host.ToLowerInvariant().Contains('login.tmall.com') -or
                $candidatePath.Contains('havanaone/login')
            $candidateIsChallenge = $candidateUrl.ToLowerInvariant().Contains('_____tmd_____') -or
                $candidateUrl.ToLowerInvariant().Contains('x5secdata=') -or
                $candidateUrl.ToLowerInvariant().Contains('x5step=') -or
                $candidateUrl.ToLowerInvariant().Contains('__captcha_solver_bg=1')
            $candidateRoute = ($candidatePath -split '/_____tmd_____/')[0]
            $sameRoute = $requestedRoute -and ($candidateRoute -eq $requestedRoute)
            $candidateScope = Get-CdpPageScope -Url $candidateUrl
            $sameScope = $requestedScope -and ($candidateScope -eq $requestedScope)
            if (($requestedIsLogin -and $candidateIsLogin) -or
                (-not $requestedIsLogin -and $candidateIsChallenge -and
                    ($sameScope -or (-not $requestedScope -and $sameRoute)))) {
                if ($candidate.id) {
                    try { Invoke-CdpWebRequest -Uri "$baseEndpoint/json/activate/$($candidate.id)" -TimeoutSec 3 | Out-Null } catch {}
                }
                Write-Output "Reused existing auth/challenge page: $candidateUrl"
                return
            }
        }
    }
    catch {
        Write-Host "Could not inspect existing auth/challenge pages before opening: $($_.Exception.Message)"
    }

    if (Test-BrowserProcessOpenPreferred -Url $Url) {
        throw "Skipping CDP /json/new for challenge-sized auth URL; use browser process fallback."
    }

    $encodedUrl = [System.Uri]::EscapeDataString($Url)
    $response = Invoke-CdpWebRequest -Method 'PUT' -Uri "$baseEndpoint/json/new?$encodedUrl" -TimeoutSec 10
    $page = $response.Content | ConvertFrom-Json

    if ($page.id) {
        try {
            Invoke-CdpWebRequest -Uri "$baseEndpoint/json/activate/$($page.id)" -TimeoutSec 3 | Out-Null
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
        [Parameter(Mandatory = $true)][string]$DebuggingAddress,
        [Parameter(Mandatory = $true)][string]$Url
    )

    $arguments = @(
        "--remote-debugging-port=$Port",
        "--remote-debugging-address=$DebuggingAddress",
        "--remote-allow-origins=*",
        "--user-data-dir=$ProfileDir",
        "--no-first-run",
        "--no-default-browser-check",
        $Url
    )

    Start-Process `
        -FilePath $Browser `
        -ArgumentList $arguments `
        -WorkingDirectory (Split-Path -Parent $Browser) `
        -WindowStyle Normal
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
        [switch]$TopLevelOnly,
        [switch]$AllBrowserProcesses
    )

    $browserProcessNames = @("chrome.exe", "msedge.exe")
    if ($AllBrowserProcesses) {
        # PC2 recovery explicitly opts into this path. Get-Process is native and
        # remains responsive when the local CIM provider is wedged.
        foreach ($nativeProcess in @(Get-Process -Name "chrome", "msedge" -ErrorAction SilentlyContinue)) {
            if ($TopLevelOnly -and $nativeProcess.MainWindowHandle -eq [IntPtr]::Zero) {
                continue
            }
            [pscustomobject]@{
                ProcessId = $nativeProcess.Id
                Name = "$($nativeProcess.ProcessName).exe"
            }
        }
        return
    }

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
        [Parameter(Mandatory = $true)][string]$ProfileDir,
        [switch]$AllBrowserProcesses
    )

    $processes = @(Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir -TopLevelOnly -AllBrowserProcesses:$AllBrowserProcesses)
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
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [switch]$AllBrowserProcesses
    )

    # Kill every process bound to the dedicated profile, not just the browser
    # process. Orphaned renderer/GPU children can keep the profile lock after a
    # crash and make the next Edge process exit before CDP starts listening.
    $processes = @(
        Get-CdpBrowserProcesses `
            -Port $Port `
            -ProfileDir $ProfileDir `
            -AllBrowserProcesses:$AllBrowserProcesses
    )

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
        $remaining = @(Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir -AllBrowserProcesses:$AllBrowserProcesses)
        if (($remaining.Count -eq 0) -and -not (Test-CdpEndpoint -Endpoint $Endpoint)) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }

    Write-Host "Timed out waiting for matching CDP browser processes and endpoint to exit."
    return $false
}

function Find-BrowserExecutable {
    param([string]$PreferredPath = "")

    if ($PreferredPath) {
        if (Test-Path -LiteralPath $PreferredPath) {
            return (Resolve-Path -LiteralPath $PreferredPath).ProviderPath
        }
        throw "Configured browser executable does not exist: $PreferredPath"
    }

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

$startupMutex = [System.Threading.Mutex]::new(
    $false,
    "FapaiFangTaobaoCdp-$Port"
)
$startupLockAcquired = $false
try {
    try {
        $startupLockAcquired = $startupMutex.WaitOne(
            [TimeSpan]::FromSeconds([Math]::Max($StartupLockTimeoutSeconds, 1))
        )
    }
    catch [System.Threading.AbandonedMutexException] {
        $startupLockAcquired = $true
    }
    if (-not $startupLockAcquired) {
        throw "Timed out waiting for the CDP startup lock on port $Port."
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
$resolvedDebuggingAddress = if ($HumanAuthMode) { "127.0.0.1" } else { $DebuggingAddress }

if ($ForceNew) {
    if (-not (Stop-ExistingCdpBrowser `
        -Port $Port `
        -ProfileDir $ProfileDir `
        -Endpoint $hostEndpoint `
        -AllBrowserProcesses:$TerminateAllBrowserProcesses
    )) {
        throw "Existing CDP browser processes did not exit cleanly for port $Port / profile $ProfileDir."
    }
}
elseif (Test-CdpEndpoint -Endpoint $hostEndpoint) {
    Write-Output "Existing CDP endpoint is available: $hostEndpoint"
    if (-not $EnsureOnly) {
        if (Test-BrowserProcessOpenPreferred -Url $StartUrl) {
            Write-Host "Skipping CDP /json/new for challenge-sized auth URL when no matching tab exists."
        }
        try {
            # Always inspect/reuse an existing auth or challenge tab first.
            # Only fall back to a browser process when CDP cannot open the URL;
            # this prevents long challenge URLs from bypassing deduplication.
            Open-CdpBrowserPage -Endpoint $hostEndpoint -Url $StartUrl
        }
        catch {
            Write-Host "CDP /json/new open failed; falling back to browser process URL open: $($_.Exception.Message)"
            $browser = Find-BrowserExecutable -PreferredPath $BrowserPath
            Open-BrowserProcessPage -Browser $browser -ProfileDir $ProfileDir -Port $Port -DebuggingAddress $resolvedDebuggingAddress -Url $StartUrl
        }
        Show-CdpBrowserWindow -Port $Port -ProfileDir $ProfileDir -AllBrowserProcesses:$TerminateAllBrowserProcesses
    }
    else {
        Write-Output "CDP endpoint is already healthy; ensure-only mode will not open a page."
    }
    Write-Output "Docker containers should use: $dockerEndpoint"
    Write-Output "Log in to Taobao in the opened browser window if it is not already authenticated."
    return
}
else {
    $staleProcesses = @(Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir)
    if ($staleProcesses.Count -gt 0) {
        Write-Host "Existing CDP browser process exists but endpoint is unavailable; restarting the dedicated auth browser."
        if (-not (Stop-ExistingCdpBrowser -Port $Port -ProfileDir $ProfileDir -Endpoint $hostEndpoint)) {
            throw "Stale CDP browser processes did not exit cleanly for port $Port / profile $ProfileDir."
        }
    }
}

New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

$browser = Find-BrowserExecutable -PreferredPath $BrowserPath
$arguments = @(
    "--remote-debugging-port=$Port",
    "--remote-debugging-address=$resolvedDebuggingAddress",
    "--remote-allow-origins=*",
    "--user-data-dir=$ProfileDir",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-session-crashed-bubble",
    $StartUrl
)

if (-not $HumanAuthMode) {
    $arguments += @(
        "--disable-blink-features=AutomationControlled",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-client-side-phishing-detection",
        "--disable-default-apps",
        "--disable-restore-session-state"
    )
}

if (-not $UseSystemProxy) {
    $arguments += "--no-proxy-server"
}
if ($DisableExtensions) {
    $arguments += "--disable-extensions"
}
if ($StartMinimized) {
    $arguments += "--start-minimized"
}

Start-Process `
    -FilePath $browser `
    -ArgumentList $arguments `
    -WorkingDirectory (Split-Path -Parent $browser) `
    -WindowStyle Normal

if (-not (Wait-CdpEndpoint -Endpoint $hostEndpoint -TimeoutSeconds $CdpStartupTimeoutSeconds)) {
    throw "Started browser but CDP endpoint did not become available within $CdpStartupTimeoutSeconds seconds: $hostEndpoint/json/version"
}

Show-CdpBrowserWindow -Port $Port -ProfileDir $ProfileDir -AllBrowserProcesses:$TerminateAllBrowserProcesses
Write-Output "Started browser: $browser"
Write-Output "Profile directory: $ProfileDir"
Write-Output "Host CDP endpoint: $hostEndpoint"
Write-Output "Docker CDP endpoint: $dockerEndpoint"
Write-Output "Human auth mode: $($HumanAuthMode.IsPresent)"
Write-Output "Log in to Taobao in the opened browser window, then keep the window open for collectors."
}
finally {
    if ($startupLockAcquired) {
        try {
            $startupMutex.ReleaseMutex()
        }
        catch {
        }
    }
    $startupMutex.Dispose()
}
