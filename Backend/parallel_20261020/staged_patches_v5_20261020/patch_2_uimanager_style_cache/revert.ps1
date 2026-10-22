# Patch 2 (v5) — Revert, target-bound and receipt-verified
#
# v5 fixes two safety gaps from the 2026-10-20 review:
#   1. -TargetOverride no longer bypasses target identity: the override must
#      normalise to the receipt's target, otherwise the revert refuses (exit 8).
#   2. A pending-only state (crash between replacement and commit) is understood:
#      pre-patch hash means nothing to undo, intended post hash means "restore".
#
# The backup is hashed and compared with the receipt pre-patch hash BEFORE the
# target is modified.

[CmdletBinding()]
param(
    [string]$TargetOverride = "",
    [string]$ReceiptDir = "",
    [string]$BackupDir = "",
    [switch]$SaveCurrentFirst
)

$ErrorActionPreference = "Continue"

function Get-NormalizedPath([string]$p) {
    $full = [System.IO.Path]::GetFullPath($p)
    return $full.TrimEnd([char[]]@('\', '/')).ToLowerInvariant()
}

function Get-Sha256([string]$p) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash
}

function Read-Json([string]$p) {
    return (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json)
}

$receiptRoot = if ($ReceiptDir) { $ReceiptDir } else { $PSScriptRoot }
$receiptPath = Join-Path $receiptRoot "patch_receipt.json"
$pendingPath = Join-Path $receiptRoot "patch_receipt.pending.json"

$receipt = $null
if (Test-Path -LiteralPath $receiptPath) {
    $receipt = Read-Json $receiptPath
} elseif (Test-Path -LiteralPath $pendingPath) {
    $pend = Read-Json $pendingPath
    Write-Warning "[P2-v5-revert] Only a pending receipt exists; treating it as the applied state if the hash matches."
    $receipt = [PSCustomObject]@{
        target          = $pend.target
        pre_patch_hash  = $pend.pre_patch_hash
        post_patch_hash = $pend.intended_post_hash
        backup_file     = $pend.backup_file
    }
} else {
    Write-Error "[P2-v5-revert] No receipt and no pending receipt in $receiptRoot. Cannot verify a safe rollback."
    exit 1
}

$target = if ($TargetOverride) { $TargetOverride } else { $receipt.target }
if (-not $receipt.target) {
    Write-Error "[P2-v5-revert] Receipt has no target field; refusing."
    exit 8
}
if ((Get-NormalizedPath $receipt.target) -ne (Get-NormalizedPath $target)) {
    Write-Error "[P2-v5-revert] TargetOverride does not match the receipt target. Receipt: $($receipt.target) | Override: $target"
    exit 8
}

$preHash = $receipt.pre_patch_hash
$postHash = $receipt.post_patch_hash
$backupFile = $receipt.backup_file

if (-not (Test-Path -LiteralPath $target)) {
    Write-Error "[P2-v5-revert] Target file not found: $target"
    exit 1
}

$currentHash = Get-Sha256 $target
Write-Host "[P2-v5-revert] Target       : $target"
Write-Host "[P2-v5-revert] Current Hash : $currentHash"
Write-Host "[P2-v5-revert] Expected Post: $postHash"
Write-Host "[P2-v5-revert] Target Pre   : $preHash"

if ($currentHash -eq $preHash) {
    Write-Host "[P2-v5-revert] Target is already in the pre-patch state. Cleaning receipts."
    Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $pendingPath -Force -ErrorAction SilentlyContinue
    exit 0
}

if ($currentHash -ne $postHash) {
    if (-not $SaveCurrentFirst) {
        Write-Error "[P2-v5-revert] Current hash $currentHash != expected post-patch hash $postHash. Later edits may exist. Refusing. Re-run with -SaveCurrentFirst to archive first."
        exit 1
    }
    $archiveDir = if ($BackupDir) { $BackupDir } else { Join-Path $PSScriptRoot "backups" }
    if (-not (Test-Path -LiteralPath $archiveDir)) { New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null }
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $archive = Join-Path $archiveDir ("UIManager.cs.edited_{0}_{1}.bak" -f $stamp, $currentHash.Substring(0, 12))
    Copy-Item -LiteralPath $target -Destination $archive
    if ((Get-Sha256 $archive) -ne $currentHash) {
        Write-Error "[P2-v5-revert] Archive verification failed; not touching the target."
        exit 1
    }
    Write-Warning "[P2-v5-revert] Edited target archived -> $archive"
}

if (-not (Test-Path -LiteralPath $backupFile)) {
    Write-Error "[P2-v5-revert] Backup file missing: $backupFile"
    exit 1
}

$backupHash = Get-Sha256 $backupFile
if ($backupHash -ne $preHash) {
    Write-Error "[P2-v5-revert] Backup hash $backupHash != receipt pre-patch hash $preHash. Aborting; the target is untouched."
    exit 1
}

$guid = [System.Guid]::NewGuid().ToString("N")
$tmpFile = "$target.tmp.$guid"
try {
    Copy-Item -LiteralPath $backupFile -Destination $tmpFile -Force
    Set-ItemProperty -LiteralPath $tmpFile -Name IsReadOnly -Value $false
    if ((Get-Sha256 $tmpFile) -ne $preHash) {
        throw "staged copy does not hash to the pre-patch value"
    }
    Move-Item -LiteralPath $tmpFile -Destination $target -Force
} catch {
    if (Test-Path -LiteralPath $tmpFile) { Remove-Item -LiteralPath $tmpFile -Force }
    Write-Error "[P2-v5-revert] Restore failed: $_"
    exit 1
}

$restoredHash = Get-Sha256 $target
if ($restoredHash -ne $preHash) {
    Write-Error "[P2-v5-revert] Post-restore verification failed. Restored $restoredHash, expected $preHash."
    exit 1
}

Write-Host "[P2-v5-revert] Restored and verified ($restoredHash)."
Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pendingPath -Force -ErrorAction SilentlyContinue
Write-Host "[P2-v5-revert] Receipts removed."
exit 0
