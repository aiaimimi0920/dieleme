param(
    [int]$Port = 9225,
    [string]$DataRoot = "",
    [string]$OutputPath = "",
    [string]$Python = "python",
    [switch]$AllowListOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$helper = Join-Path $repoRoot "tools\taobao_inplace_auth_handoff.py"
if (-not (Test-Path -LiteralPath $helper)) {
    throw "Missing in-place Taobao authentication helper."
}
if (-not $DataRoot) {
    $DataRoot = if ($env:FAPAI_DATA_ROOT_HOST) {
        $env:FAPAI_DATA_ROOT_HOST
    }
    else {
        "Z:\project\project\FPFData"
    }
}
if (-not $OutputPath) {
    $OutputPath = if ($env:FAPAI_COOKIE_SNAPSHOT) {
        $env:FAPAI_COOKIE_SNAPSHOT
    }
    else {
        Join-Path $DataRoot "secrets\nodes\pc2\taobao-cookies.json"
    }
}

$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ($previousPythonPath) { "$repoRoot;$previousPythonPath" } else { $repoRoot }
try {
    & $Python $helper `
        --cdp-endpoint "http://127.0.0.1:$Port" `
        --output-path $OutputPath `
        $(if ($AllowListOnly) { "--allow-list-only" })
    if ($LASTEXITCODE -ne 0) {
        throw "PC1 in-place Taobao authentication is not reusable yet; collection remains paused."
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
