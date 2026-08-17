param(
    [string]$DataRoot = "C:\Users\Public\nas_home\AI\FPFData",
    [string]$ApiBaseUrl = "",
    [string]$AlertWebhookUrl = "",
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
$resolvedAlertWebhookUrl = if ($AlertWebhookUrl) { $AlertWebhookUrl } else { [string]$env:FAPAI_OPERATIONS_WEBHOOK_URL }

function Write-JsonLine {
    param([Parameter(Mandatory = $true)]$Value)

    $Value | ConvertTo-Json -Compress -Depth 8
}

function Send-OperationalAlert {
    param(
        [Parameter(Mandatory = $true)][string]$EventName,
        [Parameter(Mandatory = $true)][hashtable]$Payload
    )

    if (-not $resolvedAlertWebhookUrl) {
        return
    }
    try {
        $body = [ordered]@{
            source = "trigger-taobao-login-recovery-if-needed"
            event = $EventName
            observed_at = (Get-Date).ToString("o")
            host = $env:COMPUTERNAME
            payload = $Payload
        } | ConvertTo-Json -Depth 8 -Compress
        Invoke-RestMethod `
            -Uri $resolvedAlertWebhookUrl `
            -Method Post `
            -ContentType "application/json" `
            -Body $body `
            -TimeoutSec 10 | Out-Null
    }
    catch {
        Write-Warning ("Operational alert delivery failed: {0}" -f $_.Exception.Message)
    }
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

function Resolve-ApiBaseUrl {
    param([string]$Value)

    $candidate = if ($Value) {
        $Value
    } elseif ($env:FAPAI_API_BASE_URL) {
        $env:FAPAI_API_BASE_URL
    } elseif ($env:FAPAI_CENTRAL_API_BASE_URL) {
        $env:FAPAI_CENTRAL_API_BASE_URL
    } else {
        "http://192.168.15.200:8001/api"
    }
    return ([string]$candidate).TrimEnd("/")
}

function Get-PostgresSignalSnapshot {
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

    $latestSeedAgeMinutes = Get-NullableDouble $parts[3]
    if ($null -eq $latestSeedAgeMinutes) {
        $latestSeedAgeMinutes = 999999.0
    }

    return [ordered]@{
        signal_source = "postgres_container"
        recent_seed_items = Get-NullableInt $parts[0]
        recent_occurrences = Get-NullableInt $parts[1]
        retryable_error_count = Get-NullableInt $parts[2]
        latest_seed_age_minutes = $latestSeedAgeMinutes
        collection_paused = $null
        summary_last_reason = $null
        summary_last_decision = $null
        api_status_reached = $false
    }
}

function Get-SeedSummarySignalSnapshot {
    $seedSummaryPath = Join-Path $DataRoot "output\nodes\pc2-real\seed_collector\seed_collector_summary.json"
    if (-not (Test-Path -LiteralPath $seedSummaryPath)) {
        throw "Seed summary does not exist for recovery fallback: $seedSummaryPath"
    }

    $summary = Get-Content -Raw -LiteralPath $seedSummaryPath | ConvertFrom-Json
    $summaryItem = Get-Item -LiteralPath $seedSummaryPath
    $cycleSummary = if ($null -ne $summary.cycle_summary) { $summary.cycle_summary } else { $null }
    $recentSeedItems = if ($null -ne $cycleSummary -and $null -ne $cycleSummary.items_collected) {
        [int]$cycleSummary.items_collected
    } elseif ($null -ne $summary.new_occurrences) {
        [int]$summary.new_occurrences
    } else {
        0
    }
    $recentOccurrences = if ($null -ne $cycleSummary -and $null -ne $cycleSummary.new_occurrences) {
        [int]$cycleSummary.new_occurrences
    } elseif ($null -ne $cycleSummary -and $null -ne $cycleSummary.items_seen) {
        [int]$cycleSummary.items_seen
    } else {
        0
    }
    $retryableErrors = if ($null -ne $summary.retryable_failures) {
        [int]$summary.retryable_failures
    } elseif ($null -ne $cycleSummary -and $null -ne $cycleSummary.retryable_failures) {
        [int]$cycleSummary.retryable_failures
    } else {
        0
    }
    $apiStatus = $null
    $apiBaseResolved = Resolve-ApiBaseUrl -Value $ApiBaseUrl
    try {
        $apiStatus = Invoke-RestMethod -Uri "$apiBaseResolved/status" -TimeoutSec 5
    } catch {
        $apiStatus = $null
    }

    return [ordered]@{
        signal_source = "seed_summary"
        recent_seed_items = $recentSeedItems
        recent_occurrences = $recentOccurrences
        retryable_error_count = $retryableErrors
        latest_seed_age_minutes = [Math]::Round(((Get-Date) - $summaryItem.LastWriteTime).TotalMinutes, 2)
        collection_paused = if ($null -ne $apiStatus) { $apiStatus.paused -eq $true } else { $null }
        summary_last_reason = [string]$summary.last_reason
        summary_last_decision = [string]$summary.last_decision
        summary_path = $seedSummaryPath
        api_status_reached = ($null -ne $apiStatus)
    }
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

$usePostgresSignals = $false
try {
    $containerNames = @(& docker ps -a --format "{{.Names}}" 2>$null)
    if ($LASTEXITCODE -eq 0 -and ($containerNames -contains $PostgresContainer)) {
        $usePostgresSignals = $true
    }
} catch {
    $usePostgresSignals = $false
}

$signal = if ($usePostgresSignals) {
    Get-PostgresSignalSnapshot
} else {
    Get-SeedSummarySignalSnapshot
}

$recentSeedItems = $signal.recent_seed_items
$recentOccurrences = $signal.recent_occurrences
$retryableErrors = $signal.retryable_error_count
$latestSeedAgeMinutes = $signal.latest_seed_age_minutes
$challengePressure = (
    [string]$signal.summary_last_reason -match "punish|captcha|challenge" -or
    [string]$signal.summary_last_decision -eq "seed_page_retryable_failure"
)
$seedStalled = (
    ($recentSeedItems -lt $MinRecentSeedItems) -and
    (($latestSeedAgeMinutes -ge $StaleSeedMinutes) -or $challengePressure)
)
$errorPressure = (($retryableErrors -ge $MissingPayloadThreshold) -or $challengePressure)
$shouldTrigger = ($seedStalled -and $errorPressure)

$snapshot = [ordered]@{
    signal_source = $signal.signal_source
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
    collection_paused = $signal.collection_paused
    summary_last_reason = $signal.summary_last_reason
    summary_last_decision = $signal.summary_last_decision
    api_status_reached = $signal.api_status_reached
}
if ($signal.Contains("summary_path")) {
    $snapshot.summary_path = $signal.summary_path
}

if ($snapshot.collection_paused -eq $true) {
    Send-OperationalAlert -EventName "collection_paused_for_auth" -Payload @{
        snapshot = $snapshot
        task_name = $TaskName
        task_path = $TaskPath
    }
    Write-JsonLine ([ordered]@{
        status = "collection_paused"
        snapshot = $snapshot
        note = "Collection is already paused for auth recovery. This script will not start another watchdog instance."
    })
    exit 0
}

# Manual auth escalation is the primary PC1 fallback signal from PC2's local solver.
# When manual_required is true, run the official watchdog so a human on PC1 can
# complete verification in the visible browser window.
$apiBaseResolvedForManualCheck = Resolve-ApiBaseUrl -Value $ApiBaseUrl
$manualAuthRequired = $false
$manualSolverSnapshot = $null
try {
    $apiStatusForManualCheck = Invoke-RestMethod -Uri "$apiBaseResolvedForManualCheck/status" -TimeoutSec 5
    if ($null -ne $apiStatusForManualCheck) {
        $manualSolverSnapshot = $apiStatusForManualCheck.captcha_solver
        $manualAuthRequired = ([bool]$manualSolverSnapshot.manual_required -or [bool]$manualSolverSnapshot.force_unlock_flag_exists)
    }
} catch {
    $manualAuthRequired = $false
}
$snapshot | Add-Member -NotePropertyName manual_auth_required -NotePropertyValue $manualAuthRequired
$snapshot | Add-Member -NotePropertyName manual_solver_status -NotePropertyValue $manualSolverSnapshot -Force

if ($manualAuthRequired -and $snapshot.signal_source -eq "postgres_container") {
    try {
        $apiStatusRefresh = Invoke-RestMethod -Uri "$apiBaseResolvedForManualCheck/status" -TimeoutSec 5
        if ($null -ne $apiStatusRefresh) {
            $snapshot.collection_paused = $apiStatusRefresh.paused -eq $true
        }
    } catch {
    }
}

if ($manualAuthRequired) {
    Send-OperationalAlert -EventName "manual_auth_required" -Payload @{
        snapshot = $snapshot
        task_name = $TaskName
        task_path = $TaskPath
        note = "PC1 official watchdog requested for manual Taobao verification."
    }
    $state = Read-RecoveryState -Path $StatePath
    $lastTriggeredRaw = $state.LastTriggeredAt
    if ($lastTriggeredRaw) {
        try {
            $lastTriggeredAt = [datetime]::Parse($lastTriggeredRaw)
            $cooldownEndsAt = $lastTriggeredAt.AddMinutes($RecoveryCooldownMinutes)
            if ((Get-Date) -lt $cooldownEndsAt) {
                Write-JsonLine ([ordered]@{
                    status = "manual_auth_recovery_cooldown_active"
                    recovery_cooldown_minutes = $RecoveryCooldownMinutes
                    last_triggered_at = $lastTriggeredAt.ToString("o")
                    cooldown_ends_at = $cooldownEndsAt.ToString("o")
                    snapshot = $snapshot
                    note = "Manual auth already requested recently. This script will not start the watchdog during cooldown."
                })
                exit 0
            }
        }
        catch {
        }
    }

    $task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Send-OperationalAlert -EventName "watchdog_task_missing" -Payload @{
            snapshot = $snapshot
            task_name = $TaskName
            task_path = $TaskPath
        }
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
            status = "manual_auth_watchdog_already_running"
            watchdog_task_name = $TaskName
            watchdog_task_path = $TaskPath
            snapshot = $snapshot
            note = "Complete verification in the visible browser window. This script queues the watchdog recovery path and does not print cookie value fields."
        })
        exit 0
    }

    if ($DryRun) {
        Write-JsonLine ([ordered]@{
            status = "would_trigger_manual_auth_watchdog"
            watchdog_task_name = $TaskName
            watchdog_task_path = $TaskPath
            snapshot = $snapshot
            note = "DryRun did not start the official watchdog for manual Taobao verification and never prints cookie value fields."
        })
        exit 0
    }

    Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
    $now = Get-Date
    Write-RecoveryState -Path $StatePath -LastTriggeredAt $now -Snapshot $snapshot
    Send-OperationalAlert -EventName "triggered_manual_auth_watchdog" -Payload @{
        snapshot = $snapshot
        task_name = $TaskName
        task_path = $TaskPath
        last_triggered_at = $now.ToString("o")
    }
    Write-JsonLine ([ordered]@{
        status = "triggered_manual_auth_watchdog"
        watchdog_task_name = $TaskName
        watchdog_task_path = $TaskPath
        last_triggered_at = $now.ToString("o")
        snapshot = $snapshot
        note = "The login watchdog was started for manual Taobao verification. This script queues the configured captcha solver and does not print cookie value fields."
    })
    exit 0
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
    Send-OperationalAlert -EventName "watchdog_task_missing" -Payload @{
        snapshot = $snapshot
        task_name = $TaskName
        task_path = $TaskPath
    }
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
Send-OperationalAlert -EventName "triggered_official_watchdog" -Payload @{
    snapshot = $snapshot
    task_name = $TaskName
    task_path = $TaskPath
    last_triggered_at = $now.ToString("o")
}

Write-JsonLine ([ordered]@{
    status = "triggered_official_watchdog"
    watchdog_task_name = $TaskName
    watchdog_task_path = $TaskPath
    last_triggered_at = $now.ToString("o")
    snapshot = $snapshot
    note = "The login watchdog was started for verification recovery. It queues the configured captcha solver and does not print cookie value fields."
})
