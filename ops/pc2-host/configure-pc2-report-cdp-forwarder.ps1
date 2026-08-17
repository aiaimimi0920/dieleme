param(
  [string]$ListenAddress = '192.168.15.104',
  [int]$ReportPort = 9224,
  [string]$TargetAddress = '127.0.0.1',
  [int]$TargetPort = 9223
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

& netsh.exe interface portproxy delete v4tov4 `
  listenaddress=$ListenAddress `
  listenport=$ReportPort | Out-Null

& netsh.exe interface portproxy add v4tov4 `
  listenaddress=$ListenAddress `
  listenport=$ReportPort `
  connectaddress=$TargetAddress `
  connectport=$TargetPort | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw 'Failed to configure the PC2 report CDP forwarder.'
}

$target = Test-NetConnection $TargetAddress -Port $TargetPort -WarningAction SilentlyContinue
if (-not $target.TcpTestSucceeded) {
  throw "PC2 solver CDP target is not reachable at $TargetAddress`:$TargetPort."
}

Write-Output ([pscustomobject]@{
  ListenEndpoint = "$ListenAddress`:$ReportPort"
  TargetEndpoint = "$TargetAddress`:$TargetPort"
  Healthy = $true
})
