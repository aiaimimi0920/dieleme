param(
    [string]$ApiBase = "",
    [string]$DataRoot = "",
    [string]$OutputPath = "",
    [string]$TokenPath = "",
    [int]$Port = 9225,
    [string]$Python = "python",
    [string]$ProfileDir = "",
    [string]$BrowserPath = "",
    [string]$StartUrl = "https://sf.taobao.com/list/50025969__2.htm",
    [int]$LoginWindowSeconds = 300,
    [switch]$UseSystemProxy
)

$ErrorActionPreference = "Stop"

function Resolve-ApiBase {
    $value = if ($ApiBase) {
        $ApiBase
    }
    elseif ($env:FAPAI_COLLECTOR_API_BASE) {
        $env:FAPAI_COLLECTOR_API_BASE
    }
    elseif ($env:FAPAI_API_BASE_URL) {
        $env:FAPAI_API_BASE_URL
    }
    else {
        "http://192.168.15.200:8001/api"
    }
    $value = $value.TrimEnd("/")
    if ($value -notmatch "/api$") {
        $value = "$value/api"
    }
    return $value
}

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
    $temporaryPath = "$Path.$PID.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        [System.IO.File]::WriteAllText($temporaryPath, $Content, $utf8NoBom)
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

function Read-State {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Write-State {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$State
    )
    $updatedAt = (Get-Date).ToUniversalTime().ToString("o")
    if ($State -is [System.Collections.IDictionary]) {
        $State["updated_at"] = $updatedAt
    }
    else {
        $State | Add-Member -NotePropertyName updated_at -NotePropertyValue $updatedAt -Force
    }
    Write-Utf8NoBomFile -Path $Path -Content ($State | ConvertTo-Json -Depth 6)
}

function Invoke-RecoveryPost {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)]$Body,
        [Parameter(Mandatory = $true)][hashtable]$Headers
    )
    return Invoke-RestMethod `
        -Uri $Uri `
        -Method Post `
        -ContentType "application/json" `
        -Headers $Headers `
        -Body ($Body | ConvertTo-Json -Compress -Depth 5) `
        -TimeoutSec 20
}

function Get-CdpTabs {
    param([Parameter(Mandatory = $true)][string]$Endpoint)
    try {
        $request = [System.Net.HttpWebRequest]::Create("$($Endpoint.TrimEnd('/'))/json/list")
        $request.Proxy = $null
        $request.Timeout = 3000
        $request.ReadWriteTimeout = 3000
        $response = [System.Net.HttpWebResponse]$request.GetResponse()
        try {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            try {
                return @($reader.ReadToEnd() | ConvertFrom-Json)
            }
            finally {
                $reader.Dispose()
            }
        }
        finally {
            $response.Close()
        }
    }
    catch {
        return @()
    }
}

function Test-TaobaoAuthPageExists {
    param([Parameter(Mandatory = $true)]$Tabs)
    foreach ($tab in @($Tabs)) {
        if ([string]$tab.type -ne "page") {
            continue
        }
        $url = ([string]$tab.url).ToLowerInvariant()
        if ($url -match "(^|//)([^/]+\.)?taobao\.com" -or $url -match "(^|//)([^/]+\.)?tmall\.com") {
            return $true
        }
    }
    return $false
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$startBrowserScript = Join-Path $repoRoot "scripts\start-taobao-cdp-browser.ps1"
$completeAuthScript = Join-Path $repoRoot "scripts\complete-pc1-inplace-auth.ps1"
foreach ($required in @($startBrowserScript, $completeAuthScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing PC1 auth recovery helper: $required"
    }
}

if (-not $DataRoot) {
    $DataRoot = if ($env:FAPAI_DATA_ROOT_HOST) { $env:FAPAI_DATA_ROOT_HOST } else { "C:\Users\Public\nas_home\AI\FPFData" }
}
if (-not $OutputPath) {
    $OutputPath = if ($env:FAPAI_COOKIE_SNAPSHOT) { $env:FAPAI_COOKIE_SNAPSHOT } else { Join-Path $DataRoot "secrets\nodes\pc2\taobao-cookies.json" }
}
if (-not $TokenPath) {
    $TokenPath = Join-Path $DataRoot "secrets\nas-auth-recovery.token"
}
if (-not (Test-Path -LiteralPath $TokenPath)) {
    throw "NAS auth recovery token file is missing."
}
$recoveryToken = (Get-Content -LiteralPath $TokenPath -Raw -Encoding UTF8).Trim()
if (-not $recoveryToken) {
    throw "NAS auth recovery token file is empty."
}
$recoveryHeaders = @{ "X-Fapai-Recovery-Token" = $recoveryToken }
if (-not $ProfileDir) {
    $ProfileDir = if ($env:FAPAI_AUTH_BROWSER_PROFILE_DIR) { $env:FAPAI_AUTH_BROWSER_PROFILE_DIR } else { Join-Path $DataRoot "chrome-cdp-profile-pc1-human-clean" }
}
if (-not $BrowserPath) {
    $BrowserPath = if ($env:FAPAI_AUTH_BROWSER_PATH) { $env:FAPAI_AUTH_BROWSER_PATH } else { "C:\Program Files\Google\Chrome\Application\chrome.exe" }
}

$apiBaseResolved = Resolve-ApiBase
$recoveryBase = "$apiBaseResolved/collection/auth/recovery"
$statePath = Join-Path $DataRoot "runtime\pc1-nas-auth-recovery-state.json"
$state = Read-State -Path $statePath
$response = Invoke-RestMethod -Uri $recoveryBase -Method Get -Headers $recoveryHeaders -TimeoutSec 20
$active = $response.auth_recovery.active
if ($null -eq $active) {
    exit 0
}

$recoveryId = [string]$active.recovery_id
$status = [string]$active.status
if (-not $recoveryId -or $status -notin @("requested", "pc1_claimed")) {
    exit 0
}
if ($status -eq "requested") {
    $claim = Invoke-RecoveryPost `
        -Uri "$recoveryBase/claim" `
        -Body @{ recovery_id = $recoveryId; role = "pc1"; node_id = "pc1" } `
        -Headers $recoveryHeaders
    if (-not $claim.ok) {
        exit 1
    }
}

$now = [DateTimeOffset]::UtcNow
$sameRecovery = $null -ne $state -and [string]$state.recovery_id -eq $recoveryId
$openedAt = if ($sameRecovery -and $state.auth_window_opened_at) {
    try { [DateTimeOffset]::Parse([string]$state.auth_window_opened_at) } catch { $null }
} else {
    $null
}
$withinWindow = $null -ne $openedAt -and ($now - $openedAt).TotalSeconds -lt [Math]::Max($LoginWindowSeconds, 1)
$cdpEndpoint = "http://127.0.0.1:$Port"
$tabs = @(Get-CdpTabs -Endpoint $cdpEndpoint)
$existingAuthPage = Test-TaobaoAuthPageExists -Tabs $tabs

if (-not $existingAuthPage -and -not $withinWindow) {
    $browserArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $startBrowserScript,
        "-Port", $Port,
        "-DataRoot", $DataRoot,
        "-ProfileDir", $ProfileDir,
        "-BrowserPath", $BrowserPath,
        "-DebuggingAddress", "127.0.0.1",
        "-StartUrl", $StartUrl,
        "-HumanAuthMode"
    )
    if ($UseSystemProxy) {
        $browserArgs += "-UseSystemProxy"
    }
    & powershell.exe @browserArgs | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "PC1 authentication browser failed to start."
    }
    $openedAt = [DateTimeOffset]::UtcNow
}
elseif ($null -eq $openedAt) {
    $openedAt = $now
}

$newState = [ordered]@{
    mode = "pc1_nas_auth_recovery"
    recovery_id = $recoveryId
    status = "waiting_for_reusable_auth"
    auth_window_opened_at = $openedAt.ToString("o")
    login_window_seconds = [Math]::Max($LoginWindowSeconds, 1)
    cdp_endpoint = $cdpEndpoint
    output_path = $OutputPath
}
Write-State -Path $statePath -State $newState

& powershell.exe `
    -NoProfile `
    -ExecutionPolicy Bypass `
    -File $completeAuthScript `
    -Port $Port `
    -DataRoot $DataRoot `
    -OutputPath $OutputPath `
    -Python $Python `
    -AllowListOnly | Out-Null
if ($LASTEXITCODE -ne 0) {
    exit 0
}

$cookies = Get-Content -LiteralPath $OutputPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($cookies.Count -le 0) {
    throw "PC1 authentication snapshot is empty."
}
$digest = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
$ready = Invoke-RecoveryPost `
    -Uri "$recoveryBase/snapshot_ready" `
    -Body @{
        recovery_id = $recoveryId
        sha256 = $digest
        cookie_count = $cookies.Count
        created_at_epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    } `
    -Headers $recoveryHeaders
if (-not $ready.ok) {
    exit 1
}
$newState["status"] = "snapshot_published"
$newState["cookie_count"] = $cookies.Count
$newState["snapshot_sha256"] = $digest
Write-State -Path $statePath -State $newState
Write-Output "Published validated PC1 authentication metadata for recovery $recoveryId without cookie values."
