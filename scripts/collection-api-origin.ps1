function ConvertTo-CollectionApiOrigin {
    param([AllowEmptyString()][string]$ApiBase)

    if (-not $ApiBase -or $ApiBase -match '[\x00-\x20\x7f\\%]' -or $ApiBase -match '/\.\.?(/|$)') {
        throw 'An explicit HTTPS API origin or protected loopback tunnel is required'
    }
    $api = $null
    if (-not [uri]::TryCreate($ApiBase, [UriKind]::Absolute, [ref]$api) -or
        $api.Scheme -notin @('http', 'https') -or -not $api.Host -or
        $api.UserInfo -or $api.Query -or $api.Fragment -or
        $api.AbsolutePath -notin @('/', '/api', '/api/')) {
        throw 'API base must be an HTTPS API root without credentials, query or fragment'
    }
    $address = $null
    $loopback = $api.DnsSafeHost -eq 'localhost'
    if ([Net.IPAddress]::TryParse($api.DnsSafeHost.Trim('[', ']'), [ref]$address)) {
        $loopback = [Net.IPAddress]::IsLoopback($address)
    }
    if ($api.Scheme -eq 'http' -and -not $loopback) {
        throw 'Collection credentials require HTTPS or a protected loopback tunnel'
    }
    return $api.GetLeftPart([UriPartial]::Authority)
}
