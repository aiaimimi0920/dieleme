function Resolve-Pc1AuthPython {
    param([string]$Requested = "")

    $candidate = $Requested
    if (-not $candidate -and $env:FAPAI_DESKTOP_PYTHON_PATH) {
        $candidate = $env:FAPAI_DESKTOP_PYTHON_PATH
    }
    if (-not $candidate) {
        $candidate = (Get-Command python -CommandType Application -ErrorAction Stop).Source
    }
    if (-not [IO.Path]::IsPathRooted($candidate)) {
        $candidate = (Get-Command $candidate -CommandType Application -ErrorAction Stop).Source
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "PC1 auth Python executable was not found: $candidate"
    }

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $probe = @(& $candidate -c "import sys, requests; print(sys.executable)" 2>&1)
        $probeExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($probeExit -ne 0) {
        throw "PC1 auth Python is missing the requests dependency: $candidate"
    }

    $actual = [string]($probe | Select-Object -Last 1)
    if ([IO.Path]::IsPathRooted($actual) -and (Test-Path -LiteralPath $actual -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $actual).ProviderPath
    }
    return (Resolve-Path -LiteralPath $candidate).ProviderPath
}
