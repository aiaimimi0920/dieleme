param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [string]$ApiBase = 'http://192.168.15.200:8001',
    [string]$CookieSnapshotPath = '',
    [string]$RecoveryTokenPath = '',
    [ValidateRange(1024, 65535)][int]$AuthLocalCdpPort = 9225,
    [string]$AuthBrowserProfileDir = '',
    [string]$AuthBrowserPath = '',
    [string]$SettingsApiBase = '',
    [string]$SettingsCaFile = '',
    [string]$OperatorTokenFile = ''
)

$ErrorActionPreference = 'Stop'
$api = [uri]$ApiBase
if (-not $api.IsAbsoluteUri -or $api.Scheme -notin @('http', 'https') -or $api.UserInfo -or $api.Query -or $api.Fragment -or $api.AbsolutePath -notin @('/', '/api', '/api/')) {
    throw 'API base must be an HTTP(S) API root without embedded credentials'
}
$root = [IO.Path]::GetFullPath($InstallRoot)
if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'Install root must exist' }
$data = [IO.Path]::GetFullPath($DataRoot)
$pythonResolver = Join-Path $PSScriptRoot 'resolve-pc1-auth-python.ps1'
if (-not (Test-Path -LiteralPath $pythonResolver -PathType Leaf)) { throw 'PC1 auth Python resolver is missing' }
. $pythonResolver
$resolvedPython = Resolve-Pc1AuthPython
$values = [ordered]@{
    FAPAI_COLLECTOR_API_BASE = $ApiBase
    FAPAI_DATA_ROOT_HOST = $data
    FAPAI_COOKIE_SNAPSHOT = $(if ($CookieSnapshotPath) { [IO.Path]::GetFullPath($CookieSnapshotPath) } else { Join-Path $data 'secrets\nodes\pc2\taobao-cookies.json' })
    FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE = $(if ($RecoveryTokenPath) { [IO.Path]::GetFullPath($RecoveryTokenPath) } else { Join-Path $data 'secrets\nas-auth-recovery.token' })
    FAPAI_AUTH_LOCAL_CDP_PORT = [string]$AuthLocalCdpPort
    FAPAI_DESKTOP_PYTHON_PATH = $resolvedPython
}
if ($AuthBrowserProfileDir) { $values.FAPAI_AUTH_BROWSER_PROFILE_DIR = [IO.Path]::GetFullPath($AuthBrowserProfileDir) }
if ($AuthBrowserPath) { $values.FAPAI_AUTH_BROWSER_PATH = [IO.Path]::GetFullPath($AuthBrowserPath) }
$path = Join-Path $root 'crow-desktop.runtime.json'
if (Test-Path -LiteralPath $path) {
    $previous = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if (-not $SettingsApiBase) { $SettingsApiBase = $previous.environment.FAPAI_SETTINGS_API_BASE }
    if (-not $SettingsCaFile) { $SettingsCaFile = $previous.environment.FAPAI_SETTINGS_CA_FILE }
    if (-not $OperatorTokenFile) { $OperatorTokenFile = $previous.environment.FAPAI_ENGINE_OPERATOR_TOKEN_FILE }
}
if ($SettingsApiBase -or $SettingsCaFile -or $OperatorTokenFile) {
    $control = [uri]$SettingsApiBase
    if (-not $control.IsAbsoluteUri -or $control.Scheme -ne 'https' -or $control.UserInfo -or $control.Query -or $control.Fragment -or $control.AbsolutePath -ne '/' -or -not $SettingsCaFile -or -not $OperatorTokenFile) {
        throw 'Settings requires an HTTPS origin, application CA file and operator token file'
    }
    $values.FAPAI_SETTINGS_API_BASE = $SettingsApiBase
    $values.FAPAI_SETTINGS_CA_FILE = [IO.Path]::GetFullPath($SettingsCaFile)
    $values.FAPAI_ENGINE_OPERATOR_TOKEN_FILE = [IO.Path]::GetFullPath($OperatorTokenFile)
}
$json = [ordered]@{ version = 1; environment = $values } | ConvertTo-Json -Depth 3
$temporary = Join-Path $root ('.desktop-config-' + [guid]::NewGuid().ToString('N') + '.tmp')
try {
    [IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $path) { [IO.File]::Replace($temporary, $path, [NullString]::Value) }
    else { [IO.File]::Move($temporary, $path) }
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
}
Write-Output 'Non-secret desktop runtime configuration saved.'
