function Write-SelfHealLog {
  param(
    [Parameter(Mandatory = $true)][string]$Event,
    [hashtable]$Details = @{}
  )

  $payload = [ordered]@{
    ts = (Get-Date).ToString('s')
    event = $Event
  }
  foreach ($key in $Details.Keys) {
    $payload[$key] = $Details[$key]
  }
  Add-Content -LiteralPath $logPath -Value ($payload | ConvertTo-Json -Compress -Depth 6) -Encoding UTF8
}

function New-SelfHealState {
  return [ordered]@{
    consecutive_cdp_failures = 0
    observed_challenge_id = ''
    challenge_first_seen_epoch = 0.0
    last_recovery_epoch = 0.0
    recovery_count = 0
    last_result = 'boot'
  }
}

function Read-SelfHealState {
  $state = New-SelfHealState
  if (-not (Test-Path -LiteralPath $statePath)) {
    return $state
  }
  try {
    $stored = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($key in @($state.Keys)) {
      if ($stored.PSObject.Properties.Name -contains $key) {
        $state[$key] = $stored.$key
      }
    }
  } catch {
    Write-SelfHealLog -Event 'state_read_failed' -Details @{ error = $_.Exception.Message }
  }
  return $state
}

function Write-SelfHealState {
  param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$State)

  $temporary = "$statePath.$PID.tmp"
  $json = $State | ConvertTo-Json -Compress -Depth 5
  [IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding($false)))
  Move-Item -LiteralPath $temporary -Destination $statePath -Force
}

function Invoke-JsonRequest {
  param(
    [Parameter(Mandatory = $true)][string]$Uri,
    [ValidateSet('GET', 'POST')][string]$Method = 'GET',
    [object]$Body = $null,
    [int]$TimeoutSeconds = 5
  )

  $request = [System.Net.HttpWebRequest]::Create($Uri)
  $request.Proxy = $null
  $request.Method = $Method
  $request.Timeout = [Math]::Max($TimeoutSeconds, 1) * 1000
  $request.ReadWriteTimeout = [Math]::Max($TimeoutSeconds, 1) * 1000
  $request.KeepAlive = $false
  if ($Method -eq 'POST') {
    $request.ContentType = 'application/json; charset=utf-8'
    $json = if ($null -eq $Body) { '{}' } else { $Body | ConvertTo-Json -Compress -Depth 6 }
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    $request.ContentLength = $bytes.Length
    $stream = $request.GetRequestStream()
    try {
      $stream.Write($bytes, 0, $bytes.Length)
    } finally {
      $stream.Dispose()
    }
  }

  $response = $null
  $reader = $null
  try {
    $response = [System.Net.HttpWebResponse]$request.GetResponse()
    $reader = New-Object IO.StreamReader($response.GetResponseStream(), [Text.Encoding]::UTF8)
    $content = $reader.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($content)) {
      throw "Empty JSON response from $Uri"
    }
    $parsed = $content | ConvertFrom-Json
    if ($parsed -is [System.Array]) {
      foreach ($item in $parsed) {
        Write-Output $item
      }
      return
    }
    return $parsed
  } finally {
    if ($null -ne $reader) { $reader.Dispose() }
    if ($null -ne $response) { $response.Dispose() }
  }
}

function Get-PropertyValue {
  param(
    $InputObject,
    [Parameter(Mandatory = $true)][string]$Name,
    $DefaultValue = $null
  )

  if ($null -eq $InputObject) { return $DefaultValue }
  $property = $InputObject.PSObject.Properties[$Name]
  if ($null -eq $property) { return $DefaultValue }
  return $property.Value
}
