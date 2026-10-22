param(
    [string]$ProjectRoot = 'C:\Users\QIYUXUAN\Desktop\Endless-Driver-Tutorial - EP9\Endless-Driver-Tutorial - EP9',
    [string]$Destination = 'C:\Users\QIYUXUAN\Desktop\VectorAI_Recovery_Snapshots\20261020_150604'
)
$ErrorActionPreference = 'Stop'
$commit = (& git -C $ProjectRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -ne '4bcce78a1a7764c17cef3c8ad02c7140b60a5baa') { throw 'Unexpected recovery commit.' }
$manifest = Get-Content -LiteralPath (Join-Path $Destination 'source_manifest.json') -Raw | ConvertFrom-Json
$scope = @(Get-Content -LiteralPath (Join-Path $Destination 'git_scope.txt'))
$changed = @(& git -C $ProjectRoot -c core.quotepath=false diff-tree --no-commit-id --name-only -r HEAD)
if (@($changed | Where-Object { $_ -notin $scope }).Count) { throw 'Commit includes an out-of-scope path.' }
if (@(& git -C $ProjectRoot diff --cached --name-only).Count) { throw 'Index not empty after commit.' }
$bundle = Join-Path $Destination 'Unity_history.bundle'
if (Test-Path -LiteralPath $bundle) { throw 'Refusing to overwrite existing bundle.' }
& git -C $ProjectRoot bundle create $bundle --all
if ($LASTEXITCODE -ne 0) { throw 'Git bundle creation failed.' }
$verification = @(& git -C $ProjectRoot bundle verify $bundle 2>&1)
if ($LASTEXITCODE -ne 0) { throw 'Git bundle verification failed.' }
$verification | Set-Content -LiteralPath (Join-Path $Destination 'bundle_verification.txt') -Encoding utf8
$archive = Join-Path $Destination 'Unity_source_snapshot.zip'
$restored = Join-Path $Destination 'restore_check'
if ((Test-Path -LiteralPath $archive) -or (Test-Path -LiteralPath $restored)) { throw 'Restore artifacts already exist.' }
[IO.Compression.ZipFile]::CreateFromDirectory((Join-Path $Destination 'source'), $archive,
    [IO.Compression.CompressionLevel]::Optimal, $false)
[IO.Compression.ZipFile]::ExtractToDirectory($archive, $restored)
$restoredFiles = @(Get-ChildItem -LiteralPath $restored -Recurse -File)
if ($restoredFiles.Count -ne $manifest.Count) { throw 'Restored file count mismatch.' }
foreach ($entry in $manifest) {
    foreach ($root in @($ProjectRoot, (Join-Path $Destination 'source'), $restored)) {
        $path = Join-Path $root $entry.Path
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $entry.SHA256) {
            throw "Hash mismatch: $path"
        }
    }
}
foreach ($path in $scope) {
    $expected = (& git -C $ProjectRoot hash-object --path=$path -- $path).Trim()
    $committed = (& git -C $ProjectRoot rev-parse "${commit}:$path").Trim()
    if ($LASTEXITCODE -ne 0 -or $expected -ne $committed) { throw "Committed content mismatch: $path" }
}
$hashFiles = @('Unity_source_snapshot.zip', 'Unity_history.bundle', 'source_manifest.json', 'git_scope.txt')
$hashes = @($hashFiles | ForEach-Object {
    [pscustomobject]@{ Path = $_; SHA256 = (Get-FileHash -LiteralPath (Join-Path $Destination $_) -Algorithm SHA256).Hash }
})
$hashes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Destination 'artifact_hashes.json') -Encoding utf8
$receipt = [pscustomobject]@{
    Schema = 1; State = 'committed_backup_and_restore_verified'; Commit = $commit;
    ScopedFiles = $scope.Count; ChangedFilesInCommit = $changed.Count;
    SourceFiles = $manifest.Count; RestoredFiles = $restoredFiles.Count;
    WorktreeBytesUnchanged = $true; BackupAndRestoreHashesMatch = $true;
    ScopedCommitContentVerified = $true; BundleVerified = $true;
    IndexEmpty = $true; KnownGoodRelease = $false;
    VerifiedAt = (Get-Date).ToString('o'); BackupPath = $Destination;
    Exclusions = @('Library', 'Temp', 'Logs', 'obj', 'UserSettings', 'ProfilerCaptures',
                   'machine registry', 'backend and raw data', 'deployed standalone game');
    PortabilityLimits = @('Local disk backup, not off-device redundancy',
                          'Git bundle does not contain external Git LFS objects',
                          'Remote package caches excluded; locked dependencies may need network')
}
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Destination 'verification_receipt.json') -Encoding utf8
$receipt | ConvertTo-Json -Depth 5
