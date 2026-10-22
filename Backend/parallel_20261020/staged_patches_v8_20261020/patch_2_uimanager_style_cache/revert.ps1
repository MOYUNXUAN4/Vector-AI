# Patch 2 (v7) — Revert, target-bound and receipt-verified
#
# v7: a pending-only rollback record is verified before it is used: complete,
#     well-formed hashes and a backup file that hashes to the stated pre-patch
#     state. Otherwise the revert refuses with exit 13 and names the defect,
#     instead of trusting the record and failing later.
#
# v6 adds the recovery counterpart to the apply-side commit repair:
#   3. An unreadable / truncated committed receipt no longer hides a valid
#      pending receipt. It is moved aside to `patch_receipt.corrupt_<stamp>.json`
#      and the pending record is used; with neither readable the revert refuses
#      with exit 11 instead of acting on a null receipt.
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

function Try-ReadJson([string]$p) {
    try {
        $raw = Get-Content -LiteralPath $p -Raw -ErrorAction Stop
        if ($null -eq $raw -or $raw.Trim().Length -eq 0) { return $null }
        return ($raw | ConvertFrom-Json -ErrorAction Stop)
    } catch {
        return $null
    }
}

function Test-ReceiptShape($o) {
    if ($null -eq $o) { return $false }
    if (-not $o.PSObject.Properties.Match('target').Count) { return $false }
    if (-not $o.target) { return $false }
    return $true
}

# ---- v7: verify the rollback record before trusting it -----------------------
$hex64 = '^[0-9A-Fa-f]{64}$'

function Test-RollbackRecord($rec, [string]$expectedPostHash, [string]$postField) {
    $problems = New-Object System.Collections.Generic.List[string]
    if ($null -eq $rec) {
        return [PSCustomObject]@{ ok = $false; problems = @("record is unreadable"); pre = $null; backup = $null; backup_hash = $null }
    }
    $pre = "$($rec.pre_patch_hash)".Trim()
    if (-not $pre) { $problems.Add("pre_patch_hash is missing") }
    elseif ($pre -notmatch $hex64) { $problems.Add("pre_patch_hash is not a 64-hex SHA-256 value") }

    $post = "$($rec.$postField)".Trim()
    if (-not $post) { $problems.Add("post-patch hash is missing") }
    elseif ($post -notmatch $hex64) { $problems.Add("post-patch hash is not a 64-hex SHA-256 value") }
    elseif ($expectedPostHash -and ($post -ne $expectedPostHash)) { $problems.Add("post-patch hash does not match the current target") }

    $backup = "$($rec.backup_file)".Trim()
    $backupHash = $null
    if (-not $backup) {
        $problems.Add("backup_file is missing")
    } elseif (-not (Test-Path -LiteralPath $backup -PathType Leaf)) {
        $problems.Add("backup_file does not exist: $backup")
    } elseif ($pre -match $hex64) {
        try {
            $backupHash = Get-Sha256 $backup
        } catch {
            $problems.Add("backup_file cannot be hashed: $_")
        }
        if ($backupHash -and ($backupHash -ne $pre)) {
            $problems.Add("backup_file hashes to $backupHash, not the recorded pre-patch state $pre")
        }
    }
    return [PSCustomObject]@{
        ok          = ($problems.Count -eq 0)
        problems    = @($problems)
        pre         = $pre
        backup      = $backup
        backup_hash = $backupHash
    }
}

$receiptRoot = if ($ReceiptDir) { $ReceiptDir } else { $PSScriptRoot }
$receiptPath = Join-Path $receiptRoot "patch_receipt.json"
$pendingPath = Join-Path $receiptRoot "patch_receipt.pending.json"

if (Test-Path -LiteralPath $receiptPath -PathType Container) {
    Write-Error "[P2-v7-revert] Receipt path $receiptPath is a directory, not a file. Refusing."
    exit 11
}
if (Test-Path -LiteralPath $pendingPath -PathType Container) {
    Write-Error "[P2-v7-revert] Pending receipt path $pendingPath is a directory, not a file. Refusing."
    exit 11
}

# v6: a damaged committed receipt must not hide a valid pending record.
$receipt = $null
if (Test-Path -LiteralPath $receiptPath) {
    $receipt = Try-ReadJson $receiptPath
    if (Test-ReceiptShape $receipt) {
        Write-Host "[P2-v7-revert] Using committed receipt $receiptPath"
    } else {
        $pendProbe = if (Test-Path -LiteralPath $pendingPath) { Try-ReadJson $pendingPath } else { $null }
        if (-not (Test-ReceiptShape $pendProbe)) {
            Write-Error "[P2-v7-revert] Committed receipt $receiptPath is unreadable and there is no valid pending receipt. Refusing."
            exit 11
        }
        $stamp = [System.DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
        $quarantine = Join-Path $receiptRoot ("patch_receipt.corrupt_{0}.json" -f $stamp)
        try {
            Move-Item -LiteralPath $receiptPath -Destination $quarantine -Force -ErrorAction Stop
        } catch {
            Write-Error "[P2-v7-revert] Unreadable committed receipt could not be moved aside: $_"
            exit 12
        }
        Write-Warning "[P2-v7-revert] Committed receipt was unreadable; moved aside to $quarantine. Using the pending receipt."
        $receipt = $null
    }
}
if ($null -eq $receipt) {
    if (Test-Path -LiteralPath $pendingPath) {
        $pend = Try-ReadJson $pendingPath
        if (-not (Test-ReceiptShape $pend)) {
            Write-Error "[P2-v7-revert] Pending receipt $pendingPath is unreadable. Refusing."
            exit 11
        }
        Write-Warning "[P2-v7-revert] Only a pending receipt exists; verifying it as a rollback record before use."
        $rollback = Test-RollbackRecord $pend "" "intended_post_hash"
        if (-not $rollback.ok) {
            Write-Error "[P2-v7-revert] Pending receipt cannot serve as a rollback record: $($rollback.problems -join '; '). The target is untouched. Restore the verified backup or the recorded pre-patch file by hand, then re-run."
            exit 13
        }
        $receipt = [PSCustomObject]@{
            target          = $pend.target
            pre_patch_hash  = $rollback.pre
            post_patch_hash = $pend.intended_post_hash
            backup_file     = $rollback.backup
            backup_verified = $true
            backup_sha256   = $rollback.backup_hash
        }
    } else {
        Write-Error "[P2-v7-revert] No receipt and no pending receipt in $receiptRoot. Cannot verify a safe rollback."
        exit 1
    }
}

$target = if ($TargetOverride) { $TargetOverride } else { $receipt.target }
if (-not $receipt.target) {
    Write-Error "[P2-v7-revert] Receipt has no target field; refusing."
    exit 8
}
if ((Get-NormalizedPath $receipt.target) -ne (Get-NormalizedPath $target)) {
    Write-Error "[P2-v7-revert] TargetOverride does not match the receipt target. Receipt: $($receipt.target) | Override: $target"
    exit 8
}

$preHash = $receipt.pre_patch_hash
$postHash = $receipt.post_patch_hash
$backupFile = $receipt.backup_file

if (-not (Test-Path -LiteralPath $target)) {
    Write-Error "[P2-v7-revert] Target file not found: $target"
    exit 1
}

$currentHash = Get-Sha256 $target
Write-Host "[P2-v7-revert] Target       : $target"
Write-Host "[P2-v7-revert] Current Hash : $currentHash"
Write-Host "[P2-v7-revert] Expected Post: $postHash"
Write-Host "[P2-v7-revert] Target Pre   : $preHash"

if ($currentHash -eq $preHash) {
    Write-Host "[P2-v7-revert] Target is already in the pre-patch state. Cleaning receipts."
    Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $pendingPath -Force -ErrorAction SilentlyContinue
    exit 0
}

if ($currentHash -ne $postHash) {
    if (-not $SaveCurrentFirst) {
        Write-Error "[P2-v7-revert] Current hash $currentHash != expected post-patch hash $postHash. Later edits may exist. Refusing. Re-run with -SaveCurrentFirst to archive first."
        exit 1
    }
    $archiveDir = if ($BackupDir) { $BackupDir } else { Join-Path $PSScriptRoot "backups" }
    if (-not (Test-Path -LiteralPath $archiveDir)) { New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null }
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $archive = Join-Path $archiveDir ("UIManager.cs.edited_{0}_{1}.bak" -f $stamp, $currentHash.Substring(0, 12))
    Copy-Item -LiteralPath $target -Destination $archive
    if ((Get-Sha256 $archive) -ne $currentHash) {
        Write-Error "[P2-v7-revert] Archive verification failed; not touching the target."
        exit 1
    }
    Write-Warning "[P2-v7-revert] Edited target archived -> $archive"
}

if (-not (Test-Path -LiteralPath $backupFile)) {
    Write-Error "[P2-v7-revert] Backup file missing: $backupFile"
    exit 1
}

$backupHash = Get-Sha256 $backupFile
if ($backupHash -ne $preHash) {
    Write-Error "[P2-v7-revert] Backup hash $backupHash != receipt pre-patch hash $preHash. Aborting; the target is untouched."
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
    Write-Error "[P2-v7-revert] Restore failed: $_"
    exit 1
}

$restoredHash = Get-Sha256 $target
if ($restoredHash -ne $preHash) {
    Write-Error "[P2-v7-revert] Post-restore verification failed. Restored $restoredHash, expected $preHash."
    exit 1
}

Write-Host "[P2-v7-revert] Restored and verified ($restoredHash)."
Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pendingPath -Force -ErrorAction SilentlyContinue
Write-Host "[P2-v7-revert] Receipts removed."
exit 0
