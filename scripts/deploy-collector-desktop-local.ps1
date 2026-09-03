param(
    [string]$InstallRoot = "",
    [string]$BuildTargetRoot = "",
    [string]$ApiBase = "http://192.168.15.200:8001",
    [string]$RemoteAuthHost = "192.168.15.104",
    [string]$RemoteAuthUser = "Admin",
    [string]$RemoteAuthPassword = "",
    [string]$RemoteAuthKeyPath = "",
    [string]$DataRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) "FPFData"),
    [string]$CookieSnapshotPath = "",
    [ValidateSet("remote", "local-bridge")][string]$AuthBrowserMode = "local-bridge",
    [int]$AuthLocalCdpPort = 9225,
    [int]$AuthRemoteCdpPort = 9225,
    [string]$AuthBrowserProfileDir = (Join-Path (Split-Path -Parent $PSScriptRoot) "FPFData\chrome-cdp-profile-pc1-human-clean"),
    [string]$AuthBrowserPath = "C:\Program Files\Google\Chrome\Application\chrome.exe",
    [switch]$SkipBuild,
    [switch]$SkipLaunch,
    [switch]$SkipShortcut
)

$ErrorActionPreference = "Stop"

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Resolve-RepoRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
}

function Invoke-CmdInLocalWorkingDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Command
    )

    Push-Location $env:SystemRoot
    try {
        & cmd /d /c $Command
    }
    finally {
        Pop-Location
    }
}

function Invoke-CollectorDesktopBuild {
    param(
        [Parameter(Mandatory = $true)][string]$CollectorRoot,
        [Parameter(Mandatory = $true)][string]$TargetRoot
    )

    New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null

    $previousCargoTargetDir = $env:CARGO_TARGET_DIR
    $env:CARGO_TARGET_DIR = $TargetRoot
    try {
        $installCommand = "pushd `"$CollectorRoot`" && if not exist node_modules npm install && popd"
        Invoke-CmdInLocalWorkingDirectory -Command $installCommand
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed with exit code $LASTEXITCODE"
        }

        $buildCommand = "pushd `"$CollectorRoot`" && npm run tauri:build && popd"
        Invoke-CmdInLocalWorkingDirectory -Command $buildCommand
        if ($LASTEXITCODE -ne 0) {
            throw "npm run tauri:build failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        if ($null -eq $previousCargoTargetDir) {
            Remove-Item Env:\CARGO_TARGET_DIR -ErrorAction SilentlyContinue
        }
        else {
            $env:CARGO_TARGET_DIR = $previousCargoTargetDir
        }
    }
}

function Backup-ExistingInstall {
    param(
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )

    if (-not (Test-Path -LiteralPath $DestinationRoot)) {
        return
    }

    $backupRoot = Join-Path $DestinationRoot "backup"
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupDir = Join-Path $backupRoot $timestamp
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

    foreach ($relativePath in @(
            "fapaifang_collector_desktop.exe",
            "start-fapaifang-collector.ps1",
            "scripts",
            "tools"
        )) {
        $sourcePath = Join-Path $DestinationRoot $relativePath
        if (-not (Test-Path -LiteralPath $sourcePath)) {
            continue
        }
        $backupPath = Join-Path $backupDir $relativePath
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupPath) | Out-Null
        Copy-Item -LiteralPath $sourcePath -Destination $backupPath -Recurse -Force
    }

    $oldBackups = @(Get-ChildItem -LiteralPath $backupRoot -Directory -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -Skip 5)
    foreach ($backup in $oldBackups) {
        Remove-Item -LiteralPath $backup.FullName -Recurse -Force
    }
}

function Stop-ExistingCollectorDesktop {
    $running = @(Get-Process -Name "fapaifang_collector_desktop" -ErrorAction SilentlyContinue)
    foreach ($process in $running) {
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "Could not stop collector desktop process $($process.Id): $($_.Exception.Message)"
        }
    }
}

function Copy-BundleFile {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$DestinationRoot,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    $sourcePath = Join-Path $SourceRoot $RelativePath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Missing bundle file: $sourcePath"
    }

    $destinationPath = Join-Path $DestinationRoot $RelativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destinationPath) | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
}

function Write-LauncherScript {
    param(
        [Parameter(Mandatory = $true)][string]$LauncherPath,
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [Parameter(Mandatory = $true)][string]$ApiBaseUrl,
        [Parameter(Mandatory = $true)][string]$RemoteHost,
        [Parameter(Mandatory = $true)][string]$RemoteUserName,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$RemotePasswordValue,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$RemoteKeyPath,
        [Parameter(Mandatory = $true)][string]$DataRootValue,
        [Parameter(Mandatory = $true)][string]$CookieSnapshotValue,
        [Parameter(Mandatory = $true)][string]$AuthBrowserModeValue,
        [Parameter(Mandatory = $true)][int]$AuthLocalCdpPortValue,
        [Parameter(Mandatory = $true)][int]$AuthRemoteCdpPortValue,
        [Parameter(Mandatory = $true)][string]$AuthBrowserProfileDirValue,
        [Parameter(Mandatory = $true)][string]$AuthBrowserPathValue
    )

    $launcherLines = New-Object System.Collections.Generic.List[string]
    if ($ApiBaseUrl) {
        $launcherLines.Add(('$env:FAPAI_COLLECTOR_API_BASE = ''{0}''' -f $ApiBaseUrl.Replace("'", "''")))
    }
    if ($RemoteHost) {
        $launcherLines.Add(('$env:FAPAI_REMOTE_AUTH_HOST = ''{0}''' -f $RemoteHost.Replace("'", "''")))
    }
    if ($RemoteUserName) {
        $launcherLines.Add(('$env:FAPAI_REMOTE_AUTH_USER = ''{0}''' -f $RemoteUserName.Replace("'", "''")))
    }
    if ($RemotePasswordValue) {
        $launcherLines.Add(('$env:FAPAI_REMOTE_AUTH_PASSWORD = ''{0}''' -f $RemotePasswordValue.Replace("'", "''")))
    }
    if ($RemoteKeyPath) {
        $launcherLines.Add(('$env:FAPAI_REMOTE_AUTH_KEY_PATH = ''{0}''' -f $RemoteKeyPath.Replace("'", "''")))
    }
    if ($DataRootValue) {
        $launcherLines.Add(('$env:FAPAI_DATA_ROOT_HOST = ''{0}''' -f $DataRootValue.Replace("'", "''")))
    }
    if ($CookieSnapshotValue) {
        $launcherLines.Add(('$env:FAPAI_COOKIE_SNAPSHOT = ''{0}''' -f $CookieSnapshotValue.Replace("'", "''")))
    }
    if ($AuthBrowserModeValue) {
        $launcherLines.Add(('$env:FAPAI_AUTH_BROWSER_MODE = ''{0}''' -f $AuthBrowserModeValue.Replace("'", "''")))
    }
    $launcherLines.Add(('$env:FAPAI_AUTH_LOCAL_CDP_PORT = ''{0}''' -f $AuthLocalCdpPortValue))
    $launcherLines.Add(('$env:FAPAI_AUTH_REMOTE_CDP_PORT = ''{0}''' -f $AuthRemoteCdpPortValue))
    if ($AuthBrowserProfileDirValue) {
        $launcherLines.Add(('$env:FAPAI_AUTH_BROWSER_PROFILE_DIR = ''{0}''' -f $AuthBrowserProfileDirValue.Replace("'", "''")))
    }
    if ($AuthBrowserPathValue) {
        $launcherLines.Add(('$env:FAPAI_AUTH_BROWSER_PATH = ''{0}''' -f $AuthBrowserPathValue.Replace("'", "''")))
    }
    $launcherLines.Add(('Start-Process -FilePath ''{0}''' -f $ExecutablePath.Replace("'", "''")))

    Write-Utf8NoBomFile -Path $LauncherPath -Content ($launcherLines -join [Environment]::NewLine)
}

function Update-DesktopShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$ShortcutPath,
        [Parameter(Mandatory = $true)][string]$LauncherPath,
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    $powershellExecutable = (Get-Command powershell -ErrorAction Stop).Source
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $powershellExecutable
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$LauncherPath`""
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.IconLocation = "$ExecutablePath,0"
    $shortcut.Save()
}

function Resolve-RemoteAuthKeyPath {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        return $ExplicitPath
    }

    foreach ($candidate in @(
            (Join-Path $HOME ".ssh\id_ed25519"),
            (Join-Path $HOME ".ssh\id_rsa")
        )) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).ProviderPath
        }
    }

    return ""
}
$repoRoot = Resolve-RepoRoot
$collectorRoot = Join-Path $repoRoot "collector-desktop"
$deployRoot = if ($InstallRoot) {
    $InstallRoot
}
else {
    Join-Path $env:LOCALAPPDATA "FapaiFangCollectorDesktop"
}
$resolvedBuildTargetRoot = if ($BuildTargetRoot) {
    $BuildTargetRoot
}
else {
    Join-Path $env:TEMP "fapaifang-collector-desktop-target"
}

$buildExecutable = Join-Path $resolvedBuildTargetRoot "release\fapaifang_collector_desktop.exe"
$destinationExecutable = Join-Path $deployRoot "fapaifang_collector_desktop.exe"
$launcherPath = Join-Path $deployRoot "start-fapaifang-collector.ps1"
$desktopShortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "FapaiFang 运维观察台.lnk"
$legacyDesktopShortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "FapaiFang 采集观察台.lnk"
$resolvedRemoteAuthKeyPath = Resolve-RemoteAuthKeyPath -ExplicitPath $RemoteAuthKeyPath
$resolvedCookieSnapshotPath = if ($CookieSnapshotPath) {
    $CookieSnapshotPath
} else {
    Join-Path $DataRoot "secrets\nodes\pc2\taobao-cookies.json"
}

if (-not $SkipBuild) {
    Invoke-CollectorDesktopBuild -CollectorRoot $collectorRoot -TargetRoot $resolvedBuildTargetRoot
}

if (-not (Test-Path -LiteralPath $buildExecutable)) {
    throw "Built desktop executable not found: $buildExecutable"
}

New-Item -ItemType Directory -Force -Path $deployRoot | Out-Null
Stop-ExistingCollectorDesktop
Backup-ExistingInstall -DestinationRoot $deployRoot

Copy-Item -LiteralPath $buildExecutable -Destination $destinationExecutable -Force

foreach ($relativePath in @(
        "scripts\open-remote-auth-browser.ps1",
        "scripts\start-pc1-manual-auth-session.ps1",
        "scripts\start-pc1-auth-bridge.ps1",
        "scripts\watch-pc1-auth-auto-resume.ps1",
        "scripts\watch-pc1-nas-auth-recovery.ps1",
        "scripts\register-pc1-nas-auth-recovery-task.ps1",
        "scripts\register-pc1-shared-auth-maintenance.ps1",
        "scripts\register-taobao-login-watchdog-task.ps1",
        "scripts\taobao-login-watchdog.ps1",
        "scripts\start-pc1-analysis-proxy-bridge.ps1",
        "scripts\register-pc1-analysis-proxy-bridge-task.ps1",
        "scripts\start-taobao-cdp-browser.ps1",
        "scripts\export-taobao-cookie-snapshot.ps1",
        "scripts\complete-pc1-inplace-auth.ps1",
        "tools\browserless_seed_probe.py",
        "tools\taobao_login_health.py",
        "tools\taobao_inplace_auth_handoff.py",
        "tools\internal_api_http.py"
    )) {
    Copy-BundleFile -SourceRoot $repoRoot -DestinationRoot $deployRoot -RelativePath $relativePath
}

Write-LauncherScript `
    -LauncherPath $launcherPath `
    -ExecutablePath $destinationExecutable `
    -ApiBaseUrl $ApiBase `
    -RemoteHost $RemoteAuthHost `
    -RemoteUserName $RemoteAuthUser `
    -RemotePasswordValue $RemoteAuthPassword `
    -RemoteKeyPath $resolvedRemoteAuthKeyPath `
    -DataRootValue $DataRoot `
    -CookieSnapshotValue $resolvedCookieSnapshotPath `
    -AuthBrowserModeValue $AuthBrowserMode `
    -AuthLocalCdpPortValue $AuthLocalCdpPort `
    -AuthRemoteCdpPortValue $AuthRemoteCdpPort `
    -AuthBrowserProfileDirValue $AuthBrowserProfileDir `
    -AuthBrowserPathValue $AuthBrowserPath

if (-not $SkipShortcut) {
    Update-DesktopShortcut `
        -ShortcutPath $desktopShortcutPath `
        -LauncherPath $launcherPath `
        -ExecutablePath $destinationExecutable `
        -WorkingDirectory $deployRoot
    if (($legacyDesktopShortcutPath -ne $desktopShortcutPath) -and (Test-Path -LiteralPath $legacyDesktopShortcutPath)) {
        Remove-Item -LiteralPath $legacyDesktopShortcutPath -Force
    }
}

if (-not $SkipLaunch) {
    $powershellExecutable = (Get-Command powershell -ErrorAction Stop).Source
    Start-Process `
        -FilePath $powershellExecutable `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcherPath) `
        -WorkingDirectory $deployRoot `
        -WindowStyle Hidden
}

Write-Output "Collector desktop deployed to: $deployRoot"
Write-Output "Desktop executable: $destinationExecutable"
Write-Output "Launcher script: $launcherPath"
if (-not $SkipShortcut) {
    Write-Output "Desktop shortcut: $desktopShortcutPath"
}
