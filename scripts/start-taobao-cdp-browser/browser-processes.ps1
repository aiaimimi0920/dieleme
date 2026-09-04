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
