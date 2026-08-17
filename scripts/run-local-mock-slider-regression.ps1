param(
    [string]$PythonCmd = "python",
    [int]$Runs = 3,
    [int]$Workers = 4,
    [string[]]$Scenario = @(),
    [switch]$SkipPytest,
    [switch]$SkipMatrix,
    [switch]$Headed
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
Set-Location $repoRoot

if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $repoRoot
}
else {
    $env:PYTHONPATH = "$repoRoot;$env:PYTHONPATH"
}

function Invoke-PythonStep {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string[]]$Args
    )

    Write-Host "==> $Label"
    Write-Host "$PythonCmd $($Args -join ' ')"
    & $PythonCmd @Args
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

if (-not $SkipPytest) {
    Invoke-PythonStep -Label "mock-slider pytest regression" -Args @(
        "-m",
        "pytest",
        "tools/test/test_mock_slider_drag_check.py",
        "tools/test/test_mock_solver_probe.py",
        "tools/test/test_mock_solver_matrix.py",
        "tools/test/test_captcha_solver.py",
        "tools/test/test_taobao_login_health.py",
        "tools/test/test_detail_worker.py",
        "-q"
    )
}

if (-not $SkipMatrix) {
    $matrixArgs = @(
        "tools/mock_solver_matrix.py",
        "--runs",
        "$Runs",
        "--workers",
        "$Workers"
    )
    foreach ($name in $Scenario) {
        $trimmed = [string]$name
        if (-not [string]::IsNullOrWhiteSpace($trimmed)) {
            $matrixArgs += @("--scenario", $trimmed.Trim())
        }
    }
    if ($Headed) {
        $matrixArgs += "--headed"
    }
    Invoke-PythonStep -Label "mock-slider matrix regression" -Args $matrixArgs
}

Write-Host "Local mock slider regression passed."
