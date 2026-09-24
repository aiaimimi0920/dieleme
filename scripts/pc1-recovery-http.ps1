function Invoke-Pc1RecoveryApi {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$ApiBase,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [string]$TokenPath = '',
        [string]$ApiCaFile = '',
        [ValidateSet('status', 'public_status', 'claim', 'snapshot_ready')][string]$Action = 'status',
        $Body = $null
    )

    $helper = Join-Path (Split-Path -Parent $PSScriptRoot) 'tools\pc1_recovery_request.py'
    $payload = @{
        api_base = $ApiBase
        data_root = $DataRoot
        token_path = $TokenPath
        ca_file = $ApiCaFile
        action = $Action
        body = $Body
    } | ConvertTo-Json -Depth 8 -Compress
    $previousEncoding = $OutputEncoding
    try {
        $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
        $output = @($payload | & $Python -I $helper)
        $requestExit = $LASTEXITCODE
    }
    finally {
        $OutputEncoding = $previousEncoding
    }
    try {
        $result = ($output -join "`n") | ConvertFrom-Json
    }
    catch {
        throw 'PC1 recovery transport returned an invalid response'
    }
    if ($requestExit -ne 0) {
        $code = if ($result.code -match '^[a-z_]{1,64}$') { $result.code } else { 'request_failed' }
        throw "PC1 recovery request failed: $code"
    }
    return $result
}
