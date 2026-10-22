# Patch 2 (v5) — UIManager GUIStyle Value-Key Cache, target-bound and transactional
#
# Status: DEFERRED. No C# compilation and no screenshot diff has been performed.
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
    return (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json)
}

if (-not (Test-Path -LiteralPath $target)) {
    Write-Error "[P2-v5] Target not found: $target"
    exit 1
}

$targetNorm = Get-NormalizedPath $target
$currentHash = Get-Sha256 $target
Write-Host "[P2-v5] Target: $target"
Write-Host "[P2-v5] Current Hash : $currentHash"
Write-Host "[P2-v5] Expected Base: $ExpectedBaselineHash"

$text = [System.IO.File]::ReadAllText($target)

function Assert-ReceiptTarget($receipt, [string]$path) {
    if (-not $receipt.target) {
        Write-Error "[P2-v5] Receipt has no target field; refusing."
        return $false
    }
    if ((Get-NormalizedPath $receipt.target) -ne $targetNorm) {
        Write-Error "[P2-v5] Receipt target mismatch. Receipt: $($receipt.target) | Current: $path"
        return $false
    }
    return $true
}

# A receipt directory belongs to exactly one target. Checked BEFORE the marker
# branch so a pristine same-content file elsewhere cannot inherit or overwrite
# another file's receipt.
if (Test-Path -LiteralPath $receiptPath) {
    $existingReceipt = Read-Json $receiptPath
    if (-not (Assert-ReceiptTarget $existingReceipt $target)) { exit 8 }
}
if (Test-Path -LiteralPath $pendingPath) {
    $existingPending = Read-Json $pendingPath
    if (-not (Assert-ReceiptTarget $existingPending $target)) { exit 8 }
}

if ($text.Contains("VectorStyleKey") -and $text.Contains("vectorStyleCache")) {
    if (Test-Path -LiteralPath $receiptPath) {
        $priorReceipt = Read-Json $receiptPath
        if (-not (Assert-ReceiptTarget $priorReceipt $target)) { exit 8 }
        if ($priorReceipt.post_patch_hash -and ($currentHash -eq $priorReceipt.post_patch_hash)) {
            Write-Host "[P2-v5] Already applied; receipt hash and target match ($currentHash). Nothing to do."
            exit 0
        }
        Write-Error "[P2-v5] Marker present but hash $currentHash != receipt post hash $($priorReceipt.post_patch_hash). Refusing."
        exit 5
    }
    if (Test-Path -LiteralPath $pendingPath) {
        $pend = Read-Json $pendingPath
        if (-not (Assert-ReceiptTarget $pend $target)) { exit 8 }
        if ($pend.intended_post_hash -and ($currentHash -eq $pend.intended_post_hash)) {
            $receipt = [PSCustomObject]@{
                target                 = $target
                pre_patch_hash         = $pend.pre_patch_hash
                post_patch_hash        = $currentHash
                backup_file            = $pend.backup_file
                applied_at_utc         = $pend.written_at_utc
                committed_at_utc       = [System.DateTime]::UtcNow.ToString("o")
                recovered_from_pending = $true
            }
            [System.IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 4), $utf8NoBom)
            Remove-Item -LiteralPath $pendingPath -Force
            Write-Host "[P2-v5] Recovered a pending patch: receipt committed from pending state."
            exit 0
        }
        Write-Error "[P2-v5] Marker present, pending receipt hash mismatch. Refusing; inspect $pendingPath."
        exit 5
    }
    Write-Error "[P2-v5] Marker present but no receipt and no pending receipt. State is unverifiable. Refusing."
    exit 5
}

if ($currentHash -ne $ExpectedBaselineHash) {
    if ($TargetOverride -and $AllowUnknownBaseline) {
        Write-Warning "[P2-v5] Baseline check bypassed by -AllowUnknownBaseline. Sandbox use only."
    } else {
        Write-Error "[P2-v5] Target hash $currentHash does not match expected baseline $ExpectedBaselineHash. Aborting."
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
        Write-Error "[P2-v5] Existing backup $backupFile hashes to $backupHash, not the current target $currentHash. Aborting before any change."
        exit 6
    }
    Write-Host "[P2-v5] Verified existing backup ($backupHash)."
} else {
    Copy-Item -LiteralPath $target -Destination $backupFile -Force
    $backupHash = Get-Sha256 $backupFile
    if ($backupHash -ne $currentHash) {
        Write-Error "[P2-v5] Backup copy verified as $backupHash, expected $currentHash. Aborting before any change."
        exit 6
    }
    Set-ItemProperty -LiteralPath $backupFile -Name IsReadOnly -Value $true
    Write-Host "[P2-v5] Created and verified backup -> $backupFile"
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

Write-Host "[P2-v5] Anchor hits: bar=$c1, box=$c2, style=$c3, user=$c4, ai=$c5"
if ($c1 -ne 1 -or $c2 -ne 1 -or $c3 -ne 1 -or $c4 -ne 1 -or $c5 -ne 1) {
    Write-Error "[P2-v5] One or more anchors failed to match exactly once. Aborting without modifying target."
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
    Write-Error "[P2-v5] Staging failed before any change to the target: $_"
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
    Write-Error "[P2-v5] Could not write the pending receipt, so the target was NOT changed: $_"
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
        Write-Error "[P2-v5] Replacement failed and the target is unchanged: $_"
        exit 1
    }
    Write-Error "[P2-v5] Replacement failed with the target in an unknown state ($nowHash). Pending receipt kept at $pendingPath."
    exit 9
}

$postHash = Get-Sha256 $target
if ($postHash -ne $intendedHash) {
    Write-Warning "[P2-v5] Post hash $postHash != intended $intendedHash. Restoring the backup."
    Copy-Item -LiteralPath $backupFile -Destination $target -Force
    $restored = Get-Sha256 $target
    if ($restored -eq $currentHash) {
        Remove-Item -LiteralPath $pendingPath -Force -ErrorAction SilentlyContinue
        Write-Error "[P2-v5] Rolled back to the pre-patch state ($restored) after hash mismatch."
        exit 9
    }
    Write-Error "[P2-v5] Rollback verification failed ($restored). Pending receipt kept at $pendingPath."
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
    Write-Host "[P2-v5] Applied and committed. New hash: $postHash"
    Write-Host "[P2-v5] Receipt -> $receiptPath"
} catch {
    Write-Warning "[P2-v5] Patch applied and verified ($postHash) but the committed receipt could not be written: $_"
    Write-Warning "[P2-v5] Pending receipt kept at $pendingPath; the next run will commit it."
}
exit 0
