$ErrorActionPreference = 'Stop'

$root = 'C:\fapaifang-worker'
$srcRoot = Join-Path $root 'src'
$sharedRoot = 'C:\Users\Public\nas_home\AI\FPFData'
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

[Environment]::SetEnvironmentVariable('PYTHONIOENCODING', 'utf-8', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_DB_URL', 'postgresql+psycopg://fapaifang:fapaifang@192.168.15.200:55432/fapaifang', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_DB_AUTO_CREATE', '0', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_DB_ENABLE_POSTGIS', '0', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_CDP_ENDPOINT', 'http://127.0.0.1:9223', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES', '0', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_SHARED_DATA_ROOT_HOST', $sharedRoot, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_API_BASE_URL', 'http://192.168.15.200:8001/api', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_CENTRAL_API_BASE_URL', 'http://192.168.15.200:8001/api', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_NODE_ID', 'pc2', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_REPORT_CDP_ENDPOINT', 'http://192.168.15.104:9224', 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_COOKIE_SNAPSHOT', (Join-Path $sharedRoot 'secrets\nodes\pc2\taobao-cookies.json'), 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_COOKIE_SNAPSHOT_PREFER', '0', 'Process')
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
