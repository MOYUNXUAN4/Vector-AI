# Patch 2 (v3) — UIManager GUIStyle Value-Key Cache with Hash-Bound Safety
#
# Key improvements in v3 (resolving defects from independent review 2026-10-20):
#   1. Structured Value Key: replaces the 32-bit hash identity with VectorStyleKey
#      implementing IEquatable<VectorStyleKey> and value equality. Collision risk eliminated.
#   2. Pre-flight Hash Binding: verifies target matches exact expected baseline hash
#      before touching any file. Refuses to write if target was modified.
#   3. Hash-Bound Immutable Backup: stores backup named with pre-patch hash in dedicated
#      backup folder, accompanied by cryptographic patch_receipt.json.
#   4. Transactional File Replacement: writes to temporary file first, verifies symbols,
#      then replaces target atomically.
#   5. Preserved presentation & bounded keys: UiAlpha is const 0.85f so color keys are strictly
#      bounded. HUD flags and F1 key injections remain completely excluded.

[CmdletBinding()]
param(
    [string]$TargetOverride = "",
    [switch]$AllowUnknownBaseline
)

$target = if ($TargetOverride) { $TargetOverride } else { "C:\Users\QIYUXUAN\Desktop\Endless-Driver-Tutorial - EP9\Endless-Driver-Tutorial - EP9\Assets\Endness Falling\Scripts\UIManager.cs" }
$ExpectedBaselineHash = "03C9765ED598D19F6721F851F9CF378808ED0056AAB7FAC905CCD9B9D240B488"
$receiptPath = Join-Path $PSScriptRoot "patch_receipt.json"

if (-not (Test-Path -LiteralPath $target)) {
    Write-Error "[P2-v3] Target not found: $target"
    exit 1
}

$currentHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
Write-Host "[P2-v3] Target: $target"
Write-Host "[P2-v3] Current Hash : $currentHash"
Write-Host "[P2-v3] Expected Base: $ExpectedBaselineHash"

$text = [System.IO.File]::ReadAllText($target)

if ($text.Contains("VectorStyleKey") -and $text.Contains("vectorStyleCache")) {
    # "Already applied" must be proven, not inferred from a substring.
    if (Test-Path -LiteralPath $receiptPath) {
        $priorReceipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
        if ($priorReceipt.post_patch_hash -and ($currentHash -eq $priorReceipt.post_patch_hash)) {
            Write-Host "[P2-v3] Already applied and receipt hash matches ($currentHash). Nothing to do."
            exit 0
        }
        Write-Error "[P2-v3] Patch marker present but current hash ($currentHash) != receipt post hash ($($priorReceipt.post_patch_hash)). The file changed after patching. Refusing."
        exit 5
    }
    Write-Error "[P2-v3] Patch marker present but no patch_receipt.json. State is unverifiable. Refusing; restore from version control or a known baseline first."
    exit 5
}

if ($currentHash -ne $ExpectedBaselineHash) {
    if ($TargetOverride -and $AllowUnknownBaseline) {
        Write-Warning "[P2-v3] Baseline check bypassed by -AllowUnknownBaseline. Only valid for sandbox targets."
    } else {
        Write-Error "[P2-v3] Target hash ($currentHash) does not match expected baseline ($ExpectedBaselineHash). Aborting application to avoid damaging concurrent or unverified edits."
        exit 1
    }
}

# Immutable, hash-bound backup
$backupDir = Join-Path $PSScriptRoot "backups"
if (-not (Test-Path -LiteralPath $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
}
$backupFile = Join-Path $backupDir "UIManager.cs.pre_$($currentHash.Substring(0,16)).bak"
if (-not (Test-Path -LiteralPath $backupFile)) {
    Copy-Item -LiteralPath $target -Destination $backupFile -Force
    Set-ItemProperty -LiteralPath $backupFile -Name IsReadOnly -Value $true
    Write-Host "[P2-v3] Created hash-bound immutable backup -> $backupFile"
} else {
    Write-Host "[P2-v3] Found existing immutable backup -> $backupFile"
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

Write-Host "[P2-v3] Anchor hits: bar=$c1, box=$c2, style=$c3, user=$c4, ai=$c5"
if ($c1 -ne 1 -or $c2 -ne 1 -or $c3 -ne 1 -or $c4 -ne 1 -or $c5 -ne 1) {
    Write-Error "[P2-v3] One or more anchors failed to match exactly once. Aborting without modifying target."
    exit 1
}

$modified = $plain.Replace($anchorBar, $replBar)
$modified = $modified.Replace($anchorBox, $replBox)
$modified = $modified.Replace($anchorUser, $replUser)
$modified = $modified.Replace($anchorAi, $replAi)
$modified = $modified.Replace($anchorStyle, $replStyle)

# Transactional replacement via temporary file
$guid = [System.Guid]::NewGuid().ToString("N")
$tmpFile = "$target.tmp.$guid"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

try {
    [System.IO.File]::WriteAllText($tmpFile, $modified, $utf8NoBom)
    $tmpContent = [System.IO.File]::ReadAllText($tmpFile)
    if (-not ($tmpContent.Contains("VectorStyleKey") -and $tmpContent.Contains("lblStyleRight") -and $tmpContent.Contains("vectorStyleCache"))) {
        throw "Temporary file verification failed."
    }
    Move-Item -LiteralPath $tmpFile -Destination $target -Force
} catch {
    if (Test-Path -LiteralPath $tmpFile) { Remove-Item -LiteralPath $tmpFile -Force }
    Write-Error "[P2-v3] Transactional write failed: $_"
    exit 1
}

$postHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
Write-Host "[P2-v3] Successfully applied patch. New Hash: $postHash"

# Save cryptographic receipt
$receipt = [PSCustomObject]@{
    target = $target
    pre_patch_hash = $currentHash
    post_patch_hash = $postHash
    backup_file = $backupFile
    applied_at_utc = [System.DateTime]::UtcNow.ToString("o")
}
$receiptJson = $receipt | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText($receiptPath, $receiptJson, $utf8NoBom)
Write-Host "[P2-v3] Receipt written -> $receiptPath"
exit 0
