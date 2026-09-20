[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'FapaiFangCollectorDesktop'),
    [string]$DesktopDirectory = [Environment]::GetFolderPath('Desktop'),
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedSha256
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path -LiteralPath $InstallRoot).ProviderPath
$executable = Join-Path $root 'fapaifang_collector_desktop.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw "Installed executable missing: $executable" }
if ((Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash -ne $ExpectedSha256) {
    throw 'Installed executable SHA-256 does not match the verified build; shortcut was not changed.'
}
if (-not $DesktopDirectory -or -not (Test-Path -LiteralPath $DesktopDirectory -PathType Container)) {
    throw 'Desktop directory is unavailable; shortcut was not changed.'
}
$desktop = (Resolve-Path -LiteralPath $DesktopDirectory).ProviderPath
$path = Join-Path $desktop 'Crow.lnk'
if (Test-Path -LiteralPath $path) {
    $entry = Get-Item -LiteralPath $path -Force
    if ($entry.PSIsContainer -or ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Crow.lnk is not a regular shortcut file; refusing to replace it.'
    }
}

$target = $executable
$arguments = ''
$launcher = Join-Path $root 'start-fapaifang-collector.ps1'
# Current builds read their adjacent runtime config directly. Older installs need the launcher.
if (-not (Test-Path -LiteralPath (Join-Path $root 'crow-desktop.runtime.json') -PathType Leaf) -and
    (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    $target = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
}
$icon = "$executable,0"
$staged = Join-Path $desktop ('.Crow-' + [Guid]::NewGuid().ToString('N') + '.lnk')
$shell = $null
$shortcut = $null
$saved = $null
$verified = $null

function Assert-ShortcutFields {
    param($Link)
    if ($Link.TargetPath -ne $target -or $Link.Arguments -ne $arguments -or
        $Link.WorkingDirectory -ne $root -or $Link.IconLocation -ne $icon) {
        throw 'Desktop shortcut verification failed.'
    }
}

try {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($staged)
    $shortcut.TargetPath = $target
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $root
    $shortcut.IconLocation = $icon
    $shortcut.Description = 'Crow'
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    $saved = $shell.CreateShortcut($staged)
    Assert-ShortcutFields $saved
    if ([IO.File]::Exists($path)) {
        [IO.File]::Replace($staged, $path, [NullString]::Value)
    } else {
        [IO.File]::Move($staged, $path)
    }
    $verified = $shell.CreateShortcut($path)
    Assert-ShortcutFields $verified
    if (-not ('CrowDesktopShell' -as [type])) {
        Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class CrowDesktopShell {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    public static extern void SHChangeNotify(uint eventId, uint flags, string path, IntPtr unused);
}
'@
    }
    [CrowDesktopShell]::SHChangeNotify(0x00002000, 0x00001005, $executable, [IntPtr]::Zero)
    [CrowDesktopShell]::SHChangeNotify(0x00002000, 0x00001005, $path, [IntPtr]::Zero)
    [pscustomobject]@{
        path = $path; target = $target; arguments = $arguments
        working_directory = $root; icon = $icon; executable_sha256 = $ExpectedSha256.ToLowerInvariant()
    }
}
finally {
    foreach ($item in @($verified, $saved, $shortcut, $shell)) {
        if ($null -ne $item) { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($item) | Out-Null }
    }
    if ([IO.File]::Exists($staged)) { [IO.File]::Delete($staged) }
}
