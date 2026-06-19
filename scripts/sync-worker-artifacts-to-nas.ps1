param(
    [string]$SourceRoot = "C:\Users\Public\nas_home\AI\FPFData",
    [string]$TargetRoot = "\\192.168.15.200\docker\fapaifang",
    [string[]]$IncludeDirs = @("output", "datas", "jobs", "secrets"),
    [int]$LoopIntervalSeconds = 0,
    [int]$RetryCount = 2,
    [int]$RetryWaitSeconds = 2
)

$ErrorActionPreference = "Stop"

function Invoke-ArtifactSyncOnce {
    param(
        [string]$SourceRoot,
        [string]$TargetRoot,
        [string[]]$IncludeDirs,
        [int]$RetryCount,
        [int]$RetryWaitSeconds
    )

    if (-not (Test-Path -LiteralPath $SourceRoot)) {
        throw "SourceRoot does not exist: $SourceRoot"
    }
    New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null

    foreach ($dir in $IncludeDirs) {
        $source = Join-Path $SourceRoot $dir
        if (-not (Test-Path -LiteralPath $source)) {
            Write-Warning "Skipping missing artifact directory: $source"
            continue
        }

        $target = Join-Path $TargetRoot $dir
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        $logDir = Join-Path $TargetRoot "sync-logs"
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        $log = Join-Path $logDir ("robocopy-{0}.log" -f $dir)

        robocopy $source $target /E /COPY:DAT /DCOPY:DAT /R:$RetryCount /W:$RetryWaitSeconds /XJ /MT:8 /NFL /NDL /NP /LOG+:$log
        $code = $LASTEXITCODE
        if ($code -ge 8) {
            throw "robocopy failed for $dir with exit code $code. See $log"
        }
        Write-Host "synced $dir with robocopy exit code $code"
    }
}

do {
    Invoke-ArtifactSyncOnce `
        -SourceRoot $SourceRoot `
        -TargetRoot $TargetRoot `
        -IncludeDirs $IncludeDirs `
        -RetryCount $RetryCount `
        -RetryWaitSeconds $RetryWaitSeconds

    if ($LoopIntervalSeconds -le 0) {
        break
    }
    Start-Sleep -Seconds $LoopIntervalSeconds
} while ($true)
