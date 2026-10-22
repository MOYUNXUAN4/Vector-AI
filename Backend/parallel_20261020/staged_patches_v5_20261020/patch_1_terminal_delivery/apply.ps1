# Patch 1 (v5) — Optional Terminal Retransmit, target-bound and failure-transactional
#
# Status: DEFERRED / OPTIONAL HARDENING ONLY. Do not apply to the production
# Unity project without an explicit decision. P02 showed 4/4 terminal outcomes
# persisted with this patch NOT applied.
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
    return (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json)
}

$target = if ($TargetOverride) { $TargetOverride } else { "C:\Users\QIYUXUAN\Desktop\Endless-Driver-Tutorial - EP9\Endless-Driver-Tutorial - EP9\Assets\BackEnd\UDPManager.cs" }
$ExpectedBaselineHash = "096C5FFA591E8B5D98B24F51BA4902D8E4C38699C36301589D7B512C3EB35A90"
$receiptRoot = if ($ReceiptDir) { $ReceiptDir } else { $PSScriptRoot }
$receiptPath = Join-Path $receiptRoot "patch_receipt.json"
$pendingPath = Join-Path $receiptRoot "patch_receipt.pending.json"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if (-not (Test-Path -LiteralPath $target)) {
    Write-Error "[P1-v5] Target not found: $target"
    exit 1
}

$targetNorm = Get-NormalizedPath $target
$currentHash = Get-Sha256 $target
$text = [System.IO.File]::ReadAllText($target)

Write-Host "[P1-v5] Target       : $target"
Write-Host "[P1-v5] Current Hash : $currentHash"
Write-Host "[P1-v5] Expected Base: $ExpectedBaselineHash"

function Assert-ReceiptTarget($receipt, [string]$path) {
    if (-not $receipt.target) {
        Write-Error "[P1-v5] Receipt has no target field; refusing."
        return $false
    }
    if ((Get-NormalizedPath $receipt.target) -ne $targetNorm) {
        Write-Error "[P1-v5] Receipt target mismatch. Receipt: $($receipt.target) | Current: $path"
        return $false
    }
    return $true
}

# A receipt directory belongs to exactly one target. Check this BEFORE the
# marker branch: a pristine same-content file elsewhere must not inherit another
# file's receipt, and must not be able to overwrite it.
if (Test-Path -LiteralPath $receiptPath) {
    $existingReceipt = Read-Json $receiptPath
    if (-not (Assert-ReceiptTarget $existingReceipt $target)) { exit 8 }
}
if (Test-Path -LiteralPath $pendingPath) {
    $existingPending = Read-Json $pendingPath
    if (-not (Assert-ReceiptTarget $existingPending $target)) { exit 8 }
}

# ---- already applied? ------------------------------------------------------
if ($text.Contains("RetransmitTerminalPacket") -and $text.Contains("terminalRetransmitRoutine")) {
    if (Test-Path -LiteralPath $receiptPath) {
        $prior = Read-Json $receiptPath
        if (-not (Assert-ReceiptTarget $prior $target)) { exit 8 }
        if ($prior.post_patch_hash -and ($currentHash -eq $prior.post_patch_hash)) {
            Write-Host "[P1-v5] Already applied; receipt hash and target match. Nothing to do."
            exit 0
        }
        Write-Error "[P1-v5] Marker present but hash $currentHash != receipt post hash $($prior.post_patch_hash). Refusing."
        exit 5
    }
    if (Test-Path -LiteralPath $pendingPath) {
        $pend = Read-Json $pendingPath
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
            [System.IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 4), $utf8NoBom)
            Remove-Item -LiteralPath $pendingPath -Force
            Write-Host "[P1-v5] Recovered a pending patch: receipt committed from pending state."
            exit 0
        }
        Write-Error "[P1-v5] Marker present, pending receipt hash mismatch. Refusing; inspect $pendingPath."
        exit 5
    }
    Write-Error "[P1-v5] Marker present but no receipt and no pending receipt. State is unverifiable. Refusing."
    exit 5
}

# ---- baseline --------------------------------------------------------------
if ($currentHash -ne $ExpectedBaselineHash) {
    if ($TargetOverride -and $AllowUnknownBaseline) {
        Write-Warning "[P1-v5] Baseline check bypassed by -AllowUnknownBaseline. Sandbox use only."
    } else {
        Write-Error "[P1-v5] Target hash $currentHash does not match expected baseline $ExpectedBaselineHash. Aborting."
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
        Write-Error "[P1-v5] Existing backup $backupFile hashes to $backupHash, not the current target $currentHash. It cannot serve as a rollback point. Aborting before any change."
        exit 6
    }
    Write-Host "[P1-v5] Verified existing backup ($backupHash)."
} else {
    Copy-Item -LiteralPath $target -Destination $backupFile -Force
    $backupHash = Get-Sha256 $backupFile
    if ($backupHash -ne $currentHash) {
        Write-Error "[P1-v5] Backup copy verified as $backupHash, expected $currentHash. Aborting before any change."
        exit 6
    }
    Set-ItemProperty -LiteralPath $backupFile -Name IsReadOnly -Value $true
    Write-Host "[P1-v5] Created and verified backup -> $backupFile"
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
Write-Host "[P1-v5] Anchor hits: call-site=$c1, method-slot=$c2"
if ($c1 -ne 1 -or $c2 -ne 1) {
    Write-Error "[P1-v5] Anchors did not match exactly once. Nothing written."
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
    Write-Error "[P1-v5] Staging failed before any change to the target: $_"
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
    Write-Error "[P1-v5] Could not write the pending receipt, so the target was NOT changed: $_"
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
        Write-Error "[P1-v5] Replacement failed and the target is unchanged: $_"
        exit 1
    }
    Write-Error "[P1-v5] Replacement failed with the target in an unknown state ($nowHash). Pending receipt kept at $pendingPath."
    exit 9
}

$postHash = Get-Sha256 $target
if ($postHash -ne $intendedHash) {
    Write-Warning "[P1-v5] Post hash $postHash != intended $intendedHash. Restoring the backup."
    Copy-Item -LiteralPath $backupFile -Destination $target -Force
    $restored = Get-Sha256 $target
    if ($restored -eq $currentHash) {
        Remove-Item -LiteralPath $pendingPath -Force -ErrorAction SilentlyContinue
        Write-Error "[P1-v5] Rolled back to the pre-patch state ($restored) after hash mismatch."
        exit 9
    }
    Write-Error "[P1-v5] Rollback verification failed ($restored). Pending receipt kept at $pendingPath."
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
try {
    [System.IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 4), $utf8NoBom)
    Remove-Item -LiteralPath $pendingPath -Force
    Write-Host "[P1-v5] Applied and committed. New hash: $postHash"
    Write-Host "[P1-v5] Receipt -> $receiptPath"
} catch {
    Write-Warning "[P1-v5] Patch applied and verified ($postHash) but the committed receipt could not be written: $_"
    Write-Warning "[P1-v5] Pending receipt kept at $pendingPath; the next run will commit it."
}
exit 0
