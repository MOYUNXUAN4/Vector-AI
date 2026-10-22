# Patch 2 (v3) — Revert UIManager GUIStyle Value-Key Cache with Hash Receipt Verification
#
# Key safety checks:
#   1. Verifies patch_receipt.json exists.
#   2. Verifies current target hash exactly matches the post_patch_hash recorded in receipt.
#      If someone modified the file after applying the patch, it REFUSES to overwrite.
#   3. Verifies backup file hash matches pre_patch_hash before restoring.
#   4. Restores target atomically and verifies pre_patch_hash after restoration.

[CmdletBinding()]
param(
    [string]$TargetOverride = "",
    [switch]$SaveCurrentFirst
)

$receiptPath = Join-Path $PSScriptRoot "patch_receipt.json"
if (-not (Test-Path -LiteralPath $receiptPath)) {
    Write-Error "[P2-v3-revert] No patch_receipt.json found at $receiptPath. Cannot verify safe rollback state."
    exit 1
}

$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
$target = if ($TargetOverride) { $TargetOverride } else { $receipt.target }
$preHash = $receipt.pre_patch_hash
$postHash = $receipt.post_patch_hash
$backupFile = $receipt.backup_file

if (-not (Test-Path -LiteralPath $target)) {
    Write-Error "[P2-v3-revert] Target file not found: $target"
    exit 1
}

$currentHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
Write-Host "[P2-v3-revert] Target       : $target"
Write-Host "[P2-v3-revert] Current Hash : $currentHash"
Write-Host "[P2-v3-revert] Expected Post: $postHash"
Write-Host "[P2-v3-revert] Target Pre   : $preHash"

if ($currentHash -eq $preHash) {
    Write-Host "[P2-v3-revert] Target is already in pre-patch state. Cleaning receipt."
    Remove-Item -LiteralPath $receiptPath -Force
    exit 0
}

if ($currentHash -ne $postHash) {
    if (-not $SaveCurrentFirst) {
        Write-Error "[P2-v3-revert] Current target hash ($currentHash) does not match expected post-patch hash ($postHash). Subsequent edits may exist. Refusing to restore backup to prevent data loss. Re-run with -SaveCurrentFirst to archive the edited file first."
        exit 1
    }
    $archiveDir = Join-Path $PSScriptRoot "backups"
    if (-not (Test-Path -LiteralPath $archiveDir)) { New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null }
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $archive = Join-Path $archiveDir ("UIManager.cs.edited_{0}_{1}.bak" -f $stamp, $currentHash.Substring(0, 12))
    Copy-Item -LiteralPath $target -Destination $archive
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash -ne $currentHash) {
        Write-Error "[P2-v3-revert] Archive verification failed; not touching the target."
        exit 1
    }
    Write-Warning "[P2-v3-revert] Edited target archived -> $archive"
}

if (-not (Test-Path -LiteralPath $backupFile)) {
    Write-Error "[P2-v3-revert] Hash-bound backup file missing: $backupFile"
    exit 1
}

$backupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $backupFile).Hash
if ($backupHash -ne $preHash) {
    Write-Error "[P2-v3-revert] Backup file hash ($backupHash) does not match expected pre-patch hash ($preHash). Aborting."
    exit 1
}

# Transactional restore
$guid = [System.Guid]::NewGuid().ToString("N")
$tmpFile = "$target.tmp.$guid"
try {
    Copy-Item -LiteralPath $backupFile -Destination $tmpFile -Force
    Set-ItemProperty -LiteralPath $tmpFile -Name IsReadOnly -Value $false
    Move-Item -LiteralPath $tmpFile -Destination $target -Force
} catch {
    if (Test-Path -LiteralPath $tmpFile) { Remove-Item -LiteralPath $tmpFile -Force }
    Write-Error "[P2-v3-revert] Restore failed: $_"
    exit 1
}

$restoredHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
if ($restoredHash -ne $preHash) {
    Write-Error "[P2-v3-revert] Post-restore verification failed! Restored: $restoredHash, Expected: $preHash"
    exit 1
}

Write-Host "[P2-v3-revert] Target restored and verified with original hash ($restoredHash)."
Remove-Item -LiteralPath $receiptPath -Force
Write-Host "[P2-v3-revert] Removed receipt."
exit 0
