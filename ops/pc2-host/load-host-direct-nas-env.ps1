$ErrorActionPreference = 'Stop'

$root = 'C:\fapaifang-worker'
$srcRoot = Join-Path $root 'src'
$envFile = Join-Path $root 'env.worker.local'

if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    $idx = $line.IndexOf('=')
    if ($idx -lt 1) { return }
    $name = $line.Substring(0, $idx).Trim()
    $value = $line.Substring($idx + 1)
    [Environment]::SetEnvironmentVariable($name, $value, 'Process')
  }
}

$sharedRoot = if ($env:FAPAI_NAS_SHARE_ROOT) { $env:FAPAI_NAS_SHARE_ROOT } else { '\\192.168.15.200\home\project\project\FPFData' }
$shareMount = if ($env:FAPAI_NAS_SHARE_MOUNT) { $env:FAPAI_NAS_SHARE_MOUNT } else { '\\192.168.15.200\home' }
$shareUser = [string]($env:FAPAI_NAS_SHARE_USER)
$sharePassword = [string]($env:FAPAI_NAS_SHARE_PASSWORD)
$listBrowserFallback = if ($env:FAPAI_LIST_BROWSER_FALLBACK) { $env:FAPAI_LIST_BROWSER_FALLBACK } else { '1' }
$detailBrowserFallback = if ($env:FAPAI_DETAIL_BROWSER_FALLBACK) { $env:FAPAI_DETAIL_BROWSER_FALLBACK } else { '1' }
$detailLoadOpenBrowserPages = if ($env:FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES) { $env:FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES } else { '0' }
$captchaSolverEnabled = if ($env:FAPAI_CAPTCHA_SOLVER_ENABLED) { $env:FAPAI_CAPTCHA_SOLVER_ENABLED } else { '1' }
$realTaobaoAutoSolverEnabled = if ($env:FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED) { $env:FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED } else { '0' }
$seedCaptchaSolverEnabled = if ($env:FAPAI_SEED_CAPTCHA_SOLVER_ENABLED) { $env:FAPAI_SEED_CAPTCHA_SOLVER_ENABLED } else { $captchaSolverEnabled }
$detailCaptchaSolverEnabled = if ($env:FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED) { $env:FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED } else { $captchaSolverEnabled }

if ($shareUser -and $sharePassword) {
  & cmd /c "cmdkey /add:192.168.15.200 /user:$shareUser /pass:$sharePassword >nul 2>nul" | Out-Null
  $netUseTarget = if ($shareMount -eq '\\192.168.15.200\home') { '\\192.168.15.200\home' } else { $shareMount }
  & cmd /c "net use \\192.168.15.200\home /user:$shareUser $sharePassword /persistent:yes >nul 2>nul" | Out-Null
  if ($netUseTarget -ne '\\192.168.15.200\home') {
    & cmd /c "net use $netUseTarget /user:$shareUser $sharePassword /persistent:yes >nul 2>nul" | Out-Null
  }
}

[Environment]::SetEnvironmentVariable('PYTHONIOENCODING', 'utf-8', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_DB_URL', 'postgresql+psycopg://fapaifang:fapaifang@192.168.15.200:55432/fapaifang', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_DB_AUTO_CREATE', '0', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_DB_ENABLE_POSTGIS', '0', 'Process')
$cdpEndpoint = if ($env:FAPAI_CDP_ENDPOINT) {
  $env:FAPAI_CDP_ENDPOINT
} else {
  'http://127.0.0.1:9223'
}
$detailCdpEndpoint = if ($env:FAPAI_DETAIL_CDP_ENDPOINT) {
  $env:FAPAI_DETAIL_CDP_ENDPOINT
} else {
  $cdpEndpoint
}
[Environment]::SetEnvironmentVariable('FAPAI_CDP_ENDPOINT', $cdpEndpoint, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_DETAIL_CDP_ENDPOINT', $detailCdpEndpoint, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_LIST_BROWSER_FALLBACK', $listBrowserFallback, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_DETAIL_BROWSER_FALLBACK', $detailBrowserFallback, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES', $detailLoadOpenBrowserPages, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_SHARED_DATA_ROOT_HOST', $sharedRoot, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_API_BASE_URL', 'http://192.168.15.200:8001/api', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_CENTRAL_API_BASE_URL', 'http://192.168.15.200:8001/api', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_NODE_ID', 'pc2', 'Process')
$reportCdpEndpoint = if ($env:FAPAI_REPORT_CDP_ENDPOINT) { $env:FAPAI_REPORT_CDP_ENDPOINT } else { 'http://192.168.15.104:9224' }
[Environment]::SetEnvironmentVariable('FAPAI_REPORT_CDP_ENDPOINT', $reportCdpEndpoint, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_COOKIE_SNAPSHOT', (Join-Path $sharedRoot 'secrets\nodes\pc2\taobao-cookies.json'), 'Process')
$cookieSnapshotPrefer = if ($env:FAPAI_COOKIE_SNAPSHOT_PREFER) { $env:FAPAI_COOKIE_SNAPSHOT_PREFER } else { '0' }
[Environment]::SetEnvironmentVariable('FAPAI_COOKIE_SNAPSHOT_PREFER', $cookieSnapshotPrefer, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_CAPTCHA_SOLVER_ENABLED', $captchaSolverEnabled, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED', $realTaobaoAutoSolverEnabled, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_SEED_CAPTCHA_SOLVER_ENABLED', $seedCaptchaSolverEnabled, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED', $detailCaptchaSolverEnabled, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_SEED_JOBS_FILE', (Join-Path $sharedRoot 'jobs\seed_jobs_all.json'), 'Process')

$srcSecrets = Join-Path $srcRoot 'secrets.json'
$nestedSecrets = Join-Path $srcRoot 'src\secrets.json'

if ((Test-Path $srcSecrets) -and -not (Test-Path $nestedSecrets)) {
  New-Item -ItemType Directory -Force -Path (Join-Path $srcRoot 'src') | Out-Null
  Copy-Item $srcSecrets $nestedSecrets -Force
}

[pscustomobject]@{
  Root = $root
  SrcRoot = $srcRoot
  SharedRoot = $sharedRoot
  Python = 'C:\fapaifang-worker\venv-host\Scripts\python.exe'
}
