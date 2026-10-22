# Patch 1 (v3) — Optional Terminal Retransmit with Hash-Bound Safety
#
# Status: DEFERRED / OPTIONAL HARDENING ONLY.
# Do NOT apply unless explicitly authorized. P02 testing demonstrated 100% terminal outcome
# persistence without this patch.
#
# Key improvements in v3 (resolving defects from independent review 2026-10-20):
#   1. Timing Clarification & Correction: to achieve nominal sends at +120ms and +360ms
#      relative to the terminal event, incremental delays are set to { 0.12f, 0.24f }
#      (0.12s + 0.24s = 0.36s cumulative).
#   2. Coroutine Lifecycle Caveat: clearly documents that as a MonoBehaviour coroutine,
#      execution will cease if the GameObject or scene unloads immediately upon completion.
#   3. Pre-flight Hash Binding: verifies target matches exact expected baseline hash
#      before touching any file.
#   4. Hash-Bound Immutable Backup & Receipt: records pre/post SHA-256 hashes in patch_receipt.json.
#   5. Transactional replacement: writes to temporary file first before swapping.

[CmdletBinding()]
param(
    [string]$TargetOverride = "",
    [switch]$AllowUnknownBaseline
)

$target = if ($TargetOverride) { $TargetOverride } else { "C:\Users\QIYUXUAN\Desktop\Endless-Driver-Tutorial - EP9\Endless-Driver-Tutorial - EP9\Assets\BackEnd\UDPManager.cs" }
$ExpectedBaselineHash = "096C5FFA591E8B5D98B24F51BA4902D8E4C38699C36301589D7B512C3EB35A90"
$receiptPath = Join-Path $PSScriptRoot "patch_receipt.json"

if (-not (Test-Path -LiteralPath $target)) {
    Write-Error "[P1-v3] Target not found: $target"
    exit 1
}

$currentHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
Write-Host "[P1-v3] Target: $target"
Write-Host "[P1-v3] Current Hash : $currentHash"
Write-Host "[P1-v3] Expected Base: $ExpectedBaselineHash"

$text = [System.IO.File]::ReadAllText($target)

if ($text.Contains("RetransmitTerminalPacket") -and $text.Contains("terminalRetransmitRoutine")) {
    # "Already applied" must be proven, not inferred from a substring.
    if (Test-Path -LiteralPath $receiptPath) {
        $priorReceipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
        if ($priorReceipt.post_patch_hash -and ($currentHash -eq $priorReceipt.post_patch_hash)) {
            Write-Host "[P1-v3] Already applied and receipt hash matches ($currentHash). Nothing to do."
            exit 0
        }
        Write-Error "[P1-v3] Patch marker present but current hash ($currentHash) != receipt post hash ($($priorReceipt.post_patch_hash)). The file changed after patching. Refusing."
        exit 5
    }
    Write-Error "[P1-v3] Patch marker present but no patch_receipt.json. State is unverifiable. Refusing; restore from version control or a known baseline first."
    exit 5
}

if ($currentHash -ne $ExpectedBaselineHash) {
    if ($TargetOverride -and $AllowUnknownBaseline) {
        Write-Warning "[P1-v3] Baseline check bypassed by -AllowUnknownBaseline. Only valid for sandbox targets."
    } else {
        Write-Error "[P1-v3] Target hash ($currentHash) does not match expected baseline ($ExpectedBaselineHash). Aborting application."
        exit 1
    }
}

# Immutable, hash-bound backup
$backupDir = Join-Path $PSScriptRoot "backups"
if (-not (Test-Path -LiteralPath $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
}
$backupFile = Join-Path $backupDir "UDPManager.cs.pre_$($currentHash.Substring(0,16)).bak"
if (-not (Test-Path -LiteralPath $backupFile)) {
    Copy-Item -LiteralPath $target -Destination $backupFile -Force
    Set-ItemProperty -LiteralPath $backupFile -Name IsReadOnly -Value $true
    Write-Host "[P1-v3] Created hash-bound immutable backup -> $backupFile"
} else {
    Write-Host "[P1-v3] Found existing immutable backup -> $backupFile"
}

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
    // Nominal delivery at +120ms and +360ms relative to initial send call.
    // Note: this is a MonoBehaviour coroutine and will not survive scene unload or process exit.
    private System.Collections.IEnumerator RetransmitTerminalPacket(string payload)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(payload);
        // Incremental delays: 0.12s -> +120ms; then +0.24s -> cumulative +360ms
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
Write-Host "[P1-v3] Anchor hits: call-site=$c1, method-slot=$c2"
if ($c1 -ne 1 -or $c2 -ne 1) {
    Write-Error "[P1-v3] Anchors failed to match uniquely. Aborting."
    exit 1
}

$modified = $plain.Replace($anchorCall, $replCall)
$modified = $modified.Replace($anchorMethod, $replMethod)

# Transactional replacement via temporary file
$guid = [System.Guid]::NewGuid().ToString("N")
$tmpFile = "$target.tmp.$guid"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

try {
    [System.IO.File]::WriteAllText($tmpFile, $modified, $utf8NoBom)
    $tmpContent = [System.IO.File]::ReadAllText($tmpFile)
    if (-not ($tmpContent.Contains("RetransmitTerminalPacket") -and $tmpContent.Contains("terminalRetransmitRoutine"))) {
        throw "Temporary file verification failed."
    }
    Move-Item -LiteralPath $tmpFile -Destination $target -Force
} catch {
    if (Test-Path -LiteralPath $tmpFile) { Remove-Item -LiteralPath $tmpFile -Force }
    Write-Error "[P1-v3] Transactional write failed: $_"
    exit 1
}

$postHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
Write-Host "[P1-v3] Successfully applied patch. New Hash: $postHash"

$receipt = [PSCustomObject]@{
    target = $target
    pre_patch_hash = $currentHash
    post_patch_hash = $postHash
    backup_file = $backupFile
    applied_at_utc = [System.DateTime]::UtcNow.ToString("o")
}
$receiptJson = $receipt | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText($receiptPath, $receiptJson, $utf8NoBom)
Write-Host "[P1-v3] Receipt written -> $receiptPath"
exit 0
