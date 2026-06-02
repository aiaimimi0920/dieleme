param(
    [string]$DataRoot = "",
    [string]$Image = "fapaifang-collector:local",
    [switch]$SkipPostgres,
    [string]$PostgresContainer = "fapaifang-postgres",
    [string]$PostgresDb = "fapaifang",
    [string]$PostgresUser = "fapaifang",
    [string]$PostgresPassword = "fapaifang"
)

$ErrorActionPreference = "Stop"

if (-not $DataRoot) {
    if ($env:FAPAI_DATA_ROOT_HOST) {
        $DataRoot = $env:FAPAI_DATA_ROOT_HOST
    }
    else {
        $localEnvPath = Join-Path $PSScriptRoot "..\docker.local.env"
        if (Test-Path -LiteralPath $localEnvPath) {
            $configuredRoot = Select-String -LiteralPath $localEnvPath -Pattern "^FAPAI_DATA_ROOT_HOST=(.+)$" | Select-Object -First 1
            if ($configuredRoot) {
                $DataRoot = $configuredRoot.Matches[0].Groups[1].Value.Trim()
            }
        }
    }
}

if (-not $DataRoot) {
    $DataRoot = "Z:\project\project\FPFData"
}

function Copy-VolumeToHost {
    param(
        [Parameter(Mandatory = $true)][string]$Volume,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $containerName = "fapaifang-sync-" + [guid]::NewGuid().ToString("N")
    try {
        docker create --name $containerName -v "${Volume}:/from:ro" $Image python -c "print('sync')" | Out-Null
        docker cp "${containerName}:/from/." $Destination
    }
    finally {
        docker rm -f $containerName 2>$null | Out-Null
    }
}

function Backup-PostgresToHost {
    param(
        [Parameter(Mandatory = $true)][string]$Container,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$User,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )

    $runningContainer = docker ps -q --filter "name=^/$Container$"
    if (-not $runningContainer) {
        Write-Output "Postgres container '$Container' is not running; skipped database backup."
        return
    }

    $backupDir = Join-Path $DestinationRoot "postgres\backups"
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $tmpPath = "/tmp/fapaifang-$stamp.dump"
    $destPath = Join-Path $backupDir "fapaifang-$stamp.dump"

    try {
        docker exec -e "PGPASSWORD=$Password" $Container pg_dump -U $User -d $Database -Fc -f $tmpPath
        if ($LASTEXITCODE -ne 0) {
            throw "pg_dump failed for container '$Container'."
        }

        docker cp "${Container}:$tmpPath" $destPath
        if ($LASTEXITCODE -ne 0) {
            throw "docker cp failed for Postgres dump '$tmpPath'."
        }
    }
    finally {
        docker exec $Container rm -f $tmpPath 2>$null | Out-Null
    }

    Write-Output "Postgres backup written to $destPath"
}

New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
Copy-VolumeToHost -Volume "fapaifang_fapaifang-output" -Destination (Join-Path $DataRoot "output")
Copy-VolumeToHost -Volume "fapaifang_fapaifang-datas" -Destination (Join-Path $DataRoot "datas")
Copy-VolumeToHost -Volume "fapaifang_fapaifang-jobs" -Destination (Join-Path $DataRoot "jobs")

if (-not $SkipPostgres) {
    Backup-PostgresToHost `
        -Container $PostgresContainer `
        -Database $PostgresDb `
        -User $PostgresUser `
        -Password $PostgresPassword `
        -DestinationRoot $DataRoot
}

Write-Output "Synced Docker collector volumes to $DataRoot"
