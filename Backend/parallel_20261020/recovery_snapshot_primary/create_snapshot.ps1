param(
    [string]$ProjectRoot = 'C:\Users\QIYUXUAN\Desktop\Endless-Driver-Tutorial - EP9\Endless-Driver-Tutorial - EP9',
    [string]$Destination = 'C:\Users\QIYUXUAN\Desktop\VectorAI_Recovery_Snapshots\20261020_150604'
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (Test-Path -LiteralPath $Destination) { throw 'Destination already exists; refusing to overwrite.' }
$staged = @(& git -C $ProjectRoot diff --cached --name-only)
if ($LASTEXITCODE -ne 0 -or $staged.Count -ne 0) { throw 'Git index is not empty or unavailable.' }
$roots = @('Assets', 'Packages', 'ProjectSettings')
$rootFiles = @('.gitignore', '.gitattributes', 'RECOVERY_BASELINE_20261020.md') |
    Where-Object { Test-Path -LiteralPath (Join-Path $ProjectRoot $_) -PathType Leaf }
$files = @($roots | ForEach-Object { Get-ChildItem -LiteralPath (Join-Path $ProjectRoot $_) -File -Recurse })
$files += @($rootFiles | ForEach-Object { Get-Item -LiteralPath (Join-Path $ProjectRoot $_) })
if (@($files | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
    throw 'Reparse-point file found; manual snapshot review required.'
}
function Relative([string]$Path) {
    return $Path.Substring($ProjectRoot.Length + 1).Replace('\', '/')
}
$scope = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
function Add-Scope([string]$RelativePath) {
    $path = Join-Path $ProjectRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing scope file: $RelativePath" }
    [void]$scope.Add($RelativePath.Replace('\', '/'))
    if ($RelativePath.StartsWith('Assets/')) {
        if (-not $RelativePath.EndsWith('.meta')) {
            $meta = $RelativePath + '.meta'
            if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $meta))) { throw "Missing asset metadata: $meta" }
            [void]$scope.Add($meta)
        }
        $parent = Split-Path $RelativePath -Parent
        while ($parent -and $parent -ne 'Assets') {
            $meta = $parent.Replace('\', '/') + '.meta'
            if (Test-Path -LiteralPath (Join-Path $ProjectRoot $meta) -PathType Leaf) { [void]$scope.Add($meta) }
            $parent = Split-Path $parent -Parent
        }
    }
}
$code = @($files | Where-Object {
    (Relative $_.FullName).StartsWith('Assets/') -and $_.Extension -in @('.cs', '.asmdef', '.asmref')
})
foreach ($file in $code) { Add-Scope (Relative $file.FullName) }
foreach ($folder in @('Assets/Endness Driving/Scenes/Stage', 'Assets/Endness Falling/platform',
                     'Assets/Endness Driving/Prefab/Cars', 'Assets/Settings')) {
    foreach ($file in (Get-ChildItem -LiteralPath (Join-Path $ProjectRoot $folder) -File -Recurse)) {
        if ($file.Extension -in @('.unity', '.prefab', '.asset')) { Add-Scope (Relative $file.FullName) }
    }
}
foreach ($path in @('Assets/Endness Falling/EndnessFallingEditor/CalibrationPlatform.fbx',
                    'Assets/UniversalRenderPipelineGlobalSettings.asset',
                    'Packages/manifest.json', 'Packages/packages-lock.json')) { Add-Scope $path }
foreach ($file in (Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'ProjectSettings') -File)) {
    Add-Scope (Relative $file.FullName)
}
foreach ($path in $rootFiles) { Add-Scope $path }
New-Item -ItemType Directory -Path $Destination | Out-Null
$source = Join-Path $Destination 'source'
New-Item -ItemType Directory -Path $source | Out-Null
$before = @($files | Sort-Object FullName | ForEach-Object {
    [pscustomobject]@{ Path = Relative $_.FullName; Bytes = $_.Length;
        SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
})
foreach ($entry in $before) {
    $target = Join-Path $source $entry.Path
    $parent = Split-Path $target -Parent
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $entry.Path) -Destination $target
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $entry.SHA256) { throw "Backup mismatch: $($entry.Path)" }
    if ((Get-FileHash -LiteralPath (Join-Path $ProjectRoot $entry.Path) -Algorithm SHA256).Hash -ne $entry.SHA256) {
        throw "Source changed during copy: $($entry.Path)"
    }
}
$before | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Destination 'source_manifest.json') -Encoding utf8
@($scope | Sort-Object) | Set-Content -LiteralPath (Join-Path $Destination 'git_scope.txt') -Encoding utf8
& git -C $ProjectRoot -c core.quotepath=false status --porcelain=v1 -uall |
    Set-Content -LiteralPath (Join-Path $Destination 'git_status_before.txt') -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'Cannot save Git status.' }
$receipt = [pscustomobject]@{
    Schema = 1; ProjectRoot = $ProjectRoot; Destination = $Destination;
    Created = (Get-Date).ToString('o'); HeadBefore = (& git -C $ProjectRoot rev-parse HEAD);
    SourceFiles = $before.Count; SourceBytes = ($before | Measure-Object Bytes -Sum).Sum;
    ScopedFiles = $scope.Count; BackupHashesVerified = $true;
    State = 'backup_verified_before_staging'; KnownGoodRelease = $false
}
$receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Destination 'backup_receipt.json') -Encoding utf8
$receipt | ConvertTo-Json -Depth 4
