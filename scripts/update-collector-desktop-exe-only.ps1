[CmdletBinding()]
param(
    [string]$SourceExecutable = (Join-Path $env:TEMP 'crow-observer-neuro-ui-target\release\fapaifang_collector_desktop.exe'),
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'FapaiFangCollectorDesktop'),
    [string]$DesktopDirectory = [Environment]::GetFolderPath('Desktop'),
    [string]$ExpectedSha256,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-LocalFullPath {
    param([string]$Value)
    $fullPath = [IO.Path]::GetFullPath($Value)
    $driveRoot = [IO.Path]::GetPathRoot($fullPath)
    if ($driveRoot.StartsWith('\\') -or
        ([IO.DriveInfo]::new($driveRoot)).DriveType -ne [IO.DriveType]::Fixed) {
        throw 'Only local fixed-drive paths are supported. No network installation is allowed.'
    }
    # Do not follow directory junctions into another installation or network share.
    $cursor = $fullPath
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $entry = Get-Item -LiteralPath $cursor -Force
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Reparse points are not supported: $cursor"
            }
        }
        $cursor = Split-Path -Parent $cursor
    }
    return $fullPath
}

$source = Get-LocalFullPath $SourceExecutable
$root = Get-LocalFullPath $InstallRoot
$destination = Get-LocalFullPath (Join-Path $root 'fapaifang_collector_desktop.exe')
if ($source -eq $destination) { throw 'Source and installed executable must be different files.' }
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Build executable missing: $source" }
if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
    throw "Existing installation missing: $destination. This script only updates an existing exe."
}
$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
$oldHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
if ($ExpectedSha256 -and $sourceHash -ne $ExpectedSha256) { throw 'Source SHA-256 does not match the expected build.' }

Write-Output "Source: $source"
Write-Output "Installed: $destination"
Write-Output "Source SHA-256: $sourceHash"
Write-Output "Installed SHA-256: $oldHash"
if (-not $Apply) {
    if ($sourceHash -eq $oldHash) { Write-Output 'Already current. No files changed.' }
    else { Write-Output 'CHECK ONLY. No files changed. Close the app, then use -Apply to update.' }
    return
}
if (-not $ExpectedSha256) { throw '-Apply requires -ExpectedSha256 from the build report.' }
if ($sourceHash -eq $oldHash) {
    $shortcut = & (Join-Path $PSScriptRoot 'update-collector-desktop-shortcut.ps1') `
        -InstallRoot $root -DesktopDirectory $DesktopDirectory -ExpectedSha256 $sourceHash
    Write-Output "Already current. Desktop shortcut refreshed: $($shortcut.path)"
    return
}
if (@(Get-Process -Name 'fapaifang_collector_desktop' -ErrorAction SilentlyContinue).Count) {
    throw 'Close the observer normally, then retry. This script never stops processes.'
}

$id = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$backupRoot = Get-LocalFullPath (Join-Path $root "backup\exe-only-$id")
$backup = Join-Path $backupRoot 'fapaifang_collector_desktop.exe'
$staged = Join-Path $root ".observer-update-$id.exe"
[IO.Directory]::CreateDirectory($backupRoot) | Out-Null
[IO.File]::Copy($destination, $backup, $false)
if ((Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash -ne $oldHash) {
    throw "Backup verification failed. Installed exe was not changed. Inspect: $backup"
}
Write-Output "Verified backup: $backup"

try {
    [IO.File]::Copy($source, $staged, $false)
    if ((Get-FileHash -LiteralPath $staged -Algorithm SHA256).Hash -ne $sourceHash) {
        throw 'Staged executable verification failed; installed exe was not changed.'
    }
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $oldHash) {
        throw 'Installed executable changed during update; refusing to overwrite it.'
    }
    # Atomic same-volume replacement; existing launchers, profiles and data are untouched.
    [IO.File]::Replace($staged, $destination, [NullString]::Value)
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $sourceHash) {
        throw "Installed hash verification failed. Keep the verified backup: $backup"
    }
    $shortcut = & (Join-Path $PSScriptRoot 'update-collector-desktop-shortcut.ps1') `
        -InstallRoot $root -DesktopDirectory $DesktopDirectory -ExpectedSha256 $sourceHash
    Write-Output "UPDATED AND HASH VERIFIED. Desktop shortcut refreshed: $($shortcut.path)"
    Write-Output 'No app was launched. No launcher, helper, profile, database or remote service was changed.'
}
finally {
    if ([IO.File]::Exists($staged)) { [IO.File]::Delete($staged) }
}
