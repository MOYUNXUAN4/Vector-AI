# Patch 2 (v7) — UIManager GUIStyle Value-Key Cache, target-bound and transactional
#
# Status: DEFERRED. No C# compilation and no screenshot diff has been performed.
#
# v7 closes the pending-recovery boundary reported by the 2026-10-20 review of v6:
#   8. A pending record is promoted to a committed receipt only after the whole
#      rollback record verifies: complete schema, 64-hex hashes, and a backup
#      file whose bytes hash to the stated pre-patch state. A pending record
#      with a matching post hash but a missing or mismatched backup is refused
#      with exit 13 instead of being promoted into a receipt that promises an
#      impossible rollback. `backup_verified` / `backup_sha256` are recorded.
#
# v6 closes the receipt-write failure path reported by the 2026-10-20 review of v5,
# with the same discipline as patch 1:
#   6. The committed receipt is written through a verified temp file: serialise ->
#      read back -> check target binding and hash round-trip -> move into place ->
#      read back again. Pending is removed only after that verification; any
#      failure keeps pending and exits 12, never 0.
#   7. A truncated committed receipt is moved aside to
#      `patch_receipt.corrupt_<stamp>.json` and the valid pending record is
#      recovered instead of being discarded.
#
# v5 fixes the five safety gaps reported by the 2026-10-20 review of v4, with the
# same discipline as patch 1:
#   1. Target binding: a receipt is only honoured when its `target` normalises to
#      the file being changed; same-content files elsewhere are not interchangeable.
#   2. Backup verification: an existing backup must hash to the current target
#      hash before it is used, otherwise the apply aborts before any change.
#   3. Pending/commit receipts: `patch_receipt.pending.json` is written BEFORE
#      the target is replaced and promoted only after the post hash verifies.
#   4. Rollback on post-hash mismatch: the verified backup is restored.
#   5. No atomicity claim: Move-Item -Force is not atomic on every failure path,
#      which is exactly why the pending receipt exists.
#
# The patch body is unchanged from v4 (structured VectorStyleKey, five anchors,
# no HUD default change, no F1 binding). Every anchor must match exactly once.

[CmdletBinding()]
param(
    [string]$TargetOverride = "",
    [string]$ReceiptDir = "",
    [string]$BackupDir = "",
    [switch]$AllowUnknownBaseline
)

$target = if ($TargetOverride) { $TargetOverride } else { "C:\Users\QIYUXUAN\Desktop\Endless-Driver-Tutorial - EP9\Endless-Driver-Tutorial - EP9\Assets\Endness Falling\Scripts\UIManager.cs" }
$ExpectedBaselineHash = "03C9765ED598D19F6721F851F9CF378808ED0056AAB7FAC905CCD9B9D240B488"
$receiptRoot = if ($ReceiptDir) { $ReceiptDir } else { $PSScriptRoot }
$receiptPath = Join-Path $receiptRoot "patch_receipt.json"
$pendingPath = Join-Path $receiptRoot "patch_receipt.pending.json"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

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

if (-not (Test-Path -LiteralPath $target)) {
    Write-Error "[P2-v7] Target not found: $target"
    exit 1
}

$targetNorm = Get-NormalizedPath $target
$currentHash = Get-Sha256 $target
Write-Host "[P2-v7] Target: $target"
Write-Host "[P2-v7] Current Hash : $currentHash"
Write-Host "[P2-v7] Expected Base: $ExpectedBaselineHash"

$text = [System.IO.File]::ReadAllText($target)

# ---- v6: verified, recoverable receipt commit ------------------------------
# Serialise -> temp file -> read back -> verify target binding and hash
# round-trip -> move into place -> read back again. Only then may the pending
# record be removed. Any failure returns $false and leaves pending intact so the
# caller can exit 12 instead of 0.
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
        Write-Warning "[P2-v7] Receipt commit failed: $_"
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
        Write-Warning "[P2-v7] The committed receipt is verified but the pending file could not be removed: $pendingPath"
        return $false
    }
}

function Assert-ReceiptTarget($receipt, [string]$path) {
    if (-not $receipt.target) {
        Write-Error "[P2-v7] Receipt has no target field; refusing."
        return $false
    }
    if ((Get-NormalizedPath $receipt.target) -ne $targetNorm) {
        Write-Error "[P2-v7] Receipt target mismatch. Receipt: $($receipt.target) | Current: $path"
        return $false
    }
    return $true
}

# ---- v7: a receipt may only be committed if it can still be honoured ---------
# The committed receipt promises that a verified backup can restore the file.
# Recovery must therefore verify the backup bytes, not just the post hash.
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

# A receipt directory belongs to exactly one target. Checked BEFORE the marker
# branch so a pristine same-content file elsewhere cannot inherit or overwrite
# another file's receipt.
if (Test-Path -LiteralPath $receiptPath -PathType Container) {
    Write-Error "[P2-v7] Receipt path $receiptPath is a directory, not a file. Refusing."
    exit 11
}
if (Test-Path -LiteralPath $pendingPath -PathType Container) {
    Write-Error "[P2-v7] Pending receipt path $pendingPath is a directory, not a file. Refusing."
    exit 11
}
$existingReceipt = $null
if (Test-Path -LiteralPath $receiptPath) {
    $existingReceipt = Try-ReadJson $receiptPath
    if (-not (Test-ReceiptShape $existingReceipt)) {
        $pendProbe = if (Test-Path -LiteralPath $pendingPath) { Try-ReadJson $pendingPath } else { $null }
        if (-not (Test-ReceiptShape $pendProbe)) {
            Write-Error "[P2-v7] Committed receipt $receiptPath is unreadable and there is no valid pending receipt. Receipt state is unknown. Refusing."
            exit 11
        }
        $stamp = [System.DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
        $quarantine = Join-Path $receiptRoot ("patch_receipt.corrupt_{0}.json" -f $stamp)
        try {
            Move-Item -LiteralPath $receiptPath -Destination $quarantine -Force -ErrorAction Stop
        } catch {
            Write-Error "[P2-v7] Unreadable committed receipt could not be moved aside: $_. Pending receipt kept at $pendingPath."
            exit 12
        }
        Write-Warning "[P2-v7] Committed receipt was unreadable; moved aside to $quarantine. Recovering from the pending receipt."
        $existingReceipt = $null
    }
    if ($existingReceipt -and -not (Assert-ReceiptTarget $existingReceipt $target)) { exit 8 }
}
if (Test-Path -LiteralPath $pendingPath) {
    $existingPending = Try-ReadJson $pendingPath
    if (-not (Test-ReceiptShape $existingPending)) {
        Write-Error "[P2-v7] Pending receipt $pendingPath is unreadable. Refusing; inspect it by hand."
        exit 11
    }
    if (-not (Assert-ReceiptTarget $existingPending $target)) { exit 8 }
}

if ($text.Contains("VectorStyleKey") -and $text.Contains("vectorStyleCache")) {
    if (Test-Path -LiteralPath $receiptPath) {
        $priorReceipt = Try-ReadJson $receiptPath
        if (-not (Test-ReceiptShape $priorReceipt)) {
            Write-Error "[P2-v7] Committed receipt became unreadable during this run. Refusing."
            exit 11
        }
        if (-not (Assert-ReceiptTarget $priorReceipt $target)) { exit 8 }
        if ($priorReceipt.post_patch_hash -and ($currentHash -eq $priorReceipt.post_patch_hash)) {
            Write-Host "[P2-v7] Already applied; receipt hash and target match ($currentHash). Nothing to do."
            exit 0
        }
        Write-Error "[P2-v7] Marker present but hash $currentHash != receipt post hash $($priorReceipt.post_patch_hash). Refusing."
        exit 5
    }
    if (Test-Path -LiteralPath $pendingPath) {
        $pend = Try-ReadJson $pendingPath
        if (-not (Test-ReceiptShape $pend)) {
            Write-Error "[P2-v7] Pending receipt is unreadable. Refusing; inspect $pendingPath."
            exit 11
        }
        if (-not (Assert-ReceiptTarget $pend $target)) { exit 8 }
        if ($pend.intended_post_hash -and ($currentHash -eq $pend.intended_post_hash)) {
            $rollback = Test-RollbackRecord $pend $currentHash "intended_post_hash"
            if (-not $rollback.ok) {
                Write-Error "[P2-v7] The target is patched ($currentHash) and the pending receipt matches, but its rollback record cannot be verified: $($rollback.problems -join '; '). A committed receipt would promise a rollback that cannot be performed, so it was NOT written. The pending receipt is kept unchanged at $pendingPath; restore the verified backup or reinstate the recorded pre-patch file, then re-run."
                exit 13
            }
            $receipt = [PSCustomObject]@{
                target                 = $target
                pre_patch_hash         = $rollback.pre
                post_patch_hash        = $currentHash
                backup_file            = $rollback.backup
                backup_verified        = $true
                backup_sha256          = $rollback.backup_hash
                applied_at_utc         = $pend.written_at_utc
                committed_at_utc       = [System.DateTime]::UtcNow.ToString("o")
                recovered_from_pending = $true
            }
            if (-not (Commit-Receipt $receipt)) {
                Write-Error "[P2-v7] RECOVERY REQUIRED: the target is already patched and verified ($currentHash) but the committed receipt could not be written. The pending receipt is retained at $pendingPath. Re-run this script once the receipt directory is writable."
                exit 12
            }
            $null = Clear-Pending
            Write-Host "[P2-v7] Recovered a pending patch: rollback record verified ($($rollback.backup_hash)) and receipt committed."
            exit 0
        }
        Write-Error "[P2-v7] Marker present, pending receipt hash mismatch. Refusing; inspect $pendingPath."
        exit 5
    }
    Write-Error "[P2-v7] Marker present but no receipt and no pending receipt. State is unverifiable. Refusing."
    exit 5
}

if ($currentHash -ne $ExpectedBaselineHash) {
    if ($TargetOverride -and $AllowUnknownBaseline) {
        Write-Warning "[P2-v7] Baseline check bypassed by -AllowUnknownBaseline. Sandbox use only."
    } else {
        Write-Error "[P2-v7] Target hash $currentHash does not match expected baseline $ExpectedBaselineHash. Aborting."
        exit 1
    }
}

# Backup: verify an existing one, never assume it
$backupDir = if ($BackupDir) { $BackupDir } else { Join-Path $PSScriptRoot "backups" }
if (-not (Test-Path -LiteralPath $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
}
$backupFile = Join-Path $backupDir ("UIManager.cs.pre_{0}.bak" -f $currentHash.Substring(0, 16))
if (Test-Path -LiteralPath $backupFile) {
    $backupHash = Get-Sha256 $backupFile
    if ($backupHash -ne $currentHash) {
        Write-Error "[P2-v7] Existing backup $backupFile hashes to $backupHash, not the current target $currentHash. Aborting before any change."
        exit 6
    }
    Write-Host "[P2-v7] Verified existing backup ($backupHash)."
} else {
    Copy-Item -LiteralPath $target -Destination $backupFile -Force
    $backupHash = Get-Sha256 $backupFile
    if ($backupHash -ne $currentHash) {
        Write-Error "[P2-v7] Backup copy verified as $backupHash, expected $currentHash. Aborting before any change."
        exit 6
    }
    Set-ItemProperty -LiteralPath $backupFile -Name IsReadOnly -Value $true
    Write-Host "[P2-v7] Created and verified backup -> $backupFile"
}

# Anchors
$plain = $text -replace "`r`n", "`n"

$anchorBar = ("        GUIStyle lblStyle = VectorStyle(13, cTextTitle, true, TextAnchor.MiddleLeft);" + "`n" + `
              "        GUI.Label(new Rect(cx - barW/2, cy + barH + 2f, 70, 24), `$`"L: {currentL:F0}%`", lblStyle);" + "`n" + `
              "        lblStyle.alignment = TextAnchor.UpperRight;" + "`n" + `
              "        GUI.Label(new Rect(cx + barW/2 - 70, cy + barH + 2f, 70, 24), `$`"R: {100f-reportBalanceLeft + (50f-currentL):F0}%`", lblStyle);")

$replBar = ("        GUIStyle lblStyle = VectorStyle(13, cTextTitle, true, TextAnchor.MiddleLeft);" + "`n" + `
            "        GUI.Label(new Rect(cx - barW/2, cy + barH + 2f, 70, 24), `$`"L: {currentL:F0}%`", lblStyle);" + "`n" + `
            "        GUIStyle lblStyleRight = VectorStyle(13, cTextTitle, true, TextAnchor.UpperRight);" + "`n" + `
            "        GUI.Label(new Rect(cx + barW/2 - 70, cy + barH + 2f, 70, 24), `$`"R: {100f-reportBalanceLeft + (50f-currentL):F0}%`", lblStyleRight);")

$anchorBox = "        GUIStyle s = VectorStyle(12, cTextSub, true, TextAnchor.MiddleLeft); s.padding = new RectOffset(10,0,6,0); GUI.Label(new Rect(r.x, r.y, r.width, 25), title, s);"
$replBox   = "        GUIStyle s = VectorStyle(12, cTextSub, true, TextAnchor.MiddleLeft, 10); GUI.Label(new Rect(r.x, r.y, r.width, 25), title, s);"

$anchorUser = "        GUIStyle userStyle = VectorStyle(h * 0.017f, Color.white, false, TextAnchor.MiddleLeft);"
$replUser   = "        GUIStyle userStyle = new GUIStyle(VectorStyle(h * 0.017f, Color.white, false, TextAnchor.MiddleLeft));"

$anchorAi = "        GUIStyle aiStyle = VectorStyle(h * 0.017f, cTextTitle, false, TextAnchor.MiddleLeft);"
$replAi   = "        GUIStyle aiStyle = new GUIStyle(VectorStyle(h * 0.017f, cTextTitle, false, TextAnchor.MiddleLeft));"

$anchorStyle = @'
    private GUIStyle VectorStyle(float size, Color col, bool bold, TextAnchor align)
    {
        var style = new GUIStyle(GUI.skin.label)
        {
            fontSize = Mathf.RoundToInt(size),
            fontStyle = bold ? FontStyle.Bold : FontStyle.Normal,
            alignment = align
        };

        style.normal.textColor = col;
        style.hover.textColor = col;
        style.active.textColor = col;
        style.focused.textColor = col;
        style.onNormal.textColor = col;
        style.onHover.textColor = col;
        style.onActive.textColor = col;
        style.onFocused.textColor = col;
        return style;
    }
'@ -replace "`r`n", "`n"

$replStyle = @'
    private struct VectorStyleKey : System.IEquatable<VectorStyleKey>
    {
        public readonly int fontSize;
        public readonly Color color;
        public readonly bool bold;
        public readonly TextAnchor alignment;
        public readonly int horizontalPadding;

        public VectorStyleKey(int fontSize, Color color, bool bold, TextAnchor alignment, int horizontalPadding)
        {
            this.fontSize = fontSize;
            this.color = color;
            this.bold = bold;
            this.alignment = alignment;
            this.horizontalPadding = horizontalPadding;
        }

        public bool Equals(VectorStyleKey other)
        {
            return fontSize == other.fontSize
                && bold == other.bold
                && alignment == other.alignment
                && horizontalPadding == other.horizontalPadding
                && color.Equals(other.color);
        }

        public override bool Equals(object obj)
        {
            return obj is VectorStyleKey other && Equals(other);
        }

        public override int GetHashCode()
        {
            unchecked
            {
                int hash = fontSize;
                hash = (hash * 397) ^ color.GetHashCode();
                hash = (hash * 397) ^ (bold ? 1 : 0);
                hash = (hash * 397) ^ (int)alignment;
                hash = (hash * 397) ^ horizontalPadding;
                return hash;
            }
        }
    }

    private static readonly System.Collections.Generic.Dictionary<VectorStyleKey, GUIStyle> vectorStyleCache =
        new System.Collections.Generic.Dictionary<VectorStyleKey, GUIStyle>();
    private static GUISkin vectorStyleCacheSkin;

    private GUIStyle VectorStyle(float size, Color col, bool bold, TextAnchor align)
    {
        return VectorStyle(size, col, bold, align, 0);
    }

    private GUIStyle VectorStyle(float size, Color col, bool bold, TextAnchor align, int horizontalPadding)
    {
        if (vectorStyleCacheSkin != GUI.skin)
        {
            vectorStyleCache.Clear();
            vectorStyleCacheSkin = GUI.skin;
        }

        int roundedSize = Mathf.RoundToInt(size);
        var key = new VectorStyleKey(roundedSize, col, bold, align, horizontalPadding);
        if (vectorStyleCache.TryGetValue(key, out GUIStyle cached) && cached != null)
        {
            return cached;
        }

        var style = new GUIStyle(GUI.skin.label)
        {
            fontSize = roundedSize,
            fontStyle = bold ? FontStyle.Bold : FontStyle.Normal,
            alignment = align
        };

        style.normal.textColor = col;
        style.hover.textColor = col;
        style.active.textColor = col;
        style.focused.textColor = col;
        style.onNormal.textColor = col;
        style.onHover.textColor = col;
        style.onActive.textColor = col;
        style.focused.textColor = col;
        if (horizontalPadding > 0)
        {
            style.padding = new RectOffset(horizontalPadding, 0, 6, 0);
        }

        vectorStyleCache[key] = style;
        return style;
    }
'@ -replace "`r`n", "`n"

function Count-Hits([string]$haystack, [string]$needle) {
    return ([regex]::Matches($haystack, [regex]::Escape($needle))).Count
}

$c1 = Count-Hits $plain $anchorBar
$c2 = Count-Hits $plain $anchorBox
$c3 = Count-Hits $plain $anchorStyle
$c4 = Count-Hits $plain $anchorUser
$c5 = Count-Hits $plain $anchorAi

Write-Host "[P2-v7] Anchor hits: bar=$c1, box=$c2, style=$c3, user=$c4, ai=$c5"
if ($c1 -ne 1 -or $c2 -ne 1 -or $c3 -ne 1 -or $c4 -ne 1 -or $c5 -ne 1) {
    Write-Error "[P2-v7] One or more anchors failed to match exactly once. Aborting without modifying target."
    exit 1
}

$modified = $plain.Replace($anchorBar, $replBar)
$modified = $modified.Replace($anchorBox, $replBox)
$modified = $modified.Replace($anchorUser, $replUser)
$modified = $modified.Replace($anchorAi, $replAi)
$modified = $modified.Replace($anchorStyle, $replStyle)

# Stage to a temp file and hash the intended result
$guid = [System.Guid]::NewGuid().ToString("N")
$tmpFile = "$target.tmp.$guid"

try {
    [System.IO.File]::WriteAllText($tmpFile, $modified, $utf8NoBom)
    $tmpContent = [System.IO.File]::ReadAllText($tmpFile)
    if (-not ($tmpContent.Contains("VectorStyleKey") -and $tmpContent.Contains("lblStyleRight") -and $tmpContent.Contains("vectorStyleCache"))) {
        throw "staged content is missing the expected symbols"
    }
} catch {
    if (Test-Path -LiteralPath $tmpFile) { Remove-Item -LiteralPath $tmpFile -Force }
    Write-Error "[P2-v7] Staging failed before any change to the target: $_"
    exit 1
}
$intendedHash = Get-Sha256 $tmpFile

# Pending receipt BEFORE the target is touched
try {
    if (-not (Test-Path -LiteralPath $receiptRoot)) {
        New-Item -ItemType Directory -Path $receiptRoot -Force | Out-Null
    }
    $pending = [PSCustomObject]@{
        target             = $target
        pre_patch_hash     = $currentHash
        intended_post_hash = $intendedHash
        backup_file        = $backupFile
        written_at_utc     = [System.DateTime]::UtcNow.ToString("o")
        state              = "pending"
    }
    [System.IO.File]::WriteAllText($pendingPath, ($pending | ConvertTo-Json -Depth 4), $utf8NoBom)
} catch {
    if (Test-Path -LiteralPath $tmpFile) { Remove-Item -LiteralPath $tmpFile -Force }
    Write-Error "[P2-v7] Could not write the pending receipt, so the target was NOT changed: $_"
    exit 7
}

# Replace, verify, commit
try {
    Move-Item -LiteralPath $tmpFile -Destination $target -Force
} catch {
    if (Test-Path -LiteralPath $tmpFile) { Remove-Item -LiteralPath $tmpFile -Force }
    $nowHash = if (Test-Path -LiteralPath $target) { Get-Sha256 $target } else { "" }
    if ($nowHash -eq $currentHash) {
        Remove-Item -LiteralPath $pendingPath -Force -ErrorAction SilentlyContinue
        Write-Error "[P2-v7] Replacement failed and the target is unchanged: $_"
        exit 1
    }
    Write-Error "[P2-v7] Replacement failed with the target in an unknown state ($nowHash). Pending receipt kept at $pendingPath."
    exit 9
}

$postHash = Get-Sha256 $target
if ($postHash -ne $intendedHash) {
    Write-Warning "[P2-v7] Post hash $postHash != intended $intendedHash. Restoring the backup."
    Copy-Item -LiteralPath $backupFile -Destination $target -Force
    $restored = Get-Sha256 $target
    if ($restored -eq $currentHash) {
        Remove-Item -LiteralPath $pendingPath -Force -ErrorAction SilentlyContinue
        Write-Error "[P2-v7] Rolled back to the pre-patch state ($restored) after hash mismatch."
        exit 9
    }
    Write-Error "[P2-v7] Rollback verification failed ($restored). Pending receipt kept at $pendingPath."
    exit 9
}

$receipt = [PSCustomObject]@{
    target           = $target
    pre_patch_hash   = $currentHash
    post_patch_hash  = $postHash
    backup_file      = $backupFile
    backup_verified  = $true
    backup_sha256    = $backupHash
    applied_at_utc   = [System.DateTime]::UtcNow.ToString("o")
    committed_at_utc = [System.DateTime]::UtcNow.ToString("o")
}
if (-not (Commit-Receipt $receipt)) {
    Write-Error "[P2-v7] RECOVERY REQUIRED: the patch is applied and verified ($postHash) but the committed receipt could not be written. The pending receipt is retained at $pendingPath; re-running this script will commit it once the receipt directory is writable. Do NOT treat this as applied."
    exit 12
}
$null = Clear-Pending
Write-Host "[P2-v7] Applied and committed. New hash: $postHash"
Write-Host "[P2-v7] Receipt -> $receiptPath"
exit 0
