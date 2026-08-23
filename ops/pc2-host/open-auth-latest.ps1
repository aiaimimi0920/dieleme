param(
  [string]$ApiBaseUrl = 'http://192.168.15.200:8001/api',
  [int]$Port = 9223,
  [string]$ProfileDir = 'C:\Users\Public\nas_home\AI\FPFData\edge-cdp-profile-pc2',
  [string]$RequestedUrl = '',
  [switch]$ResetToBlank
)

$ErrorActionPreference = 'Stop'

$defaultUrl = 'https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1'
$startBrowserScript = Join-Path $PSScriptRoot '..\src\scripts\start-taobao-cdp-browser.ps1'
$startBrowserScript = (Resolve-Path -LiteralPath $startBrowserScript).ProviderPath

function ConvertFrom-AuthQueryComponent {
  param([string]$Value)

  $normalized = if ($null -eq $Value) { '' } else { [string]$Value }
  $normalized = $normalized.Replace('+', ' ')
  try {
    return [System.Uri]::UnescapeDataString($normalized)
  }
  catch {
    return $normalized
  }
}

function ConvertFrom-AuthQueryString {
  param([string]$Query)

  $parameters = @{}
  $rawQuery = if ($null -eq $Query) { '' } else { [string]$Query }
  $rawQuery = $rawQuery.TrimStart('?')
  if ([string]::IsNullOrWhiteSpace($rawQuery)) {
    return $parameters
  }

  foreach ($segment in ($rawQuery -split '&')) {
    if ([string]::IsNullOrWhiteSpace($segment)) {
      continue
    }

    $separatorIndex = $segment.IndexOf('=')
    if ($separatorIndex -lt 0) {
      $rawKey = $segment
      $rawValue = ''
    }
    else {
      $rawKey = $segment.Substring(0, $separatorIndex)
      $rawValue = $segment.Substring($separatorIndex + 1)
    }

    $key = ConvertFrom-AuthQueryComponent -Value $rawKey
    if ([string]::IsNullOrWhiteSpace($key)) {
      continue
    }
    $parameters[$key] = ConvertFrom-AuthQueryComponent -Value $rawValue
  }

  return $parameters
}

function ConvertTo-AuthQueryString {
  param(
    [System.Collections.IDictionary]$Parameters,
    [string[]]$Keys
  )

  $parts = foreach ($key in $Keys) {
    if (-not $Parameters.Contains($key)) {
      continue
    }

    $value = [string]$Parameters[$key]
    if ([string]::IsNullOrWhiteSpace($value)) {
      continue
    }

    $encodedKey = [System.Uri]::EscapeDataString([string]$key)
    $encodedValue = [System.Uri]::EscapeDataString($value)
    "$encodedKey=$encodedValue"
  }

  return ($parts -join '&')
}

function Normalize-AuthChallengeUrl {
  param([string]$Url)

  $rawUrl = if ($null -eq $Url) { '' } else { [string]$Url }
  if ([string]::IsNullOrWhiteSpace($rawUrl)) {
    return $defaultUrl
  }

  try {
    $parsed = [System.Uri]$rawUrl.Trim()
  }
  catch {
    return $defaultUrl
  }

  $hostValue = if ($null -eq $parsed.Host) { '' } else { [string]$parsed.Host }
  $path = if ($null -eq $parsed.AbsolutePath) { '' } else { [string]$parsed.AbsolutePath }
  $targetHost = $hostValue.ToLowerInvariant()
  $lowerPath = $path.ToLowerInvariant()

  if ($targetHost.Contains('login.taobao.com') -or $lowerPath.Contains('havanaone/login')) {
    return $defaultUrl
  }

  function Build-ListUrl {
    param(
      [string]$PathValue,
      [System.Collections.IDictionary]$SourceQuery
    )

    $normalizedPath = if ($null -eq $PathValue) { '' } else { [string]$PathValue }
    while ($normalizedPath.Contains('//')) {
      $normalizedPath = $normalizedPath.Replace('//', '/')
    }
    if (-not $normalizedPath.ToLowerInvariant().Contains('/list/')) {
      return $defaultUrl
    }

    $builder = [System.UriBuilder]::new($parsed.Scheme, $parsed.Host)
    $builder.Path = $normalizedPath
    $nextQuery = @{}
    foreach ($key in @('location_code', 'st_param', 'auction_start_seg', 'page')) {
      $value = if ($SourceQuery.Contains($key)) { [string]$SourceQuery[$key] } else { '' }
      if (-not [string]::IsNullOrWhiteSpace($value)) {
        $nextQuery[$key] = $value
      }
    }
    $nextQuery['__captcha_solver_bg'] = '1'
    $builder.Query = ConvertTo-AuthQueryString `
      -Parameters $nextQuery `
      -Keys @('location_code', 'st_param', 'auction_start_seg', 'page', '__captcha_solver_bg')
    return $builder.Uri.AbsoluteUri
  }

  function Build-DetailUrl {
    param([string]$PathValue)

    $normalizedPath = if ($null -eq $PathValue) { '' } else { [string]$PathValue }
    while ($normalizedPath.Contains('//')) {
      $normalizedPath = $normalizedPath.Replace('//', '/')
    }
    if ($normalizedPath.ToLowerInvariant().Contains('/_____tmd_____/punish')) {
      $normalizedPath = $normalizedPath.Split('/_____tmd_____/punish', 2)[0]
    }
    if (-not [regex]::IsMatch($normalizedPath, '^/sf_item/[0-9]+\.htm$', 'IgnoreCase')) {
      return $defaultUrl
    }

    $builder = [System.UriBuilder]::new($parsed.Scheme, 'sf-item.taobao.com')
    $builder.Path = $normalizedPath
    $builder.Query = '__captcha_solver_bg=1'
    return $builder.Uri.AbsoluteUri
  }

  if ($targetHost -eq 'sf-item.taobao.com' -or $lowerPath.Contains('/sf_item/')) {
    return Build-DetailUrl -PathValue $path
  }

  if ($targetHost -ne 'sf.taobao.com') {
    return $defaultUrl
  }

  $query = ConvertFrom-AuthQueryString -Query $parsed.Query

  if ($lowerPath.Contains('/_____tmd_____/punish')) {
    $cleanPath = $path.Split('/_____tmd_____/punish', 2)[0]
    return Build-ListUrl -PathValue $cleanPath -SourceQuery $query
  }

  if ($lowerPath.Contains('/list/')) {
    $query.Remove('x5secdata')
    $query.Remove('x5step')
    return Build-ListUrl -PathValue $path -SourceQuery $query
  }

  return $defaultUrl
}

function Get-LatestSolverTargetUrl {
  try {
    $response = Invoke-WebRequest -Uri "$($ApiBaseUrl.TrimEnd('/'))/status" -UseBasicParsing -TimeoutSec 10
    $payload = $response.Content | ConvertFrom-Json
  }
  catch {
    Write-Host "Could not load collection status from $ApiBaseUrl/status: $($_.Exception.Message)"
    return ''
  }

  $solver = $payload.captcha_solver
  if ($null -eq $solver) {
    return ''
  }

  $lastRequest = $solver.last_request
  if ($null -eq $lastRequest) {
    return ''
  }

  if ($lastRequest.challenge_target_url) {
    return [string]$lastRequest.challenge_target_url
  }
  if ($lastRequest.target_url) {
    return [string]$lastRequest.target_url
  }
  if ($lastRequest.url) {
    return [string]$lastRequest.url
  }
  return ''
}

$rawTargetUrl = if ($ResetToBlank) {
  ''
} elseif ($RequestedUrl) {
  $RequestedUrl
} else {
  Get-LatestSolverTargetUrl
}
$startUrl = if ($ResetToBlank) {
  'about:blank'
} else {
  Normalize-AuthChallengeUrl -Url $rawTargetUrl
}

Write-Host "Resolved auth challenge URL: $startUrl"

& powershell `
  -NoProfile `
  -ExecutionPolicy Bypass `
  -File $startBrowserScript `
  -Port $Port `
  -ProfileDir $ProfileDir `
  -StartUrl $startUrl `
  -ForceNew `
  -TerminateAllBrowserProcesses `
  -UseSystemProxy `
  -DisableExtensions `
  -CdpStartupTimeoutSeconds 120
