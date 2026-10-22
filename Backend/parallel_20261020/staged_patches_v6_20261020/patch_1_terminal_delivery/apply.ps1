# Patch 1 (v6) — Optional Terminal Retransmit, target-bound and failure-transactional
#
# Status: DEFERRED / OPTIONAL HARDENING ONLY. Do not apply to the production
# Unity project without an explicit decision. P02 showed 4/4 terminal outcomes
# persisted with this patch NOT applied.
#
# v6 closes the receipt-write failure path reported by the 2026-10-20 review of v5:
#   6. The committed receipt is written through a verified temp file
#      (`patch_receipt.json.tmp`): serialise -> read back -> check target binding
#      and hash round-trip -> move into place -> read back again. The pending
#      receipt is removed only after the committed file has been re-read and
#      verified. Any failure keeps the pending receipt and exits 12 (recovery
#      required), never 0.
#   7. A truncated / unreadable committed receipt no longer takes priority over a
#      valid pending receipt: it is moved aside to `patch_receipt.corrupt_<stamp>.json`
#      and the pending record is recovered. Only when nothing is recoverable does
#      the script refuse (exit 11).
#
# v5 fixes the five safety gaps reported by the 2026-10-20 review of v4:
#   1. Target binding: a receipt is only honoured when its `target` normalises to
#      the same path as the file being changed. Same-content files elsewhere are
#      no longer interchangeable with the receipt target.
#   2. Backup verification: an existing backup must hash to the current target
#      hash before it is used. A corrupt backup aborts the apply instead of
#      producing a patch whose revert cannot work.
#   3. Pending/commit receipts: a `patch_receipt.pending.json` is written BEFORE
#      the target is replaced, and promoted to `patch_receipt.json` only after
#      the post hash is verified. A crash between the two leaves a recoverable
#      pending state instead of changed source with no receipt.
#   4. Rollback on post-hash mismatch: if the written file does not hash to the
#      intended value, the backup is restored and verified.
#   5. No claim of atomicity. Move-Item -Force is not atomic on every failure
#      path; the pending receipt exists precisely because it is not.
#
# Anchor discipline is unchanged: every anchor must match exactly once or
# nothing is written.

[CmdletBinding()]
param(
    [string]$TargetOverride = "",
    [string]$ReceiptDir = "",
    [string]$BackupDir = "",
    [switch]$AllowUnknownBaseline
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
    # Superseded by Try-ReadJson, which returns $null instead of throwing on a
    # truncated file. Kept as a thin alias so any external caller still works.
    return (Try-ReadJson $p)
}

$target = if ($TargetOverride) { $TargetOverride } else { "C:\Users\QIYUXUAN\Desktop\Endless-Driver-Tutorial - EP9\Endless-Driver-Tutorial - EP9\Assets\BackEnd\UDPManager.cs" }
$ExpectedBaselineHash = "096C5FFA591E8B5D98B24F51BA4902D8E4C38699C36301589D7B512C3EB35A90"
$receiptRoot = if ($ReceiptDir) { $ReceiptDir } else { $PSScriptRoot }
$receiptPath = Join-Path $receiptRoot "patch_receipt.json"
$pendingPath = Join-Path $receiptRoot "patch_receipt.pending.json"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if (-not (Test-Path -LiteralPath $target)) {
    Write-Error "[P1-v6] Target not found: $target"
    exit 1
}

$targetNorm = Get-NormalizedPath $target
$currentHash = Get-Sha256 $target
$text = [System.IO.File]::ReadAllText($target)

Write-Host "[P1-v6] Target       : $target"
Write-Host "[P1-v6] Current Hash : $currentHash"
Write-Host "[P1-v6] Expected Base: $ExpectedBaselineHash"

# ---- v6: verified, recoverable receipt commit ------------------------------
# The receipt is the only record that makes a patched tree revertible, so it is
# never written in place. Serialise -> temp file -> read back -> verify target
# binding and hash round-trip -> move into place -> read back again. Only then
# may the pending record be removed. Any failure returns $false and leaves the
# pending receipt intact so the caller can exit 12 instead of 0.
$receiptTmpPath = "$receiptPath.tmp"

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

function Commit-Receipt($receipt) {
    try {
        $json = $receipt | ConvertTo-Json -Depth 4
        [System.IO.File]::WriteAllText($receiptTmpPath, $json, $utf8NoBom)
        $staged = Try-ReadJson $receiptTmpPath
        if (-not (Test-ReceiptShape $staged)) { throw "staged receipt is unreadable or has no target" }
        if ((Get-NormalizedPath $staged.target) -ne $targetNorm) { throw "staged receipt target does not bind to this file" }
        if (-not $staged.post_patch_hash -or $staged.post_patch_hash -ne $receipt.post_patch_hash) { throw "staged receipt post hash does not round-trip" }
        Move-Item -LiteralPath $receiptTmpPath -Destination $receiptPath -Force -ErrorAction Stop
        $committed = Try-ReadJson $receiptPath
        if (-not (Test-ReceiptShape $committed)) { throw "committed receipt is unreadable" }
        if ((Get-NormalizedPath $committed.target) -ne $targetNorm) { throw "committed receipt target mismatch" }
        if ($committed.post_patch_hash -ne $receipt.post_patch_hash) { throw "committed receipt post hash mismatch" }
        return $true
    } catch {
        Write-Warning "[P1-v6] Receipt commit failed: $_"
        if (Test-Path -LiteralPath $receiptTmpPath -PathType Leaf) {
            Remove-Item -LiteralPath $receiptTmpPath -Force -ErrorAction SilentlyContinue
        }
        return $false
    }
}

function Clear-Pending {
    try {
        Remove-Item -LiteralPath $pendingPath -Force -ErrorAction Stop
        return $true
    } catch {
        Write-Warning "[P1-v6] The committed receipt is verified but the pending file could not be removed: $pendingPath"
        return $false
    }
}

function Assert-ReceiptTarget($receipt, [string]$path) {
    if (-not $receipt.target) {
        Write-Error "[P1-v6] Receipt has no target field; refusing."
        return $false
    }
    if ((Get-NormalizedPath $receipt.target) -ne $targetNorm) {
        Write-Error "[P1-v6] Receipt target mismatch. Receipt: $($receipt.target) | Current: $path"
        return $false
    }
    return $true
}

# A receipt directory belongs to exactly one target. Check this BEFORE the
# marker branch: a pristine same-content file elsewhere must not inherit another
# file's receipt, and must not be able to overwrite it.
if (Test-Path -LiteralPath $receiptPath -PathType Container) {
    Write-Error "[P1-v6] Receipt path $receiptPath is a directory, not a file. Refusing."
    exit 11
}
if (Test-Path -LiteralPath $pendingPath -PathType Container) {
    Write-Error "[P1-v6] Pending receipt path $pendingPath is a directory, not a file. Refusing."
    exit 11
}
$existingReceipt = $null
if (Test-Path -LiteralPath $receiptPath) {
    $existingReceipt = Try-ReadJson $receiptPath
    if (-not (Test-ReceiptShape $existingReceipt)) {
        # A truncated or damaged committed receipt must not outrank a valid
        # pending record. Move it aside and fall through to the pending
        # recovery; refuse only when there is nothing to recover from.
        $pendProbe = if (Test-Path -LiteralPath $pendingPath) { Try-ReadJson $pendingPath } else { $null }
        if (-not (Test-ReceiptShape $pendProbe)) {
            Write-Error "[P1-v6] Committed receipt $receiptPath is unreadable and there is no valid pending receipt. Receipt state is unknown. Refusing."
            exit 11
        }
        $stamp = [System.DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
        $quarantine = Join-Path $receiptRoot ("patch_receipt.corrupt_{0}.json" -f $stamp)
        try {
            Move-Item -LiteralPath $receiptPath -Destination $quarantine -Force -ErrorAction Stop
        } catch {
            Write-Error "[P1-v6] Unreadable committed receipt could not be moved aside: $_. Pending receipt kept at $pendingPath."
            exit 12
        }
        Write-Warning "[P1-v6] Committed receipt was unreadable; moved aside to $quarantine. Recovering from the pending receipt."
        $existingReceipt = $null
    }
    if ($existingReceipt -and -not (Assert-ReceiptTarget $existingReceipt $target)) { exit 8 }
}
if (Test-Path -LiteralPath $pendingPath) {
    $existingPending = Try-ReadJson $pendingPath
    if (-not (Test-ReceiptShape $existingPending)) {
        Write-Error "[P1-v6] Pending receipt $pendingPath is unreadable. Refusing; inspect it by hand."
        exit 11
    }
    if (-not (Assert-ReceiptTarget $existingPending $target)) { exit 8 }
}

# ---- already applied? ------------------------------------------------------
if ($text.Contains("RetransmitTerminalPacket") -and $text.Contains("terminalRetransmitRoutine")) {
    if (Test-Path -LiteralPath $receiptPath) {
        $prior = Try-ReadJson $receiptPath
        if (-not (Test-ReceiptShape $prior)) {
            Write-Error "[P1-v6] Committed receipt became unreadable during this run. Refusing."
            exit 11
        }
        if (-not (Assert-ReceiptTarget $prior $target)) { exit 8 }
        if ($prior.post_patch_hash -and ($currentHash -eq $prior.post_patch_hash)) {
            Write-Host "[P1-v6] Already applied; receipt hash and target match. Nothing to do."
            exit 0
        }
        Write-Error "[P1-v6] Marker present but hash $currentHash != receipt post hash $($prior.post_patch_hash). Refusing."
        exit 5
    }
    if (Test-Path -LiteralPath $pendingPath) {
        $pend = Try-ReadJson $pendingPath
        if (-not (Test-ReceiptShape $pend)) {
            Write-Error "[P1-v6] Pending receipt is unreadable. Refusing; inspect $pendingPath."
            exit 11
        }
        if (-not (Assert-ReceiptTarget $pend $target)) { exit 8 }
        if ($pend.intended_post_hash -and ($currentHash -eq $pend.intended_post_hash)) {
            # Crash after replacement, before commit: finalise the receipt now.
            $receipt = [PSCustomObject]@{
                target          = $target
                pre_patch_hash  = $pend.pre_patch_hash
                post_patch_hash = $currentHash
                backup_file     = $pend.backup_file
                applied_at_utc  = $pend.written_at_utc
                committed_at_utc = [System.DateTime]::UtcNow.ToString("o")
                recovered_from_pending = $true
            }
            if (-not (Commit-Receipt $receipt)) {
                Write-Error "[P1-v6] RECOVERY REQUIRED: the target is already patched and verified ($currentHash) but the committed receipt could not be written. The pending receipt is retained at $pendingPath. Re-run this script once the receipt directory is writable."
                exit 12
            }
            $null = Clear-Pending
            Write-Host "[P1-v6] Recovered a pending patch: receipt committed from pending state."
            exit 0
        }
        Write-Error "[P1-v6] Marker present, pending receipt hash mismatch. Refusing; inspect $pendingPath."
        exit 5
    }
    Write-Error "[P1-v6] Marker present but no receipt and no pending receipt. State is unverifiable. Refusing."
    exit 5
}

# ---- baseline --------------------------------------------------------------
if ($currentHash -ne $ExpectedBaselineHash) {
    if ($TargetOverride -and $AllowUnknownBaseline) {
        Write-Warning "[P1-v6] Baseline check bypassed by -AllowUnknownBaseline. Sandbox use only."
    } else {
        Write-Error "[P1-v6] Target hash $currentHash does not match expected baseline $ExpectedBaselineHash. Aborting."
        exit 1
    }
}

# ---- backup: verify an existing one, never assume it ------------------------
$backupDir = if ($BackupDir) { $BackupDir } else { Join-Path $PSScriptRoot "backups" }
if (-not (Test-Path -LiteralPath $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
}
$backupFile = Join-Path $backupDir ("UDPManager.cs.pre_{0}.bak" -f $currentHash.Substring(0, 16))

if (Test-Path -LiteralPath $backupFile) {
    $backupHash = Get-Sha256 $backupFile
    if ($backupHash -ne $currentHash) {
        Write-Error "[P1-v6] Existing backup $backupFile hashes to $backupHash, not the current target $currentHash. It cannot serve as a rollback point. Aborting before any change."
        exit 6
    }
    Write-Host "[P1-v6] Verified existing backup ($backupHash)."
} else {
    Copy-Item -LiteralPath $target -Destination $backupFile -Force
    $backupHash = Get-Sha256 $backupFile
    if ($backupHash -ne $currentHash) {
        Write-Error "[P1-v6] Backup copy verified as $backupHash, expected $currentHash. Aborting before any change."
        exit 6
    }
    Set-ItemProperty -LiteralPath $backupFile -Name IsReadOnly -Value $true
    Write-Host "[P1-v6] Created and verified backup -> $backupFile"
}

# ---- anchors ---------------------------------------------------------------
$plain = $text -replace "`r`n", "`n"

$anchorCall = "        SendTelemetry(fallEvent, fallReason);`n        geometryDiagnostics?.RecordLifecycleEvent("
$replCall = @'
        SendTelemetry(fallEvent, fallReason);
        if (lastUdpSendCallCompleted && !string.IsNullOrEmpty(lastSerializedTelemetry) && udpSender != null && isActiveAndEnabled)
        {
            if (terminalRetransmitRoutine != null) { StopCoroutine(terminalRetransmitRoutine); }
            terminalRetransmitRoutine = StartCoroutine(RetransmitTerminalPacket(lastSerializedTelemetry));
        }
        geometryDiagnostics?.RecordLifecycleEvent(
'@ -replace "`r`n", "`n"

$anchorMethod = "    private void RecordLightweightDiagnosticSample()"
$replMethod = @'
    private Coroutine terminalRetransmitRoutine;

    // Spaced retransmit of the frozen terminal packet.
    // Nominal delivery at +120ms and +360ms relative to the initial send call.
    // This is a MonoBehaviour coroutine: it does not survive scene unload or process exit.
    private System.Collections.IEnumerator RetransmitTerminalPacket(string payload)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(payload);
        float[] delays = { 0.12f, 0.24f };
        for (int i = 0; i < delays.Length; i++)
        {
            yield return new WaitForSecondsRealtime(delays[i]);
            if (udpSender == null) { terminalRetransmitRoutine = null; yield break; }
            try { udpSender.Send(bytes, bytes.Length, telemetryEndPoint); }
            catch (System.Exception) { terminalRetransmitRoutine = null; yield break; }
        }
        terminalRetransmitRoutine = null;
    }

    private void RecordLightweightDiagnosticSample()
'@ -replace "`r`n", "`n"

function Count-Hits([string]$haystack, [string]$needle) {
    return ([regex]::Matches($haystack, [regex]::Escape($needle))).Count
}

$c1 = Count-Hits $plain $anchorCall
$c2 = Count-Hits $plain $anchorMethod
Write-Host "[P1-v6] Anchor hits: call-site=$c1, method-slot=$c2"
if ($c1 -ne 1 -or $c2 -ne 1) {
    Write-Error "[P1-v6] Anchors did not match exactly once. Nothing written."
    exit 1
}

$modified = $plain.Replace($anchorCall, $replCall)
$modified = $modified.Replace($anchorMethod, $replMethod)

# ---- stage to a temp file and hash the intended result ---------------------
$guid = [System.Guid]::NewGuid().ToString("N")
$tmpFile = "$target.tmp.$guid"

try {
    [System.IO.File]::WriteAllText($tmpFile, $modified, $utf8NoBom)
    $tmpContent = [System.IO.File]::ReadAllText($tmpFile)
    if (-not ($tmpContent.Contains("RetransmitTerminalPacket") -and $tmpContent.Contains("terminalRetransmitRoutine"))) {
        throw "staged content is missing the expected symbols"
    }
} catch {
    if (Test-Path -LiteralPath $tmpFile) { Remove-Item -LiteralPath $tmpFile -Force }
    Write-Error "[P1-v6] Staging failed before any change to the target: $_"
    exit 1
}
$intendedHash = Get-Sha256 $tmpFile

# ---- pending receipt BEFORE the target is touched --------------------------
try {
    if (-not (Test-Path -LiteralPath $receiptRoot)) {
        New-Item -ItemType Directory -Path $receiptRoot -Force | Out-Null
    }
    $pending = [PSCustomObject]@{
        target              = $target
        pre_patch_hash      = $currentHash
        intended_post_hash  = $intendedHash
        backup_file         = $backupFile
        written_at_utc      = [System.DateTime]::UtcNow.ToString("o")
        state               = "pending"
    }
    [System.IO.File]::WriteAllText($pendingPath, ($pending | ConvertTo-Json -Depth 4), $utf8NoBom)
} catch {
    if (Test-Path -LiteralPath $tmpFile) { Remove-Item -LiteralPath $tmpFile -Force }
    Write-Error "[P1-v6] Could not write the pending receipt, so the target was NOT changed: $_"
    exit 7
}

# ---- replace, verify, commit ----------------------------------------------
try {
    Move-Item -LiteralPath $tmpFile -Destination $target -Force
} catch {
    if (Test-Path -LiteralPath $tmpFile) { Remove-Item -LiteralPath $tmpFile -Force }
    $nowHash = if (Test-Path -LiteralPath $target) { Get-Sha256 $target } else { "" }
    if ($nowHash -eq $currentHash) {
        Remove-Item -LiteralPath $pendingPath -Force -ErrorAction SilentlyContinue
        Write-Error "[P1-v6] Replacement failed and the target is unchanged: $_"
        exit 1
    }
    Write-Error "[P1-v6] Replacement failed with the target in an unknown state ($nowHash). Pending receipt kept at $pendingPath."
    exit 9
}

$postHash = Get-Sha256 $target
if ($postHash -ne $intendedHash) {
    Write-Warning "[P1-v6] Post hash $postHash != intended $intendedHash. Restoring the backup."
    Copy-Item -LiteralPath $backupFile -Destination $target -Force
    $restored = Get-Sha256 $target
    if ($restored -eq $currentHash) {
        Remove-Item -LiteralPath $pendingPath -Force -ErrorAction SilentlyContinue
        Write-Error "[P1-v6] Rolled back to the pre-patch state ($restored) after hash mismatch."
        exit 9
    }
    Write-Error "[P1-v6] Rollback verification failed ($restored). Pending receipt kept at $pendingPath."
    exit 9
}

$receipt = [PSCustomObject]@{
    target           = $target
    pre_patch_hash   = $currentHash
    post_patch_hash  = $postHash
    backup_file      = $backupFile
    applied_at_utc   = [System.DateTime]::UtcNow.ToString("o")
    committed_at_utc = [System.DateTime]::UtcNow.ToString("o")
}
if (-not (Commit-Receipt $receipt)) {
    Write-Error "[P1-v6] RECOVERY REQUIRED: the patch is applied and verified ($postHash) but the committed receipt could not be written. The pending receipt is retained at $pendingPath; re-running this script will commit it once the receipt directory is writable. Do NOT treat this as applied."
    exit 12
}
$null = Clear-Pending
Write-Host "[P1-v6] Applied and committed. New hash: $postHash"
Write-Host "[P1-v6] Receipt -> $receiptPath"
exit 0
