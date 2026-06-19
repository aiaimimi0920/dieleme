param(
    [string]$DataRoot = "C:\Users\Public\nas_home\AI\FPFData",
    [int]$RecentMinutes = 3,
    [int]$MinRecentSeedItems = 1,
    [int]$StaleSeedMinutes = 3,
    [int]$MissingPayloadThreshold = 20,
    [int]$RecoveryCooldownMinutes = 10,
    [string]$TaskName = "FapaiFangTaobaoLoginWatchdog",
    [string]$TaskPath = "\FapaiFang\",
    [string]$PostgresContainer = "fapaifang-postgres",
    [string]$DbUser = "fapaifang",
    [string]$DbName = "fapaifang",
    [string]$StatePath = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-JsonLine {
    param([Parameter(Mandatory = $true)]$Value)

    $Value | ConvertTo-Json -Compress -Depth 8
}

function Read-RecoveryState {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return @{}
    }

    try {
        $raw = Get-Content -Raw -LiteralPath $Path
        if (-not $raw) {
            return @{}
        }
        return $raw | ConvertFrom-Json
    }
    catch {
        return @{}
    }
}

function Write-RecoveryState {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][datetime]$LastTriggeredAt,
        [Parameter(Mandatory = $true)][object]$Snapshot
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    @{
        LastTriggeredAt = $LastTriggeredAt.ToString("o")
        Snapshot = $Snapshot
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-NullableInt {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }
    return [int]$Value
}

function Get-NullableDouble {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }
    return [double]$Value
}

if ($RecentMinutes -lt 1) {
    throw "RecentMinutes must be at least 1."
}
if ($MinRecentSeedItems -lt 0) {
    throw "MinRecentSeedItems must not be negative."
}
if ($StaleSeedMinutes -lt 1) {
    throw "StaleSeedMinutes must be at least 1."
}
if ($MissingPayloadThreshold -lt 1) {
    throw "MissingPayloadThreshold must be at least 1."
}
if ($RecoveryCooldownMinutes -lt 1) {
    throw "RecoveryCooldownMinutes must be at least 1."
}

if (-not $StatePath) {
    $StatePath = Join-Path $DataRoot "runtime\taobao-login-recovery-monitor-state.json"
}

$sql = @"
with recent_seed as (
    select count(*)::int as cnt
    from fapai_seed_item
    where first_seen_at >= now() - interval '$RecentMinutes minutes'
),
recent_occurrence as (
    select count(*)::int as cnt
    from fapai_seed_occurrence
    where seen_at >= now() - interval '$RecentMinutes minutes'
),
retryable_errors as (
    select count(*)::int as cnt
    from fapai_seed_scan_progress
    where updated_at >= now() - interval '$RecentMinutes minutes'
      and last_error is not null
      and (
        last_error = 'list_payload_missing'
        or last_error like 'ReadTimeout%'
        or last_error ilike '%punish%'
        or last_error ilike '%captcha%'
        or last_error ilike '%challenge%'
      )
),
latest_seed as (
    select round(extract(epoch from (now() - max(first_seen_at))) / 60.0, 2)::text as age_minutes
    from fapai_seed_item
)
select recent_seed.cnt,
       recent_occurrence.cnt,
       retryable_errors.cnt,
       coalesce(latest_seed.age_minutes, '')
from recent_seed, recent_occurrence, retryable_errors, latest_seed;
"@

$queryOutput = & docker exec $PostgresContainer psql -U $DbUser -d $DbName -At -F "|" -c $sql
if ($LASTEXITCODE -ne 0) {
    throw "Postgres seed recovery signal query failed with exit code $LASTEXITCODE."
}

$line = @($queryOutput | Where-Object { $_ }) | Select-Object -First 1
if (-not $line) {
    throw "Postgres seed recovery signal query returned no rows."
}

$parts = $line -split "\|", 4
if ($parts.Count -lt 4) {
    throw "Postgres seed recovery signal query returned malformed output."
}

$recentSeedItems = Get-NullableInt $parts[0]
$recentOccurrences = Get-NullableInt $parts[1]
$retryableErrors = Get-NullableInt $parts[2]
$latestSeedAgeMinutes = Get-NullableDouble $parts[3]
if ($null -eq $latestSeedAgeMinutes) {
    $latestSeedAgeMinutes = 999999.0
}

$seedStalled = (($recentSeedItems -lt $MinRecentSeedItems) -and ($latestSeedAgeMinutes -ge $StaleSeedMinutes))
$errorPressure = ($retryableErrors -ge $MissingPayloadThreshold)
$shouldTrigger = ($seedStalled -and $errorPressure)

$snapshot = [ordered]@{
    recent_minutes = $RecentMinutes
    recent_seed_items = $recentSeedItems
    recent_occurrences = $recentOccurrences
    retryable_error_count = $retryableErrors
    latest_seed_age_minutes = $latestSeedAgeMinutes
    min_recent_seed_items = $MinRecentSeedItems
    stale_seed_minutes = $StaleSeedMinutes
    missing_payload_threshold = $MissingPayloadThreshold
    seed_stalled = $seedStalled
    error_pressure = $errorPressure
    should_trigger = $shouldTrigger
}

if (-not $shouldTrigger) {
    Write-JsonLine ([ordered]@{
        status = "healthy_or_no_recovery_needed"
        snapshot = $snapshot
        note = "This script opens only the official Taobao watchdog when needed and never prints cookie value fields."
    })
    exit 0
}

$state = Read-RecoveryState -Path $StatePath
$lastTriggeredRaw = $state.LastTriggeredAt
if ($lastTriggeredRaw) {
    try {
        $lastTriggeredAt = [datetime]::Parse($lastTriggeredRaw)
        $cooldownEndsAt = $lastTriggeredAt.AddMinutes($RecoveryCooldownMinutes)
        if ((Get-Date) -lt $cooldownEndsAt) {
            Write-JsonLine ([ordered]@{
                status = "recovery_cooldown_active"
                recovery_cooldown_minutes = $RecoveryCooldownMinutes
                last_triggered_at = $lastTriggeredAt.ToString("o")
                cooldown_ends_at = $cooldownEndsAt.ToString("o")
                snapshot = $snapshot
                note = "This script opens only the official Taobao watchdog when needed and never prints cookie value fields."
            })
            exit 0
        }
    }
    catch {
        # Ignore malformed state and allow a fresh trigger.
    }
}

$task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-JsonLine ([ordered]@{
        status = "watchdog_task_missing"
        watchdog_task_name = $TaskName
        watchdog_task_path = $TaskPath
        snapshot = $snapshot
        note = "Register scripts\\register-taobao-login-watchdog-task.ps1 first. This script does not solve captcha, drag sliders, or print cookie value fields."
    })
    exit 2
}

if ([string]$task.State -eq "Running") {
    Write-JsonLine ([ordered]@{
        status = "watchdog_already_running"
        watchdog_task_name = $TaskName
        watchdog_task_path = $TaskPath
        snapshot = $snapshot
        note = "Complete verification in the visible browser window if the configured captcha solver cannot finish it. This script queues the watchdog recovery path and does not print cookie value fields."
    })
    exit 0
}

if ($DryRun) {
    Write-JsonLine ([ordered]@{
        status = "would_trigger_official_watchdog"
        watchdog_task_name = $TaskName
        watchdog_task_path = $TaskPath
        snapshot = $snapshot
        note = "DryRun did not start the official watchdog and never prints cookie value fields."
    })
    exit 0
}

Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
$now = Get-Date
Write-RecoveryState -Path $StatePath -LastTriggeredAt $now -Snapshot $snapshot

Write-JsonLine ([ordered]@{
    status = "triggered_official_watchdog"
    watchdog_task_name = $TaskName
    watchdog_task_path = $TaskPath
    last_triggered_at = $now.ToString("o")
    snapshot = $snapshot
    note = "The login watchdog was started for verification recovery. It queues the configured captcha solver and does not print cookie value fields."
})
