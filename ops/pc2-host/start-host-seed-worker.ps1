$ctx = & 'C:\fapaifang-worker\ops\load-host-worker-env.ps1'
Set-Location $ctx.SrcRoot
$outputDir = Join-Path $ctx.SharedRoot 'output\nodes\pc2-host\seed_collector'
$jobsFile = Join-Path $ctx.SharedRoot 'jobs\seed_jobs_all.json'
$workerId = if ($env:FAPAI_HOST_SEED_WORKER_ID) { $env:FAPAI_HOST_SEED_WORKER_ID } else { 'pc2-host-seed-1' }
$pagesPerRun = if ($env:FAPAI_SEED_PAGES_PER_RUN) { $env:FAPAI_SEED_PAGES_PER_RUN } else { '20' }
$failureCooldownThreshold = if ($env:FAPAI_SEED_FAILURE_COOLDOWN_THRESHOLD) { $env:FAPAI_SEED_FAILURE_COOLDOWN_THRESHOLD } else { '10' }
$failureCooldownSeconds = if ($env:FAPAI_SEED_FAILURE_COOLDOWN_SECONDS) { $env:FAPAI_SEED_FAILURE_COOLDOWN_SECONDS } else { '120' }
$apiBaseUrl = if ($env:FAPAI_API_BASE_URL) { $env:FAPAI_API_BASE_URL } else { 'http://192.168.15.200:8001/api' }
if (-not $env:FAPAI_LIST_BROWSER_FALLBACK) {
  [Environment]::SetEnvironmentVariable('FAPAI_LIST_BROWSER_FALLBACK', '1', 'Process')
}

$args = @(
  'tools\seed_collector.py',
  '--output-dir', $outputDir,
  '--cdp-endpoint', 'http://127.0.0.1:9223',
  '--job-key', 'guangdong-guangzhou-nansha-50025969',
  '--province', 'Guangdong',
  '--city', 'Guangzhou',
  '--district', 'Nansha',
  '--location-code', '440115',
  '--category', '50025969',
  '--sorts', 'sort_0:0:default,sort_3:3:price_desc,bid_desc:2:bids_desc,end_time_soon:1:end_soon,sort_4:4:sort4,sort_5:5:sort5',
  '--max-page', '83',
  '--worker-id', $workerId,
  '--loop',
  '--pages-per-run', $pagesPerRun,
  '--active-loop-interval-seconds', '10',
  '--loop-interval-seconds', '60',
  '--auth-probe-interval-seconds', '10',
  '--api-base-url', $apiBaseUrl,
  '--jobs-file', $jobsFile,
  '--failure-cooldown-threshold', $failureCooldownThreshold,
  '--failure-cooldown-seconds', $failureCooldownSeconds,
  '--parallel-sorts',
  '--solver-enabled'
)

& $ctx.Python @args
