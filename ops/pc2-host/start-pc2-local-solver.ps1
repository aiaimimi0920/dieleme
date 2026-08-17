param(
  [string]$ApiBaseUrl = 'http://192.168.15.200:8001/api',
  [string]$CdpEndpoint = 'http://127.0.0.1:9223',
  [string]$NodeId = 'pc2'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = 'C:\fapaifang-worker'
$sourceRoot = Join-Path $root 'src'
$python = Join-Path $root 'venv-host\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  $python = 'C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe'
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
