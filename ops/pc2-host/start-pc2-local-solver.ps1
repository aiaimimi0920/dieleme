param(
  [string]$ApiBaseUrl = 'http://192.168.15.200:8001/api',
  [string]$CdpEndpoint = 'http://127.0.0.1:9223',
  [string]$NodeId = 'pc2'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = 'C:\fapaifang-worker'
$sourceRoot = Join-Path $root 'src'
$envFile = Join-Path $root 'env.worker.local'
$python = Join-Path $root 'venv-host\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  $python = 'C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe'
}

$solverRuntimeDefaults = [ordered]@{
  FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED = '0'
  FAPAI_SOLVER_COOLDOWN_FAIL_THRESHOLD = '10'
  FAPAI_SOLVER_COOLDOWN_SECONDS = '180'
  FAPAI_SLIDER_RETRY_INTERVAL_SECONDS = '5'
  FAPAI_LOCAL_SOLVER_POLL_SECONDS = '5'
}
foreach ($name in $solverRuntimeDefaults.Keys) {
  $value = [Environment]::GetEnvironmentVariable($name, 'Process')
  if (-not $value -and (Test-Path -LiteralPath $envFile)) {
    $setting = Get-Content -LiteralPath $envFile | Where-Object {
      $_.Trim() -match "^$([regex]::Escape($name))="
    } | Select-Object -Last 1
    if ($setting) {
      $value = $setting.Substring($setting.IndexOf('=') + 1).Trim()
    }
  }
  if (-not $value) {
    $value = $solverRuntimeDefaults[$name]
  }
  [Environment]::SetEnvironmentVariable($name, $value, 'Process')
}

[Environment]::SetEnvironmentVariable('FAPAI_API_BASE_URL', $ApiBaseUrl, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_CDP_ENDPOINT', $CdpEndpoint, 'Process')
[Environment]::SetEnvironmentVariable('FAPAI_NODE_ID', $NodeId, 'Process')
[Environment]::SetEnvironmentVariable('PYTHONUNBUFFERED', '1', 'Process')

Set-Location -LiteralPath $sourceRoot
& $python '.\tools\pc2_local_solver.py' `
  --api-base-url $ApiBaseUrl `
  --cdp-endpoint $CdpEndpoint `
  --node-id $NodeId
exit $LASTEXITCODE
