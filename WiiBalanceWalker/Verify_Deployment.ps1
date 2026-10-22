param([string]$DeploymentRoot = $PSScriptRoot)

function Get-DeploymentHash([string]$FilePath) {
    $stream = [IO.File]::OpenRead($FilePath)
    $provider = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($provider.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $provider.Dispose()
        $stream.Dispose()
    }
}

$ErrorActionPreference = 'Stop'
try {
    $rootPath = (Resolve-Path -LiteralPath $DeploymentRoot).Path
    $manifestPath = Join-Path $rootPath 'deployment_manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $allowedNames = @('WiiBalanceWalker.exe', 'WiiBalanceWalker.pdb', 'WiiBalanceWalker.exe.config',
        'InTheHand.Net.Personal.dll', 'vJoyInterface.dll', 'vJoyInterfaceWrap.dll', 'WiimoteLib.dll')
    if ($manifest.schema_version -ne 1 -or $manifest.entry_executable -cne 'WiiBalanceWalker.exe') {
        throw 'Unsupported manifest or executable name.'
    }
    $entries = @($manifest.runtime_files)
    if ($entries.Count -ne $allowedNames.Count) { throw 'Expected exactly seven deployment files.' }
    $seen = @{}
    foreach ($entry in $entries) {
        $name = [string]$entry.path
        if ($allowedNames -cnotcontains $name -or $seen.ContainsKey($name)) {
            throw ('Unexpected or duplicate deployment path: ' + $name)
        }
        $seen[$name] = $true
        if ([string]$entry.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            $null -eq $entry.size -or [long]$entry.size -le 0) { throw ('Invalid manifest entry: ' + $name) }
        $filePath = Join-Path $rootPath $name
        $file = Get-Item -LiteralPath $filePath
        if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw ('Expected an ordinary deployment file: ' + $name)
        }
        if ($file.Length -ne [long]$entry.size) { throw ('File size differs: ' + $name) }
        $actualHash = Get-DeploymentHash $filePath
        if ($actualHash -cne [string]$entry.sha256) { throw ('SHA256 differs: ' + $name) }
    }
    if ($manifest.symbols.exe_codeview_guid -cne $manifest.symbols.pdb_guid -or
        $manifest.symbols.exe_codeview_age -ne $manifest.symbols.pdb_age -or
        [string]::IsNullOrWhiteSpace($manifest.symbols.pdb_guid)) {
        throw 'Manifest does not record a matched EXE/PDB pair.'
    }
    Write-Output ('[WII DEPLOYMENT] PASS: seven files match ' + $manifest.deployment_id)
    Write-Output '[WII DEPLOYMENT] File identity only; no program started or board connection tested.'
    exit 0
}
catch {
    [Console]::Error.WriteLine('[WII DEPLOYMENT BLOCKED] ' + $_.Exception.Message)
    exit 1
}
