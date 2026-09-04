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
